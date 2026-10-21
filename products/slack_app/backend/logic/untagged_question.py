"""Which top-level channel posts, written without tagging the app, are worth a classifier call."""

import re
from typing import Any

UNTAGGED_QUESTION_MIN_CHARS = 12
UNTAGGED_QUESTION_MAX_CHARS = 2000
UNTAGGED_QUESTION_MIN_WORDS = 3
_QUESTION_OPENER_PATTERN = re.compile(
    r"^(how|what|why|when|where|which|who|whose|is|are|was|were|can|could|does|do|did|should|would|will|has|have|any|anyone|anybody)\b",
    re.IGNORECASE,
)
# A request for information that has no question form, such as "need signups by country".
_REQUEST_OPENER_PATTERN = re.compile(
    r"^(please|pls|need|show|find|get|give|tell|list|compare|check|pull|help|looking for|wondering|curious"
    r"|i need|we need|i want|we want|i'd like|i would like|i'm looking|im looking|i am looking|i wonder|quick question)\b",
    re.IGNORECASE,
)
_REQUEST_PHRASE_PATTERN = re.compile(
    r"\b(any idea|anyone know|anybody know|looking for|wondering|curious (?:about|if|whether|how|why|what)"
    r"|need to (?:know|see|find|check|understand)|help me|can someone|could someone)\b",
    re.IGNORECASE,
)


def has_question_signal(text: str) -> bool:
    """Whether a post looks like a question by its words alone: a ``?`` or a question word first."""
    text = text.strip()
    return "?" in text or bool(_QUESTION_OPENER_PATTERN.match(text))


def has_request_signal(text: str) -> bool:
    """Whether a post asks for something: a question signal, a request word first, or a request phrase."""
    text = text.strip()
    return (
        has_question_signal(text)
        or bool(_REQUEST_OPENER_PATTERN.match(text))
        or bool(_REQUEST_PHRASE_PATTERN.search(text))
    )


def is_untagged_question_candidate(event: dict[str, Any]) -> bool:
    """Whether a top-level post nobody tagged the app in could be a question for PostHog.

    Text-only checks, because every top-level post in every channel the app is in comes through
    here. The classifier makes the real decision later. The word check also passes requests
    without a ``?`` or a question word, so phrasings like "need signups by country" reach it.
    """
    # ``group`` is a private channel. Group DMs (``mpim``) are private conversations between people.
    if event.get("channel_type") not in ("channel", "group"):
        return False
    text = (event.get("text") or "").strip()
    if not UNTAGGED_QUESTION_MIN_CHARS <= len(text) <= UNTAGGED_QUESTION_MAX_CHARS:
        return False
    # A tag of the app arrives as its own ``app_mention``. A tag of anyone else, a user group or
    # the whole channel addresses them, not PostHog.
    if "<@" in text or "<!" in text:
        return False
    if len(text.split()) < UNTAGGED_QUESTION_MIN_WORDS:
        return False
    return has_request_signal(text)
