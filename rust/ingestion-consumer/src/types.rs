use std::collections::HashMap;

use common_kafka_consumer::{Offset, PolledMessage};
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

/// The demux's view of a message: the Kafka key is the routing key.
impl From<SerializedKafkaMessage> for PolledMessage<String, SerializedKafkaMessage> {
    fn from(message: SerializedKafkaMessage) -> Self {
        PolledMessage {
            offset: Offset(message.offset),
            key: message.key.clone(),
            inner: message,
        }
    }
}

/// One poll's messages for one routing key on one partition, in offset order.
pub type Group = common_kafka_consumer::Group<String, SerializedKafkaMessage>;

/// The demux that builds one poll's groups.
pub type Accumulator = common_kafka_consumer::Accumulator<String, SerializedKafkaMessage>;
