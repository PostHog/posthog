use std::collections::VecDeque;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use common_kafka::config::KafkaConfig;
use metrics::{counter, histogram};
use prost::Message as ProtoMessage;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use tokio::sync::Semaphore;
use tokio::time::timeout;

use personhog_proto::personhog::types::v1::Person;

use crate::cache::{CachedPerson, DirtyMark, PersonCacheKey};
use crate::warming::make_consumer;

/// How long to wait before retrying a transiently failed fetch.
const RETRY_BACKOFF: Duration = Duration::from_millis(100);

/// Configuration for targeted changelog recovery.
#[derive(Clone)]
pub struct RecoveryConfig {
    pub kafka: KafkaConfig,
    pub topic: String,
    pub pod_name: String,
    /// Overall deadline for one recovery, including transient-failure
    /// retries.
    pub recv_timeout: Duration,
    /// Number of pooled consumers, bounding concurrent recoveries.
    pub pool_size: usize,
}

/// Classifies a failed fetch step for the retry loop: transient failures
/// (broker errors, timeouts, the sought record not coming back) retry
/// until the recovery deadline; permanent ones (a record that contradicts
/// its mark) fail immediately.
enum FetchError {
    Transient(String),
    Permanent(String),
}

/// Fetches single persons from the changelog — the recovery path for cache
/// entries evicted while the writer still lags. It reads Kafka, never
/// Postgres, so the leader's availability stays decoupled from writer
/// progress.
///
/// Every changelog record carries the person's full state, so the one
/// record at the dirty index's marked offset supersedes anything before
/// it; no replay is needed. And because the topic compacts by person key,
/// compaction never removes the latest record for a key — the only offset
/// the index ever holds — so the fetch lands on it for as long as the
/// topic's `delete` retention keeps it, far longer than any mark should
/// live.
///
/// A fresh `assign` positions any consumer at any (partition, offset), so
/// the consumers are fungible and pooled globally: a fixed set is built at
/// startup — where construction failure is loud and nothing is in flight —
/// and checked out per fetch, bounding concurrent recoveries at the pool
/// size the way a DB connection pool bounds queries. Checkout transfers
/// exclusive ownership through the idle deque (the semaphore only counts;
/// a permit holder always finds a consumer), so no lock is held while a
/// fetch waits on Kafka or backs off between retries. The pool-wait
/// histogram is the tuning signal for the pool size. Errors never manage
/// the pool — librdkafka clients self-heal their connections — so
/// transient fetch failures retry on the same consumer within the
/// recovery deadline, and the consumer returns to the pool regardless of
/// outcome.
pub struct ChangelogRecovery {
    topic: String,
    recv_timeout: Duration,
    idle: Mutex<VecDeque<StreamConsumer>>,
    permits: Semaphore,
}

impl ChangelogRecovery {
    pub fn new(cfg: RecoveryConfig) -> Result<Self, String> {
        if cfg.pool_size == 0 {
            return Err("recovery pool size must be at least 1".to_string());
        }
        let group = format!("personhog-leader-recovery-{pod}", pod = cfg.pod_name);
        let mut idle = VecDeque::with_capacity(cfg.pool_size);
        for _ in 0..cfg.pool_size {
            idle.push_back(
                make_consumer(&cfg.kafka, &group)
                    .map_err(|e| format!("create recovery consumer: {e}"))?,
            );
        }
        Ok(Self {
            topic: cfg.topic,
            recv_timeout: cfg.recv_timeout,
            idle: Mutex::new(idle),
            permits: Semaphore::new(cfg.pool_size),
        })
    }

    /// Fetch a person's latest state from the changelog record the dirty
    /// index marked for its most recent acked produce. The decoded record
    /// must carry the mark's key and version exactly: the mark was written
    /// from the same state the record was encoded from, so any mismatch
    /// means acked state and produced state diverged — a bug worth failing
    /// loudly over, never worth serving.
    pub async fn fetch_person_at(
        &self,
        mark: &DirtyMark,
        expected: &PersonCacheKey,
    ) -> Result<CachedPerson, String> {
        let partition = mark.partition;
        let offset = mark.offset;
        let partition_i32 = i32::try_from(partition)
            .map_err(|_| format!("partition {partition} exceeds i32::MAX"))?;

        let wait_start = Instant::now();
        let _permit = self
            .permits
            .acquire()
            .await
            .map_err(|_| "recovery pool closed".to_string())?;
        histogram!("personhog_leader_recovery_pool_wait_ms")
            .record(wait_start.elapsed().as_secs_f64() * 1000.0);
        let consumer = self
            .idle
            .lock()
            .expect("recovery pool lock poisoned")
            .pop_front()
            .expect("a permit guarantees an idle consumer");

        // Each attempt repositions with a fresh assign: it starts fetching
        // at the target immediately (repositioning a live stream via seek
        // stalls ~1s while librdkafka drains the previous position's
        // outstanding long-poll) and purges records buffered by a previous
        // attempt.
        let deadline = Instant::now() + self.recv_timeout;
        let result = loop {
            let attempt = self
                .attempt_fetch(&consumer, partition_i32, mark, expected, deadline)
                .await;
            match attempt {
                Ok(person) => break Ok(person),
                Err(FetchError::Permanent(message)) => break Err(message),
                Err(FetchError::Transient(message)) => {
                    if Instant::now() + RETRY_BACKOFF >= deadline {
                        break Err(message);
                    }
                    counter!("personhog_leader_recovery_retries_total").increment(1);
                    tracing::debug!(
                        partition,
                        offset,
                        error = %message,
                        "transient recovery failure, retrying"
                    );
                    tokio::time::sleep(RETRY_BACKOFF).await;
                }
            }
        };

        // Park the consumer so it does not keep fetching the partition
        // tail between recoveries.
        if let Err(e) = consumer.unassign() {
            tracing::warn!(partition, error = %e, "recovery consumer unassign failed");
        }
        self.idle
            .lock()
            .expect("recovery pool lock poisoned")
            .push_back(consumer);
        result
    }

    /// One positioning-and-receive attempt against a locked consumer.
    async fn attempt_fetch(
        &self,
        consumer: &StreamConsumer,
        partition_i32: i32,
        mark: &DirtyMark,
        expected: &PersonCacheKey,
        deadline: Instant,
    ) -> Result<CachedPerson, FetchError> {
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition_offset(&self.topic, partition_i32, Offset::Offset(mark.offset))
            .map_err(|e| FetchError::Permanent(format!("tpl add_partition_offset: {e}")))?;
        consumer
            .assign(&tpl)
            .map_err(|e| FetchError::Transient(format!("recovery consumer assign: {e}")))?;

        let offset = mark.offset;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            let msg = match timeout(remaining, consumer.recv()).await {
                Ok(Ok(msg)) => msg,
                Ok(Err(e)) => return Err(FetchError::Transient(format!("recovery recv: {e}"))),
                Err(_) => {
                    return Err(FetchError::Transient(format!(
                        "recovery timed out after {:?} seeking partition {} offset {offset}",
                        self.recv_timeout, mark.partition
                    )));
                }
            };

            // Skip anything that is not the sought record.
            if msg.partition() != partition_i32 || msg.offset() < offset {
                continue;
            }
            if msg.offset() > offset {
                // A record past the target before the target itself means
                // the sought record was not returned: either a stale
                // buffered record from a previous position, which the next
                // attempt's assign purges, or a record genuinely gone from
                // the changelog, which keeps failing until the deadline.
                return Err(FetchError::Transient(format!(
                    "recovery expected offset {offset} but read {}; record missing from changelog",
                    msg.offset()
                )));
            }

            return decode_person(msg.payload(), mark, expected).map_err(FetchError::Permanent);
        }
    }
}

fn decode_person(
    payload: Option<&[u8]>,
    mark: &DirtyMark,
    expected: &PersonCacheKey,
) -> Result<CachedPerson, String> {
    let offset = mark.offset;
    let payload =
        payload.ok_or_else(|| format!("recovery record at offset {offset} has no payload"))?;
    let person = <Person as ProtoMessage>::decode(payload)
        .map_err(|e| format!("recovery decode failed at offset {offset}: {e}"))?;

    if person.team_id != expected.team_id || person.id != expected.person_id {
        return Err(format!(
            "recovery record key mismatch at offset {offset}: expected team_id={} person_id={}, \
             found team_id={} person_id={}",
            expected.team_id, expected.person_id, person.team_id, person.id
        ));
    }

    if person.version != mark.version {
        return Err(format!(
            "recovery record version mismatch at offset {offset}: acked version {}, record \
             carries {} — acked state and produced record diverged",
            mark.version, person.version
        ));
    }

    CachedPerson::try_from(person)
        .map_err(|e| format!("recovery properties decode failed at offset {offset}: {e}"))
}
