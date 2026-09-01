"""
Notebook binding for the shared collaboration transport in `posthog/collab/`.

The transport owns the stream key layout, the version-CAS Lua script, and the SSE
tailer. This module fixes the notebook namespace and keeps the notebook-shaped
names the rest of the product imports.

Two writers share the notebook content stream:

- prosemirror-collab steps for rich v1 notebooks — `collab.py`
- markdown update events for markdown notebooks — `markdown_collab.py`
"""

from collections.abc import AsyncGenerator

from posthog.collab.presence import PRESENCE_EVENT_TYPE
from posthog.collab.stream import (
    APPEND_ENTRIES_LUA as APPEND_ENTRIES_LUA,
    DATA_KEY as DATA_KEY,
    KEEPALIVE_COMMENT as KEEPALIVE_COMMENT,
    STREAM_BLOCK_MS as STREAM_BLOCK_MS,
    STREAM_LIFETIME_SECONDS as STREAM_LIFETIME_SECONDS,
    STREAM_MAX_LENGTH as STREAM_MAX_LENGTH,
    STREAM_READ_COUNT as STREAM_READ_COUNT,
    STREAM_TTL_SECONDS as STREAM_TTL_SECONDS,
    UPDATE_EVENT_TYPE as UPDATE_EVENT_TYPE,
    stream_collab_sse as _stream_collab_sse,
)

NOTEBOOK_COLLAB_NAMESPACE = "notebook"

STREAM_KEY_PATTERN = "notebook:collab:{{{team_id}:{notebook_id}}}:stream"


def stream_collab_sse(
    team_id: int,
    notebook_id: str,
    *,
    last_event_id: str | None,
) -> AsyncGenerator[bytes]:
    return _stream_collab_sse(
        NOTEBOOK_COLLAB_NAMESPACE,
        team_id,
        notebook_id,
        last_event_id=last_event_id,
        ephemeral_event_types=(PRESENCE_EVENT_TYPE,),
    )
