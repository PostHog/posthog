use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::kafka::types::Partition;

use anyhow::anyhow;
use anyhow::Result;
use rdkafka::message::{BorrowedMessage, Message, OwnedHeaders};
use serde::Deserialize;

pub struct Batch<T> {
    messages: Vec<KafkaMessage<T>>,
    errors: Vec<BatchError>,
}

impl<T> Batch<T> {
    pub fn new() -> Self {
        Self {
            messages: vec![],
            errors: vec![],
        }
    }

    pub fn new_with_size_hint(hint: usize) -> Self {
        Self {
            messages: Vec::with_capacity(hint),
            errors: vec![],
        }
    }

    pub fn message_count(&self) -> usize {
        self.messages.len()
    }

    pub fn error_count(&self) -> usize {
        self.errors.len()
    }

    pub fn is_empty(&self) -> bool {
        self.messages.is_empty() && self.errors.is_empty()
    }

    // consume this Batch and return it's contents
    pub fn unpack(self) -> (Vec<KafkaMessage<T>>, Vec<BatchError>) {
        (self.messages, self.errors)
    }

    pub fn get_messages(&self) -> &Vec<KafkaMessage<T>> {
        &self.messages
    }

    pub fn push_message(&mut self, km: KafkaMessage<T>) {
        self.messages.push(km);
    }

    pub fn get_errors(&self) -> &Vec<BatchError> {
        &self.errors
    }

    pub fn push_error(&mut self, be: BatchError) {
        self.errors.push(be);
    }
}

impl<T> Default for Batch<T> {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug)]
pub struct BatchError {
    // core error we're returning. These aren't
    // global consumer errors but per-message serialization
    // or receive problems that might be associated with a
    // specific message
    error: anyhow::Error,

    // coordinates of the original message if available,
    // in case we want to commit it's offset anyway
    topic_partition: Option<Partition>,
    offset: Option<i64>,
}

impl BatchError {
    pub fn new(
        error: anyhow::Error,
        topic_partition: Option<Partition>,
        offset: Option<i64>,
    ) -> Self {
        Self {
            error,
            topic_partition,
            offset,
        }
    }
}

impl BatchError {
    pub fn get_error(&self) -> &anyhow::Error {
        &self.error
    }

    pub fn get_offset(&self) -> Option<i64> {
        self.offset
    }

    pub fn get_topic_partition(&self) -> Option<&Partition> {
        self.topic_partition.as_ref()
    }
}

/// A lightweight, owned representation of a Kafka message optimized for batch processing
#[derive(Debug, Clone)]
pub struct KafkaMessage<T> {
    /// Topic name
    topic_partition: Partition,

    /// Message offset
    offset: i64,

    /// Optional message key as raw bytes
    pub key: Option<Vec<u8>>,

    /// hydrated message, if successfully deserialized from payload
    pub message: Option<T>,

    /// Message timestamp
    pub timestamp: SystemTime,

    /// Original headers from inbound message (for republishing)
    pub original_headers: Option<OwnedHeaders>,

    pub original_payload: Option<Vec<u8>>,
}

impl<T> KafkaMessage<T> {
    pub fn new(
        topic_partition: Partition,
        offset: i64,
        key: Option<Vec<u8>>,
        message: Option<T>,
        timestamp: SystemTime,
        original_headers: Option<OwnedHeaders>,
        original_payload: Option<Vec<u8>>,
    ) -> Self {
        Self {
            topic_partition,
            offset,
            key,
            message,
            timestamp,
            original_headers,
            original_payload,
        }
    }

    /// Extract message from borrowed Kafka message efficiently
    pub fn from_borrowed_message<'a>(msg: &'a BorrowedMessage<'a>) -> Result<Self>
    where
        T: for<'de> Deserialize<'de>,
    {
        // convert from rdkafka's timestamp to common Rust form
        let resolved_timestamp = msg
            .timestamp()
            .to_millis()
            .map(|ms| Duration::from_millis(ms as u64))
            .map(|duration| UNIX_EPOCH + duration)
            .ok_or_else(|| anyhow!("Failed to resolve timestamp"))?;

        let mut out = Self {
            topic_partition: Partition::new(msg.topic().to_owned(), msg.partition()),
            offset: msg.offset(),
            key: msg.key().map(|k| k.to_vec()),
            message: None,
            timestamp: resolved_timestamp,
            original_headers: Some(msg.headers().map(|h| h.detach()).unwrap_or_default()),
            original_payload: msg.payload().map(|p| p.to_vec()),
        };

        match &out.original_payload {
            Some(payload) => {
                match serde_json::from_slice::<T>(payload) {
                    Ok(hydrated_payload) => {
                        out.message = Some(hydrated_payload);
                    }
                    Err(e) => {
                        return Err(anyhow!("Failed to deserialize message: {e}"));
                    }
                };
            }
            None => {
                return Err(anyhow!("No payload in message"));
            }
        }

        Ok(out)
    }

    // Convenience method for republishing the original event to downstream topic
    pub fn to_original_contents(&self) -> (&[u8], Option<&OwnedHeaders>) {
        (
            self.original_payload.as_deref().unwrap_or(&[]),
            self.original_headers.as_ref(),
        )
    }

    // Convenience method to get the Partition associated with the message
    pub fn get_topic_partition(&self) -> Partition {
        self.topic_partition.clone()
    }

    /// Get the message key as a UTF-8 string if possible
    pub fn key_as_str(&self) -> Option<Result<&str, std::str::Utf8Error>> {
        self.key.as_ref().map(|k| std::str::from_utf8(k))
    }

    pub fn get_offset(&self) -> i64 {
        self.offset
    }

    pub fn get_timestamp(&self) -> std::time::SystemTime {
        self.timestamp
    }

    pub fn get_message(&self) -> Option<&T> {
        self.message.as_ref()
    }

    pub fn take_message(&mut self) -> Option<T> {
        self.message.take()
    }

    /// Create a simple KafkaMessage for testing purposes
    #[cfg(test)]
    pub fn new_for_test(partition: Partition, offset: i64, message: T) -> Self {
        Self {
            topic_partition: partition,
            offset,
            key: None,
            message: Some(message),
            timestamp: SystemTime::now(),
            original_headers: None,
            original_payload: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::CapturedEvent;

    use time::OffsetDateTime;
    use uuid::Uuid;

    use rdkafka::message::{Header, Headers};

    #[tokio::test]
    async fn test_kafka_message_utilities() {
        let now = std::time::SystemTime::now();
        let now_offset_datetime = OffsetDateTime::from(now);
        let now_rfc3339 = chrono::DateTime::<chrono::Utc>::from(now).to_rfc3339();
        let distinct_id = Uuid::now_v7().to_string();
        let token = Uuid::now_v7().to_string();
        let event_name = "$pageview";
        let ip = "127.0.0.1".to_string();
        let event_uuid = Uuid::now_v7();
        let topic = "test-topic";
        let topic_partition = Partition::new(topic.to_string(), 0);
        let offset = 123;
        let key_str = format!("{token}:{distinct_id}");
        let key = key_str.as_bytes().to_vec();
        let payload = format!(
            r#"{{"uuid": "{event_uuid}", "event": "{event_name}", "distinct_id": "{distinct_id}", "token": "{token}","properties": {{}}}}"#
        );
        let headers = OwnedHeaders::new()
            .insert(Header {
                key: "header1",
                value: Some(b"value1"),
            })
            .insert(Header {
                key: "header2",
                value: Some(b""),
            })
            .insert(Header {
                key: "some_number",
                value: Some(b"123456789"),
            })
            .insert(Header {
                key: "another_number",
                value: Some(b"123"),
            });

        // Create a mock KafkaMessage for testing
        let message = KafkaMessage::<CapturedEvent> {
            topic_partition,
            offset,
            key: Some(key.clone()),
            message: Some(CapturedEvent {
                uuid: event_uuid,
                distinct_id: distinct_id.to_string(),
                session_id: None,
                ip: ip.clone(),
                now: now_rfc3339.clone(),
                token: token.clone(),
                // serialized RawEvent
                data: payload.to_string(),
                sent_at: Some(now_offset_datetime),
                event: "test_event".to_string(),
                timestamp: chrono::Utc::now(),
                is_cookieless_mode: false,
                historical_migration: false,
            }),
            timestamp: std::time::SystemTime::now(),
            original_headers: Some(headers), // stub orig headers for testing
            original_payload: Some(Vec::new()), // stub orig payload for testing
        };

        // Test string conversion methods
        assert_eq!(message.key, Some(key.clone()));
        assert_eq!(message.key_as_str().unwrap().unwrap(), &key_str);

        // Test header access
        assert!(message.original_headers.is_some());
        let headers = message.original_headers.as_ref().unwrap();
        assert!(headers.get(0).key == "header1");
        assert!(headers.get(1).key == "header2");
        assert!(headers.get(2).key == "some_number");
        assert!(headers.get(3).key == "another_number");

        // Test message access
        assert!(message.get_message().is_some());
        assert_eq!(message.get_message().unwrap().distinct_id, distinct_id);
        assert_eq!(message.get_message().unwrap().token, token);
        assert_eq!(message.get_message().unwrap().ip, ip);
        assert_eq!(message.get_message().unwrap().now, now_rfc3339);
        assert_eq!(
            message.get_message().unwrap().sent_at,
            Some(now_offset_datetime)
        );
        assert!(!message.get_message().unwrap().is_cookieless_mode);
        assert_eq!(&message.get_message().unwrap().key(), &key_str);
        assert_eq!(message.get_message().unwrap().uuid, event_uuid);
        assert_eq!(message.get_message().unwrap().distinct_id, distinct_id);
        assert_eq!(message.get_message().unwrap().token, token);
        assert_eq!(message.get_message().unwrap().ip, ip);
        assert_eq!(message.get_message().unwrap().now, now_rfc3339);
    }
}
