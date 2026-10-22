use std::sync::Arc;
use std::time::Instant;

use common_kafka_consumer::{Charge, Offset, Rejection, TopicOffsetLedger, TopicPartition};
use metrics::counter;
use tracing::warn;

use super::{offsets, Accounting, ChargedSlice, Commit, Pause, Settlement, Uncommitted};
use crate::commit_pacer::CommitPacer;
use crate::ledger_rejection::{report_rejection, RejectedSlice};

pub(crate) struct PollSettlement<A: Accounting = Uncommitted> {
    uncommitted: A,
}

impl PollSettlement {
    pub(crate) fn new(ledger: Arc<TopicOffsetLedger>) -> Self {
        Self {
            uncommitted: Uncommitted::new(ledger, CommitPacer::immediate()),
        }
    }
}

impl<A: Accounting + 'static> Settlement for PollSettlement<A> {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Option<Pause>, Rejection> {
        self.uncommitted
            .charge(topic_partition, generation, charges)
            .map(|_| None)
    }

    fn settle_run(
        &self,
        _topic_partition: &TopicPartition,
        _generation: u64,
        _offsets: &[Offset],
    ) -> anyhow::Result<()> {
        Ok(())
    }

    fn settle_poll(&self, slices: &[ChargedSlice<'_>]) -> anyhow::Result<()> {
        if slices.is_empty() {
            // Unreachable: a batch always holds a message. Counted so that "no
            // empty commits" is measured, not assumed.
            counter!("ingestion_consumer_commit_violations_total", "kind" => "empty").increment(1);
            warn!("Poll settled with no partitions");
            return Ok(());
        }

        if let Some(no_frontier) = settle_slices(&self.uncommitted, slices)? {
            let reason = no_frontier.reason();
            counter!("ingestion_consumer_commits_skipped_total", "reason" => reason).increment(1);
            warn!(reason, "Poll handed over no frontier; nothing to commit");
        }
        Ok(())
    }

    fn take_due(&self, now: Instant) -> Option<Commit> {
        let handed_out = self.uncommitted.take_due(now)?;
        Some(Commit {
            offsets: offsets(handed_out),
            resume: Vec::new(),
        })
    }

    fn take_all(&self) -> Option<Commit> {
        let handed_out = self.uncommitted.take_all()?;
        Some(Commit {
            offsets: offsets(handed_out),
            resume: Vec::new(),
        })
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.uncommitted.forget_partitions(topic_partitions);
    }
}

enum NoFrontier {
    EveryPartitionRejected,
    BehindAnEarlierPoll,
}

impl NoFrontier {
    fn reason(self) -> &'static str {
        match self {
            Self::EveryPartitionRejected => "rejected",
            Self::BehindAnEarlierPoll => "no_frontier",
        }
    }
}

fn settle_slices(
    uncommitted: &impl Accounting,
    slices: &[ChargedSlice<'_>],
) -> anyhow::Result<Option<NoFrontier>> {
    let mut settled = false;
    let mut handed_over = false;
    for slice in slices {
        let frontier = match uncommitted.settled(
            slice.topic_partition,
            slice.generation,
            slice.charges.iter().map(|(offset, _)| *offset),
        ) {
            Ok(frontier) => frontier,
            Err(rejection) => {
                report_rejection(
                    "settle",
                    slice.topic_partition,
                    rejection,
                    RejectedSlice::settled(&slice.span),
                )?;
                continue;
            }
        };
        settled = true;
        handed_over |= frontier.is_some();
    }
    Ok(match (handed_over, settled) {
        (true, _) => None,
        (false, true) => Some(NoFrontier::BehindAnEarlierPoll),
        (false, false) => Some(NoFrontier::EveryPartitionRejected),
    })
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use common_kafka_consumer::{Held, LedgerError};
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};

    use super::super::fakes::{FakeAccounting, Settled};
    use super::super::HandedOut;
    use super::*;
    use crate::order_sentinel::OffsetSpan;

    fn p(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    fn settlement() -> (PollSettlement<FakeAccounting>, FakeAccounting) {
        let accounting = FakeAccounting::default();
        let settlement = PollSettlement {
            uncommitted: accounting.clone(),
        };
        (settlement, accounting)
    }

    struct Slice {
        topic_partition: TopicPartition,
        charges: Vec<(Offset, Charge)>,
    }

    impl Slice {
        fn of(partition: i32, offsets: &[i64]) -> Self {
            Self {
                topic_partition: p(partition),
                charges: offsets
                    .iter()
                    .map(|&offset| (Offset(offset), Charge::ZERO))
                    .collect(),
            }
        }

        fn charged(&self) -> ChargedSlice<'_> {
            ChargedSlice {
                topic_partition: &self.topic_partition,
                generation: 2,
                span: OffsetSpan {
                    first: self.charges[0].0 .0,
                    last: self.charges[self.charges.len() - 1].0 .0,
                },
                charges: &self.charges,
            }
        }
    }

    fn stale() -> Rejection {
        Rejection::Stale {
            stamp: 0,
            generation: 1,
        }
    }

    fn settle_poll_counting_skips(
        settlement: &PollSettlement<FakeAccounting>,
        slices: &[Slice],
    ) -> (anyhow::Result<()>, Vec<String>) {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let charged: Vec<ChargedSlice<'_>> = slices.iter().map(Slice::charged).collect();
        let result = metrics::with_local_recorder(&recorder, || settlement.settle_poll(&charged));
        let skipped = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, _, _, value)| {
                key.key().name() == "ingestion_consumer_commits_skipped_total"
                    && matches!(value, DebugValue::Counter(count) if *count > 0)
            })
            .filter_map(|(key, _, _, _)| {
                key.key()
                    .labels()
                    .find(|label| label.key() == "reason")
                    .map(|label| label.value().to_string())
            })
            .collect();
        (result, skipped)
    }

    #[test]
    fn a_retired_poll_settles_each_slice_under_its_generation() {
        let (settlement, accounting) = settlement();

        settle_poll_counting_skips(&settlement, &[Slice::of(0, &[10, 11]), Slice::of(1, &[20])])
            .0
            .unwrap();

        assert_eq!(
            accounting.settles_seen(),
            vec![
                Settled {
                    topic_partition: p(0),
                    generation: 2,
                    offsets: vec![Offset(10), Offset(11)],
                },
                Settled {
                    topic_partition: p(1),
                    generation: 2,
                    offsets: vec![Offset(20)],
                },
            ]
        );
    }

    struct RetiredPoll {
        settles: Vec<Result<Option<Offset>, Rejection>>,
        expected_skip: Option<&'static str>,
    }

    #[rstest::rstest]
    #[case::a_frontier(RetiredPoll { settles: vec![Ok(Some(Offset(12)))], expected_skip: None })]
    #[case::behind_an_earlier_poll(RetiredPoll { settles: vec![Ok(None)], expected_skip: Some("no_frontier") })]
    #[case::every_slice_stale(RetiredPoll { settles: vec![Err(stale())], expected_skip: Some("rejected") })]
    #[case::one_stale_one_frontier(RetiredPoll { settles: vec![Err(stale()), Ok(Some(Offset(21)))], expected_skip: None })]
    #[case::one_stale_one_behind(RetiredPoll { settles: vec![Err(stale()), Ok(None)], expected_skip: Some("no_frontier") })]
    fn a_retired_poll_that_hands_over_no_frontier_counts_why(#[case] poll: RetiredPoll) {
        let (settlement, accounting) = settlement();
        let slices: Vec<Slice> = (0..poll.settles.len() as i32)
            .map(|partition| Slice::of(partition, &[10]))
            .collect();
        for result in poll.settles {
            accounting.settle_returns(result);
        }

        let (result, skipped) = settle_poll_counting_skips(&settlement, &slices);

        result.unwrap();
        assert_eq!(
            skipped,
            poll.expected_skip
                .into_iter()
                .map(String::from)
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn a_violating_slice_fails_the_poll_and_stops_settling() {
        let (settlement, accounting) = settlement();
        accounting.settle_returns(Err(Rejection::Violation {
            error: LedgerError::CompletedTwice { offset: Offset(10) },
            stamp: 2,
            generation: 2,
            held: Held::default(),
        }));

        let (result, _) =
            settle_poll_counting_skips(&settlement, &[Slice::of(0, &[10]), Slice::of(1, &[20])]);

        assert!(result.is_err());
        assert_eq!(accounting.settles_seen().len(), 1);
    }

    #[test]
    fn a_run_settles_nothing_before_its_poll_retires() {
        let (settlement, accounting) = settlement();

        settlement.settle_run(&p(0), 2, &[Offset(10)]).unwrap();

        assert!(accounting.settles_seen().is_empty());
    }

    #[test]
    fn a_charge_never_pauses() {
        let (settlement, accounting) = settlement();
        accounting.charge_returns(Ok(Held {
            offsets: usize::MAX,
            charge: Charge {
                events: u64::MAX,
                bytes: u64::MAX,
            },
        }));

        assert_eq!(settlement.charge(&p(0), 2, &[]), Ok(None));
    }

    #[test]
    fn a_hand_out_commits_without_resuming() {
        let (settlement, accounting) = settlement();
        accounting.take_hands_out(HashMap::from([(
            p(0),
            HandedOut {
                offset: Offset(12),
                remaining: Held::default(),
            },
        )]));

        let commit = settlement.take_due(Instant::now()).expect("handed out");

        assert_eq!(commit.offsets, HashMap::from([(p(0), Offset(12))]));
        assert!(commit.resume.is_empty());
    }
}

#[cfg(test)]
mod integration_tests {
    use std::collections::HashMap;

    use common_kafka_consumer::Charge;

    use super::*;
    use crate::order_sentinel::OffsetSpan;

    fn settlement() -> (Arc<TopicOffsetLedger>, PollSettlement) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement = PollSettlement::new(Arc::clone(&ledger));
        (ledger, settlement)
    }

    struct Charged {
        topic_partition: TopicPartition,
        generation: u64,
        span: OffsetSpan,
        charges: Vec<(Offset, Charge)>,
    }

    impl Charged {
        fn slice(&self) -> ChargedSlice<'_> {
            ChargedSlice {
                topic_partition: &self.topic_partition,
                generation: self.generation,
                span: self.span,
                charges: &self.charges,
            }
        }
    }

    fn charged(ledger: &TopicOffsetLedger, partition: i32, first: i64, last: i64) -> Charged {
        let topic_partition = TopicPartition::new("test", partition);
        let generation = ledger.generation(&topic_partition);
        let charges: Vec<(Offset, Charge)> = (first..=last)
            .map(|offset| (Offset(offset), Charge::ZERO))
            .collect();
        ledger
            .charge(&topic_partition, generation, charges.iter().copied())
            .expect("charge");
        Charged {
            topic_partition,
            generation,
            span: OffsetSpan { first, last },
            charges,
        }
    }

    #[test]
    fn a_retired_poll_makes_each_partitions_frontier_due() {
        let (ledger, settlement) = settlement();
        let p0 = charged(&ledger, 0, 10, 11);
        let p1 = charged(&ledger, 1, 20, 21);

        settlement.settle_poll(&[p0.slice(), p1.slice()]).unwrap();

        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([
                (p0.topic_partition, Offset(12)),
                (p1.topic_partition, Offset(22)),
            ]))
        );
    }

    #[test]
    fn a_poll_behind_an_earlier_one_becomes_due_when_the_earlier_retires() {
        let (ledger, settlement) = settlement();
        let older = charged(&ledger, 0, 10, 11);
        let newer = charged(&ledger, 0, 12, 13);

        settlement.settle_poll(&[newer.slice()]).unwrap();
        assert!(settlement.take_due(Instant::now()).is_none());

        settlement.settle_poll(&[older.slice()]).unwrap();
        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(older.topic_partition, Offset(14))]))
        );
    }

    #[test]
    fn a_stale_poll_makes_nothing_due() {
        let (ledger, settlement) = settlement();
        let poll = charged(&ledger, 0, 10, 11);
        // The partition left and came back while the poll was in flight.
        ledger.forget_partitions([("test", 0)]);

        settlement.settle_poll(&[poll.slice()]).unwrap();

        assert!(settlement.take_due(Instant::now()).is_none());
    }
}
