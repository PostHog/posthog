//! The consume loop: gate and admit each message from its key and headers, buffer it, and flush on time or size.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::future::Future;
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
use crate::config::{retry_backoff, MAX_POLL_INTERVAL};
use crate::flush::{write_flush, Writer};
use crate::limits::{Blocklist, Restrictions};
use crate::process::{admit, sampled, Admitted, Headers, Skip};
use crate::teams::TeamCache;

const KAFKA_TIMEOUT: Duration = Duration::from_secs(10);
const COMMIT_ATTEMPTS: u32 = 3;
const HEARTBEAT: Duration = Duration::from_secs(5);

/// The assignment state the rebalance callbacks keep. A partition's epoch moves on every revoke, so a message read
/// before the revoke is never mistaken for one read after a new assignment of the same partition.
#[derive(Default)]
struct Assignments {
    epochs: HashMap<Tp, (u64, bool)>,
    revoked: Vec<Tp>,
    /// Partitions without a committed offset whose first message is not read yet.
    uncommitted: HashSet<Tp>,
}

pub struct RebalanceContext {
    topics: Vec<&'static str>,
    commit_latest: bool,
    state: Arc<Mutex<Assignments>>,
}

impl RebalanceContext {
    fn tp(&self, topic: &str, partition: i32) -> Option<Tp> {
        let topic = *self.topics.iter().find(|t| **t == topic)?;
        Some(Tp { topic, partition })
    }

    /// A new group starts at the head of the topic. Committing that head now means a partition revoked before its
    /// first flush does not send its next owner to a later head, past the messages in between.
    fn commit_heads(&self, consumer: &BaseConsumer<Self>, assigned: &TopicPartitionList) {
        let committed = match consumer.committed_offsets(assigned.clone(), KAFKA_TIMEOUT) {
            Ok(committed) => committed,
            Err(error) => {
                tracing::warn!(%error, "reading committed offsets failed");
                return;
            }
        };
        let mut heads = TopicPartitionList::new();
        let mut uncommitted = Vec::new();
        for element in committed.elements() {
            if element.offset() != Offset::Invalid {
                continue;
            }
            uncommitted.extend(self.tp(element.topic(), element.partition()));
            if !self.commit_latest {
                continue;
            }
            match consumer.fetch_watermarks(element.topic(), element.partition(), KAFKA_TIMEOUT) {
                Ok((_, high)) => {
                    if let Err(error) = heads.add_partition_offset(
                        element.topic(),
                        element.partition(),
                        Offset::Offset(high),
                    ) {
                        tracing::warn!(%error, "building the starting offsets failed");
                    }
                }
                Err(error) => tracing::warn!(%error, "reading a partition head failed"),
            }
        }
        if heads.count() > 0 {
            if let Err(error) = consumer.commit(&heads, CommitMode::Sync) {
                tracing::warn!(%error, "committing the starting offsets failed");
            }
        }
        self.state.lock().unwrap().uncommitted.extend(uncommitted);
    }
}

impl ClientContext for RebalanceContext {}

impl ConsumerContext for RebalanceContext {
    fn pre_rebalance(&self, _: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        if let Rebalance::Revoke(partitions) = rebalance {
            let mut state = self.state.lock().unwrap();
            for element in partitions.elements() {
                if let Some(tp) = self.tp(element.topic(), element.partition()) {
                    let entry = state.epochs.entry(tp).or_default();
                    *entry = (entry.0 + 1, false);
                    state.revoked.push(tp);
                    state.uncommitted.remove(&tp);
                }
            }
        }
    }

    fn post_rebalance(&self, consumer: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        if let Rebalance::Assign(partitions) = rebalance {
            {
                let mut state = self.state.lock().unwrap();
                for element in partitions.elements() {
                    if let Some(tp) = self.tp(element.topic(), element.partition()) {
                        state.epochs.entry(tp).or_default().1 = true;
                    }
                }
            }
            self.commit_heads(consumer, partitions);
        }
    }
}

pub struct RecorderConsumer {
    consumer: StreamConsumer<RebalanceContext>,
    state: Arc<Mutex<Assignments>>,
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
            .set("partition.assignment.strategy", "cooperative-sticky")
            // `Config::validate` keeps every flush under this, so the group keeps the partitions while one runs.
            .set(
                "max.poll.interval.ms",
                MAX_POLL_INTERVAL.as_millis().to_string(),
            );
        if kafka.kafka_tls {
            config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }
        if !kafka.kafka_client_rack.is_empty() {
            config.set("client.rack", &kafka.kafka_client_rack);
        }
        let state = Arc::new(Mutex::new(Assignments::default()));
        let consumer: StreamConsumer<RebalanceContext> =
            config.create_with_context(RebalanceContext {
                topics: topics.clone(),
                commit_latest: offset_reset == "latest",
                state: state.clone(),
            })?;
        consumer.subscribe(&topics)?;
        Ok(Self { consumer, state })
    }

    fn take_revoked(&self) -> Vec<Tp> {
        std::mem::take(&mut self.state.lock().unwrap().revoked)
    }

    /// The epoch of a partition this process owns now.
    fn current_epoch(&self, tp: Tp) -> Option<u64> {
        match self.state.lock().unwrap().epochs.get(&tp) {
            Some(&(epoch, true)) => Some(epoch),
            _ => None,
        }
    }

    /// Commits the first offset read on a partition that had none, so a restart before the first flush starts where
    /// this process started, and the flush's `start_offset` stays the same.
    fn commit_start(&self, tp: Tp, offset: i64) {
        if !self.state.lock().unwrap().uncommitted.remove(&tp) {
            return;
        }
        let mut list = TopicPartitionList::new();
        if let Err(error) = list
            .add_partition_offset(tp.topic, tp.partition, Offset::Offset(offset))
            .and_then(|()| {
                tokio::task::block_in_place(|| self.consumer.commit(&list, CommitMode::Sync))
            })
        {
            tracing::warn!(%error, partition = tp.partition, "committing the start offset failed");
        }
    }

    /// Commits the next offset of every partition this process still owns under the same assignment.
    async fn commit(&self, offsets: &HashMap<Tp, (u64, i64)>) -> Result<(), String> {
        let mut list = TopicPartitionList::new();
        for (&tp, &(epoch, offset)) in offsets {
            if self.current_epoch(tp) == Some(epoch) {
                list.add_partition_offset(tp.topic, tp.partition, Offset::Offset(offset))
                    .map_err(|e| e.to_string())?;
            }
        }
        if list.count() == 0 {
            return Ok(());
        }
        let mut attempt = 0;
        loop {
            match tokio::task::block_in_place(|| self.consumer.commit(&list, CommitMode::Sync)) {
                Ok(()) => return Ok(()),
                Err(error) => {
                    counter!("replay_recorder_v4_commit_failures_total").increment(1);
                    attempt += 1;
                    if attempt >= COMMIT_ATTEMPTS {
                        return Err(format!("committing offsets failed: {error}"));
                    }
                    tracing::warn!(%error, attempt, "committing offsets failed");
                    tokio::time::sleep(Duration::from_millis(500 * u64::from(attempt))).await;
                }
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
    pub flush_timeout: Duration,
    pub flush_retries: u32,
    pub shutdown_flush: Duration,
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
                }
            },
        }
        handle.report_healthy();
        let revoked = consumer.take_revoked();
        if !revoked.is_empty() {
            inspectors.drop_partitions(&revoked);
            batch.retain(|tp, epoch| consumer.current_epoch(tp) == Some(epoch));
        }
        if batch.should_flush(settings.flush_interval, settings.flush_max_bytes) {
            let flushed = flush(
                std::mem::take(&mut batch),
                &mut inspectors,
                &consumer,
                &settings,
                &sources,
                writer.as_ref(),
                &handle,
                settings.flush_retries,
            )
            .await;
            if let Err(error) = flushed {
                // Nothing of this flush is committed, so a restart reads it again from the last commit.
                tracing::error!(%error, "flush failed");
                handle.signal_failure(format!("flush failed: {error}"));
                return;
            }
        }
    }
    if batch.is_empty() {
        return;
    }
    // A flush cut off by the deadline commits nothing, so the next owner reads the buffer again.
    let flushed = tokio::time::timeout(
        settings.shutdown_flush,
        flush(
            batch,
            &mut inspectors,
            &consumer,
            &settings,
            &sources,
            writer.as_ref(),
            &handle,
            0,
        ),
    )
    .await;
    match flushed {
        Ok(Ok(())) => tracing::info!("flushed the buffer on shutdown"),
        Ok(Err(error)) => tracing::warn!(%error, "the flush on shutdown failed: nothing committed"),
        Err(_) => {
            tracing::warn!("the flush on shutdown did not fit the grace period: nothing committed")
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
    let Some(epoch) = consumer.current_epoch(tp) else {
        return;
    };
    consumer.commit_start(tp, message.offset());
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
            batch.add(tp, epoch, session, raw);
        }
        Err(skip) => {
            counter!("replay_recorder_v4_messages_total", "outcome" => skip.as_str()).increment(1);
            batch.handled(tp, epoch, message.offset());
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

/// Reports the component healthy while `work` runs. Callers bound `work` with a timeout, so a hung flush still ends.
async fn with_heartbeat<T>(handle: &Handle, work: impl Future<Output = T>) -> T {
    tokio::pin!(work);
    let mut beat = tokio::time::interval(HEARTBEAT);
    loop {
        tokio::select! {
            out = &mut work => return out,
            _ = beat.tick() => handle.report_healthy(),
        }
    }
}

/// Drops blocked sessions, decodes and inspects the rest, stores them with up to `retries` more attempts, and only
/// then commits.
#[allow(clippy::too_many_arguments)]
async fn flush(
    mut batch: Batch,
    inspectors: &mut Inspectors,
    consumer: &RecorderConsumer,
    settings: &Settings,
    sources: &Sources,
    writer: Option<&Writer>,
    handle: &Handle,
    retries: u32,
) -> Result<(), String> {
    let offsets: HashMap<Tp, (u64, i64)> = batch
        .spans
        .iter()
        .map(|(tp, span)| (*tp, (span.epoch, span.last + 1)))
        .collect();
    let sessions: Vec<SessionKey> = batch
        .sessions
        .keys()
        .map(|(session, _)| session.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    // The main lane blocks a session when it first sees it. Checking at the flush gives it that time.
    let blocked = with_heartbeat(handle, sources.blocklist.blocked(&sessions)).await;
    if !blocked.is_empty() {
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
    let blocks = with_heartbeat(
        handle,
        inspectors.inspect(batch, settings.flush_concurrency),
    )
    .await;
    report(&blocks);
    if let Some(writer) = writer {
        let blocks: Vec<Arc<Block>> = blocks.into_iter().map(Arc::new).collect();
        let mut attempt = 0;
        loop {
            let stored = tokio::time::timeout(
                settings.flush_timeout,
                with_heartbeat(
                    handle,
                    write_flush(&blocks, writer, settings.flush_concurrency),
                ),
            )
            .await;
            let error = match stored {
                Ok(Ok(())) => break,
                Ok(Err(error)) => error.to_string(),
                Err(_) => format!("timed out after {:?}", settings.flush_timeout),
            };
            counter!("replay_recorder_v4_flush_failures_total").increment(1);
            attempt += 1;
            if attempt > retries {
                return Err(error);
            }
            tracing::warn!(%error, attempt, "flush attempt failed, trying again");
            with_heartbeat(handle, tokio::time::sleep(retry_backoff(attempt))).await;
        }
    }
    consumer.commit(&offsets).await?;
    inspectors.evict_idle(settings.session_idle);
    Ok(())
}

fn report(blocks: &[Block]) {
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
