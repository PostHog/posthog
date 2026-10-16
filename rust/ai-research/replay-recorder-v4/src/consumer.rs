//! The consume loop: gate and admit each message from its key and headers, buffer it, and flush on time or size.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::future::Future;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, RebalanceProtocol, StreamConsumer,
};
use rdkafka::error::RDKafkaErrorCode;
use rdkafka::message::{BorrowedMessage, Headers as _, Message as _};
use rdkafka::types::RDKafkaRespErr;
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use crate::batch::{Batch, Block, Inspectors, Raw, SessionKey, Tp};
use crate::config::{retry_backoff, FLUSH_DEADLINE, MAX_POLL_INTERVAL};
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

    /// A new group starts at the head of the topic. Assigning that head and committing it before any fetch means a
    /// partition revoked before its first flush sends its next owner to the same offset, past nothing unread.
    fn start_at_heads(&self, consumer: &BaseConsumer<Self>, assigned: &mut TopicPartitionList) {
        // One deadline for the whole assignment, so many slow partitions cannot hold the rebalance past liveness.
        let deadline = Instant::now() + KAFKA_TIMEOUT;
        let remaining = || deadline.saturating_duration_since(Instant::now());
        let committed = match consumer.committed_offsets(assigned.clone(), remaining()) {
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
            let Some(tp) = self.tp(element.topic(), element.partition()) else {
                continue;
            };
            let head = if self.commit_latest && !remaining().is_zero() {
                consumer
                    .fetch_watermarks(tp.topic, tp.partition, remaining())
                    .map_err(|error| tracing::warn!(%error, "reading a partition head failed"))
                    .ok()
            } else {
                None
            };
            let started = head.is_some_and(|(_, high)| {
                let offset = Offset::Offset(high);
                assigned
                    .set_partition_offset(tp.topic, tp.partition, offset)
                    .and_then(|()| heads.add_partition_offset(tp.topic, tp.partition, offset))
                    .map_err(|error| tracing::warn!(%error, "building the starting offsets failed"))
                    .is_ok()
            });
            if !started {
                uncommitted.push(tp);
            }
        }
        if heads.count() > 0 {
            if let Err(error) = consumer.commit(&heads, CommitMode::Sync) {
                // The first message read commits its offset instead.
                tracing::warn!(%error, "committing the starting offsets failed");
                uncommitted.extend(
                    heads
                        .elements()
                        .iter()
                        .filter_map(|e| self.tp(e.topic(), e.partition())),
                );
            }
        }
        self.state.lock().unwrap().uncommitted.extend(uncommitted);
    }

    fn mark(&self, partitions: &TopicPartitionList, assigned: bool) {
        let mut state = self.state.lock().unwrap();
        for element in partitions.elements() {
            if let Some(tp) = self.tp(element.topic(), element.partition()) {
                if assigned {
                    state.epochs.entry(tp).or_default().1 = true;
                } else {
                    let entry = state.epochs.entry(tp).or_default();
                    *entry = (entry.0 + 1, false);
                    state.revoked.push(tp);
                    state.uncommitted.remove(&tp);
                }
            }
        }
    }
}

impl ClientContext for RebalanceContext {}

impl ConsumerContext for RebalanceContext {
    /// rdkafka's own rebalance, with the starting offsets set on the assignment before it is applied.
    fn rebalance(
        &self,
        consumer: &BaseConsumer<Self>,
        err: RDKafkaRespErr,
        partitions: &mut TopicPartitionList,
    ) {
        let cooperative = matches!(
            consumer.rebalance_protocol(),
            RebalanceProtocol::Cooperative
        );
        let applied = if err == RDKafkaRespErr::RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS {
            self.start_at_heads(consumer, partitions);
            self.mark(partitions, true);
            if cooperative {
                consumer.incremental_assign(partitions)
            } else {
                consumer.assign(partitions)
            }
        } else {
            if err != RDKafkaRespErr::RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS {
                tracing::error!(error = %RDKafkaErrorCode::from(err), "rebalancing failed");
            }
            self.mark(partitions, false);
            if cooperative {
                consumer.incremental_unassign(partitions)
            } else {
                consumer.unassign()
            }
        };
        if let Err(error) = applied {
            tracing::error!(%error, "applying a rebalance failed");
        }
    }
}

pub struct RecorderConsumer {
    consumer: Arc<StreamConsumer<RebalanceContext>>,
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
        Ok(Self {
            consumer: Arc::new(consumer),
            state,
        })
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
    async fn commit_start(&self, tp: Tp, offset: i64) {
        if !self.state.lock().unwrap().uncommitted.remove(&tp) {
            return;
        }
        let mut list = TopicPartitionList::new();
        let committed =
            match list.add_partition_offset(tp.topic, tp.partition, Offset::Offset(offset)) {
                Ok(()) => self.commit_list(list).await,
                Err(error) => Err(error.to_string()),
            };
        if let Err(error) = committed {
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
            match self.commit_list(list.clone()).await {
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

    /// A synchronous commit on a blocking thread, so the caller's deadlines and heartbeats keep running. A commit
    /// that outlives `KAFKA_TIMEOUT` can still land later. Its offsets were already stored or read, so it skips nothing.
    async fn commit_list(&self, list: TopicPartitionList) -> Result<(), String> {
        let consumer = self.consumer.clone();
        let commit = tokio::task::spawn_blocking(move || consumer.commit(&list, CommitMode::Sync));
        match tokio::time::timeout(KAFKA_TIMEOUT, commit).await {
            Ok(Ok(committed)) => committed.map_err(|e| e.to_string()),
            Ok(Err(error)) => Err(error.to_string()),
            Err(_) => Err(format!("timed out after {KAFKA_TIMEOUT:?}")),
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
            inspectors.drop_partitions(&revoked);
            batch.retain(|tp, epoch| consumer.current_epoch(tp) == Some(epoch));
        }
        if batch.should_flush(settings.flush_interval, settings.flush_max_bytes) {
            let work = flush(
                std::mem::take(&mut batch),
                &mut inspectors,
                &consumer,
                &settings,
                &sources,
                writer.as_ref(),
                &handle,
                settings.flush_retries,
            );
            tokio::pin!(work);
            let flushed = tokio::select! {
                flushed = &mut work => flushed,
                _ = &mut shutdown => {
                    // The running flush holds the whole buffer, so it goes on under the shutdown deadline.
                    flush_on_shutdown(settings.shutdown_flush, work).await;
                    return;
                }
            };
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
    flush_on_shutdown(
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
}

/// A flush cut off by the deadline before its commit leaves the buffer to the next owner, which reads it again.
async fn flush_on_shutdown(deadline: Duration, work: impl Future<Output = Result<(), String>>) {
    match tokio::time::timeout(deadline, work).await {
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
    consumer.commit_start(tp, message.offset()).await;
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

/// Reports the component healthy while `work` runs. `flush` bounds `work` with a deadline, so a hung flush still ends.
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
/// then commits. All of it ends within `FLUSH_DEADLINE`.
#[allow(clippy::too_many_arguments)]
async fn flush(
    batch: Batch,
    inspectors: &mut Inspectors,
    consumer: &RecorderConsumer,
    settings: &Settings,
    sources: &Sources,
    writer: Option<&Writer>,
    handle: &Handle,
    retries: u32,
) -> Result<(), String> {
    let work = flush_steps(
        batch, inspectors, consumer, settings, sources, writer, handle, retries,
    );
    tokio::time::timeout(FLUSH_DEADLINE, work)
        .await
        .unwrap_or_else(|_| Err(format!("the flush did not end in {FLUSH_DEADLINE:?}")))
}

#[allow(clippy::too_many_arguments)]
async fn flush_steps(
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
    with_heartbeat(handle, consumer.commit(&offsets)).await?;
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

#[cfg(test)]
mod tests {
    use async_trait::async_trait;
    use envconfig::Envconfig;
    use lifecycle::{ComponentOptions, Manager};

    use super::*;

    struct StalledBlocklist;

    #[async_trait]
    impl Blocklist for StalledBlocklist {
        async fn blocked(&self, _: &[SessionKey]) -> HashSet<SessionKey> {
            std::future::pending().await
        }
    }

    #[tokio::test(start_paused = true)]
    async fn a_stalled_blocklist_fails_the_flush_at_the_deadline() {
        let kafka = KafkaConfig::init_from_hashmap(&HashMap::new()).unwrap();
        let consumer =
            RecorderConsumer::new(&kafka, "test", "latest", &["topic".to_owned()]).unwrap();
        let settings = Settings {
            sample_percentage: 100.0,
            flush_interval: Duration::from_secs(60),
            flush_max_bytes: 1 << 20,
            flush_concurrency: 1,
            flush_timeout: Duration::from_secs(60),
            flush_retries: 0,
            shutdown_flush: Duration::from_secs(20),
            session_idle: Duration::from_secs(3600),
            redirecting_topic: None,
        };
        let sources = Sources {
            teams: Arc::new(TeamCache::default()),
            restrictions: Restrictions::default(),
            blocklist: Arc::new(StalledBlocklist),
        };
        let handle = Manager::builder("test")
            .build()
            .register("consumer", ComponentOptions::new());
        let started = tokio::time::Instant::now();
        let flushed = tokio::time::timeout(
            FLUSH_DEADLINE + Duration::from_secs(1),
            flush(
                Batch::default(),
                &mut Inspectors::default(),
                &consumer,
                &settings,
                &sources,
                None,
                &handle,
                0,
            ),
        )
        .await
        .expect("the flush outlived its deadline");
        assert!(flushed.is_err());
        assert_eq!(started.elapsed(), FLUSH_DEADLINE);
    }
}
