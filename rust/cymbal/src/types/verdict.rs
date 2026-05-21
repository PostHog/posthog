use serde::{Deserialize, Serialize};

use crate::error::{EventError, UnhandledError};
use crate::types::event::AnyEvent;

/// Per-event outcome of `/process`. The full response is a `Vec<EventVerdict>`
/// aligned 1:1 with the input batch's events.
///
/// This is the contract surface between cymbal and the ingestion pipeline.
/// Cymbal commits to producing a verdict for every event within the request
/// deadline; the pipeline routes each event according to its verdict without
/// any classification logic of its own.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "lowercase")]
pub enum EventVerdict {
    /// Cymbal symbolicated the event; the updated event follows. The
    /// pipeline forwards downstream as normal.
    Process { event: Box<AnyEvent> },

    /// Event was suppressed at the cymbal layer (by-design no-op). The
    /// pipeline must not forward it downstream.
    Drop { reason: DropReason },

    /// Cymbal couldn't verdict this event in this attempt. The pipeline
    /// should retry; per-event retry exhaustion is the pipeline's concern
    /// (routes to overflow / DLQ by lane).
    ///
    /// `Retry` is the safe-by-default verdict for any failure cymbal cannot
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

/// Why cymbal couldn't verdict an event in this attempt.
///
/// Variants here represent ambiguous-or-cymbal-side failures: cymbal cannot
/// tell whether the event data or cymbal itself is to blame, so the safe
/// answer is retry. If cymbal's own resources are the predominant cause of
/// retries across recent traffic, cymbal will additionally escalate
/// subsequent requests to HTTP 429.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetryReason {
    /// Cymbal's per-event deadline elapsed before producing a verdict.
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

impl EventVerdict {
    /// Short label used for metrics. Matches the JSON `status` value.
    pub fn status_label(&self) -> &'static str {
        match self {
            EventVerdict::Process { .. } => "process",
            EventVerdict::Drop { .. } => "drop",
            EventVerdict::Retry { .. } => "retry",
            EventVerdict::Dlq { .. } => "dlq",
        }
    }

    /// Short label for the verdict's reason (or "ok" for `Process`). Used
    /// to label metric counters so operators can see *why* events landed in
    /// each verdict.
    pub fn reason_label(&self) -> &'static str {
        match self {
            EventVerdict::Process { .. } => "ok",
            EventVerdict::Drop { reason } => reason.label(),
            EventVerdict::Retry { reason, .. } => reason.label(),
            EventVerdict::Dlq { reason } => reason.label(),
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

/// Classify a per-event `EventError` into the verdict the contract demands.
///
/// `EventError` variants are cymbal's own affirmative classifications of an
/// event's state — these are the cases where cymbal can name the outcome,
/// so they map directly to terminal verdicts (`Drop` or `Dlq`).
impl From<EventError> for EventVerdict {
    fn from(err: EventError) -> Self {
        match err {
            EventError::Suppressed(_) => EventVerdict::Drop {
                reason: DropReason::IssueSuppressed,
            },
            EventError::SuppressedByRule(_) => EventVerdict::Drop {
                reason: DropReason::SuppressedByRule,
            },
            EventError::WrongEventType(_, _) => EventVerdict::Dlq {
                reason: DlqReason::WrongEventType,
            },
            EventError::InvalidProperties(_, _) => EventVerdict::Dlq {
                reason: DlqReason::InvalidProperties,
            },
            EventError::EmptyExceptionList(_) => EventVerdict::Dlq {
                reason: DlqReason::EmptyExceptionList,
            },
        }
    }
}

/// Classify an `UnhandledError` into a verdict.
///
/// `UnhandledError` represents conditions cymbal cannot affirmatively call
/// event-broken — Kafka/Redis/SQL/S3 failures, serde mishaps, etc. The
/// honest verdict is always `Retry`; cymbal does not assert the event is
/// broken because we cannot distinguish event-caused failures from
/// cymbal-side or downstream-side ones at this level.
impl From<UnhandledError> for EventVerdict {
    fn from(err: UnhandledError) -> Self {
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
            // misconfiguration. Retry is the safe-by-default verdict per the
            // contract.
            UnhandledError::SerdeError(_)
            | UnhandledError::ConfigError(_)
            | UnhandledError::Other(_) => RetryReason::UnhandledProcessingError,
        };
        EventVerdict::Retry {
            reason,
            retry_after_ms: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    #[test]
    fn event_error_maps_to_terminal_verdicts() {
        let id = Uuid::nil();

        let suppressed: EventVerdict = EventError::Suppressed(id).into();
        assert!(matches!(
            suppressed,
            EventVerdict::Drop {
                reason: DropReason::IssueSuppressed
            }
        ));

        let suppressed_rule: EventVerdict = EventError::SuppressedByRule(id).into();
        assert!(matches!(
            suppressed_rule,
            EventVerdict::Drop {
                reason: DropReason::SuppressedByRule
            }
        ));

        let wrong_type: EventVerdict = EventError::WrongEventType("foo".into(), id).into();
        assert!(matches!(
            wrong_type,
            EventVerdict::Dlq {
                reason: DlqReason::WrongEventType
            }
        ));

        let empty: EventVerdict = EventError::EmptyExceptionList(id).into();
        assert!(matches!(
            empty,
            EventVerdict::Dlq {
                reason: DlqReason::EmptyExceptionList
            }
        ));
    }

    #[test]
    fn unhandled_error_always_maps_to_retry() {
        // Infrastructure dependency → DownstreamTransient.
        let redis: EventVerdict = UnhandledError::Other("simulating redis blip".into()).into();
        assert!(matches!(redis, EventVerdict::Retry { .. }));

        // SerdeError / Other → UnhandledProcessingError. Both are Retry —
        // never Dlq — because cymbal can't tell whether the event or
        // cymbal itself is to blame.
        let serde_err: EventVerdict = UnhandledError::Other("serde failure".into()).into();
        match serde_err {
            EventVerdict::Retry {
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
    fn verdict_status_and_reason_labels_match_serialization() {
        let drop = EventVerdict::Drop {
            reason: DropReason::IssueSuppressed,
        };
        assert_eq!(drop.status_label(), "drop");
        assert_eq!(drop.reason_label(), "issue_suppressed");

        let retry = EventVerdict::Retry {
            reason: RetryReason::DeadlineExceeded,
            retry_after_ms: None,
        };
        assert_eq!(retry.status_label(), "retry");
        assert_eq!(retry.reason_label(), "deadline_exceeded");

        let dlq = EventVerdict::Dlq {
            reason: DlqReason::WrongEventType,
        };
        assert_eq!(dlq.status_label(), "dlq");
        assert_eq!(dlq.reason_label(), "wrong_event_type");
    }

    #[test]
    fn drop_serializes_with_status_and_reason_tags() {
        let drop = EventVerdict::Drop {
            reason: DropReason::IssueSuppressed,
        };
        let json = serde_json::to_value(&drop).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "status": "drop",
                "reason": "issue_suppressed"
            })
        );
    }

    #[test]
    fn retry_serializes_with_optional_retry_after_ms() {
        let no_hint = EventVerdict::Retry {
            reason: RetryReason::SourcemapFetchTimeout,
            retry_after_ms: None,
        };
        let json = serde_json::to_value(&no_hint).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "status": "retry",
                "reason": "sourcemap_fetch_timeout"
            })
        );

        let with_hint = EventVerdict::Retry {
            reason: RetryReason::DownstreamTransient,
            retry_after_ms: Some(500),
        };
        let json = serde_json::to_value(&with_hint).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "status": "retry",
                "reason": "downstream_transient",
                "retry_after_ms": 500
            })
        );
    }
}
