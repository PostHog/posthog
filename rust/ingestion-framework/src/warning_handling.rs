use std::collections::HashMap;
use std::sync::{Arc, OnceLock};

use async_trait::async_trait;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext, PipelineWarning};
use crate::js_json;
use crate::metrics::INGESTION_WARNING_COUNTER;
use crate::outputs::{HasTeamId, IngestionOutputs, OutputMessage, INGESTION_WARNINGS_OUTPUT};
use crate::results::{NonOk, Outcome};
use crate::side_effects::SideEffect;

/// Node logs a failed produce and does not reject, so that is `Ok(false)`. `Err` fails the side effect, as Node's emit rejects.
#[async_trait]
pub trait IngestionWarningEmitter: Send + Sync {
    async fn emit(&self, team_id: i64, warning: PipelineWarning) -> anyhow::Result<bool>;
}

pub struct OutputsWarningEmitter {
    pub outputs: Arc<dyn IngestionOutputs>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WarningClassification {
    pub category: &'static str,
    pub severity: &'static str,
}

// The Node registry exports this file, and a Node test fails when the two differ.
const WARNING_TYPES_JSON: &str =
    include_str!("../../common/ingestion_warnings/warning_types.generated.json");

pub fn warning_classification(warning_type: &str) -> Option<WarningClassification> {
    #[derive(serde::Deserialize)]
    struct Entry<'a> {
        #[serde(rename = "type")]
        warning_type: &'a str,
        category: &'a str,
        severity: &'a str,
    }
    #[derive(serde::Deserialize)]
    struct Registry<'a> {
        #[serde(borrow)]
        types: Vec<Entry<'a>>,
    }
    static REGISTRY: OnceLock<HashMap<&'static str, WarningClassification>> = OnceLock::new();
    REGISTRY
        .get_or_init(|| {
            let registry: Registry<'static> =
                serde_json::from_str(WARNING_TYPES_JSON).expect("valid warning types JSON");
            registry
                .types
                .into_iter()
                .map(|entry| {
                    let classification = WarningClassification {
                        category: entry.category,
                        severity: entry.severity,
                    };
                    (entry.warning_type, classification)
                })
                .collect()
        })
        .get(warning_type)
        .copied()
}

/// Byte for byte as Node. A key the caller already set keeps its place and takes the new value, as in an object spread.
pub fn serialize_ingestion_warning(
    team_id: i64,
    warning: &PipelineWarning,
) -> anyhow::Result<String> {
    let Some(classification) = warning_classification(&warning.warning_type) else {
        anyhow::bail!(
            "ingestion warning type {:?} is not in INGESTION_WARNING_TYPES",
            warning.warning_type
        );
    };
    let mut details = warning.details.clone();
    details.insert("category".into(), classification.category.into());
    details.insert("severity".into(), classification.severity.into());
    if let Some(step) = warning.pipeline_step.as_deref().filter(|s| !s.is_empty()) {
        details.insert("pipelineStep".into(), step.into());
    }
    let mut details_json = String::new();
    js_json::write_object(&mut details_json, details.iter());

    let mut out = String::with_capacity(details_json.len() + 128);
    out.push_str("{\"team_id\":");
    js_json::write_number(&mut out, team_id as f64);
    out.push_str(",\"type\":");
    js_json::write_string(&mut out, &warning.warning_type);
    out.push_str(",\"source\":");
    js_json::write_string(
        &mut out,
        warning.source.as_deref().unwrap_or("plugin-server"),
    );
    out.push_str(",\"details\":");
    js_json::write_string(&mut out, &details_json);
    out.push_str(",\"timestamp\":");
    js_json::write_string(
        &mut out,
        &chrono::Utc::now()
            .format("%Y-%m-%d %H:%M:%S%.3f")
            .to_string(),
    );
    out.push('}');
    Ok(out)
}

#[async_trait]
impl IngestionWarningEmitter for OutputsWarningEmitter {
    async fn emit(&self, team_id: i64, warning: PipelineWarning) -> anyhow::Result<bool> {
        metrics::counter!(INGESTION_WARNING_COUNTER, "type" => warning.warning_type.clone(), "emitted" => "true")
            .increment(1);
        let value = serialize_ingestion_warning(team_id, &warning)?.into_bytes();
        match self
            .outputs
            .queue_messages(
                INGESTION_WARNINGS_OUTPUT,
                vec![OutputMessage {
                    value: Some(value.into()),
                    ..Default::default()
                }],
            )
            .await
        {
            Ok(()) => Ok(true),
            Err(error) => {
                tracing::warn!(team_id, error = %error, "Failed to produce ingestion warning");
                Ok(false)
            }
        }
    }
}

/// A timed-out result drops its warnings, because the redelivery emits them again.
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
                // The emit starts on creation, so warnings are queued in item order.
                item.context
                    .side_effects
                    .push(SideEffect::spawn(async move {
                        emitter.emit(team_id, warning).await.map(|_| ())
                    }));
            }
        }
        Ok(Some(results))
    }
}
