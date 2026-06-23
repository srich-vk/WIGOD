"""Daily pipeline orchestrator.

Stages: scrape metadata -> fetch PDF -> extract text -> summarize -> store.
Idempotent: each GO is keyed and only outstanding work is performed, so a
re-run after a crash resumes cleanly and never re-pays for completed summaries.

Usage:
    python -m tntracker.pipeline --year 2026
    python -m tntracker.pipeline --year 2026 --dept 27 --max-gos 5
    python -m tntracker.pipeline --year 2026 --no-summarize   # scrape/fetch only
"""
from __future__ import annotations

import argparse
import json
import time

from . import config, db, extract, fetch, scrape, summarize


def run(year: int, dept_ids=None, max_gos: int | None = None,
        do_summarize: bool = True) -> None:
    db.init_db()

    if do_summarize and not summarize.health_check():
        print(f"!! Ollama not reachable or model '{config.OLLAMA_MODEL}' missing.")
        print("   Start it / pull the model, or run with --no-summarize.")
        do_summarize = False

    # --- Stage 1: scrape listings and record new GOs (the ledger) ----------
    print(f"[scrape] year={year}")
    scraped = scrape.scrape_all(year, dept_ids)
    new = sum(1 for g in scraped if db.insert_metadata(g))
    print(f"[scrape] {len(scraped)} listed, {new} new since last run")

    # --- Stage 2-4: process everything not yet summarized ------------------
    pending = db.rows_with_status(db.STATUS_NEW, db.STATUS_FETCHED,
                                  db.STATUS_EXTRACTED, db.STATUS_ERROR)
    if max_gos:
        pending = pending[:max_gos]
    print(f"[process] {len(pending)} GOs to work through")

    for row in pending:
        key = row["go_key"]
        try:
            _process_one(dict(row), do_summarize)
        except Exception as e:  # never let one GO abort the batch
            db.update(key, status=db.STATUS_ERROR, error=str(e)[:500])
            print(f"  {key}: ERROR {e}")
        time.sleep(config.RATE_LIMIT_SECONDS)

    print("[done]", db.counts_by_status())


def _process_one(row: dict, do_summarize: bool) -> None:
    key = row["go_key"]

    # Fetch (skip if already cached).
    if row["status"] == db.STATUS_NEW or not row.get("pdf_path"):
        info = fetch.fetch_pdf(key, row["pdf_url"])
        row.update(info)
        db.update(key, status=db.STATUS_FETCHED, **info)

    # Extract.
    if row["status"] in (db.STATUS_NEW, db.STATUS_FETCHED, db.STATUS_ERROR):
        ext = extract.extract_text(row["pdf_path"], row.get("year"))
        if not ext["is_text"]:
            db.update(key, status=db.STATUS_NO_TEXT,
                      raw_text_len=ext["raw_text_len"],
                      error="no extractable text (scanned?) — needs OCR")
            print(f"  {key}: no text, flagged for OCR")
            return
        db.update(key, status=db.STATUS_EXTRACTED,
                  raw_text_len=ext["raw_text_len"], go_date=ext["go_date"],
                  source_snippet=ext["source_snippet"])
        row["_text"] = ext["text"]

    if not do_summarize:
        return

    # Summarize.
    text = row.get("_text")
    if text is None:  # resuming an already-extracted row: re-read the PDF text
        text = extract.extract_text(row["pdf_path"], row.get("year"))["text"]
    result = summarize.summarize(text, row["dept_name"], row["go_number"],
                                 row["year"])
    db.update(
        key, status=db.STATUS_SUMMARIZED,
        summary=result["summary"], policy_area=result["policy_area"],
        districts=json.dumps(result["districts"]),
        confidence=result["confidence"],
        summarized_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    print(f"  {key}: {result['summary'][:80]}")


def _parse_args():
    p = argparse.ArgumentParser(description="TN Government Action Tracker pipeline")
    p.add_argument("--year", type=int, default=config.DEFAULT_YEAR)
    p.add_argument("--dept", type=int, action="append",
                   help="limit to dept id(s); repeatable")
    p.add_argument("--max-gos", type=int, default=None,
                   help="cap GOs processed this run (useful for testing)")
    p.add_argument("--no-summarize", action="store_true",
                   help="scrape + fetch + extract only, skip the LLM")
    return p.parse_args()


if __name__ == "__main__":
    a = _parse_args()
    run(a.year, dept_ids=a.dept, max_gos=a.max_gos,
        do_summarize=not a.no_summarize)
