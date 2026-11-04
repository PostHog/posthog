//! The consume loop: gate and admit each message from its key and headers, buffer it, and flush on time or size.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::future::Future;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use common_kafka::config::KafkaConfig;
use futures::FutureExt;
use lifecycle::Handle;
use metrics::{counter, histogram};
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, RebalanceProtocol, StreamConsumer,
};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::message::{BorrowedMessage, Headers as _, Message as _};
use rdkafka::types::RDKafkaRespErr;
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use crate::batch::{decoded_len, Batch, Block, Inspectors, Raw, SessionKey, Tp};
use crate::config::{retry_backoff, FLUSH_DEADLINE, MAX_POLL_INTERVAL};
use crate::flush::{write_flush, FlushWork, Writer, PRODUCER_FLUSH_ON_SHUTDOWN};
use crate::limits::{Restrictions, SessionLimiter};
use crate::process::{admit, sampled, Admitted, Headers, Skip};
use crate::teams::TeamCache;
use crate::watermark::{
    assignment_grace, watermark_files, FlushDone, KafkaEnds, Progress, WatermarkFiles,
    WATERMARK_FILE_INTERVAL,
};

const KAFKA_TIMEOUT: Duration = Duration::from_secs(10);
const WATERMARK_READS_TIMEOUT: Duration = Duration::from_secs(30);
const HEARTBEAT: Duration = Duration::from_secs(5);

/// How long offset commits can keep failing before the process exits. A rebalance can wait for one member for the whole
/// poll interval, so this limit outlasts a rebalance. It also limits what a restart reads again.
const COMMIT_GIVE_UP: Duration = Duration::from_secs(2 * MAX_POLL_INTERVAL.as_secs());

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
    assigned_at: HashMap<Tp, Instant>,
    revoked: Vec<Tp>,
    /// Partitions without a known committed offset, with the first offset read once there is one. It stays here until
    /// it commits or the partition is revoked.
    uncommitted: HashMap<Tp, Option<i64>>,
    /// After a failed start commit, the next one waits until then.
    start_retry_at: Option<Instant>,
    /// The next offset and epoch of each partition with stored blocks that are not committed.
    unsettled: HashMap<Tp, (u64, i64)>,
    /// When the offset commits started to fail, and when the last one failed.
    commit_failures: Option<(Instant, Instant)>,
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

    fn owned_since(&self, now: Instant, grace: Duration) -> Vec<(Tp, u64)> {
        self.epochs
            .iter()
            .filter(|(tp, (_, owned))| {
                *owned
                    && self
                        .assigned_at
                        .get(tp)
                        .is_some_and(|at| now.saturating_duration_since(*at) >= grace)
            })
            .map(|(tp, (epoch, _))| (*tp, *epoch))
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

    /// A partition that was revoked is the next owner's, even when it came back under a later epoch.
    fn offsets_due(&mut self, flushed: &HashMap<Tp, (u64, i64)>) -> Vec<(Tp, i64)> {
        self.unsettled.extend(flushed);
        let epochs = &self.epochs;
        self.unsettled.retain(
            |tp, (epoch, _)| matches!(epochs.get(tp), Some(&(current, true)) if current == *epoch),
        );
        self.unsettled
            .iter()
            .map(|(&tp, &(_, offset))| (tp, offset))
            .collect()
    }

    fn offsets_committed(&mut self) {
        // A later offset committed, so a pending start offset is of no use any more.
        for tp in self.unsettled.keys() {
            self.uncommitted.remove(tp);
        }
        self.unsettled.clear();
        self.commit_failures = None;
    }

    fn commit_failed(&mut self, now: Instant) -> Duration {
        let (since, last) = self.commit_failures.get_or_insert((now, now));
        *last = now;
        now.saturating_duration_since(*since)
    }

    fn commit_retry_due(&self, now: Instant, interval: Duration) -> bool {
        self.commit_failures
            .is_some_and(|(_, last)| now.saturating_duration_since(last) >= interval)
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
                    state.assigned_at.insert(tp, Instant::now());
                } else {
                    let entry = state.epochs.entry(tp).or_default();
                    *entry = (entry.0 + 1, false);
                    state.revoked.push(tp);
                    state.uncommitted.remove(&tp);
                    state.assigned_at.remove(&tp);
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

#[derive(Clone)]
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

    /// Commits the next offset of every partition this process still owns under the same assignment, with the offsets
    /// of earlier flushes that did not commit. A failed commit is not retried here, because the rebalance callbacks run
    /// only when the consume loop polls, so a rebalance cannot end while this waits. The blocks are stored, so until a
    /// later commit a failure means only that a new owner or a restart reads them again.
    async fn commit(&self, flushed: &HashMap<Tp, (u64, i64)>) -> Result<(), String> {
        let due = {
            let mut state = self.state.lock().unwrap();
            let due = state.offsets_due(flushed);
            if due.is_empty() {
                state.commit_failures = None;
                return Ok(());
            }
            due
        };
        let mut list = TopicPartitionList::new();
        for (tp, offset) in due {
            list.add_partition_offset(tp.topic, tp.partition, Offset::Offset(offset))
                .map_err(|e| e.to_string())?;
        }
        match self.commit_list(list).await {
            Ok(()) => {
                self.state.lock().unwrap().offsets_committed();
                Ok(())
            }
            Err(error) => {
                counter!("ai_research_v4_recorder_commit_failures_total").increment(1);
                let failing = self.state.lock().unwrap().commit_failed(Instant::now());
                if failing >= COMMIT_GIVE_UP {
                    return Err(format!(
                        "committing offsets failed for {failing:?}: {error}"
                    ));
                }
                tracing::warn!(%error, ?failing, "committing offsets failed, trying again later");
                Ok(())
            }
        }
    }

    fn read_committed(&self, owned: &[Tp]) -> Result<HashMap<Tp, i64>, KafkaError> {
        let mut list = TopicPartitionList::new();
        for tp in owned {
            list.add_partition(tp.topic, tp.partition);
        }
        Ok(self
            .consumer
            .committed_offsets(list, KAFKA_TIMEOUT)?
            .elements()
            .iter()
            .filter_map(|e| match e.offset() {
                Offset::Offset(offset) => Some((
                    self.consumer.context().tp(e.topic(), e.partition())?,
                    offset,
                )),
                _ => None,
            })
            .collect())
    }

    fn read_ends(&self, owned: &[Tp], index_topic: &str) -> Result<KafkaEnds, KafkaError> {
        let deadline = Instant::now() + WATERMARK_READS_TIMEOUT;
        let remaining = || deadline.saturating_duration_since(Instant::now());
        let reads_started_at_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_millis() as i64);
        let mut input_offsets = HashMap::new();
        for tp in owned {
            let (low, high) =
                self.consumer
                    .fetch_watermarks(tp.topic, tp.partition, remaining())?;
            input_offsets.insert(*tp, low..high);
        }
        let mut input_partitions = BTreeMap::new();
        for &topic in &self.consumer.context().topics {
            input_partitions.insert(topic, self.partition_count(topic, remaining())?);
        }
        let mut index_end_offsets = Vec::new();
        for partition in 0..self.partition_count(index_topic, remaining())? {
            let (_, end) =
                self.consumer
                    .fetch_watermarks(index_topic, partition as i32, remaining())?;
            index_end_offsets.push(end);
        }
        Ok(KafkaEnds {
            reads_started_at_ms,
            input_offsets,
            input_partitions,
            index_end_offsets,
        })
    }

    fn partition_count(&self, topic: &str, timeout: Duration) -> Result<usize, KafkaError> {
        let metadata = self.consumer.fetch_metadata(Some(topic), timeout)?;
        match metadata.topics().first() {
            Some(found) if found.error().is_none() && !found.partitions().is_empty() => {
                Ok(found.partitions().len())
            }
            _ => Err(KafkaError::MetadataFetch(
                RDKafkaErrorCode::UnknownTopicOrPartition,
            )),
        }
    }

    async fn retry_commit(&self) -> Result<(), String> {
        self.commit(&HashMap::new()).await
    }

    fn commit_retry_due(&self, interval: Duration) -> bool {
        self.state
            .lock()
            .unwrap()
            .commit_retry_due(Instant::now(), interval)
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

/// A flush holds every decompressed payload until it ends and its size is only checked between polls, so one poll of
/// small compressed messages must not decompress to more than the `room` left in the buffer.
fn take_ready<M, E>(
    first: M,
    room: usize,
    decoded_len: impl Fn(&M) -> usize,
    mut next: impl FnMut() -> Option<Result<M, E>>,
) -> (Vec<M>, Option<E>) {
    let mut room = room.saturating_sub(decoded_len(&first));
    let mut messages = vec![first];
    while messages.len() < POLL_BATCH && room > 0 {
        match next() {
            Some(Ok(message)) => {
                room = room.saturating_sub(decoded_len(&message));
                messages.push(message);
            }
            Some(Err(error)) => return (messages, Some(error)),
            None => break,
        }
    }
    (messages, None)
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
    let watermarks = writer.as_ref().map(|writer| {
        Arc::new(WatermarkFiles {
            progress: Mutex::new(Progress::default()),
            store: writer.store.clone(),
            bucket: writer.rrweb_bucket.clone(),
            index_topic: writer.index_topic.clone(),
            grace: assignment_grace(writer.index_delivery_timeout),
        })
    });
    consume(
        &consumer,
        &settings,
        &sources,
        writer.as_ref(),
        watermarks.as_ref(),
        &handle,
    )
    .await;
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
    watermarks: Option<&Arc<WatermarkFiles>>,
    handle: &Handle,
) {
    let shutdown = handle.shutdown_signal();
    tokio::pin!(shutdown);
    let mut batch = Batch::default();
    let mut inspectors = Inspectors::new(settings.session_state_max_bytes);
    let mut tick = tokio::time::interval(Duration::from_secs(1));
    let mut next_watermark_round = Instant::now() + WATERMARK_FILE_INTERVAL;
    let mut watermark_round: Option<tokio::task::JoinHandle<()>> = None;
    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            _ = tick.tick() => {}
            received = consumer.consumer.recv() => match received {
                Ok(message) => {
                    // The messages Kafka has ready go through the session limiter together, in one Redis round trip.
                    let (messages, failed) = take_ready(
                        message,
                        batch.room(settings.flush_max_bytes),
                        |message| {
                            decoded_len(
                                message.payload().unwrap_or_default(),
                                header(message, "content-encoding"),
                            )
                        },
                        || consumer.consumer.recv().now_or_never(),
                    );
                    handle_messages(&messages, consumer, settings, sources, watermarks, &mut batch)
                        .await;
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
            if let Some(watermarks) = watermarks {
                watermarks
                    .progress
                    .lock()
                    .unwrap()
                    .retain(|tp, epoch| consumer.current_epoch(tp) == Some(epoch));
            }
        }
        // Rounds start here, so a consume loop that stops leaves its files to go stale.
        if let Some(watermarks) = watermarks {
            if Instant::now() >= next_watermark_round
                && watermark_round
                    .as_ref()
                    .is_none_or(|round| round.is_finished())
            {
                next_watermark_round = Instant::now() + WATERMARK_FILE_INTERVAL;
                watermark_round = Some(tokio::spawn(write_watermarks(
                    consumer.clone(),
                    watermarks.clone(),
                )));
            }
        }
        if batch.should_flush(settings.flush_interval, settings.flush_max_bytes) {
            let work = flush(
                std::mem::take(&mut batch),
                &mut inspectors,
                consumer,
                settings,
                writer,
                watermarks.map(|w| &**w),
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
        } else if batch.is_empty() && consumer.commit_retry_due(settings.flush_interval) {
            // Without new messages, no flush comes to commit these offsets.
            if let Err(error) = with_heartbeat(handle, consumer.retry_commit()).await {
                tracing::error!(%error, "commit retry failed");
                handle.signal_failure(error);
                return;
            }
        }
    }
    if batch.is_empty() {
        if let Ok(Err(error)) =
            tokio::time::timeout(settings.shutdown_flush, consumer.retry_commit()).await
        {
            tracing::warn!(%error, "the commit on shutdown failed");
        }
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
            watermarks.map(|w| &**w),
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
    watermarks: Option<&Arc<WatermarkFiles>>,
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
    let mut progress = watermarks.map(|w| w.progress.lock().unwrap());
    for (message, tp, epoch, session) in admitted {
        let session = session.and_then(|session| {
            if blocked.contains(&session) {
                Err(Skip::Blocked)
            } else {
                Ok(session)
            }
        });
        if let Some(progress) = progress.as_mut() {
            progress.handled(
                tp,
                epoch,
                message.offset(),
                message.timestamp().to_millis(),
                session.is_ok(),
            );
        }
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
    watermarks: Option<&WatermarkFiles>,
    handle: &Handle,
    retries: u32,
) -> Result<(), String> {
    let work = flush_steps(
        batch, inspectors, consumer, settings, writer, watermarks, handle, retries,
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
    watermarks: Option<&WatermarkFiles>,
    handle: &Handle,
    retries: u32,
) -> Result<(), String> {
    let flush_started = Instant::now();
    let done = watermarks.map_or_else(FlushDone::default, |w| {
        w.progress.lock().unwrap().flush_started()
    });
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
            let attempt_started = Instant::now();
            let stored = tokio::time::timeout(
                timeout,
                with_heartbeat(
                    handle,
                    write_flush(&blocks, writer, settings.flush_concurrency, &work, &done),
                ),
            )
            .await;
            let outcome = match &stored {
                Ok(Ok(())) => "ok",
                Ok(Err(_)) => "error",
                Err(_) => "timeout",
            };
            histogram!("ai_research_v4_recorder_flush_attempt_duration_seconds", "outcome" => outcome)
                .record(attempt_started.elapsed().as_secs_f64());
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
    histogram!("ai_research_v4_recorder_flush_duration_seconds")
        .record(flush_started.elapsed().as_secs_f64());
    inspectors.evict_idle(settings.session_idle);
    Ok(())
}

/// The committed offsets are read before the progress: a partition that has handled nothing under its assignment by then has committed nothing under it, so its committed offset is past no undelivered index row. The end offsets are read after the progress, so that every index row it counts as delivered is below the index end offsets.
async fn write_watermarks(consumer: RecorderConsumer, watermarks: Arc<WatermarkFiles>) {
    let owned = |consumer: &RecorderConsumer| -> Vec<(Tp, u64)> {
        consumer
            .state
            .lock()
            .unwrap()
            .owned_since(Instant::now(), watermarks.grace)
    };
    let partitions = |owned: &[(Tp, u64)]| -> Vec<Tp> { owned.iter().map(|(tp, _)| *tp).collect() };
    let candidates = partitions(&owned(&consumer));
    if candidates.is_empty() {
        return;
    }
    let reader = consumer.clone();
    let Some(committed) = read_kafka(move || reader.read_committed(&candidates)).await else {
        return;
    };
    // Read again, so that a partition revoked since the committed offsets were read is left out.
    let owned = owned(&consumer);
    let progress: Vec<_> = {
        let progress = watermarks.progress.lock().unwrap();
        owned
            .iter()
            .map(|&(tp, epoch)| (tp, progress.of(tp, epoch)))
            .collect()
    };
    let read = partitions(&owned);
    let index_topic = watermarks.index_topic.clone();
    let Some(ends) = read_kafka(move || consumer.read_ends(&read, &index_topic)).await else {
        return;
    };
    match watermark_files(&progress, &committed, &ends, chrono::Utc::now()) {
        Ok(files) => {
            counter!("ai_research_v4_recorder_watermark_rounds_total", "outcome" => "written")
                .increment(1);
            watermarks.put(files).await;
        }
        Err(error) => tracing::error!(%error, "encoding the watermark files failed"),
    }
}

async fn read_kafka<T: Send + 'static>(
    read: impl FnOnce() -> Result<T, KafkaError> + Send + 'static,
) -> Option<T> {
    let read = tokio::task::spawn_blocking(read)
        .await
        .map_err(|error| error.to_string())
        .and_then(|read| read.map_err(|error| error.to_string()));
    match read {
        Ok(value) => Some(value),
        Err(error) => {
            tracing::warn!(%error, "reading the offsets for the watermark files failed");
            counter!("ai_research_v4_recorder_watermark_rounds_total", "outcome" => "kafka_failed")
                .increment(1);
            None
        }
    }
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
    fn a_poll_stops_taking_messages_once_they_fill_the_room() {
        let mut ready = vec![10usize; 5].into_iter();
        let (messages, failed) =
            take_ready::<usize, ()>(10, 35, |len| *len, || ready.next().map(Ok));
        assert_eq!(messages.len(), 4);
        assert_eq!(failed, None);
        assert_eq!(ready.len(), 2);

        // A full buffer still takes the first message, which `recv` has already removed from the queue.
        let mut ready = vec![10usize; 5].into_iter();
        let (messages, _) = take_ready::<usize, ()>(10, 0, |len| *len, || ready.next().map(Ok));
        assert_eq!(messages.len(), 1);
        assert_eq!(ready.len(), 5);
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
    fn a_partition_gets_watermark_files_only_once_its_assignment_is_older_than_the_grace() {
        let mut state = Assignments::default();
        let assigned = Instant::now();
        let grace = Duration::from_secs(360);
        state.epochs.insert(tp(0), (1, true));
        state.assigned_at.insert(tp(0), assigned);
        state.epochs.insert(tp(1), (1, true));
        state
            .assigned_at
            .insert(tp(1), assigned + Duration::from_secs(1));
        state.epochs.insert(tp(2), (2, false));
        assert_eq!(state.owned_since(assigned + grace, grace), [(tp(0), 1)]);
    }

    #[test]
    fn a_failed_commit_waits_for_the_next_flush_while_the_partition_stays_owned() {
        let mut state = Assignments::default();
        for partition in 0..3 {
            state.epochs.insert(tp(partition), (1, true));
        }
        let due = |state: &mut Assignments, flushed: &[(Tp, (u64, i64))]| {
            let mut due = state.offsets_due(&flushed.iter().copied().collect());
            due.sort_by_key(|(tp, _)| tp.partition);
            due
        };

        let first = [(tp(0), (1, 10)), (tp(1), (1, 10)), (tp(2), (1, 10))];
        assert_eq!(
            due(&mut state, &first),
            [(tp(0), 10), (tp(1), 10), (tp(2), 10)]
        );

        // Partition 0 reads more, partition 1 has no new messages, and partition 2 comes back under a later epoch.
        state.epochs.insert(tp(2), (2, true));
        assert_eq!(
            due(&mut state, &[(tp(0), (1, 20))]),
            [(tp(0), 20), (tp(1), 10)]
        );

        state.epochs.insert(tp(1), (2, false));
        assert_eq!(due(&mut state, &[]), [(tp(0), 20)]);

        state.uncommitted.insert(tp(0), Some(5));
        state.offsets_committed();
        assert!(due(&mut state, &[]).is_empty());
        assert!(state.uncommitted.is_empty());
    }

    #[test]
    fn only_a_success_resets_how_long_the_commits_have_failed() {
        let mut state = Assignments::default();
        let start = Instant::now();
        assert_eq!(state.commit_failed(start), Duration::ZERO);
        assert_eq!(state.commit_failed(start + COMMIT_GIVE_UP), COMMIT_GIVE_UP);
        state.offsets_committed();
        assert_eq!(state.commit_failed(start + COMMIT_GIVE_UP), Duration::ZERO);
    }

    #[test]
    fn an_idle_consumer_retries_a_failed_commit_once_per_interval() {
        let mut state = Assignments::default();
        let start = Instant::now();
        let interval = Duration::from_secs(60);
        assert!(!state.commit_retry_due(start + interval, interval));

        state.commit_failed(start);
        assert!(!state.commit_retry_due(start + interval - Duration::from_secs(1), interval));
        assert!(state.commit_retry_due(start + interval, interval));

        state.commit_failed(start + interval);
        assert!(!state.commit_retry_due(start + interval, interval));

        state.offsets_committed();
        assert!(!state.commit_retry_due(start + 2 * interval, interval));
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
                font_urls: Vec::new(),
                url_limit: None,
                edits: Vec::new(),
                declined: Vec::new(),
                unplaced: false,
                visited_urls: Vec::new(),
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
