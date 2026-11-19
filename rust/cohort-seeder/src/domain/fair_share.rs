//! Domain layer (pure): the claim-slot loads that order the next claim across teams and runs.
//! Depends on `ids`.

use super::ids::RunId;

/// The claim slots a team and one of its runs hold on this replica, counted within one run kind.
/// The next claim serves the lowest team load, then the lowest run load inside that team.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SlotLoad {
    pub team: u32,
    pub run: u32,
}

/// A run the next claim may take a chunk from, with the load its team and it already hold.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClaimCandidate {
    pub run_id: RunId,
    pub load: SlotLoad,
}

/// At least one candidate, so a claim over no run cannot be expressed.
#[derive(Debug)]
pub struct ClaimCandidates(Vec<ClaimCandidate>);

impl ClaimCandidates {
    pub fn new(candidates: Vec<ClaimCandidate>) -> Option<Self> {
        (!candidates.is_empty()).then_some(Self(candidates))
    }

    pub fn iter(&self) -> std::slice::Iter<'_, ClaimCandidate> {
        self.0.iter()
    }
}
