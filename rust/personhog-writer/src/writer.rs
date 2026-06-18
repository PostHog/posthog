use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::{counter, histogram};
use personhog_proto::personhog::types::v1::Person;
use tokio::sync::mpsc;
use tracing::{debug, error, info, warn};

use crate::consumer::FlushBatch;
use crate::kafka::{PersonConsumer, WarningsProducer};
use crate::store::{BatchOutcome, IngestionWarning, PersonDb, PersonWriteStore, RowResult};

/// Receives batches from the consumer task, writes to the persistent
/// store, and commits Kafka offsets. Runs on its own tokio task so
/// writes don't block consumption.
pub struct WriterTask<D: PersonDb + 'static> {
    consumer: Arc<PersonConsumer>,
    store: PersonWriteStore<D>,
    flush_rx: mpsc::Receiver<FlushBatch>,
    handle: Handle,
    warnings: Option<WarningsProducer>,
    consecutive_failures: u32,
}

const MAX_CONSECUTIVE_FAILURES: u32 = 3;
const BASE_BACKOFF: Duration = Duration::from_secs(1);
const MAX_BACKOFF: Duration = Duration::from_secs(5);

impl<D: PersonDb + 'static> WriterTask<D> {
    pub fn new(
        consumer: Arc<PersonConsumer>,
        store: PersonWriteStore<D>,
        flush_rx: mpsc::Receiver<FlushBatch>,
        handle: Handle,
        warnings: Option<WarningsProducer>,
    ) -> Self {
        Self {
            consumer,
            store,
            flush_rx,
            handle,
            warnings,
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
                    self.process_batch(batch).await;
                }

                _ = heartbeat.tick() => {
                    self.handle.report_healthy();
                }
            }
        }

        if let Some(producer) = &self.warnings {
            producer.flush(Duration::from_secs(5));
        }
        info!("Writer task stopped");
    }

    async fn process_batch(&mut self, batch: FlushBatch) {
        let FlushBatch {
            persons,
            offsets,
            oldest_message_ts_ms,
        } = batch;
        let total_rows = persons.len();
        counter!("personhog_writer_flushes_total").increment(1);

        // Preflight oversized persons out of the batch. Trimmed survivors
        // rejoin the main path; untrimable ones produce skip warnings.
        let (persons, mut warnings) = self.store.preflight_trim_batch(persons);
        let mut remaining: Vec<Person> = persons;

        loop {
            let to_process = std::mem::take(&mut remaining);
            match self.store.upsert_batch(to_process).await {
                BatchOutcome::Success => {
                    self.finish(total_rows, &offsets, oldest_message_ts_ms, warnings);
                    return;
                }

                BatchOutcome::Partial {
                    transient,
                    data_failed,
                } => {
                    if !data_failed.is_empty() {
                        counter!("personhog_writer_batch_fallback_total").increment(1);
                        warn!(
                            rows = data_failed.len(),
                            "batch had data-failed chunks, falling back to per-row"
                        );
                        for r in self.store.upsert_rows_parallel(data_failed).await {
                            match r {
                                RowResult::Written => {}
                                RowResult::Trimmed(w) | RowResult::Skipped(w) => warnings.push(w),
                            }
                        }
                    }

                    if transient.is_empty() {
                        self.finish(total_rows, &offsets, oldest_message_ts_ms, warnings);
                        return;
                    }

                    // Transient chunks remain — retry just those with backoff.
                    self.consecutive_failures += 1;
                    let backoff = backoff_duration(self.consecutive_failures);
                    error!(
                        consecutive_failures = self.consecutive_failures,
                        transient_rows = transient.len(),
                        backoff_ms = backoff.as_millis() as u64,
                        "transient chunk failures, retrying"
                    );

                    if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES {
                        // Emit warnings for data_failed rows that were already
                        // written in this iteration before we bail. Offsets
                        // won't commit, so Kafka replay will re-emit them, but
                        // losing them when we have them is wrong.
                        self.emit_warnings(&warnings);
                        self.handle.signal_failure(format!(
                            "store flush failed {MAX_CONSECUTIVE_FAILURES} consecutive times"
                        ));
                        return;
                    }

                    tokio::time::sleep(backoff).await;
                    remaining = transient;
                }

                BatchOutcome::Fatal(fatal) => {
                    self.emit_warnings(&warnings);
                    self.handle
                        .signal_failure(format!("upsert_batch fatal: {fatal}"));
                    return;
                }
            }
        }
    }

    fn emit_warnings(&self, warnings: &[IngestionWarning]) {
        if let Some(producer) = &self.warnings {
            for w in warnings {
                producer.emit(w);
            }
        }
    }

    fn finish(
        &mut self,
        rows: usize,
        offsets: &HashMap<i32, i64>,
        oldest_ts_ms: Option<i64>,
        warnings: Vec<IngestionWarning>,
    ) {
        self.emit_warnings(&warnings);
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
            histogram!("personhog_writer_e2e_latency_seconds").record(latency_ms as f64 / 1000.0);
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
