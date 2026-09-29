"""Find schemas that should be syncing but have stopped getting runs.

A schema's cadence lives in a Temporal schedule whose paused flag is written once, when the
schedule is created or rewritten (`sync_external_data_job_workflow`). Nothing keeps that flag
in step with `should_sync` afterwards, so a schedule paused out of band stays paused while
Postgres still reports the schema as syncing. `migrate_cdc_source_to_buffered` pauses every
per-schema schedule at its step 3 and unpauses at its step 7, so any abort in between leaves
them down.

That failure is silent in a way an ordinary sync failure is not. No run starts, so there is no
job row, no `latest_error`, and nothing for the failure digest to report. Every column a
dashboard would read keeps saying the schema is healthy.

This module carries the predicate that finds those schemas from Postgres alone, shared by the
periodic sweep that reports them and the management command that repairs them.
"""

from datetime import timedelta

from django.db.models import Case, DateTimeField, DurationField, ExpressionWrapper, F, QuerySet, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Greatest
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)

# Consecutive runs a schema can miss before the silence is a fault rather than jitter. A run
# starts late when the source is slow, the worker fleet is saturated, or the previous run
# overran its own interval, and none of those need repair.
DEFAULT_MISSED_INTERVALS = 3

# Floor under the stall window. Without it a five-minute schema qualifies after 20 minutes,
# which one slow run produces on its own.
DEFAULT_MIN_STALL = timedelta(hours=2)

# Matches the `sync_frequency_interval` column default, used when the column is null.
FALLBACK_SYNC_INTERVAL = timedelta(hours=6)

# Statuses that already report themselves. A failing schema carries its error on the row and
# reaches the failure digest; a billing-limited one still starts runs. Neither is this fault,
# and including them would bury it.
SELF_REPORTING_STATUSES = (
    ExternalDataSchema.Status.FAILED,
    ExternalDataSchema.Status.BILLING_LIMIT_REACHED,
    ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW,
    ExternalDataSchema.Status.PAUSED,
)

# `last_full_run_at` is free-form JSON. Postgres raises on a cast it cannot parse and reads a naive
# stamp in the session zone, so only an ISO stamp with an offset is cast, as in
# `ExternalDataSchema.last_full_run`.
_AWARE_ISO_TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$"

# Replaces the stale Running status on a repaired schema. The row keeps a visible record of the
# gap, and the schema's own next tick clears it.
REPAIRED_SCHEMA_ERROR = (
    "This sync stopped running on its schedule. PostHog restarted it, and the next sync runs on schedule."
)


@frozen
class StalledSchema:
    schema_id: str
    team_id: int
    name: str
    source_id: str
    source_type: str
    # "no_runs" when nothing has started since the stall window opened, which points at the
    # schedule. "stuck_job" when a run did start and never finished, which points at its
    # Temporal workflow and belongs to `unstick_external_data_jobs` instead.
    kind: str
    stalled_for: timedelta
    cdc_ingest_mode: str
    # `ad_hoc_sync.py` and the admin action set this on the schema it pauses for an in-flight
    # non-scheduled run, and clear it themselves once that run finishes successfully. It surviving
    # to a stall check means the run's own cleanup has not (yet, or ever) run, so the pause may
    # still be deliberate — unpausing here would race it against the admin-triggered workflow.
    admin_paused: bool
    # The stall window tolerates a null `sync_frequency_interval` (falls back to
    # FALLBACK_SYNC_INTERVAL for the window calculation only), but the schedule builder does not:
    # it passes the column straight into `ScheduleIntervalSpec`, where `timedelta(...) % None`
    # raises. Repairing would fail every time with the same error, so this is excluded rather
    # than left to fail — rewriting the schema's own cadence is not this tool's job.
    has_sync_interval: bool
    # True once a CDC schema has finished its initial snapshot and flipped to streaming
    # (`mark_initial_sync_complete`). `stalled_schema_queryset` already excludes this at the
    # source; this field backs `repairable_here` for the window between discovery and repair,
    # where a schema can flip to streaming after being read as `no_runs`.
    cdc_streaming: bool
    # Mirrors `ExternalDataSchema.cdc_halted`: true while the source is marked `cdc_broken`, or
    # its extraction schedule was paused after a non-retryable error. This is a configuration
    # marker independent of `should_sync` and `status`, so a halted schema can still read
    # should_sync=True and a non-self-reporting status. Cleared only by repair, resume, disable,
    # or a successful extraction run — not by anything this tool does.
    cdc_halted: bool

    @property
    def repairable_here(self) -> bool:
        """Whether unpausing the schedule is the right fix.

        A buffered CDC source is excluded because its schedule paces buffer consumption: once
        the mode is flipped, restarting the schedule out of sequence merges files against a
        table the buffered lane already writes. Those go back through
        `migrate_cdc_source_to_buffered`.

        A schema still carrying `admin_unpause_schedule_after_run` is excluded because its pause
        may belong to an in-flight admin-triggered run rather than to the outage this repairs.

        A schema with no `sync_frequency_interval` is excluded because the schedule builder
        cannot turn a null interval into a cadence.

        A streaming CDC schema is excluded because its own workflow paces the schedule; unpausing
        it does not restart a sync, it just races that workflow into re-pausing it. Those go back
        through `repair_cdc`.

        A halted CDC schema is excluded for the same reason, one step earlier: the marker exists
        precisely to stop anything else from touching the schema until `repair_cdc` clears it.
        """
        return (
            self.kind == "no_runs"
            and self.cdc_ingest_mode != "buffered"
            and not self.admin_paused
            and self.has_sync_interval
            and not self.cdc_streaming
            and not self.cdc_halted
        )


def stalled_schema_queryset(
    *,
    missed_intervals: int = DEFAULT_MISSED_INTERVALS,
    min_stall: timedelta = DEFAULT_MIN_STALL,
) -> QuerySet[ExternalDataSchema]:
    """Schemas whose last run is older than their own cadence allows.

    The window scales with `sync_frequency_interval` because a fixed one cannot serve both a
    five-minute schema and a daily one. A daily schema therefore needs days of silence to
    qualify, which is the cost of not flagging every schema that merely ran slowly.

    The window runs from the later of `last_synced_at` and `last_full_run_at`, because a run
    that imports nothing advances only the second (see `ExternalDataSchema.last_run_at`).
    """
    # NULL for a missing or unusable stamp. Postgres GREATEST skips NULLs, so `latest_run_at` then
    # falls back to `last_synced_at`.
    last_full_run = Case(
        When(
            sync_type_config__last_full_run_at__regex=_AWARE_ISO_TIMESTAMP,
            then=Cast(KeyTextTransform("last_full_run_at", "sync_type_config"), DateTimeField()),
        ),
        default=None,
        output_field=DateTimeField(),
    )
    stall_window = ExpressionWrapper(
        Greatest(
            Coalesce(F("sync_frequency_interval"), Value(FALLBACK_SYNC_INTERVAL)) * missed_intervals,
            Value(min_stall),
        ),
        output_field=DurationField(),
    )
    return (
        ExternalDataSchema.objects.filter(
            should_sync=True,
            deleted=False,
            source__deleted=False,
            # Has completed at least one sync, so a schema still working through its first
            # snapshot is not read as stalled.
            last_synced_at__isnull=False,
            # Narrows the scan before the per-row window below, which is computed and so cannot
            # use an index. No schema can qualify sooner than the floor, so this drops the bulk
            # of the fleet without changing the result.
            last_synced_at__lt=timezone.now() - min_stall,
        )
        .exclude(source__access_method=ExternalDataSource.AccessMethod.DIRECT)
        .exclude(status__in=SELF_REPORTING_STATUSES)
        # Streaming CDC and cdc_halted are excluded in `find_stalled_schemas` in Python, not
        # here: a JSON key lookup against a schema whose `sync_type_config` does not have that
        # key evaluates to SQL NULL, and `.exclude()` compiles to `NOT (...)` — NOT NULL is NULL,
        # not TRUE, so Postgres drops the row from the result entirely instead of keeping it.
        # That silently wipes out every schema without the key, not just the ones carrying it.
        .annotate(latest_run_at=Greatest(F("last_synced_at"), last_full_run, output_field=DateTimeField()))
        .annotate(
            stalled_after=ExpressionWrapper(
                F("latest_run_at") + stall_window,
                output_field=DateTimeField(),
            )
        )
        .filter(stalled_after__lt=timezone.now())
    )


def find_stalled_schemas(
    *,
    missed_intervals: int = DEFAULT_MISSED_INTERVALS,
    min_stall: timedelta = DEFAULT_MIN_STALL,
    team_id: int | None = None,
    source_type: str | None = None,
    limit: int | None = None,
) -> list[StalledSchema]:
    queryset = stalled_schema_queryset(missed_intervals=missed_intervals, min_stall=min_stall)
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    if source_type is not None:
        queryset = queryset.filter(source__source_type__iexact=source_type)

    queryset = queryset.select_related("source").order_by("latest_run_at")
    if limit is not None:
        queryset = queryset[:limit]

    schemas = list(queryset)
    if not schemas:
        return []

    # One query for the whole batch rather than one per schema. The batch is small by
    # construction: a healthy fleet returns nothing here.
    schemas_with_running_jobs = set(
        ExternalDataJob.objects.filter(
            schema_id__in=[schema.id for schema in schemas],
            status=ExternalDataJob.Status.RUNNING,
        ).values_list("schema_id", flat=True)
    )

    now = timezone.now()
    stalled = []
    for schema in schemas:
        # Streaming CDC and cdc_halted are excluded here rather than in the queryset (see the
        # comment there): a paused per-schema schedule is streaming CDC's steady state, and
        # cdc_halted exists precisely to keep everything else off the schedule until repair_cdc
        # clears it. Skipped rather than reported-but-unrepairable, unlike buffered CDC: this
        # population can be the entire fleet during a broken-source incident, and reporting it
        # every sweep would bury the schedule-stall signal this predicate exists to surface.
        if schema.is_cdc and schema.cdc_mode == "streaming":
            continue
        if schema.cdc_halted:
            continue
        stalled.append(
            StalledSchema(
                schema_id=str(schema.id),
                team_id=schema.team_id,
                name=schema.name,
                source_id=str(schema.source_id),
                source_type=schema.source.source_type,
                kind="stuck_job" if schema.id in schemas_with_running_jobs else "no_runs",
                stalled_for=now - schema.latest_run_at,  # type: ignore[attr-defined]
                cdc_ingest_mode=(schema.source.job_inputs or {}).get("cdc_ingest_mode", "legacy"),
                admin_paused=bool((schema.sync_type_config or {}).get("admin_unpause_schedule_after_run")),
                has_sync_interval=schema.sync_frequency_interval is not None,
                cdc_streaming=schema.is_cdc and schema.cdc_mode == "streaming",
                cdc_halted=schema.cdc_halted,
            )
        )
    return stalled


def repair_stalled_schema(stalled: StalledSchema) -> bool:
    """Put a stalled schema back on its schedule.

    Rewrites the Temporal schedule from the schema's current `should_sync`, which clears a
    paused flag left behind out of band and recreates a schedule that went missing. The rewrite
    does not fire a run: every scheduled run bills, so the repair waits for the schema's own
    next tick rather than charging for one now.

    Returns whether the schedule was actually rewritten. A revalidation guard below can skip
    without raising, and that is not the same outcome as a rewrite — the caller counts and logs
    them differently.
    """
    # data_load.service imports temporalio at module scope, so a top-level import here would
    # put the Temporal client on the import path of the sweep's Celery autodiscovery.
    from products.data_warehouse.backend.facade.api import sync_external_data_job_workflow  # noqa: PLC0415

    # Shared with the workflow's own finalization so a repaired row reads the same as one an
    # ordinary failed run left behind.
    from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (  # noqa: PLC0415
        _fail_stale_running_schema,
    )

    schema = ExternalDataSchema.objects.select_related("source").get(id=stalled.schema_id, team_id=stalled.team_id)

    # `stalled` is a discovery-time snapshot, and the management command's confirmation prompt
    # alone can put minutes between discovery and this call. Re-check should_sync and deleted
    # against the reloaded row rather than assuming the snapshot still holds — deleting a schema
    # does not itself flip should_sync, so a schema deleted in that window can still read
    # should_sync=True here. Either one must stay paused, not get rescheduled out from under it.
    if not schema.should_sync or schema.deleted:
        logger.info(
            "repair_stalled_schema_schedules_skipped_now_ineligible",
            schema_id=str(schema.id),
            team_id=schema.team_id,
        )
        return False

    # Same reasoning as should_sync above: an admin-triggered run can pause the schedule and set
    # this marker after discovery. Unpausing here would race the admin run's own workflow, which
    # relies on nothing else touching the schedule until it clears the marker itself.
    if (schema.sync_type_config or {}).get("admin_unpause_schedule_after_run"):
        logger.info(
            "repair_stalled_schema_schedules_skipped_admin_paused",
            schema_id=str(schema.id),
            team_id=schema.team_id,
        )
        return False

    # A null interval crashes the schedule builder below, so skip rather than fail. Re-checked
    # for the same staleness reason as the two guards above.
    if schema.sync_frequency_interval is None:
        logger.info(
            "repair_stalled_schema_schedules_skipped_no_sync_interval",
            schema_id=str(schema.id),
            team_id=schema.team_id,
        )
        return False

    # A paused schedule is steady state once a CDC schema is streaming — CDCExtractionWorkflow
    # owns it and re-pauses it on its own next tick. Unpausing here does not restart a sync, it
    # just races that workflow for nothing. Re-checked because initial_sync_complete (and so the
    # snapshot-to-streaming flip) can land in the window between discovery and this call.
    if schema.is_cdc and schema.cdc_mode == "streaming":
        logger.info(
            "repair_stalled_schema_schedules_skipped_cdc_streaming",
            schema_id=str(schema.id),
            team_id=schema.team_id,
        )
        return False

    # The halt marker exists precisely to stop anything else from touching the schedule until
    # `repair_cdc` clears it. Re-checked for the same staleness reason as the guards above.
    if schema.cdc_halted:
        logger.info(
            "repair_stalled_schema_schedules_skipped_cdc_halted",
            schema_id=str(schema.id),
            team_id=schema.team_id,
        )
        return False

    # A schema whose run never reached finalization still reads RUNNING, and the scheduler
    # treats that as a live run. Repainting it first stops the next tick being skipped.
    if schema.status == ExternalDataSchema.Status.RUNNING:
        _fail_stale_running_schema(
            str(schema.id),
            schema.team_id,
            REPAIRED_SCHEMA_ERROR,
            logger,
        )
        # get_team_ids_with_recent_sync_failures renotifies a FAILED schema once
        # last_error_notified_at is more than RENOTIFY_STILL_FAILING_AFTER old, with no newer
        # failed job required. A schema that failed long ago, was notified, and has since been
        # healthy for a while still carries that old stamp, so this repaint would otherwise read
        # as "still failing" and send the failure digest instead of the informational message
        # above. Stamping it here starts that window fresh; a genuinely new failure still notifies,
        # because its job's finished_at is newer than this stamp.
        ExternalDataSchema.objects.filter(id=schema.id, team_id=schema.team_id).update(
            last_error_notified_at=timezone.now()
        )

    sync_external_data_job_workflow(
        schema,
        create=True,
        should_sync=schema.should_sync,
        trigger_immediately=False,
    )
    return True
