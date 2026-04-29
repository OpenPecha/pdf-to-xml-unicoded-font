# pdf-cmap-fix

Fix missing or wrong **PDF `/ToUnicode` CMap** entries so text extraction and
copy-paste match what you see on the page.  The primary use case is **Tibetan**
stacked syllables (Monlam, Himalaya, Jomolhari): producers often embed
incomplete or incorrect Unicode mappings for ligature glyphs.  The same
mechanism applies to **any** Type0 / Identity-H font that appears in the
bundled GSUB-derived database (see [Beyond Tibetan](#beyond-tibetan-smoke-test)).

## Migration from `tibetan-pdf-fix` (0.1.x)

| Old (removed) | New (0.2.0) |
|---------------|-------------|
| PyPI / import `tibetan_pdf_fix` | `pdf_cmap_fix` |
| CLI `tibetan-pdf-fix` | `pdf-cmap-fix` |
| `extract_tibetan_pdf(...)` | `extract_pdf_text(...)` |
| `patch_tibetan_pdf(...)` | `patch_pdf(...)` |
| *(new)* | `build_tounicode_dict(...)` — merged CMaps as dicts **without** patching PDF bytes |
| `pip install …` same git URL | package name is now `pdf-cmap-fix` |

There is **no** compatibility shim: update imports and the CLI name.

## Install

```bash
pip install git+https://github.com/gangagyatso4364/pdf-to-xml-unicoded-font.git
# dev: pip install ".[dev]"  (pytest)
```

Requirements: Python 3.8+, [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz),
[fontTools](https://fonttools.readthedocs.io/).

## Quick Start

### Command line

```bash
pdf-cmap-fix document.pdf
# writes: document.raw.txt  document.patched.txt  document.diff.txt

pdf-cmap-fix doc1.pdf doc2.pdf doc3.pdf
```

Write a patched PDF only (same ToUnicode logic; no `.txt` files):

```bash
pdf-cmap-fix --patch-pdf document.pdf
# writes: document.patched.pdf   (input PDF is not overwritten)

pdf-cmap-fix -p doc1.pdf doc2.pdf   # short form
```

Dump merged ToUnicode data as JSON (does **not** modify the PDF):

```bash
pdf-cmap-fix --dump-cmap cmap.json document.pdf
# multiple PDFs: cmap_doc1.json, cmap_doc2.json, … (stem suffix added)
```

Large PDFs that embed **many** separate Type0 font objects (e.g. one subset per
page) can make `--dump-cmap` slow and the JSON large; prefer `build_tounicode_dict`
in Python if you need to filter by `pdf_font_name` or `changed`.

### Python API

```python
from pdf_cmap_fix import extract_pdf_text, patch_pdf, build_tounicode_dict

result = extract_pdf_text("document.pdf")

print(result["patched"])       # corrected Unicode text
print(result["stats"])         # fonts_seen, patched, upgrades, …
print(result["char_delta"])

cmap = build_tounicode_dict("document.pdf")
# cmap["fonts"] — list of dicts: existing / merged / overrides per Type0 font
# cmap["by_font_xref"] — same entries keyed by string xref
# cmap["stats"] — aggregate counters
```

Patch the PDF and return (or write) the corrected document:

```python
result = patch_pdf("document.pdf")
# result["pdf_bytes"], result["stats"], result["output_path"]
```

## Supported Fonts

The bundled `reverse_db.json` (~2.4 MB) ships with **68 Tibetan font variants**
(Monlam Uni OuChan, Himalaya, Jomolhari, …).  Rebuild and extend it from a
directory tree (e.g. a clone of [openpecha/tibetan-fonts](https://github.com/openpecha/tibetan-fonts)) — see [Rebuilding the Font Database](#rebuilding-the-font-database).

Only **Type0 / CID / Identity-H** fonts are handled (PDF char code = original GID).
**TrueType simple-encoding** (typical Ghostscript PDFs) is not supported.

## How It Works

1. Match each embedded Type0 font name to an entry in `reverse_db.json`.
2. Parse the PDF’s existing ToUnicode CMap.
3. Merge: database replaces entries wherever it has a GID mapping (GSUB is authoritative).
4. Optionally write streams back (`patch_pdf` / `extract_pdf_text`) or only return dicts (`build_tounicode_dict`).

See [`docs/approach.md`](docs/approach.md).

## Example Results

### TI1751-01-001.pdf — InDesign PDF, 528 pages

| Before (wrong) | After (correct) |
|----------------|-----------------|
| `ཀོང་ཡངས་རོལ་བའི་རྣལ་འབོར་པ་` | `ཀློང་ཡངས་རོལ་བའི་རྣལ་འབྱོར་པ་` |
| `རོ་རེའི་སེ་ཕེང་` | `རྡོ་རྗེའི་སྐྱེ་ཕྲེང་` |

Full output: [`docs/examples/TI1751-01-001/`](docs/examples/TI1751-01-001/)

### TI1055-01-001.pdf — Word PDF, 528 pages

| Before (wrong) | After (correct) |
|----------------|-----------------|
| `བྗོད་གངས་ཅན་` | `བོད་གངས་ཅན་` |
| `ཐྗོས་བསམ་སྗོམ་གསུམ་` | `ཐོས་བསམ་སྒོམ་གསུམ་` |

Full output: [`docs/examples/TI1055-01-001/`](docs/examples/TI1055-01-001/)

## Rebuilding the Font Database

The pre-built `reverse_db.json` lives in `pdf_cmap_fix/data/`.  To rebuild from
fonts on disk and/or in zip archives:

```bash
pip install fonttools
# Recursive directory (e.g. OpenPecha font checkout)
python scripts/build_reverse_db.py --fonts-dir ../tibetan-fonts

# Zip(s) + directory; later sources win on duplicate normalised font names
python scripts/build_reverse_db.py --zip scripts/bodyig.zip --fonts-dir ../tibetan-fonts-private

# Custom output path
python scripts/build_reverse_db.py --fonts-dir ./fonts -o ./out/reverse_db.json
```

If you omit `--zip` and `--fonts-dir`, the script uses `scripts/bodyig.zip` when
that file exists.

**Provenance:** record the git commit or date of the font repos you used when
shipping a regenerated database.

**Bundled `reverse_db.json` (v0.2.x):** the copy shipped in `pdf_cmap_fix/data/`
contains **68** normalised font keys (Monlam Uni OuChan, Himalaya, Jomolhari,
and related variants), built from the **bodyig**-style TTF corpus with
`build_gid_map` (cmap + GSUB type-4). It was **not** regenerated in CI from
[openpecha/tibetan-fonts](https://github.com/openpecha/tibetan-fonts) for this
release; to merge OpenPecha fonts, clone that repo and run
`build_reverse_db.py --fonts-dir …` (optionally with `--zip scripts/bodyig.zip`
first), then regression-test on `docs/examples/TI1751-01-001` and
`TI1055-01-001` before replacing the bundled file.

## Beyond Tibetan (smoke test)

The pipeline is **not** Tibetan-specific: any Identity-H Type0 font whose
glyph IDs match the **full** font used to build `reverse_db.json` can be fixed
the same way.

**Suggested smoke test:** (1) build a tiny `reverse_db.json` containing one
Latin font with `fi`/`fl` ligatures (from Google Fonts or similar, OFL).  (2)
Produce or obtain a small PDF that embeds that font as Type0/Identity-H with a
wrong ToUnicode for the ligature.  (3) Run `build_tounicode_dict` and confirm
non-empty `overrides`.  Document the outcome here or in an internal doc — a
negative result (no matching PDF found) still clarifies scope.

## Project Structure

```
pdf_cmap_fix/            Python package
├── extractor.py         Patch / extract / build_tounicode_dict / CLI
└── data/
    └── reverse_db.json  GID → Unicode (bundled)
scripts/
├── font_sources.py      Zip + directory font enumeration
├── build_reverse_db.py  Rebuild reverse_db.json
└── build_glyph_db.py    DEPRECATED — use build_reverse_db.py
docs/
├── approach.md
├── blog.md              Link / notes for the public blog draft (Google Doc)
└── examples/            Example PDFs and outputs
tests/                   pytest (optional [dev] install)
```

## License

MIT
