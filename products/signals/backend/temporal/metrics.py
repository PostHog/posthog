"""Prometheus metrics for the Signals pipeline temporal workflows.

Metrics are emitted via Temporal's built-in metric meter (activity/workflow context)
and scraped by the Prometheus endpoint on the worker pod. Follows the same pattern as
the AI-observability metrics modules (eval_reports, sentiment, trace_clustering).

Two layers of instrumentation live here:

1. ``SignalsMetricsInterceptor`` — automatic, uniform per-activity execution latency,
   schedule-to-start latency (queue-depth indicator), and workflow execution latency +
   started/finished counters. This covers every activity in the pipeline without each
   one having to opt in.
2. Explicit counter/histogram helpers (funnel, drops, report/agentic outcomes, LLM,
   embedding, ClickHouse wait) called from the relevant activities for the business
   metrics the interceptor can't infer.

Cardinality note: these metrics deliberately avoid a ``team_id`` label — per-team
drill-down lives in the product-analytics events (``signal_report_completed`` et al.).
Keep it that way to avoid a series explosion on the histograms.
"""

import time
import typing
import datetime as dt

from django.conf import settings

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.common.metrics import Attributes, ExecutionTimeRecorder, get_metric_meter

# ---------------------------------------------------------------------------
# Histogram bucket config (imported by common/worker.py for PrometheusConfig)
# ---------------------------------------------------------------------------

SIGNALS_LATENCY_HISTOGRAM_METRICS = (
    "signals_activity_execution_latency",
    "signals_activity_schedule_to_start_latency",
    "signals_workflow_execution_latency",
    "signals_llm_call_latency",
    "signals_embedding_latency",
    "signals_ch_wait_latency",
)
# Buckets span 50ms (S3/Postgres round-trips) to 4h (the agentic research activity).
SIGNALS_LATENCY_HISTOGRAM_BUCKETS = [
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,  # 1s
    2_500.0,
    5_000.0,
    10_000.0,
    30_000.0,
    60_000.0,  # 1m
    120_000.0,  # 2m
    300_000.0,  # 5m
    600_000.0,  # 10m
    1_800_000.0,  # 30m
    3_600_000.0,  # 1h
    7_200_000.0,  # 2h
    14_400_000.0,  # 4h
]

# ---------------------------------------------------------------------------
# Activity / workflow type sets for the interceptor
# ---------------------------------------------------------------------------

# Every signals-pipeline activity. The interceptor times anything in this set;
# activities for other products that share the task queue are passed through untouched.
SIGNALS_ACTIVITY_TYPES = {
    "assign_and_emit_signal_activity",
    "capture_signal_dropped_activity",
    "delete_report_activity",
    "delete_team_reports_activity",
    "dispatch_inbox_slack_notifications_activity",
    "emit_backfill_signal_activity",
    "fetch_enabled_signals_scout_runs_activity",
    "fetch_error_tracking_issues_activity",
    "fetch_report_contexts_activity",
    "fetch_signal_type_examples_activity",
    "fetch_signals_for_report_activity",
    "flush_signals_to_s3_activity",
    "generate_search_queries_activity",
    "get_embedding_activity",
    "get_grouping_paused_state_activity",
    "get_inbox_notification_state_activity",
    "mark_report_failed_activity",
    "mark_report_in_progress_activity",
    "mark_report_pending_input_activity",
    "mark_report_ready_activity",
    "match_signal_to_report_activity",
    "pause_grouping_until_activity",
    "process_team_signals_batch_activity",
    "publish_report_completed_activity",
    "read_signals_from_s3_activity",
    "reingest_signals_activity",
    "report_safety_judge_activity",
    "reset_report_to_potential_activity",
    "restore_grouping_pause_activity",
    "run_agentic_report_activity",
    "run_custom_signal_agent_activity",
    "run_signal_semantic_search_activity",
    "run_signals_scout_activity",
    "safety_filter_activity",
    "select_repository_activity",
    "send_report_inbox_notifications_activity",
    "signal_with_start_grouping_v2_activity",
    "soft_delete_report_signals_activity",
    "stamp_dispatched_signals_scout_runs_activity",
    "submit_signal_to_buffer_activity",
    "verify_match_specificity_activity",
    "wait_for_signal_in_clickhouse_activity",
}

# Workflows where end-to-end execution latency is meaningful. The long-lived,
# continue-as-new loops (buffer-signals, team-signal-grouping[-v2]) are deliberately
# excluded — their "execution" is one bounded loop iteration, not a unit of work, and
# their continue-as-new raises would be miscounted as failures.
SIGNALS_WORKFLOW_TYPES = {
    "signal-emitter",
    "signal-report-summary",
}

# ---------------------------------------------------------------------------
# Funnel / drop / outcome counters
# ---------------------------------------------------------------------------

# Signal-level funnel stages, in pipeline order. "emitted" is already covered by the
# existing `signals_emitted` counter; these track everything downstream of it. Report-level
# outcomes (a report reaching ready/failed/...) are a different unit — see
# `signals_report_outcome_total` rather than mixing them into this signal funnel.
FUNNEL_STAGE_SAFETY_BLOCKED = "safety_blocked"
FUNNEL_STAGE_GROUPED = "grouped"
FUNNEL_STAGE_CANDIDATE_PROMOTED = "candidate_promoted"


def _in_temporal_context() -> bool:
    return activity.in_activity() or workflow.in_workflow()


def increment_funnel_stage(stage: str, source_product: str, count: int = 1) -> None:
    """Count signals reaching a pipeline funnel stage. Safe to call outside Temporal (no-ops)."""
    if not _in_temporal_context() or count <= 0:
        return
    meter = get_metric_meter({"stage": stage, "source_product": source_product})
    meter.create_counter(
        "signals_funnel_stage_total",
        "Signals reaching each downstream pipeline funnel stage",
    ).add(count)


def increment_signal_dropped(stage: str, reason: str, count: int = 1) -> None:
    """Count signals dropped from the pipeline, attributed to a stage and reason."""
    if not _in_temporal_context() or count <= 0:
        return
    meter = get_metric_meter({"stage": stage, "reason": reason})
    meter.create_counter(
        "signals_dropped_total",
        "Signals dropped from the pipeline by stage and reason",
    ).add(count)


def increment_report_outcome(outcome: str) -> None:
    """Count report lifecycle completions (ready/failed/pending_input/not_actionable)."""
    if not _in_temporal_context():
        return
    meter = get_metric_meter({"outcome": outcome})
    meter.create_counter(
        "signals_report_outcome_total",
        "Signal report lifecycle outcomes",
    ).add(1)


def increment_agentic_research(outcome: str) -> None:
    """Count agentic research runs by their actionability outcome (or 'failed')."""
    if not _in_temporal_context():
        return
    meter = get_metric_meter({"outcome": outcome})
    meter.create_counter(
        "signals_agentic_research_total",
        "Agentic research runs by outcome",
    ).add(1)


# ---------------------------------------------------------------------------
# LLM / embedding helpers
# ---------------------------------------------------------------------------


def _record_latency(name: str, attributes: Attributes, started_at: float) -> None:
    meter = get_metric_meter(attributes)
    delta = dt.timedelta(milliseconds=int((time.perf_counter() - started_at) * 1000))
    meter.create_histogram_timedelta(name, description=name.replace("_", " "), unit="ms").record(delta)


def record_llm_call(*, stage: str, model: str, status: str, started_at: float) -> None:
    """Record an LLM call's latency and a status-labeled counter (success/error/timeout)."""
    if not _in_temporal_context():
        return
    attrs: Attributes = {"stage": stage, "model": model, "status": status}
    _record_latency("signals_llm_call_latency", attrs, started_at)
    get_metric_meter(attrs).create_counter(
        "signals_llm_calls_total",
        "LLM calls by stage, model and status",
    ).add(1)


def increment_llm_retry(stage: str) -> None:
    """Count an LLM validation-failure retry."""
    if not _in_temporal_context():
        return
    get_metric_meter({"stage": stage}).create_counter(
        "signals_llm_retries_total",
        "LLM calls retried after a validation failure",
    ).add(1)


def record_llm_tokens(*, stage: str, model: str, response: typing.Any) -> None:
    """Record input/output token usage from an Anthropic response (best-effort)."""
    if not _in_temporal_context():
        return
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    for token_type, attr in (("input", "input_tokens"), ("output", "output_tokens")):
        count = getattr(usage, attr, None)
        if not count:
            continue
        get_metric_meter({"stage": stage, "model": model, "token_type": token_type}).create_counter(
            "signals_llm_tokens_total",
            "LLM token usage by stage, model and token type",
        ).add(int(count))


def record_embedding_call(*, status: str, started_at: float) -> None:
    """Record an embedding generation call's latency and a status-labeled counter."""
    if not _in_temporal_context():
        return
    _record_latency("signals_embedding_latency", {"status": status}, started_at)
    get_metric_meter({"status": status}).create_counter(
        "signals_embedding_calls_total",
        "Embedding generation calls by status",
    ).add(1)


def record_ch_wait(*, started_at: float, timed_out: bool) -> None:
    """Record the ClickHouse-wait duration and, on timeout, a dedicated counter."""
    if not _in_temporal_context():
        return
    _record_latency("signals_ch_wait_latency", {"timed_out": "true" if timed_out else "false"}, started_at)
    if timed_out:
        get_metric_meter().create_counter(
            "signals_ch_wait_timeout_total",
            "Times the wait-for-signal-in-ClickHouse activity gave up after its max wait",
        ).add(1)


# ---------------------------------------------------------------------------
# Workflow counters
# ---------------------------------------------------------------------------


def _increment_workflow_started(workflow_type: str) -> None:
    get_metric_meter({"workflow_type": workflow_type}).create_counter(
        "signals_workflow_started_total",
        "Signals workflows started",
    ).add(1)


def _increment_workflow_finished(workflow_type: str, status: str) -> None:
    get_metric_meter({"workflow_type": workflow_type, "status": status}).create_counter(
        "signals_workflow_finished_total",
        "Signals workflows finished by status",
    ).add(1)


# ---------------------------------------------------------------------------
# Interceptor — automatic timing for activities and workflows
# ---------------------------------------------------------------------------


class SignalsMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for the signals pipeline."""

    task_queue = settings.VIDEO_EXPORT_TASK_QUEUE

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _SignalsActivityInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self,
        input: WorkflowInterceptorClassInput,  # noqa: A002
    ) -> type[WorkflowInboundInterceptor] | None:
        return _SignalsWorkflowInterceptor


class _SignalsActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in SIGNALS_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        # Schedule-to-start latency is a queue-depth / worker-saturation indicator.
        scheduled_time = activity_info.scheduled_time
        started_time = activity_info.started_time
        if scheduled_time and started_time:
            schedule_to_start_ms = int((started_time - scheduled_time).total_seconds() * 1000)
            get_metric_meter({"activity_type": activity_type}).create_histogram_timedelta(
                name="signals_activity_schedule_to_start_latency",
                description="Time between activity scheduling and start",
                unit="ms",
            ).record(dt.timedelta(milliseconds=schedule_to_start_ms))

        with ExecutionTimeRecorder(
            "signals_activity_execution_latency",
            description="Execution latency for signals pipeline activities",
            histogram_attributes={"activity_type": activity_type},
        ):
            return await super().execute_activity(input)


class _SignalsWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        workflow_type = workflow.info().workflow_type

        if workflow_type not in SIGNALS_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        _increment_workflow_started(workflow_type)

        with ExecutionTimeRecorder(
            "signals_workflow_execution_latency",
            description="End-to-end signals workflow execution latency",
            histogram_attributes={"workflow_type": workflow_type},
        ) as recorder:
            try:
                result = await super().execute_workflow(input)
                _increment_workflow_finished(workflow_type, "completed")
                return result
            except workflow.ContinueAsNewError:
                # Not a failure — re-raise without counting so loops aren't mislabeled.
                recorder.set_status("CONTINUED")
                raise
            except Exception:
                _increment_workflow_finished(workflow_type, "failed")
                raise
