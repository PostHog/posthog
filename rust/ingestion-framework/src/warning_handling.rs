//! Port of `ingestion-warning-handling-chunk-pipeline.ts` and the emit half of
//! `~/ingestion/common/ingestion-warnings.ts`.

use std::sync::Arc;

use async_trait::async_trait;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext, PipelineWarning};
use crate::metrics::INGESTION_WARNING_COUNTER;
use crate::outputs::{HasTeamId, IngestionOutputs, OutputMessage, INGESTION_WARNINGS_OUTPUT};
use crate::results::{NonOk, Outcome};
use crate::side_effects::SideEffect;

/// Decides whether to emit a warning and sends it. Node rate-limits per
/// `team:type:key` with `IngestionWarningLimiter`; that limiter is an app concern, so it
/// sits behind this trait.
#[async_trait]
pub trait IngestionWarningEmitter: Send + Sync {
    async fn emit(&self, team_id: i64, warning: PipelineWarning) -> bool;
}

/// Serializes as Node's `serializeIngestionWarning` does, with no rate limit.
pub struct OutputsWarningEmitter {
    pub outputs: Arc<dyn IngestionOutputs>,
}

/// Port of `serializeIngestionWarning`. The category and severity come from the Node
/// registry, so the caller passes them in `details` if it needs them.
pub fn serialize_ingestion_warning(team_id: i64, warning: &PipelineWarning) -> String {
    let mut details = warning.details.clone();
    if let Some(step) = &warning.pipeline_step {
        details.insert(
            "pipelineStep".into(),
            serde_json::Value::String(step.clone()),
        );
    }
    serde_json::json!({
        "team_id": team_id,
        "type": warning.warning_type,
        "source": warning.source.clone().unwrap_or_else(|| "plugin-server".into()),
        "details": serde_json::Value::Object(details).to_string(),
        "timestamp": chrono::Utc::now().format("%Y-%m-%d %H:%M:%S%.3f").to_string(),
    })
    .to_string()
}

#[async_trait]
impl IngestionWarningEmitter for OutputsWarningEmitter {
    async fn emit(&self, team_id: i64, warning: PipelineWarning) -> bool {
        metrics::counter!(INGESTION_WARNING_COUNTER, "type" => warning.warning_type.clone(), "emitted" => "true")
            .increment(1);
        let value = serialize_ingestion_warning(team_id, &warning).into_bytes();
        match self
            .outputs
            .queue_messages(
                INGESTION_WARNINGS_OUTPUT,
                vec![OutputMessage {
                    value: Some(value),
                    ..Default::default()
                }],
            )
            .await
        {
            Ok(()) => true,
            Err(error) => {
                tracing::warn!(team_id, error = %error, "Failed to produce ingestion warning");
                false
            }
        }
    }
}

/// Turns the warnings each result carries into side effects. A timed-out result drops its
/// warnings, because the redelivery emits them again.
pub struct IngestionWarningHandlingChunkPipeline<I, O, CI, CO> {
    emitter: Arc<dyn IngestionWarningEmitter>,
    previous: DynChunkPipeline<I, O, CI, CO>,
}

impl<I, O, CI, CO> IngestionWarningHandlingChunkPipeline<I, O, CI, CO> {
    pub fn new(
        emitter: Arc<dyn IngestionWarningEmitter>,
        previous: DynChunkPipeline<I, O, CI, CO>,
    ) -> Self {
        Self { emitter, previous }
    }
}

#[async_trait]
impl<I, O, CI, CO> ChunkPipeline<I, O, CI, CO>
    for IngestionWarningHandlingChunkPipeline<I, O, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: HasTeamId + Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.previous.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        let Some(mut results) = self.previous.next().await? else {
            return Ok(None);
        };
        for item in results.iter_mut() {
            if item.context.warnings.is_empty() {
                continue;
            }
            let warnings = std::mem::take(&mut item.context.warnings);
            if matches!(item.result, Outcome::NonOk(NonOk::Timeout { .. })) {
                continue;
            }
            let team_id = item.context.data.team_id();
            for warning in warnings {
                let emitter = self.emitter.clone();
                item.context
                    .side_effects
                    .push(SideEffect::spawn(async move {
                        emitter.emit(team_id, warning).await;
                        Ok(())
                    }));
            }
        }
        Ok(Some(results))
    }
}
