"""Flip one CDC source between legacy extraction and buffered ingress.

In place: the slot, the tables, and `initial_sync_complete` are all preserved, so there is no
re-snapshot and no WAL gap. Only consolidated schemas move — see `cdc/source_manager.py`.
"""

from __future__ import annotations

import time
import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import psycopg
import structlog

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    get_buffer_prefix,
    parse_buffer_file_name,
    purge_buffer_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import (
    WRITE_RESOLUTION_FLAG,
    is_cdc_write_resolution_enabled,
    read_load_position,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    consolidated_resource_name,
    serves_buffered_lane,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import strip_s3_protocol
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    is_pipeline_v3_enabled,
)

logger = structlog.get_logger(__name__)

# How long to wait for in-flight work to reach a terminal state before giving up. Past this the
# operator should investigate rather than flip on top of a stuck run.
DRAIN_TIMEOUT_SECONDS = 15 * 60
DRAIN_POLL_SECONDS = 10

EXPECTED_SYNC_INTERVAL = dt.timedelta(minutes=5)


class Command(BaseCommand):
    help = "Move a CDC source onto buffered ingress (or back). Consolidated schemas only."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--source-id", required=True, help="ExternalDataSource UUID")
        parser.add_argument("--rollback", action="store_true", help="Return the source to legacy extraction")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change and exit")
        parser.add_argument(
            "--drain-timeout",
            type=int,
            default=DRAIN_TIMEOUT_SECONDS,
            help=f"Seconds to wait for in-flight work to drain (default {DRAIN_TIMEOUT_SECONDS})",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_id = options["source_id"]
        rollback = options["rollback"]
        dry_run = options["dry_run"]
        target_mode = "legacy" if rollback else "buffered"

        try:
            source = ExternalDataSource.objects.get(id=source_id)
        except ExternalDataSource.DoesNotExist:
            raise CommandError(f"No source {source_id}")

        schemas = list(ExternalDataSchema.objects.filter(source_id=source.id, deleted=False))
        cdc_schemas = [s for s in schemas if s.is_cdc]
        if not cdc_schemas:
            raise CommandError(f"Source {source_id} has no CDC schemas")

        # Mirror capture's _get_cdc_schemas: a user-disabled schema must not be flipped — the last
        # step would unpause its schedule, reversing the disable.
        eligible = [s for s in cdc_schemas if s.should_sync and serves_buffered_lane(s)]
        ineligible = [s for s in cdc_schemas if s not in eligible]
        current_mode = (source.job_inputs or {}).get("cdc_ingest_mode", "legacy")

        self._report(source, current_mode, target_mode, eligible, ineligible)

        if not eligible and not rollback:
            raise CommandError(
                "No schema on this source serves the buffered lane — nothing to flip. "
                "Buffered ingress covers consolidated streaming schemas whose initial sync is done."
            )
        if current_mode == target_mode:
            self.stdout.write(self.style.WARNING(f"Already {target_mode}; nothing to do."))
            return
        if not rollback:
            self._require_pipeline_v3(source)
            self._require_write_resolution(source, eligible)
            self._require_no_reserved_columns(eligible)
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
            return

        if rollback:
            self._roll_back(source, eligible, cdc_schemas, options["drain_timeout"])
        else:
            self._flip_to_buffered(source, eligible, options["drain_timeout"])

    def _require_pipeline_v3(self, source: ExternalDataSource) -> None:
        """Refuse to flip a team that still runs the v2 pipeline.

        Position resolution lives only in the v3 loader; on v2 nothing records a load position, so
        every scheduled sync re-merges the entire buffer and no file is ever deleted — a snowballing
        re-merge on every tick, observed live before this guard existed.
        """
        if is_pipeline_v3_enabled(source.team_id, source.source_type):
            return
        raise CommandError(
            f"Team {source.team_id} runs the v2 pipeline for {source.source_type}. Buffered ingress "
            "requires v3: v2 has no position resolution, so the buffer re-merges in full on every "
            "sync and consumed files are never deleted."
        )

    def _require_write_resolution(self, source: ExternalDataSource, eligible: list[ExternalDataSchema]) -> None:
        """Refuse to flip a team whose write resolution is off.

        Without the flag the loader never records a load position, so the consumer never has grounds
        to delete a consumed file. Files then accumulate until the 14-day TTL expires them — and the
        slot advanced long ago, so that expiry is unrecoverable data loss rather than a stall.
        """
        if is_cdc_write_resolution_enabled(source.team_id, str(eligible[0].id), f"preflight-{source.id}"):
            return
        raise CommandError(
            f"{WRITE_RESOLUTION_FLAG} is off for team {source.team_id}. Buffered ingress needs it: "
            "without it no load position is recorded, consumed files are never deleted, and they "
            "expire at the S3 TTL with the slot already advanced past them."
        )

    def _require_no_reserved_columns(self, eligible: list[ExternalDataSchema]) -> None:
        """Refuse to flip a schema whose source table has a column named `_ph_cdc_seq`.

        The collision stops the batcher stamping the engine position, and capture hard-errors on it
        (CDCReservedColumnError) — catching it here keeps the source out of a flip-then-break loop.

        The buffered lane writes its own `_ph_cdc_seq` into the warehouse table, so the column alone
        proves nothing once a schema has consumed the buffer. A recorded load position is proof the
        column is ours: capture would have hard-errored on a real collision before any file existed.
        """
        conflicted = [
            s.name
            for s in eligible
            if s.table is not None
            and CDC_SEQ_COLUMN in (s.table.columns or {})
            and read_load_position(s.sync_type_config, consolidated_resource_name(s)) is None
        ]
        if conflicted:
            raise CommandError(
                f"Schemas with a source column named {CDC_SEQ_COLUMN}: {', '.join(sorted(conflicted))}. "
                "That name is reserved for change ordering — rename the column or keep the source on legacy."
            )

    def _report(
        self,
        source: ExternalDataSource,
        current_mode: str,
        target_mode: str,
        eligible: list[ExternalDataSchema],
        ineligible: list[ExternalDataSchema],
    ) -> None:
        self.stdout.write(f"Source {source.id} (team {source.team_id}): {current_mode} → {target_mode}")
        self.stdout.write(f"  buffered lane ({len(eligible)}): {', '.join(s.name for s in eligible) or '—'}")
        off_cadence = [s.name for s in eligible if s.sync_frequency_interval != EXPECTED_SYNC_INTERVAL]
        if off_cadence:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ not at the 5min platform cadence: {', '.join(sorted(off_cadence))} — "
                    "consumption paces to the schema's schedule; set them to 5min first"
                )
            )
        if ineligible:
            detail = ", ".join(
                f"{s.name} [{'disabled' if not s.should_sync else s.cdc_table_mode}]" for s in ineligible
            )
            self.stdout.write(self.style.WARNING(f"  staying on legacy ({len(ineligible)}): {detail}"))
            self.stdout.write(
                self.style.WARNING(
                    "  → hybrid source: capture keeps its transforms and the backpressure guard for those schemas"
                )
            )

    def _flip_to_buffered(
        self, source: ExternalDataSource, eligible: list[ExternalDataSchema], drain_timeout: int
    ) -> None:
        from products.data_warehouse.backend.facade.api import (
            pause_cdc_extraction_schedule,
            unpause_cdc_extraction_schedule,
        )

        source_id = str(source.id)

        self.stdout.write("1/6 pausing extraction schedule")
        pause_cdc_extraction_schedule(source_id)

        # Pausing the schedule stops future firings, not a workflow already running. A legacy run
        # with the shadow lane on keeps writing buffer files, and one landing after the purge would
        # be merged by the consumer even though the legacy lane already delivered those rows.
        self.stdout.write("2/6 waiting for the in-flight extraction run to finish")
        self._wait_for_extraction_idle(source_id, drain_timeout)

        self.stdout.write("3/6 draining sourcebatch")
        self._wait_for_sourcebatch_drain(source.team_id, [str(s.id) for s in eligible], drain_timeout)

        # Pre-flip files were already delivered by the legacy lane, and replaying them would
        # re-apply rows against a position the guard has no watermark for yet.
        self.stdout.write("4/6 purging pre-flip buffer files")
        for schema in eligible:
            purge_buffer_prefix(source.team_id, str(schema.id), logger)
        self._verify_prefixes_empty(source.team_id, eligible)

        self.stdout.write("5/6 setting cdc_ingest_mode=buffered")
        source.job_inputs = {**(source.job_inputs or {}), "cdc_ingest_mode": "buffered"}
        source.save(update_fields=["job_inputs"])

        self.stdout.write("6/6 unpausing schedules")
        unpause_cdc_extraction_schedule(source_id)
        self._set_schema_schedules(eligible, paused=False)

        self.stdout.write(self.style.SUCCESS(f"Source {source_id} is now buffered."))
        self.stdout.write(
            "Verify: capture writes buffer files and advances the slot; the next sync merges and "
            'advances sync_type_config["cdc_load_position"]; consumed files disappear on the run after.'
        )

    def _roll_back(
        self,
        source: ExternalDataSource,
        eligible: list[ExternalDataSchema],
        cdc_schemas: list[ExternalDataSchema],
        drain_timeout: int,
    ) -> None:
        from products.data_warehouse.backend.facade.api import (
            pause_cdc_extraction_schedule,
            unpause_cdc_extraction_schedule,
        )

        source_id = str(source.id)

        # Pausing the schedule stops future firings, not a workflow already running — which can
        # keep writing buffer files and advancing the slot. The drain check below is meaningless
        # until capture is actually idle.
        self.stdout.write("1/6 pausing extraction schedule")
        pause_cdc_extraction_schedule(source_id)
        self.stdout.write("2/6 waiting for the in-flight extraction run to finish")
        self._wait_for_extraction_idle(source_id, drain_timeout)

        # The buffer's tail holds WAL the slot has already advanced past — it exists nowhere else.
        # The consumer must apply it BEFORE legacy delivery resumes, or it is lost for good. Capture
        # is idle so the buffer is static; the still-running scheduled sync drains it. Scanned over
        # every schema the buffered lane serves, which includes ones disabled after the flip — but
        # not the legacy ones, whose prefixes hold shadow copies no consumer will ever read.
        self.stdout.write("3/6 waiting for the consumer to drain the buffer")
        self._wait_for_buffer_drain(source.team_id, [s for s in cdc_schemas if serves_buffered_lane(s)], drain_timeout)

        # Consumer next: a sync merging old buffered rows AFTER legacy capture resumed would
        # overwrite newer legacy writes — legacy writes carry no position, so the guard can't
        # protect them. Strict: a schedule that failed to pause could start such a sync.
        self.stdout.write("4/6 pausing per-schema schedules")
        self._pause_schema_schedules_strict(eligible)
        self._wait_for_running_sync_jobs(source.team_id, [str(s.id) for s in eligible], drain_timeout)

        self.stdout.write("5/6 setting cdc_ingest_mode=legacy")
        source.job_inputs = {**(source.job_inputs or {}), "cdc_ingest_mode": "legacy"}
        source.save(update_fields=["job_inputs"])

        # Leftover fully-applied files stay: the position guard no-ops a replay, the S3 TTL clears them.
        self.stdout.write("6/6 unpausing extraction schedule")
        unpause_cdc_extraction_schedule(source_id)

        self.stdout.write(self.style.SUCCESS(f"Source {source_id} is now legacy."))

    def _wait_for_extraction_idle(self, source_id: str, timeout: int) -> None:
        from products.data_warehouse.backend.facade.api import cdc_extraction_schedule_has_running_action

        deadline = time.monotonic() + timeout
        while cdc_extraction_schedule_has_running_action(source_id):
            if time.monotonic() >= deadline:
                raise CommandError(
                    f"An extraction run is still executing after {timeout}s. The schedule is left "
                    "paused and the mode unchanged — wait for it to finish, then re-run."
                )
            self.stdout.write("    waiting, extraction run still executing")
            time.sleep(DRAIN_POLL_SECONDS)

    def _wait_for_buffer_drain(self, team_id: int, schemas: list[ExternalDataSchema], timeout: int) -> None:
        """Block until every remaining buffer file sits strictly below the schema's load position.

        A file AT the position is not proof of consumption: one Postgres transaction shares a commit
        position across every event, so a transaction split across files leaves an unread tail whose
        `end_seq` already equals the floor, and `drop_superseded_rows` keeps rows at the watermark
        precisely so that tail can still land. The consumer settles it by deleting the file once a
        completed run proves it read it, so waiting for the deletion is the same proof the consumer
        uses — a couple of ticks on an idle schema.
        """
        from products.data_warehouse.backend.facade.api import get_s3_client

        s3 = get_s3_client()
        deadline = time.monotonic() + timeout
        while True:
            behind: list[str] = []
            for schema in schemas:
                schema.refresh_from_db(fields=["sync_type_config"])
                floor = read_load_position(schema.sync_type_config, consolidated_resource_name(schema)) or 0
                prefix = strip_s3_protocol(get_buffer_prefix(team_id, str(schema.id)))
                try:
                    keys = s3.ls(prefix, detail=False, refresh=True)
                except FileNotFoundError:
                    continue
                for key in keys:
                    parsed = parse_buffer_file_name(key.rsplit("/", 1)[-1])
                    if parsed is not None and parsed.end_seq >= floor:
                        behind.append(schema.name)
                        break
            if not behind:
                return
            if time.monotonic() >= deadline:
                raise CommandError(
                    f"Buffered changes not yet proven applied for: {', '.join(sorted(behind))} after "
                    f"{timeout}s. Rolling back now could lose them — the slot already advanced past that "
                    "WAL, and the consumer deletes each file only once it proves it read it. Extraction "
                    "is left paused; let the scheduled syncs catch up, then re-run."
                )
            self.stdout.write(f"    waiting, buffer not drained for: {', '.join(sorted(behind))}")
            time.sleep(DRAIN_POLL_SECONDS)

    def _pause_schema_schedules_strict(self, schemas: list[ExternalDataSchema]) -> None:
        from products.data_warehouse.backend.facade.api import pause_external_data_schedule

        for schema in schemas:
            try:
                pause_external_data_schedule(str(schema.id))
            except Exception as exc:
                raise CommandError(
                    f"Could not pause the schedule for {schema.name}; a sync starting mid-rollback "
                    f"could overwrite newer legacy rows. Mode unchanged — fix and re-run. ({exc})"
                )

    def _verify_prefixes_empty(self, team_id: int, eligible: list[ExternalDataSchema]) -> None:
        """Abort if any buffer file survived the purge.

        The purge itself is best-effort, but a leftover file here means the first buffered sync
        replays rows the legacy lane already delivered, against a lane with no watermark yet —
        silently. The source is still paused and the mode unset, so aborting is clean.
        """
        from products.data_warehouse.backend.facade.api import get_s3_client

        s3 = get_s3_client()
        leftovers: list[str] = []
        for schema in eligible:
            prefix = strip_s3_protocol(get_buffer_prefix(team_id, str(schema.id)))
            try:
                keys = s3.ls(prefix, detail=False, refresh=True)
            except FileNotFoundError:
                continue
            leftovers.extend(k for k in keys if parse_buffer_file_name(k.rsplit("/", 1)[-1]) is not None)
        if leftovers:
            raise CommandError(
                f"{len(leftovers)} buffer file(s) survived the purge (first: {leftovers[0]}). "
                "The source is left paused and the mode unchanged — clear the prefix and re-run."
            )

    def _wait_for_sourcebatch_drain(self, team_id: int, schema_ids: list[str], timeout: int) -> None:
        """Block until no sourcebatch batch for these schemas is still working.

        Flipping while a batch is mid-flight would leave it to land after the source stopped
        producing them, against a table the buffered lane has started writing.
        """
        if not schema_ids:
            return

        deadline = time.monotonic() + timeout
        conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
        try:
            while True:
                age = BatchQueue.get_oldest_non_terminal_batch_age_seconds(conn, team_id=team_id, schema_ids=schema_ids)
                if age is None:
                    return
                if time.monotonic() >= deadline:
                    raise CommandError(
                        f"sourcebatch still has a batch {age:.0f}s old after {timeout}s. "
                        "The source is left paused — investigate the stuck load before flipping."
                    )
                self.stdout.write(f"    waiting, oldest batch {age:.0f}s old")
                time.sleep(DRAIN_POLL_SECONDS)
        finally:
            conn.close()

    def _wait_for_running_sync_jobs(self, team_id: int, schema_ids: list[str], timeout: int) -> None:
        if not schema_ids:
            return

        deadline = time.monotonic() + timeout
        while True:
            running = ExternalDataJob.objects.filter(
                team_id=team_id, schema_id__in=schema_ids, status=ExternalDataJob.Status.RUNNING
            ).count()
            if running == 0:
                return
            if time.monotonic() >= deadline:
                raise CommandError(
                    f"{running} sync job(s) still running after {timeout}s. Schedules are left "
                    "paused and the mode unchanged — wait for them to finish, then re-run."
                )
            self.stdout.write(f"    waiting, {running} sync job(s) running")
            time.sleep(DRAIN_POLL_SECONDS)

    def _set_schema_schedules(self, schemas: list[ExternalDataSchema], *, paused: bool) -> None:
        from products.data_warehouse.backend.facade.api import (
            pause_external_data_schedule,
            unpause_external_data_schedule,
        )

        for schema in schemas:
            try:
                if paused:
                    pause_external_data_schedule(str(schema.id))
                else:
                    unpause_external_data_schedule(str(schema.id))
            except Exception:
                # The mode is already persisted, so a failed schedule call is recoverable by hand;
                # aborting here would leave the source half-flipped instead.
                self.stdout.write(self.style.WARNING(f"    could not set schedule for {schema.name} — do it manually"))
                logger.warning("cdc_flip_schedule_failed", schema_id=str(schema.id), exc_info=True)
