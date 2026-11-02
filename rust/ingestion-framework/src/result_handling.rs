//! Port of `result-handling-pipeline.ts` and `result-handling-helpers.ts`.

use std::sync::Arc;

use async_trait::async_trait;
use futures::FutureExt;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext};
use crate::errors::{join_error, SharedError};
use crate::metrics::INGESTION_PIPELINE_RESULTS_COUNTER;
use crate::outputs::{
    HasMessage, Headers, IngestionOutputs, KafkaMessage, OutputMessage, DLQ_OUTPUT,
};
use crate::results::{NonOk, Outcome};
use crate::side_effects::{SideEffect, SideEffectScheduler};

/// Port of `PipelineConfig`.
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

/// Port of `produceMessageToDLQ`.
pub async fn produce_message_to_dlq(
    outputs: &dyn IngestionOutputs,
    message: &KafkaMessage,
    error: &str,
    step: &str,
    rethrow_on_failure: bool,
) -> anyhow::Result<()> {
    let team_id = message.header("team_id");
    tracing::warn!(step, team_id = ?team_id, error, "Event sent to DLQ");
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
    let result = outputs
        .produce(
            DLQ_OUTPUT,
            OutputMessage {
                value: message.value.clone(),
                key: message.key.clone(),
                headers,
            },
        )
        .await;
    if let Err(dlq_error) = result {
        tracing::error!(step, team_id = ?team_id, error = %dlq_error, "Failed to send event to DLQ");
        if rethrow_on_failure {
            return Err(dlq_error);
        }
    }
    Ok(())
}

/// Port of `redirectMessageToOutput`. The produce is scheduled so the batch drains it. With
/// `await_ack` the returned future also waits for it.
pub async fn redirect_message_to_output(
    outputs: Arc<dyn IngestionOutputs>,
    output: &str,
    scheduler: &dyn SideEffectScheduler,
    message: &KafkaMessage,
    step: &str,
    preserve_key: bool,
    await_ack: bool,
) -> anyhow::Result<()> {
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
    let out = OutputMessage {
        value: message.value.clone(),
        key: if preserve_key {
            message.key.clone()
        } else {
            None
        },
        headers: copy_and_extend_headers(message, extra),
    };
    let output = output.to_string();
    let produce = tokio::spawn(async move { outputs.produce(&output, out).await })
        .map(|joined| match joined {
            Ok(Ok(())) => Ok(()),
            Ok(Err(error)) => Err(SharedError(Arc::new(error))),
            Err(error) => Err(SharedError(Arc::new(join_error(error)))),
        })
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
                Outcome::NonOk(non_ok) => non_ok.clone(),
            };
            let (result_label, details) = result_details(&non_ok);
            metrics::counter!(
                INGESTION_PIPELINE_RESULTS_COUNTER,
                "result" => result_label,
                "last_step_name" => step.clone(),
                "details" => details
            )
            .increment(1);

            let message = item.context.data.message().clone();
            match non_ok {
                NonOk::Dlq { reason, error } => {
                    let error_text = error.map(|e| e.to_string()).unwrap_or(reason);
                    let outputs = self.config.outputs.clone();
                    let rethrow = self.config.reject_on_dlq_failure;
                    item.context
                        .side_effects
                        .push(SideEffect::spawn(async move {
                            produce_message_to_dlq(
                                outputs.as_ref(),
                                &message,
                                &error_text,
                                &step,
                                rethrow,
                            )
                            .await
                        }));
                }
                NonOk::Drop { reason } => {
                    tracing::debug!(step = %step, reason, team_id = ?message.header("team_id"), "Event dropped");
                }
                NonOk::Redirect {
                    output,
                    preserve_key,
                    await_ack,
                    ..
                } => {
                    let outputs = self.config.outputs.clone();
                    let scheduler = self.config.scheduler.clone();
                    item.context
                        .side_effects
                        .push(SideEffect::spawn(async move {
                            redirect_message_to_output(
                                outputs,
                                &output,
                                scheduler.as_ref(),
                                &message,
                                &step,
                                preserve_key,
                                await_ack,
                            )
                            .await
                        }));
                }
                NonOk::Timeout { .. } => {}
            }
        }
        Ok(Some(results))
    }
}
