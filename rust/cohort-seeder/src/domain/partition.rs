//! Seed-topic partition newtypes: a partition index proven to fit Kafka's signed partition field and
//! this service's compact `u16` representation. Pure domain — the `kafka` layer re-exports these so
//! its call sites (`enqueue_reconcile`, reconcile dispatch) stay unchanged.

use std::fmt;

const MAX_SEED_PARTITION_COUNT: u32 = 65_536;

/// A seed-topic partition proven to fit both Kafka's signed partition field and this service's
/// compact partition representation. Values can only be minted by [`SeedPartition::all`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SeedPartition(u16);

impl SeedPartition {
    pub fn all(count: u32) -> Result<SeedPartitions, SeedPartitionCountError> {
        if count == 0 {
            return Err(SeedPartitionCountError::Zero);
        }
        if count > MAX_SEED_PARTITION_COUNT {
            return Err(SeedPartitionCountError::TooLarge(count));
        }
        Ok(SeedPartitions { next: 0, count })
    }

    pub const fn as_u16(self) -> u16 {
        self.0
    }

    pub(crate) const fn as_i32(self) -> i32 {
        self.0 as i32
    }
}

impl fmt::Display for SeedPartition {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// The exact sequence `0..count` returned after [`SeedPartition::all`] proves every index fits.
#[derive(Debug, Clone)]
pub struct SeedPartitions {
    next: u32,
    count: u32,
}

impl Iterator for SeedPartitions {
    type Item = SeedPartition;

    fn next(&mut self) -> Option<Self::Item> {
        if self.next == self.count {
            return None;
        }
        let partition = u16::try_from(self.next)
            .expect("partition count validation proves every partition index fits u16");
        self.next += 1;
        Some(SeedPartition(partition))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let remaining = usize::try_from(self.count - self.next)
            .expect("a u32 partition count fits usize on supported targets");
        (remaining, Some(remaining))
    }
}

impl ExactSizeIterator for SeedPartitions {}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum SeedPartitionCountError {
    #[error("seed partition count must be greater than zero")]
    Zero,
    #[error(
        "seed partition count {0} exceeds the largest u16-indexed partition set ({MAX_SEED_PARTITION_COUNT})"
    )]
    TooLarge(u32),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seed_partitions_cover_exactly_the_valid_partition_domain() {
        let partitions = SeedPartition::all(64).unwrap().collect::<Vec<_>>();
        assert_eq!(partitions.len(), 64);
        assert_eq!(partitions.first().unwrap().as_u16(), 0);
        assert_eq!(partitions.last().unwrap().as_u16(), 63);

        assert_eq!(
            SeedPartition::all(MAX_SEED_PARTITION_COUNT)
                .unwrap()
                .last()
                .unwrap()
                .as_u16(),
            u16::MAX,
        );
        assert!(matches!(
            SeedPartition::all(0),
            Err(SeedPartitionCountError::Zero)
        ));
        assert!(matches!(
            SeedPartition::all(MAX_SEED_PARTITION_COUNT + 1),
            Err(SeedPartitionCountError::TooLarge(count))
                if count == MAX_SEED_PARTITION_COUNT + 1
        ));
    }
}
