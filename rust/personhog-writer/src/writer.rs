use std::collections::HashMap;
use std::ops::ControlFlow;
use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::{counter, histogram};
use personhog_proto::personhog::types::v1::Person;
use tokio::sync::mpsc;
use tracing::{debug, error, info, warn};

use crate::consumer::FlushBatch;
use crate::kafka::PersonConsumer;
use crate::store::{BatchOutcome, PersonDb, PersonWriteStore};

/// The offset-commit surface the writer needs from Kafka. Abstracted so the
/// retry loop is testable without a broker.
pub trait OffsetCommitter: Send + Sync {
    fn commit_offsets(&self, offsets: &HashMap<i32, i64>)
        -> Result<(), rdkafka::error::KafkaError>;
}

impl OffsetCommitter for PersonConsumer {
    fn commit_offsets(
        &self,
        offsets: &HashMap<i32, i64>,
    ) -> Result<(), rdkafka::error::KafkaError> {
        PersonConsumer::commit_offsets(self, offsets)
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
    consecutive_failures: u32,
}

const MAX_CONSECUTIVE_FAILURES: u32 = 3;
const BASE_BACKOFF: Duration = Duration::from_secs(1);
const MAX_BACKOFF: Duration = Duration::from_secs(5);

impl<D: PersonDb + 'static, C: OffsetCommitter + 'static> WriterTask<D, C> {
    pub fn new(
        consumer: Arc<C>,
        store: PersonWriteStore<D>,
        flush_rx: mpsc::Receiver<FlushBatch>,
        handle: Handle,
    ) -> Self {
        Self {
            consumer,
            store,
            flush_rx,
            handle,
            consecutive_failures: 0,
        }
    }

    pub async fn run(mut self) {
        info!("Writer task starting");
        let mut heartbeat = tokio::time::interval(Duration::from_secs(10));

        loop {
            tokio::select! {
                biased;

                batch = self.flush_rx.recv() => {
                    let Some(batch) = batch else {
                        break;
                    };
                    // A failed flush leaves its offsets uncommitted, and
                    // Kafka commits are cumulative per partition — if a
                    // later batch committed, the failed one would be
                    // silently skipped after restart. signal_failure only
                    // starts an async shutdown, so the halt has to be
                    // structural: stop receiving here and now.
                    if self.process_batch(batch).await.is_break() {
                        break;
                    }
                }

                _ = heartbeat.tick() => {
                    self.handle.report_healthy();
                }
            }
        }

        info!("Writer task stopped");
    }

    /// Returns `Break` after signaling a failure — the run loop must stop
    /// receiving so no later batch can commit offsets past this one.
    async fn process_batch(&mut self, batch: FlushBatch) -> ControlFlow<()> {
        let FlushBatch {
            persons,
            offsets,
            oldest_message_ts_ms,
        } = batch;
        let total_rows = persons.len();
        counter!("personhog_writer_flushes_total").increment(1);

        // The leader admits every record against the writer's own rejection
        // surface, so everything here is applyable verbatim. A non-transient
        // failure below is an invariant violation: the flush halts without
        // committing (skipping would permanently diverge PG from the cache
        // and changelog), Kafka redelivers after restart, and the alarm
        // stands until admission's gap is fixed.
        let mut remaining: Vec<Person> = persons;
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
        self.handle.report_healthy();
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
    use std::sync::Mutex;

    use async_trait::async_trait;
    use lifecycle::{ComponentOptions, Manager};

    use crate::store::{StoreConfig, WriteError, WriteErrorKind};

    /// DB whose chunk calls pop scripted outcomes (None = Ok); an empty
    /// script succeeds.
    struct ScriptedDb {
        responses: Mutex<VecDeque<Option<WriteErrorKind>>>,
    }

    #[async_trait]
    impl PersonDb for ScriptedDb {
        async fn execute_chunk(&self, _chunk: &[Person]) -> Result<(), WriteError> {
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

    #[derive(Default)]
    struct RecordingCommitter {
        commits: Mutex<Vec<HashMap<i32, i64>>>,
    }

    impl OffsetCommitter for RecordingCommitter {
        fn commit_offsets(
            &self,
            offsets: &HashMap<i32, i64>,
        ) -> Result<(), rdkafka::error::KafkaError> {
            self.commits.lock().unwrap().push(offsets.clone());
            Ok(())
        }
    }

    fn scripted_writer(
        responses: Vec<Option<WriteErrorKind>>,
    ) -> (
        WriterTask<ScriptedDb, RecordingCommitter>,
        Arc<RecordingCommitter>,
        mpsc::Sender<FlushBatch>,
        Manager,
    ) {
        let committer = Arc::new(RecordingCommitter::default());
        let store = PersonWriteStore::new(
            ScriptedDb {
                responses: Mutex::new(responses.into()),
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
        (writer, committer, tx, manager)
    }

    fn batch(rows: i64) -> FlushBatch {
        FlushBatch {
            persons: (0..rows)
                .map(|id| Person {
                    id,
                    team_id: 1,
                    version: 1,
                    ..Default::default()
                })
                .collect(),
            offsets: HashMap::from([(0, rows - 1)]),
            oldest_message_ts_ms: None,
        }
    }

    #[tokio::test(start_paused = true)]
    async fn saturation_rounds_beyond_the_strike_limit_do_not_halt() {
        // More saturation rounds than MAX_CONSECUTIVE_FAILURES, then success:
        // the batch must complete and commit instead of halting the writer.
        let sat = Some(WriteErrorKind::Saturation);
        let (mut writer, committer, _tx, _manager) = scripted_writer(vec![sat, sat, sat, sat]);

        let flow = writer.process_batch(batch(3)).await;

        assert!(matches!(flow, ControlFlow::Continue(())));
        assert_eq!(committer.commits.lock().unwrap().len(), 1);
        assert_eq!(writer.consecutive_failures, 0);
    }

    #[tokio::test(start_paused = true)]
    async fn transient_rounds_still_halt_at_the_strike_limit() {
        let err = Some(WriteErrorKind::Transient);
        let (mut writer, committer, _tx, _manager) = scripted_writer(vec![err, err, err]);

        let flow = writer.process_batch(batch(3)).await;

        assert!(matches!(flow, ControlFlow::Break(())));
        assert!(committer.commits.lock().unwrap().is_empty());
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
}
