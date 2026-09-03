use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
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
const MAX_SERIES_PER_BUCKET: usize = 16;
const MAX_PAST_TIMESTAMP: ChronoDuration = ChronoDuration::days(7);
const MAX_FUTURE_TIMESTAMP: ChronoDuration = ChronoDuration::hours(24);
const INCREMENT_COUNTER: &str = r#"
local exists = redis.call('HEXISTS', KEYS[1], ARGV[1])
if exists == 0 and redis.call('HLEN', KEYS[1]) >= tonumber(ARGV[4]) then
    return 0
end
redis.call('HINCRBY', KEYS[1], ARGV[1], ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3], 'NX')
return 1
"#;

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
    TooManySeries,
    Overflow,
}

impl CounterAddError {
    pub fn reason(&self) -> &'static str {
        match self {
            Self::TimestampOutOfRange => "timestamp_out_of_range",
            Self::TooManySeries => "too_many_series",
            Self::Overflow => "overflow",
        }
    }
}

#[derive(Clone, Debug)]
pub struct ScopeCounters {
    scope: CounterScope,
    entries: HashMap<CounterEntry, i64>,
}

/// A process-local, lossy aggregation of Kafka-confirmed usage records.
#[derive(Default)]
pub struct CounterAccumulator {
    pending: Mutex<HashMap<CounterScope, HashMap<CounterEntry, i64>>>,
}

impl CounterAccumulator {
    pub fn add_record(&self, record: &KafkaBillingUsageRecord) -> Result<(), CounterAddError> {
        // TODO: Pass trusted capture time from event-derived producers into `usage_timestamp`.
        // Batch-flush time rebuckets lagged records into wrong quota windows; customer event timestamps must not be used.
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
        let mut rejection = None;
        for scope in scopes {
            // An organization aggregates the series of every team below it, so it saturates
            // first. Rejecting per scope keeps the team projection alive when it does.
            if let Err(error) =
                add_to_scope(pending.entry(scope).or_default(), buckets, &field, quantity)
            {
                rejection = Some(error);
            }
        }
        rejection.map_or(Ok(()), Err)
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

/// A flushed scope: commands sent, and deltas the Redis-side series cap refused.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ScopeFlush {
    pub commands: usize,
    pub capped: usize,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct FlushOutcome {
    pub commands: usize,
    /// Refused by the series cap, which is the projection working as designed.
    pub capped: usize,
    /// Lost because a scope's transaction failed.
    pub dropped: usize,
    pub failed_scopes: usize,
}

#[async_trait]
pub trait CounterStore: Send + Sync {
    async fn flush_scope(&self, counters: ScopeCounters) -> Result<ScopeFlush, redis::RedisError>;
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
    async fn flush_scope(&self, counters: ScopeCounters) -> Result<ScopeFlush, redis::RedisError> {
        let entry_count = counters.entries.len();
        let mut pipeline = redis::pipe();
        pipeline.atomic();
        for (entry, quantity) in counters.entries {
            let key = counter_key(&counters.scope, entry.bucket);
            pipeline
                .cmd("EVAL")
                .arg(INCREMENT_COUNTER)
                .arg(1)
                .arg(&key)
                .arg(&entry.field)
                .arg(quantity)
                .arg(entry.bucket.ttl_seconds())
                .arg(MAX_SERIES_PER_BUCKET);
        }
        let mut connection = self.connection(&counters.scope).lock().await;
        let accepted = pipeline.query_async::<Vec<i64>>(&mut *connection).await?;
        let accepted = accepted.into_iter().filter(|result| *result == 1).count();
        Ok(ScopeFlush {
            commands: accepted * 2,
            capped: entry_count - accepted,
        })
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
            None => {
                if entries
                    .keys()
                    .filter(|existing| existing.bucket == bucket)
                    .count()
                    >= MAX_SERIES_PER_BUCKET
                {
                    return Err(CounterAddError::TooManySeries);
                }
                quantity
            }
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
    let results = stream::iter(counters)
        .map(|counters| {
            let store = Arc::clone(&store);
            async move {
                let entries = counters.entries.len();
                match store.flush_scope(counters).await {
                    Ok(flushed) => FlushOutcome {
                        commands: flushed.commands,
                        capped: flushed.capped,
                        ..FlushOutcome::default()
                    },
                    Err(error) => {
                        warn!(%error, dropped_deltas = entries, "usage counter flush failed");
                        FlushOutcome {
                            dropped: entries,
                            failed_scopes: 1,
                            ..FlushOutcome::default()
                        }
                    }
                }
            }
        })
        .buffer_unordered(FLUSH_CONCURRENCY)
        .collect::<Vec<_>>()
        .await;
    results
        .into_iter()
        .fold(FlushOutcome::default(), |total, next| FlushOutcome {
            commands: total.commands + next.commands,
            capped: total.capped + next.capped,
            dropped: total.dropped + next.dropped,
            failed_scopes: total.failed_scopes + next.failed_scopes,
        })
}

pub fn spawn_flush_task(
    accumulator: Arc<CounterAccumulator>,
    redis_url: String,
    interval: Duration,
) {
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(interval);
        let mut store: Option<Arc<dyn CounterStore>> = None;
        loop {
            ticker.tick().await;
            let started = Instant::now();
            if store.is_none() {
                match RedisCounterStore::connect(&redis_url).await {
                    Ok(redis_store) => {
                        store = Some(Arc::new(redis_store));
                        metrics::gauge!("usage_ingestion_redis_counter_connected").set(1.0);
                    }
                    Err(error) => {
                        let dropped = accumulator
                            .drain()
                            .iter()
                            .map(|scope| scope.entries.len())
                            .sum::<usize>();
                        tracing::warn!(%error, dropped_deltas = dropped, "usage counter Redis is unavailable");
                        metrics::gauge!("usage_ingestion_redis_counter_connected").set(0.0);
                        metrics::counter!("usage_ingestion_redis_counter_dropped_deltas_total")
                            .increment(dropped as u64);
                        metrics::counter!("usage_ingestion_redis_counter_errors_total")
                            .increment(1);
                        continue;
                    }
                }
            }
            let counters = accumulator.drain();
            metrics::gauge!("usage_ingestion_redis_counter_accumulator_scopes")
                .set(counters.len() as f64);
            let outcome = flush(Arc::clone(store.as_ref().unwrap()), counters).await;
            metrics::histogram!("usage_ingestion_redis_counter_flush_seconds")
                .record(started.elapsed().as_secs_f64());
            metrics::counter!("usage_ingestion_redis_counter_commands_flushed_total")
                .increment(outcome.commands as u64);
            metrics::counter!("usage_ingestion_redis_counter_dropped_deltas_total")
                .increment(outcome.dropped as u64);
            metrics::counter!(
                "usage_ingestion_redis_counter_rejected_deltas_total",
                "reason" => "too_many_series"
            )
            .increment(outcome.capped as u64);
            // Only a failed transaction means the connection is suspect. A capped series does not.
            if outcome.failed_scopes > 0 {
                metrics::counter!("usage_ingestion_redis_counter_errors_total").increment(1);
                store = None;
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
            "usage:v1:{team:42}:h:477336"
        );
        assert!(counter_key(&CounterScope::Team(42), Bucket::Hour(477_336)).contains("{team:42}"));
        assert!(counter_key(&CounterScope::Team(42), Bucket::Day(19_889)).contains("{team:42}"));
    }

    #[test]
    fn bounds_series_timestamps_and_deltas() {
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
        for index in 0..MAX_SERIES_PER_BUCKET {
            accumulator
                .add(
                    42,
                    organization_id,
                    &format!("events_{index}"),
                    "event",
                    1,
                    now,
                )
                .unwrap();
        }
        assert_eq!(
            accumulator.add(42, organization_id, "one_too_many", "event", 1, now),
            Err(CounterAddError::TooManySeries)
        );

        let overflow = CounterAccumulator::default();
        overflow
            .add(43, organization_id, "events", "event", i64::MAX, now)
            .unwrap();
        assert_eq!(
            overflow.add(43, organization_id, "events", "event", 1, now),
            Err(CounterAddError::Overflow)
        );
    }

    #[test]
    fn saturated_organization_still_lets_a_team_count() {
        let organization_id = Uuid::nil();
        let accumulator = CounterAccumulator::default();
        let now = Utc::now();
        for index in 0..MAX_SERIES_PER_BUCKET {
            accumulator
                .add(
                    index as i64 + 1,
                    organization_id,
                    &format!("events_{index}"),
                    "event",
                    1,
                    now,
                )
                .unwrap();
        }

        assert_eq!(
            accumulator.add(99, organization_id, "one_too_many", "event", 7, now),
            Err(CounterAddError::TooManySeries)
        );
        let drained = accumulator.drain();
        let team = drained
            .iter()
            .find(|counters| counters.scope == CounterScope::Team(99))
            .expect("the team scope should still hold its own series");
        assert_eq!(team.entries.len(), 2);
        assert!(team.entries.values().all(|quantity| *quantity == 7));
    }
}
