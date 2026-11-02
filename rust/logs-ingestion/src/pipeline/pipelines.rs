//! Port of `pipeline/logs-pipelines.ts`. Every pipeline is built once per batch: background
//! passes of consecutive batches overlap, and a chunk pipeline must not have concurrent callers.

use std::sync::Arc;

use ingestion_framework::{
    create_ok_context, new_chunk_pipeline, ok, per_element, ChunkProcessingStep, DynChunkPipeline,
    KafkaMessage,
};

use super::admission::{
    create_backfill_gate_step, create_quota_limit_step, create_rate_limit_step,
    create_record_allowed_usage_step, create_track_incoming_traffic_step, LogsAdmissionInput,
};
use super::context::LogsPipelineContext;
use super::parse::{create_settled_parse_step, ParseOutcome};
use super::process::{create_process_log_message_step, LogsProcessingInput, LogsProcessingOutcome};
use super::types::LogsIngestionMessage;

pub const MAX_CONCURRENT_MESSAGE_PROCESSES: usize = 50;

fn create_fail_parse_on_error_step() -> ChunkProcessingStep<ParseOutcome, LogsIngestionMessage> {
    ChunkProcessingStep::sync("failParseOnErrorStep", |values: Vec<ParseOutcome>| {
        let mut parsed = Vec::with_capacity(values.len());
        for value in values {
            if let Some(failure) = value.failure {
                return Err(failure);
            }
            parsed.push(ok(value
                .parsed
                .expect("an outcome without a failure holds a message")));
        }
        Ok(parsed)
    })
}

pub fn create_logs_parse_pipeline(
    context: Arc<LogsPipelineContext>,
) -> DynChunkPipeline<Arc<KafkaMessage>, LogsIngestionMessage, (), ()> {
    new_chunk_pipeline::<Arc<KafkaMessage>, ()>()
        .pipe_chunk(per_element(create_settled_parse_step(context), None))
        .pipe_chunk(create_fail_parse_on_error_step())
        .build()
}

/// The gates, in the order billing depends on.
pub fn create_logs_admission_pipeline(
    context: Arc<LogsPipelineContext>,
) -> DynChunkPipeline<LogsAdmissionInput, LogsAdmissionInput, (), ()> {
    new_chunk_pipeline::<LogsAdmissionInput, ()>()
        .pipe_chunk(create_track_incoming_traffic_step())
        .pipe_chunk(create_backfill_gate_step(context.clone()))
        .pipe_chunk(create_quota_limit_step(context.clone()))
        .pipe_chunk(create_rate_limit_step(context))
        .pipe_chunk(create_record_allowed_usage_step())
        .build()
}

fn create_fail_pass_on_error_step(
) -> ChunkProcessingStep<LogsProcessingOutcome, LogsProcessingOutcome> {
    ChunkProcessingStep::sync(
        "failPassOnErrorStep",
        |mut values: Vec<LogsProcessingOutcome>| {
            let failures = values.iter().filter(|v| v.failure.is_some()).count();
            let quarantined = values.iter().filter(|v| v.quarantined).count();
            if failures > 0 || quarantined > 0 {
                tracing::error!(
                    quarantined,
                    failures,
                    total = values.len(),
                    "Failed to process some log messages"
                );
            }
            if let Some(i) = values.iter().position(|v| v.failure.is_some()) {
                return Err(values.swap_remove(i).failure.unwrap());
            }
            Ok(values.into_iter().map(ok).collect())
        },
    )
}

pub fn create_logs_processing_pipeline(
    context: Arc<LogsPipelineContext>,
) -> DynChunkPipeline<LogsProcessingInput, LogsProcessingOutcome, (), ()> {
    new_chunk_pipeline::<LogsProcessingInput, ()>()
        .pipe_chunk(per_element(
            create_process_log_message_step(context),
            Some(MAX_CONCURRENT_MESSAGE_PROCESSES),
        ))
        .pipe_chunk(create_fail_pass_on_error_step())
        .build()
}

pub async fn run_chunk_pipeline<I: Send + 'static, O: Send + 'static>(
    pipeline: DynChunkPipeline<I, O, (), ()>,
    values: Vec<I>,
) -> anyhow::Result<Vec<O>> {
    if values.is_empty() {
        return Ok(Vec::new());
    }
    pipeline.feed(
        values
            .into_iter()
            .map(|v| create_ok_context(v, ()))
            .collect(),
    );
    let mut out = Vec::new();
    while let Some(chunk) = pipeline.next().await? {
        out.extend(chunk.into_iter().filter_map(|r| r.result.into_value()));
    }
    Ok(out)
}
