//! Pure cascade decision logic: no Kafka, no storage, no metrics, no clock — every function takes
//! data and returns data. The caller performs the produce and supplies `new_last_updated`.

use crate::cascade::message::{CascadeDecision, CascadeMessage, DropReason};
use crate::filters::CohortId;
use crate::producer::{CohortMembershipChange, MembershipStatus};

/// Decide whether `next` — which just flipped to `new_status` at `new_last_updated` — cascades onward.
///
/// Depth is checked before the chain, so a message at the cap drops as `DepthExceeded` even when
/// `next` is also already in the chain.
pub fn should_emit(
    incoming: &CascadeMessage,
    next: CohortId,
    new_status: MembershipStatus,
    new_last_updated: &str,
    depth_cap: u8,
) -> CascadeDecision {
    if incoming.depth >= depth_cap {
        return CascadeDecision::Drop {
            reason: DropReason::DepthExceeded,
        };
    }
    if incoming.cascade_chain.contains(&next.0) {
        return CascadeDecision::Drop {
            reason: DropReason::CycleDetectedRuntime,
        };
    }

    let mut cascade_chain = incoming.cascade_chain.clone();
    cascade_chain.push(next.0);
    CascadeDecision::Emit {
        outgoing: CascadeMessage {
            change: CohortMembershipChange {
                team_id: incoming.change.team_id,
                cohort_id: next.0,
                person_id: incoming.change.person_id.clone(),
                last_updated: new_last_updated.to_string(),
                status: new_status,
            },
            // Carried forward so the chain keeps one stable replay identity across hops.
            source_offset: incoming.source_offset,
            // depth < depth_cap <= u8::MAX after the guard above, so this cannot overflow.
            depth: incoming.depth + 1,
            originating_cohort_id: incoming.originating_cohort_id,
            cascade_chain,
        },
    }
}

/// Build the first cascade in a chain from a just-emitted membership change: `depth = 1`, with the
/// flipped cohort as both `originating_cohort_id` and the sole `cascade_chain` entry.
pub fn first_cascade(change: CohortMembershipChange, source_offset: i64) -> CascadeMessage {
    let originating_cohort_id = change.cohort_id;
    CascadeMessage {
        change,
        source_offset,
        depth: 1,
        originating_cohort_id,
        cascade_chain: vec![originating_cohort_id],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TS_IN: &str = "2026-05-26 12:34:56.789123";
    const TS_OUT: &str = "2026-06-16 00:00:00.000000";

    fn change(cohort_id: i32, status: MembershipStatus) -> CohortMembershipChange {
        CohortMembershipChange {
            team_id: 42,
            cohort_id,
            person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
            last_updated: TS_IN.to_string(),
            status,
        }
    }

    /// An incoming cascade message at `depth` with the given `chain`.
    fn incoming(cohort_id: i32, depth: u8, chain: Vec<i32>) -> CascadeMessage {
        CascadeMessage {
            change: change(cohort_id, MembershipStatus::Entered),
            source_offset: 777,
            depth,
            originating_cohort_id: chain.first().copied().unwrap_or(cohort_id),
            cascade_chain: chain,
        }
    }

    #[test]
    fn normal_hop_increments_depth_and_extends_the_chain_carrying_fields() {
        let incoming = incoming(10, 1, vec![10]);
        let decision = should_emit(&incoming, CohortId(20), MembershipStatus::Left, TS_OUT, 8);

        let CascadeDecision::Emit { outgoing } = decision else {
            panic!("expected Emit, got {decision:?}");
        };
        assert_eq!(outgoing.depth, 2, "depth 1 → 2");
        assert_eq!(
            outgoing.cascade_chain,
            vec![10, 20],
            "chain [10] → [10, 20]"
        );
        // `change` is rebuilt for `next`.
        assert_eq!(outgoing.change.cohort_id, 20);
        assert_eq!(outgoing.change.status, MembershipStatus::Left);
        assert_eq!(outgoing.change.last_updated, TS_OUT);
        // team / person / source_offset / originating carry from `incoming`.
        assert_eq!(outgoing.change.team_id, incoming.change.team_id);
        assert_eq!(outgoing.change.person_id, incoming.change.person_id);
        assert_eq!(outgoing.source_offset, incoming.source_offset);
        assert_eq!(outgoing.originating_cohort_id, 10);
    }

    #[test]
    fn depth_one_below_the_cap_still_emits() {
        let incoming = incoming(10, 7, vec![1, 2, 3, 4, 5, 6, 7]);
        let decision = should_emit(
            &incoming,
            CohortId(99),
            MembershipStatus::Entered,
            TS_OUT,
            8,
        );
        let CascadeDecision::Emit { outgoing } = decision else {
            panic!("expected Emit at depth 7, got {decision:?}");
        };
        assert_eq!(outgoing.depth, 8);
        assert_eq!(outgoing.cascade_chain.len(), 8);
    }

    #[test]
    fn depth_at_the_cap_drops_depth_exceeded() {
        let incoming = incoming(10, 8, vec![1, 2, 3, 4, 5, 6, 7, 8]);
        let decision = should_emit(
            &incoming,
            CohortId(99),
            MembershipStatus::Entered,
            TS_OUT,
            8,
        );
        assert_eq!(
            decision,
            CascadeDecision::Drop {
                reason: DropReason::DepthExceeded,
            },
        );
    }

    #[test]
    fn next_already_in_chain_drops_cycle_detected_under_the_cap() {
        let incoming = incoming(10, 2, vec![10, 20]);
        let decision = should_emit(
            &incoming,
            CohortId(20),
            MembershipStatus::Entered,
            TS_OUT,
            8,
        );
        assert_eq!(
            decision,
            CascadeDecision::Drop {
                reason: DropReason::CycleDetectedRuntime,
            },
        );
    }

    #[test]
    fn depth_is_checked_before_the_chain_when_both_would_fire() {
        // At the cap and `next` already in the chain: depth wins.
        let incoming = incoming(10, 8, vec![10, 20]);
        let decision = should_emit(
            &incoming,
            CohortId(20),
            MembershipStatus::Entered,
            TS_OUT,
            8,
        );
        assert_eq!(
            decision,
            CascadeDecision::Drop {
                reason: DropReason::DepthExceeded,
            },
        );
    }

    #[test]
    fn first_cascade_seeds_depth_one_and_a_singleton_chain() {
        let cascade = first_cascade(change(91204, MembershipStatus::Entered), 555);
        assert_eq!(cascade.depth, 1);
        assert_eq!(cascade.cascade_chain, vec![91204]);
        assert_eq!(cascade.originating_cohort_id, 91204);
        assert_eq!(cascade.source_offset, 555);
        assert_eq!(cascade.change.cohort_id, 91204);
        assert_eq!(cascade.change.status, MembershipStatus::Entered);
    }

    #[test]
    fn first_cascade_then_one_hop_yields_depth_two_chain_of_two() {
        let first = first_cascade(change(10, MembershipStatus::Entered), 1);
        let decision = should_emit(&first, CohortId(20), MembershipStatus::Entered, TS_OUT, 8);
        let CascadeDecision::Emit { outgoing } = decision else {
            panic!("expected Emit, got {decision:?}");
        };
        assert_eq!(outgoing.depth, 2);
        assert_eq!(outgoing.cascade_chain, vec![10, 20]);
        assert_eq!(outgoing.originating_cohort_id, 10);
    }
}
