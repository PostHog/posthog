from products.signals.backend.temporal.agentic.report import run_agentic_report_activity
from products.signals.backend.temporal.agentic.select_repository import select_repository_activity
from products.signals.backend.temporal.backfill_error_tracking import (
    BackfillErrorTrackingWorkflow,
    emit_backfill_signal_activity,
    fetch_error_tracking_issues_activity,
)
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
    generate_search_queries_activity,
    get_embedding_activity,
    match_signal_to_report_activity,
    verify_match_specificity_activity,
)
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow, read_signals_from_s3_activity
from products.signals.backend.temporal.reingestion import (
    SignalReportReingestionWorkflow,
    TeamSignalReingestionWorkflow,
    delete_report_activity,
    delete_team_reports_activity,
    get_grouping_paused_state_activity,
    pause_grouping_until_activity,
    process_team_signals_batch_activity,
    reingest_signals_activity,
    restore_grouping_pause_activity,
    soft_delete_report_signals_activity,
)
from products.signals.backend.temporal.report_safety_judge import report_safety_judge_activity
from products.signals.backend.temporal.safety_filter import safety_filter_activity
from products.signals.backend.temporal.signal_queries import (
    fetch_signal_type_examples_activity,
    fetch_signals_for_report_activity,
    run_signal_semantic_search_activity,
    wait_for_signal_in_clickhouse_activity,
)
from products.signals.backend.temporal.summary import (
    SignalReportSummaryWorkflow,
    mark_report_failed_activity,
    mark_report_in_progress_activity,
    mark_report_pending_input_activity,
    mark_report_ready_activity,
    publish_report_completed_activity,
    reset_report_to_potential_activity,
)

WORKFLOWS = [
    BackfillErrorTrackingWorkflow,
    TeamSignalGroupingWorkflow,
    TeamSignalGroupingV2Workflow,
    BufferSignalsWorkflow,
    SignalEmitterWorkflow,
    SignalReportSummaryWorkflow,
    SignalReportReingestionWorkflow,
    TeamSignalReingestionWorkflow,
    SignalReportDeletionWorkflow,
    EmitEvalSignalWorkflow,
]

ACTIVITIES = [
    emit_backfill_signal_activity,
    fetch_error_tracking_issues_activity,
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
    publish_report_completed_activity,
    delete_team_reports_activity,
    get_grouping_paused_state_activity,
    pause_grouping_until_activity,
    process_team_signals_batch_activity,
    reingest_signals_activity,
    reset_report_to_potential_activity,
    restore_grouping_pause_activity,
    run_agentic_report_activity,
    run_signal_semantic_search_activity,
    report_safety_judge_activity,
    safety_filter_activity,
    select_repository_activity,
    soft_delete_report_signals_activity,
    verify_match_specificity_activity,
    wait_for_signal_in_clickhouse_activity,
]
