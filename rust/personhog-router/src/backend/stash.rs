//! Per-key stash for the leader path.
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
//! Requests park per key `(team_id, person_id)`, the leader's per-person
//! serialization boundary, in a shard chosen by the key alone. A key's
//! requests therefore share one queue whatever the partition count does,
//! and a request goes straight to the leader only when its key has nothing
//! parked or in flight and its partition is not stashing. The partition
//! count decides only which drain delivers a key: a drain for `p` takes
//! the keys that map to `p` under the live count.
//!
//! Entries are seq-stamped at admission and leave the stash only through
//! a definitive outcome (delivered, or failed in a way the client was
//! told about); an attempt that cannot finish — the target bounced it,
//! the drain was paused or superseded — puts its entries back at their
//! sequence positions, so a retry can never be overtaken by newer
//! same-key work. Draining runs through a [`DrainSession`], which owns
//! the take → complete/put-back lifecycle and the settle handshake.

use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use bytes::Bytes;
use dashmap::DashMap;
use http::HeaderMap;
use keyed_stash::{Entry, KeyedStash};
use personhog_common::partitioning::person_hash;
use personhog_coordination::changelog::LiveChangelog;
use tokio::sync::oneshot;
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

/// Shards of the key space, fixed so a key's shard never depends on the partition count.
const SHARDS: u32 = 64;

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
    /// The partition whose bounds admission charged.
    charged_to: u32,
}

/// What admission charged a request, released by its definitive outcome.
#[derive(Debug, Clone, Copy)]
pub struct Charge {
    partition: u32,
    bytes: usize,
}

impl StashedRequest {
    /// Callers recording a definitive outcome pass this back to
    /// [`DrainSession::complete`] so the bounds release exactly what
    /// admission charged.
    pub fn charge(&self) -> Charge {
        Charge {
            partition: self.charged_to,
            bytes: approximate_size(&self.frame),
        }
    }
}

/// Outcome of an `enqueue_or_forward` call. `Forward` means "nothing to
/// wait behind, route normally"; `Stashed` means the request has been
/// enqueued and the caller should await the receiver for its reply;
/// `Rejected` means the partition's bounds are full.
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

/// A parked key with its hash, so its partition under any count is one modulo.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
struct ParkedKey {
    key: StashKey,
    hash: u32,
}

impl ParkedKey {
    fn of(key: StashKey) -> Self {
        Self {
            key,
            hash: person_hash(key.0, key.1),
        }
    }
}

struct Shard {
    queue: Mutex<KeyedStash<ParkedKey, StashedRequest>>,
    /// Entries from admission until a definitive outcome; zero lets a request skip the lock.
    held: AtomicUsize,
}

impl Shard {
    fn lock(&self) -> MutexGuard<'_, KeyedStash<ParkedKey, StashedRequest>> {
        self.queue.lock().expect("stash shard lock poisoned")
    }
}

/// Admission totals for one partition. They count entries until a
/// definitive outcome, in-attempt ones included, so the bounds reflect
/// what the router actually holds.
#[derive(Default)]
struct Usage {
    messages: usize,
    bytes: usize,
}

struct Inner {
    shards: Vec<Shard>,
    /// Stashing partitions, each with the generation of the freeze that opened it.
    stashing: DashMap<u32, u64>,
    next_generation: AtomicU64,
    usage: DashMap<u32, Usage>,
    max_messages: usize,
    max_bytes: usize,
    changelog: LiveChangelog,
}

impl Inner {
    fn shard_of(&self, key: &ParkedKey) -> &Shard {
        &self.shards[(key.hash % SHARDS) as usize]
    }

    fn partition_of(&self, key: &ParkedKey) -> u32 {
        key.hash % self.changelog.partitions()
    }

    /// Whether any key that maps to `partition` has parked or in-flight
    /// requests, locking one shard at a time.
    fn holds_keys_of(&self, partition: u32) -> bool {
        self.shards.iter().any(|shard| {
            shard.held.load(Ordering::Acquire) > 0
                && shard
                    .lock()
                    .deferring_keys()
                    .any(|key| self.partition_of(key) == partition)
        })
    }

    fn release(&self, shard: &Shard, charge: Charge) {
        shard.held.fetch_sub(1, Ordering::AcqRel);
        match self.usage.entry(charge.partition) {
            dashmap::Entry::Occupied(mut usage) => {
                let usage_ref = usage.get_mut();
                usage_ref.messages -= 1;
                usage_ref.bytes = usage_ref.bytes.saturating_sub(charge.bytes);
                if usage_ref.messages == 0 {
                    usage.remove();
                }
                metrics::gauge!("personhog_router_stash_queued_messages").decrement(1.0);
                metrics::gauge!("personhog_router_stash_queued_bytes")
                    .decrement(charge.bytes as f64);
            }
            dashmap::Entry::Vacant(_) => debug_assert!(false, "released a charge never admitted"),
        }
    }
}

/// Shared stash table. Cheap to clone (holds an `Arc`).
#[derive(Clone)]
pub struct StashTable {
    inner: Arc<Inner>,
}

impl StashTable {
    pub fn with_bounds(max_messages: usize, max_bytes: usize, changelog: LiveChangelog) -> Self {
        let shards = (0..SHARDS)
            .map(|_| Shard {
                queue: Mutex::new(KeyedStash::new()),
                held: AtomicUsize::new(0),
            })
            .collect();
        Self {
            inner: Arc::new(Inner {
                shards,
                stashing: DashMap::new(),
                next_generation: AtomicU64::new(0),
                usage: DashMap::new(),
                max_messages,
                max_bytes,
                changelog,
            }),
        }
    }

    /// Whether `partition` still needs a drain: it is stashing, or a key
    /// that maps to it under the live count has parked or in-flight requests.
    pub fn is_pending(&self, partition: u32) -> bool {
        self.inner.stashing.contains_key(&partition) || self.inner.holds_keys_of(partition)
    }

    /// Begin buffering requests for `partition`. Each call opens a new
    /// generation, so a drain that started before it cannot close it.
    pub fn begin_stash(&self, partition: u32) {
        let generation = self.inner.next_generation.fetch_add(1, Ordering::Relaxed);
        self.inner.stashing.insert(partition, generation);
    }

    /// Park the request if its key has parked or in-flight requests, or
    /// `partition`, the one the caller forwards to, is stashing; otherwise
    /// return `Forward`. Takes the frame and headers by reference and
    /// clones them only when the request actually parks.
    ///
    /// `possibly_applied` carries the direct path's transport-failure mark
    /// into the parked entry: a request that bounced at the transport
    /// layer before parking may already have reached the leader, and the
    /// drain's eventual re-forward of it must count as a replay.
    pub fn enqueue_or_forward(
        &self,
        method: &'static str,
        frame: &Bytes,
        headers: &HeaderMap,
        key: StashKey,
        partition: u32,
        possibly_applied: bool,
    ) -> StashDecision {
        let inner = &self.inner;
        let parked = ParkedKey::of(key);
        let shard = inner.shard_of(&parked);
        if shard.held.load(Ordering::Acquire) == 0 && !inner.stashing.contains_key(&partition) {
            return StashDecision::Forward;
        }
        // Under the shard lock, so a drain's settle check sees this request or it sees the settle.
        let mut queue = shard.lock();
        if !queue.is_deferring(&parked) && !inner.stashing.contains_key(&partition) {
            return StashDecision::Forward;
        }

        let request_size = approximate_size(frame);
        let (messages, bytes) = inner
            .usage
            .get(&partition)
            .map_or((0, 0), |usage| (usage.messages, usage.bytes));
        let rejected = if messages >= inner.max_messages {
            Some(RejectCause::MaxMessages)
        } else if bytes.saturating_add(request_size) > inner.max_bytes {
            Some(RejectCause::MaxBytes)
        } else {
            None
        };
        if let Some(cause) = rejected {
            metrics::counter!("personhog_router_stash_rejected_total", "cause" => cause.label())
                .increment(1);
            return StashDecision::Rejected;
        }

        let (tx, rx) = oneshot::channel();
        queue.push(
            parked,
            StashedRequest {
                method,
                frame: frame.clone(),
                headers: headers.clone(),
                reply: tx,
                enqueued_at: Instant::now(),
                possibly_applied,
                charged_to: partition,
            },
        );
        shard.held.fetch_add(1, Ordering::AcqRel);
        let mut usage = inner.usage.entry(partition).or_default();
        usage.messages += 1;
        usage.bytes += request_size;
        metrics::counter!("personhog_router_stash_enqueued_total").increment(1);
        // Occupancy counts a parked entry until its outcome resolves.
        metrics::gauge!("personhog_router_stash_queued_messages").increment(1.0);
        metrics::gauge!("personhog_router_stash_queued_bytes").increment(request_size as f64);
        StashDecision::Stashed(rx)
    }

    /// Open a drain session for `partition`, or `None` when nothing is
    /// pending. The drain-lane layer serializes drains per partition;
    /// sessions for different partitions may still meet on one key after
    /// a count change, and a key out with one session is skipped by the
    /// others.
    pub fn drain_session(&self, partition: u32) -> Option<DrainSession> {
        if !self.is_pending(partition) {
            return None;
        }
        Some(DrainSession {
            inner: Arc::clone(&self.inner),
            partition,
            generation: self.inner.stashing.get(&partition).map(|g| *g),
            candidates: Mutex::new(Vec::new()),
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
/// When a take finds nothing, [`finish_if_settled`](Self::finish_if_settled)
/// closes the drain once no key of the partition has parked or in-flight
/// requests.
pub struct DrainSession {
    inner: Arc<Inner>,
    partition: u32,
    /// The freeze this session may close; `None` when it drains keys alone.
    generation: Option<u64>,
    /// Keys of the partition found by the last scan, not yet taken.
    candidates: Mutex<Vec<ParkedKey>>,
}

impl DrainSession {
    fn candidates(&self) -> MutexGuard<'_, Vec<ParkedKey>> {
        self.candidates
            .lock()
            .expect("drain candidates lock poisoned")
    }

    /// Take the front run of up to `max_keys` of the partition's keys for
    /// a delivery attempt. Returns an empty vec when none is available.
    /// Every returned entry is in-attempt until completed or put back;
    /// dropping entries instead would lose their clients' replies and
    /// permanently block the partition from settling.
    pub fn take_for_attempt(&self, max_keys: usize) -> Vec<TakenKeyRun> {
        let inner = &self.inner;
        if self.candidates().is_empty() {
            let found: Vec<ParkedKey> = inner
                .shards
                .iter()
                .filter(|shard| shard.held.load(Ordering::Acquire) > 0)
                .flat_map(|shard| {
                    shard
                        .lock()
                        .keys_with_backlog()
                        .filter(|key| inner.partition_of(key) == self.partition)
                        .copied()
                        .collect::<Vec<_>>()
                })
                .collect();
            *self.candidates() = found;
        }
        let mut runs = Vec::new();
        while runs.len() < max_keys {
            let Some(key) = self.candidates().pop() else {
                break;
            };
            let mut queue = inner.shard_of(&key).lock();
            // Another session holds this key, or a count change moved it elsewhere.
            if queue.has_in_attempt(&key) || inner.partition_of(&key) != self.partition {
                continue;
            }
            let entries = queue.take_front(&key, usize::MAX);
            if !entries.is_empty() {
                runs.push(TakenKeyRun {
                    key: key.key,
                    entries,
                });
            }
        }
        runs
    }

    /// Record a definitive outcome for one in-attempt entry of `key`,
    /// releasing what admission charged it.
    pub fn complete(&self, key: StashKey, charge: Charge) {
        let key = ParkedKey::of(key);
        let shard = self.inner.shard_of(&key);
        shard.lock().complete(&key);
        self.inner.release(shard, charge);
    }

    /// Return in-attempt entries whose delivery was aborted before any
    /// outcome existed. They re-enter at their sequence positions and
    /// keep their admission charges; the next attempt sees them first,
    /// in order.
    pub fn put_back(&self, key: StashKey, entries: Vec<Entry<StashedRequest>>) {
        let key = ParkedKey::of(key);
        self.inner.shard_of(&key).lock().put_back(&key, entries);
    }

    /// Close the session if no key of the partition has parked or
    /// in-flight requests, ending the freeze this session opened on, and
    /// return `true`. Returns `false` while a key remains: an arrival
    /// raced the last take, or another session holds one of its keys.
    ///
    /// Every shard stays locked across the check and the close, so under a
    /// fixed count a request that parks for this partition lands before the
    /// check or sees the freeze gone and forwards. A request that hashed under
    /// a count adopted away mid-check can still park; the reconcile pass
    /// drains it on its next tick.
    pub fn finish_if_settled(&self) -> bool {
        let inner = &self.inner;
        // A key still held needs no global lock to see.
        if inner.holds_keys_of(self.partition) {
            return false;
        }
        // With no freeze to close, a request arriving after the check forwards either way.
        let Some(generation) = self.generation else {
            return true;
        };
        let shards: Vec<_> = inner.shards.iter().map(Shard::lock).collect();
        let pending = shards.iter().any(|queue| {
            queue
                .deferring_keys()
                .any(|key| inner.partition_of(key) == self.partition)
        });
        if pending {
            return false;
        }
        inner
            .stashing
            .remove_if(&self.partition, |_, opened| *opened == generation);
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use http::HeaderValue;
    use http_body_util::{BodyExt, Empty};
    use personhog_common::partitioning::partition_for_person;
    use personhog_coordination::types::ChangelogConfig;

    /// A table over `partitions` partitions; with one, every key maps to partition 0.
    fn table_over(partitions: u32, max_messages: usize, max_bytes: usize) -> StashTable {
        StashTable::with_bounds(
            max_messages,
            max_bytes,
            LiveChangelog::new(ChangelogConfig::new("personhog_updates", partitions)),
        )
    }

    /// Drain everything with a trivial always-succeeds forwarder,
    /// collecting the requests in delivery order. Mirrors the handler's
    /// session loop: take, complete each entry, settle when no backlog
    /// remains.
    fn drain_to_vec(table: &StashTable, partition: u32) -> Vec<StashedRequest> {
        let Some(session) = table.drain_session(partition) else {
            return Vec::new();
        };
        let mut out = Vec::new();
        loop {
            let taken = session.take_for_attempt(usize::MAX);
            if taken.is_empty() {
                if session.finish_if_settled() {
                    return out;
                }
                continue;
            }
            for run in taken {
                for entry in run.entries {
                    let charge = entry.item.charge();
                    out.push(entry.item);
                    session.complete(run.key, charge);
                }
            }
        }
    }

    fn enqueue_frame(table: &StashTable, person_id: i64, frame: Bytes) -> StashDecision {
        let partition = partition_for_person(1, person_id, table.inner.changelog.partitions());
        table.enqueue_or_forward(
            "UpdatePersonProperties",
            &frame,
            &HeaderMap::new(),
            (1, person_id),
            partition,
            false,
        )
    }

    /// Enqueue a minimal stashed write for `(team_id = 1, person_id)`.
    fn enqueue(table: &StashTable, person_id: i64) -> StashDecision {
        enqueue_frame(table, person_id, Bytes::from_static(b"x"))
    }

    /// Enqueue a stashed write whose frame is `payload` bytes, exercising
    /// the byte-based stash bound.
    fn enqueue_sized(table: &StashTable, person_id: i64, payload: usize) -> StashDecision {
        enqueue_frame(table, person_id, Bytes::from(vec![0u8; payload]))
    }

    /// A trivial gRPC response for exercising the reply channel.
    fn test_response() -> http::Response<BoxBody> {
        http::Response::new(BoxBody::new(
            Empty::<Bytes>::new().map_err(|never| match never {}),
        ))
    }

    /// A person whose partition differs between `from` and `to` partitions.
    fn moving_person(from: u32, to: u32) -> i64 {
        (1..)
            .find(|id| partition_for_person(1, *id, from) != partition_for_person(1, *id, to))
            .unwrap()
    }

    fn adopt(changelog: &LiveChangelog, partitions: u32) {
        changelog.adopt(&ChangelogConfig {
            epoch: changelog.epoch() + 1,
            ..ChangelogConfig::new("personhog_updates", partitions)
        });
    }

    #[test]
    fn forward_when_not_frozen() {
        let table = table_over(1, usize::MAX, usize::MAX);
        match enqueue(&table, 1) {
            StashDecision::Forward => {}
            _ => panic!("expected Forward"),
        }
    }

    #[test]
    fn begin_then_enqueue_then_drain_preserves_per_key_order() {
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);

        // Same key, distinguishable frames — ordering is a per-key
        // contract, so the assertion must not depend on cross-key
        // iteration order.
        let _rx1 = match enqueue_sized(&table, 1, 1) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let _rx2 = match enqueue_sized(&table, 1, 2) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let drained = drain_to_vec(&table, 0);
        assert_eq!(drained.len(), 2);
        let frame_lens: Vec<usize> = drained.iter().map(|s| s.frame.len()).collect();
        assert_eq!(frame_lens, vec![1, 2]);

        // After drain, new requests forward.
        match enqueue(&table, 3) {
            StashDecision::Forward => {}
            _ => panic!("expected Forward after drain"),
        }
    }

    /// A settled drain must end the freeze, or the partition never
    /// leaves the stash path.
    #[test]
    fn a_settled_drain_ends_the_freeze() {
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);
        assert!(table.is_pending(0), "begin_stash must open the freeze");
        drain_to_vec(&table, 0);
        assert!(!table.is_pending(0), "settle must end the freeze");
    }

    /// An aborted attempt puts its entries back and leaves the partition
    /// pending: whatever is parked belongs to the successor drain, and
    /// new requests must keep stashing in the meantime. Ending the freeze
    /// instead would let requests bypass the stash and race ahead of the
    /// parked backlog.
    #[test]
    fn put_back_leaves_queue_live_for_successor() {
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);
        let _rx = match enqueue(&table, 1) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        // An attempt starts, then aborts (pause/supersession/bounce) and
        // puts everything back without settling.
        let session = table.drain_session(0).expect("partition must be pending");
        let mut taken = session.take_for_attempt(usize::MAX);
        assert_eq!(taken.len(), 1);
        let run = taken.remove(0);
        session.put_back(run.key, run.entries);
        drop(session);
        assert!(
            table.is_pending(0),
            "aborted drain must leave the partition pending"
        );

        // Requests keep parking, and a successor drain collects everything.
        let _rx2 = match enqueue(&table, 2) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed while the partition is pending"),
        };
        let drained = drain_to_vec(&table, 0);
        assert_eq!(
            drained.len(),
            2,
            "successor drain must see the full backlog"
        );
    }

    /// In-attempt entries must block the settle: the queue can look empty
    /// (backlog fully taken) while outcomes are still outstanding, and
    /// settling then would let new requests overtake an attempt that may
    /// still be put back.
    #[test]
    fn in_attempt_entries_block_settle() {
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);
        let _rx = match enqueue(&table, 1) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let session = table.drain_session(0).expect("partition must be pending");
        let mut taken = session.take_for_attempt(usize::MAX);
        let run = taken.remove(0);
        assert!(
            !session.finish_if_settled(),
            "settle must refuse while an attempt is outstanding"
        );

        let entry = run.entries.into_iter().next().unwrap();
        session.complete(run.key, entry.item.charge());
        assert!(
            session.finish_if_settled(),
            "settle must succeed once every outcome is recorded"
        );
        assert!(!table.is_pending(0));
    }

    /// Back-to-back handoffs: drain → begin_stash for the same partition
    /// must stash again.
    #[test]
    fn drain_then_begin_stash_starts_fresh() {
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);
        let _rx = match enqueue(&table, 1) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let drained = drain_to_vec(&table, 0);
        assert_eq!(drained.len(), 1);

        table.begin_stash(0);
        match enqueue(&table, 2) {
            StashDecision::Stashed(_) => {}
            _ => panic!("expected Stashed for fresh handoff"),
        }
    }

    #[test]
    fn reject_when_message_count_exceeds_max() {
        let table = table_over(1, 2, usize::MAX);
        table.begin_stash(0);

        assert!(matches!(enqueue(&table, 1), StashDecision::Stashed(_)));
        assert!(matches!(enqueue(&table, 2), StashDecision::Stashed(_)));
        assert!(matches!(enqueue(&table, 3), StashDecision::Rejected));
    }

    #[test]
    fn reject_when_byte_total_exceeds_max() {
        // Cap at ~5KB; each request below has ~2KB payload. After two
        // requests we're near 4KB; a third request would push over the cap.
        let table = table_over(1, usize::MAX, 5 * 1024);
        table.begin_stash(0);

        assert!(matches!(
            enqueue_sized(&table, 1, 2 * 1024),
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            enqueue_sized(&table, 2, 2 * 1024),
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            enqueue_sized(&table, 3, 2 * 1024),
            StashDecision::Rejected
        ));
    }

    /// Either bound triggers rejection — whichever is hit first.
    #[test]
    fn message_count_takes_precedence_when_hit_first() {
        // Generous byte budget but tight message budget.
        let table = table_over(1, 1, 100 * 1024 * 1024);
        table.begin_stash(0);

        assert!(matches!(enqueue(&table, 1), StashDecision::Stashed(_)));
        // Second message rejected on count even though bytes are nowhere near.
        assert!(matches!(enqueue(&table, 2), StashDecision::Rejected));
    }

    /// The admission bounds must release on definitive outcomes, not on
    /// takes: an entry taken for an attempt still holds its memory, and
    /// releasing at take time would let a slow drain admit unbounded
    /// backlog behind it.
    #[test]
    fn bounds_release_on_complete_not_on_take() {
        let table = table_over(1, 1, usize::MAX);
        table.begin_stash(0);
        assert!(matches!(enqueue(&table, 1), StashDecision::Stashed(_)));

        let session = table.drain_session(0).expect("partition must be pending");
        let mut taken = session.take_for_attempt(usize::MAX);
        let run = taken.remove(0);
        // Taken but not completed — still counted against the bound.
        assert!(matches!(enqueue(&table, 2), StashDecision::Rejected));

        let entry = run.entries.into_iter().next().unwrap();
        session.complete(run.key, entry.item.charge());
        // Outcome recorded — capacity is released.
        assert!(matches!(enqueue(&table, 3), StashDecision::Stashed(_)));
    }

    #[test]
    fn partitions_are_independent() {
        let table = table_over(2, usize::MAX, usize::MAX);
        table.begin_stash(0);
        let on = |partition: u32| {
            (1..)
                .find(|id| partition_for_person(1, *id, 2) == partition)
                .unwrap()
        };

        // p0 stashes, p1 forwards
        assert!(matches!(enqueue(&table, on(0)), StashDecision::Stashed(_)));
        assert!(matches!(enqueue(&table, on(1)), StashDecision::Forward));
    }

    /// A drain under the old count settles its partition while a key that
    /// the new count moves there is still parked under its old partition.
    /// A later write for that key must queue behind it, not overtake it.
    #[test]
    fn a_key_keeps_its_order_across_a_count_change() {
        let changelog = LiveChangelog::new(ChangelogConfig::new("personhog_updates", 8));
        let table = StashTable::with_bounds(usize::MAX, usize::MAX, changelog.clone());
        let person_id = moving_person(8, 4);
        let old = partition_for_person(1, person_id, 8);
        let new = partition_for_person(1, person_id, 4);
        table.begin_stash(old);
        table.begin_stash(new);
        assert!(matches!(
            enqueue_frame(&table, person_id, Bytes::from_static(b"older")),
            StashDecision::Stashed(_)
        ));

        drain_to_vec(&table, new);
        adopt(&changelog, 4);

        assert!(matches!(
            enqueue_frame(&table, person_id, Bytes::from_static(b"newer")),
            StashDecision::Stashed(_)
        ));
        let frames: Vec<Bytes> = drain_to_vec(&table, new)
            .into_iter()
            .map(|r| r.frame)
            .collect();
        assert_eq!(
            frames,
            vec![Bytes::from_static(b"older"), Bytes::from_static(b"newer")]
        );
    }

    /// After a count change two partitions' drains can both reach one key.
    /// While one holds the key's head, the other must not take its tail.
    #[test]
    fn a_key_out_with_another_drain_is_skipped() {
        let changelog = LiveChangelog::new(ChangelogConfig::new("personhog_updates", 8));
        let table = StashTable::with_bounds(usize::MAX, usize::MAX, changelog.clone());
        let person_id = moving_person(8, 4);
        let old = partition_for_person(1, person_id, 8);
        let new = partition_for_person(1, person_id, 4);
        table.begin_stash(old);
        assert!(matches!(
            enqueue_frame(&table, person_id, Bytes::from_static(b"head")),
            StashDecision::Stashed(_)
        ));
        let holder = table.drain_session(old).unwrap();
        let mut head = holder.take_for_attempt(usize::MAX);
        assert!(matches!(
            enqueue_frame(&table, person_id, Bytes::from_static(b"tail")),
            StashDecision::Stashed(_)
        ));

        adopt(&changelog, 4);
        let other = table.drain_session(new).unwrap();
        assert!(other.take_for_attempt(usize::MAX).is_empty());
        assert!(!other.finish_if_settled());

        let run = head.remove(0);
        let entry = run.entries.into_iter().next().unwrap();
        holder.complete(run.key, entry.item.charge());
        let frames: Vec<Bytes> = drain_to_vec(&table, new)
            .into_iter()
            .map(|r| r.frame)
            .collect();
        assert_eq!(frames, vec![Bytes::from_static(b"tail")]);
    }

    /// A key out with another drain still needs its new partition's drain:
    /// if that attempt bounces and puts the key back, only that drain takes it.
    #[test]
    fn a_key_out_for_delivery_keeps_its_new_partition_pending() {
        let changelog = LiveChangelog::new(ChangelogConfig::new("personhog_updates", 8));
        let table = StashTable::with_bounds(usize::MAX, usize::MAX, changelog.clone());
        let person_id = moving_person(8, 4);
        let old = partition_for_person(1, person_id, 8);
        let new = partition_for_person(1, person_id, 4);
        table.begin_stash(old);
        assert!(matches!(
            enqueue(&table, person_id),
            StashDecision::Stashed(_)
        ));
        let holder = table.drain_session(old).unwrap();
        let _head = holder.take_for_attempt(usize::MAX);

        adopt(&changelog, 4);
        assert!(table.is_pending(new));
    }

    /// A freeze opened while a drain runs belongs to the next handoff;
    /// the running drain's settle must not end it.
    #[test]
    fn a_freeze_opened_during_a_drain_survives_its_settle() {
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);
        let session = table.drain_session(0).unwrap();
        table.begin_stash(0);
        assert!(session.finish_if_settled());
        assert!(matches!(enqueue(&table, 1), StashDecision::Stashed(_)));
    }

    /// Race between concurrent enqueues and a drain: every request must
    /// end up either in the drained batch or forwarded — never lost,
    /// never duplicated.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn enqueue_and_drain_race() {
        for iteration in 0..200 {
            let table = table_over(1, usize::MAX, usize::MAX);
            table.begin_stash(0);

            const ENQUEUERS: usize = 8;
            let mut handles = Vec::with_capacity(ENQUEUERS);
            for i in 0..ENQUEUERS {
                let table = table.clone();
                handles.push(tokio::spawn(async move { enqueue(&table, i as i64) }));
            }

            // Race the drain against the in-flight enqueues.
            let drain_table = table.clone();
            let drain_handle = tokio::spawn(async move { drain_to_vec(&drain_table, 0) });

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
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);

        let rx = match enqueue(&table, 1) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let mut drained = drain_to_vec(&table, 0);
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
    #[test]
    fn dropped_receiver_makes_send_fail() {
        let table = table_over(1, usize::MAX, usize::MAX);
        table.begin_stash(0);

        let rx = match enqueue(&table, 1) {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        drop(rx);

        let mut drained = drain_to_vec(&table, 0);
        let req = drained.remove(0);
        assert!(
            req.reply.send(test_response()).is_err(),
            "send must return Err after the receiver is dropped"
        );
    }
}
