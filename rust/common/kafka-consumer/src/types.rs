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

/// One group's completion: the group's messages were delivered downstream and
/// the consumer may account them toward its poll and, later, its commit. No
/// batch identity and no message bodies cross this boundary; the consumer
/// correlates by partition and offset.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GroupCompletion {
    pub partition: Partition,
    /// The assignment epoch under which the group's poll was collected. A
    /// completion for a partition that was revoked and reassigned in between
    /// carries an older epoch than any poll of the new incarnation.
    pub assignment_epoch: u64,
    /// The offsets of the group's messages, in group order.
    pub offsets: Vec<Offset>,
    /// How many of the group's messages the worker accepted.
    pub accepted: u32,
}

/// A Kafka message offset.
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
