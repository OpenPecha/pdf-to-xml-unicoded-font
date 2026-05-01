"""
pdf_cmap_fix.extractor
======================

Patches PDF ToUnicode CMaps using a GSUB-derived reverse mapping database,
extracts Unicode text, or returns merged CMap data without mutating the PDF.

Supported font class
--------------------
Type0 / CID / Identity-H fonts whose GID space is preserved in the PDF
subset.  The bundled reverse_db.json is built from Tibetan fonts (Monlam,
Himalaya, Jomolhari) and can be extended via ``scripts/build_reverse_db.py``.

Public API
----------
    extract_pdf_text(pdf_path, ...) -> dict
    patch_pdf(pdf_path, ...) -> dict
    build_tounicode_dict(pdf_path, ...) -> dict
    extract_all(doc) / patch_doc(doc, ...)  # lower-level
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import fitz

_DATA_DIR = Path(__file__).parent / "data"
_DEFAULT_DB = _DATA_DIR / "reverse_db.json"

PREVIEW_LINES = 15
PREVIEW_DIFF = 8


def _strip_prefix(name: str) -> str:
    return name.split("+", 1)[1] if "+" in name else name


def _decode_pdf(s: str) -> str:
    return re.sub(
        r"#([0-9A-Fa-f]{2})",
        lambda m: chr(int(m.group(1), 16)),
        s,
    )


def _normalise_name(name: str) -> str:
    name = _strip_prefix(name)
    for _ in range(3):
        d = _decode_pdf(name)
        if d == name:
            break
        name = d
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _build_db_index(rev_db: dict) -> dict:
    return {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in rev_db}


def _find_in_db_with_key(
    rev_db: dict, db_index: dict, pdf_basename: str
) -> tuple[Optional[dict], Optional[str]]:
    """Return ({gid: unicode}, rev_db_font_key) or (None, None)."""
    pdf_key = _normalise_name(pdf_basename)
    best_key: Optional[str] = None
    best_score, best_delta = 0, 10**9
    for db_norm, db_key in db_index.items():
        if pdf_key == db_norm:
            score = 3
        elif pdf_key in db_norm:
            score = 2
        elif db_norm in pdf_key:
            score = 1
        else:
            continue
        delta = abs(len(db_norm) - len(pdf_key))
        if score > best_score or (score == best_score and delta < best_delta):
            best_score, best_delta, best_key = score, delta, db_key
    if best_key is None:
        return None, None
    return {int(k): v for k, v in rev_db[best_key].items()}, best_key


def _parse_tounicode(stream: bytes) -> dict:
    text = stream.decode("latin-1")
    result: dict = {}

    for blk in re.finditer(r"beginbfchar(.*?)endbfchar", text, re.DOTALL):
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk.group(1)):
            try:
                code = int(m.group(1), 16)
                uni = "".join(
                    chr(int(m.group(2)[i : i + 4], 16))
                    for i in range(0, len(m.group(2)), 4)
                )
                result[code] = uni
            except (ValueError, OverflowError):
                pass

    for blk in re.finditer(r"beginbfrange(.*?)endbfrange", text, re.DOTALL):
        for m in re.finditer(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
            blk.group(1),
        ):
            try:
                lo = int(m.group(1), 16)
                hi = int(m.group(2), 16)
                base = int(m.group(3), 16)
                for off in range(hi - lo + 1):
                    result[lo + off] = chr(base + off)
            except (ValueError, OverflowError):
                pass

    return result


def _build_tounicode_type0(mapping: dict) -> bytes:
    entries = [
        f"<{gid:04X}> <{''.join(f'{ord(c):04X}' for c in uni)}>"
        for gid, uni in sorted(mapping.items())
    ]
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
        f"{len(entries)} beginbfchar",
        *entries,
        "endbfchar",
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ]
    return "\n".join(lines).encode("latin-1")


def _merge(existing: dict, db_map: dict) -> tuple:
    merged = dict(existing)
    changed = 0
    for gid, db_uni in db_map.items():
        if db_uni != existing.get(gid, ""):
            merged[gid] = db_uni
            changed += 1
    return merged, changed


def _overrides(existing: dict, merged: dict) -> dict:
    out = {}
    for k, v in merged.items():
        if existing.get(k, "") != v:
            out[k] = v
    return out


def collect_font_merges(
    doc: fitz.Document,
    rev_db: dict,
    *,
    verbose: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Scan Type0 fonts with ToUnicode; compute merged maps without writing PDF.

    Returns (records, stats). Each record has font_xref, to_unicode_xref,
    pdf_font_name, db_key_matched, existing, merged, overrides, changed.
    """
    db_index = _build_db_index(rev_db)
    stats = dict(fonts_seen=0, patched=0, upgrades=0, no_change=0, no_match=0)
    records: list[dict[str, Any]] = []
    seen: set = set()
    reported: set = set()

    for pno in range(len(doc)):
        for f in doc[pno].get_fonts(full=True):
            xref, _, ftype, basename, _, _, _ = f
            if xref in seen:
                continue
            seen.add(xref)

            if ftype != "Type0":
                continue
            stats["fonts_seen"] += 1

            font_obj = doc.xref_object(xref)
            m = re.search(r"/ToUnicode (\d+) 0 R", font_obj)
            if not m:
                stats["no_change"] += 1
                continue
            tu_xref = int(m.group(1))
            try:
                tu_stream = doc.xref_stream(tu_xref)
            except Exception:
                stats["no_change"] += 1
                continue

            existing = _parse_tounicode(tu_stream)
            db_map, db_key = _find_in_db_with_key(rev_db, db_index, basename)

            if db_map is None:
                stats["no_match"] += 1
                norm = _normalise_name(basename)
                if verbose and norm not in reported:
                    reported.add(norm)
                    print(f"  [no DB match] {basename}")
                merged = dict(existing)
                changed = 0
                overrides: dict = {}
            else:
                norm = _normalise_name(basename)
                if verbose and norm not in reported:
                    reported.add(norm)
                    matched = next(
                        (
                            dk
                            for nk, dk in db_index.items()
                            if norm == nk or norm in nk or nk in norm
                        ),
                        "?",
                    )
                    print(f"  [matched] {basename[:50]} -> {matched}")
                merged, changed = _merge(existing, db_map)
                overrides = _overrides(existing, merged)

            records.append(
                {
                    "font_xref": xref,
                    "to_unicode_xref": tu_xref,
                    "pdf_font_name": basename,
                    "db_key_matched": db_key,
                    "existing": existing,
                    "merged": merged,
                    "overrides": overrides,
                    "changed": changed,
                }
            )

            if db_map is None:
                pass
            elif changed == 0:
                stats["no_change"] += 1
            else:
                stats["patched"] += 1
                stats["upgrades"] += changed

    return records, stats


def apply_font_merges_to_doc(doc: fitz.Document, records: list[dict[str, Any]]) -> None:
    """Write merged ToUnicode streams for records with changed > 0."""
    for r in records:
        if r["changed"] <= 0:
            continue
        doc.update_stream(
            r["to_unicode_xref"],
            _build_tounicode_type0(r["merged"]),
        )


def patch_doc(
    doc: fitz.Document,
    rev_db: dict,
    *,
    verbose: bool = False,
) -> dict[str, int]:
    records, stats = collect_font_merges(doc, rev_db, verbose=verbose)
    apply_font_merges_to_doc(doc, records)
    return stats


def extract_all(doc: fitz.Document) -> str:
    pages = []
    for pno in range(len(doc)):
        text = doc[pno].get_text(
            "text",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES,
        )
        pages.append(f"=== PAGE {pno+1} ===\n{text.strip()}")
    return "\n".join(pages)


def build_tounicode_dict(
    pdf_path,
    rev_db: Optional[dict] = None,
) -> dict[str, Any]:
    """Return per-font ToUnicode maps (existing, merged, overrides) without patching.

    Parameters
    ----------
    pdf_path : str or Path
    rev_db : optional pre-loaded reverse database

    Returns
    -------
    dict with keys:
        fonts : list of font records (see plan schema)
        by_font_xref : dict[str, dict] — keys are stringified xrefs
        stats : aggregate counters (fonts_seen, patched, upgrades, no_change, no_match)
    """
    pdf_path = Path(pdf_path)
    if rev_db is None:
        rev_db = json.loads(_DEFAULT_DB.read_text(encoding="utf-8"))

    doc = fitz.open(str(pdf_path))
    try:
        records, stats = collect_font_merges(doc, rev_db, verbose=False)
    finally:
        doc.close()

    by_xref = {str(r["font_xref"]): r for r in records}
    return {"fonts": records, "by_font_xref": by_xref, "stats": stats}


def patch_pdf(
    pdf_path,
    output_path=None,
    write_file: bool = True,
    rev_db: Optional[dict] = None,
    *,
    verbose: bool = False,
) -> dict:
    pdf_path = Path(pdf_path)
    stem = pdf_path.stem

    if rev_db is None:
        rev_db = json.loads(_DEFAULT_DB.read_text(encoding="utf-8"))

    out_path: Optional[Path] = None
    if write_file:
        out_path = Path(output_path) if output_path else pdf_path.parent / f"{stem}.patched.pdf"

    doc = fitz.open(str(pdf_path))
    try:
        stats = patch_doc(doc, rev_db, verbose=verbose)
        pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()

    if write_file and out_path is not None:
        out_path.write_bytes(pdf_bytes)

    return dict(pdf_bytes=pdf_bytes, stats=stats, output_path=out_path)


def extract_pdf_text(
    pdf_path,
    output_dir=None,
    write_files: bool = True,
    rev_db: Optional[dict] = None,
    *,
    verbose: bool = False,
) -> dict:
    pdf_path = Path(pdf_path)
    out_dir = Path(output_dir) if output_dir else pdf_path.parent
    stem = pdf_path.stem

    if rev_db is None:
        rev_db = json.loads(_DEFAULT_DB.read_text(encoding="utf-8"))

    doc_raw = fitz.open(str(pdf_path))
    raw_text = extract_all(doc_raw)
    doc_raw.close()

    doc_pat = fitz.open(str(pdf_path))
    try:
        stats = patch_doc(doc_pat, rev_db, verbose=verbose)
        patched_text = extract_all(doc_pat)
    finally:
        doc_pat.close()

    raw_lines = raw_text.splitlines()
    pat_lines = patched_text.splitlines()
    diff_lines = [
        (i, r, p)
        for i, (r, p) in enumerate(zip(raw_lines, pat_lines))
        if r != p
    ]
    char_delta = len(patched_text) - len(raw_text)

    if write_files:
        (out_dir / f"{stem}.raw.txt").write_text(raw_text, encoding="utf-8")
        (out_dir / f"{stem}.patched.txt").write_text(patched_text, encoding="utf-8")
        with open(out_dir / f"{stem}.diff.txt", "w", encoding="utf-8") as df:
            df.write(
                f"PDF:           {pdf_path.name}\n"
                f"Lines changed: {len(diff_lines)}\n"
                f"Char delta:    {char_delta:+d}\n\n"
            )
            for i, r, p in diff_lines:
                df.write(f"--- line {i+1} RAW:\n{r}\n")
                df.write(f"+++ line {i+1} PATCHED:\n{p}\n\n")

    return dict(
        raw=raw_text,
        patched=patched_text,
        stats=stats,
        diff_lines=diff_lines,
        char_delta=char_delta,
    )


def _serialise_cmap_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert int-keyed inner dicts to str for JSON."""

    def cmap_dict(d: dict) -> dict[str, str]:
        return {str(k): v for k, v in sorted(d.items())}

    out_fonts = []
    for r in payload["fonts"]:
        out_fonts.append(
            {
                "font_xref": r["font_xref"],
                "to_unicode_xref": r["to_unicode_xref"],
                "pdf_font_name": r["pdf_font_name"],
                "db_key_matched": r["db_key_matched"],
                "existing": cmap_dict(r["existing"]),
                "merged": cmap_dict(r["merged"]),
                "overrides": cmap_dict(r["overrides"]),
                "changed": r["changed"],
            }
        )
    return {"fonts": out_fonts, "stats": payload["stats"]}


def _sanitise_json_utf8(obj: Any) -> Any:
    """Replace lone UTF-16 surrogates so ``json`` output can be written as UTF-8."""

    def _fix_str(s: str) -> str:
        return "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in s)

    if isinstance(obj, str):
        return _fix_str(obj)
    if isinstance(obj, dict):
        return {_fix_str(k) if isinstance(k, str) else k: _sanitise_json_utf8(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise_json_utf8(x) for x in obj]
    return obj


def _printable(s: str) -> str:
    return "".join(c if c >= " " else f"[{ord(c):02X}]" for c in s)


def _show_preview(label: str, text: str, n: int = PREVIEW_LINES) -> None:
    print(f"\n  --- {label} (first {n} non-empty lines) ---")
    count = 0
    for line in text.splitlines():
        if line.strip() and not line.startswith("=== PAGE"):
            print(f"    {_printable(line)}")
            count += 1
            if count >= n:
                break


def _show_diff_sample(raw: str, patched: str, n: int = PREVIEW_DIFF) -> None:
    raw_lines = raw.splitlines()
    pat_lines = patched.splitlines()
    diffs = [(i, r, p) for i, (r, p) in enumerate(zip(raw_lines, pat_lines)) if r != p]
    print(f"\n  --- Sample of changed lines ({min(n, len(diffs))} of {len(diffs)}) ---")
    for i, r, p in diffs[:n]:
        print(f"    line {i+1}:")
        print(f"      RAW:     {_printable(r)}")
        print(f"      PATCHED: {_printable(p)}")


USAGE = (
    "Usage:\n"
    "  pdf-cmap-fix <pdf1> [pdf2] ...                 extract patched Unicode text\n"
    "  pdf-cmap-fix --patch-pdf <pdf1> [pdf2] ...     write patched PDFs only\n"
    "  pdf-cmap-fix --dump-cmap OUT.json <pdf> ...    write ToUnicode merge dict (JSON)\n"
)


def main() -> None:
    # Windows consoles: UTF-8 for CLI only (not at import time — breaks pytest capture)
    if hasattr(sys.stdout, "buffer") and not isinstance(
        sys.stdout, io.TextIOWrapper
    ):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    args = sys.argv[1:]
    if not args:
        sys.exit(USAGE)

    dump_cmap: Optional[str] = None
    patch_pdf_mode = False
    rest = list(args)
    if rest and rest[0] in ("--patch-pdf", "-p"):
        patch_pdf_mode = True
        rest = rest[1:]
    elif rest and rest[0] == "--dump-cmap":
        if len(rest) < 2:
            sys.exit("pdf-cmap-fix --dump-cmap requires OUTPUT.json and at least one PDF")
        dump_cmap = rest[1]
        rest = rest[2:]

    pdf_args = rest
    if not pdf_args:
        sys.exit(USAGE)

    if not _DEFAULT_DB.exists():
        sys.exit(
            f"reverse_db.json not found at {_DEFAULT_DB}.\n"
            "If you installed from source, run: python scripts/build_reverse_db.py"
        )

    print("Loading reverse DB ...")
    rev_db = json.loads(_DEFAULT_DB.read_text(encoding="utf-8"))
    print(f"  {len(rev_db)} fonts loaded")

    for arg in pdf_args:
        pdf_path = Path(arg)
        if not pdf_path.exists():
            print(f"  SKIP (not found): {arg}", file=sys.stderr)
            continue

        stem = pdf_path.stem
        print(f"\n{'='*65}")
        print(f"  PDF: {pdf_path.name}")
        print(f"{'='*65}")

        if dump_cmap is not None:
            out_json = Path(dump_cmap)
            if len(pdf_args) > 1:
                out_json = out_json.parent / f"{out_json.stem}_{pdf_path.stem}{out_json.suffix}"
            payload = build_tounicode_dict(pdf_path, rev_db=rev_db)
            serial = _sanitise_json_utf8(_serialise_cmap_result(payload))
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(serial, ensure_ascii=False, indent=2), encoding="utf-8")
            s = payload["stats"]
            print(f"  fonts seen:    {s['fonts_seen']}")
            print(f"  would patch:   {s['patched']}  ({s['upgrades']} GID upgrades)")
            print(f"  no change:     {s['no_change']}")
            print(f"  no DB match:   {s['no_match']}")
            print(f"  Written: {out_json}")
            continue

        if patch_pdf_mode:
            print("\n[Patch-only mode] Rewriting ToUnicode CMaps ...")
            result = patch_pdf(pdf_path, rev_db=rev_db, verbose=True)
            stats = result["stats"]
            pdf_bytes = result["pdf_bytes"]
            out_path = result["output_path"]
            print(f"  fonts seen:    {stats['fonts_seen']}")
            print(f"  patched:       {stats['patched']}  ({stats['upgrades']} GID upgrades)")
            print(f"  no change:     {stats['no_change']}")
            print(f"  no DB match:   {stats['no_match']}")
            print(f"  Written: {out_path}  ({len(pdf_bytes):,} bytes)")
            continue

        print("\n[Phase 1] Raw extraction ...")
        result = extract_pdf_text(pdf_path, rev_db=rev_db, verbose=True)
        raw_text = result["raw"]
        patched_text = result["patched"]
        stats = result["stats"]
        diff_lines = result["diff_lines"]
        char_delta = result["char_delta"]
        pages = len(raw_text.split("=== PAGE "))
        print(f"  {len(raw_text):,} chars, {pages-1} pages")
        _show_preview("RAW TEXT", raw_text)

        print("\n[Phase 2] Patched result ...")
        print(f"  fonts seen:    {stats['fonts_seen']}")
        print(f"  patched:       {stats['patched']}  ({stats['upgrades']} GID upgrades)")
        print(f"  no change:     {stats['no_change']}")
        print(f"  no DB match:   {stats['no_match']}")
        print(f"  Written: {pdf_path.parent}/{stem}.{{raw,patched,diff}}.txt")
        _show_preview("PATCHED TEXT", patched_text)
        print("\n[Diff]")
        print(
            f"  Lines changed: {len(diff_lines)} / "
            f"{max(len(raw_text.splitlines()), len(patched_text.splitlines()))}"
        )
        print(f"  Char delta:    {char_delta:+d}")
        _show_diff_sample(raw_text, patched_text)

    print("\nDone.")


if __name__ == "__main__":
    main()
