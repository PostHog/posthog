use std::time::{Duration, Instant};

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use rand::Rng;
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

// Per-batch retry-after backoff after a flush observes any retryable items.
// Doubles per consecutive retryable flush; cap keeps worst-case ingestion lag
// bounded so a degraded cluster doesn't push the consumer into runaway lag.
// Reset on a clean flush.
const RETRY_AFTER_INITIAL: Duration = Duration::from_secs(1);
const RETRY_AFTER_MAX: Duration = Duration::from_secs(30);
const RETRY_AFTER_JITTER_MAX: Duration = Duration::from_millis(500);

/// Drain `clickhouse_events_json`, classify each event, and forward the result
/// (with its Kafka offset) to the sink so offsets commit in receive order.
///
/// Both `$ai_*` matches and skips travel through the channel — the sink commits
/// each offset only after the message ahead of it on that partition has been
/// processed. Committing offsets in the consumer would let a skipped event at
/// offset N+1 advance the partition past an in-flight `IndexDoc` at offset N
/// that hasn't been written to OpenSearch yet.
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
                // Log and forward as Skip so the sink commits the offset and
                // the consumer doesn't wedge on a malformed event.
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

/// Tracks how long the sink should wait before the next flush after observing
/// retryable items. Doubles per consecutive retryable flush; resets on clean.
struct RetryGate {
    next_flush_at: Option<Instant>,
    consecutive: u32,
}

impl RetryGate {
    fn new() -> Self {
        Self {
            next_flush_at: None,
            consecutive: 0,
        }
    }

    fn ready(&self) -> bool {
        self.next_flush_at
            .map(|t| Instant::now() >= t)
            .unwrap_or(true)
    }

    fn observe(&mut self, had_retryables: bool) {
        if had_retryables {
            self.consecutive = self.consecutive.saturating_add(1);
            // 2^min(N, 5) caps the exponent at 32x before the duration min hits.
            let scale = 1u32 << self.consecutive.min(5);
            let base = RETRY_AFTER_INITIAL.saturating_mul(scale);
            let capped = base.min(RETRY_AFTER_MAX);
            let jitter_ms =
                rand::thread_rng().gen_range(0..=RETRY_AFTER_JITTER_MAX.as_millis() as u64);
            self.next_flush_at = Some(Instant::now() + capped + Duration::from_millis(jitter_ms));
        } else {
            self.consecutive = 0;
            self.next_flush_at = None;
        }
    }
}

/// A non-retryable flush error fails the lifecycle component so the manager
/// can shut the service down loudly.
pub async fn run_sink(
    mut rx: mpsc::Receiver<(SinkMsg, Offset)>,
    handle: lifecycle::Handle,
    writer: BulkWriter,
    config: SinkConfig,
) {
    let _guard = handle.process_scope();
    let mut batch = BulkBatch::new();
    let mut gate = RetryGate::new();
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
                if gate.ready() && batch.should_flush_size(config.max_batch_bytes) {
                    if let Err(e) = flush_and_track(&writer, &mut batch, "size", &mut gate).await {
                        handle.signal_failure(format!("Bulk flush failed (size): {e}"));
                        return;
                    }
                }
            }
            _ = timer.tick() => {
                if gate.ready() && batch.should_flush_age(config.max_batch_age) {
                    if let Err(e) = flush_and_track(&writer, &mut batch, "age", &mut gate).await {
                        handle.signal_failure(format!("Bulk flush failed (age): {e}"));
                        return;
                    }
                }
            }
        }
    }
}

async fn flush_and_track(
    writer: &BulkWriter,
    batch: &mut BulkBatch,
    trigger: &'static str,
    gate: &mut RetryGate,
) -> Result<FlushStats, FlushError> {
    let stats = writer.flush(batch).await?;
    info!(
        trigger,
        committed_partitions = stats.committed_partitions,
        permanent = stats.permanent_failures,
        retryable = stats.retryable_failures,
        store_failures = stats.store_failures,
        "bulk flush succeeded"
    );
    gate.observe(stats.retryable_failures > 0);
    Ok(stats)
}

async fn flush_remaining(writer: &BulkWriter, batch: &mut BulkBatch, reason: &'static str) {
    if batch.is_empty() {
        return;
    }
    match writer.flush(batch).await {
        Ok(stats) => info!(
            reason,
            committed_partitions = stats.committed_partitions,
            permanent = stats.permanent_failures,
            retryable = stats.retryable_failures,
            store_failures = stats.store_failures,
            "drained pending batch"
        ),
        Err(e) => error!(reason, error = %e, "drain flush failed"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retry_gate_starts_ready() {
        let gate = RetryGate::new();
        assert!(gate.ready());
        assert!(gate.next_flush_at.is_none());
        assert_eq!(gate.consecutive, 0);
    }

    #[test]
    fn retry_gate_sets_deadline_when_retryables_observed() {
        let mut gate = RetryGate::new();
        gate.observe(true);
        assert!(gate.next_flush_at.is_some());
        assert_eq!(gate.consecutive, 1);
        assert!(!gate.ready(), "fresh deadline should be in the future");
    }

    #[test]
    fn retry_gate_resets_on_clean_flush() {
        let mut gate = RetryGate::new();
        gate.observe(true);
        gate.observe(true);
        assert_eq!(gate.consecutive, 2);
        gate.observe(false);
        assert!(gate.next_flush_at.is_none());
        assert_eq!(gate.consecutive, 0);
        assert!(gate.ready());
    }

    #[test]
    fn retry_gate_caps_backoff_at_max_plus_jitter() {
        let mut gate = RetryGate::new();
        for _ in 0..20 {
            gate.observe(true);
        }
        let wait = gate.next_flush_at.unwrap().saturating_duration_since(Instant::now());
        assert!(
            wait <= RETRY_AFTER_MAX + RETRY_AFTER_JITTER_MAX,
            "wait {:?} exceeds cap",
            wait
        );
    }

    #[test]
    fn retry_gate_ready_when_deadline_in_past() {
        let mut gate = RetryGate::new();
        gate.next_flush_at = Some(Instant::now() - Duration::from_secs(1));
        assert!(gate.ready());
    }
}
