//! One-shot head-of-log fetcher for Kafka partitions.
//!
//! Provides a simple API to fetch the latest message from specified partitions
//! without joining a consumer group. Used after checkpoint imports to fetch
//! head-of-log from the output topic for validation/synchronization.

use std::time::{Duration, Instant};

use metrics::{counter, histogram};
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::error::KafkaError;
use rdkafka::{Offset, TopicPartitionList};
use serde::Deserialize;
use thiserror::Error;
use tracing::warn;

use crate::kafka::batch_message::KafkaMessage;

/// Metric name for head fetch duration histogram
pub const HEAD_FETCH_DURATION_HISTOGRAM: &str = "kafka_dedup_head_fetch_duration_ms";
/// Metric name for head fetch errors counter
pub const HEAD_FETCH_ERROR_COUNTER: &str = "kafka_dedup_head_fetch_errors";

/// Errors that can occur during head-of-log fetching.
///
/// These error types allow callers to distinguish between different failure modes
/// and take appropriate action (e.g., retry on timeout, alert on persistent errors).
#[derive(Error, Debug)]
pub enum HeadFetchError {
    /// Failed to create the Kafka consumer
    #[error("failed to create consumer: {0}")]
    ConsumerCreation(#[source] KafkaError),

    /// Failed to assign partitions to the consumer
    #[error("failed to assign partitions: {0}")]
    PartitionAssignment(#[source] KafkaError),

    /// Timeout occurred during a Kafka operation
    #[error("timeout during {operation} for partition {partition}")]
    Timeout {
        operation: &'static str,
        partition: i32,
    },

    /// Kafka broker returned an error
    #[error("kafka error during {operation} for partition {partition}: {source}")]
    Kafka {
        operation: &'static str,
        partition: i32,
        #[source]
        source: KafkaError,
    },
}

impl HeadFetchError {
    /// Returns the error type tag for metrics
    pub fn error_type(&self) -> &'static str {
        match self {
            HeadFetchError::ConsumerCreation(_) => "consumer_creation",
            HeadFetchError::PartitionAssignment(_) => "partition_assignment",
            HeadFetchError::Timeout { .. } => "timeout",
            HeadFetchError::Kafka { .. } => "kafka_error",
        }
    }

    /// Returns true if this error is a timeout
    pub fn is_timeout(&self) -> bool {
        matches!(self, HeadFetchError::Timeout { .. })
    }
}

/// Result of fetching head message for a single partition.
#[derive(Debug)]
pub enum PartitionFetchResult<T> {
    /// Successfully fetched and deserialized the head message
    Success(KafkaMessage<T>),
    /// Partition is empty (high watermark == low watermark)
    Empty,
    /// Failed to deserialize the message payload
    DeserializationError(String),
    /// Kafka operation failed for this partition
    Error(HeadFetchError),
}

impl<T> PartitionFetchResult<T> {
    /// Returns the message if successful, None otherwise
    pub fn into_message(self) -> Option<KafkaMessage<T>> {
        match self {
            PartitionFetchResult::Success(msg) => Some(msg),
            _ => None,
        }
    }

    /// Returns true if the fetch was successful
    pub fn is_success(&self) -> bool {
        matches!(self, PartitionFetchResult::Success(_))
    }

    /// Returns true if this was a timeout error
    pub fn is_timeout(&self) -> bool {
        matches!(
            self,
            PartitionFetchResult::Error(HeadFetchError::Timeout { .. })
        )
    }

    /// Returns the result type tag for metrics/logging
    pub fn result_type(&self) -> &'static str {
        match self {
            PartitionFetchResult::Success(_) => "success",
            PartitionFetchResult::Empty => "empty",
            PartitionFetchResult::DeserializationError(_) => "deserialization_error",
            PartitionFetchResult::Error(e) => e.error_type(),
        }
    }
}

/// One-shot fetcher for the latest message from specified partitions.
///
/// Uses `BaseConsumer` with manual assignment (no consumer group coordination).
/// Generic over T (the message payload type) - uses same deserialization
/// as `BatchConsumer` via `KafkaMessage<T>::from_borrowed_message()`.
///
/// Each call creates a fresh, temporary `BaseConsumer` that is dropped after use,
/// ensuring clean resource cleanup and fresh metadata for accurate high watermarks.
#[derive(Clone)]
pub struct HeadFetcher {
    config: ClientConfig,
    timeout: Duration,
}

impl HeadFetcher {
    /// Create a new HeadFetcher with the given Kafka client configuration and timeout.
    ///
    /// The config should NOT include `group.id` - manual assignment is used.
    /// The timeout applies to each Kafka operation (watermark fetch, seek, poll).
    pub fn new(config: ClientConfig, timeout: Duration) -> Self {
        Self { config, timeout }
    }

    /// Fetch the latest available message from each specified partition.
    ///
    /// Creates a temporary `BaseConsumer` for this call only (dropped on return),
    /// ensuring fresh metadata and clean resource cleanup. Queries watermarks
    /// fresh for each partition to get the true latest high watermark.
    ///
    /// # Arguments
    /// * `topic` - The topic to fetch from
    /// * `partitions` - List of partition numbers to fetch head messages from
    ///
    /// # Returns
    /// On success, returns `Vec` of `(partition_number, PartitionFetchResult<T>)`.
    /// On fatal error (consumer creation/assignment failure), returns `Err(HeadFetchError)`.
    pub fn fetch_head_messages<T>(
        &self,
        topic: &str,
        partitions: &[i32],
    ) -> Result<Vec<(i32, PartitionFetchResult<T>)>, HeadFetchError>
    where
        T: for<'de> Deserialize<'de>,
    {
        let start = Instant::now();

        // Create temporary BaseConsumer - dropped at end of function for clean cleanup.
        // Fresh consumer ensures we get latest metadata (no stale cached watermarks).
        let consumer: BaseConsumer = self
            .config
            .create()
            .map_err(HeadFetchError::ConsumerCreation)?;

        // Fetch metadata for the topic to ensure we have fresh partition info
        // This is important for newly created topics where metadata may not be cached
        let _ = consumer.fetch_metadata(Some(topic), self.timeout);

        // Build TopicPartitionList for assignment
        let mut tpl = TopicPartitionList::new();
        for &partition in partitions {
            tpl.add_partition(topic, partition);
        }
        consumer
            .assign(&tpl)
            .map_err(HeadFetchError::PartitionAssignment)?;

        // Poll a few times to trigger consumer internal state initialization.
        // rdkafka needs this to properly set up partition state before seeks.
        // Without this, we get "Erroneous state" errors on subsequent seeks.
        for _ in 0..3 {
            let _ = consumer.poll(Duration::from_millis(100));
        }

        // For each partition, query watermarks fresh and fetch if non-empty
        let mut results = Vec::with_capacity(partitions.len());
        for &partition in partitions {
            let result = self.fetch_single_partition(&consumer, topic, partition);

            // Record per-partition error metrics
            if !result.is_success() && !matches!(result, PartitionFetchResult::Empty) {
                counter!(
                    HEAD_FETCH_ERROR_COUNTER,
                    "topic" => topic.to_string(),
                    "partition" => partition.to_string(),
                    "error_type" => result.result_type()
                )
                .increment(1);
            }

            results.push((partition, result));
        }

        // Record timing metric
        let elapsed_ms = start.elapsed().as_millis() as f64;
        histogram!(HEAD_FETCH_DURATION_HISTOGRAM, "topic" => topic.to_string()).record(elapsed_ms);

        // Consumer is dropped here - connection closed, resources freed
        Ok(results)
    }

    /// Fetch head message from a single partition.
    fn fetch_single_partition<T>(
        &self,
        consumer: &BaseConsumer,
        topic: &str,
        partition: i32,
    ) -> PartitionFetchResult<T>
    where
        T: for<'de> Deserialize<'de>,
    {
        // fetch_watermarks queries broker directly - gets true current high watermark
        let (low, high) = match consumer.fetch_watermarks(topic, partition, self.timeout) {
            Ok(watermarks) => watermarks,
            Err(e) => {
                let error = if is_timeout_error(&e) {
                    HeadFetchError::Timeout {
                        operation: "fetch_watermarks",
                        partition,
                    }
                } else {
                    HeadFetchError::Kafka {
                        operation: "fetch_watermarks",
                        partition,
                        source: e,
                    }
                };
                warn!(
                    topic,
                    partition,
                    error_type = error.error_type(),
                    error = %error,
                    "Failed to fetch watermarks for partition"
                );
                return PartitionFetchResult::Error(error);
            }
        };

        if high <= low {
            // Partition is empty
            return PartitionFetchResult::Empty;
        }

        // Seek to high_watermark - 1 (the last message)
        if let Err(e) = consumer.seek(topic, partition, Offset::Offset(high - 1), self.timeout) {
            let error = if is_timeout_error(&e) {
                HeadFetchError::Timeout {
                    operation: "seek",
                    partition,
                }
            } else {
                HeadFetchError::Kafka {
                    operation: "seek",
                    partition,
                    source: e,
                }
            };
            warn!(
                topic,
                partition,
                offset = high - 1,
                error_type = error.error_type(),
                error = %error,
                "Failed to seek to head offset"
            );
            return PartitionFetchResult::Error(error);
        }

        // Poll once with timeout, deserialize using KafkaMessage<T>
        match consumer.poll(self.timeout) {
            Some(Ok(borrowed_msg)) => {
                match KafkaMessage::<T>::from_borrowed_message(&borrowed_msg) {
                    Ok(kafka_msg) => PartitionFetchResult::Success(kafka_msg),
                    Err(e) => {
                        let error_msg = e.to_string();
                        warn!(
                            topic,
                            partition,
                            error_type = "deserialization_error",
                            error = %e,
                            "Failed to deserialize head message"
                        );
                        PartitionFetchResult::DeserializationError(error_msg)
                    }
                }
            }
            Some(Err(e)) => {
                let error = if is_timeout_error(&e) {
                    HeadFetchError::Timeout {
                        operation: "poll",
                        partition,
                    }
                } else {
                    HeadFetchError::Kafka {
                        operation: "poll",
                        partition,
                        source: e,
                    }
                };
                warn!(
                    topic,
                    partition,
                    error_type = error.error_type(),
                    error = %error,
                    "Error polling partition for head message"
                );
                PartitionFetchResult::Error(error)
            }
            None => {
                // No message returned within timeout (unexpected after seek to valid offset)
                let error = HeadFetchError::Timeout {
                    operation: "poll",
                    partition,
                };
                warn!(
                    topic,
                    partition,
                    error_type = "timeout",
                    "Poll returned no message after seek to head offset"
                );
                PartitionFetchResult::Error(error)
            }
        }
    }
}

/// Check if a KafkaError represents a timeout condition
fn is_timeout_error(e: &KafkaError) -> bool {
    match e {
        KafkaError::Global(code) | KafkaError::MessageConsumption(code) => {
            matches!(
                code,
                rdkafka::types::RDKafkaErrorCode::RequestTimedOut
                    | rdkafka::types::RDKafkaErrorCode::OperationTimedOut
            )
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_head_fetcher_creation() {
        let config = ClientConfig::new();
        let fetcher = HeadFetcher::new(config, Duration::from_secs(10));
        // Just verify it can be created and cloned
        let _cloned = fetcher.clone();
    }

    #[test]
    fn test_head_fetch_error_types() {
        let timeout_err = HeadFetchError::Timeout {
            operation: "poll",
            partition: 0,
        };
        assert!(timeout_err.is_timeout());
        assert_eq!(timeout_err.error_type(), "timeout");

        let kafka_err = HeadFetchError::Kafka {
            operation: "fetch_watermarks",
            partition: 1,
            source: KafkaError::Subscription("test".to_string()),
        };
        assert!(!kafka_err.is_timeout());
        assert_eq!(kafka_err.error_type(), "kafka_error");
    }

    #[test]
    fn test_partition_fetch_result_methods() {
        let success: PartitionFetchResult<String> =
            PartitionFetchResult::DeserializationError("test".to_string());
        assert!(!success.is_success());
        assert!(!success.is_timeout());
        assert_eq!(success.result_type(), "deserialization_error");

        let empty: PartitionFetchResult<String> = PartitionFetchResult::Empty;
        assert!(!empty.is_success());
        assert_eq!(empty.result_type(), "empty");

        let timeout: PartitionFetchResult<String> =
            PartitionFetchResult::Error(HeadFetchError::Timeout {
                operation: "poll",
                partition: 0,
            });
        assert!(timeout.is_timeout());
        assert_eq!(timeout.result_type(), "timeout");
    }
}
