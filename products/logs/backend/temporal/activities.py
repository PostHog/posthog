"""Temporal activities for logs alerting."""

import time
import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q
from django.db.utils import IntegrityError

import structlog
import temporalio.activity

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.logs.backend.alert_check_query import (
    AlertCheckQuery,
    BatchedAlertCheckQuery,
    BatchedBucketedResult,
    BucketedCount,
    fetch_live_logs_checkpoint,
    is_projection_eligible,
    resolve_alert_date_to,
)
from products.logs.backend.alert_error_classifier import (
    AlertErrorCode,
    classify as classify_alert_error,
)
from products.logs.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertState,
    CheckResult,
    NotificationAction,
    apply_outcome,
    evaluate_alert_check,
)
from products.logs.backend.alert_utils import advance_next_check_at
from products.logs.backend.logs_url_params import build_logs_url_params
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.temporal.constants import MAX_CONCURRENT_ALERT_EVALS
from products.logs.backend.temporal.metrics import (
    increment_check_errors,
    increment_checkpoint_unavailable,
    increment_checks_total,
    increment_cohort_query_fallback,
    increment_cohort_save_fallback,
    increment_notification_failures,
    increment_state_transition,
    record_alerts_active,
    record_check_duration,
    record_checkpoint_lag,
    record_clickhouse_duration,
    record_cohort_event_insert_duration,
    record_cohort_save_duration,
    record_cohort_size,
    record_cohort_update_duration,
    record_pending_alerts,
    record_scheduler_lag,
    record_semaphore_wait,
)

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)


def _safe_record(label: str, fn, *args, **kwargs) -> None:
    """Best-effort metric recording — failures must never break alerting."""
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("Failed to record %s", label)


def _derive_breaches(
    buckets: list[BucketedCount],
    threshold_count: int,
    threshold_operator: str,
    evaluation_periods: int,
) -> tuple[bool, ...]:
    """Map ASC-ordered bucketed CH counts to a newest-first breach tuple of length M.

    CH's `GROUP BY` only emits buckets that have data. The state machine needs M
    data points regardless of how sparse the underlying log volume is — so we
    pad the result to `evaluation_periods` with the implicit count=0 outcome:
    `False` for `above` (0 < threshold), `True` for `below` (0 < threshold given
    the model's min_value=1 validator).

    Without this pad, a `below` alert on a truly silent service would never
    fire — CH returns no buckets, the breach tuple is empty, and the N-of-M
    evaluator never sees the implicit "count is below threshold" signal.
    """
    if threshold_operator == "above":
        actual = tuple(b.count > threshold_count for b in reversed(buckets))
        missing_breach = False
    else:
        actual = tuple(b.count < threshold_count for b in reversed(buckets))
        missing_breach = True
    pad = (missing_breach,) * max(0, evaluation_periods - len(actual))
    return actual + pad


@dataclasses.dataclass(frozen=True)
class CheckAlertsInput:
    pass


@dataclasses.dataclass(frozen=True)
class _AlertCohort:
    """Group of alerts that share team + bucket grid and can be batched into one CH query.

    Cohort key (implicit, derived in `_build_cohorts`):
    `(team_id, window_minutes, evaluation_periods, projection_eligible, date_to)`.

    All five must match for two alerts to share a query. `date_to` matters because
    checkpoint clamping can pull alerts with different `next_check_at` values onto
    the same window, and we want them to share the scan when that happens.
    """

    alerts: tuple[LogsAlertConfiguration, ...]
    date_to: datetime
    projection_eligible: bool

    @property
    def team(self) -> "Team":
        return self.alerts[0].team

    @property
    def team_id(self) -> int:
        return self.alerts[0].team_id

    @property
    def window_minutes(self) -> int:
        return self.alerts[0].window_minutes

    @property
    def evaluation_periods(self) -> int:
        return self.alerts[0].evaluation_periods

    @property
    def date_from(self) -> datetime:
        return self.date_to - timedelta(minutes=self.window_minutes * self.evaluation_periods)


@dataclasses.dataclass(frozen=True)
class _PrefetchedQuery:
    """CH query result for one alert: either `buckets` or `error` is set."""

    buckets: list[BucketedCount] | None = None
    query_duration_ms: int | None = None
    error: Exception | None = None


@dataclasses.dataclass(frozen=True)
class _CohortQueryResult:
    per_alert: dict[str, _PrefetchedQuery]

    def for_alert(self, alert: LogsAlertConfiguration) -> _PrefetchedQuery:
        return self.per_alert.get(str(alert.id), _PrefetchedQuery(buckets=[]))


@dataclasses.dataclass(frozen=True)
class _AlertEvaluation:
    """Phase 1 output: per-alert state-machine result. No Kafka, no PG yet.

    Carries the raw `outcome` (pre-dispatch) — Kafka failure is decided in
    Phase 2 and may roll the state back to `state_before`.
    """

    alert: LogsAlertConfiguration
    outcome: AlertCheckOutcome
    check_result: CheckResult
    date_from: datetime
    date_to: datetime
    state_before: str


@dataclasses.dataclass(frozen=True)
class _DispatchedAlert:
    """Phase 2 output: notification dispatched, ready for the cohort bulk save.

    `notification_failed` is the source of truth for state rollback: if True,
    the state machine's `new_state` is replaced with the alert's existing state
    so the next cycle re-tries the notification.
    """

    evaluation: _AlertEvaluation
    notification_failed: bool

    @property
    def committed_outcome(self) -> AlertCheckOutcome:
        if self.notification_failed:
            return dataclasses.replace(
                self.evaluation.outcome,
                new_state=AlertState(self.evaluation.alert.state),
            )
        return self.evaluation.outcome


@dataclasses.dataclass(frozen=True)
class CheckAlertsOutput:
    alerts_checked: int
    alerts_fired: int
    alerts_resolved: int
    alerts_errored: int


@temporalio.activity.defn
async def check_alerts_activity(input: CheckAlertsInput) -> CheckAlertsOutput:
    """Find all due alerts and evaluate them with bounded concurrency.

    Per-team batching with three phases per cohort:
      1. Batched ClickHouse `countIf` query (one query, N predicate columns).
      2. Per-alert in-memory eval (state machine) + per-alert Kafka dispatch.
      3. Single bulk Postgres save (`bulk_create` events + `bulk_update` configs).

    The semaphore bounds concurrent cohorts. Phase 2's per-alert work runs
    in-memory only — no Postgres connections involved — so its concurrency
    is bounded by Python's GIL plus the Kafka producer's queue, not by the
    DB connection pool.
    """
    now, all_alerts, checkpoint = await database_sync_to_async_pool(_load_alerts_and_checkpoint)()

    cohorts = _build_cohorts(all_alerts, now=now, checkpoint=checkpoint)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ALERT_EVALS)
    # Eval is in-memory + GIL-bound — no parallelism benefit from gather, so
    # we run it as a sync list comprehension. Dispatch is Kafka I/O and gets
    # a thread-pool wrap + gather for actual concurrency.
    dispatch_async = database_sync_to_async_pool(_dispatch_for_alert)
    cohort_query_async = database_sync_to_async_pool(_run_cohort_query)
    save_cohort_async = database_sync_to_async_pool(_save_cohort_outcomes)

    async def _bounded_cohort_eval(cohort: _AlertCohort) -> dict[str, int]:
        wait_start = time.perf_counter()
        local_stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        async with semaphore:
            wait_ms = int((time.perf_counter() - wait_start) * 1000)
            _safe_record("cohort_size histogram", record_cohort_size, len(cohort.alerts))

            # Phase 1: cohort CH query (batched, with per-alert fallback on failure).
            query_result = await cohort_query_async(cohort)

            # Phase 2a: evaluate all alerts (sync, in-memory).
            evaluations: list[_AlertEvaluation] = []
            kept_eval_starts: list[float] = []
            for alert in cohort.alerts:
                eval_start = time.perf_counter()
                try:
                    evaluations.append(
                        _evaluate_single_alert(
                            alert,
                            now,
                            checkpoint=checkpoint,
                            prefetched=query_result.for_alert(alert),
                        )
                    )
                    kept_eval_starts.append(eval_start)
                except Exception:
                    logger.exception(
                        "Unexpected error evaluating alert",
                        alert_id=str(alert.id),
                        alert_name=alert.name,
                        team_id=alert.team_id,
                    )
                    local_stats["errored"] += 1

            # Phase 2b: dispatch all alerts in parallel (Kafka concurrency).
            dispatched_or_errors = await asyncio.gather(
                *(dispatch_async(ev, now) for ev in evaluations),
                return_exceptions=True,
            )
            # Capture per-alert elapsed_ms here — *before* Phase 3 starts — so the
            # `check_duration` metric measures eval + dispatch only, matching its
            # description. Cohort save time is recorded separately.
            phase_2_end = time.perf_counter()
            dispatched: list[_DispatchedAlert] = []
            elapsed_ms_per_alert: list[int] = []
            for ev, result, eval_start in zip(evaluations, dispatched_or_errors, kept_eval_starts):
                if isinstance(result, BaseException):
                    logger.exception(
                        "Unexpected error dispatching alert",
                        alert_id=str(ev.alert.id),
                        alert_name=ev.alert.name,
                        team_id=ev.alert.team_id,
                        exc_info=result,
                    )
                    local_stats["errored"] += 1
                else:
                    dispatched.append(result)
                    elapsed_ms_per_alert.append(int((phase_2_end - eval_start) * 1000))

            # Phase 3: bulk save — one `bulk_create` + one `bulk_update` per cohort.
            saved: list[_DispatchedAlert] = []
            failed: list[_DispatchedAlert] = []
            try:
                if dispatched:
                    saved, failed = await save_cohort_async(dispatched, now)
            except Exception as e:
                logger.exception(
                    "Cohort bulk save failed (non-recoverable)",
                    team_id=cohort.team_id,
                    cohort_size=len(dispatched),
                )
                capture_exception(e, {"team_id": cohort.team_id, "phase": "bulk_save"})
                # Saves failed — count alerts as errored so the cycle stat
                # reflects that this cohort didn't advance state.
                local_stats["errored"] += len(dispatched)
                local_stats["checked"] += len(dispatched)
                return local_stats

            # Phase 4 (serial): finalize stats + per-alert post-save metrics.
            elapsed_by_alert_id = {str(d.evaluation.alert.id): ms for d, ms in zip(dispatched, elapsed_ms_per_alert)}
            for d in saved:
                _finalize_alert(d, elapsed_by_alert_id[str(d.evaluation.alert.id)], local_stats)
            for _ in failed:
                # Alert's per-alert fallback save failed — count as errored.
                local_stats["checked"] += 1
                local_stats["errored"] += 1
        _safe_record("semaphore_wait histogram", record_semaphore_wait, wait_ms)
        return local_stats

    tasks: list[asyncio.Task[dict[str, int]]] = []
    async with asyncio.TaskGroup() as tg:
        for cohort in cohorts:
            tasks.append(tg.create_task(_bounded_cohort_eval(cohort)))

    aggregated = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
    for task in tasks:
        for k, v in task.result().items():
            aggregated[k] += v

    if aggregated["checked"] > 0:
        logger.info("Alert check cycle complete", **aggregated)

    try:
        pending = await database_sync_to_async_pool(_count_pending_alerts)()
        record_pending_alerts(pending)
    except Exception:
        logger.exception("Failed to record pending_alerts gauge")

    return CheckAlertsOutput(
        alerts_checked=aggregated["checked"],
        alerts_fired=aggregated["fired"],
        alerts_resolved=aggregated["resolved"],
        alerts_errored=aggregated["errored"],
    )


def _due_alerts_qs(now: datetime):
    return (
        LogsAlertConfiguration.objects.filter(
            Q(enabled=True),
            Q(next_check_at__lte=now) | Q(next_check_at__isnull=True),
        )
        .exclude(state=LogsAlertConfiguration.State.SNOOZED, snooze_until__gt=now)
        .exclude(state=LogsAlertConfiguration.State.BROKEN)
    )


def _count_pending_alerts() -> int:
    return _due_alerts_qs(datetime.now(UTC)).count()


def _load_alerts_and_checkpoint() -> tuple[datetime, list[LogsAlertConfiguration], datetime | None]:
    """Sync setup: pin `now`, load due alerts, fetch ingestion checkpoint, emit cycle metrics."""
    now = datetime.now(UTC)

    all_alerts = list(_due_alerts_qs(now).select_related("team"))

    try:
        record_alerts_active(len(all_alerts))
    except Exception:
        logger.exception("Failed to record alerts_active gauge")

    checkpoint: datetime | None = None
    if all_alerts:
        try:
            checkpoint = fetch_live_logs_checkpoint(all_alerts[0].team)
        except Exception:
            logger.exception("Failed to fetch logs ingestion checkpoint; falling back to wall-clock")

    try:
        if checkpoint is None:
            increment_checkpoint_unavailable()
        else:
            record_checkpoint_lag(now, checkpoint)
    except Exception:
        logger.exception("Failed to record checkpoint metric")

    return now, all_alerts, checkpoint


def _build_cohorts(
    alerts: list[LogsAlertConfiguration],
    *,
    now: datetime,
    checkpoint: datetime | None,
) -> list[_AlertCohort]:
    """Group alerts into cohorts that can share a batched CH query.

    Cohort key: (team_id, window_minutes, evaluation_periods, projection_eligible, date_to).
    A single-alert "cohort" is fine — `BatchedAlertCheckQuery` with N=1 has the
    same shape as `AlertCheckQuery.execute_bucketed`, so we don't bother
    bypassing the batched path for cohorts of one.
    """
    grouped: dict[tuple, list[LogsAlertConfiguration]] = {}
    for alert in alerts:
        nca = alert.next_check_at if alert.next_check_at is not None else now
        date_to = resolve_alert_date_to(nca, checkpoint)
        key = (
            alert.team_id,
            alert.window_minutes,
            alert.evaluation_periods,
            is_projection_eligible(alert.filters),
            date_to,
        )
        grouped.setdefault(key, []).append(alert)

    return [
        _AlertCohort(alerts=tuple(members), date_to=key[4], projection_eligible=key[3])
        for key, members in grouped.items()
    ]


def _run_batched_query(cohort: _AlertCohort) -> BatchedBucketedResult:
    return BatchedAlertCheckQuery(
        team=cohort.team,
        alerts=list(cohort.alerts),
        date_from=cohort.date_from,
        date_to=cohort.date_to,
        projection_eligible=cohort.projection_eligible,
    ).execute_bucketed(interval_minutes=cohort.window_minutes, limit=cohort.evaluation_periods)


def _run_per_alert_queries(cohort: _AlertCohort) -> _CohortQueryResult:
    per_alert: dict[str, _PrefetchedQuery] = {}
    for alert in cohort.alerts:
        start = time.monotonic_ns()
        try:
            buckets = AlertCheckQuery(
                team=alert.team,
                alert=alert,
                date_from=cohort.date_from,
                date_to=cohort.date_to,
            ).execute_bucketed(interval_minutes=cohort.window_minutes, limit=cohort.evaluation_periods)
            duration_ms = (time.monotonic_ns() - start) // 1_000_000
            per_alert[str(alert.id)] = _PrefetchedQuery(buckets=buckets, query_duration_ms=duration_ms)
        except Exception as e:
            duration_ms = (time.monotonic_ns() - start) // 1_000_000
            per_alert[str(alert.id)] = _PrefetchedQuery(error=e, query_duration_ms=duration_ms)
    return _CohortQueryResult(per_alert=per_alert)


def _run_cohort_query(cohort: _AlertCohort) -> _CohortQueryResult:
    """Batched cohort CH query; per-alert fallback on non-transient failure.

    Skip fallback for single-alert cohorts (would hit the same error) and transient cluster
    errors (would hammer a struggling cluster with N more failing queries).
    """
    try:
        batched = _run_batched_query(cohort)
    except Exception as e:
        team_id = cohort.team_id
        cohort_size = len(cohort.alerts)

        if cohort_size == 1:
            return _CohortQueryResult(per_alert={str(cohort.alerts[0].id): _PrefetchedQuery(error=e)})

        classified = classify_alert_error(e)
        if classified.is_transient:
            logger.warning(
                "Batched cohort query failed (transient); skipping per-alert fallback",
                team_id=team_id,
                cohort_size=cohort_size,
                error=str(e),
                classification=classified.code,
            )
            _safe_record("cohort_query_fallback counter", increment_cohort_query_fallback, "transient_no_fallback")
            return _CohortQueryResult(per_alert={str(a.id): _PrefetchedQuery(error=e) for a in cohort.alerts})

        logger.warning(
            "Batched cohort query failed; falling back to per-alert queries",
            team_id=team_id,
            cohort_size=cohort_size,
            error=str(e),
            classification=classified.code,
        )
        capture_exception(e, {"team_id": team_id, "cohort_size": cohort_size})
        _safe_record("cohort_query_fallback counter", increment_cohort_query_fallback, "batched_failure")
        return _run_per_alert_queries(cohort)

    return _CohortQueryResult(
        per_alert={
            str(alert.id): _PrefetchedQuery(
                buckets=batched.per_alert.get(str(alert.id), []),
                query_duration_ms=batched.query_duration_ms,
            )
            for alert in cohort.alerts
        }
    )


def _check_alerts_sync() -> CheckAlertsOutput:
    """Synchronous variant kept for unit tests. Production runs through `check_alerts_activity`.

    Mirrors the async cohort dispatch shape (CH batched query → per-alert eval +
    Kafka dispatch → bulk save) so tests cover the production code path.
    """
    now, all_alerts, checkpoint = _load_alerts_and_checkpoint()
    cohorts = _build_cohorts(all_alerts, now=now, checkpoint=checkpoint)

    stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
    for cohort in cohorts:
        _safe_record("cohort_size histogram", record_cohort_size, len(cohort.alerts))

        # Phase 1: cohort CH query (batched, with per-alert fallback on failure).
        query_result = _run_cohort_query(cohort)

        # Phase 2a: evaluate all alerts.
        evaluations: list[_AlertEvaluation] = []
        eval_starts: list[float] = []
        for alert in cohort.alerts:
            eval_start = time.perf_counter()
            try:
                evaluation = _evaluate_single_alert(
                    alert,
                    now,
                    checkpoint=checkpoint,
                    prefetched=query_result.for_alert(alert),
                )
            except Exception:
                logger.exception(
                    "Unexpected error evaluating alert",
                    alert_id=str(alert.id),
                    alert_name=alert.name,
                    team_id=alert.team_id,
                )
                stats["errored"] += 1
                continue
            evaluations.append(evaluation)
            eval_starts.append(eval_start)

        # Phase 2b: dispatch all alerts.
        dispatched: list[_DispatchedAlert] = []
        kept_eval_starts_for_dispatch: list[float] = []
        for ev, eval_start in zip(evaluations, eval_starts):
            try:
                d = _dispatch_for_alert(ev, now)
            except Exception:
                logger.exception(
                    "Unexpected error dispatching alert",
                    alert_id=str(ev.alert.id),
                    alert_name=ev.alert.name,
                    team_id=ev.alert.team_id,
                )
                stats["errored"] += 1
                continue
            dispatched.append(d)
            kept_eval_starts_for_dispatch.append(eval_start)

        # Snapshot per-alert elapsed_ms here so it doesn't include Phase 3.
        phase_2_end = time.perf_counter()
        elapsed_ms_per_alert = [int((phase_2_end - es) * 1000) for es in kept_eval_starts_for_dispatch]

        # Phase 3: bulk save.
        saved: list[_DispatchedAlert] = []
        failed: list[_DispatchedAlert] = []
        try:
            if dispatched:
                saved, failed = _save_cohort_outcomes(dispatched, now)
        except Exception as e:
            logger.exception(
                "Cohort bulk save failed (non-recoverable)",
                team_id=cohort.team_id,
                cohort_size=len(dispatched),
            )
            capture_exception(e, {"team_id": cohort.team_id, "phase": "bulk_save"})
            stats["errored"] += len(dispatched)
            stats["checked"] += len(dispatched)
            continue

        # Phase 4: finalize stats + per-alert post-save metrics.
        elapsed_by_alert_id = {str(d.evaluation.alert.id): ms for d, ms in zip(dispatched, elapsed_ms_per_alert)}
        for d in saved:
            _finalize_alert(d, elapsed_by_alert_id[str(d.evaluation.alert.id)], stats)
        for _ in failed:
            stats["checked"] += 1
            stats["errored"] += 1

    if stats["checked"] > 0:
        logger.info("Alert check cycle complete", **stats)

    return CheckAlertsOutput(
        alerts_checked=stats["checked"],
        alerts_fired=stats["fired"],
        alerts_resolved=stats["resolved"],
        alerts_errored=stats["errored"],
    )


def _dispatch_notification(
    outcome: AlertCheckOutcome,
    alert: LogsAlertConfiguration,
    check_result: CheckResult,
    now: datetime,
    *,
    date_from: datetime,
    date_to: datetime,
) -> bool:
    """Emit the notification for this outcome. Returns True if delivery failed.

    Pure-effect: produces a Kafka message and logs. Does NOT mutate `stats` —
    the orchestrator owns stats accounting so it stays single-threaded after
    the parallel dispatch phase.
    """
    action = outcome.notification
    if action == NotificationAction.NONE:
        return False

    log = logger.bind(alert_id=str(alert.id), alert_name=alert.name, team_id=alert.team_id)

    if action == NotificationAction.FIRE:
        notified = _emit_alert_event(
            alert, "$logs_alert_firing", check_result, now, date_from=date_from, date_to=date_to
        )
        log.info("Alert fired", result_count=check_result.result_count, notified=notified)
    elif action == NotificationAction.RESOLVE:
        notified = _emit_alert_event(
            alert, "$logs_alert_resolved", check_result, now, date_from=date_from, date_to=date_to
        )
        log.info("Alert resolved", notified=notified)
    elif action == NotificationAction.ERROR:
        notified = _emit_alert_errored_event(alert, outcome, now)
        log.info("Alert entered errored state", consecutive_failures=outcome.consecutive_failures, notified=notified)
    elif action == NotificationAction.BROKEN:
        notified = _emit_auto_disabled_event(alert, outcome, now)
        log.warning(
            "Alert broken after consecutive failures",
            consecutive_failures=outcome.consecutive_failures,
            notified=notified,
        )
    else:
        raise ValueError(f"Unhandled NotificationAction: {action!r}")

    return not notified


def _dispatch_for_alert(evaluation: _AlertEvaluation, now: datetime) -> _DispatchedAlert:
    """Phase 2: dispatch the Kafka notification for one alert.

    Pure-effect (Kafka). The orchestrator updates `stats` serially after the
    dispatch phase so concurrent gather'd dispatches can't race on the dict.
    """
    notification_failed = _dispatch_notification(
        evaluation.outcome,
        evaluation.alert,
        evaluation.check_result,
        now,
        date_from=evaluation.date_from,
        date_to=evaluation.date_to,
    )
    return _DispatchedAlert(evaluation=evaluation, notification_failed=notification_failed)


def _stage_alert_for_save(dispatched: _DispatchedAlert, now: datetime) -> tuple[list[str], LogsAlertEvent | None]:
    """Mutate the in-memory alert so it's ready for `bulk_update`, return the
    `update_fields` list and the optional `LogsAlertEvent` row to insert.

    All state/consecutive_failures writes go through `apply_outcome` per the
    semgrep rule — same contract as the per-alert path.
    """
    evaluation = dispatched.evaluation
    alert = evaluation.alert
    committed = dispatched.committed_outcome
    is_error = evaluation.outcome.error_message is not None
    state_changed = evaluation.state_before != committed.new_state.value

    update_fields = apply_outcome(alert, committed)
    alert.last_checked_at = now
    # `updated_at` has `auto_now=True`, but Django's `bulk_update` doesn't apply
    # `auto_now` — set it explicitly so the timestamp advances on the bulk path
    # (the per-alert fallback's `alert.save()` would honour `auto_now`, but the
    # happy path is bulk_update).
    alert.updated_at = now
    alert.next_check_at = advance_next_check_at(alert.next_check_at, alert.check_interval_minutes, now)
    update_fields.extend(["last_checked_at", "next_check_at", "updated_at"])

    if (
        not dispatched.notification_failed
        and evaluation.outcome.notification != NotificationAction.NONE
        and evaluation.outcome.update_last_notified_at
    ):
        alert.last_notified_at = now
        update_fields.append("last_notified_at")

    event: LogsAlertEvent | None = None
    if state_changed or is_error:
        event = LogsAlertEvent(
            alert=alert,
            result_count=evaluation.check_result.result_count,
            threshold_breached=evaluation.check_result.threshold_breached,
            state_before=evaluation.state_before,
            state_after=committed.new_state.value,
            error_message=evaluation.outcome.error_message,
            query_duration_ms=evaluation.check_result.query_duration_ms,
        )
    return update_fields, event


# All bulk_update calls touch the same fields per cohort — alerts that aren't
# notifying still get last_notified_at written back unchanged. Cheap, keeps
# the bulk_update field list constant.
_COHORT_UPDATE_FIELDS: list[str] = [
    "state",
    "consecutive_failures",
    "last_checked_at",
    "next_check_at",
    "last_notified_at",
    "updated_at",
]


def _save_cohort_outcomes(
    dispatched: list[_DispatchedAlert], now: datetime
) -> tuple[list[_DispatchedAlert], list[_DispatchedAlert]]:
    """Phase 3: persist the cohort's outcomes via one bulk_create + one bulk_update.

    Returns `(saved, failed)` — saved alerts advanced to their committed state,
    failed alerts didn't (caller treats them as errored).

    On `IntegrityError` (constraint shaped — a row hit a DB constraint we didn't
    anticipate), fall back to per-alert UPDATEs so the rest still advance.
    `OperationalError`/`DataError` are propagated so the caller advances each
    alert's `consecutive_failures` via the standard error path; per-alert
    fallback against the same broken cluster wouldn't help.
    """
    if not dispatched:
        return [], []

    save_start = time.perf_counter()

    # Stage every alert exactly once: mutates the in-memory alert (apply_outcome,
    # advance_next_check_at, etc.) and produces the (update_fields, event) tuple
    # needed to write it. We keep the staged tuples so the IntegrityError
    # fallback can save each alert individually without re-staging — calling
    # `advance_next_check_at` twice would otherwise skip a cycle slot.
    staged: list[tuple[_DispatchedAlert, list[str], LogsAlertEvent | None]] = []
    for d in dispatched:
        update_fields, event = _stage_alert_for_save(d, now)
        staged.append((d, update_fields, event))

    events = [event for _, _, event in staged if event is not None]
    alerts = [d.evaluation.alert for d, _, _ in staged]

    event_insert_ms: int | None = None
    update_ms: int | None = None
    saved: list[_DispatchedAlert] = list(dispatched)
    failed: list[_DispatchedAlert] = []
    try:
        with transaction.atomic():
            if events:
                event_insert_start = time.perf_counter()
                LogsAlertEvent.objects.bulk_create(events)
                event_insert_ms = int((time.perf_counter() - event_insert_start) * 1000)

            update_start = time.perf_counter()
            LogsAlertConfiguration.objects.bulk_update(alerts, fields=_COHORT_UPDATE_FIELDS)
            update_ms = int((time.perf_counter() - update_start) * 1000)
    except IntegrityError as e:
        # Recover the rest of the cohort via per-alert UPDATEs using the
        # already-staged data.
        logger.warning(
            "Cohort bulk save hit IntegrityError; falling back to per-alert",
            error=str(e),
            cohort_size=len(dispatched),
        )
        capture_exception(e, {"cohort_size": len(dispatched), "fallback": "per_alert"})
        increment_cohort_save_fallback("integrity_error")
        saved, failed = _save_staged_per_alert(staged)

    save_ms = int((time.perf_counter() - save_start) * 1000)
    try:
        record_cohort_save_duration(save_ms)
        if event_insert_ms is not None:
            record_cohort_event_insert_duration(event_insert_ms)
        if update_ms is not None:
            record_cohort_update_duration(update_ms)
    except Exception:
        logger.exception("Failed to record cohort save metrics")

    return saved, failed


def _save_staged_per_alert(
    staged: list[tuple[_DispatchedAlert, list[str], LogsAlertEvent | None]],
) -> tuple[list[_DispatchedAlert], list[_DispatchedAlert]]:
    """Fallback path used when `bulk_update` raises `IntegrityError`.

    Returns `(saved, failed)`. Each alert saves independently so a single bad
    row doesn't strand the cohort. Takes pre-staged tuples (alert already
    mutated, event already instantiated) so we don't re-run
    `_stage_alert_for_save` and accidentally advance `next_check_at` twice.
    """
    saved: list[_DispatchedAlert] = []
    failed: list[_DispatchedAlert] = []
    for d, update_fields, event in staged:
        try:
            with transaction.atomic():
                if event is not None:
                    event.save()
                d.evaluation.alert.save(update_fields=update_fields)
            saved.append(d)
        except Exception as e:
            logger.exception(
                "Per-alert fallback save failed",
                alert_id=str(d.evaluation.alert.id),
                team_id=d.evaluation.alert.team_id,
            )
            capture_exception(e, {"alert_id": str(d.evaluation.alert.id), "phase": "per_alert_fallback"})
            failed.append(d)
    return saved, failed


def _finalize_alert(dispatched: _DispatchedAlert, elapsed_ms: int, stats: dict[str, int]) -> None:
    """Per-alert post-save bookkeeping: cycle stats + metrics that depend on the committed state.

    Runs serially (not gathered) so `stats` mutation stays single-threaded.
    `elapsed_ms` is the precomputed eval + dispatch duration captured by the
    orchestrator at the end of Phase 2 — *before* Phase 3 (the cohort bulk save)
    starts. `record_check_duration` therefore measures only the per-alert work,
    matching the metric description; cohort save time is captured separately by
    `record_cohort_save_duration`.
    """
    evaluation = dispatched.evaluation
    outcome = evaluation.outcome
    committed_state = dispatched.committed_outcome.new_state

    stats["checked"] += 1
    if outcome.error_message:
        stats["errored"] += 1
    elif not dispatched.notification_failed:
        if outcome.notification == NotificationAction.FIRE:
            stats["fired"] += 1
        elif outcome.notification == NotificationAction.RESOLVE:
            stats["resolved"] += 1

    try:
        record_check_duration(elapsed_ms)

        if outcome.error_message:
            increment_checks_total("errored")
        elif dispatched.notification_failed:
            increment_checks_total("errored")
        elif outcome.notification == NotificationAction.FIRE:
            increment_checks_total("fired")
        elif outcome.notification == NotificationAction.RESOLVE:
            increment_checks_total("resolved")
        else:
            increment_checks_total("ok")

        if dispatched.notification_failed:
            increment_notification_failures(outcome.notification)

        state_before_enum = AlertState(evaluation.state_before)
        if committed_state != state_before_enum:
            increment_state_transition(state_before_enum, committed_state)
    except Exception:
        logger.exception("Failed to record alert finalize metrics", alert_id=str(evaluation.alert.id))


def _evaluate_single_alert(
    alert: LogsAlertConfiguration,
    now: datetime,
    *,
    checkpoint: datetime | None = None,
    prefetched: _PrefetchedQuery | None = None,
) -> _AlertEvaluation:
    """Phase 1: run the CH query (or use prefetched buckets), apply the state machine, return the outcome.

    Pure-ish — does not dispatch Kafka, does not write to Postgres. The cohort
    orchestrator handles both side-effect phases.

    Stateless eval: a single bucketed CH query returns the last M counts; the
    N-of-M evaluator decides from those buckets directly. Anchored on
    `next_check_at` so two evals at different actual eval times produce the
    same query.

    `prefetched` is set when the caller already ran a batched query for the
    alert's cohort — either with the alert's bucket slice, or with the cohort's
    error (re-raised inside the try block to flow through the same
    classification as a per-alert failure).
    """
    original_next_check_at = alert.next_check_at

    # First-run alerts (`next_check_at` still null after enable) anchor on `now`;
    # from the second eval onward, `next_check_at` is set and idempotence holds.
    nca = alert.next_check_at if alert.next_check_at is not None else now
    date_to = resolve_alert_date_to(nca, checkpoint)
    # Each bucket represents one historical "what the alert query would have
    # returned" — window_minutes of data. M buckets cover M * window_minutes total.
    date_from = date_to - timedelta(minutes=alert.window_minutes * alert.evaluation_periods)

    check_result: CheckResult
    recent_breaches: tuple[bool, ...] = ()
    error_category: AlertErrorCode | None = None
    try:
        if prefetched is not None and prefetched.error is not None:
            raise prefetched.error
        if prefetched is not None and prefetched.buckets is not None:
            buckets = prefetched.buckets
            query_duration_ms = prefetched.query_duration_ms if prefetched.query_duration_ms is not None else 0
        else:
            query_start = time.perf_counter()
            buckets = AlertCheckQuery(
                team=alert.team,
                alert=alert,
                date_from=date_from,
                date_to=date_to,
            ).execute_bucketed(interval_minutes=alert.window_minutes, limit=alert.evaluation_periods)
            query_duration_ms = int((time.perf_counter() - query_start) * 1000)

        # execute_bucketed returns ASC (oldest first); state machine wants newest first.
        # Buckets that are entirely empty are absent from the result, so a sparse window
        # naturally produces a shorter breaches tuple — same behavior as today's
        # get_recent_breaches when fewer than M CHECK rows exist.
        breaches = _derive_breaches(buckets, alert.threshold_count, alert.threshold_operator, alert.evaluation_periods)
        latest_count = buckets[-1].count if buckets else 0
        check_result = CheckResult(
            result_count=latest_count,
            threshold_breached=breaches[0] if breaches else False,
            query_duration_ms=query_duration_ms,
        )
        recent_breaches = breaches[1:]
    except Exception as e:
        classified = classify_alert_error(e)
        error_category = classified.code
        capture_exception(e, {"alert_id": str(alert.id), "classification": classified.code})
        logger.warning(
            "Alert check query failed",
            alert_id=str(alert.id),
            alert_name=alert.name,
            team_id=alert.team_id,
            error=str(e),
            classification=classified.code,
        )
        check_result = CheckResult(
            result_count=None,
            threshold_breached=False,
            error_message=classified.user_message,
            is_transient_error=classified.is_transient,
        )

    outcome = evaluate_alert_check(alert.to_snapshot(recent_events_breached=recent_breaches), check_result, now)

    # Eval-phase metrics: CH-side and scheduler lag. Save/dispatch metrics fire
    # later in their own phases.
    try:
        if check_result.query_duration_ms is not None:
            record_clickhouse_duration(check_result.query_duration_ms)
        if original_next_check_at is not None:
            lag_ms = int((now - original_next_check_at).total_seconds() * 1000)
            if lag_ms > 0:
                record_scheduler_lag(lag_ms)
        if error_category is not None:
            increment_check_errors(error_category)
    except Exception:
        logger.exception("Failed to record alert eval metrics", alert_id=str(alert.id))

    return _AlertEvaluation(
        alert=alert,
        outcome=outcome,
        check_result=check_result,
        date_from=date_from,
        date_to=date_to,
        state_before=alert.state,
    )


def _produce_alert_internal_event(
    alert: LogsAlertConfiguration,
    event_name: str,
    properties: dict,
    now: datetime,
) -> bool:
    try:
        produce_internal_event(
            team_id=alert.team_id,
            event=InternalEventEvent(
                event=event_name,
                distinct_id=f"team_{alert.team_id}",
                properties=properties,
                timestamp=now.isoformat(),
            ),
        )
        return True
    except Exception as e:
        capture_exception(e, {"alert_id": str(alert.id), "event": event_name})
        return False


def _emit_alert_event(
    alert: LogsAlertConfiguration,
    event_name: str,
    check_result: CheckResult,
    now: datetime,
    *,
    date_from: datetime,
    date_to: datetime,
) -> bool:
    properties: dict = {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "threshold_count": alert.threshold_count,
        "threshold_operator": alert.threshold_operator,
        "window_minutes": alert.window_minutes,
        "result_count": check_result.result_count,
        "filters": alert.filters,
        "service_names": alert.filters.get("serviceNames", []),
        "severity_levels": alert.filters.get("severityLevels", []),
        "logs_url_params": build_logs_url_params(alert.filters, date_from=date_from, date_to=date_to),
        "triggered_at": now.isoformat(),
    }
    return _produce_alert_internal_event(alert, event_name, properties, now)


def _base_failure_properties(
    alert: LogsAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> dict:
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "consecutive_failures": outcome.consecutive_failures,
        "service_names": alert.filters.get("serviceNames", []),
        "severity_levels": alert.filters.get("severityLevels", []),
        "triggered_at": now.isoformat(),
    }


def _emit_auto_disabled_event(
    alert: LogsAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> bool:
    properties = {
        **_base_failure_properties(alert, outcome, now),
        "last_error_message": outcome.error_message or "",
    }
    return _produce_alert_internal_event(alert, "$logs_alert_auto_disabled", properties, now)


def _emit_alert_errored_event(
    alert: LogsAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> bool:
    properties = {
        **_base_failure_properties(alert, outcome, now),
        "error_message": outcome.error_message or "",
    }
    return _produce_alert_internal_event(alert, "$logs_alert_errored", properties, now)
