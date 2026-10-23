//! The consume loop: gate and admit each message from its key and headers, buffer it, and flush on time or size.

use std::collections::{BTreeMap, HashSet};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use futures::FutureExt;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::error::KafkaError;
use rdkafka::message::{BorrowedMessage, Headers as _, Message as _};
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use crate::batch::{Batch, Block, Inspectors, Raw, SessionKey, Tp};
use crate::flush::{write_flush, FlushError, Writer};
use crate::limits::{Restrictions, SessionLimiter};
use crate::process::{admit, sampled, Admitted, Headers, Skip};
use crate::teams::TeamCache;

/// The most messages read before the limiter decides on their sessions.
const POLL_BATCH: usize = 1000;

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

    /// The main topic comes first. The overflow lane's limiter only counts, so v4's does the same there.
    fn is_main(&self, tp: Tp) -> bool {
        self.consumer.context().topics.first() == Some(&tp.topic)
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
                counter!("ai_research_v4_recorder_commit_failures_total").increment(1);
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
    pub limiter: SessionLimiter,
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
                Ok(message) => {
                    // The messages Kafka has ready go through the session limiter together, in one Redis round trip.
                    let mut messages = vec![message];
                    let mut failed = None;
                    while messages.len() < POLL_BATCH {
                        match consumer.consumer.recv().now_or_never() {
                            Some(Ok(message)) => messages.push(message),
                            Some(Err(error)) => {
                                failed = Some(error);
                                break;
                            }
                            None => break,
                        }
                    }
                    handle_messages(&messages, &consumer, &settings, &sources, &mut batch).await;
                    drop(messages);
                    if let Some(error) = failed {
                        if receive_failed(&consumer, &handle, error) {
                            return;
                        }
                    }
                }
                Err(error) => {
                    if receive_failed(&consumer, &handle, error) {
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
            let (blocks, offsets) = inspectors
                .inspect(std::mem::take(&mut batch), settings.flush_concurrency)
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

/// Returns true when the error disabled the client for good, so only a restart recovers.
fn receive_failed(consumer: &RecorderConsumer, handle: &Handle, error: KafkaError) -> bool {
    tracing::warn!(%error, "kafka receive failed");
    counter!("ai_research_v4_recorder_kafka_errors_total").increment(1);
    match consumer.consumer.client().fatal_error() {
        Some((code, reason)) => {
            handle.signal_failure(format!("kafka consumer fatal error {code}: {reason}"));
            true
        }
        None => false,
    }
}

async fn handle_messages(
    messages: &[BorrowedMessage<'_>],
    consumer: &RecorderConsumer,
    settings: &Settings,
    sources: &Sources,
    batch: &mut Batch,
) {
    let mut admitted = Vec::with_capacity(messages.len());
    for message in messages {
        let Some(tp) = consumer
            .consumer
            .context()
            .tp(message.topic(), message.partition())
        else {
            continue;
        };
        let session = admit_message(message, tp, settings, sources)
            .await
            .map(|admitted| SessionKey {
                team_id: admitted.team_id,
                session_id: admitted.session_id,
            });
        admitted.push((message, tp, session));
    }
    // The limiter decides before anything is buffered, so a blocked session's messages never reach a block.
    let mut sessions: BTreeMap<SessionKey, bool> = BTreeMap::new();
    for (_, tp, session) in &admitted {
        if let Ok(session) = session {
            *sessions.entry(session.clone()).or_default() |= consumer.is_main(*tp);
        }
    }
    let blocked = if sessions.is_empty() {
        HashSet::new()
    } else {
        sources.limiter.blocked(&sessions).await
    };
    for (message, tp, session) in admitted {
        let session = session.and_then(|session| {
            if blocked.contains(&session) {
                Err(Skip::Blocked)
            } else {
                Ok(session)
            }
        });
        match session {
            Ok(session) => {
                counter!("ai_research_v4_recorder_messages_total", "outcome" => "admitted")
                    .increment(1);
                let raw = Raw {
                    offset: message.offset(),
                    payload: message.payload().unwrap_or_default().to_vec(),
                    content_encoding: header(message, "content-encoding").map(str::to_owned),
                };
                batch.add(tp, session, raw);
            }
            Err(skip) => {
                counter!("ai_research_v4_recorder_messages_total", "outcome" => skip.as_str())
                    .increment(1);
                batch.handled(tp, message.offset());
            }
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

/// Stores a flush's blocks, or only reports them when the recorder runs dry.
async fn flush(
    blocks: Vec<Block>,
    writer: Option<&Writer>,
    concurrency: usize,
) -> Result<(), FlushError> {
    counter!("ai_research_v4_recorder_blocks_total").increment(blocks.len() as u64);
    for block in &blocks {
        counter!("ai_research_v4_recorder_block_events_total").increment(block.stats.event_count);
        if block.stats.cold_start {
            counter!("ai_research_v4_recorder_cold_start_blocks_total").increment(1);
        }
        if block.stats.orphan_mutations > 0 {
            counter!("ai_research_v4_recorder_orphan_mutation_blocks_total").increment(1);
        }
    }
    let Some(writer) = writer else { return Ok(()) };
    let blocks: Vec<Arc<Block>> = blocks.into_iter().map(Arc::new).collect();
    write_flush(&blocks, writer, concurrency).await
}
