use std::{collections::HashMap, sync::Arc};

use common_types::ClickHouseEvent;
use serde_json::Value;

use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    recursively_sanitize_properties,
    types::{
        batch::Batch,
        event::ExceptionEvent,
        pipeline::{ExceptionEventHandledError, ExceptionEventPipelineItem},
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct PreProcessingStage {
    events_by_id: Arc<Mutex<HashMap<Uuid, ClickHouseEvent>>>,
}

impl PreProcessingStage {
    pub fn new(events_by_id: Arc<Mutex<HashMap<Uuid, ClickHouseEvent>>>) -> Self {
        Self { events_by_id }
    }

    fn parse_event(&self, event: &ClickHouseEvent) -> Result<ExceptionEvent, EventError> {
        // fix this there will be an issue with properties
        if event.event != "$exception" {
            return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
        }
        let Some(properties) = &event.properties else {
            return Err(EventError::NoProperties(event.uuid));
        };
        let mut properties: Value = match serde_json::from_str(properties) {
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

        let evt: ExceptionEvent = match serde_json::from_value(properties) {
            Ok(r) => r,
            Err(e) => {
                return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
            }
        };

        if evt.exception_list.is_empty() {
            return Err(EventError::EmptyExceptionList(event.uuid));
        }

        Ok(evt)
    }
}

impl Stage for PreProcessingStage {
    type Input = ClickHouseEvent;
    type Output = ExceptionEventPipelineItem;
    type Error = UnhandledError;

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
                        let result = match ctx.parse_event(&event) {
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
