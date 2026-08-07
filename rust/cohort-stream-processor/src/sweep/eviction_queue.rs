//! [`EvictionQueue`]: the deadline-ordered queue the sweep drains soonest-first.
//!
//! A worker schedules each live behavioral key; the sweep drains keys whose deadline has passed.
//! The timer is in [`super::scheduler`].
//!
//! # Why a `BTreeMap` + reverse index, not `BinaryHeap` + epoch map
//!
//! A key's deadline can move *earlier*, not just later: `daily_eviction_deadline`
//! (`stage1/daily.rs`) returns the boundary of the **oldest non-zero bucket**, so a late event
//! landing in a bucket older than the current oldest pulls the deadline backward. With a
//! lazily-deleted heap, an earlier-reschedule leaves the superseded, far-future entry in the heap
//! until its stale deadline eventually surfaces — up to the window length (≤180 days). Those
//! accumulate and `heap.len()` grows with total reschedules while the live-key count stays flat: an
//! unbounded leak unless you add compaction, and the natural compaction (store the live coordinate
//! so you can find and remove the old one) *is* this shape.
//!
//! A `BTreeMap<(deadline_ms, seq), K>` keyed by `(deadline, seq)` is ordered, so the soonest-due key
//! is `first_key_value`; a `HashMap<K, (deadline_ms, seq)>` reverse index lets a reschedule remove
//! the superseded entry **precisely** in `O(log n)`, in either direction. `len()` therefore always
//! equals the live-key count, and the staleness problem class disappears. `K` needs no `Ord` (it is
//! the map *value*); `seq` is a global monotonic tiebreaker that only disambiguates two live keys
//! sharing a deadline, giving a deterministic pop order.

use std::collections::{BTreeMap, HashMap};
use std::hash::Hash;

/// The ordered coordinate of a live entry: its deadline (epoch ms) plus a monotonic tiebreaker.
/// `Copy`, so it is cheaply read out of `by_deadline` before a mutating call.
type Coord = (i64, u64);

/// A deadline-ordered queue of keys, drained soonest-first by [`pop_due`](Self::pop_due).
///
/// Single-threaded by design: each partition worker owns one `EvictionQueue<BehavioralKey>` and is
/// the only mutator, so no internal synchronization is needed. Generic over `K` purely so the
/// structure can be unit-tested in isolation from `BehavioralKey`.
///
/// Invariant, upheld by every method: `by_deadline` and `index` hold exactly the same set of keys,
/// so `by_deadline.len() == index.len() == ` the live-key count, and each key maps to exactly one
/// coordinate in both directions.
pub struct EvictionQueue<K> {
    /// Keys ordered by `(deadline_ms, seq)`, so `first_key_value` is always the soonest due. `seq`
    /// only breaks ties between equal deadlines.
    by_deadline: BTreeMap<Coord, K>,
    /// Reverse index `K → its live coordinate`, so a reschedule (or [`cancel`](Self::cancel)) removes
    /// the superseded `by_deadline` entry precisely in `O(log n)` instead of leaving it to surface
    /// stale later.
    index: HashMap<K, Coord>,
    /// Global monotonic tiebreaker handed to each scheduled entry. `u64` never realistically wraps:
    /// even at a billion schedules a second it lasts ~580 years.
    next_seq: u64,
}

impl<K> EvictionQueue<K>
where
    K: Hash + Eq + Clone,
{
    pub fn new() -> Self {
        Self {
            by_deadline: BTreeMap::new(),
            index: HashMap::new(),
            next_seq: 0,
        }
    }

    /// Schedule `key` to evict at `deadline_ms`, or reschedule it if already present. A reschedule
    /// removes the previous entry first (precise supersede), so the queue holds exactly one
    /// coordinate per key whether the new deadline is later **or earlier** — and `len()` never grows
    /// with reschedules.
    pub fn schedule(&mut self, key: K, deadline_ms: i64) {
        if let Some(&old_coord) = self.index.get(&key) {
            self.by_deadline.remove(&old_coord);
        }
        let coord = (deadline_ms, self.next_seq);
        self.next_seq += 1;
        self.by_deadline.insert(coord, key.clone());
        self.index.insert(key, coord);
    }

    /// Pop the soonest-due key whose deadline is **strictly before** `due_before_ms`, returning
    /// `(key, deadline_ms)`; or [`None`] when the soonest live deadline is `>= due_before_ms` (i.e.
    /// nothing is due yet). Drain a tick by calling this in a loop until it returns [`None`].
    ///
    /// The cutoff is `due_before_ms = now_ms − safety_margin_ms`, computed by the caller (see
    /// [`due_before_ms`](super::scheduler::due_before_ms)) so the queue stays clock- and
    /// arithmetic-free.
    pub fn pop_due(&mut self, due_before_ms: i64) -> Option<(K, i64)> {
        // Copy the soonest coordinate out, dropping the immutable borrow before the mutating remove.
        let (&coord, _) = self.by_deadline.first_key_value()?;
        let (deadline_ms, _) = coord;
        if deadline_ms >= due_before_ms {
            return None;
        }
        let key = self
            .by_deadline
            .remove(&coord)
            .expect("the peeked coordinate is present");
        self.index.remove(&key);
        Some((key, deadline_ms))
    }

    /// Remove `key` from the queue, if present, so its pending eviction never fires.
    pub fn cancel(&mut self, key: &K) {
        if let Some(coord) = self.index.remove(key) {
            self.by_deadline.remove(&coord);
        }
    }

    /// The soonest live deadline, or [`None`] when empty. For observability.
    pub fn peek_next_deadline(&self) -> Option<i64> {
        self.by_deadline
            .keys()
            .next()
            .map(|&(deadline, _)| deadline)
    }

    /// The number of live keys.
    pub fn len(&self) -> usize {
        self.by_deadline.len()
    }

    pub fn is_empty(&self) -> bool {
        self.by_deadline.is_empty()
    }
}

impl<K> Default for EvictionQueue<K>
where
    K: Hash + Eq + Clone,
{
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn drain<K: Hash + Eq + Clone>(
        queue: &mut EvictionQueue<K>,
        due_before_ms: i64,
    ) -> Vec<(K, i64)> {
        let mut out = Vec::new();
        while let Some(entry) = queue.pop_due(due_before_ms) {
            out.push(entry);
        }
        out
    }

    #[test]
    fn pop_due_boundary_triple() {
        // Strict `<`: at the exact cutoff and beyond, the key is held; one ms before, it is due.
        let due_before = 1_000;
        for (deadline, should_evict) in [
            (due_before - 1, true),
            (due_before, false),
            (due_before + 1, false),
        ] {
            let mut queue = EvictionQueue::new();
            queue.schedule("k", deadline);
            let popped = queue.pop_due(due_before);
            assert_eq!(
                popped.is_some(),
                should_evict,
                "deadline {deadline} vs due_before {due_before}",
            );
            assert_eq!(queue.len(), if should_evict { 0 } else { 1 });
        }
    }

    #[test]
    fn reschedule_to_later_pops_once_at_the_later_deadline() {
        let mut queue = EvictionQueue::new();
        queue.schedule("k", 100);
        queue.schedule("k", 500); // window slid forward
        assert_eq!(queue.len(), 1, "reschedule must not duplicate the key");

        // Nothing due at the original deadline anymore.
        assert_eq!(queue.pop_due(101), None);
        assert_eq!(queue.len(), 1);

        assert_eq!(queue.pop_due(501), Some(("k", 500)));
        assert_eq!(queue.len(), 0);
        assert_eq!(queue.pop_due(501), None);
    }

    #[test]
    fn reschedule_to_earlier_leaves_no_stale_entry() {
        // The regression that motivates the BTreeMap: an earlier reschedule must remove the old
        // far-future entry, so the key pops once at the earlier deadline and `len()` returns to 0.
        let mut queue = EvictionQueue::new();
        queue.schedule("k", 10_000); // far-future
        queue.schedule("k", 200); // late event in an older bucket pulls it earlier
        assert_eq!(queue.len(), 1);

        assert_eq!(queue.pop_due(201), Some(("k", 200)));
        assert_eq!(
            queue.len(),
            0,
            "the superseded far-future entry must not linger",
        );
        // Draining far past the old far-future deadline yields nothing — proof it is gone.
        assert_eq!(queue.pop_due(1_000_000), None);
        assert_eq!(queue.peek_next_deadline(), None);
    }

    #[test]
    fn cancel_removes_the_key_so_it_never_pops() {
        let mut queue = EvictionQueue::new();
        queue.schedule("k", 100);
        queue.cancel(&"k");
        assert_eq!(queue.len(), 0);
        assert!(queue.is_empty());
        assert_eq!(queue.pop_due(1_000_000), None);

        // Cancelling an absent key is a no-op.
        queue.cancel(&"missing");
        assert_eq!(queue.len(), 0);
    }

    #[test]
    fn cancel_only_removes_the_named_key() {
        let mut queue = EvictionQueue::new();
        queue.schedule("a", 100);
        queue.schedule("b", 200);
        queue.cancel(&"a");
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.pop_due(1_000), Some(("b", 200)));
    }

    #[test]
    fn resurrection_after_pop_pops_again_at_the_new_deadline() {
        let mut queue = EvictionQueue::new();
        queue.schedule("k", 100);
        assert_eq!(queue.pop_due(101), Some(("k", 100)));
        assert_eq!(queue.len(), 0);

        queue.schedule("k", 900);
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.pop_due(200), None, "not due at the old deadline");
        assert_eq!(queue.pop_due(901), Some(("k", 900)));
        assert_eq!(queue.len(), 0);
    }

    #[test]
    fn equal_deadlines_pop_in_insertion_order() {
        // `seq` makes a shared deadline deterministic: FIFO by schedule order.
        let mut queue = EvictionQueue::new();
        for key in ["a", "b", "c", "d"] {
            queue.schedule(key, 500);
        }
        let drained = drain(&mut queue, 501);
        assert_eq!(
            drained,
            vec![("a", 500), ("b", 500), ("c", 500), ("d", 500)],
        );
        assert_eq!(queue.len(), 0);
    }

    #[test]
    fn pop_due_drains_in_deadline_then_seq_order() {
        let mut queue = EvictionQueue::new();
        // Insert out of deadline order, with a tie at 200.
        queue.schedule("late", 300);
        queue.schedule("tie_first", 200);
        queue.schedule("early", 100);
        queue.schedule("tie_second", 200);

        let drained = drain(&mut queue, 1_000);
        assert_eq!(
            drained,
            vec![
                ("early", 100),
                ("tie_first", 200),
                ("tie_second", 200),
                ("late", 300),
            ],
        );
    }

    #[test]
    fn peek_next_deadline_tracks_the_soonest_live_deadline() {
        let mut queue = EvictionQueue::new();
        assert_eq!(queue.peek_next_deadline(), None);

        queue.schedule("a", 500);
        assert_eq!(queue.peek_next_deadline(), Some(500));

        queue.schedule("b", 200);
        assert_eq!(queue.peek_next_deadline(), Some(200));

        queue.schedule("b", 900);
        assert_eq!(queue.peek_next_deadline(), Some(500));

        queue.cancel(&"a");
        assert_eq!(queue.peek_next_deadline(), Some(900));

        assert_eq!(queue.pop_due(1_000), Some(("b", 900)));
        assert_eq!(queue.peek_next_deadline(), None);
    }

    #[test]
    fn very_negative_due_before_holds_everything_without_panic() {
        // The caller's saturating `now − margin` (now small, margin huge) yields a far-negative
        // cutoff. `pop_due` is pure arithmetic-free comparison, so it holds every real (positive)
        // deadline — the safe "nothing due" direction — and never panics. See
        // `scheduler::tests::due_before_saturates_when_margin_exceeds_now`.
        let mut queue = EvictionQueue::new();
        queue.schedule("k", 1);
        let cutoff = 0_i64.saturating_sub(i64::MAX);
        assert_eq!(queue.pop_due(cutoff), None);
        assert_eq!(queue.pop_due(i64::MIN), None);
        assert_eq!(queue.len(), 1);
    }

    #[test]
    fn partial_drain_leaves_not_yet_due_keys() {
        let mut queue = EvictionQueue::new();
        queue.schedule("a", 100);
        queue.schedule("b", 200);
        queue.schedule("c", 300);

        let drained = drain(&mut queue, 250);
        assert_eq!(drained, vec![("a", 100), ("b", 200)]);
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.peek_next_deadline(), Some(300));
    }

    #[test]
    fn default_is_empty() {
        let queue: EvictionQueue<&str> = EvictionQueue::default();
        assert!(queue.is_empty());
        assert_eq!(queue.len(), 0);
        assert_eq!(queue.peek_next_deadline(), None);
    }
}
