//! The leaf membership predicate over [`Stage1State`], centralised so the worker's transition
//! detection, the sweep, and Stage 2 all read the same definition.

use crate::stage1::pick_state::PredicateOp;
use crate::stage1::state::Stage1State;

/// Whether `state` currently satisfies its leaf predicate.
///
/// `op` is the count comparator the bucket variants need; it lives on the leaf's
/// [`LeafStateMeta`](crate::filters::reverse_index::LeafStateMeta) (never in the state, so the
/// threshold has one source of truth), and every caller has that meta in hand. It is ignored for the
/// op-less variants ([`BehavioralSingle`](Stage1State::BehavioralSingle) /
/// [`PersonProperty`](Stage1State::PersonProperty)) and **must** be `Some` for a bucket variant.
/// A bucket state reached with `op == None` is a catalog/meta desync — it returns `false` rather
/// than panicking, but that path is structurally unreachable in correct operation.
pub fn predicate(state: &Stage1State, op: Option<PredicateOp>) -> bool {
    match state {
        Stage1State::BehavioralSingle { has_match, .. } => *has_match,
        Stage1State::PersonProperty { matches, .. } => *matches,
        Stage1State::BehavioralDailyBuckets { buckets, .. } => {
            op.is_some_and(|op| daily_predicate(buckets, op))
        }
    }
}

/// Whether a daily-bucket window's matching-event `count` (the bucket sum) satisfies `op`.
///
/// The `count >= 1 &&` guard is the **parity rule**: the existing pipeline's SQL only evaluates the
/// comparator over persons with at least one matching `precalculated_events` row
/// (`hogql_cohort_query.py:1015`), so a person with `count == 0` is never a member regardless of the
/// operator. That makes `lte 5` mean `count ∈ [1, 5]`, `eq 0` always false, and `gte 3` unchanged;
/// it also turns a window slide that drains every contributing bucket into a clean `Left`.
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
        // buckets sum to 4.
        let buckets = [0, 1, 0, 2, 1];
        assert!(daily_predicate(&buckets, PredicateOp::Gte(3)));
        assert!(!daily_predicate(&buckets, PredicateOp::Gte(5)));
        assert!(daily_predicate(&buckets, PredicateOp::Lte(4)));
        assert!(!daily_predicate(&buckets, PredicateOp::Lt(4)));
        assert!(daily_predicate(&buckets, PredicateOp::Eq(4)));
    }

    #[test]
    fn daily_predicate_count_zero_is_never_a_member() {
        // The parity guard: with no contributing rows the existing SQL evaluates the comparator over
        // nobody, so even comparators a literal 0 would satisfy (`lte`, `lt`, `eq 0`) are false.
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
        // A missing op is a meta desync, defended as a non-match (not a panic).
        assert!(!predicate(&state, None));
    }
}
