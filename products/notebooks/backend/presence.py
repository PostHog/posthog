"""
Ephemeral caret/presence broadcasting for notebook collaboration.

The stream and its lossy semantics live in `posthog/collab/presence.py`; this module
binds them to the notebook namespace.
"""

from typing import Any

from posthog.collab.presence import (
    PRESENCE_BACKFILL_MS as PRESENCE_BACKFILL_MS,
    PRESENCE_EVENT_TYPE as PRESENCE_EVENT_TYPE,
    PRESENCE_MAX_LENGTH as PRESENCE_MAX_LENGTH,
    PRESENCE_TTL_SECONDS as PRESENCE_TTL_SECONDS,
    presence_sse_frame as _presence_sse_frame,
    publish_presence as _publish_presence,
)

from products.notebooks.backend.collab_stream import NOTEBOOK_COLLAB_NAMESPACE

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
    _publish_presence(
        NOTEBOOK_COLLAB_NAMESPACE,
        team_id,
        notebook_id,
        client_id=client_id,
        user_id=user_id,
        user_name=user_name,
        version=version,
        cursor=cursor,
    )


def presence_sse_frame(fields: dict[bytes, bytes], *, stream_key: str, stream_id: str) -> bytes | None:
    return _presence_sse_frame(fields, namespace=NOTEBOOK_COLLAB_NAMESPACE, stream_key=stream_key, stream_id=stream_id)
