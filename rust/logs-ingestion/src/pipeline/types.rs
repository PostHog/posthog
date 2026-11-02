//! Port of `logs-ingestion-types.ts` and `types.ts`.

use std::collections::BTreeMap;
use std::sync::Arc;

use ingestion_framework::KafkaMessage;

use crate::internal_logs::InternalLogs;
use crate::property_filter::coerce::{is_js_whitespace, js_parse_int};
use crate::rate_limiter::RateLimitedMessage;

/// Must match `DEFAULT_LOGS_RETENTION_DAYS` in `posthog/models/team/logs_retention.py`.
pub const DEFAULT_LOGS_RETENTION_DAYS: f64 = 14.0;
pub const DEFAULT_TRACES_RETENTION_DAYS: f64 = 14.0;
/// A producer can stamp internal rows with less retention than the team default.
pub const INTERNAL_LOGS_MIN_RETENTION_DAYS: f64 = 1.0;

#[derive(Debug, Clone)]
pub struct LogsIngestionMessage {
    pub token: String,
    pub message: Arc<KafkaMessage>,
    pub team_id: i64,
    pub bytes_uncompressed: f64,
    pub bytes_uncompressed_records: f64,
    pub bytes_compressed: f64,
    pub record_count: f64,
    pub min_timestamp_micros: Option<f64>,
    pub backfill_requested: bool,
    pub internal_logs: Option<InternalLogs>,
}

impl RateLimitedMessage for LogsIngestionMessage {
    fn team_id(&self) -> i64 {
        self.team_id
    }
    fn bytes_uncompressed(&self) -> f64 {
        self.bytes_uncompressed
    }
    fn created_at_header(&self) -> Option<&[u8]> {
        self.message
            .headers
            .iter()
            .find(|(k, _)| k == "created_at")
            .and_then(|(_, v)| v.as_deref())
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct UsageStats {
    pub bytes_received: f64,
    pub records_received: f64,
    pub bytes_allowed: f64,
    pub records_allowed: f64,
    pub bytes_allowed_records: f64,
    pub bytes_dropped: f64,
    pub records_dropped: f64,
    pub pii_replacements: f64,
    pub retention_days: f64,
}

pub const DEFAULT_USAGE_STATS: UsageStats = UsageStats {
    bytes_received: 0.0,
    records_received: 0.0,
    bytes_allowed: 0.0,
    records_allowed: 0.0,
    bytes_allowed_records: 0.0,
    bytes_dropped: 0.0,
    records_dropped: 0.0,
    pii_replacements: 0.0,
    retention_days: DEFAULT_LOGS_RETENTION_DAYS,
};

/// `UsageStatsByTeam`: a `Map`, so iteration follows insertion order.
#[derive(Debug, Clone, Default)]
pub struct UsageStatsByTeam(pub Vec<(i64, UsageStats)>);

impl UsageStatsByTeam {
    pub fn get_mut(&mut self, team_id: i64) -> Option<&mut UsageStats> {
        self.0
            .iter_mut()
            .find(|(t, _)| *t == team_id)
            .map(|(_, s)| s)
    }

    pub fn row(&mut self, team_id: i64) -> &mut UsageStats {
        if let Some(i) = self.0.iter().position(|(t, _)| *t == team_id) {
            return &mut self.0[i].1;
        }
        self.0.push((team_id, DEFAULT_USAGE_STATS));
        &mut self.0.last_mut().unwrap().1
    }
}

pub fn retention_bytes_metric_name(retention_days: f64) -> Option<String> {
    [14.0, 30.0, 90.0]
        .contains(&retention_days)
        .then(|| format!("bytes_ingested_retention_{}d", retention_days as i64))
}

pub fn describe_batch_position(messages: &[KafkaMessage]) -> BTreeMap<String, String> {
    let mut spans: BTreeMap<i32, (i64, i64)> = BTreeMap::new();
    for m in messages {
        let span = spans.entry(m.partition).or_insert((m.offset, m.offset));
        span.0 = span.0.min(m.offset);
        span.1 = span.1.max(m.offset);
    }
    spans
        .into_iter()
        .map(|(p, (min, max))| {
            let span = if min == max {
                min.to_string()
            } else {
                format!("{min}-{max}")
            };
            (p.to_string(), span)
        })
        .collect()
}

/// `parseSizeHeader`: `parseInt(raw ?? '0', 10)`, rejecting NaN and negatives.
pub fn parse_size_header(raw: Option<&str>) -> Option<f64> {
    let parsed = js_parse_int(raw.unwrap_or("0"), Some(10));
    (parsed.is_finite() && parsed >= 0.0).then_some(parsed)
}

/// `parseMinTimestampHeader`: `Number(raw)` when it is a safe integer.
pub fn parse_min_timestamp_header(raw: Option<&str>) -> Option<f64> {
    let raw = raw?;
    if raw.trim_matches(is_js_whitespace).is_empty() {
        return None;
    }
    let n = js_string_to_number(raw);
    (n.fract() == 0.0 && n.abs() <= 9_007_199_254_740_991.0).then_some(n)
}

/// ECMAScript `StringToNumber`.
pub fn js_string_to_number(raw: &str) -> f64 {
    let s = raw.trim_matches(is_js_whitespace);
    if s.is_empty() {
        return 0.0;
    }
    for (prefix, radix) in [
        ("0x", 16),
        ("0X", 16),
        ("0o", 8),
        ("0O", 8),
        ("0b", 2),
        ("0B", 2),
    ] {
        if let Some(digits) = s.strip_prefix(prefix) {
            if digits.is_empty() || !digits.chars().all(|c| c.is_digit(radix)) {
                return f64::NAN;
            }
            return digits.chars().fold(0.0, |acc, c| {
                acc * radix as f64 + c.to_digit(radix).unwrap() as f64
            });
        }
    }
    let unsigned = s.strip_prefix(['+', '-']).unwrap_or(s);
    if unsigned == "Infinity" {
        return if s.starts_with('-') {
            f64::NEG_INFINITY
        } else {
            f64::INFINITY
        };
    }
    let valid = {
        let b = unsigned.as_bytes();
        let mut i = 0;
        let int_start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        let mut digits = i - int_start;
        if i < b.len() && b[i] == b'.' {
            i += 1;
            let frac_start = i;
            while i < b.len() && b[i].is_ascii_digit() {
                i += 1;
            }
            digits += i - frac_start;
        }
        if digits > 0 && i < b.len() && (b[i] == b'e' || b[i] == b'E') {
            i += 1;
            if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
                i += 1;
            }
            let exp_start = i;
            while i < b.len() && b[i].is_ascii_digit() {
                i += 1;
            }
            if i == exp_start {
                return f64::NAN;
            }
        }
        digits > 0 && i == b.len()
    };
    if !valid {
        return f64::NAN;
    }
    s.parse::<f64>().unwrap_or(f64::NAN)
}

pub fn billing_byte_reduction_for_drops(
    header_bytes: f64,
    bytes_dropped: f64,
    bytes_total: f64,
) -> f64 {
    if header_bytes <= 0.0 || bytes_dropped <= 0.0 || bytes_total <= 0.0 {
        return 0.0;
    }
    let fraction = (bytes_dropped / bytes_total).min(1.0);
    crate::property_filter::coerce::js_math_round(header_bytes * fraction)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn size_and_timestamp_headers_parse_like_node() {
        assert_eq!(parse_size_header(Some("12abc")), Some(12.0));
        assert_eq!(parse_size_header(Some("1e3")), Some(1.0));
        assert_eq!(parse_size_header(Some("  7")), Some(7.0));
        assert_eq!(parse_size_header(Some("-5")), None);
        assert_eq!(parse_size_header(Some("abc")), None);
        assert_eq!(parse_size_header(None), Some(0.0));
        assert_eq!(parse_min_timestamp_header(Some("1.5")), None);
        assert_eq!(parse_min_timestamp_header(Some("garbage")), None);
        assert_eq!(parse_min_timestamp_header(Some(" 12 ")), Some(12.0));
        assert_eq!(parse_min_timestamp_header(Some("0x10")), Some(16.0));
        assert_eq!(parse_min_timestamp_header(Some("1e3")), Some(1000.0));
        assert_eq!(parse_min_timestamp_header(Some("")), None);
    }
}
