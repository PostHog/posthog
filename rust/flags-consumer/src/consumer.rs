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
use crate::types::{
    classify_distinct_id_message, classify_person_message, CdcEvent, DistinctIdMessage,
    PersonMessage,
};

/// A CDC event paired with its Kafka offset for deferred storage.
pub struct EventWithOffset {
    pub event: CdcEvent,
    pub offset: Offset,
}

/// Highest-watermark tracker for heartbeat writes.
/// Keyed by (topic, partition), stores offset. Topic uses `Box<str>` since
/// it's read-only after construction.
type HeartbeatState = HashMap<(Box<str>, i32), i64>;

/// Run the person-topic consumer loop.
///
/// Receives messages from `clickhouse_person`, classifies them, and sends
/// them to the shared channel. Filtered messages have their offsets stored
/// immediately so the consumer group doesn't lag.
pub async fn consume_person_loop(
    consumer: SingleTopicConsumer,
    tx: mpsc::Sender<EventWithOffset>,
    team_filter: Option<HashSet<i32>>,
    shutdown: CancellationToken,
) {
    const SOURCE: &str = "person";

    loop {
        tokio::select! {
            biased;
            _ = shutdown.cancelled() => {
                tracing::info!("{SOURCE} consumer shutting down");
                break;
            }
            result = consumer.json_recv::<PersonMessage>() => {
                match result {
                    Ok((msg, offset)) => {
                        metrics::counter!(metric_consts::MESSAGES_RECEIVED, "source" => SOURCE)
                            .increment(1);

                        if let Some(ref filter) = team_filter {
                            if !filter.contains(&msg.team_id) {
                                offset.store().expect("failed to store filtered offset");
                                metrics::counter!(metric_consts::MESSAGES_FILTERED, "source" => SOURCE)
                                    .increment(1);
                                continue;
                            }
                        }

                        let event = classify_person_message(msg);
                        if tx.send(EventWithOffset { event, offset }).await.is_err() {
                            tracing::info!("{SOURCE} channel closed, exiting");
                            break;
                        }
                    }
                    Err(RecvErr::Serde(e)) => {
                        tracing::warn!("{SOURCE} serde error (poison pill skipped): {e}");
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => SOURCE, "reason" => "serde")
                            .increment(1);
                    }
                    Err(RecvErr::Empty) => {
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => SOURCE, "reason" => "empty")
                            .increment(1);
                    }
                    Err(RecvErr::Kafka(e)) => {
                        tracing::error!("{SOURCE} kafka error: {e}");
                        metrics::counter!(metric_consts::KAFKA_ERRORS, "source" => SOURCE).increment(1);
                        tokio::time::sleep(Duration::from_millis(100)).await;
                    }
                }
            }
        }
    }
}

/// Run the distinct-ID-topic consumer loop.
///
/// Same structure as `consume_person_loop` but for the
/// `clickhouse_person_distinct_id` topic.
pub async fn consume_distinct_id_loop(
    consumer: SingleTopicConsumer,
    tx: mpsc::Sender<EventWithOffset>,
    team_filter: Option<HashSet<i32>>,
    shutdown: CancellationToken,
) {
    const SOURCE: &str = "distinct_id";

    loop {
        tokio::select! {
            biased;
            _ = shutdown.cancelled() => {
                tracing::info!("{SOURCE} consumer shutting down");
                break;
            }
            result = consumer.json_recv::<DistinctIdMessage>() => {
                match result {
                    Ok((msg, offset)) => {
                        metrics::counter!(metric_consts::MESSAGES_RECEIVED, "source" => SOURCE)
                            .increment(1);

                        if let Some(ref filter) = team_filter {
                            if !filter.contains(&msg.team_id) {
                                offset.store().expect("failed to store filtered offset");
                                metrics::counter!(metric_consts::MESSAGES_FILTERED, "source" => SOURCE)
                                    .increment(1);
                                continue;
                            }
                        }

                        let event = classify_distinct_id_message(msg);
                        if tx.send(EventWithOffset { event, offset }).await.is_err() {
                            tracing::info!("{SOURCE} channel closed, exiting");
                            break;
                        }
                    }
                    Err(RecvErr::Serde(e)) => {
                        tracing::warn!("{SOURCE} serde error (poison pill skipped): {e}");
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => SOURCE, "reason" => "serde")
                            .increment(1);
                    }
                    Err(RecvErr::Empty) => {
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => SOURCE, "reason" => "empty")
                            .increment(1);
                    }
                    Err(RecvErr::Kafka(e)) => {
                        tracing::error!("{SOURCE} kafka error: {e}");
                        metrics::counter!(metric_consts::KAFKA_ERRORS, "source" => SOURCE).increment(1);
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
                        let topic = Box::from(item.offset.topic());
                        let partition = item.offset.partition();
                        let offset = item.offset.get_value();
                        heartbeat_state
                            .entry((topic, partition))
                            .and_modify(|stored| {
                                if offset > *stored {
                                    *stored = offset;
                                }
                            })
                            .or_insert(offset);

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

/// Flush the accumulated batch: process events, then store offsets.
///
/// On failure (retries exhausted), offsets are still stored to avoid
/// blocking the pipeline. This is acceptable for the POC — we log the
/// error and move on.
async fn flush_batch(
    batch: &mut Vec<EventWithOffset>,
    storage: &PostgresStorage,
    config: &Config,
    heartbeat_state: &mut HeartbeatState,
) {
    let batch_len = batch.len();
    metrics::histogram!(metric_consts::BATCH_SIZE).record(batch_len as f64);

    let events: Vec<CdcEvent> = batch.iter().map(|e| e.event.clone()).collect();

    match processor::process_batch(&events, storage, config).await {
        Ok(()) => {
            tracing::debug!(batch_size = batch_len, "batch processed successfully");
        }
        Err(e) => {
            tracing::error!(batch_size = batch_len, error = %e, "batch processing failed, skipping");
        }
    }

    // Store offsets regardless of processing outcome. For the POC we
    // prefer forward progress over reprocessing failed batches.
    for item in batch.drain(..) {
        // Update heartbeat watermarks one final time from the batch.
        let topic = Box::from(item.offset.topic());
        let partition = item.offset.partition();
        let offset = item.offset.get_value();
        heartbeat_state
            .entry((topic, partition))
            .and_modify(|stored| {
                if offset > *stored {
                    *stored = offset;
                }
            })
            .or_insert(offset);

        if let Err(e) = item.offset.store() {
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
