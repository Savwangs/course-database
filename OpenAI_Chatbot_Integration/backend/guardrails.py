"""
Input guardrails for the DVC Course Assistant.

Runs before the LLM: profanity, PII, prompt injection, language, off-topic.
Each checker returns (reason_code, user_message) or (None, None) if passed.
"""

import re
from typing import Tuple

# ---------------------------------------------------------------------------
#  Profanity (small blocklist; extend or use better-profanity in production)
# ---------------------------------------------------------------------------

_PROFANITY_BLOCKLIST = frozenset({
    "damn", "hell", "crap", "shit", "ass", "bastard", "bitch", "fuck",
    "fucking", "wtf", "stfu", "dumbass", "bullshit", "piss", "pissed",
})


def check_profanity(query: str) -> Tuple[str | None, str | None]:
    """Return (reason_code, message) if profanity detected, else (None, None)."""
    if not query or not query.strip():
        return None, None
    lower = query.lower()
    words = re.findall(r"[a-z]+", lower)
    for w in words:
        if w in _PROFANITY_BLOCKLIST:
            return "PROFANITY_DETECTED", "Please rephrase without offensive language."
    return None, None


# ---------------------------------------------------------------------------
#  PII detection (SSN, obvious password phrasing)
# ---------------------------------------------------------------------------

_SSN_PATTERN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
_PASSWORD_PHRASES = re.compile(
    r"\b(password|passwd|pwd)\s*[=:]\s*\S+|\bmy\s+password\s+is\s+\S+",
    re.IGNORECASE,
)


def check_pii(query: str) -> Tuple[str | None, str | None]:
    """Return (reason_code, message) if PII detected, else (None, None)."""
    if not query or not query.strip():
        return None, None
    if _SSN_PATTERN.search(query):
        return "PII_DETECTED", "Please do not share SSN or other sensitive personal information. I can only help with DVC courses and transfer info."
    if _PASSWORD_PHRASES.search(query):
        return "PII_DETECTED", "Please do not share passwords or secrets. I can only help with DVC courses and transfer info."
    return None, None


# ---------------------------------------------------------------------------
#  Prompt injection (phrase blocklist)
# ---------------------------------------------------------------------------

_INJECTION_PHRASES = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard previous",
    "forget previous",
    "new instructions",
    "you are now",
    "act as",
    "pretend you are",
    "from now on you",
    "override",
    "bypass",
    "jailbreak",
)


def check_prompt_injection(query: str) -> Tuple[str | None, str | None]:
    """Return (reason_code, message) if injection suspected, else (None, None)."""
    if not query or not query.strip():
        return None, None
    lower = query.lower()
    for phrase in _INJECTION_PHRASES:
        if phrase in lower:
            return "PROMPT_INJECTION_SUSPECTED", "I can only help with DVC courses and transfer information. Please ask a course- or transfer-related question."
    return None, None


# ---------------------------------------------------------------------------
#  Language detection (English-only)
# ---------------------------------------------------------------------------

def check_language(query: str) -> Tuple[str | None, str | None]:
    """Return (reason_code, message) if non-English detected, else (None, None)."""
    if not query or not query.strip():
        return None, None
    try:
        import langdetect
        lang = langdetect.detect(query)
        if lang != "en":
            return "NON_ENGLISH", "I can only help in English. Please ask your question in English."
    except (ImportError, Exception):
        # Fail open: if langdetect not installed or detection fails, allow the query
        pass
    return None, None


# ---------------------------------------------------------------------------
#  Off-topic (keyword-based: politics, recipes, general trivia)
# ---------------------------------------------------------------------------

_OFF_TOPIC_KEYWORDS = frozenset({
    "recipe", "recipes", "cook", "baking", "chocolate cake", "how to cook",
    "election", "president", "vote", "political", "republican", "democrat",
    "trivia", "quiz", "random fact", "medical advice", "legal advice",
    "financial advice", "invest", "stock market", "tax advice", "lawyer",
    "doctor", "diagnosis", "therapy", "relationship advice", "breakup",
})


def check_off_topic(query: str) -> Tuple[str | None, str | None]:
    """Return (reason_code, message) if clearly off-topic, else (None, None)."""
    if not query or not query.strip():
        return None, None
    lower = query.lower()
    for kw in _OFF_TOPIC_KEYWORDS:
        if kw in lower:
            return "OFF_TOPIC", "I can only help with DVC courses and transfer info. Please ask about courses, sections, prerequisites, or UC transfer."
    return None, None
