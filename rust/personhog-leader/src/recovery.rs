use std::time::{Duration, Instant};

use common_kafka::config::KafkaConfig;
use prost::Message as ProtoMessage;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use tokio::sync::Mutex;
use tokio::time::timeout;

use personhog_proto::personhog::types::v1::Person;

use crate::cache::{CachedPerson, DirtyMark, PersonCacheKey};
use crate::warming::make_consumer;

/// Configuration for targeted changelog recovery.
#[derive(Clone)]
pub struct RecoveryConfig {
    pub kafka: KafkaConfig,
    pub topic: String,
    pub pod_name: String,
    /// Timeout for receiving the record after seeking to its offset.
    pub recv_timeout: Duration,
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
/// the index ever holds — so the seek lands on it for as long as the
/// topic's `delete` retention keeps it, far longer than any mark should
/// live.
pub struct ChangelogRecovery {
    /// One long-lived consumer shared across recoveries, with the
    /// assignment swapped per fetch. Guarded by a mutex: recoveries only
    /// happen on the rare evicted-while-dirty miss, and serializing them
    /// is far cheaper than paying a consumer's broker-metadata round-trips
    /// on every recovering request.
    consumer: Mutex<StreamConsumer>,
    topic: String,
    recv_timeout: Duration,
}

impl ChangelogRecovery {
    pub fn new(cfg: RecoveryConfig) -> Result<Self, String> {
        let group = format!("personhog-leader-recovery-{pod}", pod = cfg.pod_name);
        let consumer = make_consumer(&cfg.kafka, &group)
            .map_err(|e| format!("create recovery consumer: {e}"))?;
        Ok(Self {
            consumer: Mutex::new(consumer),
            topic: cfg.topic,
            recv_timeout: cfg.recv_timeout,
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

        let consumer = self.consumer.lock().await;
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition_offset(&self.topic, partition_i32, Offset::Offset(offset))
            .map_err(|e| format!("tpl add_partition_offset: {e}"))?;
        consumer
            .assign(&tpl)
            .map_err(|e| format!("recovery consumer assign: {e}"))?;

        let deadline = Instant::now() + self.recv_timeout;
        let result = loop {
            // An exhausted budget saturates to zero, which makes the
            // timeout fire on its next poll — no separate deadline check.
            let remaining = deadline.saturating_duration_since(Instant::now());
            let msg = match timeout(remaining, consumer.recv()).await {
                Ok(Ok(msg)) => msg,
                Ok(Err(e)) => break Err(format!("recovery recv: {e}")),
                Err(_) => {
                    break Err(format!(
                        "recovery timed out after {:?} seeking partition {partition} offset {offset}",
                        self.recv_timeout
                    ));
                }
            };

            // Records from a previous fetch's assignment can linger in the
            // consumer's queue; skip anything that is not the sought record.
            if msg.partition() != partition_i32 || msg.offset() < offset {
                continue;
            }
            if msg.offset() > offset {
                // Seeking to an existing offset returns exactly that record;
                // reading past it means the record is gone — impossible
                // while the index only holds latest-record offsets, so fail
                // loudly rather than install whatever came back.
                break Err(format!(
                    "recovery expected offset {offset} but read {}; record missing from changelog",
                    msg.offset()
                ));
            }

            break decode_person(msg.payload(), mark, expected);
        };

        // Stop background fetching until the next recovery swaps in a new
        // assignment.
        if let Err(e) = consumer.unassign() {
            tracing::warn!(error = %e, "recovery consumer unassign failed");
        }
        result
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
