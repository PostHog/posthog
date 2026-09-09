"""
Ephemeral caret/presence broadcasting for notebook collaboration.

Presence lives in its own Redis stream per notebook: the content stream's ids ARE
document versions (a CAS invariant), so presence can't share it. Ids here are
auto-generated and entries are short-lived — receivers always render the latest
ping per client and TTL-prune the rest, so a dropped event self-heals on the next one.
"""

from typing import Any

from posthog.collab_stream import (
    PRESENCE_EVENT_TYPE,
    PRESENCE_TTL_SECONDS as PRESENCE_TTL_SECONDS,
    publish_presence_entry,
)

PRESENCE_STREAM_KEY_PATTERN = "notebook:collab:{{{team_id}:{notebook_id}}}:presence"


def publish_presence(
    team_id: int,
    notebook_id: str,
    *,
    client_id: str,
    user_id: int,
    user_name: str,
    version: int,
    cursor: dict[str, Any],
) -> None:
    """Fire-and-forget caret broadcast. Lossy by design: receivers always render the latest
    ping per client and TTL-prune the rest, so a dropped event self-heals on the next one."""
    stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)
    payload = {
        "type": PRESENCE_EVENT_TYPE,
        "client_id": client_id,
        "user_id": user_id,
        "user_name": user_name,
        "version": version,
        "cursor": cursor,
    }

    publish_presence_entry(stream_key, payload, log_name="notebook_collab")
