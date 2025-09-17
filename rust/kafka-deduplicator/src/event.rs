use serde::{Deserialize, Serialize};

// Placeholder for event data
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct EventData {
    pub timestamp: u64,
    pub distinct_id: String,
    pub token: String,
    pub event_name: String,
    pub team_id: u32,
    pub source: u8,
}
