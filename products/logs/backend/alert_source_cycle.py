"""Read-only evaluation of due logs alerts for the shared alerts platform.

The production logs fleet evaluates these same alerts every minute on its own queue, so
this path must not write. It calls no `apply_outcome`, advances no `next_check_at`, writes
no `LogsAlertEvent` and produces no Kafka message. A write here would notify a person twice
for one breach.

Grouping, query execution and the lifecycle decision all reuse the production helpers, so a
preview says what production would have sent. The configuration read stands in for a shared
alert configuration that the alerts platform does not own yet.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from itertools import batched
from typing import Any

import structlog

from posthog.models import Team

from products.alerts.backend.facade.contracts import AlertDeliveryPreview, SourceKind
from products.alerts.backend.facade.destinations import list_active_alert_destinations
from products.logs.backend.alert_check_query import (
    BatchedAlertCheckQuery,
    BucketedCount,
    fetch_live_logs_checkpoint,
    is_projection_eligible,
    resolve_alert_date_to,
    rolling_check_lookback_minutes,
)
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG, EventKind
from products.logs.backend.alert_state_machine import CheckResult, NotificationAction, evaluate_alert_check
from products.logs.backend.alert_utils import due_alerts_q, next_allowed_check_at
from products.logs.backend.models import LogsAlertConfiguration

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
        is_projection_eligible(row["filters"]),
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


def _preview_for_alert(
    alert: LogsAlertConfiguration,
    buckets: list[BucketedCount],
    *,
    evaluation_periods: int,
    window_end: datetime,
    now: datetime,
) -> AlertDeliveryPreview | None:
    current_breached, *prior_windows_breached = _derive_breaches(
        buckets, alert.threshold_count, alert.threshold_operator, evaluation_periods
    ) or (False,)

    outcome = evaluate_alert_check(
        alert.to_snapshot(recent_events_breached=tuple(prior_windows_breached)),
        CheckResult(result_count=None, threshold_breached=current_breached),
        now,
    )
    if outcome.notification == NotificationAction.NONE:
        return None

    spec = EVENT_KIND_CONFIG[_NOTIFICATION_EVENT_KINDS[outcome.notification]]
    destinations = list_active_alert_destinations(
        team_id=alert.team_id, alert_id=str(alert.id), allowed_event_ids=[spec.event_id]
    )
    return AlertDeliveryPreview(
        source_kind=SourceKind.LOGS,
        alert_id=str(alert.id),
        alert_name=alert.name,
        notification=outcome.notification.value,
        destination_names=tuple(destination.name for destination in destinations),
        evaluation_key=f"{alert.id}:window:{window_end.isoformat()}",
    )


def evaluate_due_logs_alerts(now: datetime) -> tuple[AlertDeliveryPreview, ...]:
    """`now` is the tick occasion, not the clock, so a retried attempt evaluates the same
    alerts against the same windows and derives the same evaluation keys."""
    rows = list(
        LogsAlertConfiguration.objects.filter(
            due_alerts_q(
                now,
                broken_state=LogsAlertConfiguration.State.BROKEN,
                snoozed_state=LogsAlertConfiguration.State.SNOOZED,
            )
        )
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
            "filters",
            "next_check_at",
            "schedule_restriction",
        )
    )
    # Production excludes a structurally broken filter before evaluating, so including one
    # here would preview a notification production would never send.
    rows = [row for row in rows if _detect_broken_filter_config(row["filters"]) is None]
    if not rows:
        return ()

    teams = {team.id: team for team in Team.objects.filter(id__in={row["team_id"] for row in rows})}
    rows = [row for row in rows if row["team_id"] in teams]
    rows = [row for row in rows if not _is_in_quiet_hours(row, teams[row["team_id"]], now)]
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
        cohorts.setdefault(_cohort_key(row, checkpoint, now), []).append(str(row["id"]))

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
            alerts_by_id = {str(alert.id): alert for alert in LogsAlertConfiguration.objects.filter(id__in=list(chunk))}
            # An alert deleted since the discovery read is absent from this pass rather than
            # a KeyError that would cost every other team its evaluation.
            alerts = [alerts_by_id[alert_id] for alert_id in chunk if alert_id in alerts_by_id]
            if not alerts:
                continue

            try:
                result = BatchedAlertCheckQuery(
                    team=teams[team_id],
                    alerts=alerts,
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
                    cohort_size=len(alerts),
                    error=str(error),
                )
                continue

            for alert in alerts:
                try:
                    preview = _preview_for_alert(
                        alert,
                        result.per_alert.get(str(alert.id), []),
                        evaluation_periods=evaluation_periods,
                        window_end=date_to,
                        now=now,
                    )
                except Exception as error:
                    logger.exception(
                        "Failed to evaluate a logs alert for preview; skipping the alert",
                        alert_id=str(alert.id),
                        team_id=alert.team_id,
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
