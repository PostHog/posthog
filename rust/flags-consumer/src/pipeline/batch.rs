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

/// Interns topic name strings so `HeartbeatState` key lookups don't
/// allocate on every message.
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

pub struct EventWithOffset {
    pub event: CdcEvent,
    pub offset: Offset,
}

/// Highest offset seen per (topic, partition). Used for periodic heartbeat writes.
type HeartbeatState = HashMap<(Arc<str>, i32), i64>;

/// Accumulates events into batches, flushing on size or timeout.
/// Also writes periodic heartbeat records for lag monitoring.
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
                        tracing::info!("channel closed, flushing remaining batch");
                        if !batch.is_empty() {
                            flush_batch(&mut batch, &storage, &config, &mut heartbeat_state, &mut topic_interns).await;
                        }
                        flush_heartbeats(&storage, &heartbeat_state).await;
                        break;
                    }
                }
            }
        }
    }
}

/// Update the heartbeat high-watermark for the given offset's (topic, partition).
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

/// Flush the batch: drain events into the processor, then store offsets.
/// `drain(..)` preserves the vec's allocation for the next batch.
///
/// Offsets are only stored when the batch writes succeed. On failure the
/// offsets are dropped, so Kafka will redeliver those messages on restart.
async fn flush_batch(
    batch: &mut Vec<EventWithOffset>,
    storage: &PostgresStorage,
    config: &Config,
    heartbeat_state: &mut HeartbeatState,
    topic_interns: &mut TopicInterns,
) {
    let batch_len = batch.len();
    metrics::histogram!(metric_consts::BATCH_SIZE).record(batch_len as f64);

    match processor::process_batch(batch.drain(..), batch_len, storage, config).await {
        Ok(offsets) => {
            for offset in offsets {
                track_heartbeat(&offset, heartbeat_state, topic_interns);

                if let Err(e) = offset.store() {
                    tracing::warn!(error = %e, "failed to store offset");
                }
            }
        }
        Err(e) => {
            tracing::error!(
                batch_size = batch_len,
                error = %e,
                "batch write failed, offsets not committed — will reprocess on restart"
            );
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
