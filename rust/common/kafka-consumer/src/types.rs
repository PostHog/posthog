use std::fmt;

use crate::charge::Charge;

/// A partition index on the loop's single topic.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Partition(pub i32);

impl fmt::Display for Partition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// A Kafka message offset.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Offset(pub i64);

impl Offset {
    /// The next offset after this one — what Kafka expects in a commit.
    pub fn next(self) -> Offset {
        Offset(self.0 + 1)
    }
}

impl fmt::Display for Offset {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// A pod-local counter bumped on every partition assignment. Groups are
/// stamped with their driver's epoch; a completion whose epoch does not match
/// the current driver's is a straggler from before a reassignment and is
/// dropped — the replay it represents is legal duplication, never loss.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AssignmentEpoch(pub u64);

/// One frontier movement: the partition, its new frontier, and the charge of
/// the span the frontier walked over.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Advance {
    pub partition: Partition,
    pub frontier: Offset,
    pub charge: Charge,
}

/// A drain's last word: the final frontier to commit (if anything ever
/// completed) and the charge the frontier never walked over.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DrainHarvest {
    pub partition: Partition,
    pub frontier: Option<Offset>,
    pub dropped: Charge,
}
