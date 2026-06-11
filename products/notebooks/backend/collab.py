"""
Redis-stream backed buffer for notebook collaboration events.

Two kinds of entries share one stream per notebook, with the stream id (`N-x`)
carrying the notebook version:

- prosemirror-collab steps (`N-0`, payload has `step`) for rich v1 notebooks
- markdown update events (`N-0` via CAS submit, `N-1` via post-save publish;
  payload has `type: "update"` and optionally a `diff`) for markdown notebooks

Markdown diffs are lists of `{start, end, text}` spans with offsets in UTF-16
code units, so JavaScript clients can apply them with plain `String.slice`.
"""

import json
import zlib
import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

logger = structlog.get_logger(__name__)

STREAM_KEY_PATTERN = "notebook:collab:{{{team_id}:{notebook_id}}}:stream"

STREAM_TTL_SECONDS = 60 * 60 * 24  # 1 day, refreshed on every XADD
STREAM_MAX_LENGTH = 5000  # ~hour of heavy editing
STREAM_READ_COUNT = 32

# Max XREAD wait, proxies idle-kill connections around 60s
STREAM_BLOCK_MS = 15_000

# SSE lifetime cap - browser auto-reconnects via Last-Event-ID
STREAM_LIFETIME_SECONDS = 5 * 60

DATA_KEY = b"data"
KEEPALIVE_COMMENT = b": keepalive\n\n"
UPDATE_EVENT_TYPE = "update"

# Above this, update events carry no diff and receivers fall back to a full reload.
MAX_PUBLISHED_DIFF_BYTES = 64 * 1024

# Keep in sync with `NotebookNodeType.MarkdownNotebook` in frontend/src/scenes/notebooks/types.ts.
MARKDOWN_NOTEBOOK_NODE_TYPE = "ph-markdown-notebook"

_UTF16 = "utf-16-le"


@dataclass
class StepEntry:
    step: dict
    client_id: str


@dataclass
class MarkdownDiff:
    # `{start, end, text}` spans in UTF-16 code units, ascending and non-overlapping
    changes: list[dict]
    # CRC-32 of the base markdown (UTF-16-LE bytes); receivers verify before applying
    base_crc: int


@dataclass
class MarkdownUpdateEntry:
    version: int
    diff: list[dict]
    base_crc: int | None
    client_id: str | None


@dataclass
class MarkdownSubmitResult:
    # "accepted" - update appended; `version` is the new top
    # "conflict" - caller is behind; `version` is the current top, `updates` is the missed range
    # "stale"    - the missed range can't be replayed as markdown diffs; caller must reload
    status: Literal["accepted", "conflict", "stale"]
    version: int
    updates: list[MarkdownUpdateEntry] | None = None


def get_markdown_notebook_markdown(content: Any) -> str | None:
    """Extract the markdown source from a markdown-notebook document, or None if it isn't one."""
    if not isinstance(content, dict):
        return None
    nodes = content.get("content")
    if not isinstance(nodes, list) or len(nodes) != 1:
        return None
    node = nodes[0]
    if not isinstance(node, dict) or node.get("type") != MARKDOWN_NOTEBOOK_NODE_TYPE:
        return None
    attrs = node.get("attrs")
    markdown = attrs.get("markdown") if isinstance(attrs, dict) else None
    return markdown if isinstance(markdown, str) else None


def _encode_utf16(text: str) -> bytes:
    # surrogatepass: JSON can legally smuggle lone surrogates ("\ud83e") into Postgres content
    return text.encode(_UTF16, "surrogatepass")


def _utf16_unit(data: bytes, unit_index: int) -> int:
    return data[2 * unit_index] | (data[2 * unit_index + 1] << 8)


def _is_high_surrogate(data: bytes, unit_index: int) -> bool:
    return 0xD800 <= _utf16_unit(data, unit_index) <= 0xDBFF


def _is_low_surrogate(data: bytes, unit_index: int) -> bool:
    return 0xDC00 <= _utf16_unit(data, unit_index) <= 0xDFFF


def _common_prefix_bytes(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    i = 0
    chunk = 4096
    while i < n:
        if a[i : i + chunk] == b[i : i + chunk]:
            i += chunk
            continue
        end = min(i + chunk, n)
        while i < end and a[i] == b[i]:
            i += 1
        return i
    return n


def _common_suffix_bytes(a: bytes, b: bytes, max_bytes: int) -> int:
    i = 0
    chunk = 4096
    while i < max_bytes:
        step = min(chunk, max_bytes - i)
        if a[len(a) - i - step : len(a) - i] == b[len(b) - i - step : len(b) - i]:
            i += step
            continue
        while i < max_bytes and a[len(a) - i - 1] == b[len(b) - i - 1]:
            i += 1
        return i
    return max_bytes


def utf16_single_span_diff(base: str, next_text: str) -> dict | None:
    """Single replaced span between two strings, with offsets in UTF-16 code units.

    Boundaries never split a surrogate pair, so the replacement text always decodes
    (and JSON-encodes) cleanly. Returns None when the strings are equal.
    """
    if base == next_text:
        return None

    base_bytes = _encode_utf16(base)
    next_bytes = _encode_utf16(next_text)
    base_units = len(base_bytes) // 2
    next_units = len(next_bytes) // 2

    prefix = _common_prefix_bytes(base_bytes, next_bytes) // 2
    if prefix > 0 and _is_high_surrogate(base_bytes, prefix - 1):
        prefix -= 1

    max_suffix_bytes = (min(base_units, next_units) - prefix) * 2
    suffix = _common_suffix_bytes(base_bytes, next_bytes, max_suffix_bytes) // 2
    if suffix > 0 and _is_low_surrogate(next_bytes, next_units - suffix):
        suffix -= 1

    text = next_bytes[2 * prefix : 2 * (next_units - suffix)].decode(_UTF16, "surrogatepass")
    return {"start": prefix, "end": base_units - suffix, "text": text}


def apply_utf16_text_changes(base: str, changes: list[dict]) -> str | None:
    """Apply `{start, end, text}` spans (UTF-16 code-unit offsets, ascending, non-overlapping).

    Returns None when the changes don't fit the base string. Mirrors
    `tryApplyTextChanges` in frontend/src/lib/components/MarkdownNotebook/collaboration.ts.
    """
    base_bytes = _encode_utf16(base)
    base_units = len(base_bytes) // 2
    result = bytearray()
    cursor = 0
    for change in changes:
        start, end, text = change.get("start"), change.get("end"), change.get("text")
        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(text, str):
            return None
        if start < cursor or start > end or end > base_units:
            return None
        result += base_bytes[2 * cursor : 2 * start]
        result += _encode_utf16(text)
        cursor = end
    result += base_bytes[2 * cursor :]
    try:
        return bytes(result).decode(_UTF16, "surrogatepass")
    except UnicodeDecodeError:
        return None


def markdown_crc(text: str) -> int:
    """CRC-32 of the UTF-16-LE bytes. Mirrors `markdownCrc` in collaboration.ts."""
    return zlib.crc32(_encode_utf16(text))


def build_markdown_update_diff(previous_content: Any, next_content: Any) -> MarkdownDiff | None:
    """Diff two markdown-notebook documents into stream-publishable changes.

    Returns None when either document isn't a markdown notebook, nothing changed,
    or the diff is too large to be worth streaming (receivers reload instead).
    """
    previous_markdown = get_markdown_notebook_markdown(previous_content)
    next_markdown = get_markdown_notebook_markdown(next_content)
    if previous_markdown is None or next_markdown is None:
        return None
    change = utf16_single_span_diff(previous_markdown, next_markdown)
    if change is None:
        return None
    if len(change["text"].encode("utf-8")) > MAX_PUBLISHED_DIFF_BYTES:
        return None
    return MarkdownDiff(changes=[change], base_crc=markdown_crc(previous_markdown))


@dataclass
class SubmitResult:
    # "accepted" - steps appended; `version` is the new top
    # "conflict" - caller is behind; `version` is the current top, `steps_since` is the missed range
    # "stale"    - missed range was trimmed (MAXLEN/TTL) or the stream was lost and the client's
    #              baseline no longer matches Postgres; caller must reload from Postgres
    status: Literal["accepted", "conflict", "stale"]
    version: int
    steps_since: list[StepEntry] | None = None


# Atomically append N step entries if the current stream version equals last_seen_version.
#
# When the stream is empty (TTL expired / evicted / never written) we cannot trust the caller's
# last_seen_version on its own — a stale tab with an old baseline could otherwise be accepted
# and silently downgrade the persisted version on the subsequent Notebook update. Cross-check
# against last_saved_version (the value durably stored in Postgres): only accept if they match
# exactly, otherwise force the client to reload.
#
# ARGV:
#   1: last_seen_version (int)         -- prosemirror confirmed version on the client
#   2: last_saved_version (int)        -- notebook.version from Postgres, fetched by the caller
#   3: ttl_seconds (int)
#   4: max_length (int)
#   5..N: step entry JSON strings (one per prosemirror step)
#
# Returns:
#   {0, current_stream_version}        -- conflict, caller should fetch missed steps
#   {1, new_version}                   -- accepted
#   {2, last_saved_version}            -- stream lost + client baseline disagrees with Postgres → stale
_APPEND_STEPS_LUA = """
local stream_key = KEYS[1]
local last_seen_version = tonumber(ARGV[1])
local last_saved_version = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local max_length = tonumber(ARGV[4])

local current_stream_version = last_seen_version
local last = redis.call('XREVRANGE', stream_key, '+', '-', 'COUNT', 1)
local stream_empty = (#last == 0)
if not stream_empty then
    local id_str = last[1][1]
    local dash = string.find(id_str, '-')
    current_stream_version = tonumber(string.sub(id_str, 1, dash - 1))
end

if stream_empty and last_seen_version ~= last_saved_version then
    return {2, last_saved_version}
end

if current_stream_version ~= last_seen_version then
    -- A failed XADD (publish errors are logged, not raised) can leave the stream behind
    -- Postgres. When the caller's baseline matches Postgres, resync forward instead of
    -- rejecting every save against a permanently lagging stream.
    if current_stream_version < last_seen_version and last_seen_version == last_saved_version then
        current_stream_version = last_seen_version
    else
        return {0, current_stream_version}
    end
end

local next_version = current_stream_version
for i = 5, #ARGV do
    next_version = next_version + 1
    redis.call('XADD', stream_key, 'MAXLEN', '~', max_length, next_version .. '-0', 'data', ARGV[i])
end

redis.call('EXPIRE', stream_key, ttl)
return {1, next_version}
"""


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

    script = client.register_script(_APPEND_STEPS_LUA)
    accepted, version = script(
        keys=[stream_key],
        args=[last_seen_version, last_saved_version, STREAM_TTL_SECONDS, STREAM_MAX_LENGTH, *serialized],
    )

    if accepted == 1:
        return SubmitResult(status="accepted", version=version)
    if accepted == 2:
        return SubmitResult(status="stale", version=version)

    return _fetch_missed_steps(stream_key, last_seen_version=last_seen_version, current_stream_version=version)


def submit_markdown_update(
    team_id: int,
    notebook_id: str,
    *,
    client_id: str,
    diff: MarkdownDiff | None,
    last_seen_version: int,
    last_saved_version: int,
) -> MarkdownSubmitResult:
    """Atomically append one markdown update event if the caller's baseline matches the stream head.

    `diff` transforms the markdown at `last_seen_version` into the saved markdown; receivers
    apply it without refetching. A None diff still bumps the version (receivers reload).
    """
    client = redis_module.get_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)

    payload: dict[str, Any] = {"type": UPDATE_EVENT_TYPE, "client_id": client_id}
    if diff is not None:
        payload["diff"] = diff.changes
        payload["base_crc"] = diff.base_crc

    script = client.register_script(_APPEND_STEPS_LUA)
    accepted, version = script(
        keys=[stream_key],
        args=[last_seen_version, last_saved_version, STREAM_TTL_SECONDS, STREAM_MAX_LENGTH, json.dumps(payload)],
    )

    if accepted == 1:
        return MarkdownSubmitResult(status="accepted", version=version)
    if accepted == 2:
        return MarkdownSubmitResult(status="stale", version=version)

    return fetch_missed_markdown_updates(
        team_id, notebook_id, last_seen_version=last_seen_version, current_version=version
    )


def fetch_missed_markdown_updates(
    team_id: int,
    notebook_id: str,
    *,
    last_seen_version: int,
    current_version: int,
) -> MarkdownSubmitResult:
    """Collect the markdown diffs for versions (last_seen_version, current_version].

    Returns "conflict" with the full ordered range when every version is replayable as a
    diff, "stale" when any is missing (trimmed, diff-less ping, or prosemirror step).
    """
    if current_version <= last_seen_version:
        return MarkdownSubmitResult(status="stale", version=current_version)

    client = redis_module.get_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)
    # `({N}-1` skips both entries for the baseline version (N-0 CAS submits, N-1 publishes)
    raw = client.xrange(stream_key, min=f"({last_seen_version}-1", max=f"{current_version}-1")

    updates_by_version: dict[int, MarkdownUpdateEntry] = {}
    for stream_id, fields in raw:
        version = int(stream_id.decode().split("-", 1)[0])
        if version in updates_by_version:
            continue
        try:
            data = json.loads(fields[DATA_KEY])
        except (json.JSONDecodeError, KeyError):
            return MarkdownSubmitResult(status="stale", version=current_version)
        diff = data.get("diff")
        if data.get("type") != UPDATE_EVENT_TYPE or not isinstance(diff, list):
            return MarkdownSubmitResult(status="stale", version=current_version)
        base_crc = data.get("base_crc")
        updates_by_version[version] = MarkdownUpdateEntry(
            version=version,
            diff=diff,
            base_crc=base_crc if isinstance(base_crc, int) else None,
            client_id=data.get("client_id"),
        )

    expected_versions = range(last_seen_version + 1, current_version + 1)
    if any(version not in updates_by_version for version in expected_versions):
        return MarkdownSubmitResult(status="stale", version=current_version)

    return MarkdownSubmitResult(
        status="conflict",
        version=current_version,
        updates=[updates_by_version[version] for version in expected_versions],
    )


def _update_payload(version: int, diff: MarkdownDiff | None = None, client_id: str | None = None) -> str:
    payload: dict[str, Any] = {"type": UPDATE_EVENT_TYPE, "version": version}
    if diff is not None:
        payload["diff"] = diff.changes
        payload["base_crc"] = diff.base_crc
    if client_id is not None:
        payload["client_id"] = client_id
    return json.dumps(payload)


def _log_publish_error(err: redis_exceptions.RedisError, *, stream_key: str, notebook_id: str, version: int) -> None:
    logger.warning(
        "notebook_collab_update_publish_error",
        stream_key=stream_key,
        notebook_short_id=notebook_id,
        version=version,
        error=str(err),
    )


def publish_notebook_update(
    team_id: int,
    notebook_id: str,
    version: int,
    *,
    diff: MarkdownDiff | None = None,
    client_id: str | None = None,
) -> None:
    client = redis_module.get_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)

    try:
        client.xadd(
            stream_key,
            {"data": _update_payload(version, diff=diff, client_id=client_id)},
            id=f"{version}-1",
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )
        client.expire(stream_key, STREAM_TTL_SECONDS)
    except redis_exceptions.RedisError as err:
        _log_publish_error(err, stream_key=stream_key, notebook_id=notebook_id, version=version)


async def apublish_notebook_update(
    team_id: int,
    notebook_id: str,
    version: int,
    *,
    diff: MarkdownDiff | None = None,
    client_id: str | None = None,
) -> None:
    client = redis_module.get_async_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)

    try:
        await client.xadd(
            stream_key,
            {"data": _update_payload(version, diff=diff, client_id=client_id)},
            id=f"{version}-1",
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )
        await client.expire(stream_key, STREAM_TTL_SECONDS)
    except redis_exceptions.RedisError as err:
        _log_publish_error(err, stream_key=stream_key, notebook_id=notebook_id, version=version)


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


async def stream_collab_sse(
    team_id: int,
    notebook_id: str,
    *,
    last_event_id: str | None,
) -> AsyncGenerator[bytes]:
    """
    Tail this notebook's Redis stream from last_event_id (or from now if None).
    Yields one SSE frame per step, plus a keepalive comment during idle gaps.
    """
    client = redis_module.get_async_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)
    current_id = last_event_id or "$"

    try:
        async with asyncio.timeout(STREAM_LIFETIME_SECONDS):
            while True:
                try:
                    messages = await client.xread(
                        {stream_key: current_id}, block=STREAM_BLOCK_MS, count=STREAM_READ_COUNT
                    )
                except redis_exceptions.RedisError as err:
                    logger.warning("notebook_collab_stream_error", notebook_short_id=notebook_id, error=str(err))
                    yield b'event: error\ndata: {"error":"stream error"}\n\n'
                    return

                if not messages:
                    yield KEEPALIVE_COMMENT
                    continue

                # We only XREAD one stream key, so messages is always [(key, entries)]
                _, entries = messages[0]
                for stream_id, fields in entries:
                    current_id = stream_id.decode()
                    try:
                        data = json.loads(fields[DATA_KEY])
                    except json.JSONDecodeError:
                        logger.warning("notebook_collab_invalid_payload", stream_key=stream_key, stream_id=current_id)
                        continue
                    event_type = data.get("type")
                    if event_type == UPDATE_EVENT_TYPE:
                        yield (
                            f"id: {current_id}\nevent: update\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
                        ).encode()
                    elif "step" in data:
                        yield f"id: {current_id}\nevent: step\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()
                    else:
                        logger.warning("notebook_collab_unknown_payload", stream_key=stream_key, stream_id=current_id)

                # cooperative yield: prevents tight-loop monopolization when XREAD doesn't block
                await asyncio.sleep(0)
    except TimeoutError:
        # Lifetime cap hit; client reconnects with Last-Event-ID against a fresh worker
        return
