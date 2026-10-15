use std::collections::{HashMap, HashSet};
use std::ops::ControlFlow;
use std::sync::Arc;
use std::time::Duration;

use common_liveness::SyncLivenessReporter;
use lifecycle::Handle;
use metrics::{counter, histogram};
use personhog_proto::personhog::types::v1::Person;
use tokio::sync::mpsc;
use tokio::time::Instant;
use tracing::{debug, error, info, warn};

use crate::consumer::FlushBatch;
use crate::kafka::PersonConsumer;
use crate::store::{BatchOutcome, PersonDb, PersonWriteStore};

/// The offset-commit and assignment surface the writer needs from Kafka.
/// Abstracted so the retry loop is testable without a broker.
pub trait OffsetCommitter: Send + Sync {
    fn commit_offsets(&self, offsets: &HashMap<i32, i64>)
        -> Result<(), rdkafka::error::KafkaError>;

    /// `None` while the consumer has not joined its group yet.
    fn assigned_partitions(&self) -> Result<Option<HashSet<i32>>, rdkafka::error::KafkaError>;
}

impl OffsetCommitter for PersonConsumer {
    fn commit_offsets(
        &self,
        offsets: &HashMap<i32, i64>,
    ) -> Result<(), rdkafka::error::KafkaError> {
        PersonConsumer::commit_offsets(self, offsets)
    }

    fn assigned_partitions(&self) -> Result<Option<HashSet<i32>>, rdkafka::error::KafkaError> {
        PersonConsumer::assigned_partitions(self)
    }
}

/// Receives batches from the consumer task, writes to the persistent
/// store, and commits Kafka offsets. Runs on its own tokio task so
/// writes don't block consumption.
pub struct WriterTask<D: PersonDb + 'static, C: OffsetCommitter + 'static> {
    consumer: Arc<C>,
    store: PersonWriteStore<D>,
    flush_rx: mpsc::Receiver<FlushBatch>,
    handle: Handle,
    liveness: Arc<dyn SyncLivenessReporter>,
    consecutive_failures: u32,
}

const MAX_CONSECUTIVE_FAILURES: u32 = 3;
const BASE_BACKOFF: Duration = Duration::from_secs(1);
const MAX_BACKOFF: Duration = Duration::from_secs(5);
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(10);
/// A flush longer than this reports the lane unhealthy. The manager restarts
/// the pod unless the flush completes before its next health check.
const FLUSH_HEALTH_BUDGET: Duration = Duration::from_secs(300);

impl<D: PersonDb + 'static, C: OffsetCommitter + 'static> WriterTask<D, C> {
    pub fn new(
        consumer: Arc<C>,
        store: PersonWriteStore<D>,
        flush_rx: mpsc::Receiver<FlushBatch>,
        handle: Handle,
    ) -> Self {
        let liveness: Arc<dyn SyncLivenessReporter> = Arc::new(handle.clone());
        Self {
            consumer,
            store,
            flush_rx,
            handle,
            liveness,
            consecutive_failures: 0,
        }
    }

    pub async fn run(mut self) {
        info!("Writer task starting");
        let mut heartbeat = tokio::time::interval(HEARTBEAT_INTERVAL);
        let liveness = Arc::clone(&self.liveness);

        loop {
            tokio::select! {
                biased;

                batch = self.flush_rx.recv() => {
                    let Some(batch) = batch else {
                        break;
                    };
                    // Keep the heartbeat ticking during the flush, which can
                    // outlast the liveness deadline on a slow database.
                    let started = Instant::now();
                    let mut over_budget = false;
                    let flush = self.process_batch(batch);
                    tokio::pin!(flush);
                    let flow = loop {
                        tokio::select! {
                            flow = &mut flush => break flow,
                            _ = heartbeat.tick() => {
                                if started.elapsed() < FLUSH_HEALTH_BUDGET {
                                    liveness.report_healthy();
                                } else if !over_budget {
                                    over_budget = true;
                                    warn!(
                                        budget_secs = FLUSH_HEALTH_BUDGET.as_secs(),
                                        "flush exceeded the health budget, reporting the lane unhealthy"
                                    );
                                    liveness.report_unhealthy();
                                }
                            }
                        }
                    };
                    // A failed flush leaves its offsets uncommitted, and
                    // Kafka commits are cumulative per partition — if a
                    // later batch committed, the failed one would be
                    // silently skipped after restart. signal_failure only
                    // starts an async shutdown, so the halt has to be
                    // structural: stop receiving here and now.
                    if flow.is_break() {
                        break;
                    }
                }

                _ = heartbeat.tick() => {
                    liveness.report_healthy();
                }
            }
        }

        info!("Writer task stopped");
    }

    /// Returns `Break` after signaling a failure — the run loop must stop
    /// receiving so no later batch can commit offsets past this one.
    async fn process_batch(&mut self, batch: FlushBatch) -> ControlFlow<()> {
        let FlushBatch {
            mut persons,
            mut offsets,
            oldest_message_ts_ms,
        } = batch;

        // A partition revoked while this batch waited in the channel belongs
        // to another pod now, which re-reads these rows from the last commit.
        match self.consumer.assigned_partitions() {
            Ok(None) => {}
            Ok(Some(assigned)) => {
                let before = persons.len();
                persons.retain(|row| assigned.contains(&row.partition));
                offsets.retain(|partition, _| assigned.contains(partition));
                let dropped = before - persons.len();
                if dropped > 0 {
                    counter!("personhog_writer_revoked_rows_dropped_total", "stage" => "queued")
                        .increment(dropped as u64);
                    info!(rows = dropped, "dropped queued rows for revoked partitions");
                }
            }
            Err(e) => warn!(error = %e, "assignment unavailable, writing the batch unfiltered"),
        }
        if persons.is_empty() {
            return ControlFlow::Continue(());
        }

        let total_rows = persons.len();
        counter!("personhog_writer_flushes_total").increment(1);

        // The leader admits every record against the writer's own rejection
        // surface, so everything here is applyable verbatim. A non-transient
        // failure below is an invariant violation: the flush halts without
        // committing (skipping would permanently diverge PG from the cache
        // and changelog), Kafka redelivers after restart, and the alarm
        // stands until admission's gap is fixed.
        let mut remaining: Vec<Person> = persons.into_iter().map(|row| row.person).collect();
        let mut saturation_rounds: u32 = 0;

        loop {
            let to_process = std::mem::take(&mut remaining);
            match self.store.upsert_batch(to_process).await {
                BatchOutcome::Success => {
                    self.finish(total_rows, &offsets, oldest_message_ts_ms);
                    return ControlFlow::Continue(());
                }

                BatchOutcome::Partial {
                    transient,
                    saturated,
                    data_failed,
                } => {
                    let mut retry = transient;
                    let mut saturated = saturated;
                    if !data_failed.is_empty() {
                        counter!("personhog_writer_batch_fallback_total").increment(1);
                        warn!(
                            rows = data_failed.len(),
                            "batch had data-failed chunks, falling back to per-row"
                        );
                        let fallback = self.store.upsert_rows_parallel(data_failed).await;
                        if !fallback.violations.is_empty() {
                            let first = &fallback.violations[0];
                            self.handle.signal_failure(format!(
                                "{} unapplyable row(s) despite leader admission (first: \
                                 team_id={} person_id={} kind={:?}); refusing to commit",
                                fallback.violations.len(),
                                first.team_id,
                                first.person_id,
                                first.kind
                            ));
                            return ControlFlow::Break(());
                        }
                        retry.extend(fallback.transient);
                        saturated.extend(fallback.saturated);
                    }

                    if retry.is_empty() && saturated.is_empty() {
                        self.finish(total_rows, &offsets, oldest_message_ts_ms);
                        return ControlFlow::Continue(());
                    }

                    let backoff = if retry.is_empty() {
                        // Only saturation: the pool was busy with our own
                        // statements. Waiting is backpressure, not a strike —
                        // counting it toward escalation would let a slow-PG
                        // burst crash-loop the pod, and each restart drops
                        // the buffers and redelivers, worsening the load
                        // that caused the saturation.
                        saturation_rounds += 1;
                        counter!("personhog_writer_saturation_retries_total").increment(1);
                        let backoff = backoff_duration(saturation_rounds);
                        warn!(
                            saturation_rounds,
                            saturated_rows = saturated.len(),
                            backoff_ms = backoff.as_millis() as u64,
                            "pool saturated, retrying without escalation"
                        );
                        backoff
                    } else {
                        // Real transient failures remain — retry with backoff
                        // and count toward escalation.
                        self.consecutive_failures += 1;
                        let backoff = backoff_duration(self.consecutive_failures);
                        error!(
                            consecutive_failures = self.consecutive_failures,
                            transient_rows = retry.len(),
                            backoff_ms = backoff.as_millis() as u64,
                            "transient failures, retrying"
                        );

                        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES {
                            self.handle.signal_failure(format!(
                                "store flush failed {MAX_CONSECUTIVE_FAILURES} consecutive times"
                            ));
                            return ControlFlow::Break(());
                        }
                        backoff
                    };

                    tokio::time::sleep(backoff).await;
                    retry.extend(saturated);
                    remaining = retry;
                }

                BatchOutcome::Fatal(fatal) => {
                    self.handle
                        .signal_failure(format!("upsert_batch fatal: {fatal}"));
                    return ControlFlow::Break(());
                }
            }
        }
    }

    fn finish(&mut self, rows: usize, offsets: &HashMap<i32, i64>, oldest_ts_ms: Option<i64>) {
        self.consecutive_failures = 0;
        self.liveness.report_healthy();
        self.commit_and_record(offsets, oldest_ts_ms, rows);
    }

    fn commit_and_record(
        &self,
        offsets: &HashMap<i32, i64>,
        oldest_ts_ms: Option<i64>,
        rows_written: usize,
    ) {
        if let Err(e) = self.consumer.commit_offsets(offsets) {
            counter!("personhog_writer_offset_commit_errors_total").increment(1);
            error!(error = %e, "failed to commit offsets");
        }

        counter!("personhog_writer_offset_commits_total").increment(1);

        if let Some(ts_ms) = oldest_ts_ms {
            let now_ms = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as i64;
            let latency_ms = now_ms.saturating_sub(ts_ms);
            histogram!("personhog_writer_e2e_latency_ms").record(latency_ms as f64);
        }

        debug!(rows = rows_written, "flushed to store");
    }
}

fn backoff_duration(consecutive_failures: u32) -> Duration {
    let backoff = BASE_BACKOFF * 2u32.saturating_pow(consecutive_failures.saturating_sub(1));
    backoff.min(MAX_BACKOFF)
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    use async_trait::async_trait;
    use lifecycle::{ComponentOptions, Manager};

    use crate::buffer::BufferedPerson;
    use crate::store::{StoreConfig, WriteError, WriteErrorKind};

    /// DB whose chunk calls pop scripted outcomes (None = Ok); an empty
    /// script succeeds.
    struct ScriptedDb {
        responses: Mutex<VecDeque<Option<WriteErrorKind>>>,
        rows_written: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl PersonDb for ScriptedDb {
        async fn execute_chunk(&self, chunk: &[Person]) -> Result<(), WriteError> {
            self.rows_written.fetch_add(chunk.len(), Ordering::SeqCst);
            match self.responses.lock().unwrap().pop_front().flatten() {
                None => Ok(()),
                Some(kind) => Err(WriteError {
                    message: format!("scripted: {kind:?}"),
                    kind,
                }),
            }
        }

        async fn execute_row(&self, _person: &Person) -> Result<(), WriteError> {
            Ok(())
        }
    }

    struct RecordingCommitter {
        commits: Mutex<Vec<HashMap<i32, i64>>>,
        assigned: Option<HashSet<i32>>,
    }

    impl RecordingCommitter {
        fn owning(partitions: &[i32]) -> Self {
            Self {
                commits: Mutex::default(),
                assigned: Some(partitions.iter().copied().collect()),
            }
        }

        fn unjoined() -> Self {
            Self {
                commits: Mutex::default(),
                assigned: None,
            }
        }
    }

    impl Default for RecordingCommitter {
        fn default() -> Self {
            Self::owning(&[0])
        }
    }

    impl OffsetCommitter for RecordingCommitter {
        fn commit_offsets(
            &self,
            offsets: &HashMap<i32, i64>,
        ) -> Result<(), rdkafka::error::KafkaError> {
            self.commits.lock().unwrap().push(offsets.clone());
            Ok(())
        }

        fn assigned_partitions(&self) -> Result<Option<HashSet<i32>>, rdkafka::error::KafkaError> {
            Ok(self.assigned.clone())
        }
    }

    type ScriptedWriter = (
        WriterTask<ScriptedDb, RecordingCommitter>,
        Arc<RecordingCommitter>,
        Arc<AtomicUsize>,
        mpsc::Sender<FlushBatch>,
        Manager,
    );

    fn scripted_writer(responses: Vec<Option<WriteErrorKind>>) -> ScriptedWriter {
        scripted_writer_with(RecordingCommitter::default(), responses)
    }

    fn scripted_writer_with(
        committer: RecordingCommitter,
        responses: Vec<Option<WriteErrorKind>>,
    ) -> ScriptedWriter {
        let committer = Arc::new(committer);
        let rows_written = Arc::new(AtomicUsize::new(0));
        let store = PersonWriteStore::new(
            ScriptedDb {
                responses: Mutex::new(responses.into()),
                rows_written: Arc::clone(&rows_written),
            },
            StoreConfig {
                chunk_size: 100,
                row_fallback_concurrency: 4,
            },
            Arc::new(tokio::sync::Semaphore::new(8)),
        );
        let (tx, rx) = mpsc::channel(1);
        let mut manager = Manager::builder("test").build();
        let handle = manager.register("writer", ComponentOptions::new());
        let writer = WriterTask::new(Arc::clone(&committer), store, rx, handle);
        (writer, committer, rows_written, tx, manager)
    }

    fn row(partition: i32, id: i64) -> BufferedPerson {
        BufferedPerson {
            partition,
            person: Person {
                id,
                team_id: 1,
                version: 1,
                ..Default::default()
            },
        }
    }

    fn batch(rows: i64) -> FlushBatch {
        FlushBatch {
            persons: (0..rows).map(|id| row(0, id)).collect(),
            offsets: HashMap::from([(0, rows - 1)]),
            oldest_message_ts_ms: None,
        }
    }

    #[tokio::test(start_paused = true)]
    async fn saturation_rounds_beyond_the_strike_limit_do_not_halt() {
        // More saturation rounds than MAX_CONSECUTIVE_FAILURES, then success:
        // the batch must complete and commit instead of halting the writer.
        let sat = Some(WriteErrorKind::Saturation);
        let (mut writer, committer, _rows, _tx, _manager) =
            scripted_writer(vec![sat, sat, sat, sat]);

        let flow = writer.process_batch(batch(3)).await;

        assert!(matches!(flow, ControlFlow::Continue(())));
        assert_eq!(committer.commits.lock().unwrap().len(), 1);
        assert_eq!(writer.consecutive_failures, 0);
    }

    #[tokio::test(start_paused = true)]
    async fn transient_rounds_still_halt_at_the_strike_limit() {
        let err = Some(WriteErrorKind::Transient);
        let (mut writer, committer, _rows, _tx, _manager) = scripted_writer(vec![err, err, err]);

        let flow = writer.process_batch(batch(3)).await;

        assert!(matches!(flow, ControlFlow::Break(())));
        assert!(committer.commits.lock().unwrap().is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn queued_batch_is_filtered_by_the_current_assignment() {
        let both: HashMap<i32, i64> = HashMap::from([(0, 1), (1, 4)]);
        let cases = vec![
            (
                "owns 0",
                RecordingCommitter::owning(&[0]),
                2,
                vec![HashMap::from([(0, 1)])],
            ),
            (
                "owns both",
                RecordingCommitter::owning(&[0, 1]),
                3,
                vec![both.clone()],
            ),
            ("not joined", RecordingCommitter::unjoined(), 3, vec![both]),
            ("owns nothing", RecordingCommitter::owning(&[]), 0, vec![]),
        ];
        for (name, committer, rows, commits) in cases {
            let (mut writer, committer, rows_written, _tx, _manager) =
                scripted_writer_with(committer, vec![]);
            let mut queued = batch(2);
            queued.persons.push(row(1, 7));
            queued.offsets.insert(1, 4);

            let flow = writer.process_batch(queued).await;

            assert!(matches!(flow, ControlFlow::Continue(())), "{name}");
            assert_eq!(rows_written.load(Ordering::SeqCst), rows, "{name}");
            assert_eq!(*committer.commits.lock().unwrap(), commits, "{name}");
        }
    }

    #[test]
    fn backoff_doubles_each_failure() {
        assert_eq!(backoff_duration(1), Duration::from_secs(1));
        assert_eq!(backoff_duration(2), Duration::from_secs(2));
        assert_eq!(backoff_duration(3), Duration::from_secs(4));
    }

    #[test]
    fn backoff_caps_at_max() {
        assert_eq!(backoff_duration(4), Duration::from_secs(5));
        assert_eq!(backoff_duration(10), Duration::from_secs(5));
        assert_eq!(backoff_duration(100), Duration::from_secs(5));
    }

    #[test]
    fn backoff_zero_failures_returns_base() {
        assert_eq!(backoff_duration(0), Duration::from_secs(1));
    }

    struct SlowDb {
        delay: Duration,
    }

    #[async_trait]
    impl PersonDb for SlowDb {
        async fn execute_chunk(&self, _chunk: &[Person]) -> Result<(), WriteError> {
            tokio::time::sleep(self.delay).await;
            Ok(())
        }

        async fn execute_row(&self, _person: &Person) -> Result<(), WriteError> {
            Ok(())
        }
    }

    #[derive(Default)]
    struct RecordingLiveness {
        healthy: Mutex<Vec<Instant>>,
        unhealthy: Mutex<Vec<Instant>>,
    }

    impl SyncLivenessReporter for RecordingLiveness {
        fn report_healthy(&self) {
            self.healthy.lock().unwrap().push(Instant::now());
        }

        fn report_unhealthy(&self) {
            self.unhealthy.lock().unwrap().push(Instant::now());
        }
    }

    async fn run_one_flush(flush_len: Duration) -> (Instant, Arc<RecordingLiveness>) {
        let store = PersonWriteStore::new(
            SlowDb { delay: flush_len },
            StoreConfig {
                chunk_size: 100,
                row_fallback_concurrency: 4,
            },
            Arc::new(tokio::sync::Semaphore::new(8)),
        );
        let (tx, rx) = mpsc::channel(1);
        let mut manager = Manager::builder("test").build();
        let handle = manager.register("writer", ComponentOptions::new());
        let liveness = Arc::new(RecordingLiveness::default());
        let mut writer =
            WriterTask::new(Arc::new(RecordingCommitter::default()), store, rx, handle);
        writer.liveness = liveness.clone();

        let started = Instant::now();
        let task = tokio::spawn(writer.run());
        tx.send(batch(1)).await.unwrap();
        tokio::time::sleep(flush_len + HEARTBEAT_INTERVAL).await;
        drop(tx);
        task.await.unwrap();
        (started, liveness)
    }

    fn largest_gap(instants: &[Instant]) -> Duration {
        instants
            .windows(2)
            .map(|pair| pair[1] - pair[0])
            .max()
            .unwrap_or(Duration::MAX)
    }

    #[tokio::test(start_paused = true)]
    async fn long_flush_keeps_the_heartbeat_alive() {
        let flush_len = Duration::from_secs(90);
        let (started, liveness) = run_one_flush(flush_len).await;

        let flush_end = started + flush_len;
        let mut points: Vec<Instant> = liveness
            .healthy
            .lock()
            .unwrap()
            .iter()
            .copied()
            .filter(|t| *t <= flush_end)
            .collect();
        points.insert(0, started);
        points.push(flush_end);
        let gap = largest_gap(&points);
        assert!(
            gap <= 2 * HEARTBEAT_INTERVAL,
            "heartbeat paused for {gap:?} during the flush"
        );
        assert!(liveness.unhealthy.lock().unwrap().is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn flush_past_the_health_budget_reports_unhealthy_once() {
        let flush_len = FLUSH_HEALTH_BUDGET + Duration::from_secs(90);
        let (started, liveness) = run_one_flush(flush_len).await;

        let silent_from = started + FLUSH_HEALTH_BUDGET + HEARTBEAT_INTERVAL;
        let healthy_past_budget = liveness
            .healthy
            .lock()
            .unwrap()
            .iter()
            .filter(|t| **t > silent_from && **t < started + flush_len)
            .count();
        assert_eq!(
            healthy_past_budget, 0,
            "a wedged flush must stop reporting healthy"
        );
        let unhealthy = liveness.unhealthy.lock().unwrap().clone();
        assert_eq!(unhealthy.len(), 1, "a wedged flush reports unhealthy once");
        assert!(
            unhealthy[0] >= started + FLUSH_HEALTH_BUDGET && unhealthy[0] <= silent_from,
            "unhealthy report landed {:?} after the flush started",
            unhealthy[0] - started
        );
    }
}
