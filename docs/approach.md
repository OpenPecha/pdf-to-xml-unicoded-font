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

For each Tibetan font in the bundled archive (`bodyig.zip`), we:

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

The result is stored in `tibetan_pdf_fix/data/reverse_db.json`:

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

The database covers **68 font variants** from Monlam, Himalaya, and Jomolhari
families (deduped from 70 TTF files in `bodyig.zip`).

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
| Extract text | `extract_tibetan_pdf` | `tibetan-pdf-fix file.pdf` | Writes `file.raw.txt`, `file.patched.txt`, `file.diff.txt` next to the PDF (or another `output_dir`).  Does **not** change the original PDF. |
| Emit patched PDF | `patch_tibetan_pdf` | `tibetan-pdf-fix --patch-pdf file.pdf` (alias `-p`) | Writes `file.patched.pdf` by default (or a path you pass).  The original PDF is still untouched. |

The patched PDF is a normal PDF with corrected ToUnicode streams, so
copy-paste, search, and downstream extractors that honour ToUnicode will see the
same corrected Tibetan Unicode as in `extract_tibetan_pdf`'s `patched` string.

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

The reverse_db covers all fonts in `bodyig.zip`.  Normalised keys (used
internally for matching):

```
himalaya            himalayaa           himalayab
himalayac           himalayad           himalayae
himalayaf           himalayag           himalayah
himalayai           himalayaj           himalayak
himalyal            himalayam           himalayan
himalayasn          himalaya0           jomolhari
monlamuniouchan1    monlamuniouchan2    monlamuniouchan3
monlamuniouchan4    monlamuniouchan5    ...
```

(Full list: 68 unique font variants.)

Fonts **not** yet supported (TrueType simple encoding):

- Himalaya-G variant used in older Ghostscript PDFs (PUA codepoints F001-F04B,
  predating Tibetan Unicode standardisation)
- Any Ghostscript-generated PDF where Tibetan fonts are embedded as TrueType
  simple fonts with sequential char-code assignment

## Results on Example PDFs

### TI1751-01-001.pdf (InDesign, 528 pages)

| Metric | Value |
|--------|-------|
| Font | Monlam Uni OuChan2 (Type0/CID) |
| Lines changed | 2,540 / 5,361 |
| Char delta | +9,969 |

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
| Font | Monlam Uni OuChan2 (Type0/CID) |
| Lines changed | 10,205 / 11,979 |
| Char delta | -23,725 (shorter = removal of spurious characters) |

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
pdf-to-xml-unicoded-font/
├── tibetan_pdf_fix/          Python package (installed)
│   ├── __init__.py
│   ├── extractor.py          Patch ToUnicode; text extract or patched-PDF output
│   └── data/
│       └── reverse_db.json   Pre-built GID -> Unicode database (2.4 MB)
├── scripts/
│   ├── build_reverse_db.py   Rebuild reverse_db.json (needs bodyig.zip)
│   └── build_glyph_db.py     Legacy alternate DB builder
├── docs/
│   ├── approach.md           This file
│   └── examples/
│       ├── TI1751-01-001/    InDesign PDF + raw/patched/diff outputs
│       │   ├── TI1751-01-001.pdf
│       │   ├── TI1751-01-001.raw.txt
│       │   ├── TI1751-01-001.patched.txt
│       │   └── TI1751-01-001.diff.txt
│       └── TI1055-01-001/    Word PDF + raw/patched/diff outputs
│           ├── TI1055-01-001.pdf
│           ├── TI1055-01-001.raw.txt
│           ├── TI1055-01-001.patched.txt
│           └── TI1055-01-001.diff.txt
├── pyproject.toml
├── README.md
└── .gitignore
```

## Rebuilding the Database

If you obtain `bodyig.zip` and place it in `scripts/`, you can regenerate
`reverse_db.json`:

```bash
pip install fonttools
python scripts/build_reverse_db.py
```

This processes all 70 TTF files in the archive (deduped to 68 unique font
variants) and writes the updated database to
`tibetan_pdf_fix/data/reverse_db.json`.
