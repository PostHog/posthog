"""Evaluation of due logs alerts on the shared alerts platform.

Reads and writes the skeleton shared tables, never the logs product's own. The production
logs fleet evaluates the same alerts on its own queue against `LogsAlertConfiguration`, so
the two stacks keep separate state and neither can notify on the other's behalf. Delivery
still stops at a recorded preview.

Grouping, query execution and the lifecycle decision reuse the production helpers, so an
evaluation says what the logs stack would have said given the same configuration.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from itertools import batched
from typing import Any
from uuid import UUID

from django.db.models import Q

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts.backend.facade.contracts import AlertDeliveryPreview, GroupTransition, SourceKind
from products.alerts.backend.facade.destinations import list_active_alert_destinations
from products.alerts.backend.facade.scheduling import advance_next_check_at
from products.alerts.backend.models import WIPAlert, WIPAlertConfiguration
from products.logs.backend.alert_check_query import (
    BatchedAlertCheckQuery,
    BucketedCount,
    fetch_live_logs_checkpoint,
    is_projection_eligible,
    resolve_alert_date_to,
    rolling_check_lookback_minutes,
)
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG, EventKind
from products.logs.backend.alert_state_machine import (
    AlertSnapshot,
    AlertState,
    CheckResult,
    NotificationAction,
    evaluate_alert_check,
)
from products.logs.backend.alert_utils import next_allowed_check_at

# Private to the production activity. Reimplementing either would let this cycle drift
# from what production evaluates. Promoting them to a shared home is the deeper fix.
from products.logs.backend.temporal.activities import _derive_breaches, _detect_broken_filter_config
from products.logs.backend.temporal.constants import MAX_ALERT_COHORT_SIZE

logger = structlog.get_logger(__name__)

# A fleet-wide burst would otherwise return one activity payload over Temporal's ~2 MiB
# limit, which fails the whole cycle rather than truncating it.
MAX_PREVIEWS_PER_CYCLE = 500

# Cohorts run one after another in a single activity. The cycle caps how many it evaluates
# so that the activity finishes inside its start-to-close timeout. An unbounded cycle would
# instead time out and return nothing, which costs every team its evaluation.
MAX_COHORTS_PER_CYCLE = 60

_NOTIFICATION_EVENT_KINDS: dict[NotificationAction, EventKind] = {
    NotificationAction.FIRE: "firing",
    NotificationAction.RESOLVE: "resolved",
    NotificationAction.ERROR: "errored",
    NotificationAction.BROKEN: "broken",
}


def _cohort_key(row: Mapping[str, Any], checkpoint: datetime | None, now: datetime) -> tuple:
    return (
        row["team_id"],
        row["window_minutes"],
        row["evaluation_periods"],
        row["check_interval_minutes"],
        is_projection_eligible(row["source_config"]),
        resolve_alert_date_to(row["next_check_at"] or now, checkpoint),
    )


def _is_in_quiet_hours(row: Mapping[str, Any], team: Team, now: datetime) -> bool:
    """True when the alert's schedule restriction blocks a check at `now`.

    Production reschedules such an alert past the restriction and evaluates nothing. This
    cycle cannot write, so it drops the row instead. An unreadable restriction blocks the
    alert, which is what production does with one it cannot parse.
    """
    restriction = row["schedule_restriction"]
    if not restriction:
        return False
    try:
        return next_allowed_check_at(now, team_timezone=team.timezone, schedule_restriction=restriction) > now
    except Exception as error:
        logger.exception(
            "Skipping logs alert with invalid quiet-hours configuration",
            alert_id=str(row["id"]),
            team_id=row["team_id"],
            error=str(error),
        )
        return True


@frozen
class _QuerySubject:
    """Satisfies the query layer's `AlertQuerySubject`, so it never sees a configuration model."""

    id: UUID
    team_id: int
    filters: dict[str, Any]


def _snapshot(configuration: WIPAlertConfiguration, alert: WIPAlert, prior_breached: tuple[bool, ...]) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(alert.state),
        evaluation_periods=configuration.evaluation_periods,
        datapoints_to_alarm=configuration.datapoints_to_alarm,
        cooldown_minutes=configuration.cooldown_minutes,
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snooze_until,
        consecutive_failures=configuration.consecutive_failures,
        recent_events_breached=prior_breached,
    )


def _apply_outcome(configuration: WIPAlertConfiguration, alert: WIPAlert, outcome, now: datetime) -> None:
    """Persists the decision to the shared tables. The logs product's own rows are untouched:
    that stack keeps its own state and reaches its own verdict on the same configuration."""
    alert.state = outcome.new_state.value
    if outcome.update_last_notified_at:
        alert.last_notified_at = now
    alert.save(update_fields=["state", "last_notified_at"])

    configuration.consecutive_failures = outcome.consecutive_failures
    configuration.next_check_at = advance_next_check_at(
        configuration.next_check_at, configuration.check_interval_minutes, now
    )
    configuration.save(update_fields=["consecutive_failures", "next_check_at"])


def _evaluate_one(
    configuration: WIPAlertConfiguration,
    alert: WIPAlert,
    buckets: list[BucketedCount],
    *,
    window_end: datetime,
    now: datetime,
) -> AlertDeliveryPreview | None:
    current_breached, *prior_windows_breached = _derive_breaches(
        buckets, configuration.threshold_count, configuration.threshold_operator, configuration.evaluation_periods
    ) or (False,)

    outcome = evaluate_alert_check(
        _snapshot(configuration, alert, tuple(prior_windows_breached)),
        CheckResult(result_count=None, threshold_breached=current_breached),
        now,
    )
    _apply_outcome(configuration, alert, outcome, now)
    if outcome.notification == NotificationAction.NONE:
        return None

    spec = EVENT_KIND_CONFIG[_NOTIFICATION_EVENT_KINDS[outcome.notification]]
    destinations = list_active_alert_destinations(
        team_id=configuration.team_id,
        alert_id=str(configuration.legacy_configuration_id or configuration.id),
        allowed_event_ids=[spec.event_id],
    )
    return AlertDeliveryPreview(
        source=SourceKind.LOGS,
        alert_id=str(configuration.id),
        alert_name=configuration.name,
        evaluation_key=f"{configuration.id}:window:{window_end.isoformat()}",
        destination_names=tuple(destination.name for destination in destinations),
        # One transition with an empty grouping key. Logs does not group yet, and delivery
        # reads a list either way, so fan-out changes this call and nothing downstream.
        transitions=(GroupTransition(grouping_key="", notification=outcome.notification.value),),
    )


def _slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for. One that has never been checked has no due time of
    its own, so it belongs to the tick that found it."""
    return (next_check_at or cutoff).replace(second=0, microsecond=0).isoformat()


def evaluate_logs_batch(team_id: int, slot: str, cutoff: datetime) -> tuple[AlertDeliveryPreview, ...]:
    """Evaluates one batch key: a team's alerts due in one minute, against the tick's cutoff.

    The dispatcher passes the key rather than a list of ids, so the set is read here and is the
    fresher one. `cutoff` is the tick occasion, not the clock, so a retried attempt evaluates the
    same alerts against the same windows and derives the same evaluation keys.

    The due predicate is applied again here. Discovery ran earlier in the tick, so a
    configuration can have been disabled since, and evaluating one that is no longer due
    records a transition nobody asked for.
    """
    rows = list(
        WIPAlertConfiguration.objects.for_team(team_id)
        .filter(enabled=True, source_kind=WIPAlertConfiguration.SourceKind.LOGS)
        .filter(Q(next_check_at__lte=cutoff) | Q(next_check_at__isnull=True))
        # Ordered so the cohort budget and the preview cap keep the same alerts on a
        # retried attempt. Without an ordering Postgres is free to return the rows in a
        # different physical order and the truncation would fall somewhere else.
        .order_by("id")
        .values(
            "id",
            "team_id",
            "window_minutes",
            "evaluation_periods",
            "check_interval_minutes",
            "source_config",
            "next_check_at",
            "schedule_restriction",
        )
    )
    # Production excludes a structurally broken filter before evaluating, so including one
    # here would preview a notification production would never send.
    rows = [row for row in rows if _slot_of(row["next_check_at"], cutoff) == slot]
    rows = [row for row in rows if _detect_broken_filter_config(row["source_config"]) is None]
    if not rows:
        return ()

    teams = {team.id: team for team in Team.objects.filter(id__in={row["team_id"] for row in rows})}
    rows = [row for row in rows if row["team_id"] in teams]
    rows = [row for row in rows if not _is_in_quiet_hours(row, teams[row["team_id"]], cutoff)]
    if not rows:
        return ()

    # One checkpoint for the pass, matching the production discovery activity. A failure
    # falls back to wall-clock rather than ending the cycle.
    try:
        checkpoint = fetch_live_logs_checkpoint(teams[rows[0]["team_id"]])
    except Exception as error:
        logger.exception("Failed to fetch logs ingestion checkpoint; falling back to wall-clock", error=str(error))
        checkpoint = None

    cohorts: dict[tuple, list[str]] = {}
    for row in rows:
        cohorts.setdefault(_cohort_key(row, checkpoint, cutoff), []).append(str(row["id"]))

    if len(cohorts) > MAX_COHORTS_PER_CYCLE:
        logger.warning(
            "Truncating logs alert cohorts to keep the cycle inside its activity timeout",
            produced=len(cohorts),
            evaluated=MAX_COHORTS_PER_CYCLE,
        )

    previews: list[AlertDeliveryPreview] = []
    for key, alert_ids in list(cohorts.items())[:MAX_COHORTS_PER_CYCLE]:
        team_id, window_minutes, evaluation_periods, cadence_minutes, projection_eligible, date_to = key
        lookback = rolling_check_lookback_minutes(window_minutes, cadence_minutes, evaluation_periods)

        # Capped the way the production cohort query requires: one batched query carries one
        # countIf column per alert, so an uncapped cohort is an unbounded query.
        for chunk in batched(alert_ids, MAX_ALERT_COHORT_SIZE, strict=False):
            # Hydrated one chunk at a time. Production splits discovery from evaluation so
            # that it never holds every due alert in the fleet in memory at once.
            configurations_by_id = {
                str(configuration.id): configuration
                for configuration in WIPAlertConfiguration.objects.for_team(team_id).filter(id__in=list(chunk))
            }
            # A configuration deleted since the discovery read is absent from this pass rather
            # than a KeyError that would cost every other team its evaluation.
            configurations = [configurations_by_id[i] for i in chunk if i in configurations_by_id]
            if not configurations:
                continue
            # One runtime row per configuration until a source groups, so the empty key is the
            # whole of its state today and a real key needs no new table.
            alerts_by_configuration = {
                str(alert.configuration_id): alert
                for alert in WIPAlert.objects.for_team(team_id).filter(
                    configuration__in=configurations, grouping_key=""
                )
            }
            for configuration in configurations:
                if str(configuration.id) not in alerts_by_configuration:
                    alerts_by_configuration[str(configuration.id)] = WIPAlert.objects.create(
                        team_id=team_id, configuration=configuration, grouping_key=""
                    )

            try:
                result = BatchedAlertCheckQuery(
                    team=teams[team_id],
                    alerts=[_QuerySubject(id=c.id, team_id=c.team_id, filters=c.source_config) for c in configurations],
                    date_from=date_to - timedelta(minutes=lookback),
                    date_to=date_to,
                    projection_eligible=projection_eligible,
                ).execute_rolling_checks(date_to, window_minutes, cadence_minutes, evaluation_periods)
            except Exception as error:
                # One team's query must not end the pass for every other team, which is how
                # the production cohort runner contains the same failure.
                logger.exception(
                    "Logs alert cohort query failed; skipping the cohort",
                    team_id=team_id,
                    cohort_size=len(configurations),
                    error=str(error),
                )
                continue

            for configuration in configurations:
                try:
                    preview = _evaluate_one(
                        configuration,
                        alerts_by_configuration[str(configuration.id)],
                        result.per_alert.get(str(configuration.id), []),
                        window_end=date_to,
                        now=cutoff,
                    )
                except Exception as error:
                    logger.exception(
                        "Failed to evaluate a logs alert; skipping it",
                        configuration_id=str(configuration.id),
                        team_id=configuration.team_id,
                        error=str(error),
                    )
                    continue
                if preview is not None:
                    previews.append(preview)

    if len(previews) > MAX_PREVIEWS_PER_CYCLE:
        logger.warning(
            "Truncating logs alert previews for the Temporal payload limit",
            produced=len(previews),
            returned=MAX_PREVIEWS_PER_CYCLE,
        )
    return tuple(previews[:MAX_PREVIEWS_PER_CYCLE])
