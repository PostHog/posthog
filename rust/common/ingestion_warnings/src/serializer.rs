//! Builds the ingestion-warning event envelope shared by every Rust producer.
//!
//! A warning is emitted as a synthetic `$$client_ingestion_warning`
//! [`CapturedEvent`] on the `client_ingestion_warning` topic — the same lane
//! the JS SDK's client warnings already use. The Node.js `clientwarnings`
//! consumer resolves the token to a `team_id`, reads the structured
//! type/details/source we stamp into the event properties, and writes the v2
//! ingestion-warning row (see
//! `nodejs/src/ingestion/common/steps/event-processing/handle-client-ingestion-warning-step.ts`).
//! Routing through that consumer means capture never needs database access or
//! token→team resolution, and every Rust service emits warnings identically.
//!
//! The envelope's top-level `distinct_id` is deliberately the token, never the
//! offending event's distinct_id: the consumer's metadata validation drops
//! events whose distinct_id exceeds the length limit, and `distinct_id_too_large`
//! is itself a warning type — reusing the offending id would silently discard
//! exactly those warnings. The real offending identifiers ride in `details`,
//! which the consumer does not length-validate.

use std::collections::HashMap;

use chrono::{DateTime, SecondsFormat, Utc};
use common_types::{CapturedEvent, RawEvent};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::registry::WarningType;
use crate::WarningSource;

/// `source` field value for warnings emitted by capture. Also used as
/// [`crate::CAPTURE_V1_ANALYTICS`]'s `service`.
pub const SOURCE_CAPTURE: &str = "capture";

/// Synthetic event name the Node.js `clientwarnings` consumer routes on.
pub const CLIENT_INGESTION_WARNING_EVENT: &str = "$$client_ingestion_warning";

/// Event-property keys the consumer reads to reconstruct the structured
/// warning (see `handle-client-ingestion-warning-step.ts`).
const PROP_TYPE: &str = "$$client_ingestion_warning_type";
const PROP_SOURCE: &str = "$$client_ingestion_warning_source";
const PROP_DETAILS: &str = "$$client_ingestion_warning_details";

/// Build the `$$client_ingestion_warning` envelope for one (batch-deduped)
/// warning.
///
/// `extra_details` carries caller context (camelCase keys such as `distinctId`,
/// `eventUuid`, `lib`, `path`). The builder injects `count` and `pipelineStep`;
/// `team_id`, `category`, and `severity` are the consumer's responsibility (it
/// owns the authoritative registry), so we never stamp them here.
pub fn build_warning_event(
    token: &str,
    source: WarningSource,
    warning: WarningType,
    mut extra_details: Map<String, Value>,
    count: u64,
    timestamp: DateTime<Utc>,
) -> Result<CapturedEvent, serde_json::Error> {
    extra_details.insert("count".to_string(), json!(count));
    // The consumer lifts `pipelineStep` out of details into the warning's
    // top-level pipeline_step column, so it must live inside details here.
    extra_details.insert("pipelineStep".to_string(), json!(warning.pipeline_step()));

    let mut properties: HashMap<String, Value> = HashMap::new();
    properties.insert(PROP_TYPE.to_string(), json!(warning.as_str()));
    properties.insert(PROP_SOURCE.to_string(), json!(source.service));
    properties.insert(PROP_DETAILS.to_string(), Value::Object(extra_details));

    let uuid = Uuid::now_v7();
    let raw_event = RawEvent {
        token: Some(token.to_string()),
        distinct_id: Some(json!(token)),
        uuid: Some(uuid),
        event: CLIENT_INGESTION_WARNING_EVENT.to_string(),
        properties,
        ..Default::default()
    };
    // Capture serialises the inner event to a string, then the whole
    // `CapturedEvent` again on send — matching the normal sink wire format.
    let data = serde_json::to_string(&raw_event)?;

    Ok(CapturedEvent {
        uuid,
        distinct_id: token.to_string(),
        session_id: None,
        ip: String::new(),
        data,
        now: timestamp.to_rfc3339_opts(SecondsFormat::Millis, true),
        sent_at: None,
        token: token.to_string(),
        event: CLIENT_INGESTION_WARNING_EVENT.to_string(),
        timestamp,
        is_cookieless_mode: false,
        historical_migration: false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CAPTURE_V1_ANALYTICS;

    /// Parse the inner `RawEvent` and its `$$client_ingestion_warning_details`
    /// object back out of a built envelope.
    fn parse_envelope(event: &CapturedEvent) -> (Value, Value) {
        let raw: Value = serde_json::from_str(&event.data).unwrap();
        let details = raw["properties"][PROP_DETAILS].clone();
        (raw, details)
    }

    #[test]
    fn envelope_is_a_client_ingestion_warning_event_keyed_by_token() {
        let event = build_warning_event(
            "phc_test_token",
            CAPTURE_V1_ANALYTICS,
            WarningType::MissingEventName,
            Map::new(),
            3,
            Utc::now(),
        )
        .unwrap();

        assert_eq!(event.event, "$$client_ingestion_warning");
        assert_eq!(event.token, "phc_test_token");
        // distinct_id must be the (safe, bounded) token, never a caller value.
        assert_eq!(event.distinct_id, "phc_test_token");
    }

    #[test]
    fn properties_carry_the_structured_type_source_and_details() {
        let mut extra = Map::new();
        extra.insert("distinctId".to_string(), json!("user-1"));
        extra.insert("lib".to_string(), json!("posthog-js"));
        let event = build_warning_event(
            "phc_test_token",
            CAPTURE_V1_ANALYTICS,
            WarningType::MissingEventName,
            extra,
            3,
            Utc::now(),
        )
        .unwrap();

        let (raw, details) = parse_envelope(&event);
        assert_eq!(raw["properties"][PROP_TYPE], "missing_event_name");
        assert_eq!(raw["properties"][PROP_SOURCE], "capture");

        // Injected by the builder.
        assert_eq!(details["count"], 3);
        assert_eq!(details["pipelineStep"], "capture_validation");
        // Caller context passes through untouched.
        assert_eq!(details["distinctId"], "user-1");
        assert_eq!(details["lib"], "posthog-js");
    }

    /// The offending distinct_id lives in `details` only; the envelope's
    /// top-level distinct_id stays the token so an oversized id can never make
    /// the consumer drop a `distinct_id_too_large` warning.
    #[test]
    fn oversized_offender_distinct_id_never_reaches_the_envelope_field() {
        let huge = "x".repeat(10_000);
        let mut extra = Map::new();
        extra.insert("distinctId".to_string(), json!(huge));
        let event = build_warning_event(
            "phc_real",
            CAPTURE_V1_ANALYTICS,
            WarningType::DistinctIdTooLarge,
            extra,
            1,
            Utc::now(),
        )
        .unwrap();

        assert_eq!(event.distinct_id, "phc_real");
        let (_, details) = parse_envelope(&event);
        assert_eq!(details["distinctId"].as_str().unwrap().len(), 10_000);
    }

    /// The message `source` reflects the caller's [`crate::WarningSource`]
    /// rather than a hardcoded capture literal — the point of parameterizing
    /// the builder for reuse by other Rust services.
    #[test]
    fn source_field_reflects_the_caller_supplied_source() {
        let other = WarningSource {
            service: "batch_import",
            path: "some_path",
        };
        let event = build_warning_event(
            "phc_test_token",
            other,
            WarningType::EmptyBatch,
            Map::new(),
            1,
            Utc::now(),
        )
        .unwrap();
        let (raw, _) = parse_envelope(&event);
        assert_eq!(raw["properties"][PROP_SOURCE], "batch_import");
    }
}
