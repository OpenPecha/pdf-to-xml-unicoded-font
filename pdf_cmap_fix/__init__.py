"""
pdf_cmap_fix
============

Fix incorrect or incomplete PDF ``/ToUnicode`` CMaps using a GSUB-derived
GID→Unicode database (primarily Tibetan Monlam / Himalaya / Jomolhari fonts),
then extract text or emit a patched PDF.

Public API
----------
    from pdf_cmap_fix import extract_pdf_text, patch_pdf, build_tounicode_dict

    result = extract_pdf_text("doc.pdf")
    print(result["patched"])

    patch_pdf("doc.pdf")  # writes doc.patched.pdf

    cmap = build_tounicode_dict("doc.pdf")  # no PDF mutation; ``fonts`` / ``stats``
"""

from .extractor import (
    build_tounicode_dict,
    collect_font_merges,
    extract_all,
    extract_pdf_text,
    patch_doc,
    patch_pdf,
)

__version__ = "0.2.0"
__all__ = [
    "build_tounicode_dict",
    "collect_font_merges",
    "extract_all",
    "extract_pdf_text",
    "patch_doc",
    "patch_pdf",
]
