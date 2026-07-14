//! Registry of ingestion warning types emitted by Rust services, mirroring the
//! Node.js registry conventions (`nodejs/src/ingestion/common/ingestion-warnings.ts`):
//! `category` classifies the surface area, `severity` is `error` when data was
//! dropped/lost and `warning` when it was mutated/degraded.
//!
//! `from_tag` is an explicit allowlist: only tags registered here ever produce a
//! warning. Unknown or deliberately excluded tags (auth/transport/server errors,
//! intentional drops like `dropped_performance_event`) map to `None` and emit
//! nothing.

/// A warning type known to the v2 ingestion warnings pipeline.
///
/// Every variant's `as_str()` doubles as the `type` field of the produced
/// message and as the `type` metric label, so values must be stable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WarningType {
    // Per-event validation drops (capture v1 `validate_events`).
    MissingEventName,
    EventNameTooLong,
    MissingDistinctId,
    DistinctIdTooLarge,
    InvalidEventTimestamp,
    MalformedEventProperties,
    InvalidOptions,
    // Whole-batch validation aborts (capture v1 `validate_batch` / uuid checks).
    EmptyBatch,
    InvalidBatch,
    MissingEventUuid,
    InvalidEventUuid,
    DuplicateEventUuid,
}

impl WarningType {
    /// All registered warning types, for exhaustive tests.
    pub const ALL: [WarningType; 12] = [
        WarningType::MissingEventName,
        WarningType::EventNameTooLong,
        WarningType::MissingDistinctId,
        WarningType::DistinctIdTooLarge,
        WarningType::InvalidEventTimestamp,
        WarningType::MalformedEventProperties,
        WarningType::InvalidOptions,
        WarningType::EmptyBatch,
        WarningType::InvalidBatch,
        WarningType::MissingEventUuid,
        WarningType::InvalidEventUuid,
        WarningType::DuplicateEventUuid,
    ];

    /// Map a capture error tag (`v1::Error::tag()` / per-event drop detail)
    /// to a registered warning type. Returns `None` for anything not on the
    /// allowlist — callers emit nothing in that case.
    pub fn from_tag(tag: &str) -> Option<Self> {
        match tag {
            "missing_event_name" => Some(Self::MissingEventName),
            "event_name_too_long" => Some(Self::EventNameTooLong),
            "missing_distinct_id" => Some(Self::MissingDistinctId),
            "distinct_id_too_large" => Some(Self::DistinctIdTooLarge),
            "invalid_event_timestamp" => Some(Self::InvalidEventTimestamp),
            "malformed_event_properties" => Some(Self::MalformedEventProperties),
            "invalid_options" => Some(Self::InvalidOptions),
            "empty_batch" => Some(Self::EmptyBatch),
            "invalid_batch" => Some(Self::InvalidBatch),
            "missing_event_uuid" => Some(Self::MissingEventUuid),
            "invalid_event_uuid" => Some(Self::InvalidEventUuid),
            "duplicate_event_uuid" => Some(Self::DuplicateEventUuid),
            _ => None,
        }
    }

    /// The message/metric `type` string. Matches the originating error tag 1:1.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::MissingEventName => "missing_event_name",
            Self::EventNameTooLong => "event_name_too_long",
            Self::MissingDistinctId => "missing_distinct_id",
            Self::DistinctIdTooLarge => "distinct_id_too_large",
            Self::InvalidEventTimestamp => "invalid_event_timestamp",
            Self::MalformedEventProperties => "malformed_event_properties",
            Self::InvalidOptions => "invalid_options",
            Self::EmptyBatch => "empty_batch",
            Self::InvalidBatch => "invalid_batch",
            Self::MissingEventUuid => "missing_event_uuid",
            Self::InvalidEventUuid => "invalid_event_uuid",
            Self::DuplicateEventUuid => "duplicate_event_uuid",
        }
    }

    /// Warning category (`size | merge | event | transformation | replay`).
    /// All capture validation failures concern individual event payloads.
    pub const fn category(self) -> &'static str {
        "event"
    }

    /// `error` = data was dropped/lost; `warning` = data was mutated/degraded.
    /// Every registered capture type drops events, so all are `error`.
    pub const fn severity(self) -> &'static str {
        "error"
    }

    /// Pipeline step recorded in the details JSON (`pipelineStep`).
    pub const fn pipeline_step(self) -> &'static str {
        "capture_validation"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[test]
    fn from_tag_round_trips_every_registered_type() {
        for warning in WarningType::ALL {
            assert_eq!(
                WarningType::from_tag(warning.as_str()),
                Some(warning),
                "tag {} must round-trip",
                warning.as_str()
            );
        }
    }

    // Excluded on purpose: intentional drops, auth/transport/server errors, and
    // post-validation drops are not data-quality signals for the v2 surface.
    #[rstest]
    #[case::intentional_drop("dropped_performance_event")]
    #[case::auth("invalid_api_token")]
    #[case::auth_missing("missing_authorization")]
    #[case::transport("payload_too_large")]
    #[case::transport_decoding("request_decoding_error")]
    #[case::transport_parsing("request_parsing_error")]
    #[case::transport_encoding("unsupported_content_encoding")]
    #[case::timeout("request_timeout")]
    #[case::server("internal_error")]
    #[case::server_unavailable("service_unavailable")]
    #[case::billing("billing_limit_exceeded")]
    #[case::post_validation("event_restriction")]
    #[case::sink("rejected")]
    #[case::unknown("some_future_tag")]
    #[case::empty("")]
    fn from_tag_rejects_unregistered_tags(#[case] tag: &str) {
        assert_eq!(
            WarningType::from_tag(tag),
            None,
            "tag {tag:?} must not emit"
        );
    }

    #[test]
    fn metadata_is_capture_validation_error() {
        for warning in WarningType::ALL {
            assert_eq!(warning.category(), "event");
            assert_eq!(warning.severity(), "error");
            assert_eq!(warning.pipeline_step(), "capture_validation");
        }
    }

    /// Guards the cross-language contract: warnings are emitted as
    /// `$$client_ingestion_warning` envelopes that the Node.js `clientwarnings`
    /// consumer types from its own registry. A Rust type absent there silently
    /// falls back to the generic `client_ingestion_warning` type, so every
    /// `WarningType` must exist as a key in nodejs `INGESTION_WARNING_TYPES`.
    #[test]
    fn every_rust_type_is_registered_in_nodejs() {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../nodejs/src/ingestion/common/ingestion-warnings.ts"
        );
        let src = std::fs::read_to_string(path)
            .unwrap_or_else(|e| panic!("read nodejs registry at {path}: {e}"));
        // Registry entries look like `    missing_event_name: { category: ... }`,
        // so a type appearing as a `key:` prefix means it is registered — this
        // won't trip on the same string inside a comment or value.
        let keys: std::collections::HashSet<&str> = src
            .lines()
            .filter_map(|line| line.trim().split_once(':').map(|(key, _)| key.trim()))
            .collect();
        for warning in WarningType::ALL {
            assert!(
                keys.contains(warning.as_str()),
                "Rust WarningType `{}` is not registered in nodejs INGESTION_WARNING_TYPES; \
                 the clientwarnings consumer would fall back to the generic type",
                warning.as_str()
            );
        }
    }
}
