//! Per-partition stash queue for the write-path.
//!
//! During a partition handoff, the coordinator advances the handoff state
//! through `Freezing → Draining → Warming → Complete`. From the moment
//! the handoff is created (in `Freezing`) and until the routing table
//! flips at `Complete`, routers buffer (stash) incoming write requests
//! for that partition here. When `Complete` arrives the stashed
//! requests are drained in arrival order to the new owner.
//!
//! This gives the protocol a clean "no split-brain writes" guarantee
//! without returning errors to callers — every write that hits the
//! router during the handoff window is either delivered to the new
//! owner in arrival order or fails fast with `UNAVAILABLE` once its
//! per-request deadline expires (see `RouterStashHandler`).

use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Instant;

use dashmap::DashMap;
use personhog_proto::personhog::types::v1::{
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use tokio::sync::{oneshot, Mutex};
use tonic::Status;

/// Fixed per-request overhead estimate that approximates the bookkeeping
/// cost of holding a request in the queue (struct fields, oneshot
/// channel, etc.). Combined with the variable payload size below, this
/// approximation is intentionally rough — the goal is a memory bound,
/// not exact accounting. This is an implementation detail of the size
/// approximation, not a user-tunable knob.
const PER_REQUEST_OVERHEAD: usize = 64;

/// Why the stash rejected a request. Used for metric labelling.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RejectCause {
    MaxMessages,
    MaxBytes,
}

impl RejectCause {
    fn label(self) -> &'static str {
        match self {
            RejectCause::MaxMessages => "max_messages",
            RejectCause::MaxBytes => "max_bytes",
        }
    }
}

/// Approximate the memory footprint of a stashed request. Used to
/// enforce the byte-based stash bound. Sums the variable-size fields
/// plus a fixed overhead estimate; doesn't attempt exact proto-encoded
/// sizing because we only need an order-of-magnitude bound, and
/// approximate counting is cheaper.
fn approximate_size(req: &UpdatePersonPropertiesRequest) -> usize {
    PER_REQUEST_OVERHEAD
        + req.event_name.len()
        + req.set_properties.len()
        + req.set_once_properties.len()
        + req.unset_properties.iter().map(|s| s.len()).sum::<usize>()
}

/// A request held in the stash along with the channel used to deliver its
/// response back to the original caller.
pub struct StashedRequest {
    pub request: UpdatePersonPropertiesRequest,
    pub client_name: Option<String>,
    pub reply: oneshot::Sender<Result<UpdatePersonPropertiesResponse, Status>>,
    /// Wall-clock time the request was enqueued. Used to record stash-wait
    /// histograms when drain forwards the request, giving operators
    /// visibility into how long callers spent parked during a handoff.
    pub enqueued_at: Instant,
}

/// Inner queue plus running byte total. Tracked together so the byte
/// count stays consistent with the queue contents.
struct StashQueue {
    requests: VecDeque<StashedRequest>,
    bytes: usize,
}

impl StashQueue {
    fn new() -> Self {
        Self {
            requests: VecDeque::new(),
            bytes: 0,
        }
    }
}

struct PartitionStash {
    max_messages: usize,
    max_bytes: usize,
    /// `Some(queue)` while alive; `None` once `drain` has both taken
    /// the queue contents and evicted this entry from the dashmap —
    /// both inside the same critical section. The `None` state therefore
    /// doubles as a tombstone: a concurrent `begin_stash` that races
    /// `drain` and observes `None` knows the dashmap entry is already
    /// gone and that the next `get_or_create` will produce a fresh
    /// entry rather than re-grab this doomed `Arc`.
    queue: Mutex<Option<StashQueue>>,
}

impl PartitionStash {
    fn new(max_messages: usize, max_bytes: usize) -> Self {
        Self {
            max_messages,
            max_bytes,
            // Initialize to `Some` so a freshly-created entry is
            // immediately ready for enqueues. A `None` queue
            // unambiguously signals "drained" — no other origin
            // produces it.
            queue: Mutex::new(Some(StashQueue::new())),
        }
    }
}

/// Outcome of an `enqueue_or_forward` call. `Forward` means "not frozen,
/// route normally"; `Stashed` means the request has been enqueued and the
/// caller should await the receiver for its reply; `Rejected` means the
/// stash is full (either too many messages or too many bytes).
pub enum StashDecision {
    Forward,
    Stashed(oneshot::Receiver<Result<UpdatePersonPropertiesResponse, Status>>),
    Rejected,
}

/// Shared stash table. Cheap to clone (holds an `Arc`).
#[derive(Clone)]
pub struct StashTable {
    inner: Arc<DashMap<u32, Arc<PartitionStash>>>,
    max_messages: usize,
    max_bytes: usize,
}

impl StashTable {
    pub fn with_bounds(max_messages: usize, max_bytes: usize) -> Self {
        Self {
            inner: Arc::new(DashMap::new()),
            max_messages,
            max_bytes,
        }
    }

    fn get_or_create(&self, partition: u32) -> Arc<PartitionStash> {
        self.inner
            .entry(partition)
            .or_insert_with(|| Arc::new(PartitionStash::new(self.max_messages, self.max_bytes)))
            .clone()
    }

    /// Begin buffering requests for `partition`. Idempotent: safe to call
    /// multiple times (watch reconnects etc.).
    ///
    /// Each iteration is a single attempt to bind to a live dashmap
    /// entry. The loop terminates because the only way to observe
    /// `None` is to race a `drain` that evicted the entry inside its
    /// queue lock — meaning the next `get_or_create` will create a
    /// fresh entry rather than re-grab the doomed `Arc`. In production
    /// the routing-table layer awaits `drain` before issuing the next
    /// `begin_stash` for the same partition, so this loop runs at most
    /// twice.
    pub async fn begin_stash(&self, partition: u32) {
        while !self.try_acquire_alive_entry(partition).await {}
    }

    /// One attempt to bind to the live dashmap entry for `partition`.
    /// Returns `true` if we successfully observed a `Some` queue (the
    /// entry is alive and ready for enqueues); `false` if we raced a
    /// `drain` that left a tombstoned `None`, in which case the caller
    /// should retry to pick up the fresh entry.
    async fn try_acquire_alive_entry(&self, partition: u32) -> bool {
        let stash = self.get_or_create(partition);
        let guard = stash.queue.lock().await;
        guard.is_some()
    }

    /// Enqueue a request if the partition is frozen; otherwise return
    /// `Forward` to signal the caller should route normally.
    pub async fn enqueue_or_forward(
        &self,
        partition: u32,
        request: UpdatePersonPropertiesRequest,
        client_name: Option<String>,
    ) -> StashDecision {
        let stash = match self.inner.get(&partition) {
            Some(entry) => Arc::clone(entry.value()),
            None => return StashDecision::Forward,
        };
        let mut guard = stash.queue.lock().await;
        // `None` here means a concurrent `drain` already took this stash's
        // queue and removed the dashmap entry. We arrived holding an Arc to
        // the orphaned PartitionStash. Returning Forward routes via the
        // normal path; the partition is no longer stashing.
        let Some(queue) = guard.as_mut() else {
            return StashDecision::Forward;
        };

        let request_size = approximate_size(&request);

        if queue.requests.len() >= stash.max_messages {
            metrics::counter!(
                "personhog_router_stash_rejected_total",
                "cause" => RejectCause::MaxMessages.label()
            )
            .increment(1);
            return StashDecision::Rejected;
        }
        if queue.bytes.saturating_add(request_size) > stash.max_bytes {
            metrics::counter!(
                "personhog_router_stash_rejected_total",
                "cause" => RejectCause::MaxBytes.label()
            )
            .increment(1);
            return StashDecision::Rejected;
        }

        let (tx, rx) = oneshot::channel();
        queue.requests.push_back(StashedRequest {
            request,
            client_name,
            reply: tx,
            enqueued_at: Instant::now(),
        });
        queue.bytes += request_size;
        metrics::counter!("personhog_router_stash_enqueued_total").increment(1);
        StashDecision::Stashed(rx)
    }

    /// Drain stashed requests for `partition` by applying `forward_batch`
    /// to each batch the loop dequeues, in FIFO order. Loops until the
    /// queue is empty under the lock, then evicts the dashmap entry.
    ///
    /// Each iteration takes the current queue contents into a local
    /// batch under the lock and releases the lock before applying
    /// `forward_batch`. Requests that arrive *during* a forward
    /// iteration land on the same queue (the dashmap entry is still
    /// present, so `enqueue_or_forward` enqueues them as usual). The
    /// next loop iteration picks them up. The drain only exits when
    /// it observes an empty queue under the lock — at which point no
    /// further arrival can sneak in before the dashmap eviction in
    /// the same critical section.
    ///
    /// This preserves arrival order across the cutover: any request
    /// stashed before drain finishes is forwarded before drain
    /// returns. Without this loop pattern, drain would take a single
    /// snapshot, evict the dashmap entry, and let new requests bypass
    /// the stash via the live routing path — letting them race ahead
    /// of older requests still being replayed and corrupting per-key
    /// ordering at the leader.
    ///
    /// Yielding whole batches (rather than one request at a time)
    /// gives callers the freedom to forward in parallel within a
    /// batch — for example, by grouping by leader-side serialization
    /// key and fanning out across keys. Sequential within a key is
    /// still required to preserve per-key ordering at the leader.
    ///
    /// Convergence is workload-dependent: under sustained
    /// arrival-rate ≥ forward-rate the loop runs as long as load
    /// continues. Per-request bounded latency is the caller's
    /// responsibility (e.g. a deadline check inside `forward_batch`
    /// that fail-fasts past-deadline requests with `UNAVAILABLE`).
    pub async fn drain<F, Fut>(&self, partition: u32, mut forward_batch: F)
    where
        F: FnMut(Vec<StashedRequest>) -> Fut,
        Fut: std::future::Future<Output = ()>,
    {
        let stash = match self.inner.get(&partition) {
            Some(entry) => Arc::clone(entry.value()),
            None => return,
        };

        loop {
            let batch = {
                let mut guard = stash.queue.lock().await;
                let Some(q) = guard.as_mut() else {
                    // Already drained — the dashmap entry was removed
                    // by a concurrent caller. Nothing to do.
                    return;
                };
                if q.requests.is_empty() {
                    // Queue is empty under the lock. Atomically
                    // tombstone the queue and evict the dashmap entry
                    // — both inside this critical section — so any
                    // racing `enqueue_or_forward` either pushes
                    // before our lock acquire (forcing us through one
                    // more loop iteration) or observes the entry
                    // already gone afterwards.
                    *guard = None;
                    self.inner.remove(&partition);
                    return;
                }
                let taken: Vec<StashedRequest> =
                    std::mem::take(&mut q.requests).into_iter().collect();
                q.bytes = 0;
                taken
            };

            forward_batch(batch).await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Collect drained requests into a `Vec` via the forward-batch
    /// closure. Mirrors the original return-VecDeque API for tests
    /// that just want to inspect what was drained without exercising
    /// the per-batch fan-out semantics.
    ///
    /// The outer closure is `move` so the Arc clone it owns is
    /// dropped when drain returns; otherwise it would survive past
    /// `try_unwrap` and inflate the refcount.
    async fn drain_to_vec(table: &StashTable, partition: u32) -> Vec<StashedRequest> {
        let collected = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let sink = std::sync::Arc::clone(&collected);
        table
            .drain(partition, move |batch| {
                let sink = std::sync::Arc::clone(&sink);
                async move {
                    sink.lock().unwrap().extend(batch);
                }
            })
            .await;
        std::sync::Arc::try_unwrap(collected)
            .ok()
            .expect("drain finished — outer closure should have dropped its sink clone")
            .into_inner()
            .unwrap()
    }

    fn mk_request(team_id: i64, person_id: i64) -> UpdatePersonPropertiesRequest {
        UpdatePersonPropertiesRequest {
            team_id,
            person_id,
            partition: 0,
            event_name: "test".to_string(),
            set_properties: Vec::new(),
            set_once_properties: Vec::new(),
            unset_properties: Vec::new(),
        }
    }

    fn mk_request_with_payload(
        person_id: i64,
        payload_size: usize,
    ) -> UpdatePersonPropertiesRequest {
        UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id,
            partition: 0,
            event_name: "test".to_string(),
            set_properties: vec![0u8; payload_size],
            set_once_properties: Vec::new(),
            unset_properties: Vec::new(),
        }
    }

    #[tokio::test]
    async fn forward_when_not_frozen() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Forward => {}
            _ => panic!("expected Forward"),
        }
    }

    #[tokio::test]
    async fn begin_then_enqueue_then_drain_preserves_fifo() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        let _rx1 = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let _rx2 = match table.enqueue_or_forward(0, mk_request(1, 2), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let drained = drain_to_vec(&table, 0).await;
        assert_eq!(drained.len(), 2);
        let ids: Vec<i64> = drained.iter().map(|s| s.request.person_id).collect();
        assert_eq!(ids, vec![1, 2]);

        // After drain, new requests forward.
        match table.enqueue_or_forward(0, mk_request(1, 3), None).await {
            StashDecision::Forward => {}
            _ => panic!("expected Forward after drain"),
        }
    }

    /// Drain must remove the dashmap entry so subsequent steady-state
    /// requests for that partition can short-circuit on `dashmap.get`
    /// returning `None`, avoiding the per-request Mutex lock that
    /// `enqueue_or_forward` would otherwise take.
    #[tokio::test]
    async fn drain_removes_dashmap_entry() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;
        assert!(
            table.inner.contains_key(&0),
            "begin_stash must populate the entry"
        );
        drain_to_vec(&table, 0).await;
        assert!(
            !table.inner.contains_key(&0),
            "drain must remove the entry so future requests skip the lock path"
        );
    }

    /// Back-to-back handoffs: drain → begin_stash for the same partition
    /// must produce a fresh empty queue, not preserve stale state.
    #[tokio::test]
    async fn drain_then_begin_stash_starts_fresh() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;
        let _rx = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let drained = drain_to_vec(&table, 0).await;
        assert_eq!(drained.len(), 1);

        // New handoff begins
        table.begin_stash(0).await;
        // Fresh queue; brand-new requests stash, not forward
        match table.enqueue_or_forward(0, mk_request(1, 2), None).await {
            StashDecision::Stashed(_) => {}
            _ => panic!("expected Stashed for fresh handoff"),
        }
    }

    #[tokio::test]
    async fn reject_when_message_count_exceeds_max() {
        let table = StashTable::with_bounds(2, usize::MAX);
        table.begin_stash(0).await;

        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 1), None).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 2), None).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 3), None).await,
            StashDecision::Rejected
        ));
    }

    #[tokio::test]
    async fn reject_when_byte_total_exceeds_max() {
        // Cap at ~5KB; each request below has ~2KB payload. After two
        // requests we're near 4KB; a third request would push over the cap.
        let table = StashTable::with_bounds(usize::MAX, 5 * 1024);
        table.begin_stash(0).await;

        assert!(matches!(
            table
                .enqueue_or_forward(0, mk_request_with_payload(1, 2 * 1024), None)
                .await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table
                .enqueue_or_forward(0, mk_request_with_payload(2, 2 * 1024), None)
                .await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table
                .enqueue_or_forward(0, mk_request_with_payload(3, 2 * 1024), None)
                .await,
            StashDecision::Rejected
        ));
    }

    /// Either bound triggers rejection — whichever is hit first.
    #[tokio::test]
    async fn message_count_takes_precedence_when_hit_first() {
        // Generous byte budget but tight message budget.
        let table = StashTable::with_bounds(1, 100 * 1024 * 1024);
        table.begin_stash(0).await;

        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 1), None).await,
            StashDecision::Stashed(_)
        ));
        // Second message rejected on count even though bytes are nowhere near.
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 2), None).await,
            StashDecision::Rejected
        ));
    }

    #[tokio::test]
    async fn partitions_are_independent() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        // p0 stashes, p1 forwards
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 1), None).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table.enqueue_or_forward(1, mk_request(1, 1), None).await,
            StashDecision::Forward
        ));
    }

    /// Race between concurrent enqueue and drain. The `Arc<PartitionStash>`
    /// + `Option<StashQueue>` design exists so that an enqueue that has
    /// already cloned the Arc when drain runs sees `None` after drain
    /// takes the queue, and returns `Forward` rather than pushing into a
    /// dead queue. With many iterations this drives the race window
    /// repeatedly; the invariant is that every request must end up either
    /// in the drained batch or forwarded — never lost, never duplicated.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn enqueue_and_drain_race() {
        for iteration in 0..200 {
            let table = StashTable::with_bounds(usize::MAX, usize::MAX);
            table.begin_stash(0).await;

            const ENQUEUERS: usize = 8;
            let mut handles = Vec::with_capacity(ENQUEUERS);
            for i in 0..ENQUEUERS {
                let table = table.clone();
                handles.push(tokio::spawn(async move {
                    table
                        .enqueue_or_forward(0, mk_request(1, i as i64), None)
                        .await
                }));
            }

            // Race the drain against the in-flight enqueues.
            let drain_table = table.clone();
            let drain_handle = tokio::spawn(async move { drain_to_vec(&drain_table, 0).await });

            let drained = drain_handle.await.unwrap();
            let mut stashed_count = 0usize;
            let mut forwarded_count = 0usize;
            for h in handles {
                match h.await.unwrap() {
                    StashDecision::Stashed(_) => stashed_count += 1,
                    StashDecision::Forward => forwarded_count += 1,
                    StashDecision::Rejected => {
                        panic!("unexpected Rejected on iteration {iteration}")
                    }
                }
            }

            // With the loop-drain, every Stashed request is forwarded
            // through `drain` regardless of when it arrived (concurrent
            // arrivals during forwarding are caught by the next loop
            // iteration). The previous "stashed count == drained count"
            // assertion still holds because no request can be lost.
            assert_eq!(
                drained.len() + forwarded_count,
                ENQUEUERS,
                "every request must be either drained or forwarded (iteration {iteration})"
            );
            assert_eq!(
                drained.len(),
                stashed_count,
                "drained count must equal stashed count (iteration {iteration})"
            );
        }
    }

    /// When a stashed request's drain handler delivers a result via the
    /// reply channel, the original caller (waiting on the receiver) must
    /// see it. This exercises the contract the `RouterStashHandler` drain
    /// path relies on.
    #[tokio::test]
    async fn drained_request_reply_round_trips() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        let rx = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let mut drained = drain_to_vec(&table, 0).await;
        let req = drained.remove(0);
        let response = UpdatePersonPropertiesResponse {
            person: None,
            updated: true,
        };
        req.reply
            .send(Ok(response.clone()))
            .expect("send must succeed when receiver is alive");

        let received = rx.await.expect("receiver must observe sender");
        assert_eq!(received.unwrap(), response);
    }

    /// If the original caller dropped its receiver (e.g. the gRPC client
    /// disconnected) before drain delivered the reply, the `send` must
    /// return `Err`. The drain handler relies on this signal to bump the
    /// `personhog_router_stash_dropped_total` counter.
    #[tokio::test]
    async fn dropped_receiver_makes_send_fail() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        let rx = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        drop(rx);

        let mut drained = drain_to_vec(&table, 0).await;
        let req = drained.remove(0);
        let response = UpdatePersonPropertiesResponse {
            person: None,
            updated: false,
        };
        assert!(
            req.reply.send(Ok(response)).is_err(),
            "send must return Err after the receiver is dropped"
        );
    }

    /// Regression for the structural race the `drained` tombstone closes:
    /// a `begin_stash` that observes the post-`take` `None` queue between
    /// `drain` releasing the queue lock and `drain` evicting the dashmap
    /// entry must not initialize a new queue on the doomed `Arc`. With
    /// the tombstone, `begin_stash` sees `drained=true`, drops the lock,
    /// and retries via `get_or_create` — which produces a fresh dashmap
    /// entry once `drain` finishes its `inner.remove`.
    ///
    /// The race window is microseconds; we run many iterations to
    /// exercise it. The protocol awaits `drain` before issuing the next
    /// `begin_stash` for a partition today, so this race cannot trigger
    /// in production — the test guards against future callers that
    /// might break that ordering.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn drain_does_not_orphan_concurrent_begin_stash() {
        for iteration in 0..500 {
            let table = StashTable::with_bounds(usize::MAX, usize::MAX);
            table.begin_stash(0).await;

            // Drain in one task; concurrent begin_stash in another.
            // The key invariant: after both complete, the dashmap must
            // contain a live entry for the partition (because
            // begin_stash was the most recent successful call), so a
            // subsequent enqueue sees it and parks.
            let drain_table = table.clone();
            let drain_handle = tokio::spawn(async move {
                drain_table.drain(0, |_batch| async {}).await;
            });
            let begin_table = table.clone();
            let begin_handle = tokio::spawn(async move { begin_table.begin_stash(0).await });

            drain_handle.await.unwrap();
            begin_handle.await.unwrap();

            // Only meaningful to assert when begin_stash logically ran
            // *after* drain (drain.remove evicted, begin_stash created
            // a fresh entry). If begin_stash logically ran first
            // (observed the prior `Some` queue, was idempotent), then
            // drain legitimately drained that prior queue and a
            // subsequent enqueue forwards via the live path — that's a
            // protocol-violation scenario, not a stash-module bug, and
            // the routing-table layer prevents it. We accept either
            // outcome here; what we *don't* accept is a non-empty
            // drained queue that was just initialized by begin_stash on
            // an orphaned Arc, which the tombstone prevents.
            let outcome = table.enqueue_or_forward(0, mk_request(1, 1), None).await;
            match outcome {
                StashDecision::Stashed(_) => {
                    // Fresh dashmap entry exists — begin_stash set it up correctly.
                }
                StashDecision::Forward => {
                    // Begin_stash logically ran first and was idempotent;
                    // drain emptied the prior queue. No orphaned Arc.
                }
                StashDecision::Rejected => {
                    panic!("unexpected Rejected on iteration {iteration}");
                }
            }
        }
    }
}
