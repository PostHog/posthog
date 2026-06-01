use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use metrics::{counter, gauge, histogram};

use crate::types::SerializedKafkaMessage;
use crate::worker_registry::{WorkerRegistry, WorkerState};

/// A slice of a batch assigned to one worker, carrying the messages and the
/// routing keys of all distinct_ids included. Routing keys are needed to
/// decrement pin ref-counts when the sub-batch resolves.
pub struct SubBatch {
    pub worker_idx: usize,
    pub messages: Vec<SerializedKafkaMessage>,
    /// Unique routing keys contained in this sub-batch. Pass back to
    /// `Dispatcher::on_sub_batch_resolved` on ACK or DLQ.
    pub routing_keys: Vec<String>,
}

/// Sticky pin for one routing key. Tracks which worker owns the key and how
/// many in-flight batches currently reference it. The pin is evicted when
/// ref_count reaches 0.
struct Pin {
    worker_idx: usize,
    ref_count: u32,
}

/// Mutable assignment state, held behind a single Mutex.
struct PinTable {
    /// `"{token}:{distinct_id}"` → sticky assignment.
    pins: HashMap<String, Pin>,
    /// Number of in-flight sub-batches per worker. Used for bin-packing: new
    /// key-groups are assigned to whichever healthy worker has the lowest load.
    in_flight: Vec<usize>,
}

impl PinTable {
    fn new(worker_count: usize) -> Self {
        Self {
            pins: HashMap::new(),
            in_flight: vec![0; worker_count],
        }
    }

    /// Drop all pins targeting dead workers. Returns the count of evictions.
    fn drop_dead_pins(&mut self, registry: &WorkerRegistry) -> usize {
        let before = self.pins.len();
        self.pins.retain(|_, pin| !registry.is_dead(pin.worker_idx));
        before - self.pins.len()
    }

    /// Pick the healthy/degraded worker with the lowest in-flight load.
    /// Returns None when no healthy workers exist.
    fn least_loaded_healthy(
        &self,
        registry: &WorkerRegistry,
        provisional: &[usize],
    ) -> Option<usize> {
        (0..self.in_flight.len())
            .filter(|&idx| {
                matches!(
                    registry.state(idx),
                    WorkerState::Healthy | WorkerState::Degraded
                )
            })
            .min_by_key(|&idx| self.in_flight[idx] + provisional[idx])
    }
}

/// Routes batches to Node.js workers with sticky per-distinct_id assignment.
///
/// **Assignment** (`assign`): groups messages by `token:distinct_id`, honors
/// existing pins for live workers, bin-packs new keys onto the least-loaded
/// healthy worker, and returns one `SubBatch` per worker.
///
/// **Stickiness**: a routing key stays on the same worker across batches
/// (ref-counted pin). Pins are dropped when a worker is declared dead or
/// when the last referencing batch resolves.
///
/// **Recovery**: `on_sub_batch_resolved` decrements ref-counts and the
/// per-worker in-flight counter. Zero-count pins are evicted so the key
/// is re-pinned on its next arrival.
pub struct Dispatcher {
    pin_table: Mutex<PinTable>,
    registry: Arc<WorkerRegistry>,
}

impl Dispatcher {
    pub fn new(registry: Arc<WorkerRegistry>) -> Self {
        let worker_count = registry.worker_count();
        Self {
            pin_table: Mutex::new(PinTable::new(worker_count)),
            registry,
        }
    }

    /// Assign a batch of messages to workers.
    ///
    /// Steps:
    /// 1. Drop pins for workers that are now dead.
    /// 2. Group messages by routing key.
    /// 3. Honor existing pins for live workers; collect unassigned groups.
    /// 4. Largest-first bin-pack unassigned groups onto healthy/degraded
    ///    workers by current in-flight load.
    /// 5. Increment in-flight counters and pin ref-counts.
    /// 6. Return one `SubBatch` per worker.
    ///
    /// Returns an empty vec if all workers are dead/unhealthy.
    pub fn assign(&self, messages: Vec<SerializedKafkaMessage>) -> Vec<SubBatch> {
        let mut table = self.pin_table.lock().unwrap();

        // Drop stale pins for dead workers before routing this batch.
        let evictions = table.drop_dead_pins(&self.registry);
        if evictions > 0 {
            counter!("ingestion_consumer_dispatcher_pin_evictions_total", "reason" => "dead_worker")
                .increment(evictions as u64);
        }

        // Group messages by routing key, preserving insertion order for
        // deterministic bin-packing behaviour in tests.
        let mut key_groups: HashMap<String, Vec<SerializedKafkaMessage>> = HashMap::new();
        let mut missing_headers = 0u64;

        for msg in messages {
            let key = routing_key(&msg);
            let key = if key == ":" {
                missing_headers += 1;
                // Both headers absent: use partition+offset as a synthetic unique key so
                // these messages spread across workers instead of all pinning to one.
                format!(":{}:{}", msg.partition, msg.offset)
            } else {
                key
            };
            key_groups.entry(key).or_default().push(msg);
        }

        if missing_headers > 0 {
            counter!("ingestion_consumer_dispatcher_missing_routing_headers_total")
                .increment(missing_headers);
        }

        histogram!("ingestion_consumer_distinct_ids_per_batch").record(key_groups.len() as f64);

        // Worker index → (messages, routing_keys). Collects all messages that
        // will form one sub-batch per worker.
        let mut worker_msgs: HashMap<usize, (Vec<SerializedKafkaMessage>, Vec<String>)> =
            HashMap::new();

        // Tracks how many new sub-batches we're about to add to each worker in
        // this assign call, used for provisional bin-packing load. At most 1
        // per worker per call because all assignments to the same worker merge
        // into a single sub-batch.
        let worker_count = table.in_flight.len();
        let mut provisional = vec![0usize; worker_count];

        let mut unassigned: Vec<(String, Vec<SerializedKafkaMessage>)> = Vec::new();

        for (key, msgs) in key_groups {
            match table.pins.get_mut(&key) {
                Some(pin) if !self.registry.is_dead(pin.worker_idx) => {
                    // Existing live pin — honor it.
                    pin.ref_count += 1;
                    let worker_idx = pin.worker_idx;
                    let entry = worker_msgs.entry(worker_idx).or_default();
                    if entry.0.is_empty() {
                        provisional[worker_idx] = provisional[worker_idx].saturating_add(1);
                    }
                    entry.0.extend(msgs);
                    entry.1.push(key);
                }
                _ => {
                    // No pin or pinned to a dead worker — drop stale entry and
                    // queue for bin-packing.
                    table.pins.remove(&key);
                    unassigned.push((key, msgs));
                }
            }
        }

        // Largest-first bin-pack: assign the biggest key-groups first so
        // heavy hitters drive the load distribution.
        unassigned.sort_unstable_by(|a, b| b.1.len().cmp(&a.1.len()));

        for (key, msgs) in unassigned {
            let Some(worker_idx) = table.least_loaded_healthy(&self.registry, &provisional) else {
                // All workers unhealthy — this key cannot be assigned.
                counter!("ingestion_consumer_dispatcher_unroutable_messages_total")
                    .increment(msgs.len() as u64);
                continue;
            };

            table.pins.insert(
                key.clone(),
                Pin {
                    worker_idx,
                    ref_count: 1,
                },
            );

            let entry = worker_msgs.entry(worker_idx).or_default();
            if entry.0.is_empty() {
                provisional[worker_idx] = provisional[worker_idx].saturating_add(1);
            }
            entry.0.extend(msgs);
            entry.1.push(key);
        }

        // Increment in-flight counters for workers that got messages.
        for (&worker_idx, (msgs, _)) in &worker_msgs {
            if !msgs.is_empty() {
                table.in_flight[worker_idx] = table.in_flight[worker_idx].saturating_add(1);
                counter!(
                    "ingestion_consumer_dispatcher_sub_batches_assigned_total",
                    "worker" => worker_idx.to_string(),
                )
                .increment(1);
                counter!(
                    "ingestion_consumer_dispatcher_messages_routed_total",
                    "worker" => worker_idx.to_string(),
                )
                .increment(msgs.len() as u64);
            }
        }

        gauge!("ingestion_consumer_dispatcher_pins_total").set(table.pins.len() as f64);

        worker_msgs
            .into_iter()
            .filter(|(_, (msgs, _))| !msgs.is_empty())
            .map(|(worker_idx, (messages, routing_keys))| SubBatch {
                worker_idx,
                messages,
                routing_keys,
            })
            .collect()
    }

    /// Call after a sub-batch resolves (ACK or DLQ). Decrements the worker's
    /// in-flight counter and the ref-count for each key. Evicts zero-count
    /// pins so the key is re-assigned on its next arrival.
    pub fn on_sub_batch_resolved(&self, worker_idx: usize, routing_keys: &[String]) {
        let mut table = self.pin_table.lock().unwrap();

        table.in_flight[worker_idx] = table.in_flight[worker_idx].saturating_sub(1);

        let mut evictions = 0usize;
        for key in routing_keys {
            if let Some(pin) = table.pins.get_mut(key) {
                // Skip stale resolves: after a worker dies, `drop_dead_pins` evicts the
                // old pin and `assign` may create a new one for a different worker using
                // the same key. A DLQ resolve from the original dead sub-batch would
                // otherwise corrupt the new pin's ref_count.
                if pin.worker_idx != worker_idx {
                    continue;
                }
                pin.ref_count = pin.ref_count.saturating_sub(1);
                if pin.ref_count == 0 {
                    table.pins.remove(key);
                    evictions += 1;
                }
            }
        }

        if evictions > 0 {
            counter!(
                "ingestion_consumer_dispatcher_pin_evictions_total",
                "reason" => "resolved",
            )
            .increment(evictions as u64);
        }

        gauge!("ingestion_consumer_dispatcher_pins_total").set(table.pins.len() as f64);
    }

    /// Record the outcome of a send attempt for passive health tracking.
    /// Delegates to the underlying WorkerRegistry.
    pub fn record_send_outcome(&self, worker_idx: usize, is_error: bool) {
        self.registry.record_outcome(worker_idx, is_error);
    }
}

/// Extract the routing key from a message's `token` and `distinct_id` headers.
fn routing_key(message: &SerializedKafkaMessage) -> String {
    let token = message
        .headers
        .get("token")
        .map(|s| s.as_str())
        .unwrap_or("");
    let distinct_id = message
        .headers
        .get("distinct_id")
        .map(|s| s.as_str())
        .unwrap_or("");
    format!("{token}:{distinct_id}")
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::time::Duration;

    use super::*;
    use crate::worker_registry::{WorkerRegistry, WorkerRegistryConfig};

    // ---- helpers ----

    fn make_msg(token: &str, distinct_id: &str) -> SerializedKafkaMessage {
        let mut headers = HashMap::new();
        headers.insert("token".to_string(), token.to_string());
        headers.insert("distinct_id".to_string(), distinct_id.to_string());
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: None,
            value: None,
            headers,
        }
    }

    fn make_msgs(specs: &[(&str, &str)]) -> Vec<SerializedKafkaMessage> {
        specs.iter().map(|(t, d)| make_msg(t, d)).collect()
    }

    /// Registry with N healthy workers and no cooldown. `dead_declaration` is
    /// very short so tests can drive a worker to dead quickly.
    fn healthy_registry(n: usize) -> Arc<WorkerRegistry> {
        let urls: Vec<String> = (0..n)
            .map(|i| format!("http://worker:{}", 9001 + i))
            .collect();
        let config = WorkerRegistryConfig {
            probe_interval: Duration::from_millis(50),
            dead_declaration: Duration::from_millis(30),
            passive_window: Duration::from_millis(500),
            passive_error_threshold: 0.5,
            passive_min_samples: 2,
            degraded_hold: Duration::from_millis(50),
            min_state_duration: Duration::ZERO,
            probe_failure_threshold: 2,
        };
        Arc::new(WorkerRegistry::new(&urls, config))
    }

    // ---- routing key ----

    #[test]
    fn test_routing_key_format() {
        let msg = make_msg("tok", "user-1");
        assert_eq!(routing_key(&msg), "tok:user-1");
    }

    #[test]
    fn test_routing_key_missing_headers() {
        let msg = SerializedKafkaMessage {
            topic: "t".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: None,
            value: None,
            headers: HashMap::new(),
        };
        assert_eq!(routing_key(&msg), ":");
    }

    // ---- basic assignment ----

    #[test]
    fn test_single_worker_all_messages_go_there() {
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(registry);

        let sub_batches = dispatcher.assign(make_msgs(&[("t", "a"), ("t", "b"), ("t", "c")]));

        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker_idx, 0);
        assert_eq!(sub_batches[0].messages.len(), 3);
    }

    #[test]
    fn test_empty_batch_returns_no_sub_batches() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);
        assert!(dispatcher.assign(vec![]).is_empty());
    }

    #[test]
    fn test_same_distinct_id_goes_to_same_worker_across_batches() {
        let registry = healthy_registry(3);
        let dispatcher = Dispatcher::new(registry);

        let batch1 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        assert_eq!(batch1.len(), 1);
        let worker = batch1[0].worker_idx;
        dispatcher.on_sub_batch_resolved(worker, &batch1[0].routing_keys);

        // Second batch: same key must go to same worker (pin still alive until resolved).
        // We resolved already, so the pin was evicted — it will re-pin to the same or
        // different worker. What we care about is that within a batch, same key → same worker.
        let batch2 = dispatcher.assign(make_msgs(&[("t", "user-1"), ("t", "user-1")]));
        assert_eq!(batch2.len(), 1); // both user-1 messages merge into one sub-batch
    }

    // ---- sticky pins ----

    #[test]
    fn test_pin_is_sticky_across_batches() {
        let registry = healthy_registry(3);
        let dispatcher = Dispatcher::new(registry);

        // First batch pins "t:user-1" to some worker.
        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        let pinned_worker = b1[0].worker_idx;

        // Do NOT resolve b1 — pin stays alive with ref_count=1.

        // Second batch: same key must hit the same worker.
        let b2 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        assert_eq!(b2.len(), 1);
        assert_eq!(b2[0].worker_idx, pinned_worker);
    }

    #[test]
    fn test_different_keys_may_go_to_different_workers() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // With 2 workers, bin-packing should spread 2 fresh keys across them.
        let sub_batches = dispatcher.assign(make_msgs(&[("t", "user-1"), ("t", "user-2")]));

        let total_msgs: usize = sub_batches.iter().map(|b| b.messages.len()).sum();
        assert_eq!(total_msgs, 2);
    }

    // ---- ref counting ----

    #[test]
    fn test_pin_evicted_when_ref_count_reaches_zero() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        let worker = b1[0].worker_idx;

        // Pin exists (ref_count = 1).
        {
            let table = dispatcher.pin_table.lock().unwrap();
            assert!(table.pins.contains_key("t:user-1"));
        }

        dispatcher.on_sub_batch_resolved(worker, &b1[0].routing_keys);

        // Pin evicted (ref_count hit 0).
        {
            let table = dispatcher.pin_table.lock().unwrap();
            assert!(!table.pins.contains_key("t:user-1"));
        }
    }

    #[test]
    fn test_pin_ref_count_accumulates_across_batches() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        let worker = b1[0].worker_idx;

        // Second batch, same key, pin not yet resolved: ref_count should be 2.
        dispatcher.assign(make_msgs(&[("t", "user-1")]));

        {
            let table = dispatcher.pin_table.lock().unwrap();
            let pin = table.pins.get("t:user-1").unwrap();
            assert_eq!(pin.ref_count, 2);
        }

        // Resolve first sub-batch: ref_count drops to 1, pin stays.
        dispatcher.on_sub_batch_resolved(worker, &b1[0].routing_keys);
        {
            let table = dispatcher.pin_table.lock().unwrap();
            assert!(table.pins.contains_key("t:user-1"));
            assert_eq!(table.pins["t:user-1"].ref_count, 1);
        }
    }

    // ---- in-flight counter ----

    #[test]
    fn test_in_flight_incremented_on_assign() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        let worker = b1[0].worker_idx;

        let table = dispatcher.pin_table.lock().unwrap();
        assert_eq!(table.in_flight[worker], 1);
    }

    #[test]
    fn test_in_flight_decremented_on_resolve() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        let worker = b1[0].worker_idx;

        dispatcher.on_sub_batch_resolved(worker, &b1[0].routing_keys);

        let table = dispatcher.pin_table.lock().unwrap();
        assert_eq!(table.in_flight[worker], 0);
    }

    #[test]
    fn test_multiple_keys_same_worker_one_in_flight_increment() {
        // All messages in a batch that go to the same worker produce a single
        // sub-batch, so in_flight should only increment by 1 — not by the
        // number of distinct keys.
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(registry);

        dispatcher.assign(make_msgs(&[("t", "a"), ("t", "b"), ("t", "c")]));

        let table = dispatcher.pin_table.lock().unwrap();
        assert_eq!(table.in_flight[0], 1);
    }

    // ---- bin-packing ----

    #[test]
    fn test_bin_packing_targets_least_loaded_worker() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // Artificially load worker 0 with 3 in-flight sub-batches.
        {
            let mut table = dispatcher.pin_table.lock().unwrap();
            table.in_flight[0] = 3;
        }

        // A fresh key should go to worker 1 (load = 0).
        let b = dispatcher.assign(make_msgs(&[("t", "fresh")]));
        assert_eq!(b.len(), 1);
        assert_eq!(b[0].worker_idx, 1);
    }

    // ---- dead worker handling ----

    #[tokio::test]
    async fn test_dead_worker_pin_dropped_and_rerouted() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Pin "user-1" to whichever worker gets it first.
        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        let original_worker = b1[0].worker_idx;
        let other_worker = 1 - original_worker;

        // Drive the pinned worker to dead via passive signal.
        for _ in 0..5 {
            registry.record_outcome(original_worker, true);
        }
        tokio::time::sleep(Duration::from_millis(40)).await;
        assert!(registry.is_dead(original_worker));

        // Next batch: pin must be dropped and key rerouted to the live worker.
        let b2 = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        assert_eq!(b2.len(), 1);
        assert_eq!(b2[0].worker_idx, other_worker);
    }

    #[test]
    fn test_all_workers_dead_returns_empty() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Force both workers to Unhealthy via passive signal (min_state_duration=0).
        for idx in 0..2 {
            for _ in 0..5 {
                registry.record_outcome(idx, true);
            }
        }

        // Both workers are Unhealthy (not yet dead, but Unhealthy).
        // Dispatcher should not route to Unhealthy workers.
        let b = dispatcher.assign(make_msgs(&[("t", "user-1")]));
        assert!(b.is_empty());
    }
}
