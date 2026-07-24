//! Registry of ingestion warning types emitted by Rust services.
//!
//! The `WarningType` enum — every registered type with its `as_str()` tag and
//! registry-declared `category()`/`severity()` — is generated at build time (see
//! `build.rs`) from `warning_types.generated.json`, which mirrors the whole
//! Node.js registry, the single source of truth for the warning taxonomy
//! (`nodejs/src/ingestion/common/ingestion-warning-types.ts`). The taxonomy is
//! producer-agnostic: which service emits which type is not registry data — each
//! producer references the variants it emits, and the message's `source` field
//! records who said it.
//!
//! `from_tag` is a hand-written allowlist mapping capture error tags to warning
//! types: only tags registered here ever produce a warning. Unknown or
//! deliberately excluded tags (auth/transport/server errors, intentional drops
//! like `dropped_performance_event`) map to `None` and emit nothing. The
//! allowlist's domain is welded by test to the registry's `captureProduced`
//! flags — the Node consumer's trust allowlist for the capture envelope —
//! since skew in either direction silently drops warnings: a flagged type
//! without an arm is never emitted, and an arm without the flag is emitted
//! but rejected at the consumer. An arm for a type removed from the registry
//! stops compiling.

// Brings in `pub enum WarningType` with `ALL`, `as_str`, `category`, and
// `severity`.
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[test]
    fn from_tag_domain_equals_the_capture_trust_allowlist() {
        // Two hand-maintained copies of "the types capture emits" must stay
        // equal: the `from_tag` arms here (the emit allowlist) and the
        // registry's `captureProduced` flags (the Node consumer's trust
        // allowlist, carried through the artifact). Skew fails silently in
        // production in either direction — a flagged type without an arm is
        // never emitted; an arm without the flag is emitted and then
        // rejected at the consumer's trust check. Comparing the variant
        // itself (not just presence) also pins each arm to the right type,
        // so a mis-mapped tag can't hide behind an unrelated `Some`.
        for warning in WarningType::ALL {
            assert_eq!(
                WarningType::from_tag(warning.as_str()),
                warning.capture_produced().then_some(warning),
                "{}: from_tag arm and captureProduced flag disagree — add the missing side",
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
