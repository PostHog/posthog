//! Boot recovery for the events consumer.
//!
//! With durable restore, the store reopens with state the broker's committed offsets may not
//! match. Nothing may fold until the consumer has reclaimed unowned slices, redriven the merge
//! outbox and sought every owned partition back to the first event it polled and did not fold. A
//! fold before that would set per-key replay marks above offsets that are fetched again later, so
//! the second fetch would skip those events as replays.

use std::collections::{BTreeMap, HashSet};

use rdkafka::error::KafkaResult;
use rdkafka::{Offset, TopicPartitionList};

use crate::consumers::events::ConsumedEvent;
use crate::partitions::ResumeOffset;
use crate::store::durability::PendingRestore;

/// The lowest offset per events partition that boot polled and did not fold. A seek there fetches
/// every skipped event again. librdkafka discards messages it fetched before a seek, so a held-back
/// event is delivered once more, not twice.
#[derive(Debug, Default, PartialEq, Eq)]
pub(crate) struct ResumePoints(BTreeMap<i32, i64>);

impl ResumePoints {
    pub(crate) fn hold_back(&mut self, events: &[ConsumedEvent]) {
        for event in events {
            self.lower(event.partition, event.offset);
        }
    }

    /// A restored store resumes at its restore plan's position on every partition the plan keeps.
    /// The seek list leaves out the ones this consumer does not own.
    pub(crate) fn rewind_to(&mut self, positions: &BTreeMap<u16, ResumeOffset>) {
        for (&partition, &offset) in positions {
            self.lower(i32::from(partition), offset.get());
        }
    }

    /// The seek list for the partitions still owned, or `None` when nothing needs a seek. Fails only
    /// on a negative offset, which a polled message never carries.
    pub(crate) fn seek_list(
        &self,
        topic: &str,
        owned: &HashSet<i32>,
    ) -> KafkaResult<Option<TopicPartitionList>> {
        let mut tpl = TopicPartitionList::new();
        for (&partition, &offset) in &self.0 {
            if owned.contains(&partition) {
                tpl.add_partition_offset(topic, partition, Offset::Offset(offset))?;
            }
        }
        Ok((tpl.count() > 0).then_some(tpl))
    }

    fn lower(&mut self, partition: i32, offset: i64) {
        self.0
            .entry(partition)
            .and_modify(|held| *held = (*held).min(offset))
            .or_insert(offset);
    }
}

/// Where the events consumer's boot stands. Nothing folds before [`BootPhase::Live`]. A pending
/// checkpoint restore rides along until the rewind commits its positions and settles it.
pub(crate) enum BootPhase {
    /// Waiting for two consecutive polls to report the same non-empty assignment.
    Settling {
        previous: Option<HashSet<i32>>,
        resume: ResumePoints,
        restore: Option<PendingRestore>,
    },
    /// Recovery ran. The owned partitions must seek before anything folds.
    Rewinding {
        resume: ResumePoints,
        restore: Option<PendingRestore>,
    },
    /// A restored position expired during boot and the process is stopping. Nothing seeks, settles
    /// or folds, and the restore marker keeps the next boot on the restore path.
    Halted,
    Live,
}

impl BootPhase {
    pub(crate) fn settling(restore: Option<PendingRestore>) -> Self {
        Self::Settling {
            previous: None,
            resume: ResumePoints::default(),
            restore,
        }
    }
}

/// Returns `true` once the same non-empty assignment is seen on two consecutive polls. An empty or
/// changing assignment is not yet settled; a cooperative-incremental assign re-baselines until stable.
pub(crate) fn boot_assignment_settled(
    assignment: &HashSet<i32>,
    prev: &mut Option<HashSet<i32>>,
) -> bool {
    if assignment.is_empty() {
        return false;
    }
    if prev.as_ref() != Some(assignment) {
        *prev = Some(assignment.clone());
        return false;
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::consumers::events::CohortStreamEvent;

    const TOPIC: &str = "cohort_stream_events";

    fn polled(partition: i32, offset: i64) -> ConsumedEvent {
        ConsumedEvent {
            event: CohortStreamEvent {
                team_id: 7,
                person_id: "p".to_string(),
                distinct_id: "d".to_string(),
                uuid: "u".to_string(),
                event: "$pageview".to_string(),
                timestamp: "2026-05-26 12:34:56.789000".to_string(),
                properties: None,
                person_properties: None,
                elements_chain: None,
                source_offset: offset,
                source_partition: 0,
                redirected_from: None,
                redirect_hops: 0,
            },
            partition,
            offset,
            broker_ts_ms: None,
        }
    }

    fn sought(seek_list: Option<TopicPartitionList>) -> Option<BTreeMap<i32, i64>> {
        seek_list.map(|tpl| {
            tpl.elements_for_topic(TOPIC)
                .iter()
                .map(|elem| match elem.offset() {
                    Offset::Offset(offset) => (elem.partition(), offset),
                    other => panic!("boot seeks an absolute offset, got {other:?}"),
                })
                .collect()
        })
    }

    struct Case {
        name: &'static str,
        polls: &'static [&'static [(i32, i64)]],
        restored: Option<&'static [(u16, i64)]>,
        owned: &'static [i32],
        expected: Option<&'static [(i32, i64)]>,
    }

    #[test]
    fn resume_points_seek_every_owned_partition_to_its_first_unfolded_offset() {
        let cases = [
            Case {
                name: "the lowest polled offset per partition wins across polls",
                polls: &[&[(0, 5), (1, 7)], &[(0, 3), (0, 6), (1, 8)]],
                restored: None,
                owned: &[0, 1],
                expected: Some(&[(0, 3), (1, 7)]),
            },
            Case {
                name: "a restore lowers held partitions and adds owned ones boot never polled",
                polls: &[&[(0, 10), (1, 2)]],
                restored: Some(&[(0, 4), (1, 6), (2, 9), (3, 1)]),
                owned: &[0, 1, 2],
                expected: Some(&[(0, 4), (1, 2), (2, 9)]),
            },
            Case {
                name: "a partition revoked during boot is not sought",
                polls: &[&[(0, 3), (1, 7)]],
                restored: None,
                owned: &[1],
                expected: Some(&[(1, 7)]),
            },
            Case {
                name: "nothing held needs no seek",
                polls: &[&[]],
                restored: None,
                owned: &[0, 1],
                expected: None,
            },
            Case {
                name: "only unowned partitions held needs no seek",
                polls: &[&[(2, 4)]],
                restored: Some(&[(3, 1)]),
                owned: &[0],
                expected: None,
            },
        ];

        for case in cases {
            let owned: HashSet<i32> = case.owned.iter().copied().collect();
            let mut resume = ResumePoints::default();
            for poll in case.polls {
                let events: Vec<ConsumedEvent> = poll
                    .iter()
                    .map(|&(partition, offset)| polled(partition, offset))
                    .collect();
                resume.hold_back(&events);
            }
            if let Some(offsets) = case.restored {
                let positions = offsets
                    .iter()
                    .map(|&(partition, offset)| {
                        (partition, ResumeOffset::try_from(offset).unwrap())
                    })
                    .collect();
                resume.rewind_to(&positions);
            }

            assert_eq!(
                sought(resume.seek_list(TOPIC, &owned).unwrap()),
                case.expected
                    .map(|offsets| offsets.iter().copied().collect()),
                "{}",
                case.name,
            );
        }
    }

    #[test]
    fn boot_assignment_settled_requires_a_stable_non_empty_assignment() {
        let mut prev: Option<HashSet<i32>> = None;

        assert!(!boot_assignment_settled(&HashSet::new(), &mut prev));
        assert_eq!(prev, None);

        let first: HashSet<i32> = [0].into_iter().collect();
        assert!(!boot_assignment_settled(&first, &mut prev));
        assert_eq!(prev.as_ref(), Some(&first));

        let second: HashSet<i32> = [0, 1].into_iter().collect();
        assert!(!boot_assignment_settled(&second, &mut prev));
        assert_eq!(prev.as_ref(), Some(&second));

        assert!(boot_assignment_settled(&second, &mut prev));
    }
}
