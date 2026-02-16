use std::{collections::HashMap, sync::Arc};
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::POST_PROCESSING_STAGE,
    stages::pipeline::{ExceptionEventHandledError, ExceptionEventPipelineItem},
    types::{
        batch::Batch,
        exception_properties::ExceptionProperties,
        stage::{Stage, StageResult},
    },
};

pub trait PropertiesContainer: Send + Clone + 'static {
    fn set_properties(&mut self, new_props: ExceptionProperties) -> Result<(), UnhandledError>;
    fn attach_error(&mut self, error: String) -> Result<(), UnhandledError>;
}

#[derive(Clone)]
pub struct UpdatePropertiesStage<T: PropertiesContainer> {
    events_by_id: Arc<Mutex<HashMap<Uuid, T>>>,
}

impl<T: PropertiesContainer> UpdatePropertiesStage<T> {
    pub fn new(events_by_id: Arc<Mutex<HashMap<Uuid, T>>>) -> Self {
        Self { events_by_id }
    }

    fn add_error_to_event(&self, mut event: T, e: impl ToString) -> Result<T, UnhandledError> {
        event.attach_error(e.to_string());
        Ok(event)
    }

    async fn handle_error(
        &self,
        error: ExceptionEventHandledError,
    ) -> Result<Result<T, EventError>, UnhandledError> {
        let (uuid, error) = (error.uuid, error.error);
        let mut evt = self
            .events_by_id
            .lock()
            .await
            .remove(&uuid)
            .ok_or(UnhandledError::Other("Missing event".into()))?;
        evt.attach_error(error.to_string());
        Ok(Ok(evt))
    }

    async fn handle_value(&self, props: ExceptionProperties) -> Result<T, UnhandledError> {
        let mut evt = self
            .events_by_id
            .lock()
            .await
            .remove(&props.uuid)
            .ok_or(UnhandledError::Other("Missing event".into()))?;
        evt.set_properties(props)?;
        Ok(Ok(evt))
    }
}

impl<T: PropertiesContainer> Stage for UpdatePropertiesStage<T> {
    type Input = ExceptionEventPipelineItem;
    type Output = T;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        POST_PROCESSING_STAGE
    }

    async fn process(self, input: Batch<Self::Input>) -> Result<Batch<Self::Output>, Self::Error> {
        input
            .apply_func(
                async |item, ctx| match item {
                    Err(err) => ctx.handle_error(err).await,
                    Ok(event) => ctx.handle_value(event).await,
                },
                self,
            )
            .await
    }
}
