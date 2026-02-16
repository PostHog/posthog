use std::collections::HashMap;

use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SerializedMessage {
    pub topic: String,
    pub partition: i32,
    pub offset: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<i64>,
    pub key: Option<String>,   // base64-encoded
    pub value: Option<String>, // base64-encoded
    pub headers: Vec<HashMap<String, String>>, // header values are base64-encoded
}

#[derive(Debug, Serialize, Deserialize)]
pub struct BatchRequest {
    pub messages: Vec<SerializedMessage>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
pub struct BatchResponse {
    pub status: String,
    pub accepted: Option<usize>,
    pub error: Option<String>,
}

impl SerializedMessage {
    pub fn from_kafka_message(
        topic: &str,
        partition: i32,
        offset: i64,
        timestamp: Option<i64>,
        key: Option<&[u8]>,
        value: Option<&[u8]>,
        headers: Vec<(String, Vec<u8>)>,
    ) -> Self {
        let encoded_headers: Vec<HashMap<String, String>> = headers
            .into_iter()
            .map(|(k, v)| {
                let mut m = HashMap::new();
                m.insert(k, BASE64.encode(v));
                m
            })
            .collect();

        Self {
            topic: topic.to_string(),
            partition,
            offset,
            timestamp,
            key: key.map(|k| BASE64.encode(k)),
            value: value.map(|v| BASE64.encode(v)),
            headers: encoded_headers,
        }
    }

    pub fn get_header(&self, name: &str) -> Option<String> {
        for header in &self.headers {
            if let Some(encoded) = header.get(name) {
                if let Ok(decoded) = BASE64.decode(encoded) {
                    return String::from_utf8(decoded).ok();
                }
            }
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_serialization_round_trip() {
        let msg = SerializedMessage::from_kafka_message(
            "events_plugin_ingestion",
            3,
            12345,
            Some(1708012800000),
            Some(b"phc_abc:user-1"),
            Some(b"{\"event\":\"$pageview\"}"),
            vec![
                ("token".to_string(), b"phc_abc".to_vec()),
                ("distinct_id".to_string(), b"user-1".to_vec()),
            ],
        );

        let json = serde_json::to_string(&msg).unwrap();
        let parsed: SerializedMessage = serde_json::from_str(&json).unwrap();

        assert_eq!(parsed, msg);
        assert_eq!(parsed.topic, "events_plugin_ingestion");
        assert_eq!(parsed.partition, 3);
        assert_eq!(parsed.offset, 12345);
        assert_eq!(parsed.timestamp, Some(1708012800000));
    }

    #[test]
    fn test_json_matches_nodejs_schema() {
        let msg = SerializedMessage::from_kafka_message(
            "events_plugin_ingestion",
            0,
            0,
            None,
            None,
            Some(b"test"),
            vec![("token".to_string(), b"phc_abc".to_vec())],
        );

        let json: serde_json::Value = serde_json::to_value(&msg).unwrap();

        assert!(json["topic"].is_string());
        assert!(json["partition"].is_number());
        assert!(json["offset"].is_number());
        assert!(json["key"].is_null());
        assert!(json["value"].is_string());
        assert!(json["headers"].is_array());
        assert!(json["headers"][0]["token"].is_string());
        // timestamp should be omitted when None
        assert!(json.get("timestamp").is_none());
    }

    #[test]
    fn test_get_header() {
        let msg = SerializedMessage::from_kafka_message(
            "test",
            0,
            0,
            None,
            None,
            None,
            vec![
                ("token".to_string(), b"phc_abc".to_vec()),
                ("distinct_id".to_string(), b"user-1".to_vec()),
            ],
        );

        assert_eq!(msg.get_header("token"), Some("phc_abc".to_string()));
        assert_eq!(msg.get_header("distinct_id"), Some("user-1".to_string()));
        assert_eq!(msg.get_header("missing"), None);
    }

    #[test]
    fn test_null_key_and_value() {
        let msg = SerializedMessage::from_kafka_message("test", 0, 0, None, None, None, vec![]);

        assert!(msg.key.is_none());
        assert!(msg.value.is_none());
        assert!(msg.headers.is_empty());
    }

    #[test]
    fn test_batch_request_serialization() {
        let request = BatchRequest {
            messages: vec![
                SerializedMessage::from_kafka_message(
                    "test",
                    0,
                    0,
                    None,
                    None,
                    Some(b"data"),
                    vec![],
                ),
                SerializedMessage::from_kafka_message(
                    "test",
                    0,
                    1,
                    None,
                    None,
                    Some(b"data2"),
                    vec![],
                ),
            ],
        };

        let json = serde_json::to_string(&request).unwrap();
        let parsed: BatchRequest = serde_json::from_str(&json).unwrap();

        assert_eq!(parsed.messages.len(), 2);
        assert_eq!(parsed.messages[0].offset, 0);
        assert_eq!(parsed.messages[1].offset, 1);
    }
}
