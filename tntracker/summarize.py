"""Summarize a GO into one plain-English line using a local Ollama model.

Design constraints baked into the prompt:
  * No editorial commentary — describe only what the order does.
  * Grounded strictly in the supplied text (anti-hallucination, decision #9).
  * Summarize INTO English regardless of source language (handles Tamil GOs).
  * Structured JSON output so tagging is deterministic (decision #8).
"""
from __future__ import annotations

import json

import requests

from . import config

SYSTEM_PROMPT = (
    "You are a neutral government-records summarizer for Tamil Nadu Government "
    "Orders (GOs). You write factual, one-sentence summaries in plain English. "
    "You never add opinion, praise, criticism, or speculation. You only state "
    "what the order does, based strictly on the provided text. If the text is in "
    "Tamil, summarize it in English. If you cannot tell what the order does from "
    "the text, say so in the summary and set confidence low."
)

# Closed vocabulary keeps the timeline filterable instead of a tag soup.
POLICY_AREAS = [
    "agriculture", "education", "health", "welfare", "infrastructure",
    "finance", "environment", "law_and_order", "transport", "energy",
    "housing", "rural_development", "urban_development", "industry",
    "administrative", "other",
]

USER_TEMPLATE = """Summarize this Tamil Nadu Government Order.

Department: {dept}
GO: {go_number} ({year})

--- GO TEXT (may be truncated) ---
{text}
--- END TEXT ---

Return ONLY a JSON object with these keys:
  "summary": one factual sentence (<= 40 words) describing what the order does
  "policy_area": one of {areas}
  "districts": array of TN district names explicitly mentioned (else [])
  "confidence": number 0.0-1.0 for how clearly the text states the action
"""


def summarize(text: str, dept: str, go_number: str | None, year: int) -> dict:
    """Call Ollama and return a normalized dict. Raises on transport failure."""
    user = USER_TEMPLATE.format(
        dept=dept, go_number=go_number or "?", year=year,
        text=text[:config.MAX_TEXT_CHARS], areas=", ".join(POLICY_AREAS),
    )
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",            # constrain Ollama to emit valid JSON
        "options": {"temperature": 0.1, "num_ctx": config.OLLAMA_NUM_CTX},
    }
    r = requests.post(config.OLLAMA_URL, json=payload,
                      timeout=config.OLLAMA_TIMEOUT)
    r.raise_for_status()
    content = r.json()["message"]["content"]
    return _normalize(json.loads(content))


def _normalize(raw: dict) -> dict:
    area = str(raw.get("policy_area", "other")).strip().lower()
    if area not in POLICY_AREAS:
        area = "other"
    districts = raw.get("districts") or []
    if not isinstance(districts, list):
        districts = [str(districts)]
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "summary": str(raw.get("summary", "")).strip(),
        "policy_area": area,
        "districts": [str(d).strip() for d in districts if str(d).strip()],
        "confidence": conf,
    }


def health_check() -> bool:
    """True if the Ollama server is reachable and the model is present."""
    try:
        tags = requests.get(
            config.OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=5
        ).json()
        names = [m.get("name", "") for m in tags.get("models", [])]
        return any(config.OLLAMA_MODEL.split(":")[0] in n for n in names)
    except requests.RequestException:
        return False
