//! Event-timestamp parsing for Stage 1.
//!
//! [`clickhouse_timestamp_to_millis`] accepts the same two wire shapes as
//! [`hogvm::globals`](crate::hogvm) but is **stricter**: it returns epoch millis and yields [`None`]
//! on an unparseable value rather than passing it through. The timestamp drives eviction deadlines
//! and the argMax tiebreaker, so a value we cannot place on the timeline must skip the event.

use chrono::{DateTime, NaiveDateTime};

/// Parse an event timestamp to epoch milliseconds, or [`None`] if it matches neither shape. The
/// zone-less ClickHouse form is interpreted as UTC.
pub fn clickhouse_timestamp_to_millis(raw: &str) -> Option<i64> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(raw) {
        return Some(dt.timestamp_millis());
    }
    NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f")
        .ok()
        .map(|naive| naive.and_utc().timestamp_millis())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Epoch-ms for `2026-05-26T12:34:56.789Z`, computed independently of chrono so it pins the
    /// parse rather than re-deriving it.
    const GOLDEN_MS: i64 = 1_779_798_896_789;

    #[test]
    fn clickhouse_form_parses_to_golden_millis() {
        assert_eq!(
            clickhouse_timestamp_to_millis("2026-05-26 12:34:56.789000"),
            Some(GOLDEN_MS),
        );
    }

    #[test]
    fn iso_form_agrees_with_clickhouse_form() {
        assert_eq!(
            clickhouse_timestamp_to_millis("2026-05-26T12:34:56.789Z"),
            Some(GOLDEN_MS),
        );
    }

    #[test]
    fn rfc3339_offset_is_normalized_to_utc() {
        let with_offset = clickhouse_timestamp_to_millis("2026-05-26T12:34:56.789+02:00").unwrap();
        assert_eq!(with_offset, GOLDEN_MS - 2 * 3_600_000);
    }

    #[test]
    fn sub_millisecond_digits_truncate() {
        assert_eq!(
            clickhouse_timestamp_to_millis("2026-01-01 00:00:00.000999"),
            clickhouse_timestamp_to_millis("2026-01-01 00:00:00.000000"),
        );
    }

    #[test]
    fn unparseable_values_are_none() {
        for bad in ["", "not a date", "2026-13-99 99:99:99", "1716800000"] {
            assert_eq!(
                clickhouse_timestamp_to_millis(bad),
                None,
                "expected None for {bad:?}"
            );
        }
    }
}
