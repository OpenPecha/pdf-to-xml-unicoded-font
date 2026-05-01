"""Unit tests for pdf_cmap_fix pure helpers and integration smoke tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_cmap_fix.extractor import (
    _build_tounicode_type0,
    _merge,
    _normalise_name,
    _parse_tounicode,
    _sanitise_json_utf8,
    _serialise_cmap_result,
    build_tounicode_dict,
)

REPO = Path(__file__).resolve().parents[1]
TI1751 = REPO / "docs" / "examples" / "TI1751-01-001" / "TI1751-01-001.pdf"


def test_normalise_name_subset_and_hex_escapes() -> None:
    s = "FPFIFO+Monlam#2320Uni#2320OuChan2"
    assert _normalise_name(s) == "monlamuniouchan2"


def test_merge_db_authoritative_word_like_case() -> None:
    """DB replaces wrong multi-char ToUnicode (TI1055-style spurious ྗ)."""
    existing = {216: "ྗོ", 390: "ལྗོ"}
    db_map = {216: "ོ", 390: "ལ"}
    merged, changed = _merge(existing, db_map)
    assert merged[216] == "ོ"
    assert merged[390] == "ལ"
    assert changed == 2


def test_merge_partial_overlap() -> None:
    existing = {1: "a", 2: "b"}
    db_map = {2: "B", 3: "c"}
    merged, changed = _merge(existing, db_map)
    assert merged[1] == "a"
    assert merged[2] == "B"
    assert merged[3] == "c"
    assert changed == 2


def test_parse_tounicode_bfchar_spaced() -> None:
    cmap = b"""begincmap
1 beginbfchar
<0001> <0041>
endbfchar
endcmap
"""
    d = _parse_tounicode(cmap)
    assert d[1] == "A"


def test_parse_tounicode_bfchar_compact() -> None:
    cmap = b"""begincmap
1 beginbfchar
<0001><00420043>
endbfchar
endcmap
"""
    d = _parse_tounicode(cmap)
    assert d[1] == "BC"


def test_build_tounicode_roundtrip() -> None:
    m = {1: "A", 16: "བ"}
    raw = _build_tounicode_type0(m)
    back = _parse_tounicode(raw)
    assert back[1] == "A"
    assert back[16] == "བ"


def test_sanitise_json_utf8_surrogate() -> None:
    bad = "\ud800"
    assert _sanitise_json_utf8({"x": bad}) == {"x": "\ufffd"}


def test_serialise_cmap_result_str_keys() -> None:
    payload = {
        "fonts": [
            {
                "font_xref": 42,
                "to_unicode_xref": 99,
                "pdf_font_name": "X+Font",
                "db_key_matched": "font1",
                "existing": {1: "a"},
                "merged": {1: "A"},
                "overrides": {1: "A"},
                "changed": 1,
            }
        ],
        "stats": {"fonts_seen": 1},
    }
    out = _serialise_cmap_result(payload)
    assert out["fonts"][0]["existing"] == {"1": "a"}
    assert out["fonts"][0]["merged"] == {"1": "A"}


@pytest.mark.skipif(not TI1751.is_file(), reason="example PDF not present")
def test_build_tounicode_dict_ti1751() -> None:
    db_path = REPO / "pdf_cmap_fix" / "data" / "reverse_db.json"
    rev_db = json.loads(db_path.read_text(encoding="utf-8"))
    result = build_tounicode_dict(TI1751, rev_db=rev_db)
    assert result["stats"]["fonts_seen"] >= 1
    assert len(result["fonts"]) >= 1
    any_overrides = any(len(f["overrides"]) > 0 for f in result["fonts"])
    assert any_overrides, "TI1751 should have at least one overridden GID"
