use std::time::Duration;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::{parser::parse, types::SinkMsg};

// Cap idle wait inside the recv select! so `report_healthy()` runs on a steady cadence
// regardless of topic traffic. Must stay well below `with_liveness_deadline` set on the
// consumer component in main.rs (60s) so an idle topic never trips the stall counter.
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(15);

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

/// Stage B sink: log every parsed `IndexDoc` and commit its offset. Skips commit
/// without logging. Stage C replaces the body with the OpenSearch `_bulk` writer
/// while keeping the offset-after-ack contract intact.
pub async fn run_sink(
    mut rx: mpsc::Receiver<(SinkMsg, Offset)>,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();
    loop {
        let next = tokio::select! {
            _ = handle.shutdown_recv() => {
                info!("Sink loop shutting down");
                return;
            }
            v = rx.recv() => v,
        };

        let Some((msg, offset)) = next else {
            info!("Channel closed, sink loop exiting");
            return;
        };

        if let SinkMsg::Index(doc) = &msg {
            info!(?doc, "indexed (stage B placeholder)");
        }

        if let Err(e) = offset.store() {
            error!("Failed to store offset after sink: {e}");
        }
    }
}
