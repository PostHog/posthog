//! Per-worker output buffer (TDD §3) — PR 1.8.
//!
//! A thin typed wrapper over `Vec<CohortMembershipChange>`. Named [`OutputBuffer`] (not a bare
//! `Vec`) so M3 / PR 3.4 can promote it to a worker-owned, two-topic buffer (membership + cascade)
//! without touching the worker's call sites. Deliberately minimal.

use crate::producer::CohortMembershipChange;

/// Accumulates the membership changes a worker produces for one drained sub-batch, then yields them
/// to the sink via [`take`](Self::take).
#[derive(Debug, Default)]
pub struct OutputBuffer {
    changes: Vec<CohortMembershipChange>,
}

impl OutputBuffer {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&mut self, change: CohortMembershipChange) {
        self.changes.push(change);
    }

    pub fn extend(&mut self, changes: impl IntoIterator<Item = CohortMembershipChange>) {
        self.changes.extend(changes);
    }

    pub fn is_empty(&self) -> bool {
        self.changes.is_empty()
    }

    /// Take the buffered changes, leaving the buffer empty for the next sub-batch.
    pub fn take(&mut self) -> Vec<CohortMembershipChange> {
        std::mem::take(&mut self.changes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::producer::MembershipStatus;

    fn change(cohort_id: i32) -> CohortMembershipChange {
        CohortMembershipChange {
            team_id: 1,
            cohort_id,
            person_id: "p".to_string(),
            last_updated: "2026-05-26 12:34:56.789123".to_string(),
            status: MembershipStatus::Entered,
        }
    }

    #[test]
    fn push_extend_take_round_trip() {
        let mut buffer = OutputBuffer::new();
        assert!(buffer.is_empty());

        buffer.push(change(1));
        buffer.extend([change(2), change(3)]);
        assert!(!buffer.is_empty());

        let taken = buffer.take();
        assert_eq!(
            taken.iter().map(|c| c.cohort_id).collect::<Vec<_>>(),
            vec![1, 2, 3]
        );
        assert!(buffer.is_empty(), "take leaves the buffer empty");
    }
}
