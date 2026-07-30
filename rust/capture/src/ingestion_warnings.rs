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
    UNKNOWN_ATTRIBUTION,
};
use common_types::{EventWithLibraryInfo, RawEvent};
use serde_json::{json, Map};

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

fn unknown_if_missing(value: Option<&str>) -> String {
    match value {
        Some(v) if !v.trim().is_empty() => v.to_string(),
        _ => UNKNOWN_ATTRIBUTION.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
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
}
