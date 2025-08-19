use anyhow::Result;
use rdkafka::message::OwnedMessage;
use tracing::{debug, warn};

use crate::kafka::tracker::{MessageCompletion, MessageHandle};

/// Result of message processing - simple success/failure
#[derive(Debug, Clone)]
pub enum MessageResult {
    Success,
    Failed(String),
}

/// A wrapper around a Kafka message that can be acknowledged
pub struct AckableMessage {
    /// The original Kafka message
    pub message: OwnedMessage,

    /// Message handle for completion
    handle: MessageHandle,

    /// Whether this message has been acked
    acked: bool,
}

impl AckableMessage {
    pub(crate) fn new(message: OwnedMessage, handle: MessageHandle) -> Self {
        Self {
            message,
            handle,
            acked: false,
        }
    }

    /// Acknowledge successful processing of this message
    pub async fn ack(mut self) {
        if self.acked {
            warn!("Message already acked: id={}", self.handle.message_id);
            return;
        }

        self.handle.complete(MessageResult::Success).await;
        self.acked = true;

        debug!("Acked message: id={}", self.handle.message_id);
    }

    /// Acknowledge failed processing of this message
    pub async fn nack(mut self, error: String) {
        if self.acked {
            warn!("Message already acked: id={}", self.handle.message_id);
            return;
        }

        self.handle
            .complete(MessageResult::Failed(error.clone()))
            .await;
        self.acked = true;

        debug!(
            "Nacked message: id={}, error={}",
            self.handle.message_id, error
        );
    }

    /// Get the underlying Kafka message
    pub fn kafka_message(&self) -> &OwnedMessage {
        &self.message
    }

    /// Check if this message has been acknowledged
    pub fn is_acked(&self) -> bool {
        self.acked
    }

    /// Get memory size from handle
    pub fn memory_size(&self) -> usize {
        self.handle.memory_size
    }
}

impl Drop for AckableMessage {
    fn drop(&mut self) {
        if !self.acked {
            warn!(
                "Message dropped without acking: id={}",
                self.handle.message_id
            );

            // Auto-nack on drop to prevent hanging
            let completion = MessageCompletion {
                offset: self.handle.offset,
                result: MessageResult::Failed("Message dropped without acking".to_string()),
                memory_size: self.handle.memory_size,
            };

            if self.handle.completion_tx.send(completion).is_err() {
                warn!(
                    "Failed to send auto-nack for dropped message: id={}",
                    self.handle.message_id
                );
            }
        }
    }
}

impl MessageResult {
    pub fn is_success(&self) -> bool {
        matches!(self, MessageResult::Success)
    }

    pub fn error_message(&self) -> String {
        match self {
            MessageResult::Success => "Success".to_string(),
            MessageResult::Failed(msg) => msg.clone(),
        }
    }
}

/// Trait for message processors that work with ackable messages
#[async_trait::async_trait]
pub trait MessageProcessor: Send + Sync + Clone + 'static {
    /// Process an ackable message
    /// The processor is responsible for calling ack() or nack() on the message
    async fn process_message(&self, message: AckableMessage) -> Result<()>;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::InFlightTracker;
    use rdkafka::message::{OwnedHeaders, OwnedMessage, Timestamp};
    use std::sync::Arc;

    fn create_test_message(
        topic: &str,
        partition: i32,
        offset: i64,
        payload: &str,
    ) -> OwnedMessage {
        OwnedMessage::new(
            Some(payload.as_bytes().to_vec()),
            Some("test-key".as_bytes().to_vec()),
            topic.to_string(),
            Timestamp::now(),
            partition,
            offset,
            Some(OwnedHeaders::new()),
        )
    }

    #[tokio::test]
    async fn test_message_ack() {
        let tracker = Arc::new(InFlightTracker::new());
        let message = create_test_message("test-topic", 0, 0, "test-payload");
        let (_message_id, handle) = tracker.track_message(&message, 100).await;

        let ackable = AckableMessage::new(message, handle);

        // Verify message is tracked
        assert_eq!(tracker.in_flight_count().await, 1);
        assert_eq!(tracker.memory_usage().await, 100);

        // Ack the message
        ackable.ack().await;

        // Process completions
        tracker.process_completions().await;

        // Verify message is completed
        assert_eq!(tracker.in_flight_count().await, 0);
        assert_eq!(tracker.memory_usage().await, 0);

        let stats = tracker.get_stats().await;
        assert_eq!(stats.completed, 1);
        assert_eq!(stats.failed, 0);
    }

    #[tokio::test]
    async fn test_message_nack() {
        let tracker = Arc::new(InFlightTracker::new());
        let message = create_test_message("test-topic", 0, 0, "test-payload");
        let (_, handle) = tracker.track_message(&message, 50).await;

        let ackable = AckableMessage::new(message, handle);

        // Nack the message
        ackable.nack("test error".to_string()).await;

        // Process completions
        tracker.process_completions().await;

        // Verify message is completed with failure
        assert_eq!(tracker.in_flight_count().await, 0);
        assert_eq!(tracker.memory_usage().await, 0);

        let stats = tracker.get_stats().await;
        assert_eq!(stats.completed, 0);
        assert_eq!(stats.failed, 1);
    }

    #[test]
    fn test_message_result() {
        let success = MessageResult::Success;
        assert!(success.is_success());
        assert_eq!(success.error_message(), "Success");

        let failed = MessageResult::Failed("error message".to_string());
        assert!(!failed.is_success());
        assert_eq!(failed.error_message(), "error message");
    }
}
