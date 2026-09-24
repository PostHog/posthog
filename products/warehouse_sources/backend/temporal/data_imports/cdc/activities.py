"""CDC Temporal activities.

cdc_extract_activity: Core extraction. Reads the WAL, decodes and batches it, and writes each
table's changes to the S3 change buffer, which the table's own scheduled sync consumes. A
snapshotting table's changes wait there until its snapshot completes.

validate_cdc_prerequisites_activity: Wraps prerequisite validator for Temporal.
"""

from __future__ import annotations

import time
import uuid
import typing
import datetime as dt
import dataclasses
from collections.abc import Callable

from django.db import InterfaceError, OperationalError, close_old_connections

import pyarrow as pa
import structlog
import pyarrow.compute as pc
import posthoganalytics
from temporalio import activity

from posthog.temporal.common.errors import NonReportableError
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    CDC_SNAPSHOT_LANE_KEY,
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc import metrics
from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import (
    cdc_supported_source_types,
    get_cdc_adapter,
    source_type_supports_cdc,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_SEQ_COLUMN,
    ChangeEventBatcher,
    enrich_delete_rows,
    enrich_toast_omitted_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.broken import (
    SELF_MANAGED_LAG_REASON,
    clear_recovered_self_managed_lag,
    mark_cdc_broken,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import CDCBufferWriter, purge_buffer_prefix
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import (
    MAX_FRIENDLY_MESSAGE_LENGTH,
    CDCErrorCategory,
    CDCErrorInfo,
    CDCReservedColumnError,
    CDCSlotNotConfiguredError,
    classify_cdc_error,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.legacy_conversion import convert_legacy_cdc_state
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import has_engine_seq
from products.warehouse_sources.backend.temporal.data_imports.cdc.naming import (
    CDC_EXTRACTION_WORKFLOW_ID_PREFIX,
    cdc_qualified_table_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import (
    BUFFER_LANE,
    cancel_running_sync,
    snapshot_in_buffer,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    captures_to_buffer,
    snapshot_can_start_in_buffer,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    _build_schema_snapshot,
)

logger = structlog.get_logger(__name__)

# Shown as latest_error on schemas reset by slot-invalidation recovery.
SLOT_INVALIDATION_RECOVERY_MESSAGE = (
    "The source database invalidated this source's replication slot (its WAL retention limit was "
    "exceeded), so changes since the last successful sync could not be read. PostHog recreated the "
    "slot and scheduled a full re-sync of this table; change data capture resumes automatically "
    "once the re-sync completes."
)

# The sweeper's auto-drop must fire below the engine's own retention cap, otherwise the
# engine invalidates the slot first and we lose the chance to act cleanly.
RETENTION_CAP_SAFETY_FACTOR = 0.8

# Mirrors maximum_attempts on CDCExtractionWorkflow's retry policy (workflows.py). On the final
# attempt a failure won't be retried, so it's the last chance to record a visible failed-run row.
CDC_MAX_EXTRACTION_ATTEMPTS = 3

# How long an unchanged failure suppresses further visibility rows for a schema. A source that stays
# unreachable re-fails on every tick, and the schedule retries each failed tick at the workflow level
# too (maximum_attempts on the schedule's action), so a 10-minute source would otherwise stamp the
# same row per schema several times an hour for as long as the outage lasts. The schema's own status
# and latest_error are refreshed every run regardless — these rows are sync history, and repeating an
# identical one says nothing new while burying the runs that do.
CDC_FAILURE_VISIBILITY_COOLDOWN = dt.timedelta(hours=1)

# Per-peek bound on WAL changes. A large backlog is drained over several passes (and, if needed,
# several scheduled runs) instead of one unbounded read that risks the 2h activity timeout and
# re-decodes from the slot start on every retry. The slot advances after each pass, so the next
# peek resumes where this one stopped.
CDC_MAX_CHANGES_PER_READ = 100_000
# Ceiling for the adaptive growth below. A peek never splits a transaction, so this window does not
# bound a large one; the decoder spills it to disk, capped by MAX_TX_BUFFER_EVENTS and MAX_TX_SPILL_BYTES.
CDC_MAX_CHANGES_LIMIT_CAP = 800_000
# Stop starting new peeks past this wall-clock so the final flush + slot advance fit inside the
# activity's 2h start-to-close timeout (see CDCExtractionWorkflow). The remainder is picked up on
# the next scheduled run.
CDC_READ_SOFT_DEADLINE_SECONDS = 90 * 60
# Heartbeat at most this often while fetching WAL rows (the activity heartbeat timeout is 10m).
CDC_READ_HEARTBEAT_INTERVAL_SECONDS = 30.0


@dataclasses.dataclass
class CDCExtractInput:
    team_id: int
    source_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "source_id": str(self.source_id),
        }


@dataclasses.dataclass
class ValidateCDCPrerequisitesInput:
    team_id: int
    source_id: uuid.UUID
    management_mode: str
    tables: list[str]
    schema: str
    slot_name: str | None
    publication_name: str | None


class CDCExtractActivity:
    """Object-oriented body of cdc_extract_activity.

    All shared state lives on the instance. ``run()`` orchestrates the high
    level steps; private methods implement individual phases.
    """

    def __init__(self, inputs: CDCExtractInput) -> None:
        self.inputs = inputs
        self.log: structlog.types.FilteringBoundLogger = logger.bind(
            team_id=inputs.team_id, source_id=str(inputs.source_id)
        )

        # Populated during run().
        self.source: ExternalDataSource | None = None
        self.cdc_schemas: list[ExternalDataSchema] = []
        self.schema_by_name: dict[str, ExternalDataSchema] = {}
        self.pk_columns_by_table: dict[str, list[str]] = {}
        # Missing entry = sync all columns; otherwise the set is the projection (always includes PKs).
        self.enabled_columns_by_table: dict[str, set[str]] = {}
        self.adapter: typing.Any = None
        self.reader: typing.Any = None
        self.batcher: ChangeEventBatcher | None = None
        self.last_end_lsn: str | None = None
        self.last_confirmed_lsn: str | None = None
        # Transaction-boundary tracking for safe mid-run slot advances. All events of
        # one transaction share the same commit end LSN (position_serialized), so an LSN
        # change marks a fully-yielded transaction. We only ever micro-advance the slot
        # past transactions that are completely yielded — see _read_wal_loop.
        self.current_txn_lsn: str | None = None
        self.last_complete_txn_end_lsn: str | None = None
        # End of WAL before this run peeked, and whether the peek reached the end of the backlog.
        # Together they let a run that decoded nothing still release the WAL it examined — see
        # _handle_no_changes.
        self._pre_read_position: str | None = None
        self._backlog_drained: bool = False
        self.event_count: int = 0
        self.all_table_names: set[str] = set()
        # Wall-clock start, set in run(); drives cdc_extraction_duration_seconds.
        self._run_started_at: float | None = None
        # Writer is lazy so runs that buffer nothing never touch S3 setup; the per-schema file index
        # keeps same-position-range batches (a split transaction) from overwriting each other.
        self._buffer_writer: CDCBufferWriter | None = None
        self._buffer_file_index: dict[str, int] = {}
        self._buffer_cleaned_schemas: set[str] = set()
        # Table names whose changes this run writes to the buffer. Resolved once in _setup.
        self._buffered_table_names: set[str] = set()
        self._truncated_tables: list[str] = []

    # ------------------------------------------------------------------
    # Logger helpers
    # ------------------------------------------------------------------
    def _schema_log(self, schema: ExternalDataSchema) -> structlog.types.FilteringBoundLogger:
        """Logger bound with per-schema `log_source_id` so lines route under the schema in the Syncs UI."""
        return self.log.bind(log_source_id=str(schema.id))

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------
    def _emit_run_duration(self, status: str) -> None:
        if self._run_started_at is None:
            return
        metrics.get_extraction_duration_metric(self.inputs.team_id, str(self.inputs.source_id), status).record(
            time.monotonic() - self._run_started_at
        )

    def _confirm_position(self, lsn: str) -> None:
        """Advance the replication slot, recording success/failure metrics."""
        source_id = str(self.inputs.source_id)
        try:
            self.reader.confirm_position(lsn)
        except Exception:
            metrics.get_slot_advance_failures_metric(self.inputs.team_id, source_id).add(1)
            raise
        metrics.get_slot_advance_metric(self.inputs.team_id, source_id).add(1)

    # ------------------------------------------------------------------
    # Schema fetching (kept as a method so tests can patch it on the class)
    # ------------------------------------------------------------------
    def _get_cdc_schemas(self) -> list[ExternalDataSchema]:
        """Get all active CDC schemas for the source."""
        return list(
            ExternalDataSchema.objects.filter(
                source=self.source,
                sync_type=ExternalDataSchema.SyncType.CDC,
                should_sync=True,
            ).exclude(deleted=True)
        )

    # ------------------------------------------------------------------
    # sync_type_config persistence (locked merge, see update_sync_type_config_keys)
    # ------------------------------------------------------------------
    def _update_schema_sync_type_config(
        self,
        schema: ExternalDataSchema,
        *,
        updates: dict[str, typing.Any] | None = None,
        removes: list[str] | None = None,
        mutate: Callable[[dict[str, typing.Any]], None] | None = None,
        extra_model_fields: dict[str, typing.Any] | None = None,
    ) -> None:
        """Persist a `sync_type_config` change through the locked-merge helper, then refresh the
        in-memory copy from the returned dict.

        Every `sync_type_config` write in this activity goes through here so the long-lived
        in-memory schema can't clobber a concurrent API PATCH (or another writer) — the merge
        re-reads the row under a lock instead of overwriting it wholesale.
        """
        schema.sync_type_config = update_sync_type_config_keys(
            schema.id,
            schema.team_id,
            updates=updates,
            removes=removes,
            mutate=mutate,
            extra_model_fields=extra_model_fields,
        )
        if extra_model_fields:
            for field, value in extra_model_fields.items():
                setattr(schema, field, value)

    # ------------------------------------------------------------------
    # Buffer writes
    # ------------------------------------------------------------------
    def _write_buffer_file(self, schema: ExternalDataSchema, table_name: str, table: pa.Table) -> None:
        """Write one micro-batch to the S3 change buffer. Raises on failure: the buffer is the only
        delivery, and the slot is about to advance past these changes.
        """
        file_index = self._buffer_file_index.get(table_name, 0)
        if self._buffer_writer is None:
            self._buffer_writer = CDCBufferWriter(self.log)

        schema_id = str(schema.id)
        if schema_id not in self._buffer_cleaned_schemas:
            # First write this run: remove files a superseded attempt left at or
            # past where this run restarted (batch boundaries are not stable
            # across attempts — see buffer.py). The batch's min seq IS the
            # restart floor for this schema.
            restart_seq = pc.min(table.column(CDC_SEQ_COLUMN)).as_py()
            self._buffer_writer.cleanup_superseded_files(
                team_id=schema.team_id, schema_id=schema_id, restart_seq=restart_seq
            )
            self._buffer_cleaned_schemas.add(schema_id)

        result = self._buffer_writer.write_batch(
            team_id=schema.team_id,
            schema_id=schema_id,
            table=table,
            file_index=file_index,
        )
        self._buffer_file_index[table_name] = file_index + 1

        metrics.get_buffer_files_written_metric(self.inputs.team_id, str(self.inputs.source_id)).add(1)
        metrics.get_buffer_write_duration_metric(self.inputs.team_id, str(self.inputs.source_id)).record(
            result.write_duration_seconds
        )
        self._schema_log(schema).debug(
            "cdc_buffer_written",
            table=table_name,
            s3_path=result.s3_path,
            rows=result.row_count,
            start_seq=result.start_seq,
            end_seq=result.end_seq,
        )

    # ------------------------------------------------------------------
    # Per-flush processing
    # ------------------------------------------------------------------
    def _process_flush(self, tables: dict[str, pa.Table]) -> None:
        """Enrich one micro-batch and write each captured table's changes to the S3 change buffer."""
        events_extracted = 0

        for table_name, raw_table in tables.items():
            schema = self.schema_by_name.get(table_name)
            if schema is None or table_name not in self._buffered_table_names:
                continue

            self._safe_heartbeat()

            # raw_table has one row per source change event.
            events_extracted += raw_table.num_rows

            key_columns = self.pk_columns_by_table.get(table_name, [])

            # TOAST fill first so DELETE enrichment copies resolved values, not the
            # nulls standing in for omitted columns.
            enriched_table = enrich_toast_omitted_rows(raw_table, key_columns)
            enriched_table = enrich_delete_rows(enriched_table, key_columns)
            if not enriched_table.num_rows:
                continue

            # A source column named _ph_cdc_seq means the batcher could not append the
            # engine position; writing anyway would name, order, and clean up files by
            # customer data — cleanup can then delete unconsumed files (see errors.py).
            if not has_engine_seq(enriched_table):
                raise CDCReservedColumnError(f"Table {table_name} has a source column named {CDC_SEQ_COLUMN}")
            self._write_buffer_file(schema, table_name, enriched_table)

        if events_extracted:
            metrics.get_events_extracted_metric(self.inputs.team_id, str(self.inputs.source_id)).add(events_extracted)

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Core CDC extraction.

        1. Connect to source PG, read all pending WAL changes
        2. Decode and batch by table
        3. Write each captured table's changes to the S3 change buffer
        4. Advance slot position
        5. Update cdc_last_log_position per schema
        """
        close_old_connections()
        self._run_started_at = time.monotonic()
        self.log.info("cdc_extract_started")

        try:
            if not self._setup():
                return
        except (OperationalError, InterfaceError) as exc:
            # `_setup` only reads our own app DB (source + schema rows), never a customer's — every
            # CDC source is read over a raw driver connection, not Django's ORM — so this can only be
            # a transient connection-pool blip on our side (e.g. PgBouncer dropping an idle
            # connection), the same class already re-raised as `NonReportableError` for own-DB blips
            # in import_data_sync.py. Temporal's retry policy isn't `NonRetryableException`-gated
            # here, so it still retries; this only keeps a self-resolving blip out of error tracking.
            self.log.warning("cdc_setup_transient_app_db_error", exc_info=True)
            raise NonReportableError(str(exc)) from exc

        try:
            self._prepare_buffer()
            self._require_configured_slot()
            self.reader.connect()
            # Taken before the peek, so anything committed after it stays above this position and
            # is decoded by a later run.
            self._pre_read_position = self.reader.current_position()

            self._load_pk_columns()
            self._read_wal_loop()

            self.log.info("wal_changes_read", event_count=self.event_count, tables=list(self.all_table_names))

            self._detect_pk_changes_post_wal()
            truncated_tables = self._handle_truncates()

            if self.event_count == 0:
                self._handle_no_changes(truncated_tables)
                return

            self._final_flush()
            self._advance_slot_after_run()
            self._update_log_positions()

        except Exception as exc:
            if self.adapter is not None and self.adapter.is_slot_invalidation_error(exc):
                try:
                    self._recover_from_slot_invalidation(exc)
                    self._emit_run_duration("recovered")
                    return
                except Exception as recovery_exc:
                    self.log.exception("cdc_slot_recovery_failed")
                    self._fail(recovery_exc)
            self._fail(exc)
        finally:
            if self.reader is not None:
                self.reader.close()

        self._finalize_success()
        self.log.info("cdc_extract_completed", event_count=self.event_count)

    # ------------------------------------------------------------------
    # Setup phase
    # ------------------------------------------------------------------
    def _setup(self) -> bool:
        """Load source + schemas + adapter. Returns False if there's nothing to do.

        Self-cleans the Temporal schedule if the source is deleted or has no
        active CDC schemas — otherwise the workflow keeps firing forever.
        """
        try:
            self.source = ExternalDataSource.objects.get(pk=self.inputs.source_id)
        except ExternalDataSource.DoesNotExist:
            self.log.info("source_not_found_deleting_schedule")
            self._delete_own_schedule()
            return False

        if self.source.deleted:
            self.log.info("source_soft_deleted_deleting_schedule")
            self._delete_own_schedule()
            return False

        if not source_type_supports_cdc(self.source.source_type):
            # No adapter means no change stream to read, so every tick of this schedule can only
            # fail. Delete it instead of reporting the same failure once per interval for as long
            # as the source lives. `sync_cdc_extraction_schedule` refuses to create it again.
            self.log.info("source_type_does_not_support_cdc_deleting_schedule", source_type=self.source.source_type)
            self._delete_own_schedule()
            return False

        self.cdc_schemas = self._get_cdc_schemas()
        if not self.cdc_schemas:
            self.log.info("no_active_cdc_schemas_deleting_schedule")
            self._delete_own_schedule()
            return False

        self.schema_by_name = {s.name: s for s in self.cdc_schemas}
        self.adapter = get_cdc_adapter(self.source)
        self.reader = self.adapter.create_reader(self.source)

        # Guarded like the metric meter: CDC activity bodies are also exercised by direct
        # instantiation outside an activity context, where activity.info() raises.
        attempt = activity.info().attempt if activity.in_activity() else 1
        if attempt > 1:
            metrics.get_extract_retry_metric(self.inputs.team_id, str(self.inputs.source_id)).add(1)
            self.log.info("cdc_extract_retry_attempt", attempt=attempt)
        return True

    def _prepare_buffer(self) -> None:
        """Convert leftover legacy state and start pending snapshots in the buffer, before the WAL read."""
        assert self.source is not None and self.adapter is not None
        convert_legacy_cdc_state(
            self.source,
            self.cdc_schemas,
            ingest_mode=self.adapter.parse_cdc_config(self.source).ingest_mode,
            logger=self.log,
        )

        for schema in self.cdc_schemas:
            if not captures_to_buffer(schema):
                # No lane writes this table mode, so the buffer could never deliver its changes.
                self._schema_log(schema).warning("cdc_table_mode_not_captured", cdc_table_mode=schema.cdc_table_mode)
                continue
            if (schema.sync_type_config or {}).get("cdc_deferred_runs"):
                # Conversion restarts this snapshot once the old sync stops, and the new one re-reads the table.
                # Starting it in the buffer now would let the old sync hand over without its deferred changes.
                continue
            if snapshot_can_start_in_buffer(schema):
                self._start_snapshot_in_buffer(schema)
            self._buffered_table_names.add(schema.name)
        self.log.info("cdc_buffered_ingress_active", buffered=sorted(self._buffered_table_names))

    def _start_snapshot_in_buffer(self, schema: ExternalDataSchema) -> None:
        """Start carrying a snapshotting table's changes in the buffer.

        Runs before this run reads the WAL, so no change for the table has been captured since its
        snapshot began. Its buffer is emptied first: files left from before a gap in capture, such as
        a re-enable, must not be replayed over the snapshot.
        """
        purge_buffer_prefix(schema.team_id, str(schema.id), self._schema_log(schema), strict=True)

        def _mark_if_still_snapshotting(config: dict[str, typing.Any]) -> None:
            # Read under the row lock. A hand-over that flipped the table to streaming after this run
            # loaded it has already cleared the marker, and a new one would outlive the snapshot. The
            # table's changes still belong in the buffer, which its streaming consumer now reads.
            if config.get("cdc_mode") == "snapshot":
                config[CDC_SNAPSHOT_LANE_KEY] = BUFFER_LANE

        self._update_schema_sync_type_config(schema, mutate=_mark_if_still_snapshotting)
        self._schema_log(schema).info(
            "cdc_snapshot_started_in_buffer", schema_id=str(schema.id), marked=snapshot_in_buffer(schema)
        )

    def _delete_own_schedule(self) -> None:
        try:
            from products.data_warehouse.backend.facade.api import delete_cdc_extraction_schedule

            delete_cdc_extraction_schedule(str(self.inputs.source_id))
        except Exception:
            self.log.exception("failed_to_delete_own_schedule")

    # ------------------------------------------------------------------
    # PK column loading
    # ------------------------------------------------------------------
    def _load_pk_columns(self) -> None:
        """Build PK map from schema metadata, falling back to information_schema."""
        assert self.source is not None
        cdc_table_names = {s.name for s in self.cdc_schemas}

        # Build PK map from schema metadata (stored at source creation)
        for schema in self.cdc_schemas:
            stored_pks = schema.sync_type_config.get("primary_key_columns", [])
            if stored_pks:
                self.pk_columns_by_table[schema.name] = stored_pks

        # Fall back to information_schema for any tables missing PKs
        missing_pk_tables = [t for t in cdc_table_names if t not in self.pk_columns_by_table]
        if missing_pk_tables:
            queried_pks = self._query_pk_columns(missing_pk_tables)
            self.pk_columns_by_table.update(queried_pks)
            # Persist discovered PKs to avoid re-querying
            for schema in self.cdc_schemas:
                if schema.name not in queried_pks:
                    continue
                # Only schemas with no stored key reach here, so this is always a first write. Its
                # table merged on an empty key until now, which means the rows already in it were
                # never keyed. Log it so an operator can decide whether that table needs a
                # re-snapshot rather than having the merge key appear from nowhere.
                self._schema_log(schema).warning(
                    "cdc_pk_columns_first_write", table=schema.name, discovered=queried_pks[schema.name]
                )
                self._update_schema_sync_type_config(schema, updates={"primary_key_columns": queried_pks[schema.name]})

        self.log.info("pk_columns_loaded", tables=list(self.pk_columns_by_table.keys()))

        for schema in self.cdc_schemas:
            enabled = schema.enabled_columns
            # `None` = sync all; `[]` = retain PKs + incremental only. Match the
            # invariant used by build_select_clause / pipeline_sync / filter_dwh_columns.
            if isinstance(enabled, list):
                retained: set[str] = {str(c) for c in enabled}
                # PKs must stay even if the user dropped them from enabled_columns — merges break otherwise.
                for pk in self.pk_columns_by_table.get(schema.name, []):
                    retained.add(pk)
                inc = schema.incremental_field
                if isinstance(inc, str) and inc:
                    retained.add(inc)
                self.enabled_columns_by_table[schema.name] = retained

    def _query_pk_columns(self, table_names: list[str]) -> dict[str, list[str]]:
        """Look up primary keys in the source catalog, keyed back on `ExternalDataSchema.name`.

        Schema names are qualified (`schema.table`) while the catalog lookup takes one namespace
        plus bare relation names, so a name has to be split for the query and rejoined for the
        result. Passing the qualified name straight through matched no catalog row, so any schema
        without a stored primary key fell back to an empty merge key. Splitting on the first dot and
        defaulting to the source's namespace matches how the tables are resolved when they are added
        to the publication.
        """
        assert self.source is not None
        default_namespace = (self.source.job_inputs or {}).get("schema", "public")
        names_by_namespace: dict[str, dict[str, str]] = {}
        for name in table_names:
            namespace, dot, relation = name.partition(".")
            if not dot:
                namespace, relation = default_namespace, name
            names_by_namespace.setdefault(namespace, {})[relation] = name

        resolved: dict[str, list[str]] = {}
        for namespace, relations_by_name in names_by_namespace.items():
            queried = self.reader.get_primary_key_columns(namespace, list(relations_by_name))
            for relation, pk_columns in queried.items():
                resolved[relations_by_name[relation]] = pk_columns
        return resolved

    def _project_event_columns(self, event: ChangeEvent) -> ChangeEvent:
        retained = self.enabled_columns_by_table.get(event.table_name)
        if retained is None:
            return event
        filtered = {name: value for name, value in event.columns.items() if name in retained}
        # Omitted (unchanged-TOAST) markers for disabled columns must go too, or the
        # batcher would materialize a disabled column just to carry the marker.
        filtered_omitted = frozenset(name for name in event.omitted_columns if name in retained)
        if filtered.keys() == event.columns.keys() and filtered_omitted == event.omitted_columns:
            return event
        return ChangeEvent(
            operation=event.operation,
            table_name=event.table_name,
            position_serialized=event.position_serialized,
            timestamp=event.timestamp,
            columns=filtered,
            column_types=event.column_types,
            omitted_columns=filtered_omitted,
        )

    def _qualified_table_name(self, schema: ExternalDataSchema) -> str:
        default_schema = (self.source.job_inputs or {}).get("schema") if self.source else None
        return cdc_qualified_table_name(schema, default_schema)

    def _build_event_name_map(self) -> dict[str, str]:
        """Map each schema's source-qualified `schema.table` name to its stored `name`.

        WAL events are always qualified (`public.orders`) but `name` may be stored bare
        (`orders`), so an exact-equality match silently drops every change for a bare row.
        """
        mapping: dict[str, str] = {}
        for schema in self.cdc_schemas:
            mapping[self._qualified_table_name(schema)] = schema.name
            mapping.setdefault(schema.name, schema.name)  # also match a bare-emitted name
        return mapping

    # ------------------------------------------------------------------
    # WAL read loop with periodic micro-batch flushes
    # ------------------------------------------------------------------
    def _safe_heartbeat(self, *details: typing.Any) -> None:
        """Heartbeat is a best-effort liveness signal, not a required step. The SDK relays a
        sync activity's heartbeat through the worker's event loop with its own short internal
        timeout, and a transient miss there must never abort an otherwise-healthy multi-hour
        WAL read.
        """
        try:
            activity.heartbeat(*details)
        except Exception:
            self.log.debug("cdc_heartbeat_failed", exc_info=True)

    def _make_read_heartbeat(self) -> Callable[[], None]:
        """Throttled ``activity.heartbeat`` for ``read_changes``' per-row callback.

        The decoder yields nothing until a COMMIT, so a single large transaction would
        otherwise starve the 10m heartbeat timeout while it is being fetched. Throttled by
        wall-clock to avoid a heartbeat call on every WAL row.
        """
        last_heartbeat = 0.0

        def heartbeat() -> None:
            nonlocal last_heartbeat
            now = time.monotonic()
            if now - last_heartbeat >= CDC_READ_HEARTBEAT_INTERVAL_SECONDS:
                self._safe_heartbeat()
                last_heartbeat = now

        return heartbeat

    def _read_wal_loop(self) -> None:
        """Read WAL events with periodic micro-batch flushes, bounded per peek.

        Each pass peeks at most ``CDC_MAX_CHANGES_PER_READ`` changes so a large backlog can't
        push the activity past its 2h timeout. When a pass returns a full page, the slot is
        advanced past everything it committed and another pass runs, until the backlog drains,
        the soft deadline hits, or (defensively) the limit cap is reached.

        Each flush writes the buffer before the slot advances past it, so a long extraction never
        replays committed events on the next run.
        """
        assert self._run_started_at is not None
        assert self.adapter is not None
        event_name_to_schema_name = self._build_event_name_map()
        self.batcher = ChangeEventBatcher(position_to_seq=self.adapter.position_to_seq)
        on_row = self._make_read_heartbeat()

        limit = CDC_MAX_CHANGES_PER_READ
        while True:
            for event in self.reader.read_changes(upto_nchanges=limit, on_row=on_row):
                self._safe_heartbeat()

                # Resolve to the schema's stored `name` so downstream keying lines up. Log
                # unmatched drops: a silent drop here is how a name mismatch starves a table.
                canonical_name = event_name_to_schema_name.get(event.table_name)
                if canonical_name is None:
                    self.log.debug("cdc_event_dropped_unmatched_table", table=event.table_name)
                    continue
                if canonical_name != event.table_name:
                    event = dataclasses.replace(event, table_name=canonical_name)

                event = self._project_event_columns(event)
                self.batcher.add(event)

                # A change in position_serialized proves the previous transaction fully
                # yielded — all of its events are now buffered or flushed. Record its end LSN
                # as the high-water mark we may safely release the WAL up to.
                if event.position_serialized != self.current_txn_lsn:
                    self.last_complete_txn_end_lsn = self.current_txn_lsn
                    self.current_txn_lsn = event.position_serialized

                self.last_end_lsn = event.position_serialized
                self.event_count += 1

                if self.batcher.should_flush:
                    tables = self.batcher.flush()
                    self.all_table_names.update(tables.keys())
                    self._process_flush(tables)
                    metrics.get_micro_batches_flushed_metric(self.inputs.team_id, str(self.inputs.source_id)).add(1)
                    # Advance only to the end of the last FULLY-yielded transaction, never to
                    # last_end_lsn: a micro-flush can fire mid-transaction (the batcher
                    # threshold is checked per event), and every event of the in-flight
                    # transaction shares its commit end LSN. Confirming that LSN while the
                    # transaction's tail is still un-yielded in the generator would release
                    # the WAL past un-flushed events — a crash before the next flush then
                    # loses them permanently. Consequences of this conservative bound:
                    #   (a) a single giant transaction gets no micro-advance until it
                    #       completes (a retry re-decodes it — safe, slow);
                    #   (b) on crash-replay the already-flushed prefix of the in-flight
                    #       transaction is re-read; cleanup_superseded_files trims the files
                    #       that held it before the retry writes them again.
                    if (
                        self.last_complete_txn_end_lsn is not None
                        and self.last_complete_txn_end_lsn != self.last_confirmed_lsn
                    ):
                        self._handle_truncates()
                        self._confirm_position(self.last_complete_txn_end_lsn)
                        self.last_confirmed_lsn = self.last_complete_txn_end_lsn
                    self.log.info("cdc_micro_batch_flushed", events_so_far=self.event_count)

            # Capture remaining table names before deciding on the next pass / final flush.
            self.all_table_names.update(self.batcher.table_names)

            rows_consumed = self.reader.last_rows_consumed
            # Drained: the peek returned less than a full page, so the backlog is exhausted.
            # Leave any buffered tail for run()'s _final_flush + advance.
            if rows_consumed < limit:
                self._backlog_drained = True
                return

            if (time.monotonic() - self._run_started_at) >= CDC_READ_SOFT_DEADLINE_SECONDS:
                self.log.warning(
                    "cdc_read_soft_deadline_reached",
                    events_so_far=self.event_count,
                    rows_consumed=rows_consumed,
                )
                return

            # Full page: drain the buffered (committed) events and advance the slot past every
            # transaction this pass committed so the next peek resumes cleanly.
            #
            # A full page that advanced nothing is a defensive guard, not a live path:
            # pg_logical_slot_peek_binary_changes only returns fully-committed transactions, so a
            # page that returns rows always commits something and advances. Were that ever to not
            # hold, grow the window so an oversized single transaction can complete in one peek (or
            # trip the decoder's MAX_TX_BUFFER_EVENTS guard) instead of re-peeking the same page.
            if not self._drain_and_advance_page():
                limit = min(limit * 2, CDC_MAX_CHANGES_LIMIT_CAP)

    def _drain_and_advance_page(self) -> bool:
        """Between peeks: flush buffered events and advance the slot past every committed
        transaction. Returns whether the slot advanced.

        Safe to advance to the decoder's last commit end LSN here (not only to
        last_complete_txn_end_lsn as the mid-loop micro-flush does): the peek has stopped at a
        transaction boundary, so every event yielded this pass belongs to a committed
        transaction and is now flushed. Unmatched-table commits carry the slot forward too —
        their WAL is intentionally dropped. Re-reading instead would write already-flushed
        events to the buffer again.
        """
        assert self.batcher is not None
        if self.batcher.event_count > 0:
            tables = self.batcher.flush()
            self.all_table_names.update(tables.keys())
            self._process_flush(tables)
            metrics.get_micro_batches_flushed_metric(self.inputs.team_id, str(self.inputs.source_id)).add(1)

        commit_lsn = self.reader.last_commit_end_lsn
        if commit_lsn is not None and commit_lsn != self.last_confirmed_lsn:
            self._handle_truncates()
            self._confirm_position(commit_lsn)
            self.last_confirmed_lsn = commit_lsn
            self.last_end_lsn = commit_lsn
            self._safe_heartbeat()
            return True
        return False

    # ------------------------------------------------------------------
    # Post-WAL handling
    # ------------------------------------------------------------------
    def _detect_pk_changes_post_wal(self) -> None:
        """Report tables whose replica identity key stopped matching the primary key we merge on.

        Detection only. Adopting the new key here would re-key a live Delta table whose existing
        rows were merged under the old one, so every row already in the table would be duplicated
        rather than replaced from that point on. The safe remediation is a full re-snapshot of the
        table, which is an operator decision, not something a WAL read should trigger on its own.
        """
        for table_name in self.all_table_names:
            decoder_pks = self.reader.get_decoder_key_columns(table_name)
            stored_pks = self.pk_columns_by_table.get(table_name, [])
            # Compared as sets because pg_catalog orders the stored key by index position while the
            # decoder reports it in table column order, so a composite key can differ in order
            # without having changed.
            if not decoder_pks or set(decoder_pks) == set(stored_pks):
                continue
            pk_schema = self.schema_by_name.get(table_name)
            pk_log = self._schema_log(pk_schema) if pk_schema is not None else self.log
            pk_log.warning("cdc_pk_columns_diverged", table=table_name, stored=stored_pks, wal=decoder_pks)

    def _handle_truncates(self) -> list[str]:
        """Process any truncated tables observed during decoding.

        Runs before every slot advance, so a failed reset or purge fails the run while the slot still
        holds the TRUNCATE and the retry repeats it. Returns every table truncated this run, so the
        no-changes path can decide whether to advance the slot.
        """
        truncated_tables = list(self.reader.truncated_tables)
        self.reader.clear_truncated_tables()
        self._truncated_tables.extend(truncated_tables)
        # The decoder names a table `schema.table`, while a schema created with a source schema set is
        # stored bare, so the lookup goes through the same map as the change events.
        stored_names = self._build_event_name_map()
        for table_name in truncated_tables:
            trunc_schema = self.schema_by_name.get(stored_names.get(table_name, table_name))
            if trunc_schema is None:
                continue
            self._schema_log(trunc_schema).warning(
                "truncate_detected", table=table_name, schema_id=str(trunc_schema.id)
            )
            self._reset_schema_to_snapshot(trunc_schema)
            self._unpause_schema_schedule(trunc_schema)
        return list(self._truncated_tables)

    def _reset_schema_to_snapshot(self, schema: ExternalDataSchema) -> None:
        """Put a schema back into snapshot mode so its own schedule re-syncs it from scratch."""
        # A snapshot already running may have read the table before changes this reset drops, as
        # when a retry reads a TRUNCATE again. It must not reach its hand-over. A failed cancel fails
        # the run while the slot still holds the TRUNCATE, so the retry repeats the reset.
        cancelled = cancel_running_sync(schema)
        if cancelled:
            self._schema_log(schema).info("cdc_reset_cancelled_running_sync", workflow_id=cancelled)
        # The re-seeding snapshot starts after this run, so it covers every change this run read.
        # Pending changes go too, because a change from before a TRUNCATE would bring back rows.
        if self.batcher is not None:
            self.batcher.discard(schema.name)
        # Purged before the marker is set, because the hand-over keeps every file of a marked schema.
        # A failed purge fails the run while the slot still holds the TRUNCATE, so the next run
        # repeats the reset.
        purge_buffer_prefix(schema.team_id, str(schema.id), self._schema_log(schema), strict=True)
        # reset_pipeline forces the batch import to wipe the table first (handle_reset_or_full_refresh),
        # preventing pre-truncate rows from surviving a TRUNCATE or lost-slot re-snapshot. Later runs
        # write the table's changes to the emptied buffer as an unbroken run, so the next snapshot
        # stays in the buffer with them.
        self._update_schema_sync_type_config(
            schema,
            updates={"cdc_mode": "snapshot", "reset_pipeline": True, CDC_SNAPSHOT_LANE_KEY: BUFFER_LANE},
            removes=["cdc_last_log_position"],
            extra_model_fields={"initial_sync_complete": False},
        )

    def _unpause_schema_schedule(self, schema: ExternalDataSchema) -> None:
        schema_log = self._schema_log(schema)
        try:
            from products.data_warehouse.backend.facade.api import unpause_external_data_schedule

            unpause_external_data_schedule(str(schema.id))
            schema_log.info("unpaused_schema_schedule_for_resnapshot", schema_id=str(schema.id))
        except Exception:
            schema_log.warning("failed_to_unpause_schema_schedule", schema_id=str(schema.id), exc_info=True)

    def _pause_cdc_extraction_schedule(self) -> None:
        """Pause the source's CDC extraction schedule after a non-retryable failure (best-effort)."""
        assert self.source is not None
        source_id = str(self.source.id)
        try:
            # Deferred: data_load.service participates in the CDC schedule<->workflow import cycle.
            from products.data_warehouse.backend.facade.api import pause_cdc_extraction_schedule

            pause_cdc_extraction_schedule(source_id)
            self.log.warning("cdc_extraction_schedule_paused_non_retryable", source_id=source_id)
        except Exception:
            self.log.warning("cdc_pause_schedule_failed", source_id=source_id, exc_info=True)

    def _handle_no_changes(self, truncated_tables: list[str]) -> None:
        """Early-return path: no DML events were read."""
        # A mid-run page advance already released the WAL it committed, so the slot moved this run.
        advanced = self.last_confirmed_lsn is not None
        if truncated_tables:
            truncate_end_lsn = self.reader.last_commit_end_lsn
            if truncate_end_lsn is not None:
                self._confirm_position(truncate_end_lsn)
                self.log.info("slot_advanced_past_truncate", position=truncate_end_lsn)
                advanced = True

        # Logical decoding reads every WAL record, but the peek only returns the ones the
        # publication covers, so a source whose publication is quiet while the rest of the database
        # writes yields nothing to advance on. The slot then pins the WAL from its last confirmed
        # position and the source retains it until the lag safety net drops the slot. The peek
        # examined every record up to the pre-read position and kept none of them, so releasing that
        # much is safe. Two conditions bound it. The backlog must have drained, because a run
        # stopped by the read deadline left records below that position unread. Nothing else may
        # have advanced the slot this run, because the pre-read position can sit behind where those
        # advances left it, and the next quiet run releases the remainder anyway.
        if not advanced and self._backlog_drained and self._pre_read_position is not None:
            try:
                self._confirm_position(self._pre_read_position)
                self.log.info("slot_advanced_no_changes", position=self._pre_read_position)
            except Exception:
                # Retention hygiene, not the run's work. Failing here would mark every schema failed
                # and email the customer about a run that read nothing and lost nothing.
                self.log.warning("slot_advance_no_changes_failed", exc_info=True)

        now = dt.datetime.now(tz=dt.UTC)
        for schema in self.cdc_schemas:
            self._record_healthy_run(schema, now)
        self.log.info("no_wal_changes")
        self._emit_run_duration("no_changes")

    # ------------------------------------------------------------------
    # Flush + finalization
    # ------------------------------------------------------------------
    def _final_flush(self) -> None:
        """Flush the events the read loop left in the batcher."""
        assert self.batcher is not None
        if self.batcher.event_count > 0:
            self._process_flush(self.batcher.flush())

    def _advance_slot_after_run(self) -> None:
        """Advance the slot past everything this run read, once the final flush has landed.

        A read always stops at a transaction boundary, and by now every event up to the decoder's
        last commit is flushed. Confirming that commit rather than the last event also moves past
        trailing transactions with no row events. A TRUNCATE on its own is one: this run already
        handled it, and reading it again would reset the table a second time.
        """
        target = self.reader.last_commit_end_lsn or self.last_end_lsn
        if target is not None and target != self.last_confirmed_lsn:
            self._confirm_position(target)
            self.last_end_lsn = target
            self.log.info("slot_advanced", position=target)

    def _update_log_positions(self) -> None:
        """Update per-schema cdc_last_log_position (skip schemas reset to snapshot mode)."""
        if self.last_end_lsn is None:
            return
        for schema in self.cdc_schemas:
            if schema.sync_type_config.get("cdc_mode") == "snapshot":
                continue
            self._update_schema_sync_type_config(schema, updates={"cdc_last_log_position": self.last_end_lsn})

    def _require_configured_slot(self) -> None:
        """Fail fast when a CDC-enabled source has no replication slot name stored.

        Streaming an empty slot name surfaces as ``replication slot "" does not exist``, which
        the invalidation check reads as a recoverable slot drop — so recovery (and Repair CDC)
        run, only to dead-end because there is no slot name to recreate. Raise the non-retryable
        misconfiguration up front instead, with guidance that actually resolves it.
        """
        assert self.adapter is not None
        assert self.source is not None
        if not self.adapter.parse_cdc_config(self.source).slot_name:
            raise CDCSlotNotConfiguredError()

    # ------------------------------------------------------------------
    # Failure / success finalization
    # ------------------------------------------------------------------
    def _recover_from_slot_invalidation(self, exc: Exception) -> None:
        """The slot can't be resumed (invalidated or dropped on the source DB): recreate it
        and reset every CDC schema to snapshot mode so it re-syncs from current table state.

        WAL between the slot's last confirmed position and the new slot's consistent point is
        gone — the re-snapshot covers current rows, but intermediate changes in that gap
        (including their _cdc history rows) cannot be recovered.
        """
        assert self.source is not None
        assert self.adapter is not None
        self.log.warning("cdc_slot_unrecoverable_recreating", error=str(exc))

        # Reset schemas before touching the slot (schedules stay paused): if recreation
        # fails below, the next run hits the invalidation again and recovery reruns
        # idempotently — no schema keeps streaming across the gap unnoticed.
        for schema in self.cdc_schemas:
            self._reset_schema_to_snapshot(schema)
            schema.status = ExternalDataSchema.Status.FAILED
            schema.latest_error = SLOT_INVALIDATION_RECOVERY_MESSAGE
            schema.save(update_fields=["status", "latest_error", "updated_at"])
            self._schema_log(schema).warning("cdc_schema_reset_for_slot_recovery", schema_id=str(schema.id))

        resource_fields = self.adapter.recreate_slot(
            self.source, tables=[self._qualified_table_name(s) for s in self.cdc_schemas]
        )

        self.source.job_inputs = {**(self.source.job_inputs or {}), **resource_fields}
        self.source.save(update_fields=["job_inputs", "updated_at"])

        # Unpause only after the new slot exists, so no snapshot can run before change
        # capture has a consistent point to resume from.
        for schema in self.cdc_schemas:
            self._unpause_schema_schedule(schema)

        self.log.info("cdc_slot_recovery_complete", schemas_reset=len(self.cdc_schemas))

    def _fail(self, exc: Exception) -> typing.NoReturn:
        """Persist a friendly failure, emit analytics, and re-raise.

        Non-retryable classifications raise ``NonRetryableException`` so the workflow's retry
        policy stops re-running a deterministic failure; retryable ones re-raise as-is to let
        Temporal retry.
        """
        info = self._handle_failure(exc)
        if not info.retryable:
            self._capture_non_retryable(info)
            raise NonRetryableException(info.friendly_message) from exc
        raise exc

    def _handle_failure(self, exc: Exception) -> CDCErrorInfo:
        """Classify the failure, store the friendly message on the jobs/schemas, return the info."""
        self.log.exception("cdc_extract_failed")
        # `exc` itself may be a dropped/killed DB connection (e.g. the source read or a write
        # earlier in this run hit "server closed the connection unexpectedly"). Django leaves that
        # connection in the pool until the next query touches it, so without this the job/schema
        # writes below immediately re-fail with "the connection is closed", masking the real error
        # and leaving jobs stuck RUNNING instead of recording the friendly failure message.
        close_old_connections()
        info = classify_cdc_error(exc, self.adapter)
        friendly = info.friendly_message[:MAX_FRIENDLY_MESSAGE_LENGTH]
        # A missing slot/publication won't recover on retry: mark the source broken — that persists
        # the per-schema FAILED state + the cdc_broken marker the UI/health check read and pauses the
        # schedule, so it stops firing hourly against a resource that is gone (the same zombie the lag
        # safety net produces). Any other failure just fails this run's schemas.
        marked_broken = info.category in (
            CDCErrorCategory.SLOT_MISSING,
            CDCErrorCategory.SLOT_NOT_CONFIGURED,
            CDCErrorCategory.PUBLICATION_MISSING,
        )
        if marked_broken:
            assert self.source is not None
            # This run records its own FAILED job rows below; a second set from mark_cdc_broken
            # would show every incident as two identical failed runs.
            mark_cdc_broken(self.source, info.category.value, friendly, create_visibility_jobs=False)
        elif not info.retryable and self.source is not None:
            # A non-retryable error re-fails every scheduled run, so pause the schedule instead of
            # looping it. No cdc_broken marker: the slot is intact, so it stays Repair-CDC-ineligible.
            self._pause_cdc_extraction_schedule()
        for schema in self.cdc_schemas:
            if not marked_broken:
                schema.status = ExternalDataSchema.Status.FAILED
                schema.latest_error = friendly
                schema.save(update_fields=["status", "latest_error", "updated_at"])
                if not info.retryable:
                    # Persisted so the failure digest email can tell "paused, action required"
                    # apart from "will retry" — the schedule pause itself leaves no DB trace.
                    self._update_schema_sync_type_config(
                        schema,
                        updates={
                            "cdc_extraction_paused": {
                                "reason": info.category.value,
                                "at": dt.datetime.now(tz=dt.UTC).isoformat(),
                            }
                        },
                    )
            # User-facing column gets the friendly copy; the raw error still routes to structured
            # logs / the Syncs log viewer for debugging.
            self._schema_log(schema).error(
                "cdc_extract_schema_failed", error=str(exc), category=info.category, retryable=info.retryable
            )
        terminal = not info.retryable or activity.info().attempt >= CDC_MAX_EXTRACTION_ATTEMPTS
        # Capture creates no ExternalDataJob of its own, so the Syncs tab would stay empty while the
        # schema reads FAILED. Write a terminal FAILED row per schema so the run is visible — but only
        # once retries are exhausted or the error is non-retryable, otherwise every transient retry
        # would leave a stray failed row.
        if terminal:
            try:
                self._create_failure_visibility_jobs(friendly)
            except Exception:
                self.log.warning("cdc_failure_visibility_jobs_failed", exc_info=True)
        # mark_cdc_broken schedules the digest itself; every other terminal failure schedules it
        # here, mirroring what update_external_job_status does for non-CDC syncs.
        if terminal and not marked_broken:
            self._schedule_failure_digest()
        # An unclassified failure stays retryable and never pauses the schedule, so a deterministic
        # one re-fails every scheduled run indefinitely. Only _capture_non_retryable emits analytics,
        # so these never reach error triage — capture the terminal case so the taxonomy can be taught
        # to recognise it (and, where fatal, stop retrying).
        if terminal and info.category == CDCErrorCategory.UNKNOWN:
            self._capture_unclassified(exc)
        self._emit_run_duration("failed")
        return info

    def _schedule_failure_digest(self) -> None:
        try:
            # Deferred: the tasks module pulls Celery wiring onto the import path.
            from products.data_warehouse.backend.facade.tasks import schedule_external_data_failure_digest

            schedule_external_data_failure_digest(self.inputs.team_id, trigger="cdc")
        except Exception:
            # Best-effort: the daily catch-up still delivers via the FAILED job rows.
            self.log.warning("cdc_digest_schedule_failed", exc_info=True)

    def _capture_non_retryable(self, info: CDCErrorInfo) -> None:
        # Best-effort: analytics must never mask the NonRetryableException the caller is about to raise.
        try:
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="cdc extraction non-retryable error",
                properties={
                    "team_id": self.inputs.team_id,
                    "source_id": str(self.inputs.source_id),
                    "category": str(info.category),
                },
            )
        except Exception:
            self.log.warning("cdc_non_retryable_capture_failed", exc_info=True)

    def _capture_unclassified(self, exc: BaseException) -> None:
        # Send the exception types and psycopg SQLSTATE codes in the cause chain — never str(exc),
        # which can embed the customer's host, database, schema, or table names — so the taxonomy can
        # be extended to catch this. A SQLSTATE is a fixed 5-character code (e.g. 42501 = insufficient
        # privilege), carries no customer data, and pins down which deterministic error is looping
        # where the exception type alone is ambiguous (many map to the same psycopg class).
        seen: set[int] = set()
        type_names: list[str] = []
        sqlstates: list[str] = []
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            type_names.append(type(current).__name__)
            sqlstate = getattr(current, "sqlstate", None)
            if isinstance(sqlstate, str) and sqlstate not in sqlstates:
                sqlstates.append(sqlstate)
            current = current.__cause__ or current.__context__
        # Best-effort: analytics must never mask the failure the caller is about to re-raise.
        try:
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="cdc extraction unclassified error",
                properties={
                    "team_id": self.inputs.team_id,
                    "source_id": str(self.inputs.source_id),
                    "exception_types": type_names,
                    "sqlstates": sqlstates,
                },
            )
        except Exception:
            self.log.warning("cdc_unclassified_capture_failed", exc_info=True)

    def _create_failure_visibility_jobs(self, friendly_error: str) -> None:
        """Create one terminal FAILED ExternalDataJob per CDC schema for this run.

        Schemas still inside the cooldown for this same failure are skipped (see
        _schemas_in_failure_cooldown).
        """
        now = dt.datetime.now(tz=dt.UTC)
        activity_info = activity.info()
        in_cooldown = self._schemas_in_failure_cooldown(friendly_error, now)
        if in_cooldown:
            self.log.info("cdc_failure_visibility_jobs_suppressed", schemas=len(in_cooldown))
        for schema in self.cdc_schemas:
            if schema.id in in_cooldown:
                continue
            ExternalDataJob.objects.create(
                team_id=self.inputs.team_id,
                pipeline_id=self.inputs.source_id,
                schema=schema,
                status=ExternalDataJob.Status.FAILED,
                rows_synced=0,
                latest_error=friendly_error,
                workflow_id=activity_info.workflow_id,
                workflow_run_id=activity_info.workflow_run_id,
                pipeline_version=ExternalDataJob.PipelineVersion.V3,
                finished_at=now,
                schema_snapshot=_build_schema_snapshot(schema),
            )

    def _schemas_in_failure_cooldown(self, friendly_error: str, now: dt.datetime) -> set[uuid.UUID]:
        """Schemas whose most recent capture failure row already reports this exact failure, within
        the cooldown.

        Only the newest capture row in the window counts, so a different error gets its own row.
        Capture writes no row for a successful run, so the same failure recurring after one stays
        suppressed until the window ends. Rows from other workflows are ignored: they come from each
        table's scheduled sync, which says nothing about whether this failure has already been
        reported. One query for the whole source; the window keeps it small.
        """
        recent_jobs = (
            ExternalDataJob.objects.filter(
                team_id=self.inputs.team_id,
                schema_id__in=[schema.id for schema in self.cdc_schemas],
                created_at__gt=now - CDC_FAILURE_VISIBILITY_COOLDOWN,
                workflow_id__startswith=CDC_EXTRACTION_WORKFLOW_ID_PREFIX,
            )
            .order_by("schema_id", "-created_at")
            .values("schema_id", "status", "latest_error")
        )

        in_cooldown: set[uuid.UUID] = set()
        seen: set[uuid.UUID] = set()
        for job in recent_jobs:
            schema_id = job["schema_id"]
            if schema_id in seen:
                continue
            seen.add(schema_id)
            if job["status"] == ExternalDataJob.Status.FAILED and job["latest_error"] == friendly_error:
                in_cooldown.add(schema_id)
        return in_cooldown

    def _record_run_heartbeat(self, schema: ExternalDataSchema, run_at: dt.datetime) -> None:
        """Persist a per-schema last-run heartbeat (cdc_last_run_at / cdc_last_run_event_count) so a
        quiet zero-event run still proves extraction is alive. Nothing reads these keys yet — an
        upcoming CDC health check and the status endpoint will — so this is a forward-looking
        breadcrumb, not an ExternalDataJob row per idle run.
        """
        self._update_schema_sync_type_config(
            schema,
            updates={"cdc_last_run_at": run_at.isoformat(), "cdc_last_run_event_count": self.event_count},
        )

    def _record_healthy_run(self, schema: ExternalDataSchema, now: dt.datetime) -> None:
        """Record that extraction ran for this schema, without touching its status.

        The schema's status belongs to the scheduled sync that consumes its buffer. Repainting it
        here would erase a failing consumer run within one capture tick, hiding a buffer backlog
        until its files hit the S3 TTL, which is unrecoverable.
        """
        try:
            self._record_run_heartbeat(schema, now)
            # A completed tick proves extraction runs again. The consumer cannot clear this marker:
            # its job completions are absorbed while the marker holds.
            if (schema.sync_type_config or {}).get("cdc_extraction_paused"):
                self._update_schema_sync_type_config(schema, removes=["cdc_extraction_paused"])
        except ExternalDataSchema.DoesNotExist:
            pass

    def _finalize_success(self) -> None:
        now = dt.datetime.now(tz=dt.UTC)
        for schema in self.cdc_schemas:
            self._record_healthy_run(schema, now)
        self._emit_run_duration("completed")


@activity.defn
def cdc_extract_activity(inputs: CDCExtractInput) -> None:
    """Core CDC extraction activity. Thin wrapper around CDCExtractActivity."""
    CDCExtractActivity(inputs).run()


@activity.defn
def validate_cdc_prerequisites_activity(inputs: ValidateCDCPrerequisitesInput) -> list[str]:
    """Validate CDC prerequisites for a source. Returns list of error messages."""
    close_old_connections()

    source = ExternalDataSource.objects.get(pk=inputs.source_id)
    adapter = get_cdc_adapter(source)

    return adapter.validate_prerequisites(
        source=source,
        management_mode=inputs.management_mode,  # type: ignore[arg-type]
        tables=inputs.tables,
        schema=inputs.schema,
        slot_name=inputs.slot_name,
        publication_name=inputs.publication_name,
    )


# ---------------------------------------------------------------------------
# Orphan slot sweeper
# ---------------------------------------------------------------------------


@activity.defn
def cleanup_orphan_slots_activity() -> None:
    """Safety-net sweeper: clean up orphaned CDC slots and monitor WAL lag.

    1. For deleted/inactive PostHog-managed sources → drop slot + publication
    2. For active sources → check WAL lag:
       - Warning threshold: log warning, update source status
       - Critical threshold (PostHog-managed, safety net on): drop slot, mark error
       - Self-managed: never drop, only warn
    """
    close_old_connections()

    log = logger.bind()
    log.info("cleanup_orphan_slots_started")
    sweep_started_mono = time.monotonic()
    sweep_started = dt.datetime.now(tz=dt.UTC)

    # The CDC fields live in `job_inputs`, an EncryptedJSONField: every leaf value is
    # Fernet-encrypted at rest, so `job_inputs__cdc_enabled=True` (and the slot/publication
    # filters) can never match. We must scope by the unencrypted `source_type` column and
    # decode each source's CDC config in Python. Deleted sources are included on purpose —
    # cleaning up their orphaned slots is the whole point of this sweep.
    sources = ExternalDataSource.objects.filter(source_type__in=cdc_supported_source_types()).iterator(chunk_size=100)

    sources_checked = 0
    sources_errored = 0
    slots_dropped = 0
    # A single source's management connection (10s connect_timeout × several ops) can stall the
    # loop, so heartbeat from a background thread rather than once per iteration — otherwise a
    # stalled source would starve heartbeats and Temporal would kill the whole sweep.
    with HeartbeaterSync(logger=log):
        for source in sources:
            try:
                adapter = get_cdc_adapter(source)
            except ValueError:
                continue

            try:
                cdc_config = adapter.parse_cdc_config(source)
            except Exception:
                log.exception("failed_to_parse_cdc_config", source_id=str(source.id))
                metrics.get_sweeper_source_errors_metric().add(1)
                sources_errored += 1
                continue

            # Restore the original filter semantics on decrypted values: skip sources that
            # don't have CDC enabled with both a slot and publication name to clean up.
            if not (cdc_config.enabled and cdc_config.slot_name and cdc_config.publication_name):
                continue

            sources_checked += 1

            source_log = log.bind(
                source_id=str(source.id),
                team_id=source.team_id,
                slot_name=cdc_config.slot_name,
                management_mode=cdc_config.management_mode,
            )

            # 1. Deleted sources — drop the Temporal schedule (always; PostHog-side)
            #    and PostHog-managed slot/publication (only when we own them).
            if source.deleted:
                try:
                    from products.data_warehouse.backend.facade.api import delete_cdc_extraction_schedule

                    delete_cdc_extraction_schedule(str(source.id))
                except Exception:
                    source_log.exception("failed_to_delete_cdc_extraction_schedule")
                    metrics.get_sweeper_source_errors_metric().add(1)

                if cdc_config.management_mode == "posthog":
                    source_log.info("cleaning_up_deleted_source_slot")
                    try:
                        with adapter.management_connection(source, connect_timeout=10) as conn:
                            adapter.drop_resources(conn, cdc_config.slot_name, cdc_config.publication_name)
                        slots_dropped += 1
                    except Exception:
                        source_log.exception("failed_to_cleanup_deleted_source_slot")
                        metrics.get_sweeper_source_errors_metric().add(1)
                        sources_errored += 1

                # Buffer prefixes: destroy() defers all external reaping to this sweep, so
                # without this the change files outlive the source until the lifecycle rule
                # expires them. Idempotent — a purged prefix is a no-op.
                for schema_id in ExternalDataSchema.objects.filter(
                    source=source, sync_type=ExternalDataSchema.SyncType.CDC
                ).values_list("id", flat=True):
                    purge_buffer_prefix(source.team_id, str(schema_id), source_log)
                continue

            # 2. Active sources — check WAL lag
            source_started = dt.datetime.now(tz=dt.UTC)
            try:
                with adapter.management_connection(source, connect_timeout=10) as conn:
                    lag_bytes = adapter.get_lag_bytes(conn, cdc_config.slot_name)
                    retention_cap_mb = adapter.get_retention_cap_mb(conn)
            except Exception:
                source_log.exception("failed_to_check_slot_lag")
                metrics.get_sweeper_source_errors_metric().add(1)
                sources_errored += 1
                continue

            if lag_bytes is None:
                source_log.warning("slot_not_found_or_no_flush_lsn")
                continue

            metrics.get_wal_lag_metric(source.team_id, str(source.id)).set(lag_bytes)
            lag_mb = lag_bytes / (1024 * 1024)

            critical_threshold_mb = cdc_config.lag_critical_threshold_mb
            if retention_cap_mb is not None:
                critical_threshold_mb = min(critical_threshold_mb, int(retention_cap_mb * RETENTION_CAP_SAFETY_FACTOR))

            if lag_mb >= critical_threshold_mb:
                source_log.error(
                    "slot_lag_critical",
                    lag_mb=round(lag_mb, 1),
                    threshold_mb=critical_threshold_mb,
                    retention_cap_mb=retention_cap_mb,
                )

                if cdc_config.management_mode == "posthog" and cdc_config.auto_drop_slot:
                    source_log.warning("auto_dropping_slot_critical_lag")
                    try:
                        with adapter.management_connection(source, connect_timeout=10) as conn:
                            adapter.drop_resources(conn, cdc_config.slot_name, cdc_config.publication_name)

                        slots_dropped += 1
                        metrics.get_auto_drop_metric(source.team_id, str(source.id)).add(1)
                        # The slot is gone — move the source to an explicit broken state and pause the
                        # schedule so it stops retrying against a slot that no longer exists.
                        mark_cdc_broken(
                            source,
                            "auto_dropped_critical_lag",
                            f"Change data capture was automatically stopped because replication lag "
                            f"exceeded {critical_threshold_mb} MB and the safety net dropped the "
                            f"replication slot. Use Repair CDC to recreate it and re-sync.",
                            lag_mb=round(lag_mb, 1),
                        )
                    except Exception:
                        source_log.exception("failed_to_auto_drop_slot")
                        metrics.get_sweeper_source_errors_metric().add(1)
                        sources_errored += 1
                elif cdc_config.management_mode == "self_managed":
                    # Customer owns the slot: surface the broken state but keep the schedule running
                    # and never drop — the lag may recover once they reduce load on the source.
                    try:
                        mark_cdc_broken(
                            source,
                            SELF_MANAGED_LAG_REASON,
                            f"Change data capture replication lag exceeded {critical_threshold_mb} MB. "
                            f"This slot is self-managed, so PostHog did not drop it — reduce load or WAL "
                            f"retention on the source database, or it may invalidate the slot and "
                            f"require a full re-sync.",
                            pause=False,
                            lag_mb=round(lag_mb, 1),
                        )
                    except Exception:
                        source_log.exception("failed_to_mark_self_managed_broken")
                        metrics.get_sweeper_source_errors_metric().add(1)
                        sources_errored += 1

            elif lag_mb >= cdc_config.lag_warning_threshold_mb:
                source_log.warning(
                    "slot_lag_warning",
                    lag_mb=round(lag_mb, 1),
                    threshold_mb=cdc_config.lag_warning_threshold_mb,
                )
            elif cdc_config.management_mode == "self_managed":
                try:
                    cleared = clear_recovered_self_managed_lag(source)
                    if cleared:
                        source_log.info("slot_lag_recovered_self_managed", lag_mb=round(lag_mb, 1), schemas=cleared)
                except Exception:
                    source_log.exception("failed_to_clear_recovered_lag")
                    metrics.get_sweeper_source_errors_metric().add(1)
                    sources_errored += 1

            source_log.info(
                "slot_lag_checked",
                lag_mb=round(lag_mb, 1),
                duration_ms=round((dt.datetime.now(tz=dt.UTC) - source_started).total_seconds() * 1000),
            )

    metrics.get_sweeper_sources_checked_metric().add(sources_checked)
    metrics.get_sweeper_duration_metric().record(time.monotonic() - sweep_started_mono)
    log.info(
        "cleanup_orphan_slots_completed",
        sources_checked=sources_checked,
        sources_errored=sources_errored,
        slots_dropped=slots_dropped,
        duration_s=round((dt.datetime.now(tz=dt.UTC) - sweep_started).total_seconds(), 1),
    )
