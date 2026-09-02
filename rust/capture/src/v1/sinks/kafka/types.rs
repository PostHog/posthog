use std::borrow::Cow;

use chrono::{DateTime, Utc};
use uuid::Uuid;

use super::producer::ProduceError;
use crate::v1::sinks::types::{Outcome, SinkResult};

// ---------------------------------------------------------------------------
// error_code_tag
// ---------------------------------------------------------------------------

/// Lives in `common_kafka::error` so producers outside capture share one error
/// label vocabulary. Re-exported here because this is the path the sink's
/// callers and DESIGN.md know it by.
pub use common_kafka::error::error_code_tag;

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
