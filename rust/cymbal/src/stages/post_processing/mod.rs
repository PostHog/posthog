use std::{collections::HashMap, sync::Arc};

use common_types::ClickHouseEvent;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    types::{
        batch::Batch,
        event::ExceptionProperties,
        pipeline::{ExceptionEventHandledError, ExceptionEventPipelineItem},
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
                let mut event = self.events_by_id.lock().await.get(&uuid).unwrap().clone();
                self.add_error_to_event(&mut event, err)?;
                Ok(Some(event))
            }
        }
    }

    async fn handle_value(
        &self,
        event: ExceptionProperties,
    ) -> Result<Option<ClickHouseEvent>, UnhandledError> {
        // WARN: Wont work here
        let value = serde_json::to_value(event)?;
        let event: ClickHouseEvent = serde_json::from_value(value)?;
        Ok(Some(event))
    }
}

impl Stage for PostProcessingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ClickHouseEvent;
    type Error = UnhandledError;

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
