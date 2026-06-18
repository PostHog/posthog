"""Business-level Prometheus counters for signals pipeline incident alerts."""

from temporalio import activity, workflow

from posthog.temporal.common.metrics import get_metric_meter

FUNNEL_STAGE_EMITTED = "emitted"
FUNNEL_STAGE_GROUPED = "grouped"
FUNNEL_STAGE_PROMOTED = "promoted"

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


def increment_safety_blocked(source_product: str = "unknown") -> None:
    """Count a signal rejected by the safety filter — a legitimate terminal exit, not a drop."""
    if not _in_temporal_context():
        return
    get_metric_meter({"source_product": source_product}).create_counter(
        "signals_safety_blocked_total",
        "Signals rejected by the safety filter",
    ).add(1)


def increment_dropped(stage: str, reason: str, count: int = 1) -> None:
    """Count signals lost to an error, attributed to a stage and reason."""
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
    """Count a scout run by terminal status."""
    if not _in_temporal_context():
        return
    get_metric_meter({"status": status}).create_counter(
        "signals_scout_runs_total",
        "Signals scout runs by terminal status",
    ).add(1)
