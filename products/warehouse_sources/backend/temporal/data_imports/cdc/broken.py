"""Mark a CDC source as broken.

When change data capture can no longer make progress on its own — the safety net dropped
the slot after critical lag, or an extraction hit a missing slot/publication — the source
must move to an explicit, user-visible "broken" state instead of silently retrying forever.

This persists the broken state across three surfaces that the UI and health check already read:

- ``source.status = ERROR`` — the source-level "something is wrong" signal.
- per-CDC-schema ``sync_type_config["cdc_broken"]`` plus ``status=FAILED`` / friendly ``latest_error``.
- the Temporal extraction schedule is paused so it stops firing against a resource that is gone.

Clearing ``cdc_broken`` and unpausing the schedule (done by ``repair_cdc`` / ``disable_cdc``)
restores operation — see the recovery contract in those API actions.
"""

from __future__ import annotations

import typing
import datetime as dt

import structlog
import posthoganalytics

from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    _build_schema_snapshot,
)

logger = structlog.get_logger(__name__)


def mark_cdc_broken(
    source: ExternalDataSource,
    reason: str,
    message: str,
    *,
    pause: bool = True,
    create_visibility_jobs: bool = True,
    **extra: typing.Any,
) -> None:
    """Move a CDC source into the broken state.

    ``reason`` is a stable machine code (e.g. ``"auto_dropped_critical_lag"``); ``message`` is the
    friendly, credential-safe copy shown to the user. ``pause`` controls whether the extraction
    schedule is paused — left on for PostHog-managed breakage (the slot is gone, retrying is futile)
    and turned off for self-managed critical lag, whose customer-owned slot may still recover.
    ``create_visibility_jobs`` is turned off by callers inside a run (the extraction activity),
    which already record their own FAILED job rows. ``extra`` keys (e.g. ``lag_mb``) are merged
    into the persisted ``cdc_broken`` marker.
    """
    log = logger.bind(source_id=str(source.id), team_id=source.team_id, reason=reason)

    source.status = ExternalDataSource.Status.ERROR
    source.save(update_fields=["status", "updated_at"])

    broken_marker = {"reason": reason, "at": dt.datetime.now(tz=dt.UTC).isoformat(), **extra}
    cdc_schemas = list(
        ExternalDataSchema.objects.filter(
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        ).exclude(deleted=True)
    )
    # The sweeper re-marks an unrepaired source on every sweep while the condition persists.
    # Report once: only schemas newly entering this broken state produce failure-digest
    # evidence, otherwise an ongoing condition would re-email the team daily and pile a
    # synthetic FAILED run per sweep onto the Syncs tab.
    newly_broken = [
        schema
        for schema in cdc_schemas
        if ((schema.sync_type_config or {}).get("cdc_broken") or {}).get("reason") != reason
    ]
    for schema in cdc_schemas:
        # Locked merge so a concurrent API PATCH of sync_type_config can't clobber the marker.
        update_sync_type_config_keys(
            schema.id,
            source.team_id,
            updates={"cdc_broken": broken_marker},
            extra_model_fields={
                "status": ExternalDataSchema.Status.FAILED,
                "latest_error": message,
            },
        )

    if pause:
        _pause_schedule(source, log)

    # Breakage often originates outside a run (the lag sweeper), so no FAILED job row exists.
    # The failure digest email needs one: its schema query requires a failed job newer than the
    # last notification, and the daily catch-up selects teams by recent failed jobs.
    if newly_broken:
        if create_visibility_jobs:
            _create_failure_visibility_jobs(source, newly_broken, message, log)
        _schedule_failure_digest(source, log)

    _notify(source, message, log)
    _capture(source, reason, paused=pause, log=log)

    log.warning("cdc_marked_broken", schemas=len(cdc_schemas), newly_broken=len(newly_broken), paused=pause)


def _create_failure_visibility_jobs(
    source: ExternalDataSource,
    cdc_schemas: list[ExternalDataSchema],
    message: str,
    log: typing.Any,
) -> None:
    now = dt.datetime.now(tz=dt.UTC)
    for schema in cdc_schemas:
        try:
            ExternalDataJob.objects.create(
                team_id=source.team_id,
                pipeline_id=source.id,
                schema=schema,
                status=ExternalDataJob.Status.FAILED,
                rows_synced=0,
                latest_error=message,
                pipeline_version=ExternalDataJob.PipelineVersion.V3,
                finished_at=now,
                schema_snapshot=_build_schema_snapshot(schema),
            )
        except Exception:
            log.warning("cdc_broken_visibility_job_failed", schema_id=str(schema.id), exc_info=True)


def _schedule_failure_digest(source: ExternalDataSource, log: typing.Any) -> None:
    try:
        # Deferred: the tasks module pulls Celery wiring onto the import path.
        from products.data_warehouse.backend.facade.tasks import schedule_external_data_failure_digest

        schedule_external_data_failure_digest(source.team_id, trigger="cdc")
    except Exception:
        # Best-effort: the daily catch-up still delivers via the visibility job rows.
        log.warning("cdc_broken_digest_schedule_failed", exc_info=True)


def _pause_schedule(source: ExternalDataSource, log: typing.Any) -> None:
    try:
        # Deferred: data_load.service participates in the CDC schedule<->workflow import cycle.
        from products.data_warehouse.backend.facade.api import pause_cdc_extraction_schedule

        pause_cdc_extraction_schedule(str(source.id))
    except Exception:
        # Best-effort: a failed pause must not block persisting the broken state.
        log.warning("cdc_broken_pause_schedule_failed", exc_info=True)


def _notify(source: ExternalDataSource, message: str, log: typing.Any) -> None:
    try:
        from products.notifications.backend.facade.api import (
            NotificationData,
            NotificationType,
            Priority,
            TargetType,
            create_notification,
        )

        create_notification(
            NotificationData(
                team_id=source.team_id,
                notification_type=NotificationType.PIPELINE_FAILURE,
                priority=Priority.NORMAL,
                title="Change data capture needs attention",
                body=message,
                target_type=TargetType.TEAM,
                target_id=str(source.team_id),
            )
        )
    except Exception:
        log.warning("cdc_broken_notification_failed", exc_info=True)


def _capture(source: ExternalDataSource, reason: str, *, paused: bool, log: typing.Any) -> None:
    try:
        posthoganalytics.capture(
            distinct_id=get_machine_id(),
            event="cdc marked broken",
            properties={
                "team_id": source.team_id,
                "source_id": str(source.id),
                "reason": reason,
                "paused": paused,
            },
        )
    except Exception:
        log.warning("cdc_broken_capture_failed", exc_info=True)
