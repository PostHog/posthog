from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from products.logs.backend.alert_check_query import is_projection_eligible, resolve_alert_date_to
from products.logs.backend.alert_evaluation import LogsAlertEvaluation, evaluate_logs_alert
from products.logs.backend.alert_state_machine import AlertCheckOutcome, evaluate_alert_check
from products.logs.backend.temporal.activities import (
    _AlertCohort,
    _AlertEvaluation,
    _CohortQueryResult,
    _derive_breaches,
    _evaluate_single_alert,
)
from products.logs.backend.temporal.constants import MAX_ALERT_COHORT_SIZE


@frozen
class LogsAlertComparison:
    legacy: _AlertEvaluation
    adapted: LogsAlertEvaluation
    proposed_outcome: AlertCheckOutcome
    now: datetime
    checkpoint: datetime | None
    query_date_from: datetime
    query_date_to: datetime
    counts_match: bool
    evidence_matches: bool
    errors_match: bool
    lifecycle_matches: bool
    notifications_match: bool
    windows_match: bool


def compare_logs_alert_cohort(
    cohort: _AlertCohort,
    query_result: _CohortQueryResult,
    *,
    now: datetime,
    checkpoint: datetime | None,
) -> tuple[LogsAlertComparison, ...]:
    """Compare one captured cohort locally. Never discover, query, dispatch, or save.

    Counts use identical supplied evidence, not two live reads. Legacy reported windows
    retain the production cohort invocation's checkpoint=None so a clamped query window
    remains a visible disagreement. Outcomes precede quiet hours and delivery handling.
    """
    if not 1 <= len(cohort.alerts) <= MAX_ALERT_COHORT_SIZE:
        raise ValueError("Supply one bounded, nonempty cohort")
    if any(alert.get_deferred_fields() for alert in cohort.alerts):
        raise ValueError("Supply fully loaded alert configurations")
    cohort = deepcopy(cohort)
    # Legacy evaluation raises the error, so each alert needs its own exception to keep tracebacks off caller inputs.
    per_alert = {
        alert_id: replace(
            result,
            buckets=list(result.buckets) if result.buckets is not None else None,
            error=copy(result.error),
        )
        for alert_id, result in query_result.per_alert.items()
    }
    alert_ids = {str(alert.id) for alert in cohort.alerts}
    if len(alert_ids) != len(cohort.alerts) or alert_ids != per_alert.keys():
        raise ValueError("Supply exactly one query result per cohort alert")

    comparisons: list[LogsAlertComparison] = []
    for alert in cohort.alerts:
        if (
            alert.team_id != cohort.team_id
            or alert.window_minutes != cohort.window_minutes
            or alert.check_interval_minutes != cohort.check_interval_minutes
            or alert.evaluation_periods != cohort.evaluation_periods
            or is_projection_eligible(alert.filters) != cohort.projection_eligible
            or resolve_alert_date_to(alert.next_check_at if alert.next_check_at is not None else now, checkpoint)
            != cohort.date_to
        ):
            raise ValueError("Configuration and checkpoint must match the captured cohort window and grid")
        supplied = per_alert[str(alert.id)]
        if supplied.buckets is None and supplied.error is None:
            raise ValueError("Missing query evidence must not trigger a live query")
        expected_starts = {
            cohort.date_to - timedelta(minutes=alert.window_minutes + i * alert.check_interval_minutes)
            for i in range(alert.evaluation_periods)
        }
        if supplied.error is None and any(b.timestamp not in expected_starts for b in supplied.buckets or []):
            raise ValueError("Bucket timestamps must match the captured rolling windows")
        adapted = evaluate_logs_alert(
            alert,
            buckets=supplied.buckets,
            error=supplied.error,
            query_duration_ms=supplied.query_duration_ms,
        )
        legacy = _evaluate_single_alert(alert, now, prefetched=supplied, record_diagnostics=False)
        outcome = evaluate_alert_check(
            alert.to_snapshot(recent_events_breached=adapted.breaches[1:]), adapted.check, now
        )
        legacy_breaches = (
            _derive_breaches(
                supplied.buckets or [], alert.threshold_count, alert.threshold_operator, alert.evaluation_periods
            )
            if supplied.error is None
            else ()
        )
        comparisons.append(
            LogsAlertComparison(
                legacy=legacy,
                adapted=adapted,
                proposed_outcome=outcome,
                now=now,
                checkpoint=checkpoint,
                query_date_from=cohort.date_from,
                query_date_to=cohort.date_to,
                counts_match=legacy.check_result.result_count
                == (adapted.bucket_results[0].value if adapted.bucket_results else None),
                evidence_matches=legacy_breaches == adapted.breaches,
                errors_match=(legacy.check_result.error_message, legacy.check_result.is_transient_error)
                == (adapted.check.error_message, adapted.check.is_transient_error),
                lifecycle_matches=(
                    legacy.outcome.new_state,
                    legacy.outcome.consecutive_failures,
                    legacy.outcome.disable,
                )
                == (outcome.new_state, outcome.consecutive_failures, outcome.disable),
                notifications_match=(legacy.outcome.notification, legacy.outcome.update_last_notified_at)
                == (outcome.notification, outcome.update_last_notified_at),
                windows_match=legacy.date_from == cohort.date_from and legacy.date_to == cohort.date_to,
            )
        )
    return tuple(comparisons)
