//! Stage 1 leaf transitions.
//!
//! The worker emits a [`LeafTransition`] only *after* the backing state is durably committed. The
//! behavioral path never clears a match, so a behavioral [`TransitionKind::Left`] only arrives via
//! sweep eviction.

use uuid::Uuid;

use crate::filters::TeamId;
use crate::stage1::key::LeafStateKey;

/// The direction of a membership flip for one leaf.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransitionKind {
    Entered,
    Left,
}

/// A single leaf's membership flip for one person, carrying what a later stage needs to route and
/// attribute it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LeafTransition {
    pub team_id: TeamId,
    pub leaf_state_key: LeafStateKey,
    pub person_id: Uuid,
    pub condition_hash: [u8; 16],
    pub kind: TransitionKind,
}
