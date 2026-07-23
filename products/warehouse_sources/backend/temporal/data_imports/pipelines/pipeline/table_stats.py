"""Per-table size telemetry for the data-import pipelines.

Emits how much data each source pulls into the pod, tagged by `(source_type, stage)`, so an
unbounded source materialisation shows up as a high, chunk-size-insensitive tail per source. Two
stages are recorded because a source can bypass the shared `Batcher` (e.g. yielding `pa.Table`s
directly, or a future extract path): `stage="pipeline"` is the raw item off `resource.items()` (the
catch-all, every source), `stage="batcher"` is the materialised Arrow table (the true in-memory
peak). Bytes are optional because a list item's Arrow size isn't known until it's materialised.

`table_payload_bytes` is slice-accurate (unlike `pa.Table.nbytes`, which reports the full shared
buffer for a zero-copy slice) — the `Batcher` produces zero-copy slices, so `.nbytes` would
over-count there.
"""

import os
from typing import Any, Optional

import pyarrow as pa
import pyarrow.compute as pc
import posthoganalytics
from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.utils import get_machine_id

# Any single table whose in-memory Arrow payload crosses this is logged and captured as a PostHog
# event with the pod/team/schema/source context needed to reproduce it. The metrics below capture the
# full distribution; this surfaces the specific offenders to fix. Event volume is bounded because it
# only fires on the outliers (a paginating source can call record_table_stats thousands of times per
# sync — one event each would flood ingestion; the histograms carry that full distribution instead).
OUTLIER_TABLE_BYTES: int = 512 * 1024 * 1024  # 512 MiB

# The event a large table emits. Tagged with pod/host, source_type, schema_name, team_id, rows, bytes.
LARGE_TABLE_EVENT = "data_import_large_table"


def _pod_name() -> Optional[str]:
    """The k8s pod name (== the container hostname) so events can be sliced by pod/host."""
    return os.environ.get("HOSTNAME")


def _column_payload_bytes(col: pa.ChunkedArray) -> int:
    """Slice-accurate in-memory payload bytes: value bytes + offset buffer (string/binary/list)
    or col_length * byte_width (fixed-width); nested/other types return 0. Avoids `.nbytes` (wrong for slices)."""
    col_type = col.type
    col_length = len(col)
    if pa.types.is_string(col_type) or pa.types.is_binary(col_type):
        payload = int(pc.sum(pc.binary_length(col)).as_py() or 0)
        return payload + col_length * 4  # value bytes + 32-bit offsets
    if pa.types.is_large_string(col_type) or pa.types.is_large_binary(col_type):
        payload = int(pc.sum(pc.binary_length(col)).as_py() or 0)
        return payload + col_length * 8
    if pa.types.is_list(col_type):
        elements = int(pc.sum(pc.list_value_length(col)).as_py() or 0)
        return elements + col_length * 4
    if pa.types.is_struct(col_type):
        # Recurse into child fields so a nested struct (e.g. a Mongo document under `data`) is counted
        # instead of undercounting to 0. A flatten failure degrades to 0 rather than breaking accounting.
        try:
            return sum(_column_payload_bytes(child) for child in col.flatten())
        except Exception:
            return 0
    # Fixed-width primitives expose bit_width; variable-length / other nested types raise -> 0.
    try:
        bit_width = col_type.bit_width
    except (ValueError, AttributeError):
        return 0
    return col_length * (bit_width // 8)


def table_payload_bytes(table: pa.Table) -> int:
    return sum(_column_payload_bytes(table.column(name)) for name in table.column_names)


def record_table_stats(
    *,
    source_type: Optional[str],
    stage: str,
    num_rows: int,
    payload_bytes: Optional[int],
    logger: FilteringBoundLogger,
    team_id: Optional[int] = None,
    schema_name: Optional[str] = None,
) -> None:
    """Record row/byte size for one source table, keyed on `(source_type, stage)`.

    Safe outside an activity (unit tests construct the pipeline/batcher directly): the Temporal meter
    is only touched inside an activity context; the outlier log + event still fire. Metric labels are
    kept to `source_type` + `stage` (bounded cardinality); `pod`/`team_id`/`schema_name` ride the
    outlier log and the PostHog event only.
    """
    resolved_source_type = source_type or "unknown"
    if activity.in_activity():
        meter = activity.metric_meter().with_additional_attributes(
            {"source_type": resolved_source_type, "stage": stage}
        )
        meter.create_histogram("data_import_table_rows", "Row count of one source table").record(max(num_rows, 0))
        if payload_bytes is not None:
            meter.create_histogram(
                "data_import_table_bytes", "In-memory Arrow payload of one source table", "By"
            ).record(max(payload_bytes, 0))
    if payload_bytes is not None and payload_bytes >= OUTLIER_TABLE_BYTES:
        pod_name = _pod_name()
        logger.warning(
            LARGE_TABLE_EVENT,
            source_type=resolved_source_type,
            stage=stage,
            payload_bytes=payload_bytes,
            num_rows=num_rows,
            team_id=team_id,
            schema_name=schema_name,
            pod_name=pod_name,
        )
        # Long-lived Temporal worker, so posthoganalytics' background flush thread stays alive
        # (unlike the Celery pitfall) — this matches capture_repartition_event. Best-effort: a
        # telemetry failure must never fail the import.
        try:
            machine_id = get_machine_id()
            posthoganalytics.capture(
                distinct_id=machine_id,
                event=LARGE_TABLE_EVENT,
                properties={
                    "source_type": resolved_source_type,
                    "stage": stage,
                    "num_rows": num_rows,
                    "payload_bytes": payload_bytes,
                    "team_id": team_id,
                    "schema_name": schema_name,
                    "pod_name": pod_name,
                    "machine_id": machine_id,
                },
            )
        except Exception:
            logger.debug("Failed to capture data_import_large_table event", exc_info=True)


def record_source_item_stats(
    item: Any,
    *,
    source_type: Optional[str],
    logger: FilteringBoundLogger,
    team_id: Optional[int] = None,
    schema_name: Optional[str] = None,
) -> None:
    """Measure one raw item yielded by a source (the `stage="pipeline"` catch-all, before batching).

    Every source flows through here regardless of whether it uses the shared `Batcher`. Row count is
    always known; Arrow bytes only for a `pa.Table` item — a list/dict isn't materialised yet, so its
    bytes are recorded at `stage="batcher"` instead.
    """
    if isinstance(item, pa.Table):
        num_rows = item.num_rows
        payload_bytes: Optional[int] = table_payload_bytes(item)
    elif isinstance(item, list):
        num_rows = len(item)
        payload_bytes = None
    else:  # a single dict row
        num_rows = 1
        payload_bytes = None
    record_table_stats(
        source_type=source_type,
        stage="pipeline",
        num_rows=num_rows,
        payload_bytes=payload_bytes,
        logger=logger,
        team_id=team_id,
        schema_name=schema_name,
    )
