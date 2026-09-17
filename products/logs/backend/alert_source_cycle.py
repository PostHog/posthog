"""Evaluation of due logs alerts on the shared alerts platform.

Reads a batch of checks from the shared platform and reports what it decided. The logs
product's own tables are never touched: the production logs fleet evaluates the same alerts
against `LogsAlertConfiguration` on its own queue, so the two stacks keep separate state and
neither can notify on the other's behalf. Delivery stops at a recorded preview.

Cohorting, query execution and the lifecycle decision reuse the production helpers, so an
evaluation says what the logs stack would have said given the same configuration.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import batched

import structlog

from posthog.models import Team

from products.alerts.backend.facade.contracts import (
    AlertDeliveryPreview,
    GroupTransition,
    SourceKind,
    WIPAlertCheck,
    WIPAlertOutcome,
)
from products.alerts.backend.facade.destinations import list_active_alert_destinations
from products.alerts.backend.facade.wip_alerts import due_checks, record_outcomes
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

# Private to the production activity. Reimplementing either would let this path drift from
# what the logs stack evaluates. Promoting them to a shared home is the deeper fix.
from products.logs.backend.temporal.activities import _derive_breaches, _detect_broken_filter_config
from products.logs.backend.temporal.constants import MAX_ALERT_COHORT_SIZE

logger = structlog.get_logger(__name__)

# A fleet-wide burst would otherwise return one activity payload over Temporal's ~2 MiB limit,
# which fails the whole batch rather than truncating it.
MAX_PREVIEWS_PER_CYCLE = 500

# Cohorts run one after another in a single activity, so the batch caps how many it evaluates
# to finish inside its start-to-close timeout. An unbounded batch would time out and return
# nothing, which costs every alert in it.
MAX_COHORTS_PER_CYCLE = 60

_NOTIFICATION_EVENT_KINDS: dict[NotificationAction, EventKind] = {
    NotificationAction.FIRE: "firing",
    NotificationAction.RESOLVE: "resolved",
    NotificationAction.ERROR: "errored",
    NotificationAction.BROKEN: "broken",
}


def _cohort_key(check: WIPAlertCheck, checkpoint: datetime | None, now: datetime) -> tuple:
    return (
        check.window_minutes,
        check.evaluation_periods,
        check.check_interval_minutes,
        is_projection_eligible(check.source_config),
        resolve_alert_date_to(check.next_check_at or now, checkpoint),
    )


def _is_in_quiet_hours(check: WIPAlertCheck, team: Team, now: datetime) -> bool:
    """True when the alert's schedule restriction blocks a check at `now`."""
    if not check.schedule_restriction:
        return False
    try:
        return (
            next_allowed_check_at(now, team_timezone=team.timezone, schedule_restriction=check.schedule_restriction)
            > now
        )
    except Exception as error:
        # A restriction we cannot parse must not decide the alert either way, so the check
        # proceeds and the production stack keeps ownership of the broken configuration.
        logger.exception(
            "Unparseable schedule restriction; evaluating anyway", check_id=str(check.id), error=str(error)
        )
        return False


def _snapshot(check: WIPAlertCheck, prior_breached: tuple[bool, ...]) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(check.state),
        evaluation_periods=check.evaluation_periods,
        datapoints_to_alarm=check.datapoints_to_alarm,
        cooldown_minutes=check.cooldown_minutes,
        last_notified_at=check.last_notified_at,
        snooze_until=check.snooze_until,
        consecutive_failures=check.consecutive_failures,
        recent_events_breached=prior_breached,
    )


def _evaluate_one(
    check: WIPAlertCheck, buckets: list[BucketedCount], *, window_end: datetime, now: datetime
) -> tuple[WIPAlertOutcome, AlertDeliveryPreview | None]:
    current_breached, *prior_windows_breached = _derive_breaches(
        buckets, check.threshold_count, check.threshold_operator, check.evaluation_periods
    ) or (False,)

    outcome = evaluate_alert_check(
        _snapshot(check, tuple(prior_windows_breached)),
        CheckResult(result_count=None, threshold_breached=current_breached),
        now,
    )
    recorded = WIPAlertOutcome(
        configuration_id=check.id,
        new_state=outcome.new_state.value,
        notified=outcome.update_last_notified_at,
        consecutive_failures=outcome.consecutive_failures,
    )
    if outcome.notification == NotificationAction.NONE:
        return recorded, None

    spec = EVENT_KIND_CONFIG[_NOTIFICATION_EVENT_KINDS[outcome.notification]]
    destinations = list_active_alert_destinations(
        team_id=check.team_id,
        alert_id=str(check.legacy_configuration_id or check.id),
        allowed_event_ids=[spec.event_id],
    )
    return recorded, AlertDeliveryPreview(
        source=SourceKind.LOGS,
        alert_id=str(check.id),
        alert_name=check.name,
        evaluation_key=f"{check.id}:window:{window_end.isoformat()}",
        destination_names=tuple(destination.name for destination in destinations),
        # One transition with an empty grouping key. Logs does not group yet, and delivery
        # reads a list either way, so fan-out changes this call and nothing downstream.
        transitions=(GroupTransition(grouping_key="", notification=outcome.notification.value),),
    )


def _evaluate_cohort(
    team: Team, checks: Sequence[WIPAlertCheck], key: tuple, *, now: datetime, preview_budget: int
) -> tuple[list[WIPAlertOutcome], list[AlertDeliveryPreview]]:
    window_minutes, evaluation_periods, cadence_minutes, projection_eligible, date_to = key
    lookback = rolling_check_lookback_minutes(window_minutes, cadence_minutes, evaluation_periods)

    try:
        result = BatchedAlertCheckQuery(
            team=team,
            alerts=checks,
            date_from=date_to - timedelta(minutes=lookback),
            date_to=date_to,
            projection_eligible=projection_eligible,
        ).execute_rolling_checks(date_to, window_minutes, cadence_minutes, evaluation_periods)
    except Exception as error:
        # One cohort's query must not end the batch, which is how the production cohort runner
        # contains the same failure.
        logger.exception(
            "Logs alert cohort query failed; skipping the cohort",
            team_id=team.id,
            cohort_size=len(checks),
            error=str(error),
        )
        return [], []

    outcomes: list[WIPAlertOutcome] = []
    previews: list[AlertDeliveryPreview] = []
    for check in checks:
        try:
            outcome, preview = _evaluate_one(
                check, result.per_alert.get(str(check.id), []), window_end=date_to, now=now
            )
        except Exception as error:
            logger.exception("Failed to evaluate a logs alert; skipping it", check_id=str(check.id), error=str(error))
            continue
        outcomes.append(outcome)
        if preview is not None and len(previews) < preview_budget:
            previews.append(preview)
    return outcomes, previews


def evaluate_logs_batch(team_id: int, slot: str, cutoff: datetime) -> tuple[AlertDeliveryPreview, ...]:
    """Evaluates one batch key: a team's alerts due in one minute, against the tick's cutoff.

    The dispatcher passes the key rather than a list of ids, so the set is read here and is the
    fresher one. `cutoff` is the tick occasion, not the clock, so a retried attempt evaluates
    the same alerts against the same windows and derives the same evaluation keys.
    """
    checks = due_checks(team_id, SourceKind.LOGS.value, slot, cutoff)
    # Production excludes a structurally broken filter before evaluating, so including one
    # would record a transition production would never record.
    checks = tuple(c for c in checks if _detect_broken_filter_config(c.source_config) is None)
    if not checks:
        return ()

    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return ()
    checks = tuple(c for c in checks if not _is_in_quiet_hours(c, team, cutoff))
    if not checks:
        return ()

    # One checkpoint for the pass, matching the production discovery activity. A failure falls
    # back to wall-clock rather than ending the batch.
    try:
        checkpoint = fetch_live_logs_checkpoint(team)
    except Exception as error:
        logger.exception("Failed to fetch logs ingestion checkpoint; falling back to wall-clock", error=str(error))
        checkpoint = None

    cohorts: dict[tuple, list[WIPAlertCheck]] = {}
    for check in checks:
        cohorts.setdefault(_cohort_key(check, checkpoint, cutoff), []).append(check)

    if len(cohorts) > MAX_COHORTS_PER_CYCLE:
        logger.warning(
            "Truncating logs alert cohorts to keep the batch inside its activity timeout",
            produced=len(cohorts),
            evaluated=MAX_COHORTS_PER_CYCLE,
        )

    outcomes: list[WIPAlertOutcome] = []
    previews: list[AlertDeliveryPreview] = []
    for key, cohort in list(cohorts.items())[:MAX_COHORTS_PER_CYCLE]:
        # Capped the way the production cohort query requires: one batched query carries one
        # countIf column per alert, so an uncapped cohort is an unbounded query.
        for chunk in batched(cohort, MAX_ALERT_COHORT_SIZE, strict=False):
            chunk_outcomes, chunk_previews = _evaluate_cohort(
                team, list(chunk), key, now=cutoff, preview_budget=MAX_PREVIEWS_PER_CYCLE - len(previews)
            )
            outcomes.extend(chunk_outcomes)
            previews.extend(chunk_previews)

    record_outcomes(team_id, outcomes, cutoff, team_timezone=team.timezone)
    return tuple(previews[:MAX_PREVIEWS_PER_CYCLE])
