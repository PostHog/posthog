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


def increment_recently_seen_lookup(result: str) -> None:
    """Count recently-seen cache lookups by result."""
    if not _in_temporal_context():
        return
    get_metric_meter({"result": result}).create_counter(
        "signals_recently_seen_lookups_total",
        "Recently-seen cache lookups by result",
    ).add(1)


def increment_ch_wait_query(mode: str, reason: str) -> None:
    """Count ClickHouse confirmation queries by wait mode and reason."""
    if not _in_temporal_context():
        return
    get_metric_meter({"mode": mode, "reason": reason}).create_counter(
        "signals_ch_wait_queries_total",
        "ClickHouse confirmation queries issued by signals waits",
    ).add(1)


def increment_ch_wait_completion(mode: str, result: str) -> None:
    """Count wait completions by mode and completion path."""
    if not _in_temporal_context():
        return
    get_metric_meter({"mode": mode, "result": result}).create_counter(
        "signals_ch_wait_completions_total",
        "Signals consistency waits by completion result",
    ).add(1)


def increment_research_run_collapsed() -> None:
    """Count a promotion that folded into an already-running research workflow instead of its own run.

    This is the research-debounce savings metric: with the debounce off it counts the rare race where
    a signal lands mid-run, and with it on it counts every signal that a waiting run absorbed.
    """
    if not _in_temporal_context():
        return
    get_metric_meter().create_counter(
        "signals_research_runs_collapsed_total",
        "Report promotions absorbed by an already-running research workflow",
    ).add(1)


def increment_report_fetch_recovered(attempt: int) -> None:
    """Count a research run whose signals only became readable in ClickHouse on a retried fetch."""
    if not _in_temporal_context():
        return
    get_metric_meter({"attempt": str(attempt)}).create_counter(
        "signals_report_fetch_recovered_total",
        "Report signal fetches that succeeded only after retrying an empty read",
    ).add(1)


def increment_report_run_deferred(reason: str) -> None:
    """Count a research run that exited without researching or failing, leaving the report to re-promote."""
    if not _in_temporal_context():
        return
    get_metric_meter({"reason": reason}).create_counter(
        "signals_report_runs_deferred_total",
        "Report research runs deferred to a later promotion by reason",
    ).add(1)


def increment_scout_run(status: str) -> None:
    """Count a scout run by terminal status."""
    if not _in_temporal_context():
        return
    get_metric_meter({"status": status}).create_counter(
        "signals_scout_runs_total",
        "Signals scout runs by terminal status",
    ).add(1)
