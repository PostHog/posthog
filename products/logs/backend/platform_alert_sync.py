"""Keeps the platform copy of a logs alert in step with the logs alert it came from.

Only a configuration the backfill already copied is touched, so a team reaches the platform
through a backfill and never through an edit. Wired in `LogsConfig.ready()`.
"""

import os
from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import structlog

from posthog.exceptions_capture import capture_exception

from products.alerts.backend.facade.platform_alerts import delete_configuration_copied_from, sync_existing_configuration
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import platform_upsert_for

logger = structlog.get_logger(__name__)

# Turns the sync off without a deploy. The platform copies then go stale until it is back on
# and the backfill runs again.
SYNC_ENABLED = os.environ.get("LOGS_ALERTING_PLATFORM_SYNC_ENABLED", "true").lower() == "true"

# The fields a person edits. The logs evaluator saves only runtime fields on every check, and a
# save that touches none of these must not cost the platform a write.
_CONFIGURATION_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "enabled",
        "filters",
        "threshold_count",
        "threshold_operator",
        "window_minutes",
        "check_interval_minutes",
        "evaluation_periods",
        "datapoints_to_alarm",
        "cooldown_minutes",
        "schedule_restriction",
        "snooze_until",
    }
)


@receiver(post_save, sender=LogsAlertConfiguration)
def sync_platform_copy_on_save(
    sender: type[LogsAlertConfiguration],
    instance: LogsAlertConfiguration,
    created: bool,
    raw: bool = False,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    if raw or created or not SYNC_ENABLED:
        return
    if update_fields is not None and not (update_fields & _CONFIGURATION_FIELDS):
        return
    # A failed copy is logged, never raised: the platform is a canary and must not block a logs
    # alert edit. The savepoint keeps a failure from breaking the caller's transaction.
    try:
        with transaction.atomic():
            sync_existing_configuration(platform_upsert_for(instance))
    except Exception as error:
        logger.exception("platform_alert_sync.save_failed", legacy_configuration_id=str(instance.id))
        capture_exception(error)


@receiver(post_delete, sender=LogsAlertConfiguration)
def delete_platform_copy(
    sender: type[LogsAlertConfiguration],
    instance: LogsAlertConfiguration,
    **kwargs: Any,
) -> None:
    if not SYNC_ENABLED:
        return
    try:
        with transaction.atomic():
            delete_configuration_copied_from(instance.team_id, instance.id)
    except Exception as error:
        logger.exception("platform_alert_sync.delete_failed", legacy_configuration_id=str(instance.id))
        capture_exception(error)
