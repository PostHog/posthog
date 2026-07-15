use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka::config::KafkaConfig;
use dashmap::DashMap;
use metrics::counter;
use prost::Message as ProtoMessage;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use tokio::sync::Mutex;
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
/// The consumer pool tracks partition ownership: warming registers a
/// partition's consumer before the partition serves traffic and release
/// drops it, so the fetch path is a read-only lookup and the fallible
/// client construction never happens under a request. Concurrent
/// recoveries only contend when they target the same partition. Errors
/// never manage the pool — librdkafka clients self-heal their connections
/// — so transient fetch failures retry on the same consumer within the
/// recovery deadline.
pub struct ChangelogRecovery {
    kafka: KafkaConfig,
    group: String,
    topic: String,
    recv_timeout: Duration,
    consumers: DashMap<u32, Arc<Mutex<StreamConsumer>>>,
}

impl ChangelogRecovery {
    pub fn new(cfg: RecoveryConfig) -> Self {
        Self {
            kafka: cfg.kafka,
            group: format!("personhog-leader-recovery-{pod}", pod = cfg.pod_name),
            topic: cfg.topic,
            recv_timeout: cfg.recv_timeout,
            consumers: DashMap::new(),
        }
    }

    /// Create the partition's recovery consumer as the pod takes
    /// ownership. Idempotent: a re-warm without an intervening release
    /// keeps the existing consumer.
    pub fn add_partition(&self, partition: u32) -> Result<(), String> {
        use dashmap::mapref::entry::Entry;

        match self.consumers.entry(partition) {
            Entry::Occupied(_) => Ok(()),
            Entry::Vacant(entry) => {
                let consumer = make_consumer(&self.kafka, &self.group)
                    .map_err(|e| format!("create recovery consumer: {e}"))?;
                entry.insert(Arc::new(Mutex::new(consumer)));
                Ok(())
            }
        }
    }

    /// Drop the partition's recovery consumer on release. A recovery
    /// already holding the slot finishes on the old consumer harmlessly.
    pub fn remove_partition(&self, partition: u32) {
        self.consumers.remove(&partition);
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

        let Some(slot) = self
            .consumers
            .get(&partition)
            .map(|entry| Arc::clone(entry.value()))
        else {
            return Err(format!(
                "no recovery consumer for partition {partition}; partition not owned"
            ));
        };
        let consumer = slot.lock().await;

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
