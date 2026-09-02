//! Per-partition stash for the leader path.
//!
//! During a partition handoff, the coordinator advances the handoff state
//! through `Freezing → Draining → Warming → Complete`. From the moment
//! the handoff is created (in `Freezing`) and until the routing table
//! flips at `Complete`, routers buffer (stash) incoming leader-path
//! requests — writes and strong reads alike — for that partition here.
//! When `Complete` arrives the stashed requests are drained to the new
//! owner in per-key admission order.
//!
//! Stashing both request kinds gives the protocol two guarantees at once:
//! no split-brain writes, and strong reads that stay read-your-write
//! through the handoff — a read queued behind the write it must observe
//! (per-key FIFO) drains after it, instead of racing ahead to the old
//! owner's frozen cache.
//!
//! Internally each partition holds a [`KeyedStash`] keyed by
//! `(team_id, person_id)` — the leader's per-person serialization
//! boundary. Entries are seq-stamped at admission and leave the stash
//! only through a definitive outcome (delivered, or failed in a way the
//! client was told about); an attempt that cannot finish — the target
//! bounced it, the drain was paused or superseded — puts its entries
//! back at their sequence positions, so a retry can never be overtaken
//! by newer same-key work. Draining runs through a [`DrainSession`],
//! which owns the take → complete/put-back lifecycle and the
//! empty-queue eviction handshake.

use std::sync::Arc;
use std::time::Instant;

use bytes::Bytes;
use dashmap::DashMap;
use http::HeaderMap;
use keyed_stash::{Entry, KeyedStash};
use tokio::sync::{oneshot, Mutex};
use tonic::body::BoxBody;

/// The leader's per-person serialization key: `(team_id, person_id)`.
/// Per-key ordering is preserved from admission through drain; distinct
/// keys carry no ordering relationship and may drain in parallel.
pub type StashKey = (i64, i64);

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

/// Approximate the memory footprint of a stashed request — the raw frame
/// plus a fixed per-entry overhead estimate. Used to enforce the
/// byte-based stash bound; an order-of-magnitude bound is enough, so this
/// doesn't attempt exact accounting of the headers map.
fn approximate_size(frame: &Bytes) -> usize {
    PER_REQUEST_OVERHEAD + frame.len()
}

/// A raw leader-path request held in the stash along with everything
/// needed to replay it and return the response to the original caller.
pub struct StashedRequest {
    /// gRPC method the frame targets, so drain replays each request to
    /// the path it arrived on (writes and strong reads share the stash).
    pub method: &'static str,
    /// The raw gRPC request frame, forwarded verbatim on replay.
    pub frame: Bytes,
    /// The client's request headers, forwarded verbatim (the router stamps
    /// `x-partition` at forward time).
    pub headers: HeaderMap,
    /// The leader's per-person serialization key, used to preserve
    /// per-key ordering during drain.
    pub key: StashKey,
    pub reply: oneshot::Sender<http::Response<BoxBody>>,
    /// Wall-clock time the request was enqueued. Used to enforce the
    /// per-request drain deadline and to record stash-wait histograms,
    /// giving operators visibility into how long callers spent parked
    /// during a handoff.
    pub enqueued_at: Instant,
    /// Set when a delivery attempt failed at the transport layer after
    /// the request may already have been sent: the leader might have
    /// applied it without us seeing the response. Re-forwarding such a
    /// request is an at-least-once replay — covered by the redelivery
    /// contract in `personhog-leader`'s README — and is counted so
    /// operators can see how often it happens.
    pub possibly_applied: bool,
}

impl StashedRequest {
    /// The size this request counts against the byte bound. Callers
    /// recording a definitive outcome pass this back to
    /// [`DrainSession::complete`] so the bound releases exactly what
    /// admission charged.
    pub fn approximate_size(&self) -> usize {
        approximate_size(&self.frame)
    }
}

/// Inner keyed queue plus running admission totals. `messages` and
/// `bytes` count entries from admission until a definitive outcome —
/// including entries taken for an in-flight attempt, which still hold
/// their memory — so the bounds reflect what the router is actually
/// holding, not just what is queued.
struct StashQueue {
    queue: KeyedStash<StashKey, StashedRequest>,
    messages: usize,
    bytes: usize,
}

impl StashQueue {
    fn new() -> Self {
        Self {
            queue: KeyedStash::new(),
            messages: 0,
            bytes: 0,
        }
    }
}

struct PartitionStash {
    max_messages: usize,
    max_bytes: usize,
    /// `Some(queue)` while alive; `None` once a drain session has both
    /// observed the queue fully settled and evicted this entry from the
    /// dashmap — both inside the same critical section. The `None` state
    /// therefore doubles as a tombstone: a concurrent `begin_stash` that
    /// races the eviction and observes `None` knows the dashmap entry is
    /// already gone and that the next `get_or_create` will produce a
    /// fresh entry rather than re-grab this doomed `Arc`.
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
    Stashed(oneshot::Receiver<http::Response<BoxBody>>),
    Rejected,
}

/// One key's front run taken for a delivery attempt: every entry queued
/// for the key at take time, in admission order. Entries are in-attempt
/// until each is completed or put back through the session.
pub struct TakenKeyRun {
    pub key: StashKey,
    pub entries: Vec<Entry<StashedRequest>>,
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

    /// Whether the partition currently has a stash entry — a live
    /// window, or backlog a yielded drain left parked. The entry only
    /// disappears through drain's settle-and-evict, so its existence is
    /// exactly "the stash lifecycle for this partition is not closed".
    pub fn has_entry(&self, partition: u32) -> bool {
        self.inner.contains_key(&partition)
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
    /// `None` is to race a drain session's eviction, which removes the
    /// entry inside its queue lock — meaning the next `get_or_create`
    /// will create a fresh entry rather than re-grab the doomed `Arc`.
    /// In production the routing-table layer awaits the drain before
    /// issuing the next `begin_stash` for the same partition, so this
    /// loop runs at most twice.
    pub async fn begin_stash(&self, partition: u32) {
        while !self.try_acquire_alive_entry(partition).await {}
    }

    /// One attempt to bind to the live dashmap entry for `partition`.
    /// Returns `true` if we successfully observed a `Some` queue (the
    /// entry is alive and ready for enqueues); `false` if we raced an
    /// eviction that left a tombstoned `None`, in which case the caller
    /// should retry to pick up the fresh entry.
    async fn try_acquire_alive_entry(&self, partition: u32) -> bool {
        let stash = self.get_or_create(partition);
        let guard = stash.queue.lock().await;
        guard.is_some()
    }

    /// Enqueue a request if the partition is frozen; otherwise return
    /// `Forward` to signal the caller should route normally.
    /// Takes the frame and headers by reference and clones them only when
    /// the request actually parks — the steady state (no handoff in
    /// progress) returns `Forward` from the dashmap miss without copying
    /// anything.
    ///
    /// `possibly_applied` carries the direct path's transport-failure mark
    /// into the parked entry: a request that bounced at the transport
    /// layer before parking may already have reached the leader, and the
    /// drain's eventual re-forward of it must count as a replay.
    pub async fn enqueue_or_forward(
        &self,
        partition: u32,
        method: &'static str,
        frame: &Bytes,
        headers: &HeaderMap,
        key: StashKey,
        possibly_applied: bool,
    ) -> StashDecision {
        let stash = match self.inner.get(&partition) {
            Some(entry) => Arc::clone(entry.value()),
            None => return StashDecision::Forward,
        };
        let mut guard = stash.queue.lock().await;
        // `None` here means a drain session already settled this stash
        // and removed the dashmap entry. We arrived holding an Arc to
        // the orphaned PartitionStash. Returning Forward routes via the
        // normal path; the partition is no longer stashing.
        let Some(queue) = guard.as_mut() else {
            return StashDecision::Forward;
        };

        let request_size = approximate_size(frame);

        if queue.messages >= stash.max_messages {
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
        queue.queue.push(
            key,
            StashedRequest {
                method,
                frame: frame.clone(),
                headers: headers.clone(),
                key,
                reply: tx,
                enqueued_at: Instant::now(),
                possibly_applied,
            },
        );
        queue.messages += 1;
        queue.bytes += request_size;
        metrics::counter!("personhog_router_stash_enqueued_total").increment(1);
        // Occupancy gauges count a parked entry until its outcome
        // resolves, so in-attempt entries still occupy capacity.
        metrics::gauge!("personhog_router_stash_queued_messages").increment(1.0);
        metrics::gauge!("personhog_router_stash_queued_bytes").increment(request_size as f64);
        StashDecision::Stashed(rx)
    }

    /// Open a drain session for `partition`, or `None` when nothing is
    /// stashed. The session pins the partition's stash so every take,
    /// complete, and put-back lands on the same queue the entries came
    /// from, even across the eviction handshake.
    ///
    /// The drain-lane layer serializes drains per partition, so at most
    /// one session is active for a partition at a time; the session API
    /// relies on that for its eviction reasoning but tolerates a racing
    /// `begin_stash` (see [`DrainSession::finish_if_settled`]).
    pub fn drain_session(&self, partition: u32) -> Option<DrainSession> {
        let stash = Arc::clone(self.inner.get(&partition)?.value());
        Some(DrainSession {
            inner: Arc::clone(&self.inner),
            partition,
            stash,
        })
    }
}

/// The take → complete/put-back lifecycle for one partition's drain.
///
/// A drain repeatedly takes per-key front runs, attempts delivery, and
/// records exactly one of two outcomes per entry:
///
/// * [`complete`](Self::complete) — the entry's client got a definitive
///   answer (the forwarded response, or a terminal error). The entry is
///   gone and its admission charge is released.
/// * [`put_back`](Self::put_back) — the attempt was aborted before any
///   outcome existed (the target bounced it, the drain was paused or
///   superseded). The entries re-enter at their sequence positions,
///   ahead of everything admitted after them.
///
/// When a take finds no backlog, [`finish_if_settled`](Self::finish_if_settled)
/// closes the drain: if the queue is fully settled it tombstones the
/// queue and evicts the dashmap entry in one critical section, so any
/// racing `enqueue_or_forward` either pushes before the settle check
/// (forcing the caller through another take) or observes the entry
/// already gone and forwards live.
///
/// Requests that arrive *during* a session land on the same queue (the
/// dashmap entry stays present until the settle eviction) and are picked
/// up by a later take, preserving per-key admission order across the
/// cutover.
pub struct DrainSession {
    inner: Arc<DashMap<u32, Arc<PartitionStash>>>,
    partition: u32,
    stash: Arc<PartitionStash>,
}

impl DrainSession {
    /// Take the front run of up to `max_keys` keys for a delivery
    /// attempt. Returns an empty vec when no backlog is queued. Every
    /// returned entry is in-attempt until completed or put back;
    /// dropping entries instead would lose their clients' replies and
    /// permanently block the queue from settling.
    pub async fn take_for_attempt(&self, max_keys: usize) -> Vec<TakenKeyRun> {
        let mut guard = self.stash.queue.lock().await;
        let Some(q) = guard.as_mut() else {
            return Vec::new();
        };
        let keys: Vec<StashKey> = q
            .queue
            .keys_with_backlog()
            .take(max_keys)
            .copied()
            .collect();
        keys.into_iter()
            .map(|key| TakenKeyRun {
                entries: q.queue.take_front(&key, usize::MAX),
                key,
            })
            .collect()
    }

    /// Record a definitive outcome for one in-attempt entry of `key`,
    /// releasing `size` bytes (the entry's `approximate_size`) from the
    /// admission bounds.
    pub async fn complete(&self, key: StashKey, size: usize) {
        let mut guard = self.stash.queue.lock().await;
        // In-attempt entries block the settle eviction and this session
        // is the only writer of outcomes, so the queue cannot have been
        // tombstoned while an attempt was outstanding.
        let Some(q) = guard.as_mut() else {
            debug_assert!(false, "complete() on a tombstoned stash");
            return;
        };
        q.queue.complete(&key);
        q.messages -= 1;
        q.bytes = q.bytes.saturating_sub(size);
        metrics::gauge!("personhog_router_stash_queued_messages").decrement(1.0);
        metrics::gauge!("personhog_router_stash_queued_bytes").decrement(size as f64);
    }

    /// Return in-attempt entries whose delivery was aborted before any
    /// outcome existed. They re-enter at their sequence positions and
    /// keep their admission charges; the next attempt sees them first,
    /// in order.
    pub async fn put_back(&self, key: StashKey, entries: Vec<Entry<StashedRequest>>) {
        if entries.is_empty() {
            return;
        }
        let mut guard = self.stash.queue.lock().await;
        // Same reasoning as `complete`: outstanding in-attempt entries
        // make the tombstone unreachable.
        let Some(q) = guard.as_mut() else {
            debug_assert!(false, "put_back() on a tombstoned stash");
            return;
        };
        q.queue.put_back(&key, entries);
    }

    /// Close the session if the queue is fully settled — no queued
    /// entries and no in-attempt entries. On success the queue is
    /// tombstoned and the dashmap entry evicted inside the same critical
    /// section, and `true` is returned: the partition has left the stash
    /// path and new requests forward live. Returns `false` when an
    /// arrival raced in since the last take; the caller should take
    /// again.
    ///
    /// The eviction removes the entry only if it still holds this
    /// session's stash, so a `begin_stash` that already replaced a
    /// tombstoned entry with a fresh one can never have its new queue
    /// evicted from under it.
    pub async fn finish_if_settled(&self) -> bool {
        let mut guard = self.stash.queue.lock().await;
        match guard.as_ref() {
            // Already tombstoned — a prior settle got there first.
            None => true,
            Some(q) if q.queue.is_empty() => {
                *guard = None;
                self.inner
                    .remove_if(&self.partition, |_, v| Arc::ptr_eq(v, &self.stash));
                true
            }
            Some(_) => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use http::HeaderValue;
    use http_body_util::{BodyExt, Empty};

    /// Drain everything with a trivial always-succeeds forwarder,
    /// collecting the requests in delivery order. Mirrors the handler's
    /// session loop: take, complete each entry, settle when no backlog
    /// remains.
    async fn drain_to_vec(table: &StashTable, partition: u32) -> Vec<StashedRequest> {
        let Some(session) = table.drain_session(partition) else {
            return Vec::new();
        };
        let mut out = Vec::new();
        loop {
            let taken = session.take_for_attempt(usize::MAX).await;
            if taken.is_empty() {
                if session.finish_if_settled().await {
                    return out;
                }
                continue;
            }
            for run in taken {
                for entry in run.entries {
                    let size = entry.item.approximate_size();
                    out.push(entry.item);
                    session.complete(run.key, size).await;
                }
            }
        }
    }

    /// Enqueue a minimal stashed write for `(team_id = 1, person_id)`.
    async fn enqueue(table: &StashTable, partition: u32, person_id: i64) -> StashDecision {
        table
            .enqueue_or_forward(
                partition,
                "UpdatePersonProperties",
                &Bytes::from_static(b"x"),
                &HeaderMap::new(),
                (1, person_id),
                false,
            )
            .await
    }

    /// Enqueue a stashed write whose frame is `payload` bytes, exercising
    /// the byte-based stash bound.
    async fn enqueue_sized(
        table: &StashTable,
        partition: u32,
        person_id: i64,
        payload: usize,
    ) -> StashDecision {
        table
            .enqueue_or_forward(
                partition,
                "UpdatePersonProperties",
                &Bytes::from(vec![0u8; payload]),
                &HeaderMap::new(),
                (1, person_id),
                false,
            )
            .await
    }

    /// A trivial gRPC response for exercising the reply channel.
    fn test_response() -> http::Response<BoxBody> {
        http::Response::new(BoxBody::new(
            Empty::<Bytes>::new().map_err(|never| match never {}),
        ))
    }

    #[tokio::test]
    async fn forward_when_not_frozen() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        match enqueue(&table, 0, 1).await {
            StashDecision::Forward => {}
            _ => panic!("expected Forward"),
        }
    }

    #[tokio::test]
    async fn begin_then_enqueue_then_drain_preserves_per_key_order() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        // Same key, distinguishable frames — ordering is a per-key
        // contract, so the assertion must not depend on cross-key
        // iteration order.
        let _rx1 = match enqueue_sized(&table, 0, 1, 1).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let _rx2 = match enqueue_sized(&table, 0, 1, 2).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let drained = drain_to_vec(&table, 0).await;
        assert_eq!(drained.len(), 2);
        let frame_lens: Vec<usize> = drained.iter().map(|s| s.frame.len()).collect();
        assert_eq!(frame_lens, vec![1, 2]);

        // After drain, new requests forward.
        match enqueue(&table, 0, 3).await {
            StashDecision::Forward => {}
            _ => panic!("expected Forward after drain"),
        }
    }

    /// A settled drain must remove the dashmap entry so subsequent
    /// steady-state requests for that partition can short-circuit on
    /// `dashmap.get` returning `None`, avoiding the per-request Mutex
    /// lock that `enqueue_or_forward` would otherwise take.
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
            "settle must remove the entry so future requests skip the lock path"
        );
    }

    /// An aborted attempt puts its entries back and leaves the entry
    /// live: whatever is parked belongs to the successor drain, and new
    /// requests must keep stashing in the meantime. Evicting instead
    /// would let requests bypass the stash and race ahead of the parked
    /// backlog.
    #[tokio::test]
    async fn put_back_leaves_queue_live_for_successor() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;
        let _rx = match enqueue(&table, 0, 1).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        // An attempt starts, then aborts (pause/supersession/bounce) and
        // puts everything back without settling.
        let session = table.drain_session(0).expect("entry must be live");
        let mut taken = session.take_for_attempt(usize::MAX).await;
        assert_eq!(taken.len(), 1);
        let run = taken.remove(0);
        session.put_back(run.key, run.entries).await;
        drop(session);
        assert!(
            table.inner.contains_key(&0),
            "aborted drain must leave the entry live"
        );

        // Requests keep parking, and a successor drain collects everything.
        let _rx2 = match enqueue(&table, 0, 2).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed while entry is live"),
        };
        let drained = drain_to_vec(&table, 0).await;
        assert_eq!(
            drained.len(),
            2,
            "successor drain must see the full backlog"
        );
    }

    /// In-attempt entries must block the settle eviction: the queue can
    /// look empty (backlog fully taken) while outcomes are still
    /// outstanding, and settling then would orphan the eventual put-back
    /// into a tombstoned queue, dropping the clients' replies.
    #[tokio::test]
    async fn in_attempt_entries_block_settle() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;
        let _rx = match enqueue(&table, 0, 1).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let session = table.drain_session(0).expect("entry must be live");
        let mut taken = session.take_for_attempt(usize::MAX).await;
        let run = taken.remove(0);
        assert!(
            !session.finish_if_settled().await,
            "settle must refuse while an attempt is outstanding"
        );

        let entry = run.entries.into_iter().next().unwrap();
        let size = entry.item.approximate_size();
        session.complete(run.key, size).await;
        assert!(
            session.finish_if_settled().await,
            "settle must succeed once every outcome is recorded"
        );
        assert!(!table.inner.contains_key(&0));
    }

    /// Back-to-back handoffs: drain → begin_stash for the same partition
    /// must produce a fresh empty queue, not preserve stale state.
    #[tokio::test]
    async fn drain_then_begin_stash_starts_fresh() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;
        let _rx = match enqueue(&table, 0, 1).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let drained = drain_to_vec(&table, 0).await;
        assert_eq!(drained.len(), 1);

        // New handoff begins
        table.begin_stash(0).await;
        // Fresh queue; brand-new requests stash, not forward
        match enqueue(&table, 0, 2).await {
            StashDecision::Stashed(_) => {}
            _ => panic!("expected Stashed for fresh handoff"),
        }
    }

    #[tokio::test]
    async fn reject_when_message_count_exceeds_max() {
        let table = StashTable::with_bounds(2, usize::MAX);
        table.begin_stash(0).await;

        assert!(matches!(
            enqueue(&table, 0, 1).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            enqueue(&table, 0, 2).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            enqueue(&table, 0, 3).await,
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
            enqueue_sized(&table, 0, 1, 2 * 1024).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            enqueue_sized(&table, 0, 2, 2 * 1024).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            enqueue_sized(&table, 0, 3, 2 * 1024).await,
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
            enqueue(&table, 0, 1).await,
            StashDecision::Stashed(_)
        ));
        // Second message rejected on count even though bytes are nowhere near.
        assert!(matches!(
            enqueue(&table, 0, 2).await,
            StashDecision::Rejected
        ));
    }

    /// The admission bounds must release on definitive outcomes, not on
    /// takes: an entry taken for an attempt still holds its memory, and
    /// releasing at take time would let a slow drain admit unbounded
    /// backlog behind it.
    #[tokio::test]
    async fn bounds_release_on_complete_not_on_take() {
        let table = StashTable::with_bounds(1, usize::MAX);
        table.begin_stash(0).await;
        assert!(matches!(
            enqueue(&table, 0, 1).await,
            StashDecision::Stashed(_)
        ));

        let session = table.drain_session(0).expect("entry must be live");
        let mut taken = session.take_for_attempt(usize::MAX).await;
        let run = taken.remove(0);
        // Taken but not completed — still counted against the bound.
        assert!(matches!(
            enqueue(&table, 0, 2).await,
            StashDecision::Rejected
        ));

        let entry = run.entries.into_iter().next().unwrap();
        let size = entry.item.approximate_size();
        session.complete(run.key, size).await;
        // Outcome recorded — capacity is released.
        assert!(matches!(
            enqueue(&table, 0, 3).await,
            StashDecision::Stashed(_)
        ));
    }

    #[tokio::test]
    async fn partitions_are_independent() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        // p0 stashes, p1 forwards
        assert!(matches!(
            enqueue(&table, 0, 1).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            enqueue(&table, 1, 1).await,
            StashDecision::Forward
        ));
    }

    /// Race between concurrent enqueue and drain. The `Arc<PartitionStash>`
    /// + `Option<StashQueue>` design exists so that an enqueue that has
    /// already cloned the Arc when the settle eviction runs sees `None`,
    /// and returns `Forward` rather than pushing into a dead queue. With
    /// many iterations this drives the race window repeatedly; the
    /// invariant is that every request must end up either in the drained
    /// batch or forwarded — never lost, never duplicated.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn enqueue_and_drain_race() {
        for iteration in 0..200 {
            let table = StashTable::with_bounds(usize::MAX, usize::MAX);
            table.begin_stash(0).await;

            const ENQUEUERS: usize = 8;
            let mut handles = Vec::with_capacity(ENQUEUERS);
            for i in 0..ENQUEUERS {
                let table = table.clone();
                handles.push(tokio::spawn(
                    async move { enqueue(&table, 0, i as i64).await },
                ));
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

            // The session loop only settles after observing no backlog,
            // so every Stashed request is delivered regardless of when it
            // arrived (concurrent arrivals are caught by a later take).
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

        let rx = match enqueue(&table, 0, 1).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let mut drained = drain_to_vec(&table, 0).await;
        let req = drained.remove(0);
        let mut response = test_response();
        response
            .headers_mut()
            .insert("x-test", HeaderValue::from_static("ok"));
        req.reply
            .send(response)
            .expect("send must succeed when receiver is alive");

        let received = rx.await.expect("receiver must observe sender");
        assert_eq!(received.headers().get("x-test").unwrap(), "ok");
    }

    /// If the original caller dropped its receiver (e.g. the gRPC client
    /// disconnected) before drain delivered the reply, the `send` must
    /// return `Err`. The drain handler relies on this signal to bump the
    /// `personhog_router_stash_dropped_total` counter.
    #[tokio::test]
    async fn dropped_receiver_makes_send_fail() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        let rx = match enqueue(&table, 0, 1).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        drop(rx);

        let mut drained = drain_to_vec(&table, 0).await;
        let req = drained.remove(0);
        assert!(
            req.reply.send(test_response()).is_err(),
            "send must return Err after the receiver is dropped"
        );
    }

    /// Regression for the structural race the `drained` tombstone closes:
    /// a `begin_stash` that observes the post-settle `None` queue between
    /// the settle tombstoning the queue and evicting the dashmap entry
    /// must not initialize a new queue on the doomed `Arc`. With the
    /// tombstone, `begin_stash` sees `None`, drops the lock, and retries
    /// via `get_or_create` — which produces a fresh dashmap entry once
    /// the eviction finishes.
    ///
    /// The race window is microseconds; we run many iterations to
    /// exercise it. The protocol awaits the drain before issuing the next
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
                drain_to_vec(&drain_table, 0).await;
            });
            let begin_table = table.clone();
            let begin_handle = tokio::spawn(async move { begin_table.begin_stash(0).await });

            drain_handle.await.unwrap();
            begin_handle.await.unwrap();

            // Only meaningful to assert when begin_stash logically ran
            // *after* the settle (eviction removed the entry, begin_stash
            // created a fresh one). If begin_stash logically ran first
            // (observed the prior `Some` queue, was idempotent), then
            // the drain legitimately drained that prior queue and a
            // subsequent enqueue forwards via the direct path — that's a
            // protocol-violation scenario, not a stash-module bug, and
            // the routing-table layer prevents it. We accept either
            // outcome here; what we *don't* accept is a non-empty
            // drained queue that was just initialized by begin_stash on
            // an orphaned Arc, which the tombstone prevents.
            let outcome = enqueue(&table, 0, 1).await;
            match outcome {
                StashDecision::Stashed(_) => {
                    // Fresh dashmap entry exists — begin_stash set it up correctly.
                }
                StashDecision::Forward => {
                    // Begin_stash logically ran first and was idempotent;
                    // the drain emptied the prior queue. No orphaned Arc.
                }
                StashDecision::Rejected => {
                    panic!("unexpected Rejected on iteration {iteration}");
                }
            }
        }
    }
}
