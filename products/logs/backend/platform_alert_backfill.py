"""One-way copy of logs alert configurations into the skeleton shared tables.

The control plane stays with the logs product: this reads, never writes back. Each check reads the
logs alert's current settings, so an edit counts without a rerun. A check can only see a copy that
is enabled, so the logs API copies an alert created or turned back on in a team that already runs
logs on the platform.

`legacy_configuration_id` carries the row each copy came from, so a second run updates
rather than duplicates, and a later comparison can line the two stacks up per alert.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Final
from uuid import UUID

import structlog

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import disable_configurations, upsert_configuration, upsert_if_running
from products.alerts_platform.backend.facade.contracts import PlatformAlertUpsert, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.logs.backend.alert_state_machine import AlertState
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_source_config import logs_source_config

logger = structlog.get_logger(__name__)


@frozen
class BackfillCounts:
    created: int
    updated: int
    skipped: int
    failed: int


# The settings a logs alert shares with its platform copy. The schedule stays the platform's own once
# the copy exists, and `enabled` follows its own rules on each side.
SETTINGS_FIELDS: Final = (
    "name",
    "source_config",
    "evaluation_periods",
    "datapoints_to_alarm",
    "cooldown_minutes",
    "schedule_restriction",
)
# The logs alert's columns that make up `source_config["condition"]` on the copy.
CONDITION_FIELDS: Final = ("threshold_count", "threshold_operator", "window_minutes")


def platform_upsert_of(alert: LogsAlertConfiguration) -> PlatformAlertUpsert:
    """The platform copy of a logs alert, which the backfill writes and every check reads again.

    The bound is not validated here, so a bound the query cannot read reaches triage and marks the
    alert BROKEN.
    """
    return PlatformAlertUpsert(
        legacy_configuration_id=alert.id,
        team_id=alert.team_id,
        name=alert.name,
        enabled=alert.enabled,
        source_kind=SourceKind.LOGS,
        source_config=logs_source_config(alert.filters, {field: getattr(alert, field) for field in CONDITION_FIELDS}),
        check_interval_minutes=alert.check_interval_minutes,
        evaluation_periods=alert.evaluation_periods,
        datapoints_to_alarm=alert.datapoints_to_alarm,
        cooldown_minutes=alert.cooldown_minutes,
        schedule_restriction=alert.schedule_restriction,
        next_check_at=alert.next_check_at,
        snooze_until=alert.snooze_until,
    )


# A muted logs alert is a state of its own. On the platform a mute only silences notifications,
# so the copy keeps checking with the snooze carried on `snooze_until`. A pending resolve is still
# firing, because its incident stays open until the resolve completes.
PLATFORM_HANDOVER_STATE: Final[dict[str, PlatformAlertState]] = {
    LogsAlertConfiguration.State.NOT_FIRING: PlatformAlertState.NOT_FIRING,
    LogsAlertConfiguration.State.FIRING: PlatformAlertState.FIRING,
    LogsAlertConfiguration.State.PENDING_RESOLVE: PlatformAlertState.FIRING,
    LogsAlertConfiguration.State.SNOOZED: PlatformAlertState.NOT_FIRING,
    LogsAlertConfiguration.State.ERRORED: PlatformAlertState.ERRORED,
    LogsAlertConfiguration.State.BROKEN: PlatformAlertState.BROKEN,
}


def logs_state_of_platform(
    platform_state: PlatformAlertState, *, logs_state: str, snooze_until: datetime | None, at: datetime
) -> AlertState:
    """The logs state for a platform state, the inverse of `PLATFORM_HANDOVER_STATE`.

    A handback and the API's read of an alert the platform owns both use it. Only the read can
    see a firing, because the platform keeps a firing alert until it resolves.

    The platform keeps a mute on `snooze_until` rather than as a state, and the logs API kept
    writing snoozes to the logs row, so an active one stays the logs state.
    """
    if logs_state == LogsAlertConfiguration.State.SNOOZED and snooze_until is not None and snooze_until > at:
        return AlertState.SNOOZED
    return _LOGS_STATE_OF_PLATFORM[platform_state]


_LOGS_STATE_OF_PLATFORM: Final[dict[PlatformAlertState, AlertState]] = {
    PlatformAlertState.NOT_FIRING: AlertState.NOT_FIRING,
    PlatformAlertState.FIRING: AlertState.FIRING,
    PlatformAlertState.SNOOZED: AlertState.NOT_FIRING,
    PlatformAlertState.ERRORED: AlertState.ERRORED,
    PlatformAlertState.BROKEN: AlertState.BROKEN,
}


def _is_team_sampled(team_id: int, sample_percent: int) -> bool:
    """Whether a team falls inside a sample.

    Logs samples teams, not alerts, because one query checks a whole cohort of a team's alerts.
    A sample of alerts spread across every team costs nearly as many queries as copying them all.
    Decided by the team id, so a rerun picks the same teams and widening the sample only adds teams.
    """
    return team_id % 100 < sample_percent


def backfill_platform_alert_configurations(
    *, team_id: int | None = None, sample_percent: int = 100, alert_ids: Collection[UUID] | None = None
) -> BackfillCounts:
    """Copies every logs alert configuration, or one team's, or a sample of teams', or named alerts.

    Every copy adds ClickHouse load beside production's, so a rollout copies a sample first and
    widens it while the parallel run's query load stays inside its budget. Named alerts let a
    rollout copy the ones a comparison still lacks evidence for.
    """
    if not 1 <= sample_percent <= 100:
        raise ValueError("sample_percent must be between 1 and 100")
    # The platform owns these, and every edit writes both rows already.
    source = LogsAlertConfiguration.objects.exclude(owner=PlatformAlertOwner.PLATFORM)
    if team_id is not None:
        source = source.filter(team_id=team_id)
    if alert_ids is not None:
        source = source.filter(id__in=alert_ids)

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


def disable_platform_alert_configurations(
    *, team_id: int | None = None, alert_ids: Collection[UUID] | None = None
) -> int:
    """Stops the parallel run for every logs copy, or one team's, or named alerts'. Returns how many it stopped.

    The copies stay, with their state and history. Running the backfill again turns them back on.
    """
    disabled = disable_configurations(SourceKind.LOGS, team_id=team_id, legacy_configuration_ids=alert_ids)
    logger.info("platform_alert_backfill.disabled", disabled=disabled, team_id=team_id)
    return disabled


def follow_logs_alert(alert: LogsAlertConfiguration) -> None:
    """Copies a logs alert that was just created or turned back on, if its team runs logs on the platform.

    Checks only read enabled copies, so no check would ever see this alert otherwise, and it would
    stay off the platform until the next backfill.
    """
    upsert_if_running(platform_upsert_of(alert), revive=True)
