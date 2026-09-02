use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use futures::{stream, StreamExt};
use redis::cluster::ClusterClient;
use redis::cluster_async::ClusterConnection;
use tokio::sync::Mutex as AsyncMutex;
use tracing::warn;
use uuid::Uuid;

use crate::record::KafkaBillingUsageRecord;

const HOURLY_TTL_SECONDS: u64 = 25 * 60 * 60;
const DAILY_TTL_SECONDS: u64 = 31 * 24 * 60 * 60;
const CONNECTIONS: usize = 16;
const FLUSH_CONCURRENCY: usize = 16;

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

#[derive(Clone, Debug)]
pub struct ScopeCounters {
    scope: CounterScope,
    entries: HashMap<CounterEntry, i64>,
}

impl ScopeCounters {
    fn command_count(&self) -> usize {
        self.entries.len() * 2
    }
}

/// A process-local, lossy aggregation of Kafka-confirmed usage records.
#[derive(Default)]
pub struct CounterAccumulator {
    pending: Mutex<HashMap<CounterScope, HashMap<CounterEntry, i64>>>,
}

impl CounterAccumulator {
    pub fn add_record(&self, record: &KafkaBillingUsageRecord) {
        self.add(
            record.team_id,
            record.organization_id,
            &record.usage_key,
            &record.unit,
            record.quantity,
            record.usage_timestamp,
        );
    }

    pub fn add(
        &self,
        team_id: i64,
        organization_id: Uuid,
        usage_key: &str,
        unit: &str,
        quantity: i64,
        timestamp: DateTime<Utc>,
    ) {
        let field = usage_field(usage_key, unit);
        let mut pending = self.pending.lock().expect("usage counter mutex poisoned");
        for scope in [
            CounterScope::Team(team_id),
            CounterScope::Organization(organization_id),
        ] {
            let entries = pending.entry(scope).or_default();
            for bucket in Bucket::from_timestamp(timestamp) {
                *entries
                    .entry(CounterEntry {
                        bucket,
                        field: field.clone(),
                    })
                    .or_default() += quantity;
            }
        }
    }

    pub fn drain(&self) -> Vec<ScopeCounters> {
        let mut pending = self.pending.lock().expect("usage counter mutex poisoned");
        std::mem::take(&mut *pending)
            .into_iter()
            .map(|(scope, entries)| ScopeCounters { scope, entries })
            .collect()
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

#[async_trait]
pub trait CounterStore: Send + Sync {
    async fn flush_scope(&self, counters: ScopeCounters) -> Result<usize, redis::RedisError>;
}

/// Cluster-aware store. Each scope is one transaction, and every key in it has the same hash tag.
pub struct RedisCounterStore {
    connections: Vec<AsyncMutex<ClusterConnection>>,
}

impl RedisCounterStore {
    pub async fn connect(url: &str) -> Result<Self, redis::RedisError> {
        let client = ClusterClient::new([url])?;
        let mut connections = Vec::with_capacity(CONNECTIONS);
        for _ in 0..CONNECTIONS {
            connections.push(AsyncMutex::new(client.get_async_connection().await?));
        }
        Ok(Self { connections })
    }

    fn connection(&self, scope: &CounterScope) -> &AsyncMutex<ClusterConnection> {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        scope.hash(&mut hasher);
        &self.connections[(hasher.finish() as usize) % self.connections.len()]
    }
}

#[async_trait]
impl CounterStore for RedisCounterStore {
    async fn flush_scope(&self, counters: ScopeCounters) -> Result<usize, redis::RedisError> {
        let command_count = counters.command_count();
        let mut pipeline = redis::pipe();
        pipeline.atomic();
        for (entry, quantity) in counters.entries {
            let key = counter_key(&counters.scope, entry.bucket);
            pipeline
                .cmd("HINCRBY")
                .arg(&key)
                .arg(&entry.field)
                .arg(quantity)
                .ignore();
            pipeline
                .cmd("EXPIRE")
                .arg(&key)
                .arg(entry.bucket.ttl_seconds())
                .arg("NX")
                .ignore();
        }
        let mut connection = self.connection(&counters.scope).lock().await;
        pipeline.query_async::<()>(&mut *connection).await?;
        Ok(command_count)
    }
}

pub fn counter_key(scope: &CounterScope, bucket: Bucket) -> String {
    let scope = match scope {
        CounterScope::Team(team_id) => format!("team:{team_id}"),
        CounterScope::Organization(organization_id) => format!("org:{organization_id}"),
    };
    format!(
        "usage:v1:{{{scope}}}:{}:{}",
        bucket.suffix(),
        bucket.index()
    )
}

fn usage_field(usage_key: &str, unit: &str) -> String {
    // The length prefix keeps the pair unambiguous even if a producer uses a delimiter in a name.
    format!("{}:{usage_key}{unit}", usage_key.len())
}

pub async fn flush(store: Arc<dyn CounterStore>, counters: Vec<ScopeCounters>) -> (usize, usize) {
    let results = stream::iter(counters)
        .map(|counters| {
            let store = Arc::clone(&store);
            async move {
                let entries = counters.entries.len();
                match store.flush_scope(counters).await {
                    Ok(commands) => (commands, 0),
                    Err(error) => {
                        warn!(%error, dropped_deltas = entries, "usage counter flush failed");
                        (0, entries)
                    }
                }
            }
        })
        .buffer_unordered(FLUSH_CONCURRENCY)
        .collect::<Vec<_>>()
        .await;
    results.into_iter().fold(
        (0, 0),
        |(commands, dropped), (next_commands, next_dropped)| {
            (commands + next_commands, dropped + next_dropped)
        },
    )
}

pub fn spawn_flush_task(
    accumulator: Arc<CounterAccumulator>,
    store: Arc<dyn CounterStore>,
    interval: Duration,
) {
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(interval);
        loop {
            ticker.tick().await;
            let started = Instant::now();
            let counters = accumulator.drain();
            metrics::gauge!("usage_ingestion_redis_counter_accumulator_scopes")
                .set(counters.len() as f64);
            let (commands, dropped) = flush(Arc::clone(&store), counters).await;
            metrics::histogram!("usage_ingestion_redis_counter_flush_seconds")
                .record(started.elapsed().as_secs_f64());
            metrics::counter!("usage_ingestion_redis_counter_commands_flushed_total")
                .increment(commands as u64);
            metrics::counter!("usage_ingestion_redis_counter_dropped_deltas_total")
                .increment(dropped as u64);
            if dropped > 0 {
                metrics::counter!("usage_ingestion_redis_counter_errors_total").increment(1);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hashes_stay_with_their_scope_and_accumulator_merges_series() {
        let organization_id = Uuid::nil();
        let accumulator = CounterAccumulator::default();
        let timestamp = DateTime::from_timestamp(1_718_409_600, 0).unwrap();
        accumulator.add(42, organization_id, "events", "event", 2, timestamp);
        accumulator.add(42, organization_id, "events", "event", 3, timestamp);
        accumulator.add(43, organization_id, "events", "event", 1, timestamp);

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
            "usage:v1:{team:42}:h:477336"
        );
        assert!(counter_key(&CounterScope::Team(42), Bucket::Hour(477_336)).contains("{team:42}"));
        assert!(counter_key(&CounterScope::Team(42), Bucket::Day(19_889)).contains("{team:42}"));
    }
}
