use std::{
    collections::HashMap,
    fmt::{Debug, Display},
    future::Future,
    sync::Arc,
};

use common_types::ClickHouseEvent;
use thiserror::Error;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    stages::{
        grouping::GroupingStage, linking::LinkingStage, post_processing::PostProcessingStage,
        pre_processing::PreProcessingStage, resolution::ResolutionStage,
    },
    types::{batch::Batch, event::ExceptionEvent},
};

pub trait Pipeline {
    type Input;
    type Output;
    type Error;

    fn run(
        &self,
        batch: Batch<Self::Input>,
        app_context: Arc<AppContext>,
    ) -> impl Future<Output = Result<Batch<Self::Output>, Self::Error>>;
}

pub struct ExceptionEventPipeline {}

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

pub type ExceptionEventPipelineItem = Result<ExceptionEvent, ExceptionEventHandledError>;

impl Pipeline for ExceptionEventPipeline {
    type Input = ClickHouseEvent;
    type Output = ClickHouseEvent;
    type Error = UnhandledError;

    async fn run(
        &self,
        batch: Batch<Self::Input>,
        app_context: Arc<AppContext>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let events_by_id = Arc::new(Mutex::new(HashMap::<Uuid, ClickHouseEvent>::new()));
        batch
            // Parse event
            .apply_stage(PreProcessingStage::new(events_by_id.clone()))
            .await?
            // Resolve stack traces
            .apply_stage(ResolutionStage::from(&app_context))
            .await?
            // Group events by fingerprint
            .apply_stage(GroupingStage::from(&app_context))
            .await?
            // Link events to issues
            .apply_stage(LinkingStage::from(&app_context))
            .await?
            // Handle errors, conversion to CH events
            .apply_stage(PostProcessingStage::new(events_by_id.clone()))
            .await
    }
}
