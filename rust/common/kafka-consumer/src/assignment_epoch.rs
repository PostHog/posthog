use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

/// The consumer's assignment generation: bumped once per partition-assign
/// rebalance event, and read wherever work must be tied to the assignment it
/// was created under. A reader that stamps work at creation can later tell
/// whether the work predates the current assignment.
///
/// The owning consumer's rebalance callback is the single bump site; every
/// other holder only reads. Clones share one counter, so every component
/// holds the same generation.
#[derive(Clone, Debug)]
pub struct AssignmentEpoch {
    counter: Arc<AtomicU64>,
}

impl AssignmentEpoch {
    pub fn new() -> Self {
        Self {
            counter: Arc::new(AtomicU64::new(1)),
        }
    }

    /// Record one more assignment. Called from the rebalance callback.
    pub fn bump(&self) {
        self.counter.fetch_add(1, Ordering::Relaxed);
    }

    /// The current epoch, for stamping work as it is created.
    pub fn current(&self) -> u64 {
        self.counter.load(Ordering::Relaxed)
    }
}

impl Default for AssignmentEpoch {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clones_share_the_counter() {
        let epoch = AssignmentEpoch::new();
        let clone = epoch.clone();
        assert_eq!(epoch.current(), 1);

        clone.bump();

        assert_eq!(epoch.current(), 2);
        assert_eq!(clone.current(), 2);
    }
}
