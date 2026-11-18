use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use futures::{stream, StreamExt};
use redis::cluster::ClusterClientBuilder;
use redis::cluster_async::ClusterConnection;
use tracing::warn;
use uuid::Uuid;

use crate::record::KafkaBillingUsageRecord;

const HOURLY_TTL_SECONDS: u64 = 25 * 60 * 60;
const DAILY_TTL_SECONDS: u64 = 31 * 24 * 60 * 60;
const DEFAULT_FLUSH_CONCURRENCY: usize = 16;
const DEFAULT_MAX_PENDING_ENTRIES: usize = 250_000;
const REDIS_CONNECTION_TIMEOUT: Duration = Duration::from_secs(5);
const REDIS_RESPONSE_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_PAST_TIMESTAMP: ChronoDuration = ChronoDuration::days(7);
const MAX_FUTURE_TIMESTAMP: ChronoDuration = ChronoDuration::hours(24);

#[derive(Clone, Copy, Debug)]
pub struct CounterConfig {
    pub flush_concurrency: usize,
}

impl Default for CounterConfig {
    fn default() -> Self {
        Self {
            flush_concurrency: DEFAULT_FLUSH_CONCURRENCY,
        }
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum CounterScope {
    Team(i64),
    Organization(Uuid),
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Bucket {
    Hour(i64),
    Day(i64),
}

impl Bucket {
    fn from_timestamp(timestamp: DateTime<Utc>) -> [Self; 2] {
        let seconds = timestamp.timestamp();
        [
            Self::Hour(seconds.div_euclid(60 * 60)),
            Self::Day(seconds.div_euclid(24 * 60 * 60)),
        ]
    }

    fn suffix(self) -> &'static str {
        match self {
            Self::Hour(_) => "h",
            Self::Day(_) => "d",
        }
    }

    fn index(self) -> i64 {
        match self {
            Self::Hour(index) | Self::Day(index) => index,
        }
    }

    fn ttl_seconds(self) -> u64 {
        match self {
            Self::Hour(_) => HOURLY_TTL_SECONDS,
            Self::Day(_) => DAILY_TTL_SECONDS,
        }
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct CounterEntry {
    bucket: Bucket,
    field: String,
}

#[derive(Debug, PartialEq, Eq)]
pub enum CounterAddError {
    TimestampOutOfRange,
    Overflow,
    Capacity,
}

impl CounterAddError {
    pub fn reason(&self) -> &'static str {
        match self {
            Self::TimestampOutOfRange => "timestamp_out_of_range",
            Self::Overflow => "overflow",
            Self::Capacity => "capacity",
        }
    }
}

#[derive(Clone, Debug)]
pub struct ScopeCounters {
    scope: CounterScope,
    entries: HashMap<CounterEntry, i64>,
}

/// A process-local, lossy aggregation of Kafka-confirmed usage records.
pub struct CounterAccumulator {
    pending: Mutex<PendingCounters>,
    max_entries: usize,
}

#[derive(Default)]
struct PendingCounters {
    scopes: HashMap<CounterScope, HashMap<CounterEntry, i64>>,
    entries: usize,
}

impl Default for CounterAccumulator {
    fn default() -> Self {
        Self::new(DEFAULT_MAX_PENDING_ENTRIES)
    }
}

impl CounterAccumulator {
    pub fn new(max_entries: usize) -> Self {
        Self {
            pending: Mutex::new(PendingCounters::default()),
            max_entries,
        }
    }

    pub fn add_record(&self, record: &KafkaBillingUsageRecord) -> Result<(), CounterAddError> {
        self.add(
            record.team_id,
            record.organization_id,
            &record.usage_key,
            &record.unit,
            record.quantity,
            record.usage_timestamp,
        )
    }

    pub fn add(
        &self,
        team_id: i64,
        organization_id: Uuid,
        usage_key: &str,
        unit: &str,
        quantity: i64,
        timestamp: DateTime<Utc>,
    ) -> Result<(), CounterAddError> {
        let now = Utc::now();
        if timestamp < now - MAX_PAST_TIMESTAMP || timestamp > now + MAX_FUTURE_TIMESTAMP {
            return Err(CounterAddError::TimestampOutOfRange);
        }
        let field = usage_field(usage_key, unit);
        let buckets = Bucket::from_timestamp(timestamp);
        let scopes = [
            CounterScope::Team(team_id),
            CounterScope::Organization(organization_id),
        ];
        let mut pending = self.pending.lock().expect("usage counter mutex poisoned");
        let new_entries = scopes
            .iter()
            .flat_map(|scope| {
                buckets.iter().filter(|bucket| {
                    !pending.scopes.get(scope).is_some_and(|entries| {
                        entries.contains_key(&CounterEntry {
                            bucket: **bucket,
                            field: field.clone(),
                        })
                    })
                })
            })
            .count();
        if pending.entries.saturating_add(new_entries) > self.max_entries {
            return Err(CounterAddError::Capacity);
        }
        let mut rejection = None;
        for scope in scopes {
            let entries = pending.scopes.entry(scope).or_default();
            let before = entries.len();
            if let Err(error) = add_to_scope(entries, buckets, &field, quantity) {
                rejection = Some(error);
            }
            pending.entries += entries.len() - before;
        }
        rejection.map_or(Ok(()), Err)
    }

    pub fn drain(&self) -> Vec<ScopeCounters> {
        let mut pending = self.pending.lock().expect("usage counter mutex poisoned");
        pending.entries = 0;
        std::mem::take(&mut pending.scopes)
            .into_iter()
            .map(|(scope, entries)| ScopeCounters { scope, entries })
            .collect()
    }

    fn counts(&self) -> (usize, usize) {
        let pending = self.pending.lock().expect("usage counter mutex poisoned");
        (pending.scopes.len(), pending.entries)
    }

    pub fn scope_count_for_records(records: &[KafkaBillingUsageRecord]) -> usize {
        records
            .iter()
            .flat_map(|record| {
                [
                    CounterScope::Team(record.team_id),
                    CounterScope::Organization(record.organization_id),
                ]
            })
            .collect::<std::collections::HashSet<_>>()
            .len()
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct FlushOutcome {
    pub commands: usize,
    /// Lost because a scope's transaction failed.
    pub dropped: usize,
    pub failed_scopes: usize,
}

#[async_trait]
pub trait CounterStore: Send + Sync {
    async fn flush_scope(&self, counters: &ScopeCounters) -> Result<usize, redis::RedisError>;
}

/// Cluster-aware store. Each scope is one transaction, and every key in it has the same hash tag.
pub struct RedisCounterStore {
    connection: ClusterConnection,
}

impl RedisCounterStore {
    pub async fn connect(url: &str, _config: CounterConfig) -> Result<Self, redis::RedisError> {
        let client = ClusterClientBuilder::new([url])
            .connection_timeout(REDIS_CONNECTION_TIMEOUT)
            .response_timeout(REDIS_RESPONSE_TIMEOUT)
            .build()?;
        Ok(Self {
            connection: client.get_async_connection().await?,
        })
    }
}

#[async_trait]
impl CounterStore for RedisCounterStore {
    async fn flush_scope(&self, counters: &ScopeCounters) -> Result<usize, redis::RedisError> {
        let entry_count = counters.entries.len();
        let mut pipeline = redis::pipe();
        pipeline.atomic();
        for (entry, quantity) in &counters.entries {
            let key = counter_key(&counters.scope, entry.bucket);
            pipeline
                .cmd("HINCRBY")
                .arg(&key)
                .arg(&entry.field)
                .arg(*quantity)
                .ignore()
                .cmd("EXPIRE")
                .arg(key)
                .arg(entry.bucket.ttl_seconds())
                .arg("NX")
                .ignore();
        }
        let mut connection = self.connection.clone();
        pipeline.query_async::<()>(&mut connection).await?;
        Ok(entry_count * 2)
    }
}

pub fn counter_key(scope: &CounterScope, bucket: Bucket) -> String {
    let scope = match scope {
        CounterScope::Team(team_id) => format!("team={team_id}"),
        CounterScope::Organization(organization_id) => format!("org={organization_id}"),
    };
    format!(
        "usage:v1:{{{scope}}}:{}:{}",
        bucket.suffix(),
        bucket.index()
    )
}

/// Both buckets of one scope move together, so a rejected series leaves the scope untouched.
fn add_to_scope(
    entries: &mut HashMap<CounterEntry, i64>,
    buckets: [Bucket; 2],
    field: &str,
    quantity: i64,
) -> Result<(), CounterAddError> {
    let mut totals = [0_i64; 2];
    for (bucket, total) in buckets.into_iter().zip(&mut totals) {
        let entry = CounterEntry {
            bucket,
            field: field.to_string(),
        };
        *total = match entries.get(&entry) {
            Some(current) => current
                .checked_add(quantity)
                .ok_or(CounterAddError::Overflow)?,
            None => quantity,
        };
    }
    for (bucket, total) in buckets.into_iter().zip(totals) {
        entries.insert(
            CounterEntry {
                bucket,
                field: field.to_string(),
            },
            total,
        );
    }
    Ok(())
}

fn usage_field(usage_key: &str, unit: &str) -> String {
    // The length prefix keeps the pair unambiguous even if a producer uses a delimiter in a name.
    format!("{}:{usage_key}{unit}", usage_key.len())
}

pub async fn flush(store: Arc<dyn CounterStore>, counters: Vec<ScopeCounters>) -> FlushOutcome {
    flush_with_concurrency(store, counters, DEFAULT_FLUSH_CONCURRENCY).await
}

async fn flush_with_concurrency(
    store: Arc<dyn CounterStore>,
    counters: Vec<ScopeCounters>,
    flush_concurrency: usize,
) -> FlushOutcome {
    let results = stream::iter(counters)
        .map(|counters| {
            let store = Arc::clone(&store);
            async move {
                let entries = counters.entries.len();
                match store.flush_scope(&counters).await {
                    Ok(commands) => FlushOutcome {
                        commands,
                        ..FlushOutcome::default()
                    },
                    Err(error) => {
                        warn!(%error, dropped_deltas = entries, "usage counter write outcome is unknown");
                        FlushOutcome {
                            dropped: entries,
                            failed_scopes: 1,
                            ..FlushOutcome::default()
                        }
                    }
                }
            }
        })
        .buffer_unordered(flush_concurrency)
        .collect::<Vec<_>>()
        .await;
    results
        .into_iter()
        .fold(FlushOutcome::default(), |mut total, next| {
            total.commands += next.commands;
            total.dropped += next.dropped;
            total.failed_scopes += next.failed_scopes;
            total
        })
}

pub fn spawn_flush_task(
    accumulator: Arc<CounterAccumulator>,
    redis_url: String,
    interval: Duration,
    config: CounterConfig,
) {
    tokio::spawn(async move {
        // Publish the series before the first connect, so a flush loop that dies reads as
        // disconnected rather than as a projection nobody enabled.
        metrics::gauge!("usage_ingestion_redis_counter_connected").set(0.0);
        let mut ticker = tokio::time::interval(interval);
        let mut store: Option<Arc<dyn CounterStore>> = None;
        loop {
            ticker.tick().await;
            flush_tick(&accumulator, &redis_url, config, &mut store).await;
        }
    });
}

async fn flush_tick(
    accumulator: &CounterAccumulator,
    redis_url: &str,
    config: CounterConfig,
    store: &mut Option<Arc<dyn CounterStore>>,
) {
    let started = Instant::now();
    if store.is_none() {
        match RedisCounterStore::connect(redis_url, config).await {
            Ok(redis_store) => {
                *store = Some(Arc::new(redis_store));
                metrics::gauge!("usage_ingestion_redis_counter_connected").set(1.0);
            }
            Err(error) => {
                let (retained_scopes, retained_deltas) = accumulator.counts();
                tracing::warn!(%error, retained_deltas, "usage counter Redis is unavailable");
                metrics::gauge!("usage_ingestion_redis_counter_connected").set(0.0);
                metrics::gauge!("usage_ingestion_redis_counter_accumulator_scopes")
                    .set(retained_scopes as f64);
                metrics::gauge!("usage_ingestion_redis_counter_accumulator_entries")
                    .set(retained_deltas as f64);
                metrics::counter!("usage_ingestion_redis_counter_errors_total").increment(1);
                return;
            }
        }
    }
    let counters = accumulator.drain();
    metrics::gauge!("usage_ingestion_redis_counter_accumulator_scopes").set(counters.len() as f64);
    metrics::gauge!("usage_ingestion_redis_counter_accumulator_entries").set(
        counters
            .iter()
            .map(|counters| counters.entries.len())
            .sum::<usize>() as f64,
    );
    let outcome = flush_with_concurrency(
        Arc::clone(store.as_ref().unwrap()),
        counters,
        config.flush_concurrency,
    )
    .await;
    let (pending_scopes, pending_entries) = accumulator.counts();
    metrics::gauge!("usage_ingestion_redis_counter_accumulator_scopes").set(pending_scopes as f64);
    metrics::gauge!("usage_ingestion_redis_counter_accumulator_entries")
        .set(pending_entries as f64);
    metrics::histogram!("usage_ingestion_redis_counter_flush_seconds")
        .record(started.elapsed().as_secs_f64());
    metrics::counter!("usage_ingestion_redis_counter_commands_flushed_total")
        .increment(outcome.commands as u64);
    metrics::counter!("usage_ingestion_redis_counter_dropped_deltas_total")
        .increment(outcome.dropped as u64);
    if outcome.failed_scopes > 0 {
        metrics::gauge!("usage_ingestion_redis_counter_connected").set(0.0);
        metrics::counter!("usage_ingestion_redis_counter_errors_total").increment(1);
        *store = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};

    struct FailingStore;

    #[async_trait]
    impl CounterStore for FailingStore {
        async fn flush_scope(&self, _counters: &ScopeCounters) -> Result<usize, redis::RedisError> {
            Err(redis::RedisError::from((
                redis::ErrorKind::IoError,
                "test write failure",
            )))
        }
    }

    fn gauge(snapshotter: &Snapshotter, name: &str) -> Option<f64> {
        snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find(|(key, _, _, _)| key.key().name() == name)
            .and_then(|(_, _, _, value)| match value {
                DebugValue::Gauge(value) => Some(value.into_inner()),
                _ => None,
            })
    }

    #[test]
    fn hashes_stay_with_their_scope_and_accumulator_merges_series() {
        let organization_id = Uuid::nil();
        let accumulator = CounterAccumulator::default();
        let timestamp = Utc::now();
        accumulator
            .add(42, organization_id, "events", "event", 2, timestamp)
            .unwrap();
        accumulator
            .add(42, organization_id, "events", "event", 3, timestamp)
            .unwrap();
        accumulator
            .add(43, organization_id, "events", "event", 1, timestamp)
            .unwrap();

        let drained = accumulator.drain();
        assert_eq!(drained.len(), 3);
        assert!(accumulator.drain().is_empty());
        let team = drained
            .iter()
            .find(|counters| counters.scope == CounterScope::Team(42))
            .unwrap();
        assert_eq!(team.entries.len(), 2);
        assert!(team.entries.values().all(|quantity| *quantity == 5));
        assert_eq!(
            counter_key(&CounterScope::Team(42), Bucket::Hour(477_336)),
            "usage:v1:{team=42}:h:477336"
        );
        assert!(counter_key(&CounterScope::Team(42), Bucket::Hour(477_336)).contains("{team=42}"));
        assert!(counter_key(&CounterScope::Team(42), Bucket::Day(19_889)).contains("{team=42}"));
        assert_eq!(
            counter_key(
                &CounterScope::Organization(organization_id),
                Bucket::Day(19_889)
            ),
            "usage:v1:{org=00000000-0000-0000-0000-000000000000}:d:19889"
        );
    }

    #[test]
    fn rejects_out_of_range_timestamps_overflow_and_capacity() {
        let organization_id = Uuid::nil();
        let accumulator = CounterAccumulator::default();
        let now = Utc::now();

        assert_eq!(
            accumulator.add(
                42,
                organization_id,
                "events",
                "event",
                1,
                now - ChronoDuration::days(8),
            ),
            Err(CounterAddError::TimestampOutOfRange)
        );
        assert_eq!(
            accumulator.add(
                42,
                organization_id,
                "events",
                "event",
                1,
                now + ChronoDuration::hours(25),
            ),
            Err(CounterAddError::TimestampOutOfRange)
        );
        let overflow = CounterAccumulator::default();
        overflow
            .add(43, organization_id, "events", "event", i64::MAX, now)
            .unwrap();
        assert_eq!(
            overflow.add(43, organization_id, "events", "event", 1, now),
            Err(CounterAddError::Overflow)
        );
        let full = CounterAccumulator::new(3);
        assert_eq!(
            full.add(44, organization_id, "events", "event", 1, now),
            Err(CounterAddError::Capacity)
        );
        assert!(full.drain().is_empty());
    }

    #[test]
    fn connection_failure_retains_pending_deltas() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let accumulator = CounterAccumulator::default();
        accumulator
            .add(42, Uuid::nil(), "events", "event", 1, Utc::now())
            .unwrap();
        let mut store = None;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();

        metrics::with_local_recorder(&recorder, || {
            runtime.block_on(flush_tick(
                &accumulator,
                "://invalid",
                CounterConfig::default(),
                &mut store,
            ));
        });

        assert!(store.is_none());
        assert_eq!(
            gauge(
                &snapshotter,
                "usage_ingestion_redis_counter_accumulator_entries"
            ),
            Some(4.0)
        );
        let retained = accumulator.drain();
        assert_eq!(retained.len(), 2);
        assert_eq!(
            retained
                .iter()
                .map(|counters| counters.entries.len())
                .sum::<usize>(),
            4
        );
    }

    #[test]
    fn write_failure_drops_deltas_and_marks_the_store_disconnected() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let accumulator = CounterAccumulator::default();
        accumulator
            .add(42, Uuid::nil(), "events", "event", 1, Utc::now())
            .unwrap();
        let mut store: Option<Arc<dyn CounterStore>> = Some(Arc::new(FailingStore));
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();

        metrics::with_local_recorder(&recorder, || {
            runtime.block_on(flush_tick(
                &accumulator,
                "unused",
                CounterConfig::default(),
                &mut store,
            ));
        });

        assert!(store.is_none());
        assert_eq!(
            accumulator
                .drain()
                .iter()
                .map(|counters| counters.entries.len())
                .sum::<usize>(),
            0
        );
        assert_eq!(
            gauge(&snapshotter, "usage_ingestion_redis_counter_connected"),
            Some(0.0)
        );
        assert_eq!(
            gauge(
                &snapshotter,
                "usage_ingestion_redis_counter_accumulator_entries"
            ),
            Some(0.0)
        );
    }
}
