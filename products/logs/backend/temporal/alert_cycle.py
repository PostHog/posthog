"""Read-only logs evaluation cycle for the shared alerts platform.

Exercises the orchestration to evaluation to delivery path with a real source, without
changing any alert. The production logs fleet evaluates these same alerts every minute on
its own queue, so this cycle must not write: no state transition, no `next_check_at`
advance, no notification. `alert_state_machine.apply_outcome` is therefore never called
here, and delivery stops at a recorded preview.

The configuration read stands in for a shared alert configuration that the alerts platform
does not own yet. Until that model exists, the cycle reads `LogsAlertConfiguration` directly.
"""

import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.dataclasses import frozen
    from posthog.sync import database_sync_to_async_pool

    from products.alerts.backend.facade.contracts import (
        AlertDeliveryPreview,
        SourceCycleInputs,
        SourceCycleResult,
        SourceKind,
    )

WORKFLOW_NAME = "logs-alert-source-cycle"


@frozen
class LogsCycleEvaluation:
    previews: list[AlertDeliveryPreview]
    alerts_evaluated: int


_NOTIFICATION_EVENT_KINDS = {"fire": "firing", "resolve": "resolved", "error": "errored", "broken": "broken"}

_COHORT_VALUES = (
    "id",
    "team_id",
    "name",
    "window_minutes",
    "evaluation_periods",
    "datapoints_to_alarm",
    "check_interval_minutes",
    "cooldown_minutes",
    "threshold_count",
    "threshold_operator",
    "filters",
    "next_check_at",
    "state",
    "snooze_until",
    "last_notified_at",
    "consecutive_failures",
)


def _evaluate_due_logs_alerts_sync() -> LogsCycleEvaluation:
    # Django models and the query layer are imported here rather than at module level.
    # The workflow class below forces this module to evaluate inside Temporal's sandbox,
    # which a Django model import trips.
    from products.alerts.backend.facade.destinations import list_active_alert_destinations
    from products.logs.backend.alert_check_query import (
        BatchedAlertCheckQuery,
        fetch_live_logs_checkpoint,
        is_projection_eligible,
        resolve_alert_date_to,
    )
    from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG
    from products.logs.backend.alert_state_machine import (
        AlertSnapshot,
        AlertState,
        CheckResult,
        NotificationAction,
        evaluate_alert_check,
    )
    from products.logs.backend.alert_utils import due_alerts_q
    from products.logs.backend.models import LogsAlertConfiguration

    # Reused rather than reimplemented: the pad for buckets ClickHouse never emits is
    # what makes a `below` alert on a silent service fire at all.
    from products.logs.backend.temporal.activities import _derive_breaches

    now = dt.datetime.now(dt.UTC)
    rows = list(
        LogsAlertConfiguration.objects.filter(
            due_alerts_q(
                now,
                broken_state=LogsAlertConfiguration.State.BROKEN,
                snoozed_state=LogsAlertConfiguration.State.SNOOZED,
            )
        ).values(*_COHORT_VALUES)
    )
    if not rows:
        return LogsCycleEvaluation(previews=[], alerts_evaluated=0)

    from posthog.models import Team

    teams = {team.id: team for team in Team.objects.filter(id__in={row["team_id"] for row in rows})}

    checkpoints = {team_id: fetch_live_logs_checkpoint(team) for team_id, team in teams.items()}

    cohorts: dict[tuple, list[dict]] = {}
    for row in rows:
        if row["team_id"] not in teams:
            continue
        date_to = resolve_alert_date_to(row["next_check_at"] or now, checkpoints[row["team_id"]])
        key = (
            row["team_id"],
            row["window_minutes"],
            row["evaluation_periods"],
            row["check_interval_minutes"],
            is_projection_eligible(row["filters"]),
            date_to,
        )
        cohorts.setdefault(key, []).append(row)

    previews: list[AlertDeliveryPreview] = []
    for (
        team_id,
        window_minutes,
        evaluation_periods,
        cadence_minutes,
        projection_eligible,
        date_to,
    ), members in cohorts.items():
        alert_ids = [str(row["id"]) for row in members]
        alerts = list(LogsAlertConfiguration.objects.filter(id__in=alert_ids))
        result = BatchedAlertCheckQuery(
            team=teams[team_id],
            alerts=alerts,
            date_from=date_to - dt.timedelta(minutes=window_minutes),
            date_to=date_to,
            projection_eligible=projection_eligible,
        ).execute_rolling_checks(date_to, window_minutes, cadence_minutes, evaluation_periods)

        rows_by_id = {str(row["id"]): row for row in members}
        for alert in alerts:
            row = rows_by_id[str(alert.id)]
            breaches = _derive_breaches(
                result.per_alert.get(str(alert.id), []),
                row["threshold_count"],
                row["threshold_operator"],
                evaluation_periods,
            )
            current_breached, *prior_windows_breached = breaches or [False]
            outcome = evaluate_alert_check(
                AlertSnapshot(
                    state=AlertState(row["state"]),
                    evaluation_periods=evaluation_periods,
                    datapoints_to_alarm=row["datapoints_to_alarm"],
                    cooldown_minutes=row["cooldown_minutes"],
                    last_notified_at=row["last_notified_at"],
                    snooze_until=row["snooze_until"],
                    consecutive_failures=row["consecutive_failures"],
                    recent_events_breached=tuple(prior_windows_breached),
                ),
                CheckResult(result_count=None, threshold_breached=current_breached),
                now,
            )
            if outcome.notification == NotificationAction.NONE:
                continue

            event_kind = _NOTIFICATION_EVENT_KINDS.get(outcome.notification.value)
            spec = EVENT_KIND_CONFIG.get(event_kind) if event_kind else None
            destinations = (
                list_active_alert_destinations(
                    team_id=team_id, alert_id=str(alert.id), allowed_event_ids=[spec.event_id]
                )
                if spec is not None
                else []
            )
            previews.append(
                AlertDeliveryPreview(
                    source_kind=SourceKind.LOGS,
                    alert_id=str(alert.id),
                    alert_name=row["name"],
                    notification=outcome.notification.value,
                    destination_names=tuple(destination.name for destination in destinations),
                    evaluation_key=f"window:{date_to.isoformat()}",
                )
            )

    return LogsCycleEvaluation(previews=previews, alerts_evaluated=len(rows))


@activity.defn
async def evaluate_due_logs_alerts_activity() -> LogsCycleEvaluation:
    return await database_sync_to_async_pool(_evaluate_due_logs_alerts_sync)()


@workflow.defn(name=WORKFLOW_NAME)
class LogsAlertSourceCycleWorkflow(PostHogWorkflow):
    """Evaluates every due logs alert, then starts one delivery preview per notification."""

    inputs_cls = SourceCycleInputs

    @workflow.run
    async def run(self, inputs: SourceCycleInputs) -> SourceCycleResult:
        evaluation = await workflow.execute_activity(
            evaluate_due_logs_alerts_activity,
            start_to_close_timeout=dt.timedelta(minutes=2),
            schedule_to_close_timeout=dt.timedelta(minutes=4),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        for preview in evaluation.previews:
            await workflow.start_child_workflow(
                "alerts-product-deliver-preview",
                preview,
                # The key names the occasion, so a replayed cycle reuses this id.
                id=f"alerts-deliver-preview-{preview.alert_id}-{preview.evaluation_key}",
                task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(minutes=1),
            )

        return SourceCycleResult(
            source_kind=inputs.source_kind,
            alerts_evaluated=evaluation.alerts_evaluated,
            notifications_dispatched=len(evaluation.previews),
        )


SOURCE_CYCLE_WORKFLOWS = [LogsAlertSourceCycleWorkflow]
SOURCE_CYCLE_ACTIVITIES = [evaluate_due_logs_alerts_activity]
