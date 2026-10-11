"""One-way copy of logs alert configurations into the skeleton shared tables.

The control plane stays with the logs product: this reads, never writes back. Each check reads the
logs alert's current settings, so an edit counts without a rerun. A change of check interval, and
turning an alert back on, still need one.

`legacy_configuration_id` carries the row each copy came from, so a second run updates
rather than duplicates, and a later comparison can line the two stacks up per alert.
"""

import structlog

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import disable_configurations, upsert_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.logs.backend.alert_source_cycle import platform_upsert_of
from products.logs.backend.models import LogsAlertConfiguration

logger = structlog.get_logger(__name__)


@frozen
class BackfillCounts:
    created: int
    updated: int
    skipped: int
    failed: int


def _is_team_sampled(team_id: int, sample_percent: int) -> bool:
    """Whether a team falls inside a sample.

    Logs samples teams, not alerts, because one query checks a whole cohort of a team's alerts.
    A sample of alerts spread across every team costs nearly as many queries as copying them all.
    Decided by the team id, so a rerun picks the same teams and widening the sample only adds teams.
    """
    return team_id % 100 < sample_percent


def backfill_platform_alert_configurations(*, team_id: int | None = None, sample_percent: int = 100) -> BackfillCounts:
    """Copies every logs alert configuration, or one team's, or a sample of teams'.

    Every copy adds ClickHouse load beside production's, so a rollout copies a sample first and
    widens it while the parallel run's query load stays inside its budget.
    """
    if not 1 <= sample_percent <= 100:
        raise ValueError("sample_percent must be between 1 and 100")
    source = LogsAlertConfiguration.objects.all()
    if team_id is not None:
        source = source.filter(team_id=team_id)

    created = 0
    updated = 0
    skipped = 0
    failed = 0
    for configuration in source.iterator():
        if not _is_team_sampled(configuration.team_id, sample_percent):
            skipped += 1
            continue
        # One alert the copy rejects must not stop the rest.
        try:
            was_created = upsert_configuration(platform_upsert_of(configuration))
        except Exception:
            logger.exception(
                "platform_alert_backfill.failed", alert_id=str(configuration.id), team_id=configuration.team_id
            )
            failed += 1
            continue
        if was_created:
            created += 1
        else:
            updated += 1

    logger.info(
        "platform_alert_backfill.complete",
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
        team_id=team_id,
    )
    return BackfillCounts(created=created, updated=updated, skipped=skipped, failed=failed)


def disable_platform_alert_configurations(*, team_id: int | None = None) -> int:
    """Stops the parallel run for every logs copy, or one team's. Returns how many it stopped.

    The copies stay, with their state and history. Running the backfill again turns them back on.
    """
    disabled = disable_configurations(SourceKind.LOGS, team_id=team_id)
    logger.info("platform_alert_backfill.disabled", disabled=disabled, team_id=team_id)
    return disabled
