"""Object-store handoff for materialized SQLV2 frames (sql_v2_frame_store.md, phase 1).

A Temporal worker streams a frame's ClickHouse result (raw Arrow IPC stream bytes) into
one object here; the data-plane status endpoint answers the kernel's poll with a 302 to a
short-lived presigned GET of that object. Tenant isolation is the team prefix: keys are
always built from data-plane token claims, never from request input, and presigning
refuses any key outside the requesting team's prefix.
"""

import re
import datetime as dt
from typing import IO

from django.conf import settings

from posthog.storage import object_storage

FRAMES_PREFIX = "notebooks/frames"
ARROW_STREAM_CONTENT_TYPE = "application/vnd.apache.arrow.stream"
# Long enough for the kernel's redirect-follow (and a retry or two), no more — a presigned
# URL is a bearer secret of the same class as the data-plane token.
PRESIGN_EXPIRY_SECONDS = 300

_KEY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class FrameStoreError(Exception):
    pass


def is_enabled() -> bool:
    """The frame store is env-gated (rollout) and needs object storage to be configured."""
    return bool(settings.NOTEBOOKS_FRAME_STORE_ENABLED and settings.OBJECT_STORAGE_ENABLED)


def team_prefix(team_id: int) -> str:
    """The per-team key prefix — the tenant isolation unit for frame objects."""
    return f"{FRAMES_PREFIX}/team_{int(team_id)}/"


def build_frame_key(team_id: int, notebook_short_id: str, query_hash: str) -> str:
    """Build the object key for one materialized frame.

    Segments are validated defensively: they come from token claims and a server-side
    hash, but a key must never be constructible with path separators in it.
    """
    for segment in (notebook_short_id, query_hash):
        # fullmatch, not match: `$` in `.match` also matches before a trailing newline, so a
        # segment like "nb\n" would pass — and this key is spliced into a SQL statement on the
        # CH-writes path, where the doc's threat model makes exact charset validation load-bearing.
        if not _KEY_SEGMENT_RE.fullmatch(segment):
            raise FrameStoreError(f"Invalid frame key segment: {segment!r}")
    return f"{team_prefix(team_id)}{notebook_short_id}/{query_hash}.arrow"


def write_stream(key: str, fileobj: IO[bytes]) -> int:
    """Stream `fileobj` into the frame object at `key`; return the stored object's size.

    Memory is bounded by boto3's multipart part buffer, and a failed upload is aborted by
    the transfer manager — a torn stream never leaves a servable partial object. The
    post-write HEAD both confirms the object exists (an UnavailableStorage client no-ops
    writes silently) and provides the size for observability.
    """
    object_storage.write_stream(key, fileobj, extras={"ContentType": ARROW_STREAM_CONTENT_TYPE})
    return stat_frame(key)


def stat_frame(key: str, *, written_after: "dt.datetime | None" = None) -> int:
    """Confirm the frame object at `key` exists and return its size.

    The post-write existence check for both write paths: the worker upload (an
    UnavailableStorage client no-ops writes silently) and the CH-side INSERT (whose
    success response says the query finished, not that the bytes are servable).

    `written_after` guards the CH-side path against a silent no-op: ClickHouse writes from
    its own network, so if it "succeeds" against a store/bucket the app can't read, a stale
    object from an earlier run at this deterministic key would otherwise pass existence and be
    served as fresh. Requiring LastModified at/after the write start turns that into a loud
    failure. The margin for clock skew is the caller's to bake into `written_after`.
    """
    head = object_storage.head_object(key)
    if head is None:
        raise FrameStoreError("Frame object was not stored")
    if written_after is not None:
        last_modified = head.get("LastModified")
        if isinstance(last_modified, dt.datetime) and last_modified < written_after:
            raise FrameStoreError("Frame object predates this write — object store endpoint/bucket skew?")
    return int(head.get("ContentLength") or 0)


def presign_get(key: str, team_id: int) -> str:
    """Mint a short-lived presigned GET for `key`, refusing keys outside the team's prefix.

    The caller must have verified the data-plane token for `team_id` first; this check is
    the last line keeping a poisoned stored key from ever crossing tenant boundaries.
    """
    if not key.startswith(team_prefix(team_id)):
        raise FrameStoreError("Frame key is not under the requesting team's prefix")
    url = object_storage.get_presigned_url(
        key, expiration=PRESIGN_EXPIRY_SECONDS, content_type=ARROW_STREAM_CONTENT_TYPE
    )
    if not url:
        raise FrameStoreError("Could not presign the frame object")
    return url


def delete_frame(key: str) -> None:
    """Remove a frame object the caller itself just wrote and verified corrupt.

    Keys are deterministic per (team, notebook, user, query), so a generic failure path
    must never delete — it could destroy an object an earlier successful run's still-live
    status points at. The only legitimate caller is the writer discarding its own bytes.
    """
    object_storage.delete(key)
