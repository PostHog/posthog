//! The leaf membership predicate over [`Stage1State`] (TDD §4.1).
//!
//! "Is this person currently in this leaf's set?" is a pure function of the stored state. PR 1.6
//! covers the two M1 variants; the count-comparator (`gte`/`lte`/… over bucket sums) for
//! `performed_event_multiple` is PR 2.1. Centralising it here keeps the worker's transition
//! detection ("did the predicate flip?") reading the *same* definition the sweep and Stage 2 will.

use crate::stage1::state::Stage1State;

/// Whether `state` currently satisfies its leaf predicate.
///
/// - [`Stage1State::BehavioralSingle`] → `has_match` (any matching event in the live window).
/// - [`Stage1State::PersonProperty`] → `matches` (the last-write-wins boolean).
pub fn predicate(state: &Stage1State) -> bool {
    match state {
        Stage1State::BehavioralSingle { has_match, .. } => *has_match,
        Stage1State::PersonProperty { matches, .. } => *matches,
    }
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
}
