//! What a checkpoint restore does with each slice: resume it from the checkpoint's positions, or
//! reset it because the checkpoint holds no positions for it.

use std::collections::BTreeMap;

use super::manifest::OffsetManifest;
use crate::partitions::{InputTopic, ResumeOffset};

/// What a restore does with one partition's slice.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SliceRestore {
    /// Keep the slice and replay each input from its checkpoint position.
    Resume(BTreeMap<InputTopic, ResumeOffset>),
    /// Drop the slice so it begins again behind the coverage fence.
    Reset(ResetReason),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ResetReason {
    NotInCheckpoint,
}

impl ResetReason {
    pub fn label(&self) -> &'static str {
        match self {
            Self::NotInCheckpoint => "not_in_checkpoint",
        }
    }
}

/// One [`SliceRestore`] per partition of the topic, built only by [`Self::check`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RestorePlan(BTreeMap<u16, SliceRestore>);

impl RestorePlan {
    /// Check every partition against the manifest. A slice the manifest covers resumes from its
    /// positions; any other slice resets, because nothing says where its inputs resume. An input
    /// the manifest lacks, because its gate turned on after the capture, gets no position and
    /// resumes from its group's commit.
    pub fn check(manifest: &OffsetManifest, partition_count: u16) -> Self {
        Self(
            (0..partition_count)
                .map(|partition| {
                    let slice = match manifest.slice(partition) {
                        Some(recorded) => SliceRestore::Resume(recorded.clone()),
                        None => SliceRestore::Reset(ResetReason::NotInCheckpoint),
                    };
                    (partition, slice)
                })
                .collect(),
        )
    }

    pub fn resets(&self) -> impl Iterator<Item = (u16, &ResetReason)> {
        self.0.iter().filter_map(|(&partition, slice)| match slice {
            SliceRestore::Reset(reason) => Some((partition, reason)),
            SliceRestore::Resume(_) => None,
        })
    }

    /// Where `topic` resumes on every slice the plan keeps.
    pub fn positions(&self, topic: &InputTopic) -> BTreeMap<u16, ResumeOffset> {
        self.0
            .iter()
            .filter_map(|(&partition, slice)| match slice {
                SliceRestore::Resume(positions) => Some((partition, *positions.get(topic)?)),
                SliceRestore::Reset(_) => None,
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    use crate::partitions::InputPositions;
    use crate::store::durability::lineage::PodOrdinal;

    const EVENTS: &str = "cohort_stream_events";
    const MERGES: &str = "person_merge_events";

    fn offset(value: i64) -> ResumeOffset {
        ResumeOffset::try_from(value).unwrap()
    }

    fn manifest(slices: &[(u16, &[(&str, i64)])]) -> OffsetManifest {
        let topics: BTreeSet<&str> = slices
            .iter()
            .flat_map(|(_, positions)| positions.iter().map(|(topic, _)| *topic))
            .collect();
        let owned = slices.iter().map(|(partition, _)| *partition).collect();
        let positions = topics
            .into_iter()
            .map(|topic| {
                InputPositions::new(
                    InputTopic::new(topic),
                    slices
                        .iter()
                        .flat_map(|(partition, positions)| {
                            positions
                                .iter()
                                .filter(move |(t, _)| *t == topic)
                                .map(move |&(_, value)| (*partition, offset(value)))
                        })
                        .collect(),
                )
            })
            .collect();
        OffsetManifest::capture(PodOrdinal::STANDALONE, &owned, positions).unwrap()
    }

    #[test]
    fn a_slice_the_manifest_lacks_resets_and_every_other_resumes_from_its_positions() {
        let recorded = manifest(&[
            (0, &[(EVENTS, 10), (MERGES, 5)]),
            (2, &[(EVENTS, 7), (MERGES, 1)]),
        ]);

        let plan = RestorePlan::check(&recorded, 3);

        assert_eq!(
            plan.0,
            BTreeMap::from([
                (
                    0,
                    SliceRestore::Resume(BTreeMap::from([
                        (InputTopic::new(EVENTS), offset(10)),
                        (InputTopic::new(MERGES), offset(5)),
                    ])),
                ),
                (1, SliceRestore::Reset(ResetReason::NotInCheckpoint)),
                (
                    2,
                    SliceRestore::Resume(BTreeMap::from([
                        (InputTopic::new(EVENTS), offset(7)),
                        (InputTopic::new(MERGES), offset(1)),
                    ])),
                ),
            ]),
        );
        assert_eq!(
            plan.positions(&InputTopic::new(EVENTS)),
            BTreeMap::from([(0, offset(10)), (2, offset(7))]),
        );
    }
}
