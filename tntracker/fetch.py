"""Download and cache GO PDFs.

The cached PDF is our permanent source of truth: gov links get re-pointed and
files pulled, so we keep the original and its sha256 for auditability.
"""
from __future__ import annotations

import hashlib
import time

import requests

from . import config

_PDF_MAGIC = b"%PDF"


def fetch_pdf(go_key: str, pdf_url: str) -> dict:
    """Download if not already cached. Returns {pdf_path, pdf_sha256}.

    Raises on a non-PDF / failed download so the caller can mark an error.
    """
    dest = config.PDF_DIR / f"{go_key}.pdf"

    if dest.exists() and dest.stat().st_size > 0:
        return {"pdf_path": str(dest), "pdf_sha256": _sha256(dest)}

    last_err = None
    for attempt in range(config.REQUEST_RETRIES):
        try:
            r = requests.get(
                pdf_url,
                headers={"User-Agent": config.USER_AGENT},
                timeout=config.REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            if not r.content.startswith(_PDF_MAGIC):
                raise ValueError("response is not a PDF (got HTML/redirect?)")
            dest.write_bytes(r.content)
            return {"pdf_path": str(dest), "pdf_sha256": _sha256(dest)}
        except (requests.RequestException, ValueError) as e:
            last_err = e
            time.sleep(config.RATE_LIMIT_SECONDS * (attempt + 1))
    raise RuntimeError(f"PDF fetch failed: {pdf_url} ({last_err})")


def _sha256(path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()
