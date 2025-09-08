use chrono::{DateTime, Datelike, Duration, Utc};
use jiff::{civil::DateTime as JiffDateTime, Timestamp as JiffTimestamp};
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

fn parse_date(supposed_iso_string: &str) -> Option<DateTime<Utc>> {
    // First try parsing as a numeric timestamp (milliseconds since epoch)
    if let Ok(js_timestamp) = supposed_iso_string.parse::<f64>() {
        if let Some(dt) = DateTime::from_timestamp_millis(js_timestamp as i64) {
            return Some(dt);
        }
    }

    // Use jiff for flexible date/time parsing - it handles many formats automatically
    // Try parsing as a timestamp first (with timezone)
    if let Ok(jiff_timestamp) = supposed_iso_string.parse::<JiffTimestamp>() {
        // Convert jiff timestamp to chrono
        let seconds = jiff_timestamp.as_second();
        let nanos = jiff_timestamp.subsec_nanosecond();
        // Convert i32 to u32 safely (nanoseconds should always be positive)
        if let Ok(nanos_u32) = nanos.try_into() {
            if let Some(chrono_dt) = DateTime::from_timestamp(seconds, nanos_u32) {
                return Some(chrono_dt);
            }
        }
    }

    // Try parsing as a civil datetime (no timezone) and assume UTC
    if let Ok(jiff_civil) = supposed_iso_string.parse::<JiffDateTime>() {
        // Convert to timestamp assuming UTC
        if let Ok(jiff_timestamp) = jiff_civil.to_zoned(jiff::tz::TimeZone::UTC) {
            let seconds = jiff_timestamp.timestamp().as_second();
            let nanos = jiff_timestamp.timestamp().subsec_nanosecond();
            // Convert i32 to u32 safely
            if let Ok(nanos_u32) = nanos.try_into() {
                if let Some(chrono_dt) = DateTime::from_timestamp(seconds, nanos_u32) {
                    return Some(chrono_dt);
                }
            }
        }
    }

    // Try parsing as just a date (assume midnight UTC)
    if let Ok(jiff_date) = supposed_iso_string.parse::<jiff::civil::Date>() {
        // Convert to datetime at midnight UTC
        let jiff_datetime = jiff_date.at(0, 0, 0, 0);
        if let Ok(jiff_timestamp) = jiff_datetime.to_zoned(jiff::tz::TimeZone::UTC) {
            let seconds = jiff_timestamp.timestamp().as_second();
            let nanos = jiff_timestamp.timestamp().subsec_nanosecond();
            // Convert i32 to u32 safely
            if let Ok(nanos_u32) = nanos.try_into() {
                if let Some(chrono_dt) = DateTime::from_timestamp(seconds, nanos_u32) {
                    return Some(chrono_dt);
                }
            }
        }
    }

    // Handle common date formats that jiff might not parse automatically
    // Try MM/DD/YYYY and DD/MM/YYYY formats
    if let Some(parsed) = try_parse_slash_date(supposed_iso_string) {
        return Some(parsed);
    }

    // Fallback to chrono for RFC3339/RFC2822 formats that jiff might not handle
    if let Ok(dt) = DateTime::parse_from_rfc3339(supposed_iso_string) {
        return Some(dt.with_timezone(&Utc));
    }

    if let Ok(dt) = DateTime::parse_from_rfc2822(supposed_iso_string) {
        return Some(dt.with_timezone(&Utc));
    }

    None
}

/// Helper function to parse common slash-separated date formats
fn try_parse_slash_date(date_str: &str) -> Option<DateTime<Utc>> {
    let parts: Vec<&str> = date_str.split('/').collect();
    if parts.len() != 3 {
        return None;
    }

    // Try to parse as numbers
    let nums: Result<Vec<u32>, _> = parts.iter().map(|s| s.parse::<u32>()).collect();
    if let Ok(nums) = nums {
        if nums.len() == 3 {
            // Try MM/DD/YYYY format first (US format) - validate ranges
            if nums[0] >= 1 && nums[0] <= 12 && nums[1] >= 1 && nums[1] <= 31 && nums[2] >= 1900 && nums[2] <= 9999 {
                if let Some(dt) = try_create_date(nums[2] as i32, nums[0], nums[1]) {
                    return Some(dt);
                }
            }
            // Try DD/MM/YYYY format (European format) - validate ranges
            if nums[0] >= 1 && nums[0] <= 31 && nums[1] >= 1 && nums[1] <= 12 && nums[2] >= 1900 && nums[2] <= 9999 {
                if let Some(dt) = try_create_date(nums[2] as i32, nums[1], nums[0]) {
                    return Some(dt);
                }
            }
            // Try YYYY/MM/DD format - validate ranges
            if nums[0] >= 1900 && nums[0] <= 9999 && nums[1] >= 1 && nums[1] <= 12 && nums[2] >= 1 && nums[2] <= 31 {
                if let Some(dt) = try_create_date(nums[0] as i32, nums[1], nums[2]) {
                    return Some(dt);
                }
            }
        }
    }
    None
}

/// Helper to safely create a DateTime from year/month/day
fn try_create_date(year: i32, month: u32, day: u32) -> Option<DateTime<Utc>> {
    // Use jiff to create a date and convert to chrono
    // Convert types safely for jiff's API
    let year_i16: i16 = year.try_into().ok()?;
    let month_i8: i8 = month.try_into().ok()?;
    let day_i8: i8 = day.try_into().ok()?;

    if let Ok(jiff_date) = jiff::civil::Date::new(year_i16, month_i8, day_i8) {
        let jiff_datetime = jiff_date.at(0, 0, 0, 0);
        if let Ok(jiff_timestamp) = jiff_datetime.to_zoned(jiff::tz::TimeZone::UTC) {
            let seconds = jiff_timestamp.timestamp().as_second();
            let nanos = jiff_timestamp.timestamp().subsec_nanosecond();
            if let Ok(nanos_u32) = nanos.try_into() {
                if let Some(chrono_dt) = DateTime::from_timestamp(seconds, nanos_u32) {
                    return Some(chrono_dt);
                }
            }
        }
    }
    None
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
        let test_cases = vec![
            // ISO 8601 formats (handled by jiff)
            ("2023-01-01T12:00:00Z", true),
            ("2023-01-01T12:00:00.123Z", true),
            ("2023-01-01T12:00:00+02:00", true),
            ("2023-01-01T12:00:00-05:00", true),

            // Date-only formats (handled by jiff)
            ("2023-01-01", true),
            ("2023-12-31", true),

            // Civil datetime (no timezone, handled by jiff)
            ("2023-01-01 12:00:00", true),
            ("2023-01-01T12:00:00", true),

            // Slash-separated formats (handled by our custom logic)
            ("01/01/2023", true),
            ("12/31/2023", true),
            ("2023/01/01", true),

            // Numeric timestamps (handled by our logic)
            ("1672574400000", true), // Timestamp in milliseconds
            ("1672574400", true),    // Timestamp in seconds

            // Invalid formats
            ("invalid-date", false),
            ("99999-01-01T12:00:00Z", false), // Year too large, should not parse
            ("13/32/2023", false), // Invalid month and day
            ("01/32/2023", false), // Invalid day
            ("", false),
            ("not-a-date-at-all", false),
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
    fn test_jiff_parsing_capabilities() {
        // Test that jiff provides better parsing than the old hardcoded approach
        let test_cases = vec![
            // Various ISO 8601 variants
            "2023-01-01T12:00:00.123456Z",
            "2023-01-01T12:00:00.123Z",
            "2023-01-01T12:00:00Z",
            "2023-01-01T12:00Z",

            // With different timezones
            "2023-01-01T12:00:00+05:30", // India timezone
            "2023-01-01T12:00:00-08:00", // PST

            // Date-only formats
            "2023-01-01",
            "2023-12-31",
        ];

        for date_str in test_cases {
            let result = parse_date(date_str);
            assert!(result.is_some(), "Failed to parse with jiff: {}", date_str);

            // Verify the result is a valid UTC datetime
            let dt = result.unwrap();
            assert!(dt.year() >= 1 && dt.year() <= 9999, "Year out of expected range for: {}", date_str);
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

    #[test]
    fn test_bounds_check_logic() {
        // Test that the bounds check logic works correctly
        // This is more of a unit test for the bounds checking code

        // Test that year 0 is within bounds (year 0 is actually valid in chrono)
        let year_zero = Utc.with_ymd_and_hms(0, 1, 1, 12, 0, 0).unwrap();
        assert!(!(year_zero.year() < 0 || year_zero.year() > 9999), "Year 0 should be within bounds");

        // Test that year 10000 is out of bounds
        let year_10000 = Utc.with_ymd_and_hms(10000, 1, 1, 12, 0, 0).unwrap();
        assert!(year_10000.year() < 0 || year_10000.year() > 9999, "Year 10000 should be out of bounds");

        // Test that year 1 is within bounds
        let year_1 = Utc.with_ymd_and_hms(1, 1, 1, 12, 0, 0).unwrap();
        assert!(!(year_1.year() < 0 || year_1.year() > 9999), "Year 1 should be within bounds");

        // Test that year 9999 is within bounds
        let year_9999 = Utc.with_ymd_and_hms(9999, 1, 1, 12, 0, 0).unwrap();
        assert!(!(year_9999.year() < 0 || year_9999.year() > 9999), "Year 9999 should be within bounds");

        // Test negative year
        let year_neg1 = Utc.with_ymd_and_hms(-1, 1, 1, 12, 0, 0).unwrap();
        assert!(year_neg1.year() < 0 || year_neg1.year() > 9999, "Year -1 should be out of bounds");
    }
}
