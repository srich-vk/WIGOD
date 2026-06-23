"""Central configuration for the TN Government Action Tracker pilot.

All tunable knobs live here: source URLs, the department map, model choice,
filesystem paths, and politeness settings for scraping.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

# --- Source site -----------------------------------------------------------
BASE_URL = "https://www.tn.gov.in"
DEPT_LIST_URL = f"{BASE_URL}/godept_list.php"
# go.php?dep_id=<base64>&year=<base64> returns the GO listing for one dept/year.
GO_PAGE_URL = f"{BASE_URL}/go.php"

# Request politeness / resilience.
USER_AGENT = "tn-action-tracker/0.1 (pilot; contact: sricharanv3@gmail.com)"
REQUEST_TIMEOUT = 30          # seconds per HTTP request
REQUEST_RETRIES = 3
RATE_LIMIT_SECONDS = 1.5      # delay between requests to the gov server

# --- Department map --------------------------------------------------------
# Scraped from godept_list.php. Keys are the numeric dep_id the site uses;
# the page encodes them as base64 in the query string (see b64()).
DEPARTMENTS: dict[int, str] = {
    1: "Adi Dravidar and Tribal Welfare Department",
    2: "Agriculture - Farmers Welfare Department",
    3: "Animal Husbandry, Dairying, Fisheries and Fishermen Welfare Department",
    4: "BC, MBC & Minorities Welfare Department",
    5: "Co-operation, Food and Consumer Protection Department",
    6: "Commercial Taxes and Registration Department",
    7: "Energy Department",
    8: "Environment, Climate Change and Forests Department",
    9: "Finance Department",
    10: "Handlooms, Handicrafts, Textiles and Khadi Department",
    11: "Health and Family Welfare Department",
    12: "Higher Education Department",
    13: "Highways and Minor Ports Department",
    14: "Home, Prohibition and Excise Department",
    15: "Housing and Urban Development Department",
    16: "Industries, Investment Promotion & Commerce Department",
    17: "Information Technology and Digital Services Department",
    18: "Labour Welfare and Skill Development Department",
    19: "Law Department",
    21: "Municipal Administration and Water Supply Department",
    22: "Human Resources Management Department",
    23: "Planning, Development and Special Initiatives Department",
    24: "Public Department",
    26: "Revenue and Disaster Management Department",
    27: "Rural Development and Panchayat Raj Department",
    28: "School Education Department",
    29: "Micro, Small and Medium Enterprises Department",
    30: "Social Welfare and Women Empowerment Department",
    31: "Tamil Dev. and Information Department",
    32: "Tourism, Culture and Religious Endowments Department",
    33: "Transport Department",
    34: "Youth Welfare and Sports Development Department",
    35: "Welfare of Differently Abled Persons",
    38: "Public (Elections) Department",
    41: "Special Programme Implementation",
    42: "Public Works Department",
    44: "Water Resources Department",
    45: "Natural Resources Department",
}

# Noise control: departments whose output is almost entirely admin/HR churn.
# The brief asks us to skip transfers/name-changes; HR Management is pure noise.
SKIP_DEPARTMENTS: set[int] = {22}

# GO type codes seen in filenames: ms=Miscellaneous(policy), d=Determination,
# rt=Routine (often transfers/admin). Leave empty to keep everything and let
# the summarizer + policy_area tag handle filtering; add "rt" to drop routine.
SKIP_GO_TYPES: set[str] = set()

# --- LLM provider ----------------------------------------------------------
# "groq"  -> hosted Groq API (fast, no local GPU needed)
# "ollama" -> local Ollama server (offline, private)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq").lower()

# --- LLM: Groq (hosted, OpenAI-compatible) ---------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3-32b"   # strong Tamil; reasoning disabled for clean JSON
GROQ_TIMEOUT = 60
GROQ_MAX_RETRIES = 8     # back off on 429 rate limits
# 8b free tier is 6k tokens/MIN. With ~1.1k tokens/request (after MAX_TEXT_CHARS)
# ~13s/request (~4-5/min) keeps us safely under that per-minute cap.
GROQ_MIN_INTERVAL = 13.0


def groq_api_key() -> str:
    """Resolve the Groq key: env GROQ_API_KEY first, then a local groq.txt file.

    groq.txt is gitignored; prefer the env var in real deployments.
    """
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    key_file = PROJECT_ROOT / "groq.txt"
    if key_file.exists():
        return key_file.read_text().strip()
    return ""


# --- LLM: local Ollama -----------------------------------------------------
# Host is overridable via OLLAMA_HOST (e.g. "127.0.0.1:11500") so you can point
# at a user-level GPU server without touching code.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "localhost:11434")
OLLAMA_URL = f"http://{OLLAMA_HOST}/api/chat"
OLLAMA_MODEL = "qwen2.5:7b"   # chosen for Tamil+English quality on 4GB VRAM
OLLAMA_TIMEOUT = 300          # generous: 7b spills to CPU on a 3050 laptop
OLLAMA_NUM_CTX = 8192
# Cap how much PDF text we feed the model (chars). A GO's operative content is
# at the top, so this stays small to keep us within Groq's per-minute token
# budget (and inference fast). Raise it if summaries miss later-page details.
MAX_TEXT_CHARS = 3000

# --- OCR (scanned GOs) -----------------------------------------------------
# Most TN GOs are scanned image PDFs, so OCR is the primary text source.
# We shell out to the installed `pdftoppm` (poppler) and `tesseract` CLIs.
OCR_LANG = "tam+eng"   # auto-falls back to "eng" if Tamil data isn't installed
OCR_DPI = 300          # 300 is a good accuracy/speed balance for gov scans
OCR_MAX_PAGES = 6      # OCR only the first N pages (GO body is up front)
OCR_MIN_CHARS = 80     # below this after OCR, treat as truly unreadable

# --- Filesystem paths ------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PDF_DIR = DATA_DIR / "pdfs"          # cached source PDFs (source of truth)
DB_PATH = DATA_DIR / "tracker.db"
SITE_DIR = PROJECT_ROOT / "site"     # generated static timeline

DEFAULT_YEAR = 2026


def b64(value) -> str:
    """Encode an int/str the way tn.gov.in expects its query params."""
    return base64.b64encode(str(value).encode()).decode()


def ensure_dirs() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
