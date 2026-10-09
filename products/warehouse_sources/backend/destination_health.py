"""Whether deliveries to a destination work, and pausing one that keeps failing on its own settings.

A destination with bad settings (wrong password, unknown database, unreachable host) fails every
run that delivers to it. After `DATA_WAREHOUSE_DESTINATION_PAUSE_AFTER_CONFIGURATION_FAILURES`
such failures in a row, PostHog turns off every link to it and tells the project once. The schemas
themselves stay on, so a table that also syncs to the PostHog warehouse or another destination
keeps syncing there.

Every write here is best effort. A health record that cannot be saved must never fail a delivery.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    ExternalDataSchemaDestination,
    ExternalDataSourceDestination,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
)

logger = structlog.get_logger(__name__)

# Shown for a failure that is not a configuration error. The raw error can name hosts or carry
# driver output, so it stays in the logs and the user sees this instead.
TRANSIENT_DELIVERY_ERROR = "PostHog could not deliver data to this destination. The next sync will try again."


def record_delivery_failure(destination: ExternalDataDestination, error: BaseException) -> None:
    """Save the error on the destination, and pause it if its settings failed too many times in a row."""
    try:
        _record_failure(destination, error)
    except Exception as e:
        capture_exception(e)
        logger.warning("destination_health_failure_not_recorded", destination_id=str(destination.id), error=str(e))


def record_delivery_success(destination: ExternalDataDestination) -> None:
    """Mark a failing destination healthy again. A paused one stays paused until a user turns it back on.

    Reads the instance the delivery already loaded, so a destination that is already healthy costs
    no query.
    """
    if (
        destination.status == ExternalDataDestination.Status.HEALTHY
        and not destination.consecutive_configuration_failures
    ):
        return
    try:
        updated = (
            ExternalDataDestination.objects.for_team(destination.team_id, canonical=True)
            .filter(id=destination.id)
            .exclude(status=ExternalDataDestination.Status.PAUSED)
            .update(
                status=ExternalDataDestination.Status.HEALTHY,
                consecutive_configuration_failures=0,
                updated_at=timezone.now(),
            )
        )
        if updated:
            destination.status = ExternalDataDestination.Status.HEALTHY
            destination.consecutive_configuration_failures = 0
    except Exception as e:
        capture_exception(e)
        logger.warning("destination_health_success_not_recorded", destination_id=str(destination.id), error=str(e))


def resume_destination(destination: ExternalDataDestination) -> None:
    """Turn a destination back on after a user edits it or selects it again.

    Turns its links back on only when PostHog paused it. Nothing else turns a link off, so every
    link that is off on a paused destination is one the pause turned off.
    """
    with transaction.atomic():
        locked = (
            ExternalDataDestination.objects.for_team(destination.team_id, canonical=True)
            .select_for_update()
            .filter(id=destination.id, deleted=False)
            .first()
        )
        if locked is None:
            return
        if locked.status == ExternalDataDestination.Status.PAUSED:
            _set_links_enabled(locked, enabled=True)
        locked.status = ExternalDataDestination.Status.HEALTHY
        locked.consecutive_configuration_failures = 0
        locked.save(update_fields=["status", "consecutive_configuration_failures", "updated_at"])

    destination.status = locked.status
    destination.consecutive_configuration_failures = 0


def _record_failure(destination: ExternalDataDestination, error: BaseException) -> None:
    is_configuration_error = isinstance(error, DestinationConfigurationError)
    message = error.detail if isinstance(error, DestinationConfigurationError) else TRANSIENT_DELIVERY_ERROR
    now = timezone.now()
    paused = False

    with transaction.atomic():
        locked = (
            ExternalDataDestination.objects.for_team(destination.team_id, canonical=True)
            .select_for_update()
            .filter(id=destination.id, deleted=False)
            .first()
        )
        if locked is None:
            return

        locked.latest_error = message
        locked.latest_error_at = now
        # A run that started before the pause can still reach a paused destination. Its failure
        # updates the error but must not send a second notification.
        if locked.status != ExternalDataDestination.Status.PAUSED:
            if is_configuration_error:
                locked.consecutive_configuration_failures += 1
            if (
                is_configuration_error
                and locked.consecutive_configuration_failures
                >= settings.DATA_WAREHOUSE_DESTINATION_PAUSE_AFTER_CONFIGURATION_FAILURES
            ):
                _set_links_enabled(locked, enabled=False)
                locked.status = ExternalDataDestination.Status.PAUSED
                paused = True
            else:
                locked.status = ExternalDataDestination.Status.FAILING
        locked.save(
            update_fields=[
                "latest_error",
                "latest_error_at",
                "status",
                "consecutive_configuration_failures",
                "updated_at",
            ]
        )

        if paused:
            from posthog.tasks.email import send_warehouse_destination_paused

            logger.warning(
                "destination_paused_after_configuration_errors",
                destination_id=str(locked.id),
                destination_type=locked.type,
                failures=locked.consecutive_configuration_failures,
            )
            team_id, destination_id, name = locked.team_id, str(locked.id), locked.name
            transaction.on_commit(
                lambda: send_warehouse_destination_paused.delay(team_id, destination_id, name, message, now.isoformat())
            )

    destination.status = locked.status
    destination.latest_error = locked.latest_error
    destination.latest_error_at = locked.latest_error_at
    destination.consecutive_configuration_failures = locked.consecutive_configuration_failures


def _set_links_enabled(destination: ExternalDataDestination, *, enabled: bool) -> None:
    for link_model in (ExternalDataSourceDestination, ExternalDataSchemaDestination):
        link_model.objects.for_team(destination.team_id, canonical=True).filter(
            destination_id=destination.id, enabled=not enabled
        ).update(enabled=enabled, updated_at=timezone.now())
