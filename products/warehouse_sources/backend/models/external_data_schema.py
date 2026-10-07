import re
import sys
import uuid
import fnmatch
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, Optional

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

import structlog
from dateutil import parser

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.migration_helpers import deprecate_field
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr
from posthog.sync import database_sync_to_async

from products.warehouse_sources.backend.facade.contracts import UnsupportedSyncTypeError
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.retry_limits import (
    MAX_RESUMABLE_SOURCE_RETRIES_PRODUCTION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SOURCE_CURSOR_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import (
    ExternalDataSchemaStatus,
    ExternalDataSchemaSyncFrequency,
    ExternalDataSchemaSyncType,
    IncrementalFieldType,
    IncrementalSyncBlockedReason,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema

logger = structlog.get_logger(__name__)

type IncrementalFieldValue = str | int | float | None

# Sync type strings that early clients wrote to the column. They name a real mode, so they map to it.
LEGACY_SYNC_TYPE_ALIASES: dict[str, ExternalDataSchemaSyncType] = {
    "full": ExternalDataSchemaSyncType.FULL_REFRESH,
}

# Matched by `Any_Source_Errors`, so the exception text must keep this prefix.
UNSUPPORTED_SYNC_TYPE_ERROR = "Unsupported sync type"
UNSUPPORTED_SYNC_TYPE_DISABLED_MESSAGE = (
    "This table has a sync type that PostHog does not support. Choose a sync type in the table's "
    "sync settings, then re-enable the sync."
)


def resolve_sync_type(value: str | None) -> ExternalDataSchemaSyncType | None:
    """Turn a stored `sync_type` into the enum. The column does not enforce its choices."""
    if value is None:
        return None
    try:
        return ExternalDataSchemaSyncType(value)
    except ValueError:
        alias = LEGACY_SYNC_TYPE_ALIASES.get(value)
        if alias is not None:
            return alias
        raise UnsupportedSyncTypeError(f"{UNSUPPORTED_SYNC_TYPE_ERROR}: '{value}'") from None


# Recorded as the job's latest_error, which the syncs UI shows to the customer.
SYNC_DISABLED_JOB_ERROR = "Sync stopped because syncing was turned off"
SCHEMA_DELETED_JOB_ERROR = "Sync stopped because the table was deleted"
AUTO_DISABLED_JOB_ERROR = "Sync stopped because of an error that retrying would not fix"

# `Any_Source_Errors` rewrites the raised exception into this copy, so a blocked schema carries it
# as `latest_error`. Matched below, not only displayed.
MISSING_PRIMARY_KEY_DISABLED_MESSAGE = (
    "This table needs a primary key to sync incrementally, but none is set. Choose a primary key "
    "for the table in its sync settings, or switch it to full table replication, then re-enable the sync."
)
DUPLICATE_PRIMARY_KEY_DISABLED_MESSAGE = (
    "The primary key set for this table isn't unique, so incremental syncing can't reliably match "
    "rows to update. Choose a unique primary key in the table's sync settings, or switch it to full "
    "table replication, then re-enable the sync."
)

# Runs that fail outside the workflow record the raw text instead. Copied from
# `pipelines/core/arrow_utils.py`, which would pull pyarrow onto the Django model path; a test
# holds the two in step.
MISSING_PRIMARY_KEYS_RAW_ERROR = "Primary key required for incremental syncs"
DUPLICATE_PRIMARY_KEYS_RAW_ERROR = "The primary keys for this table are not unique"

_INCREMENTAL_SYNC_BLOCKED_MARKERS: tuple[tuple[str, IncrementalSyncBlockedReason], ...] = (
    (MISSING_PRIMARY_KEY_DISABLED_MESSAGE, IncrementalSyncBlockedReason.MISSING_PRIMARY_KEY),
    (MISSING_PRIMARY_KEYS_RAW_ERROR, IncrementalSyncBlockedReason.MISSING_PRIMARY_KEY),
    (DUPLICATE_PRIMARY_KEY_DISABLED_MESSAGE, IncrementalSyncBlockedReason.DUPLICATE_PRIMARY_KEY),
    (DUPLICATE_PRIMARY_KEYS_RAW_ERROR, IncrementalSyncBlockedReason.DUPLICATE_PRIMARY_KEY),
)


def incremental_sync_blocked_reason(latest_error: str | None) -> str | None:
    """Classify a sync error as one of the two states a customer resolves by changing the key.

    Reading the error keeps this in step with the failure by construction: a successful run clears
    `latest_error`, and a different failure replaces it, so there is no second state to expire.
    """
    if not latest_error:
        return None
    return next((reason.value for marker, reason in _INCREMENTAL_SYNC_BLOCKED_MARKERS if marker in latest_error), None)


# How stale a rewrite checkpoint may get before its import hold lapses. Generous on purpose: a
# multi-budget rewrite renews the stamp on every advancing attempt, and attempts arrive at the
# schema's own sync cadence, which can be six hours apart. The number that matters is the ceiling on
# how long a rewrite nobody is advancing can pause a table's imports.
REPARTITION_HOLD_MAX_AGE = timedelta(hours=48)

SCHEDULED_FULL_REFRESH_SYNC_TYPES = frozenset(
    {ExternalDataSchemaSyncType.INCREMENTAL, ExternalDataSchemaSyncType.APPEND, ExternalDataSchemaSyncType.XMIN}
)
MAX_FULL_REFRESH_INTERVAL_DAYS = 90
SCHEDULED_FULL_REFRESH_MAX_SLACK = timedelta(hours=1)


@dataclass(frozen=True, kw_only=True)
class SyncDisableContext:
    """Caller-supplied context for a should_sync disable, carried to the teardown task.

    ``error_message`` overrides the default job error (the auto-disable path records
    its user-facing non-retryable error instead of the generic "turned off" copy).
    ``exclude_workflow_id`` names a Temporal workflow the teardown must not cancel,
    for disables issued from inside the workflow's own failure handling.
    """

    error_message: str | None = None
    exclude_workflow_id: str | None = None


_sync_disable_context: ContextVar[SyncDisableContext | None] = ContextVar("sync_disable_context", default=None)


@contextmanager
def sync_disable_context(
    *, error_message: str | None = None, exclude_workflow_id: str | None = None
) -> Generator[None]:
    token = _sync_disable_context.set(
        SyncDisableContext(error_message=error_message, exclude_workflow_id=exclude_workflow_id)
    )
    try:
        yield
    finally:
        _sync_disable_context.reset(token)


def _schedule_sync_teardown(*, schema_id: str, team_id: int, deleted: bool) -> None:
    """Dispatch the async teardown of a schema's in-flight sync work, post-commit.

    Stopping the scheduler is not enough: the in-flight run keeps its Temporal
    workflow, its Running job, and its enqueued v3 batches, and a run that still
    trickles progress falls through both reconcile sweeps. The teardown runs in a
    Celery task because it may fail tens of thousands of queue rows and talks to
    Temporal, neither of which may block the write that flipped the flag; cancelling
    a workflow is irreversible, so the dispatch waits for the commit.
    """
    ctx = _sync_disable_context.get()
    if ctx is not None and ctx.error_message:
        reason = ctx.error_message
    elif deleted:
        reason = SCHEMA_DELETED_JOB_ERROR
    else:
        reason = SYNC_DISABLED_JOB_ERROR
    exclude_workflow_id = ctx.exclude_workflow_id if ctx is not None else None

    def _dispatch() -> None:
        # Deferred to keep Celery off the import path of this models module.
        from products.warehouse_sources.backend.tasks import cleanup_disabled_external_data_schema  # noqa: PLC0415

        cleanup_disabled_external_data_schema.delay(
            team_id=team_id,
            schema_id=schema_id,
            reason=reason,
            exclude_workflow_id=exclude_workflow_id,
        )

    transaction.on_commit(_dispatch)


def _schema_ids_with_running_jobs(schema_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    # Deferred to break the import cycle with external_data_job.
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob  # noqa: PLC0415

    return set(
        ExternalDataJob.objects.filter(schema_id__in=schema_ids, status=ExternalDataJob.Status.RUNNING).values_list(
            "schema_id", flat=True
        )
    )


# A run parks one cursor per displaced attempt, so the bound must cover the largest attempt cap an
# import activity gets. The trim keeps the newest entries, and a live run's entries are the newest.
STAGED_CURSOR_PENDING_LIMIT = MAX_RESUMABLE_SOURCE_RETRIES_PRODUCTION

# The key, inside a staged cursor, for the incremental value a later attempt of the same workflow
# run can resume after. It differs from the staged `last_value`, which the loader promotes only
# when the whole run completes.
STAGED_RESUME_VALUE_KEY = "resume_value"

# The key, inside a staged cursor, for the run whose queue rows the resume value actually describes.
# An attempt that only inherits the value from an earlier attempt, without queuing a batch of its
# own yet, is not that run: finalizing a later zero-batch continuation must target the run that
# holds the rows, not whichever attempt most recently restated the same value.
STAGED_RESUME_OWNER_KEY = "resume_owner_run_uuid"

# The key for the append run that the loader started to write and has not completed. The loader
# owns the value (see `pipeline_v3/load/append_rollback.py`). A reset deletes the table, so it
# drops the key too.
APPEND_RUN_MARKER_KEY = "append_run_in_progress"


class ExternalDataSchemaQuerySet(models.QuerySet["ExternalDataSchema"]):
    def update(self, **kwargs: Any) -> int:
        """Chokepoint for bulk writes that stop a schema from syncing.

        Queryset ``.update()`` bypasses ``Model.save()``, so without this override a
        bulk disable (e.g. ``disable_cdc``) or bulk soft-delete (source ``destroy``)
        would strand its in-flight runs. The transition set is read before the write
        so rows already disabled/deleted are not re-torn-down, and only schemas with
        a Running job dispatch a task.
        """
        disabling = kwargs.get("should_sync") is False
        deleting = kwargs.get("deleted") is True

        # `auto_disabled_at` is written by `save()`, which a bulk write skips. The auto-disable
        # path always runs through `update_should_sync`, which saves the instance, so a bulk
        # write that names `should_sync` is the user's decision. An earlier halt must not
        # outlive it, or a schema nobody halted stays in the failure digest. An explicit value
        # still wins, so a caller can stage a halted row.
        if "should_sync" in kwargs and "auto_disabled_at" not in kwargs:
            kwargs["auto_disabled_at"] = None

        transitioning: list[tuple[uuid.UUID, int]] = []
        if disabling or deleting:
            predicate = models.Q()
            if disabling:
                predicate |= models.Q(should_sync=True)
            if deleting:
                predicate |= ~models.Q(deleted=True)
            transitioning = list(self.filter(predicate).values_list("id", "team_id"))
        updated = super().update(**kwargs)
        if transitioning:
            running = _schema_ids_with_running_jobs([schema_id for schema_id, _ in transitioning])
            for schema_id, team_id in transitioning:
                if schema_id in running:
                    _schedule_sync_teardown(schema_id=str(schema_id), team_id=team_id, deleted=deleting)
        return updated


# In `sync_type_config`: set while the S3 change buffer carries this table's snapshot. Cleared by the
# snapshot to streaming flip. See cdc/snapshot_lane.py.
CDC_SNAPSHOT_LANE_KEY = "cdc_snapshot_lane"


# In `sync_type_config`: how many of this schema's runs failed in a row, and when the last of them
# failed. `retry_limits` turns the count into this schema's retry cap and its smallest gap between
# runs. A key here rather than a column because clearing it is what a reset is for: a reset
# re-reads the table from the start, which is the progress a streak counts the absence of.
FAILURE_STREAK_KEY = "failure_streak"
FAILURE_STREAK_RUNS_KEY = "runs"
FAILURE_STREAK_LAST_FAILED_AT_KEY = "last_failed_at"


class ExternalDataSchema(  # nosemgrep: semgrep.rules.security.prefer-uuid7-django-pk -- grandfathered UUIDT primary key
    ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields
):
    # Kept on the model so the nested names stay unchanged.
    Status = ExternalDataSchemaStatus
    SyncType = ExternalDataSchemaSyncType
    SyncFrequency = ExternalDataSchemaSyncFrequency

    name = models.CharField(max_length=400)
    label = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source = models.ForeignKey("warehouse_sources.ExternalDataSource", related_name="schemas", on_delete=models.CASCADE)
    table = models.ForeignKey("warehouse_sources.DataWarehouseTable", on_delete=models.SET_NULL, null=True, blank=True)
    should_sync = models.BooleanField(default=True)
    auto_disabled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When PostHog stopped syncing this schema itself, after an error that retrying would not fix. "
        "Null while syncing is on, and while syncing is off because the user turned it off.",
    )
    latest_error = models.TextField(
        null=True, blank=True, help_text="The latest error that occurred when syncing this schema."
    )
    last_error_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this schema's failure was last included in a failure digest email.",
    )
    status = models.CharField(max_length=400, null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_type = models.CharField(max_length=128, choices=SyncType.choices, null=True, blank=True)
    # User-managed vendor API version override for this schema. NULL (the norm) means the schema
    # syncs on its source's pinned version; a value here wins over the source pin. Deliberately
    # ignored by version-migration tooling — only the user changes it. Not available for
    # webhook-sync schemas (webhook payload versions are configured per source at the vendor).
    api_version = models.CharField(max_length=128, null=True, blank=True)
    # See `sources/common/history_window.py`. A column rather than a `sync_type_config` key
    # because it has to outlive a reset, and clearing that blob is what a reset is for.
    history_start = models.DateTimeField(null=True, blank=True)
    # { "incremental_field": string, "incremental_field_type": string, "incremental_field_last_value": any, "incremental_field_earliest_value": any, "incremental_field_lookback_seconds": int | None, "reset_pipeline": bool, "partitioning_enabled": bool, "partition_count": int, "partition_size": int, "partition_mode": str, "partitioning_keys": list[str], "chunk_size_override": int | None, "primary_key_columns": list[str] | None, "verified_primary_keys": list[str] | None, "source_cursor": { "kind": str, "data": dict }, "max_partition_bytes": int, "partition_measurement": { "job_id": str, "phase": "pre_extraction" | "post_load", "budget": int, "healthy": bool }, "last_repartition_at": iso8601 str, "repartition_pending": { "partition_mode": str, "partition_format": str | None, "partition_count": int | None, "partition_size": int | None, "partition_keys": list[str], "trigger_reason": str }, "repartition_swap": { "state": "ready", "temp_uri": str, "live_uri": str }, "repartition_rewrite": { "temp_uri": str, "rows_written": int, "target": dict }, "query_folder_state": { "<table>__query": { "active": str, "active_since": iso8601 str, "active_job_id": str, "history_since": iso8601 str, "inactive_since": { str: iso8601 str } } }, "registered_schema_fingerprint": str }
    sync_type_config = models.JSONField(
        default=dict,
        blank=True,
    )
    # Normalized leaf subdir under the source's S3 folder that Delta data is written to (the actual
    # folder name, e.g. `my_table`, not `My Table`). Pins legacy rows (renamed to qualified form
    # during multi-schema migration) to their original path. Empty for rows written before this
    # column existed — readers fall back to the legacy JSON key, then the normalized schema `name`.
    s3_folder_name = models.CharField(max_length=400, null=True, blank=True)
    # Deprecated in favour of `sync_frequency_interval`
    sync_frequency = deprecate_field(
        models.CharField(
            max_length=128, choices=SyncFrequency.choices, default=SyncFrequency.DAILY.value, blank=True, null=True
        )
    )
    sync_frequency_interval = models.DurationField(default=timedelta(hours=6), null=True, blank=True)
    sync_time_of_day = models.TimeField(null=True, blank=True, help_text="Time of day to run the sync (UTC)")
    full_refresh_interval_days = models.SmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_FULL_REFRESH_INTERVAL_DAYS)],
        help_text="Days between scheduled full refreshes. A full refresh re-imports every row, so rows deleted "
        "at the source are removed from the table. Null means no scheduled full refreshes.",
    )
    next_full_refresh_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the next scheduled full refresh is due. The first scheduled sync that starts at most an hour "
        "before this time re-imports the table. Saving a new interval or time, or any full resync, moves it one "
        "interval ahead, onto full_refresh_time_of_day when that is set.",
    )
    full_refresh_time_of_day = models.TimeField(
        null=True,
        blank=True,
        help_text="UTC time of day that scheduled full refreshes are due. Null means one interval after the last "
        "full resync or save.",
    )
    initial_sync_complete = models.BooleanField(default=False)
    description = models.CharField(max_length=1000, null=True, blank=True)
    # null = sync all columns (default). Non-empty list = exact column projection.
    # PK + active incremental field are always retained server-side regardless of this list.
    enabled_columns = models.JSONField(null=True, blank=True, default=None)
    # null (default) = sync all rows. List of {column, operator, value} predicates ANDed onto the WHERE clause.
    row_filters = models.JSONField(null=True, blank=True, default=None)

    objects = ExternalDataSchemaQuerySet.as_manager()

    __repr__ = sane_repr("name")

    class Meta:
        db_table = "posthog_externaldataschema"

    def _sync_teardown_kind(self, update_fields: Iterable[str] | None) -> str | None:
        """Which stop-syncing transition this save performs, read from the DB before writing.

        The DB read (rather than a value cached at load time) is what makes a no-op
        re-save of ``should_sync=False`` not re-fail anything: only a row that is
        currently syncing (or not yet deleted) counts as a transition. Saves scoped
        by ``update_fields`` to other columns skip the read entirely, so the
        pipeline's frequent bookkeeping saves pay nothing.
        """
        if self._state.adding:
            return None
        disabling = self.should_sync is False and (update_fields is None or "should_sync" in update_fields)
        deleting = self.deleted is True and (update_fields is None or "deleted" in update_fields)
        if not disabling and not deleting:
            return None
        prior = ExternalDataSchema.objects.filter(pk=self.pk).values_list("should_sync", "deleted").first()
        if prior is None:
            return None
        prior_should_sync, prior_deleted = prior
        if deleting and not prior_deleted:
            return "deleted"
        if disabling and prior_should_sync:
            return "disabled"
        return None

    def _apply_auto_disabled_marker(self, teardown_kind: str | None, update_fields: Iterable[str] | None) -> bool:
        """Record whether PostHog stopped this schema itself. Returns whether the value changed.

        The failure digest emails a team about a schema PostHog halted, and stays quiet about one
        the user switched off, so which of the two happened must outlive the write that stopped
        the schema. Only the auto-disable path supplies an error message through
        ``sync_disable_context``, and that is what tells the two apart. A save that leaves
        ``should_sync`` False without performing the disable transition keeps the existing stamp,
        so the pipeline's frequent bookkeeping saves cannot erase it.
        """
        if update_fields is not None and "should_sync" not in update_fields:
            return False
        if self.should_sync:
            marker = None
        elif teardown_kind == "disabled":
            context = _sync_disable_context.get()
            marker = timezone.now() if context is not None and context.error_message else None
        else:
            return False
        if marker == self.auto_disabled_at:
            return False
        self.auto_disabled_at = marker
        return True

    def save(self, *args: Any, skip_activity_log: bool = False, **kwargs: Any) -> None:
        # Populate the S3 folder on first write so the column is always authoritative for new rows.
        # Legacy/qualified rows set it explicitly before renaming (see `_qualify_legacy_row`); this
        # only fills it when empty, so an existing folder is never overwritten by a later rename.
        if not self.s3_folder_name and self.name and self.name.strip():
            self.s3_folder_name = NamingConvention.normalize_identifier(self.resolved_s3_folder_name or self.name)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "s3_folder_name"}

        # Chokepoint for instance writes that stop this schema from syncing; the queryset
        # `.update()` twin lives on ExternalDataSchemaQuerySet. Detected before the write,
        # dispatched only after it succeeds.
        teardown_kind = self._sync_teardown_kind(kwargs.get("update_fields"))

        if self._apply_auto_disabled_marker(teardown_kind, kwargs.get("update_fields")):
            scoped_fields = kwargs.get("update_fields")
            if scoped_fields is not None:
                kwargs["update_fields"] = {*scoped_fields, "auto_disabled_at"}

        if skip_activity_log:
            # Internal pipeline-driven bookkeeping saves (sync_type_config / xmin state) don't need
            # an audit trail. Bypass ModelActivityMixin.save() so we skip its extra _get_before_update
            # SELECT — that read needs a fresh pooler connection and raises OperationalError when the
            # transaction pooler has dropped the connection mid-sync, failing the import activity.
            #
            # These calls always target an already-persisted row. Without force_update, Django's
            # UUID-pk-with-default fallback would silently retry a no-op UPDATE as an INSERT if the
            # row was deleted concurrently (e.g. the source/schema deleted mid-sync) — either
            # resurrecting deleted data, or failing with a misleading FK IntegrityError on source_id
            # instead of a clear "no such row" error.
            kwargs.setdefault("force_update", True)
            super(ModelActivityMixin, self).save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

        if teardown_kind is not None and _schema_ids_with_running_jobs([self.pk]):
            _schedule_sync_teardown(schema_id=str(self.pk), team_id=self.team_id, deleted=teardown_kind == "deleted")

    def folder_path(self) -> str:
        return f"team_{self.team_id}_{self.source.source_type}_{str(self.id)}".lower().replace("-", "_")

    @property
    def normalized_name(self):
        return NamingConvention.normalize_identifier(self.name)

    @property
    def normalized_s3_folder_name(self) -> str:
        """Normalized Delta folder leaf the loader actually wrote the table under.

        Diverges from ``normalized_name`` for folder-pinned rows (e.g. Postgres ``public.users``
        → folder ``users``); readers that resolve ``normalized_name`` point at a prefix with no
        ``_delta_log`` and surface "No files in log segment".
        """
        return NamingConvention.normalize_identifier(self.resolved_s3_folder_name or self.name)

    @property
    def is_incremental(self):
        return self.sync_type == self.SyncType.INCREMENTAL

    @property
    def is_append(self):
        return self.sync_type == self.SyncType.APPEND

    @property
    def is_webhook(self):
        return self.sync_type == self.SyncType.WEBHOOK

    @property
    def is_cdc(self):
        return self.sync_type == self.SyncType.CDC

    @property
    def is_xmin(self):
        return self.sync_type == self.SyncType.XMIN

    @property
    def cdc_halted(self) -> bool:
        """True while a CDC marker absorbs status updates: the source is marked broken, or the
        extraction schedule was paused after a non-retryable error. Cleared by repair, resume,
        disable, or a successful extraction run."""
        config = self.sync_type_config or {}
        return bool(config.get("cdc_broken")) or bool(config.get("cdc_extraction_paused"))

    @property
    def sync_halted(self) -> bool:
        """True when syncing will not resume without user action."""
        return not self.should_sync or self.cdc_halted

    @property
    def _failure_streak(self) -> dict[str, Any]:
        """The streak marker, or an empty one for any value this cannot read.

        Both readers below run on the terminal status write of every run, so a raise here would
        fail every sync of the schema rather than throttle it.
        """
        config = self.sync_type_config if isinstance(self.sync_type_config, dict) else {}
        streak = config.get(FAILURE_STREAK_KEY)
        return streak if isinstance(streak, dict) else {}

    @property
    def failed_runs_in_a_row(self) -> int:
        """Runs of this schema that failed since its last completed run."""
        runs = self._failure_streak.get(FAILURE_STREAK_RUNS_KEY)
        return runs if isinstance(runs, int) and not isinstance(runs, bool) and runs > 0 else 0

    @property
    def failure_streak_last_failed_at(self) -> datetime | None:
        """When the newest run in the streak failed, or None while there is no streak."""
        stamped = self._failure_streak.get(FAILURE_STREAK_LAST_FAILED_AT_KEY)
        if not isinstance(stamped, str):
            return None
        try:
            parsed = datetime.fromisoformat(stamped)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def note_failed_run(self, failed_at: datetime) -> None:
        """Add one failed run to the streak, in memory.

        The caller saves `sync_type_config` under the row lock it already holds for the run's
        terminal status, so the streak lands in that statement rather than in a second
        read-modify-write that could race it.
        """
        config = self.sync_type_config if isinstance(self.sync_type_config, dict) else {}
        config[FAILURE_STREAK_KEY] = {
            FAILURE_STREAK_RUNS_KEY: self.failed_runs_in_a_row + 1,
            FAILURE_STREAK_LAST_FAILED_AT_KEY: failed_at.isoformat(),
        }
        self.sync_type_config = config

    def clear_failure_streak(self) -> None:
        """Drop the streak, in memory. The caller saves `sync_type_config`."""
        if isinstance(self.sync_type_config, dict):
            self.sync_type_config.pop(FAILURE_STREAK_KEY, None)

    @property
    def cdc_mode(self) -> Literal["snapshot", "streaming"] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("cdc_mode")
        return None

    @property
    def cdc_last_log_position(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("cdc_last_log_position")
        return None

    @property
    def cdc_table_mode(self) -> Literal["consolidated", "cdc_only", "both"]:
        if self.sync_type_config:
            return self.sync_type_config.get("cdc_table_mode", "consolidated")
        return "consolidated"

    @property
    def should_use_incremental_field(self):
        return self.is_incremental or self.is_append or self.is_webhook

    @property
    def table_row_count_is_cumulative(self) -> bool:
        # These sync types append/merge into the warehouse table across runs, so its true size is the
        # full table count — not the latest run's row_count, which is only that run's delta. Full refresh
        # replaces the whole table, so there the run's row_count already equals the table size.
        return self.should_use_incremental_field or self.is_cdc or self.is_xmin

    @property
    def incremental_field(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field", None)

        return None

    @property
    def incremental_field_type(self) -> IncrementalFieldType | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_type", None)

        return None

    @property
    def incremental_field_last_value(self) -> IncrementalFieldValue:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_last_value", None)

        return None

    @property
    def incremental_field_earliest_value(self) -> IncrementalFieldValue:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_earliest_value", None)

        return None

    @property
    def last_full_run_at(self) -> str | None:
        """ISO timestamp of the last run that actually extracted, so a schema completing on a
        negative probe still gets one full run per interval (see `_fast_return_eligible`)."""
        if self.sync_type_config:
            return self.sync_type_config.get("last_full_run_at", None)

        return None

    @property
    def last_full_run(self) -> datetime | None:
        """Parsed `last_full_run_at`, or None when it does not parse or has no zone.

        Picking a zone for a naive stamp would invent freshness the schema may not have.
        """
        raw = self.last_full_run_at
        if raw is None:
            return None
        try:
            stamped = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None
        return stamped if stamped.tzinfo is not None else None

    @property
    def last_run_at(self) -> datetime | None:
        """When a sync last ran, whether or not it moved any rows.

        A run that extracts nothing advances only `last_full_run_at`, because `last_synced_at` is
        also the signals watermark. A fast return does the reverse, so neither stamp is enough alone.
        """
        stamps = [stamp for stamp in (self.last_synced_at, self.last_full_run) if stamp is not None]
        return max(stamps) if stamps else None

    @property
    def incremental_field_lookback_seconds(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_lookback_seconds", None)

        return None

    @property
    def reset_pipeline(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("reset_pipeline", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partitioning_enabled(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("partitioning_enabled", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partition_count(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_count", None)

        return None

    @property
    def partition_size(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_size", None)

        return None

    @property
    def last_vacuum_version(self) -> int | None:
        # Delta version of the schema's snapshot table at its last vacuum (cadence watermark).
        if self.sync_type_config:
            return self.sync_type_config.get("last_vacuum_version", None)

        return None

    @property
    def last_vacuum_version_cdc(self) -> int | None:
        # Same watermark for the _cdc companion table — a separate delta table whose versions
        # are unrelated to the snapshot's, so it can't share last_vacuum_version.
        if self.sync_type_config:
            return self.sync_type_config.get("last_vacuum_version_cdc", None)

        return None

    @property
    def partition_count_override(self) -> int | None:
        # Operator-pinned partition_count set via the admin repartition action. Unlike
        # `partition_count` (which is auto-detected and wiped on every reset), this key
        # survives `update_sync_type_config_for_reset_pipeline` so the operator's choice
        # wins the reset resync that the repartition triggers. It is consumed (popped) by
        # `set_partitioning_enabled` once applied, so a later reset re-detects.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_count_override", None)

        return None

    @property
    def partition_size_override(self) -> int | None:
        # Operator-pinned partition_size for numerical mode. Same one-shot semantics as
        # `partition_count_override`.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_size_override", None)

        return None

    @property
    def partition_mode_override(self) -> PartitionMode | None:
        # Operator-pinned partition_mode set via the admin "change partition mode" action.
        # Like `partition_count_override`, it survives `update_sync_type_config_for_reset_pipeline`
        # (which wipes the auto-detected `partition_mode`) so the operator's choice wins the reset
        # resync that the mode change triggers, then is consumed by `set_partitioning_enabled`.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_mode_override", None)

        return None

    @property
    def partitioning_keys_override(self) -> list[str] | None:
        # Operator-pinned partitioning_keys paired with `partition_mode_override` — e.g. the
        # date/timestamp column to bucket on when switching a table to datetime mode. Same
        # one-shot, reset-surviving semantics as `partition_mode_override`.
        if self.sync_type_config:
            return self.sync_type_config.get("partitioning_keys_override", None)

        return None

    @property
    def partition_mode(self) -> PartitionMode | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_mode", None)

        return None

    @property
    def partition_format(self) -> PartitionFormat | None:
        # This key doesn't get reset on pipeline_reset.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_format", None)

        return None

    @property
    def partitioning_keys(self) -> list[str] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partitioning_keys", None)

        return None

    @property
    def primary_key_columns(self) -> list[str] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("primary_key_columns", None)

        return None

    @property
    def verified_primary_keys(self) -> list[str] | None:
        """The key a full-table probe proved unique, so later runs only probe what they read."""
        if self.sync_type_config:
            return self.sync_type_config.get("verified_primary_keys", None)

        return None

    @property
    def incremental_sync_blocked(self) -> str | None:
        """Why the last run proved this schema's incremental sync can never succeed, if it did."""
        return incremental_sync_blocked_reason(self.latest_error)

    @property
    def chunk_size_override(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("chunk_size_override", None)

        return None

    @property
    def schema_metadata(self) -> dict[str, Any] | None:
        if self.sync_type_config:
            metadata = self.sync_type_config.get("schema_metadata")
            if isinstance(metadata, dict):
                return metadata
        return None

    @property
    def resolved_s3_folder_name(self) -> str | None:
        # JSON fallback covers rows written by old workers before the column rollout.
        if self.s3_folder_name:
            return self.s3_folder_name
        legacy_key = (self.sync_type_config or {}).get("dwh_storage_key")
        if isinstance(legacy_key, str) and legacy_key:
            return legacy_key
        return None

    @property
    def foreign_keys(self) -> list[dict[str, str]] | None:
        metadata = self.schema_metadata
        if metadata:
            foreign_keys = metadata.get("foreign_keys")
            if isinstance(foreign_keys, list):
                return foreign_keys
        return None

    def set_partitioning_enabled(
        self,
        partitioning_keys: list[str],
        partition_count: Optional[int],
        partition_size: Optional[int],
        partition_mode: Optional[PartitionMode],
        partition_format: Optional[PartitionFormat],
    ) -> None:
        # Merged under the row lock rather than saved from this copy, which the loader holds for the
        # whole run while CDC capture writes the same JSON (the snapshot marker among it).
        self.sync_type_config = update_sync_type_config_keys(
            self.id,
            self.team_id,
            updates={
                "partitioning_enabled": True,
                "partition_count": partition_count,
                "partition_size": partition_size,
                "partitioning_keys": partitioning_keys,
                "partition_mode": partition_mode,
                "partition_format": partition_format,
            },
            # Consume any operator-pinned overrides: they've now been baked into the effective
            # settings above, so drop them. This makes the pin one-shot — a later reset falls
            # back to auto-detection instead of re-applying a stale pin (re-pin via the admin
            # repartition action if needed).
            removes=[
                "partition_count_override",
                "partition_size_override",
                "partition_mode_override",
                "partitioning_keys_override",
            ],
        )

    # --- In-place repartition controller state ------------------------------------------------
    # These keys drive the automated, no-source-pull repartition that bounds per-partition memory
    # so incremental merges stop OOMing the worker. Detection records `max_partition_bytes` and (when
    # over budget) a `repartition_pending` target; the next run's pre-extraction activity performs the
    # in-place rewrite, using `repartition_swap` as a crash-safe marker, then stamps `last_repartition_at`.

    @property
    def max_partition_bytes(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("max_partition_bytes", None)
        return None

    @property
    def partition_measurement(self) -> dict[str, Any] | None:
        if self.sync_type_config:
            measurement = self.sync_type_config.get("partition_measurement", None)
            if isinstance(measurement, dict):
                return measurement
        return None

    @property
    def last_repartition_at(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("last_repartition_at", None)
        return None

    @property
    def repartition_pending(self) -> dict[str, Any] | None:
        if self.sync_type_config:
            pending = self.sync_type_config.get("repartition_pending", None)
            if isinstance(pending, dict):
                return pending
        return None

    @property
    def repartition_swap(self) -> dict[str, Any] | None:
        if self.sync_type_config:
            swap = self.sync_type_config.get("repartition_swap", None)
            if isinstance(swap, dict):
                return swap
        return None

    @property
    def repartition_rewrite(self) -> dict[str, Any] | None:
        """Checkpoint of a rewrite that ran out of activity budget before finishing streaming.

        Its temp table holds a scan-ordered prefix of the live table's rows. The next attempt resumes
        appending from that offset instead of re-streaming from row 0, so a table too large to rewrite
        in one activity converges across attempts rather than giving up terminally. Cleared once temp
        is fully built (a swap is staged) or when the controller gives up. Shape:
        {"temp_uri": str, "rows_written": int, "target": dict, "live_version": int, "held_at": str,
        "budget_exhausted": bool}.
        """
        if self.sync_type_config:
            marker = self.sync_type_config.get("repartition_rewrite", None)
            if isinstance(marker, dict):
                return marker
        return None

    @property
    def repartition_holds_import(self) -> bool:
        """Whether an unfinished rewrite should pause this schema's imports.

        A rewrite spanning several activity budgets can only resume while live stays at the Delta
        version its checkpoint was built against, and this schema's own merge is what moves it. Left
        alone, every sync invalidates the checkpoint the previous run wrote, so the rewrite restarts
        from row 0 forever and the table never converges. Holding imports for the duration trades
        staleness on one table for a rewrite that can finish.

        `held_at` is restamped on every checkpoint write, so a rewrite that keeps advancing keeps
        renewing the hold. One that stops advancing lets it lapse after `REPARTITION_HOLD_MAX_AGE`,
        so a wedged or abandoned rewrite cannot pause ingestion indefinitely — the worst case is a
        stale table, never a stopped one.
        """
        rewrite = self.repartition_rewrite
        if not rewrite:
            return False
        held_at = rewrite.get("held_at")
        if not isinstance(held_at, str):
            # A checkpoint written before `held_at` existed. Treat it as lapsed rather than holding on
            # a timestamp we cannot age out.
            return False
        try:
            stamped = datetime.fromisoformat(held_at)
        except ValueError:
            return False
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=UTC)
        return datetime.now(UTC) - stamped < REPARTITION_HOLD_MAX_AGE

    @property
    def repartition_claim(self) -> dict[str, Any] | None:
        """The fencing claim of the newest repartition attempt: {"token", "job_id", "claimed_at"}.

        S3 has no locking, so this row is the coordination point between concurrent repartition
        attempts (a heartbeat-timed-out zombie and its Temporal retry). The newest claimant owns the
        table; older attempts compare their token against this and stand down. Never cleared — it is
        only ever compared against a live attempt's token, so a stale claim is inert.
        """
        if self.sync_type_config:
            claim = self.sync_type_config.get("repartition_claim", None)
            if isinstance(claim, dict):
                return claim
        return None

    def _save_sync_type_config(self) -> None:
        # temporalio at module scope would put the Temporal client on the django.setup() path —
        # this is a models module (see external_data_source.reload_schemas for the same pattern).
        from posthog.temporal.common.utils import retry_on_db_connection_drop  # noqa: PLC0415

        # Internal bookkeeping write — skip the activity-log SELECT (see save()) since these run
        # inside the sync/repartition activity where a dropped pooler connection would fail the run.
        # These fire once per batch across every schema sync, so a transient pooler wait_timeout
        # (the pool momentarily out of free backend connections) is worth one retry rather than
        # losing the write silently.
        retry_on_db_connection_drop(
            lambda: self.save(update_fields=["sync_type_config", "updated_at"], skip_activity_log=True)
        )

    def record_partition_measurement(self, max_partition_bytes: int, measurement: dict[str, Any] | None = None) -> None:
        # Deferred: this module loads during django.setup() and the util pulls in temporalio.
        from posthog.temporal.common.utils import retry_on_db_connection_drop  # noqa: PLC0415

        updates: dict[str, Any] = {"max_partition_bytes": max_partition_bytes}
        if measurement is not None:
            updates["partition_measurement"] = measurement
        self.sync_type_config = retry_on_db_connection_drop(
            lambda: update_sync_type_config_keys(self.id, self.team_id, updates=updates)
        )

    def set_repartition_pending(self, target: dict[str, Any]) -> None:
        self.sync_type_config["repartition_pending"] = target
        self._save_sync_type_config()

    def clear_repartition_pending(self) -> None:
        self.sync_type_config.pop("repartition_pending", None)
        self._save_sync_type_config()

    def set_repartition_swap(self, swap: dict[str, Any]) -> None:
        self.sync_type_config["repartition_swap"] = swap
        self._save_sync_type_config()

    def set_repartition_claim(self, claim: dict[str, Any]) -> bool:
        from posthog.temporal.common.utils import retry_on_db_connection_drop  # noqa: PLC0415

        # A timed-out activity may still be running when its retry stakes a newer claim. Merge under
        # the row lock so the older activity's stale model copy cannot overwrite that newer token (or
        # any unrelated config written while it was running) and accidentally reclaim the table.
        def _write(config: dict[str, Any]) -> None:
            current = config.get("repartition_claim")
            if isinstance(current, dict):
                current_claimed_at = current.get("claimed_at")
                claimed_at = claim.get("claimed_at")
                if isinstance(current_claimed_at, str) and isinstance(claimed_at, str):
                    if current_claimed_at > claimed_at:
                        return
            config["repartition_claim"] = claim

        self.sync_type_config = retry_on_db_connection_drop(
            lambda: update_sync_type_config_keys(schema_id=self.id, team_id=self.team_id, mutate=_write)
        )
        return self.sync_type_config.get("repartition_claim") == claim

    def abandon_repartition_if_claimed(self, claim_token: str) -> bool:
        from posthog.temporal.common.utils import retry_on_db_connection_drop  # noqa: PLC0415

        def _write(config: dict[str, Any]) -> None:
            claim = config.get("repartition_claim")
            if not (isinstance(claim, dict) and claim.get("token") == claim_token):
                return
            if config.get("repartition_swap") is not None:
                return
            for key in ("repartition_pending", "repartition_swap", "repartition_rewrite"):
                config.pop(key, None)
            config["last_repartition_at"] = timezone.now().isoformat()

        self.sync_type_config = retry_on_db_connection_drop(
            lambda: update_sync_type_config_keys(schema_id=self.id, team_id=self.team_id, mutate=_write)
        )
        claim = self.sync_type_config.get("repartition_claim")
        return (
            isinstance(claim, dict)
            and claim.get("token") == claim_token
            and not any(
                key in self.sync_type_config
                for key in ("repartition_pending", "repartition_swap", "repartition_rewrite")
            )
        )

    def clear_repartition_swap(self) -> None:
        self.sync_type_config.pop("repartition_swap", None)
        self._save_sync_type_config()

    def set_repartition_rewrite(self, checkpoint: dict[str, Any]) -> None:
        self.sync_type_config["repartition_rewrite"] = checkpoint
        self._save_sync_type_config()

    def clear_repartition_rewrite(self) -> None:
        self.sync_type_config.pop("repartition_rewrite", None)
        self._save_sync_type_config()

    @property
    def delta_revive_required(self) -> dict[str, Any] | None:
        """Set when the live Delta table is readable but hollow — its log references data files that
        are gone from S3 (the terminal state an interrupted or interleaved repartition swap leaves).
        `handle_corrupted_delta_log` honors this to reset + rebuild the table even though the log
        itself opens fine. Shape: {"reason": str, "missing_path": str, "detected_at": iso8601 str}.
        """
        if self.sync_type_config:
            marker = self.sync_type_config.get("delta_revive_required", None)
            if isinstance(marker, dict):
                return marker
        return None

    def set_delta_revive_required(self, info: dict[str, Any]) -> None:
        self.sync_type_config["delta_revive_required"] = info
        self._save_sync_type_config()

    @property
    def column_type_widened(self) -> dict[str, Any] | None:
        """Set by the v3 load consumer when a failed sync was classified as a safe numeric
        column-type widening and `reset_pipeline` was stamped alongside it, so the next scheduled
        sync resets and fully re-syncs the table (see `auto_widen_resync`). Read by the
        external-data health check to mute a failure that is about to self-heal; consumed by
        `update_sync_type_config_for_reset_pipeline` when any reset (automatic or manual) runs.
        Shape: {"column": str, "stored_type": str, "incoming_type": str, "detected_at": iso8601 str}.
        """
        if self.sync_type_config:
            marker = self.sync_type_config.get("column_type_widened", None)
            if isinstance(marker, dict):
                return marker
        return None

    @property
    def coarsen_requested(self) -> dict[str, Any] | None:
        """Set by `stage_warehouse_coarsening` to nominate this table for the coarsening rewrite.

        Nominating overrides the *policy* gates the automatic path applies (OOM history, layout age,
        minimum partition count) because an operator has looked at the table. It never
        overrides the *safety* checks: the controller still measures the live layout and refuses any
        target that would not fit the memory budget, so a nomination can only ever be a no-op, never a
        rewrite into partitions too big to merge. Consumed on the next evaluation either way.
        Shape: {"requested_at": iso8601 str, "requested_by": str}.
        """
        if self.sync_type_config:
            marker = self.sync_type_config.get("coarsen_requested", None)
            if isinstance(marker, dict):
                return marker
        return None

    def set_coarsen_requested(self, info: dict[str, Any]) -> None:
        self.sync_type_config["coarsen_requested"] = info
        self._save_sync_type_config()

    def clear_coarsen_requested(self) -> None:
        self.sync_type_config.pop("coarsen_requested", None)
        self._save_sync_type_config()

    def stamp_last_repartition_at(self) -> None:
        self.sync_type_config["last_repartition_at"] = timezone.now().isoformat()
        self._save_sync_type_config()

    def stage_incremental_field_value(self, run_uuid: str, last_value: Any, earliest_value: Any = None) -> None:
        """Hold a run's cursor in `incremental_staged` until the load side promotes it.

        The outgoing attempt of a run and the incoming attempt stage concurrently, and each holds its
        own in-memory copy of this row. The merge runs under the row lock so neither copy erases the
        other's entry.
        """
        values = {
            key: self._serialize_incremental_value(value)
            for key, value in (("last_value", last_value), ("earliest_value", earliest_value))
            if value is not None
        }
        self._stage_cursor_values(run_uuid, values)

    def stage_handoff_resume_value(self, run_uuid: str, resume_value: Any, owner_run_uuid: str | None = None) -> None:
        """Record the incremental value a later attempt of this workflow run can resume after.

        Stage only a value whose rows already have their queue rows, because the next attempt reads
        the source strictly above it. None records that this attempt has no such value, which stops
        the next attempt from using the value of an older attempt.

        `owner_run_uuid` is the run whose queue rows the value describes, for finalizing a later
        zero-batch continuation. It defaults to `run_uuid`, the common case of an attempt that just
        queued the batch the value describes.
        """
        self._stage_cursor_values(
            run_uuid,
            {
                STAGED_RESUME_VALUE_KEY: self._serialize_incremental_value(resume_value),
                STAGED_RESUME_OWNER_KEY: owner_run_uuid if owner_run_uuid is not None else run_uuid,
            },
        )

    def stage_source_cursor(self, run_uuid: str, payload: dict[str, Any]) -> None:
        """Hold a run's source cursor in `incremental_staged`, which the load side promotes with the watermark."""
        self._stage_cursor_values(run_uuid, {SOURCE_CURSOR_KEY: payload})

    def _stage_cursor_values(self, run_uuid: str, values: dict[str, Any]) -> None:
        def mutate(config: dict[str, Any]) -> None:
            live = config.get("incremental_staged", {})
            if live.get("run_uuid") == run_uuid:
                staged = live
            else:
                # A run that stages after a newer attempt displaced it continues its parked cursor,
                # so one run's values are never split between the live slot and the parked list.
                staged = _drop_parked_staged_cursor(config, run_uuid) or {"run_uuid": run_uuid}
                _park_displaced_staged_cursor(config, live)
            staged.update(values)
            config["incremental_staged"] = staged

        # Deferred: this module loads during django.setup() and the util pulls in temporalio.
        from posthog.temporal.common.utils import retry_on_db_connection_drop  # noqa: PLC0415

        self.sync_type_config = retry_on_db_connection_drop(
            lambda: update_sync_type_config_keys(self.id, self.team_id, mutate=mutate)
        )

    def promote_staged_incremental_values(
        self,
        run_uuid: str,
        merge_source_cursors: Callable[[Any, Any], dict[str, Any]] | None = None,
    ) -> bool:
        """Move the staged cursor of `run_uuid` onto the live watermark keys.

        Returns True when a staged cursor for the run existed, in the live slot or the parked list.
        The monotonic guard can still keep the current watermark, so True does not mean a key changed.
        """
        found = False

        def mutate(config: dict[str, Any]) -> None:
            nonlocal found
            live: dict[str, Any] | None = config.get("incremental_staged")
            if live is not None and live.get("run_uuid") != run_uuid:
                live = None
            staged = live if live is not None else _drop_parked_staged_cursor(config, run_uuid)
            if staged is None:
                return
            found = True
            field_type = config.get("incremental_field_type")
            if "last_value" in staged:
                _advance_promoted_cursor(
                    config, "incremental_field_last_value", staged["last_value"], "last", field_type
                )
            if "earliest_value" in staged:
                _advance_promoted_cursor(
                    config, "incremental_field_earliest_value", staged["earliest_value"], "earliest", field_type
                )
            if SOURCE_CURSOR_KEY in staged:
                candidate = staged[SOURCE_CURSOR_KEY]
                current = config.get(SOURCE_CURSOR_KEY)
                if current is not None:
                    if merge_source_cursors is None:
                        raise ValueError("Source cursor promotion requires a merger when a cursor is already stored")
                    candidate = merge_source_cursors(current, candidate)
                config[SOURCE_CURSOR_KEY] = candidate
            if live is not None:
                config.pop("incremental_staged", None)

        self.sync_type_config = update_sync_type_config_keys(self.id, self.team_id, mutate=mutate)
        return found

    def _serialize_incremental_value(self, value: Any) -> Any:
        incremental_field_type = self.sync_type_config.get("incremental_field_type")
        if "numpy" in sys.modules:
            import numpy  # noqa: PLC0415

            value = value.item() if isinstance(value, numpy.generic) else value
        if value is None:
            return None
        if (
            incremental_field_type == IncrementalFieldType.Integer
            or incremental_field_type == IncrementalFieldType.Numeric
        ):
            if isinstance(value, int | float):
                return value
            elif isinstance(value, datetime):
                return value.isoformat()
            else:
                return int(value)
        elif (
            incremental_field_type == IncrementalFieldType.DateTime
            or incremental_field_type == IncrementalFieldType.Timestamp
        ):
            if isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, int | float) and not isinstance(value, bool):
                return value
            else:
                return str(value)
        return str(value)

    def restart_full_refresh_clock(self) -> None:
        if self.full_refresh_interval_days is None:
            self.next_full_refresh_at = None
            return
        interval = timedelta(days=self.full_refresh_interval_days)
        now = timezone.now()
        if self.full_refresh_time_of_day is None:
            self.next_full_refresh_at = now + interval
            return
        # Count from the chosen time the wipe served, not from when it landed. A refresh can run up to the
        # slack early or wait for a later sync, and counting from the wipe would move the time every cycle.
        served = now + SCHEDULED_FULL_REFRESH_MAX_SLACK
        anchor = datetime.combine(served.date(), self.full_refresh_time_of_day, tzinfo=UTC)
        if anchor > served:
            anchor -= timedelta(days=1)
        self.next_full_refresh_at = anchor + interval

    def scheduled_full_refresh_due(self, now: datetime | None = None) -> bool:
        if (
            self.full_refresh_interval_days is None
            or self.next_full_refresh_at is None
            or self.sync_type not in SCHEDULED_FULL_REFRESH_SYNC_TYPES
        ):
            return False
        # The wipe that restarts the clock lands a little after its tick, so without slack every refresh would
        # slip one tick later than the one before.
        slack = SCHEDULED_FULL_REFRESH_MAX_SLACK
        if self.sync_frequency_interval is not None:
            slack = min(slack, self.sync_frequency_interval / 2)
        return (now or timezone.now()) >= self.next_full_refresh_at - slack

    def update_sync_type_config_for_reset_pipeline(self, *, clear_initial_sync_complete: bool = True) -> None:
        removes = [
            "reset_pipeline",
            # Any reset resolves a pending safe-widening marker; the re-created table adopts the new
            # type. column_type_widened_last_reset_at is deliberately kept so the auto-resync cooldown
            # survives the reset it timestamps.
            "column_type_widened",
            "incremental_field_last_value",
            "incremental_field_earliest_value",
            "incremental_staged",
            "incremental_staged_pending",
            APPEND_RUN_MARKER_KEY,
            "partitioning_enabled",
            "partition_size",
            "partition_count",
            "partitioning_keys",
            "partition_mode",
            "backfilled_partition_format",
            "partition_measurement",
            SOURCE_CURSOR_KEY,
            # Cursor keys from before `source_cursor`. A source still reads them when it has no
            # `source_cursor`, so a reset has to drop them too.
            "xmin_last_value",
            "xmin_ceiling",
            "xmin_num_wraparound",
        ]
        # We don't reset partition_format
        # We don't reset chunk_size_override
        # We intentionally don't reset partition_count_override / partition_size_override /
        # partition_mode_override / partitioning_keys_override: an operator pins those via the admin
        # repartition / change-partition-mode actions precisely so they survive this reset and win
        # the resync it triggers. They're consumed in set_partitioning_enabled.

        # Routine full-refresh syncs pass False: the flag is a "first sync ever completed" latch
        # consumed by webhook gating and schema-state displays, and clearing it on every run left
        # it false between runs whenever a sync wrote zero rows (no Delta table means post-load
        # never re-set it). Explicit resets (reset_pipeline, corruption rebuild, sync-method
        # change, delete_table) keep clearing so CDC's False->True streaming flip still fires.
        extra_model_fields = {"initial_sync_complete": False} if clear_initial_sync_complete else None

        # Merged under the row lock rather than saved from this copy: the sync loaded it when it
        # started, and CDC capture writes the same JSON meanwhile (the snapshot marker among it).
        self.sync_type_config = update_sync_type_config_keys(
            self.id,
            self.team_id,
            removes=removes,
            extra_model_fields=extra_model_fields,
            restart_full_refresh_clock=True,
        )
        if clear_initial_sync_complete:
            self.initial_sync_complete = False
        # This copy still holds the due time, and a later full save of it would wipe the table again.
        self.restart_full_refresh_clock()

    def update_incremental_field_value(
        self, last_value: Any, save: bool = True, type: Literal["last"] | Literal["earliest"] = "last"
    ) -> None:
        incremental_field_type = self.sync_type_config.get("incremental_field_type")

        # a numpy scalar can only arrive here if numpy is already imported (the import-pipeline
        # paths that produce one import it); gating keeps numpy off the django.setup() path
        if "numpy" in sys.modules:
            import numpy  # noqa: PLC0415

            last_value_py = last_value.item() if isinstance(last_value, numpy.generic) else last_value
        else:
            last_value_py = last_value
        last_value_json: Any

        if last_value_py is None:
            return

        if (
            incremental_field_type == IncrementalFieldType.Integer
            or incremental_field_type == IncrementalFieldType.Numeric
        ):
            if isinstance(last_value_py, int | float):
                last_value_json = last_value_py
            elif isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            else:
                last_value_json = int(last_value_py)
        elif (
            incremental_field_type == IncrementalFieldType.DateTime
            or incremental_field_type == IncrementalFieldType.Timestamp
        ):
            if isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            elif isinstance(last_value_py, int | float) and not isinstance(last_value_py, bool):
                last_value_json = last_value_py
            else:
                last_value_json = str(last_value_py)
        else:
            last_value_json = str(last_value_py)

        if type == "last":
            self.sync_type_config["incremental_field_last_value"] = last_value_json
        elif type == "earliest":
            self.sync_type_config["incremental_field_earliest_value"] = last_value_json
        else:
            raise ValueError(f"Unsupported type for update_incremental_field_value: {type}")

        if save:
            # A run calls this after every chunk with the copy it loaded at the start, so a full save would
            # put back settings the user changed during the run.
            self.save(update_fields=["sync_type_config", "updated_at"], skip_activity_log=True)

    def update_source_cursor(self, payload: dict[str, Any]) -> None:
        # Call only once the run's rows are durable: a mid-run crash then re-reads the window
        # instead of skipping it.
        self.sync_type_config = update_sync_type_config_keys(
            self.id, self.team_id, updates={SOURCE_CURSOR_KEY: payload}
        )

    def clear_source_cursor(self, legacy_keys: Iterable[str] = ()) -> None:
        """Drop the source cursor so the next run reads from the start of the source.

        `legacy_keys` names cursor keys from before `source_cursor`. Pass them for a source that
        still reads them, or the next run reads its cursor from them instead.
        """
        self.sync_type_config = update_sync_type_config_keys(
            self.id, self.team_id, removes=[SOURCE_CURSOR_KEY, *legacy_keys]
        )

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = timezone.now()
        self.save()

    def delete_table(self):
        # s3fs/boto3 at module scope would load at app population — only this method needs them
        from products.data_warehouse.backend.facade.api import get_s3_client  # noqa: PLC0415

        if self.table is not None:
            try:
                client = get_s3_client()
                client.delete(f"{settings.BUCKET_URL}/{self.folder_path()}", recursive=True)
            except FileNotFoundError:
                # s3fs raises this when nothing exists under the prefix. The files are already
                # gone, which is the state this method wants, so the teardown below still runs.
                logger.info("delete_table_prefix_already_deleted", schema_id=str(self.id), team_id=self.team_id)
            except Exception as e:
                capture_exception(e)

            if not self.table.deleted:
                self.table.soft_delete()

            self.table_id = None
            self.last_synced_at = None
            self.status = None
            self.save()

            self.update_sync_type_config_for_reset_pipeline()


# JS `Date.prototype.toString()` output (e.g. "Sun Mar 15 2026 16:59:47 GMT+0000 (Coordinated
# Universal Time)") appends a human-readable timezone name in parentheses that dateutil can't
# parse, even though the preceding GMT offset already fully specifies the instant.
JS_DATE_TOSTRING_TZ_NAME_RE = re.compile(r"\([^()]*\)\s*\Z")

# MySQL's zero-date convention for "no date set" ('0000-00-00', optionally with a
# '00:00:00' time part). Some REST sources (e.g. ServiceM8's `edit_date`) emit this literal
# string too, and dateutil raises ParserError on the year-0 value rather than treating it
# as absent.
ZERO_DATETIME_SENTINEL_RE = re.compile(r"\A0000-00-00(?:[ T]00:00:00(?:\.0+)?)?\Z")


def _is_zero_datetime_sentinel(value: str) -> bool:
    return bool(ZERO_DATETIME_SENTINEL_RE.match(value.strip()))


def _parse_datetime_string(value: str) -> datetime:
    try:
        return parser.parse(value)
    except parser.ParserError:
        stripped = JS_DATE_TOSTRING_TZ_NAME_RE.sub("", value)
        if stripped == value:
            raise
        return parser.parse(stripped)


def _align_epoch_cursor(value: Any, partner: Any) -> Any:
    # Two epoch numbers already order as numbers, so only a mixed pair needs the conversion.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    if not isinstance(partner, datetime | date):
        return value
    converted = datetime.fromtimestamp(value, tz=UTC)
    if isinstance(partner, datetime):
        return converted if partner.tzinfo else converted.replace(tzinfo=None)
    return converted.date()


def _park_displaced_staged_cursor(config: dict[str, Any], staged: dict[str, Any]) -> None:
    """A run is live or parked, never both: only another run's staging parks it, and its own
    staging moves it back. Both happen under the row lock."""
    cursor_keys = {"last_value", "earliest_value", SOURCE_CURSOR_KEY, STAGED_RESUME_VALUE_KEY}
    if not staged.get("run_uuid") or not (cursor_keys & staged.keys()):
        return
    pending = [*config.get("incremental_staged_pending", []), staged]
    config["incremental_staged_pending"] = pending[-STAGED_CURSOR_PENDING_LIMIT:]


def _drop_parked_staged_cursor(config: dict[str, Any], run_uuid: str) -> dict[str, Any] | None:
    """Remove the parked cursor of `run_uuid` and return it, or None when the run has none."""
    pending = config.get("incremental_staged_pending", [])
    dropped = next((entry for entry in pending if entry.get("run_uuid") == run_uuid), None)
    if dropped is None:
        return None
    remaining = [entry for entry in pending if entry.get("run_uuid") != run_uuid]
    if remaining:
        config["incremental_staged_pending"] = remaining
    else:
        config.pop("incremental_staged_pending", None)
    return dropped


def staged_handoff_resume_point(config: dict[str, Any], workflow_run_id: str | None) -> tuple[str, Any] | None:
    """The run that owns the queued rows, and the value, recorded by the newest attempt of
    `workflow_run_id`.

    The returned run is `STAGED_RESUME_OWNER_KEY`, not necessarily the attempt that most recently
    staged the entry: an attempt that only inherited the value, without queuing a batch of its own
    yet, stages it under its own `run_uuid` for parking purposes but records the earlier run as the
    owner. A caller that finalizes a zero-batch continuation needs the owner, since that is the run
    whose queue rows still need the final marker.
    """
    if not workflow_run_id:
        return None
    prefix = f"{workflow_run_id}-a"
    newest: dict[str, Any] | None = None
    newest_attempt = 0
    for staged in (config.get("incremental_staged") or {}, *config.get("incremental_staged_pending", [])):
        run_uuid = staged.get("run_uuid")
        if not isinstance(run_uuid, str) or not run_uuid.startswith(prefix):
            continue
        attempt = run_uuid.removeprefix(prefix)
        if attempt.isdigit() and int(attempt) > newest_attempt:
            newest, newest_attempt = staged, int(attempt)
    if newest is None:
        return None
    owner_run_uuid = newest.get(STAGED_RESUME_OWNER_KEY) or newest["run_uuid"]
    return owner_run_uuid, newest.get(STAGED_RESUME_VALUE_KEY)


def staged_handoff_resume_value(config: dict[str, Any], workflow_run_id: str | None) -> Any:
    """The value the newest attempt of `workflow_run_id` recorded with `stage_handoff_resume_value`.

    Only the newest attempt counts. An attempt that restarted from the stored watermark can replace
    the queue rows of the attempts before it, so their values no longer describe what the loader
    will load.
    """
    point = staged_handoff_resume_point(config, workflow_run_id)
    return None if point is None else point[1]


def _advance_promoted_cursor(
    config: dict[str, Any],
    key: str,
    value: Any,
    kind: Literal["last", "earliest"],
    field_type: IncrementalFieldType | None,
) -> None:
    current = config.get(key)
    if current is None:
        config[key] = value
        return
    comparison = _compare_incremental_values(current, value, field_type)
    # For a pair the comparator cannot order (a null field type, a naive against an aware datetime,
    # or a millisecond epoch) the newest promotion wins, so those sources still advance their
    # watermark. Keeping the current value would freeze it for good.
    if comparison is None or (kind == "last" and comparison < 0) or (kind == "earliest" and comparison > 0):
        config[key] = value


def _compare_incremental_values(current: Any, candidate: Any, field_type: IncrementalFieldType | None) -> int | None:
    try:
        left = process_incremental_value(current, field_type)
        right = process_incremental_value(candidate, field_type)
        left, right = _align_epoch_cursor(left, right), _align_epoch_cursor(right, left)
    except Exception:
        return None
    if left is None or right is None:
        return None
    if field_type == IncrementalFieldType.ObjectID:
        # An ObjectID is 24 hex digits that open with its creation time, so equal-length ids order
        # as strings. Anything else is unordered.
        if isinstance(left, str) and isinstance(right, str) and len(left) == len(right):
            return (left > right) - (left < right)
        return None
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    left_is_number = isinstance(left, int | float)
    right_is_number = isinstance(right, int | float)
    if left_is_number != right_is_number:
        return None
    if not left_is_number and not isinstance(left, datetime | date):
        return None
    try:
        return (left > right) - (left < right)
    except TypeError:
        return None


def _coerce_incremental_datetime(value: str) -> datetime | int:
    """Parse a DateTime/Timestamp/Date cursor string, falling back to a raw integer.

    Some drivers surface a numeric cursor as a bare digit string even though the field is
    typed as a date/time type (e.g. a ClickHouse column Arrow can't emit natively, cast to
    String, whose current type no longer matches the incremental field's stored type).
    dateutil's heuristics then misread the digits as a calendar year and overflow past
    datetime's year-9999 ceiling (`ParserError`), or raise a bare `OverflowError` for longer
    digit runs. Legitimate compact date strings like "20240115" (YYYYMMDD) parse correctly
    above and never reach this fallback.
    """
    try:
        return _parse_datetime_string(value)
    except (parser.ParserError, OverflowError):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
        raise


def process_incremental_value(value: Any | None, field_type: IncrementalFieldType | None) -> Any:
    if value is None or value == "None" or field_type is None:
        return None

    if (
        field_type == IncrementalFieldType.Integer
        or field_type == IncrementalFieldType.Numeric
        or field_type == IncrementalFieldType.XID
    ):
        return value

    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        if isinstance(value, datetime):
            return value

        # A date-only column (e.g. a MySQL DATE) can back a DateTime/Timestamp field when the column
        # type changed after the incremental field was saved.
        if isinstance(value, date):
            return datetime.combine(value, time.min)

        # Some sources (e.g. Stripe `created`) expose datetime cursors as Unix-epoch numbers.
        # dateutil can't parse a non-string, so pass epochs through unchanged for the source query.
        if isinstance(value, int | float) and not isinstance(value, bool):
            return value

        if isinstance(value, str) and _is_zero_datetime_sentinel(value):
            return None

        return _coerce_incremental_datetime(value)

    if field_type == IncrementalFieldType.Date:
        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        if isinstance(value, int | float) and not isinstance(value, bool):
            return value

        if isinstance(value, str) and _is_zero_datetime_sentinel(value):
            return None

        parsed = _coerce_incremental_datetime(value)
        return parsed if isinstance(parsed, int) else parsed.date()

    if field_type == IncrementalFieldType.ObjectID:
        return str(value)


def apply_incremental_lookback(
    value: Any, field_type: IncrementalFieldType | None, lookback_seconds: int | None
) -> Any:
    """Shift a processed incremental watermark back by `lookback_seconds` for the source query only.

    Used to re-read a rolling overlap window each incremental run so late or backdated rows (whose
    incremental field lands at or below the stored watermark) are picked up. The persisted watermark
    is never mutated — this only adjusts the value bound into the source's WHERE clause. Timestamp/date
    fields only; for `Date` a sub-day lookback rounds down to whole days.
    """
    if value is None or not isinstance(lookback_seconds, int) or lookback_seconds <= 0:
        return value

    if field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp, IncrementalFieldType.Date):
        # Epoch-number cursors (e.g. Stripe `created`) are in seconds, so shift them directly since
        # timedelta subtraction only supports datetime/date operands.
        if isinstance(value, int | float) and not isinstance(value, bool):
            return value - lookback_seconds
        return value - timedelta(seconds=lookback_seconds)

    return value


@database_sync_to_async
def asave_external_data_schema(schema: ExternalDataSchema) -> None:
    schema.save()


def get_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    schema = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, source_id=source_id, name=schema_name)
        .first()
    )
    return schema


@database_sync_to_async
def aget_schema_by_id(schema_id: str, team_id: int) -> ExternalDataSchema | None:
    return (
        ExternalDataSchema.objects.prefetch_related("source").exclude(deleted=True).get(id=schema_id, team_id=team_id)
    )


def update_should_sync(
    schema_id: str,
    team_id: int,
    should_sync: bool,
    *,
    disable_error_message: str | None = None,
    disable_exclude_workflow_id: str | None = None,
) -> ExternalDataSchema | None:
    # data_load.service imports temporalio at module scope; this is a models module, so a
    # top-level import would put the Temporal client on the django.setup() path
    from products.data_warehouse.backend.facade.api import (  # noqa: PLC0415
        external_data_workflow_exists,
        pause_external_data_schedule,
        sync_external_data_job_workflow,
        unpause_external_data_schedule,
    )

    schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id, team_id=team_id)
    schema.should_sync = should_sync
    # Turning syncing back on says the source is worth trying again, so the next run starts on
    # the full retry cap and the normal cadence.
    if should_sync:
        schema.clear_failure_streak()
    with sync_disable_context(error_message=disable_error_message, exclude_workflow_id=disable_exclude_workflow_id):
        schema.save()

    if not schema.source.supports_scheduled_sync:
        return schema

    schedule_exists = external_data_workflow_exists(schema_id)

    if schedule_exists:
        if should_sync is False:
            pause_external_data_schedule(schema_id)
        elif should_sync is True:
            unpause_external_data_schedule(schema_id)
    else:
        if should_sync is True:
            sync_external_data_job_workflow(schema, create=True)

    return schema


def update_sync_type_config_keys(
    schema_id: str | uuid.UUID,
    team_id: int,
    *,
    updates: dict[str, Any] | None = None,
    removes: Iterable[str] | None = None,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    extra_model_fields: dict[str, Any] | None = None,
    restart_full_refresh_clock: bool = False,
) -> dict[str, Any]:
    """Atomically merge keys into a schema's `sync_type_config` under a row lock and return the
    persisted config.

    The CDC extract activity holds a long-lived in-memory schema and writes `sync_type_config`
    repeatedly across a run, while API PATCHes rewrite the same JSON concurrently. A
    read-modify-write off a copy loaded earlier loses whichever side saved last. Re-fetching the
    row inside the transaction with `select_for_update` makes every writer merge onto the latest
    committed value instead of clobbering it.

    `updates` sets keys, `removes` pops keys, and `mutate` runs last for in-place edits of nested
    structures that must happen inside the critical section.
    Callers refresh their in-memory copy from the returned dict.

    `extra_model_fields` saves additional model fields in the same transaction and row lock — use
    when a reset must flip both `sync_type_config` and another field (e.g. `initial_sync_complete`)
    atomically so no reader can observe the half-written state.

    `restart_full_refresh_clock` sets `next_full_refresh_at` from the locked row's interval, which may
    be newer than the caller's copy. The returned dict does not carry it.

    Saves with `skip_activity_log=True`: `sync_type_config` is excluded from the schema's audit
    diff anyway, and the bypass skips the extra `_get_before_update` SELECT that can fail when the
    pooler drops the connection mid-sync.
    """
    with transaction.atomic():
        schema = ExternalDataSchema.objects.select_for_update().get(id=schema_id, team_id=team_id)
        config = schema.sync_type_config or {}
        if updates:
            config.update(updates)
        if removes:
            for key in removes:
                config.pop(key, None)
        if mutate is not None:
            mutate(config)
        schema.sync_type_config = config
        update_fields = ["sync_type_config", "updated_at"]
        if extra_model_fields:
            for field, value in extra_model_fields.items():
                setattr(schema, field, value)
                update_fields.append(field)
        if restart_full_refresh_clock:
            # From the locked row's interval, which may be newer than the caller's copy.
            schema.restart_full_refresh_clock()
            update_fields.append("next_full_refresh_at")
        schema.save(update_fields=update_fields, skip_activity_log=True)
        return config


def save_repartition_checkpoint_if_claimed(
    schema: ExternalDataSchema, *, claim_token: str, checkpoint: dict[str, Any]
) -> bool:
    """Write a rewrite checkpoint only while `claim_token` still owns the schema. Returns whether it did.

    Checking the claim before calling `set_repartition_rewrite` is not enough: that saves the whole
    `sync_type_config` column from an in-memory copy, so a worker superseded between the check and the
    save writes back its own stale `repartition_claim` and un-fences itself. Re-reading the claim under
    the row lock, in the same transaction as the write, closes that window — the same reason
    `update_sync_type_config_keys` exists.
    """
    claimed = False

    def _write(config: dict[str, Any]) -> None:
        nonlocal claimed
        claim = config.get("repartition_claim")
        if not (claim and claim.get("token") == claim_token):
            return
        config["repartition_rewrite"] = checkpoint
        claimed = True

    update_sync_type_config_keys(schema_id=schema.id, team_id=schema.team_id, mutate=_write)
    return claimed


def finalize_repartition_scheme(
    schema: ExternalDataSchema,
    *,
    partitioning_keys: list[str],
    partition_count: int | None,
    partition_size: int | None,
    partition_mode: PartitionMode | None,
    partition_format: PartitionFormat | None,
    claim_token: str | None = None,
) -> bool:
    """Adopt the scheme a completed repartition swap put on disk, and retire its markers, in one write.

    The swap has already re-bucketed the data in S3, so until these settings land the schema row
    describes a layout the table no longer has. An incremental merge in that window scopes its
    predicate to a `_ph_partition_key` value the table cannot contain, matches nothing, and inserts
    every fetched row instead of upserting it. `set_partitioning_enabled` plus the three marker
    writes leave four separate chances to stop halfway; doing it under one row lock means a reader
    sees either the whole new scheme or the untouched `repartition_swap` marker that says the swap is
    still unresolved.

    Returns whether the write happened. False means `claim_token` no longer owns the schema, so a
    newer attempt owns this swap and will finalize it.
    """
    wrote = False

    def _write(config: dict[str, Any]) -> None:
        nonlocal wrote
        if claim_token is not None:
            claim = config.get("repartition_claim")
            if not (claim and claim.get("token") == claim_token):
                return
        config["partitioning_enabled"] = True
        config["partition_count"] = partition_count
        config["partition_size"] = partition_size
        config["partitioning_keys"] = partitioning_keys
        config["partition_mode"] = partition_mode
        config["partition_format"] = partition_format
        # Engage the cooldown here rather than in a follow-up write, or a stop between the two
        # re-flags the table on the next sync and repartitions it again straight away.
        config["last_repartition_at"] = timezone.now().isoformat()
        for key in (
            # Operator pins are one-shot: they are baked into the settings above, so a later reset
            # falls back to auto-detection (see `set_partitioning_enabled`).
            "partition_count_override",
            "partition_size_override",
            "partition_mode_override",
            "partitioning_keys_override",
            "repartition_swap",
            "repartition_pending",
            "repartition_rewrite",
            "partition_measurement",
        ):
            config.pop(key, None)
        wrote = True

    schema.sync_type_config = update_sync_type_config_keys(schema_id=schema.id, team_id=schema.team_id, mutate=_write)
    return wrote


def stage_partition_scheme_for_full_refresh(
    schema: ExternalDataSchema,
    *,
    partitioning_keys: list[str],
    partition_count: int | None,
    partition_size: int | None,
    partition_mode: PartitionMode | None,
    partition_format: PartitionFormat | None,
    claim_token: str | None = None,
) -> bool:
    """Pin a new partition scheme for the next full refresh to write, and retire the repartition markers.

    A full-refresh sync deletes the table and writes it again, so it can lay out the new scheme with
    no rewrite at all. The scheme goes in as the `*_override` keys because the reset at the start of
    that sync removes the plain partition settings, and the overrides are the keys it keeps for the
    sync to consume (see `update_sync_type_config_for_reset_pipeline` and `set_partitioning_enabled`).
    `partition_format` survives the reset on its own.
    """
    overrides: dict[str, Any] = {
        "partitioning_keys_override": partitioning_keys or None,
        "partition_count_override": partition_count,
        "partition_size_override": partition_size,
        "partition_mode_override": partition_mode,
    }

    wrote = False

    def _write(config: dict[str, Any]) -> None:
        nonlocal wrote
        if claim_token is not None:
            claim = config.get("repartition_claim")
            if not (claim and claim.get("token") == claim_token):
                return
        if config.get("repartition_swap") is not None:
            return
        for key, value in overrides.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        if partition_format is not None:
            config["partition_format"] = partition_format
        # The cooldown stops detection from flagging the old layout again before the sync rewrites it.
        config["last_repartition_at"] = timezone.now().isoformat()
        for key in ("repartition_swap", "repartition_pending", "repartition_rewrite"):
            config.pop(key, None)
        wrote = True

    schema.sync_type_config = update_sync_type_config_keys(schema_id=schema.id, team_id=schema.team_id, mutate=_write)
    return wrote


def mark_schema_running_unless_halted(schema: ExternalDataSchema) -> bool:
    """Paint a schema Running at the start of a run, unless a CDC halt marker holds.

    A halted schema absorbs every later status update, so Running painted over it would hide its
    FAILED status and error until the marker clears. One conditional UPDATE: a marker written
    under the row lock either commits first and blocks this, or commits after and repaints FAILED.
    """
    updated = (
        ExternalDataSchema.objects.filter(id=schema.id, team_id=schema.team_id)
        .exclude(sync_type_config__has_key="cdc_broken")
        .exclude(sync_type_config__has_key="cdc_extraction_paused")
        .update(status=ExternalDataSchema.Status.RUNNING, updated_at=timezone.now())
    )
    if updated:
        schema.status = ExternalDataSchema.Status.RUNNING
    return bool(updated)


def mark_initial_sync_complete(schema_id: str | uuid.UUID, team_id: int) -> None:
    """Mark a schema's first successful sync complete. Called by the V3 loader's post-load.

    On the False→True transition, a CDC schema still in snapshot mode moves to
    ``cdc_mode="streaming"`` in the same row lock. Callers must only invoke this once the
    run's data has durably landed in the destination table — the streaming flip is what lets
    the scheduled sync start merging the change buffer, and merges against a half-loaded
    snapshot corrupt the table. Locked for the same reason as ``update_sync_type_config_keys``:
    the CDC extract activity writes ``sync_type_config`` concurrently, and an unlocked
    read-modify-write here could clobber its keys.
    """
    with transaction.atomic():
        schema = ExternalDataSchema.objects.select_for_update().exclude(deleted=True).get(id=schema_id, team_id=team_id)
        if schema.initial_sync_complete:
            return

        schema.initial_sync_complete = True
        update_fields = ["initial_sync_complete", "updated_at"]

        if schema.is_cdc and schema.cdc_mode == "snapshot":
            config = schema.sync_type_config or {}
            config["cdc_mode"] = "streaming"
            # In the same lock as the flip, so a hand-over retried after a failed flip still finds it.
            config.pop(CDC_SNAPSHOT_LANE_KEY, None)
            schema.sync_type_config = config
            update_fields.append("sync_type_config")

        schema.save(update_fields=update_fields, skip_activity_log=True)


def get_all_schemas_for_source_id(source_id: str, team_id: int):
    return list(ExternalDataSchema.objects.exclude(deleted=True).filter(team_id=team_id, source_id=source_id).all())


@frozen
class DirectSchemaReconciliation:
    active_schemas: list[ExternalDataSchema]
    stale_schemas: list[ExternalDataSchema]


def get_schemas_for_direct_reconciliation(
    source_id: str | uuid.UUID,
    team_id: int,
    current_schema_names: list[str],
) -> DirectSchemaReconciliation:
    candidates = list(
        ExternalDataSchema.objects.filter(
            models.Q(team_id=team_id, source_id=source_id),
            models.Q(deleted=False) | models.Q(table__deleted=False),
        ).select_related("table")
    )
    active = [schema for schema in candidates if schema.deleted is False]
    current_names = set(current_schema_names)
    stale = [schema for schema in candidates if schema.name not in current_names]
    return DirectSchemaReconciliation(active_schemas=active, stale_schemas=stale)


# A discovered schema can carry a stable identifier for its upstream resource under this key in its
# `schema_metadata`. A source sets it when the resource keeps its identity through an upstream rename (a
# Google Sheets worksheet keeps its sheet id when its title changes). Reconciliation then keeps the
# stored schema, its table and its sync settings across the rename instead of disabling the schema and
# offering the new name as a separate one.
SCHEMA_RESOURCE_ID_METADATA_KEY = "source_resource_id"


def _resource_id(metadata: object) -> str | None:
    if isinstance(metadata, dict) and metadata.get(SCHEMA_RESOURCE_ID_METADATA_KEY) is not None:
        return str(metadata[SCHEMA_RESOURCE_ID_METADATA_KEY])
    return None


def _renamed_schema_names(
    old_schemas: list["ExternalDataSchema"],
    new_schema_names: list[str],
    schema_metadata_by_name: dict[str, dict],
) -> dict[str, str]:
    """Map each discovered name that is a renamed stored schema to that schema's stored name."""
    stored_names = {schema.name for schema in old_schemas}
    stored_name_by_resource_id: dict[str, str] = {}
    for schema in old_schemas:
        resource_id = _resource_id(schema.schema_metadata)
        if resource_id is not None:
            stored_name_by_resource_id[resource_id] = schema.name

    renames: dict[str, str] = {}
    for new_name in new_schema_names:
        if new_name in stored_names:
            continue
        resource_id = _resource_id(schema_metadata_by_name.get(new_name))
        stored_name = stored_name_by_resource_id.get(resource_id) if resource_id is not None else None
        if stored_name is None:
            continue
        resource_at_stored_name = _resource_id(schema_metadata_by_name.get(stored_name))
        if stored_name not in new_schema_names or resource_at_stored_name != resource_id:
            renames[new_name] = stored_name
    return renames


def _apply_schema_renames[T](values: dict[str, T], renames: dict[str, str]) -> dict[str, T]:
    rename_destinations = set(renames.values())
    remapped = {
        name: value for name, value in values.items() if name not in rename_destinations and name not in renames
    }
    remapped.update({renames[name]: values[name] for name in renames})
    return remapped


def _store_discovered_resource_ids(
    old_schemas: list["ExternalDataSchema"], schema_metadata_by_name: dict[str, dict]
) -> None:
    for schema in old_schemas:
        discovered_id = _resource_id(schema_metadata_by_name.get(schema.name))
        if discovered_id is None or _resource_id(schema.schema_metadata) == discovered_id:
            continue

        def store_resource_id(config: dict[str, Any], discovered_id: str = discovered_id) -> None:
            metadata = config.get("schema_metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            config["schema_metadata"] = {**metadata, SCHEMA_RESOURCE_ID_METADATA_KEY: discovered_id}

        schema.sync_type_config = update_sync_type_config_keys(
            schema_id=schema.id, team_id=schema.team_id, mutate=store_resource_id
        )


def _update_labels(old_schemas: list["ExternalDataSchema"], new_schemas: dict[str, str | None]) -> None:
    for schema in old_schemas:
        new_label = new_schemas.get(schema.name)
        if new_label is not None and schema.label != new_label:
            schema.label = new_label
            schema.save(update_fields=["label", "updated_at"])


@frozen
class SchemaSyncResult:
    created: list[str]
    deleted: list[str]


def _pause_schedule_then_disable_schema(schema: "ExternalDataSchema") -> None:
    """Pause a discovery-removed table's schedule, and only then persist the table as off.

    The sync workflow does not read `should_sync`, so the schedule is what actually stops the
    billable runs. Writing the row off first would strand the table whenever the pause fails: the
    schedule keeps starting runs, and the next discovery run sees a row that is already off, so it
    never retries the pause. Keeping the row on until the pause lands makes a failed pause
    self-healing, because the table is still on and still unlisted when discovery next runs.

    Nothing here raises: Django drops the remaining `on_commit` callbacks once one of them raises,
    so an error would also strand every other table removed in the same commit, and on the API
    paths it would fail a request whose reconcile already committed. A pause that lands without its
    write (or without its teardown dispatch) heals the same way, on the next discovery run. The
    write is scoped to its own columns because the row was read before the commit, so a full save
    would push back whatever a concurrent writer changed in the meantime.
    """
    # Call-time import for the reason given in update_should_sync above.
    from products.data_warehouse.backend.facade.api import pause_external_data_schedule  # noqa: PLC0415

    try:
        pause_external_data_schedule(str(schema.id))
        schema.should_sync = False
        schema.status = ExternalDataSchema.Status.COMPLETED
        schema.save(update_fields=["should_sync", "status", "updated_at"])
    except Exception:
        logger.exception(
            "discovery_removed_schema_disable_failed",
            external_data_schema_id=str(schema.id),
            team_id=schema.team_id,
        )


def sync_old_schemas_with_new_schemas(
    new_schemas: dict[str, str | None],
    source_id: str,
    team_id: int,
    descriptions: dict[str, str | None] | None = None,
    strict_name_match: bool = False,
    schema_metadata_by_name: dict[str, dict] | None = None,
) -> SchemaSyncResult:
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    old_schemas_names = [schema.name for schema in old_schemas]

    if schema_metadata_by_name:
        # Discovery reports a renamed resource under its new name. Name it as the stored schema from
        # here on, so the matching below keeps that row and refreshes its label to the new name.
        renames = _renamed_schema_names(old_schemas, list(new_schemas), schema_metadata_by_name)
        if renames:
            new_schemas = _apply_schema_renames(new_schemas, renames)
            if descriptions:
                descriptions = _apply_schema_renames(descriptions, renames)
            schema_metadata_by_name = _apply_schema_renames(schema_metadata_by_name, renames)
        _store_discovered_resource_ids(old_schemas, schema_metadata_by_name)

    if descriptions:
        for old_schema in old_schemas:
            new_description = descriptions.get(old_schema.name)
            if old_schema.description != new_description:
                old_schema.description = new_description
                old_schema.save(update_fields=["description", "updated_at"])

    # Update display labels on existing schemas
    _update_labels(old_schemas, new_schemas)

    new_schema_names = list(new_schemas.keys())

    # Discovery names a table qualified (`schema.table`) or bare (`table`) depending on config, so
    # bare and qualified mean the same table — else a live row is wrongly disabled/duplicated. Two
    # qualified names still need exact equality so same-named tables in different schemas stay distinct.
    # `strict_name_match` disables the bare↔qualified equivalence for sources where bare and
    # qualified rows coexist by design (GitHub keeps its legacy repo's rows bare forever, so
    # `owner/other.issues` must NOT match the legacy bare `issues` row).
    def _same_table(a: str, b: str) -> bool:
        if strict_name_match:
            return a == b
        one_qualified = ("." in a) != ("." in b)
        return a == b or (one_qualified and a.rpartition(".")[2] == b.rpartition(".")[2])

    # Create discovered names not already stored; flag stored names discovery no longer reports.
    schemas_to_create: list[str] = []
    for new_name in new_schema_names:
        if not any(_same_table(new_name, old_name) for old_name in old_schemas_names):
            schemas_to_create.append(new_name)

    schemas_to_possibly_delete: list[str] = []
    for old_name in old_schemas_names:
        if not any(_same_table(old_name, new_name) for new_name in new_schema_names):
            schemas_to_possibly_delete.append(old_name)
    deleted_schemas: list[str] = []
    actually_created: list[str] = []

    for schema in schemas_to_create:
        seeded_metadata = (schema_metadata_by_name or {}).get(schema)
        deleted_obj = (
            ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id, name=schema, deleted=True)
            .order_by("-updated_at", "-created_at")
            .first()
        )
        if deleted_obj is not None:
            deleted_obj.deleted = False
            deleted_obj.deleted_at = None
            deleted_obj.description = descriptions.get(schema) if descriptions else None
            deleted_obj.label = new_schemas.get(schema)
            update_fields = ["deleted", "deleted_at", "description", "label", "updated_at"]
            if seeded_metadata:
                existing_config = deleted_obj.sync_type_config or {}
                existing_metadata = existing_config.get("schema_metadata")
                merged = {**(existing_metadata if isinstance(existing_metadata, dict) else {}), **seeded_metadata}
                deleted_obj.sync_type_config = {**existing_config, "schema_metadata": merged}
                update_fields.append("sync_type_config")
            deleted_obj.save(update_fields=update_fields)
            actually_created.append(schema)
            continue

        obj, created = ExternalDataSchema.objects.get_or_create(
            team_id=team_id,
            source_id=source_id,
            name=schema,
            deleted=False,
            defaults={
                "should_sync": False,
                "description": descriptions.get(schema) if descriptions else None,
                "label": new_schemas.get(schema),
                **({"sync_type_config": {"schema_metadata": seeded_metadata}} if seeded_metadata else {}),
            },
        )
        if created:
            actually_created.append(schema)

    for schema in schemas_to_possibly_delete:
        # There _could_ exist multiple schemas with the same name, there shouldn't be, but it's not impossible
        schemas_to_check = ExternalDataSchema.objects.filter(
            team_id=team_id, name=schema, source_id=source_id, deleted=False
        )
        for s in schemas_to_check:
            # Only rows nobody enabled disappear entirely. A user-enabled row survives as visibly
            # disabled, because soft-deleting it would silently discard the user's selection (e.g.
            # a scope-gated table the source stopped offering before its first successful sync).
            if s.table_id is None and not s.should_sync:
                s.soft_delete()
                deleted_schemas.append(schema)
            elif s.should_sync:
                # After the commit because callers can hold the source row lock, and the Temporal
                # call must not run inside it. A row already off needs no pause, and pausing it
                # again every run would open a Temporal connection per table per run.
                transaction.on_commit(partial(_pause_schedule_then_disable_schema, s))
            else:
                s.status = ExternalDataSchema.Status.COMPLETED
                s.save()

    return SchemaSyncResult(created=actually_created, deleted=deleted_schemas)


def schema_name_matches_auto_sync_patterns(name: str, patterns: list[str] | None) -> bool:
    """Whether a discovered schema name qualifies for auto-sync under a source's glob patterns.

    Patterns are fnmatch globs matched case-insensitively against both the stored name and its
    unqualified tail — mirroring `_same_table`'s bare↔qualified equivalence, so `raw_*` matches
    `public.raw_events`. No patterns means every name qualifies.
    """
    cleaned = [pattern.strip().lower() for pattern in patterns or [] if isinstance(pattern, str) and pattern.strip()]
    if not cleaned:
        return True

    candidates = {name.lower(), name.rpartition(".")[2].lower()}
    return any(fnmatch.fnmatchcase(candidate, pattern) for pattern in cleaned for candidate in candidates)


def auto_enable_new_schemas(
    source: "ExternalDataSource",
    created_schema_names: list[str],
    source_schemas_by_name: dict[str, "SourceSchema"],
) -> list[str]:
    """Enable syncing for newly discovered schemas on sources that opted into auto-sync.

    Only rows still in the untouched discovery state (disabled, no sync type) are considered, so
    revived rows keep whatever a user configured before and retries are idempotent. Sync config
    comes from the same defaults as one-shot setup; each enabled schema gets a Temporal schedule
    and an immediate first sync, like flipping the toggle in the UI.
    """
    if not created_schema_names or not source.auto_sync_new_schemas or not source.supports_scheduled_sync:
        return []

    # Call-time imports: the sources package's import chain pulls the source registry back into
    # these models, and data_load.service puts temporalio on the django.setup() path (see
    # update_should_sync above).
    from products.data_warehouse.backend.facade.api import sync_external_data_job_workflow  # noqa: PLC0415
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (  # noqa: PLC0415
        build_default_schemas,
    )

    enabled: list[str] = []
    candidates = ExternalDataSchema.objects.filter(
        team_id=source.team_id,
        source_id=source.id,
        name__in=created_schema_names,
        deleted=False,
        should_sync=False,
        sync_type__isnull=True,
    )
    for schema in candidates:
        if not schema_name_matches_auto_sync_patterns(schema.name, source.auto_sync_schema_patterns):
            continue

        source_schema = source_schemas_by_name.get(schema.name)
        if source_schema is None:
            continue

        defaults = build_default_schemas([source_schema])[0]
        if not defaults.get("should_sync"):
            # Webhook-only tables and tables the source marks default-off need explicit opt-in.
            continue

        sync_type = defaults["sync_type"]
        original_sync_type_config = schema.sync_type_config
        sync_type_config = {**(original_sync_type_config or {})}
        if defaults.get("incremental_field") is not None:
            sync_type_config["incremental_field"] = defaults["incremental_field"]
            sync_type_config["incremental_field_type"] = defaults["incremental_field_type"]
        if defaults.get("primary_key_columns"):
            sync_type_config["primary_key_columns"] = defaults["primary_key_columns"]
        if (
            sync_type == ExternalDataSchema.SyncType.INCREMENTAL
            and source_schema.default_incremental_lookback_seconds is not None
        ):
            sync_type_config["incremental_field_lookback_seconds"] = source_schema.default_incremental_lookback_seconds

        # Claim the row under a lock before enabling it, so a discovery pass running concurrently
        # (a second "Pull new schemas" click, or the 6h schedule firing alongside a manual refresh)
        # can't also enable the same row and fire a duplicate first sync. Re-read inside the lock
        # and bail if it is no longer the untouched discovery row.
        try:
            with transaction.atomic():
                locked = ExternalDataSchema.objects.select_for_update().get(id=schema.id, team_id=source.team_id)
                if locked.should_sync or locked.sync_type is not None:
                    continue
                locked.sync_type = sync_type
                locked.sync_type_config = sync_type_config
                locked.should_sync = True
                locked.save()
        except Exception as e:
            # A bad schema must not block the rest; nothing was persisted, so the next discovery
            # pass reconsiders this row unchanged.
            capture_exception(e)
            continue

        try:
            sync_external_data_job_workflow(locked, create=True)
            enabled.append(locked.name)
        except Exception as e:
            # Scheduling talks to Temporal and can fail after we persisted the enabled state. Roll
            # the row back to the untouched discovery state so the next discovery pass retries it —
            # this helper only reconsiders disabled, untyped rows, so leaving it enabled would strand
            # it without a schedule or first sync until someone reloaded the source by hand.
            capture_exception(e)
            try:
                with transaction.atomic():
                    revert = ExternalDataSchema.objects.select_for_update().get(id=locked.id, team_id=source.team_id)
                    revert.should_sync = False
                    revert.sync_type = None
                    revert.sync_type_config = original_sync_type_config
                    revert.save()
            except Exception as rollback_error:
                capture_exception(rollback_error)

    return enabled


def sync_frequency_to_sync_frequency_interval(frequency: str) -> timedelta | None:
    if frequency == "never":
        return None
    if frequency == "1min":
        return timedelta(minutes=1)
    if frequency == "5min":
        return timedelta(minutes=5)
    if frequency == "15min":
        return timedelta(minutes=15)
    if frequency == "30min":
        return timedelta(minutes=30)
    if frequency == "1hour":
        return timedelta(hours=1)
    if frequency == "6hour":
        return timedelta(hours=6)
    if frequency == "12hour":
        return timedelta(hours=12)
    if frequency == "24hour":
        return timedelta(hours=24)
    if frequency == "7day":
        return timedelta(days=7)
    if frequency == "30day":
        return timedelta(days=30)

    raise ValueError(f"Frequency {frequency} is not supported")


def sync_frequency_interval_to_sync_frequency(sync_frequency_interval: timedelta | None) -> str | None:
    if sync_frequency_interval is None:
        return None
    if sync_frequency_interval == timedelta(minutes=1):
        return "1min"
    if sync_frequency_interval == timedelta(minutes=5):
        return "5min"
    if sync_frequency_interval == timedelta(minutes=15):
        return "15min"
    if sync_frequency_interval == timedelta(minutes=30):
        return "30min"
    if sync_frequency_interval == timedelta(hours=1):
        return "1hour"
    if sync_frequency_interval == timedelta(hours=6):
        return "6hour"
    if sync_frequency_interval == timedelta(hours=12):
        return "12hour"
    if sync_frequency_interval == timedelta(hours=24):
        return "24hour"
    if sync_frequency_interval == timedelta(days=7):
        return "7day"
    if sync_frequency_interval == timedelta(days=30):
        return "30day"

    raise ValueError(f"Frequency interval {sync_frequency_interval} is not supported")
