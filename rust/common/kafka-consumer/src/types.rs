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
