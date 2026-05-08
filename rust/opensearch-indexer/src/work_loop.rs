use std::ops::ControlFlow;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use common_redis::{Client, CustomRedisError};
use rand::Rng;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use crate::{
    bulk::{BulkBatch, BulkWriter, FlushError, FlushStats},
    parser::parse,
    sampling::{decide, Decision, SamplingConfig},
    types::{IndexDoc, SinkMsg},
};

/// Pure policy mapping from a decide() result to the sink message. Pulled out
/// of the consumer loop so the fail-open behavior is unit-testable without
/// constructing a Kafka consumer.
///
/// Anything other than `Ok(Decision::Drop | Decision::Deny | Decision::NotEnrolled)`
/// indexes, including any `Err(_)`, which is the fail-open commit. Reversing
/// the `Err(_)` arm to `SinkMsg::Skip` would silently drop events during a
/// Redis outage.
fn classify_for_sink(
    decide_result: Result<Decision, CustomRedisError>,
    doc: Box<IndexDoc>,
) -> SinkMsg {
    match decide_result {
        Ok(Decision::Drop | Decision::Deny | Decision::NotEnrolled) => SinkMsg::Skip,
        Ok(_) | Err(_) => SinkMsg::Index(doc),
    }
}

/// Map a `decide()` result onto the value used as the `decision` label on the
/// aggregate Prometheus counter. `Err` is its own label ("redis_error") rather
/// than collapsing onto an Ok variant: the fail-open IndexFloor commit and a
/// Redis outage are operationally distinct events.
fn decision_label(result: &Result<Decision, CustomRedisError>) -> &'static str {
    match result {
        Ok(d) => d.label(),
        Err(_) => "redis_error",
    }
}

// Cap idle wait inside the recv select! so `report_healthy()` runs on a steady cadence
// regardless of topic traffic. Must stay well below `with_liveness_deadline` set on the
// consumer component in main.rs (60s) so an idle topic never trips the stall counter.
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(15);

// Timer cadence for the sink's age-based flush check. Independent of the configured
// max-age threshold; the timer just wakes us up to evaluate `should_flush_age`.
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

/// Send `item` on `tx`, but bail with `ControlFlow::Break` if the shutdown
/// token cancels first. `biased` ensures cancellation deterministically wins
/// over a blocked send (channel full, sink slow). Without it, dropping the
/// `biased` keyword or reordering the arms would silently re-introduce the
/// "SIGTERM during blocked send drops in-flight item" race.
async fn send_or_shutdown<T>(
    shutdown: &CancellationToken,
    tx: &mpsc::Sender<T>,
    item: T,
) -> ControlFlow<()> {
    tokio::select! {
        biased;
        _ = shutdown.cancelled() => {
            info!("Consumer received shutdown during send; closing channel");
            ControlFlow::Break(())
        }
        res = tx.send(item) => match res {
            Ok(()) => ControlFlow::Continue(()),
            Err(_) => {
                info!("Bulk channel closed; consumer loop exiting");
                ControlFlow::Break(())
            }
        }
    }
}

/// Drain `clickhouse_events_json`, classify each event, and forward the result
/// (with its Kafka offset) to the sink so offsets commit in receive order.
///
/// Both `$ai_*` matches and skips travel through the channel; the sink commits
/// each offset only after the message ahead of it on that partition has been
/// processed. Committing offsets in the consumer would let a skipped event at
/// offset N+1 advance the partition past an in-flight `IndexDoc` at offset N
/// that hasn't been written to OpenSearch yet.
pub async fn run_consumer(
    consumer: SingleTopicConsumer,
    tx: mpsc::Sender<(SinkMsg, Offset)>,
    handle: lifecycle::Handle,
    redis: Arc<dyn Client + Send + Sync>,
    sampling_config: Arc<SamplingConfig>,
) {
    let _guard = handle.process_scope();
    let shutdown_token = handle.shutdown_token();
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
            Ok(Some(doc)) => {
                let decide_result = decide(Arc::clone(&redis), &sampling_config, &doc).await;
                common_metrics::inc(
                    "opensearch_indexer_events_total",
                    &[(
                        "decision".to_string(),
                        decision_label(&decide_result).to_string(),
                    )],
                    1,
                );
                if let Err(ref e) = decide_result {
                    warn!(error = %e, team_id = doc.team_id, "decide() Redis error; defaulting to IndexFloor");
                }
                classify_for_sink(decide_result, Box::new(doc))
            }
            Ok(None) => SinkMsg::Skip,
            Err(e) => {
                // Log and forward as Skip so the sink commits the offset and
                // the consumer doesn't wedge on a malformed event.
                error!(uuid = %event.uuid, "Parse error: {e}");
                SinkMsg::Skip
            }
        };

        if send_or_shutdown(&shutdown_token, &tx, (msg, offset))
            .await
            .is_break()
        {
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
            // The `if gate.ready()` precondition pauses receives while the
            // gate is closed (sustained retryable failures). The mpsc channel
            // fills, the consumer's tx.send blocks, and back-pressure flows
            // back to Kafka via consumer-group lag. Without this guard, the
            // batch grows unboundedly during a degraded-cluster window
            // because retained retryables stack on top of new arrivals every
            // backoff cycle. The timer arm stays active so age-based flushes
            // can drain retained items once the gate reopens.
            recv = rx.recv(), if gate.ready() => {
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
                    if let Err(e) = flush_and_track(&writer, &mut batch, "size", &mut gate).await {
                        handle.signal_failure(format!("Bulk flush failed (size): {e}"));
                        return;
                    }
                }
            }
            _ = timer.tick() => {
                // The recv arm is gated on `gate.ready()`, so when the gate
                // is closed we won't notice the channel closing via that
                // path. Detect it here so a consumer panic during a degraded
                // window doesn't hang the sink until the lifecycle stall
                // threshold trips.
                if rx.is_closed() && rx.is_empty() {
                    flush_remaining(&writer, &mut batch, "channel closed (timer-detected)").await;
                    info!("Channel closed (detected via timer), sink loop exiting");
                    return;
                }
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
        let wait = gate
            .next_flush_at
            .unwrap()
            .saturating_duration_since(Instant::now());
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

    // ---- classify_for_sink: regression guards on the policy mapping ----

    fn fixture_doc() -> Box<IndexDoc> {
        Box::new(IndexDoc {
            timestamp: "2024-01-01T12:00:00.000Z".to_string(),
            trace_id: Some("t-1".to_string()),
            team_id: 42,
            model: None,
            provider: None,
            tool_names: Vec::new(),
            is_error: false,
            cost: None,
            latency_ms: None,
            input: None,
            output: None,
            error: None,
            event_uuid: uuid::Uuid::nil(),
            parsed_at: Instant::now(),
        })
    }

    #[test]
    fn classify_for_sink_drops_on_decision_drop() {
        let msg = classify_for_sink(Ok(Decision::Drop), fixture_doc());
        assert!(matches!(msg, SinkMsg::Skip));
    }

    #[test]
    fn classify_for_sink_drops_on_decision_deny() {
        let msg = classify_for_sink(Ok(Decision::Deny), fixture_doc());
        assert!(matches!(msg, SinkMsg::Skip));
    }

    #[test]
    fn classify_for_sink_skips_on_decision_not_enrolled() {
        let msg = classify_for_sink(Ok(Decision::NotEnrolled), fixture_doc());
        assert!(matches!(msg, SinkMsg::Skip));
    }

    #[test]
    fn classify_for_sink_indexes_on_decision_floor() {
        let msg = classify_for_sink(Ok(Decision::IndexFloor), fixture_doc());
        assert!(matches!(msg, SinkMsg::Index(_)));
    }

    #[test]
    fn classify_for_sink_indexes_on_decision_sample() {
        let msg = classify_for_sink(Ok(Decision::IndexSample), fixture_doc());
        assert!(matches!(msg, SinkMsg::Index(_)));
    }

    #[test]
    fn classify_for_sink_indexes_on_decision_error() {
        let msg = classify_for_sink(Ok(Decision::IndexError), fixture_doc());
        assert!(matches!(msg, SinkMsg::Index(_)));
    }

    #[test]
    fn classify_for_sink_fail_open_indexes_on_redis_timeout() {
        // Regression guard for the fail-open commit. Reversing this to Skip
        // would silently drop events during a Redis outage.
        let msg = classify_for_sink(Err(CustomRedisError::Timeout), fixture_doc());
        assert!(matches!(msg, SinkMsg::Index(_)));
    }

    #[test]
    fn classify_for_sink_fail_open_indexes_on_redis_parse_error() {
        // Even unrecoverable Redis errors fail-open; sampling correctness is
        // not worth pausing the consumer over.
        let msg = classify_for_sink(
            Err(CustomRedisError::ParseError("synthetic".to_string())),
            fixture_doc(),
        );
        assert!(matches!(msg, SinkMsg::Index(_)));
    }

    // ---- decision_label: aggregate Prometheus label correctness ----

    #[test]
    fn decision_label_floor() {
        assert_eq!(decision_label(&Ok(Decision::IndexFloor)), "floor");
    }

    #[test]
    fn decision_label_sample() {
        assert_eq!(decision_label(&Ok(Decision::IndexSample)), "sample");
    }

    #[test]
    fn decision_label_error() {
        assert_eq!(decision_label(&Ok(Decision::IndexError)), "error");
    }

    #[test]
    fn decision_label_drop() {
        assert_eq!(decision_label(&Ok(Decision::Drop)), "drop");
    }

    #[test]
    fn decision_label_deny() {
        assert_eq!(decision_label(&Ok(Decision::Deny)), "deny");
    }

    #[test]
    fn decision_label_not_enrolled() {
        assert_eq!(decision_label(&Ok(Decision::NotEnrolled)), "not_enrolled");
    }

    #[test]
    fn decision_label_redis_error_for_any_err_kind() {
        // The Err arm collapses every CustomRedisError variant onto a single
        // label so dashboards don't shatter into per-error-kind series.
        assert_eq!(
            decision_label(&Err(CustomRedisError::Timeout)),
            "redis_error"
        );
        assert_eq!(
            decision_label(&Err(CustomRedisError::ParseError("x".to_string()))),
            "redis_error"
        );
        assert_eq!(
            decision_label(&Err(CustomRedisError::NotFound)),
            "redis_error"
        );
    }

    // ---- send_or_shutdown ----

    #[tokio::test]
    async fn send_or_shutdown_returns_continue_on_successful_send() {
        let token = CancellationToken::new();
        let (tx, mut rx) = mpsc::channel::<i32>(1);
        let result = send_or_shutdown(&token, &tx, 42).await;
        assert!(matches!(result, ControlFlow::Continue(())));
        assert_eq!(rx.recv().await, Some(42));
    }

    #[tokio::test]
    async fn send_or_shutdown_returns_break_when_channel_closed() {
        let token = CancellationToken::new();
        let (tx, rx) = mpsc::channel::<i32>(1);
        drop(rx); // close the receiver
        let result = send_or_shutdown(&token, &tx, 42).await;
        assert!(matches!(result, ControlFlow::Break(())));
    }

    #[tokio::test]
    async fn send_or_shutdown_returns_break_when_already_cancelled() {
        // Pre-cancelled token + open channel: shutdown wins via biased select.
        let token = CancellationToken::new();
        token.cancel();
        let (tx, _rx) = mpsc::channel::<i32>(1);
        let result = send_or_shutdown(&token, &tx, 42).await;
        assert!(matches!(result, ControlFlow::Break(())));
    }

    #[tokio::test]
    async fn send_or_shutdown_breaks_on_cancel_during_blocked_send() {
        // Channel full → tx.send blocks. Cancel must win promptly. This is
        // the regression guard against removing `biased` or reordering the
        // arms in `send_or_shutdown` (both subtle changes that pass the
        // type-checker but silently break shutdown semantics).
        let token = CancellationToken::new();
        let (tx, _rx) = mpsc::channel::<i32>(1);
        tx.send(99).await.expect("first send fills the channel");

        let token_clone = token.clone();
        let send_task = tokio::spawn(async move { send_or_shutdown(&token_clone, &tx, 100).await });

        // Give the send a beat to enter the blocked state.
        tokio::time::sleep(Duration::from_millis(20)).await;
        token.cancel();

        let result = tokio::time::timeout(Duration::from_millis(200), send_task)
            .await
            .expect("send_or_shutdown must return within 200ms after cancel")
            .expect("task joined");
        assert!(matches!(result, ControlFlow::Break(())));
    }
}
