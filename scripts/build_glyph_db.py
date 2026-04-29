"""DEPRECATED — use ``build_reverse_db.py`` instead.

This script produced ``glyph_db.json`` with a different schema and is not used
by the ``pdf_cmap_fix`` runtime.  Kept only for historical reference.

---

Build a glyph database from all TTF fonts inside bodyig.zip.

Uses recursive GSUB ligature decomposition so that stacked Tibetan syllables
(e.g. GID for རྐྱུ) map to the full Unicode sequence U+0F62 U+0F90 U+0FB1 U+0F74,
not just the base character.

Output: .fontcache/glyph_db.json
Structure per font entry:
  {
    "glyph_order": ["glyph_name", ...],      # GID index -> name
    "gid_to_unicode": {"0": "U+0020", ...}   # GID -> unicode sequence string
  }
"""

from __future__ import annotations

import json
import zipfile
import io
import sys
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
except ImportError:
    sys.exit("fontTools not found. Run: pip install fonttools")

FONTCACHE = Path(__file__).parent
ZIP_PATH = FONTCACHE / "bodyig.zip"
OUT_PATH = FONTCACHE / "glyph_db.json"


def build_gsub_lig_rules(font: TTFont) -> dict[str, list[str]]:
    """Return {lig_glyph_name: [component_glyph_names...]} from all GSUB type-4 lookups."""
    rules: dict[str, list[str]] = {}
    if "GSUB" not in font:
        return rules
    for lookup in font["GSUB"].table.LookupList.Lookup:
        if lookup.LookupType != 4:
            continue
        for sub in lookup.SubTable:
            for first_gname, lig_list in sub.ligatures.items():
                for lig in lig_list:
                    rules[lig.LigGlyph] = [first_gname] + list(lig.Component)
    return rules


def build_gid_unicode_map(font: TTFont) -> dict[int, str]:
    """Build GID -> unicode string mapping using cmap + recursive GSUB decomposition."""
    cmap = font.getBestCmap() or {}
    glyph_order = font.getGlyphOrder()
    lig_rules = build_gsub_lig_rules(font)

    # glyph name -> single unicode char (from cmap)
    gname_to_uni: dict[str, str] = {gname: chr(cp) for cp, gname in cmap.items()}

    cache: dict[str, str] = {}

    def decompose(gname: str, depth: int = 0) -> str:
        if gname in cache:
            return cache[gname]
        if depth > 30:
            return ""
        if gname in gname_to_uni:
            result = gname_to_uni[gname]
        elif gname in lig_rules:
            result = "".join(decompose(c, depth + 1) for c in lig_rules[gname])
        else:
            result = ""
        cache[gname] = result
        return result

    mapping: dict[int, str] = {}
    for gid, gname in enumerate(glyph_order):
        uni = decompose(gname)
        if uni:
            mapping[gid] = uni
    return mapping


def extract_font_data(ttf: TTFont) -> dict:
    glyph_order = ttf.getGlyphOrder()
    gid_to_unicode = build_gid_unicode_map(ttf)

    # Serialise as {str(gid): unicode_string}  (JSON keys must be strings)
    return {
        "glyph_order": glyph_order,
        "gid_to_unicode": {str(gid): uni for gid, uni in gid_to_unicode.items()},
    }


def build_db() -> None:
    if not ZIP_PATH.exists():
        sys.exit(f"Not found: {ZIP_PATH}")

    db: dict[str, dict] = {}

    with zipfile.ZipFile(ZIP_PATH) as zf:
        ttf_entries = [e for e in zf.namelist() if e.lower().endswith(".ttf")]
        print(f"Found {len(ttf_entries)} TTF files in {ZIP_PATH.name}")

        for entry in ttf_entries:
            short = Path(entry).name
            print(f"  Processing {short} ...", end=" ", flush=True)
            try:
                data = zf.read(entry)
                ttf = TTFont(io.BytesIO(data), lazy=False)
                font_data = extract_font_data(ttf)
                db[entry] = font_data
                n_glyphs = len(font_data["glyph_order"])
                n_mapped = len(font_data["gid_to_unicode"])
                n_multi  = sum(1 for v in font_data["gid_to_unicode"].values() if len(v) > 1)
                print(f"{n_glyphs} glyphs, {n_mapped} mapped ({n_multi} multi-char stacks)")
            except Exception as exc:
                print(f"ERROR: {exc}")

    OUT_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}  ({OUT_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build_db()
