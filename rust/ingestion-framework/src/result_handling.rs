//! Port of `result-handling-pipeline.ts` and `result-handling-helpers.ts`.

use std::sync::Arc;

use async_trait::async_trait;
use futures::FutureExt;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext};
use crate::errors::SharedError;
use crate::metrics::INGESTION_PIPELINE_RESULTS_COUNTER;
use crate::outputs::{
    HasMessage, Headers, IngestionOutputs, KafkaMessage, OutputMessage, DLQ_OUTPUT,
};
use crate::results::{NonOk, Outcome};
use crate::side_effects::{SideEffect, SideEffectScheduler};

#[derive(Clone)]
pub struct PipelineConfig {
    pub outputs: Arc<dyn IngestionOutputs>,
    pub scheduler: Arc<dyn SideEffectScheduler>,
    /// Fail the side effect when the DLQ produce fails. Set it only when the consumer stores
    /// no offsets after a failed side effect.
    pub reject_on_dlq_failure: bool,
}

fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

/// Port of `copyAndExtendHeaders`. A Node header value that is not a buffer or a string is
/// stringified, so a null value becomes `"null"`.
pub fn copy_and_extend_headers(message: &KafkaMessage, additional: Headers) -> Headers {
    let mut headers = Headers::new();
    for (key, value) in &message.headers {
        let value = match value {
            Some(bytes) => String::from_utf8_lossy(bytes).into_owned(),
            None => "null".to_string(),
        };
        headers.set(key.clone(), value);
    }
    for (key, value) in additional.0 {
        headers.set(key, value);
    }
    headers
}

pub fn dlq_output_message(message: &KafkaMessage, error: &str, step: &str) -> OutputMessage {
    let headers = copy_and_extend_headers(
        message,
        [
            ("dlq_reason", error.to_string()),
            ("dlq_step", step.to_string()),
            ("dlq_timestamp", now_iso()),
            ("dlq_topic", message.topic.clone()),
            ("dlq_partition", message.partition.to_string()),
            ("dlq_offset", message.offset.to_string()),
        ]
        .into_iter()
        .collect(),
    );
    OutputMessage {
        value: message.value.clone(),
        key: message.key.clone(),
        headers,
    }
}

async fn produce_dlq_message(
    outputs: &dyn IngestionOutputs,
    out: OutputMessage,
    team_id: Option<String>,
    step: &str,
    rethrow_on_failure: bool,
) -> anyhow::Result<()> {
    if let Err(dlq_error) = outputs.produce(DLQ_OUTPUT, out).await {
        tracing::error!(step, team_id = ?team_id, error = %dlq_error, "Failed to send event to DLQ");
        if rethrow_on_failure {
            return Err(dlq_error);
        }
    }
    Ok(())
}

pub async fn produce_message_to_dlq(
    outputs: &dyn IngestionOutputs,
    message: &KafkaMessage,
    error: &str,
    step: &str,
    rethrow_on_failure: bool,
) -> anyhow::Result<()> {
    let team_id = message.header("team_id");
    tracing::warn!(step, team_id = ?team_id, error, "Event sent to DLQ");
    let out = dlq_output_message(message, error, step);
    produce_dlq_message(outputs, out, team_id, step, rethrow_on_failure).await
}

pub fn redirect_output_message(
    message: &KafkaMessage,
    step: &str,
    preserve_key: bool,
) -> OutputMessage {
    let mut extra = Headers::new();
    extra.set("redirect-step", step);
    extra.set("redirect-timestamp", now_iso());
    // Dropping the key spreads the redirected stream across partitions; keep the original
    // key recoverable for consumers of the stream.
    if !preserve_key {
        if let Some(key) = &message.key {
            extra.set(
                "redirect-original-key",
                String::from_utf8_lossy(key).into_owned(),
            );
        }
    }
    OutputMessage {
        value: message.value.clone(),
        key: if preserve_key {
            message.key.clone()
        } else {
            None
        },
        headers: copy_and_extend_headers(message, extra),
    }
}

async fn produce_redirect(
    outputs: Arc<dyn IngestionOutputs>,
    output: String,
    scheduler: &dyn SideEffectScheduler,
    out: OutputMessage,
    await_ack: bool,
) -> anyhow::Result<()> {
    // The produce starts here, before the scheduler sees it, as Node calls
    // `outputs.produce` before it schedules the promise.
    let produce = async move { outputs.produce(&output, out).await }
        .map(|result| result.map_err(|error| SharedError(Arc::new(error))))
        .boxed()
        .shared();
    let scheduled = produce.clone();
    scheduler.schedule(SideEffect::spawn(async move {
        scheduled.await.map_err(anyhow::Error::new)
    }));
    if await_ack {
        produce.await.map_err(anyhow::Error::new)?;
    }
    Ok(())
}

pub async fn redirect_message_to_output(
    outputs: Arc<dyn IngestionOutputs>,
    output: &str,
    scheduler: &dyn SideEffectScheduler,
    message: &KafkaMessage,
    step: &str,
    preserve_key: bool,
    await_ack: bool,
) -> anyhow::Result<()> {
    let out = redirect_output_message(message, step, preserve_key);
    produce_redirect(outputs, output.to_string(), scheduler, out, await_ack).await
}

fn result_details(result: &NonOk) -> (&'static str, String) {
    match result {
        NonOk::Drop { reason } => ("drop", reason.clone()),
        NonOk::Dlq { reason, .. } => ("dlq", reason.clone()),
        NonOk::Redirect {
            output,
            preserve_key,
            ..
        } => ("redirect", format!("{output}(preserve_key={preserve_key})")),
        NonOk::Timeout { reason } => ("timeout", reason.clone()),
    }
}

/// Wraps a chunk pipeline and turns each non-OK result into its side effect: a DLQ produce,
/// a drop log, or a redirect produce. A timeout produces nothing, because the redelivery
/// produces it.
pub struct ResultHandlingPipeline<I, O, CI, CO> {
    pipeline: DynChunkPipeline<I, O, CI, CO>,
    config: PipelineConfig,
}

impl<I, O, CI, CO> ResultHandlingPipeline<I, O, CI, CO> {
    pub fn new(pipeline: DynChunkPipeline<I, O, CI, CO>, config: PipelineConfig) -> Self {
        Self { pipeline, config }
    }
}

#[async_trait]
impl<I, O, CI, CO> ChunkPipeline<I, O, CI, CO> for ResultHandlingPipeline<I, O, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: HasMessage + Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.pipeline.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        let Some(mut results) = self.pipeline.next().await? else {
            return Ok(None);
        };
        for item in results.iter_mut() {
            let step: Arc<str> = item
                .context
                .last_step
                .clone()
                .unwrap_or_else(|| Arc::from("unknown"));
            let non_ok = match &item.result {
                Outcome::Ok(_) => {
                    metrics::counter!(
                        INGESTION_PIPELINE_RESULTS_COUNTER,
                        "result" => "ok",
                        "last_step_name" => step,
                        "details" => ""
                    )
                    .increment(1);
                    continue;
                }
                Outcome::NonOk(non_ok) => non_ok,
            };
            let (result_label, details) = result_details(non_ok);
            metrics::counter!(
                INGESTION_PIPELINE_RESULTS_COUNTER,
                "result" => result_label,
                "last_step_name" => step.clone(),
                "details" => details
            )
            .increment(1);

            // Each side effect starts its produce on creation, so produces are issued in
            // item order, as Node issues them inside this loop.
            let side_effect = match non_ok {
                NonOk::Dlq { reason, error } => {
                    let error_text = match error {
                        Some(error) => error.to_string(),
                        None => reason.clone(),
                    };
                    let message = item.context.data.message();
                    let team_id = message.header("team_id");
                    tracing::warn!(step = %step, team_id = ?team_id, error = %error_text, "Event sent to DLQ");
                    let out = dlq_output_message(message, &error_text, &step);
                    let outputs = self.config.outputs.clone();
                    let rethrow = self.config.reject_on_dlq_failure;
                    SideEffect::spawn(async move {
                        produce_dlq_message(outputs.as_ref(), out, team_id, &step, rethrow).await
                    })
                }
                NonOk::Drop { reason } => {
                    let message = item.context.data.message();
                    tracing::debug!(step = %step, reason, team_id = ?message.header("team_id"), "Event dropped");
                    continue;
                }
                NonOk::Redirect {
                    output,
                    preserve_key,
                    await_ack,
                    ..
                } => {
                    let out =
                        redirect_output_message(item.context.data.message(), &step, *preserve_key);
                    let output = output.clone();
                    let await_ack = *await_ack;
                    let outputs = self.config.outputs.clone();
                    let scheduler = self.config.scheduler.clone();
                    SideEffect::spawn(async move {
                        produce_redirect(outputs, output, scheduler.as_ref(), out, await_ack).await
                    })
                }
                NonOk::Timeout { .. } => continue,
            };
            item.context.side_effects.push(side_effect);
        }
        Ok(Some(results))
    }
}
