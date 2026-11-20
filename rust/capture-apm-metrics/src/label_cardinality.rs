//! Finds label keys that make a metric explode into many series. The README
//! section "High cardinality label drop" describes the detection stages.

use std::collections::{HashMap, HashSet};
use std::hash::Hasher;
use std::str::FromStr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

use capture_logs::log_record::ORIGINAL_TIMESTAMP_ATTRIBUTE;
use capture_logs::metric_record::KafkaMetricRow;
use chrono::Utc;
use dashmap::DashMap;
use metrics::{counter, gauge};
use prometheus_rw_proto::prometheus::v1::{metric_metadata::MetricType, MetricMetadata};
use siphasher::sip::SipHasher13;
use tracing::warn;

use crate::series_label_gate::Clock;

const PRUNE_INTERVAL: Duration = Duration::from_secs(300);
const MEASURE_CHUNK_ROWS: usize = 1024;

const HISTOGRAM_SUFFIXES: [&str; 3] = ["_bucket", "_count", "_sum"];
const SERVICE_NAME_RESOURCE: &str = "service.name";
const MAX_NAME_CHARS: usize = 100;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Off,
    Shadow,
}

impl FromStr for Mode {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().as_str() {
            "off" => Ok(Mode::Off),
            "shadow" => Ok(Mode::Shadow),
            other => Err(format!("unknown label cardinality mode {other:?}")),
        }
    }
}

impl Mode {
    fn as_str(self) -> &'static str {
        match self {
            Mode::Off => "off",
            Mode::Shadow => "shadow",
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Scope {
    Attribute,
    Resource,
}

#[derive(Debug, Clone)]
pub struct Settings {
    pub mode: Mode,
    pub window: Duration,
    pub value_limit: u64,
    pub min_new_share: f64,
    pub candidate_min_new_series: u32,
    pub max_candidates: usize,
    pub max_candidates_per_token: usize,
    pub max_keys_per_candidate: usize,
    pub max_tracked_metrics: usize,
    pub max_tracked_metrics_per_token: usize,
    pub protected_keys: HashSet<String>,
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
    keys: HashMap<(Scope, u64), KeySketch>,
    flagged: Vec<(Scope, u64)>,
}

struct NewSeriesCount {
    window: i64,
    count: u32,
    token_hash: u64,
}

struct RowHashes<'a> {
    new_series: bool,
    values: Vec<(Scope, u64, u64, &'a str)>,
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
    protected: HashSet<(Scope, u64)>,
}

impl LabelCardinality {
    pub fn new(settings: Settings) -> Arc<Self> {
        Arc::new(Self::build(settings, Arc::new(unix_now)))
    }

    fn build(settings: Settings, clock: Clock) -> Self {
        let mut protected: HashSet<(Scope, u64)> = settings
            .protected_keys
            .iter()
            .flat_map(|key| {
                let hash = key_hash(key);
                [(Scope::Attribute, hash), (Scope::Resource, hash)]
            })
            .collect();
        protected.insert((Scope::Attribute, key_hash(ORIGINAL_TIMESTAMP_ATTRIBUTE)));
        protected.insert((Scope::Resource, key_hash(SERVICE_NAME_RESOURCE)));
        Self {
            protected,
            settings,
            clock,
            new_series: DashMap::new(),
            tracked_count: AtomicUsize::new(0),
            tracked_per_token: DashMap::new(),
            candidates: DashMap::new(),
            candidate_count: AtomicUsize::new(0),
            candidates_per_token: DashMap::new(),
        }
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
        if self.settings.mode == Mode::Off || new_rows.is_empty() {
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
            keys: HashMap::new(),
            flagged: Vec::new(),
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
        if self.settings.mode == Mode::Off || self.candidates.is_empty() {
            return;
        }
        let now = (self.clock)();
        let window = self.window_index(now);

        let mut keys_by_name: HashMap<&str, u64> = HashMap::new();
        let mut groups: HashMap<u64, Vec<usize>> = HashMap::new();
        for (index, row) in rows.iter().enumerate() {
            let metric_key = *keys_by_name
                .entry(row.metric_name.as_str())
                .or_insert_with(|| metric_key(token, source.family(&row.metric_name)));
            if self.candidates.contains_key(&metric_key) {
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
            window,
        );
    }

    fn measure(
        &self,
        rows: &[KafkaMetricRow],
        new_series: &[bool],
        groups: HashMap<u64, Vec<usize>>,
        source: &Source,
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
                self.roll(&mut candidate, window);
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
                if !self.protected.contains(&(scope, key)) {
                    values.push((scope, key, value_hash(value), name.as_str()));
                }
            }
        }
        RowHashes { new_series, values }
    }

    fn feed(&self, candidate: &mut Candidate, row: RowHashes) {
        let max_keys = self.settings.max_keys_per_candidate;
        let new_rows = u64::from(row.new_series);
        let mut keys_full = 0u64;
        for (scope, key, hash, name) in row.values {
            if let Some(entry) = candidate.keys.get_mut(&(scope, key)) {
                entry.sketch.insert(hash);
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
            candidate.keys.insert(
                (scope, key),
                KeySketch {
                    sketch,
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

    /// Every series is new at the start of a window, so only a complete window is judged.
    fn roll(&self, candidate: &mut Candidate, window: i64) {
        if candidate.window == window {
            return;
        }
        self.evaluate(candidate);
        candidate.window = window;
        candidate.keys.clear();
    }

    fn evaluate(&self, candidate: &mut Candidate) {
        candidate.flagged.clear();
        for ((scope, key), entry) in &candidate.keys {
            let distinct = entry.sketch.estimate();
            if distinct < self.settings.value_limit
                || (entry.new_rows as f64) < self.settings.min_new_share * entry.rows as f64
            {
                continue;
            }
            candidate.flagged.push((*scope, *key));
            warn!(
                token = %candidate.token,
                metric = %candidate.family,
                scope = ?scope,
                key = %entry.name,
                distinct_values = distinct,
                rows = entry.rows,
                new_series_rows = entry.new_rows,
                mode = self.settings.mode.as_str(),
                "High cardinality metric label flagged"
            );
            counter!(
                "capture_metrics_label_cardinality_keys_flagged",
                "mode" => self.settings.mode.as_str()
            )
            .increment(1);
        }
    }

    fn prune(&self, now: i64) {
        let window = self.window_index(now);
        self.candidates.retain(|_, candidate| {
            let candidate = candidate.get_mut().unwrap_or_else(PoisonError::into_inner);
            self.roll(candidate, window);
            if candidate.qualified_window >= window - 1 {
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
        gauge!("capture_metrics_label_cardinality_candidates")
            .set(self.candidate_count.load(Ordering::Acquire) as f64);
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

fn value_hash(value: &str) -> u64 {
    let mut hasher = SipHasher13::new();
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

fn unix_now() -> i64 {
    Utc::now().timestamp()
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::AtomicI64;

    use capture_logs::endpoints::prometheus::write_timeseries_to_kafka_rows;
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
            min_new_share: 0.5,
            candidate_min_new_series: 10,
            max_candidates: 100,
            max_candidates_per_token: 100,
            max_keys_per_candidate: 32,
            max_tracked_metrics: 1000,
            max_tracked_metrics_per_token: 1000,
            protected_keys: ["le".to_string(), "quantile".to_string()].into(),
        }
    }

    fn detector(mode: Mode) -> (LabelCardinality, Arc<AtomicI64>) {
        detector_with(settings(mode))
    }

    fn detector_with(settings: Settings) -> (LabelCardinality, Arc<AtomicI64>) {
        let now = Arc::new(AtomicI64::new(START));
        let clock_now = Arc::clone(&now);
        let detector =
            LabelCardinality::build(settings, Arc::new(move || clock_now.load(Ordering::SeqCst)));
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

    fn all_rows_new(rows: &[KafkaMetricRow]) -> Vec<usize> {
        (0..rows.len()).collect()
    }

    fn end_window(detector: &LabelCardinality, now: &AtomicI64) {
        let next = now.load(Ordering::SeqCst) + settings(Mode::Shadow).window.as_secs() as i64;
        now.store(next, Ordering::SeqCst);
        detector.prune(next);
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
        let mut flagged = HashSet::new();
        for entry in detector.candidates.iter() {
            let candidate = entry.value().lock().unwrap();
            for (scope, key) in &candidate.flagged {
                flagged.insert((*entry.key(), *scope, *key));
            }
        }
        flagged
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
    fn sketch_estimate_stays_within_a_few_standard_errors() {
        for n in [100u64, 1_000, 10_000, 100_000] {
            let mut sketch = Sketch::new();
            for i in 0..n {
                sketch.insert(value_hash(&i.to_string()));
            }
            let error = (sketch.estimate() as f64 - n as f64).abs() / n as f64;
            assert!(error < 0.2, "n={n} estimate={}", sketch.estimate());
        }
    }
}
