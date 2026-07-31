//! Per-path SDK attribution for ingestion warnings.
//!
//! Every capture pipeline learns the client SDK differently, and the differences
//! are permanent, not transitional:
//!
//! * v1 requires the `PostHog-Sdk-Info` header and materializes
//!   `$lib`/`$lib_version` from it, overriding whatever the body claims
//!   ([`crate::v1::context::RequestContext::sdk_lib_and_version`]).
//! * The legacy path has no such header contract. Its only source is the events'
//!   `$lib`/`$lib_version` properties, which are gone by the time the pipeline
//!   holds serialized `CapturedEvent`s — so the batch handler snapshots them
//!   onto [`ProcessingContext`] while the events are still typed.
//! * Replay and the AI endpoint each carry their own quirks and will need their
//!   own conversion here when they start emitting.
//!
//! Normalizing lives here rather than in `common_ingestion_warnings` so that
//! crate never learns capture's event shapes: it takes concrete strings and
//! stamps them.

use std::collections::HashSet;

use common_ingestion_warnings::{
    emit_request_warning, WarningEmitter, WarningRequestContext, WarningSource, WarningType,
    CAPTURE_LEGACY_ANALYTICS, UNKNOWN_ATTRIBUTION,
};
use common_types::{EventWithLibraryInfo, RawEvent};
use serde_json::{json, Map};
use uuid::Uuid;

use crate::api::CaptureError;
use crate::v0_request::ProcessingContext;
use crate::v1::context::RequestContext;

/// Max accepted length of a client-supplied `$lib` or `$lib_version`, matching
/// the bound v1 puts on the `PostHog-Sdk-Info` header (real values are ~20
/// bytes). Oversized values are treated as absent rather than truncated: they
/// would otherwise ride into every warning payload for the batch and into the
/// `Debug` output of [`ProcessingContext`], which the legacy path logs several
/// times per request when chatty debug is on.
const MAX_SDK_ATTRIBUTION_LEN: usize = 200;

/// SDK identity as reported by a batch, for attribution only.
///
/// Both fields are unvalidated client input. Nothing routes on them.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SdkAttribution {
    pub lib: Option<String>,
    pub lib_version: Option<String>,
}

impl SdkAttribution {
    /// Take attribution from the first event of a batch.
    ///
    /// One batch is one SDK in every real client: batching is a client-side
    /// buffer flush, so events in it share a `$lib`. Scanning further to
    /// reconcile disagreement would cost a pass over the batch on the hot path
    /// to improve a field that is only ever displayed.
    pub fn from_first_event(events: &[RawEvent]) -> Self {
        let Some(info) = events.first().and_then(|e| e.extract_library_info()) else {
            return Self::default();
        };
        Self {
            lib: within_bound(info.name),
            lib_version: info.version.and_then(within_bound),
        }
    }
}

fn within_bound(value: String) -> Option<String> {
    (value.len() <= MAX_SDK_ATTRIBUTION_LEN).then_some(value)
}

/// Warning attribution for a legacy-path batch.
///
/// SDK fields come from the snapshot the handler took during batch construction;
/// a batch that reported no `$lib` (or a `$lib` with no version, which the JS
/// SDK can do) stamps [`UNKNOWN_ATTRIBUTION`] rather than dropping the key.
pub fn legacy_request_context(context: &ProcessingContext) -> WarningRequestContext {
    WarningRequestContext {
        token: context.token.clone(),
        lib: unknown_if_missing(context.sdk_attribution.lib.as_deref()),
        lib_version: unknown_if_missing(context.sdk_attribution.lib_version.as_deref()),
        path: context.path.clone(),
    }
}

/// Warning attribution for a v1 request.
///
/// `sdk_lib_and_version` is all-or-nothing — the header is a single
/// `name/version` string — so both fields fall back together.
pub fn v1_request_context(context: &RequestContext) -> WarningRequestContext {
    let (lib, lib_version) = context
        .sdk_lib_and_version()
        .unwrap_or((UNKNOWN_ATTRIBUTION, UNKNOWN_ATTRIBUTION));
    WarningRequestContext {
        token: context.api_token.clone(),
        lib: lib.to_string(),
        lib_version: lib_version.to_string(),
        path: context.path.to_string(),
    }
}

/// Emit the `high_volume_distinct_id` warning for one batch's rate-limited
/// events. Shared by the v1 and legacy rate limiter stages, which differ only in
/// their [`WarningSource`] — the payload must not drift between them, since a
/// reader of the v2 table can't tell which pipeline served a request.
///
/// `distinct_id` is included only when the batch had exactly one hot key; with
/// several it would be an arbitrary pick, and `distinctIdCount` already says how
/// many there were. The value needs no size bounding here: both pipelines drop
/// oversized distinct_ids before the limiter runs.
pub fn emit_rate_limit_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    source: WarningSource,
    limited_distinct_ids: &HashSet<&str>,
    limited_event_count: u64,
) {
    let mut details = Map::new();
    details.insert(
        "distinctIdCount".to_string(),
        json!(limited_distinct_ids.len()),
    );
    if let [distinct_id] = limited_distinct_ids.iter().copied().collect::<Vec<_>>()[..] {
        details.insert("distinctId".to_string(), json!(distinct_id));
    }

    emit_request_warning(
        emitter,
        request,
        source,
        WarningType::HighVolumeDistinctId,
        details,
        limited_event_count,
    );
}

/// Emit the `distinct_id_truncated` warning for one legacy batch's events
/// whose distinct_id was cut down to the 200-char cap at extraction. The
/// events were ingested (modified, not dropped), so this is legacy-only: v1
/// rejects oversized ids outright as `distinct_id_too_large`.
///
/// Identifier details are included only when the batch had exactly one
/// truncated event; with several they would be an arbitrary pick, and `count`
/// already carries the volume. The truncated value is at most 200 chars, so
/// it needs no bounding of its own; `distinctIdLength` is the original char
/// count, telling the customer how far over the cap they were.
pub fn emit_distinct_id_truncated_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    sample: Option<(String, usize, Uuid)>,
    count: u64,
) {
    let mut details = Map::new();
    if let Some((distinct_id, original_chars, event_uuid)) = sample {
        details.insert("distinctId".to_string(), json!(distinct_id));
        details.insert("distinctIdLength".to_string(), json!(original_chars));
        details.insert("eventUuid".to_string(), json!(event_uuid));
    }

    emit_request_warning(
        emitter,
        request,
        CAPTURE_LEGACY_ANALYTICS,
        WarningType::DistinctIdTruncated,
        details,
        count,
    );
}

fn unknown_if_missing(value: Option<&str>) -> String {
    match value {
        Some(v) if !v.trim().is_empty() => v.to_string(),
        _ => UNKNOWN_ATTRIBUTION.to_string(),
    }
}

/// Map a legacy-path request abort to the ingestion warning customers should
/// see, or `None` for failures customers can't act on.
///
/// This is the legacy pipeline's counterpart to v1's `Error::tag()` →
/// [`WarningType::from_tag`] route. It matches enum variants instead of the
/// `to_metric_tag()` strings so renames are compile-checked, and it lives here
/// rather than in `common_ingestion_warnings` so that crate never learns
/// capture's error taxonomy.
///
/// `None` arms are deliberate and exhaustive, mirroring the exclusions v1
/// pins in `from_tag_rejects_unregistered_tags`. There is no catch-all: a new
/// `CaptureError` variant fails to compile here until someone decides whether
/// customers should see a warning for it.
pub fn warning_for_capture_error(err: &CaptureError) -> Option<WarningType> {
    match err {
        CaptureError::MissingEventName => Some(WarningType::MissingEventName),
        CaptureError::MissingDistinctId => Some(WarningType::MissingDistinctId),
        // Only the Kafka sink raises EventTooBig during processing; the
        // transport-level size limits fail at the parsing stage, before a
        // verified token exists, and so never reach the abort path. This is
        // the same drop the nodejs pipeline reports as message_size_too_large
        // when its own produce hits the broker limit.
        CaptureError::EventTooBig(_) => Some(WarningType::MessageSizeTooLarge),

        // Transport and parse failures surface before a verified token
        // exists, so there is no team to attribute a warning to.
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

        // Validation conditions with no warning yet (candidates, not
        // oversights), plus the recordings-only variants this analytics
        // mapper never sees.
        CaptureError::InvalidCookielessMode
        | CaptureError::InvalidTimestamp
        | CaptureError::MissingSnapshotData
        | CaptureError::MissingSessionId
        | CaptureError::MissingWindowId
        | CaptureError::InvalidSessionId => None,

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

/// Emit the ingestion warning for a legacy-path `process_events` abort, if the
/// error maps to one.
///
/// The legacy pipeline rejects the whole request on the first invalid event.
/// For validation aborts that means nothing was sent, so `count` charges the
/// full batch, matching what `report_dropped_events` records for the same
/// failure; it's floored at 1 for v1 parity, since a zero count would read as
/// "nothing happened" in the v2 table. `EventTooBig` is the exception: the
/// sink raises it per message after earlier events in the batch were already
/// enqueued (and typically deliver despite the 413), so charging the batch
/// would report delivered events as failed. It emits `count = 1` — at least
/// one event was rejected — matching the sink's per-event
/// `kafka_message_size` drop metric.
pub fn emit_processing_abort_warning(
    emitter: Option<&dyn WarningEmitter>,
    context: &ProcessingContext,
    err: &CaptureError,
    event_count: u64,
) {
    let Some(warning) = warning_for_capture_error(err) else {
        return;
    };
    let count = match err {
        CaptureError::EventTooBig(_) => 1,
        _ => event_count.max(1),
    };
    emit_request_warning(
        emitter,
        &legacy_request_context(context),
        CAPTURE_LEGACY_ANALYTICS,
        warning,
        Map::new(),
        count,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_ingestion_warnings::test_support::CollectingEmitter;
    use serde_json::json;

    fn raw_event(properties: serde_json::Value) -> RawEvent {
        RawEvent {
            event: "$pageview".to_string(),
            properties: properties
                .as_object()
                .expect("test properties must be an object")
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
            ..Default::default()
        }
    }

    fn legacy_context(attribution: SdkAttribution) -> ProcessingContext {
        ProcessingContext {
            user_agent: None,
            sent_at: None,
            token: "tok".to_string(),
            now: chrono::Utc::now(),
            client_ip: "127.0.0.1".to_string(),
            request_id: "req".to_string(),
            path: "/e/".to_string(),
            is_mirror_deploy: false,
            historical_migration: false,
            chatty_debug_enabled: false,
            capture_mode: crate::config::CaptureMode::Events,
            sdk_attribution: attribution,
        }
    }

    #[test]
    fn first_event_supplies_attribution_for_the_whole_batch() {
        let events = vec![
            raw_event(json!({"$lib": "web", "$lib_version": "1.2.3"})),
            raw_event(json!({"$lib": "posthog-python", "$lib_version": "9.9.9"})),
        ];
        assert_eq!(
            SdkAttribution::from_first_event(&events),
            SdkAttribution {
                lib: Some("web".to_string()),
                lib_version: Some("1.2.3".to_string()),
            }
        );
    }

    // Each of these is a payload capture accepts today, so each must produce a
    // stampable context rather than a missing key. Oversized values are dropped
    // rather than truncated, so they land on the same fallback.
    #[test]
    fn unusable_attribution_becomes_unknown() {
        let at_bound = "w".repeat(MAX_SDK_ATTRIBUTION_LEN);
        let over_bound = "w".repeat(MAX_SDK_ATTRIBUTION_LEN + 1);
        let cases = [
            (
                "no events",
                vec![],
                UNKNOWN_ATTRIBUTION,
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "no properties",
                vec![raw_event(json!({}))],
                UNKNOWN_ATTRIBUTION,
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "lib without version",
                vec![raw_event(json!({"$lib": "web"}))],
                "web",
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "non-string lib",
                vec![raw_event(json!({"$lib": 42, "$lib_version": "1.2.3"}))],
                UNKNOWN_ATTRIBUTION,
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "empty lib",
                vec![raw_event(json!({"$lib": "", "$lib_version": ""}))],
                UNKNOWN_ATTRIBUTION,
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "oversized lib",
                vec![raw_event(
                    json!({"$lib": over_bound, "$lib_version": "1.2.3"}),
                )],
                UNKNOWN_ATTRIBUTION,
                "1.2.3",
            ),
            (
                "oversized version",
                vec![raw_event(
                    json!({"$lib": "web", "$lib_version": over_bound}),
                )],
                "web",
                UNKNOWN_ATTRIBUTION,
            ),
            (
                "lib at the bound",
                vec![raw_event(
                    json!({"$lib": at_bound, "$lib_version": "1.2.3"}),
                )],
                at_bound.as_str(),
                "1.2.3",
            ),
        ];

        for (label, events, expected_lib, expected_lib_version) in cases {
            let attribution = SdkAttribution::from_first_event(&events);
            let ctx = legacy_request_context(&legacy_context(attribution));
            assert_eq!(ctx.lib, expected_lib, "{label}: lib");
            assert_eq!(ctx.lib_version, expected_lib_version, "{label}: libVersion");
        }
    }

    #[test]
    fn abort_warnings_map_only_customer_actionable_errors() {
        let cases: [(CaptureError, Option<WarningType>); 13] = [
            (
                CaptureError::MissingEventName,
                Some(WarningType::MissingEventName),
            ),
            (
                CaptureError::MissingDistinctId,
                Some(WarningType::MissingDistinctId),
            ),
            (
                CaptureError::EventTooBig("too big".to_string()),
                Some(WarningType::MessageSizeTooLarge),
            ),
            // Excluded on purpose; see warning_for_capture_error's doc.
            (CaptureError::InvalidCookielessMode, None),
            (CaptureError::EmptyBatch, None),
            (CaptureError::EmptyPayload, None),
            (CaptureError::InvalidTimestamp, None),
            (
                CaptureError::RequestParsingError("bad json".to_string()),
                None,
            ),
            (CaptureError::NoTokenError, None),
            (CaptureError::BillingLimit, None),
            (CaptureError::RetryableSinkError, None),
            (CaptureError::NonRetryableSinkError, None),
            (CaptureError::InternalError("boom".to_string()), None),
        ];

        for (err, expected) in cases {
            assert_eq!(
                warning_for_capture_error(&err),
                expected,
                "mapping for {err:?}"
            );
        }
    }

    // Guards the trust chain end to end: a mapper arm for a type that is not
    // capture-produced would be demoted to a generic client warning by the
    // nodejs consumer, and one routed via DIRECT_EMIT would violate the
    // common crate's one-route invariant. Both fail silently in production,
    // so pin them here like the common crate's weld test does for from_tag.
    #[test]
    fn mapped_abort_warnings_ride_the_capture_produced_tag_route() {
        let mapping_errors = [
            CaptureError::MissingEventName,
            CaptureError::MissingDistinctId,
            CaptureError::EventTooBig("too big".to_string()),
        ];
        let mapped = mapping_errors.iter().filter_map(warning_for_capture_error);

        for warning in mapped {
            assert!(
                warning.capture_produced(),
                "{warning:?} is not on the consumer trust allowlist"
            );
            assert_eq!(
                WarningType::from_tag(warning.as_str()),
                Some(warning),
                "{warning:?} must be tag-routed"
            );
            assert!(
                !WarningType::DIRECT_EMIT.contains(&warning),
                "{warning:?} must not also be direct-emit"
            );
        }
    }

    #[test]
    fn abort_helper_charges_full_batch_with_legacy_validation_source() {
        // (error, event_count, expected emitted count): a validation abort
        // charges the batch size (nothing was sent), flooring zero to 1 so
        // the v2 row never reads as a no-op, matching v1's batch-abort
        // convention. EventTooBig charges 1: earlier batch events were
        // already enqueued and typically deliver, so a batch count would
        // report delivered events as failed.
        let cases = [
            (
                CaptureError::MissingDistinctId,
                WarningType::MissingDistinctId,
                25u64,
                25u64,
            ),
            (
                CaptureError::MissingDistinctId,
                WarningType::MissingDistinctId,
                0u64,
                1u64,
            ),
            (
                CaptureError::EventTooBig("too big".to_string()),
                WarningType::MessageSizeTooLarge,
                25u64,
                1u64,
            ),
        ];

        for (error, expected_warning, event_count, expected_count) in cases {
            let emitter = CollectingEmitter::default();
            let context = legacy_context(SdkAttribution {
                lib: Some("web".to_string()),
                lib_version: Some("1.2.3".to_string()),
            });

            emit_processing_abort_warning(Some(&emitter), &context, &error, event_count);

            let emitted = emitter.emitted();
            assert_eq!(emitted.len(), 1, "{error:?} event_count={event_count}");
            let warning = &emitted[0];
            assert_eq!(warning.token, "tok");
            assert_eq!(
                warning.source,
                common_ingestion_warnings::CAPTURE_LEGACY_ANALYTICS
            );
            assert_eq!(warning.warning, expected_warning);
            assert_eq!(warning.count, expected_count, "{error:?}");
            assert_eq!(warning.extra_details.get("lib"), Some(&json!("web")));
            assert_eq!(
                warning.extra_details.get("libVersion"),
                Some(&json!("1.2.3"))
            );
            assert_eq!(warning.extra_details.get("path"), Some(&json!("/e/")));
        }
    }

    #[test]
    fn abort_helper_emits_nothing_for_unmapped_errors() {
        let emitter = CollectingEmitter::default();
        let context = legacy_context(SdkAttribution::default());

        emit_processing_abort_warning(
            Some(&emitter),
            &context,
            &CaptureError::RetryableSinkError,
            10,
        );

        assert!(emitter.emitted().is_empty());
    }
}
