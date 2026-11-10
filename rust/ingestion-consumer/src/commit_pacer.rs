//! Commit pacing for the ingestion consumer. A settlement hands over each
//! partition's frontier as it takes it from the ledger; the consumer asks the
//! pacer what is due and commits that in one call. The pacer holds no I/O.
//!
//! The pacer keeps the latest frontier per partition, with the charge of every
//! take since the last commit, and hands them out at most once per interval.
//! A zero interval makes every take due.
//!
//! The broker can reject a commit the client already sent, and librdkafka
//! does not retry a manual commit rejected with `STALE_MEMBER_EPOCH`. So the
//! pacer re-sends each partition's last handed-out offset on the next
//! [`RESENDS`] due takes. Committing an offset again is idempotent.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Held, Offset, TakenFrontier, TopicPartition};

/// How many due takes re-send a handed-out offset with nothing newer. At the
/// default 500 ms interval that covers 2 s, against the heartbeat round trip
/// that delivers a new member epoch after a rejection.
pub const RESENDS: u32 = 4;

pub struct CommitPacer {
    interval: Duration,
    frontiers: HashMap<TopicPartition, PendingFrontier>,
    handed_out: HashMap<TopicPartition, HandedOutFrontier>,
    last_take: Option<Instant>,
}

struct PendingFrontier {
    offset: Offset,
    held: Held,
}

struct HandedOutFrontier {
    offset: Offset,
    resends_left: u32,
}

impl CommitPacer {
    pub fn every(interval: Duration) -> Self {
        Self {
            interval,
            frontiers: HashMap::new(),
            handed_out: HashMap::new(),
            last_take: None,
        }
    }

    /// Replace the partition's pending offset; frontiers only move forward.
    pub fn advance_frontier(&mut self, topic_partition: &TopicPartition, taken: TakenFrontier) {
        let taken_offsets = usize::try_from(taken.offset - taken.first)
            .expect("a frontier is above its window base");
        let pending = self
            .frontiers
            .entry(topic_partition.clone())
            .or_insert(PendingFrontier {
                offset: taken.offset,
                held: Held::default(),
            });
        pending.offset = taken.offset;
        pending.held += Held {
            offsets: taken_offsets,
            charge: taken.charge,
        };
    }

    pub fn pending(&self, topic_partition: &TopicPartition) -> Held {
        self.frontiers
            .get(topic_partition)
            .map(|pending| pending.held)
            .unwrap_or_default()
    }

    /// Partitions leaving the assignment: drop whatever is held for them. A
    /// commit issued for a partition another member now owns could move the
    /// group's offset back behind that member's progress, so the frontier
    /// and the last handed-out offset go with the partition.
    pub fn forget_partitions(&mut self, topic_partitions: &[TopicPartition]) {
        for topic_partition in topic_partitions {
            self.frontiers.remove(topic_partition);
            self.handed_out.remove(topic_partition);
        }
    }

    pub fn take_due(&mut self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        let resend_due = self
            .handed_out
            .values()
            .any(|handed_out| handed_out.resends_left > 0);
        if self.frontiers.is_empty() && !resend_due {
            return None;
        }
        if self
            .last_take
            .is_some_and(|last| now.duration_since(last) < self.interval)
        {
            return None;
        }
        self.last_take = Some(now);
        let mut due = self.take_pending();
        for (topic_partition, handed_out) in &mut self.handed_out {
            if handed_out.resends_left == 0 || due.contains_key(topic_partition) {
                continue;
            }
            handed_out.resends_left -= 1;
            due.insert(topic_partition.clone(), handed_out.offset);
        }
        Some(due)
    }

    /// Every pending frontier, and the last handed-out offset of every other
    /// partition, whatever its re-send count.
    pub fn take_all(&mut self) -> Option<HashMap<TopicPartition, Offset>> {
        let mut due = self.take_pending();
        for (topic_partition, handed_out) in &self.handed_out {
            due.entry(topic_partition.clone())
                .or_insert(handed_out.offset);
        }
        (!due.is_empty()).then_some(due)
    }

    fn take_pending(&mut self) -> HashMap<TopicPartition, Offset> {
        let mut due = HashMap::with_capacity(self.frontiers.len());
        for (topic_partition, pending) in self.frontiers.drain() {
            self.handed_out.insert(
                topic_partition.clone(),
                HandedOutFrontier {
                    offset: pending.offset,
                    resends_left: RESENDS,
                },
            );
            due.insert(topic_partition, pending.offset);
        }
        due
    }
}

#[cfg(test)]
pub(crate) mod test_support {
    use common_kafka_consumer::Charge;

    use super::*;

    pub(crate) fn tp(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    /// A take that started at window base `first` and reached `offset`.
    pub(crate) fn taken(first: i64, offset: i64) -> TakenFrontier {
        TakenFrontier {
            first: Offset(first),
            offset: Offset(offset),
            charge: Charge::ZERO,
            gap_offset_count: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::*;
    use super::*;

    #[test]
    fn a_pending_frontier_is_due_on_the_next_take() {
        let mut pacer = CommitPacer::every(Duration::ZERO);
        pacer.advance_frontier(&tp(0), taken(0, 10));

        let offsets = pacer.take_due(Instant::now()).expect("due");
        assert_eq!(offsets, HashMap::from([(tp(0), Offset(10))]));
    }

    #[test]
    fn a_handed_out_offset_is_re_sent_on_the_next_due_takes_until_the_count_runs_out() {
        let mut pacer = CommitPacer::every(Duration::ZERO);
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.take_due(Instant::now()).expect("due");

        for _ in 0..RESENDS {
            assert_eq!(
                pacer.take_due(Instant::now()),
                Some(HashMap::from([(tp(0), Offset(10))]))
            );
        }
        assert!(pacer.take_due(Instant::now()).is_none());
        assert_eq!(
            pacer.take_all(),
            Some(HashMap::from([(tp(0), Offset(10))])),
            "a take of everything carries the last offset past its count"
        );
    }

    #[test]
    fn a_re_send_waits_for_the_interval() {
        let mut pacer = CommitPacer::every(Duration::from_millis(500));
        let start = Instant::now();
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.take_due(start).expect("due");

        assert!(pacer.take_due(start + Duration::from_millis(100)).is_none());
        assert_eq!(
            pacer.take_due(start + Duration::from_millis(500)),
            Some(HashMap::from([(tp(0), Offset(10))]))
        );
    }

    #[test]
    fn a_newer_frontier_supersedes_the_re_send_and_restarts_its_count() {
        let mut pacer = CommitPacer::every(Duration::ZERO);
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.take_due(Instant::now()).expect("due");
        pacer.take_due(Instant::now()).expect("a re-send");

        pacer.advance_frontier(&tp(0), taken(10, 12));
        assert_eq!(
            pacer.take_due(Instant::now()),
            Some(HashMap::from([(tp(0), Offset(12))]))
        );
        for _ in 0..RESENDS {
            assert_eq!(
                pacer.take_due(Instant::now()),
                Some(HashMap::from([(tp(0), Offset(12))]))
            );
        }
        assert!(pacer.take_due(Instant::now()).is_none());
    }

    #[test]
    fn a_re_send_rides_with_another_partitions_frontier() {
        let mut pacer = CommitPacer::every(Duration::ZERO);
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.take_due(Instant::now()).expect("due");

        pacer.advance_frontier(&tp(1), taken(0, 20));
        assert_eq!(
            pacer.take_due(Instant::now()),
            Some(HashMap::from([(tp(0), Offset(10)), (tp(1), Offset(20))]))
        );
    }

    #[test]
    fn a_forgotten_partition_is_not_re_sent() {
        let mut pacer = CommitPacer::every(Duration::ZERO);
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.advance_frontier(&tp(1), taken(0, 20));
        pacer.take_due(Instant::now()).expect("due");

        pacer.forget_partitions(&[tp(0)]);

        assert_eq!(
            pacer.take_due(Instant::now()),
            Some(HashMap::from([(tp(1), Offset(20))]))
        );
        assert_eq!(pacer.take_all(), Some(HashMap::from([(tp(1), Offset(20))])));
        pacer.forget_partitions(&[tp(1)]);
        assert!(pacer.take_all().is_none());
    }

    #[test]
    fn the_latest_frontier_per_partition_is_what_goes_out() {
        let mut pacer = CommitPacer::every(Duration::ZERO);
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.advance_frontier(&tp(1), taken(0, 20));
        pacer.advance_frontier(&tp(0), taken(10, 12));

        let offsets = pacer.take_due(Instant::now()).expect("due");
        assert_eq!(
            offsets,
            HashMap::from([(tp(0), Offset(12)), (tp(1), Offset(20))])
        );
    }

    #[test]
    fn a_forgotten_partition_is_not_committed() {
        let mut pacer = CommitPacer::every(Duration::ZERO);
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.advance_frontier(&tp(1), taken(0, 20));

        pacer.forget_partitions(&[tp(0)]);

        assert_eq!(
            pacer.take_due(Instant::now()).expect("due"),
            HashMap::from([(tp(1), Offset(20))])
        );
    }

    #[test]
    fn frontiers_handed_over_within_the_interval_wait_for_it() {
        let mut pacer = CommitPacer::every(Duration::from_millis(500));
        let start = Instant::now();

        pacer.advance_frontier(&tp(0), taken(0, 10));
        assert!(
            pacer.take_due(start).is_some(),
            "the first frontier goes out at once"
        );

        pacer.advance_frontier(&tp(0), taken(10, 12));
        pacer.advance_frontier(&tp(1), taken(0, 20));
        assert!(
            pacer.take_due(start + Duration::from_millis(100)).is_none(),
            "inside the interval nothing goes out"
        );
        assert_eq!(
            pacer
                .take_due(start + Duration::from_millis(500))
                .expect("due"),
            HashMap::from([(tp(0), Offset(12)), (tp(1), Offset(20))]),
            "one take carries everything that arrived during the interval"
        );
    }

    #[test]
    fn an_empty_take_does_not_start_the_interval() {
        let mut pacer = CommitPacer::every(Duration::from_millis(500));
        let start = Instant::now();
        assert!(pacer.take_due(start).is_none());

        pacer.advance_frontier(&tp(0), taken(0, 10));
        assert!(pacer.take_due(start + Duration::from_millis(100)).is_some());
    }

    #[test]
    fn take_all_ignores_the_interval() {
        let mut pacer = CommitPacer::every(Duration::from_secs(3600));
        let start = Instant::now();
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.take_due(start).expect("due");

        pacer.advance_frontier(&tp(0), taken(10, 12));
        assert!(pacer.take_due(start + Duration::from_secs(1)).is_none());
        assert_eq!(
            pacer.take_all().expect("pending"),
            HashMap::from([(tp(0), Offset(12))])
        );
    }
}
