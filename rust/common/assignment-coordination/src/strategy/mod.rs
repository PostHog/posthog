mod sticky_balanced;

pub use sticky_balanced::StickyBalancedStrategy;

use std::collections::HashMap;

/// How a strategy may place partitions on a member.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlacementPolicy {
    /// Keeps existing assignments and receives new placements. When `cap`
    /// is set, the member's total partition count is bounded by it: during
    /// a Deployment rollout each new-generation pod is capped at its final
    /// share, so the first pod of the new generation is never handed the
    /// whole partition space.
    Active { cap: Option<u32> },
    /// Keeps existing assignments but receives new placements only when no
    /// capped active member has room, and sheds partitions to capped
    /// active members below their cap. Old-generation Ready pods hold
    /// during a Deployment rollout: they are alive and serving, but every
    /// partition they can shed belongs on the incoming generation.
    Hold,
}

/// A member eligible to own partitions, tagged with the placement policy
/// the caller derived for it (e.g. from K8s rollout state).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Member {
    pub name: String,
    pub policy: PlacementPolicy,
}

impl Member {
    pub fn active(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            policy: PlacementPolicy::Active { cap: None },
        }
    }

    pub fn active_capped(name: impl Into<String>, cap: u32) -> Self {
        Self {
            name: name.into(),
            policy: PlacementPolicy::Active { cap: Some(cap) },
        }
    }

    pub fn hold(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            policy: PlacementPolicy::Hold,
        }
    }

    /// Wrap plain member names as uncapped active members — the shape for
    /// callers with no rollout signal, which is the pre-policy behavior.
    pub fn active_all<S: AsRef<str>>(names: &[S]) -> Vec<Member> {
        names.iter().map(|n| Member::active(n.as_ref())).collect()
    }
}

/// Trait for partition assignment strategies.
///
/// The coordinator calls `compute_assignments` whenever the set of active
/// members changes. Implementations decide how to map partitions to members.
/// The coordinator then diffs the result against current assignments to
/// determine which partitions need handoffs.
pub trait AssignmentStrategy: Send + Sync {
    /// Compute the desired partition-to-member mapping.
    ///
    /// - `current`: existing partition -> member_name mapping (empty on first run)
    /// - `members`: members eligible for assignment, with placement policies
    /// - `num_partitions`: total number of partitions to distribute
    fn compute_assignments(
        &self,
        current: &HashMap<u32, String>,
        members: &[Member],
        num_partitions: u32,
    ) -> HashMap<u32, String>;
}
