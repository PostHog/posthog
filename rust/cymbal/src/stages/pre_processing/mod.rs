use std::{collections::HashMap, sync::Arc};

use serde_json::Value;

use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::PRE_PROCESSING_STAGE,
    pipeline::exception::MAX_EXCEPTION_VALUE_LENGTH,
    recursively_sanitize_properties,
    stages::pipeline::{ExceptionEventHandledError, ExceptionEventPipelineItem},
    types::{
        batch::Batch,
        event::AnyEvent,
        exception_properties::ExceptionProperties,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct PreProcessingStage {
    events_by_id: Arc<Mutex<HashMap<Uuid, AnyEvent>>>,
}

impl PreProcessingStage {
    pub fn new(events_by_id: Arc<Mutex<HashMap<Uuid, AnyEvent>>>) -> Self {
        Self { events_by_id }
    }

    fn parse_event(&self, event: AnyEvent) -> Result<ExceptionProperties, EventError> {
        if event.event != "$exception" {
            return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
        }

        let mut properties: Value = match serde_json::from_value(event.properties) {
            Ok(r) => r,
            Err(e) => {
                return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
            }
        };

        if let Some(v) = properties
            .as_object_mut()
            .and_then(|o| o.get_mut("$exception_list"))
        {
            // We PG sanitize the exception list, because the strings in it can end up in PG kind of arbitrarily.
            // TODO - the prep stage has already sanitized the properties, so maybe we don't need to do this again?
            recursively_sanitize_properties(event.uuid, v, 0)?;
        }

        let mut evt: ExceptionProperties = match serde_json::from_value(properties) {
            Ok(r) => r,
            Err(e) => {
                return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
            }
        };

        if evt.exception_list.is_empty() {
            return Err(EventError::EmptyExceptionList(event.uuid));
        }

        for exception in evt.exception_list.iter_mut() {
            if exception.exception_message.len() > MAX_EXCEPTION_VALUE_LENGTH {
                let truncate_at = exception
                    .exception_message
                    .char_indices()
                    .take_while(|(i, _)| *i < MAX_EXCEPTION_VALUE_LENGTH)
                    .last()
                    .map(|(i, c)| i + c.len_utf8())
                    .unwrap_or(0);
                exception.exception_message.truncate(truncate_at);
                exception.exception_message.push_str("...");
            }
        }

        // Set metadata fields that are skipped during deserialization
        evt.uuid = event.uuid;
        evt.timestamp = event.timestamp;
        evt.team_id = event.team_id;

        Ok(evt)
    }
}

impl Stage for PreProcessingStage {
    type Input = AnyEvent;
    type Output = ExceptionEventPipelineItem;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        PRE_PROCESSING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let events_by_id = self.events_by_id.clone();
        batch
            .apply_func(
                move |event, ctx| {
                    let events_by_id = events_by_id.clone();
                    let uuid = event.uuid;

                    async move {
                        events_by_id.lock().await.insert(uuid, event.clone());

                        // Parse event into intermediate representation
                        let result = match ctx.parse_event(event) {
                            Ok(evt) => Ok(evt),
                            Err(err) => Err(ExceptionEventHandledError::new(uuid, err)),
                        };

                        Ok(result)
                    }
                },
                self,
            )
            .await
    }
}
