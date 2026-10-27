//! The consume loop: gate and admit each message from its key and headers, buffer it, and flush on time or size.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::future::Future;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use futures::FutureExt;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, RebalanceProtocol, StreamConsumer,
};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::message::{BorrowedMessage, Headers as _, Message as _};
use rdkafka::types::RDKafkaRespErr;
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use crate::batch::{Batch, Block, Inspectors, Raw, SessionKey, Tp};
use crate::config::{retry_backoff, FLUSH_DEADLINE, MAX_POLL_INTERVAL};
use crate::flush::{write_flush, FlushWork, Writer, PRODUCER_FLUSH_ON_SHUTDOWN};
use crate::limits::{Restrictions, SessionLimiter};
use crate::process::{admit, sampled, Admitted, Headers, Skip};
use crate::teams::TeamCache;

const KAFKA_TIMEOUT: Duration = Duration::from_secs(10);
const COMMIT_ATTEMPTS: u32 = 3;
const HEARTBEAT: Duration = Duration::from_secs(5);

/// The consumer's `session.timeout.ms`, the replay lanes' value. Past it the group can give the partitions to another
/// process, so a flush stops storing then.
pub const SESSION_TIMEOUT: Duration = Duration::from_secs(90);

/// The most messages read before the limiter decides on their sessions.
const POLL_BATCH: usize = 1000;

/// The assignment state the rebalance callbacks keep. A partition's epoch moves on every revoke, so a message read
/// before the revoke is never mistaken for one read after a new assignment of the same partition.
#[derive(Default)]
struct Assignments {
    epochs: HashMap<Tp, (u64, bool)>,
    revoked: Vec<Tp>,
    /// Partitions without a known committed offset, with the first offset read once there is one. It stays here until
    /// it commits or the partition is revoked.
    uncommitted: HashMap<Tp, Option<i64>>,
    /// After a failed start commit, the next one waits until then.
    start_retry_at: Option<Instant>,
}

/// The pause after a failed start commit, so a broker that does not answer does not stall every message.
const START_RETRY: Duration = Duration::from_secs(5);

impl Assignments {
    /// The start offsets to commit now: all pending ones when `force`, otherwise none during the pause after a failure.
    fn starts_due(&self, now: Instant, force: bool) -> Vec<(Tp, i64)> {
        if !force && self.start_retry_at.is_some_and(|at| now < at) {
            return Vec::new();
        }
        self.uncommitted
            .iter()
            .filter_map(|(&tp, start)| Some((tp, (*start)?)))
            .collect()
    }

    fn starts_committed(&mut self, starts: &[(Tp, i64)], committed: bool, now: Instant) {
        if committed {
            for (tp, offset) in starts {
                if self.uncommitted.get(tp) == Some(&Some(*offset)) {
                    self.uncommitted.remove(tp);
                }
            }
            self.start_retry_at = None;
        } else {
            self.start_retry_at = Some(now + START_RETRY);
        }
    }
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
                // Each partition commits its first offset read instead. Where an offset is committed already, the
                // first message read is at that offset, so the commit does not move it.
                tracing::warn!(%error, "reading committed offsets failed");
                let assigned = assigned
                    .elements()
                    .iter()
                    .filter_map(|e| self.tp(e.topic(), e.partition()))
                    .collect::<Vec<_>>();
                self.state
                    .lock()
                    .unwrap()
                    .uncommitted
                    .extend(assigned.into_iter().map(|tp| (tp, None)));
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
        self.state
            .lock()
            .unwrap()
            .uncommitted
            .extend(uncommitted.into_iter().map(|tp| (tp, None)));
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
            .set(
                "session.timeout.ms",
                SESSION_TIMEOUT.as_millis().to_string(),
            )
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

    /// The main topic comes first. The overflow lane's limiter only counts, so v4's does the same there.
    fn is_main(&self, tp: Tp) -> bool {
        self.consumer.context().topics.first() == Some(&tp.topic)
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
        match self.state.lock().unwrap().uncommitted.get_mut(&tp) {
            Some(start) => {
                start.get_or_insert(offset);
            }
            None => return,
        }
        self.commit_starts(false).await;
    }

    /// Commits the start offsets that are still pending. A failed one is tried again on a later message, and with
    /// `force` before a flush stores anything.
    async fn commit_starts(&self, force: bool) {
        let starts = self.state.lock().unwrap().starts_due(Instant::now(), force);
        if starts.is_empty() {
            return;
        }
        let mut list = TopicPartitionList::new();
        let committed = match starts.iter().try_for_each(|(tp, offset)| {
            list.add_partition_offset(tp.topic, tp.partition, Offset::Offset(*offset))
        }) {
            Ok(()) => self.commit_list(list).await,
            Err(error) => Err(error.to_string()),
        };
        if let Err(error) = &committed {
            tracing::warn!(%error, "committing the start offsets failed");
        }
        self.state
            .lock()
            .unwrap()
            .starts_committed(&starts, committed.is_ok(), Instant::now());
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
                Ok(()) => {
                    // A later offset committed, so a pending start offset is of no use any more.
                    let mut state = self.state.lock().unwrap();
                    for element in list.elements() {
                        if let Some(tp) = self
                            .consumer
                            .context()
                            .tp(element.topic(), element.partition())
                        {
                            state.uncommitted.remove(&tp);
                        }
                    }
                    return Ok(());
                }
                Err(error) => {
                    counter!("ai_research_v4_recorder_commit_failures_total").increment(1);
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
    pub session_state_max_bytes: usize,
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
    consume(&consumer, &settings, &sources, writer.as_ref(), &handle).await;
    // The flushes do not wait for their index rows, so the producer can still hold some.
    if let Some(writer) = &writer {
        writer.flush_producers(PRODUCER_FLUSH_ON_SHUTDOWN).await;
    }
}

async fn consume(
    consumer: &RecorderConsumer,
    settings: &Settings,
    sources: &Sources,
    writer: Option<&Writer>,
    handle: &Handle,
) {
    let shutdown = handle.shutdown_signal();
    tokio::pin!(shutdown);
    let mut batch = Batch::default();
    let mut inspectors = Inspectors::new(settings.session_state_max_bytes);
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
                    handle_messages(&messages, consumer, settings, sources, &mut batch).await;
                    drop(messages);
                    if let Some(error) = failed {
                        if receive_failed(consumer, handle, error) {
                            return;
                        }
                    }
                }
                Err(error) => {
                    if receive_failed(consumer, handle, error) {
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
                consumer,
                settings,
                writer,
                handle,
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
            consumer,
            settings,
            writer,
            handle,
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
        let Some(epoch) = consumer.current_epoch(tp) else {
            continue;
        };
        consumer.commit_start(tp, message.offset()).await;
        let session = admit_message(message, tp, settings, sources)
            .await
            .map(|admitted| SessionKey {
                team_id: admitted.team_id,
                session_id: admitted.session_id,
            });
        admitted.push((message, tp, epoch, session));
    }
    // The limiter decides before anything is buffered, so a blocked session's messages never reach a block.
    let mut sessions: BTreeMap<SessionKey, bool> = BTreeMap::new();
    for (_, tp, _, session) in &admitted {
        if let Ok(session) = session {
            *sessions.entry(session.clone()).or_default() |= consumer.is_main(*tp);
        }
    }
    let blocked = if sessions.is_empty() {
        HashSet::new()
    } else {
        sources.limiter.blocked(&sessions).await
    };
    for (message, tp, epoch, session) in admitted {
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
                    captured_at_ms: message.timestamp().to_millis(),
                    payload: message.payload().unwrap_or_default().to_vec(),
                    content_encoding: header(message, "content-encoding").map(str::to_owned),
                };
                batch.add(tp, epoch, session, raw);
            }
            Err(skip) => {
                counter!("ai_research_v4_recorder_messages_total", "outcome" => skip.as_str())
                    .increment(1);
                batch.handled(tp, epoch, message.offset());
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

/// Decodes and inspects the buffered sessions, stores them with up to `retries` more attempts, and only then commits.
/// All of it ends within `FLUSH_DEADLINE`.
#[allow(clippy::too_many_arguments)]
async fn flush(
    batch: Batch,
    inspectors: &mut Inspectors,
    consumer: &RecorderConsumer,
    settings: &Settings,
    writer: Option<&Writer>,
    handle: &Handle,
    retries: u32,
) -> Result<(), String> {
    let work = flush_steps(
        batch, inspectors, consumer, settings, writer, handle, retries,
    );
    tokio::time::timeout(FLUSH_DEADLINE, work)
        .await
        .unwrap_or_else(|_| Err(format!("the flush did not end in {FLUSH_DEADLINE:?}")))
}

#[allow(clippy::too_many_arguments)]
async fn flush_steps(
    batch: Batch,
    inspectors: &mut Inspectors,
    consumer: &RecorderConsumer,
    settings: &Settings,
    writer: Option<&Writer>,
    handle: &Handle,
    retries: u32,
) -> Result<(), String> {
    let offsets: HashMap<Tp, (u64, i64)> = batch
        .spans
        .iter()
        .map(|(tp, span)| (*tp, (span.epoch, span.last + 1)))
        .collect();
    // Before anything is stored, so a restart after a failed flush reads it again from where this process started.
    with_heartbeat(handle, consumer.commit_starts(true)).await;
    let blocks = with_heartbeat(
        handle,
        inspectors.inspect(batch, settings.flush_concurrency),
    )
    .await;
    report(&blocks);
    if let Some(writer) = writer {
        let mut blocks: Vec<Arc<Block>> = blocks.into_iter().map(Arc::new).collect();
        let work = Arc::new(FlushWork::default());
        let started = Instant::now();
        let mut attempt = 0;
        loop {
            // Readers keep the newest attempt of a flush, so an attempt after this process lost a partition would
            // win over the new owner's flush. It also loses the partitions when the group hears nothing for the
            // session timeout, so no attempt runs past it.
            let owned = still_owned(
                blocks.clone(),
                &offsets,
                consumer.consumer.assignment_lost(),
                |tp| consumer.current_epoch(tp),
            );
            if owned.is_empty() && !blocks.is_empty() {
                tracing::warn!(
                    "the flush lost its partitions: nothing more is written or committed"
                );
                return Ok(());
            }
            blocks = owned;
            let left = SESSION_TIMEOUT.saturating_sub(started.elapsed());
            if left.is_zero() {
                return Err(format!(
                    "the flush did not store its blocks within the session timeout of {SESSION_TIMEOUT:?}"
                ));
            }
            let timeout = settings.flush_timeout.min(left);
            let stored = tokio::time::timeout(
                timeout,
                with_heartbeat(
                    handle,
                    write_flush(&blocks, writer, settings.flush_concurrency, &work),
                ),
            )
            .await;
            let error = match stored {
                Ok(Ok(())) => break,
                Ok(Err(error)) => error.to_string(),
                Err(_) => format!("timed out after {timeout:?}"),
            };
            counter!("ai_research_v4_recorder_flush_failures_total").increment(1);
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

/// The blocks this process may still write: none once the group took its assignment away, and otherwise those of the
/// partitions it still owns under the assignment the flush read them in.
fn still_owned(
    blocks: Vec<Arc<Block>>,
    offsets: &HashMap<Tp, (u64, i64)>,
    lost: bool,
    current_epoch: impl Fn(Tp) -> Option<u64>,
) -> Vec<Arc<Block>> {
    if lost {
        return Vec::new();
    }
    blocks
        .into_iter()
        .filter(|block| {
            let tp = block.origin.tp;
            offsets
                .get(&tp)
                .is_some_and(|&(epoch, _)| current_epoch(tp) == Some(epoch))
        })
        .collect()
}

fn report(blocks: &[Block]) {
    counter!("ai_research_v4_recorder_blocks_total").increment(blocks.len() as u64);
    for block in blocks {
        counter!("ai_research_v4_recorder_block_events_total").increment(block.stats.event_count);
        if block.stats.cold_start {
            counter!("ai_research_v4_recorder_cold_start_blocks_total").increment(1);
        }
        if block.stats.orphan_mutations > 0 {
            counter!("ai_research_v4_recorder_orphan_mutation_blocks_total").increment(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use replay_core_v4::inspect::stats::BlockStats;

    use super::*;
    use crate::batch::Origin;

    fn tp(partition: i32) -> Tp {
        Tp {
            topic: "main",
            partition,
        }
    }

    #[test]
    fn a_failed_start_commit_stays_pending_at_the_first_offset() {
        let mut state = Assignments::default();
        state.uncommitted.insert(tp(0), None);
        state.uncommitted.get_mut(&tp(0)).unwrap().get_or_insert(10);
        let now = Instant::now();
        let starts = state.starts_due(now, false);
        assert_eq!(starts, [(tp(0), 10)]);
        state.starts_committed(&starts, false, now);

        // A later message does not move the start, and waits for the pause unless the flush forces it.
        state.uncommitted.get_mut(&tp(0)).unwrap().get_or_insert(11);
        assert!(state.starts_due(now, false).is_empty());
        assert_eq!(state.starts_due(now, true), [(tp(0), 10)]);
        let starts = state.starts_due(now + START_RETRY, false);
        assert_eq!(starts, [(tp(0), 10)]);
        state.starts_committed(&starts, true, now);
        assert!(state.uncommitted.is_empty());
    }

    #[test]
    fn a_retry_writes_only_the_partitions_this_process_still_owns() {
        let block = |partition: i32| {
            Arc::new(Block {
                session: SessionKey {
                    team_id: 7,
                    session_id: "s".to_owned(),
                },
                origin: Origin {
                    tp: tp(partition),
                    start_offset: 0,
                    end_offset: 0,
                    flush_end_offset: 0,
                },
                messages: Vec::new(),
                stats: BlockStats::default(),
                moments: Vec::new(),
                image_urls: Vec::new(),
                remote_urls: Vec::new(),
                url_limit: None,
                captured_at_ms: None,
            })
        };
        let offsets = HashMap::from([(tp(0), (1, 5)), (tp(1), (1, 5)), (tp(2), (1, 5))]);
        // Partition 1 was assigned again, and partition 2 was revoked.
        let epochs = HashMap::from([(tp(0), 1), (tp(1), 2)]);
        let owned = |lost: bool| -> Vec<i32> {
            still_owned(vec![block(0), block(1), block(2)], &offsets, lost, |tp| {
                epochs.get(&tp).copied()
            })
            .iter()
            .map(|b| b.origin.tp.partition)
            .collect()
        };
        assert_eq!(owned(false), [0]);
        assert!(owned(true).is_empty());
    }
}
