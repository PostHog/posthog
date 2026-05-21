use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use tracing::{error, info, warn};

use crate::aggregator::Aggregator;
use crate::config::Config;
use crate::metrics_consts::*;
use crate::producer::Producer;
use crate::types::{IngestableEvent, TupleKey};

/// One worker loop. Each pod runs one worker per input topic.
///
/// At-least-once: on each flush we produce non-transactionally, then on
/// success advance the consumer's stored offsets. Background auto-commit
/// (configured in init_with_defaults) flushes the stored offsets to the
/// broker every 5s. On graceful shutdown we drain one final flush and
/// force a synchronous commit so the next pod resumes from exactly here.
pub async fn worker_loop<E, P, F>(
    config: Arc<Config>,
    consumer: SingleTopicConsumer,
    producer: P,
    handle: lifecycle::Handle,
    fan_out_fn: F,
) where
    E: IngestableEvent,
    P: Producer,
    F: Fn(&E) -> Vec<TupleKey>,
{
    let _guard = handle.process_scope();

    let mut aggregator = Aggregator::new();
    // One Offset handle per partition: the latest message we've consumed.
    // On successful flush we call .store() on each, which advances the
    // consumer's stored offset; auto-commit ships it to the broker.
    let mut pending_offsets: HashMap<i32, Offset> = HashMap::new();

    let mut flush_timer = tokio::time::interval(Duration::from_secs(config.flush_interval_secs));
    flush_timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    flush_timer.reset();

    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => {
                info!("worker received shutdown; draining final flush");
                flush(&mut aggregator, &mut pending_offsets, &producer, FLUSH_REASON_SHUTDOWN).await;
                if let Err(e) = consumer.commit() {
                    warn!(error = %e, "kafka sync commit at shutdown failed; falling back to broker auto-commit");
                }
                return;
            }
            _ = flush_timer.tick() => {
                handle.report_healthy();
                flush(&mut aggregator, &mut pending_offsets, &producer, FLUSH_REASON_TIMER).await;
            }
            recv = consumer.json_recv::<E>() => {
                handle.report_healthy();
                match recv {
                    Ok((event, offset)) => {
                        metrics::counter!(EVENTS_RECEIVED).increment(1);

                        if config.should_process(event.team_id()) {
                            let tuples = fan_out_fn(&event);
                            metrics::counter!(TUPLES_AGGREGATED).increment(tuples.len() as u64);
                            for t in tuples {
                                aggregator.add(t, 1);
                            }
                        } else {
                            metrics::counter!(EVENTS_FILTERED).increment(1);
                        }

                        pending_offsets.insert(offset.partition(), offset);

                        if aggregator.len() >= config.max_buffered_tuples {
                            flush(
                                &mut aggregator,
                                &mut pending_offsets,
                                &producer,
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

/// Produce the aggregated counts to the output topic, then advance the
/// consumer's stored offsets so they get auto-committed. On produce failure,
/// the snapshot is merged back into the aggregator and offsets are left
/// untouched so the next flush retries the same input range.
pub(crate) async fn flush<P: Producer>(
    aggregator: &mut Aggregator,
    pending_offsets: &mut HashMap<i32, Offset>,
    producer: &P,
    reason: &'static str,
) {
    if aggregator.is_empty() && pending_offsets.is_empty() {
        return;
    }

    let snapshot: Vec<(TupleKey, u64)> = aggregator.drain().into_iter().collect();

    metrics::counter!(FLUSH_TOTAL, "reason" => reason).increment(1);
    metrics::histogram!(FLUSH_TUPLES).record(snapshot.len() as f64);

    if let Err(e) = producer.produce(snapshot.clone()).await {
        metrics::counter!(PRODUCER_FLUSH_FAILED).increment(1);
        error!(error = %e, "produce failed; restoring counts, retrying next flush");
        for (tuple, count) in snapshot {
            aggregator.add(tuple, count);
        }
        return;
    }

    // Produce succeeded; advance the stored offset for each partition we
    // consumed from. Background auto-commit will ship these to the broker
    // within ~5s; shutdown forces a sync commit.
    for (_partition, offset) in pending_offsets.drain() {
        if let Err(e) = offset.store() {
            metrics::counter!(OFFSET_STORE_FAILED).increment(1);
            warn!(error = %e, "failed to store offset; auto-commit will be a no-op for this partition until the next successful flush");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::aggregator::Aggregator;
    use crate::producer::ProduceError;
    use crate::types::{PropertyType, TupleKey};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    /// Mock producer that records each call and can be configured to fail on
    /// specific call indices.
    struct MockProducer {
        calls: AtomicUsize,
        fail_on: Mutex<Vec<usize>>,
        seen_items: Mutex<Vec<Vec<(TupleKey, u64)>>>,
    }

    impl MockProducer {
        fn new() -> Self {
            Self {
                calls: AtomicUsize::new(0),
                fail_on: Mutex::new(Vec::new()),
                seen_items: Mutex::new(Vec::new()),
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
    }

    #[async_trait::async_trait]
    impl Producer for MockProducer {
        async fn produce(&self, items: Vec<(TupleKey, u64)>) -> Result<(), ProduceError> {
            let n = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
            self.seen_items.lock().unwrap().push(items.clone());
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

    fn populate(agg: &mut Aggregator, count: u64) {
        for i in 0..count {
            agg.add(tuple(2, "k", &format!("v{i}")), 1);
        }
    }

    #[tokio::test]
    async fn successful_flush_drains_aggregator() {
        let mut agg = Aggregator::new();
        populate(&mut agg, 5);

        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new();
        flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;

        assert!(agg.is_empty());
        assert_eq!(producer.call_count(), 1);
        assert_eq!(producer.last_items().len(), 5);
    }

    #[tokio::test]
    async fn failed_flush_restores_counts() {
        let mut agg = Aggregator::new();
        populate(&mut agg, 3);

        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new().fail_on(1);
        flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;

        assert_eq!(
            agg.len(),
            3,
            "aggregator must restore drained counts on produce failure"
        );
    }

    #[tokio::test]
    async fn failed_then_successful_flush_eventually_clears_state() {
        let mut agg = Aggregator::new();
        populate(&mut agg, 4);

        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new().fail_on(1);

        flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;
        assert!(!agg.is_empty());

        flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;
        assert!(agg.is_empty());
        assert_eq!(producer.call_count(), 2);
    }

    #[tokio::test]
    async fn empty_aggregator_empty_offsets_is_noop() {
        let mut agg = Aggregator::new();
        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new();
        flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;
        assert_eq!(producer.call_count(), 0);
    }

    #[tokio::test]
    async fn restored_counts_merge_with_new_counts_in_next_window() {
        let mut agg = Aggregator::new();
        agg.add(tuple(2, "k1", "v1"), 1);

        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new().fail_on(1);
        flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;

        agg.add(tuple(2, "k1", "v1"), 1);

        flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;

        let batch = producer.last_items();
        assert_eq!(batch.len(), 1);
        assert_eq!(batch[0].1, 2);
    }

    #[tokio::test]
    async fn repeated_failure_holds_all_state_indefinitely() {
        let mut agg = Aggregator::new();
        agg.add(tuple(2, "k1", "v1"), 1);

        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new().fail_on(1).fail_on(2).fail_on(3);

        for _ in 0..3 {
            flush(&mut agg, &mut pending, &producer, FLUSH_REASON_TIMER).await;
        }

        assert_eq!(agg.len(), 1);
        assert_eq!(producer.call_count(), 3);
    }
}
