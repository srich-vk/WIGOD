"""OCR for scanned GO PDFs via the poppler + tesseract CLIs.

Most TN GOs are scanned images, so this is the main text source, not a rare
fallback. We render pages to PNG with `pdftoppm` and OCR them with `tesseract`
in Tamil+English. No extra Python deps — just the system binaries.
"""
from __future__ import annotations

import functools
import subprocess
import tempfile
from pathlib import Path

from . import config


class OCRUnavailable(RuntimeError):
    """Raised when the required CLI tools aren't installed."""


@functools.lru_cache(maxsize=1)
def available_langs() -> frozenset[str]:
    try:
        out = subprocess.run(["tesseract", "--list-langs"],
                             capture_output=True, text=True, check=True)
        return frozenset(out.stdout.split()[1:])  # first line is a header
    except (FileNotFoundError, subprocess.CalledProcessError):
        return frozenset()


@functools.lru_cache(maxsize=1)
def effective_lang() -> str:
    """Use configured langs that are actually installed; fall back to eng."""
    have = available_langs()
    wanted = [l for l in config.OCR_LANG.split("+") if l in have]
    if not wanted:
        if "eng" in have:
            print("  !! Tamil tesseract data not installed; OCR using eng only "
                  "(install 'tesseract-data-tam' for Tamil GOs).")
            return "eng"
        raise OCRUnavailable("no usable tesseract language data found")
    if "tam" not in wanted and "tam" in config.OCR_LANG.split("+"):
        print("  !! 'tam' not installed; OCR using:", "+".join(wanted))
    return "+".join(wanted)


def tools_present() -> bool:
    def _ok(cmd):
        try:
            subprocess.run([cmd, "-h" if cmd == "pdftoppm" else "--version"],
                           capture_output=True, check=False)
            return True
        except FileNotFoundError:
            return False
    return _ok("pdftoppm") and _ok("tesseract") and bool(available_langs())


def ocr_pdf(pdf_path: str) -> str:
    """Render the first OCR_MAX_PAGES pages and OCR them. Returns joined text."""
    if not tools_present():
        raise OCRUnavailable("pdftoppm/tesseract not available")
    lang = effective_lang()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # pdftoppm -> tmp/pg-1.png, pg-2.png, ...
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(config.OCR_DPI),
             "-l", str(config.OCR_MAX_PAGES), pdf_path, str(tmp_path / "pg")],
            capture_output=True, check=True,
        )
        texts = []
        for png in sorted(tmp_path.glob("pg*.png")):
            res = subprocess.run(
                ["tesseract", str(png), "stdout", "-l", lang],
                capture_output=True, text=True, check=True,
            )
            texts.append(res.stdout)
    return "\n".join(texts).strip()
