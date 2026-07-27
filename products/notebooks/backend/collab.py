"""
prosemirror-collab step buffering for rich (v1) notebooks.

Steps are appended to the shared versioned content stream — see `collab_stream.py` for
the transport and `markdown_collab.py` for the markdown-notebook update events that
share the same stream.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

import structlog

from posthog import redis as redis_module

from products.notebooks.backend.collab_stream import (
    APPEND_ENTRIES_LUA,
    DATA_KEY,
    STREAM_KEY_PATTERN,
    STREAM_MAX_LENGTH,
    STREAM_TTL_SECONDS,
)

logger = structlog.get_logger(__name__)


@dataclass
class StepEntry:
    step: dict
    client_id: str


@dataclass
class SubmitResult:
    # "accepted" - steps appended; `version` is the new top
    # "conflict" - caller is behind; `version` is the current top, `steps_since` is the missed range
    # "stale"    - missed range was trimmed (MAXLEN/TTL) or the stream was lost and the client's
    #              baseline no longer matches Postgres; caller must reload from Postgres
    status: Literal["accepted", "conflict", "stale"]
    version: int
    steps_since: list[StepEntry] | None = None


def submit_steps(
    team_id: int,
    notebook_id: str,
    client_id: str,
    steps_json: list[dict],
    last_seen_version: int,
    *,
    last_saved_version: int,
    user_id: int | None = None,
    user_name: str | None = None,
    cursor_head: int | None = None,
) -> SubmitResult:
    client = redis_module.get_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)

    # Presence (author + cursor) is constant for the whole batch — build once, spread per step.
    presence: dict[str, Any] = {
        k: v for k, v in (("user_id", user_id), ("user_name", user_name), ("cursor_head", cursor_head)) if v is not None
    }
    # Version isn't in the payload — the stream id (N-0) IS the version, and SSE delivers it as `id:`.
    serialized = [json.dumps({"step": step, "client_id": client_id, **presence}) for step in steps_json]

    script = client.register_script(APPEND_ENTRIES_LUA)
    accepted, version = script(
        keys=[stream_key],
        args=[last_seen_version, last_saved_version, STREAM_TTL_SECONDS, STREAM_MAX_LENGTH, *serialized],
    )

    if accepted == 1:
        return SubmitResult(status="accepted", version=version)
    if accepted == 2:
        return SubmitResult(status="stale", version=version)

    return _fetch_missed_steps(stream_key, last_seen_version=last_seen_version, current_stream_version=version)


def _fetch_missed_steps(stream_key: str, *, last_seen_version: int, current_stream_version: int) -> SubmitResult:
    # Client is somehow ahead of the stream — no missed range we could send.
    # The only safe response is "reload the notebook".
    if current_stream_version < last_seen_version:
        return SubmitResult(status="stale", version=current_stream_version)

    client = redis_module.get_client()
    raw = client.xrange(stream_key, min=f"({last_seen_version}-0", max=f"{current_stream_version}-0")

    missed_steps: list[StepEntry] = []
    for _stream_id, fields in raw:
        data = json.loads(fields[DATA_KEY])
        if "step" not in data or "client_id" not in data:
            continue
        missed_steps.append(StepEntry(step=data["step"], client_id=data["client_id"]))

    # MAXLEN/TTL trimmed part of the gap - incomplete rebase set, reload from Postgres
    gap_size = current_stream_version - last_seen_version
    if len(missed_steps) < gap_size:
        return SubmitResult(status="stale", version=current_stream_version)

    return SubmitResult(status="conflict", version=current_stream_version, steps_since=missed_steps)
