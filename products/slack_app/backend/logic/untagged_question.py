"""Which channel posts, written without tagging the app, are worth a classifier call."""

import re
from typing import Any

UNTAGGED_QUESTION_MIN_CHARS = 12
UNTAGGED_QUESTION_MAX_CHARS = 2000
UNTAGGED_QUESTION_MIN_WORDS = 3
# A message for another bot or a typed Slack command, such as "/remind" or "!deploy".
_COMMAND_PATTERN = re.compile(r"^[/!]\S")


def is_untagged_question_candidate(event: dict[str, Any]) -> bool:
    """Whether a top-level post nobody tagged the app in could be a question for PostHog.

    Text-only checks, because every top-level post in every channel the app is in comes through
    here. The classifier makes the real decision later.
    """
    # ``group`` is a private channel. Group DMs (``mpim``) are private conversations between people.
    if event.get("channel_type") not in ("channel", "group"):
        return False
    text = (event.get("text") or "").strip()
    if not UNTAGGED_QUESTION_MIN_CHARS <= len(text) <= UNTAGGED_QUESTION_MAX_CHARS:
        return False
    if len(text.split()) < UNTAGGED_QUESTION_MIN_WORDS:
        return False
    return not _COMMAND_PATTERN.match(text)


def is_reply(event: dict[str, Any]) -> bool:
    thread_ts = event.get("thread_ts")
    return isinstance(thread_ts, str) and thread_ts != event.get("ts")


def is_untagged_thread_question_candidate(event: dict[str, Any]) -> bool:
    """Whether a reply nobody tagged the app in, in a thread the app is not part of, could be a question for PostHog.

    Only a reply in a thread its author started qualifies. A reply in another person's thread
    is usually an answer to that person, and an offer there interrupts their conversation.
    Slack sets ``parent_user_id`` on every reply, so this check costs no Slack call.
    """
    if not is_reply(event) or not event.get("user") or event.get("parent_user_id") != event.get("user"):
        return False
    return is_untagged_question_candidate(event)
