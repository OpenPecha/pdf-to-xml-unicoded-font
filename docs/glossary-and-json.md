# Glossary and JSON formats

Terms and file formats used throughout **pdf-cmap-fix**. Read this if you are integrating the library or regenerating `reverse_db.json`.

## Terms

| Term | Meaning |
|------|---------|
| **Type0 font** | PDF composite font for CID-keyed glyphs (often used with OpenType/CFF). This tool focuses on Type0 fonts that use Identity-H encoding. |
| **CID / GID** | Character identifier in the font’s glyph space. For Identity-H subsets, the PDF char code often equals the **glyph ID (GID)** from the embedded font. |
| **Identity-H** | Horizontal identity encoding: two-byte character codes map directly to glyph IDs. The reverse database maps **GID → Unicode string**. |
| **ToUnicode** | A PDF stream (`/ToUnicode`) that maps character codes to Unicode for copy-paste and text extraction. Many Tibetan PDFs ship incomplete or wrong tables for stacked syllables. |
| **CMap** | Character map; here mainly the **ToUnicode CMap** content (PDF syntax with `beginbfchar` / `beginbfrange` ranges). |
| **GSUB** | OpenType **Glyph Substitution** table. Type-4 lookups describe **ligatures** (e.g. stacked Tibetan). The builder walks these rules to expand ligature glyphs into Unicode sequences. |
| **Reverse database** | `reverse_db.json`: for each known font (by normalised name), a map **GID (string) → Unicode string**. Built offline from `.ttf`/`.otf` using cmap + GSUB. |
| **Normalised font key** | Font family name derived from the source filename: lowercase, only `a–z` and `0–9` (all other characters removed). Used as JSON keys and for matching PDF subset names. |
| **`rev_db` / `db_key_matched`** | At runtime, the PDF’s embedded font base name is matched to one key in the reverse database; `db_key_matched` records which key was used (or `null`). |

## `pdf_cmap_fix/data/reverse_db.json`

Shipped as package data. Shape:

```json
{
  "monlamuniouchan1": {
    "42": "ཀ",
    "43": "ཁ"
  },
  "himalayaa": { ... }
}
```

- **Top-level keys:** normalised font identifiers (see [font-inventory.md](font-inventory.md)).
- **Per-font values:** object whose keys are **decimal strings** of GID integers, values are **Unicode strings** (may be multiple code points for one glyph after GSUB decomposition).

This file is **not** a PDF mapping of page bytes; it is only the font-authoritative GID→Unicode side used to **patch** each font’s ToUnicode stream.

## Python API: `build_tounicode_dict` return value

Returned dict:

| Key | Type | Description |
|-----|------|-------------|
| `fonts` | `list[dict]` | One record per Type0 font that has a ToUnicode stream (may repeat logical fonts across pages; records dedupe by font xref where implemented). |
| `by_font_xref` | `dict[str, dict]` | Same records keyed by string form of `font_xref`. |
| `stats` | `dict` | Aggregates: `fonts_seen`, `patched`, `upgrades`, `no_change`, `no_match`. |

Each record in `fonts`:

| Field | Description |
|-------|-------------|
| `font_xref` | PDF object number for the font dictionary. |
| `to_unicode_xref` | PDF object number for the `/ToUnicode` stream. |
| `pdf_font_name` | Base name as reported by the PDF (may include subset prefix). |
| `db_key_matched` | Key from `reverse_db.json` used for merge, or `null` if no match. |
| `existing` | Parsed current ToUnicode: **GID → Unicode** (`int` keys in memory). |
| `merged` | After applying the database: combined map used if written to PDF. |
| `overrides` | Entries where merged differs from existing (what actually changes). |
| `changed` | Count of GID entries updated from the database perspective (merge metric). |

## CLI `--dump-cmap` JSON

The CLI writes a JSON-serialisable subset: inner maps use **string keys** for GIDs (`"42"` not `42`). Structure mirrors `_serialise_cmap_result`: top-level `fonts` array and `stats`; there is no `by_font_xref` in the dumped file (only in the in-memory Python result).

## Related reading

- [approach.md](approach.md) — pipeline and design notes.
- [README.md](../README.md) — installation, CLI, and rebuilding the database.
