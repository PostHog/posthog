use chrono::{DateTime, Datelike, Duration, Utc};
use jiff::civil::DateTime as JiffDateTime;
use regex::Regex;
use std::borrow::Cow;

const FUTURE_EVENT_HOURS_CUTOFF_MILLIS: i64 = 23 * 3600 * 1000; // 23 hours

/// Parse event timestamp with clock skew adjustment and validation
///
/// # Arguments
/// * `timestamp` - The event timestamp string (optional)
/// * `offset` - The offset in milliseconds (optional)
/// * `sent_at` - The client-sent timestamp (optional)
/// * `ignore_sent_at` - Whether to ignore sent_at for clock skew adjustment
/// * `clock_skew` - The clock skew in milliseconds (optional, added to computed timestamp)
/// * `now` - The current server timestamp
///
/// # Returns
/// * `DateTime<Utc>` - The parsed and validated timestamp
pub fn parse_event_timestamp(
    timestamp: Option<&str>,
    offset: Option<i64>,
    sent_at: Option<DateTime<Utc>>,
    ignore_sent_at: bool,
    clock_skew: Option<i64>,
    now: DateTime<Utc>,
) -> DateTime<Utc> {
    // Use sent_at only if not ignored
    let effective_sent_at = if ignore_sent_at { None } else { sent_at };

    // Handle timestamp parsing and clock skew adjustment
    let mut parsed_ts = handle_timestamp(timestamp, offset, effective_sent_at, now);

    // Apply clock skew if present
    if let Some(skew_ms) = clock_skew {
        parsed_ts = parsed_ts + Duration::milliseconds(skew_ms);
    }

    // Check for future events - clamp to now
    let now_diff = parsed_ts.signed_duration_since(now).num_milliseconds();
    if now_diff > FUTURE_EVENT_HOURS_CUTOFF_MILLIS {
        parsed_ts = now;
    }

    // Check if timestamp is out of bounds - fallback to epoch
    if parsed_ts.year() < 0 || parsed_ts.year() > 9999 {
        parsed_ts = DateTime::UNIX_EPOCH;
    }

    parsed_ts
}

fn handle_timestamp(
    timestamp: Option<&str>,
    offset: Option<i64>,
    sent_at: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
) -> DateTime<Utc> {
    let mut parsed_ts = now;

    if let Some(timestamp_str) = timestamp {
        let timestamp_parsed = parse_date(timestamp_str);

        if let (Some(sent_at), Some(timestamp_parsed)) = (sent_at, timestamp_parsed) {
            // Handle clock skew between client and server
            // skew = sent_at - now
            // x = now + (timestamp - sent_at)
            let duration = timestamp_parsed.signed_duration_since(sent_at);
            parsed_ts = now + duration;
        } else if let Some(timestamp_parsed) = timestamp_parsed {
            parsed_ts = timestamp_parsed;
        }
    }

    // Handle offset if present
    if let Some(offset_ms) = offset {
        parsed_ts = now - Duration::milliseconds(offset_ms);
    }

    parsed_ts
}

/// Parse a date string using a streamlined approach
///
/// This function tries parsing in order of preference:
/// 1. chrono RFC3339 parser (handles standard ISO 8601 with proper timezone conversion)
/// 2. dateparser (handles 95%+ of formats): ISO 8601, slash-separated, RFC2822, numeric timestamps
/// 3. jiff (minimal fallback): civil datetime with T but no timezone (e.g., "2023-01-01T12:00:00")
pub fn parse_date(supposed_iso_string: &str) -> Option<DateTime<Utc>> {
    // First normalize any non-standard timezone formats (e.g., +03 -> +03:00)
    let normalized_input = normalize_timezone_format(supposed_iso_string);

    // Try chrono's RFC3339 parser first for proper timezone handling
    if let Ok(dt) = DateTime::parse_from_rfc3339(&normalized_input) {
        return Some(dt.with_timezone(&Utc));
    }

    // Try dateparser for other formats - but note it may not handle timezones correctly
    // - Date-only: 2023-01-01
    // - Civil datetime with space: 2023-01-01 12:00:00
    // - Slash-separated: 01/01/2023, 2023/01/01
    // - RFC2822: Tue, 1 Jul 2003 10:52:37 +0200
    // - Numeric timestamps: 1672574400000, 1672574400
    if let Ok(dt) = dateparser::parse(&normalized_input) {
        return Some(dt);
    }

    // Minimal jiff fallback for the one format dateparser can't handle:
    // Civil datetime with T but no timezone (e.g., "2023-01-01T12:00:00")
    if let Ok(jiff_civil) = normalized_input.parse::<JiffDateTime>() {
        return convert_jiff_to_chrono(jiff_civil.to_zoned(jiff::tz::TimeZone::UTC).ok()?);
    }

    None
}

/// Normalize non-standard timezone formats to standard RFC3339 format
/// Returns a Cow that borrows the input if no normalization is needed, or owns a new string if modified
/// Uses regex to precisely match ISO datetime strings with non-standard timezone format
/// Examples:
/// - "2025-09-17T14:05:04.805+03" -> "2025-09-17T14:05:04.805+03:00" (owned)
/// - "2025-09-17T14:05:04.805-05" -> "2025-09-17T14:05:04.805-05:00" (owned)
/// - "2025-09-17T14:05:04.805Z" -> "2025-09-17T14:05:04.805Z" (borrowed)
/// - "2023-01-01" -> "2023-01-01" (borrowed, no match)
fn normalize_timezone_format(input: &str) -> Cow<'_, str> {
    // Quick optimization: check last 3 chars first
    if input.len() < 3 {
        return Cow::Borrowed(input);
    }

    let last_3_chars = &input[input.len() - 3..];
    if !(last_3_chars.starts_with('+') || last_3_chars.starts_with('-'))
        || !last_3_chars[1..].chars().all(|c| c.is_ascii_digit())
    {
        return Cow::Borrowed(input);
    }

    // Use regex to confirm this is an ISO datetime with non-standard timezone format
    // Pattern: YYYY-MM-DDTHH:MM:SS[.fff][+/-]HH
    static TIMEZONE_REGEX: std::sync::LazyLock<Regex> = std::sync::LazyLock::new(|| {
        Regex::new(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?[+-]\d{2}$").unwrap()
    });

    if TIMEZONE_REGEX.is_match(input) {
        // Found ISO datetime with +XX or -XX timezone, convert to +XX:00 or -XX:00
        Cow::Owned(format!("{input}:00"))
    } else {
        // Not the format we're looking for, return unchanged
        Cow::Borrowed(input)
    }
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

    #[test]
    fn test_parse_event_timestamp_with_clock_skew_positive() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_str = "2023-01-01T10:00:00Z";
        let clock_skew = Some(5000); // 5 seconds in milliseconds

        let result = parse_event_timestamp(
            Some(timestamp_str),
            None,
            None,
            false,
            clock_skew,
            now,
        );

        // Expected: timestamp (10:00:00) + clock_skew (5 seconds) = 10:00:05
        let expected = DateTime::parse_from_rfc3339("2023-01-01T10:00:05Z")
            .unwrap()
            .with_timezone(&Utc);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_with_clock_skew_negative() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_str = "2023-01-01T10:00:00Z";
        let clock_skew = Some(-3000); // -3 seconds in milliseconds

        let result = parse_event_timestamp(
            Some(timestamp_str),
            None,
            None,
            false,
            clock_skew,
            now,
        );

        // Expected: timestamp (10:00:00) + clock_skew (-3 seconds) = 09:59:57
        let expected = DateTime::parse_from_rfc3339("2023-01-01T09:59:57Z")
            .unwrap()
            .with_timezone(&Utc);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_without_clock_skew() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_str = "2023-01-01T10:00:00Z";

        let result = parse_event_timestamp(
            Some(timestamp_str),
            None,
            None,
            false,
            None, // No clock_skew
            now,
        );

        let expected = DateTime::parse_from_rfc3339("2023-01-01T10:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_with_sent_at_and_clock_skew() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_str = "2023-01-01T10:00:00Z";
        let sent_at = DateTime::parse_from_rfc3339("2023-01-01T11:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let clock_skew = Some(2000); // 2 seconds in milliseconds

        let result = parse_event_timestamp(
            Some(timestamp_str),
            None,
            Some(sent_at),
            false,
            clock_skew,
            now,
        );

        // First apply sent_at adjustment: now + (timestamp - sent_at) = 12:00:00 + (10:00:00 - 11:00:00) = 11:00:00
        // Then apply clock_skew: 11:00:00 + 2 seconds = 11:00:02
        let expected = DateTime::parse_from_rfc3339("2023-01-01T11:00:02Z")
            .unwrap()
            .with_timezone(&Utc);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_clock_skew_with_no_timestamp() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let clock_skew = Some(5000); // 5 seconds

        let result = parse_event_timestamp(
            None, // No timestamp
            None,
            None,
            false,
            clock_skew,
            now,
        );

        // Expected: now (12:00:00) + clock_skew (5 seconds) = 12:00:05
        let expected = DateTime::parse_from_rfc3339("2023-01-01T12:00:05Z")
            .unwrap()
            .with_timezone(&Utc);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_clock_skew_doesnt_affect_offset() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let offset = Some(3600000); // 1 hour in milliseconds
        let clock_skew = Some(5000); // 5 seconds

        let result = parse_event_timestamp(
            None,
            offset,
            None,
            false,
            clock_skew,
            now,
        );

        // Offset is applied: now - offset = 12:00:00 - 1 hour = 11:00:00
        // Then clock_skew is applied: 11:00:00 + 5 seconds = 11:00:05
        let expected = DateTime::parse_from_rfc3339("2023-01-01T11:00:05Z")
            .unwrap()
            .with_timezone(&Utc);

        assert_eq!(result, expected);
    }

    #[test]
    fn test_parse_event_timestamp_clock_skew_clamped_to_now() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_str = "2023-01-01T10:00:00Z";
        // Very large positive clock skew that would push timestamp > 23 hours into future
        let clock_skew = Some(100 * 3600 * 1000); // 100 hours in milliseconds

        let result = parse_event_timestamp(
            Some(timestamp_str),
            None,
            None,
            false,
            clock_skew,
            now,
        );

        // Should be clamped to now since it exceeds the 23-hour cutoff
        assert_eq!(result, now);
    }
}
