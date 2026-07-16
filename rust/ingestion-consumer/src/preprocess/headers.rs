//! Typed event-header parsing from the raw Kafka header map.
//!
//! [`EventHeaders`] extracts the subset of headers the preprocess pipeline
//! reads, before the event body is parsed. Mirrors the Node.js `EventHeaders`
//! type and `parseEventHeaders` (`common/kafka/consumer/consumer-v1.ts`),
//! including the per-header presence counter (`kafka_header_status_total`).
//!
//! POC note: the Node parser also runs `sanitizeString` on `token`/`distinct_id`
//! and `normalizeSessionId` on `session_id`. Those normalizations are not ported
//! here (recorded in `common/pipelines/POC_NOTES.md`); values are taken verbatim.

use std::collections::HashMap;

use metrics::counter;

use super::metrics_consts::KAFKA_HEADER_STATUS;

/// The subset of Kafka message headers the preprocess pipeline reads. Parsed
/// once per message from the raw header map, before the event body is touched.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EventHeaders {
    pub token: Option<String>,
    pub distinct_id: Option<String>,
    pub session_id: Option<String>,
    pub timestamp: Option<String>,
    pub event: Option<String>,
    pub uuid: Option<String>,
    pub now: Option<String>,
    pub force_disable_person_processing: bool,
    pub historical_migration: bool,
    pub skip_heatmap_processing: bool,
}

/// The headers whose presence is tracked, in the Node.js order.
const TRACKED_HEADERS: [&str; 10] = [
    "token",
    "distinct_id",
    "session_id",
    "timestamp",
    "event",
    "uuid",
    "now",
    "force_disable_person_processing",
    "historical_migration",
    "skip_heatmap_processing",
];

impl EventHeaders {
    /// Parse the tracked headers out of the raw string map and emit a
    /// presence/absence counter per tracked header. Presence mirrors Node's
    /// truthiness check: a string header counts as present only when non-empty;
    /// a boolean header counts as present only when `true`.
    pub fn parse(headers: &HashMap<String, String>) -> Self {
        let string_field = |key: &str| headers.get(key).filter(|value| !value.is_empty()).cloned();
        let bool_field = |key: &str| headers.get(key).map(String::as_str) == Some("true");

        let parsed = EventHeaders {
            token: string_field("token"),
            distinct_id: string_field("distinct_id"),
            session_id: string_field("session_id"),
            timestamp: string_field("timestamp"),
            event: string_field("event"),
            uuid: string_field("uuid"),
            now: string_field("now"),
            force_disable_person_processing: bool_field("force_disable_person_processing"),
            historical_migration: bool_field("historical_migration"),
            skip_heatmap_processing: bool_field("skip_heatmap_processing"),
        };
        parsed.emit_status_metrics();
        parsed
    }

    fn is_present(&self, header: &str) -> bool {
        match header {
            "token" => self.token.is_some(),
            "distinct_id" => self.distinct_id.is_some(),
            "session_id" => self.session_id.is_some(),
            "timestamp" => self.timestamp.is_some(),
            "event" => self.event.is_some(),
            "uuid" => self.uuid.is_some(),
            "now" => self.now.is_some(),
            "force_disable_person_processing" => self.force_disable_person_processing,
            "historical_migration" => self.historical_migration,
            "skip_heatmap_processing" => self.skip_heatmap_processing,
            _ => false,
        }
    }

    fn emit_status_metrics(&self) {
        for header in TRACKED_HEADERS {
            let status = if self.is_present(header) {
                "present"
            } else {
                "absent"
            };
            counter!(KAFKA_HEADER_STATUS, "header" => header, "status" => status).increment(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn map(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn parses_all_fields() {
        let headers = map(&[
            ("token", "phc_abc"),
            ("distinct_id", "user-1"),
            ("session_id", "sess-1"),
            ("timestamp", "2026-07-14T00:00:00Z"),
            ("event", "$pageview"),
            ("uuid", "01890000-0000-0000-0000-000000000000"),
            ("now", "2026-07-14T00:00:01Z"),
            ("force_disable_person_processing", "true"),
            ("historical_migration", "true"),
            ("skip_heatmap_processing", "true"),
        ]);
        let parsed = EventHeaders::parse(&headers);
        assert_eq!(parsed.token.as_deref(), Some("phc_abc"));
        assert_eq!(parsed.distinct_id.as_deref(), Some("user-1"));
        assert_eq!(parsed.session_id.as_deref(), Some("sess-1"));
        assert_eq!(parsed.timestamp.as_deref(), Some("2026-07-14T00:00:00Z"));
        assert_eq!(parsed.event.as_deref(), Some("$pageview"));
        assert_eq!(
            parsed.uuid.as_deref(),
            Some("01890000-0000-0000-0000-000000000000")
        );
        assert_eq!(parsed.now.as_deref(), Some("2026-07-14T00:00:01Z"));
        assert!(parsed.force_disable_person_processing);
        assert!(parsed.historical_migration);
        assert!(parsed.skip_heatmap_processing);
    }

    #[test]
    fn missing_headers_default_to_none_and_false() {
        let parsed = EventHeaders::parse(&HashMap::new());
        assert_eq!(parsed, EventHeaders::default());
        assert!(parsed.token.is_none());
        assert!(!parsed.force_disable_person_processing);
        assert!(!parsed.historical_migration);
        assert!(!parsed.skip_heatmap_processing);
    }

    #[test]
    fn empty_string_values_are_absent() {
        let headers = map(&[("token", ""), ("event", "")]);
        let parsed = EventHeaders::parse(&headers);
        assert!(parsed.token.is_none());
        assert!(parsed.event.is_none());
    }

    #[test]
    fn boolean_headers_only_true_is_true() {
        for (value, expected) in [("true", true), ("false", false), ("1", false), ("", false)] {
            let headers = map(&[("historical_migration", value)]);
            let parsed = EventHeaders::parse(&headers);
            assert_eq!(parsed.historical_migration, expected, "value {value:?}");
        }
    }
}
