use std::collections::HashMap;

use serde::{Deserialize, Serialize};

/// Matches `SerializedKafkaMessage` in `nodejs/src/ingestion/api/types.ts`.
/// Values are raw UTF-8 strings (PostHog Kafka messages are always JSON text).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerializedKafkaMessage {
    pub topic: String,
    pub partition: i32,
    pub offset: i64,
    pub timestamp: i64,
    pub key: Option<String>,
    pub value: Option<String>,
    pub headers: HashMap<String, String>,
}

/// Matches `IngestBatchRequest` in `nodejs/src/ingestion/api/types.ts`.
#[derive(Debug, Serialize, Deserialize)]
pub struct IngestBatchRequest {
    pub batch_id: String,
    pub messages: Vec<SerializedKafkaMessage>,
}

/// Matches `IngestBatchResponse` in `nodejs/src/ingestion/api/types.ts`.
#[derive(Debug, Serialize, Deserialize)]
pub struct IngestBatchResponse {
    pub batch_id: String,
    pub status: String,
    pub accepted: u32,
    pub error: Option<String>,
}
