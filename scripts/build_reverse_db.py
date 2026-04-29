"""
Build the reverse glyph matching database.

For each font (from zip archives and/or recursive directories), derives:
  GID -> correct Unicode sequence

by recursively decomposing GSUB ligature rules.

Usage
-----
    python scripts/build_reverse_db.py --fonts-dir ../tibetan-fonts
    python scripts/build_reverse_db.py --zip scripts/bodyig.zip
    python scripts/build_reverse_db.py --zip a.zip --fonts-dir ../fonts --output out.json

If no --zip / --fonts-dir is given, uses scripts/bodyig.zip when that file exists.

Duplicate normalised font keys: later sources win (overwrite); a warning is printed.

Output is written to pdf_cmap_fix/data/reverse_db.json by default.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
except ImportError:
    sys.exit("pip install fonttools")

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from font_sources import iter_fonts_from_dir, iter_fonts_from_zip
REPO_ROOT = SCRIPTS_DIR.parent
DEFAULT_ZIP = SCRIPTS_DIR / "bodyig.zip"
DEFAULT_OUT = REPO_ROOT / "pdf_cmap_fix" / "data" / "reverse_db.json"


def normalise_name(path_or_name: str) -> str:
    stem = Path(path_or_name).stem
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def gsub_lig_rules(font: TTFont) -> dict[str, list[str]]:
    """All GSUB type-4 rules: {result_gname: [component_gnames]}."""
    rules: dict[str, list[str]] = {}
    if "GSUB" not in font:
        return rules
    for lookup in font["GSUB"].table.LookupList.Lookup:
        if lookup.LookupType != 4:
            continue
        for sub in lookup.SubTable:
            for first, lig_list in sub.ligatures.items():
                for lig in lig_list:
                    rules[lig.LigGlyph] = [first] + list(lig.Component)
    return rules


def build_gid_map(font: TTFont) -> dict[int, str]:
    """GID -> unicode sequence via cmap + recursive GSUB decomposition."""
    cmap = font.getBestCmap() or {}
    glyph_order = font.getGlyphOrder()
    rules = gsub_lig_rules(font)
    gname_to_uni = {gname: chr(cp) for cp, gname in cmap.items()}
    cache: dict[str, str] = {}

    def decompose(gname: str, depth: int = 0) -> str:
        if gname in cache:
            return cache[gname]
        if depth > 30:
            return ""
        if gname in gname_to_uni:
            result = gname_to_uni[gname]
        elif gname in rules:
            result = "".join(decompose(c, depth + 1) for c in rules[gname])
        else:
            result = ""
        cache[gname] = result
        return result

    result: dict[int, str] = {}
    for gid, gname in enumerate(glyph_order):
        uni = decompose(gname)
        if uni:
            result[gid] = uni
    return result


def _process_font(
    label: str,
    font: TTFont,
    db: dict[str, dict[str, str]],
    seen_keys: dict[str, str],
) -> None:
    key = normalise_name(label)
    short = Path(label).name
    if key in seen_keys:
        prev = seen_keys[key]
        print(f"  WARN duplicate key {key!r}: replacing {prev} -> {short}")
    seen_keys[key] = short

    print(f"  {short} … ", end="", flush=True)
    try:
        gid_map = build_gid_map(font)
        multi = sum(1 for v in gid_map.values() if len(v) > 1)
        db[key] = {str(gid): uni for gid, uni in gid_map.items()}
        print(f"{len(gid_map)} GIDs mapped, {multi} multi-char stacks")
    except Exception as exc:
        print(f"ERROR: {exc}")


def build_database(zips: list[Path], font_dirs: list[Path]) -> dict[str, dict[str, str]]:
    db: dict[str, dict[str, str]] = {}
    seen_keys: dict[str, str] = {}

    for zp in zips:
        if not zp.is_file():
            print(f"SKIP (not a file): {zp}", file=sys.stderr)
            continue
        print(f"\n== Zip: {zp} ==")
        for entry, data in iter_fonts_from_zip(zp):
            try:
                font = TTFont(io.BytesIO(data), lazy=False)
                _process_font(entry, font, db, seen_keys)
            except Exception as exc:
                print(f"  ERROR {entry}: {exc}")

    for d in font_dirs:
        if not d.is_dir():
            print(f"SKIP (not a directory): {d}", file=sys.stderr)
            continue
        print(f"\n== Directory: {d} ==")
        for path, _ in iter_fonts_from_dir(d):
            try:
                font = TTFont(str(path), lazy=False)
                _process_font(str(path), font, db, seen_keys)
            except Exception as exc:
                print(f"  ERROR {path}: {exc}")

    return db


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build GID→Unicode reverse database from TTF/OTF fonts.",
    )
    p.add_argument(
        "--zip",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Zip file containing fonts (repeatable).",
    )
    p.add_argument(
        "--fonts-dir",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Directory to scan recursively for .ttf/.otf (repeatable).",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    zips: list[Path] = list(args.zip)
    font_dirs: list[Path] = list(args.fonts_dir)

    if not zips and not font_dirs:
        if DEFAULT_ZIP.is_file():
            zips = [DEFAULT_ZIP]
            print(f"No --zip/--fonts-dir; using default {DEFAULT_ZIP}")
        else:
            sys.exit(
                "Provide at least one --zip or --fonts-dir, or place bodyig.zip in scripts/.\n"
                "Example: python scripts/build_reverse_db.py --fonts-dir ../tibetan-fonts"
            )

    out_path = args.output or DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)

    db = build_database(zips, font_dirs)
    out_path.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}  ({out_path.stat().st_size // 1024} KB)")
    print(f"Fonts in DB: {len(db)}")


if __name__ == "__main__":
    main()
