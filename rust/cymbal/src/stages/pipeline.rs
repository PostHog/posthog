use std::{
    collections::HashMap,
    fmt::{Debug, Display},
    sync::Arc,
};

use common_types::ClickHouseEvent;
use thiserror::Error;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    metric_consts::EXCEPTION_PROCESSING_PIPELINE,
    stages::{
        alerting::AlertingStage, grouping::GroupingStage, linking::LinkingStage,
        post_processing::PostProcessingStage, pre_processing::PreProcessingStage,
        resolution::ResolutionStage,
    },
    types::{
        batch::Batch, event::AnyEvent, exception_properties::ExceptionProperties, stage::Stage,
    },
};

pub struct ExceptionEventPipeline {
    app_context: Arc<AppContext>,
}

impl ExceptionEventPipeline {
    pub fn new(app_context: Arc<AppContext>) -> Self {
        Self { app_context }
    }
}

pub type EventPipelineItem = Result<ClickHouseEvent, EventError>;

#[derive(Error, Debug)]
pub struct ExceptionEventHandledError {
    pub uuid: Uuid,
    pub error: EventError,
}

impl ExceptionEventHandledError {
    pub fn new(uuid: Uuid, error: EventError) -> Self {
        Self { uuid, error }
    }
}

impl Display for ExceptionEventHandledError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        Display::fmt(&self.error, f)
    }
}

pub type ExceptionEventPipelineItem = Result<ExceptionProperties, ExceptionEventHandledError>;

impl Stage for ExceptionEventPipeline {
    type Input = AnyEvent;
    type Output = AnyEvent;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        EXCEPTION_PROCESSING_PIPELINE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let events_by_id = Arc::new(Mutex::new(HashMap::<Uuid, AnyEvent>::new()));
        batch
            // Parse event
            .apply_stage(PreProcessingStage::new(events_by_id.clone()))
            .await?
            // Resolve stack traces
            .apply_stage(ResolutionStage::from(&self.app_context))
            .await?
            // Group events by fingerprint
            .apply_stage(GroupingStage::from(&self.app_context))
            .await?
            // Link events to issues and suppress
            .apply_stage(LinkingStage::from(&self.app_context))
            .await?
            // Send internal events for alerting
            .apply_stage(AlertingStage::from(&self.app_context))
            .await?
            // Handle errors, conversion to CH events
            .apply_stage(PostProcessingStage::new(events_by_id.clone()))
            .await
    }
}
