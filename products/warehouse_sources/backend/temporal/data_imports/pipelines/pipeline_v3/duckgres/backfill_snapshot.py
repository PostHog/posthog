"""Delta snapshot resolution and chunk planning for the duckgres backfill.

Pure read-side: no queue or app-DB writes live here. Given a schema (and
optionally a pinned version), produce the chunk plan — groups of the Delta
table's own live parquet files bounded by bytes and file count.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from django.conf import settings

from products.warehouse_sources.backend.models import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

CHUNK_TARGET_BYTES = 1024**3  # ~1 GiB of parquet per chunk statement
MAX_FILES_PER_CHUNK = 512  # bound the read_parquet([...]) literal list


class BackfillUnsupportedError(Exception):
    """The Delta table cannot be backfilled by this planner (parks NEEDS_RESYNC)."""


@dataclass(frozen=True)
class BackfillChunk:
    index: int
    paths: list[str]
    byte_size: int
    row_count: int


@dataclass(frozen=True)
class BackfillSnapshotPlan:
    snapshot_version: int
    chunks: list[BackfillChunk]
    covered_batches: list[tuple[str, int]]


def delta_table_uri(schema: ExternalDataSchema) -> str:
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{_delta_table_folder(schema)}"


def _delta_table_folder(schema: ExternalDataSchema) -> str:
    """The Delta table's own folder segment, as the loader actually wrote it.

    The loader names the folder after the DLT resource (the unqualified table
    name), so it diverges from schema.normalized_name for schema-qualified
    sources: Postgres "public.foo" normalizes to "public_foo", but the Delta
    folder is "foo". Reading normalized_name here points the backfill at a
    prefix with no _delta_log (surfaces as "No files in log segment"). The
    catalog table's url_pattern is the authoritative location — it is what the
    query engine reads — so take the leaf from there, and fall back to
    normalized_name only when no table row exists yet (nothing to backfill).

    url_pattern is a user-writable field, so the leaf is normalized through the
    same convention the writer used to produce it. This is a no-op for every
    legitimate folder (they are already normalize_identifier output) and strips
    any injected separators so the leaf can never escape the schema's own prefix.
    """
    table = schema.table
    if table and table.url_pattern:
        segments = [seg for seg in table.url_pattern.rstrip("/").split("/") if seg and seg not in ("*", "**")]
        if segments:
            return NamingConvention.normalize_identifier(segments[-1])
    return schema.normalized_name


def _delta_storage_options() -> dict[str, str]:
    """Storage options for metadata-only Delta log reads from the consumer pod.

    Prod: empty — deltalake's object_store resolves the pod's ambient AWS
    credential chain (IRSA/env) itself. Local dev: MinIO endpoint + keys.
    (posthog.ducklake.storage.get_deltalake_storage_options is NOT usable
    here: it requires DuckLake RDS env that consumer pods do not carry.)
    """
    if settings.USE_LOCAL_SETUP:
        return {
            "AWS_ACCESS_KEY_ID": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "AWS_SECRET_ACCESS_KEY": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            "AWS_ENDPOINT_URL": settings.OBJECT_STORAGE_ENDPOINT,
            "AWS_ALLOW_HTTP": "true",
            "AWS_REGION": "us-east-1",
        }
    return {}


def resolve_snapshot_chunks(schema: ExternalDataSchema, version: int | None = None) -> tuple[int, list[BackfillChunk]]:
    plan = resolve_snapshot_plan(schema, version=version)
    return plan.snapshot_version, plan.chunks


def resolve_snapshot_plan(schema: ExternalDataSchema, version: int | None = None) -> BackfillSnapshotPlan:
    uri = delta_table_uri(schema)
    if version is None:
        # No pinned version to cache against — this is the initial plan, reading
        # whatever HEAD currently is, which is not a stable cache key.
        return _resolve_snapshot_plan(uri, version)
    return _resolve_pinned_snapshot_plan(uri, version)


# A cached plan holds every live parquet path and commit key for its table, so
# entry *size* scales with table size — an entry-count cap alone doesn't bound
# memory. Weigh entries by that count and cap the total instead: a plan over
# budget on its own is simply never cached (recomputed every call, same as
# before this cache existed), so one huge table can't make the cache retain an
# unbounded amount indefinitely.
_PINNED_SNAPSHOT_PLAN_CACHE_MAX_WEIGHT = 50_000

_pinned_snapshot_plan_cache: OrderedDict[tuple[str, int], tuple[BackfillSnapshotPlan, int]] = OrderedDict()
_pinned_snapshot_plan_cache_weight = 0
_pinned_snapshot_plan_cache_lock = threading.Lock()


def _plan_weight(plan: BackfillSnapshotPlan) -> int:
    return sum(len(chunk.paths) for chunk in plan.chunks) + len(plan.covered_batches)


def _resolve_pinned_snapshot_plan(uri: str, version: int) -> BackfillSnapshotPlan:
    """Cached for already-committed (pinned) versions only.

    A commit at or before an already-resolved version never changes, but
    deltalake's history() has no checkpoint shortcut — it walks the
    _delta_log from genesis one commit at a time. The reconciler calls
    resolve_snapshot_plan with the same pinned version on every ~30s tick
    until a backfill finishes draining its queue, so without this cache a
    large table (tens of thousands of commits) gets its entire commit log
    re-read from S3 on every pass, which can trip S3 rate limiting.
    """
    global _pinned_snapshot_plan_cache_weight

    key = (uri, version)
    with _pinned_snapshot_plan_cache_lock:
        cached = _pinned_snapshot_plan_cache.get(key)
        if cached is not None:
            _pinned_snapshot_plan_cache.move_to_end(key)
            return cached[0]

    plan = _resolve_snapshot_plan(uri, version)
    weight = _plan_weight(plan)

    with _pinned_snapshot_plan_cache_lock:
        while (
            _pinned_snapshot_plan_cache
            and _pinned_snapshot_plan_cache_weight + weight > _PINNED_SNAPSHOT_PLAN_CACHE_MAX_WEIGHT
        ):
            _, (_, evicted_weight) = _pinned_snapshot_plan_cache.popitem(last=False)
            _pinned_snapshot_plan_cache_weight -= evicted_weight
        if weight <= _PINNED_SNAPSHOT_PLAN_CACHE_MAX_WEIGHT:
            _pinned_snapshot_plan_cache[key] = (plan, weight)
            _pinned_snapshot_plan_cache_weight += weight
    return plan


def _resolve_snapshot_plan(uri: str, version: int | None) -> BackfillSnapshotPlan:
    from deltalake import DeltaTable

    dt = DeltaTable(uri, version=version, storage_options=_delta_storage_options())
    resolved_version = dt.version()

    if _has_deletion_vectors(dt):
        # deltalake 1.4.0 cannot stream DV tables (to_pyarrow_dataset rejects
        # the reader feature), and reading the add files directly would serve
        # deleted rows. Park the schema; a full-refresh resync heals it.
        raise BackfillUnsupportedError(
            "Delta table has the deletionVectors reader feature; backfill requires a full resync"
        )

    adds = dt.get_add_actions(flatten=True)
    paths = adds.column("path").to_pylist()
    sizes = adds.column("size_bytes").to_pylist()
    counts: list[int]
    try:
        counts = [int(c) if c is not None else 0 for c in adds.column("num_records").to_pylist()]
    except KeyError:
        counts = [0] * len(paths)

    files = []
    for p, size, rows in zip(paths, sizes, counts):
        # Add-action paths are percent-encoded relative paths (or, rarely,
        # absolute URIs). Decode so read_parquet sees the real object key.
        decoded = unquote(p)
        full = decoded if decoded.startswith(("s3://", "s3a://")) else f"{uri.rstrip('/')}/{decoded}"
        files.append((full, size or 0, rows or 0))
    return BackfillSnapshotPlan(
        snapshot_version=resolved_version,
        chunks=_group_files_into_chunks(files),
        covered_batches=_committed_batch_keys(dt, snapshot_version=resolved_version),
    )


def _has_deletion_vectors(dt: Any) -> bool:
    """Conservative: a DV-enabled table parks even if no DV is currently active —
    re-deriving per-file DV state is not worth the risk of serving deleted rows."""
    try:
        protocol = dt.protocol()
        features = list(protocol.reader_features or [])
        return "deletionVectors" in features
    except Exception:
        return True  # unknown protocol shape: park, never lie


def _committed_batch_keys(dt: Any, *, snapshot_version: int) -> list[tuple[str, int]]:
    """Return live v3 batch keys committed at or before the pinned snapshot.

    Delta commits are the only exact boundary for snapshot containment. Queue
    timestamps can race the snapshot read, but a commit with version <= the
    pinned version is necessarily represented in the files this backfill reads.
    """
    keys: list[tuple[str, int]] = []
    for commit in dt.history():
        commit_version = commit.get("version")
        if isinstance(commit_version, int) and commit_version > snapshot_version:
            continue

        metadata = _commit_metadata(commit)
        run_uuid = metadata.get("run_uuid")
        batch_index = metadata.get("batch_index")
        if run_uuid is None or batch_index is None:
            continue
        try:
            keys.append((str(run_uuid), int(batch_index)))
        except (TypeError, ValueError):
            continue
    return keys


def _commit_metadata(commit: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = dict(commit)
    raw = commit.get("userMetadata")
    if isinstance(raw, str):
        try:
            nested = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            nested = {}
    elif isinstance(raw, dict):
        nested = raw
    else:
        nested = {}
    metadata.update(nested)
    return metadata


def _group_files_into_chunks(files: list[tuple[str, int, int]]) -> list[BackfillChunk]:
    chunks: list[BackfillChunk] = []
    cur_paths: list[str] = []
    cur_bytes = 0
    cur_rows = 0
    for path, size, rows in files:
        if cur_paths and (cur_bytes + size > CHUNK_TARGET_BYTES or len(cur_paths) >= MAX_FILES_PER_CHUNK):
            chunks.append(BackfillChunk(len(chunks), cur_paths, cur_bytes, cur_rows))
            cur_paths, cur_bytes, cur_rows = [], 0, 0
        cur_paths.append(path)
        cur_bytes += size
        cur_rows += rows
    if cur_paths:
        chunks.append(BackfillChunk(len(chunks), cur_paths, cur_bytes, cur_rows))
    return chunks
