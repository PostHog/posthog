use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::config::Config;
use crate::metric_consts;
use crate::processor;
use crate::storage::postgres::PostgresStorage;
use crate::types::{CdcEvent, KafkaMessage};

/// A CDC event paired with its Kafka offset for deferred storage.
pub struct EventWithOffset {
    pub event: CdcEvent,
    pub offset: Offset,
}

/// Highest-watermark tracker for heartbeat writes.
/// Keyed by (topic, partition), stores offset. Topic uses `Box<str>` since
/// it's read-only after construction.
type HeartbeatState = HashMap<(Box<str>, i32), i64>;

/// Run a single-topic consumer loop, generic over the message type.
///
/// `M` must implement [`KafkaMessage`], which provides the deserialization
/// target, the `team_id()` accessor for early filtering, the `classify()`
/// method to convert raw messages into [`CdcEvent`]s, and the `SOURCE`
/// label for metrics.
///
/// Monomorphised at compile time — no dynamic dispatch, no vtable overhead.
pub async fn consume_loop<M: KafkaMessage>(
    consumer: SingleTopicConsumer,
    tx: mpsc::Sender<EventWithOffset>,
    team_filter: Option<HashSet<i32>>,
    shutdown: CancellationToken,
) {
    loop {
        tokio::select! {
            biased;
            _ = shutdown.cancelled() => {
                tracing::info!("{} consumer shutting down", M::SOURCE);
                break;
            }
            result = consumer.json_recv::<M>() => {
                match result {
                    Ok((msg, offset)) => {
                        metrics::counter!(metric_consts::MESSAGES_RECEIVED, "source" => M::SOURCE)
                            .increment(1);

                        if let Some(ref filter) = team_filter {
                            if !filter.contains(&msg.team_id()) {
                                offset.store().expect("failed to store filtered offset");
                                metrics::counter!(metric_consts::MESSAGES_FILTERED, "source" => M::SOURCE)
                                    .increment(1);
                                continue;
                            }
                        }

                        let event = msg.classify();
                        if tx.send(EventWithOffset { event, offset }).await.is_err() {
                            tracing::info!("{} channel closed, exiting", M::SOURCE);
                            break;
                        }
                    }
                    Err(RecvErr::Serde(e)) => {
                        tracing::warn!("{} serde error (poison pill skipped): {e}", M::SOURCE);
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => M::SOURCE, "reason" => "serde")
                            .increment(1);
                    }
                    Err(RecvErr::Empty) => {
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => M::SOURCE, "reason" => "empty")
                            .increment(1);
                    }
                    Err(RecvErr::Kafka(e)) => {
                        tracing::error!("{} kafka error: {e}", M::SOURCE);
                        metrics::counter!(metric_consts::KAFKA_ERRORS, "source" => M::SOURCE).increment(1);
                        tokio::time::sleep(Duration::from_millis(100)).await;
                    }
                }
            }
        }
    }
}

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

    // Consume the first immediate tick so timers only fire after the interval.
    batch_timer.tick().await;
    heartbeat_timer.tick().await;

    loop {
        tokio::select! {
            biased;

            _ = shutdown.cancelled() => {
                tracing::info!("batch processor shutting down, flushing final batch");
                if !batch.is_empty() {
                    flush_batch(&mut batch, &storage, &config, &mut heartbeat_state).await;
                }
                flush_heartbeats(&storage, &heartbeat_state).await;
                break;
            }

            _ = batch_timer.tick() => {
                if !batch.is_empty() {
                    flush_batch(&mut batch, &storage, &config, &mut heartbeat_state).await;
                    liveness_handle.report_healthy();
                }
            }

            _ = heartbeat_timer.tick() => {
                flush_heartbeats(&storage, &heartbeat_state).await;
            }

            msg = rx.recv() => {
                match msg {
                    Some(item) => {
                        // Track heartbeat watermarks from every received message.
                        track_heartbeat(&item.offset, &mut heartbeat_state);

                        batch.push(item);
                        if batch.len() >= config.batch_size {
                            flush_batch(&mut batch, &storage, &config, &mut heartbeat_state).await;
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
fn track_heartbeat(offset: &Offset, state: &mut HeartbeatState) {
    let topic = Box::from(offset.topic());
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
) {
    let batch_len = batch.len();
    metrics::histogram!(metric_consts::BATCH_SIZE).record(batch_len as f64);

    let offsets = processor::process_batch(batch.drain(..), batch_len, storage, config).await;

    for offset in offsets {
        track_heartbeat(&offset, heartbeat_state);

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
                source,
                partition,
                error = %e,
                "failed to write heartbeat"
            );
        }
    }
}
