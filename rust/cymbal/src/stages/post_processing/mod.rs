use std::{collections::HashMap, sync::Arc};

use serde_json::Value;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::POST_PROCESSING_STAGE,
    stages::pipeline::{ExceptionEventHandledError, ExceptionEventPipelineItem},
    types::{
        batch::Batch,
        event::AnyEvent,
        exception_properties::ExceptionProperties,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct PostProcessingStage {
    events_by_id: Arc<Mutex<HashMap<Uuid, AnyEvent>>>,
}

impl PostProcessingStage {
    pub fn new(events_by_id: Arc<Mutex<HashMap<Uuid, AnyEvent>>>) -> Self {
        Self { events_by_id }
    }

    // This is expensive, since it round-trips the event through JSON.
    // We could maybe change ClickhouseEvent to only do serde at the edges
    fn add_error_to_event(
        &self,
        mut event: AnyEvent,
        e: impl ToString,
    ) -> Result<AnyEvent, UnhandledError> {
        let mut props: HashMap<String, Value> = serde_json::from_value(event.properties)?;
        let mut errors = match props.remove("$cymbal_errors") {
            Some(serde_json::Value::Array(errors)) => errors,
            _ => Vec::new(),
        };
        errors.push(serde_json::Value::String(e.to_string()));
        props.insert(
            "$cymbal_errors".to_string(),
            serde_json::Value::Array(errors),
        );
        event.properties = serde_json::to_value(props)?;
        Ok(event)
    }

    async fn handle_error(
        &self,
        error: ExceptionEventHandledError,
    ) -> Result<Option<AnyEvent>, UnhandledError> {
        let (uuid, error) = (error.uuid, error.error);
        match error {
            EventError::Suppressed(_) => Ok(None),
            err => {
                let event = self
                    .events_by_id
                    .lock()
                    .await
                    .remove(&uuid)
                    .ok_or(UnhandledError::Other("Missing event".into()))?;
                let event = self.add_error_to_event(event, err)?;
                Ok(Some(event))
            }
        }
    }

    async fn handle_value(
        &self,
        props: ExceptionProperties,
    ) -> Result<Option<AnyEvent>, UnhandledError> {
        let mut evt = self
            .events_by_id
            .lock()
            .await
            .remove(&props.uuid)
            .ok_or(UnhandledError::Other("Missing event".into()))?;
        evt.properties = serde_json::to_value(&props)?;
        Ok(Some(evt))
    }
}

impl Stage for PostProcessingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = AnyEvent;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        POST_PROCESSING_STAGE
    }

    async fn process(self, input: Batch<Self::Input>) -> StageResult<Self> {
        // Implement error handling logic here
        Ok(input
            .apply_func(
                async |item, ctx| match item {
                    Err(e) => ctx.handle_error(e).await,
                    Ok(event) => ctx.handle_value(event).await,
                },
                self,
            )
            .await?
            .into_iter()
            .flatten()
            .collect::<Vec<_>>()
            .into())
    }
}
