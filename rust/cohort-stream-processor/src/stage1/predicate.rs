//! The leaf membership predicate over [`Stage1State`], centralised so the worker's transition
//! detection, the sweep, and Stage 2 all read the same definition.

use crate::stage1::state::Stage1State;

/// Whether `state` currently satisfies its leaf predicate.
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
