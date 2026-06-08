//! The leaf membership predicate over [`Stage1State`], centralised so the worker's transition
//! detection, the sweep, and Stage 2 all read the same definition.

use crate::stage1::pick_state::PredicateOp;
use crate::stage1::state::Stage1State;

/// Whether `state` currently satisfies its leaf predicate. `op` is the bucket variants' count
/// comparator (from the leaf's [`LeafStateMeta`](crate::filters::reverse_index::LeafStateMeta)); it
/// is `None` for the op-less variants. A bucket state with `op == None` is a meta desync and reads as
/// a non-member rather than panicking.
pub fn predicate(state: &Stage1State, op: Option<PredicateOp>) -> bool {
    match state {
        Stage1State::BehavioralSingle { has_match, .. } => *has_match,
        Stage1State::PersonProperty { matches, .. } => *matches,
        Stage1State::BehavioralDailyBuckets { buckets, .. } => {
            op.is_some_and(|op| daily_predicate(buckets, op))
        }
    }
}

/// Whether the window's matching-event count (the bucket sum) satisfies `op`. The `count >= 1` guard
/// mirrors the existing pipeline's SQL, which only evaluates the comparator over persons with at
/// least one matching row (`hogql_cohort_query.py:1015`) — so `count == 0` is never a member.
pub fn daily_predicate(buckets: &[u32], op: PredicateOp) -> bool {
    let count: u32 = buckets.iter().copied().fold(0, u32::saturating_add);
    count >= 1 && op.evaluate(count)
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
        assert!(predicate(&matched, None));
        assert!(!predicate(&unmatched, None));
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
        assert!(predicate(&matched, None));
        assert!(!predicate(&unmatched, None));
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
    fn predicate_dispatches_bucket_variant_through_the_op() {
        let state = Stage1State::BehavioralDailyBuckets {
            buckets: vec![1, 2, 0],
            window_start_day: 20_600,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(predicate(&state, Some(PredicateOp::Gte(3))), "sum 3 ≥ 3");
        assert!(!predicate(&state, Some(PredicateOp::Gte(4))));
        assert!(!predicate(&state, None), "missing op reads as a non-member");
    }
}
