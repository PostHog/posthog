use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Serialize, Deserialize, Clone)]
pub struct AnyEvent {
    pub uuid: Uuid,
    pub event: String,
    pub team_id: i32,
    pub timestamp: String,

    pub properties: Value,

    #[serde(flatten)]
    pub others: HashMap<String, Value>,
}
