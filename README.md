# WIGOD — What Is my GOvernment Doing?

A day-by-day timeline of what the Tamil Nadu state government actually did —
built entirely from public **Government Orders (GOs)** on `tn.gov.in`. No
commentary, no opinion: one plain-English line per order, tagged by department,
policy area, and district, with a link back to the source PDF.

Summarization runs **locally** on an Ollama LLM — no external API, no per-token
cost, nothing leaves your machine.

---

## How it works

```
scrape  →  fetch  →  extract  →  summarize  →  store  →  render
go.php     PDF        pdfplumber   Ollama        SQLite    static site
listings   (cached)   text+date    (qwen2.5:7b)  ledger    timeline
```

1. **scrape** — `go.php?dep_id=&year=` is read per department; GO PDF links + GO
   numbers are parsed out (language and GO type come from the filename).
2. **fetch** — each GO PDF is downloaded once and cached under `data/pdfs/`
   (kept permanently as the source of truth, with a sha256).
3. **extract** — text is pulled with `pdfplumber` when a GO is digital; **most
   TN GOs are scanned images**, so it falls back to OCR (`pdftoppm` + `tesseract`,
   Tamil+English). The issue date is regex-parsed from the resulting text.
4. **summarize** — a local Ollama model produces a structured JSON summary
   (summary line, policy area, districts, confidence). Tamil GOs are summarized
   into English. The prompt forbids commentary and requires grounding in the text.
5. **store** — everything lands in SQLite (`data/tracker.db`), keyed by the GO's
   unique filename stem. Re-runs only process new/outstanding GOs (idempotent).
6. **render** — a static `site/index.html` + `data.json` filterable timeline.

### Design decisions (locked for the pilot)
- **Daily batch**, not on-demand. **Static site**, not a live webapp.
- **Don't language-filter** — translate-summarize Tamil into English instead.
- **Per-GO dedup ledger** via the filename stem; cached PDFs are source of truth.
- **Source excerpt stored** alongside each summary for auditability.
- Related GOs are stored independently and grouped at render time by tag.
- HR Management department is skipped as pure admin noise.

---

## Setup

Requires Python 3.10+ and [Ollama](https://ollama.com).

```bash
# 1. Python deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. OCR tools (most GOs are scanned images)
#    Arch: sudo pacman -S tesseract tesseract-data-eng tesseract-data-tam poppler
#    Tamil data (tesseract-data-tam) is required for Tamil-only GOs.

# 3. Ollama + the model (one-time; ~4.7 GB download)
#    Arch: yay -S ollama   (or: curl -fsSL https://ollama.com/install.sh | sh)
ollama serve &            # start the local server (if not already running)
ollama pull qwen2.5:7b
```

> On a 4 GB GPU (e.g. RTX 3050 Laptop) qwen2.5:7b partly runs on CPU — slower
> but fine for an unattended daily batch. For faster/rougher runs, set
> `OLLAMA_MODEL = "qwen2.5:3b"` in `tntracker/config.py`.

---

## Usage

```bash
# Full daily run for a year
python -m tntracker.pipeline --year 2026

# Test on a single department, a few GOs
python -m tntracker.pipeline --year 2026 --dept 27 --max-gos 5

# Scrape + fetch + extract only (no LLM) — handy without Ollama running
python -m tntracker.pipeline --year 2026 --no-summarize

# Build the static timeline from the DB
python -m tntracker.render
# then open the printed file:// URL (site/index.html)
```

Department IDs are listed in `tntracker/config.py` (`DEPARTMENTS`).

### LLM provider
Summarization runs through either hosted **Groq** (default) or local **Ollama**,
selected by `LLM_PROVIDER` (`groq` | `ollama`) in `tntracker/config.py` / env.
- Groq: set `GROQ_API_KEY` (env var, or a gitignored `groq.txt` for local use);
  model is `GROQ_MODEL` (default `qwen/qwen3-32b`).
- Ollama: set `OLLAMA_HOST`; model is `OLLAMA_MODEL` (needs a local GPU server).

### Daily automation (GitHub Actions → GitHub Pages)
The repo runs itself in the cloud — no local machine needed. `.github/workflows/daily.yml`
scrapes new GOs, summarizes them via Groq, renders the timeline into `docs/`, and
commits `docs/` + `data/tracker.db` back to `main`. GitHub Pages serves the result
from `main` `/docs` at `https://srich-vk.github.io/WIGOD/`.

The pipeline is idempotent: the committed `data/tracker.db` ledger lets each run
skip GOs already summarized, so a run only processes the handful of new orders
(well within Groq's free tier). The ledger **must** stay committed — that's why
it is no longer gitignored.

> ⚠️ **The daily schedule is currently disabled (manual `workflow_dispatch` only).**
> GitHub-hosted runners (US/EU Azure IPs) **cannot reach `tn.gov.in`** — it silently
> drops non-Indian / datacenter traffic, so the scrape times out (verified: HTTP 000,
> no TCP connect). The pipeline and Pages publishing work; only the *scrape host* is
> the open problem. To automate, run this from a machine with Indian network access —
> a **self-hosted GitHub runner** (`runs-on: self-hosted`) or an **India-region VPS**
> on cron — then re-enable the `schedule:` block in `.github/workflows/daily.yml`.
> Until then, the site is refreshed by running the pipeline locally and pushing.

**One-time setup (GitHub UI), already done for this repo:**
1. Repo secret `GROQ_API_KEY` (Settings → Secrets and variables → Actions).
2. Pages: Settings → Pages → Source = *Deploy from a branch* → `main` `/docs`.

To run the daily job on your own machine instead, use cron:
```bash
# crontab -e  — run at 06:30 daily, then regenerate the site
30 6 * * * cd /home/srich-vk/Documents/WIMAD && .venv/bin/python -m tntracker.pipeline --year 2026 && .venv/bin/python -m tntracker.render
```

---

## Project layout

```
tntracker/
  config.py        URLs, department map, model, paths, politeness knobs
  scrape.py        parse go.php GO listings
  fetch.py         download + cache + hash PDFs
  extract.py       embedded-text extraction, OCR fallback, date parsing
  ocr.py           pdftoppm + tesseract OCR (Tamil+English) for scanned GOs
  summarize.py     structured summarization via Groq or local Ollama
  db.py            SQLite schema + dedup ledger
  pipeline.py      orchestrates the daily run (idempotent, resumable)
  render.py        emits the static site
  templates/index.html   filterable timeline UI
data/              tracker.db (committed ledger) + cached pdfs/ (gitignored)
site/              generated static site for local dev (gitignored)
docs/              generated static site published to GitHub Pages (committed by CI)
.github/workflows/daily.yml   scheduled cloud run (scrape → summarize → publish)
```

## Known limits / next steps
- Press releases are published as **images** on tn.gov.in, so they'd need OCR —
  deferred (this pilot is GO-only).
- GO dates depend on regex-matching the PDF text; unmatched dates sort under
  "Date unknown".
- The "GOs of public interest" filter can be layered on top of the per-department
  scrape to further cut volume.
