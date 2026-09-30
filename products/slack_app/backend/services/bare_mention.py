import re
from typing import Any

from django.core.cache import cache

from products.slack_app.backend.services.slack_messages import extract_message_text

AWAITED_REQUEST_TTL_SECONDS = 60 * 60

BARE_MENTION_REPLY = (
    "Hi! What would you like to know? Reply in this thread with your question. For example:\n"
    "• How many people signed up last week?\n"
    "• Were there any new errors after yesterday's deploy?\n"
    "• Which feature flags have not been used in 30 days?\n"
    "If you reply more than an hour from now, mention me in the reply."
)

_USER_TAG = re.compile(r"<@[^>]+>")


def is_bare_mention(event: dict[str, Any]) -> bool:
    thread_ts = event.get("thread_ts")
    # Inside a thread, the earlier messages are the request.
    if isinstance(thread_ts, str) and thread_ts != event.get("ts"):
        return False
    if event.get("files"):
        return False
    return not _USER_TAG.sub("", extract_message_text(event)).strip()


def thread_is_recent(thread_ts: str | None, *, now: float) -> bool:
    try:
        return thread_ts is not None and now - float(thread_ts) <= AWAITED_REQUEST_TTL_SECONDS
    except ValueError:
        return False


def _key(slack_team_id: str, channel: str, thread_ts: str) -> str:
    return f"slack_app:awaited_request:v1:{slack_team_id}:{channel}:{thread_ts}"


def await_request(slack_team_id: str, channel: str, thread_ts: str, *, slack_user_id: str) -> bool:
    """Claim the thread for the person's next message. False when the thread is already claimed."""
    return bool(cache.add(_key(slack_team_id, channel, thread_ts), slack_user_id, timeout=AWAITED_REQUEST_TTL_SECONDS))


def awaited_request_from(slack_team_id: str, channel: str | None, thread_ts: str | None, *, now: float) -> str | None:
    """The Slack user whose request this thread waits for, or None."""
    # Threaded messages arrive in high volume. The age check keeps the cache read to
    # threads that can still hold a claim.
    if channel is None or thread_ts is None or not thread_is_recent(thread_ts, now=now):
        return None
    slack_user_id = cache.get(_key(slack_team_id, channel, thread_ts))
    return slack_user_id if isinstance(slack_user_id, str) else None


def clear_awaited_request(slack_team_id: str, channel: str, thread_ts: str) -> None:
    cache.delete(_key(slack_team_id, channel, thread_ts))
