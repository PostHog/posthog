use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use metrics::{counter, gauge, histogram};

use crate::routing::{Router, RoutingStrategy, WorkerLoad};
use crate::stash::{DeferredGroup, Stash};
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::{WorkerId, WorkerRegistry};

/// A slice of a batch assigned to one worker, carrying the messages and the
/// routing keys of all distinct_ids included. Routing keys are needed to
/// decrement pin ref-counts when the sub-batch resolves.
pub struct SubBatch {
    pub worker: WorkerId,
    pub messages: Vec<SerializedKafkaMessage>,
    /// Unique routing keys contained in this sub-batch. Pass back to
    /// `Dispatcher::on_sub_batch_resolved` on ACK or DLQ.
    pub routing_keys: Vec<String>,
}

/// Sticky pin for one routing key. Tracks which worker owns the key and how
/// many in-flight batches reference it. The pin is evicted when ref_count
/// reaches 0 and the key has no deferred groups outstanding (see [`Stash`]).
struct Pin {
    worker: WorkerId,
    ref_count: u32,
}

/// Mutable assignment state, held behind a single Mutex.
struct PinTable {
    /// `"{token}:{distinct_id}"` → sticky assignment.
    pins: HashMap<String, Pin>,
    /// Outstanding (in-flight) message count per worker. Both routing strategies
    /// use it as the per-worker load signal so new key-groups land on
    /// lightly-loaded workers — load is balanced by message volume rather than
    /// by sub-batch count. A worker with no outstanding messages has no entry.
    in_flight: WorkerLoad,
    /// Messages deferred because their key's worker is draining/dead, keyed by
    /// batch, plus per-key outstanding counts. Flushed by `flush_deferred`.
    stash: Stash,
}

impl PinTable {
    fn new() -> Self {
        Self {
            pins: HashMap::new(),
            in_flight: WorkerLoad::new(),
            stash: Stash::new(),
        }
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
    by_worker: HashMap<WorkerId, WorkerSubBatchBuilder>,
}

impl WorkerAssignments {
    fn new() -> Self {
        Self::default()
    }

    fn add_group(&mut self, worker: WorkerId, group: MessageGroup) {
        let builder = self
            .by_worker
            .entry(worker)
            .or_insert_with(|| WorkerSubBatchBuilder {
                messages: Vec::new(),
                routing_keys: Vec::new(),
            });

        builder.messages.extend(group.messages);
        builder.routing_keys.push(group.routing_key);
    }

    fn routed_counts(&self) -> impl Iterator<Item = (WorkerId, usize)> + '_ {
        self.by_worker
            .iter()
            .filter(|(_, builder)| !builder.is_empty())
            .map(|(worker, builder)| (worker.clone(), builder.message_count()))
    }

    fn into_sub_batches(self) -> Vec<SubBatch> {
        self.by_worker
            .into_iter()
            .filter(|(_, builder)| !builder.is_empty())
            .map(|(worker, builder)| SubBatch {
                worker,
                messages: builder.messages,
                routing_keys: builder.routing_keys,
            })
            .collect()
    }
}

/// Routes batches to Node.js workers with sticky per-distinct_id assignment.
///
/// **Assignment** (`assign`): groups messages by `token:distinct_id`, honors
/// existing pins for live workers, routes new keys onto a healthy worker via the
/// configured [`RoutingStrategy`], and returns one `SubBatch` per worker.
///
/// **Stickiness**: a routing key stays on the same worker across batches
/// (ref-counted pin). Pins are dropped when a worker is declared dead (or leaves
/// the pool) or when the last referencing batch resolves.
///
/// **Recovery**: `on_sub_batch_resolved` decrements ref-counts and subtracts
/// the sub-batch's messages from the worker's outstanding load. Zero-count
/// pins are evicted so the key is re-pinned on its next arrival.
pub struct Dispatcher {
    pin_table: Mutex<PinTable>,
    registry: Arc<WorkerRegistry>,
    /// Worker selector for unpinned keys. Behind its own mutex because P2C
    /// selection mutates the RNG.
    router: Mutex<Router>,
}

impl Dispatcher {
    /// Construct a dispatcher with the default routing strategy.
    pub fn new(registry: Arc<WorkerRegistry>) -> Self {
        Self::with_strategy(registry, RoutingStrategy::default())
    }

    /// Construct a dispatcher with an explicit routing strategy.
    pub fn with_strategy(registry: Arc<WorkerRegistry>, strategy: RoutingStrategy) -> Self {
        Self {
            pin_table: Mutex::new(PinTable::new()),
            registry,
            router: Mutex::new(Router::new(strategy)),
        }
    }

    /// Test-only constructor with a seeded RNG so P2C selection is deterministic.
    #[cfg(test)]
    fn with_strategy_seeded(
        registry: Arc<WorkerRegistry>,
        strategy: RoutingStrategy,
        seed: u64,
    ) -> Self {
        Self {
            pin_table: Mutex::new(PinTable::new()),
            registry,
            router: Mutex::new(Router::with_seed(strategy, seed)),
        }
    }

    /// Assign a batch of messages to workers.
    ///
    /// Groups messages by routing key, then per group:
    /// - honor an existing pin to a worker still taking work;
    /// - **defer** (stash under `batch_id`) a key pinned to a draining/dead
    ///   worker, or one that already has deferred groups pending, so newer
    ///   messages can't race ahead of the key's earlier ones;
    /// - otherwise route fresh via the configured strategy — or defer the
    ///   group when no worker is routable at all, so a transient full-pool
    ///   outage holds messages instead of failing the batch.
    ///
    /// Returns one `SubBatch` per worker to send now. Deferred groups stay in
    /// the stash and are flushed later via [`Dispatcher::flush_deferred`].
    pub fn assign(&self, batch_id: &str, messages: Vec<SerializedKafkaMessage>) -> Vec<SubBatch> {
        let mut table = self.pin_table.lock().unwrap();

        let GroupedMessages {
            groups: key_groups,
            missing_header_count,
        } = group_messages_by_routing_key(messages);

        if missing_header_count > 0 {
            counter!("ingestion_consumer_dispatcher_missing_routing_headers_total")
                .increment(missing_header_count);
        }

        histogram!("ingestion_consumer_distinct_ids_per_batch").record(key_groups.len() as f64);

        let mut assignments = WorkerAssignments::new();

        // Candidate workers and their working load for this round. `working_load`
        // starts from each candidate's outstanding load and is bumped as groups
        // are assigned, so intra-batch placement accounts for earlier picks.
        let healthy = self.registry.healthy_workers();
        let mut working_load: WorkerLoad = healthy
            .iter()
            .map(|w| (w.clone(), table.in_flight.get(w).copied().unwrap_or(0)))
            .collect();

        let mut unpinned_groups: Vec<MessageGroup> = Vec::new();
        let mut deferred_count = 0u64;
        let mut unroutable_deferred_count = 0u64;

        for group in key_groups {
            let pinned_worker = table.pins.get(&group.routing_key).map(|p| p.worker.clone());
            match pinned_worker {
                Some(worker)
                    if !table.stash.is_deferring(&group.routing_key)
                        && !self.registry.is_dead(&worker)
                        && !self.registry.is_draining(&worker) =>
                {
                    // Live pin on a worker still taking work, nothing deferred
                    // ahead of it — honor it.
                    table.pins.get_mut(&group.routing_key).unwrap().ref_count += 1;
                    bump_load(&mut working_load, &worker, group.messages.len());
                    assignments.add_group(worker, group);
                }
                Some(_) => {
                    // Pinned to a draining/dead worker, or the key already has
                    // deferred groups pending — defer so newer messages can't
                    // race ahead of the key's earlier in-flight/deferred ones.
                    table.stash.defer(
                        batch_id,
                        DeferredGroup {
                            routing_key: group.routing_key,
                            messages: group.messages,
                        },
                    );
                    deferred_count += 1;
                }
                None if table.stash.is_deferring(&group.routing_key) => {
                    // No pin, but the key already has stashed groups (it was
                    // unroutable earlier) — newer messages must queue behind
                    // them, not race ahead.
                    table.stash.defer(
                        batch_id,
                        DeferredGroup {
                            routing_key: group.routing_key,
                            messages: group.messages,
                        },
                    );
                    deferred_count += 1;
                }
                None => unpinned_groups.push(group),
            }
        }

        // Route the unpinned groups via the configured strategy. Bin-packing
        // wants the biggest groups placed first so heavy hitters drive the load
        // distribution; P2C is per-group and order-independent.
        let mut router = self.router.lock().unwrap();

        if router.prefers_largest_first() {
            unpinned_groups.sort_unstable_by(|a, b| b.messages.len().cmp(&a.messages.len()));
        }

        for group in unpinned_groups {
            let Some(worker) = router.select(&healthy, &working_load) else {
                // No routable worker right now (e.g. the whole pool is draining
                // during a deploy overlap). Stash the group so the flush loop
                // can route it once a worker returns — dropping it would fail
                // the whole batch and restart the process for a transient
                // condition.
                counter!("ingestion_consumer_dispatcher_unroutable_messages_total")
                    .increment(group.messages.len() as u64);
                table.stash.defer(
                    batch_id,
                    DeferredGroup {
                        routing_key: group.routing_key,
                        messages: group.messages,
                    },
                );
                unroutable_deferred_count += 1;
                continue;
            };

            bump_load(&mut working_load, &worker, group.messages.len());
            table.pins.insert(
                group.routing_key.clone(),
                Pin {
                    worker: worker.clone(),
                    ref_count: 1,
                },
            );
            assignments.add_group(worker, group);
        }
        drop(router);

        // Add each worker's message volume to its outstanding load.
        for (worker, message_count) in assignments.routed_counts() {
            *table.in_flight.entry(worker.clone()).or_insert(0) += message_count;
            counter!(
                "ingestion_consumer_dispatcher_sub_batches_assigned_total",
                "worker" => worker.clone(),
            )
            .increment(1);
            counter!(
                "ingestion_consumer_dispatcher_messages_routed_total",
                "worker" => worker.clone(),
            )
            .increment(message_count as u64);
        }

        if deferred_count > 0 {
            counter!(
                "ingestion_consumer_dispatcher_deferred_groups_total",
                "reason" => "drain",
            )
            .increment(deferred_count);
        }
        if unroutable_deferred_count > 0 {
            counter!(
                "ingestion_consumer_dispatcher_deferred_groups_total",
                "reason" => "unroutable",
            )
            .increment(unroutable_deferred_count);
        }
        gauge!("ingestion_consumer_dispatcher_pins_total").set(table.pins.len() as f64);
        record_stash_gauges(&table.stash);

        assignments.into_sub_batches()
    }

    /// Whether `batch_id` still has deferred groups awaiting flush.
    pub fn has_deferred(&self, batch_id: &str) -> bool {
        self.pin_table.lock().unwrap().stash.has_batch(batch_id)
    }

    /// Whether the worker has any in-flight (sent, unresolved) messages. The
    /// reaper uses this to promptly complete a drain for a worker that was idle
    /// when it left the pool — its in-flight never resolves, so the registry's
    /// `complete_drain` (which fires from `on_sub_batch_resolved`) never would.
    pub fn has_in_flight(&self, worker: &WorkerId) -> bool {
        self.pin_table
            .lock()
            .unwrap()
            .in_flight
            .get(worker)
            .is_some_and(|&n| n > 0)
    }

    /// Total messages currently held in the stash across all batches. Exposed
    /// for observability and for tests to synchronize on deferral.
    pub fn stashed_messages(&self) -> usize {
        self.pin_table.lock().unwrap().stash.message_count()
    }

    /// Number of live sticky pins. Exposed so tests can assert the pin table
    /// drains back to zero once all in-flight work has resolved — a leak here
    /// permanently skews routing.
    pub fn pin_count(&self) -> usize {
        self.pin_table.lock().unwrap().pins.len()
    }

    /// Total outstanding (sent, unresolved) messages across all workers.
    /// Exposed so tests can assert the load accounting drains back to zero.
    pub fn total_in_flight(&self) -> usize {
        self.pin_table.lock().unwrap().in_flight.values().sum()
    }

    /// Defer messages whose send failed (the worker died mid-send) so they can be
    /// replayed in order. Must be called **before** `on_sub_batch_resolved` for
    /// the failed sub-batch, so the ref-count drop doesn't evict the pin while
    /// the key still has work to replay.
    pub fn defer_failed(&self, batch_id: &str, messages: Vec<SerializedKafkaMessage>) {
        let mut table = self.pin_table.lock().unwrap();
        let GroupedMessages { groups, .. } = group_messages_by_routing_key(messages);
        let deferred_count = groups.len() as u64;
        for group in groups {
            table.stash.defer(
                batch_id,
                DeferredGroup {
                    routing_key: group.routing_key,
                    messages: group.messages,
                },
            );
        }
        if deferred_count > 0 {
            counter!(
                "ingestion_consumer_dispatcher_deferred_groups_total",
                "reason" => "send_failed",
            )
            .increment(deferred_count);
        }
        record_stash_gauges(&table.stash);
    }

    /// Flush a batch's deferred groups: route each to a healthy worker now that
    /// the key's earlier in-flight has resolved, re-pinning it. Returns the
    /// sub-batches to send. Groups that can't route yet (no healthy worker) stay
    /// stashed — call again after a backoff. Cross-key order is preserved because
    /// the consumer flushes batches oldest-first.
    pub fn flush_deferred(&self, batch_id: &str) -> Vec<SubBatch> {
        let mut table = self.pin_table.lock().unwrap();
        let groups = table.stash.take_batch(batch_id);
        if groups.is_empty() {
            return Vec::new();
        }

        let healthy = self.registry.healthy_workers();
        let mut working_load: WorkerLoad = healthy
            .iter()
            .map(|w| (w.clone(), table.in_flight.get(w).copied().unwrap_or(0)))
            .collect();
        let mut assignments = WorkerAssignments::new();

        let mut router = self.router.lock().unwrap();
        for group in groups {
            // Prefer the key's existing pin when it still points to a healthy
            // worker, so a key deferred across several batches re-homes to a
            // single survivor — preserving per-distinct_id (person-batching)
            // locality instead of scattering its messages across workers.
            // Fall back to load-based selection for a fresh key, or when the
            // pinned worker is itself unhealthy (e.g. the drainer we're leaving).
            let sticky = table
                .pins
                .get(&group.routing_key)
                .map(|pin| pin.worker.clone())
                .filter(|w| healthy.contains(w));
            let worker = match sticky {
                Some(worker) => worker,
                None => {
                    let Some(worker) = router.select(&healthy, &working_load) else {
                        // No healthy worker yet — keep it stashed for a later flush.
                        table.stash.put_back(batch_id, group);
                        continue;
                    };
                    worker
                }
            };
            bump_load(&mut working_load, &worker, group.messages.len());
            // Re-pin the key to the new worker. The deferral is NOT cleared here:
            // the flushed messages are now in flight but not yet ACKed, so the key
            // must keep deferring until that send resolves (see the `clears_deferral`
            // path in `on_sub_batch_resolved`). Otherwise a newer batch could honor
            // this fresh pin and race the not-yet-landed flushed messages.
            match table.pins.get_mut(&group.routing_key) {
                Some(pin) => {
                    pin.worker = worker.clone();
                    pin.ref_count += 1;
                }
                None => {
                    table.pins.insert(
                        group.routing_key.clone(),
                        Pin {
                            worker: worker.clone(),
                            ref_count: 1,
                        },
                    );
                }
            }
            assignments.add_group(
                worker,
                MessageGroup {
                    routing_key: group.routing_key,
                    messages: group.messages,
                },
            );
        }
        drop(router);

        for (worker, message_count) in assignments.routed_counts() {
            *table.in_flight.entry(worker.clone()).or_insert(0) += message_count;
            counter!(
                "ingestion_consumer_dispatcher_deferred_flushed_total",
                "worker" => worker.to_string(),
            )
            .increment(message_count as u64);
        }
        gauge!("ingestion_consumer_dispatcher_pins_total").set(table.pins.len() as f64);
        record_stash_gauges(&table.stash);

        assignments.into_sub_batches()
    }

    /// Call after a sub-batch resolves (ACK or DLQ). Subtracts the sub-batch's
    /// message count from the worker's outstanding load and decrements the
    /// ref-count for each key. Evicts zero-count pins so the key is re-assigned
    /// on its next arrival. `message_count` must match the sub-batch's length.
    ///
    /// `clears_deferral` must be true only when resolving a **flushed** sub-batch
    /// (one produced by `flush_deferred`): it decrements the key's outstanding
    /// deferral count, so the key keeps deferring newer messages from the moment
    /// it was first deferred until its flushed messages have actually landed —
    /// closing the window where a newer batch could race them.
    pub fn on_sub_batch_resolved(
        &self,
        worker: &WorkerId,
        message_count: usize,
        routing_keys: &[String],
        clears_deferral: bool,
    ) {
        let mut table = self.pin_table.lock().unwrap();

        let now_zero = match table.in_flight.get_mut(worker) {
            Some(load) => {
                *load = load.saturating_sub(message_count);
                *load == 0
            }
            None => false,
        };
        if now_zero {
            table.in_flight.remove(worker);
            // A draining worker with no in-flight left has finished its work —
            // mark it reapable so it's removed promptly rather than at the timeout.
            if self.registry.is_draining(worker) {
                self.registry.complete_drain(worker);
            }
        }

        let mut evictions = 0usize;
        for key in routing_keys {
            // For a flushed sub-batch, the key's flushed chunk has now landed —
            // clear one outstanding deferral before checking whether it can evict.
            if clears_deferral {
                table.stash.completed(key);
            }
            // Don't evict a pin while the key still has deferred groups awaiting
            // flush — new messages must keep deferring behind them to preserve
            // per-distinct_id order.
            let still_deferring = table.stash.is_deferring(key);
            if let Some(pin) = table.pins.get_mut(key) {
                // Skip stale resolves: a key's pin may have been re-pointed to a
                // different worker (e.g. by a deferred flush). A resolve from the
                // original sub-batch must not touch the new pin's ref_count.
                if pin.worker != *worker {
                    continue;
                }
                pin.ref_count = pin.ref_count.saturating_sub(1);
                if pin.ref_count == 0 && !still_deferring {
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
    pub fn record_send_outcome(&self, worker: &str, is_error: bool) {
        self.registry.record_outcome(worker, is_error);
    }
}

/// Add `count` to a worker's working load for this round, if it is a candidate.
/// Workers that aren't routing candidates (e.g. a pin honored on an unhealthy
/// worker) have no entry and don't affect selection, so they're skipped.
fn bump_load(working_load: &mut WorkerLoad, worker: &WorkerId, count: usize) {
    if let Some(load) = working_load.get_mut(worker) {
        *load = load.saturating_add(count);
    }
}

/// Publish point-in-time stash depth so a drain's backlog is observable and can
/// be alerted on if it fails to drain to zero. Call after every mutation.
fn record_stash_gauges(stash: &Stash) {
    gauge!("ingestion_consumer_dispatcher_stashed_batches").set(stash.batch_count() as f64);
    gauge!("ingestion_consumer_dispatcher_stashed_groups").set(stash.len() as f64);
    gauge!("ingestion_consumer_dispatcher_stashed_messages").set(stash.message_count() as f64);
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

    fn worker_url(i: usize) -> String {
        format!("http://worker:{}", 9001 + i)
    }

    fn wid(i: usize) -> WorkerId {
        WorkerId::from(worker_url(i).as_str())
    }

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

    fn make_msg_at(token: &str, distinct_id: &str, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            offset,
            ..make_msg(token, distinct_id)
        }
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
        let urls: Vec<String> = (0..n).map(worker_url).collect();
        let config = WorkerRegistryConfig {
            probe_interval: Duration::from_millis(50),
            dead_declaration: Duration::from_millis(30),
            passive_window: Duration::from_millis(500),
            passive_error_threshold: 0.5,
            passive_min_samples: 2,
            degraded_hold: Duration::from_millis(50),
            min_state_duration: Duration::ZERO,
            probe_failure_threshold: 2,
            drain_timeout: Duration::from_secs(5),
        };
        Arc::new(WorkerRegistry::new(&urls, config))
    }

    fn in_flight_of(dispatcher: &Dispatcher, worker: &WorkerId) -> usize {
        dispatcher
            .pin_table
            .lock()
            .unwrap()
            .in_flight
            .get(worker)
            .copied()
            .unwrap_or(0)
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
        let mut assignments = WorkerAssignments::new();

        assignments.add_group(
            wid(1),
            MessageGroup {
                routing_key: "tok:user-1".to_string(),
                messages: make_msgs(&[("tok", "user-1")]),
            },
        );
        assignments.add_group(
            wid(1),
            MessageGroup {
                routing_key: "tok:user-2".to_string(),
                messages: make_msgs(&[("tok", "user-2")]),
            },
        );

        assert_eq!(
            assignments.routed_counts().collect::<Vec<_>>(),
            vec![(wid(1), 2)]
        );

        let sub_batches = assignments.into_sub_batches();
        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker, wid(1));
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

        let sub_batches = dispatcher.assign("b", make_msgs(&[("t", "a"), ("t", "b"), ("t", "c")]));

        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker, wid(0));
        assert_eq!(sub_batches[0].messages.len(), 3);
    }

    #[test]
    fn test_empty_batch_returns_no_sub_batches() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);
        assert!(dispatcher.assign("b", vec![]).is_empty());
    }

    #[test]
    fn test_same_distinct_id_merges_within_batch() {
        let registry = healthy_registry(3);
        let dispatcher = Dispatcher::new(registry);

        let batch1 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        assert_eq!(batch1.len(), 1);
        let worker = batch1[0].worker.clone();
        dispatcher.on_sub_batch_resolved(
            &worker,
            batch1[0].messages.len(),
            &batch1[0].routing_keys,
            false,
        );

        // Both user-1 messages merge into one sub-batch.
        let batch2 = dispatcher.assign("b", make_msgs(&[("t", "user-1"), ("t", "user-1")]));
        assert_eq!(batch2.len(), 1);
    }

    // ---- sticky pins ----

    #[test]
    fn test_pin_is_sticky_across_batches() {
        let registry = healthy_registry(3);
        let dispatcher = Dispatcher::new(registry);

        // First batch pins "t:user-1" to some worker.
        let b1 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        let pinned_worker = b1[0].worker.clone();

        // Do NOT resolve b1 — pin stays alive with ref_count=1.

        // Second batch: same key must hit the same worker.
        let b2 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        assert_eq!(b2.len(), 1);
        assert_eq!(b2[0].worker, pinned_worker);
    }

    #[test]
    fn test_different_keys_may_go_to_different_workers() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // With 2 workers, bin-packing should spread 2 fresh keys across them.
        let sub_batches = dispatcher.assign("b", make_msgs(&[("t", "user-1"), ("t", "user-2")]));

        let total_msgs: usize = sub_batches.iter().map(|b| b.messages.len()).sum();
        assert_eq!(total_msgs, 2);
    }

    // ---- ref counting ----

    #[test]
    fn test_pin_evicted_when_ref_count_reaches_zero() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        let worker = b1[0].worker.clone();

        assert!(dispatcher
            .pin_table
            .lock()
            .unwrap()
            .pins
            .contains_key("t:user-1"));

        dispatcher.on_sub_batch_resolved(&worker, b1[0].messages.len(), &b1[0].routing_keys, false);

        assert!(!dispatcher
            .pin_table
            .lock()
            .unwrap()
            .pins
            .contains_key("t:user-1"));
    }

    #[test]
    fn test_pin_ref_count_accumulates_across_batches() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        let worker = b1[0].worker.clone();

        // Second batch, same key, pin not yet resolved: ref_count should be 2.
        dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        assert_eq!(
            dispatcher.pin_table.lock().unwrap().pins["t:user-1"].ref_count,
            2
        );

        // Resolve first sub-batch: ref_count drops to 1, pin stays.
        dispatcher.on_sub_batch_resolved(&worker, b1[0].messages.len(), &b1[0].routing_keys, false);
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
        let b1 = dispatcher.assign("b", make_msgs(&[("t", "user-1"), ("t", "user-1")]));
        let worker = b1[0].worker.clone();

        assert_eq!(in_flight_of(&dispatcher, &worker), 2);
    }

    #[test]
    fn test_in_flight_messages_decremented_on_resolve() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign("b", make_msgs(&[("t", "user-1"), ("t", "user-1")]));
        let worker = b1[0].worker.clone();

        dispatcher.on_sub_batch_resolved(&worker, b1[0].messages.len(), &b1[0].routing_keys, false);

        assert_eq!(in_flight_of(&dispatcher, &worker), 0);
    }

    #[test]
    fn test_in_flight_messages_counts_every_message_to_worker() {
        // Three distinct keys routed to the single worker merge into one
        // sub-batch, but in-flight load tracks the total message volume (3),
        // not the sub-batch count.
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(registry);

        dispatcher.assign("b", make_msgs(&[("t", "a"), ("t", "b"), ("t", "c")]));

        assert_eq!(in_flight_of(&dispatcher, &wid(0)), 3);
    }

    // ---- bin-packing ----

    #[test]
    fn test_bin_packing_targets_least_loaded_worker() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // Artificially load worker 0 with 3 outstanding messages.
        dispatcher
            .pin_table
            .lock()
            .unwrap()
            .in_flight
            .insert(wid(0), 3);

        // A fresh key should go to worker 1 (load = 0).
        let b = dispatcher.assign("b", make_msgs(&[("t", "fresh")]));
        assert_eq!(b.len(), 1);
        assert_eq!(b[0].worker, wid(1));
    }

    #[test]
    fn test_bin_packing_balances_by_message_volume_not_group_count() {
        // Regression: load is tracked by message count, not sub-batch presence.
        // One heavy key (10 msgs) plus five small keys (1 msg each) must not all
        // pile onto one worker — the small keys bin-pack onto the other worker
        // until load is balanced.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let mut specs: Vec<(&str, &str)> = vec![("t", "heavy"); 10];
        for d in ["a", "b", "c", "d", "e"] {
            specs.push(("t", d));
        }

        let sub_batches = dispatcher.assign("b", make_msgs(&specs));
        assert_eq!(sub_batches.len(), 2, "both workers must carry messages");

        let load0 = in_flight_of(&dispatcher, &wid(0));
        let load1 = in_flight_of(&dispatcher, &wid(1));
        assert_eq!(load0 + load1, 15);

        // The heavy key lands alone on one worker; the five singles fill the
        // other. With per-sub-batch accounting the singles would all dump onto
        // one worker, giving 15 vs 1.
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
        let b1 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        let original_worker = b1[0].worker.clone();
        let other_worker = if original_worker == wid(0) {
            wid(1)
        } else {
            wid(0)
        };

        // Drive the pinned worker to dead via passive signal.
        for _ in 0..5 {
            registry.record_outcome(&original_worker, true);
        }
        tokio::time::sleep(Duration::from_millis(40)).await;
        assert!(registry.is_dead(&original_worker));

        // Resolve b1 so the dead worker has no in-flight (the max_in_flight=1
        // ordering: the previous batch completes before the next assigns). The
        // zero-ref pin is evicted, so the key re-routes to the live worker.
        dispatcher.on_sub_batch_resolved(
            &original_worker,
            b1[0].messages.len(),
            &b1[0].routing_keys,
            false,
        );

        let b2 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        assert_eq!(b2.len(), 1);
        assert_eq!(b2[0].worker, other_worker);
    }

    #[test]
    fn test_all_workers_dead_returns_empty() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Force both workers to Unhealthy via passive signal (min_state_duration=0).
        for i in 0..2 {
            for _ in 0..5 {
                registry.record_outcome(&worker_url(i), true);
            }
        }

        // Both workers are Unhealthy — the dispatcher should not route to them.
        let b = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        assert!(b.is_empty());
    }

    // ---- P2C routing strategy ----

    fn p2c_dispatcher(n: usize, seed: u64) -> Dispatcher {
        Dispatcher::with_strategy_seeded(healthy_registry(n), RoutingStrategy::P2c, seed)
    }

    #[test]
    fn test_p2c_single_worker_all_messages_go_there() {
        let dispatcher = p2c_dispatcher(1, 1);

        let sub_batches = dispatcher.assign("b", make_msgs(&[("t", "a"), ("t", "b"), ("t", "c")]));

        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker, wid(0));
        assert_eq!(sub_batches[0].messages.len(), 3);
    }

    #[test]
    fn test_p2c_pin_is_sticky_across_batches() {
        let dispatcher = p2c_dispatcher(3, 7);

        // First batch pins "t:user-1"; do NOT resolve so the pin stays alive.
        let b1 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        let pinned_worker = b1[0].worker.clone();

        // Second batch with the same key must hit the same worker, bypassing P2C.
        let b2 = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        assert_eq!(b2.len(), 1);
        assert_eq!(b2[0].worker, pinned_worker);
    }

    #[test]
    fn test_p2c_spreads_fresh_keys_across_two_workers() {
        // With two workers, P2C samples both and the load bump after the first
        // key steers the second to the other worker — one message each.
        let dispatcher = p2c_dispatcher(2, 3);

        let sub_batches = dispatcher.assign("b", make_msgs(&[("t", "user-1"), ("t", "user-2")]));

        assert_eq!(sub_batches.len(), 2, "both workers must carry a message");
        let total: usize = sub_batches.iter().map(|b| b.messages.len()).sum();
        assert_eq!(total, 2);
    }

    #[test]
    fn test_p2c_prefers_least_loaded_of_two_workers() {
        // With two workers P2C always compares both, so a pre-loaded worker 0
        // sends the fresh key to worker 1.
        let dispatcher = p2c_dispatcher(2, 9);
        dispatcher
            .pin_table
            .lock()
            .unwrap()
            .in_flight
            .insert(wid(0), 5);

        let b = dispatcher.assign("b", make_msgs(&[("t", "fresh")]));
        assert_eq!(b.len(), 1);
        assert_eq!(b[0].worker, wid(1));
    }

    #[tokio::test]
    async fn test_p2c_all_workers_dead_returns_empty() {
        let registry = healthy_registry(2);
        let dispatcher =
            Dispatcher::with_strategy_seeded(Arc::clone(&registry), RoutingStrategy::P2c, 1);

        for i in 0..2 {
            for _ in 0..5 {
                registry.record_outcome(&worker_url(i), true);
            }
        }

        let b = dispatcher.assign("b", make_msgs(&[("t", "user-1")]));
        assert!(b.is_empty());
    }

    // ---- graceful drain ----

    #[test]
    fn test_draining_worker_gets_no_new_keys() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));
        registry.start_draining(&worker_url(0));

        let msgs: Vec<_> = (0..10).map(|i| make_msg("t", &format!("u{i}"))).collect();
        let sub_batches = dispatcher.assign("b", msgs);

        assert!(
            sub_batches.iter().all(|b| b.worker != wid(0)),
            "no new keys may route to a draining worker"
        );
    }

    #[test]
    fn test_unroutable_fresh_key_defers_until_a_worker_returns() {
        // A fresh (unpinned) key arriving while NO worker is routable — e.g.
        // the whole pool is draining during a deploy overlap — must be deferred
        // like pinned keys are, not silently dropped. A drop fails the batch and
        // restarts the process even though a worker may return moments later.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        registry.start_draining(&worker_url(0));
        registry.start_draining(&worker_url(1));

        let b = dispatcher.assign("batch-1", make_msgs(&[("t", "fresh")]));
        assert!(b.is_empty(), "nothing is routable while the pool drains");
        assert!(
            dispatcher.has_deferred("batch-1"),
            "an unroutable fresh key must be deferred, not dropped"
        );

        // A worker rejoins — the deferred group flushes to it, nothing was lost.
        registry.add_worker(wid(0));
        let flushed = dispatcher.flush_deferred("batch-1");
        assert_eq!(flushed.len(), 1);
        assert_eq!(flushed[0].worker, wid(0));
        assert_eq!(flushed[0].messages.len(), 1);
        assert!(!dispatcher.has_deferred("batch-1"));
    }

    #[test]
    fn test_fresh_key_queues_behind_its_own_deferred_groups() {
        // batch-1 defers a fresh key because nothing was routable; a worker
        // then returns BEFORE batch-1 is flushed. batch-2's messages for the
        // key have no pin to defer behind — they must still queue behind the
        // stashed batch-1 group instead of routing ahead of it.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));
        registry.start_draining(&worker_url(0));
        registry.start_draining(&worker_url(1));

        assert!(dispatcher
            .assign("batch-1", make_msgs(&[("t", "k")]))
            .is_empty());
        assert!(dispatcher.has_deferred("batch-1"));

        registry.add_worker(wid(0));

        let b2 = dispatcher.assign("batch-2", make_msgs(&[("t", "k")]));
        assert!(
            b2.is_empty(),
            "newer messages must not race ahead of the key's stashed ones"
        );
        assert!(dispatcher.has_deferred("batch-2"));

        // Flush oldest-first: each batch delivers its own group, and batch-2
        // stays sticky to the pin batch-1's flush created.
        let f1 = dispatcher.flush_deferred("batch-1");
        assert_eq!(f1.len(), 1);
        dispatcher.on_sub_batch_resolved(
            &f1[0].worker,
            f1[0].messages.len(),
            &f1[0].routing_keys,
            true,
        );
        let f2 = dispatcher.flush_deferred("batch-2");
        assert_eq!(f2.len(), 1);
        assert_eq!(f2[0].worker, f1[0].worker);
    }

    #[test]
    fn test_pinned_key_defers_off_draining_worker() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Pin "user-1"; do NOT resolve, so the pin stays live on its worker.
        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let pinned = b1[0].worker.clone();

        registry.start_draining(&pinned);

        // The live pin points at a draining worker — new messages for the key are
        // deferred (held), not sent and not rerouted, so they can't pass the
        // earlier in-flight message still being processed on that worker.
        let b2 = dispatcher.assign("batch-2", make_msgs(&[("t", "user-1")]));
        assert!(
            b2.is_empty(),
            "messages for a draining-pinned key must be deferred, not routed"
        );
        assert!(dispatcher.has_deferred("batch-2"));
    }

    #[tokio::test]
    async fn test_pinned_key_defers_off_dead_worker() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let pinned = b1[0].worker.clone();

        // Kill the pinned worker via passive signal, leaving b1 in-flight.
        for _ in 0..5 {
            registry.record_outcome(&pinned, true);
        }
        tokio::time::sleep(Duration::from_millis(40)).await;
        assert!(registry.is_dead(&pinned));

        let b2 = dispatcher.assign("batch-2", make_msgs(&[("t", "user-1")]));
        assert!(
            b2.is_empty(),
            "messages for a dead-pinned key with in-flight must be deferred"
        );
        assert!(dispatcher.has_deferred("batch-2"));
    }

    #[test]
    fn test_flush_deferred_routes_to_healthy_worker_and_repins() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Pin user-1, then drain its worker so the next batch defers.
        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let pinned = b1[0].worker.clone();
        registry.start_draining(&pinned);
        let b2 = dispatcher.assign("batch-2", make_msgs(&[("t", "user-1")]));
        assert!(b2.is_empty());

        // Resolve batch-1's in-flight so the worker finishes draining.
        dispatcher.on_sub_batch_resolved(&pinned, b1[0].messages.len(), &b1[0].routing_keys, false);

        // Flushing batch-2 re-routes the deferred group onto the surviving worker.
        let flushed = dispatcher.flush_deferred("batch-2");
        assert_eq!(flushed.len(), 1);
        assert_ne!(
            flushed[0].worker, pinned,
            "deferred group routes off drainer"
        );
        assert_eq!(flushed[0].routing_keys, vec!["t:user-1".to_string()]);
        assert!(
            !dispatcher.has_deferred("batch-2"),
            "nothing left after flush"
        );
    }

    #[test]
    fn test_defer_keeps_pin_alive_until_flushed() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let pinned = b1[0].worker.clone();
        registry.start_draining(&pinned);
        dispatcher.assign("batch-2", make_msgs(&[("t", "user-1")]));

        // Resolving batch-1 drops ref_count to 0, but the deferred batch-2 group
        // must keep the pin from being evicted (so order is preserved on flush).
        dispatcher.on_sub_batch_resolved(&pinned, b1[0].messages.len(), &b1[0].routing_keys, false);
        assert_eq!(
            dispatcher.pin_count(),
            1,
            "pin retained while deferred pending"
        );

        // After flushing, the pin is repointed and stays (now ref-counted by the
        // flushed sub-batch), but nothing is deferred anymore.
        dispatcher.flush_deferred("batch-2");
        assert!(!dispatcher.has_deferred("batch-2"));
    }

    #[test]
    fn test_defer_failed_holds_messages_for_replay() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let worker = b1[0].worker.clone();

        // Simulate a send failure: defer the failed messages, then resolve.
        dispatcher.defer_failed("batch-1", make_msgs(&[("t", "user-1")]));
        dispatcher.on_sub_batch_resolved(&worker, b1[0].messages.len(), &b1[0].routing_keys, false);

        assert!(
            dispatcher.has_deferred("batch-1"),
            "failed messages held for replay"
        );
        assert_eq!(
            dispatcher.pin_count(),
            1,
            "pin kept for the deferred replay"
        );

        let flushed = dispatcher.flush_deferred("batch-1");
        assert_eq!(flushed.len(), 1);
        assert!(!dispatcher.has_deferred("batch-1"));
    }

    #[test]
    fn test_rejoin_during_drain_keeps_deferring_until_flushed() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Pin user-1, keep it in-flight, then drain its worker.
        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let pinned = b1[0].worker.clone();
        registry.start_draining(&pinned);

        // batch-2 defers behind the draining pin.
        let b2 = dispatcher.assign("batch-2", make_msgs(&[("t", "user-1")]));
        assert!(b2.is_empty());
        assert!(dispatcher.has_deferred("batch-2"));

        // The worker rejoins (EndpointSlice re-adds it) — draining is cleared.
        registry.add_worker(pinned.clone());
        assert!(!registry.is_draining(&pinned));

        // Even so, new messages must keep deferring: the key still has deferred
        // groups outstanding, so honoring the (now-healthy-again) pin would let
        // newer messages jump ahead of the older deferred ones.
        let b3 = dispatcher.assign("batch-3", make_msgs(&[("t", "user-1")]));
        assert!(
            b3.is_empty(),
            "must keep deferring while earlier deferred work is unflushed"
        );
        assert!(dispatcher.has_deferred("batch-3"));

        // Resolve batch-1's in-flight, then flush the deferred batches in order
        // and resolve the flushed sub-batches (which clears the deferral).
        dispatcher.on_sub_batch_resolved(&pinned, b1[0].messages.len(), &b1[0].routing_keys, false);
        for batch in ["batch-2", "batch-3"] {
            let flushed = dispatcher.flush_deferred(batch);
            assert_eq!(flushed.len(), 1);
            dispatcher.on_sub_batch_resolved(
                &flushed[0].worker,
                flushed[0].messages.len(),
                &flushed[0].routing_keys,
                true,
            );
        }
        assert!(!dispatcher.has_deferred("batch-2") && !dispatcher.has_deferred("batch-3"));

        // With the stash drained, a fresh batch honors the pin again.
        let b4 = dispatcher.assign("batch-4", make_msgs(&[("t", "user-1")]));
        assert_eq!(b4.len(), 1, "honors the pin once nothing is deferred");
    }

    #[test]
    fn test_flushed_key_keeps_deferring_until_acked() {
        // The ordering-critical case: after a key is flushed to a survivor, its
        // messages are in flight but not yet ACKed. A newer batch for the same key
        // must keep deferring until that flush lands — otherwise it could be
        // routed onto the fresh pin and race the not-yet-acked flushed messages.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let pinned = b1[0].worker.clone();
        registry.start_draining(&pinned);

        // batch-2 defers; batch-1 resolves; flush batch-2 to the survivor.
        assert!(dispatcher
            .assign("batch-2", make_msgs(&[("t", "user-1")]))
            .is_empty());
        dispatcher.on_sub_batch_resolved(&pinned, b1[0].messages.len(), &b1[0].routing_keys, false);
        let flushed = dispatcher.flush_deferred("batch-2");
        assert_eq!(flushed.len(), 1);

        // Flushed but NOT yet resolved → a newer batch must still defer.
        let b3 = dispatcher.assign("batch-3", make_msgs(&[("t", "user-1")]));
        assert!(
            b3.is_empty(),
            "newer messages must not race the in-flight flushed messages"
        );

        // Once the flush ACKs (clears_deferral), the key is free to be honored.
        dispatcher.on_sub_batch_resolved(
            &flushed[0].worker,
            flushed[0].messages.len(),
            &flushed[0].routing_keys,
            true,
        );
        // batch-3's deferred group is the only thing left; flush it to confirm the
        // key drains fully and a fresh assign then honors the pin.
        let f3 = dispatcher.flush_deferred("batch-3");
        assert_eq!(f3.len(), 1);
        dispatcher.on_sub_batch_resolved(
            &f3[0].worker,
            f3[0].messages.len(),
            &f3[0].routing_keys,
            true,
        );
        let b4 = dispatcher.assign("batch-4", make_msgs(&[("t", "user-1")]));
        assert_eq!(
            b4.len(),
            1,
            "honors the pin once all flushed work has landed"
        );
    }

    #[test]
    fn test_cross_batch_deferred_flush_preserves_order() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // batch-1 pins user-1 (offset 0); keep it in-flight, then drain its worker.
        let b1 = dispatcher.assign("batch-1", vec![make_msg_at("t", "user-1", 0)]);
        let pinned = b1[0].worker.clone();
        registry.start_draining(&pinned);

        // The next two batches each carry user-1's next message — both defer,
        // each held under its own batch, behind the draining pin.
        let b2 = dispatcher.assign("batch-2", vec![make_msg_at("t", "user-1", 1)]);
        let b3 = dispatcher.assign("batch-3", vec![make_msg_at("t", "user-1", 2)]);
        assert!(
            b2.is_empty() && b3.is_empty(),
            "both must defer behind the drainer"
        );

        // Drain finishes when batch-1's in-flight resolves.
        dispatcher.on_sub_batch_resolved(&pinned, b1[0].messages.len(), &b1[0].routing_keys, false);

        // Flush oldest-first (as complete_oldest_batch does): each batch yields
        // only its own message, in Kafka offset order.
        let f2 = dispatcher.flush_deferred("batch-2");
        let f3 = dispatcher.flush_deferred("batch-3");
        assert_eq!(offsets(&f2), vec![1], "batch-2 flushes its own message");
        assert_eq!(offsets(&f3), vec![2], "batch-3 flushes its own message");
        assert!(!dispatcher.has_deferred("batch-2") && !dispatcher.has_deferred("batch-3"));
    }

    #[test]
    fn test_cross_batch_deferred_flush_stays_on_one_survivor() {
        // A key deferred across multiple batches during a drain must re-home to a
        // SINGLE survivor — otherwise one distinct_id's events scatter across
        // workers and lose person-batching locality. Needs >=2 survivors after a
        // drain, so 3 workers. (With 2 workers there's one survivor and the bug is
        // masked, which is why `..._preserves_order` above can't catch it.)
        let registry = healthy_registry(3);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Pin user-1, keep it in-flight, then drain its worker.
        let b1 = dispatcher.assign("batch-1", make_msgs(&[("t", "user-1")]));
        let pinned = b1[0].worker.clone();
        registry.start_draining(&pinned);

        // Two later batches each carry user-1 → both defer behind the drainer.
        assert!(dispatcher
            .assign("batch-2", make_msgs(&[("t", "user-1")]))
            .is_empty());
        assert!(dispatcher
            .assign("batch-3", make_msgs(&[("t", "user-1")]))
            .is_empty());

        // Drain completes when batch-1's in-flight resolves.
        dispatcher.on_sub_batch_resolved(&pinned, b1[0].messages.len(), &b1[0].routing_keys, false);

        // Flush oldest-first. batch-2 re-homes user-1 onto a survivor; batch-3 must
        // land on the SAME survivor. Without the fix, batch-2's flush bumps that
        // survivor's load, so batch-3's least-loaded pick scatters to the other one.
        let f2 = dispatcher.flush_deferred("batch-2");
        let f3 = dispatcher.flush_deferred("batch-3");
        assert_eq!(f2.len(), 1);
        assert_eq!(f3.len(), 1);
        assert_ne!(f2[0].worker, pinned, "re-homes off the drainer");
        assert_eq!(
            f3[0].worker, f2[0].worker,
            "a key deferred across batches must re-home to one survivor, not scatter"
        );
    }

    fn offsets(sub_batches: &[SubBatch]) -> Vec<i64> {
        sub_batches
            .iter()
            .flat_map(|b| b.messages.iter().map(|m| m.offset))
            .collect()
    }

    #[test]
    fn test_resolve_completes_drain_when_in_flight_hits_zero() {
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Send a batch to worker 0, then mark it draining while in-flight.
        let b = dispatcher.assign("b", make_msgs(&[("t", "a")]));
        let worker = b[0].worker.clone();
        registry.start_draining(&worker);
        assert!(
            registry.reapable_workers().is_empty(),
            "not reapable while in-flight remains"
        );

        // Resolving the last in-flight sub-batch should mark it reapable.
        dispatcher.on_sub_batch_resolved(&worker, b[0].messages.len(), &b[0].routing_keys, false);
        assert_eq!(registry.reapable_workers(), vec![worker]);
    }

    #[test]
    fn test_idle_drained_worker_reaped_via_reaper_path() {
        // A worker drained while idle has no in-flight to resolve, so
        // `on_sub_batch_resolved`/`complete_drain` never fire for it. The reaper
        // instead completes the drain when `has_in_flight` is false. This checks
        // the accessors that path relies on.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let idle = wid(0);
        registry.start_draining(&idle);

        // Reaper's condition holds: the worker is draining and has no in-flight.
        assert!(registry.draining_workers().contains(&idle));
        assert!(
            !dispatcher.has_in_flight(&idle),
            "idle worker has no in-flight"
        );
        assert!(
            registry.reapable_workers().is_empty(),
            "not reapable yet — its deadline is the full drain timeout"
        );

        // The reaper completes the drain → immediately reapable, no timeout wait.
        registry.complete_drain(&idle);
        assert_eq!(registry.reapable_workers(), vec![idle]);
    }
}
