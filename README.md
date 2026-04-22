# tibetan-pdf-fix

Fix missing or wrong Tibetan stacked syllables in PDF text extraction.

Tibetan PDFs often embed fonts with incomplete or incorrect **ToUnicode CMap**
entries for stacked syllable glyphs.  Standard extraction tools then silently
drop subjoined letters — `རྡོ་རྗེ་` becomes `རོ་རེ་` — or insert spurious
characters.  This tool patches the in-memory CMap using a pre-built database
derived from the original fonts' GSUB ligature tables.  You can either
re-extract corrected Unicode text, or write a **new PDF** whose ToUnicode maps
are fixed so copy-paste and other tools see the right Tibetan.

## Install

```bash
pip install git+https://github.com/gangagyatso4364/pdf-to-xml-unicoded-font.git
```

Requirements: Python 3.8+, [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz),
[fontTools](https://fonttools.readthedocs.io/).

## Quick Start

### Command line

```bash
tibetan-pdf-fix document.pdf
# writes: document.raw.txt  document.patched.txt  document.diff.txt

tibetan-pdf-fix doc1.pdf doc2.pdf doc3.pdf
```

Write a patched PDF only (same ToUnicode logic as above; no `.txt` files):

```bash
tibetan-pdf-fix --patch-pdf document.pdf
# writes: document.patched.pdf   (input PDF is not overwritten)

tibetan-pdf-fix -p doc1.pdf doc2.pdf   # short form
```

### Python API

```python
from tibetan_pdf_fix import extract_tibetan_pdf

result = extract_tibetan_pdf("document.pdf")

print(result["patched"])       # corrected Unicode text
print(result["stats"])         # {"fonts_seen": 3, "patched": 2, "upgrades": 1583, ...}
print(result["char_delta"])    # net change in character count

# Output files are written by default to the same directory as the PDF:
#   document.raw.txt     — original extraction (before patching)
#   document.patched.txt — corrected extraction
#   document.diff.txt    — every changed line
```

Output to a different directory:

```python
result = extract_tibetan_pdf("document.pdf", output_dir="/tmp/output")
```

In-memory only (no files written):

```python
result = extract_tibetan_pdf("document.pdf", write_files=False)
```

Patch the PDF and return (or write) the corrected document:

```python
from tibetan_pdf_fix import patch_tibetan_pdf

result = patch_tibetan_pdf("document.pdf")
# default: writes document.patched.pdf next to the input
# result["pdf_bytes"] — patched PDF as bytes
# result["stats"]     — same shape as extract_tibetan_pdf
# result["output_path"] — Path written, or None if write_file=False

result = patch_tibetan_pdf("document.pdf", output_path="/tmp/out.pdf")
result = patch_tibetan_pdf("document.pdf", write_file=False)  # bytes only, no file
```

## Supported Fonts

The bundled database (`reverse_db.json`, 2.4 MB) covers **68 Tibetan font
variants** from three families:

| Family | Variants |
|--------|----------|
| **Monlam Uni OuChan** | OuChan1 through OuChan5 |
| **Himalaya** | Himalaya-A through Himalaya-N, Himalaya-SN, himalaya0 |
| **Jomolhari** | Jomolhari |
| *(others)* | Additional variants in bodyig.zip |

The database is built from **GSUB type-4 ligature rules** in each font, so
stacked syllables of arbitrary depth are correctly decomposed — not just the
simple vowel+consonant combinations.

### Font encoding requirements

Only **Type0 / CID / Identity-H** fonts are patched.  These fonts preserve
the original GID in the PDF, so the database lookup is exact.

**TrueType simple-encoding** fonts (typical of Ghostscript-generated PDFs)
are currently not patched.  In Ghostscript PDFs the char-codes are
sequentially assigned by Ghostscript and do not correspond to original font
GIDs, making reliable lookup impossible without reading the embedded subset's
glyph order.

## How It Works

1. For each Tibetan font in the PDF, look up its GID→Unicode mapping in the
   pre-built `reverse_db.json`.
2. Parse the PDF's existing ToUnicode CMap for that font.
3. Replace each entry where the database has a mapping (the database is
   authoritative — it comes from the font's own GSUB table, not from the PDF
   creator's heuristics).
4. Write the corrected CMap back into the in-memory PDF, then either
   re-extract text (`extract_tibetan_pdf`) or serialise the document to a new
   PDF file (`patch_tibetan_pdf` / `tibetan-pdf-fix --patch-pdf`).

See [`docs/approach.md`](docs/approach.md) for the full technical explanation.

## Example Results

### TI1751-01-001.pdf — InDesign PDF, 528 pages

```
Lines changed: 2,540 / 5,361     Char delta: +9,969
```

| Before (wrong) | After (correct) |
|----------------|-----------------|
| `ཀོང་ཡངས་རོལ་བའི་རྣལ་འབོར་པ་` | `ཀློང་ཡངས་རོལ་བའི་རྣལ་འབྱོར་པ་` |
| `ཀི་ཟབ་གཏེར་` | `ཀྱི་ཟབ་གཏེར་` |
| `རོ་རེའི་སེ་ཕེང་` | `རྡོ་རྗེའི་སྐྱེ་ཕྲེང་` |
| `སིང་གསོལ་འདེབས་` | `སྙིང་གསོལ་འདེབས་` |
| `བིན་རླབས་` | `བྱིན་རླབས་` |

Full output: [`docs/examples/TI1751-01-001/`](docs/examples/TI1751-01-001/)

### TI1055-01-001.pdf — Word PDF, 528 pages

```
Lines changed: 10,205 / 11,979    Char delta: -23,725
```

Word had embedded incorrect multi-character sequences for many vowel glyphs
(spurious subjoined-ja `ྗ` inserted before every `ོ`):

| Before (wrong) | After (correct) |
|----------------|-----------------|
| `བྗོད་གངས་ཅན་` | `བོད་གངས་ཅན་` |
| `དང་པྗོ་དཔར་སྐྲུན་` | `དང་པོ་དཔར་སྐྲུན་` |
| `ཐྗོས་བསམ་སྗོམ་གསུམ་` | `ཐོས་བསམ་སྒོམ་གསུམ་` |
| `མྱིག་འདུན་` | `མིག་འདུན་` |

Full output: [`docs/examples/TI1055-01-001/`](docs/examples/TI1055-01-001/)

## Rebuilding the Font Database

The pre-built `reverse_db.json` is included in the package.  If you have
`bodyig.zip` (the source font archive, ~69 MB, not included in this repo),
you can rebuild it:

```bash
# Place bodyig.zip in the scripts/ directory, then:
pip install fonttools
python scripts/build_reverse_db.py
```

## Project Structure

```
tibetan_pdf_fix/       Python package
├── extractor.py       Core logic: patch ToUnicode, extract text or emit PDF
└── data/
    └── reverse_db.json  GID -> Unicode database (bundled)
scripts/
├── build_reverse_db.py  Rebuild database from bodyig.zip
└── build_glyph_db.py    Legacy alternate builder
docs/
├── approach.md          Full technical explanation
└── examples/            Example PDFs and before/after outputs
    ├── TI1055-01-001/   Word PDF (.pdf, .raw.txt, .patched.txt, .diff.txt)
    └── TI1751-01-001/   InDesign PDF (.pdf, .raw.txt, .patched.txt, .diff.txt)
```

## License

MIT
