"""Read-only evaluation of due logs alerts for the shared alerts platform.

The production logs fleet evaluates these same alerts every minute on its own queue, so
this path must not write. It calls no `apply_outcome`, advances no `next_check_at`, writes
no `LogsAlertEvent` and produces no Kafka message. A write here would notify a person twice
for one breach.

Grouping, query execution and the lifecycle decision all reuse the production helpers, so a
preview says what production would have sent. The configuration read stands in for a shared
alert configuration that the alerts platform does not own yet.
"""

from datetime import UTC, datetime, timedelta
from itertools import batched

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
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG
from products.logs.backend.alert_state_machine import CheckResult, NotificationAction, evaluate_alert_check
from products.logs.backend.alert_utils import due_alerts_q
from products.logs.backend.models import LogsAlertConfiguration

# Private to the production activity. Reimplementing either would let this cycle drift
# from what production evaluates. Promoting them to a shared home is the deeper fix.
from products.logs.backend.temporal.activities import _derive_breaches, _detect_broken_filter_config
from products.logs.backend.temporal.constants import MAX_ALERT_COHORT_SIZE

logger = structlog.get_logger(__name__)

# A fleet-wide burst would otherwise return one activity payload over Temporal's ~2 MiB
# limit, which fails the whole cycle rather than truncating it.
MAX_PREVIEWS_PER_CYCLE = 500

_NOTIFICATION_EVENT_KINDS = {
    NotificationAction.FIRE: "firing",
    NotificationAction.RESOLVE: "resolved",
    NotificationAction.ERROR: "errored",
    NotificationAction.BROKEN: "broken",
}


def _cohort_key(row: dict, checkpoint: datetime | None, now: datetime) -> tuple:
    return (
        row["team_id"],
        row["window_minutes"],
        row["evaluation_periods"],
        row["check_interval_minutes"],
        is_projection_eligible(row["filters"]),
        resolve_alert_date_to(row["next_check_at"] or now, checkpoint),
    )


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
        evaluation_key=f"window:{window_end.isoformat()}",
    )


def evaluate_due_logs_alerts() -> tuple[AlertDeliveryPreview, ...]:
    now = datetime.now(UTC)
    rows = list(
        LogsAlertConfiguration.objects.filter(
            due_alerts_q(
                now,
                broken_state=LogsAlertConfiguration.State.BROKEN,
                snoozed_state=LogsAlertConfiguration.State.SNOOZED,
            )
        ).values(
            "id",
            "team_id",
            "window_minutes",
            "evaluation_periods",
            "check_interval_minutes",
            "filters",
            "next_check_at",
        )
    )
    # Production excludes a structurally broken filter before evaluating, so including one
    # here would preview a notification production would never send.
    rows = [row for row in rows if _detect_broken_filter_config(row["filters"]) is None]
    if not rows:
        return ()

    teams = {team.id: team for team in Team.objects.filter(id__in={row["team_id"] for row in rows})}
    rows = [row for row in rows if row["team_id"] in teams]
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

    alerts_by_id = {
        str(alert.id): alert for alert in LogsAlertConfiguration.objects.filter(id__in=[row["id"] for row in rows])
    }

    previews: list[AlertDeliveryPreview] = []
    for key, alert_ids in cohorts.items():
        team_id, window_minutes, evaluation_periods, cadence_minutes, projection_eligible, date_to = key
        lookback = rolling_check_lookback_minutes(window_minutes, cadence_minutes, evaluation_periods)

        # Capped the way the production cohort query requires: one batched query carries one
        # countIf column per alert, so an uncapped cohort is an unbounded query.
        for chunk in batched(alert_ids, MAX_ALERT_COHORT_SIZE, strict=False):
            alerts = [alerts_by_id[alert_id] for alert_id in chunk]
            result = BatchedAlertCheckQuery(
                team=teams[team_id],
                alerts=alerts,
                date_from=date_to - timedelta(minutes=lookback),
                date_to=date_to,
                projection_eligible=projection_eligible,
            ).execute_rolling_checks(date_to, window_minutes, cadence_minutes, evaluation_periods)

            for alert in alerts:
                preview = _preview_for_alert(
                    alert,
                    result.per_alert.get(str(alert.id), []),
                    evaluation_periods=evaluation_periods,
                    window_end=date_to,
                    now=now,
                )
                if preview is not None:
                    previews.append(preview)

    if len(previews) > MAX_PREVIEWS_PER_CYCLE:
        logger.warning(
            "Truncating logs alert previews for the Temporal payload limit",
            produced=len(previews),
            returned=MAX_PREVIEWS_PER_CYCLE,
        )
    return tuple(previews[:MAX_PREVIEWS_PER_CYCLE])
