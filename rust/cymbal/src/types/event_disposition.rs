use serde::{Deserialize, Serialize};

use crate::error::UnhandledError;
use crate::types::event::AnyEvent;

/// Per-event routing decision from `/v2/resolve`. The full response is a `Vec<EventDisposition>`
/// aligned 1:1 with the input batch's events.
///
/// This is the contract surface between cymbal and the ingestion pipeline.
/// Cymbal commits to producing a disposition for every event within the request
/// deadline; the pipeline routes each event according to its disposition without
/// any classification logic of its own.
///
/// Wire examples:
///
/// ```json
/// { "action": "forward", "event": { "event": "$exception" } }
/// { "action": "drop", "reason": "issue_suppressed" }
/// { "action": "retry", "reason": "deadline_exceeded" }
/// { "action": "dlq", "reason": "invalid_properties" }
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
pub enum EventDisposition {
    /// Cymbal symbolicated the event; the updated event follows. The
    /// pipeline forwards downstream as normal.
    Forward { event: Box<AnyEvent> },

    /// Event was suppressed at the cymbal layer (by-design no-op). The
    /// pipeline must not forward it downstream.
    Drop { reason: DropReason },

    /// Cymbal couldn't decide where this event should go in this attempt. The pipeline
    /// should retry; per-event retry exhaustion is the pipeline's concern
    /// (routes to overflow / DLQ by lane).
    ///
    /// `Retry` is the safe-by-default disposition for any failure cymbal cannot
    /// affirmatively classify as broken event data — including panics,
    /// timeouts, and any transient infrastructure failure.
    Retry {
        reason: RetryReason,
        #[serde(skip_serializing_if = "Option::is_none")]
        retry_after_ms: Option<u64>,
    },

    /// Event is affirmatively broken — retrying it would not help. The
    /// pipeline must route to DLQ without further attempts. Reserved for
    /// cases cymbal can name with certainty (parse failures, schema
    /// violations, etc.).
    ///
    /// `/v2/resolve` currently preserves the legacy `/process` behavior for
    /// handled event errors by forwarding the original event with
    /// `$cymbal_errors` attached. This variant is reserved for future cases
    /// where Cymbal can safely make a terminal DLQ decision.
    Dlq { reason: DlqReason },
}

/// Why an event was dropped at cymbal.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DropReason {
    /// The event's issue is suppressed by issue status.
    IssueSuppressed,
    /// The event's issue is suppressed by a suppression rule.
    SuppressedByRule,
}

/// Why cymbal couldn't disposition an event in this attempt.
///
/// Variants here represent ambiguous-or-cymbal-side failures: cymbal cannot
/// tell whether the event data or cymbal itself is to blame, so the safe
/// answer is retry. If cymbal's own resources are the predominant cause of
/// retries across recent traffic, cymbal will additionally escalate
/// subsequent requests to HTTP 429.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetryReason {
    /// Cymbal's per-event deadline elapsed before producing a disposition.
    DeadlineExceeded,
    /// A downstream sourcemap fetch timed out.
    SourcemapFetchTimeout,
    /// Cymbal threw an unhandled exception (panic or wrapped error) while
    /// processing this event. The pipeline should retry; if the failure
    /// persists across retries, it routes to overflow / DLQ.
    UnhandledProcessingError,
    /// A transient infrastructure dependency was unavailable (Kafka, Redis,
    /// SQL, S3, etc.).
    DownstreamTransient,
}

/// Why an event was determined to be broken.
///
/// Cymbal must only emit `Dlq` for events it can affirmatively call broken.
/// Anything ambiguous — including unhandled errors and panics during
/// processing — must use `Retry` instead.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DlqReason {
    /// The event type is not one cymbal handles.
    WrongEventType,
    /// The event's properties failed schema deserialization.
    InvalidProperties,
    /// The event's exception list was empty — nothing to process.
    EmptyExceptionList,
}

impl EventDisposition {
    /// Classify an `UnhandledError` into a disposition.
    ///
    /// `UnhandledError` represents conditions cymbal cannot affirmatively call
    /// event-broken — Kafka/Redis/SQL/S3 failures, serde mishaps, etc. The
    /// honest disposition is always `Retry`; cymbal does not assert the event
    /// is broken because we cannot distinguish event-caused failures from
    /// cymbal-side or downstream-side ones at this level.
    pub fn from_unhandled_error(err: UnhandledError) -> Self {
        let reason = match err {
            // Kafka / SQL / S3 / Redis are infrastructure dependencies; if
            // they hiccup we'd rather have the pipeline retry than DLQ the
            // event.
            UnhandledError::KafkaError(_)
            | UnhandledError::KafkaProduceError(_)
            | UnhandledError::SqlxError(_)
            | UnhandledError::S3Error(_)
            | UnhandledError::ByteStreamError(_)
            | UnhandledError::RedisError(_) => RetryReason::DownstreamTransient,
            // SerdeError / ConfigError / Other are ambiguous — they could be
            // cymbal bugs, event-data quirks we don't classify, or
            // misconfiguration. Retry is the safe-by-default disposition per
            // the contract.
            UnhandledError::SerdeError(_)
            | UnhandledError::ConfigError(_)
            | UnhandledError::Other(_) => RetryReason::UnhandledProcessingError,
        };
        EventDisposition::Retry {
            reason,
            retry_after_ms: None,
        }
    }

    /// Short label used for metrics. Matches the JSON `action` value.
    pub fn action_label(&self) -> &'static str {
        match self {
            EventDisposition::Forward { .. } => "forward",
            EventDisposition::Drop { .. } => "drop",
            EventDisposition::Retry { .. } => "retry",
            EventDisposition::Dlq { .. } => "dlq",
        }
    }

    /// Short label for the disposition's reason (or "ok" for `Forward`). Used
    /// to label metric counters so operators can see *why* events landed in
    /// each disposition.
    pub fn reason_label(&self) -> &'static str {
        match self {
            EventDisposition::Forward { .. } => "ok",
            EventDisposition::Drop { reason } => reason.label(),
            EventDisposition::Retry { reason, .. } => reason.label(),
            EventDisposition::Dlq { reason } => reason.label(),
        }
    }
}

impl DropReason {
    pub fn label(&self) -> &'static str {
        match self {
            DropReason::IssueSuppressed => "issue_suppressed",
            DropReason::SuppressedByRule => "suppressed_by_rule",
        }
    }
}

impl RetryReason {
    pub fn label(&self) -> &'static str {
        match self {
            RetryReason::DeadlineExceeded => "deadline_exceeded",
            RetryReason::SourcemapFetchTimeout => "sourcemap_fetch_timeout",
            RetryReason::UnhandledProcessingError => "unhandled_processing_error",
            RetryReason::DownstreamTransient => "downstream_transient",
        }
    }

    /// Whether this retry reason was caused by cymbal's own state (pool,
    /// queue, internal deadline) versus an event-specific or downstream
    /// condition. Used by the self-health tracker to decide when to escalate
    /// to HTTP 429.
    pub fn is_cymbal_caused(&self) -> bool {
        match self {
            RetryReason::DeadlineExceeded => true,
            RetryReason::UnhandledProcessingError => true,
            RetryReason::SourcemapFetchTimeout => false,
            RetryReason::DownstreamTransient => false,
        }
    }
}

impl DlqReason {
    pub fn label(&self) -> &'static str {
        match self {
            DlqReason::WrongEventType => "wrong_event_type",
            DlqReason::InvalidProperties => "invalid_properties",
            DlqReason::EmptyExceptionList => "empty_exception_list",
        }
    }
}

impl From<UnhandledError> for EventDisposition {
    fn from(err: UnhandledError) -> Self {
        Self::from_unhandled_error(err)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unhandled_error_always_maps_to_retry() {
        // Ambiguous errors are still retryable — never DLQ.
        let other: EventDisposition =
            UnhandledError::Other("simulating processing blip".into()).into();
        assert!(matches!(other, EventDisposition::Retry { .. }));

        // SerdeError / Other → UnhandledProcessingError. Both are Retry —
        // never Dlq — because cymbal can't tell whether the event or
        // cymbal itself is to blame.
        let serde_err: EventDisposition = UnhandledError::Other("serde failure".into()).into();
        match serde_err {
            EventDisposition::Retry {
                reason: RetryReason::UnhandledProcessingError,
                retry_after_ms: None,
            } => {}
            other => panic!("expected Retry/UnhandledProcessingError, got {:?}", other),
        }
    }

    #[test]
    fn cymbal_caused_retries_are_flagged() {
        assert!(RetryReason::DeadlineExceeded.is_cymbal_caused());
        assert!(RetryReason::UnhandledProcessingError.is_cymbal_caused());
        assert!(!RetryReason::SourcemapFetchTimeout.is_cymbal_caused());
        assert!(!RetryReason::DownstreamTransient.is_cymbal_caused());
    }

    #[test]
    fn disposition_action_and_reason_labels_match_serialization() {
        let drop = EventDisposition::Drop {
            reason: DropReason::IssueSuppressed,
        };
        assert_eq!(drop.action_label(), "drop");
        assert_eq!(drop.reason_label(), "issue_suppressed");

        let retry = EventDisposition::Retry {
            reason: RetryReason::DeadlineExceeded,
            retry_after_ms: None,
        };
        assert_eq!(retry.action_label(), "retry");
        assert_eq!(retry.reason_label(), "deadline_exceeded");

        let dlq = EventDisposition::Dlq {
            reason: DlqReason::WrongEventType,
        };
        assert_eq!(dlq.action_label(), "dlq");
        assert_eq!(dlq.reason_label(), "wrong_event_type");
    }

    #[test]
    fn drop_serializes_with_action_and_reason_tags() {
        let drop = EventDisposition::Drop {
            reason: DropReason::IssueSuppressed,
        };
        let json = serde_json::to_value(&drop).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "action": "drop",
                "reason": "issue_suppressed"
            })
        );
    }

    #[test]
    fn retry_serializes_with_optional_retry_after_ms() {
        let no_hint = EventDisposition::Retry {
            reason: RetryReason::SourcemapFetchTimeout,
            retry_after_ms: None,
        };
        let json = serde_json::to_value(&no_hint).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "action": "retry",
                "reason": "sourcemap_fetch_timeout"
            })
        );

        let with_hint = EventDisposition::Retry {
            reason: RetryReason::DownstreamTransient,
            retry_after_ms: Some(500),
        };
        let json = serde_json::to_value(&with_hint).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "action": "retry",
                "reason": "downstream_transient",
                "retry_after_ms": 500
            })
        );
    }
}
