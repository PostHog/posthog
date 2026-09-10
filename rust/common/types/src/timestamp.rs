use chrono::{DateTime, Datelike, Duration, Utc};
use jiff::civil::DateTime as JiffDateTime;
use regex::Regex;
use std::borrow::Cow;

const FUTURE_EVENT_HOURS_CUTOFF_MILLIS: i64 = 23 * 3600 * 1000; // 23 hours

/// Clock skew corrections are rounded to this quantum. The session replay
/// ingester rounds the same measurement to the same quantum, so both paths move
/// an event by the same amount.
pub const CLOCK_SKEW_QUANTUM_MS: i64 = 5 * 60 * 1000;

/// Round a measured skew to the nearest [`CLOCK_SKEW_QUANTUM_MS`], which is the
/// amount that is safe to subtract from an event timestamp.
///
/// A measurement of `sent_at - now` is the device clock offset minus the time
/// the request spent in transit, and a single request cannot separate the two.
/// Transit delay is therefore charged to the device clock, which pushes every
/// event of a slow request forward by the delay. Because the delay is small
/// against the quantum, rounding drops it, and the same device gets the same
/// correction on a slow request and on a fast one. A device clock that is
/// really wrong is wrong by minutes or more, so it still gets corrected.
pub fn quantize_clock_skew(measured: Duration) -> Duration {
    let ms = measured.num_milliseconds();
    // Integer division truncates toward zero, so add half a quantum in the
    // direction of the measurement to round half away from zero.
    let half = ms.signum() * (CLOCK_SKEW_QUANTUM_MS / 2);
    let quanta = ms.saturating_add(half) / CLOCK_SKEW_QUANTUM_MS;
    Duration::milliseconds(quanta.saturating_mul(CLOCK_SKEW_QUANTUM_MS))
}

/// Result of parsing an event timestamp.
pub struct ParsedTimestamp {
    /// The parsed and validated event timestamp.
    pub timestamp: DateTime<Utc>,
    /// Measured skew (sent_at - now), which mixes the device clock offset with
    /// the request transit delay. None when no measurement was possible.
    pub clock_skew: Option<Duration>,
}

/// Parse event timestamp with clock skew adjustment and validation
///
/// # Arguments
/// * `timestamp` - The event timestamp string (optional)
/// * `offset` - The offset in milliseconds (optional)
/// * `sent_at` - The client-sent timestamp (optional)
/// * `ignore_sent_at` - Whether to ignore sent_at for clock skew adjustment
/// * `now` - The current server timestamp
pub fn parse_event_timestamp(
    timestamp: Option<&str>,
    offset: Option<i64>,
    sent_at: Option<DateTime<Utc>>,
    ignore_sent_at: bool,
    now: DateTime<Utc>,
) -> ParsedTimestamp {
    // Use sent_at only if not ignored
    let effective_sent_at = if ignore_sent_at { None } else { sent_at };

    // Handle timestamp parsing and clock skew adjustment
    let mut result = handle_timestamp(timestamp, offset, effective_sent_at, now);

    // Check for future events - clamp to now
    let now_diff = result
        .timestamp
        .signed_duration_since(now)
        .num_milliseconds();
    if now_diff > FUTURE_EVENT_HOURS_CUTOFF_MILLIS {
        result.timestamp = now;
    }

    // Check if timestamp is out of bounds - fallback to epoch
    if result.timestamp.year() < 0 || result.timestamp.year() > 9999 {
        result.timestamp = DateTime::UNIX_EPOCH;
    }

    result
}

fn handle_timestamp(
    timestamp: Option<&str>,
    offset: Option<i64>,
    sent_at: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
) -> ParsedTimestamp {
    let mut parsed_ts = now;
    let mut clock_skew = None;

    if let Some(timestamp_str) = timestamp {
        let timestamp_parsed = parse_date(timestamp_str);

        if let (Some(sent_at), Some(timestamp_parsed)) = (sent_at, timestamp_parsed) {
            // Clock skew: how far the client clock is ahead of the server.
            // We subtract this from the client-provided timestamp to get
            // the event time in server clock terms. Only the quantized part is
            // safe to subtract, because the rest can be request transit delay.
            let measured = sent_at - now;
            parsed_ts = timestamp_parsed - quantize_clock_skew(measured);
            clock_skew = Some(measured);
        } else if let Some(timestamp_parsed) = timestamp_parsed {
            parsed_ts = timestamp_parsed;
        }
    }

    // Handle offset if present
    if let Some(offset_ms) = offset {
        parsed_ts = now - Duration::milliseconds(offset_ms);
    }

    ParsedTimestamp {
        timestamp: parsed_ts,
        clock_skew,
    }
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

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    #[test]
    fn positive_skew_client_clock_ahead() {
        // Client clock is 10 minutes ahead of server.
        // Skew = sent_at - now = +10m, which is two whole quanta.
        // Corrected = timestamp - skew = 11:00:00 - 10m = 10:50:00
        let now = dt("2023-01-01T12:00:00Z");
        let sent_at = Some(dt("2023-01-01T12:10:00Z"));
        let result = parse_event_timestamp(Some("2023-01-01T11:00:00Z"), None, sent_at, false, now);
        assert_eq!(result.timestamp, dt("2023-01-01T10:50:00Z"));
        assert_eq!(result.clock_skew, Some(Duration::minutes(10)));
    }

    #[test]
    fn negative_skew_client_clock_behind() {
        // Client clock is 10 minutes behind server.
        // Skew = sent_at - now = -10m
        // Corrected = timestamp - skew = 11:00:00 + 10m = 11:10:00
        let now = dt("2023-01-01T12:00:00Z");
        let sent_at = Some(dt("2023-01-01T11:50:00Z"));
        let result = parse_event_timestamp(Some("2023-01-01T11:00:00Z"), None, sent_at, false, now);
        assert_eq!(result.timestamp, dt("2023-01-01T11:10:00Z"));
        assert_eq!(result.clock_skew, Some(Duration::minutes(-10)));
    }

    #[test]
    fn transit_delay_does_not_move_the_timestamp() {
        // A device with a good clock on a request that took 40s to arrive:
        // the measurement looks like a device 40s behind, and correcting it
        // would store the event 40s late.
        let now = dt("2023-01-01T12:00:40Z");
        let sent_at = Some(dt("2023-01-01T12:00:00Z"));
        let result = parse_event_timestamp(Some("2023-01-01T11:00:00Z"), None, sent_at, false, now);
        assert_eq!(result.timestamp, dt("2023-01-01T11:00:00Z"));
        assert_eq!(result.clock_skew, Some(Duration::seconds(-40)));
    }

    #[test]
    fn quantize_rounds_to_the_nearest_quantum() {
        let quantum = Duration::milliseconds(CLOCK_SKEW_QUANTUM_MS);
        let cases = [
            (Duration::zero(), Duration::zero()),
            (Duration::seconds(149), Duration::zero()),
            (Duration::seconds(-149), Duration::zero()),
            (Duration::seconds(151), quantum),
            (Duration::seconds(-151), -quantum),
            (Duration::seconds(150), quantum),
            (Duration::seconds(-150), -quantum),
            (Duration::hours(2), Duration::hours(2)),
            (Duration::hours(-2), Duration::hours(-2)),
        ];
        for (measured, expected) in cases {
            assert_eq!(quantize_clock_skew(measured), expected, "{measured}");
        }
    }

    #[test]
    fn zero_skew_clocks_aligned() {
        let now = dt("2023-01-01T12:00:00Z");
        let sent_at = Some(dt("2023-01-01T12:00:00Z"));
        let result = parse_event_timestamp(Some("2023-01-01T11:00:00Z"), None, sent_at, false, now);
        assert_eq!(result.timestamp, dt("2023-01-01T11:00:00Z"));
        assert_eq!(result.clock_skew, Some(Duration::zero()));
    }

    #[test]
    fn no_sent_at_no_correction() {
        let now = dt("2023-01-01T12:00:00Z");
        let result = parse_event_timestamp(Some("2023-01-01T11:00:00Z"), None, None, false, now);
        assert_eq!(result.timestamp, dt("2023-01-01T11:00:00Z"));
        assert!(result.clock_skew.is_none());
    }

    #[test]
    fn ignore_sent_at_skips_correction() {
        let now = dt("2023-01-01T12:00:00Z");
        let sent_at = Some(dt("2023-01-01T12:00:10Z"));
        let result = parse_event_timestamp(Some("2023-01-01T11:00:00Z"), None, sent_at, true, now);
        assert_eq!(result.timestamp, dt("2023-01-01T11:00:00Z"));
        assert!(result.clock_skew.is_none());
    }

    #[test]
    fn no_timestamp_falls_back_to_now() {
        let now = dt("2023-01-01T12:00:00Z");
        let result = parse_event_timestamp(None, None, None, false, now);
        assert_eq!(result.timestamp, now);
        assert!(result.clock_skew.is_none());
    }

    #[test]
    fn no_timestamp_with_sent_at_falls_back_to_now() {
        let now = dt("2023-01-01T12:00:00Z");
        let sent_at = Some(dt("2023-01-01T12:00:05Z"));
        let result = parse_event_timestamp(None, None, sent_at, false, now);
        assert_eq!(result.timestamp, now);
        assert!(result.clock_skew.is_none());
    }
}
