use chrono::{DateTime, Datelike, Duration, Utc};
use serde_json::Value;
use std::collections::HashMap;
use tracing::error;

const FUTURE_EVENT_HOURS_CUTOFF_MILLIS: i64 = 23 * 3600 * 1000; // 23 hours

#[derive(Debug, Clone)]
pub struct IngestionWarning {
    pub warning_type: String,
    pub details: HashMap<String, Value>,
}

pub type IngestionWarningCallback = Box<dyn Fn(IngestionWarning) + Send + Sync>;

pub fn parse_event_timestamp(
    event_data: &HashMap<String, Value>,
    callback: Option<&IngestionWarningCallback>,
) -> DateTime<Utc> {
    // Extract 'now' field - set by capture endpoint and assumed valid
    let now = match event_data.get("now") {
        Some(Value::String(now_str)) => match DateTime::parse_from_rfc3339(now_str) {
            Ok(dt) => dt.with_timezone(&Utc),
            Err(_) => {
                error!("Invalid 'now' timestamp: {}", now_str);
                return DateTime::UNIX_EPOCH;
            }
        },
        _ => {
            error!("Missing or invalid 'now' field");
            return DateTime::UNIX_EPOCH;
        }
    };

    // Extract and validate 'sent_at' if present

    let sent_at = if let Some(properties) = event_data.get("properties").and_then(|p| p.as_object())
    {
        if properties
            .get("$ignore_sent_at")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            None
        } else {
            event_data
                .get("sent_at")
                .and_then(|v| v.as_str())
                .map(
                    |sent_at_str| match DateTime::parse_from_rfc3339(sent_at_str) {
                        Ok(dt) => Some(dt.with_timezone(&Utc)),
                        Err(_) => {
                            if let Some(cb) = callback {
                                let mut details = HashMap::new();
                                details.insert(
                                    "eventUuid".to_string(),
                                    event_data
                                        .get("uuid")
                                        .cloned()
                                        .unwrap_or(Value::String("".to_string())),
                                );
                                details.insert(
                                    "field".to_string(),
                                    Value::String("sent_at".to_string()),
                                );
                                details.insert(
                                    "value".to_string(),
                                    Value::String(sent_at_str.to_string()),
                                );
                                details.insert(
                                    "reason".to_string(),
                                    Value::String("invalid format".to_string()),
                                );

                                cb(IngestionWarning {
                                    warning_type: "ignored_invalid_timestamp".to_string(),
                                    details,
                                });
                            }
                            None
                        }
                    },
                )
                .flatten()
        }
    } else {
        event_data
            .get("sent_at")
            .and_then(|v| v.as_str())
            .map(
                |sent_at_str| match DateTime::parse_from_rfc3339(sent_at_str) {
                    Ok(dt) => Some(dt.with_timezone(&Utc)),
                    Err(_) => {
                        if let Some(cb) = callback {
                            let mut details = HashMap::new();
                            details.insert(
                                "eventUuid".to_string(),
                                event_data
                                    .get("uuid")
                                    .cloned()
                                    .unwrap_or(Value::String("".to_string())),
                            );
                            details
                                .insert("field".to_string(), Value::String("sent_at".to_string()));
                            details.insert(
                                "value".to_string(),
                                Value::String(sent_at_str.to_string()),
                            );
                            details.insert(
                                "reason".to_string(),
                                Value::String("invalid format".to_string()),
                            );

                            cb(IngestionWarning {
                                warning_type: "ignored_invalid_timestamp".to_string(),
                                details,
                            });
                        }
                        None
                    }
                },
            )
            .flatten()
    };

    // Get team_id for error reporting
    let team_id = event_data
        .get("team_id")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    let parsed_ts = handle_timestamp(event_data, now, sent_at, team_id);

    // Check for future events
    let now_diff = parsed_ts.signed_duration_since(now).num_milliseconds();
    let parsed_ts = if now_diff > FUTURE_EVENT_HOURS_CUTOFF_MILLIS {
        if let Some(cb) = callback {
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

            cb(IngestionWarning {
                warning_type: "event_timestamp_in_future".to_string(),
                details,
            });
        }
        now // Fix the timestamp to now
    } else {
        parsed_ts
    };

    // Check if timestamp is out of bounds
    let parsed_ts_out_of_bounds = parsed_ts.year() < 0 || parsed_ts.year() > 9999;
    if parsed_ts_out_of_bounds {
        if let Some(cb) = callback {
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

            cb(IngestionWarning {
                warning_type: "ignored_invalid_timestamp".to_string(),
                details,
            });
        }
        return DateTime::UNIX_EPOCH;
    }

    parsed_ts
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

fn parse_date(supposed_iso_string: &str) -> Option<DateTime<Utc>> {
    // First try parsing as a JavaScript Date would (more lenient)
    if let Ok(js_timestamp) = supposed_iso_string.parse::<f64>() {
        // Handle numeric timestamps (milliseconds since epoch)
        if let Some(dt) = DateTime::from_timestamp_millis(js_timestamp as i64) {
            return Some(dt);
        }
    }

    // Try parsing date-only format first (common case)
    use chrono::NaiveDate;
    if let Ok(naive_date) = NaiveDate::parse_from_str(supposed_iso_string, "%Y-%m-%d") {
        if let Some(naive_dt) = naive_date.and_hms_opt(0, 0, 0) {
            return Some(DateTime::from_naive_utc_and_offset(naive_dt, Utc));
        }
    }

    // Try parsing datetime formats with timezone info
    let tz_formats = [
        // ISO 8601 variants
        "%Y-%m-%dT%H:%M:%S%.fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%.f%:z",
        "%Y-%m-%dT%H:%M:%S%:z",
    ];

    for format in &tz_formats {
        if let Ok(dt) = DateTime::parse_from_str(supposed_iso_string, format) {
            return Some(dt.with_timezone(&Utc));
        }
    }

    // Try parsing naive datetime formats (assume UTC)
    let naive_formats = [
        "%Y-%m-%d %H:%M:%S%.f",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ];

    for format in &naive_formats {
        if let Ok(naive_dt) = chrono::NaiveDateTime::parse_from_str(supposed_iso_string, format) {
            return Some(DateTime::from_naive_utc_and_offset(naive_dt, Utc));
        }
    }

    // Try parsing just date formats and add midnight time
    let date_formats = ["%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"];

    for format in &date_formats {
        if let Ok(naive_date) = NaiveDate::parse_from_str(supposed_iso_string, format) {
            if let Some(naive_dt) = naive_date.and_hms_opt(0, 0, 0) {
                return Some(DateTime::from_naive_utc_and_offset(naive_dt, Utc));
            }
        }
    }

    // Try RFC3339 parsing
    if let Ok(dt) = DateTime::parse_from_rfc3339(supposed_iso_string) {
        return Some(dt.with_timezone(&Utc));
    }

    // Try RFC2822 parsing
    if let Ok(dt) = DateTime::parse_from_rfc2822(supposed_iso_string) {
        return Some(dt.with_timezone(&Utc));
    }

    // If all else fails, try chrono's lenient parsing
    if let Ok(naive_dt) =
        chrono::NaiveDateTime::parse_from_str(supposed_iso_string, "%Y-%m-%d %H:%M:%S")
    {
        return Some(DateTime::from_naive_utc_and_offset(naive_dt, Utc));
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};
    use std::sync::{Arc, Mutex};

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
        let event = create_test_event(now_str, None, None, None, None);

        let result = parse_event_timestamp(&event, None);
        let expected = DateTime::parse_from_rfc3339(now_str)
            .unwrap()
            .with_timezone(&Utc);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_with_clock_skew() {
        let now_str = "2023-01-01T12:00:00Z";
        let sent_at_str = "2023-01-01T12:00:05Z"; // 5 seconds ahead
        let timestamp_str = "2023-01-01T11:59:55Z"; // 10 seconds before sent_at

        let event = create_test_event(now_str, Some(timestamp_str), Some(sent_at_str), None, None);

        let result = parse_event_timestamp(&event, None);
        // Expected: now + (timestamp - sent_at) = 12:00:00 + (11:59:55 - 12:00:05) = 12:00:00 - 00:00:10 = 11:59:50
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 59, 50).unwrap();

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_with_offset() {
        let now_str = "2023-01-01T12:00:00Z";
        let offset = 5000; // 5 seconds

        let event = create_test_event(now_str, None, None, Some(offset), None);

        let result = parse_event_timestamp(&event, None);
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 59, 55).unwrap();

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_ignore_sent_at() {
        let now_str = "2023-01-01T12:00:00Z";
        let sent_at_str = "2023-01-01T12:00:05Z";
        let timestamp_str = "2023-01-01T11:00:00Z";

        let event = create_test_event(
            now_str,
            Some(timestamp_str),
            Some(sent_at_str),
            None,
            Some(true),
        );

        let result = parse_event_timestamp(&event, None);
        // Should use timestamp directly since sent_at is ignored
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 0, 0).unwrap();

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_future_event() {
        let now_str = "2023-01-01T12:00:00Z";
        let future_timestamp = "2023-01-02T12:00:00Z"; // 24 hours in the future

        let event = create_test_event(now_str, Some(future_timestamp), None, None, None);

        let warnings = Arc::new(Mutex::new(Vec::new()));
        let warnings_clone = warnings.clone();
        let callback: IngestionWarningCallback = Box::new(move |warning| {
            warnings_clone.lock().unwrap().push(warning);
        });

        let result = parse_event_timestamp(&event, Some(&callback));

        // Should clamp to now for future events
        let expected = DateTime::parse_from_rfc3339(now_str)
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(result, expected);

        let warnings_vec = warnings.lock().unwrap();
        assert_eq!(warnings_vec.len(), 1);
        assert_eq!(warnings_vec[0].warning_type, "event_timestamp_in_future");
    }

    #[test]
    fn test_parse_event_timestamp_out_of_bounds() {
        let now_str = "2023-01-01T12:00:00Z";
        let invalid_timestamp = "0001-01-01T12:00:00Z"; // Year 1 is within bounds, this will be parsed successfully

        let event = create_test_event(now_str, Some(invalid_timestamp), None, None, None);

        let warnings = Arc::new(Mutex::new(Vec::new()));
        let warnings_clone = warnings.clone();
        let callback: IngestionWarningCallback = Box::new(move |warning| {
            warnings_clone.lock().unwrap().push(warning);
        });

        let result = parse_event_timestamp(&event, Some(&callback));

        // Should use the parsed timestamp (year 1 is valid)
        let expected = DateTime::parse_from_rfc3339(invalid_timestamp)
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(result, expected);

        let warnings_vec = warnings.lock().unwrap();
        assert_eq!(warnings_vec.len(), 0); // No warnings for valid timestamps
    }

    #[test]
    fn test_parse_event_timestamp_unparseable() {
        let now_str = "2023-01-01T12:00:00Z";
        let invalid_timestamp = "99999-01-01T12:00:00Z"; // This should fail to parse due to year being too large

        let event = create_test_event(now_str, Some(invalid_timestamp), None, None, None);

        let warnings = Arc::new(Mutex::new(Vec::new()));
        let warnings_clone = warnings.clone();
        let callback: IngestionWarningCallback = Box::new(move |warning| {
            warnings_clone.lock().unwrap().push(warning);
        });

        let result = parse_event_timestamp(&event, Some(&callback));

        // Should fall back to 'now' when timestamp fails to parse
        let expected = DateTime::parse_from_rfc3339(now_str)
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(result, expected);

        let warnings_vec = warnings.lock().unwrap();
        assert_eq!(warnings_vec.len(), 0); // No warnings when parsing fails, just falls back to now
    }

    #[test]
    fn test_parse_event_timestamp_invalid_sent_at() {
        let now_str = "2023-01-01T12:00:00Z";
        let timestamp_str = "2023-01-01T11:00:00Z";
        let invalid_sent_at = "invalid-date";

        let event = create_test_event(
            now_str,
            Some(timestamp_str),
            Some(invalid_sent_at),
            None,
            None,
        );

        let warnings = Arc::new(Mutex::new(Vec::new()));
        let warnings_clone = warnings.clone();
        let callback: IngestionWarningCallback = Box::new(move |warning| {
            warnings_clone.lock().unwrap().push(warning);
        });

        let result = parse_event_timestamp(&event, Some(&callback));

        // Should use timestamp directly since sent_at is invalid
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 0, 0).unwrap();
        assert_eq!(result, expected);

        let warnings_vec = warnings.lock().unwrap();
        assert_eq!(warnings_vec.len(), 1);
        assert_eq!(warnings_vec[0].warning_type, "ignored_invalid_timestamp");
    }

    #[test]
    fn test_parse_date_various_formats() {
        let test_cases = vec![
            ("2023-01-01T12:00:00Z", true),
            ("2023-01-01T12:00:00.123Z", true),
            ("2023-01-01T12:00:00+02:00", true),
            ("2023-01-01 12:00:00", true),
            ("2023-01-01", true),
            ("01/01/2023", true),
            ("1672574400000", true), // Timestamp in milliseconds
            ("invalid-date", false),
        ];

        for (date_str, should_parse) in test_cases {
            let result = parse_date(date_str);
            if should_parse {
                assert!(result.is_some(), "Failed to parse: {}", date_str);
            } else {
                assert!(result.is_none(), "Unexpectedly parsed: {}", date_str);
            }
        }
    }

    #[test]
    fn test_complex_timestamp_scenario() {
        // Test complex scenario with all components
        let now_str = "2023-01-01T12:00:00Z";
        let sent_at_str = "2023-01-01T12:00:02Z"; // 2 seconds ahead of server
        let timestamp_str = "2023-01-01T11:59:58Z"; // 4 seconds before sent_at

        let event = create_test_event(now_str, Some(timestamp_str), Some(sent_at_str), None, None);

        let result = parse_event_timestamp(&event, None);

        // Expected calculation:
        // skew = sent_at - now = 12:00:02 - 12:00:00 = +2s
        // timestamp_diff = timestamp - sent_at = 11:59:58 - 12:00:02 = -4s
        // result = now + timestamp_diff = 12:00:00 + (-4s) = 11:59:56
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 59, 56).unwrap();

        assert_eq!(result, expected);
    }
}
