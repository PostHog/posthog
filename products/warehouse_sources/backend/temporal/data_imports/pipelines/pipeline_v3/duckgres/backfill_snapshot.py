"""Delta snapshot resolution and chunk planning for the duckgres backfill.

Pure read-side: no queue or app-DB writes live here. Given a schema (and
optionally a pinned version), produce the chunk plan — groups of the Delta
table's own live parquet files bounded by bytes and file count.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from django.conf import settings

from products.warehouse_sources.backend.models import ExternalDataSchema

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
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{schema.normalized_name}"


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
    from deltalake import DeltaTable

    uri = delta_table_uri(schema)
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
