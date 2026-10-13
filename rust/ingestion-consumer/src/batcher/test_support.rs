use std::collections::HashMap;

use crate::types::SerializedKafkaMessage;

pub fn message(key: &str, partition: i32, offset: i64) -> SerializedKafkaMessage {
    SerializedKafkaMessage {
        topic: "events".into(),
        partition,
        offset,
        timestamp: 0,
        key: Some(key.to_string()),
        value: Some("{}".to_string()),
        headers: HashMap::new(),
    }
}

pub fn offsets(messages: &[SerializedKafkaMessage]) -> Vec<i64> {
    messages.iter().map(|m| m.offset).collect()
}
