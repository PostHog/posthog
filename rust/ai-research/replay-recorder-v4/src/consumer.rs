//! The consume loop: gate and admit each message from its key and headers, buffer it, and flush on time or size.

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::message::{BorrowedMessage, Headers as _, Message as _};
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use crate::batch::{Batch, Block, Inspectors, Raw, SessionKey, Tp};
use crate::flush::{write_flush, FlushError, Writer};
use crate::limits::{Blocklist, Restrictions};
use crate::process::{admit, sampled, Admitted, Headers, Skip};
use crate::teams::TeamCache;

/// Records the partitions each rebalance takes away, so the loop can drop what it buffered for them.
pub struct RebalanceContext {
    topics: Vec<&'static str>,
    revoked: Arc<Mutex<Vec<Tp>>>,
}

impl RebalanceContext {
    fn tp(&self, topic: &str, partition: i32) -> Option<Tp> {
        let topic = *self.topics.iter().find(|t| **t == topic)?;
        Some(Tp { topic, partition })
    }
}

impl ClientContext for RebalanceContext {}

impl ConsumerContext for RebalanceContext {
    fn pre_rebalance(&self, _: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        if let Rebalance::Revoke(partitions) = rebalance {
            let revoked = partitions
                .elements()
                .iter()
                .filter_map(|e| self.tp(e.topic(), e.partition()))
                .collect::<Vec<_>>();
            self.revoked.lock().unwrap().extend(revoked);
        }
    }
}

pub struct RecorderConsumer {
    consumer: StreamConsumer<RebalanceContext>,
    revoked: Arc<Mutex<Vec<Tp>>>,
}

impl RecorderConsumer {
    /// `topics` are leaked so a partition is a cheap `Copy` key. There are at most two, created once.
    pub fn new(
        kafka: &KafkaConfig,
        group: &str,
        offset_reset: &str,
        topics: &[String],
    ) -> Result<Self, rdkafka::error::KafkaError> {
        let topics: Vec<&'static str> = topics
            .iter()
            .filter(|t| !t.is_empty())
            .map(|t| &*Box::leak(t.clone().into_boxed_str()))
            .collect();
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
                topics: topics.clone(),
                revoked: revoked.clone(),
            })?;
        consumer.subscribe(&topics)?;
        Ok(Self { consumer, revoked })
    }

    fn take_revoked(&self) -> Vec<Tp> {
        std::mem::take(&mut *self.revoked.lock().unwrap())
    }

    /// Commits the next offset of every partition this process still owns.
    fn commit(&self, offsets: &std::collections::HashMap<Tp, i64>) {
        let assigned = self.consumer.assignment().unwrap_or_default();
        let mut list = TopicPartitionList::new();
        for (&tp, &offset) in offsets {
            if assigned.find_partition(tp.topic, tp.partition).is_some() {
                if let Err(error) =
                    list.add_partition_offset(tp.topic, tp.partition, Offset::Offset(offset + 1))
                {
                    tracing::warn!(%error, partition = tp.partition, "building the offset commit failed");
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
    pub flush_concurrency: usize,
    pub session_idle: Duration,
    /// The main topic, when the main lane moves its force-overflow messages to the overflow topic.
    pub redirecting_topic: Option<String>,
}

/// What the consume loop reads besides Kafka.
pub struct Sources {
    pub teams: Arc<TeamCache>,
    pub restrictions: Restrictions,
    pub blocklist: Arc<dyn Blocklist>,
}

pub async fn run(
    consumer: RecorderConsumer,
    settings: Settings,
    sources: Sources,
    writer: Option<Writer>,
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
                Ok(message) => handle_message(&message, &consumer, &settings, &sources, &mut batch).await,
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
            let mut flushed = std::mem::take(&mut batch);
            drop_blocked(&mut flushed, sources.blocklist.as_ref()).await;
            let (blocks, offsets) = inspectors
                .inspect(flushed, settings.flush_concurrency)
                .await;
            if let Err(error) = flush(blocks, writer.as_ref(), settings.flush_concurrency).await {
                // Nothing of this flush is committed, so a restart reads it again from the last commit.
                tracing::error!(%error, "flush failed");
                handle.signal_failure(format!("flush failed: {error}"));
                break;
            }
            consumer.commit(&offsets);
            inspectors.evict_idle(settings.session_idle);
        }
    }
}

async fn handle_message(
    message: &BorrowedMessage<'_>,
    consumer: &RecorderConsumer,
    settings: &Settings,
    sources: &Sources,
    batch: &mut Batch,
) {
    let Some(tp) = consumer
        .consumer
        .context()
        .tp(message.topic(), message.partition())
    else {
        return;
    };
    match admit_message(message, tp, settings, sources).await {
        Ok(admitted) => {
            counter!("replay_recorder_v4_messages_total", "outcome" => "admitted").increment(1);
            let session = SessionKey {
                team_id: admitted.team_id,
                session_id: admitted.session_id,
            };
            let raw = Raw {
                offset: message.offset(),
                payload: message.payload().unwrap_or_default().to_vec(),
                content_encoding: header(message, "content-encoding").map(str::to_owned),
            };
            batch.add(tp, session, raw);
        }
        Err(skip) => {
            counter!("replay_recorder_v4_messages_total", "outcome" => skip.as_str()).increment(1);
            batch.handled(tp, message.offset());
        }
    }
}

/// Everything before the payload: the gate on the Kafka key, then the headers, restrictions and team.
async fn admit_message(
    message: &BorrowedMessage<'_>,
    tp: Tp,
    settings: &Settings,
    sources: &Sources,
) -> Result<Admitted, Skip> {
    sampled(message.key(), settings.sample_percentage)?;
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as i64);
    let headers = Headers {
        token: header(message, "token"),
        session_id: header(message, "session_id"),
        distinct_id: header(message, "distinct_id"),
        event: header(message, "event"),
        uuid: header(message, "uuid"),
    };
    let restriction = sources.restrictions.get(&headers, now_ms / 1000).await;
    let team = headers.token.and_then(|token| sources.teams.get(token));
    let redirect_overflow = settings.redirecting_topic.as_deref() == Some(tp.topic);
    admit(&headers, restriction, redirect_overflow, team, now_ms)
}

/// Drops the sessions the replay lanes blocked, before anything is decoded. The main lane blocks a session when it
/// first sees it. Checking at the flush gives it that time.
async fn drop_blocked(batch: &mut Batch, blocklist: &dyn Blocklist) {
    let sessions: Vec<SessionKey> = batch
        .sessions
        .keys()
        .map(|(session, _)| session.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let blocked = blocklist.blocked(&sessions).await;
    if blocked.is_empty() {
        return;
    }
    let messages: usize = batch
        .sessions
        .iter()
        .filter(|((session, _), _)| blocked.contains(session))
        .map(|(_, pending)| pending.messages.len())
        .sum();
    counter!("replay_recorder_v4_messages_total", "outcome" => Skip::Blocked.as_str())
        .increment(messages as u64);
    batch
        .sessions
        .retain(|(session, _), _| !blocked.contains(session));
}

/// Stores a flush's blocks, or only reports them when the recorder runs dry.
async fn flush(
    blocks: Vec<Block>,
    writer: Option<&Writer>,
    concurrency: usize,
) -> Result<(), FlushError> {
    counter!("replay_recorder_v4_blocks_total").increment(blocks.len() as u64);
    for block in &blocks {
        counter!("replay_recorder_v4_block_events_total").increment(block.stats.event_count);
        if block.stats.cold_start {
            counter!("replay_recorder_v4_cold_start_blocks_total").increment(1);
        }
        if block.stats.orphan_mutations > 0 {
            counter!("replay_recorder_v4_orphan_mutation_blocks_total").increment(1);
        }
    }
    let Some(writer) = writer else { return Ok(()) };
    let blocks: Vec<Arc<Block>> = blocks.into_iter().map(Arc::new).collect();
    write_flush(&blocks, writer, concurrency).await
}
