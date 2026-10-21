"""Which top-level channel posts, written without tagging the app, are worth a classifier call."""

import re
from typing import Any

UNTAGGED_QUESTION_MIN_CHARS = 12
UNTAGGED_QUESTION_MAX_CHARS = 2000
_QUESTION_OPENER_PATTERN = re.compile(
    r"^(how|what|why|when|where|which|who|whose|is|are|was|were|can|could|does|do|did|should|would|will|has|have|any|anyone|anybody)\b",
    re.IGNORECASE,
)


def is_untagged_question_candidate(event: dict[str, Any]) -> bool:
    """Whether a top-level post nobody tagged the app in could be a question for PostHog.

    Text-only checks, because every top-level post in every channel the app is in comes through
    here. The classifier makes the real decision later, on the few posts that pass.
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
    return "?" in text or bool(_QUESTION_OPENER_PATTERN.match(text))
