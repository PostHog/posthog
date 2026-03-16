from products.signals.backend.temporal.actionability_judge import actionability_judge_activity
from products.signals.backend.temporal.buffer import (
    BufferSignalsWorkflow,
    flush_signals_to_s3_activity,
    signal_with_start_grouping_v2_activity,
    submit_signal_to_buffer_activity,
)
from products.signals.backend.temporal.deletion import SignalReportDeletionWorkflow
from products.signals.backend.temporal.emit_eval_signal import EmitEvalSignalWorkflow, emit_eval_signal_activity
from products.signals.backend.temporal.emitter import SignalEmitterWorkflow
from products.signals.backend.temporal.grouping import (
    TeamSignalGroupingWorkflow,
    assign_and_emit_signal_activity,
    fetch_report_contexts_activity,
    fetch_signal_type_examples_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    match_signal_to_report_activity,
    run_signal_semantic_search_activity,
    verify_match_specificity_activity,
    wait_for_signal_in_clickhouse_activity,
)
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow, read_signals_from_s3_activity
from products.signals.backend.temporal.reingestion import (
    SignalReportReingestionWorkflow,
    delete_report_activity,
    reingest_signals_activity,
    soft_delete_report_signals_activity,
)
from products.signals.backend.temporal.safety_judge import safety_judge_activity
from products.signals.backend.temporal.summarize_signals import summarize_signals_activity
from products.signals.backend.temporal.summary import (
    SignalReportSummaryWorkflow,
    fetch_signals_for_report_activity,
    mark_report_failed_activity,
    mark_report_in_progress_activity,
    mark_report_pending_input_activity,
    mark_report_ready_activity,
    reset_report_to_potential_activity,
)

WORKFLOWS = [
    TeamSignalGroupingWorkflow,
    TeamSignalGroupingV2Workflow,
    BufferSignalsWorkflow,
    SignalEmitterWorkflow,
    SignalReportSummaryWorkflow,
    SignalReportReingestionWorkflow,
    SignalReportDeletionWorkflow,
    EmitEvalSignalWorkflow,
]

ACTIVITIES = [
    actionability_judge_activity,
    assign_and_emit_signal_activity,
    delete_report_activity,
    emit_eval_signal_activity,
    fetch_report_contexts_activity,
    flush_signals_to_s3_activity,
    signal_with_start_grouping_v2_activity,
    submit_signal_to_buffer_activity,
    fetch_signal_type_examples_activity,
    fetch_signals_for_report_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    match_signal_to_report_activity,
    mark_report_failed_activity,
    read_signals_from_s3_activity,
    mark_report_in_progress_activity,
    mark_report_pending_input_activity,
    mark_report_ready_activity,
    reingest_signals_activity,
    reset_report_to_potential_activity,
    run_signal_semantic_search_activity,
    safety_judge_activity,
    soft_delete_report_signals_activity,
    verify_match_specificity_activity,
    wait_for_signal_in_clickhouse_activity,
    summarize_signals_activity,
]
