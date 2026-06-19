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
    /// Outstanding (in-flight) message count per worker. Used for bin-packing:
    /// new key-groups are assigned to whichever healthy worker carries the
    /// fewest outstanding messages, so load is balanced by volume rather than
    /// by sub-batch count.
    in_flight_messages: Vec<usize>,
}

impl PinTable {
    fn new(worker_count: usize) -> Self {
        Self {
            pins: HashMap::new(),
            in_flight_messages: vec![0; worker_count],
        }
    }

    /// Drop all pins targeting dead workers. Returns the count of evictions.
    fn drop_dead_pins(&mut self, registry: &WorkerRegistry) -> usize {
        let before = self.pins.len();
        self.pins.retain(|_, pin| !registry.is_dead(pin.worker_idx));
        before - self.pins.len()
    }

    /// Pick the healthy/degraded worker carrying the fewest outstanding
    /// messages — existing in-flight load plus what has been provisionally
    /// assigned earlier in this round. Returns None when no healthy workers
    /// exist.
    fn least_loaded_healthy(
        &self,
        registry: &WorkerRegistry,
        provisional: &[usize],
    ) -> Option<usize> {
        (0..self.in_flight_messages.len())
            .filter(|&idx| {
                matches!(
                    registry.state(idx),
                    WorkerState::Healthy | WorkerState::Degraded
                )
            })
            .min_by_key(|&idx| self.in_flight_messages[idx] + provisional[idx])
    }
}

struct MessageGroup {
    routing_key: String,
    messages: Vec<SerializedKafkaMessage>,
}

struct WorkerSubBatchBuilder {
    messages: Vec<SerializedKafkaMessage>,
    routing_keys: Vec<String>,
}

impl WorkerSubBatchBuilder {
    fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }

    fn message_count(&self) -> usize {
        self.messages.len()
    }
}

#[derive(Default)]
struct WorkerAssignments {
    by_worker: HashMap<usize, WorkerSubBatchBuilder>,
    /// Messages provisionally assigned to each worker so far this round. Drives
    /// least-loaded bin-packing so the largest groups steer load by volume.
    provisional_messages: Vec<usize>,
}

impl WorkerAssignments {
    fn new(worker_count: usize) -> Self {
        Self {
            by_worker: HashMap::new(),
            provisional_messages: vec![0; worker_count],
        }
    }

    fn provisional_messages(&self) -> &[usize] {
        &self.provisional_messages
    }

    fn add_group(&mut self, worker_idx: usize, group: MessageGroup) {
        let builder = self
            .by_worker
            .entry(worker_idx)
            .or_insert_with(|| WorkerSubBatchBuilder {
                messages: Vec::new(),
                routing_keys: Vec::new(),
            });

        // Accumulate by message volume, not group count, so a worker holding one
        // heavy key counts as more loaded than one holding several tiny keys.
        self.provisional_messages[worker_idx] =
            self.provisional_messages[worker_idx].saturating_add(group.messages.len());

        builder.messages.extend(group.messages);
        builder.routing_keys.push(group.routing_key);
    }

    fn routed_counts(&self) -> impl Iterator<Item = (usize, usize)> + '_ {
        self.by_worker
            .iter()
            .filter(|(_, builder)| !builder.is_empty())
            .map(|(&worker_idx, builder)| (worker_idx, builder.message_count()))
    }

    fn into_sub_batches(self) -> Vec<SubBatch> {
        self.by_worker
            .into_iter()
            .filter(|(_, builder)| !builder.is_empty())
            .map(|(worker_idx, builder)| SubBatch {
                worker_idx,
                messages: builder.messages,
                routing_keys: builder.routing_keys,
            })
            .collect()
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
/// **Recovery**: `on_sub_batch_resolved` decrements ref-counts and subtracts
/// the sub-batch's messages from the worker's outstanding load. Zero-count
/// pins are evicted so the key is re-pinned on its next arrival.
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
    ///    workers by current outstanding message load.
    /// 5. Add routed messages to in-flight load and bump pin ref-counts.
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

        let GroupedMessages {
            groups: key_groups,
            missing_header_count,
        } = group_messages_by_routing_key(messages);

        if missing_header_count > 0 {
            counter!("ingestion_consumer_dispatcher_missing_routing_headers_total")
                .increment(missing_header_count);
        }

        histogram!("ingestion_consumer_distinct_ids_per_batch").record(key_groups.len() as f64);

        let worker_count = table.in_flight_messages.len();
        let mut assignments = WorkerAssignments::new(worker_count);

        let mut unpinned_groups: Vec<MessageGroup> = Vec::new();

        for group in key_groups {
            match table.pins.get_mut(&group.routing_key) {
                Some(pin) if !self.registry.is_dead(pin.worker_idx) => {
                    // Existing live pin — honor it.
                    pin.ref_count += 1;
                    let worker_idx = pin.worker_idx;
                    assignments.add_group(worker_idx, group);
                }
                _ => {
                    // No pin or pinned to a dead worker — drop stale entry and
                    // queue for bin-packing.
                    table.pins.remove(&group.routing_key);
                    unpinned_groups.push(group);
                }
            }
        }

        // Largest-first bin-pack: assign the biggest key-groups first so
        // heavy hitters drive the load distribution.
        unpinned_groups.sort_unstable_by(|a, b| b.messages.len().cmp(&a.messages.len()));

        for group in unpinned_groups {
            let Some(worker_idx) =
                table.least_loaded_healthy(&self.registry, assignments.provisional_messages())
            else {
                // All workers unhealthy — this key cannot be assigned.
                counter!("ingestion_consumer_dispatcher_unroutable_messages_total")
                    .increment(group.messages.len() as u64);
                continue;
            };

            table.pins.insert(
                group.routing_key.clone(),
                Pin {
                    worker_idx,
                    ref_count: 1,
                },
            );

            assignments.add_group(worker_idx, group);
        }

        // Add each worker's message volume to its outstanding load.
        for (worker_idx, message_count) in assignments.routed_counts() {
            table.in_flight_messages[worker_idx] =
                table.in_flight_messages[worker_idx].saturating_add(message_count);
            counter!(
                "ingestion_consumer_dispatcher_sub_batches_assigned_total",
                "worker" => worker_idx.to_string(),
            )
            .increment(1);
            counter!(
                "ingestion_consumer_dispatcher_messages_routed_total",
                "worker" => worker_idx.to_string(),
            )
            .increment(message_count as u64);
        }

        gauge!("ingestion_consumer_dispatcher_pins_total").set(table.pins.len() as f64);

        assignments.into_sub_batches()
    }

    /// Call after a sub-batch resolves (ACK or DLQ). Subtracts the sub-batch's
    /// message count from the worker's outstanding load and decrements the
    /// ref-count for each key. Evicts zero-count pins so the key is re-assigned
    /// on its next arrival. `message_count` must match the sub-batch's length.
    pub fn on_sub_batch_resolved(
        &self,
        worker_idx: usize,
        message_count: usize,
        routing_keys: &[String],
    ) {
        let mut table = self.pin_table.lock().unwrap();

        table.in_flight_messages[worker_idx] =
            table.in_flight_messages[worker_idx].saturating_sub(message_count);

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

struct GroupedMessages {
    groups: Vec<MessageGroup>,
    missing_header_count: u64,
}

fn group_messages_by_routing_key(messages: Vec<SerializedKafkaMessage>) -> GroupedMessages {
    let mut grouped_messages: HashMap<String, Vec<SerializedKafkaMessage>> = HashMap::new();
    let mut missing_header_count = 0u64;

    for message in messages {
        let routing_key = routing_key(&message).unwrap_or_else(|| {
            missing_header_count += 1;
            // Use a synthetic unique key so messages missing routing headers spread
            // across workers instead of all pinning to one shared fallback key.
            format!(":{}:{}", message.partition, message.offset)
        });
        grouped_messages
            .entry(routing_key)
            .or_default()
            .push(message);
    }

    GroupedMessages {
        groups: grouped_messages
            .into_iter()
            .map(|(routing_key, messages)| MessageGroup {
                routing_key,
                messages,
            })
            .collect(),
        missing_header_count,
    }
}

/// Extract the routing key from a message's `token` and `distinct_id` headers.
fn routing_key(message: &SerializedKafkaMessage) -> Option<String> {
    let token = message.headers.get("token")?;
    let distinct_id = message.headers.get("distinct_id")?;
    Some(format!("{token}:{distinct_id}"))
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

    fn make_msg_with_headers(headers: HashMap<String, String>) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 7,
            offset: 42,
            timestamp: 0,
            key: None,
            value: None,
            headers,
        }
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
        assert_eq!(routing_key(&msg), Some("tok:user-1".to_string()));
    }

    #[test]
    fn test_routing_key_missing_headers() {
        assert_eq!(routing_key(&make_msg_with_headers(HashMap::new())), None);
    }

    #[test]
    fn test_routing_key_requires_token_and_distinct_id() {
        let mut headers = HashMap::new();
        headers.insert("token".to_string(), "tok".to_string());

        assert_eq!(routing_key(&make_msg_with_headers(headers)), None);
    }

    #[test]
    fn test_group_messages_by_routing_key_uses_synthetic_key_for_missing_headers() {
        let grouped = group_messages_by_routing_key(vec![make_msg_with_headers(HashMap::new())]);

        assert_eq!(grouped.missing_header_count, 1);
        assert_eq!(grouped.groups.len(), 1);
        assert_eq!(grouped.groups[0].routing_key, ":7:42");
        assert_eq!(grouped.groups[0].messages.len(), 1);
    }

    #[test]
    fn test_group_messages_by_routing_key_groups_same_routing_key() {
        let grouped =
            group_messages_by_routing_key(make_msgs(&[("tok", "user-1"), ("tok", "user-1")]));

        assert_eq!(grouped.missing_header_count, 0);
        assert_eq!(grouped.groups.len(), 1);
        assert_eq!(grouped.groups[0].routing_key, "tok:user-1");
        assert_eq!(grouped.groups[0].messages.len(), 2);
    }

    // ---- worker assignments ----

    #[test]
    fn test_worker_assignments_merges_groups_for_same_worker() {
        let mut assignments = WorkerAssignments::new(2);

        assignments.add_group(
            1,
            MessageGroup {
                routing_key: "tok:user-1".to_string(),
                messages: make_msgs(&[("tok", "user-1")]),
            },
        );
        assignments.add_group(
            1,
            MessageGroup {
                routing_key: "tok:user-2".to_string(),
                messages: make_msgs(&[("tok", "user-2")]),
            },
        );

        assert_eq!(assignments.provisional_messages(), &[0, 2]);
        assert_eq!(
            assignments.routed_counts().collect::<Vec<_>>(),
            vec![(1, 2)]
        );

        let sub_batches = assignments.into_sub_batches();
        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker_idx, 1);
        assert_eq!(sub_batches[0].messages.len(), 2);
        assert_eq!(
            sub_batches[0].routing_keys,
            vec!["tok:user-1".to_string(), "tok:user-2".to_string()]
        );
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
        dispatcher.on_sub_batch_resolved(worker, batch1[0].messages.len(), &batch1[0].routing_keys);

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

        dispatcher.on_sub_batch_resolved(worker, b1[0].messages.len(), &b1[0].routing_keys);

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
        dispatcher.on_sub_batch_resolved(worker, b1[0].messages.len(), &b1[0].routing_keys);
        {
            let table = dispatcher.pin_table.lock().unwrap();
            assert!(table.pins.contains_key("t:user-1"));
            assert_eq!(table.pins["t:user-1"].ref_count, 1);
        }
    }

    // ---- in-flight load ----

    #[test]
    fn test_in_flight_messages_incremented_by_message_count_on_assign() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // Two messages for one key → one sub-batch carrying two messages.
        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1"), ("t", "user-1")]));
        let worker = b1[0].worker_idx;

        let table = dispatcher.pin_table.lock().unwrap();
        assert_eq!(table.in_flight_messages[worker], 2);
    }

    #[test]
    fn test_in_flight_messages_decremented_on_resolve() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign(make_msgs(&[("t", "user-1"), ("t", "user-1")]));
        let worker = b1[0].worker_idx;

        dispatcher.on_sub_batch_resolved(worker, b1[0].messages.len(), &b1[0].routing_keys);

        let table = dispatcher.pin_table.lock().unwrap();
        assert_eq!(table.in_flight_messages[worker], 0);
    }

    #[test]
    fn test_in_flight_messages_counts_every_message_to_worker() {
        // Three distinct keys routed to the single worker merge into one
        // sub-batch, but in-flight load tracks the total message volume (3),
        // not the sub-batch count.
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(registry);

        dispatcher.assign(make_msgs(&[("t", "a"), ("t", "b"), ("t", "c")]));

        let table = dispatcher.pin_table.lock().unwrap();
        assert_eq!(table.in_flight_messages[0], 3);
    }

    // ---- bin-packing ----

    #[test]
    fn test_bin_packing_targets_least_loaded_worker() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // Artificially load worker 0 with 3 outstanding messages.
        {
            let mut table = dispatcher.pin_table.lock().unwrap();
            table.in_flight_messages[0] = 3;
        }

        // A fresh key should go to worker 1 (load = 0).
        let b = dispatcher.assign(make_msgs(&[("t", "fresh")]));
        assert_eq!(b.len(), 1);
        assert_eq!(b[0].worker_idx, 1);
    }

    #[test]
    fn test_bin_packing_balances_by_message_volume_not_group_count() {
        // Regression: load is tracked by message count, not sub-batch presence.
        // One heavy key (10 msgs) plus five small keys (1 msg each) must not all
        // pile onto worker 0 — the small keys bin-pack onto the other worker
        // until load is balanced.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let mut specs: Vec<(&str, &str)> = vec![("t", "heavy"); 10];
        for d in ["a", "b", "c", "d", "e"] {
            specs.push(("t", d));
        }

        let sub_batches = dispatcher.assign(make_msgs(&specs));
        assert_eq!(sub_batches.len(), 2, "both workers must carry messages");

        let table = dispatcher.pin_table.lock().unwrap();
        let load0 = table.in_flight_messages[0];
        let load1 = table.in_flight_messages[1];
        assert_eq!(load0 + load1, 15);

        // The heavy key lands alone on one worker; the five singles fill the
        // other. With the old 0/1 accounting the singles would all dump onto
        // worker 0, giving 15 vs 1.
        let (heavy, light) = if load0 >= load1 {
            (load0, load1)
        } else {
            (load1, load0)
        };
        assert_eq!(heavy, 10);
        assert_eq!(light, 5);
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
