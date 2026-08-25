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
    /// Identifies this consumer process incarnation. The worker's feed-order
    /// sentinel rebaselines a key when the sender changes (restart/rebalance
    /// legitimately replays uncommitted offsets).
    pub consumer_id: String,
    /// True when this request may repeat previously sent messages (an HTTP
    /// retry, or a deferred-flush re-route after a send failure). The worker's
    /// sentinel counts repeats on replay requests as at-least-once replays
    /// rather than order violations.
    pub replay: bool,
}

/// Matches `IngestBatchResponse` in `nodejs/src/ingestion/api/types.ts`.
#[derive(Debug, Serialize, Deserialize)]
pub struct IngestBatchResponse {
    pub batch_id: String,
    pub status: String,
    pub accepted: u32,
    pub error: Option<String>,
}
