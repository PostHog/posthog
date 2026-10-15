"""One-way copy of logs alert configurations into the skeleton shared tables.

The control plane stays with the logs product: this reads, never writes back, and nothing
keeps the copy in sync afterwards. Run it again to pick up changes.

`legacy_configuration_id` carries the row each copy came from, so a second run updates
rather than duplicates, and a later comparison can line the two stacks up per alert.
"""

from typing import Final

import structlog

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import upsert_configuration
from products.alerts_platform.backend.facade.contracts import SOURCE_CONDITION_KEY, PlatformAlertUpsert, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.logs.backend.alert_source_cycle import LogsAlertCondition
from products.logs.backend.models import LogsAlertConfiguration

logger = structlog.get_logger(__name__)


@frozen
class BackfillCounts:
    created: int
    updated: int


def platform_upsert_of(alert: LogsAlertConfiguration) -> PlatformAlertUpsert:
    """The platform copy of a logs alert, which the backfill writes and every check reads again."""
    return PlatformAlertUpsert(
        legacy_configuration_id=alert.id,
        team_id=alert.team_id,
        name=alert.name,
        enabled=alert.enabled,
        source_kind=SourceKind.LOGS,
        source_config={
            **alert.filters,
            SOURCE_CONDITION_KEY: LogsAlertCondition(
                threshold_count=alert.threshold_count,
                threshold_operator=alert.threshold_operator,
                window_minutes=alert.window_minutes,
            ).as_source_config(),
        },
        check_interval_minutes=alert.check_interval_minutes,
        evaluation_periods=alert.evaluation_periods,
        datapoints_to_alarm=alert.datapoints_to_alarm,
        cooldown_minutes=alert.cooldown_minutes,
        schedule_restriction=alert.schedule_restriction,
        next_check_at=alert.next_check_at,
        snooze_until=alert.snooze_until,
    )


# A muted logs alert is a state of its own. On the platform a mute only silences notifications,
# so the copy keeps checking with the snooze carried on `snooze_until`. Firing states have no entry,
# because a firing alert stays with logs until it resolves.
PLATFORM_HANDOVER_STATE: Final[dict[str, PlatformAlertState]] = {
    LogsAlertConfiguration.State.NOT_FIRING: PlatformAlertState.NOT_FIRING,
    LogsAlertConfiguration.State.SNOOZED: PlatformAlertState.NOT_FIRING,
    LogsAlertConfiguration.State.ERRORED: PlatformAlertState.ERRORED,
    LogsAlertConfiguration.State.BROKEN: PlatformAlertState.BROKEN,
}


def backfill_platform_alert_configurations(*, team_id: int | None = None) -> BackfillCounts:
    """Copies every logs alert configuration, or one team's."""
    source = LogsAlertConfiguration.objects.all()
    if team_id is not None:
        source = source.filter(team_id=team_id)

    created = 0
    updated = 0
    for configuration in source.iterator():
        was_created = upsert_configuration(platform_upsert_of(configuration))
        if was_created:
            created += 1
        else:
            updated += 1

    logger.info("platform_alert_backfill.complete", created=created, updated=updated, team_id=team_id)
    return BackfillCounts(created=created, updated=updated)
