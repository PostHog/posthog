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
    SerializationFailed(String),
    Produce(ProduceError),
    Timeout,
    TaskPanicked,
}

impl KafkaSinkError {
    pub fn outcome(&self) -> Outcome {
        match self {
            Self::SinkUnavailable => Outcome::RetriableError,
            Self::SerializationFailed(_) => Outcome::FatalError,
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
            Self::SerializationFailed(_) => "serialization_failed",
            Self::Produce(e) => e.as_tag(),
            Self::Timeout => "timeout",
            Self::TaskPanicked => "task_panicked",
        }
    }

    pub fn detail(&self) -> Cow<'_, str> {
        match self {
            Self::SinkUnavailable => Cow::Borrowed("sink unavailable"),
            Self::SerializationFailed(m) => Cow::Owned(format!("serialization failed: {m}")),
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
