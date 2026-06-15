use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use tracing::{error, info, warn};

use crate::aggregator::Aggregator;
use crate::config::Config;
use crate::metrics_consts::*;
use crate::producer::Producer;
use crate::seen_cache::SeenCache;
use crate::types::{IngestableEvent, PropertyType, TupleKey};

#[derive(Clone, Copy, Default)]
pub struct ReductionConfig {
    pub max_values_per_key: usize,
    pub seen_cache_capacity: usize,
}

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
    worker: &'static str,
    reduction: ReductionConfig,
) where
    E: IngestableEvent,
    P: Producer,
    F: Fn(&E) -> Vec<(TupleKey, u64)>,
{
    let _guard = handle.process_scope();

    let mut aggregator = Aggregator::new();
    let seen_cache = (reduction.seen_cache_capacity > 0)
        .then(|| SeenCache::new(reduction.seen_cache_capacity, worker));
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
                flush(&mut aggregator, &mut pending_offsets, &producer, FLUSH_REASON_SHUTDOWN, worker, reduction.max_values_per_key, seen_cache.as_ref()).await;
                if let Err(e) = consumer.commit() {
                    warn!(error = %e, "kafka sync commit at shutdown failed; falling back to broker auto-commit");
                }
                return;
            }
            _ = flush_timer.tick() => {
                handle.report_healthy();
                flush(&mut aggregator, &mut pending_offsets, &producer, FLUSH_REASON_TIMER, worker, reduction.max_values_per_key, seen_cache.as_ref()).await;
            }
            recv = consumer.recv_with(E::decode) => {
                handle.report_healthy();
                match recv {
                    Ok((event, offset)) => {
                        metrics::counter!(EVENTS_RECEIVED, "worker" => worker).increment(1);

                        if config.should_process(event.team_id()) {
                            let tuples = fan_out_fn(&event);
                            metrics::counter!(TUPLES_AGGREGATED, "worker" => worker).increment(tuples.len() as u64);
                            for (t, count) in tuples {
                                aggregator.add(t, count);
                            }
                        } else {
                            metrics::counter!(EVENTS_FILTERED, "worker" => worker).increment(1);
                        }

                        pending_offsets.insert(offset.partition(), offset);

                        if aggregator.len() >= config.max_buffered_tuples {
                            flush(
                                &mut aggregator,
                                &mut pending_offsets,
                                &producer,
                                FLUSH_REASON_BACKPRESSURE,
                                worker,
                                reduction.max_values_per_key,
                                seen_cache.as_ref(),
                            ).await;
                        }
                    }
                    Err(RecvErr::Empty) | Err(RecvErr::Serde(_)) => {
                        // SingleTopicConsumer auto-stores poison-pill offsets.
                    }
                    Err(RecvErr::Kafka(e)) => {
                        metrics::counter!(KAFKA_RECV_ERRORS, "worker" => worker).increment(1);
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
    worker: &'static str,
    max_values_per_key: usize,
    seen_cache: Option<&SeenCache>,
) {
    if aggregator.is_empty() && pending_offsets.is_empty() {
        return;
    }

    let mut snapshot: Vec<(TupleKey, u64)> = aggregator.drain().into_iter().collect();
    if max_values_per_key > 0 {
        snapshot = cap_top_k(snapshot, max_values_per_key, worker);
    }

    let to_emit: Vec<(TupleKey, u64)> = match seen_cache {
        Some(cache) => snapshot
            .into_iter()
            .filter(|(tuple, _)| !cache.seen(tuple))
            .collect(),
        None => snapshot,
    };

    metrics::counter!(FLUSH_TOTAL, "reason" => reason, "worker" => worker).increment(1);
    metrics::histogram!(FLUSH_TUPLES, "worker" => worker).record(to_emit.len() as f64);

    for (_, count) in &to_emit {
        metrics::histogram!(FLUSH_TUPLE_COUNT, "worker" => worker).record(*count as f64);
    }

    if !to_emit.is_empty() {
        if let Err(e) = producer.produce(to_emit.clone()).await {
            metrics::counter!(PRODUCER_FLUSH_FAILED, "worker" => worker).increment(1);
            error!(error = %e, "produce failed; restoring counts, retrying next flush");
            for (tuple, count) in to_emit {
                aggregator.add(tuple, count);
            }
            return;
        }
        if let Some(cache) = seen_cache {
            for (tuple, _) in &to_emit {
                cache.insert(tuple);
            }
        }
    }

    // Produce succeeded; advance the stored offset for each partition we
    // consumed from. Background auto-commit will ship these to the broker
    // within ~5s; shutdown forces a sync commit.
    for (_partition, offset) in pending_offsets.drain() {
        if let Err(e) = offset.store() {
            metrics::counter!(OFFSET_STORE_FAILED, "worker" => worker).increment(1);
            warn!(error = %e, "failed to store offset; auto-commit will be a no-op for this partition until the next successful flush");
        }
    }
}

/// Cap each (team, type, key) to its `k` highest-count values, dropping
/// the rest. Keys with `<= k` distinct values are untouched, so low-cardinality
/// keys keep everything; only high-cardinality keys lose their long tail.
type CapGroup = (i64, PropertyType, String);

fn cap_top_k(
    snapshot: Vec<(TupleKey, u64)>,
    k: usize,
    worker: &'static str,
) -> Vec<(TupleKey, u64)> {
    let mut by_key: HashMap<CapGroup, Vec<(TupleKey, u64)>> = HashMap::new();
    for entry in snapshot {
        let group = (
            entry.0.team_id,
            entry.0.property_type,
            entry.0.property_key.clone(),
        );
        by_key.entry(group).or_default().push(entry);
    }

    let mut out = Vec::new();
    for (_, mut values) in by_key {
        if values.len() > k {
            values.select_nth_unstable_by(k, |a, b| b.1.cmp(&a.1));
            let dropped = values.len() - k;
            values.truncate(k);
            metrics::counter!(TOP_K_DROPPED, "worker" => worker).increment(dropped as u64);
        }
        out.extend(values);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::aggregator::Aggregator;
    use crate::producer::ProduceError;
    use crate::types::{PropertyType, TupleKey};
    use proptest::prelude::*;
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
        fn successful_batches(&self) -> Vec<Vec<(TupleKey, u64)>> {
            let items = self.seen_items.lock().unwrap();
            let fail = self.fail_on.lock().unwrap();
            items
                .iter()
                .enumerate()
                .filter(|(i, _)| !fail.contains(&(i + 1)))
                .map(|(_, batch)| batch.clone())
                .collect()
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

    #[test]
    fn cap_top_k_keeps_keys_under_the_cap() {
        let snap = vec![
            (tuple(2, "$browser", "Chrome"), 5),
            (tuple(2, "$browser", "Firefox"), 1),
            (tuple(2, "$browser", "Safari"), 1),
        ];
        let out = cap_top_k(snap, 10, "test");
        assert_eq!(
            out.len(),
            3,
            "a key with fewer than k values keeps all of them"
        );
    }

    #[test]
    fn cap_top_k_drops_tail_of_high_card_key() {
        let snap = vec![
            (tuple(2, "$insert_id", "a"), 1),
            (tuple(2, "$insert_id", "b"), 9),
            (tuple(2, "$insert_id", "c"), 5),
            (tuple(2, "$insert_id", "d"), 1),
        ];
        let out = cap_top_k(snap, 2, "test");
        assert_eq!(out.len(), 2);
        let counts: Vec<u64> = out.iter().map(|(_, c)| *c).collect();
        assert!(
            counts.contains(&9) && counts.contains(&5),
            "keeps the two highest counts"
        );
    }

    #[test]
    fn cap_top_k_caps_each_key_independently() {
        let snap = vec![
            (tuple(2, "$browser", "Chrome"), 3),
            (tuple(2, "$insert_id", "a"), 1),
            (tuple(2, "$insert_id", "b"), 2),
            (tuple(2, "$insert_id", "c"), 3),
        ];
        let out = cap_top_k(snap, 2, "test");
        let browser = out
            .iter()
            .filter(|(t, _)| t.property_key == "$browser")
            .count();
        let insert = out
            .iter()
            .filter(|(t, _)| t.property_key == "$insert_id")
            .count();
        assert_eq!(browser, 1, "low-card key untouched");
        assert_eq!(insert, 2, "high-card key capped to k");
    }

    #[tokio::test]
    async fn successful_flush_drains_aggregator() {
        let mut agg = Aggregator::new();
        populate(&mut agg, 5);

        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new();
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            None,
        )
        .await;

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
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            None,
        )
        .await;

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

        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            None,
        )
        .await;
        assert!(!agg.is_empty());

        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            None,
        )
        .await;
        assert!(agg.is_empty());
        assert_eq!(producer.call_count(), 2);
    }

    #[tokio::test]
    async fn empty_aggregator_empty_offsets_is_noop() {
        let mut agg = Aggregator::new();
        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new();
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            None,
        )
        .await;
        assert_eq!(producer.call_count(), 0);
    }

    #[tokio::test]
    async fn restored_counts_merge_with_new_counts_in_next_window() {
        let mut agg = Aggregator::new();
        agg.add(tuple(2, "k1", "v1"), 1);

        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new().fail_on(1);
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            None,
        )
        .await;

        agg.add(tuple(2, "k1", "v1"), 1);

        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            None,
        )
        .await;

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
            flush(
                &mut agg,
                &mut pending,
                &producer,
                FLUSH_REASON_TIMER,
                "test",
                0,
                None,
            )
            .await;
        }

        assert_eq!(agg.len(), 1);
        assert_eq!(producer.call_count(), 3);
    }

    #[tokio::test]
    async fn seen_cache_suppresses_already_emitted_tuples() {
        let cache = SeenCache::new(1000, "test");
        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new();

        let mut agg = Aggregator::new();
        agg.add(tuple(2, "k", "v"), 1);
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            Some(&cache),
        )
        .await;
        assert_eq!(producer.last_items().len(), 1, "first sight is emitted");

        agg.add(tuple(2, "k", "v"), 1);
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            Some(&cache),
        )
        .await;
        assert_eq!(
            producer.call_count(),
            1,
            "an already-cached tuple is suppressed, so there is no second produce"
        );
        assert!(
            agg.is_empty(),
            "suppressed tuples still drain the aggregator"
        );
    }

    #[tokio::test]
    async fn seen_cache_reemits_after_produce_failure() {
        let cache = SeenCache::new(1000, "test");
        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new().fail_on(1);

        let mut agg = Aggregator::new();
        agg.add(tuple(2, "k", "v"), 1);
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            Some(&cache),
        )
        .await;
        assert_eq!(agg.len(), 1, "failed produce restores the tuple for retry");

        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            Some(&cache),
        )
        .await;
        assert_eq!(producer.call_count(), 2);
        assert_eq!(
            producer.last_items().len(),
            1,
            "a tuple forgotten on produce failure is re-emitted, not lost to the cache"
        );
    }

    #[tokio::test]
    async fn seen_cache_emits_new_values_and_suppresses_repeats() {
        let cache = SeenCache::new(1000, "test");
        let mut pending: HashMap<i32, Offset> = HashMap::new();
        let producer = MockProducer::new();

        let mut agg = Aggregator::new();
        agg.add(tuple(2, "k", "a"), 1);
        agg.add(tuple(2, "k", "b"), 1);
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            Some(&cache),
        )
        .await;
        assert_eq!(
            producer.last_items().len(),
            2,
            "distinct new tuples all emit"
        );

        agg.add(tuple(2, "k", "a"), 1); // already seen
        agg.add(tuple(2, "k", "c"), 1); // new
        flush(
            &mut agg,
            &mut pending,
            &producer,
            FLUSH_REASON_TIMER,
            "test",
            0,
            Some(&cache),
        )
        .await;
        let batch = producer.last_items();
        assert_eq!(
            batch.len(),
            1,
            "only the new value emits; the repeat is suppressed"
        );
        assert_eq!(batch[0].0.property_value, "c");
    }

    fn arb_property_type() -> impl Strategy<Value = PropertyType> {
        prop_oneof![
            Just(PropertyType::Event),
            Just(PropertyType::Person),
            (0u8..=4).prop_map(PropertyType::Group),
        ]
    }

    prop_compose! {
        fn arb_tuple()(
            team_id in -3i64..=3,
            property_type in arb_property_type(),
            property_key in "[a-c]{1,2}",
            property_value in "[x-z]{1,2}",
        ) -> TupleKey {
            TupleKey { team_id, property_type, property_key, property_value }
        }
    }

    #[derive(Debug, Clone)]
    enum WorkerOp {
        Add(TupleKey, u64),
        Flush,
    }

    fn arb_worker_op() -> impl Strategy<Value = WorkerOp> {
        prop_oneof![
            // 4:1 weighting so the aggregator actually accumulates between flushes
            // instead of every other op being an immediate drain.
            4 => (arb_tuple(), 1u64..100).prop_map(|(t, n)| WorkerOp::Add(t, n)),
            1 => Just(WorkerOp::Flush),
        ]
    }

    proptest! {
        #[test]
        fn flush_conserves_counts(
            ops in prop::collection::vec(arb_worker_op(), 0..60),
            fail_indices in prop::collection::vec(1usize..30, 0..15),
        ) {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap();

            let mut agg = Aggregator::new();
            let mut pending: HashMap<i32, Offset> = HashMap::new();
            let mut producer = MockProducer::new();
            for idx in &fail_indices {
                producer = producer.fail_on(*idx);
            }

            let mut recorded: HashMap<TupleKey, u64> = HashMap::new();

            for op in &ops {
                match op {
                    WorkerOp::Add(t, n) => {
                        agg.add(t.clone(), *n);
                        *recorded.entry(t.clone()).or_insert(0) += *n;
                    }
                    WorkerOp::Flush => {
                        runtime.block_on(flush(
                            &mut agg,
                            &mut pending,
                            &producer,
                            FLUSH_REASON_TIMER,
                            "test",
                            0,
                            None,
                        ));
                    }
                }
            }

            let mut accounted: HashMap<TupleKey, u64> = HashMap::new();
            for (t, n) in agg.drain() {
                *accounted.entry(t).or_insert(0) += n;
            }
            for batch in producer.successful_batches() {
                for (t, n) in batch {
                    *accounted.entry(t).or_insert(0) += n;
                }
            }

            prop_assert_eq!(recorded, accounted);
        }
    }
}
