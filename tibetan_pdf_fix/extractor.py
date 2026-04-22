"""
tibetan_pdf_fix.extractor
=========================

Patches PDF ToUnicode CMaps for Tibetan fonts using a GSUB-derived reverse
mapping database, then extracts Unicode text.

Supported font class
--------------------
Type0 / CID / Identity-H fonts whose GID space is preserved in the PDF
subset (e.g. fonts created by InDesign or Word with a CID Identity-H
encoding).  The bundled reverse_db.json covers 68 Tibetan font variants
from the Monlam, Himalaya, and Jomolhari families.

Not supported
-------------
TrueType simple-encoding fonts where the PDF char-codes are Ghostscript-
assigned sequential values that do not correspond to the original font GIDs.

Public API
----------
    extract_tibetan_pdf(pdf_path, output_dir=None, write_files=True) -> dict
        Patch + extract Unicode text (writes .raw.txt / .patched.txt / .diff.txt).
    patch_tibetan_pdf(pdf_path, output_path=None, write_file=True) -> dict
        Patch only; returns (and optionally writes) the patched PDF bytes.
    main()   # CLI entry point:
        tibetan-pdf-fix <pdf1> [pdf2] ...                  # text extraction
        tibetan-pdf-fix --patch-pdf <pdf1> [pdf2] ...      # write patched PDFs
"""
from __future__ import annotations

import sys
import re
import json
import io
from pathlib import Path
from typing import Optional

import fitz

# Force UTF-8 on Windows consoles
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Bundled database shipped with the package
_DATA_DIR = Path(__file__).parent / "data"
_DEFAULT_DB = _DATA_DIR / "reverse_db.json"

PREVIEW_LINES = 15
PREVIEW_DIFF  = 8


# ---------------------------------------------------------------------------
# Font name normalisation & DB lookup
# ---------------------------------------------------------------------------

def _strip_prefix(name: str) -> str:
    return name.split("+", 1)[1] if "+" in name else name


def _decode_pdf(s: str) -> str:
    return re.sub(r'#([0-9A-Fa-f]{2})',
                  lambda m: chr(int(m.group(1), 16)), s)


def _normalise_name(name: str) -> str:
    """Normalise a PDF font name for DB lookup.

    Strips subset prefix (e.g. FPFIFO+), decodes PDF hex escapes up to 3
    times (InDesign double-encodes font names), then strips all non-
    alphanumeric characters and lowercases.
    """
    name = _strip_prefix(name)
    for _ in range(3):
        d = _decode_pdf(name)
        if d == name:
            break
        name = d
    return re.sub(r'[^a-z0-9]', '', name.lower())


def _build_db_index(rev_db: dict) -> dict:
    """Return {normalised_key: original_key} for every font in rev_db."""
    return {re.sub(r'[^a-z0-9]', '', k.lower()): k for k in rev_db}


def _find_in_db(rev_db: dict, db_index: dict,
                pdf_basename: str) -> Optional[dict]:
    """Best-scored DB lookup.

    Returns {gid_int: unicode_str} or None.
    Scoring: exact match = 3, pdf_key in db_key = 2, db_key in pdf_key = 1.
    Ties broken by shortest length delta.
    """
    pdf_key = _normalise_name(pdf_basename)
    best_key, best_score, best_delta = None, 0, 10**9
    for db_norm, db_key in db_index.items():
        if   pdf_key == db_norm: score = 3
        elif pdf_key in db_norm: score = 2
        elif db_norm in pdf_key: score = 1
        else: continue
        delta = abs(len(db_norm) - len(pdf_key))
        if score > best_score or (score == best_score and delta < best_delta):
            best_score, best_delta, best_key = score, delta, db_key
    if best_key is None:
        return None
    return {int(k): v for k, v in rev_db[best_key].items()}


# ---------------------------------------------------------------------------
# ToUnicode CMap parsing
# ---------------------------------------------------------------------------

def _parse_tounicode(stream: bytes) -> dict:
    """Parse bfchar + bfrange blocks. Works for 1-byte and 2-byte codes,
    and tolerates both spaced (<01> <0062>) and compact (<01><0062>) formats.
    """
    text = stream.decode("latin-1")
    result: dict = {}

    for blk in re.finditer(r'beginbfchar(.*?)endbfchar', text, re.DOTALL):
        for m in re.finditer(r'<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>', blk.group(1)):
            try:
                code = int(m.group(1), 16)
                uni  = "".join(chr(int(m.group(2)[i:i+4], 16))
                               for i in range(0, len(m.group(2)), 4))
                result[code] = uni
            except (ValueError, OverflowError):
                pass

    for blk in re.finditer(r'beginbfrange(.*?)endbfrange', text, re.DOTALL):
        for m in re.finditer(
            r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>',
            blk.group(1)
        ):
            try:
                lo   = int(m.group(1), 16)
                hi   = int(m.group(2), 16)
                base = int(m.group(3), 16)
                for off in range(hi - lo + 1):
                    result[lo + off] = chr(base + off)
            except (ValueError, OverflowError):
                pass

    return result


# ---------------------------------------------------------------------------
# ToUnicode CMap building (Type0 / CID only)
# ---------------------------------------------------------------------------

def _build_tounicode_type0(mapping: dict) -> bytes:
    """2-byte GID format for Type0/CID/Identity-H fonts."""
    entries = [
        f"<{gid:04X}> <{''.join(f'{ord(c):04X}' for c in uni)}>"
        for gid, uni in sorted(mapping.items())
    ]
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin", "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
        "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange",
        f"{len(entries)} beginbfchar", *entries,
        "endbfchar", "endcmap",
        "CMapName currentdict /CMap defineresource pop", "end", "end",
    ]
    return "\n".join(lines).encode("latin-1")


# ---------------------------------------------------------------------------
# Core merge & patch
# ---------------------------------------------------------------------------

def _merge(existing: dict, db_map: dict) -> tuple:
    """Merge db_map into existing.

    The reverse_db is the authoritative source (built from the original full
    font via GSUB decomposition).  For any GID where we have a DB entry, it
    replaces whatever the PDF's embedded ToUnicode said, because embedded
    ToUnicode entries for ligature/stacked glyphs are frequently wrong or
    missing.
    """
    merged  = dict(existing)
    changed = 0
    for gid, db_uni in db_map.items():
        if db_uni != existing.get(gid, ""):
            merged[gid] = db_uni
            changed += 1
    return merged, changed


def patch_doc(doc: fitz.Document, rev_db: dict) -> dict:
    """Patch all Type0 fonts in *doc* in-place.

    Only Type0/CID fonts are patched because they use Identity-H encoding
    where the PDF char-code equals the original font GID, so the reverse_db
    lookup is valid.  TrueType simple-encoding fonts (e.g. Ghostscript PDFs)
    are skipped because their char-codes are Ghostscript-assigned sequential
    numbers that do not correspond to original GIDs.

    Returns a stats dict with keys: fonts_seen, patched, upgrades,
    no_change, no_match.
    """
    db_index = _build_db_index(rev_db)
    stats    = dict(fonts_seen=0, patched=0, upgrades=0,
                    no_change=0, no_match=0)
    seen:     set = set()
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
            m = re.search(r'/ToUnicode (\d+) 0 R', font_obj)
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

            db_map = _find_in_db(rev_db, db_index, basename)
            if db_map is None:
                stats["no_match"] += 1
                norm = _normalise_name(basename)
                if norm not in reported:
                    reported.add(norm)
                    print(f"  [no DB match] {basename}")
                continue

            norm = _normalise_name(basename)
            if norm not in reported:
                reported.add(norm)
                matched = next(
                    (dk for nk, dk in db_index.items()
                     if norm == nk or norm in nk or nk in norm), "?"
                )
                print(f"  [matched] {basename[:50]} -> {matched}")

            merged, changed = _merge(existing, db_map)
            if changed == 0:
                stats["no_change"] += 1
                continue

            try:
                doc.update_stream(tu_xref, _build_tounicode_type0(merged))
                stats["patched"]  += 1
                stats["upgrades"] += changed
            except Exception as e:
                print(f"  ERROR xref={xref}: {e}", file=sys.stderr)

    return stats


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_all(doc: fitz.Document) -> str:
    """Extract plain text from all pages, preserving whitespace and ligatures."""
    pages = []
    for pno in range(len(doc)):
        text = doc[pno].get_text(
            "text",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES
        )
        pages.append(f"=== PAGE {pno+1} ===\n{text.strip()}")
    return "\n".join(pages)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def patch_tibetan_pdf(
    pdf_path,
    output_path=None,
    write_file: bool = True,
    rev_db: Optional[dict] = None,
) -> dict:
    """Patch a PDF's ToUnicode CMaps and return the patched PDF.

    The same GSUB-derived reverse database used by :func:`extract_tibetan_pdf`
    is applied to every Type0/CID/Identity-H Tibetan font in the PDF, but
    instead of extracting text, the patched PDF document itself is returned
    (and optionally written to disk).  The result is a fully-valid PDF whose
    copy-paste / downstream text extraction will produce correct Tibetan
    Unicode.

    Parameters
    ----------
    pdf_path : str or Path
        Path to the input PDF file.
    output_path : str or Path, optional
        Destination for the patched PDF.  If omitted, defaults to
        ``<pdf_parent>/<stem>.patched.pdf``.
    write_file : bool
        If True (default), write the patched PDF to *output_path*.
    rev_db : dict, optional
        Pre-loaded reverse database.  If None, the bundled reverse_db.json is
        loaded automatically.

    Returns
    -------
    dict with keys:
        pdf_bytes   : bytes - patched PDF content
        stats       : dict  - font patching statistics
                              (fonts_seen, patched, upgrades, no_change, no_match)
        output_path : Path or None - file written to, or None if write_file=False
    """
    pdf_path = Path(pdf_path)
    stem     = pdf_path.stem

    if rev_db is None:
        rev_db = json.loads(_DEFAULT_DB.read_text(encoding="utf-8"))

    out_path: Optional[Path] = None
    if write_file:
        out_path = Path(output_path) if output_path else pdf_path.parent / f"{stem}.patched.pdf"

    doc = fitz.open(str(pdf_path))
    try:
        stats = patch_doc(doc, rev_db)
        # Serialise the patched in-memory document.  garbage=4 + deflate
        # produce a clean, compressed PDF; incremental=False ensures the
        # rewritten ToUnicode streams are preserved even when saving back
        # over the input path.
        pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()

    if write_file and out_path is not None:
        out_path.write_bytes(pdf_bytes)

    return dict(
        pdf_bytes=pdf_bytes,
        stats=stats,
        output_path=out_path,
    )


def extract_tibetan_pdf(
    pdf_path,
    output_dir=None,
    write_files: bool = True,
    rev_db: Optional[dict] = None,
) -> dict:
    """Extract and fix Tibetan Unicode text from a PDF.

    Parameters
    ----------
    pdf_path : str or Path
        Path to the input PDF file.
    output_dir : str or Path, optional
        Directory for output files.  Defaults to the same directory as the PDF.
    write_files : bool
        If True (default), write <stem>.raw.txt, <stem>.patched.txt, and
        <stem>.diff.txt to *output_dir*.
    rev_db : dict, optional
        Pre-loaded reverse database.  If None, the bundled reverse_db.json is
        loaded automatically.

    Returns
    -------
    dict with keys:
        raw        : str   - text extracted before patching
        patched    : str   - text extracted after patching
        stats      : dict  - font patching statistics
        diff_lines : list  - [(line_no, raw_line, patched_line), ...]
        char_delta : int   - len(patched) - len(raw)
    """
    pdf_path  = Path(pdf_path)
    out_dir   = Path(output_dir) if output_dir else pdf_path.parent
    stem      = pdf_path.stem

    if rev_db is None:
        rev_db = json.loads(_DEFAULT_DB.read_text(encoding="utf-8"))

    # Phase 1: raw extraction
    doc_raw  = fitz.open(str(pdf_path))
    raw_text = extract_all(doc_raw)
    doc_raw.close()

    # Phase 2: patch + extract
    doc_pat      = fitz.open(str(pdf_path))
    stats        = patch_doc(doc_pat, rev_db)
    patched_text = extract_all(doc_pat)
    doc_pat.close()

    # Diff
    raw_lines     = raw_text.splitlines()
    pat_lines     = patched_text.splitlines()
    diff_lines    = [
        (i, r, p)
        for i, (r, p) in enumerate(zip(raw_lines, pat_lines))
        if r != p
    ]
    char_delta = len(patched_text) - len(raw_text)

    if write_files:
        (out_dir / f"{stem}.raw.txt").write_text(raw_text,     encoding="utf-8")
        (out_dir / f"{stem}.patched.txt").write_text(patched_text, encoding="utf-8")
        with open(out_dir / f"{stem}.diff.txt", "w", encoding="utf-8") as df:
            df.write(f"PDF:           {pdf_path.name}\n"
                     f"Lines changed: {len(diff_lines)}\n"
                     f"Char delta:    {char_delta:+d}\n\n")
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


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

USAGE = (
    "Usage:\n"
    "  tibetan-pdf-fix <pdf1> [pdf2] ...               extract patched Unicode text\n"
    "  tibetan-pdf-fix --patch-pdf <pdf1> [pdf2] ...   write patched PDFs only"
)


def main() -> None:
    """Command-line interface.

    Modes:
        tibetan-pdf-fix <pdf1> [pdf2] ...
            Full extraction: writes <stem>.raw.txt, <stem>.patched.txt,
            and <stem>.diff.txt next to each PDF.
        tibetan-pdf-fix --patch-pdf <pdf1> [pdf2] ...
            Patch-only: writes <stem>.patched.pdf next to each input PDF;
            no text extraction or diff.
    """
    args = sys.argv[1:]
    if not args:
        sys.exit(USAGE)

    patch_pdf_mode = False
    if args and args[0] in ("--patch-pdf", "-p"):
        patch_pdf_mode = True
        args = args[1:]

    if not args:
        sys.exit(USAGE)

    if not _DEFAULT_DB.exists():
        sys.exit(
            f"reverse_db.json not found at {_DEFAULT_DB}.\n"
            "If you installed from source, run: python scripts/build_reverse_db.py"
        )

    print("Loading reverse DB ...")
    rev_db = json.loads(_DEFAULT_DB.read_text(encoding="utf-8"))
    print(f"  {len(rev_db)} fonts loaded")

    for arg in args:
        pdf_path = Path(arg)
        if not pdf_path.exists():
            print(f"  SKIP (not found): {arg}", file=sys.stderr)
            continue

        stem = pdf_path.stem
        print(f"\n{'='*65}")
        print(f"  PDF: {pdf_path.name}")
        print(f"{'='*65}")

        if patch_pdf_mode:
            print(f"\n[Patch-only mode] Rewriting ToUnicode CMaps ...")
            result = patch_tibetan_pdf(pdf_path, rev_db=rev_db)
            s = result["stats"]
            print(f"  fonts seen:    {s['fonts_seen']}")
            print(f"  patched:       {s['patched']}  ({s['upgrades']} GID upgrades)")
            print(f"  no change:     {s['no_change']}")
            print(f"  no DB match:   {s['no_match']}")
            print(f"  Written: {result['output_path']}  "
                  f"({len(result['pdf_bytes']):,} bytes)")
            continue

        print(f"\n[Phase 1] Raw extraction ...")
        result = extract_tibetan_pdf(pdf_path, rev_db=rev_db)

        pages = len(result["raw"].split("=== PAGE "))
        print(f"  {len(result['raw']):,} chars, {pages-1} pages")
        _show_preview("RAW TEXT", result["raw"])

        print(f"\n[Phase 2] Patched result ...")
        s = result["stats"]
        print(f"  fonts seen:    {s['fonts_seen']}")
        print(f"  patched:       {s['patched']}  ({s['upgrades']} GID upgrades)")
        print(f"  no change:     {s['no_change']}")
        print(f"  no DB match:   {s['no_match']}")
        print(f"  Written: {pdf_path.parent}/{stem}.{{raw,patched,diff}}.txt")
        _show_preview("PATCHED TEXT", result["patched"])

        print(f"\n[Diff]")
        print(f"  Lines changed: {len(result['diff_lines'])} / "
              f"{max(len(result['raw'].splitlines()), len(result['patched'].splitlines()))}")
        print(f"  Char delta:    {result['char_delta']:+d}")
        _show_diff_sample(result["raw"], result["patched"])

    print(f"\nDone.")


if __name__ == "__main__":
    main()
