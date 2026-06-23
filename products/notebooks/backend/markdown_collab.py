"""
Markdown notebook collaboration: version-CAS update events over the shared content stream.

Markdown diffs are lists of `{start, end, text}` spans with offsets in UTF-16 code units,
so JavaScript clients can apply them with plain `String.slice`. The stream transport and
the CAS Lua script are shared with the prosemirror-steps collab — see `collab_stream.py`.
"""

import json
import zlib
from dataclasses import dataclass
from typing import Any, Literal

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

from products.notebooks.backend.collab_stream import (
    APPEND_ENTRIES_LUA,
    DATA_KEY,
    STREAM_KEY_PATTERN,
    STREAM_MAX_LENGTH,
    STREAM_TTL_SECONDS,
    UPDATE_EVENT_TYPE,
)

logger = structlog.get_logger(__name__)

# Above this, update events carry no diff and receivers fall back to a full reload.
MAX_PUBLISHED_DIFF_BYTES = 64 * 1024

# Keep in sync with `NotebookNodeType.MarkdownNotebook` in frontend/src/scenes/notebooks/types.ts.
MARKDOWN_NOTEBOOK_NODE_TYPE = "ph-markdown-notebook"

_UTF16 = "utf-16-le"


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
    `tryApplyTextChanges` in frontend/src/lib/components/MarkdownNotebook/textChanges.ts.
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


def submit_markdown_update(
    team_id: int,
    notebook_id: str,
    *,
    client_id: str,
    diff: MarkdownDiff | None,
    last_seen_version: int,
    last_saved_version: int,
    user_id: int | None = None,
    user_name: str | None = None,
    cursor: dict[str, Any] | None = None,
) -> MarkdownSubmitResult:
    """Atomically append one markdown update event if the caller's baseline matches the stream head.

    `diff` transforms the markdown at `last_seen_version` into the saved markdown; receivers
    apply it without refetching. A None diff still bumps the version (receivers reload).
    `cursor` is the author's caret in the saved markdown, so receivers can move the author's
    remote caret in the same paint as the text change.
    """
    client = redis_module.get_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)

    payload: dict[str, Any] = {"type": UPDATE_EVENT_TYPE, "client_id": client_id}
    if diff is not None:
        payload["diff"] = diff.changes
        payload["base_crc"] = diff.base_crc
    presence = {k: v for k, v in (("user_id", user_id), ("user_name", user_name), ("cursor", cursor)) if v is not None}
    payload.update(presence)

    script = client.register_script(APPEND_ENTRIES_LUA)
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
