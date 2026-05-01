# pdf-cmap-fix

Fix missing or wrong **PDF `/ToUnicode` CMap** entries so text extraction and copy-paste match what you see on the page. The primary use case is **Tibetan** stacked syllables (Monlam, Himalaya, Jomolhari): producers often embed incomplete or incorrect Unicode mappings for ligature glyphs. The same mechanism applies to **any** Type0 / Identity-H font present in the bundled GSUB-derived database.

**GitHub:** [OpenPecha/pdf-cmap-fix](https://github.com/OpenPecha/pdf-cmap-fix)

**Documentation:** [docs/README.md](docs/README.md) · [Glossary & JSON formats](docs/glossary-and-json.md) · [Approach](docs/approach.md) · [Font inventory (962 keys)](docs/font-inventory.md)

---

## Table of contents

1. [Installation](#installation)
2. [Quick start (CLI)](#quick-start-cli)
3. [Python API reference](#python-api-reference)
4. [Bundled reverse database (font sources)](#bundled-reverse-database-font-sources)
5. [Updating `reverse_db.json` in the future](#updating-reverse_dbjson-in-the-future)
6. [Migration from `tibetan-pdf-fix`](#migration-from-tibetan-pdf-fix-01x)
7. [Supported fonts & limits](#supported-fonts--limits)
8. [How it works](#how-it-works)
9. [Example results](#example-results)
10. [Project structure](#project-structure)
11. [License](#license)

---

## Installation

Requires **Python 3.8+**, [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`), and [fontTools](https://fonttools.readthedocs.io/) (declared in `pyproject.toml`).

### From Git (recommended for latest `main`)

Install the package directly from this repository:

```bash
pip install "pdf-cmap-fix @ git+https://github.com/OpenPecha/pdf-cmap-fix.git"
```

Equivalent shorthand:

```bash
pip install git+https://github.com/OpenPecha/pdf-cmap-fix.git
```

Editable checkout for development:

```bash
git clone https://github.com/OpenPecha/pdf-cmap-fix.git
cd pdf-cmap-fix
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

After install, the CLI **`pdf-cmap-fix`** is on your `PATH`. The bundled database ships inside the wheel/sdist as package data (`pdf_cmap_fix/data/reverse_db.json`).

---

## Quick start (CLI)

```bash
pdf-cmap-fix document.pdf
# writes: document.raw.txt  document.patched.txt  document.diff.txt
```

```bash
pdf-cmap-fix doc1.pdf doc2.pdf doc3.pdf
```

**Patched PDF only** (same ToUnicode logic; does not overwrite the input):

```bash
pdf-cmap-fix --patch-pdf document.pdf
# writes: document.patched.pdf
pdf-cmap-fix -p doc1.pdf doc2.pdf   # short form
```

**Dump merged ToUnicode data as JSON** (does **not** modify the PDF):

```bash
pdf-cmap-fix --dump-cmap cmap.json document.pdf
# multiple PDFs → cmap_<stem>.json per file
```

Large PDFs with **many** Type0 font objects can make `--dump-cmap` slow and the JSON huge; prefer [`build_tounicode_dict`](#build_tounicode_dict) in Python if you need to filter by font name or xref.

---

## Python API reference

Import the public API from **`pdf_cmap_fix`**:

```python
from pdf_cmap_fix import (
    extract_pdf_text,
    patch_pdf,
    build_tounicode_dict,
    collect_font_merges,
    patch_doc,
    extract_all,
)
```

Optional: load a custom JSON database with `json.loads(...)` and pass as `rev_db=` where supported.

| Function | Purpose |
|----------|---------|
| **`extract_pdf_text`** | Opens the PDF twice: extract raw text, then patch ToUnicode in memory and extract again. Can write `.raw.txt`, `.patched.txt`, `.diff.txt`. |
| **`patch_pdf`** | Applies merged ToUnicode streams and returns bytes (and optionally writes `*.patched.pdf`). |
| **`build_tounicode_dict`** | No PDF mutation: returns per-font `existing` / `merged` / `overrides` plus `stats`. |
| **`collect_font_merges`** | Lower-level: scan the document and compute merge records without writing streams. |
| **`patch_doc`** | Apply merges to an already-open **`fitz.Document`** using `collect_font_merges` + stream updates. |
| **`extract_all`** | Extract plain text from every page (with whitespace/ligature flags); used inside `extract_pdf_text`. |

### `extract_pdf_text`

```python
extract_pdf_text(
    pdf_path,
    output_dir=None,
    write_files=True,
    rev_db=None,
    *,
    verbose=False,
) -> dict
```

| Return key | Type | Description |
|------------|------|-------------|
| `raw` | `str` | Text extracted before patching. |
| `patched` | `str` | Text extracted after ToUnicode merge. |
| `stats` | `dict` | `fonts_seen`, `patched`, `upgrades`, `no_change`, `no_match`. |
| `diff_lines` | `list` | Line indices and raw/patched pairs where lines differ. |
| `char_delta` | `int` | `len(patched) - len(raw)`. |

If `write_files` is true (default), writes `{stem}.raw.txt`, `{stem}.patched.txt`, `{stem}.diff.txt` next to the PDF (or under `output_dir`).

### `patch_pdf`

```python
patch_pdf(
    pdf_path,
    output_path=None,
    write_file=True,
    rev_db=None,
    *,
    verbose=False,
) -> dict
```

| Return key | Description |
|------------|-------------|
| `pdf_bytes` | Patched PDF as `bytes`. |
| `stats` | Same counters as above. |
| `output_path` | `Path` where the file was written, or `None` if `write_file=False`. |

Default output path: `{stem}.patched.pdf` beside the input.

### `build_tounicode_dict`

```python
build_tounicode_dict(pdf_path, rev_db=None) -> dict
```

Returns `fonts` (list of per-font records), `by_font_xref` (dict keyed by xref string), and `stats`. See [docs/glossary-and-json.md](docs/glossary-and-json.md) for field-level documentation.

### `collect_font_merges`

```python
collect_font_merges(doc: fitz.Document, rev_db: dict, *, verbose=False)
-> tuple[list[dict], dict]
```

Returns `(records, stats)`. Each record includes `font_xref`, `to_unicode_xref`, `pdf_font_name`, `db_key_matched`, `existing`, `merged`, `overrides`, `changed`.

### `patch_doc`

```python
patch_doc(doc: fitz.Document, rev_db: dict, *, verbose=False) -> dict[str, int]
```

Mutates **`doc`** in place (writes ToUnicode streams where `changed > 0`). Returns **`stats`**.

### `extract_all`

```python
extract_all(doc: fitz.Document) -> str
```

Full-document text with page banners (`=== PAGE n ===`). Used internally after patching.

---

## Bundled reverse database (font sources)

The file **`pdf_cmap_fix/data/reverse_db.json`** ships with the package (~**16 MB** on disk as of the build below). It maps **normalised font key → { GID string → Unicode string }**, built offline from TrueType/OpenType sources using cmap + GSUB type-4 ligature decomposition (see `scripts/build_reverse_db.py`).

| Property | Value |
|----------|--------|
| **Build date** | **2026-04-28** |
| **Font entries (keys)** | **962** |
| **Full key list** | [docs/font-inventory.md](docs/font-inventory.md) |

### How this copy was produced

Sources were combined **in order**; **later** archives override earlier entries when the **normalised font key** collides (same stem after lowercasing and stripping non-alphanumeric characters):

1. **`scripts/bodyig.zip`** — legacy “bodyig”-style corpus bundled with this repo for reproducibility.
2. **`scripts/tibetan-fonts-main.zip`** — snapshot of the **public** [OpenPecha `tibetan-fonts`](https://github.com/openpecha/tibetan-fonts) **`main`** branch (downloaded as ZIP).
3. **`scripts/tibetan-fonts-private-main.zip`** — snapshot of the **private** Tibetan fonts repo **`main`** branch (downloaded as ZIP).

Command used (from repository root):

```bash
python scripts/build_reverse_db.py ^
  --zip scripts/bodyig.zip ^
  --zip scripts/tibetan-fonts-main.zip ^
  --zip scripts/tibetan-fonts-private-main.zip ^
  -o pdf_cmap_fix/data/reverse_db.json
```

**Why ZIP instead of `git clone`?** On Windows, cloning large font repositories can fail when paths contain characters NTFS rejects (for example `:`). Reading **`.ttf` / `.otf` directly from ZIP files** avoids extracting those paths to disk and matches how CI or contributors can refresh the database without a full checkout.

---

## Updating `reverse_db.json` in the future

When upstream font repositories add or change faces:

1. Download fresh **`main`** ZIP archives (or clone on Linux/macOS / WSL if you prefer `--fonts-dir`).
2. Re-run `build_reverse_db.py` with the same `--zip` order (or adjust order deliberately if you want a different precedence).
3. Replace `pdf_cmap_fix/data/reverse_db.json` and record the **new build date** in this README (and optionally in `CHANGELOG.md`).
4. Regression-test on known PDFs (for example under `docs/examples/`) before tagging a release.

Optional inputs:

```bash
pip install fonttools
python scripts/build_reverse_db.py --fonts-dir path/to/fonts -o pdf_cmap_fix/data/reverse_db.json
python scripts/build_reverse_db.py --zip scripts/bodyig.zip --fonts-dir ../more-fonts -o out.json
```

If you omit `--zip` and `--fonts-dir`, the script defaults to **`scripts/bodyig.zip`** when that file exists.

See also **Rebuild** notes in [CHANGELOG.md](CHANGELOG.md).

---

## Migration from `tibetan-pdf-fix` (0.1.x)

| Old (removed) | New (0.2.0) |
|---------------|-------------|
| PyPI / import `tibetan_pdf_fix` | `pdf_cmap_fix` |
| CLI `tibetan-pdf-fix` | `pdf-cmap-fix` |
| `extract_tibetan_pdf(...)` | `extract_pdf_text(...)` |
| `patch_tibetan_pdf(...)` | `patch_pdf(...)` |
| *(new)* | `build_tounicode_dict(...)` — merged CMaps as dicts **without** patching PDF bytes |
| `pip install …` same git URL | Package name **`pdf-cmap-fix`** |

There is **no** compatibility shim: update imports and the CLI name.

---

## Supported fonts & limits

The bundled database covers **962** normalised font keys drawn from the archives above (see [docs/font-inventory.md](docs/font-inventory.md)). Only **Type0 / CID / Identity-H** fonts are handled (PDF character code = original GID in the subset). **TrueType simple-encoding** PDFs (typical of some Ghostscript workflows) are **not** supported by this path.

---

## How it works

1. Match each embedded Type0 font name to an entry in `reverse_db.json`.
2. Parse the PDF’s existing ToUnicode CMap.
3. Merge: the database replaces entries wherever it has a GID mapping (GSUB-derived mappings are treated as authoritative).
4. Optionally write streams back (`patch_pdf` / `extract_pdf_text`) or only return dicts (`build_tounicode_dict`).

Details: [`docs/approach.md`](docs/approach.md).

---

## Example results

### TI1751-01-001.pdf — InDesign PDF, 528 pages

| Before (wrong) | After (correct) |
|----------------|-----------------|
| `ཀོང་ཡངས་རོལ་བའི་རྣལ་འབོར་པ་` | `ཀློང་ཡངས་རོལ་བའི་རྣལ་འབྱོར་པ་` |
| `རོ་རེའི་སེ་ཕེང་` | `རྡོ་རྗེའི་སྐྱེ་ཕྲེང་` |

Outputs: [`docs/examples/TI1751-01-001/`](docs/examples/TI1751-01-001/)

### TI1055-01-001.pdf — Word PDF, 528 pages

| Before (wrong) | After (correct) |
|----------------|-----------------|
| `བྗོད་གངས་ཅན་` | `བོད་གངས་ཅན་` |
| `ཐྗོས་བསམ་སྗོམ་གསུམ་` | `ཐོས་བསམ་སྒོམ་གསུམ་` |

Outputs: [`docs/examples/TI1055-01-001/`](docs/examples/TI1055-01-001/)

---

## Beyond Tibetan (smoke test)

The pipeline is **not** Tibetan-specific: any Identity-H Type0 font whose glyph IDs align with a font used to build `reverse_db.json` can be fixed the same way. For a minimal Latin test, build a tiny database from a font with `fi`/`fl` ligatures and validate non-empty `overrides` on a deliberately broken PDF.

---

## Project structure

```
pdf_cmap_fix/              Python package
├── extractor.py           Patch / extract / build_tounicode_dict / CLI
└── data/
    └── reverse_db.json    GID → Unicode (bundled; regenerate via scripts)
scripts/
├── font_sources.py        Zip + directory font enumeration
├── build_reverse_db.py    Rebuild reverse_db.json (Windows-safe UTF-8 logging)
└── build_glyph_db.py      Deprecated — use build_reverse_db.py
docs/
├── README.md              Documentation index
├── glossary-and-json.md   Terms + JSON shapes
├── font-inventory.md      All 962 bundled font keys
├── approach.md            Design / pipeline
├── blog.md                Draft / notes
└── examples/              Example PDFs and outputs
tests/                     pytest (optional [dev] install)
```

---

## License

MIT
