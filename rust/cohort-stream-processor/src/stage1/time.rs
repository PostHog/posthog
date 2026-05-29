//! Event-timestamp parsing for Stage 1 (TDD §4.1.1).
//!
//! [`clickhouse_timestamp_to_millis`] mirrors the two wire formats [`hogvm::globals::
//! normalize_timestamp`](crate::hogvm) accepts — already-valid RFC 3339, and the ClickHouse
//! `"%Y-%m-%d %H:%M:%S%.f"` form parsed as UTC — but it is **stricter**: it returns epoch
//! milliseconds (`i64`) and yields [`None`] on an unparseable value rather than passing the raw
//! string through. The timestamp is load-bearing here (it drives eviction deadlines and the
//! person-property argMax tiebreaker), so a value we cannot place on the timeline must skip the
//! event, not silently degrade.

use chrono::{DateTime, NaiveDateTime};

/// Parse an event timestamp to epoch milliseconds, or [`None`] if it matches neither supported
/// shape.
///
/// An RFC 3339 string carries its own offset and is converted to UTC millis; the ClickHouse form
/// has no zone and is interpreted as UTC (matching `convertClickhouseRawEventToFilterGlobals`).
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

    /// `"2026-05-26 12:34:56.789000"` is `2026-05-26T12:34:56.789Z`; the golden epoch-ms below is
    /// computed independently (days-since-epoch × 86_400_000 + intra-day millis) so it pins the
    /// parse rather than re-deriving it from chrono.
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
        // The two wire shapes for the same instant must produce identical millis.
        assert_eq!(
            clickhouse_timestamp_to_millis("2026-05-26T12:34:56.789Z"),
            Some(GOLDEN_MS),
        );
    }

    #[test]
    fn rfc3339_offset_is_normalized_to_utc() {
        // 12:34:56.789+02:00 is 10:34:56.789Z — two hours earlier.
        let with_offset = clickhouse_timestamp_to_millis("2026-05-26T12:34:56.789+02:00").unwrap();
        assert_eq!(with_offset, GOLDEN_MS - 2 * 3_600_000);
    }

    #[test]
    fn sub_millisecond_digits_truncate() {
        // Microsecond precision in the ClickHouse form truncates to whole milliseconds.
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
