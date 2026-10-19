use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Charge, Offset, Rejection, TopicOffsetLedger, TopicPartition};

use super::{Admission, ChargedSlice, Commit, PartitionBudget, Pause, Settlement, Uncommitted};
use crate::commit_pacer::CommitPacer;
use crate::ledger_rejection::{report_rejection, RejectedSlice};
use crate::order_sentinel::OffsetSpan;
use crate::partition_budget::BudgetLimits;

pub(crate) struct GroupSettlement<B: Admission = PartitionBudget> {
    budget: B,
}

impl GroupSettlement {
    pub(crate) fn new(
        ledger: Arc<TopicOffsetLedger>,
        commit_interval: Duration,
        limits: BudgetLimits,
    ) -> Self {
        Self {
            budget: PartitionBudget::new(
                Uncommitted::new(ledger, CommitPacer::every(commit_interval)),
                limits,
            ),
        }
    }
}

impl<B: Admission + 'static> Settlement for GroupSettlement<B> {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Option<Pause>, Rejection> {
        self.budget.charge(topic_partition, generation, charges)
    }

    fn settle_run(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: &[Offset],
    ) -> anyhow::Result<()> {
        if let Err(rejection) =
            self.budget
                .settled(topic_partition, generation, offsets.iter().copied())
        {
            report_rejection(
                "settle",
                topic_partition,
                rejection,
                RejectedSlice::settled(&OffsetSpan {
                    first: offsets[0].0,
                    last: offsets[offsets.len() - 1].0,
                }),
            )?;
        }
        Ok(())
    }

    fn settle_poll(&self, _slices: &[ChargedSlice<'_>]) -> anyhow::Result<()> {
        Ok(())
    }

    fn take_due(&self, now: Instant) -> Option<Commit> {
        self.budget.take_due(now)
    }

    fn take_all(&self) -> Option<Commit> {
        self.budget.take_all()
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.budget.forget_partitions(topic_partitions);
    }

    fn paused(&self) -> Vec<TopicPartition> {
        self.budget.paused()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::num::NonZeroU64;

    use common_kafka_consumer::{Held, LedgerError};

    use super::super::fakes::{FakeAdmission, Settled};
    use super::*;

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    fn settlement() -> GroupSettlement<FakeAdmission> {
        GroupSettlement {
            budget: FakeAdmission::default(),
        }
    }

    #[test]
    fn a_run_reaches_the_admission_under_its_generation() {
        let settlement = settlement();

        settlement
            .settle_run(&p0(), 3, &[Offset(10), Offset(11)])
            .unwrap();

        assert_eq!(
            settlement.budget.settled(),
            vec![Settled {
                topic_partition: p0(),
                generation: 3,
                offsets: vec![Offset(10), Offset(11)],
            }]
        );
    }

    struct RejectedRun {
        rejection: Rejection,
        expected_error: bool,
    }

    #[rstest::rstest]
    #[case::stale(RejectedRun {
        rejection: Rejection::Stale { stamp: 0, generation: 1 },
        expected_error: false,
    })]
    #[case::violation(RejectedRun {
        rejection: Rejection::Violation {
            error: LedgerError::CompletedTwice { offset: Offset(10) },
            stamp: 0,
            generation: 0,
            held: Held::default(),
        },
        expected_error: true,
    })]
    fn only_a_violating_run_fails(#[case] run: RejectedRun) {
        let settlement = settlement();
        settlement.budget.settle_returns(Err(run.rejection));

        assert_eq!(
            settlement.settle_run(&p0(), 0, &[Offset(10)]).is_err(),
            run.expected_error
        );
    }

    #[test]
    fn a_retired_poll_settles_nothing() {
        let settlement = settlement();
        let charges = [(Offset(10), Charge::ZERO)];

        settlement
            .settle_poll(&[ChargedSlice {
                topic_partition: &p0(),
                generation: 0,
                span: OffsetSpan {
                    first: 10,
                    last: 10,
                },
                charges: &charges,
            }])
            .unwrap();

        assert!(settlement.budget.settled().is_empty());
    }

    #[test]
    fn the_admissions_decisions_reach_the_consumer() {
        let settlement = settlement();
        settlement.budget.charge_returns(Ok(Some(Pause)));
        settlement.budget.pauses(&[p0()]);
        settlement.budget.take_hands_out(Commit {
            offsets: HashMap::from([(p0(), Offset(11))]),
            resume: vec![p0()],
        });

        assert_eq!(settlement.charge(&p0(), 0, &[]), Ok(Some(Pause)));
        assert_eq!(settlement.paused(), vec![p0()]);
        let commit = settlement.take_due(Instant::now()).expect("handed out");
        assert_eq!(commit.offsets, HashMap::from([(p0(), Offset(11))]));
        assert_eq!(commit.resume, vec![p0()]);
        settlement.forget_partitions(&[p0()]);
        assert_eq!(settlement.budget.forgotten(), vec![p0()]);
    }

    // Composition: the real budget, accounting, ledger and pacer together.

    fn real_hourly_settlement(limits: BudgetLimits) -> (Arc<TopicOffsetLedger>, GroupSettlement) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement =
            GroupSettlement::new(Arc::clone(&ledger), Duration::from_secs(3600), limits);
        (ledger, settlement)
    }

    #[test]
    fn a_take_the_interval_holds_counts_toward_the_pause() {
        let (_, settlement) = real_hourly_settlement(
            BudgetLimits::new(NonZeroU64::new(10), None, 0.8).expect("valid limits"),
        );
        let first = [(
            Offset(0),
            Charge {
                events: 6,
                bytes: 0,
            },
        )];
        settlement.charge(&p0(), 0, &first).unwrap();
        settlement.settle_run(&p0(), 0, &[Offset(0)]).unwrap();

        let next = [(
            Offset(1),
            Charge {
                events: 4,
                bytes: 0,
            },
        )];
        assert_eq!(settlement.charge(&p0(), 0, &next), Ok(Some(Pause)));
    }

    #[test]
    fn a_run_settled_twice_fails_and_keeps_the_frontier_taken_before_it() {
        let (ledger, settlement) = real_hourly_settlement(BudgetLimits::unset());
        super::super::charge_offsets(&ledger, &p0(), 0, &[10, 11]);
        settlement.settle_run(&p0(), 0, &[Offset(10)]).unwrap();

        assert!(settlement.settle_run(&p0(), 0, &[Offset(10)]).is_err());

        assert_eq!(
            settlement.take_all().map(|commit| commit.offsets),
            Some(HashMap::from([(p0(), Offset(11))])),
            "offset 10 completed before the violation"
        );
    }
}
