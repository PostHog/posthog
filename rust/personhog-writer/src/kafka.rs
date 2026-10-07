use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use common_kafka::config::KafkaConfig;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::message::BorrowedMessage;
use rdkafka::{ClientConfig, ClientContext, TopicPartitionList};

// ── Consumer ────────────────────────────────────────────────────

/// Records the partitions each rebalance takes away, so the consume loop can
/// drop their buffered rows before the new owner starts reading them.
struct RebalanceContext {
    revoked: Arc<Mutex<Vec<i32>>>,
    joined: Arc<AtomicBool>,
}

impl ClientContext for RebalanceContext {}

impl ConsumerContext for RebalanceContext {
    fn pre_rebalance(&self, _base_consumer: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        match rebalance {
            Rebalance::Assign(_) => self.joined.store(true, Ordering::SeqCst),
            Rebalance::Revoke(partitions) => {
                let mut revoked = self.revoked.lock().unwrap();
                revoked.extend(partitions.elements().iter().map(|e| e.partition()));
            }
            Rebalance::Error(_) => {}
        }
    }
}

/// Wraps a Kafka StreamConsumer with its topic, providing a clean
/// interface for receiving messages and committing offsets.
pub struct PersonConsumer {
    consumer: StreamConsumer<RebalanceContext>,
    topic: String,
    revoked: Arc<Mutex<Vec<i32>>>,
    joined: Arc<AtomicBool>,
}

impl PersonConsumer {
    /// Client-level fatal state, queryable even after the event that
    /// set it was consumed. A fatal client never recovers, so the
    /// caller must exit rather than keep polling it.
    pub fn fatal_error(&self) -> Option<(rdkafka::error::RDKafkaErrorCode, String)> {
        self.consumer.client().fatal_error()
    }

    pub fn from_config(
        kafka: &KafkaConfig,
        consumer_group: &str,
        offset_reset: &str,
        topic: String,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &kafka.kafka_hosts)
            .set("group.id", consumer_group)
            .set("auto.offset.reset", offset_reset)
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            // Only committed transactions: with the leader's epoch fencing
            // on, aborted windows and zombie leftovers must never reach
            // Postgres. Identical behavior on a non-transactional topic.
            // The price is a liveness coupling: this consumer cannot
            // advance past an open window, so a leader that stops
            // mid-window holds the partition at its last stable offset
            // until the broker abandons the transaction — bounded by the
            // leader's derived broker transaction timeout (about 6s at
            // the production lease).
            .set("isolation.level", "read_committed")
            // Cooperative-sticky: during scale events, only partitions that need
            // to move are revoked. Non-moving partitions keep being consumed.
            .set("partition.assignment.strategy", "cooperative-sticky");

        // Static group membership: the broker holds partition assignments for
        // session.timeout.ms after a pod disappears, so quick restarts
        // (deploys, OOM kills) don't trigger a rebalance at all.
        // Requires stable pod names (StatefulSet) so the same ID reconnects.
        if !kafka.kafka_client_id.is_empty() {
            client_config
                .set("client.id", &kafka.kafka_client_id)
                .set("group.instance.id", &kafka.kafka_client_id);
        }

        if kafka.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }

        if !kafka.kafka_client_rack.is_empty() {
            client_config.set("client.rack", &kafka.kafka_client_rack);
        }

        Self::new(&client_config, topic)
    }

    /// Create from a raw `ClientConfig`. Useful in tests where you control
    /// the config directly (e.g., mock clusters).
    pub fn new(config: &ClientConfig, topic: String) -> Result<Self, rdkafka::error::KafkaError> {
        let revoked = Arc::new(Mutex::new(Vec::new()));
        let joined = Arc::new(AtomicBool::new(false));
        let consumer: StreamConsumer<RebalanceContext> =
            config.create_with_context(RebalanceContext {
                revoked: Arc::clone(&revoked),
                joined: Arc::clone(&joined),
            })?;
        consumer.subscribe(&[&topic])?;
        Ok(Self {
            consumer,
            topic,
            revoked,
            joined,
        })
    }

    pub async fn recv(&self) -> Result<BorrowedMessage<'_>, rdkafka::error::KafkaError> {
        self.consumer.recv().await
    }

    pub fn take_revoked(&self) -> Vec<i32> {
        std::mem::take(&mut *self.revoked.lock().unwrap())
    }

    /// `None` until the first assignment arrives: before that, an empty
    /// assignment means the group is still forming, not that this pod owns
    /// nothing.
    pub fn assigned_partitions(&self) -> Result<Option<HashSet<i32>>, rdkafka::error::KafkaError> {
        if !self.joined.load(Ordering::SeqCst) {
            return Ok(None);
        }
        Ok(Some(
            self.consumer
                .assignment()?
                .elements()
                .iter()
                .map(|e| e.partition())
                .collect(),
        ))
    }

    pub fn positions(&self) -> Result<HashMap<i32, i64>, rdkafka::error::KafkaError> {
        Ok(self
            .consumer
            .position()?
            .elements()
            .iter()
            .filter_map(|e| match e.offset() {
                rdkafka::Offset::Offset(next) => Some((e.partition(), next)),
                _ => None,
            })
            .collect())
    }

    pub fn commit_offsets(
        &self,
        offsets: &HashMap<i32, i64>,
    ) -> Result<(), rdkafka::error::KafkaError> {
        if offsets.is_empty() {
            return Ok(());
        }

        // A partition revoked while its batch was in flight belongs to
        // another pod now; committing it here would move that pod's offset.
        let assigned = self.assigned_partitions()?.unwrap_or_default();
        let mut tpl = TopicPartitionList::new();
        let mut skipped: u64 = 0;
        for (partition, offset) in offsets {
            if !assigned.contains(partition) {
                skipped += 1;
                continue;
            }
            tpl.add_partition_offset(&self.topic, *partition, rdkafka::Offset::Offset(offset + 1))?;
        }
        if skipped > 0 {
            counter!("personhog_writer_offset_commits_skipped_total", "reason" => "unassigned")
                .increment(skipped);
        }
        if tpl.count() == 0 {
            return Ok(());
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        Ok(())
    }

    pub fn topic(&self) -> &str {
        &self.topic
    }
}
