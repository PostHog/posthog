//! Registry of ingestion warning types emitted by Rust services.
//!
//! The `WarningType` enum, its `ALL` list, and `as_str()` are generated at build
//! time (see `build.rs`) from `capture_warning_types.generated.json`, which is
//! mirrored from the Node.js registry — the single source of truth for the warning
//! taxonomy (`nodejs/src/ingestion/common/ingestion-warning-types.ts`). Category and
//! severity are resolved Node-side at serialization time and are not represented here.
//!
//! `from_tag` is a hand-written allowlist mapping capture error tags to warning
//! types: only tags registered here ever produce a warning. Unknown or deliberately
//! excluded tags (auth/transport/server errors, intentional drops like
//! `dropped_performance_event`) map to `None` and emit nothing. The
//! `from_tag_round_trips_every_registered_type` test guarantees every generated
//! variant has a `from_tag` arm, so adding a capture type in Node.js forces the
//! matching Rust mapping here.

// Brings in `pub enum WarningType`, `WarningType::ALL`, and `WarningType::as_str`.
include!(concat!(env!("OUT_DIR"), "/warning_types.rs"));

impl WarningType {
    /// Map a capture error tag (`v1::Error::tag()` / per-event drop detail) to a
    /// registered warning type. Returns `None` for anything not on the allowlist —
    /// callers emit nothing in that case.
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

    /// Pipeline step recorded in the details JSON (`pipelineStep`). Every registered
    /// capture type is a validation-stage drop, so they share this step.
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
        // Guards the hand-written `from_tag` against the generated enum: a new
        // variant mirrored from Node.js without a matching `from_tag` arm fails here.
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
}
