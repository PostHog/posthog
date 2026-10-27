use std::fmt;
use std::ops::{Add, Sub};

/// A partition index on the consumer's single topic. It carries no topic, so
/// a consumer of several topics must not key on it alone.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Partition(pub i32);

impl fmt::Display for Partition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// Accepted offsets of one partition and generation from one worker
/// response: the messages were delivered downstream and the consumer may
/// account them toward its poll and, later, its commit. No batch identity
/// and no message bodies cross this boundary; the consumer correlates by
/// partition and offset.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GroupCompletion {
    pub partition: Partition,
    /// The assignment epoch the messages' poll was submitted under. A
    /// completion for a partition that was revoked and reassigned since then
    /// carries an older epoch than any poll after the reassignment.
    pub assignment_epoch: u64,
    /// The ledger generation the group's messages were charged under.
    pub generation: u64,
    /// The accepted offsets, in send order.
    pub offsets: Vec<Offset>,
    /// Always `offsets.len()`: a completion carries accepted offsets only.
    pub accepted: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Offset(pub i64);

impl Sub for Offset {
    type Output = i64;

    fn sub(self, rhs: Offset) -> i64 {
        self.0 - rhs.0
    }
}

impl Add<usize> for Offset {
    type Output = Offset;

    fn add(self, rhs: usize) -> Offset {
        Offset(self.0 + rhs as i64)
    }
}

impl fmt::Display for Offset {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}
