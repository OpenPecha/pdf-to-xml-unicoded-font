"""
Enumerate font files for reverse_db building.

Supports:
  - zip archives (any .ttf / .otf member path)
  - recursive directory scan (*.ttf, *.otf)
"""
from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

_FONT_SUFFIXES = (".ttf", ".otf")


def iter_fonts_from_zip(zip_path: Path) -> Iterator[tuple[str, bytes]]:
    """Yield (virtual_path_for_dedup, font_bytes) for each font inside the zip."""
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if not lower.endswith(_FONT_SUFFIXES):
                continue
            yield name, zf.read(name)


def iter_fonts_from_dir(root: Path) -> Iterator[tuple[Path, None]]:
    """Yield (absolute_path, None) for each .ttf / .otf under *root* recursively."""
    root = root.resolve()
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in _FONT_SUFFIXES:
            yield path, None

