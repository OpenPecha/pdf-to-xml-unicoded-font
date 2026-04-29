"""Smoke tests for ``scripts/build_reverse_db.py`` (``build_gid_map``)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def _system_ttf() -> Path | None:
    for p in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ):
        if p.is_file():
            return p
    return None


@pytest.mark.skipif(_system_ttf() is None, reason="no common system TTF found")
def test_build_gid_map_smoke() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import build_reverse_db as br

    font = TTFont(str(_system_ttf()), lazy=False)
    m = br.build_gid_map(font)
    assert len(m) >= 50
    # Space or digit should map to ASCII from cmap
    assert any(v.strip() and ord(v[0]) < 0x80 for v in m.values())


def test_normalise_font_stem() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import build_reverse_db as br

    assert br.normalise_name("fonts/Monlam Uni OuChan2.ttf") == "monlamuniouchan2"
