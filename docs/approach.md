# Technical Approach

## The Problem

Tibetan script uses stacked syllables — consonant clusters written vertically
where a base consonant is combined with superscript or subscript letters:

```
ཀྱི་  =  ཀ (ka) + ྱ (subjoined-ya) + ི (i-vowel) + ་ (tsek)
རྡོ་  =  ར (ra) + ྡ (subjoined-da) + ོ (o-vowel) + ་ (tsek)
སྤྱོད =  ས (sa) + ྤ (subjoined-pa) + ྱ (subjoined-ya) + ོ (o-vowel) + ད (da)
```

When such documents are exported to PDF, the font shaping engine merges these
multi-codepoint sequences into a single glyph (a **ligature**).  Each ligature
has a **Glyph ID (GID)** in the font.  The PDF contains a mapping called the
**ToUnicode CMap** that should map each GID back to the correct Unicode
sequence so that copy-paste and text extraction tools work correctly.

In practice, this mapping is frequently wrong or incomplete:

- **InDesign PDFs (Type0/CID)**: The ToUnicode may exist but omit subjoined
  letters — e.g. GID for `རྡོ་` is mapped to `རོ་` (the base + vowel only),
  silently dropping `ྡ`.
- **Word PDFs (Type0/CID)**: Word sometimes inserts an incorrect extra
  subjoined-ja (`ྗ`) into vowel-only glyphs — every `ོ` becomes `ྗོ`.
- **Ghostscript PDFs (TrueType)**: The PDF char-codes are Ghostscript-assigned
  sequential integers that do not correspond to font GIDs.  The ToUnicode
  covers only simple consonants; stacked glyphs have no mapping at all.

## The Solution

### Step 1 — Build a Reverse GID Database

The shipped **`pdf_cmap_fix/data/reverse_db.json`** lists **962** normalised
font keys (~16 MB on disk for the current bundle; see [font-inventory.md](font-inventory.md)).
It is produced by **`scripts/build_reverse_db.py`** from one or more archives
and/or directories (see root **README**): in practice **`scripts/bodyig.zip`**,
**`scripts/tibetan-fonts-main.zip`**, and **`scripts/tibetan-fonts-private-main.zip`**
are merged **in order**, with **later** inputs overriding earlier entries when
the normalised font stem collides.

For each font file:

1. Load the font with `fontTools`.
2. Read the **cmap** table: `codepoint → glyph_name` for atomic characters.
3. Read all **GSUB type-4 (ligature)** rules: `lig_glyph → [component_glyphs]`.
4. Recursively decompose each ligature back to its atomic components and then
   to their Unicode codepoints.

This gives us the **reverse mapping**: `GID → correct Unicode sequence` for
every glyph in the font, including complex stacked syllables.

```python
# simplified sketch
def decompose(gname):
    if gname in cmap_reverse:          # atomic character
        return cmap_reverse[gname]
    if gname in gsub_rules:            # ligature
        return "".join(decompose(c) for c in gsub_rules[gname])
    return ""                          # unmappable glyph
```

The result is stored in `pdf_cmap_fix/data/reverse_db.json`:

```json
{
  "monlamuniouchan2": {
    "216": "ོ",
    "390": "ལྔ",
    "1042": "རྐྱུ"
  },
  ...
}
```

The earliest documentation referred only to **`bodyig.zip`** (Monlam / Himalaya /
Jomolhari-heavy); the **bundled** database now aggregates many more faces—see
the full key list in [font-inventory.md](font-inventory.md).

### Step 2 — Match PDF Font to Database Entry

PDF fonts have names like `FPFIFO+Monlam#2320Uni#2320OuChan2`.  We normalise
both the PDF name and every DB key by:

1. Stripping the 6-character subset prefix (`FPFIFO+`).
2. Decoding PDF hex-escapes (`#23` → `#`, then `#20` → ` `) up to 3 times
   (InDesign double-encodes font names).
3. Stripping all non-alphanumeric characters and lowercasing.

`FPFIFO+Monlam#2320Uni#2320OuChan2` → `monlamuniouchan2` ✓

Scoring ranks exact matches above prefix/substring matches, with ties broken
by shortest name-length difference.

### Step 3 — Patch the ToUnicode CMap

For each matched Type0 font in the PDF:

1. Read the existing ToUnicode CMap stream.
2. For every GID where our DB has a mapping, **replace** the existing entry
   with the DB value — unconditionally, because the GSUB decomposition of the
   original full font is the authoritative source.
3. Write the merged CMap back into the PDF in memory (`pymupdf` updates the
   in-memory document).  The **input PDF file on disk is never modified**.

The new CMap uses 2-byte GID format (`<XXXX>`) as required for Type0/CID
Identity-H fonts.

### Text extraction vs patched PDF

After the CMap merge, the library can do either of the following (same patch,
same `reverse_db.json` matching rules):

| Mode | API | CLI | On disk |
|------|-----|-----|---------|
| Extract text | `extract_pdf_text` | `pdf-cmap-fix file.pdf` | Writes `file.raw.txt`, `file.patched.txt`, `file.diff.txt` next to the PDF (or another `output_dir`).  Does **not** change the original PDF. |
| Emit patched PDF | `patch_pdf` | `pdf-cmap-fix --patch-pdf file.pdf` (alias `-p`) | Writes `file.patched.pdf` by default (or a path you pass).  The original PDF is still untouched. |
| Dict only (no PDF write) | `build_tounicode_dict` | `pdf-cmap-fix --dump-cmap out.json file.pdf` | Writes JSON with per-font `existing`, `merged`, and `overrides` maps. |

The patched PDF is a normal PDF with corrected ToUnicode streams, so
copy-paste, search, and downstream extractors that honour ToUnicode will see the
same corrected Tibetan Unicode as in `extract_pdf_text`'s `patched` string.

### Why "Replace Unconditionally"?

Early versions of this tool merged by keeping the *longer* of the two
sequences.  This was wrong for Word-generated PDFs (TI1055):

| GID | Word ToUnicode | Correct |
|-----|---------------|---------|
| 216 | `ྗོ` (2 chars, wrong) | `ོ` (1 char, correct) |
| 390 | `ལྗོ` (3 chars, wrong) | `ལ` (1 char) |

Word inserted a spurious subjoined-ja (`ྗ`, U+0F97) into many vowel-only
glyphs.  The authoritative DB value is always correct because it comes from
the actual font's GSUB table rather than from Word's heuristics.

### Why Only Type0 Fonts?

Type0/CID fonts with **Identity-H encoding** preserve the original font GIDs
in the PDF.  Char code `N` in the PDF content stream = GID `N` in the
original font = entry `N` in our reverse_db.  The mapping is exact.

TrueType **simple-encoding** fonts (e.g. Ghostscript-generated PDFs) assign
their own sequential char codes (1, 2, 3, ...) per-subset.  Char code 1 is
Ghostscript's *first used glyph*, which may be GID 3 or GID 1042 or anything
else in the original font.  Without reading the embedded subset's glyph order
and matching it against the full font's glyph order, there is no reliable way
to map char codes back to original GIDs.  Patching these blindly produces
garbled output.

## Supported Fonts

Matching uses **normalised keys** as stored in **`reverse_db.json`** (lowercase
letters and digits only). The bundled file lists **962** keys—see
[font-inventory.md](font-inventory.md). Example keys still common in Tibetan
publications include **`monlamuniouchan2`**, **`himalaya`**, **`jomolhari`**, and
many others from the combined font ZIPs.

Fonts **not** yet supported (TrueType simple encoding):

- Himalaya-G variant used in older Ghostscript PDFs (PUA codepoints F001-F04B,
  predating Tibetan Unicode standardisation)
- Any Ghostscript-generated PDF where Tibetan fonts are embedded as TrueType
  simple fonts with sequential char-code assignment

## Results on Example PDFs

### TI1751-01-001.pdf (InDesign, 528 pages)

Metrics below use the **bundled** `reverse_db.json` and current extractor;
exact counts move slightly if the database or PDF tooling changes.

| Metric | Value |
|--------|-------|
| Pages | 528 |
| Type0 fonts seen (with `/ToUnicode`) | 2,163 |
| Lines differing (`.diff.txt`, page-banner format) | ~5,295 |
| Char delta (`patched` − `raw`) | ~+10,093 |

Tibetan body text is largely **Monlam Uni OuChan2**; the publication also embeds
other Type0/Latin/CJK fonts (Calibri, Himalaya, Dedris, PMingLiU, …)—see the
**`--dump-cmap`** JSON for per-font names and xref IDs.

Representative fixes:

| RAW (wrong) | PATCHED (correct) |
|-------------|-------------------|
| `ཀོང་ཡངས་` | `ཀློང་ཡངས་` (added subjoined-la) |
| `རྣལ་འབོར་` | `རྣལ་འབྱོར་` (added subjoined-ya) |
| `ཀི་` | `ཀྱི་` (added subjoined-ya) |
| `རོ་རེའི་` | `རྡོ་རྗེའི་` (added subjoined-da, subjoined-ja) |
| `སིང་` | `སྙིང་` (added subjoined-nya) |
| `བིན་རླབས་` | `བྱིན་རླབས་` (added subjoined-ya) |

### TI1055-01-001.pdf (Microsoft Word, 528 pages)

| Metric | Value |
|--------|-------|
| Pages | 528 |
| Type0 fonts seen (with `/ToUnicode`) | 4 |
| Lines differing (`.diff.txt`) | ~10,205 |
| Char delta | ~−23,725 (shorter = removal of spurious characters) |

Representative fixes:

| RAW (wrong) | PATCHED (correct) |
|-------------|-------------------|
| `བྗོད་` | `བོད་` (removed spurious ྗ) |
| `དང་པྗོ་` | `དང་པོ་` (removed spurious ྗ) |
| `མྱིག་` | `མིག་` (corrected subjoined-ya) |
| `ཐྗོས་བསམ་སྗོམ་` | `ཐོས་བསམ་སྒོམ་` (spurious ྗ removed) |
| `གྲངས་གྱིས་མ་ལྗོང་` | `གྲངས་གྱིས་མ་ལོང་` (spurious ྗ removed) |

The negative char delta is expected: Word had inserted spurious multi-codepoint
sequences for glyphs that should map to a single codepoint, so the corrected
output is shorter but accurate.

## File Layout

```
pdf-cmap-fix/
├── pdf_cmap_fix/             Python package (installed)
│   ├── __init__.py
│   ├── extractor.py          Patch ToUnicode; extract; build_tounicode_dict; CLI
│   └── data/
│       └── reverse_db.json   Pre-built GID → Unicode database (~16 MB; 962 keys)
├── scripts/
│   ├── font_sources.py       Enumerate fonts from zip and/or directories
│   ├── build_reverse_db.py   Rebuild reverse_db.json (zip and/or --fonts-dir)
│   └── build_glyph_db.py     DEPRECATED — use build_reverse_db.py
├── docs/
│   ├── approach.md           This file
│   └── examples/
│       ├── TI1751-01-001/    InDesign PDF + reference outputs
│       │   ├── TI1751-01-001.pdf
│       │   ├── TI1751-01-001.raw.txt
│       │   ├── TI1751-01-001.patched.txt
│       │   ├── TI1751-01-001.diff.txt
│       │   ├── TI1751-01-001.patched.pdf   (from CLI `-p` / `--patch-pdf`)
│       │   └── TI1751-01-001.cmap-dump.json  (`--dump-cmap`; very large)
│       └── TI1055-01-001/    Word PDF + reference outputs
│           ├── TI1055-01-001.pdf
│           ├── TI1055-01-001.raw.txt
│           ├── TI1055-01-001.patched.txt
│           ├── TI1055-01-001.diff.txt
│           ├── TI1055-01-001.patched.pdf
│           └── TI1055-01-001.cmap-dump.json
├── pyproject.toml
├── README.md
└── .gitignore
```

## Rebuilding the Database

Place the font ZIPs under `scripts/` (and/or pass `--fonts-dir`)—see the root
**README** for the recommended **`bodyig`** + **`tibetan-fonts-main`** +
**`tibetan-fonts-private-main`** order:

```bash
pip install fonttools
python scripts/build_reverse_db.py --zip scripts/bodyig.zip
python scripts/build_reverse_db.py --fonts-dir ../tibetan-fonts
python scripts/build_reverse_db.py \
  --zip scripts/bodyig.zip \
  --zip scripts/tibetan-fonts-main.zip \
  --zip scripts/tibetan-fonts-private-main.zip \
  -o pdf_cmap_fix/data/reverse_db.json
```

If you omit `--zip` and `--fonts-dir`, the script defaults to `scripts/bodyig.zip`
when that file exists.  Duplicate normalised font names: **later** sources
overwrite earlier ones (with a warning on stderr).

Output defaults to `pdf_cmap_fix/data/reverse_db.json`.
