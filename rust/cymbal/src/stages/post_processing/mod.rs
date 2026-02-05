use std::{collections::HashMap, sync::Arc};

use common_types::ClickHouseEvent;
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

#[derive(Clone)]
pub struct PostProcessingStage {
    events_by_id: Arc<Mutex<HashMap<Uuid, ClickHouseEvent>>>,
}

impl PostProcessingStage {
    pub fn new(events_by_id: Arc<Mutex<HashMap<Uuid, ClickHouseEvent>>>) -> Self {
        Self { events_by_id }
    }

    // This is expensive, since it round-trips the event through JSON.
    // We could maybe change ClickhouseEvent to only do serde at the edges
    fn add_error_to_event(
        &self,
        event: &mut ClickHouseEvent,
        e: impl ToString,
    ) -> Result<(), UnhandledError> {
        let mut props = event.take_raw_properties()?;
        let mut errors = match props.remove("$cymbal_errors") {
            Some(serde_json::Value::Array(errors)) => errors,
            _ => Vec::new(),
        };

        errors.push(serde_json::Value::String(e.to_string()));
        props.insert(
            "$cymbal_errors".to_string(),
            serde_json::Value::Array(errors),
        );
        event.set_raw_properties(props)?;
        Ok(())
    }

    async fn handle_error(
        &self,
        error: ExceptionEventHandledError,
    ) -> Result<Option<ClickHouseEvent>, UnhandledError> {
        let (uuid, error) = (error.uuid, error.error);
        match error {
            EventError::Suppressed(_) => Ok(None),
            err => {
                let mut event = self
                    .events_by_id
                    .lock()
                    .await
                    .remove(&uuid)
                    .ok_or(UnhandledError::Other("Missing event".into()))?;
                self.add_error_to_event(&mut event, err)?;
                Ok(Some(event))
            }
        }
    }

    async fn handle_value(
        &self,
        props: ExceptionProperties,
    ) -> Result<Option<ClickHouseEvent>, UnhandledError> {
        let mut evt = self
            .events_by_id
            .lock()
            .await
            .remove(&props.uuid)
            .ok_or(UnhandledError::Other("Missing event".into()))?;
        evt.properties = Some(serde_json::to_string(&props)?);
        Ok(Some(evt))
    }
}

impl Stage for PostProcessingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ClickHouseEvent;
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
