"""
tibetan_pdf_fix
===============

Fix missing Tibetan stacked syllables in PDF text extraction, or emit a
patched PDF with corrected ToUnicode maps.

Quick start
-----------
    from tibetan_pdf_fix import extract_tibetan_pdf, patch_tibetan_pdf

    result = extract_tibetan_pdf("myfile.pdf")
    print(result["patched"])   # corrected Unicode text
    # Output files: myfile.raw.txt, myfile.patched.txt, myfile.diff.txt

    out = patch_tibetan_pdf("myfile.pdf")   # writes myfile.patched.pdf
"""

from .extractor import (
    extract_tibetan_pdf,
    patch_tibetan_pdf,
    extract_all,
    patch_doc,
)

__version__ = "0.1.0"
__all__ = [
    "extract_tibetan_pdf",
    "patch_tibetan_pdf",
    "extract_all",
    "patch_doc",
]
