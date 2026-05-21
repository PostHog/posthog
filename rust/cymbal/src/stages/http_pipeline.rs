use std::sync::Arc;

use moka::future::Cache;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    issue_resolution::Issue,
    metric_consts::HTTP_EXCEPTION_PIPELINE,
    stages::{
        alerting::SpikeAlertAccumulator,
        pipeline::{create_pre_post_processing, ExceptionEventPipeline, HandledError},
    },
    types::{
        batch::Batch,
        event::{AnyEvent, PropertiesContainer},
        exception_properties::ExceptionProperties,
        operator::TeamId,
        stage::{Stage, StageResult},
    },
};

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
        let (preprocess, postprocess) =
            create_pre_post_processing(batch.len(), Box::new(handle_result));

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

fn handle_result(
    mut original: AnyEvent,
    processed: Result<ExceptionProperties, HandledError>,
) -> Result<Option<AnyEvent>, UnhandledError> {
    let item: Option<AnyEvent> = match processed {
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
