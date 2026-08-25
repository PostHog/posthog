import uuid
import datetime as dt
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import deltalake
import structlog
import pyarrow.compute as pc

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import get_schema_if_exists
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    pyarrow_schema_from_arrow_exportable,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import VACUUM_RETENTION
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    build_delta_table_uri,
    delta_storage_options,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ParentRowFilter

# Upper bound on rows held in memory per page. Source configs drive page_size for API paging
# semantics; a misconfigured or future large value must not turn into a whole-table page.
MAX_PARENT_PAGE_SIZE = 5000

# How far back a snapshot pin may reach. Derived from the writer's vacuum retention, with
# margin, so a pinned version's files can't have been tombstoned and vacuumed out from under
# an in-flight fan-out. Vacuum keys deletion off tombstone age, and a file live at the pinned
# version can only be tombstoned after that version, so any pin inside the window is safe.
MAX_SNAPSHOT_ROLLBACK = VACUUM_RETENTION - dt.timedelta(hours=4)

logger = structlog.get_logger(__name__)


class WarehouseParentTableNotFoundError(Exception):
    """The fan-out parent schema has no readable Delta table to fan out over.

    The run-time check in `import_data_activity_sync` only sees Postgres, so the table can
    still be missing, purged, or short a column. Callers of `resolve_parent_table_ref` catch
    this and fall back to the parent API for that run, which is why the check is eager.
    """


@dataclass(frozen=True)
class ParentTableRef:
    """A parent Delta table pinned to one version, so the whole fan-out reads one snapshot."""

    uri: str
    version: int


def _physical_columns_by_api_name(
    delta_table: "deltalake.DeltaTable", parent_name: str, columns: list[str]
) -> dict[str, str]:
    """Map API field names to the snake_case identifiers the Delta writer stored them under."""
    physical_schema_names = set(pyarrow_schema_from_arrow_exportable(delta_table.schema()).names)

    physical_by_api_name: dict[str, str] = {}
    missing_columns: list[str] = []
    for api_name in columns:
        physical = NamingConvention.normalize_identifier(api_name)
        if physical in physical_schema_names:
            physical_by_api_name[api_name] = physical
        else:
            missing_columns.append(api_name)

    if missing_columns:
        raise WarehouseParentTableNotFoundError(
            f"Parent table '{parent_name}' is missing requested column(s) {missing_columns} — "
            f"re-sync the parent schema so the fan-out fields are present"
        )
    return physical_by_api_name


@frozen
class _ResolvedRowFilter:
    """A row filter resolved against a Delta table's actual column type."""

    scan_filter: pc.Expression | None
    row_passes: Callable[[dict[str, Any]], bool]
    physical_column: str


def _row_filter_scan_and_predicate(
    delta_table: "deltalake.DeltaTable", parent_name: str, row_filter: ParentRowFilter
) -> _ResolvedRowFilter:
    """Resolve a row filter into an optional parquet-scan pushdown and a matching row check.

    The row check (applied to every materialized row regardless of whether a pushdown ran) is
    the single source of truth for the filter's semantics, not just an optimization on top of
    it: pyarrow's `greater_equal`/`array_filter` compute kernels have no implementation for its
    canonical `string_view` type, and pyarrow's Parquet dataset scanner can materialize a
    string/large_string column as `string_view` internally while evaluating a pushed-down
    filter — regardless of the column's declared schema type — crashing the scan. So a string
    field's cutoff is only ever checked here, in Python, after the value is materialized;
    pushdown is built only for the timestamp type that isn't affected, as a pure I/O
    optimization. NULLs are kept: a row without the filter field carries no recency signal, and
    the tag-values iterator's per-row cutoff (the semantics this reproduces) keeps them too.

    `physical_column` is the filter field's physical column name; the caller must ensure it's
    projected, even if not requested as output, or the row check would see it as absent and
    keep every row.
    """
    physical = _physical_columns_by_api_name(delta_table, parent_name, [row_filter.field])[row_filter.field]
    field_type = pyarrow_schema_from_arrow_exportable(delta_table.schema()).field(physical).type
    cutoff = row_filter.floor(dt.datetime.now(dt.UTC))

    scan_filter: pc.Expression | None
    floor: dt.datetime | str
    if pa.types.is_timestamp(field_type):
        floor = cutoff if field_type.tz is not None else cutoff.replace(tzinfo=None)
        field_ref = pc.field(physical)
        scan_filter = field_ref.is_null() | (field_ref >= pa.scalar(floor, type=field_type))
    elif pa.types.is_string(field_type) or pa.types.is_large_string(field_type):
        # ISO-8601 UTC strings order lexicographically, so a string floor compares correctly —
        # just not through pyarrow's own kernel (see the missing-kernel note above).
        floor = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        scan_filter = None
    else:
        raise WarehouseParentTableNotFoundError(
            f"Parent table '{parent_name}' stores filter field '{row_filter.field}' as {field_type}, "
            f"which can't be compared against a time floor"
        )

    def _passes_floor(row: dict[str, Any]) -> bool:
        value = row.get(physical)
        return value is None or value >= floor

    return _ResolvedRowFilter(scan_filter=scan_filter, row_passes=_passes_floor, physical_column=physical)


def resolve_parent_table_ref(
    team_id: int,
    source_id: str,
    parent_name: str,
    required_columns: list[str] | None = None,
    row_filter: ParentRowFilter | None = None,
) -> ParentTableRef:
    """Locate the parent schema row, derive its Delta table URI, and pin the current version.

    Does a Django ORM read — call it from sync context at source-build time (e.g. inside
    `source_for_pipeline`), NOT lazily from the pipeline's iterator executor threads, whose
    ad-hoc DB connections are exactly the pooler-drop failure mode `ExternalDataSchema.save`
    documents. The storage leaf comes from `normalized_s3_folder_name`, the same property the
    writer resolves, so legacy-migrated rows land on the same table either side.

    The version is pinned here rather than at first read: the read is lazy and can start minutes
    into the pipeline, by which time a full-refresh parent may be mid-rewrite (overwrite + appends
    across several commits). Pinning means later parent commits are invisible to this run — the
    child fans out over one complete snapshot instead of a torn one.

    A parent whose newest job is not COMPLETED doesn't block the child: the pin rolls back
    to the version as of the parent's last completed job (Delta time travel), which is a
    complete snapshot by definition. That covers a writer that is mid-sync and one that
    failed mid-write, whose torn overwrite+appends would otherwise be the table's latest
    version with no RUNNING row to betray it. A rollback target older than
    `MAX_SNAPSHOT_ROLLBACK` is refused instead, keeping the pin inside the window where its
    files are safe from vacuum. What remains is clock skew: the rollback compares Postgres
    `finished_at` against Delta commit timestamps stamped by (possibly different) worker
    clocks, so backward skew exceeding the final-commit-to-`finished_at` gap could pull an
    in-flight commit under the pin. That surfaces as a retryable read failure, not corrupt
    data.

    Only ever raises WarehouseParentTableNotFoundError: callers treat it as the
    fall-back-to-the-API signal, so an unexpected error here (S3, a corrupt Delta log, a
    malformed source_id) must become that signal too, not fail the run past their handler.
    """
    try:
        parent_schema = get_schema_if_exists(parent_name, team_id, uuid.UUID(source_id))
        if parent_schema is None:
            raise WarehouseParentTableNotFoundError(
                f"Parent schema '{parent_name}' does not exist for source {source_id}"
            )
        uri = build_delta_table_uri(parent_schema.folder_path(), parent_schema.normalized_s3_folder_name)

        storage_options = delta_storage_options()
        if not deltalake.DeltaTable.is_deltatable(uri, storage_options=storage_options):
            raise WarehouseParentTableNotFoundError(
                f"Parent schema '{parent_name}' has no synced table yet — complete its initial sync first"
            )
        delta_table = deltalake.DeltaTable(uri, storage_options=storage_options)

        as_of = _snapshot_pin_as_of(team_id, parent_schema.id)
        if as_of is not None:
            delta_table.load_as_version(as_of)
        if required_columns:
            # Validate eagerly: the reader is a generator, so a missing column would otherwise
            # surface deep inside the pipeline, past the caller's fall-back-to-the-API branch.
            _physical_columns_by_api_name(delta_table, parent_name, required_columns)
        if row_filter is not None:
            # Same eagerness for the filter: the reader rebuilds this, but a missing or
            # unfilterable column must surface while the API fallback is still possible.
            _row_filter_scan_and_predicate(delta_table, parent_name, row_filter)
        return ParentTableRef(uri=uri, version=delta_table.version())
    except WarehouseParentTableNotFoundError:
        raise
    except Exception as e:
        raise WarehouseParentTableNotFoundError(f"Parent table '{parent_name}' could not be resolved: {e}") from e


def try_resolve_parent_table(
    *,
    team_id: int,
    source_id: str,
    parent_name: str,
    required_columns: list[str],
    schema_name: str,
    row_filter: ParentRowFilter | None = None,
) -> ParentTableRef | None:
    """Resolve the parent table, or None when this run must read the parent from the API.

    The fallback branch every caller needs, in one place: `resolve_parent_table_ref` raises
    only `WarehouseParentTableNotFoundError`, so None covers a missing, unreadable, or
    too-stale parent table. Callers must treat None as "use the API parent", including any
    behavior that only makes sense over a warehouse snapshot.
    """
    try:
        return resolve_parent_table_ref(
            team_id, source_id, parent_name, required_columns=required_columns, row_filter=row_filter
        )
    except WarehouseParentTableNotFoundError:
        # Same event name as the run-time gate's fallback log, so one stream covers every
        # fallback class.
        logger.warning(
            "data_imports.fanout_parent_unusable",
            schema=schema_name,
            parent=parent_name,
            reason="table_unreadable",
            exc_info=True,
        )
        return None


def parent_snapshot_covers_through(team_id: int, source_id: str, parent_name: str) -> dt.datetime | None:
    """How far the parent's data is guaranteed complete, or None if it has never completed a sync.

    A child that derives its next scan floor from its own rows has to cap what it emits at this
    value, or the floor advances past parent changes the snapshot could not show it yet and they
    are never scanned again.

    This is when the parent's last completed sync *started*, not when it finished. A sync reads
    each row at some point between those two, so a row read early carries the state it had then,
    and a parent change landing later in the same sync may be missing from the snapshot entirely.
    Only changes from before the sync started are guaranteed to be in it. `finished_at` is the
    right stamp for picking a Delta version (see `_snapshot_pin_as_of`) and the wrong one for
    coverage; they are different quantities.

    Call this BEFORE resolving the table, never after. A sync completing between the two reads
    then leaves the cap on the older job while the pinned snapshot holds the newer one, which errs
    toward emitting too little. Reversing the order errs toward emitting rows the snapshot never
    covered, which is the bug this exists to prevent.
    """
    try:
        parent_schema = get_schema_if_exists(parent_name, team_id, uuid.UUID(source_id))
    except (ValueError, AttributeError):
        return None
    if parent_schema is None:
        return None
    return (
        ExternalDataJob.objects.filter(
            team_id=team_id,
            schema_id=parent_schema.id,
            status=ExternalDataJob.Status.COMPLETED,
            finished_at__isnull=False,
        )
        .order_by("-finished_at")
        .values_list("created_at", flat=True)
        .first()
    )


def _snapshot_pin_as_of(team_id: int, parent_schema_id: uuid.UUID) -> dt.datetime | None:
    """The timestamp to time-travel the parent table to, or None to read its latest version.

    Raises rather than returning a pin that can't be trusted, so the caller falls back to the
    parent API.

    None means "read the latest version", which is right when the parent's newest job
    COMPLETED: commits after it are maintenance (compaction), and pinning behind a compaction
    can point at files a later vacuum removed. A newest job that is RUNNING or terminally
    failed may instead have left a torn overwrite+appends as the latest version, so the read
    rolls back to the last completed snapshot. The completed-job timestamp deliberately comes
    from Postgres, not the Delta log: `finished_at` is stamped strictly after the job's final
    commit, so every commit at or before it belongs to a finished run.

    The COMPLETED-newest case is not airtight — `update_external_job_status` documents a
    lock-takeover where a zombie loader keeps writing after its job was force-failed and a
    newer job completed, so a writer can still be live. That yields one torn parent list and
    self-heals on the next run, which is why it doesn't force a rollback here.

    A rollback target older than MAX_SNAPSHOT_ROLLBACK is refused. A parent that fails every
    attempt would otherwise pin children to an ever-older snapshot while its retries keep
    tombstoning and vacuuming those files, and the resulting missing-file error surfaces
    inside the reader's generator, past the caller's fallback.
    """
    newest_job_status = (
        ExternalDataJob.objects.filter(team_id=team_id, schema_id=parent_schema_id)
        .order_by("-created_at")
        .values_list("status", flat=True)
        .first()
    )
    if newest_job_status is None or newest_job_status == ExternalDataJob.Status.COMPLETED:
        return None
    last_completed = (
        ExternalDataJob.objects.filter(
            team_id=team_id,
            schema_id=parent_schema_id,
            status=ExternalDataJob.Status.COMPLETED,
            # Postgres sorts NULLs first on a descending order_by, and jobs predating the
            # `finished_at` column still carry NULL — without this, `.first()` returns one of
            # those and hides every newer completed job.
            finished_at__isnull=False,
        )
        .order_by("-finished_at")
        .values_list("finished_at", flat=True)
        .first()
    )
    if last_completed is None:
        # No completed job to pin to (e.g. purged history) while the latest version can't be
        # trusted — let the caller fall back to the API.
        raise WarehouseParentTableNotFoundError("Parent schema has no completed job to snapshot from")
    if dt.datetime.now(dt.UTC) - last_completed > MAX_SNAPSHOT_ROLLBACK:
        raise WarehouseParentTableNotFoundError(
            f"Parent schema's last completed sync finished {last_completed.isoformat()}, "
            f"beyond the window where its files are guaranteed to survive vacuum"
        )
    return last_completed


def iter_parent_pages_from_warehouse(
    *,
    table: ParentTableRef,
    parent_name: str,
    columns: list[str],
    page_size: int,
    schema_name: str,
    row_filter: ParentRowFilter | None = None,
) -> Generator[list[dict[str, Any]]]:
    """Yield fan-out parent rows from the parent schema's already-synced Delta table.

    Pages are shaped like the REST parent pages the dependent-resource machinery consumes
    (`list[dict]` keyed by the parent API's field names), so a child resource can be driven by
    this iterator instead of re-pulling the parent endpoint. Values are NOT identical to the
    API's: they carry the Delta column's physical type, so a timestamp comes back as a
    datetime rather than the API's ISO string, and a nested object as a dict. Only project
    `include_from_parent` fields whose physical type matches what the API returned, or the
    child table's column type will flip between runs as the API fallback engages.

    Reads the version pinned by `resolve_parent_table_ref`, so a parent re-syncing during the
    (potentially long) fan-out can't shift the rows underneath it.

    `columns` are API field names (e.g. ``lastSeen``); the Delta writer stores snake_case
    identifiers, so each is normalized to locate the physical column and rows are re-keyed
    back to the API names.

    Strictly streaming: the scan holds one projected batch in memory at a time, with column
    projection pushed down to the parquet read. No sorting, no dedupe state — rows are
    assumed unique per parent, which holds for merge/full-refresh parents by construction;
    append-mode parents accumulate duplicates, so the run-time check in
    `import_data_activity_sync` sends them down the parent-API path instead of here. Do not
    add whole-table materialization (`to_table`, global sorts, seen-sets) — parents can be
    arbitrarily large.
    """
    page_size = max(1, min(page_size, MAX_PARENT_PAGE_SIZE))
    delta_table = deltalake.DeltaTable(table.uri, version=table.version, storage_options=delta_storage_options())
    physical_by_api_name = _physical_columns_by_api_name(delta_table, parent_name, columns)

    resolved_row_filter: _ResolvedRowFilter | None = None
    projected = list(dict.fromkeys(physical_by_api_name.values()))
    if row_filter is not None:
        resolved_row_filter = _row_filter_scan_and_predicate(delta_table, parent_name, row_filter)
        if resolved_row_filter.physical_column not in projected:
            # The row check below needs the value even when the caller didn't ask for it as
            # output — otherwise it reads as absent and every row would pass.
            projected.append(resolved_row_filter.physical_column)

    scan_filter = resolved_row_filter.scan_filter if resolved_row_filter is not None else None

    dataset = delta_table.to_pyarrow_dataset()

    rows_streamed = 0
    outcome = "failed"
    try:
        page: list[dict[str, Any]] = []
        for batch in dataset.to_batches(columns=projected, batch_size=page_size, filter=scan_filter):
            for row in batch.to_pylist():
                if resolved_row_filter is not None and not resolved_row_filter.row_passes(row):
                    continue
                page.append({api_name: row.get(physical) for api_name, physical in physical_by_api_name.items()})
                rows_streamed += 1
                if len(page) >= page_size:
                    yield page
                    page = []
        if page:
            yield page
        outcome = "completed"
    except GeneratorExit:
        outcome = "stopped"
        raise
    finally:
        # In a `finally` because a consumer can stop early: a resumable child checkpoints
        # mid-fan-out, and the pipeline's iterator cleanup closes this generator, which raises
        # GeneratorExit at the `yield` above. Logging after the loop would lose those runs
        # entirely. Only `completed` carries a full row count; a `stopped` or `failed` scan must
        # not be read as a shrinking snapshot.
        #
        # The snapshot only grows for an incremental parent, while the vendor's own listing
        # drops rows past its retention. This count against the child's ignored stale-parent
        # responses is how we tell whether the fan-out set has drifted above what the API
        # would return — see the reuse follow-up in the plan.
        logger.info(
            "data_imports.fanout_parent_rows_streamed",
            schema=schema_name,
            parent=parent_name,
            rows=rows_streamed,
            version=table.version,
            outcome=outcome,
            filtered=row_filter is not None,
        )
