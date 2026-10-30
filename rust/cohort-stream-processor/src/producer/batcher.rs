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

    /// Take everything buffered as one batch, or `None` when the buffer is empty.
    /// `source_offset` is the informational offset the batch's first-hop cascades carry.
    pub fn take_batch(&mut self, source_offset: i64) -> Option<OutputBatch> {
        if self.changes.is_empty() {
            return None;
        }
        Some(OutputBatch {
            changes: std::mem::take(&mut self.changes),
            source_offset,
        })
    }
}

/// Buffered changes ready to produce. [`OutputBuffer::take_batch`] is the only constructor, so a
/// batch is never empty.
#[derive(Debug)]
pub struct OutputBatch {
    changes: Vec<CohortMembershipChange>,
    source_offset: i64,
}

impl OutputBatch {
    pub fn into_parts(self) -> (Vec<CohortMembershipChange>, i64) {
        (self.changes, self.source_offset)
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
    fn take_batch_drains_in_order_and_yields_nothing_when_empty() {
        let mut buffer = OutputBuffer::new();
        assert!(
            buffer.take_batch(0).is_none(),
            "an empty buffer has no batch"
        );

        buffer.push(change(1));
        buffer.extend([change(2), change(3)]);

        let (taken, source_offset) = buffer
            .take_batch(9)
            .expect("three changes buffered")
            .into_parts();
        assert_eq!(
            taken.iter().map(|c| c.cohort_id).collect::<Vec<_>>(),
            vec![1, 2, 3]
        );
        assert_eq!(source_offset, 9);
        assert!(
            buffer.take_batch(10).is_none(),
            "the batch left the buffer empty"
        );
    }
}
