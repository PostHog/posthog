//! The consume loop: gate, read and admit each message, buffer it, and flush on time or size.

use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::message::{BorrowedMessage, Headers, Message as _};
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use crate::batch::{Batch, Block, Inspectors, SessionKey};
use crate::process::{admit, read, sampled};
use crate::teams::TeamCache;

/// Records the partitions each rebalance takes away, so the loop can drop what it buffered for them.
pub struct RebalanceContext {
    revoked: Arc<Mutex<Vec<i32>>>,
}

impl ClientContext for RebalanceContext {}

impl ConsumerContext for RebalanceContext {
    fn pre_rebalance(&self, _: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        if let Rebalance::Revoke(partitions) = rebalance {
            self.revoked
                .lock()
                .unwrap()
                .extend(partitions.elements().iter().map(|e| e.partition()));
        }
    }
}

pub struct RecorderConsumer {
    consumer: StreamConsumer<RebalanceContext>,
    topic: String,
    revoked: Arc<Mutex<Vec<i32>>>,
}

impl RecorderConsumer {
    pub fn new(
        kafka: &KafkaConfig,
        group: &str,
        offset_reset: &str,
        topic: &str,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        let mut config = ClientConfig::new();
        config
            .set("bootstrap.servers", &kafka.kafka_hosts)
            .set("group.id", group)
            .set("auto.offset.reset", offset_reset)
            // Offsets move only after a flush has stored the blocks for them.
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("partition.assignment.strategy", "cooperative-sticky");
        if kafka.kafka_tls {
            config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }
        if !kafka.kafka_client_rack.is_empty() {
            config.set("client.rack", &kafka.kafka_client_rack);
        }
        let revoked = Arc::new(Mutex::new(Vec::new()));
        let consumer: StreamConsumer<RebalanceContext> =
            config.create_with_context(RebalanceContext {
                revoked: revoked.clone(),
            })?;
        consumer.subscribe(&[topic])?;
        Ok(Self {
            consumer,
            topic: topic.to_owned(),
            revoked,
        })
    }

    fn take_revoked(&self) -> Vec<i32> {
        std::mem::take(&mut *self.revoked.lock().unwrap())
    }

    /// Commits the next offset of every partition this process still owns.
    fn commit(&self, offsets: &std::collections::HashMap<i32, i64>) {
        let assigned = self.consumer.assignment().unwrap_or_default();
        let mut list = TopicPartitionList::new();
        for (&partition, &offset) in offsets {
            if assigned.find_partition(&self.topic, partition).is_some() {
                if let Err(error) =
                    list.add_partition_offset(&self.topic, partition, Offset::Offset(offset + 1))
                {
                    tracing::warn!(%error, partition, "building the offset commit failed");
                }
            }
        }
        if list.count() > 0 {
            if let Err(error) = self.consumer.commit(&list, CommitMode::Async) {
                tracing::warn!(%error, "committing offsets failed");
                counter!("replay_recorder_v4_commit_failures_total").increment(1);
            }
        }
    }
}

fn header<'m>(message: &'m BorrowedMessage<'_>, name: &str) -> Option<&'m str> {
    message
        .headers()?
        .iter()
        .find(|h| h.key == name)
        .and_then(|h| h.value)
        .and_then(|v| std::str::from_utf8(v).ok())
}

pub struct Settings {
    pub sample_percentage: f64,
    pub flush_interval: Duration,
    pub flush_max_bytes: usize,
    pub session_idle: Duration,
}

pub async fn run(
    consumer: RecorderConsumer,
    settings: Settings,
    teams: Arc<TeamCache>,
    handle: Handle,
) {
    let shutdown = handle.shutdown_signal();
    tokio::pin!(shutdown);
    let mut batch = Batch::default();
    let mut inspectors = Inspectors::default();
    let mut tick = tokio::time::interval(Duration::from_secs(1));
    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            _ = tick.tick() => {}
            received = consumer.consumer.recv() => match received {
                Ok(message) => handle_message(&message, &settings, &teams, &mut batch),
                Err(error) => {
                    tracing::warn!(%error, "kafka receive failed");
                    counter!("replay_recorder_v4_kafka_errors_total").increment(1);
                    // A fatal error disables the client for good, so only a restart recovers.
                    if let Some((code, reason)) = consumer.consumer.client().fatal_error() {
                        handle.signal_failure(format!("kafka consumer fatal error {code}: {reason}"));
                        return;
                    }
                }
            },
        }
        handle.report_healthy();
        let revoked = consumer.take_revoked();
        if !revoked.is_empty() {
            batch.drop_partitions(&revoked);
            inspectors.drop_partitions(&revoked);
        }
        if batch.should_flush(settings.flush_interval, settings.flush_max_bytes) {
            let (blocks, offsets) = inspectors.inspect(std::mem::take(&mut batch));
            flush(&blocks);
            consumer.commit(&offsets);
            inspectors.evict_idle(settings.session_idle);
        }
    }
}

fn handle_message(
    message: &BorrowedMessage<'_>,
    settings: &Settings,
    teams: &TeamCache,
    batch: &mut Batch,
) {
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as i64);
    let admitted = sampled(message.key(), settings.sample_percentage)
        .and_then(|()| {
            read(
                message.payload().unwrap_or_default(),
                header(message, "content-encoding"),
            )
        })
        .and_then(|read| {
            let team = header(message, "token").and_then(|token| teams.get(token));
            admit(&read, team, now_ms).map(|team_id| (team_id, read))
        });
    match admitted {
        Ok((team_id, read)) => {
            counter!("replay_recorder_v4_messages_total", "outcome" => "recorded").increment(1);
            let session = SessionKey {
                team_id,
                session_id: read.session_id.clone(),
            };
            batch.add(message.partition(), message.offset(), session, read);
        }
        Err(skip) => {
            counter!("replay_recorder_v4_messages_total", "outcome" => skip.as_str()).increment(1);
            batch.handled(message.partition(), message.offset());
        }
    }
}

/// Reports what a flush inspected. The writers that store blocks come in the next layers.
fn flush(blocks: &[Block]) {
    counter!("replay_recorder_v4_blocks_total").increment(blocks.len() as u64);
    for block in blocks {
        counter!("replay_recorder_v4_block_events_total").increment(block.stats.event_count);
        if block.stats.cold_start {
            counter!("replay_recorder_v4_cold_start_blocks_total").increment(1);
        }
        if block.stats.orphan_mutations > 0 {
            counter!("replay_recorder_v4_orphan_mutation_blocks_total").increment(1);
        }
    }
}
