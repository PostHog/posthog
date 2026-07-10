//! Serializer for the v2 ingestion warnings message contract.
//!
//! Messages are `JSONEachRow` rows for the `clickhouse_ingestion_warnings`
//! topic, consumed by the 5-column `kafka_ingestion_warnings_v2` table:
//! exactly `team_id`, `type`, `source`, `details`, `timestamp` at the top
//! level. All structured attributes live inside `details`, which is a
//! stringified (double-encoded) JSON object — matching the Node.js
//! `serializeIngestionWarning` contract so the storage table's `DEFAULT
//! JSONExtractString(details, ...)` columns populate.
//!
//! Producers without database access (capture) cannot resolve token→team, so
//! rows are emitted with `team_id: 0` and the API token stamped into
//! `details.token`; the read side matches them to a team by token.

use chrono::{DateTime, Utc};
use serde_json::{json, Map, Value};

use crate::registry::WarningType;

/// `source` field for warnings emitted by capture.
pub const SOURCE_CAPTURE: &str = "capture";

/// ClickHouse `DateTime64(6, 'UTC')`-parseable timestamp format.
const TIMESTAMP_FORMAT: &str = "%Y-%m-%d %H:%M:%S%.6f";

/// Serialize one warning into a `JSONEachRow` message payload.
///
/// `extra_details` carries caller-supplied context (camelCase keys such as
/// `distinctId`, `eventUuid`, `lib`, `path`). The serializer injects `token`,
/// `count`, `category`, `severity`, and `pipelineStep` itself so callers can
/// never produce an inconsistent row; caller-supplied values for those keys
/// are overwritten.
pub fn serialize_warning(
    token: &str,
    warning: WarningType,
    mut extra_details: Map<String, Value>,
    count: u64,
    timestamp: DateTime<Utc>,
) -> Result<Vec<u8>, serde_json::Error> {
    extra_details.insert("token".to_string(), json!(token));
    extra_details.insert("count".to_string(), json!(count));
    extra_details.insert("category".to_string(), json!(warning.category()));
    extra_details.insert("severity".to_string(), json!(warning.severity()));
    extra_details.insert("pipelineStep".to_string(), json!(warning.pipeline_step()));

    let details = serde_json::to_string(&extra_details)?;
    let row = json!({
        "team_id": 0,
        "type": warning.as_str(),
        "source": SOURCE_CAPTURE,
        "details": details,
        "timestamp": timestamp.format(TIMESTAMP_FORMAT).to_string(),
    });
    serde_json::to_vec(&row)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn sample_row() -> Value {
        let mut extra = Map::new();
        extra.insert("distinctId".to_string(), json!("user-1"));
        extra.insert(
            "eventUuid".to_string(),
            json!("0196fe0f-0000-7000-8000-000000000000"),
        );
        extra.insert("lib".to_string(), json!("posthog-js"));
        let ts = Utc.with_ymd_and_hms(2026, 7, 10, 21, 0, 0).unwrap()
            + chrono::Duration::microseconds(123456);
        let bytes = serialize_warning(
            "phc_test_token",
            WarningType::MissingEventName,
            extra,
            3,
            ts,
        )
        .unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    #[test]
    fn row_has_exactly_the_five_kafka_table_columns() {
        let row = sample_row();
        let obj = row.as_object().unwrap();
        let mut keys: Vec<&str> = obj.keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            ["details", "source", "team_id", "timestamp", "type"],
            "extra or missing top-level keys break the 5-column Kafka table"
        );
        assert_eq!(row["team_id"], 0);
        assert_eq!(row["type"], "missing_event_name");
        assert_eq!(row["source"], "capture");
    }

    #[test]
    fn timestamp_is_clickhouse_datetime64_format() {
        let row = sample_row();
        assert_eq!(row["timestamp"], "2026-07-10 21:00:00.123456");
    }

    #[test]
    fn details_is_double_encoded_with_injected_metadata_and_caller_context() {
        let row = sample_row();
        // `details` must be a JSON *string* (double-encoded), not an object.
        let details_str = row["details"].as_str().expect("details must be a string");
        let details: Value = serde_json::from_str(details_str).unwrap();

        // Injected by the serializer.
        assert_eq!(details["token"], "phc_test_token");
        assert_eq!(details["count"], 3);
        assert_eq!(details["category"], "event");
        assert_eq!(details["severity"], "error");
        assert_eq!(details["pipelineStep"], "capture_validation");

        // Caller-provided camelCase entity keys pass through untouched.
        assert_eq!(details["distinctId"], "user-1");
        assert_eq!(details["eventUuid"], "0196fe0f-0000-7000-8000-000000000000");
        assert_eq!(details["lib"], "posthog-js");
    }

    #[test]
    fn serializer_overwrites_caller_supplied_reserved_keys() {
        let mut extra = Map::new();
        extra.insert("severity".to_string(), json!("info"));
        extra.insert("token".to_string(), json!("spoofed"));
        let bytes =
            serialize_warning("phc_real", WarningType::EmptyBatch, extra, 1, Utc::now()).unwrap();
        let row: Value = serde_json::from_slice(&bytes).unwrap();
        let details: Value = serde_json::from_str(row["details"].as_str().unwrap()).unwrap();
        assert_eq!(details["severity"], "error");
        assert_eq!(details["token"], "phc_real");
    }
}
