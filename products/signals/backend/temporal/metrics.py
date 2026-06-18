"""Prometheus metrics for the signals pipeline.

Deliberately narrow: a handful of business-level counters that power incident
alerts, emitted at the same stable callsites as the pipeline's product-analytics
events (``signal_emitted``, ``signal_dropped``, ``signal_report_completed``, ...).
Because they live next to those ``capture()`` calls, they move with the code when
activities are renamed or moved — they are not pinned to an activity-name registry.

What is intentionally NOT here:

- Per-activity / per-workflow execution latency and failure counts. Temporal's
  built-in SDK metrics already expose these for free on this worker, labelled by
  ``activity_type`` / ``workflow_type``: ``temporal_activity_execution_latency``,
  ``temporal_activity_schedule_to_start_latency`` (queue depth, the saturation
  signal), ``temporal_activity_execution_failed``, ``temporal_workflow_failed``,
  and ``temporal_workflow_endtoend_latency``. Re-deriving them here would mean
  hand-maintaining a list of every activity name.
- LLM token / cost / latency and embedding latency — cost/quality signals already
  covered by LLM observability and the product-analytics events, not incidents.

Cardinality note: no ``team_id`` label — per-team drill-down lives in the
product-analytics events. Labels stay within the small bounded sets below.
"""

from temporalio import activity, workflow

from posthog.temporal.common.metrics import get_metric_meter

# Funnel stages, in pipeline order, for `signals_funnel_total`. The funnel is
# self-contained (emitted is the denominator) so alerts depend on one metric.
FUNNEL_STAGE_EMITTED = "emitted"
FUNNEL_STAGE_SAFETY_BLOCKED = "safety_blocked"
FUNNEL_STAGE_GROUPED = "grouped"
FUNNEL_STAGE_PROMOTED = "promoted"

# LLM call outcomes for `signals_llm_calls_total`.
LLM_STATUS_OK = "ok"
LLM_STATUS_ERROR = "error"


def _in_temporal_context() -> bool:
    return activity.in_activity() or workflow.in_workflow()


def increment_funnel(stage: str, source_product: str = "unknown", count: int = 1) -> None:
    """Count signals reaching a pipeline funnel stage. No-ops outside a Temporal context."""
    if not _in_temporal_context() or count <= 0:
        return
    get_metric_meter({"stage": stage, "source_product": source_product}).create_counter(
        "signals_funnel_total",
        "Signals reaching each pipeline funnel stage",
    ).add(count)


def increment_dropped(stage: str, reason: str, count: int = 1) -> None:
    """Count signals lost to an error, attributed to a stage and reason (the error indicator)."""
    if not _in_temporal_context() or count <= 0:
        return
    get_metric_meter({"stage": stage, "reason": reason}).create_counter(
        "signals_dropped_total",
        "Signals dropped from the pipeline by stage and reason",
    ).add(count)


def increment_report_completed(result: str) -> None:
    """Count report completions by result (ready/failed/not_actionable/pending_input)."""
    if not _in_temporal_context():
        return
    get_metric_meter({"result": result}).create_counter(
        "signals_reports_total",
        "Signal reports completed by result",
    ).add(1)


def increment_llm_call(stage: str, status: str) -> None:
    """Count an LLM call on the grouping/summary hot path by stage and outcome."""
    if not _in_temporal_context():
        return
    get_metric_meter({"stage": stage, "status": status}).create_counter(
        "signals_llm_calls_total",
        "LLM calls by stage and outcome",
    ).add(1)


def increment_ch_wait_timeout() -> None:
    """Count a give-up of the wait-for-signal-in-ClickHouse consistency wait."""
    if not _in_temporal_context():
        return
    get_metric_meter().create_counter(
        "signals_ch_wait_timeouts_total",
        "Times the wait-for-signal-in-ClickHouse activity gave up after its max wait",
    ).add(1)


def increment_scout_run(status: str) -> None:
    """Count a scout run by terminal status — the signal source feeding the pipeline."""
    if not _in_temporal_context():
        return
    get_metric_meter({"status": status}).create_counter(
        "signals_scout_runs_total",
        "Signals scout runs by terminal status",
    ).add(1)
