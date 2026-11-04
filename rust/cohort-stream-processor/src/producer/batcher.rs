//! Per-worker output buffer.

use crate::producer::CohortMembershipChange;

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

    /// `None` when nothing is buffered, so a caller never produces an empty batch.
    pub fn take(&mut self) -> Option<Vec<CohortMembershipChange>> {
        if self.changes.is_empty() {
            return None;
        }
        Some(std::mem::take(&mut self.changes))
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
            origin: None,
            run_id: None,
        }
    }

    #[test]
    fn take_drains_in_order_and_yields_nothing_when_empty() {
        let mut buffer = OutputBuffer::new();
        assert!(buffer.take().is_none(), "an empty buffer has no batch");

        buffer.push(change(1));
        buffer.extend([change(2), change(3)]);

        let taken = buffer.take().expect("three changes buffered");
        assert_eq!(
            taken.iter().map(|c| c.cohort_id).collect::<Vec<_>>(),
            vec![1, 2, 3]
        );
        assert!(buffer.take().is_none(), "take left the buffer empty");
    }
}
