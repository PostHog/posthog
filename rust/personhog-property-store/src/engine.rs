use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use bytes::Bytes;
use metrics::Label;
use slatedb::compactor::{
    CompactionScheduler, CompactionSchedulerSupplier, CompactionSpec, CompactionStatus,
    CompactorStateView, SizeTieredCompactionSchedulerSupplier, SourceId,
};
use slatedb::config::{CompactionWorkerOptions, CompactorOptions, Settings};
use slatedb::db_cache::foyer::{FoyerCache, FoyerCacheOptions};
use slatedb::db_cache::{DbCache, SplitCache};
use slatedb::{BloomFilterPolicy, FilterPolicy, MergeOperator, MergeOperatorError};
use slatedb_common::metrics::{CounterFn, GaugeFn, HistogramFn, MetricsRecorder, UpDownCounterFn};

use crate::encoding::version_of;
use crate::PropertyStoreConfig;

/// Keeps the higher person version, so writes need no read and converge in any order.
pub(crate) struct KeepNewest;

impl MergeOperator for KeepNewest {
    fn merge(
        &self,
        _key: &Bytes,
        existing: Option<Bytes>,
        value: Bytes,
    ) -> Result<Bytes, MergeOperatorError> {
        let Some(existing) = existing else {
            return Ok(value);
        };
        match (version_of(&existing), version_of(&value)) {
            (Some(held), Some(new)) if new > held => Ok(value),
            (Some(_), Some(_)) => Ok(existing),
            _ => Err(MergeOperatorError::Callback {
                message: "malformed stored properties".to_string(),
            }),
        }
    }
}

pub(crate) fn shared_cache(config: &PropertyStoreConfig) -> Arc<dyn DbCache> {
    let cache = |capacity: u64| -> Arc<dyn DbCache> {
        Arc::new(FoyerCache::new_with_opts(FoyerCacheOptions {
            max_capacity: capacity,
            ..Default::default()
        }))
    };
    Arc::new(
        SplitCache::new()
            .with_block_cache(
                (config.block_cache_bytes > 0).then(|| cache(config.block_cache_bytes)),
            )
            .with_meta_cache(Some(cache(config.meta_cache_bytes)))
            .build(),
    )
}

/// Fencing does not wait on this poll: a fenced writer's conditional log write fails.
const WRITER_MANIFEST_POLL: Duration = Duration::from_secs(10);

const COMPACTION_FETCH_BYTES: usize = 256 * 1024;

/// Two, so routine L0 compaction keeps draining flushes during a full compaction.
const SHARD_COMPACTIONS: usize = 2;

/// The writer and its compactor must build SSTs with the same filters.
pub(crate) fn filter_policies(config: &PropertyStoreConfig) -> Vec<Arc<dyn FilterPolicy>> {
    vec![Arc::new(BloomFilterPolicy::new(config.filter_bits_per_key))]
}

pub(crate) fn settings(config: &PropertyStoreConfig) -> Settings {
    Settings {
        l0_sst_size_bytes: config.l0_sst_bytes,
        max_unflushed_bytes: config.max_unflushed_bytes,
        min_filter_keys: config.min_filter_keys,
        manifest_poll_interval: WRITER_MANIFEST_POLL,
        compression_codec: config.compression.codec(),
        compactor_options: None,
        ..Settings::default()
    }
}

pub(crate) fn compactor_options(config: &PropertyStoreConfig) -> CompactorOptions {
    CompactorOptions {
        max_concurrent_compactions: SHARD_COMPACTIONS,
        worker: Some(CompactionWorkerOptions {
            max_concurrent_compactions: SHARD_COMPACTIONS,
            max_fetch_tasks: 1,
            bytes_to_fetch: COMPACTION_FETCH_BYTES,
            min_filter_keys: config.min_filter_keys,
            ..CompactionWorkerOptions::default()
        }),
        ..CompactorOptions::default()
    }
}

/// SlateDB does not check an admin submission against active compactions, so a full compaction
/// beside a routine merge of the same runs would drop that merge's rows at commit.
pub(crate) struct ExclusiveSubmissions;

impl CompactionSchedulerSupplier for ExclusiveSubmissions {
    fn compaction_scheduler(
        &self,
        options: &CompactorOptions,
    ) -> Box<dyn CompactionScheduler + Send + Sync> {
        Box::new(Exclusive(
            SizeTieredCompactionSchedulerSupplier::new().compaction_scheduler(options),
        ))
    }
}

struct Exclusive(Box<dyn CompactionScheduler + Send + Sync>);

impl CompactionScheduler for Exclusive {
    fn propose(&self, state: &CompactorStateView) -> Vec<CompactionSpec> {
        self.0.propose(state)
    }

    fn validate(
        &self,
        state: &CompactorStateView,
        spec: &CompactionSpec,
    ) -> Result<(), slatedb::Error> {
        self.0.validate(state, spec)?;
        let claimed = state
            .compactions()
            .into_iter()
            .flat_map(|compactions| compactions.recent_compactions())
            .filter(|c| {
                matches!(
                    c.status(),
                    CompactionStatus::Scheduled
                        | CompactionStatus::Running
                        | CompactionStatus::Compacted
                )
            })
            .map(|c| c.spec());
        if conflicts(claimed, spec) {
            return Err(slatedb::Error::invalid(
                "the compaction overlaps an active one".to_string(),
            ));
        }
        Ok(())
    }
}

/// A spec matches itself when it is validated again at commit, so an equal spec is not a conflict.
fn conflicts<'a>(
    mut claimed: impl Iterator<Item = &'a CompactionSpec>,
    spec: &CompactionSpec,
) -> bool {
    let touched = |s: &CompactionSpec| -> Vec<SourceId> {
        s.sources()
            .iter()
            .copied()
            .chain(s.destination().map(SourceId::SortedRun))
            .collect()
    };
    let mine = touched(spec);
    claimed.any(|other| other != spec && touched(other).iter().any(|id| mine.contains(id)))
}

/// Publishes SlateDB's metrics without a shard label; gauges sum or max across open databases.
pub(crate) struct ShardMetrics {
    instance: u64,
    retired: Arc<AtomicBool>,
}

static NEXT_INSTANCE: AtomicU64 = AtomicU64::new(0);

impl ShardMetrics {
    pub(crate) fn new() -> Self {
        Self {
            instance: NEXT_INSTANCE.fetch_add(1, Ordering::Relaxed),
            retired: Arc::new(AtomicBool::new(false)),
        }
    }

    pub(crate) fn recorder(&self) -> Arc<dyn MetricsRecorder> {
        Arc::new(MetricsBridge {
            instance: self.instance,
            retired: Arc::clone(&self.retired),
        })
    }

    pub(crate) fn retire(&self) {
        readings().retire(self.instance, &self.retired);
    }
}

struct MetricsBridge {
    instance: u64,
    retired: Arc<AtomicBool>,
}

/// Unique per database open, so keeping them would add series on every open.
const DROPPED_LABELS: &[&str] = &["worker_id"];

fn series(name: &str, labels: &[(&str, &str)]) -> Series {
    let name = format!(
        "slatedb_{}",
        name.trim_start_matches("slatedb.").replace('.', "_")
    );
    let combine = if ["epoch", "timestamp", "heartbeat", "l0_sst_count"]
        .iter()
        .any(|part| name.contains(part))
    {
        Combine::Max
    } else {
        Combine::Sum
    };
    Series {
        name,
        labels: labels
            .iter()
            .filter(|(k, _)| !DROPPED_LABELS.contains(k))
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect(),
        combine,
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum Combine {
    Sum,
    Max,
}

#[derive(Clone, PartialEq, Eq, Hash)]
struct Series {
    name: String,
    labels: Vec<(String, String)>,
    combine: Combine,
}

impl Series {
    fn labels(&self) -> Vec<Label> {
        self.labels
            .iter()
            .map(|(k, v)| Label::new(k.clone(), v.clone()))
            .collect()
    }

    fn publish(&self, value: i64) {
        metrics::gauge!(self.name.clone(), self.labels()).set(value as f64);
    }

    fn combine(&self, readings: &HashMap<u64, i64>) -> i64 {
        match self.combine {
            Combine::Sum => readings.values().sum(),
            Combine::Max => readings.values().copied().max().unwrap_or(0),
        }
    }
}

#[derive(Default)]
struct Readings {
    values: Mutex<HashMap<Series, HashMap<u64, i64>>>,
}

impl Readings {
    /// Publishing under the lock keeps retired readings out and values in order.
    fn update(
        &self,
        series: &Series,
        instance: u64,
        retired: &AtomicBool,
        update: impl FnOnce(&mut i64),
    ) -> Option<i64> {
        let mut values = self.values.lock().expect("gauge readings lock poisoned");
        if retired.load(Ordering::SeqCst) {
            return None;
        }
        let readings = values.entry(series.clone()).or_default();
        update(readings.entry(instance).or_default());
        let combined = series.combine(readings);
        series.publish(combined);
        Some(combined)
    }

    fn retire(&self, instance: u64, retired: &AtomicBool) -> Vec<(Series, i64)> {
        let mut values = self.values.lock().expect("gauge readings lock poisoned");
        retired.store(true, Ordering::SeqCst);
        values
            .iter_mut()
            .filter_map(|(series, readings)| {
                readings.remove(&instance)?;
                let combined = series.combine(readings);
                series.publish(combined);
                Some((series.clone(), combined))
            })
            .collect()
    }
}

static READINGS: OnceLock<Readings> = OnceLock::new();

fn readings() -> &'static Readings {
    READINGS.get_or_init(Readings::default)
}

struct Counter(metrics::Counter);
impl CounterFn for Counter {
    fn increment(&self, value: u64) {
        self.0.increment(value);
    }
}

struct ShardGauge {
    series: Series,
    instance: u64,
    retired: Arc<AtomicBool>,
}

impl ShardGauge {
    fn apply(&self, update: impl FnOnce(&mut i64)) {
        readings().update(&self.series, self.instance, &self.retired, update);
    }
}

impl GaugeFn for ShardGauge {
    fn set(&self, value: i64) {
        self.apply(|held| *held = value);
    }
}

impl UpDownCounterFn for ShardGauge {
    fn increment(&self, value: i64) {
        self.apply(|held| *held += value);
    }
}

struct Histogram(metrics::Histogram);
impl HistogramFn for Histogram {
    fn record(&self, value: f64) {
        self.0.record(value);
    }
}

impl MetricsRecorder for MetricsBridge {
    fn register_counter(
        &self,
        name: &str,
        _description: &str,
        labels: &[(&str, &str)],
    ) -> Arc<dyn CounterFn> {
        let series = series(name, labels);
        Arc::new(Counter(metrics::counter!(
            series.name.clone(),
            series.labels()
        )))
    }

    fn register_gauge(
        &self,
        name: &str,
        _description: &str,
        labels: &[(&str, &str)],
    ) -> Arc<dyn GaugeFn> {
        Arc::new(ShardGauge {
            series: series(name, labels),
            instance: self.instance,
            retired: Arc::clone(&self.retired),
        })
    }

    fn register_up_down_counter(
        &self,
        name: &str,
        _description: &str,
        labels: &[(&str, &str)],
    ) -> Arc<dyn UpDownCounterFn> {
        Arc::new(ShardGauge {
            series: series(name, labels),
            instance: self.instance,
            retired: Arc::clone(&self.retired),
        })
    }

    fn register_histogram(
        &self,
        name: &str,
        _description: &str,
        labels: &[(&str, &str)],
        _boundaries: &[f64],
    ) -> Arc<dyn HistogramFn> {
        let series = series(name, labels);
        Arc::new(Histogram(metrics::histogram!(
            series.name.clone(),
            series.labels()
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::encoding::{encode_value, StoredProperties};
    use rstest::rstest;

    fn value(version: i64) -> Bytes {
        encode_value(&StoredProperties {
            version,
            deleted: false,
            created_at: 0,
            properties: Bytes::from(version.to_string()),
        })
    }

    #[test]
    fn a_retired_database_leaves_the_gauge_readings_for_good() {
        let readings = Readings::default();
        let (first, second) = (AtomicBool::new(false), AtomicBool::new(false));
        let mem = series("db.total_mem_size_bytes", &[]);
        assert_eq!(readings.update(&mem, 1, &first, |held| *held = 3), Some(3));
        assert_eq!(readings.update(&mem, 2, &second, |held| *held = 4), Some(7));
        let after: Vec<i64> = readings
            .retire(1, &first)
            .into_iter()
            .map(|(_, v)| v)
            .collect();
        assert_eq!(after, vec![4]);
        assert_eq!(readings.update(&mem, 1, &first, |held| *held = 9), None);
        assert_eq!(
            readings.update(&mem, 2, &second, |held| *held += 1),
            Some(5)
        );
    }

    #[test]
    fn points_in_time_take_the_maximum_and_open_ids_are_dropped() {
        let readings = Readings::default();
        let (first, second) = (AtomicBool::new(false), AtomicBool::new(false));
        let epoch = series("compactor.epoch", &[("worker_id", "01ABC")]);
        assert!(epoch.labels.is_empty());
        readings.update(&epoch, 1, &first, |held| *held = 3);
        assert_eq!(
            readings.update(&epoch, 2, &second, |held| *held = 5),
            Some(5)
        );
    }

    #[test]
    fn the_higher_version_wins_in_either_order() {
        let key = Bytes::new();
        for (first, second) in [(3, 5), (5, 3)] {
            let merged = KeepNewest
                .merge(&key, Some(value(first)), value(second))
                .unwrap();
            assert_eq!(version_of(&merged), Some(5));
        }
        assert_eq!(KeepNewest.merge(&key, None, value(2)).unwrap(), value(2));
    }

    fn runs(sources: &[u32], destination: u32) -> CompactionSpec {
        CompactionSpec::new(
            sources.iter().map(|&id| SourceId::SortedRun(id)).collect(),
            destination,
        )
    }

    #[rstest]
    #[case::disjoint_runs(runs(&[4, 3], 3), false)]
    #[case::a_shared_run(runs(&[3, 2, 1, 0], 0), true)]
    #[case::merged_into_a_run_of_mine(runs(&[2, 1], 1), true)]
    #[case::the_same_spec_validated_again(runs(&[1, 0], 0), false)]
    fn a_submission_conflicts_with_an_active_compaction_it_shares_a_run_with(
        #[case] active: CompactionSpec,
        #[case] conflicting: bool,
    ) {
        let full_compaction = runs(&[1, 0], 0);

        assert_eq!(
            conflicts([&active].into_iter(), &full_compaction),
            conflicting
        );
    }
}
