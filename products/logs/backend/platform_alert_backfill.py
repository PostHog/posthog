"""One-way copy of logs alert configurations into the skeleton shared tables.

The control plane stays with the logs product: this reads, never writes back, and nothing
keeps the copy in sync afterwards. Run it again to pick up changes.

`legacy_configuration_id` carries the row each copy came from, so a second run updates
rather than duplicates, and a later comparison can line the two stacks up per alert.
"""

import structlog

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import PlatformAlertUpsert, SourceKind
from products.alerts.backend.facade.platform_alerts import upsert_configuration
from products.logs.backend.models import LogsAlertConfiguration

logger = structlog.get_logger(__name__)


@frozen
class BackfillCounts:
    created: int
    updated: int


def backfill_platform_alert_configurations(*, team_id: int | None = None) -> BackfillCounts:
    """Copies every logs alert configuration, or one team's."""
    source = LogsAlertConfiguration.objects.all()
    if team_id is not None:
        source = source.filter(team_id=team_id)

    created = 0
    updated = 0
    for configuration in source.iterator():
        was_created = upsert_configuration(
            PlatformAlertUpsert(
                legacy_configuration_id=configuration.id,
                team_id=configuration.team_id,
                name=configuration.name,
                enabled=configuration.enabled,
                source_kind=SourceKind.LOGS,
                source_config=configuration.filters,
                threshold_count=configuration.threshold_count,
                threshold_operator=configuration.threshold_operator,
                window_minutes=configuration.window_minutes,
                check_interval_minutes=configuration.check_interval_minutes,
                evaluation_periods=configuration.evaluation_periods,
                datapoints_to_alarm=configuration.datapoints_to_alarm,
                cooldown_minutes=configuration.cooldown_minutes,
                schedule_restriction=configuration.schedule_restriction,
                next_check_at=configuration.next_check_at,
                snooze_until=configuration.snooze_until,
            )
        )
        if was_created:
            created += 1
        else:
            updated += 1

    logger.info("platform_alert_backfill.complete", created=created, updated=updated, team_id=team_id)
    return BackfillCounts(created=created, updated=updated)
