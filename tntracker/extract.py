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


def extract_text(pdf_path: str, prefer_year: int | None = None) -> dict:
    """Get text from a GO PDF: try embedded text first, then OCR.

    Returns {text, raw_text_len, go_date, source_snippet, is_text, method}.
    `method` is 'embedded', 'ocr', or 'none'.

    `prefer_year` (the GO's own year, from its filename) disambiguates when the
    body cites older orders: we prefer a date in that year over a cited one.
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
        "go_date": _find_date(text, prefer_year) if is_text else None,
        "source_snippet": text[:600],
        "is_text": is_text,
        "method": method if is_text else "none",
    }


def _find_date(text: str, prefer_year: int | None = None) -> str | None:
    """Collect every date in the GO and pick its actual issue date.

    GO bodies routinely cite older orders ("...vide G.O. dated 21.01.1992..."),
    so the first match is unreliable. We gather all candidates and prefer one in
    the GO's own year; otherwise fall back to the latest plausible (not-future)
    date, which is almost always the issue date.
    """
    candidates: list[_dt.date] = []
    today = _dt.date.today()
    for rx, kind in _DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if kind == "dmy":
                    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                else:
                    d, mo, y = (int(m.group(1)),
                                _MONTHS[m.group(2).lower()], int(m.group(3)))
                dt = _dt.date(y, mo, d)
            except (ValueError, KeyError):
                continue
            if dt <= today:  # ignore obvious garbage / future dates
                candidates.append(dt)
    if not candidates:
        return None
    if prefer_year:
        in_year = [c for c in candidates if c.year == prefer_year]
        if in_year:
            return max(in_year).isoformat()
    return max(candidates).isoformat()
    return None
