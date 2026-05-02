use std::time::Duration;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::{
    bulk::{BulkBatch, BulkWriter, FlushError, FlushStats},
    parser::parse,
    types::SinkMsg,
};

// Cap idle wait inside the recv select! so `report_healthy()` runs on a steady cadence
// regardless of topic traffic. Must stay well below `with_liveness_deadline` set on the
// consumer component in main.rs (60s) so an idle topic never trips the stall counter.
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(15);

// Timer cadence for the sink's age-based flush check. Independent of the configured
// max-age threshold — the timer just wakes us up to evaluate `should_flush_age`.
// Picking 250ms keeps worst-case flush latency under (max_age + 250ms) without
// burning CPU on a hot loop.
const SINK_TIMER_INTERVAL: Duration = Duration::from_millis(250);

/// Drain `clickhouse_events_json`, classify each event, and forward the result
/// (with its Kafka offset) to the sink so offsets commit in receive order.
///
/// Both `$ai_*` matches and skips travel through the channel — the sink commits
/// each offset only after the message ahead of it on that partition has been
/// processed. Committing offsets in the consumer would let a skipped event at
/// offset N+1 advance the partition past an in-flight `IndexDoc` at offset N
/// that hasn't been written to OpenSearch yet — see plan §"Key correctness
/// divergences from property-defs-rs".
pub async fn run_consumer(
    consumer: SingleTopicConsumer,
    tx: mpsc::Sender<(SinkMsg, Offset)>,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();
    loop {
        handle.report_healthy();

        let recv_result = tokio::select! {
            _ = handle.shutdown_recv() => {
                info!("Consumer loop shutting down");
                return;
            }
            _ = tokio::time::sleep(HEARTBEAT_INTERVAL) => {
                // Idle tick: refresh heartbeat at the top of the next iteration.
                continue;
            }
            r = consumer.json_recv() => r,
        };

        let (event, offset) = match recv_result {
            Ok(r) => r,
            Err(RecvErr::Empty) => {
                warn!("Received empty event from kafka");
                continue;
            }
            Err(RecvErr::Serde(e)) => {
                // kafka_consumer auto-stores poison pills; just log.
                warn!("Failed to deserialize event: {e}");
                continue;
            }
            Err(RecvErr::Kafka(e)) => {
                handle.signal_failure(format!("Kafka error: {e:?}"));
                return;
            }
        };

        let msg = match parse(&event) {
            Ok(Some(doc)) => SinkMsg::Index(Box::new(doc)),
            Ok(None) => SinkMsg::Skip,
            Err(e) => {
                // Stage E will route parse errors to the DLQ. For now, log and skip;
                // the sink will commit the offset so the consumer doesn't wedge.
                error!(uuid = %event.uuid, "Parse error: {e}");
                SinkMsg::Skip
            }
        };

        if tx.send((msg, offset)).await.is_err() {
            info!("Bulk channel closed; consumer loop exiting");
            return;
        }
    }
}

#[derive(Clone, Copy)]
pub struct SinkConfig {
    pub max_batch_bytes: usize,
    pub max_batch_age: Duration,
}

/// Stage C1 sink: accumulate `(IndexDoc | Skip, Offset)` into a `BulkBatch`,
/// flush on either the size or age threshold, and commit offsets after the
/// `_bulk` ack. A non-retryable flush error fails the lifecycle component so
/// the manager can shut the service down loudly.
pub async fn run_sink(
    mut rx: mpsc::Receiver<(SinkMsg, Offset)>,
    handle: lifecycle::Handle,
    writer: BulkWriter,
    config: SinkConfig,
) {
    let _guard = handle.process_scope();
    let mut batch = BulkBatch::new();
    let mut timer = tokio::time::interval(SINK_TIMER_INTERVAL);
    timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => {
                flush_remaining(&writer, &mut batch, "shutdown").await;
                info!("Sink loop shutting down");
                return;
            }
            recv = rx.recv() => {
                let Some((msg, offset)) = recv else {
                    flush_remaining(&writer, &mut batch, "channel closed").await;
                    info!("Channel closed, sink loop exiting");
                    return;
                };
                match msg {
                    SinkMsg::Index(doc) => batch.push_index(*doc, offset),
                    SinkMsg::Skip => batch.push_skip(offset),
                }
                if batch.should_flush_size(config.max_batch_bytes) {
                    if let Err(e) = try_flush(&writer, &mut batch, "size").await {
                        handle.signal_failure(format!("Bulk flush failed (size): {e}"));
                        return;
                    }
                }
            }
            _ = timer.tick() => {
                if batch.should_flush_age(config.max_batch_age) {
                    if let Err(e) = try_flush(&writer, &mut batch, "age").await {
                        handle.signal_failure(format!("Bulk flush failed (age): {e}"));
                        return;
                    }
                }
            }
        }
    }
}

async fn try_flush(
    writer: &BulkWriter,
    batch: &mut BulkBatch,
    trigger: &'static str,
) -> Result<FlushStats, FlushError> {
    let stats = writer.flush(batch).await?;
    info!(
        trigger,
        committed = stats.committed,
        failures = stats.failures,
        "bulk flush succeeded"
    );
    Ok(stats)
}

async fn flush_remaining(writer: &BulkWriter, batch: &mut BulkBatch, reason: &'static str) {
    if batch.is_empty() {
        return;
    }
    match writer.flush(batch).await {
        Ok(stats) => info!(
            reason,
            committed = stats.committed,
            "drained pending batch"
        ),
        Err(e) => error!(reason, error = %e, "drain flush failed"),
    }
}
