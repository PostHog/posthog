//! Boot recovery for the events consumer.
//!
//! With durable restore, the store reopens with state the broker's committed offsets may not
//! match. The consumer reclaims unowned slices and redrives the merge outbox before its first
//! poll. After a checkpoint restore, nothing may fold until it has also sought every owned
//! partition back to its restored position, or to the first event it polled and did not fold. A
//! fold before that would set per-key replay marks above offsets that are fetched again later, so
//! the second fetch would skip those events as replays.

use std::collections::{BTreeMap, HashSet};

use rdkafka::error::KafkaResult;

use crate::consumers::events::ConsumedEvent;
use crate::partitions::{CommitStamp, ResumeOffset, StampedList};
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

    /// Lowers each partition's resume point to the position its restore plan keeps, so a restored
    /// store never resumes past its checkpoint. The seek list leaves out the ones this consumer does
    /// not own.
    pub(crate) fn rewind_to(&mut self, positions: &BTreeMap<u16, ResumeOffset>) {
        for (&partition, &offset) in positions {
            self.lower(i32::from(partition), offset.get());
        }
    }

    /// The seek list for the partitions still owned, stamped for the restore's commit, or `None`
    /// when nothing needs a seek. Fails only on a negative offset, which a polled message never
    /// carries.
    pub(crate) fn seek_list(
        &self,
        stamp: &CommitStamp,
        topic: &str,
        owned: &HashSet<i32>,
    ) -> KafkaResult<Option<StampedList>> {
        let positions: Vec<(i32, i64)> = self
            .0
            .iter()
            .filter(|(partition, _)| owned.contains(partition))
            .map(|(&partition, &offset)| (partition, offset))
            .collect();
        if positions.is_empty() {
            return Ok(None);
        }
        stamp.list(topic, positions).map(Some)
    }

    fn lower(&mut self, partition: i32, offset: i64) {
        self.0
            .entry(partition)
            .and_modify(|held| *held = (*held).min(offset))
            .or_insert(offset);
    }
}

/// Where the events consumer's boot stands. Nothing folds before [`BootPhase::Live`].
pub(crate) enum BootPhase {
    /// Recovery ran on a restored store. The owned partitions must seek, and the rewind must commit
    /// the restore's positions and finish it, before anything folds.
    Rewinding {
        resume: ResumePoints,
        restore: Box<PendingRestore>,
    },
    /// A restored position expired during boot and the process is stopping. Nothing seeks or folds,
    /// and the restore marker keeps the next boot on the restore path.
    Halted,
    Live,
}

#[cfg(test)]
mod tests {
    use super::*;
    use rdkafka::Offset;

    use crate::consumers::events::CohortStreamEvent;
    use crate::partitions::PartitionOwnership;

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

    fn sought(seek_list: Option<StampedList>) -> Option<BTreeMap<i32, i64>> {
        seek_list.map(|list| {
            list.as_list()
                .elements_for_topic(TOPIC)
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
                name: "a partition another pod owns is not sought",
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

            let stamp = CommitStamp::for_test(PartitionOwnership::single(4));
            assert_eq!(
                sought(resume.seek_list(&stamp, TOPIC, &owned).unwrap()),
                case.expected
                    .map(|offsets| offsets.iter().copied().collect()),
                "{}",
                case.name,
            );
        }
    }
}
