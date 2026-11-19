//! Finds label keys that make a metric explode into many series, and drops
//! them before the series fingerprint is final. The README section "High
//! cardinality label drop" describes the detection stages and the rules.

use std::collections::hash_map::RandomState;
use std::collections::{HashMap, HashSet};
use std::hash::{BuildHasher, Hasher};
use std::str::FromStr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

use capture_logs::log_record::ORIGINAL_TIMESTAMP_ATTRIBUTE;
use capture_logs::metric_record::{compute_series_fingerprint, KafkaMetricRow};
use capture_logs::unknown_tokens::UnknownTokens;
use chrono::Utc;
use common_redis::{Client, CustomRedisError, PipelineCommand};
use dashmap::DashMap;
use metrics::{counter, gauge};
use prometheus_rw_proto::prometheus::v1::{metric_metadata::MetricType, MetricMetadata};
use serde::{Deserialize, Serialize};
use siphasher::sip::SipHasher13;
use tokio::sync::mpsc;
use tracing::{debug, warn};

use crate::histogram_assembly::fingerprint_with_bounds;
use crate::series_label_gate::Clock;

const REDIS_KEY_PREFIX: &str = "capture-logs:metric-label-drop-rules";
const REDIS_BUCKET_SECS: i64 = 3600;
const PULL_PAGE_SIZE: usize = 10_000;
const WRITER_CHANNEL_CAPACITY: usize = 10_000;
const PRUNE_INTERVAL: Duration = Duration::from_secs(300);
const MEASURE_CHUNK_ROWS: usize = 1024;

pub const DROPPED_LABELS_ATTRIBUTE: &str = "posthog.dropped_labels";
const HISTOGRAM_SUFFIXES: [&str; 3] = ["_bucket", "_count", "_sum"];
const SERVICE_NAME_RESOURCE: &str = "service.name";
const MAX_PENDING_PUSHES: usize = 10_000;
const MAX_RULES: usize = 200_000;
const MAX_RULES_PER_TOKEN: usize = 2_000;
const MAX_NAME_CHARS: usize = 100;
const HISTOGRAM_TYPE: &str = "histogram";
const SUM_TYPE: &str = "sum";
const GAUGE_TYPE: &str = "gauge";
const DELTA: &str = "delta";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Off,
    Shadow,
    Enforce,
}

impl FromStr for Mode {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().as_str() {
            "off" => Ok(Mode::Off),
            "shadow" => Ok(Mode::Shadow),
            "enforce" => Ok(Mode::Enforce),
            other => Err(format!("unknown label cardinality mode {other:?}")),
        }
    }
}

impl Mode {
    fn as_str(self) -> &'static str {
        match self {
            Mode::Off => "off",
            Mode::Shadow => "shadow",
            Mode::Enforce => "enforce",
        }
    }
}

pub struct Source<'a> {
    remote_write: bool,
    declared: HashMap<&'a str, MetricType>,
}

impl<'a> Source<'a> {
    pub fn otlp() -> Self {
        Self {
            remote_write: false,
            declared: HashMap::new(),
        }
    }

    pub fn remote_write(metadata: &'a [MetricMetadata]) -> Self {
        let declared = metadata
            .iter()
            .filter_map(|m| {
                MetricType::try_from(m.r#type)
                    .ok()
                    .map(|t| (m.metric_family_name.as_str(), t))
            })
            .collect();
        Self {
            remote_write: true,
            declared,
        }
    }

    fn is_composite(&self, base: &str) -> bool {
        matches!(
            self.declared.get(base),
            None | Some(MetricType::Histogram) | Some(MetricType::Summary)
        )
    }

    fn family<'r>(&self, metric_name: &'r str) -> &'r str {
        if !self.remote_write || self.declared.contains_key(metric_name) {
            return metric_name;
        }
        for suffix in HISTOGRAM_SUFFIXES {
            if let Some(base) = metric_name.strip_suffix(suffix) {
                if !base.is_empty() && self.is_composite(base) {
                    return base;
                }
            }
        }
        metric_name
    }

    fn is_component_label(&self, row: &KafkaMetricRow, key: &str) -> bool {
        if !self.remote_write {
            return false;
        }
        match key {
            "le" => {
                row.metric_name.ends_with("_bucket")
                    && self.family(&row.metric_name) != row.metric_name
            }
            "quantile" => {
                self.declared.get(self.family(&row.metric_name)) == Some(&MetricType::Summary)
            }
            _ => false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Scope {
    Attribute,
    Resource,
}

#[derive(Debug, Clone)]
pub struct Settings {
    pub mode: Mode,
    pub window: Duration,
    pub value_limit: u64,
    pub min_share: f64,
    pub min_new_share: f64,
    pub candidate_min_new_series: u32,
    pub max_candidates: usize,
    pub max_candidates_per_token: usize,
    pub max_keys_per_candidate: usize,
    pub max_tracked_metrics: usize,
    pub max_tracked_metrics_per_token: usize,
    pub rule_ttl: Duration,
    pub protected_keys: HashSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Rule {
    pub metric_key: u64,
    pub token_hash: u64,
    pub scope: Scope,
    pub key_hash: u64,
    #[serde(skip)]
    pub expires_at: i64,
}

#[derive(Clone)]
struct Sketch {
    registers: [u8; SKETCH_REGISTERS],
}

const SKETCH_INDEX_BITS: u32 = 8;
const SKETCH_REGISTERS: usize = 1 << SKETCH_INDEX_BITS;

impl Sketch {
    fn new() -> Self {
        Self {
            registers: [0; SKETCH_REGISTERS],
        }
    }

    fn insert(&mut self, hash: u64) {
        let index = (hash >> (64 - SKETCH_INDEX_BITS)) as usize;
        let rest = hash << SKETCH_INDEX_BITS;
        let rank = (rest.leading_zeros().min(64 - SKETCH_INDEX_BITS) + 1) as u8;
        if rank > self.registers[index] {
            self.registers[index] = rank;
        }
    }

    fn estimate(&self) -> u64 {
        let m = SKETCH_REGISTERS as f64;
        let mut sum = 0.0;
        let mut zeros = 0u32;
        for &register in &self.registers {
            sum += f64::from_bits((1023 - register as u64) << 52);
            if register == 0 {
                zeros += 1;
            }
        }
        let alpha = 0.7213 / (1.0 + 1.079 / m);
        let raw = alpha * m * m / sum;
        if raw <= 2.5 * m && zeros > 0 {
            return (m * (m / zeros as f64).ln()).round() as u64;
        }
        raw.round() as u64
    }
}

struct KeySketch {
    sketch: Sketch,
    /// Distinct series of the rows that carry this key, with and without the key. Both cover
    /// the same rows, so a series without the key never counts as saved.
    with: Sketch,
    others: Sketch,
    name: Box<str>,
    rows: u64,
    new_rows: u64,
}

struct Candidate {
    token: Arc<str>,
    token_hash: u64,
    family: Box<str>,
    window: i64,
    qualified_window: i64,
    series: Sketch,
    keys: HashMap<(Scope, u64), KeySketch>,
}

struct NewSeriesCount {
    window: i64,
    count: u32,
    token_hash: u64,
}

struct RowHashes<'a> {
    series: u64,
    new_series: bool,
    values: Vec<(Scope, u64, u64, u64, &'a str)>,
}

pub struct LabelCardinality {
    settings: Settings,
    clock: Clock,
    new_series: DashMap<u64, NewSeriesCount>,
    tracked_count: AtomicUsize,
    tracked_per_token: DashMap<u64, usize>,
    candidates: DashMap<u64, Mutex<Candidate>>,
    candidate_count: AtomicUsize,
    candidates_per_token: DashMap<u64, usize>,
    rules: DashMap<u64, Vec<Rule>>,
    rule_count: AtomicUsize,
    rules_per_token: DashMap<u64, usize>,
    protected: HashSet<(Scope, u64)>,
    skipped: DashMap<u64, i64>,
    // A fixed key lets a sender pick values that fill few registers and hide from the sketch.
    value_keys: (u64, u64),
    unknown_tokens: UnknownTokens,
    tx: Option<mpsc::Sender<Rule>>,
}

impl LabelCardinality {
    pub fn new(
        settings: Settings,
        unknown_tokens: UnknownTokens,
    ) -> (Arc<Self>, mpsc::Receiver<Rule>) {
        let (tx, rx) = mpsc::channel(WRITER_CHANNEL_CAPACITY);
        let detector = Self {
            unknown_tokens,
            ..Self::build(settings, Some(tx), Arc::new(unix_now))
        };
        (Arc::new(detector), rx)
    }

    pub fn local_only(settings: Settings, unknown_tokens: UnknownTokens) -> Arc<Self> {
        Arc::new(Self {
            unknown_tokens,
            ..Self::build(settings, None, Arc::new(unix_now))
        })
    }

    fn build(settings: Settings, tx: Option<mpsc::Sender<Rule>>, clock: Clock) -> Self {
        let mut protected: HashSet<(Scope, u64)> = settings
            .protected_keys
            .iter()
            .flat_map(|key| {
                let hash = key_hash(key);
                [(Scope::Attribute, hash), (Scope::Resource, hash)]
            })
            .collect();
        for key in [ORIGINAL_TIMESTAMP_ATTRIBUTE, DROPPED_LABELS_ATTRIBUTE] {
            protected.insert((Scope::Attribute, key_hash(key)));
            protected.insert((Scope::Resource, key_hash(key)));
        }
        protected.insert((Scope::Resource, key_hash(SERVICE_NAME_RESOURCE)));
        Self {
            protected,
            skipped: DashMap::new(),
            value_keys: random_keys(),
            unknown_tokens: UnknownTokens::disabled(),
            settings,
            clock,
            new_series: DashMap::new(),
            tracked_count: AtomicUsize::new(0),
            tracked_per_token: DashMap::new(),
            candidates: DashMap::new(),
            candidate_count: AtomicUsize::new(0),
            candidates_per_token: DashMap::new(),
            rules: DashMap::new(),
            rule_count: AtomicUsize::new(0),
            rules_per_token: DashMap::new(),
            tx,
        }
    }

    /// Marks the current window of `token` as incomplete, so it is not judged.
    pub fn skip(&self, token: &str) {
        let token_hash = token_key(token);
        // Only a token with candidates has a window to skip, which bounds this map.
        if self.settings.mode == Mode::Off || !self.candidates_per_token.contains_key(&token_hash) {
            return;
        }
        let window = self.window_index((self.clock)());
        self.skipped.insert(token_hash, window);
    }

    fn window_index(&self, now: i64) -> i64 {
        now.div_euclid(self.settings.window.as_secs().max(1) as i64)
    }

    pub fn note_new_series(
        &self,
        token: &str,
        rows: &[KafkaMetricRow],
        new_rows: &[usize],
        source: &Source,
    ) {
        // Capture cannot resolve a token to a team, so a token the consumer found to have
        // no team must not take the tracking slots of real projects.
        if self.settings.mode == Mode::Off
            || new_rows.is_empty()
            || self.unknown_tokens.is_unknown(token)
        {
            return;
        }
        let now = (self.clock)();
        let window = self.window_index(now);
        let mut per_family: HashMap<&str, u32> = HashMap::new();
        for &index in new_rows {
            if let Some(row) = rows.get(index) {
                *per_family
                    .entry(source.family(&row.metric_name))
                    .or_default() += 1;
            }
        }
        let token_hash = token_key(token);
        let token_label: Arc<str> = Arc::from(token);
        let mut admitted: HashSet<u64> = HashSet::new();
        let mut tracking_full = 0u64;
        for (family_name, added) in per_family {
            let metric_key = metric_key(token, family_name);
            let qualified = {
                let mut entry = match self.new_series.entry(metric_key) {
                    dashmap::Entry::Occupied(entry) => entry.into_ref(),
                    dashmap::Entry::Vacant(slot) => {
                        if !self.reserve_tracking(token_hash) {
                            tracking_full += 1;
                            continue;
                        }
                        slot.insert(NewSeriesCount {
                            window,
                            count: 0,
                            token_hash,
                        })
                    }
                };
                if entry.window != window {
                    entry.window = window;
                    entry.count = 0;
                }
                let before = entry.count;
                entry.count = entry.count.saturating_add(added);
                before < self.settings.candidate_min_new_series
                    && entry.count >= self.settings.candidate_min_new_series
            };
            if !qualified {
                continue;
            }
            if let Some(slot) = self.candidates.get(&metric_key) {
                if let Ok(mut candidate) = slot.lock() {
                    candidate.qualified_window = window;
                }
                continue;
            }
            if self.add_candidate(metric_key, &token_label, token_hash, family_name, window) {
                admitted.insert(metric_key);
            }
        }
        if tracking_full > 0 {
            counter!("capture_metrics_label_cardinality_tracking_full").increment(tracking_full);
        }
        if admitted.is_empty() {
            return;
        }
        let mut groups: HashMap<u64, Vec<usize>> = HashMap::new();
        for (index, row) in rows.iter().enumerate() {
            let metric_key = metric_key(token, source.family(&row.metric_name));
            if admitted.contains(&metric_key) {
                groups.entry(metric_key).or_default().push(index);
            }
        }
        self.measure(
            rows,
            &new_flags(rows.len(), new_rows),
            groups,
            source,
            now,
            window,
        );
    }

    fn reserve_tracking(&self, token_hash: u64) -> bool {
        if self.tracked_count.fetch_add(1, Ordering::AcqRel) >= self.settings.max_tracked_metrics {
            self.tracked_count.fetch_sub(1, Ordering::AcqRel);
            return false;
        }
        let mut count = self.tracked_per_token.entry(token_hash).or_insert(0);
        if *count >= self.settings.max_tracked_metrics_per_token {
            drop(count);
            self.tracked_count.fetch_sub(1, Ordering::AcqRel);
            return false;
        }
        *count += 1;
        true
    }

    fn add_candidate(
        &self,
        metric_key: u64,
        token: &Arc<str>,
        token_hash: u64,
        family_name: &str,
        window: i64,
    ) -> bool {
        if self.candidates.contains_key(&metric_key) {
            return true;
        }
        if self.candidate_count.fetch_add(1, Ordering::AcqRel) >= self.settings.max_candidates {
            self.candidate_count.fetch_sub(1, Ordering::AcqRel);
            counter!("capture_metrics_label_cardinality_candidates_full", "cap" => "global")
                .increment(1);
            return false;
        }
        {
            let mut per_token = self.candidates_per_token.entry(token_hash).or_insert(0);
            if *per_token >= self.settings.max_candidates_per_token {
                drop(per_token);
                self.candidate_count.fetch_sub(1, Ordering::AcqRel);
                counter!("capture_metrics_label_cardinality_candidates_full", "cap" => "token")
                    .increment(1);
                return false;
            }
            *per_token += 1;
        }
        let candidate = Candidate {
            token: Arc::clone(token),
            token_hash,
            family: truncated(family_name).into(),
            window,
            qualified_window: window,
            series: Sketch::new(),
            keys: HashMap::new(),
        };
        if let dashmap::Entry::Vacant(slot) = self.candidates.entry(metric_key) {
            slot.insert(Mutex::new(candidate));
        } else {
            self.candidate_count.fetch_sub(1, Ordering::AcqRel);
            self.release_candidate_slot(token_hash);
        }
        true
    }

    fn release_candidate_slot(&self, token_hash: u64) {
        if let Some(mut per_token) = self.candidates_per_token.get_mut(&token_hash) {
            *per_token = per_token.saturating_sub(1);
        }
    }

    pub fn observe(
        &self,
        token: &str,
        rows: &[KafkaMetricRow],
        new_rows: &[usize],
        source: &Source,
    ) {
        if self.settings.mode == Mode::Off
            || (self.candidates.is_empty() && self.rules.is_empty())
            || self.unknown_tokens.is_unknown(token)
        {
            return;
        }
        let now = (self.clock)();
        let window = self.window_index(now);
        let token_label: Arc<str> = Arc::from(token);
        let token_hash = token_key(token);

        let mut keys_by_name: HashMap<&str, u64> = HashMap::new();
        let mut groups: HashMap<u64, Vec<usize>> = HashMap::new();
        for (index, row) in rows.iter().enumerate() {
            let family_name = source.family(&row.metric_name);
            let metric_key = *keys_by_name
                .entry(row.metric_name.as_str())
                .or_insert_with(|| metric_key(token, family_name));
            if self.candidates.contains_key(&metric_key)
                || (self.rules.contains_key(&metric_key)
                    && self.add_candidate(
                        metric_key,
                        &token_label,
                        token_hash,
                        family_name,
                        window,
                    ))
            {
                groups.entry(metric_key).or_default().push(index);
            }
        }
        if groups.is_empty() {
            return;
        }
        self.measure(
            rows,
            &new_flags(rows.len(), new_rows),
            groups,
            source,
            now,
            window,
        );
    }

    fn measure(
        &self,
        rows: &[KafkaMetricRow],
        new_series: &[bool],
        groups: HashMap<u64, Vec<usize>>,
        source: &Source,
        now: i64,
        window: i64,
    ) {
        let mut contended = 0u64;
        for (metric_key, indices) in groups {
            let Some(slot) = self.candidates.get(&metric_key) else {
                continue;
            };
            for chunk in indices.chunks(MEASURE_CHUNK_ROWS) {
                let hashes: Vec<RowHashes> = chunk
                    .iter()
                    .map(|&index| self.row_hashes(&rows[index], new_series[index], source))
                    .collect();
                let Ok(mut candidate) = slot.try_lock() else {
                    contended += 1;
                    continue;
                };
                self.roll(metric_key, &mut candidate, window, now);
                for row in hashes {
                    self.feed(&mut candidate, row);
                }
            }
        }
        if contended > 0 {
            counter!("capture_metrics_label_cardinality_batches_contended").increment(contended);
        }
    }

    fn row_hashes<'r>(
        &self,
        row: &'r KafkaMetricRow,
        new_series: bool,
        source: &Source,
    ) -> RowHashes<'r> {
        let mut series = value_hash(self.value_keys, &row.service_name);
        let mut values = Vec::new();
        for (scope, map) in [
            (Scope::Attribute, &row.attributes),
            (Scope::Resource, &row.resource_attributes),
        ] {
            for (name, value) in map {
                if scope == Scope::Attribute
                    && (name == ORIGINAL_TIMESTAMP_ATTRIBUTE
                        || source.is_component_label(row, name))
                {
                    continue;
                }
                let key = key_hash(name);
                let hash = value_hash(self.value_keys, value);
                let pair = pair_hash(scope, key, hash);
                series = series.wrapping_add(pair);
                if !self.protected.contains(&(scope, key)) {
                    values.push((scope, key, hash, pair, name.as_str()));
                }
            }
        }
        RowHashes {
            series,
            new_series,
            values,
        }
    }

    fn feed(&self, candidate: &mut Candidate, row: RowHashes) {
        candidate.series.insert(row.series);
        let max_keys = self.settings.max_keys_per_candidate;
        let new_rows = u64::from(row.new_series);
        let mut keys_full = 0u64;
        for (scope, key, hash, pair, name) in row.values {
            let others = row.series.wrapping_sub(pair);
            if let Some(entry) = candidate.keys.get_mut(&(scope, key)) {
                entry.sketch.insert(hash);
                entry.with.insert(row.series);
                entry.others.insert(others);
                entry.rows += 1;
                entry.new_rows += new_rows;
                continue;
            }
            if candidate.keys.len() >= max_keys {
                keys_full += 1;
                continue;
            }
            let mut sketch = Sketch::new();
            sketch.insert(hash);
            let mut with = Sketch::new();
            with.insert(row.series);
            let mut others_sketch = Sketch::new();
            others_sketch.insert(others);
            candidate.keys.insert(
                (scope, key),
                KeySketch {
                    sketch,
                    with,
                    others: others_sketch,
                    name: truncated(name).into(),
                    rows: 1,
                    new_rows,
                },
            );
        }
        if keys_full > 0 {
            counter!("capture_metrics_label_cardinality_keys_full").increment(keys_full);
        }
    }

    /// Judges a window only when it is complete. Every series is new at the start of a window,
    /// so a partial window shows a new-series share near 1 for real labels too.
    fn roll(&self, metric_key: u64, candidate: &mut Candidate, window: i64, now: i64) {
        if candidate.window == window {
            return;
        }
        self.evaluate(metric_key, candidate, now);
        candidate.window = window;
        candidate.series = Sketch::new();
        candidate.keys.clear();
    }

    /// A new rule needs a key that accounts for most of the metric's series and gives most of
    /// its points a new series. A key accounts for the series when its values or the series it
    /// saves reach the share. Values catch two labels that carry the same value. Saved series
    /// catch cardinality split across two labels. Both skip a stable key, such as a user ID,
    /// beside a per-point key. The new-series test skips a key, such as a pod name, whose series
    /// repeat.
    fn evaluate(&self, metric_key: u64, candidate: &Candidate, now: i64) {
        let ttl = self.settings.rule_ttl.as_secs() as i64;
        let limit = self.settings.value_limit;
        let min_new_share = self.settings.min_new_share;
        if self
            .skipped
            .get(&candidate.token_hash)
            .is_some_and(|window| *window == candidate.window)
        {
            return;
        }
        let series = candidate.series.estimate();
        for ((scope, key), entry) in &candidate.keys {
            let distinct = entry.sketch.estimate();
            let new_share = entry.new_rows as f64 / entry.rows.max(1) as f64;
            if distinct * 2 < limit || new_share * 2.0 < min_new_share {
                continue;
            }
            let existing = self.rules.get(&metric_key).and_then(|rules| {
                rules
                    .iter()
                    .find(|rule| {
                        rule.scope == *scope && rule.key_hash == *key && rule.expires_at > now
                    })
                    .map(|rule| rule.expires_at)
            });
            let new_rule = match existing {
                Some(expires_at) => {
                    if expires_at - now > ttl / 2 {
                        continue;
                    }
                    false
                }
                None => {
                    let share = self.settings.min_share * series as f64;
                    let saved = entry
                        .with
                        .estimate()
                        .saturating_sub(entry.others.estimate());
                    if distinct < limit
                        || ((distinct as f64) < share && (saved as f64) < share)
                        || new_share < min_new_share
                    {
                        continue;
                    }
                    true
                }
            };
            let rule = Rule {
                metric_key,
                token_hash: candidate.token_hash,
                scope: *scope,
                key_hash: *key,
                expires_at: now + ttl,
            };
            if !self.merge_rule(rule.clone()) {
                continue;
            }
            if new_rule {
                warn!(
                    token = %candidate.token,
                    metric = %candidate.family,
                    scope = ?rule.scope,
                    key = %entry.name,
                    distinct_values = distinct,
                    distinct_series = series,
                    rows = entry.rows,
                    new_series_rows = entry.new_rows,
                    mode = self.settings.mode.as_str(),
                    "High cardinality metric label flagged"
                );
                counter!(
                    "capture_metrics_label_cardinality_rules_created",
                    "mode" => self.settings.mode.as_str()
                )
                .increment(1);
            }
            if let Some(tx) = &self.tx {
                if tx.try_send(rule).is_err() {
                    counter!("capture_metrics_label_cardinality_redis_queue_full").increment(1);
                }
            }
        }
    }

    fn merge_rule(&self, rule: Rule) -> bool {
        if let Some(mut rules) = self.rules.get_mut(&rule.metric_key) {
            if let Some(existing) = rules
                .iter_mut()
                .find(|r| r.scope == rule.scope && r.key_hash == rule.key_hash)
            {
                existing.expires_at = existing.expires_at.max(rule.expires_at);
                return true;
            }
        }
        if self.rule_count.fetch_add(1, Ordering::AcqRel) >= MAX_RULES {
            self.rule_count.fetch_sub(1, Ordering::AcqRel);
            counter!("capture_metrics_label_cardinality_rules_full", "cap" => "global")
                .increment(1);
            return false;
        }
        {
            let mut per_token = self.rules_per_token.entry(rule.token_hash).or_insert(0);
            if *per_token >= MAX_RULES_PER_TOKEN {
                drop(per_token);
                self.rule_count.fetch_sub(1, Ordering::AcqRel);
                counter!("capture_metrics_label_cardinality_rules_full", "cap" => "token")
                    .increment(1);
                return false;
            }
            *per_token += 1;
        }
        let mut rules = self.rules.entry(rule.metric_key).or_default();
        if rules
            .iter()
            .any(|r| r.scope == rule.scope && r.key_hash == rule.key_hash)
        {
            self.rule_count.fetch_sub(1, Ordering::AcqRel);
            self.release_rule_slot(rule.token_hash);
            return true;
        }
        rules.push(rule);
        true
    }

    fn release_rule_slot(&self, token_hash: u64) {
        if let Some(mut per_token) = self.rules_per_token.get_mut(&token_hash) {
            *per_token = per_token.saturating_sub(1);
        }
    }

    pub fn strip_reserved(&self, rows: &mut [KafkaMetricRow], source: &Source) {
        for row in rows.iter_mut() {
            let attribute = row.attributes.remove(DROPPED_LABELS_ATTRIBUTE);
            let resource = row.resource_attributes.remove(DROPPED_LABELS_ATTRIBUTE);
            if attribute.is_some() || resource.is_some() {
                row.series_fingerprint = series_fingerprint(row, source);
            }
        }
    }

    /// Returns true when a row changed, so the caller classifies the rows again.
    pub fn apply(&self, token: &str, rows: &mut Vec<KafkaMetricRow>, source: &Source) -> bool {
        if self.settings.mode == Mode::Off || self.rules.is_empty() {
            return false;
        }
        let now = (self.clock)();
        let enforce = self.settings.mode == Mode::Enforce;
        let mut active_by_name: HashMap<String, Vec<(Scope, u64)>> = HashMap::new();
        let mut recomputed: HashMap<i64, i64> = HashMap::new();
        let mut changed = vec![false; rows.len()];
        let mut changed_count = 0u64;

        for (index, row) in rows.iter_mut().enumerate() {
            // Combining cumulative series needs reset-aware aggregation, so they
            // are left as they are.
            if row.metric_type != GAUGE_TYPE && row.aggregation_temporality != DELTA {
                continue;
            }
            if !active_by_name.contains_key(&row.metric_name) {
                let active =
                    self.active_rules(metric_key(token, source.family(&row.metric_name)), now);
                active_by_name.insert(row.metric_name.clone(), active);
            }
            let active = &active_by_name[&row.metric_name];
            if active.is_empty() {
                continue;
            }
            let mut dropped: Vec<String> = Vec::new();
            for (scope, map) in [
                (Scope::Attribute, &mut row.attributes),
                (Scope::Resource, &mut row.resource_attributes),
            ] {
                let matched: Vec<String> = map
                    .keys()
                    .filter(|key| active.contains(&(scope, key_hash(key))))
                    .cloned()
                    .collect();
                for key in matched {
                    if enforce {
                        map.remove(&key);
                    }
                    dropped.push(key);
                }
            }
            if dropped.is_empty() {
                continue;
            }
            changed_count += 1;
            if !enforce {
                continue;
            }
            changed[index] = true;
            row.series_fingerprint = *recomputed
                .entry(row.series_fingerprint)
                .or_insert_with(|| series_fingerprint(row, source));
            dropped.sort_unstable();
            dropped.dedup();
            let keys = serde_json::to_string(&dropped).unwrap_or_default();
            row.attributes.insert(
                DROPPED_LABELS_ATTRIBUTE.to_string(),
                serde_json::Value::String(keys).to_string(),
            );
        }

        if changed_count > 0 {
            counter!(
                "capture_metrics_label_cardinality_rows_dropped",
                "mode" => self.settings.mode.as_str()
            )
            .increment(changed_count);
        }
        if !enforce || changed_count == 0 {
            return false;
        }
        coalesce(rows, &changed);
        true
    }

    fn active_rules(&self, metric_key: u64, now: i64) -> Vec<(Scope, u64)> {
        self.rules
            .get(&metric_key)
            .map(|rules| {
                rules
                    .iter()
                    .filter(|rule| {
                        rule.expires_at > now
                            && !self.protected.contains(&(rule.scope, rule.key_hash))
                    })
                    .map(|rule| (rule.scope, rule.key_hash))
                    .collect()
            })
            .unwrap_or_default()
    }

    fn prune(&self, now: i64) {
        let window = self.window_index(now);
        self.rules.retain(|_, rules| {
            rules.retain(|rule| {
                if rule.expires_at > now {
                    return true;
                }
                self.rule_count.fetch_sub(1, Ordering::AcqRel);
                self.release_rule_slot(rule.token_hash);
                false
            });
            !rules.is_empty()
        });
        self.rules_per_token.retain(|_, count| *count > 0);
        self.candidates.retain(|metric_key, candidate| {
            let candidate = candidate.get_mut().unwrap_or_else(PoisonError::into_inner);
            self.roll(*metric_key, candidate, window, now);
            if candidate.qualified_window >= window - 1 || self.rules.contains_key(metric_key) {
                return true;
            }
            self.candidate_count.fetch_sub(1, Ordering::AcqRel);
            self.release_candidate_slot(candidate.token_hash);
            false
        });
        self.candidates_per_token.retain(|_, count| *count > 0);
        self.new_series.retain(|_, count| {
            if count.window >= window {
                return true;
            }
            self.tracked_count.fetch_sub(1, Ordering::AcqRel);
            if let Some(mut per_token) = self.tracked_per_token.get_mut(&count.token_hash) {
                *per_token = per_token.saturating_sub(1);
            }
            false
        });
        self.tracked_per_token.retain(|_, count| *count > 0);
        self.skipped.retain(|_, skipped| *skipped >= window - 1);
        gauge!("capture_metrics_label_cardinality_candidates")
            .set(self.candidate_count.load(Ordering::Acquire) as f64);
        gauge!("capture_metrics_label_cardinality_rules")
            .set(self.rule_count.load(Ordering::Acquire) as f64);
    }

    pub fn spawn_pruner(self: &Arc<Self>) {
        let detector = Arc::clone(self);
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(PRUNE_INTERVAL);
            ticker.tick().await;
            loop {
                ticker.tick().await;
                detector.prune((detector.clock)());
            }
        });
    }

    pub async fn pull_rules(&self, client: &dyn Client) -> Result<usize, CustomRedisError> {
        let now = (self.clock)();
        let ttl = self.settings.rule_ttl.as_secs() as i64;
        let mut merged = 0usize;
        // A pod holds at most MAX_RULES, so reading more only adds load when senders fill Redis.
        let mut budget = MAX_RULES;
        'buckets: for key in bucket_keys(now, now + ttl) {
            let mut offset = 0usize;
            loop {
                if budget == 0 {
                    counter!("capture_metrics_label_cardinality_pull_capped").increment(1);
                    break 'buckets;
                }
                let page_size = PULL_PAGE_SIZE.min(budget);
                let page = match client
                    .zrangebyscore_limit_withscores(
                        key.clone(),
                        now.to_string(),
                        "+inf".to_string(),
                        offset as isize,
                        page_size as isize,
                    )
                    .await
                {
                    Ok(page) => page,
                    Err(CustomRedisError::NotFound) => break,
                    Err(e) => return Err(e),
                };
                let page_len = page.len();
                budget -= page_len;
                for (member, score) in page {
                    match serde_json::from_str::<Rule>(&member) {
                        Ok(mut rule) => {
                            rule.expires_at = score as i64;
                            if self.merge_rule(rule) {
                                merged += 1;
                            }
                        }
                        Err(e) => debug!("Skipping unreadable label drop rule: {e}"),
                    }
                }
                if page_len < page_size {
                    break;
                }
                offset += page_len;
            }
        }
        Ok(merged)
    }

    pub fn spawn_redis_sync(
        self: &Arc<Self>,
        client: Arc<dyn Client>,
        mut rx: mpsc::Receiver<Rule>,
        interval: Duration,
        timeout: Duration,
    ) {
        let detector = Arc::clone(self);
        let ttl_secs = self.settings.rule_ttl.as_secs() + REDIS_BUCKET_SECS as u64;
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            let mut pending: Vec<Rule> = Vec::new();
            loop {
                tokio::select! {
                    rule = rx.recv() => {
                        let Some(rule) = rule else { return };
                        pending.push(rule);
                        while let Ok(rule) = rx.try_recv() {
                            pending.push(rule);
                        }
                        push_rules(client.as_ref(), &mut pending, ttl_secs, timeout).await;
                    }
                    _ = ticker.tick() => {
                        if !pending.is_empty() {
                            push_rules(client.as_ref(), &mut pending, ttl_secs, timeout).await;
                        }
                        let outcome = match tokio::time::timeout(timeout, detector.pull_rules(client.as_ref())).await {
                            Ok(Ok(merged)) => {
                                debug!("Pulled {merged} label drop rules from Redis");
                                "ok"
                            }
                            Ok(Err(e)) => {
                                debug!("Label drop rule pull from Redis failed: {e}");
                                if e.is_unrecoverable_error() {
                                    client.heal().await;
                                }
                                "error"
                            }
                            Err(_) => "timeout",
                        };
                        counter!("capture_metrics_label_cardinality_redis_pulls", "outcome" => outcome)
                            .increment(1);
                    }
                }
            }
        });
    }
}

async fn push_rules(
    client: &dyn Client,
    pending: &mut Vec<Rule>,
    ttl_secs: u64,
    timeout: Duration,
) {
    let pushed = pending.len() as u64;
    let commands = rule_commands(pending, ttl_secs);
    let outcome = match tokio::time::timeout(timeout, client.execute_pipeline(commands)).await {
        Ok(Ok(_)) => "ok",
        Ok(Err(e)) => {
            debug!("Label drop rule push to Redis failed: {e}");
            "error"
        }
        Err(_) => "timeout",
    };
    counter!("capture_metrics_label_cardinality_redis_pushed", "outcome" => outcome)
        .increment(pushed);
    if outcome == "ok" {
        pending.clear();
    } else if pending.len() > MAX_PENDING_PUSHES {
        pending.drain(..pending.len() - MAX_PENDING_PUSHES);
    }
}

/// Must match the row builders, or a dropped label does not combine series.
fn series_fingerprint(row: &KafkaMetricRow, source: &Source) -> i64 {
    let mut attributes = row.attributes.clone();
    attributes.remove(ORIGINAL_TIMESTAMP_ATTRIBUTE);
    attributes.remove(DROPPED_LABELS_ATTRIBUTE);
    let fingerprint = compute_series_fingerprint(
        &row.metric_name,
        &row.metric_type,
        &row.service_name,
        &row.resource_attributes,
        &attributes,
    );
    if source.remote_write && row.metric_type == HISTOGRAM_TYPE {
        fingerprint_with_bounds(fingerprint, &row.histogram_bounds)
    } else {
        fingerprint
    }
}

/// Storage caps points per series and hour, so a combined series keeps one point per second per request.
fn coalesce(rows: &mut Vec<KafkaMetricRow>, changed: &[bool]) {
    let mut first: HashMap<(i64, i64), usize> = HashMap::new();
    let mut keep = vec![true; rows.len()];
    for index in 0..rows.len() {
        if !changed[index] || !rows[index].value.is_finite() {
            continue;
        }
        let second = rows[index].timestamp.timestamp();
        let target = *first
            .entry((rows[index].series_fingerprint, second))
            .or_insert(index);
        if target == index {
            continue;
        }
        let (head, tail) = rows.split_at_mut(index);
        if merge_point(&mut head[target], &tail[0]) {
            keep[index] = false;
        }
    }
    let mut keep = keep.into_iter();
    rows.retain(|_| keep.next().unwrap_or(true));
}

fn merge_point(target: &mut KafkaMetricRow, other: &KafkaMetricRow) -> bool {
    if target.metric_type != other.metric_type {
        return false;
    }
    match target.metric_type.as_str() {
        SUM_TYPE => {
            target.value += other.value;
            target.count += other.count;
            true
        }
        HISTOGRAM_TYPE => {
            if target.histogram_bounds != other.histogram_bounds
                || target.histogram_counts.len() != other.histogram_counts.len()
            {
                return false;
            }
            for (count, add) in target
                .histogram_counts
                .iter_mut()
                .zip(&other.histogram_counts)
            {
                *count += add;
            }
            target.value += other.value;
            target.count += other.count;
            true
        }
        GAUGE_TYPE => true,
        _ => false,
    }
}

fn metric_key(token: &str, family: &str) -> u64 {
    let mut hasher = SipHasher13::new();
    hasher.write(&(token.len() as u64).to_le_bytes());
    hasher.write(token.as_bytes());
    hasher.write(family.as_bytes());
    hasher.finish()
}

fn token_key(token: &str) -> u64 {
    let mut hasher = SipHasher13::new();
    hasher.write(token.as_bytes());
    hasher.finish()
}

fn pair_hash(scope: Scope, key_hash: u64, value_hash: u64) -> u64 {
    let mut hasher = SipHasher13::new();
    hasher.write_u8(scope as u8);
    hasher.write(&key_hash.to_le_bytes());
    hasher.write(&value_hash.to_le_bytes());
    hasher.finish()
}

fn key_hash(key: &str) -> u64 {
    let mut hasher = SipHasher13::new_with_keys(0, 1);
    hasher.write(key.as_bytes());
    hasher.finish()
}

fn truncated(name: &str) -> &str {
    match name.char_indices().nth(MAX_NAME_CHARS) {
        Some((end, _)) => &name[..end],
        None => name,
    }
}

fn random_keys() -> (u64, u64) {
    let state = RandomState::new();
    (state.hash_one(0u8), state.hash_one(1u8))
}

fn value_hash((k0, k1): (u64, u64), value: &str) -> u64 {
    let mut hasher = SipHasher13::new_with_keys(k0, k1);
    hasher.write(value.as_bytes());
    hasher.finish()
}

fn new_flags(len: usize, new_rows: &[usize]) -> Vec<bool> {
    let mut flags = vec![false; len];
    for &index in new_rows {
        if let Some(flag) = flags.get_mut(index) {
            *flag = true;
        }
    }
    flags
}

fn bucket_key(unix_secs: i64) -> String {
    format!(
        "{REDIS_KEY_PREFIX}:{}",
        unix_secs.div_euclid(REDIS_BUCKET_SECS)
    )
}

fn bucket_keys(from: i64, to: i64) -> Vec<String> {
    let first = from.div_euclid(REDIS_BUCKET_SECS);
    let last = to.div_euclid(REDIS_BUCKET_SECS);
    (first..=last)
        .map(|bucket| format!("{REDIS_KEY_PREFIX}:{bucket}"))
        .collect()
}

fn rule_commands(rules: &[Rule], ttl_secs: u64) -> Vec<PipelineCommand> {
    let mut by_bucket: HashMap<String, Vec<(i64, String)>> = HashMap::new();
    for rule in rules {
        let Ok(member) = serde_json::to_string(rule) else {
            continue;
        };
        by_bucket
            .entry(bucket_key(rule.expires_at))
            .or_default()
            .push((rule.expires_at, member));
    }
    let mut commands = Vec::with_capacity(by_bucket.len() * 2);
    for (bucket, members) in by_bucket {
        // A late publish of an older detection must not shorten the rule.
        commands.push(PipelineCommand::ZAddGt {
            key: bucket.clone(),
            members,
        });
        commands.push(PipelineCommand::Expire {
            key: bucket,
            seconds: ttl_secs,
        });
    }
    commands
}

fn unix_now() -> i64 {
    Utc::now().timestamp()
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::AtomicI64;

    use capture_logs::endpoints::prometheus::write_timeseries_to_kafka_rows;
    use common_redis::MockRedisClient;
    use prometheus_rw_proto::prometheus::v1::{Label, MetricMetadata, Sample, TimeSeries};

    use super::*;
    use crate::histogram_assembly::fold_classic_histograms;

    const TOKEN: &str = "phc_test";
    const START: i64 = 1_800_000_000;
    const LIMIT: u64 = 200;

    fn rw() -> Source<'static> {
        Source::remote_write(&[])
    }

    fn settings(mode: Mode) -> Settings {
        Settings {
            mode,
            window: Duration::from_secs(1800),
            value_limit: LIMIT,
            min_share: 0.5,
            min_new_share: 0.5,
            candidate_min_new_series: 10,
            max_candidates: 100,
            max_candidates_per_token: 100,
            max_keys_per_candidate: 32,
            max_tracked_metrics: 1000,
            max_tracked_metrics_per_token: 1000,
            rule_ttl: Duration::from_secs(7200),
            protected_keys: ["le".to_string(), "quantile".to_string()].into(),
        }
    }

    fn detector(mode: Mode) -> (LabelCardinality, Arc<AtomicI64>) {
        detector_with(settings(mode))
    }

    fn detector_with(settings: Settings) -> (LabelCardinality, Arc<AtomicI64>) {
        let now = Arc::new(AtomicI64::new(START));
        let clock_now = Arc::clone(&now);
        let detector = LabelCardinality::build(
            settings,
            None,
            Arc::new(move || clock_now.load(Ordering::SeqCst)),
        );
        (detector, now)
    }

    fn label(name: &str, value: &str) -> Label {
        Label {
            name: name.to_string(),
            value: value.to_string(),
        }
    }

    fn histogram_series(users: usize, with_user: bool) -> Vec<TimeSeries> {
        let timestamp = Utc::now().timestamp_millis();
        let mut series = Vec::new();
        for user in 0..users {
            let mut base = vec![
                label("job", "api"),
                label("route", &format!("/r{}", user % 4)),
            ];
            if with_user {
                base.push(label("user_id", &format!("u{user}")));
            }
            let mut push = |name: &str, extra: Option<Label>, value: f64| {
                let mut labels = vec![label("__name__", name)];
                labels.extend(base.iter().cloned());
                labels.extend(extra);
                series.push(TimeSeries {
                    labels,
                    samples: vec![Sample { value, timestamp }],
                });
            };
            push("latency_bucket", Some(label("le", "0.5")), 1.0);
            push("latency_bucket", Some(label("le", "+Inf")), 2.0);
            push("latency_sum", None, 0.7);
            push("latency_count", None, 2.0);
            push("requests_total", None, 5.0);
        }
        series
    }

    fn remote_write_rows(users: usize, with_user: bool) -> Vec<KafkaMetricRow> {
        let (rows, _) = write_timeseries_to_kafka_rows(histogram_series(users, with_user), &[]);
        fold_classic_histograms(rows, &[])
    }

    fn as_delta(mut rows: Vec<KafkaMetricRow>) -> Vec<KafkaMetricRow> {
        for row in rows.iter_mut() {
            row.aggregation_temporality = DELTA.to_string();
        }
        rows
    }

    fn all_rows_new(rows: &[KafkaMetricRow]) -> Vec<usize> {
        (0..rows.len()).collect()
    }

    fn end_window(detector: &LabelCardinality, now: &AtomicI64) {
        let next = now.load(Ordering::SeqCst) + settings(Mode::Shadow).window.as_secs() as i64;
        now.store(next, Ordering::SeqCst);
        detector.prune(next);
    }

    fn learn(detector: &LabelCardinality, now: &AtomicI64, rows: &[KafkaMetricRow]) {
        detector.note_new_series(TOKEN, rows, &all_rows_new(rows), &rw());
        detector.observe(TOKEN, rows, &all_rows_new(rows), &rw());
        end_window(detector, now);
    }

    fn rows_with(
        name: &str,
        key: &str,
        values: impl Iterator<Item = String>,
    ) -> Vec<KafkaMetricRow> {
        let timestamp = Utc::now().timestamp_millis();
        let series = values
            .map(|value| TimeSeries {
                labels: vec![label("__name__", name), label(key, &value)],
                samples: vec![Sample {
                    value: 1.0,
                    timestamp,
                }],
            })
            .collect();
        write_timeseries_to_kafka_rows(series, &[]).0
    }

    fn rule_keys(detector: &LabelCardinality) -> HashSet<(u64, Scope, u64)> {
        detector
            .rules
            .iter()
            .flat_map(|rules| {
                rules
                    .iter()
                    .map(|r| (r.metric_key, r.scope, r.key_hash))
                    .collect::<Vec<_>>()
            })
            .collect()
    }

    fn rule_key(family: &str, scope: Scope, key: &str) -> (u64, Scope, u64) {
        (metric_key(TOKEN, family), scope, key_hash(key))
    }

    fn named_rows(names: &[String], series_per_metric: usize) -> Vec<KafkaMetricRow> {
        let timestamp = Utc::now().timestamp_millis();
        let series = names
            .iter()
            .flat_map(|name| {
                (0..series_per_metric).map(move |user| TimeSeries {
                    labels: vec![
                        label("__name__", name),
                        label("user_id", &format!("u{user}")),
                    ],
                    samples: vec![Sample {
                        value: 1.0,
                        timestamp,
                    }],
                })
            })
            .collect();
        write_timeseries_to_kafka_rows(series, &[]).0
    }

    fn rule_for(family: &str, scope: Scope, key: &str) -> Rule {
        Rule {
            metric_key: metric_key(TOKEN, family),
            token_hash: token_key(TOKEN),
            scope,
            key_hash: key_hash(key),
            expires_at: START + 3600,
        }
    }

    #[test]
    fn flags_only_the_key_that_drives_series_growth() {
        let (detector, now) = detector(Mode::Shadow);
        let rows = remote_write_rows(1000, true);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        assert!(
            rule_keys(&detector).is_empty(),
            "a partial window is not judged"
        );
        end_window(&detector, &now);

        assert_eq!(
            rule_keys(&detector),
            HashSet::from([
                rule_key("latency", Scope::Attribute, "user_id"),
                rule_key("requests_total", Scope::Attribute, "user_id"),
            ])
        );
    }

    #[test]
    fn a_key_whose_series_repeat_is_not_flagged() {
        let (detector, now) = detector(Mode::Shadow);
        let pods = rows_with("requests", "pod", (0..1000).map(|i| format!("p{i}")));
        detector.note_new_series(TOKEN, &pods, &all_rows_new(&pods), &rw());
        for _ in 0..3 {
            detector.observe(TOKEN, &pods, &[], &rw());
        }
        for batch in 0..4 {
            let ids = rows_with(
                "jobs",
                "request_id",
                (0..1000).map(|i| format!("r{batch}-{i}")),
            );
            detector.observe(TOKEN, &ids, &all_rows_new(&ids), &rw());
            detector.note_new_series(TOKEN, &ids, &all_rows_new(&ids), &rw());
        }
        end_window(&detector, &now);

        assert_eq!(
            rule_keys(&detector),
            HashSet::from([rule_key("jobs", Scope::Attribute, "request_id")])
        );
    }

    #[test]
    fn a_stable_key_beside_a_per_point_key_is_not_flagged() {
        let (detector, now) = detector(Mode::Shadow);
        let timestamp = Utc::now().timestamp_millis();
        let series: Vec<TimeSeries> = (0..2000)
            .map(|i| TimeSeries {
                labels: vec![
                    label("__name__", "jobs"),
                    label("user_id", &format!("u{}", i % 300)),
                    label("request_id", &format!("r{i}")),
                ],
                samples: vec![Sample {
                    value: 1.0,
                    timestamp,
                }],
            })
            .collect();
        let (rows, _) = write_timeseries_to_kafka_rows(series, &[]);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);

        assert_eq!(
            rule_keys(&detector),
            HashSet::from([rule_key("jobs", Scope::Attribute, "request_id")])
        );
    }

    #[test]
    fn a_window_with_skipped_requests_is_not_judged() {
        let (detector, now) = detector(Mode::Shadow);
        let rows = remote_write_rows(1000, true);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.skip(TOKEN);
        end_window(&detector, &now);
        assert!(rule_keys(&detector).is_empty());

        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);
        assert!(rule_keys(&detector).contains(&rule_key("latency", Scope::Attribute, "user_id")));
    }

    #[test]
    fn a_key_split_across_a_second_label_is_still_flagged() {
        let (detector, now) = detector(Mode::Shadow);
        let timestamp = Utc::now().timestamp_millis();
        let series: Vec<TimeSeries> = (0..1500)
            .map(|i| TimeSeries {
                labels: vec![
                    label("__name__", "jobs"),
                    label("hax", &format!("h{}", i / 5)),
                    label("pad", &format!("p{}", i % 5)),
                ],
                samples: vec![Sample {
                    value: 1.0,
                    timestamp,
                }],
            })
            .collect();
        let (rows, _) = write_timeseries_to_kafka_rows(series, &[]);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);

        assert_eq!(
            rule_keys(&detector),
            HashSet::from([rule_key("jobs", Scope::Attribute, "hax")])
        );
    }

    #[test]
    fn two_labels_with_the_same_value_are_both_flagged() {
        let (detector, now) = detector(Mode::Shadow);
        let timestamp = Utc::now().timestamp_millis();
        let series: Vec<TimeSeries> = (0..1000)
            .map(|i| TimeSeries {
                labels: vec![
                    label("__name__", "jobs"),
                    label("request_id", &format!("r{i}")),
                    label("trace_id", &format!("t{i}")),
                ],
                samples: vec![Sample {
                    value: 1.0,
                    timestamp,
                }],
            })
            .collect();
        let (rows, _) = write_timeseries_to_kafka_rows(series, &[]);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);

        assert_eq!(
            rule_keys(&detector),
            HashSet::from([
                rule_key("jobs", Scope::Attribute, "request_id"),
                rule_key("jobs", Scope::Attribute, "trace_id"),
            ])
        );
    }

    #[test]
    fn an_optional_key_beside_a_per_point_key_is_not_flagged() {
        let (detector, now) = detector(Mode::Shadow);
        let timestamp = Utc::now().timestamp_millis();
        let series: Vec<TimeSeries> = (0..3000)
            .map(|i| {
                let mut labels = vec![
                    label("__name__", "jobs"),
                    label("request_id", &format!("r{i}")),
                ];
                if i % 10 == 0 {
                    labels.push(label("user_id", &format!("u{i}")));
                }
                TimeSeries {
                    labels,
                    samples: vec![Sample {
                        value: 1.0,
                        timestamp,
                    }],
                }
            })
            .collect();
        let (rows, _) = write_timeseries_to_kafka_rows(series, &[]);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);

        assert_eq!(
            rule_keys(&detector),
            HashSet::from([rule_key("jobs", Scope::Attribute, "request_id")])
        );
    }

    #[test]
    fn histogram_components_split_across_requests_count_as_one_series() {
        let (detector, now) = detector(Mode::Shadow);
        let (rows, _) = write_timeseries_to_kafka_rows(histogram_series(1000, true), &[]);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);

        assert!(rule_keys(&detector).contains(&rule_key("latency", Scope::Attribute, "user_id")));
    }

    #[test]
    fn new_metric_names_stop_being_tracked_at_the_cap() {
        let mut capped = settings(Mode::Shadow);
        capped.max_tracked_metrics = 5;
        let (detector, _) = detector_with(capped);
        let names: Vec<String> = (0..20).map(|i| format!("m{i}")).collect();
        let rows = named_rows(&names, 1);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());

        assert_eq!(detector.new_series.len(), 5);
    }

    #[tokio::test]
    async fn a_token_with_no_team_takes_no_tracking_slots() {
        use capture_logs::unknown_tokens::{UnknownTokenMode, UNKNOWN_TOKENS_KEY};
        use common_redis::MockRedisClient;

        let unknown = UnknownTokens::new(UnknownTokenMode::Shadow, Duration::from_secs(600));
        let client = MockRedisClient::new()
            .zrangebyscore_ret(UNKNOWN_TOKENS_KEY, vec!["phc_ghost".to_string()]);
        let now_ms = Utc::now().timestamp_millis();
        unknown
            .refresh(&client, now_ms, Duration::from_secs(3600))
            .await
            .unwrap();
        let mut capped = settings(Mode::Shadow);
        capped.max_tracked_metrics = 5;
        let (mut detector, _) = detector_with(capped);
        detector.unknown_tokens = unknown;
        let names: Vec<String> = (0..20).map(|i| format!("m{i}")).collect();
        let rows = named_rows(&names, 1);
        detector.note_new_series("phc_ghost", &rows, &all_rows_new(&rows), &rw());
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());

        assert_eq!(detector.new_series.len(), 5);
        assert!(detector
            .tracked_per_token
            .iter()
            .all(|entry| *entry.key() == token_key(TOKEN)));
    }

    #[test]
    fn one_token_at_its_cap_leaves_room_for_another() {
        let mut capped = settings(Mode::Shadow);
        capped.max_tracked_metrics_per_token = 5;
        let (detector, _) = detector_with(capped);
        let names: Vec<String> = (0..20).map(|i| format!("m{i}")).collect();
        let rows = named_rows(&names, 1);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.note_new_series("phc_other", &rows, &all_rows_new(&rows), &rw());

        assert_eq!(detector.new_series.len(), 10);
    }

    #[test]
    fn a_candidate_that_stops_qualifying_frees_its_slot() {
        for poisoned in [false, true] {
            let mut one_slot = settings(Mode::Shadow);
            one_slot.max_candidates = 1;
            let (detector, now) = detector_with(one_slot);
            let first = named_rows(&["first".to_string()], 20);
            detector.note_new_series(TOKEN, &first, &all_rows_new(&first), &rw());
            if poisoned {
                let slot = detector
                    .candidates
                    .get(&metric_key(TOKEN, "first"))
                    .unwrap();
                let poisoning = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    let _guard = slot.lock().unwrap();
                    panic!("poison the candidate lock");
                }));
                assert!(poisoning.is_err());
            }

            let window = settings(Mode::Shadow).window.as_secs() as i64;
            now.store(START + 2 * window, Ordering::SeqCst);
            detector.observe(TOKEN, &first, &[], &rw());
            detector.prune(START + 2 * window);

            let second = named_rows(&["second".to_string()], 20);
            detector.note_new_series(TOKEN, &second, &all_rows_new(&second), &rw());
            assert!(
                detector
                    .candidates
                    .contains_key(&metric_key(TOKEN, "second")),
                "poisoned: {poisoned}"
            );
        }
    }

    #[test]
    fn rules_stop_being_admitted_at_the_cap() {
        let (detector, _) = detector(Mode::Shadow);
        for i in 0..MAX_RULES_PER_TOKEN + 10 {
            detector.merge_rule(rule_for(&format!("m{i}"), Scope::Attribute, "user_id"));
        }
        assert_eq!(rule_keys(&detector).len(), MAX_RULES_PER_TOKEN);

        for i in 0..MAX_RULES + 10 {
            let mut rule = rule_for(&format!("other{i}"), Scope::Attribute, "user_id");
            rule.token_hash = i as u64;
            detector.merge_rule(rule);
        }
        assert_eq!(rule_keys(&detector).len(), MAX_RULES);
        assert_eq!(detector.rules.len(), MAX_RULES);
    }

    #[test]
    fn service_name_is_never_flagged() {
        let (detector, now) = detector(Mode::Shadow);
        let timestamp = Utc::now().timestamp_millis();
        let series: Vec<TimeSeries> = (0..1000)
            .map(|i| TimeSeries {
                labels: vec![
                    label("__name__", "jobs_total"),
                    label("job", &format!("j{i}")),
                ],
                samples: vec![Sample {
                    value: 1.0,
                    timestamp,
                }],
            })
            .collect();
        let (rows, _) = write_timeseries_to_kafka_rows(series, &[]);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);

        assert!(rule_keys(&detector).is_empty());
    }

    #[test]
    fn the_batch_that_admits_a_candidate_is_measured() {
        let (detector, now) = detector(Mode::Shadow);
        let rows = remote_write_rows(1000, true);
        detector.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&detector, &now);

        assert!(rule_keys(&detector).contains(&rule_key("latency", Scope::Attribute, "user_id")));
    }

    #[test]
    fn only_histogram_and_summary_components_share_a_family() {
        let metadata = [
            ("jobs_count", MetricType::Gauge),
            ("requests", MetricType::Counter),
            ("rpc_duration", MetricType::Summary),
        ]
        .map(|(name, kind)| MetricMetadata {
            r#type: kind as i32,
            metric_family_name: name.to_string(),
            ..Default::default()
        });
        let source = Source::remote_write(&metadata);
        for (name, family) in [
            ("latency_bucket", "latency"),
            ("latency_count", "latency"),
            ("jobs_count", "jobs_count"),
            ("requests_count", "requests_count"),
            ("rpc_duration_sum", "rpc_duration"),
        ] {
            assert_eq!(source.family(name), family, "{name}");
        }
        assert_eq!(Source::otlp().family("latency_count"), "latency_count");

        let row = |name: &str| named_rows(&[name.to_string()], 1).remove(0);
        assert!(source.is_component_label(&row("rpc_duration"), "quantile"));
        assert!(!source.is_component_label(&row("queue_depth"), "quantile"));
        assert!(source.is_component_label(&row("latency_bucket"), "le"));
        assert!(!rw().is_component_label(&row("queue_depth"), "le"));
    }

    #[test]
    fn one_token_cannot_take_every_candidate_slot() {
        let mut capped = settings(Mode::Shadow);
        capped.max_candidates_per_token = 2;
        let (detector, _) = detector_with(capped);
        let names: Vec<String> = (0..5).map(|i| format!("m{i}")).collect();
        let rows = named_rows(&names, 20);
        detector.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        detector.note_new_series("phc_other", &rows, &all_rows_new(&rows), &rw());

        assert_eq!(detector.candidates.len(), 4);
    }

    #[test]
    fn the_admitting_batch_is_measured_in_full() {
        let (detector, now) = detector(Mode::Shadow);
        let timestamp = Utc::now().timestamp_millis();
        let series: Vec<TimeSeries> = (0..4000)
            .map(|i| TimeSeries {
                labels: vec![
                    label("__name__", "jobs_total"),
                    label("user_id", &format!("u{}", i / 4)),
                    label("instance", &format!("i{i}")),
                ],
                samples: vec![Sample {
                    value: 1.0,
                    timestamp,
                }],
            })
            .collect();
        let (rows, _) = write_timeseries_to_kafka_rows(series, &[]);
        // The gate already knows three of each user's four series.
        let new_rows: Vec<usize> = (0..rows.len()).step_by(4).collect();
        detector.note_new_series(TOKEN, &rows, &new_rows, &rw());
        end_window(&detector, &now);

        assert!(!rule_keys(&detector).contains(&rule_key(
            "jobs_total",
            Scope::Attribute,
            "user_id"
        )));
    }

    #[test]
    fn a_burst_right_after_admission_is_evaluated() {
        let (detector, now) = detector(Mode::Shadow);
        let small = remote_write_rows(20, true);
        detector.note_new_series(TOKEN, &small, &all_rows_new(&small), &rw());
        let burst = remote_write_rows(1000, true);
        detector.observe(TOKEN, &burst, &all_rows_new(&burst), &rw());
        end_window(&detector, &now);
        assert!(rule_keys(&detector).contains(&rule_key("latency", Scope::Attribute, "user_id")));
    }

    #[test]
    fn values_chosen_against_a_fixed_hash_key_are_still_counted() {
        assert_ne!(random_keys(), random_keys());
        let mut sketch = Sketch::new();
        let mut chosen = 0;
        for i in 0.. {
            let value = format!("\"u{i}\"");
            if value_hash((0, 0), &value) >> 63 == 0 {
                sketch.insert(value_hash((7, 11), &value));
                chosen += 1;
                if chosen == 20_000 {
                    break;
                }
            }
        }
        assert!(sketch.estimate() > 15_000, "estimate={}", sketch.estimate());
    }

    #[test]
    fn sketch_estimate_stays_within_a_few_standard_errors() {
        for n in [100u64, 1_000, 10_000, 100_000] {
            let mut sketch = Sketch::new();
            for i in 0..n {
                sketch.insert(value_hash((0, 0), &i.to_string()));
            }
            let error = (sketch.estimate() as f64 - n as f64).abs() / n as f64;
            assert!(error < 0.2, "n={n} estimate={}", sketch.estimate());
        }
    }

    #[test]
    fn enforce_gives_the_fingerprint_of_rows_built_without_the_label() {
        let (detector, now) = detector(Mode::Enforce);
        let mut rows = as_delta(remote_write_rows(1000, true));
        learn(&detector, &now, &rows);
        detector.apply(TOKEN, &mut rows, &rw());

        let expected = remote_write_rows(1000, false);
        let fingerprints = |rows: &[KafkaMetricRow]| {
            let mut by_name: HashMap<String, HashSet<i64>> = HashMap::new();
            for row in rows {
                by_name
                    .entry(row.metric_name.clone())
                    .or_default()
                    .insert(row.series_fingerprint);
            }
            by_name
        };
        assert_eq!(fingerprints(&rows), fingerprints(&expected));
        assert_eq!(fingerprints(&rows)["latency"].len(), 4);
        assert!(rows
            .iter()
            .all(|row| !row.attributes.contains_key("user_id")));
        assert!(rows.iter().all(|row| {
            row.attributes
                .get(DROPPED_LABELS_ATTRIBUTE)
                .map(String::as_str)
                == Some(r#""[\"user_id\"]""#)
        }));
    }

    #[test]
    fn shadow_mode_flags_the_key_but_leaves_rows_unchanged() {
        let (detector, now) = detector(Mode::Shadow);
        let mut rows = as_delta(remote_write_rows(1000, true));
        let before: Vec<i64> = rows.iter().map(|r| r.series_fingerprint).collect();
        learn(&detector, &now, &rows);
        detector.apply(TOKEN, &mut rows, &rw());

        assert!(!rule_keys(&detector).is_empty());
        assert!(rows
            .iter()
            .all(|row| !row.attributes.contains_key(DROPPED_LABELS_ATTRIBUTE)));
        let after: Vec<i64> = rows.iter().map(|r| r.series_fingerprint).collect();
        assert_eq!(before, after);
        assert!(rows
            .iter()
            .all(|row| row.attributes.contains_key("user_id")));
    }

    #[test]
    fn a_rule_does_not_apply_to_another_token() {
        let (detector, now) = detector(Mode::Enforce);
        let rows = remote_write_rows(1000, true);
        learn(&detector, &now, &rows);

        let mut other = as_delta(remote_write_rows(10, true));
        detector.apply("phc_other", &mut other, &rw());
        assert!(other
            .iter()
            .all(|row| row.attributes.contains_key("user_id")));
    }

    #[test]
    fn a_rule_ends_when_the_key_stays_under_half_the_limit() {
        let (detector, now) = detector(Mode::Enforce);
        let rows = remote_write_rows(1000, true);
        learn(&detector, &now, &rows);
        assert!(!rule_keys(&detector).is_empty());

        let ttl = settings(Mode::Enforce).rule_ttl.as_secs() as i64;
        for step in 1..=8 {
            now.store(START + step * ttl / 4, Ordering::SeqCst);
            let rows = remote_write_rows(50, true);
            detector.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        }
        let mut rows = as_delta(remote_write_rows(50, true));
        detector.apply(TOKEN, &mut rows, &rw());
        assert!(rows
            .iter()
            .all(|row| row.attributes.contains_key("user_id")));
    }

    #[test]
    fn a_rule_stays_while_the_key_stays_over_half_the_limit() {
        let (detector, now) = detector(Mode::Enforce);
        let rows = remote_write_rows(1000, true);
        learn(&detector, &now, &rows);

        let ttl = settings(Mode::Enforce).rule_ttl.as_secs() as i64;
        for step in 1..=8 {
            now.store(START + step * ttl / 4, Ordering::SeqCst);
            let rows = remote_write_rows(150, true);
            detector.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        }
        let mut rows = as_delta(remote_write_rows(150, true));
        detector.apply(TOKEN, &mut rows, &rw());
        assert!(rows
            .iter()
            .all(|row| !row.attributes.contains_key("user_id")));
    }

    #[test]
    fn a_rule_lapses_when_the_key_series_start_to_repeat() {
        let (detector, now) = detector(Mode::Enforce);
        let rows = remote_write_rows(1000, true);
        learn(&detector, &now, &rows);

        let ttl = settings(Mode::Enforce).rule_ttl.as_secs() as i64;
        for step in 1..=8 {
            now.store(START + step * ttl / 4, Ordering::SeqCst);
            detector.observe(TOKEN, &rows, &[], &rw());
        }
        let mut rows = as_delta(remote_write_rows(150, true));
        detector.apply(TOKEN, &mut rows, &rw());
        assert!(rows
            .iter()
            .all(|row| row.attributes.contains_key("user_id")));
    }

    #[test]
    fn a_rule_does_not_drop_a_key_this_pod_protects() {
        let mut protecting = settings(Mode::Enforce);
        protecting.protected_keys.insert("user_id".to_string());
        let (detector, _) = detector_with(protecting);
        detector.merge_rule(rule_for("requests_total", Scope::Attribute, "user_id"));

        let mut rows = as_delta(named_rows(&["requests_total".to_string()], 3));
        detector.apply(TOKEN, &mut rows, &rw());
        assert!(rows
            .iter()
            .all(|row| row.attributes.contains_key("user_id")));
    }

    #[test]
    fn an_otlp_name_with_a_histogram_suffix_is_its_own_family() {
        let (detector, _) = detector(Mode::Enforce);
        detector.merge_rule(rule_for("queue", Scope::Attribute, "user_id"));

        let mut otlp = as_delta(named_rows(&["queue_count".to_string()], 3));
        detector.apply(TOKEN, &mut otlp, &Source::otlp());
        assert!(otlp
            .iter()
            .all(|row| row.attributes.contains_key("user_id")));

        let mut remote_write = as_delta(named_rows(&["queue_count".to_string()], 3));
        detector.apply(TOKEN, &mut remote_write, &rw());
        assert!(remote_write
            .iter()
            .all(|row| !row.attributes.contains_key("user_id")));
    }

    #[test]
    fn combined_rows_coalesce_into_one_point_per_second() {
        let (detector, now) = detector(Mode::Enforce);
        let mut rows = as_delta(remote_write_rows(1000, true));
        let timestamp = chrono::DateTime::from_timestamp_millis(1_800_000_000_500).unwrap();
        for row in rows.iter_mut() {
            row.timestamp = timestamp;
        }
        learn(&detector, &now, &rows);
        detector.apply(TOKEN, &mut rows, &rw());

        let totals: Vec<&KafkaMetricRow> = rows
            .iter()
            .filter(|row| row.metric_name == "requests_total")
            .collect();
        assert_eq!(totals.len(), 4);
        assert_eq!(totals.iter().map(|row| row.value).sum::<f64>(), 5000.0);
        let latency: Vec<&KafkaMetricRow> = rows
            .iter()
            .filter(|row| row.metric_name == "latency")
            .collect();
        assert_eq!(latency.len(), 4);
        assert_eq!(latency.iter().map(|row| row.count).sum::<i64>(), 2000);
        assert!(rows.iter().all(|row| row.timestamp == timestamp));
    }

    #[test]
    fn cumulative_series_are_left_unchanged() {
        let (detector, now) = detector(Mode::Enforce);
        let mut rows = remote_write_rows(1000, true);
        let before: Vec<i64> = rows.iter().map(|row| row.series_fingerprint).collect();
        learn(&detector, &now, &rows);
        detector.apply(TOKEN, &mut rows, &rw());

        let after: Vec<i64> = rows.iter().map(|row| row.series_fingerprint).collect();
        assert_eq!(after, before);
        assert!(!rule_keys(&detector).is_empty());
        assert!(rows.iter().all(|row| {
            row.attributes.contains_key("user_id")
                && !row.attributes.contains_key(DROPPED_LABELS_ATTRIBUTE)
        }));
    }

    #[test]
    fn a_sender_marker_is_removed_before_fingerprinting() {
        let (detector, _) = detector(Mode::Enforce);
        let mut rows = named_rows(&["jobs_total".to_string()], 3);
        let expected: Vec<i64> = rows.iter().map(|row| row.series_fingerprint).collect();
        let source = rw();
        for row in rows.iter_mut() {
            row.attributes.insert(
                DROPPED_LABELS_ATTRIBUTE.to_string(),
                r#""forged""#.to_string(),
            );
            row.resource_attributes.insert(
                DROPPED_LABELS_ATTRIBUTE.to_string(),
                r#""forged""#.to_string(),
            );
            row.series_fingerprint = compute_series_fingerprint(
                &row.metric_name,
                &row.metric_type,
                &row.service_name,
                &row.resource_attributes,
                &row.attributes,
            );
        }
        detector.strip_reserved(&mut rows, &source);

        assert!(rows.iter().all(|row| {
            !row.attributes.contains_key(DROPPED_LABELS_ATTRIBUTE)
                && !row
                    .resource_attributes
                    .contains_key(DROPPED_LABELS_ATTRIBUTE)
        }));
        let actual: Vec<i64> = rows.iter().map(|row| row.series_fingerprint).collect();
        assert_eq!(actual, expected);
    }

    #[test]
    fn a_sender_marker_on_an_old_classic_histogram_keeps_its_fingerprint() {
        let (detector, _) = detector(Mode::Enforce);
        let old = (Utc::now() - chrono::Duration::days(30)).timestamp_millis();
        let mut series = histogram_series(3, true);
        for ts in series.iter_mut() {
            ts.samples[0].timestamp = old;
        }
        let (rows, _) = write_timeseries_to_kafka_rows(series, &[]);
        let mut rows = fold_classic_histograms(rows, &[]);
        assert!(rows
            .iter()
            .all(|row| row.attributes.contains_key(ORIGINAL_TIMESTAMP_ATTRIBUTE)));
        let expected: Vec<i64> = rows.iter().map(|row| row.series_fingerprint).collect();
        for row in rows.iter_mut() {
            row.attributes.insert(
                DROPPED_LABELS_ATTRIBUTE.to_string(),
                r#""forged""#.to_string(),
            );
        }
        detector.strip_reserved(&mut rows, &rw());

        let actual: Vec<i64> = rows.iter().map(|row| row.series_fingerprint).collect();
        assert_eq!(actual, expected);
    }

    #[tokio::test]
    async fn a_pull_stops_at_the_rule_cap() {
        let members: Vec<(String, f64)> = (0..MAX_RULES + PULL_PAGE_SIZE)
            .map(|i| (format!("unreadable-{i}"), (START + 60) as f64))
            .collect();
        let client =
            MockRedisClient::new().zrangebyscore_withscores_ret(&bucket_key(START + 60), members);
        let (detector, _) = detector(Mode::Enforce);
        detector.pull_rules(&client).await.unwrap();

        let reads = client
            .get_calls()
            .iter()
            .filter(|call| call.op == "zrangebyscore_limit_withscores")
            .count();
        assert_eq!(reads, MAX_RULES / PULL_PAGE_SIZE);
    }

    #[tokio::test]
    async fn a_rule_found_on_one_pod_is_enforced_on_another() {
        let (tx, mut rx) = mpsc::channel(WRITER_CHANNEL_CAPACITY);
        let now = Arc::new(AtomicI64::new(START));
        let clock_now = Arc::clone(&now);
        let pod_a = LabelCardinality::build(
            settings(Mode::Enforce),
            Some(tx),
            Arc::new(move || clock_now.load(Ordering::SeqCst)),
        );
        let rows = remote_write_rows(1000, true);
        pod_a.note_new_series(TOKEN, &rows, &all_rows_new(&rows), &rw());
        pod_a.observe(TOKEN, &rows, &all_rows_new(&rows), &rw());
        end_window(&pod_a, &now);

        let mut pushed = Vec::new();
        while let Ok(rule) = rx.try_recv() {
            pushed.push(rule);
        }
        let mut client = MockRedisClient::new();
        for command in rule_commands(&pushed, 0) {
            if let PipelineCommand::ZAddGt { key, members } = command {
                client = client.zrangebyscore_withscores_ret(
                    &key,
                    members
                        .into_iter()
                        .map(|(score, member)| (member, score as f64))
                        .collect(),
                );
            }
        }

        let (pod_b, pod_b_now) = detector(Mode::Enforce);
        pod_b_now.store(now.load(Ordering::SeqCst), Ordering::SeqCst);
        assert_eq!(pod_b.pull_rules(&client).await.unwrap(), 2);
        let expiry = now.load(Ordering::SeqCst) + settings(Mode::Enforce).rule_ttl.as_secs() as i64;
        assert!(pod_b
            .rules
            .iter()
            .all(|rules| rules.iter().all(|rule| rule.expires_at == expiry)));
        let mut rows = as_delta(remote_write_rows(10, true));
        pod_b.apply(TOKEN, &mut rows, &rw());
        assert!(rows
            .iter()
            .all(|row| !row.attributes.contains_key("user_id")));
    }
}
