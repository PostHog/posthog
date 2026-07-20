//! `EvictionQueue` driven against the real `BehavioralKey` over a simulated day of events, through the
//! crate's public sweep API (no Kafka, no clock — synthetic `now` stepped by hand).
//!
//! The deterministic oracle is the whole point: an independent `HashMap<BehavioralKey, deadline>` of each
//! key's *live* (post-reschedule) deadline. Stepping a fake `now` in 30 s increments and draining
//! `pop_due(now − margin)` each step, we assert every key evicts **exactly once**, at the **first**
//! step where `live_deadline + safety_margin < now`, never earlier, with the queue length equal to
//! the not-yet-evicted count throughout.

use std::collections::HashMap;

use cohort_stream_processor::stage1::key::LeafStateKey;
use cohort_stream_processor::store::BehavioralKey;
use cohort_stream_processor::sweep::{due_before_ms, EvictionQueue};
use uuid::Uuid;

const BASE_MS: i64 = 1_700_000_000_000; // an arbitrary "start of day" epoch-ms anchor
const DAY_MS: i64 = 86_400_000;
const STEP_MS: i64 = 30_000; // the 30 s sweep cadence
const MARGIN_MS: i64 = 300_000; // the 5 min safety margin

/// A distinct `BehavioralKey` per index. `person_id` alone guarantees distinctness; `team`, `partition`,
/// and `leaf_state_key` are varied too so the simulation looks like real `(team, leaf, person)` keys.
fn key(i: usize) -> BehavioralKey {
    BehavioralKey::new(
        (i % 64) as u16,
        (i % 5) as u64 + 1,
        Uuid::from_u128(0x00C0_FFEE_0000_0000_u128 + i as u128),
        LeafStateKey((i as u128).to_le_bytes()),
    )
}

#[test]
fn one_day_of_events_evicts_each_key_once_at_its_deadline() {
    const N: usize = 300;

    let mut queue: EvictionQueue<BehavioralKey> = EvictionQueue::new();
    // The independent oracle: each key's *final* deadline after all reschedules.
    let mut oracle: HashMap<BehavioralKey, i64> = HashMap::new();

    // Pass 1 — initial deadlines spread evenly across the 24 h window, all at least `MARGIN_MS` past
    // `BASE_MS` so nothing is due at the first step.
    for i in 0..N {
        let initial = BASE_MS + MARGIN_MS + (i as i64) * DAY_MS / (N as i64);
        queue.schedule(key(i), initial);
        oracle.insert(key(i), initial);
    }
    assert_eq!(queue.len(), N, "distinct keys, one slot each");

    // Pass 2 — reschedule two thirds of the keys, mixing both directions:
    //   - i % 3 == 1: later (the window slid forward as newer events arrived).
    //   - i % 3 == 2: earlier (a late event landed in an older bucket, pulling the deadline back —
    //     the case a lazily-deleted BinaryHeap would leave a stale far-future entry behind for).
    for i in 0..N {
        let current = oracle[&key(i)];
        let rescheduled = match i % 3 {
            1 => current + DAY_MS / (2 * N as i64),
            2 => current - DAY_MS / (2 * N as i64),
            _ => continue,
        };
        queue.schedule(key(i), rescheduled);
        oracle.insert(key(i), rescheduled);
    }
    assert_eq!(queue.len(), N, "reschedules supersede, never duplicate");

    // Precondition for the "first eligible step" assertion below: no key is due at the first step.
    let earliest_deadline = *oracle.values().min().expect("non-empty");
    assert!(
        earliest_deadline > due_before_ms(BASE_MS + STEP_MS, MARGIN_MS),
        "the simulation must start before any key is due",
    );

    // Step `now` forward in 30 s increments, draining everything due at each step.
    let mut evicted: HashMap<BehavioralKey, i64> = HashMap::new();
    let mut now = BASE_MS;
    let mut prev_due_before = i64::MIN; // the previous step's cutoff; -inf before the first step
    let mut steps = 0;

    while evicted.len() < N {
        now += STEP_MS;
        steps += 1;
        assert!(steps < 100_000, "simulation failed to converge");

        let cutoff = due_before_ms(now, MARGIN_MS);
        while let Some((evicted_key, deadline)) = queue.pop_due(cutoff) {
            let live = oracle[&evicted_key];
            assert_eq!(deadline, live, "a key evicts carrying its live deadline");
            assert!(
                deadline < cutoff,
                "no key evicts before due: deadline {deadline} >= cutoff {cutoff}",
            );
            assert!(
                deadline >= prev_due_before,
                "evicted at the FIRST eligible step (was not due one step earlier)",
            );
            assert!(
                evicted.insert(evicted_key, now).is_none(),
                "each key evicts exactly once",
            );
        }

        assert_eq!(
            queue.len(),
            N - evicted.len(),
            "queue length equals the not-yet-evicted count at every step",
        );
        prev_due_before = cutoff;
    }

    assert_eq!(evicted.len(), N, "every key evicted exactly once");
    assert!(queue.is_empty());
    assert_eq!(queue.peek_next_deadline(), None);

    // Every eviction lands within one sweep step after the ideal `deadline + margin` instant. The
    // window is half-open `(ideal, ideal + STEP]`: strict `<` in `pop_due` means a deadline+margin
    // exactly on a step boundary is held one more step, firing at `ideal + STEP`.
    for (k, &fired_at) in &evicted {
        let ideal = oracle[k] + MARGIN_MS;
        assert!(
            fired_at > ideal && fired_at <= ideal + STEP_MS,
            "key fired at {fired_at}, expected within ({ideal}, {}]",
            ideal + STEP_MS,
        );
    }
}

#[test]
fn cancelled_keys_never_evict() {
    let mut queue: EvictionQueue<BehavioralKey> = EvictionQueue::new();
    let deadline = BASE_MS + MARGIN_MS;
    for i in 0..10 {
        queue.schedule(key(i), deadline);
    }

    // Cancel the even-indexed keys (e.g. their external state was deleted) before the sweep runs.
    for i in (0..10).step_by(2) {
        queue.cancel(&key(i));
    }
    assert_eq!(queue.len(), 5);

    // Step well past the deadline + margin and drain.
    let cutoff = due_before_ms(deadline + MARGIN_MS + STEP_MS, MARGIN_MS);
    let mut evicted = Vec::new();
    while let Some((k, _)) = queue.pop_due(cutoff) {
        evicted.push(k);
    }

    assert_eq!(evicted.len(), 5, "only the non-cancelled keys evict");
    for i in (0..10).step_by(2) {
        assert!(
            !evicted.contains(&key(i)),
            "cancelled key {i} must never evict",
        );
    }
    for i in (1..10).step_by(2) {
        assert!(evicted.contains(&key(i)), "live key {i} must evict");
    }
    assert!(queue.is_empty());
}
