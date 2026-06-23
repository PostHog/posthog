use std::collections::HashMap;

use common_types::ClickHouseEvent;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::core::error::EventError;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct AnyEvent {
    pub uuid: Uuid,
    pub event: String,
    pub team_id: i32,
    pub timestamp: String,

    pub properties: Value,

    #[serde(flatten)]
    pub others: HashMap<String, Value>,
}

impl TryFrom<ClickHouseEvent> for AnyEvent {
    type Error = EventError;

    fn try_from(value: ClickHouseEvent) -> Result<Self, Self::Error> {
        let properties = match &value.properties {
            Some(p) => serde_json::from_str(p)
                .map_err(|e| EventError::InvalidProperties(value.uuid, e.to_string()))?,
            None => Value::Null,
        };

        Ok(AnyEvent {
            uuid: value.uuid,
            event: value.event,
            team_id: value.team_id,
            timestamp: value.timestamp,
            properties,
            // We don't preserve all properties from ClickhouseEvent.
            others: HashMap::new(),
        })
    }
}
