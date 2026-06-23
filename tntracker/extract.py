"""Extract text from a GO PDF and try to find its issue date.

Failure path (decision #7): if a PDF yields little/no text it is treated as
scanned and flagged STATUS_NO_TEXT rather than OCR'd. We log and move on.
"""
from __future__ import annotations

import datetime as _dt
import re

import pdfplumber

from . import config, ocr

# Minimum chars before we trust a PDF as text (vs. a scanned image).
_MIN_TEXT = 80

# TN GOs print the date in a few common forms; try them in order.
_DATE_PATTERNS = [
    # "Dated: 12.06.2026" / "Dated 12-06-2026"
    (re.compile(r"Dat(?:ed|e)\s*[:\-]?\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", re.I),
     "dmy"),
    # "12th June 2026" / "12 June, 2026"
    (re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+"
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)[,\s]+(\d{4})", re.I),
     "dMy"),
]
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}


def extract_text(pdf_path: str) -> dict:
    """Get text from a GO PDF: try embedded text first, then OCR.

    Returns {text, raw_text_len, go_date, source_snippet, is_text, method}.
    `method` is 'embedded', 'ocr', or 'none'.
    """
    # 1) Embedded text (fast path — works for the minority of digital GOs).
    text = ""
    try:
        parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:config.OCR_MAX_PAGES]:
                parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
    except Exception:
        text = ""

    method = "embedded"

    # 2) OCR fallback for scanned image PDFs (the common case for TN GOs).
    if len(text) < _MIN_TEXT:
        try:
            ocr_text = ocr.ocr_pdf(pdf_path)
            if len(ocr_text) > len(text):
                text, method = ocr_text, "ocr"
        except ocr.OCRUnavailable as e:
            print(f"  (OCR unavailable: {e})")
        except Exception as e:
            print(f"  (OCR failed: {e})")

    is_text = len(text) >= config.OCR_MIN_CHARS
    return {
        "text": text,
        "raw_text_len": len(text),
        "go_date": _find_date(text) if is_text else None,
        "source_snippet": text[:600],
        "is_text": is_text,
        "method": method if is_text else "none",
    }


def _find_date(text: str) -> str | None:
    for rx, kind in _DATE_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        try:
            if kind == "dmy":
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                d, mo, y = (int(m.group(1)),
                            _MONTHS[m.group(2).lower()], int(m.group(3)))
            return _dt.date(y, mo, d).isoformat()
        except (ValueError, KeyError):
            continue
    return None
