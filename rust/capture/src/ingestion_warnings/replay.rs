//! Ingestion warnings for the session replay path (`/s`).
//!
//! Replay's context projection lives here for the same reason legacy's does: the
//! path has no subtree of its own, spanning `v0_endpoint`, `payload/recordings`,
//! and `events/recordings`.
//!
//! Two things make replay's payloads read differently from the other pipelines'.
//! A batch of `$snapshot` events becomes one `$snapshot_items` message, so a
//! validation failure drops the whole request and `count` charges the batch. And
//! the token is only known after the body has been read, decompressed and parsed
//! (`crate::payload::recordings::handle_recording_payload`), so every transport
//! and parse failure is unattributable here exactly as it is for legacy.

use common_ingestion_warnings::{
    emit_request_warning, WarningEmitter, WarningRequestContext, WarningType, CAPTURE_REPLAY,
};
use serde_json::{json, Map};

use super::{unknown_if_missing, within_bound, SdkAttribution};
use crate::api::CaptureError;
use crate::events::recordings::{snapshot_library_fallback_from, RawRecording};
use crate::v0_request::ProcessingContext;

/// Why a `$session_id` was rejected.
///
/// Each value points at a different fix: a missing id means the SDK never set
/// one, a non-string means a custom integration is passing the wrong JSON type,
/// and the two shape failures mean the id itself has to change. The offending
/// value is deliberately not reported (see [`emit_replay_abort_warning`]), so
/// this is what makes the warning actionable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionIdRejection {
    NotAString,
    TooLong,
    InvalidCharset,
}

impl SessionIdRejection {
    fn as_str(self) -> &'static str {
        match self {
            Self::NotAString => "not_a_string",
            Self::TooLong => "too_long",
            Self::InvalidCharset => "invalid_charset",
        }
    }
}

/// Why a `$snapshot_data` property was rejected.
///
/// `Absent` means the property is missing entirely, which is usually an SDK too
/// old to send it. `WrongJsonType` means it is present but neither an array of
/// rrweb events nor a single event object, which is usually a payload built by
/// hand.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotDataRejection {
    Absent,
    WrongJsonType,
}

impl SnapshotDataRejection {
    fn as_str(self) -> &'static str {
        match self {
            Self::Absent => "absent",
            Self::WrongJsonType => "wrong_json_type",
        }
    }
}

/// The `reason` detail to ship with a replay abort, when the error has one.
///
/// `CaptureError` collapses distinguishable conditions into single variants
/// (`CaptureError::InvalidSessionId` covers three, `CaptureError::MissingSnapshotData`
/// two), and the HTTP status and metric tags depend on that collapsing, so the
/// pipeline reports the specific reason alongside the error instead of splitting
/// the variants. Each variant here is named for the error it accompanies.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplayRejectionReason {
    InvalidSessionId(SessionIdRejection),
    MissingSnapshotData(SnapshotDataRejection),
}

impl ReplayRejectionReason {
    fn as_str(self) -> &'static str {
        match self {
            Self::InvalidSessionId(reason) => reason.as_str(),
            Self::MissingSnapshotData(reason) => reason.as_str(),
        }
    }
}

/// Read SDK attribution off one snapshot event, falling back to the request's
/// user agent.
///
/// Callers pass the batch's first event, which is sound because one batch is one
/// SDK in every real client (the reasoning behind
/// [`super::SdkAttribution::from_first_event`], which takes the whole batch) and
/// because replay reads all its other metadata from the first event too.
///
/// `lib` falls back to the user agent through the same helper the pipeline uses
/// to label the ingested recording, so a warning names the library the customer
/// will see on their events rather than a second, differently-derived guess.
/// There is no such fallback for `lib_version`: nothing else in the request
/// carries it, so an absent one stays absent and projects to
/// `UNKNOWN_ATTRIBUTION`.
pub fn attribution_from_event(event: &RawRecording, user_agent: &str) -> SdkAttribution {
    let lib = event
        .properties
        .lib
        .clone()
        .or_else(|| snapshot_library_fallback_from(Some(user_agent)));

    SdkAttribution {
        lib: lib.and_then(within_bound),
        lib_version: event.properties.lib_version.clone().and_then(within_bound),
    }
}

/// Warning attribution for a replay batch.
///
/// Snapshot events carry `$lib`/`$lib_version` in their own envelope shape, so
/// the payload handler projects them onto [`ProcessingContext`] while the events
/// are still typed, the same way the legacy batch handler does.
pub fn request_context(context: &ProcessingContext) -> WarningRequestContext {
    WarningRequestContext {
        token: context.token.clone(),
        lib: unknown_if_missing(context.sdk_attribution.lib.as_deref()),
        lib_version: unknown_if_missing(context.sdk_attribution.lib_version.as_deref()),
        path: context.path.clone(),
    }
}

/// Map a replay-path request abort to the ingestion warning customers should
/// see, or `None` for failures customers can't act on.
///
/// This is the replay pipeline's counterpart to v1's `Error::tag()` →
/// [`WarningType::from_tag`] route. Like legacy's, it matches enum variants
/// rather than `to_metric_tag()` strings so renames are compile-checked, and the
/// types it returns take the `DIRECT_EMIT` route because no `v1::Error` ever
/// produces a tag naming a replay condition.
///
/// `None` arms are deliberate and exhaustive, mirroring the exclusions v1 pins
/// in `from_tag_rejects_unregistered_tags`. There is no catch-all: a new
/// `CaptureError` variant fails to compile here until someone decides whether
/// customers should see a warning for it.
pub fn warning_for_capture_error(err: &CaptureError) -> Option<WarningType> {
    match err {
        CaptureError::MissingDistinctId => Some(WarningType::MissingDistinctId),
        CaptureError::MissingSessionId => Some(WarningType::MissingSessionId),
        CaptureError::InvalidSessionId => Some(WarningType::InvalidSessionId),
        CaptureError::MissingSnapshotData => Some(WarningType::MissingSnapshotData),
        // Only the Kafka sink raises EventTooBig once processing has started. The
        // transport-level size limits raise it too, but they fire while
        // decompressing the body, before a verified token exists, so they never
        // reach the abort path. `setup.rs` caps the decompressed payload at the
        // producer's own message limit for this capture mode, which keeps the
        // sink raise rare: it needs the re-serialized envelope to outgrow the
        // payload it came from, or a broker limit below the producer's.
        CaptureError::EventTooBig(_) => Some(WarningType::MessageSizeTooLarge),

        // Transport and parse failures surface before a verified token exists,
        // so there is no team to attribute a warning to.
        CaptureError::RequestDecodingError(_)
        | CaptureError::RequestParsingError(_)
        | CaptureError::RequestHydrationError(_)
        | CaptureError::EmptyBatch
        | CaptureError::EmptyPayload
        | CaptureError::EmptyPayloadFiltered => None,

        // Auth failures: the token is missing, ambiguous, or invalid, so any
        // attribution would be untrustworthy.
        CaptureError::NoTokenError
        | CaptureError::MultipleTokensError
        | CaptureError::TokenValidationError(_) => None,

        // Unreachable on this path rather than excluded by policy.
        // `extract_is_cookieless_mode` defaults to `Some(false)` instead of
        // returning `None`, `$window_id` falls back to the session id so
        // `MissingWindowId` is never constructed, and replay's timestamp parse
        // reports no failure to map. The analytics-only variants below this
        // pipeline never sees round out the exhaustive match.
        CaptureError::InvalidCookielessMode
        | CaptureError::InvalidTimestamp
        | CaptureError::MissingWindowId
        | CaptureError::NonAiEventOnAiLane(_)
        | CaptureError::AiEventTooBig(_)
        | CaptureError::MissingEventName => None,

        // Quota, rate, and ops-imposed drops are surfaced through billing and
        // ops channels, not the warnings UI.
        CaptureError::BillingLimit
        | CaptureError::RateLimited
        | CaptureError::GlobalRateLimitExceeded() => None,

        // Sink and server failures are ours to fix, not the customer's.
        CaptureError::RetryableSinkError
        | CaptureError::NonRetryableSinkError
        | CaptureError::ServiceUnavailable(_)
        | CaptureError::BodyReadTimeout
        | CaptureError::InternalError(_) => None,
    }
}

/// Emit the ingestion warning for a replay-path `process_replay_events` abort,
/// if the error maps to one.
///
/// The pipeline rejects the whole request on the first invalid event and would
/// have produced a single message for the batch, so `count` charges the full
/// batch, matching what `report_dropped_events` records for the same failure;
/// it's floored at 1 because a zero would read as "nothing happened" in the v2
/// table. `EventTooBig` is the exception: the sink raises it for the one message
/// it tried to produce, so charging the batch would overstate a single failure.
///
/// `reason` carries the specific condition behind a variant that covers several.
/// The offending `$session_id` itself is deliberately left out: it is
/// unvalidated client input landing in a customer-visible column, and the reason
/// plus `sessionIdLength` already say what has to change.
pub fn emit_replay_abort_warning(
    emitter: Option<&dyn WarningEmitter>,
    context: &ProcessingContext,
    err: &CaptureError,
    reason: Option<ReplayRejectionReason>,
    session_id_chars: Option<usize>,
    event_count: u64,
) {
    let Some(warning) = warning_for_capture_error(err) else {
        return;
    };

    let mut details = Map::new();
    if let Some(reason) = reason {
        details.insert("reason".to_string(), json!(reason.as_str()));
    }
    if let Some(chars) = session_id_chars {
        details.insert("sessionIdLength".to_string(), json!(chars));
    }
    details.insert("eventCount".to_string(), json!(event_count));

    let count = match err {
        CaptureError::EventTooBig(_) => 1,
        _ => event_count.max(1),
    };

    emit_request_warning(
        emitter,
        &request_context(context),
        CAPTURE_REPLAY,
        warning,
        details,
        count,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::CaptureMode;
    use crate::ingestion_warnings::{SdkAttribution, MAX_SDK_ATTRIBUTION_LEN};
    use common_ingestion_warnings::test_support::CollectingEmitter;
    use common_ingestion_warnings::UNKNOWN_ATTRIBUTION;
    use rstest::rstest;

    fn replay_context(attribution: SdkAttribution) -> ProcessingContext {
        ProcessingContext {
            user_agent: None,
            sent_at: None,
            token: "tok".to_string(),
            now: chrono::Utc::now(),
            client_ip: "127.0.0.1".to_string(),
            request_id: "req".to_string(),
            path: "/s".to_string(),
            is_mirror_deploy: false,
            historical_migration: false,
            chatty_debug_enabled: false,
            capture_mode: CaptureMode::Recordings,
            ai_max_event_bytes: 0,
            sdk_attribution: attribution,
        }
    }

    // Pins which conditions are the customer's to fix versus ours. The match is
    // exhaustive with no catch-all, so a new variant won't compile until someone
    // decides; this table is what pins the decision itself.
    #[rstest]
    #[case::missing_distinct_id(
        CaptureError::MissingDistinctId,
        Some(WarningType::MissingDistinctId)
    )]
    #[case::missing_session_id(CaptureError::MissingSessionId, Some(WarningType::MissingSessionId))]
    #[case::invalid_session_id(CaptureError::InvalidSessionId, Some(WarningType::InvalidSessionId))]
    #[case::missing_snapshot_data(
        CaptureError::MissingSnapshotData,
        Some(WarningType::MissingSnapshotData)
    )]
    #[case::oversize(
        CaptureError::EventTooBig("too big".to_string()),
        Some(WarningType::MessageSizeTooLarge)
    )]
    #[case::parse(CaptureError::RequestParsingError("bad json".to_string()), None)]
    #[case::decode(CaptureError::RequestDecodingError("bad gzip".to_string()), None)]
    #[case::empty_batch(CaptureError::EmptyBatch, None)]
    #[case::empty_payload(CaptureError::EmptyPayload, None)]
    #[case::no_token(CaptureError::NoTokenError, None)]
    #[case::billing(CaptureError::BillingLimit, None)]
    #[case::rate_limited(CaptureError::RateLimited, None)]
    #[case::unreachable_cookieless(CaptureError::InvalidCookielessMode, None)]
    #[case::unreachable_window_id(CaptureError::MissingWindowId, None)]
    #[case::unreachable_timestamp(CaptureError::InvalidTimestamp, None)]
    #[case::retryable_sink(CaptureError::RetryableSinkError, None)]
    #[case::non_retryable_sink(CaptureError::NonRetryableSinkError, None)]
    #[case::body_timeout(CaptureError::BodyReadTimeout, None)]
    #[case::internal(CaptureError::InternalError("boom".to_string()), None)]
    fn abort_warnings_map_only_customer_actionable_errors(
        #[case] err: CaptureError,
        #[case] expected: Option<WarningType>,
    ) {
        assert_eq!(warning_for_capture_error(&err), expected);
    }

    // Guards the trust chain end to end. A type this mapper emits that is not
    // capture-produced would be demoted to a generic client warning by the nodejs
    // consumer, and one also reachable via `from_tag` would violate the common
    // crate's one-route invariant. Both fail silently in production.
    #[test]
    fn emitted_warnings_are_trusted_and_single_routed() {
        let mapping_errors = [
            CaptureError::MissingDistinctId,
            CaptureError::MissingSessionId,
            CaptureError::InvalidSessionId,
            CaptureError::MissingSnapshotData,
            CaptureError::EventTooBig("too big".to_string()),
        ];
        let mapped = mapping_errors.iter().filter_map(warning_for_capture_error);

        for warning in mapped {
            assert!(
                warning.capture_produced(),
                "{warning:?} is not on the consumer trust allowlist"
            );
        }

        // The replay-only types must stay off the tag route; the two shared with
        // analytics stay on it. Either way, exactly one route per type.
        for warning in [
            WarningType::MissingSessionId,
            WarningType::InvalidSessionId,
            WarningType::MissingSnapshotData,
        ] {
            assert!(
                WarningType::DIRECT_EMIT.contains(&warning),
                "{warning:?} must be direct-emit"
            );
            assert_eq!(
                WarningType::from_tag(warning.as_str()),
                None,
                "{warning:?} must not also be tag-routed"
            );
        }
    }

    #[rstest]
    #[case::not_a_string(SessionIdRejection::NotAString, "not_a_string")]
    #[case::too_long(SessionIdRejection::TooLong, "too_long")]
    #[case::invalid_charset(SessionIdRejection::InvalidCharset, "invalid_charset")]
    fn session_id_rejection_reasons_are_a_closed_vocabulary(
        #[case] reason: SessionIdRejection,
        #[case] expected: &str,
    ) {
        assert_eq!(reason.as_str(), expected);
    }

    #[rstest]
    #[case::absent(SnapshotDataRejection::Absent, "absent")]
    #[case::wrong_json_type(SnapshotDataRejection::WrongJsonType, "wrong_json_type")]
    fn snapshot_data_rejection_reasons_are_a_closed_vocabulary(
        #[case] reason: SnapshotDataRejection,
        #[case] expected: &str,
    ) {
        assert_eq!(reason.as_str(), expected);
    }

    // The details are the customer-visible payload, and the offending session id
    // must never be among them.
    #[test]
    fn invalid_session_id_reports_the_reason_and_length_but_not_the_value() {
        let emitter = CollectingEmitter::default();
        let context = replay_context(SdkAttribution {
            lib: Some("web".to_string()),
            lib_version: Some("1.2.3".to_string()),
        });

        emit_replay_abort_warning(
            Some(&emitter),
            &context,
            &CaptureError::InvalidSessionId,
            Some(ReplayRejectionReason::InvalidSessionId(
                SessionIdRejection::InvalidCharset,
            )),
            Some(71),
            4,
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        let warning = &emitted[0];
        assert_eq!(warning.warning, WarningType::InvalidSessionId);
        assert_eq!(warning.count, 4);
        assert_eq!(warning.extra_details["reason"], json!("invalid_charset"));
        assert_eq!(warning.extra_details["sessionIdLength"], json!(71));
        assert_eq!(warning.extra_details["eventCount"], json!(4));
        assert_eq!(warning.extra_details["lib"], json!("web"));
        assert_eq!(warning.extra_details["libVersion"], json!("1.2.3"));
        assert_eq!(warning.extra_details["path"], json!("/s"));
        assert!(
            !warning.extra_details.contains_key("sessionId"),
            "the offending session id must not ride into a customer-visible column"
        );
    }

    // A validation abort drops every event in the batch; the sink's oversize
    // rejection is one message. Charging the batch for the latter would report a
    // single failure as many.
    #[rstest]
    #[case::validation_charges_the_batch(CaptureError::MissingSessionId, 7, 7)]
    #[case::validation_floors_at_one(CaptureError::MissingSnapshotData, 0, 1)]
    #[case::oversize_charges_one(CaptureError::EventTooBig("too big".to_string()), 7, 1)]
    fn abort_counts_match_what_was_dropped(
        #[case] err: CaptureError,
        #[case] event_count: u64,
        #[case] expected_count: u64,
    ) {
        let emitter = CollectingEmitter::default();

        emit_replay_abort_warning(
            Some(&emitter),
            &replay_context(SdkAttribution::default()),
            &err,
            None,
            None,
            event_count,
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        assert_eq!(emitted[0].count, expected_count);
    }

    #[test]
    fn unmapped_errors_emit_nothing() {
        let emitter = CollectingEmitter::default();

        emit_replay_abort_warning(
            Some(&emitter),
            &replay_context(SdkAttribution::default()),
            &CaptureError::RetryableSinkError,
            None,
            None,
            3,
        );

        assert!(emitter.emitted().is_empty());
    }

    #[test]
    fn no_emitter_is_a_silent_no_op() {
        emit_replay_abort_warning(
            None,
            &replay_context(SdkAttribution::default()),
            &CaptureError::MissingSessionId,
            None,
            None,
            3,
        );
    }

    // Each of these is a payload capture accepts today, so each must produce a
    // stampable context rather than a missing key.
    #[rstest]
    #[case::nothing_reported(None, None, UNKNOWN_ATTRIBUTION, UNKNOWN_ATTRIBUTION)]
    #[case::lib_without_version(Some("web"), None, "web", UNKNOWN_ATTRIBUTION)]
    #[case::both(Some("posthog-ios"), Some("3.1.0"), "posthog-ios", "3.1.0")]
    #[case::empty_lib(Some(""), Some(""), UNKNOWN_ATTRIBUTION, UNKNOWN_ATTRIBUTION)]
    fn attribution_falls_back_to_unknown_when_unusable(
        #[case] lib: Option<&str>,
        #[case] lib_version: Option<&str>,
        #[case] expected_lib: &str,
        #[case] expected_lib_version: &str,
    ) {
        let context = replay_context(SdkAttribution {
            lib: lib.map(str::to_string),
            lib_version: lib_version.map(str::to_string),
        });

        let projected = request_context(&context);
        assert_eq!(projected.lib, expected_lib);
        assert_eq!(projected.lib_version, expected_lib_version);
        assert_eq!(projected.token, "tok");
        assert_eq!(projected.path, "/s");
    }

    // Oversized values are dropped rather than truncated, so they land on the
    // unknown fallback instead of riding into every warning for the request.
    #[test]
    fn oversized_attribution_is_dropped_at_projection() {
        let over_bound = "w".repeat(MAX_SDK_ATTRIBUTION_LEN + 1);
        let at_bound = "w".repeat(MAX_SDK_ATTRIBUTION_LEN);

        let projected = request_context(&replay_context(SdkAttribution {
            lib: within_bound(over_bound),
            lib_version: within_bound(at_bound.clone()),
        }));

        assert_eq!(projected.lib, UNKNOWN_ATTRIBUTION);
        assert_eq!(projected.lib_version, at_bound);
    }

    fn recording(properties: serde_json::Value) -> RawRecording {
        serde_json::from_value(json!({"event": "$snapshot", "properties": properties})).unwrap()
    }

    // Each case is a payload real SDKs send. The `$lib`-absent rows are the ones
    // that matter: replay has no `PostHog-Sdk-Info` header, so the user agent is
    // the only remaining signal, and it must resolve the same way the ingested
    // recording's own `$lib` does.
    #[rstest]
    #[case::lib_and_version(
        json!({"$lib": "web", "$lib_version": "1.2.3"}),
        "posthog-js/1.2.3",
        Some("web"),
        Some("1.2.3")
    )]
    #[case::lib_without_version(json!({"$lib": "posthog-ios"}), "whatever", Some("posthog-ios"), None)]
    #[case::posthog_user_agent_fallback(json!({}), "posthog-python/3.0.1", Some("posthog-python"), None)]
    #[case::browser_user_agent_falls_back_to_web(json!({}), "Mozilla/5.0", Some("web"), None)]
    #[case::version_without_lib_still_reports_version(
        json!({"$lib_version": "9.9.9"}),
        "posthog-node/9.9.9",
        Some("posthog-node"),
        Some("9.9.9")
    )]
    fn attribution_reads_the_snapshot_envelope_then_the_user_agent(
        #[case] properties: serde_json::Value,
        #[case] user_agent: &str,
        #[case] expected_lib: Option<&str>,
        #[case] expected_version: Option<&str>,
    ) {
        let attribution = attribution_from_event(&recording(properties), user_agent);

        assert_eq!(attribution.lib.as_deref(), expected_lib);
        assert_eq!(attribution.lib_version.as_deref(), expected_version);
    }

    // Oversized client input is dropped at extraction so it never reaches the
    // context, matching what the analytics path does with the same values.
    #[test]
    fn oversized_snapshot_attribution_is_dropped_at_extraction() {
        let over_bound = "w".repeat(MAX_SDK_ATTRIBUTION_LEN + 1);

        let attribution = attribution_from_event(
            &recording(json!({"$lib": over_bound, "$lib_version": over_bound})),
            "posthog-js/1.0.0",
        );

        assert_eq!(attribution.lib, None);
        assert_eq!(attribution.lib_version, None);
    }
}
