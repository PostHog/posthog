use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::{counter, histogram};
use tokio::sync::mpsc;
use tracing::{debug, error, info, warn};

use crate::consumer::FlushBatch;
use crate::kafka::{PersonConsumer, WarningsProducer};
use crate::store::{PersonStore, RowResult, WriteErrorKind};

/// Receives batches from the consumer task, writes to the persistent
/// store, and commits Kafka offsets. Runs on its own tokio task so
/// writes don't block consumption.
pub struct WriterTask<S: PersonStore> {
    consumer: Arc<PersonConsumer>,
    store: S,
    flush_rx: mpsc::Receiver<FlushBatch>,
    handle: Handle,
    warnings: Option<WarningsProducer>,
    consecutive_failures: u32,
}

const MAX_CONSECUTIVE_FAILURES: u32 = 3;
const BASE_BACKOFF: Duration = Duration::from_secs(1);
const MAX_BACKOFF: Duration = Duration::from_secs(5);

impl<S: PersonStore> WriterTask<S> {
    pub fn new(
        consumer: Arc<PersonConsumer>,
        store: S,
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
        let count = batch.persons.len();
        counter!("personhog_writer_flushes_total").increment(1);

        loop {
            match self.store.upsert_batch(&batch.persons).await {
                Ok(()) => {
                    self.consecutive_failures = 0;
                    self.handle.report_healthy();
                    self.commit_and_record(&batch, count);
                    return;
                }
                Err(e) => match e.kind {
                    WriteErrorKind::Data | WriteErrorKind::PropertiesSizeViolation => {
                        // Data error: fall back to per-row inserts to isolate
                        // bad records. The store handles trimming internally.
                        counter!("personhog_writer_batch_fallback_total").increment(1);
                        warn!(rows = count, error = %e, "batch failed, falling back to per-row");

                        let mut succeeded = 0;
                        let mut warnings = Vec::new();
                        for person in &batch.persons {
                            match self.store.upsert_row(person).await {
                                RowResult::Written => succeeded += 1,
                                RowResult::Trimmed(w) => {
                                    succeeded += 1;
                                    warnings.push(w);
                                }
                                RowResult::Skipped(w) => warnings.push(w),
                            }
                        }

                        if let Some(producer) = &self.warnings {
                            for warning in &warnings {
                                producer.emit(warning);
                            }
                        }

                        self.consecutive_failures = 0;
                        self.handle.report_healthy();
                        self.commit_and_record(&batch, succeeded);
                        return;
                    }
                    WriteErrorKind::Transient => {
                        // Transient error: retry the same batch with backoff
                        self.consecutive_failures += 1;
                        let backoff = backoff_duration(self.consecutive_failures);
                        error!(
                            error = %e,
                            consecutive_failures = self.consecutive_failures,
                            rows = count,
                            backoff_ms = backoff.as_millis() as u64,
                            "transient error, retrying batch"
                        );

                        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES {
                            self.handle.signal_failure(format!(
                                "store flush failed {MAX_CONSECUTIVE_FAILURES} consecutive times: {e}"
                            ));
                            return;
                        }

                        tokio::time::sleep(backoff).await;
                        // Loop back to retry the same batch
                    }
                },
            }
        }
    }

    fn commit_and_record(&self, batch: &FlushBatch, rows_written: usize) {
        if let Err(e) = self.consumer.commit_offsets(&batch.offsets) {
            counter!("personhog_writer_offset_commit_errors_total").increment(1);
            error!(error = %e, "failed to commit offsets");
        }

        counter!("personhog_writer_offset_commits_total").increment(1);

        if let Some(ts_ms) = batch.oldest_message_ts_ms {
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
