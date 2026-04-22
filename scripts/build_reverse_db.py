"""
Build the reverse glyph matching database.

For each font in bodyig.zip, derives:
  GID -> correct Unicode sequence

by recursively decomposing GSUB ligature rules.
This is the REVERSE of normal shaping (Unicode -> GID).

Usage
-----
    Place bodyig.zip in the scripts/ directory, then run:

        python scripts/build_reverse_db.py

    Output is written to tibetan_pdf_fix/data/reverse_db.json.

Output format
-------------
{
  "normalisedfontstemname": {   # all lowercase, alphanumeric only
    "1234": "ཀལ",               # GID (str) -> unicode sequence
    ...
  }
}

Note: bodyig.zip (69 MB) is not included in the repository.
The pre-built reverse_db.json is shipped with the package.
"""
from __future__ import annotations
import json, zipfile, io, sys, re
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
except ImportError:
    sys.exit("pip install fonttools")

SCRIPTS_DIR = Path(__file__).parent
ZIP_PATH    = SCRIPTS_DIR / "bodyig.zip"
OUT_PATH    = SCRIPTS_DIR.parent / "tibetan_pdf_fix" / "data" / "reverse_db.json"


def normalise_name(path_or_name: str) -> str:
    stem = Path(path_or_name).stem
    return re.sub(r'[^a-z0-9]', '', stem.lower())


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


def main() -> None:
    if not ZIP_PATH.exists():
        sys.exit(f"Not found: {ZIP_PATH}")

    db: dict[str, dict[str, str]] = {}
    seen_keys: dict[str, str] = {}   # normalised_name -> zip entry (for dedup reporting)

    with zipfile.ZipFile(ZIP_PATH) as zf:
        ttf_entries = [e for e in zf.namelist() if e.lower().endswith(".ttf")]
        print(f"Processing {len(ttf_entries)} TTF files …")

        for entry in ttf_entries:
            key = normalise_name(entry)
            short = Path(entry).name
            if key in seen_keys:
                print(f"  SKIP (dup) {short}")
                continue
            seen_keys[key] = entry

            print(f"  {short} … ", end="", flush=True)
            try:
                data = zf.read(entry)
                font = TTFont(io.BytesIO(data), lazy=False)
                gid_map = build_gid_map(font)
                multi = sum(1 for v in gid_map.values() if len(v) > 1)
                # Store as {str(gid): unicode_str}
                db[key] = {str(gid): uni for gid, uni in gid_map.items()}
                print(f"{len(gid_map)} GIDs mapped, {multi} multi-char stacks")
            except Exception as exc:
                print(f"ERROR: {exc}")

    OUT_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}  ({OUT_PATH.stat().st_size // 1024} KB)")
    print(f"Fonts in DB: {len(db)}")


if __name__ == "__main__":
    main()
