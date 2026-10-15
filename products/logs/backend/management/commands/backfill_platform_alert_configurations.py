from collections.abc import Collection
from uuid import UUID

from products.alerts_platform.backend.facade.backfill_command import PlatformBackfillCommand
from products.logs.backend.platform_alert_backfill import (
    BackfillCounts,
    backfill_platform_alert_configurations,
    disable_platform_alert_configurations,
)


class Command(PlatformBackfillCommand):
    help = "Copy logs alert configurations into the skeleton shared alert tables."
    source_name = "logs"
    # Logs samples whole teams, because one query checks a cohort of a team's alerts.
    sample_unit = "team"

    def backfill(
        self, *, team_id: int | None, sample_percent: int, alert_ids: Collection[UUID] | None
    ) -> BackfillCounts:
        return backfill_platform_alert_configurations(
            team_id=team_id, sample_percent=sample_percent, alert_ids=alert_ids
        )

    def disable(self, *, team_id: int | None, alert_ids: Collection[UUID] | None) -> int:
        return disable_platform_alert_configurations(team_id=team_id, alert_ids=alert_ids)
