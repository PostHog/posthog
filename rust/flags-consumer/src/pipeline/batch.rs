use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::kafka_consumer::Offset;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::config::Config;
use crate::metric_consts;
use crate::pipeline::processor;
use crate::storage::postgres::PostgresStorage;
use crate::types::CdcEvent;

/// Small cache mapping topic name `&str` → `Arc<str>` so we allocate
/// once per unique topic name instead of once per message.
struct TopicInterns(HashMap<Box<str>, Arc<str>>);

impl TopicInterns {
    fn new() -> Self {
        Self(HashMap::new())
    }

    fn get(&mut self, topic: &str) -> Arc<str> {
        if let Some(arc) = self.0.get(topic) {
            return Arc::clone(arc);
        }
        let arc: Arc<str> = Arc::from(topic);
        self.0.insert(Box::from(topic), Arc::clone(&arc));
        arc
    }
}

/// A CDC event paired with its Kafka offset for deferred storage.
pub struct EventWithOffset {
    pub event: CdcEvent,
    pub offset: Offset,
}

/// Highest-watermark tracker for heartbeat writes.
/// Keyed by (topic_name, partition), stores the highest offset seen.
/// Topic names are interned via `Arc<str>` so the key lookup reuses the
/// same allocation instead of heap-allocating a `Box<str>` per message.
type HeartbeatState = HashMap<(Arc<str>, i32), i64>;

/// Run the batch processor loop.
///
/// Drains the shared channel, accumulates events into batches (flushed on
/// size or timeout), and periodically writes heartbeat records.
pub async fn batch_processor_loop(
    mut rx: mpsc::Receiver<EventWithOffset>,
    storage: Arc<PostgresStorage>,
    config: Arc<Config>,
    shutdown: CancellationToken,
    liveness_handle: lifecycle::Handle,
) {
    let mut batch: Vec<EventWithOffset> = Vec::with_capacity(config.batch_size);
    let mut batch_timer = tokio::time::interval(config.batch_timeout());
    let mut heartbeat_timer =
        tokio::time::interval(Duration::from_secs(config.heartbeat_interval_secs));
    let mut heartbeat_state: HeartbeatState = HashMap::new();
    let mut topic_interns = TopicInterns::new();

    // Consume the first immediate tick so timers only fire after the interval.
    batch_timer.tick().await;
    heartbeat_timer.tick().await;

    loop {
        tokio::select! {
            biased;

            _ = shutdown.cancelled() => {
                tracing::info!("batch processor shutting down, flushing final batch");
                if !batch.is_empty() {
                    flush_batch(&mut batch, &storage, &config, &mut heartbeat_state, &mut topic_interns).await;
                }
                flush_heartbeats(&storage, &heartbeat_state).await;
                break;
            }

            _ = batch_timer.tick() => {
                if !batch.is_empty() {
                    flush_batch(&mut batch, &storage, &config, &mut heartbeat_state, &mut topic_interns).await;
                }
                // Report healthy on every tick — an idle consumer is alive.
                liveness_handle.report_healthy();
            }

            _ = heartbeat_timer.tick() => {
                flush_heartbeats(&storage, &heartbeat_state).await;
            }

            msg = rx.recv() => {
                match msg {
                    Some(item) => {
                        track_heartbeat(&item.offset, &mut heartbeat_state, &mut topic_interns);

                        batch.push(item);
                        if batch.len() >= config.batch_size {
                            flush_batch(&mut batch, &storage, &config, &mut heartbeat_state, &mut topic_interns).await;
                            liveness_handle.report_healthy();
                        }
                    }
                    None => {
                        tracing::info!("channel closed, batch processor exiting");
                        break;
                    }
                }
            }
        }
    }
}

/// Update the heartbeat high-watermark for the given offset's (topic, partition).
/// Uses `TopicInterns` to avoid a heap allocation per call — the `Arc<str>`
/// key is cloned (reference count bump) instead of allocating a fresh `Box<str>`.
fn track_heartbeat(offset: &Offset, state: &mut HeartbeatState, interns: &mut TopicInterns) {
    let topic = interns.get(offset.topic());
    let partition = offset.partition();
    let value = offset.get_value();
    state
        .entry((topic, partition))
        .and_modify(|stored| {
            if value > *stored {
                *stored = value;
            }
        })
        .or_insert(value);
}

/// Flush the accumulated batch: process events, store offsets.
///
/// Drains the batch vec — `drain(..)` moves elements out while preserving
/// the backing allocation, so the next batch reuses the same memory.
///
/// `process_batch` takes `EventWithOffset` items directly so it can move
/// events into storage data types without cloning, and returns offsets
/// for storage after processing completes.
async fn flush_batch(
    batch: &mut Vec<EventWithOffset>,
    storage: &PostgresStorage,
    config: &Config,
    heartbeat_state: &mut HeartbeatState,
    topic_interns: &mut TopicInterns,
) {
    let batch_len = batch.len();
    metrics::histogram!(metric_consts::BATCH_SIZE).record(batch_len as f64);

    let offsets = processor::process_batch(batch.drain(..), batch_len, storage, config).await;

    for offset in offsets {
        track_heartbeat(&offset, heartbeat_state, topic_interns);

        if let Err(e) = offset.store() {
            tracing::warn!(error = %e, "failed to store offset");
        }
    }
}

/// Write heartbeat records for all tracked (source, partition) pairs.
async fn flush_heartbeats(storage: &PostgresStorage, state: &HeartbeatState) {
    for ((source, partition), offset) in state {
        if let Err(e) = storage
            .write_heartbeat(source, *partition, *offset, None)
            .await
        {
            tracing::warn!(
                source = &**source,
                partition,
                error = %e,
                "failed to write heartbeat"
            );
        }
    }
}
