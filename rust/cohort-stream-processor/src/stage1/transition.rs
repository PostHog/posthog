//! Stage 1 leaf transitions (TDD §4.1).
//!
//! When a leaf's [`predicate`](crate::stage1::predicate::predicate) flips, the worker emits a
//! [`LeafTransition`] *after* the backing state is durably committed (the plan's "no transition
//! without durable state behind it" rule). PR 1.6 only surfaces these — Stage 2 composition,
//! cascade, and the `cohort_membership_changed` produce are later PRs. In M1 the behavioral path
//! never clears a match, so only [`TransitionKind::Left`] from the person-property path appears;
//! [`TransitionKind::Left`] for behavioral arrives with sweep eviction (PR 2.2–2.3).

use uuid::Uuid;

use crate::filters::TeamId;
use crate::stage1::key::LeafStateKey;

/// The direction of a membership flip for one leaf.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransitionKind {
    /// The predicate went `false → true`.
    Entered,
    /// The predicate went `true → false`.
    Left,
}

/// A single leaf's membership flip for one person, carrying everything a later stage needs to
/// route and attribute it: the team, the per-leaf state key, the person, the originating
/// `conditionHash`, and the direction.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LeafTransition {
    pub team_id: TeamId,
    pub leaf_state_key: LeafStateKey,
    pub person_id: Uuid,
    pub condition_hash: [u8; 16],
    pub kind: TransitionKind,
}
