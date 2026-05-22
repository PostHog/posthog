use std::sync::Arc;

use moka::future::Cache;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    issue_resolution::Issue,
    metric_consts::HTTP_EXCEPTION_PIPELINE,
    stages::{
        alerting::AlertingStage,
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
/// map the handled error directly into a routing decision (`/v2/resolve`).
pub struct HttpResolveResult {
    pub original_event: AnyEvent,
    pub result: Result<ExceptionProperties, EventError>,
}

pub struct HttpResolvePipeline {
    app_context: Arc<AppContext>,
    batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
}

impl HttpResolvePipeline {
    pub fn new(
        app_context: Arc<AppContext>,
        batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
    ) -> Self {
        Self {
            app_context,
            batch_issue_cache,
        }
    }
}

impl Stage for HttpResolvePipeline {
    type Input = AnyEvent;
    type Output = HttpResolveResult;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let (preprocess, postprocess) =
            create_pre_post_processing(batch.len(), Box::new(preserve_result));

        let exception_pipeline =
            ExceptionEventPipeline::new(self.app_context.clone(), self.batch_issue_cache);

        batch
            .apply_stage(preprocess)
            .await?
            .apply_stage(exception_pipeline)
            .await?
            .apply_stage(postprocess)
            .await
    }
}

pub struct HttpProcessPipeline {
    app_context: Arc<AppContext>,
}

impl HttpProcessPipeline {
    pub fn new(app_context: Arc<AppContext>) -> Self {
        Self { app_context }
    }
}

impl Stage for HttpProcessPipeline {
    type Input = AnyEvent;
    type Output = Option<AnyEvent>;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let (preprocess, postprocess) =
            create_pre_post_processing(batch.len(), Box::new(preserve_result));
        let exception_pipeline = ExceptionEventPipeline::new(self.app_context.clone(), None);

        let processed = batch
            .apply_stage(preprocess)
            .await?
            .apply_stage(exception_pipeline)
            .await?
            .apply_stage(AlertingStage::new(self.app_context))
            .await?
            .apply_stage(postprocess)
            .await?;
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
) -> Result<HttpResolveResult, UnhandledError> {
    Ok(HttpResolveResult {
        original_event: original,
        result: processed,
    })
}

fn handle_legacy_result(result: HttpResolveResult) -> Result<Option<AnyEvent>, UnhandledError> {
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
