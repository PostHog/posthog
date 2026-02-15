from products.signals.backend.temporal.activities import (
    assign_signal_to_report_activity,
    emit_to_clickhouse_activity,
    fetch_signals_for_report_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    llm_match_signal_activity,
    mark_report_failed_activity,
    mark_report_in_progress_activity,
    mark_report_ready_activity,
    run_signal_semantic_search_activity,
    summarize_signals_activity,
)
from products.signals.backend.temporal.workflow import EmitSignalWorkflow, SignalResearchWorkflow

WORKFLOWS = [
    EmitSignalWorkflow,
    SignalResearchWorkflow,
]

ACTIVITIES = [
    assign_signal_to_report_activity,
    emit_to_clickhouse_activity,
    fetch_signals_for_report_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    llm_match_signal_activity,
    mark_report_failed_activity,
    mark_report_in_progress_activity,
    mark_report_ready_activity,
    run_signal_semantic_search_activity,
    summarize_signals_activity,
]
