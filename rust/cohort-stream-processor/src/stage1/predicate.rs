//! The leaf membership predicate over [`Stage1State`], centralised so the worker's transition
//! detection, the sweep, and Stage 2 all read the same definition.

use metrics::counter;

use crate::observability::metrics::STAGE1_STATE_DECODE_ERROR;
use crate::stage1::compressed_history::compressed_sum;
use crate::stage1::pick_state::PredicateOp;
use crate::stage1::state::Stage1State;

/// Whether `state` currently satisfies its leaf predicate, for the **op-less** variants
/// (`BehavioralSingle`, `PersonProperty`). The bucket variants carry a count comparator and must be
/// evaluated via [`daily_predicate`] / [`compressed_predicate`] with their leaf's [`PredicateOp`] —
/// every real caller already does (the worker's `mutate_behavioral_daily` and the sweep call those
/// directly). Reaching a bucket variant here is a dispatch desync: the `LeafStateKey` pins the
/// variant, so this can only happen on a coding error, and it is counted via
/// `STAGE1_STATE_DECODE_ERROR` and read as a non-member — loud, never a silently-dropped member.
pub fn predicate(state: &Stage1State) -> bool {
    match state {
        Stage1State::BehavioralSingle { has_match, .. } => *has_match,
        Stage1State::PersonProperty { matches, .. } => *matches,
        Stage1State::BehavioralDailyBuckets { .. }
        | Stage1State::BehavioralCompressedHistory { .. } => {
            counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
            false
        }
    }
}

/// Parity-critical membership floor: zero matching rows is never a member, even for `lte`/`lt`/`eq 0`.
/// Mirrors the existing pipeline's SQL, which only evaluates the comparator over persons with at least
/// one matching row (`hogql_cohort_query.py:1015`) — `count() >= 1 AND <op>`. Shared by
/// [`daily_predicate`] and [`compressed_predicate`] so the floor cannot drift between the two state
/// representations of one `performed_event_multiple` leaf.
fn count_is_member(count: u32, op: PredicateOp) -> bool {
    count >= 1 && op.evaluate(count)
}

/// Whether the window's matching-event count (the bucket sum) satisfies `op`.
pub fn daily_predicate(buckets: &[u32], op: PredicateOp) -> bool {
    let count: u32 = buckets.iter().copied().fold(0, u32::saturating_add);
    count_is_member(count, op)
}

/// Whether the compressed window's matching-event count (the sparse entries' count sum) satisfies
/// `op`. Identical to [`daily_predicate`] — including the shared [`count_is_member`] floor — only over
/// the sparse [`compressed_sum`] instead of a dense bucket array, so the two state representations of
/// one `performed_event_multiple` leaf evaluate membership the same way.
pub fn compressed_predicate(entries: &[(i32, u32)], op: PredicateOp) -> bool {
    let count = compressed_sum(entries);
    count_is_member(count, op)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn behavioral_single_predicate_is_has_match() {
        let matched = Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        let unmatched = Stage1State::BehavioralSingle {
            has_match: false,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(predicate(&matched));
        assert!(!predicate(&unmatched));
    }

    #[test]
    fn person_property_predicate_is_matches() {
        let matched = Stage1State::PersonProperty {
            matches: true,
            last_updated_at_ms: 1,
            last_updated_offset: 2,
        };
        let unmatched = Stage1State::PersonProperty {
            matches: false,
            last_updated_at_ms: 1,
            last_updated_offset: 2,
        };
        assert!(predicate(&matched));
        assert!(!predicate(&unmatched));
    }

    #[test]
    fn daily_predicate_applies_the_comparator_to_the_bucket_sum() {
        let buckets = [0, 1, 0, 2, 1]; // sum 4
        assert!(daily_predicate(&buckets, PredicateOp::Gte(3)));
        assert!(!daily_predicate(&buckets, PredicateOp::Gte(5)));
        assert!(daily_predicate(&buckets, PredicateOp::Lte(4)));
        assert!(!daily_predicate(&buckets, PredicateOp::Lt(4)));
        assert!(daily_predicate(&buckets, PredicateOp::Eq(4)));
    }

    #[test]
    fn daily_predicate_count_zero_is_never_a_member() {
        let empty = [0, 0, 0];
        assert!(
            !daily_predicate(&empty, PredicateOp::Lte(5)),
            "lte 5 over count 0"
        );
        assert!(
            !daily_predicate(&empty, PredicateOp::Lt(5)),
            "lt 5 over count 0"
        );
        assert!(
            !daily_predicate(&empty, PredicateOp::Eq(0)),
            "eq 0 over count 0"
        );
        assert!(
            !daily_predicate(&empty, PredicateOp::Gte(1)),
            "gte 1 over count 0"
        );
    }

    #[test]
    fn daily_predicate_count_one_floor_holds_for_lte_and_eq() {
        let one = [1, 0];
        assert!(
            daily_predicate(&one, PredicateOp::Lte(5)),
            "count 1 ∈ [1, 5]"
        );
        assert!(daily_predicate(&one, PredicateOp::Eq(1)));
        assert!(
            !daily_predicate(&one, PredicateOp::Eq(0)),
            "count 1 is never eq 0"
        );
    }

    #[test]
    fn bucket_variants_through_op_less_predicate_read_as_non_member() {
        // Buckets must be evaluated via daily_predicate/compressed_predicate with their op; reaching
        // the op-less `predicate` is a dispatch desync. Both states below WOULD be members under
        // Gte(3) (sum 3), so this proves the desync reads as a non-member rather than silently a
        // member. The op-carrying dispatch is covered by daily_predicate_/compressed_predicate_ above.
        let daily = Stage1State::BehavioralDailyBuckets {
            buckets: vec![1, 2, 0],
            window_start_day: 20_600,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(!predicate(&daily));
        let compressed = Stage1State::BehavioralCompressedHistory {
            entries: vec![(20_240, 1), (20_400, 2)],
            window_start_day: 20_240,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(!predicate(&compressed));
    }

    #[test]
    fn compressed_predicate_applies_the_comparator_to_the_entry_sum() {
        let entries = [(100, 1), (200, 2), (300, 1)]; // sum 4
        assert!(compressed_predicate(&entries, PredicateOp::Gte(3)));
        assert!(!compressed_predicate(&entries, PredicateOp::Gte(5)));
        assert!(compressed_predicate(&entries, PredicateOp::Lte(4)));
        assert!(!compressed_predicate(&entries, PredicateOp::Lt(4)));
        assert!(compressed_predicate(&entries, PredicateOp::Eq(4)));
    }

    #[test]
    fn compressed_predicate_count_zero_floor_matches_daily() {
        // An empty entry set is count 0 → never a member, even for lte/lt/eq 0 (the count >= 1 floor).
        let empty: [(i32, u32); 0] = [];
        assert!(!compressed_predicate(&empty, PredicateOp::Lte(5)));
        assert!(!compressed_predicate(&empty, PredicateOp::Lt(5)));
        assert!(!compressed_predicate(&empty, PredicateOp::Eq(0)));
        assert!(!compressed_predicate(&empty, PredicateOp::Gte(1)));
        // And a single match (count 1) satisfies lte/eq 1 just as daily does.
        let one = [(100, 1)];
        assert!(compressed_predicate(&one, PredicateOp::Lte(5)));
        assert!(compressed_predicate(&one, PredicateOp::Eq(1)));
        assert!(!compressed_predicate(&one, PredicateOp::Eq(0)));
    }
}
