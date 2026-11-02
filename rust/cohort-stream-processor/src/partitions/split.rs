//! The split this pod runs under, and its place in a reshard. A reshard multiplies the pod count by
//! a whole factor. A pod whose ordinal is below the old count keeps its store and drops the
//! partitions it gives away. Every other pod takes its partitions over from the pod of the old split
//! that owned them.

use std::fmt;
use std::num::NonZeroU16;

use super::PartitionOwnership;
use crate::store::durability::PodOrdinal;

/// This pod's split, and its place in a reshard. Only [`Self::new`] builds one, so a reshard always
/// raises the pod count by a whole factor, and the parent always covers this pod.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SplitClaim {
    ownership: PartitionOwnership,
    role: Role,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    /// No reshard is under way.
    Steady,
    /// The ordinal is below the old pod count, so this pod's store already holds its partitions. It
    /// wrote them under `parent`.
    Parent { parent: PartitionOwnership },
    /// The ordinal is at or above the old pod count. Its partitions belong to `parent` until it
    /// takes them over. `parent_now` is the parent's place in the new split.
    Child {
        parent: PartitionOwnership,
        parent_now: PartitionOwnership,
    },
}

#[derive(Debug, thiserror::Error)]
pub enum SplitError {
    #[error("a reshard from {from} to {pods} pods must raise the pod count")]
    NotAGrowth { from: NonZeroU16, pods: NonZeroU16 },
    #[error("a reshard from {from} to {pods} pods must multiply the pod count by a whole number")]
    NotAMultiple { from: NonZeroU16, pods: NonZeroU16 },
}

impl SplitClaim {
    /// `reshard_from` is the pod count before the reshard, or `None` outside one. No path merges
    /// two stores, so a reshard that lowers the pod count is refused.
    pub fn new(
        ownership: PartitionOwnership,
        reshard_from: Option<NonZeroU16>,
    ) -> Result<Self, SplitError> {
        let Some(from) = reshard_from else {
            return Ok(Self {
                ownership,
                role: Role::Steady,
            });
        };
        let pods = ownership.pods();
        if from >= pods {
            return Err(SplitError::NotAGrowth { from, pods });
        }
        if !pods.get().is_multiple_of(from.get()) {
            return Err(SplitError::NotAMultiple { from, pods });
        }
        let ordinal = ownership.ordinal().get();
        let place = |pods| {
            PartitionOwnership::new(
                pods,
                PodOrdinal::from(ordinal % from.get()),
                ownership.partition_count(),
            )
            .expect("a divisor of the pod count splits the partitions evenly")
        };
        let parent = place(from);
        let role = if ordinal < from.get() {
            Role::Parent { parent }
        } else {
            Role::Child {
                parent,
                parent_now: place(pods),
            }
        };
        Ok(Self { ownership, role })
    }

    pub fn ownership(&self) -> PartitionOwnership {
        self.ownership
    }

    pub fn role(&self) -> Role {
        self.role
    }
}

impl fmt::Display for SplitClaim {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.role {
            Role::Steady => write!(f, "{}", self.ownership),
            Role::Parent { parent } | Role::Child { parent, .. } => {
                write!(f, "{}, resharded from {parent}", self.ownership)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PARTITIONS: u16 = 64;

    fn split(pods: u16, ordinal: u16) -> PartitionOwnership {
        PartitionOwnership::new(
            NonZeroU16::new(pods).unwrap(),
            PodOrdinal::from(ordinal),
            PARTITIONS,
        )
        .unwrap()
    }

    #[test]
    fn a_reshard_gives_every_ordinal_its_role_and_parent() {
        let cases = [
            (
                1,
                2,
                0,
                Role::Parent {
                    parent: split(1, 0),
                },
            ),
            (
                1,
                2,
                1,
                Role::Child {
                    parent: split(1, 0),
                    parent_now: split(2, 0),
                },
            ),
            (
                2,
                4,
                0,
                Role::Parent {
                    parent: split(2, 0),
                },
            ),
            (
                2,
                4,
                1,
                Role::Parent {
                    parent: split(2, 1),
                },
            ),
            (
                2,
                4,
                2,
                Role::Child {
                    parent: split(2, 0),
                    parent_now: split(4, 0),
                },
            ),
            (
                2,
                4,
                3,
                Role::Child {
                    parent: split(2, 1),
                    parent_now: split(4, 1),
                },
            ),
            (
                1,
                4,
                0,
                Role::Parent {
                    parent: split(1, 0),
                },
            ),
            (
                1,
                4,
                3,
                Role::Child {
                    parent: split(1, 0),
                    parent_now: split(4, 0),
                },
            ),
        ];
        for (from, pods, ordinal, role) in cases {
            let claim = SplitClaim::new(split(pods, ordinal), NonZeroU16::new(from)).unwrap();
            assert_eq!(claim.role(), role, "pod {ordinal} of {from} -> {pods}");
            assert_eq!(claim.ownership(), split(pods, ordinal));
        }

        assert_eq!(
            SplitClaim::new(split(2, 1), None).unwrap().role(),
            Role::Steady
        );
    }

    #[test]
    fn a_reshard_must_raise_the_pod_count_by_a_whole_factor() {
        let two = NonZeroU16::new(2).unwrap();
        assert!(matches!(
            SplitClaim::new(split(1, 0), Some(two)),
            Err(SplitError::NotAGrowth { .. })
        ));
        assert!(matches!(
            SplitClaim::new(split(2, 1), Some(two)),
            Err(SplitError::NotAGrowth { .. })
        ));
        let three_of_twelve =
            PartitionOwnership::new(NonZeroU16::new(3).unwrap(), PodOrdinal::from(2), 12).unwrap();
        assert!(matches!(
            SplitClaim::new(three_of_twelve, Some(two)),
            Err(SplitError::NotAMultiple { .. })
        ));
    }
}
