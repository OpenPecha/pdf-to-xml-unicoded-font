# Changelog

## 0.2.0 — 2026-04-28

### Documentation & data

- Expanded **README**: installation (`pip install git+…`), full Python API reference, CLI quick start, bundled database provenance (build date **2026-04-28**, ZIP sources, update workflow).
- Added **docs/README.md** (index), **docs/glossary-and-json.md** (terms + JSON formats), **docs/font-inventory.md** (all **962** normalised keys).
- Bundled **`reverse_db.json`** regenerated from `bodyig.zip`, `tibetan-fonts-main.zip`, and `tibetan-fonts-private-main.zip` (~16 MB).

### Breaking

- Package renamed from `tibetan-pdf-fix` / `tibetan_pdf_fix` to **`pdf-cmap-fix`** / **`pdf_cmap_fix`** (no shim).
- CLI: `tibetan-pdf-fix` → **`pdf-cmap-fix`**.
- API: `extract_tibetan_pdf` → **`extract_pdf_text`**, `patch_tibetan_pdf` → **`patch_pdf`**.

### Added

- **`build_tounicode_dict(pdf_path)`** — returns per-font `existing`, `merged`, and `overrides` without mutating the PDF.
- **`collect_font_merges`** — lower-level merge inspection.
- CLI **`--dump-cmap OUT.json`** for JSON export of the same structure.
- **`scripts/build_reverse_db.py`**: `--zip` (repeatable), `--fonts-dir` (repeatable), `-o` / `--output`; default output `pdf_cmap_fix/data/reverse_db.json`.
- **`scripts/font_sources.py`** — shared zip / directory iteration (`.ttf`, `.otf`).

### Deprecated

- **`scripts/build_glyph_db.py`** — superseded by `build_reverse_db.py`.

## 0.1.0 — earlier

- Initial `tibetan-pdf-fix` release.
