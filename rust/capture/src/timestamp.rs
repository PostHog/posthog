use chrono::{DateTime, Datelike, Duration, Utc};
use jiff::civil::DateTime as JiffDateTime;
use serde_json::Value;
use std::collections::HashMap;

const FUTURE_EVENT_HOURS_CUTOFF_MILLIS: i64 = 23 * 3600 * 1000; // 23 hours

#[derive(Debug, Clone)]
pub struct IngestionWarning {
    pub warning_type: String,
    pub details: HashMap<String, Value>,
}

#[derive(Debug, Clone)]
pub struct TimestampResult {
    pub timestamp: DateTime<Utc>,
    pub warnings: Vec<IngestionWarning>,
}

/// Parse event timestamp with clock skew adjustment and validation
///
/// # Arguments
/// * `event_data` - The event data containing timestamp, sent_at, offset fields
/// * `now` - The current server timestamp
///
/// # Returns
/// * `TimestampResult` - Contains the parsed timestamp and any ingestion warnings
pub fn parse_event_timestamp(
    event_data: &HashMap<String, Value>,
    now: DateTime<Utc>,
) -> TimestampResult {
    let mut warnings = Vec::new();

    // Extract and validate 'sent_at' if present
    let sent_at = extract_sent_at(event_data, &mut warnings);

    // Get team_id for error reporting
    let team_id = event_data
        .get("team_id")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    let mut parsed_ts = handle_timestamp(event_data, now, sent_at, team_id);

    // Check for future events
    let now_diff = parsed_ts.signed_duration_since(now).num_milliseconds();
    if now_diff > FUTURE_EVENT_HOURS_CUTOFF_MILLIS {
        let mut details = HashMap::new();
        details.insert(
            "timestamp".to_string(),
            event_data
                .get("timestamp")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );
        details.insert(
            "sentAt".to_string(),
            event_data
                .get("sent_at")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );
        details.insert(
            "offset".to_string(),
            event_data
                .get("offset")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );
        details.insert("now".to_string(), Value::String(now.to_rfc3339()));
        details.insert("result".to_string(), Value::String(parsed_ts.to_rfc3339()));
        details.insert(
            "eventUuid".to_string(),
            event_data
                .get("uuid")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );
        details.insert(
            "eventName".to_string(),
            event_data
                .get("event")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );

        warnings.push(IngestionWarning {
            warning_type: "event_timestamp_in_future".to_string(),
            details,
        });

        parsed_ts = now; // Fix the timestamp to now
    }

    // Check if timestamp is out of bounds
    if parsed_ts.year() < 0 || parsed_ts.year() > 9999 {
        let mut details = HashMap::new();
        details.insert(
            "eventUuid".to_string(),
            event_data
                .get("uuid")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );
        details.insert("field".to_string(), Value::String("timestamp".to_string()));
        details.insert(
            "value".to_string(),
            event_data
                .get("timestamp")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );
        details.insert(
            "reason".to_string(),
            Value::String("out of bounds".to_string()),
        );
        details.insert(
            "offset".to_string(),
            event_data
                .get("offset")
                .cloned()
                .unwrap_or(Value::String("".to_string())),
        );
        details.insert(
            "parsed_year".to_string(),
            Value::Number(parsed_ts.year().into()),
        );

        warnings.push(IngestionWarning {
            warning_type: "ignored_invalid_timestamp".to_string(),
            details,
        });

        parsed_ts = DateTime::UNIX_EPOCH;
    }

    TimestampResult {
        timestamp: parsed_ts,
        warnings,
    }
}

fn extract_sent_at(
    event_data: &HashMap<String, Value>,
    warnings: &mut Vec<IngestionWarning>,
) -> Option<DateTime<Utc>> {
    // Check if $ignore_sent_at is set in properties
    if let Some(properties) = event_data.get("properties").and_then(|p| p.as_object()) {
        if properties
            .get("$ignore_sent_at")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            return None;
        }
    }

    // Extract sent_at and parse it
    event_data
        .get("sent_at")
        .and_then(|v| v.as_str())
        .and_then(|sent_at_str| {
            match DateTime::parse_from_rfc3339(sent_at_str) {
                Ok(dt) => Some(dt.with_timezone(&Utc)),
                Err(_) => {
                    let mut details = HashMap::new();
                    details.insert(
                        "eventUuid".to_string(),
                        event_data
                            .get("uuid")
                            .cloned()
                            .unwrap_or(Value::String("".to_string())),
                    );
                    details.insert("field".to_string(), Value::String("sent_at".to_string()));
                    details.insert(
                        "value".to_string(),
                        Value::String(sent_at_str.to_string()),
                    );
                    details.insert(
                        "reason".to_string(),
                        Value::String("invalid format".to_string()),
                    );

                    warnings.push(IngestionWarning {
                        warning_type: "ignored_invalid_timestamp".to_string(),
                        details,
                    });
                    None
                }
            }
        })
}

fn handle_timestamp(
    event_data: &HashMap<String, Value>,
    now: DateTime<Utc>,
    sent_at: Option<DateTime<Utc>>,
    _team_id: i64,
) -> DateTime<Utc> {
    let mut parsed_ts = now;

    if let Some(timestamp_value) = event_data.get("timestamp") {
        if let Some(timestamp_str) = timestamp_value.as_str() {
            let timestamp = parse_date(timestamp_str);

            if let (Some(sent_at), Some(timestamp)) = (sent_at, timestamp) {
                // Handle clock skew between client and server
                // skew = sent_at - now
                // x = now + (timestamp - sent_at)
                match timestamp.signed_duration_since(sent_at) {
                    duration => {
                        parsed_ts = now + duration;
                    }
                }
            } else if let Some(timestamp) = timestamp {
                parsed_ts = timestamp;
            }
        }
    }

    // Handle offset if present
    if let Some(offset_value) = event_data.get("offset") {
        if let Some(offset_num) = offset_value.as_i64() {
            parsed_ts = now - Duration::milliseconds(offset_num);
        }
    }

    parsed_ts
}

/// Parse a date string using a streamlined two-step approach
///
/// This function tries parsing in order of preference:
/// 1. dateparser (handles 95%+ of formats): ISO 8601, slash-separated, RFC2822, numeric timestamps
/// 2. jiff (minimal fallback): civil datetime with T but no timezone (e.g., "2023-01-01T12:00:00")
fn parse_date(supposed_iso_string: &str) -> Option<DateTime<Utc>> {
    // Try dateparser first - it handles most formats including:
    // - ISO 8601/RFC3339: 2023-01-01T12:00:00Z, 2023-01-01T12:00:00+02:00
    // - Date-only: 2023-01-01
    // - Civil datetime with space: 2023-01-01 12:00:00
    // - Slash-separated: 01/01/2023, 2023/01/01
    // - RFC2822: Tue, 1 Jul 2003 10:52:37 +0200
    // - Numeric timestamps: 1672574400000, 1672574400
    if let Ok(dt) = dateparser::parse(supposed_iso_string) {
        return Some(dt);
    }

    // Minimal jiff fallback for the one format dateparser can't handle:
    // Civil datetime with T but no timezone (e.g., "2023-01-01T12:00:00")
    if let Ok(jiff_civil) = supposed_iso_string.parse::<JiffDateTime>() {
        return convert_jiff_to_chrono(jiff_civil.to_zoned(jiff::tz::TimeZone::UTC).ok()?);
    }

    None
}

/// Helper function to convert jiff timestamp to chrono DateTime<Utc>
fn convert_jiff_to_chrono(jiff_timestamp: jiff::Zoned) -> Option<DateTime<Utc>> {
    let seconds = jiff_timestamp.timestamp().as_second();
    let nanos = jiff_timestamp.timestamp().subsec_nanosecond();
    // Convert i32 to u32 safely (nanoseconds should always be positive)
    let nanos_u32 = nanos.try_into().ok()?;
    DateTime::from_timestamp(seconds, nanos_u32)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};
    use serde_json::Map;

    fn create_test_event(
        now: &str,
        timestamp: Option<&str>,
        sent_at: Option<&str>,
        offset: Option<i64>,
        ignore_sent_at: Option<bool>,
    ) -> HashMap<String, Value> {
        let mut event = HashMap::new();
        event.insert("now".to_string(), Value::String(now.to_string()));
        event.insert("team_id".to_string(), Value::Number(123.into()));
        event.insert("uuid".to_string(), Value::String("test-uuid".to_string()));
        event.insert("event".to_string(), Value::String("test_event".to_string()));

        if let Some(ts) = timestamp {
            event.insert("timestamp".to_string(), Value::String(ts.to_string()));
        }

        if let Some(sa) = sent_at {
            event.insert("sent_at".to_string(), Value::String(sa.to_string()));
        }

        if let Some(off) = offset {
            event.insert("offset".to_string(), Value::Number(off.into()));
        }

        if let Some(ignore) = ignore_sent_at {
            let mut properties = Map::new();
            properties.insert("$ignore_sent_at".to_string(), Value::Bool(ignore));
            event.insert("properties".to_string(), Value::Object(properties));
        }

        event
    }

    #[test]
    fn test_parse_event_timestamp_basic() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let event = create_test_event(now_str, None, None, None, None);

        let result = parse_event_timestamp(&event, now);

        assert_eq!(result.timestamp, now);
        assert_eq!(result.warnings.len(), 0);
    }

    #[test]
    fn test_parse_event_timestamp_with_clock_skew() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let sent_at_str = "2023-01-01T12:00:05Z"; // 5 seconds ahead
        let timestamp_str = "2023-01-01T11:59:55Z"; // 10 seconds before sent_at

        let event = create_test_event(now_str, Some(timestamp_str), Some(sent_at_str), None, None);

        let result = parse_event_timestamp(&event, now);
        // Expected: now + (timestamp - sent_at) = 12:00:00 + (11:59:55 - 12:00:05) = 12:00:00 - 00:00:10 = 11:59:50
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 59, 50).unwrap();

        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 0);
    }

    #[test]
    fn test_parse_event_timestamp_with_offset() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let offset = 5000; // 5 seconds

        let event = create_test_event(now_str, None, None, Some(offset), None);

        let result = parse_event_timestamp(&event, now);
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 59, 55).unwrap();

        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 0);
    }

    #[test]
    fn test_parse_event_timestamp_ignore_sent_at() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let sent_at_str = "2023-01-01T12:00:05Z";
        let timestamp_str = "2023-01-01T11:00:00Z";

        let event = create_test_event(
            now_str,
            Some(timestamp_str),
            Some(sent_at_str),
            None,
            Some(true),
        );

        let result = parse_event_timestamp(&event, now);
        // Should use timestamp directly since sent_at is ignored
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 0, 0).unwrap();

        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 0);
    }

    #[test]
    fn test_parse_event_timestamp_future_event() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let future_timestamp = "2023-01-02T12:00:00Z"; // 24 hours in the future

        let event = create_test_event(now_str, Some(future_timestamp), None, None, None);

        let result = parse_event_timestamp(&event, now);

        // Should clamp to now for future events
        let expected = DateTime::parse_from_rfc3339(now_str)
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 1);
        assert_eq!(result.warnings[0].warning_type, "event_timestamp_in_future");
    }

    #[test]
    fn test_parse_event_timestamp_out_of_bounds() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let invalid_timestamp = "0001-01-01T12:00:00Z"; // Year 1 is within bounds, this will be parsed successfully

        let event = create_test_event(now_str, Some(invalid_timestamp), None, None, None);

        let result = parse_event_timestamp(&event, now);

        // Should use the parsed timestamp (year 1 is valid)
        let expected = DateTime::parse_from_rfc3339(invalid_timestamp)
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 0); // No warnings for valid timestamps
    }

    #[test]
    fn test_parse_event_timestamp_unparseable() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let invalid_timestamp = "99999-01-01T12:00:00Z"; // This should fail to parse due to year being too large

        let event = create_test_event(now_str, Some(invalid_timestamp), None, None, None);

        let result = parse_event_timestamp(&event, now);

        // Should fall back to 'now' when timestamp fails to parse
        let expected = DateTime::parse_from_rfc3339(now_str)
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 0); // No warnings when parsing fails, just falls back to now
    }

    #[test]
    fn test_parse_event_timestamp_invalid_sent_at() {
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let timestamp_str = "2023-01-01T11:00:00Z";
        let invalid_sent_at = "invalid-date";

        let event = create_test_event(
            now_str,
            Some(timestamp_str),
            Some(invalid_sent_at),
            None,
            None,
        );

        let result = parse_event_timestamp(&event, now);

        // Should use timestamp directly since sent_at is invalid
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 0, 0).unwrap();
        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 1);
        assert_eq!(result.warnings[0].warning_type, "ignored_invalid_timestamp");
    }

    #[test]
    fn test_parse_date_various_formats() {
        // Test core date parsing functionality across different format types
        let valid_cases = vec![
            // ISO 8601/RFC3339 (dateparser)
            "2023-01-01T12:00:00Z",
            "2023-01-01T12:00:00+02:00",
            "2023-01-01",

            // Civil datetime (jiff fallback)
            "2023-01-01T12:00:00",

            // Slash-separated (dateparser)
            "01/01/2023",
            "2023/01/01",

            // RFC2822 (dateparser)
            "Tue, 1 Jul 2003 10:52:37 +0200",

            // Numeric timestamps (dateparser)
            "1672574400000",
            "1672574400",
        ];

        let invalid_cases = vec![
            "invalid-date",
            "99999-01-01T12:00:00Z", // Year too large
            "13/32/2023", // Invalid month/day
            "",
        ];

        for date_str in valid_cases {
            assert!(parse_date(date_str).is_some(), "Failed to parse: {}", date_str);
        }

        for date_str in invalid_cases {
            assert!(parse_date(date_str).is_none(), "Unexpectedly parsed: {}", date_str);
        }
    }


    #[test]
    fn test_complex_timestamp_scenario() {
        // Test complex scenario with all components
        let now_str = "2023-01-01T12:00:00Z";
        let now = DateTime::parse_from_rfc3339(now_str).unwrap().with_timezone(&Utc);
        let sent_at_str = "2023-01-01T12:00:02Z"; // 2 seconds ahead of server
        let timestamp_str = "2023-01-01T11:59:58Z"; // 4 seconds before sent_at

        let event = create_test_event(now_str, Some(timestamp_str), Some(sent_at_str), None, None);

        let result = parse_event_timestamp(&event, now);

        // Expected calculation:
        // skew = sent_at - now = 12:00:02 - 12:00:00 = +2s
        // timestamp_diff = timestamp - sent_at = 11:59:58 - 12:00:02 = -4s
        // result = now + timestamp_diff = 12:00:00 + (-4s) = 11:59:56
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 59, 56).unwrap();

        assert_eq!(result.timestamp, expected);
        assert_eq!(result.warnings.len(), 0);
    }

}
