"""Summarize a GO into one plain-English line via Groq or a local Ollama model.

Provider is selected by config.LLM_PROVIDER ("groq" | "ollama").

Design constraints baked into the prompt:
  * No editorial commentary — describe only what the order does.
  * Grounded strictly in the supplied text (anti-hallucination, decision #9).
  * Summarize INTO English regardless of source language (handles Tamil GOs).
  * Structured JSON output so tagging is deterministic (decision #8).
"""
from __future__ import annotations

import json
import time

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
  "summary": one factual sentence describing what the order does. FORMAT RULES:
     - Begin with a present-tense action verb (e.g. Sanctions, Allocates,
       Approves, Amends, Creates, Releases, Constitutes, Revises, Appoints,
       Establishes, Extends).
     - Do NOT begin with "The Tamil Nadu government", "The order", "This GO",
       "It", or the department name. Start directly with the verb.
     - Include the key amount/figure and the purpose when present.
     - <= 35 words, plain English, no trailing period needed.
  "policy_area": one of {areas}
  "districts": array of TN district names explicitly mentioned (else [])
  "confidence": number 0.0-1.0 for how clearly the text states the action
"""


def summarize(text: str, dept: str, go_number: str | None, year: int) -> dict:
    """Summarize one GO. Routes to the configured provider. Raises on failure."""
    user = USER_TEMPLATE.format(
        dept=dept, go_number=go_number or "?", year=year,
        text=text[:config.MAX_TEXT_CHARS], areas=", ".join(POLICY_AREAS),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    if config.LLM_PROVIDER == "groq":
        content = _call_groq(messages)
    else:
        content = _call_ollama(messages)
    return _normalize(json.loads(content))


_last_groq_call = 0.0  # module-level throttle to stay under the per-minute cap


def _call_groq(messages: list[dict]) -> str:
    global _last_groq_call
    key = config.groq_api_key()
    if not key:
        raise RuntimeError("No Groq API key (set GROQ_API_KEY or create groq.txt)")
    # Pace requests: sleep until GROQ_MIN_INTERVAL has elapsed since the last one.
    gap = config.GROQ_MIN_INTERVAL - (time.monotonic() - _last_groq_call)
    if gap > 0:
        time.sleep(gap)
    payload = {
        "model": config.GROQ_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},  # force valid JSON
    }
    # Qwen3 is a reasoning model; disable thinking so content is just the JSON.
    if "qwen" in config.GROQ_MODEL.lower():
        payload["reasoning_effort"] = "none"
    headers = {"Authorization": f"Bearer {key}"}
    for attempt in range(config.GROQ_MAX_RETRIES):
        r = requests.post(config.GROQ_URL, json=payload, headers=headers,
                          timeout=config.GROQ_TIMEOUT)
        _last_groq_call = time.monotonic()
        if r.status_code == 429:  # rate limited — wait and retry
            wait = float(r.headers.get("retry-after", 2 ** attempt))
            time.sleep(min(wait, 30))
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("Groq rate limit: retries exhausted")


def _call_ollama(messages: list[dict]) -> str:
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",            # constrain Ollama to emit valid JSON
        "options": {"temperature": 0.1, "num_ctx": config.OLLAMA_NUM_CTX},
    }
    r = requests.post(config.OLLAMA_URL, json=payload,
                      timeout=config.OLLAMA_TIMEOUT)
    r.raise_for_status()
    return r.json()["message"]["content"]


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
    """True if the configured provider is reachable and usable."""
    if config.LLM_PROVIDER == "groq":
        return bool(config.groq_api_key())
    try:
        tags = requests.get(
            config.OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=5
        ).json()
        names = [m.get("name", "") for m in tags.get("models", [])]
        return any(config.OLLAMA_MODEL.split(":")[0] in n for n in names)
    except requests.RequestException:
        return False
