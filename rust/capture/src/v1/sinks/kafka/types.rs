use std::borrow::Cow;

use chrono::{DateTime, Utc};
use rdkafka::error::RDKafkaErrorCode;
use uuid::Uuid;

use super::producer::ProduceError;
use crate::v1::sinks::types::{Outcome, SinkResult};

// ---------------------------------------------------------------------------
// error_code_tag
// ---------------------------------------------------------------------------

/// Stable, low-cardinality snake_case tag for an RDKafkaErrorCode.
/// Usable anywhere -- producer, sink, handler, logging.
pub fn error_code_tag(code: RDKafkaErrorCode) -> &'static str {
    match code {
        RDKafkaErrorCode::QueueFull => "queue_full",
        RDKafkaErrorCode::MessageSizeTooLarge => "message_size_too_large",
        RDKafkaErrorCode::MessageTimedOut => "message_timed_out",
        RDKafkaErrorCode::UnknownTopicOrPartition => "unknown_topic_or_partition",
        RDKafkaErrorCode::TopicAuthorizationFailed => "topic_authorization_failed",
        RDKafkaErrorCode::ClusterAuthorizationFailed => "cluster_authorization_failed",
        RDKafkaErrorCode::InvalidMessage => "invalid_message",
        RDKafkaErrorCode::InvalidMessageSize => "invalid_message_size",
        RDKafkaErrorCode::NotLeaderForPartition => "not_leader_for_partition",
        RDKafkaErrorCode::RequestTimedOut => "request_timed_out",
        // Broker/idempotent-producer codes from delivery reports
        RDKafkaErrorCode::NotEnoughReplicas => "not_enough_replicas",
        RDKafkaErrorCode::NotEnoughReplicasAfterAppend => "not_enough_replicas_after_append",
        RDKafkaErrorCode::OperationNotAttempted => "operation_not_attempted",
        RDKafkaErrorCode::OutOfOrderSequenceNumber => "out_of_order_sequence_number",
        RDKafkaErrorCode::DuplicateSequenceNumber => "duplicate_sequence_number",
        RDKafkaErrorCode::NetworkException => "network_exception",
        RDKafkaErrorCode::CoordinatorLoadInProgress => "coordinator_load_in_progress",
        RDKafkaErrorCode::CoordinatorNotAvailable => "coordinator_not_available",
        // Transport/infra codes surfaced by ClientContext::error() callback
        RDKafkaErrorCode::BrokerTransportFailure => "broker_transport_failure",
        RDKafkaErrorCode::AllBrokersDown => "all_brokers_down",
        RDKafkaErrorCode::Resolve => "resolve",
        RDKafkaErrorCode::Authentication => "authentication",
        RDKafkaErrorCode::SaslAuthenticationFailed => "sasl_authentication_failed",
        _ => "rdkafka_other",
    }
}

// ---------------------------------------------------------------------------
// KafkaSinkError
// ---------------------------------------------------------------------------

/// Full-fidelity error enum capturing every failure mode in the Kafka sink.
/// `SinkResult` trait methods derive their output from this.
///
/// Note: "sink not found" is handled at the Router level (`RouterError`),
/// not here. This enum only covers failures within a single configured sink.
#[derive(Debug)]
pub enum KafkaSinkError {
    SinkUnavailable,
    Produce(ProduceError),
    Timeout,
    TaskPanicked,
}

impl KafkaSinkError {
    pub fn outcome(&self) -> Outcome {
        match self {
            Self::SinkUnavailable => Outcome::RetriableError,
            Self::Produce(e) => {
                if e.is_retriable() {
                    Outcome::RetriableError
                } else {
                    Outcome::FatalError
                }
            }
            Self::Timeout => Outcome::Timeout,
            Self::TaskPanicked => Outcome::RetriableError,
        }
    }

    pub fn as_tag(&self) -> &'static str {
        match self {
            Self::SinkUnavailable => "sink_unavailable",
            Self::Produce(e) => e.as_tag(),
            Self::Timeout => "timeout",
            Self::TaskPanicked => "task_panicked",
        }
    }

    pub fn detail(&self) -> Cow<'_, str> {
        match self {
            Self::SinkUnavailable => Cow::Borrowed("sink unavailable"),
            Self::Produce(e) => Cow::Owned(format!("{e}")),
            Self::Timeout => Cow::Borrowed("produce timeout"),
            Self::TaskPanicked => Cow::Borrowed("task panicked during delivery"),
        }
    }
}

// ---------------------------------------------------------------------------
// KafkaResult
// ---------------------------------------------------------------------------

/// Kafka-specific implementation of [`SinkResult`]. Outcome is derived from
/// the error -- no explicit outcome field.
#[derive(Debug)]
pub struct KafkaResult {
    uuid: Uuid,
    error: Option<KafkaSinkError>,
    enqueued_at: DateTime<Utc>,
    completed_at: Option<DateTime<Utc>>,
}

impl KafkaResult {
    #[allow(dead_code)]
    pub(crate) fn ok(uuid: Uuid, enqueued_at: DateTime<Utc>) -> Self {
        Self {
            uuid,
            error: None,
            enqueued_at,
            completed_at: None,
        }
    }

    #[allow(dead_code)]
    pub(crate) fn err(uuid: Uuid, error: KafkaSinkError, enqueued_at: DateTime<Utc>) -> Self {
        Self {
            uuid,
            error: Some(error),
            enqueued_at,
            completed_at: None,
        }
    }

    pub(crate) fn with_completed_at(mut self, t: DateTime<Utc>) -> Self {
        self.completed_at = Some(t);
        self
    }

    pub fn error(&self) -> Option<&KafkaSinkError> {
        self.error.as_ref()
    }
}

impl SinkResult for KafkaResult {
    fn key(&self) -> Uuid {
        self.uuid
    }

    fn outcome(&self) -> Outcome {
        match &self.error {
            None => Outcome::Success,
            Some(e) => e.outcome(),
        }
    }

    fn cause(&self) -> Option<&'static str> {
        self.error.as_ref().map(|e| e.as_tag())
    }

    fn detail(&self) -> Option<Cow<'_, str>> {
        self.error.as_ref().map(|e| e.detail())
    }

    fn elapsed(&self) -> Option<std::time::Duration> {
        self.completed_at
            .and_then(|t| t.signed_duration_since(self.enqueued_at).to_std().ok())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[rstest::rstest]
    #[case(RDKafkaErrorCode::QueueFull, "queue_full")]
    #[case(RDKafkaErrorCode::MessageSizeTooLarge, "message_size_too_large")]
    #[case(RDKafkaErrorCode::MessageTimedOut, "message_timed_out")]
    #[case(
        RDKafkaErrorCode::UnknownTopicOrPartition,
        "unknown_topic_or_partition"
    )]
    #[case(
        RDKafkaErrorCode::TopicAuthorizationFailed,
        "topic_authorization_failed"
    )]
    #[case(
        RDKafkaErrorCode::ClusterAuthorizationFailed,
        "cluster_authorization_failed"
    )]
    #[case(RDKafkaErrorCode::InvalidMessage, "invalid_message")]
    #[case(RDKafkaErrorCode::InvalidMessageSize, "invalid_message_size")]
    #[case(RDKafkaErrorCode::NotLeaderForPartition, "not_leader_for_partition")]
    #[case(RDKafkaErrorCode::RequestTimedOut, "request_timed_out")]
    #[case(RDKafkaErrorCode::NotEnoughReplicas, "not_enough_replicas")]
    #[case(
        RDKafkaErrorCode::NotEnoughReplicasAfterAppend,
        "not_enough_replicas_after_append"
    )]
    #[case(RDKafkaErrorCode::OperationNotAttempted, "operation_not_attempted")]
    #[case(
        RDKafkaErrorCode::OutOfOrderSequenceNumber,
        "out_of_order_sequence_number"
    )]
    #[case(RDKafkaErrorCode::DuplicateSequenceNumber, "duplicate_sequence_number")]
    #[case(RDKafkaErrorCode::NetworkException, "network_exception")]
    #[case(
        RDKafkaErrorCode::CoordinatorLoadInProgress,
        "coordinator_load_in_progress"
    )]
    #[case(RDKafkaErrorCode::CoordinatorNotAvailable, "coordinator_not_available")]
    #[case(RDKafkaErrorCode::BrokerTransportFailure, "broker_transport_failure")]
    #[case(RDKafkaErrorCode::AllBrokersDown, "all_brokers_down")]
    #[case(RDKafkaErrorCode::Resolve, "resolve")]
    #[case(RDKafkaErrorCode::Authentication, "authentication")]
    #[case(
        RDKafkaErrorCode::SaslAuthenticationFailed,
        "sasl_authentication_failed"
    )]
    fn error_code_tag_named_variants(#[case] code: RDKafkaErrorCode, #[case] expected: &str) {
        assert_eq!(error_code_tag(code), expected);
    }

    #[rstest::rstest]
    #[case(RDKafkaErrorCode::Unknown)]
    #[case(RDKafkaErrorCode::OffsetOutOfRange)]
    #[case(RDKafkaErrorCode::GroupAuthorizationFailed)]
    fn error_code_tag_unlisted_codes_fall_through(#[case] code: RDKafkaErrorCode) {
        assert_eq!(error_code_tag(code), "rdkafka_other");
    }
}
