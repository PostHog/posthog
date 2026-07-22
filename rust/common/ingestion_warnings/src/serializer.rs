//! Serialization of ingestion warnings, for both transports.
//!
//! A [`Warning`] is a registered type plus caller details; committing it to a
//! transport is a terminal call. The two transports produce deliberately
//! different payloads for different pipeline stages:
//!
//! | | [`Warning::into_event_envelope`] (capture) | [`Warning::into_row`] (team-aware services) |
//! |---|---|---|
//! | Output | `$$client_ingestion_warning` [`CapturedEvent`] | terminal v2 row JSON |
//! | Lane | public event stream (attacker-writable namespace) | ACL-guarded warnings topic |
//! | Addressing | API token (consumer resolves the team) | `team_id` |
//! | Classification | absent — the Node consumer re-judges the message (trust allowlist, consumer-stamped category/severity) | producer-stamped from the registry |
//! | Injected details | `count`, the source's `pipelineStep` | `teamId`, `category`, `severity`, the source's `pipelineStep` |
//! | Timestamp | RFC 3339 envelope fields | ClickHouse-format `timestamp` field |
//!
//! The asymmetry is the security design, enforced by the type: classification
//! exists only inside `into_row`, so an envelope carrying classification or a
//! row missing it is unrepresentable. Anything arriving on the event lane is
//! indistinguishable from a client-forged event (the envelope's event name and
//! properties are writable by any token holder), so the consumer is
//! authoritative there (see
//! `nodejs/src/ingestion/common/steps/event-processing/handle-client-ingestion-warning-step.ts`);
//! rows are trusted by transport. Routing the envelope through that consumer
//! also means capture never needs database access or token→team resolution.
//!
//! The envelope's top-level `distinct_id` is deliberately the token, never the
//! offending event's distinct_id: the consumer's metadata validation drops
//! events whose distinct_id exceeds the length limit, and `distinct_id_too_large`
//! is itself a warning type — reusing the offending id would silently discard
//! exactly those warnings. The real offending identifiers ride in `details`,
//! which the consumer does not length-validate.

use std::collections::HashMap;

use chrono::{SecondsFormat, Utc};
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

/// One warning, before it is committed to a transport.
///
/// Details carry caller context with camelCase keys (`distinctId`,
/// `eventUuid`, `personId`, `message`, ...) — identifiers and sizes, never
/// raw payload content: details are user-visible. Keys a transport injects
/// are inserted after the caller's, so caller details can never override
/// them. If direct-row producers multiply, the natural extension is an
/// additive `details(&impl Serialize)` overload with closed per-warning
/// structs at the callers; today's caller population doesn't warrant it.
pub struct Warning {
    warning: WarningType,
    details: Map<String, Value>,
    count: u64,
}

impl Warning {
    pub fn new(warning: WarningType) -> Self {
        Self {
            warning,
            details: Map::new(),
            count: 1,
        }
    }

    pub fn with_detail(mut self, key: impl Into<String>, value: impl Into<Value>) -> Self {
        self.details.insert(key.into(), value.into());
        self
    }

    /// Extend details from a map (colliding keys are overwritten by `details`).
    pub fn with_details(mut self, details: Map<String, Value>) -> Self {
        self.details.extend(details);
        self
    }

    /// Number of occurrences this warning represents after per-batch dedup.
    /// Only the envelope transport carries it; defaults to 1.
    pub fn with_count(mut self, count: u64) -> Self {
        self.count = count;
        self
    }

    /// Commit to the event-envelope transport: a `$$client_ingestion_warning`
    /// [`CapturedEvent`] for the public event lane, keyed by API token.
    ///
    /// Carries no classification: the Node consumer resolves the token to a
    /// team, applies the capture trust allowlist to the structured type, and
    /// stamps category/severity from its own registry — nothing arriving on
    /// this lane is believed about itself. Injects `count` (batch dedup) and
    /// the source's `pipelineStep` into details.
    pub fn into_event_envelope(
        self,
        token: &str,
        source: WarningSource,
    ) -> Result<CapturedEvent, serde_json::Error> {
        let timestamp = Utc::now();
        let mut details = self.details;
        details.insert("count".to_string(), json!(self.count));
        // The consumer lifts `pipelineStep` out of details into the warning's
        // top-level pipeline_step column, so it must live inside details here.
        details.insert("pipelineStep".to_string(), json!(source.pipeline_step));

        let mut properties: HashMap<String, Value> = HashMap::new();
        properties.insert(PROP_TYPE.to_string(), json!(self.warning.as_str()));
        properties.insert(PROP_SOURCE.to_string(), json!(source.service));
        properties.insert(PROP_DETAILS.to_string(), Value::Object(details));

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

    /// Commit to the direct-row transport: the terminal v2 warning row for
    /// the ACL-guarded warnings topic, addressed by `team_id`.
    ///
    /// Classification is producer-stamped here — the registry's
    /// `category()`/`severity()`, the row's own `teamId`, and the source's
    /// `pipelineStep` (which the v2 table materializes its `pipeline_step`
    /// column from) are inserted over the caller's details so a stray key
    /// can never override them or disagree with the addressing — and the
    /// `timestamp` uses the ClickHouse format the v2 table materializes
    /// columns from.
    pub fn into_row(self, team_id: i64, source: WarningSource) -> Value {
        let mut details = self.details;
        details.insert("teamId".to_string(), Value::from(team_id));
        details.insert("category".to_string(), Value::from(self.warning.category()));
        details.insert("severity".to_string(), Value::from(self.warning.severity()));
        details.insert("pipelineStep".to_string(), json!(source.pipeline_step));
        let details = Value::Object(details);
        json!({
            "team_id": team_id,
            "type": self.warning.as_str(),
            "source": source.service,
            "details": details.to_string(),
            "timestamp": Utc::now().format("%Y-%m-%d %H:%M:%S%.3f").to_string(),
        })
    }
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
        let event = Warning::new(WarningType::MissingEventName)
            .into_event_envelope("phc_test_token", CAPTURE_V1_ANALYTICS)
            .unwrap();

        assert_eq!(event.event, "$$client_ingestion_warning");
        assert_eq!(event.token, "phc_test_token");
        // distinct_id must be the (safe, bounded) token, never a caller value.
        assert_eq!(event.distinct_id, "phc_test_token");
    }

    #[test]
    fn envelope_properties_carry_the_structured_type_source_and_details() {
        let event = Warning::new(WarningType::MissingEventName)
            .with_detail("distinctId", "user-1")
            .with_detail("lib", "posthog-js")
            .with_count(3)
            .into_event_envelope("phc_test_token", CAPTURE_V1_ANALYTICS)
            .unwrap();

        let (raw, details) = parse_envelope(&event);
        assert_eq!(raw["properties"][PROP_TYPE], "missing_event_name");
        assert_eq!(raw["properties"][PROP_SOURCE], "capture");

        // Injected by the envelope terminal.
        assert_eq!(details["count"], 3);
        assert_eq!(details["pipelineStep"], "capture_validation");
        // Caller context passes through untouched — and no classification:
        // the consumer stamps category/severity itself.
        assert_eq!(details["distinctId"], "user-1");
        assert_eq!(details["lib"], "posthog-js");
        assert!(details.get("category").is_none());
        assert!(details.get("severity").is_none());
    }

    /// The offending distinct_id lives in `details` only; the envelope's
    /// top-level distinct_id stays the token so an oversized id can never make
    /// the consumer drop a `distinct_id_too_large` warning.
    #[test]
    fn oversized_offender_distinct_id_never_reaches_the_envelope_field() {
        let huge = "x".repeat(10_000);
        let event = Warning::new(WarningType::DistinctIdTooLarge)
            .with_detail("distinctId", huge)
            .into_event_envelope("phc_real", CAPTURE_V1_ANALYTICS)
            .unwrap();

        assert_eq!(event.distinct_id, "phc_real");
        let (_, details) = parse_envelope(&event);
        assert_eq!(details["distinctId"].as_str().unwrap().len(), 10_000);
    }

    /// The message `source` reflects the caller's [`crate::WarningSource`]
    /// rather than a hardcoded capture literal — the point of parameterizing
    /// the envelope for reuse by other Rust services.
    #[test]
    fn envelope_source_field_reflects_the_caller_supplied_source() {
        let other = WarningSource {
            service: "batch_import",
            path: "some_path",
            pipeline_step: "batch_import_validation",
        };
        let event = Warning::new(WarningType::EmptyBatch)
            .into_event_envelope("phc_test_token", other)
            .unwrap();
        let (raw, details) = parse_envelope(&event);
        assert_eq!(raw["properties"][PROP_SOURCE], "batch_import");
        assert_eq!(details["pipelineStep"], "batch_import_validation");
    }

    const TEST_ROW_SOURCE: WarningSource = WarningSource {
        service: "personhog-test",
        path: "test_path",
        pipeline_step: "personhog_test_step",
    };

    #[test]
    fn rows_carry_registry_types_and_classifications() {
        for warning in WarningType::ALL {
            let payload = Warning::new(warning)
                .with_detail("personId", "uuid-ish")
                .into_row(7, TEST_ROW_SOURCE);

            assert_eq!(payload["team_id"], 7);
            assert_eq!(payload["type"], warning.as_str());
            assert_eq!(payload["source"], "personhog-test");
            let details: Value =
                serde_json::from_str(payload["details"].as_str().unwrap()).unwrap();
            assert_eq!(details["category"], warning.category());
            assert_eq!(details["severity"], warning.severity());
            assert_eq!(details["teamId"], 7, "teamId is injected from addressing");
            assert_eq!(details["pipelineStep"], "personhog_test_step");
            assert_eq!(details["personId"], "uuid-ish");
            let timestamp = payload["timestamp"].as_str().unwrap();
            assert_eq!(timestamp.len(), 23);
            assert_eq!(timestamp.as_bytes()[10], b' ');
        }
    }

    #[test]
    fn row_injected_keys_cannot_be_overridden_by_caller_details() {
        let payload = Warning::new(WarningType::PersonPropertiesSizeViolation)
            .with_detail("category", "spoofed")
            .with_detail("teamId", 999)
            .with_detail("pipelineStep", "spoofed")
            .into_row(1, TEST_ROW_SOURCE);
        let details: Value = serde_json::from_str(payload["details"].as_str().unwrap()).unwrap();
        assert_eq!(details["category"], "size");
        assert_eq!(details["teamId"], 1);
        assert_eq!(details["pipelineStep"], "personhog_test_step");
    }
}
