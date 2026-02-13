from products.signals.backend.temporal.grouping import (
    EmitSignalWorkflow,
    assign_signal_to_report_activity,
    emit_to_clickhouse_activity,
    fetch_signal_type_examples_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    llm_match_signal_activity,
    run_signal_semantic_search_activity,
)
from products.signals.backend.temporal.summary import (
    SignalReportSummaryWorkflow,
    fetch_signals_for_report_activity,
    mark_report_failed_activity,
    mark_report_in_progress_activity,
    mark_report_ready_activity,
    summarize_signals_activity,
)

WORKFLOWS = [
    EmitSignalWorkflow,
    SignalReportSummaryWorkflow,
]

ACTIVITIES = [
    assign_signal_to_report_activity,
    emit_to_clickhouse_activity,
    fetch_signal_type_examples_activity,
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
