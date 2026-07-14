use std::collections::HashMap;

use common_types::CapturedEventHeaders;
use hdrhistogram::Histogram;
use serde::Serialize;

/// Cap on tracked distinct_id cardinality; beyond it new ids are counted in
/// `distinct_id_overflow` so a pathological partition can't balloon memory.
const MAX_TRACKED_DISTINCT_IDS: usize = 50_000;

/// Cumulative size-histogram bucket boundaries (bytes).
const SIZE_BUCKETS: &[u64] = &[
    256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216,
];

#[derive(Debug, Clone, Serialize)]
pub struct KeyCount {
    pub key: String,
    pub count: u64,
    pub pct: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TokenCount {
    pub token: String,
    pub team_id: Option<i32>,
    pub count: u64,
    pub pct: f64,
    pub total_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SizeBucket {
    pub le: u64,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SizeStats {
    pub count: u64,
    pub min: u64,
    pub max: u64,
    pub mean: f64,
    pub p50: u64,
    pub p90: u64,
    pub p99: u64,
    pub total_bytes: u64,
    pub histogram: Vec<SizeBucket>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct FlagCounts {
    pub historical_migration: u64,
    pub force_disable_person_processing: u64,
    pub missing_headers: u64,
    pub missing_token: u64,
}

/// Aggregates produced by one analysis run. `team_id` on tokens is filled in
/// afterwards by the token resolver.
#[derive(Debug, Clone, Serialize)]
pub struct Aggregates {
    pub messages: u64,
    pub top_events: Vec<KeyCount>,
    pub top_distinct_ids: Vec<KeyCount>,
    pub distinct_ids_tracked: u64,
    pub distinct_id_overflow: u64,
    pub top_tokens: Vec<TokenCount>,
    pub sizes: SizeStats,
    pub flags: FlagCounts,
}

struct TokenStats {
    count: u64,
    total_bytes: u64,
}

/// Incremental, header-only aggregation over a partition's messages.
/// Pure data structure: feed it `(headers, payload_size)` pairs and call
/// [`Aggregator::finish`].
pub struct Aggregator {
    messages: u64,
    events: HashMap<String, u64>,
    tokens: HashMap<String, TokenStats>,
    distinct_ids: HashMap<String, u64>,
    distinct_id_overflow: u64,
    sizes: Histogram<u64>,
    total_bytes: u64,
    flags: FlagCounts,
}

impl Default for Aggregator {
    fn default() -> Self {
        Self::new()
    }
}

impl Aggregator {
    pub fn new() -> Self {
        let mut sizes = Histogram::new(3).expect("3 significant figures is always valid");
        sizes.auto(true);
        Self {
            messages: 0,
            events: HashMap::new(),
            tokens: HashMap::new(),
            distinct_ids: HashMap::new(),
            distinct_id_overflow: 0,
            sizes,
            total_bytes: 0,
            flags: FlagCounts::default(),
        }
    }

    pub fn record(&mut self, headers: Option<&CapturedEventHeaders>, payload_size: u64) {
        self.messages += 1;
        self.total_bytes += payload_size;
        // Values beyond the auto-resized range cannot fail to record.
        self.sizes.record(payload_size).ok();

        let Some(headers) = headers else {
            self.flags.missing_headers += 1;
            return;
        };

        if let Some(event) = &headers.event {
            *self.events.entry(event.clone()).or_default() += 1;
        }
        if let Some(distinct_id) = &headers.distinct_id {
            if self.distinct_ids.len() < MAX_TRACKED_DISTINCT_IDS
                || self.distinct_ids.contains_key(distinct_id)
            {
                *self.distinct_ids.entry(distinct_id.clone()).or_default() += 1;
            } else {
                self.distinct_id_overflow += 1;
            }
        }
        match &headers.token {
            Some(token) => {
                let stats = self.tokens.entry(token.clone()).or_insert(TokenStats {
                    count: 0,
                    total_bytes: 0,
                });
                stats.count += 1;
                stats.total_bytes += payload_size;
            }
            None => self.flags.missing_token += 1,
        }
        if headers.historical_migration == Some(true) {
            self.flags.historical_migration += 1;
        }
        if headers.force_disable_person_processing == Some(true) {
            self.flags.force_disable_person_processing += 1;
        }
    }

    pub fn finish(self, top_k: usize) -> Aggregates {
        let messages = self.messages;
        let pct = |count: u64| {
            if messages == 0 {
                0.0
            } else {
                (count as f64 / messages as f64) * 100.0
            }
        };

        let mut histogram = Vec::with_capacity(SIZE_BUCKETS.len());
        for &le in SIZE_BUCKETS {
            histogram.push(SizeBucket {
                le,
                count: self.sizes.count_between(0, le),
            });
        }

        let sizes = SizeStats {
            count: self.sizes.len(),
            min: if self.sizes.is_empty() {
                0
            } else {
                self.sizes.min()
            },
            max: self.sizes.max(),
            mean: self.sizes.mean(),
            p50: self.sizes.value_at_quantile(0.5),
            p90: self.sizes.value_at_quantile(0.9),
            p99: self.sizes.value_at_quantile(0.99),
            total_bytes: self.total_bytes,
            histogram,
        };

        let distinct_ids_tracked = self.distinct_ids.len() as u64;

        Aggregates {
            messages,
            top_events: top_counts(self.events, top_k, pct),
            top_distinct_ids: top_counts(self.distinct_ids, top_k, pct),
            distinct_ids_tracked,
            distinct_id_overflow: self.distinct_id_overflow,
            top_tokens: top_tokens(self.tokens, top_k, pct),
            sizes,
            flags: self.flags,
        }
    }
}

fn top_counts(
    counts: HashMap<String, u64>,
    top_k: usize,
    pct: impl Fn(u64) -> f64,
) -> Vec<KeyCount> {
    let mut entries: Vec<(String, u64)> = counts.into_iter().collect();
    entries.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    entries
        .into_iter()
        .take(top_k)
        .map(|(key, count)| KeyCount {
            key,
            count,
            pct: pct(count),
        })
        .collect()
}

fn top_tokens(
    tokens: HashMap<String, TokenStats>,
    top_k: usize,
    pct: impl Fn(u64) -> f64,
) -> Vec<TokenCount> {
    let mut entries: Vec<(String, TokenStats)> = tokens.into_iter().collect();
    entries.sort_by(|a, b| b.1.count.cmp(&a.1.count).then_with(|| a.0.cmp(&b.0)));
    entries
        .into_iter()
        .take(top_k)
        .map(|(token, stats)| TokenCount {
            token,
            team_id: None,
            count: stats.count,
            pct: pct(stats.count),
            total_bytes: stats.total_bytes,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn headers(token: &str, distinct_id: &str, event: &str) -> CapturedEventHeaders {
        CapturedEventHeaders {
            token: Some(token.to_string()),
            distinct_id: Some(distinct_id.to_string()),
            session_id: None,
            timestamp: None,
            event: Some(event.to_string()),
            uuid: None,
            now: None,
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        }
    }

    #[test]
    fn aggregates_top_events_tokens_and_distinct_ids() {
        let mut agg = Aggregator::new();
        for _ in 0..7 {
            agg.record(Some(&headers("token_a", "user_1", "$pageview")), 100);
        }
        for _ in 0..3 {
            agg.record(Some(&headers("token_b", "user_2", "$identify")), 1000);
        }
        let result = agg.finish(10);

        assert_eq!(result.messages, 10);
        assert_eq!(result.top_events[0].key, "$pageview");
        assert_eq!(result.top_events[0].count, 7);
        assert!((result.top_events[0].pct - 70.0).abs() < f64::EPSILON);
        assert_eq!(result.top_distinct_ids[0].key, "user_1");
        assert_eq!(result.top_tokens[0].token, "token_a");
        assert_eq!(result.top_tokens[0].total_bytes, 700);
        assert_eq!(result.top_tokens[1].token, "token_b");
        assert_eq!(result.top_tokens[1].total_bytes, 3000);
        assert_eq!(result.sizes.total_bytes, 3700);
        assert_eq!(result.sizes.count, 10);
    }

    #[test]
    fn respects_top_k() {
        let mut agg = Aggregator::new();
        for i in 0..20 {
            agg.record(Some(&headers("t", &format!("user_{i}"), "e")), 10);
        }
        let result = agg.finish(5);
        assert_eq!(result.top_distinct_ids.len(), 5);
        assert_eq!(result.distinct_ids_tracked, 20);
    }

    #[test]
    fn counts_missing_headers_and_flags() {
        let mut agg = Aggregator::new();
        agg.record(None, 50);
        let mut h = headers("t", "d", "e");
        h.historical_migration = Some(true);
        h.force_disable_person_processing = Some(true);
        agg.record(Some(&h), 60);
        let mut no_token = headers("t", "d", "e");
        no_token.token = None;
        agg.record(Some(&no_token), 70);

        let result = agg.finish(10);
        assert_eq!(result.flags.missing_headers, 1);
        assert_eq!(result.flags.historical_migration, 1);
        assert_eq!(result.flags.force_disable_person_processing, 1);
        assert_eq!(result.flags.missing_token, 1);
    }

    #[test]
    fn size_histogram_buckets_are_cumulative() {
        let mut agg = Aggregator::new();
        agg.record(None, 100);
        agg.record(None, 2000);
        agg.record(None, 2_000_000);
        let result = agg.finish(10);

        let bucket = |le: u64| {
            result
                .sizes
                .histogram
                .iter()
                .find(|b| b.le == le)
                .unwrap()
                .count
        };
        assert_eq!(bucket(256), 1);
        assert_eq!(bucket(4096), 2);
        assert_eq!(bucket(16777216), 3);
    }

    #[test]
    fn empty_aggregation_is_well_formed() {
        let result = Aggregator::new().finish(10);
        assert_eq!(result.messages, 0);
        assert_eq!(result.sizes.count, 0);
        assert!(result.top_events.is_empty());
    }
}
