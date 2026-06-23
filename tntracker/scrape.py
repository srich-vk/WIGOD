"""Scrape GO listings from go.php for a department/year.

The listing rows use single-quoted hrefs of the form:
    ...cms_migrated/document/GO/rd_e_ms_108_2026.pdf'>G.O.(Ms) No.108
We parse the PDF URL (the stable key) plus the human GO number, and derive
language + GO type from the filename stem.
"""
from __future__ import annotations

import re
import time

import requests

from . import config

# PDF links to actual GO documents. Captures the full URL and the filename stem.
_GO_LINK_RE = re.compile(
    r"""href=['"]([^'"]*document/GO/([^'"/]+)\.pdf)['"]""",
    re.IGNORECASE,
)
# The GO number text immediately following the link, e.g. G.O.(Ms) No.108
_GO_NUM_RE = re.compile(r"G\.?O\.?\s*\(?(Ms|D|Rt|P)\)?\s*No\.?\s*([0-9]+)", re.I)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT})
    return s


def _get(session: requests.Session, url: str, params: dict | None = None) -> str:
    last_err = None
    for attempt in range(config.REQUEST_RETRIES):
        try:
            r = session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:  # transient: back off and retry
            last_err = e
            time.sleep(config.RATE_LIMIT_SECONDS * (attempt + 1))
    raise RuntimeError(f"GET failed after retries: {url} ({last_err})")


def _parse_lang_and_type(stem: str) -> tuple[str, str | None]:
    """rd_e_ms_108_2026 -> ('en', 'ms'); xx_t_... -> ('ta', ...)."""
    parts = stem.lower().split("_")
    lang = "ta" if "t" in parts[1:3] else ("en" if "e" in parts[1:3] else "unknown")
    go_type = next((p for p in parts if p in ("ms", "d", "rt", "p")), None)
    return lang, go_type


def scrape_department(dept_id: int, year: int, session=None) -> list[dict]:
    """Return a de-duplicated list of GO metadata dicts for one dept/year."""
    session = session or _session()
    # NB: the base64 params include '=' padding which must NOT be percent-encoded
    # or the server ignores them and serves the homepage. Build the query raw.
    url = (f"{config.GO_PAGE_URL}?dep_id={config.b64(dept_id)}"
           f"&year={config.b64(year)}")
    html = _get(session, url)
    dept_name = config.DEPARTMENTS.get(dept_id, f"Department {dept_id}")

    # Walk the HTML once; pair each PDF link with the nearest GO-number text.
    results: dict[str, dict] = {}
    for m in _GO_LINK_RE.finditer(html):
        url, stem = m.group(1), m.group(2)
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = config.BASE_URL + url
        elif not url.startswith("http"):
            url = config.BASE_URL + "/" + url.lstrip("./")

        lang, go_type = _parse_lang_and_type(stem)
        if go_type and go_type in config.SKIP_GO_TYPES:
            continue

        tail = html[m.end():m.end() + 60]
        num_match = _GO_NUM_RE.search(tail)
        go_number = num_match.group(2) if num_match else None

        # Each link appears twice (once with the GO-number label, once blank).
        # Don't let the blank occurrence clobber a number we already captured.
        if stem in results and go_number is None:
            continue

        results[stem] = {
            "go_key": stem,
            "dept_id": dept_id,
            "dept_name": dept_name,
            "year": year,
            "go_number": go_number,
            "go_type": go_type,
            "source_lang": lang,
            "pdf_url": url,
        }
    return list(results.values())


def scrape_all(year: int, dept_ids=None) -> list[dict]:
    """Scrape every (non-skipped) department for the given year."""
    session = _session()
    dept_ids = dept_ids or [
        d for d in config.DEPARTMENTS if d not in config.SKIP_DEPARTMENTS
    ]
    all_gos: list[dict] = []
    for dept_id in dept_ids:
        try:
            gos = scrape_department(dept_id, year, session)
            all_gos.extend(gos)
            print(f"  dept {dept_id:>2} {config.DEPARTMENTS.get(dept_id,''):.40s}"
                  f" -> {len(gos)} GOs")
        except Exception as e:  # one bad dept shouldn't kill the run
            print(f"  dept {dept_id}: scrape error: {e}")
        time.sleep(config.RATE_LIMIT_SECONDS)
    return all_gos
