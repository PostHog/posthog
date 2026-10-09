//! What a checkpoint restore does with each slice: resume it from the checkpoint's positions, or
//! reset it because the broker can no longer replay what the checkpoint lacks.

use std::collections::{BTreeMap, BTreeSet};

use rdkafka::error::{KafkaError, KafkaResult};
use rdkafka::types::RDKafkaErrorCode;

use super::manifest::OffsetManifest;
use crate::partitions::{InputGroups, InputTopic, ResumeOffset};

/// Watermarks of the enabled inputs.
pub trait ReplayWindow {
    fn inputs(&self) -> &BTreeSet<InputTopic>;
    /// `[low, high]` of `topic` on every partition in `0..partition_count`.
    fn watermarks(
        &self,
        topic: &InputTopic,
        partition_count: u16,
    ) -> KafkaResult<BTreeMap<u16, (i64, i64)>>;
}

impl ReplayWindow for InputGroups {
    fn inputs(&self) -> &BTreeSet<InputTopic> {
        InputGroups::inputs(self)
    }

    fn watermarks(
        &self,
        topic: &InputTopic,
        partition_count: u16,
    ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
        InputGroups::watermarks(self, topic, partition_count)
    }
}

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
    ReplayOutOfRange {
        topic: InputTopic,
        resume: ResumeOffset,
        low: i64,
        high: i64,
    },
}

impl ResetReason {
    pub fn label(&self) -> &'static str {
        match self {
            Self::NotInCheckpoint => "not_in_checkpoint",
            Self::ReplayOutOfRange { .. } => "replay_out_of_range",
        }
    }
}

/// One [`SliceRestore`] per partition of the topic, built only by [`Self::check`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RestorePlan(BTreeMap<u16, SliceRestore>);

impl RestorePlan {
    /// Check every partition's checkpoint positions against the broker. A slice resumes only when
    /// every enabled input it records can still be replayed from its position: within
    /// `[low, high]`. An enabled input the manifest lacks, because its gate turned on after the
    /// capture, gets no position and resumes from its group's commit. A manifest input that is no
    /// longer enabled is ignored.
    pub fn check(
        manifest: &OffsetManifest,
        window: &impl ReplayWindow,
        partition_count: u16,
    ) -> KafkaResult<Self> {
        let checked: Vec<&InputTopic> = window.inputs().intersection(manifest.inputs()).collect();
        let bounds = checked
            .iter()
            .map(|&topic| Ok((topic, window.watermarks(topic, partition_count)?)))
            .collect::<KafkaResult<BTreeMap<_, _>>>()?;
        let mut slices = BTreeMap::new();
        for partition in 0..partition_count {
            let Some(recorded) = manifest.slice(partition) else {
                slices.insert(partition, SliceRestore::Reset(ResetReason::NotInCheckpoint));
                continue;
            };
            let mut resume = BTreeMap::new();
            let mut reset = None;
            for &topic in &checked {
                let position = recorded[topic];
                let (low, high) = *bounds[topic]
                    .get(&partition)
                    .ok_or(KafkaError::OffsetFetch(RDKafkaErrorCode::UnknownPartition))?;
                if !(low..=high).contains(&position.get()) {
                    reset = Some(ResetReason::ReplayOutOfRange {
                        topic: topic.clone(),
                        resume: position,
                        low,
                        high,
                    });
                    break;
                }
                resume.insert(topic.clone(), position);
            }
            let slice = match reset {
                Some(reason) => SliceRestore::Reset(reason),
                None => SliceRestore::Resume(resume),
            };
            slices.insert(partition, slice);
        }
        Ok(Self(slices))
    }

    pub fn resumes_any(&self) -> bool {
        self.0
            .values()
            .any(|slice| matches!(slice, SliceRestore::Resume(_)))
    }

    pub fn resets(&self) -> impl Iterator<Item = (u16, &ResetReason)> {
        self.0.iter().filter_map(|(&partition, slice)| match slice {
            SliceRestore::Reset(reason) => Some((partition, reason)),
            SliceRestore::Resume(_) => None,
        })
    }

    /// Every position the plan keeps: the slice, the input and where it resumes.
    pub fn kept(&self) -> impl Iterator<Item = (u16, &InputTopic, ResumeOffset)> {
        self.0.iter().flat_map(|(&partition, slice)| {
            let positions = match slice {
                SliceRestore::Resume(positions) => Some(positions),
                SliceRestore::Reset(_) => None,
            };
            positions
                .into_iter()
                .flatten()
                .map(move |(topic, &offset)| (partition, topic, offset))
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
    use crate::partitions::InputPositions;
    use crate::store::durability::lineage::PodOrdinal;

    const EVENTS: &str = "cohort_stream_events";
    const MERGES: &str = "person_merge_events";
    const SEEDS: &str = "cohort_stream_seed_events";

    struct Window {
        inputs: BTreeSet<InputTopic>,
        bounds: BTreeMap<(&'static str, u16), (i64, i64)>,
    }

    impl ReplayWindow for Window {
        fn inputs(&self) -> &BTreeSet<InputTopic> {
            &self.inputs
        }

        fn watermarks(
            &self,
            topic: &InputTopic,
            partition_count: u16,
        ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
            Ok((0..partition_count)
                .map(|partition| {
                    let bounds = self
                        .bounds
                        .get(&(topic.as_str(), partition))
                        .copied()
                        .unwrap_or((0, 1_000));
                    (partition, bounds)
                })
                .collect())
        }
    }

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

    type Bounds = ((&'static str, u16), (i64, i64));

    fn window(inputs: &[&str], bounds: &[Bounds]) -> Window {
        Window {
            inputs: inputs.iter().map(|topic| InputTopic::new(*topic)).collect(),
            bounds: bounds.iter().copied().collect(),
        }
    }

    #[test]
    fn a_slice_resumes_only_when_every_enabled_recorded_input_can_still_replay() {
        let recorded = manifest(&[
            (0, &[(EVENTS, 10), (MERGES, 5)]),
            (1, &[(EVENTS, 10), (MERGES, 5)]),
            (2, &[(EVENTS, 10), (MERGES, 5)]),
            (4, &[(EVENTS, 10), (MERGES, 5)]),
        ]);
        // Partition 4 sits on both edges: caught up on the events, at the oldest retained merge.
        let window = window(
            &[EVENTS, MERGES],
            &[
                ((MERGES, 1), (6, 50)),
                ((EVENTS, 2), (0, 9)),
                ((EVENTS, 4), (3, 10)),
                ((MERGES, 4), (5, 5)),
            ],
        );

        let plan = RestorePlan::check(&recorded, &window, 5).unwrap();

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
                (
                    1,
                    SliceRestore::Reset(ResetReason::ReplayOutOfRange {
                        topic: InputTopic::new(MERGES),
                        resume: offset(5),
                        low: 6,
                        high: 50,
                    }),
                ),
                (
                    2,
                    SliceRestore::Reset(ResetReason::ReplayOutOfRange {
                        topic: InputTopic::new(EVENTS),
                        resume: offset(10),
                        low: 0,
                        high: 9,
                    }),
                ),
                (3, SliceRestore::Reset(ResetReason::NotInCheckpoint)),
                (
                    4,
                    SliceRestore::Resume(BTreeMap::from([
                        (InputTopic::new(EVENTS), offset(10)),
                        (InputTopic::new(MERGES), offset(5)),
                    ])),
                ),
            ]),
        );
        assert!(plan.resumes_any());
        assert_eq!(
            plan.positions(&InputTopic::new(EVENTS)),
            BTreeMap::from([(0, offset(10)), (4, offset(10))]),
        );
    }

    #[test]
    fn inputs_enabled_on_one_side_only_neither_reset_nor_resume_a_slice() {
        let recorded = manifest(&[(0, &[(EVENTS, 10), (MERGES, 5)])]);
        // The merge input was disabled after the capture, and the seed input enabled after it.
        let window = window(&[EVENTS, SEEDS], &[((MERGES, 0), (900, 1_000))]);

        let plan = RestorePlan::check(&recorded, &window, 1).unwrap();

        assert_eq!(
            plan.0,
            BTreeMap::from([(
                0,
                SliceRestore::Resume(BTreeMap::from([(InputTopic::new(EVENTS), offset(10))])),
            )]),
        );
        assert!(plan.positions(&InputTopic::new(SEEDS)).is_empty());
    }

    #[test]
    fn a_plan_that_resets_every_slice_resumes_nothing() {
        let recorded = manifest(&[(0, &[(EVENTS, 10)])]);
        let window = window(&[EVENTS], &[((EVENTS, 0), (11, 20))]);

        let plan = RestorePlan::check(&recorded, &window, 2).unwrap();

        assert!(!plan.resumes_any());
        assert_eq!(
            plan.resets()
                .map(|(partition, _)| partition)
                .collect::<Vec<_>>(),
            [0, 1],
        );
    }
}
