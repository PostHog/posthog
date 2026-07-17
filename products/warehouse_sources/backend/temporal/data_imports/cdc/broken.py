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

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)


def mark_cdc_broken(
    source: ExternalDataSource,
    reason: str,
    message: str,
    *,
    pause: bool = True,
    **extra: typing.Any,
) -> None:
    """Move a CDC source into the broken state.

    ``reason`` is a stable machine code (e.g. ``"auto_dropped_critical_lag"``); ``message`` is the
    friendly, credential-safe copy shown to the user. ``pause`` controls whether the extraction
    schedule is paused — left on for PostHog-managed breakage (the slot is gone, retrying is futile)
    and turned off for self-managed critical lag, whose customer-owned slot may still recover.
    ``extra`` keys (e.g. ``lag_mb``) are merged into the persisted ``cdc_broken`` marker.
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

    _notify(source, message, log)
    _capture(source, reason, paused=pause, log=log)

    log.warning("cdc_marked_broken", schemas=len(cdc_schemas), paused=pause)


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
