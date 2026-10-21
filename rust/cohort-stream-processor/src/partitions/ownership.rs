//! Static partition ownership. Pod `ordinal` of `pods` owns every partition `p` with
//! `p % pods == ordinal` on all five inputs, for as long as it runs. The consumers assign
//! themselves these partitions instead of joining a group rebalance, so no partition moves between
//! running pods. The store records the ownership it was written under.

use std::fmt;
use std::num::NonZeroU16;

use rdkafka::error::KafkaResult;
use rdkafka::{Offset, TopicPartitionList};
use serde::{Deserialize, Serialize};

use crate::store::durability::PodOrdinal;

/// The partitions one pod owns. Only [`Self::new`] splits the partitions between more than one
/// pod, so `pods` divides the partition count and the ordinal is below `pods`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "SplitWire", into = "SplitWire")]
pub struct PartitionOwnership {
    pods: NonZeroU16,
    ordinal: PodOrdinal,
    partition_count: u16,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum OwnershipError {
    #[error("{pods} pods cannot split {partition_count} partitions evenly")]
    UnevenSplit {
        pods: NonZeroU16,
        partition_count: u16,
    },
    #[error("pod ordinal {ordinal} is not below the pod count {pods}")]
    OrdinalOutOfRange {
        ordinal: PodOrdinal,
        pods: NonZeroU16,
    },
}

const ENCODED_LEN: usize = 6;

/// The JSON shape, decoded through [`PartitionOwnership::new`].
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SplitWire {
    pods: NonZeroU16,
    ordinal: PodOrdinal,
    partitions: u16,
}

impl TryFrom<SplitWire> for PartitionOwnership {
    type Error = OwnershipError;

    fn try_from(wire: SplitWire) -> Result<Self, Self::Error> {
        Self::new(wire.pods, wire.ordinal, wire.partitions)
    }
}

impl From<PartitionOwnership> for SplitWire {
    fn from(ownership: PartitionOwnership) -> Self {
        Self {
            pods: ownership.pods,
            ordinal: ownership.ordinal,
            partitions: ownership.partition_count,
        }
    }
}

impl PartitionOwnership {
    /// One pod owns every partition.
    pub const fn single(partition_count: u16) -> Self {
        Self {
            pods: NonZeroU16::MIN,
            ordinal: PodOrdinal::STANDALONE,
            partition_count,
        }
    }

    /// Every pod must own the same number of partitions, so `pods` must divide `partition_count`.
    pub fn new(
        pods: NonZeroU16,
        ordinal: PodOrdinal,
        partition_count: u16,
    ) -> Result<Self, OwnershipError> {
        if !partition_count.is_multiple_of(pods.get()) {
            return Err(OwnershipError::UnevenSplit {
                pods,
                partition_count,
            });
        }
        if ordinal.get() >= pods.get() {
            return Err(OwnershipError::OrdinalOutOfRange { ordinal, pods });
        }
        Ok(Self {
            pods,
            ordinal,
            partition_count,
        })
    }

    pub fn pods(&self) -> NonZeroU16 {
        self.pods
    }

    pub fn ordinal(&self) -> PodOrdinal {
        self.ordinal
    }

    pub fn partition_count(&self) -> u16 {
        self.partition_count
    }

    pub fn owns(&self, partition: u16) -> bool {
        partition < self.partition_count && partition % self.pods.get() == self.ordinal.get()
    }

    /// True when every partition `other` owns is one this split owns. That holds when `self.pods`
    /// divides `other.pods` and `other.ordinal % self.pods == self.ordinal`: every `p` with
    /// `p % other.pods == other.ordinal` then has `p % self.pods == self.ordinal`.
    pub fn covers(&self, other: &Self) -> bool {
        self.partition_count == other.partition_count
            && other.pods.get().is_multiple_of(self.pods.get())
            && other.ordinal.get() % self.pods.get() == self.ordinal.get()
    }

    /// The owned partitions in ascending order.
    pub fn partitions(&self) -> impl Iterator<Item = u16> {
        (self.ordinal.get()..self.partition_count).step_by(usize::from(self.pods.get()))
    }

    /// `topic`'s owned partitions, each at its group's committed offset, for `Consumer::assign`.
    pub fn assignment(&self, topic: &str) -> KafkaResult<TopicPartitionList> {
        let mut assignment = TopicPartitionList::new();
        for partition in self.partitions() {
            assignment.add_partition_offset(topic, i32::from(partition), Offset::Stored)?;
        }
        Ok(assignment)
    }

    /// The `cf_meta` record: the pod count, the ordinal and the partition count, each a
    /// big-endian `u16`.
    pub(crate) fn encode(&self) -> [u8; ENCODED_LEN] {
        let mut bytes = [0; ENCODED_LEN];
        bytes[0..2].copy_from_slice(&self.pods.get().to_be_bytes());
        bytes[2..4].copy_from_slice(&self.ordinal.get().to_be_bytes());
        bytes[4..6].copy_from_slice(&self.partition_count.to_be_bytes());
        bytes
    }

    /// `None` for bytes that [`Self::encode`] did not write.
    pub(crate) fn decode(bytes: &[u8]) -> Option<Self> {
        let [p0, p1, o0, o1, c0, c1] = <[u8; ENCODED_LEN]>::try_from(bytes).ok()?;
        let pods = NonZeroU16::new(u16::from_be_bytes([p0, p1]))?;
        let ordinal = PodOrdinal::from(u16::from_be_bytes([o0, o1]));
        Self::new(pods, ordinal, u16::from_be_bytes([c0, c1])).ok()
    }
}

impl fmt::Display for PartitionOwnership {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "pod {} of {} over {} partitions",
            self.ordinal, self.pods, self.partition_count
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_split_of_the_partitions_gives_each_partition_exactly_one_owner() {
        const PARTITIONS: u16 = 64;
        for pods in [1, 2, 4, 8, 16, 32, 64] {
            let pods = NonZeroU16::new(pods).unwrap();
            let split: Vec<PartitionOwnership> = (0..pods.get())
                .map(|ordinal| {
                    PartitionOwnership::new(pods, PodOrdinal::from(ordinal), PARTITIONS).unwrap()
                })
                .collect();
            let mut owners = [0usize; PARTITIONS as usize];
            for ownership in &split {
                let partitions: Vec<u16> = ownership.partitions().collect();
                assert_eq!(
                    partitions.len(),
                    usize::from(PARTITIONS / pods.get()),
                    "{ownership}"
                );
                for partition in 0..PARTITIONS {
                    assert_eq!(
                        ownership.owns(partition),
                        partitions.contains(&partition),
                        "{ownership}: partition {partition}",
                    );
                }
                for partition in partitions {
                    owners[usize::from(partition)] += 1;
                }
            }
            assert!(
                owners.iter().all(|&count| count == 1),
                "{pods} pods: {owners:?}"
            );
        }

        let pod_one_of_four =
            PartitionOwnership::new(NonZeroU16::new(4).unwrap(), PodOrdinal::from(1), 16).unwrap();
        assert_eq!(
            pod_one_of_four.partitions().collect::<Vec<_>>(),
            [1, 5, 9, 13]
        );
        assert!(!pod_one_of_four.owns(17), "past the partition count");
    }

    #[test]
    fn the_ownership_record_keeps_its_layout_and_rejects_bytes_encode_never_writes() {
        let pod_one_of_two =
            PartitionOwnership::new(NonZeroU16::new(2).unwrap(), PodOrdinal::from(1), 64).unwrap();
        assert_eq!(pod_one_of_two.encode(), [0, 2, 0, 1, 0, 64]);
        assert_eq!(
            PartitionOwnership::decode(&[0, 2, 0, 1, 0, 64]),
            Some(pod_one_of_two)
        );
        for bytes in [
            &[0, 2, 0, 1, 0][..],
            &[0, 0, 0, 0, 0, 64],
            &[0, 2, 0, 2, 0, 64],
            &[0, 3, 0, 0, 0, 64],
        ] {
            assert_eq!(PartitionOwnership::decode(bytes), None, "{bytes:?}");
        }
    }

    #[test]
    fn a_split_covers_another_exactly_when_it_owns_every_partition_the_other_owns() {
        // Over 64 partitions every pod count is a power of two, so one count of a pair always
        // divides the other. 12 has counts that do not, such as 2 and 3.
        for partitions in [64u16, 12] {
            let splits: Vec<PartitionOwnership> = (1..=partitions)
                .filter(|pods| partitions.is_multiple_of(*pods))
                .flat_map(|pods| {
                    let pods = NonZeroU16::new(pods).unwrap();
                    (0..pods.get()).map(move |ordinal| {
                        PartitionOwnership::new(pods, PodOrdinal::from(ordinal), partitions)
                            .unwrap()
                    })
                })
                .collect();
            for a in &splits {
                for b in &splits {
                    let inclusion = b.partitions().all(|partition| a.owns(partition));
                    assert_eq!(a.covers(b), inclusion, "{a} covers {b}");
                }
            }
        }

        let over_32 = PartitionOwnership::single(32);
        assert!(!PartitionOwnership::single(64).covers(&over_32));
    }

    #[test]
    fn the_assignment_resumes_each_owned_partition_at_its_committed_offset() {
        let ownership =
            PartitionOwnership::new(NonZeroU16::new(2).unwrap(), PodOrdinal::from(1), 4).unwrap();
        let assignment = ownership.assignment("cohort_stream_events").unwrap();
        let assigned: Vec<(String, i32, Offset)> = assignment
            .elements()
            .iter()
            .map(|elem| (elem.topic().to_owned(), elem.partition(), elem.offset()))
            .collect();
        assert_eq!(
            assigned,
            [
                ("cohort_stream_events".to_owned(), 1, Offset::Stored),
                ("cohort_stream_events".to_owned(), 3, Offset::Stored),
            ],
        );
    }
}
