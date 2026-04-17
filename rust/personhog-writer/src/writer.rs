use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::StreamConsumer;
use tokio::sync::mpsc;
use tracing::{debug, error, info};

use crate::consumer::FlushBatch;
use crate::kafka::commit_offsets;
use crate::pg::PgWriter;

/// Receives batches from the consumer task, upserts to Postgres, and
/// commits Kafka offsets. Runs on its own tokio task so PG writes
/// don't block consumption.
pub struct WriterTask {
    consumer: Arc<StreamConsumer>,
    writer: PgWriter,
    flush_rx: mpsc::Receiver<FlushBatch>,
    handle: Handle,
    topic: String,
    consecutive_failures: u32,
}

const MAX_CONSECUTIVE_FAILURES: u32 = 3;
const BASE_BACKOFF: Duration = Duration::from_secs(1);
const MAX_BACKOFF: Duration = Duration::from_secs(5);

impl WriterTask {
    pub fn new(
        consumer: Arc<StreamConsumer>,
        writer: PgWriter,
        flush_rx: mpsc::Receiver<FlushBatch>,
        handle: Handle,
        topic: String,
    ) -> Self {
        Self {
            consumer,
            writer,
            flush_rx,
            handle,
            topic,
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

                    let count = batch.persons.len();
                    counter!("personhog_writer_flushes_total").increment(1);

                    match self.writer.batch_upsert(&batch.persons).await {
                        Ok(()) => {
                            self.consecutive_failures = 0;
                            self.handle.report_healthy();

                            if let Err(e) = commit_offsets(&self.consumer, &self.topic, &batch.offsets) {
                                error!(error = %e, "failed to commit offsets");
                            }

                            counter!("personhog_writer_offset_commits_total").increment(1);
                            debug!(rows = count, "flushed to Postgres");
                        }
                        Err(e) => {
                            self.consecutive_failures += 1;
                            let backoff = backoff_duration(self.consecutive_failures);
                            error!(
                                error = %e,
                                consecutive_failures = self.consecutive_failures,
                                rows = count,
                                backoff_ms = backoff.as_millis() as u64,
                                "flush to Postgres failed, offsets not committed"
                            );

                            if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES {
                                self.handle.signal_failure(format!(
                                    "Postgres flush failed {MAX_CONSECUTIVE_FAILURES} consecutive times: {e}"
                                ));
                            }

                            tokio::time::sleep(backoff).await;
                        }
                    }
                }

                _ = heartbeat.tick() => {
                    self.handle.report_healthy();
                }
            }
        }

        info!("Writer task stopped");
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
