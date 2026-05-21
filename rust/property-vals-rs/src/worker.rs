use std::collections::HashMap;
use std::sync::Arc;

use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use tracing::{error, info, warn};

use crate::aggregator::Aggregator;
use crate::app_context::AppContext;
use crate::metrics_consts::*;
use crate::producer::{OffsetSnapshot, Producer};
use crate::types::{IngestableEvent, TupleKey};

/// One worker loop. Each pod runs one worker per input topic. Each worker
/// owns its own transactional producer (with a distinct `transactional.id`)
/// because rdkafka allows only one outstanding transaction per id.
///
/// Generic over the message type so the events consumer and the groups
/// consumer can share this code. The caller supplies the per-message
/// fan-out function.
pub async fn worker_loop<E, P, F>(
    ctx: Arc<AppContext>,
    consumer: SingleTopicConsumer,
    mut producer: P,
    handle: lifecycle::Handle,
    fan_out_fn: F,
) where
    E: IngestableEvent,
    P: Producer,
    F: Fn(&E) -> Vec<TupleKey>,
{
    let _guard = handle.process_scope();

    let mut aggregator = Aggregator::new();
    // Latest seen offset per partition; the worker only stores a snapshot
    // (topic + partition + offset value) because the real consumer Offset
    // handle isn't needed anymore. The transactional producer commits these
    // via `send_offsets_to_transaction` atomically with the produce.
    let mut pending_offsets: HashMap<i32, OffsetSnapshot> = HashMap::new();

    let mut flush_timer = tokio::time::interval(ctx.flush_interval);
    flush_timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    flush_timer.reset();

    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => {
                info!("worker received shutdown; draining final flush");
                flush(
                    &mut aggregator,
                    &mut pending_offsets,
                    &mut producer,
                    FLUSH_REASON_SHUTDOWN,
                ).await;
                return;
            }
            _ = flush_timer.tick() => {
                handle.report_healthy();
                flush(
                    &mut aggregator,
                    &mut pending_offsets,
                    &mut producer,
                    FLUSH_REASON_TIMER,
                ).await;
            }
            recv = consumer.json_recv::<E>() => {
                handle.report_healthy();
                match recv {
                    Ok((event, offset)) => {
                        metrics::counter!(EVENTS_RECEIVED).increment(1);

                        if ctx.should_process(event.team_id()) {
                            let tuples = fan_out_fn(&event);
                            metrics::counter!(TUPLES_AGGREGATED).increment(tuples.len() as u64);
                            aggregator.record_many(tuples);
                        } else {
                            metrics::counter!(EVENTS_FILTERED).increment(1);
                        }

                        pending_offsets.insert(
                            offset.partition(),
                            OffsetSnapshot {
                                topic: offset.topic().to_string(),
                                partition: offset.partition(),
                                offset: offset.get_value(),
                            },
                        );

                        if aggregator.len() >= ctx.max_buffered_tuples {
                            flush(
                                &mut aggregator,
                                &mut pending_offsets,
                                &mut producer,
                                FLUSH_REASON_BACKPRESSURE,
                            ).await;
                        }
                    }
                    Err(RecvErr::Empty) | Err(RecvErr::Serde(_)) => {
                        // SingleTopicConsumer auto-stores poison-pill offsets.
                    }
                    Err(RecvErr::Kafka(e)) => {
                        metrics::counter!(KAFKA_RECV_ERRORS).increment(1);
                        warn!(error = %e, "kafka recv error");
                    }
                }
            }
        }
    }
}

/// Atomically produce the aggregated counts and commit input offsets through
/// a Kafka transaction. Either both writes are durable or neither happens,
/// so the worker never leaves the system in a state where records were
/// delivered but offsets weren't committed (or vice versa). On failure the
/// drained snapshot is merged back into the aggregator so counts aren't
/// lost.
pub(crate) async fn flush<P: Producer>(
    aggregator: &mut Aggregator,
    pending_offsets: &mut HashMap<i32, OffsetSnapshot>,
    producer: &mut P,
    reason: &'static str,
) {
    if aggregator.is_empty() && pending_offsets.is_empty() {
        return;
    }

    let snapshot: Vec<(crate::types::TupleKey, u64)> = aggregator.drain().into_iter().collect();
    let offsets: Vec<OffsetSnapshot> = pending_offsets.values().cloned().collect();

    metrics::counter!(FLUSH_TOTAL, "reason" => reason).increment(1);
    metrics::histogram!(FLUSH_TUPLES).record(snapshot.len() as f64);

    if let Err(e) = producer.produce_and_commit(snapshot.clone(), offsets).await {
        metrics::counter!(PRODUCER_FLUSH_FAILED).increment(1);
        error!(error = %e, "transactional commit failed; restoring counts, deferring offsets");
        for (tuple, count) in snapshot {
            aggregator.add(tuple, count);
        }
        return;
    }

    // Transaction committed atomically; safe to drop the pending offset
    // snapshots since they've already been committed inside the txn.
    pending_offsets.clear();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::aggregator::Aggregator;
    use crate::producer::ProduceError;
    use crate::types::{PropertyType, TupleKey};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    /// Mock producer that records each (items, offsets) call and can be
    /// configured to fail on specific call indices.
    struct MockProducer {
        calls: AtomicUsize,
        fail_on: Mutex<Vec<usize>>,
        seen_items: Mutex<Vec<Vec<(TupleKey, u64)>>>,
        seen_offsets: Mutex<Vec<Vec<OffsetSnapshot>>>,
    }

    impl MockProducer {
        fn new() -> Self {
            Self {
                calls: AtomicUsize::new(0),
                fail_on: Mutex::new(Vec::new()),
                seen_items: Mutex::new(Vec::new()),
                seen_offsets: Mutex::new(Vec::new()),
            }
        }
        fn fail_on(self, call_index: usize) -> Self {
            self.fail_on.lock().unwrap().push(call_index);
            self
        }
        fn call_count(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
        fn last_items(&self) -> Vec<(TupleKey, u64)> {
            self.seen_items
                .lock()
                .unwrap()
                .last()
                .cloned()
                .unwrap_or_default()
        }
        fn last_offsets(&self) -> Vec<OffsetSnapshot> {
            self.seen_offsets
                .lock()
                .unwrap()
                .last()
                .cloned()
                .unwrap_or_default()
        }
    }

    #[async_trait::async_trait]
    impl Producer for MockProducer {
        async fn produce_and_commit(
            &mut self,
            items: Vec<(TupleKey, u64)>,
            offsets: Vec<OffsetSnapshot>,
        ) -> Result<(), ProduceError> {
            let n = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
            self.seen_items.lock().unwrap().push(items.clone());
            self.seen_offsets.lock().unwrap().push(offsets.clone());
            if self.fail_on.lock().unwrap().contains(&n) {
                let total = items.len().max(1);
                return Err(ProduceError::PartialFailure {
                    failed: total,
                    total,
                });
            }
            Ok(())
        }
    }

    fn tuple(team: i64, key: &str, value: &str) -> TupleKey {
        TupleKey {
            team_id: team,
            property_type: PropertyType::Event,
            property_key: key.to_string(),
            property_value: value.to_string(),
        }
    }

    fn snapshot(partition: i32, offset: i64) -> OffsetSnapshot {
        OffsetSnapshot {
            topic: "team_event_partitioned_events_json".to_string(),
            partition,
            offset,
        }
    }

    fn populate(agg: &mut Aggregator, count: u64) {
        for i in 0..count {
            agg.record(tuple(2, "k", &format!("v{i}")));
        }
    }

    #[tokio::test]
    async fn successful_flush_drains_aggregator_and_clears_offsets() {
        let mut agg = Aggregator::new();
        populate(&mut agg, 5);

        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        pending.insert(0, snapshot(0, 100));
        pending.insert(1, snapshot(1, 200));

        let mut producer = MockProducer::new();
        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;

        assert!(agg.is_empty());
        assert!(pending.is_empty());
        assert_eq!(producer.call_count(), 1);
        assert_eq!(producer.last_items().len(), 5);
        assert_eq!(producer.last_offsets().len(), 2);
    }

    #[tokio::test]
    async fn failed_flush_restores_counts_and_keeps_pending_offsets() {
        let mut agg = Aggregator::new();
        populate(&mut agg, 3);

        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        pending.insert(0, snapshot(0, 50));

        let mut producer = MockProducer::new().fail_on(1);
        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;

        assert_eq!(
            agg.len(),
            3,
            "aggregator must restore drained counts on transaction abort"
        );
        assert_eq!(
            pending.len(),
            1,
            "pending_offsets must NOT clear when produce_and_commit fails"
        );
    }

    #[tokio::test]
    async fn failed_then_successful_flush_eventually_clears_state() {
        let mut agg = Aggregator::new();
        populate(&mut agg, 4);

        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        pending.insert(0, snapshot(0, 99));

        let mut producer = MockProducer::new().fail_on(1);

        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;
        assert!(!agg.is_empty());
        assert!(!pending.is_empty());

        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;
        assert!(agg.is_empty());
        assert!(pending.is_empty());
        assert_eq!(producer.call_count(), 2);
    }

    #[tokio::test]
    async fn empty_aggregator_with_pending_offsets_still_calls_producer() {
        let mut agg = Aggregator::new();
        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        pending.insert(0, snapshot(0, 7));

        let mut producer = MockProducer::new();
        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;

        assert!(pending.is_empty());
        assert_eq!(producer.call_count(), 1);
        assert_eq!(producer.last_items().len(), 0);
        assert_eq!(producer.last_offsets().len(), 1);
    }

    #[tokio::test]
    async fn empty_aggregator_empty_offsets_is_noop() {
        let mut agg = Aggregator::new();
        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        let mut producer = MockProducer::new();
        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;
        assert_eq!(producer.call_count(), 0);
    }

    #[tokio::test]
    async fn restored_counts_merge_with_new_counts_in_next_window() {
        let mut agg = Aggregator::new();
        agg.record(tuple(2, "k1", "v1"));

        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        pending.insert(0, snapshot(0, 10));

        let mut producer = MockProducer::new().fail_on(1);
        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;

        agg.record(tuple(2, "k1", "v1"));

        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;

        let batch = producer.last_items();
        assert_eq!(batch.len(), 1);
        assert_eq!(batch[0].1, 2);
    }

    #[tokio::test]
    async fn produce_and_commit_receives_items_and_offsets_atomically() {
        let mut agg = Aggregator::new();
        agg.record(tuple(2, "k1", "v1"));

        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        pending.insert(0, snapshot(0, 42));

        let mut producer = MockProducer::new();
        flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;

        assert_eq!(producer.call_count(), 1);
        assert_eq!(producer.last_items().len(), 1);
        assert_eq!(producer.last_offsets().len(), 1);
        assert_eq!(producer.last_offsets()[0].partition, 0);
        assert_eq!(producer.last_offsets()[0].offset, 42);
    }

    #[tokio::test]
    async fn repeated_failure_holds_all_state_indefinitely() {
        let mut agg = Aggregator::new();
        agg.record(tuple(2, "k1", "v1"));

        let mut pending: HashMap<i32, OffsetSnapshot> = HashMap::new();
        pending.insert(0, snapshot(0, 7));

        let mut producer = MockProducer::new().fail_on(1).fail_on(2).fail_on(3);

        for _ in 0..3 {
            flush(&mut agg, &mut pending, &mut producer, FLUSH_REASON_TIMER).await;
        }

        assert_eq!(agg.len(), 1);
        assert_eq!(pending.len(), 1);
        assert_eq!(producer.call_count(), 3);
    }
}
