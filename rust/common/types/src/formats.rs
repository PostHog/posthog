// For stuff like clickhouse formats, etc
use chrono::{DateTime, NaiveDateTime, ParseError, Utc};

pub const CH_FORMAT: &str = "%Y-%m-%d %H:%M:%S%.3f";

// Equivalent to the JS:'yyyy-MM-dd HH:mm:ss.u'
pub fn parse_datetime_assuming_utc(input: &str) -> Result<DateTime<Utc>, ParseError> {
    let mut parsed = DateTime::parse_from_rfc3339(input).map(|d| d.to_utc());

    if parsed.is_err() {
        // If we can't parse a timestamp, try parsing it as a naive datetime
        // and assuming UTC
        parsed = NaiveDateTime::parse_from_str(input, "%Y-%m-%d %H:%M:%S%.f").map(|d| d.and_utc())
    }

    parsed
}

pub fn format_ch_datetime(ts: DateTime<Utc>) -> String {
    ts.format(CH_FORMAT).to_string()
}
