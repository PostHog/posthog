use std::sync::Arc;

use moka::future::Cache;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    issue_resolution::Issue,
    metric_consts::HTTP_EXCEPTION_PIPELINE,
    stages::{
        alerting::SpikeAlertAccumulator,
        pipeline::{create_pre_post_processing, ExceptionEventPipeline},
    },
    types::{
        batch::Batch,
        event::{AnyEvent, PropertiesContainer},
        exception_properties::ExceptionProperties,
        operator::TeamId,
        stage::{Stage, StageResult},
    },
};

/// Raw per-event result from Cymbal's HTTP processing pipeline, before any
/// endpoint-specific response adaptation. The original event is kept alongside
/// the processing result so callers can either enrich it (legacy `/process`) or
/// map the handled error directly into a routing decision (`/v2/process`).
pub struct HttpEventProcessingResult {
    pub original_event: AnyEvent,
    pub result: Result<ExceptionProperties, EventError>,
}

pub struct HttpEventProcessingPipeline {
    app_context: Arc<AppContext>,
    batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
    spike_alert_accumulator: Option<Arc<SpikeAlertAccumulator>>,
}

impl HttpEventProcessingPipeline {
    pub fn new(
        app_context: Arc<AppContext>,
        batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
        spike_alert_accumulator: Option<Arc<SpikeAlertAccumulator>>,
    ) -> Self {
        Self {
            app_context,
            batch_issue_cache,
            spike_alert_accumulator,
        }
    }
}

impl Stage for HttpEventProcessingPipeline {
    type Input = AnyEvent;
    type Output = HttpEventProcessingResult;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let (preprocess, postprocess) =
            create_pre_post_processing(batch.len(), Box::new(preserve_result));

        let exception_pipeline = ExceptionEventPipeline::new(
            self.app_context.clone(),
            self.batch_issue_cache,
            self.spike_alert_accumulator,
        );

        batch
            .apply_stage(preprocess)
            .await?
            .apply_stage(exception_pipeline)
            .await?
            .apply_stage(postprocess)
            .await
    }
}

pub struct HttpEventPipeline {
    app_context: Arc<AppContext>,
    /// Optional shared per-batch issue cache, threaded down to `LinkingStage`.
    /// `/v2/process` creates one cache per request and supplies it on every
    /// per-event invocation so they share fingerprint -> Issue dedup across
    /// the request. `None` for the legacy `/process` flow (linking stage
    /// allocates a fresh cache).
    batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
    /// Optional accumulator for deferring spike-alert work. `/v2/process`
    /// creates one accumulator per request, threads it through every
    /// per-event invocation, and runs spike detection once at end-of-request
    /// with the merged inputs. `None` for the legacy `/process` flow
    /// (alerting stage calls Redis inline).
    spike_alert_accumulator: Option<Arc<SpikeAlertAccumulator>>,
}

impl HttpEventPipeline {
    pub fn new(
        app_context: Arc<AppContext>,
        batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
        spike_alert_accumulator: Option<Arc<SpikeAlertAccumulator>>,
    ) -> Self {
        Self {
            app_context,
            batch_issue_cache,
            spike_alert_accumulator,
        }
    }
}

impl Stage for HttpEventPipeline {
    type Input = AnyEvent;
    type Output = Option<AnyEvent>;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let processing_pipeline = HttpEventProcessingPipeline::new(
            self.app_context,
            self.batch_issue_cache,
            self.spike_alert_accumulator,
        );

        let processed = processing_pipeline.process(batch).await?;
        let events = processed
            .into_iter()
            .map(handle_legacy_result)
            .collect::<Result<Vec<_>, UnhandledError>>()?;
        Ok(Batch::from(events))
    }
}

fn preserve_result(
    original: AnyEvent,
    processed: Result<ExceptionProperties, EventError>,
) -> Result<HttpEventProcessingResult, UnhandledError> {
    Ok(HttpEventProcessingResult {
        original_event: original,
        result: processed,
    })
}

fn handle_legacy_result(
    result: HttpEventProcessingResult,
) -> Result<Option<AnyEvent>, UnhandledError> {
    let mut original = result.original_event;
    let item: Option<AnyEvent> = match result.result {
        Ok(props) => {
            original.set_properties(props)?;
            Some(original)
        }
        Err(err) => match err {
            EventError::Suppressed(_) | EventError::SuppressedByRule(_) => None,
            err => {
                original.attach_error(err.to_string())?;
                Some(original)
            }
        },
    };
    Ok(item)
}
