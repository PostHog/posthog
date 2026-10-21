"""Which top-level channel posts, written without tagging the app, are worth a classifier call."""

import re
from typing import Any

UNTAGGED_QUESTION_MIN_CHARS = 12
UNTAGGED_QUESTION_MAX_CHARS = 2000
UNTAGGED_QUESTION_MIN_WORDS = 3
# A message for another bot or a typed Slack command, such as "/remind" or "!deploy".
_COMMAND_PATTERN = re.compile(r"^[/!]\S")
_POSTHOG_PATTERN = re.compile(r"\bpost\s?hog\b", re.IGNORECASE)
# Slack wraps links, channels and tags in angle brackets. A PostHog URL alone does not name PostHog.
_SLACK_MARKUP_PATTERN = re.compile(r"<[^>]*>")


def mentions_posthog(text: str) -> bool:
    """Whether the words of a post name PostHog, outside links."""
    return bool(_POSTHOG_PATTERN.search(_SLACK_MARKUP_PATTERN.sub(" ", text)))


def is_untagged_question_candidate(event: dict[str, Any]) -> bool:
    """Whether a top-level post nobody tagged the app in could be a question for PostHog.

    Text-only checks, because every top-level post in every channel the app is in comes through
    here. The post must name PostHog, so the classifier sees what people ask about PostHog in any
    phrasing, with or without a ``?``. The classifier makes the real decision later.
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
    if _COMMAND_PATTERN.match(text):
        return False
    return mentions_posthog(text)
