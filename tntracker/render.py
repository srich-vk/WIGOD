"""Render the static timeline site from the DB.

Emits site/data.json (consumed by the page's JS) and copies the template
index.html into site/. Static-by-design (decision #2): no server needed.

Usage: python -m tntracker.render
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import config, db

_TEMPLATE = Path(__file__).resolve().parent / "templates" / "index.html"


def render() -> None:
    config.ensure_dirs()
    rows = db.summarized_rows()

    entries = [
        {
            "go_key": r["go_key"],
            "date": r["go_date"],
            "department": r["dept_name"],
            "go_number": r["go_number"],
            "go_type": r["go_type"],
            "lang": r["source_lang"],
            "summary": r["summary"],
            "policy_area": r["policy_area"],
            "districts": r["districts"],
            "confidence": r["confidence"],
            "pdf_url": r["pdf_url"],
            "snippet": r["source_snippet"],
        }
        for r in rows
    ]

    payload = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "count": len(entries),
        "departments": sorted({e["department"] for e in entries}),
        "policy_areas": sorted({e["policy_area"] for e in entries if e["policy_area"]}),
        "entries": entries,
    }

    out_json = config.SITE_DIR / "data.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    shutil.copyfile(_TEMPLATE, config.SITE_DIR / "index.html")

    print(f"[render] {len(entries)} entries -> {out_json}")
    print(f"[render] open: file://{(config.SITE_DIR / 'index.html').resolve()}")


if __name__ == "__main__":
    render()
