use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Charge, Offset, Rejection, TopicOffsetLedger, TopicPartition};

use super::{
    Accounting, Admission, Charged, ChargedSlice, Commit, PartitionBudget, RunOutcome, Settlement,
    Uncommitted,
};
use crate::commit_pacer::CommitPacer;
use crate::ledger_rejection::{report_rejection, RejectedSlice};
use crate::order_sentinel::OffsetSpan;
use crate::partition_budget::BudgetLimits;

pub(crate) struct GroupSettlement<A: Accounting = Uncommitted, D: Admission = PartitionBudget> {
    accounting: A,
    admission: D,
}

impl GroupSettlement {
    pub(crate) fn new(
        ledger: Arc<TopicOffsetLedger>,
        commit_interval: Duration,
        limits: BudgetLimits,
    ) -> Self {
        Self {
            accounting: Uncommitted::new(ledger, CommitPacer::every(commit_interval)),
            admission: PartitionBudget::new(limits),
        }
    }
}

impl<A: Accounting + 'static, D: Admission + 'static> Settlement for GroupSettlement<A, D> {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Charged, Rejection> {
        let uncommitted = self
            .accounting
            .charge(topic_partition, generation, charges)?
            .charge;
        Ok(Charged {
            uncommitted,
            pause: self.admission.charged(topic_partition, uncommitted),
        })
    }

    fn settle_run(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: &[Offset],
    ) -> anyhow::Result<RunOutcome> {
        let (Some(first), Some(last)) = (offsets.first(), offsets.last()) else {
            return Ok(RunOutcome::Settled);
        };
        if let Err(rejection) =
            self.accounting
                .settled(topic_partition, generation, offsets.iter().copied())
        {
            report_rejection(
                "settle",
                topic_partition,
                rejection,
                RejectedSlice::settled(&OffsetSpan {
                    first: first.0,
                    last: last.0,
                }),
            )?;
            return Ok(RunOutcome::Stale);
        }
        Ok(RunOutcome::Settled)
    }

    fn settle_poll(&self, _slices: &[ChargedSlice<'_>]) -> anyhow::Result<()> {
        Ok(())
    }

    fn take_due(&self, now: Instant) -> Option<Commit> {
        let handed_out = self.accounting.take_due(now)?;
        let resume = self.admission.handed_out(&handed_out);
        Some(Commit::new(handed_out, resume))
    }

    fn take_all(&self) -> Option<Commit> {
        let handed_out = self.accounting.take_all()?;
        let resume = self.admission.handed_out(&handed_out);
        Some(Commit::new(handed_out, resume))
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.accounting.forget_partitions(topic_partitions);
        self.admission.forget_partitions(topic_partitions);
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use common_kafka_consumer::{Held, LedgerError};

    use super::super::fakes::{FakeAccounting, FakeAdmission, Settled};
    use super::super::{HandedOut, Pause};
    use super::*;

    fn p(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    fn events(events: u64) -> Charge {
        Charge { events, bytes: 0 }
    }

    fn uncommitted_events(events: u64) -> Held {
        Held {
            offsets: events as usize,
            charge: Charge { events, bytes: 0 },
        }
    }

    fn handed_out(offset: i64, remaining_events: u64) -> HandedOut {
        HandedOut {
            offset: Offset(offset),
            remaining: uncommitted_events(remaining_events),
        }
    }

    fn settlement() -> (
        GroupSettlement<FakeAccounting, FakeAdmission>,
        FakeAccounting,
        FakeAdmission,
    ) {
        let accounting = FakeAccounting::default();
        let admission = FakeAdmission::default();
        let settlement = GroupSettlement {
            accounting: accounting.clone(),
            admission: admission.clone(),
        };
        (settlement, accounting, admission)
    }

    #[test]
    fn a_charge_asks_the_admission_with_the_uncommitted_charge() {
        let (settlement, accounting, admission) = settlement();
        accounting.charge_returns(Ok(uncommitted_events(10)));
        admission.charged_returns(Some(Pause));

        assert_eq!(
            settlement
                .charge(&p(0), 0, &[])
                .map(|charged| charged.pause),
            Ok(Some(Pause))
        );
        assert_eq!(admission.charges_seen(), vec![(p(0), events(10))]);
    }

    #[test]
    fn a_rejected_charge_asks_the_admission_nothing() {
        let (settlement, accounting, admission) = settlement();
        let stale = Rejection::Stale {
            stamp: 0,
            generation: 1,
        };
        accounting.charge_returns(Err(stale));

        assert_eq!(
            settlement
                .charge(&p(0), 0, &[])
                .map(|charged| charged.pause),
            Err(stale)
        );
        assert!(admission.charges_seen().is_empty());
    }

    #[test]
    fn a_hand_out_commits_its_offsets_and_resumes_what_the_admission_decides() {
        let (settlement, accounting, admission) = settlement();
        let hand_out = HashMap::from([(p(0), handed_out(11, 3)), (p(1), handed_out(21, 0))]);
        accounting.take_hands_out(hand_out.clone());
        admission.handed_out_returns(vec![p(0)]);

        let commit = settlement.take_due(Instant::now()).expect("handed out");

        assert_eq!(
            commit.offsets,
            HashMap::from([(p(0), Offset(11)), (p(1), Offset(21))])
        );
        assert_eq!(commit.resume, vec![p(0)]);
        assert_eq!(admission.hand_outs_seen(), vec![hand_out]);
    }

    #[test]
    fn take_all_asks_the_admission_like_take_due() {
        let (settlement, accounting, admission) = settlement();
        accounting.take_hands_out(HashMap::from([(p(0), handed_out(11, 0))]));
        admission.handed_out_returns(vec![p(0)]);

        assert_eq!(
            settlement.take_all().expect("handed out").resume,
            vec![p(0)]
        );
    }

    #[test]
    fn a_run_reaches_the_accounting_under_its_generation() {
        let (settlement, accounting, _) = settlement();

        settlement
            .settle_run(&p(0), 3, &[Offset(10), Offset(11)])
            .unwrap();

        assert_eq!(
            accounting.settles_seen(),
            vec![Settled {
                topic_partition: p(0),
                generation: 3,
                offsets: vec![Offset(10), Offset(11)],
            }]
        );
    }

    #[test]
    fn an_empty_run_settles_nothing() {
        let (settlement, accounting, _) = settlement();

        settlement.settle_run(&p(0), 0, &[]).unwrap();

        assert!(accounting.settles_seen().is_empty());
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
        let (settlement, accounting, _) = settlement();
        accounting.settle_returns(Err(run.rejection));

        assert_eq!(
            settlement.settle_run(&p(0), 0, &[Offset(10)]).is_err(),
            run.expected_error
        );
    }

    #[test]
    fn a_retired_poll_settles_nothing() {
        let (settlement, accounting, _) = settlement();
        let charges = [(Offset(10), Charge::ZERO)];

        settlement
            .settle_poll(&[ChargedSlice {
                topic_partition: &p(0),
                generation: 0,
                span: OffsetSpan {
                    first: 10,
                    last: 10,
                },
                charges: &charges,
            }])
            .unwrap();

        assert!(accounting.settles_seen().is_empty());
    }

    #[test]
    fn a_revoke_reaches_both_the_accounting_and_the_admission() {
        let (settlement, accounting, admission) = settlement();

        settlement.forget_partitions(&[p(0)]);

        assert_eq!(accounting.forgotten(), vec![p(0)]);
        assert_eq!(admission.forgotten(), vec![p(0)]);
    }
}

#[cfg(test)]
mod integration_tests {
    use std::collections::HashMap;
    use std::num::NonZeroU64;

    use super::super::{charge_offsets, Pause};
    use super::*;

    fn settlement() -> (Arc<TopicOffsetLedger>, GroupSettlement) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement =
            GroupSettlement::new(Arc::clone(&ledger), Duration::ZERO, BudgetLimits::unset());
        (ledger, settlement)
    }

    #[test]
    fn a_partition_commits_only_once_its_completed_prefix_is_contiguous() {
        let (ledger, settlement) = settlement();
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10, 11, 12]);

        settlement.settle_run(&p0, 0, &[Offset(12)]).unwrap();
        assert!(
            settlement.take_due(Instant::now()).is_none(),
            "the window base is still incomplete"
        );

        settlement
            .settle_run(&p0, 0, &[Offset(10), Offset(11)])
            .unwrap();
        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(p0, Offset(13))])),
            "the late completion releases the whole prefix"
        );
    }

    #[test]
    fn a_partition_with_a_held_prefix_does_not_hold_back_another() {
        let (ledger, settlement) = settlement();
        let p0 = TopicPartition::new("events", 0);
        let p1 = TopicPartition::new("events", 1);
        charge_offsets(&ledger, &p0, 0, &[10, 11]);
        charge_offsets(&ledger, &p1, 0, &[20, 21]);

        settlement
            .settle_run(&p0, 0, &[Offset(10), Offset(11)])
            .unwrap();
        settlement.settle_run(&p1, 0, &[Offset(21)]).unwrap();

        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(p0, Offset(12))])),
            "partition 1 waits for offset 20"
        );
    }

    #[test]
    fn a_run_settled_twice_fails_and_keeps_the_frontier_taken_before_it() {
        let (ledger, settlement) = settlement();
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10, 11]);
        settlement.settle_run(&p0, 0, &[Offset(10)]).unwrap();

        assert!(settlement.settle_run(&p0, 0, &[Offset(10)]).is_err());

        assert_eq!(
            settlement.take_all().map(|commit| commit.offsets),
            Some(HashMap::from([(p0, Offset(11))])),
            "offset 10 completed before the violation"
        );
    }

    #[test]
    fn a_stale_stamp_run_commits_nothing() {
        let (ledger, settlement) = settlement();
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10]);

        ledger.forget_partitions([("events", 0)]);
        charge_offsets(&ledger, &p0, 1, &[10]);

        settlement.settle_run(&p0, 0, &[Offset(10)]).unwrap();

        assert!(settlement.take_due(Instant::now()).is_none());
        assert_eq!(
            ledger.held(&p0).offsets,
            1,
            "the redelivered offset stays uncompleted"
        );
    }

    #[test]
    fn a_frontier_within_the_interval_waits_for_it_unless_everything_is_taken() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement = GroupSettlement::new(
            Arc::clone(&ledger),
            Duration::from_secs(3600),
            BudgetLimits::unset(),
        );
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10, 11]);
        let now = Instant::now();

        settlement.settle_run(&p0, 0, &[Offset(10)]).unwrap();
        assert_eq!(
            settlement.take_due(now).map(|commit| commit.offsets),
            Some(HashMap::from([(p0.clone(), Offset(11))]))
        );

        settlement.settle_run(&p0, 0, &[Offset(11)]).unwrap();
        assert!(settlement.take_due(now).is_none());
        assert_eq!(
            settlement.take_all().map(|commit| commit.offsets),
            Some(HashMap::from([(p0, Offset(12))]))
        );
    }

    #[test]
    fn a_revoked_partitions_pending_frontier_is_not_committed() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement = GroupSettlement::new(
            Arc::clone(&ledger),
            Duration::from_secs(3600),
            BudgetLimits::unset(),
        );
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10]);
        settlement.settle_run(&p0, 0, &[Offset(10)]).unwrap();
        assert!(settlement.take_due(Instant::now()).is_some());

        charge_offsets(&ledger, &p0, 0, &[11]);
        settlement.settle_run(&p0, 0, &[Offset(11)]).unwrap();
        settlement.forget_partitions(&[p0]);

        assert!(settlement.take_all().is_none());
    }

    const HOUR: Duration = Duration::from_secs(3600);

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    fn budgeted_hourly_settlement_of_10_events_resuming_under_8() -> GroupSettlement {
        GroupSettlement::new(
            Arc::new(TopicOffsetLedger::new()),
            HOUR,
            BudgetLimits::new(NonZeroU64::new(10), None, 0.8).expect("valid limits"),
        )
    }

    fn charge(
        settlement: &GroupSettlement,
        topic_partition: &TopicPartition,
        offset: i64,
        events: u64,
    ) -> Option<Pause> {
        settlement
            .charge(
                topic_partition,
                0,
                &[(Offset(offset), Charge { events, bytes: 0 })],
            )
            .expect("the ledger accepts the charge")
            .pause
    }

    #[test]
    fn a_take_the_interval_holds_counts_toward_the_pause() {
        let settlement = budgeted_hourly_settlement_of_10_events_resuming_under_8();
        charge(&settlement, &p0(), 10, 6);
        settlement.settle_run(&p0(), 0, &[Offset(10)]).unwrap();

        assert_eq!(charge(&settlement, &p0(), 11, 4), Some(Pause));
    }

    enum HandOut {
        DueAfterTheInterval,
        All,
    }

    #[rstest::rstest]
    #[case::due_after_the_interval(HandOut::DueAfterTheInterval)]
    #[case::all(HandOut::All)]
    fn a_paused_partition_resumes_only_when_its_frontier_is_handed_out(#[case] hand_out: HandOut) {
        let settlement = budgeted_hourly_settlement_of_10_events_resuming_under_8();
        let now = Instant::now();
        charge(&settlement, &p0(), 9, 1);
        settlement.settle_run(&p0(), 0, &[Offset(9)]).unwrap();
        settlement
            .take_due(now)
            .expect("the first frontier is due at once");
        assert_eq!(charge(&settlement, &p0(), 10, 10), Some(Pause));

        settlement.settle_run(&p0(), 0, &[Offset(10)]).unwrap();
        assert!(settlement.take_due(now).is_none());

        let commit = match hand_out {
            HandOut::DueAfterTheInterval => settlement.take_due(now + HOUR),
            HandOut::All => settlement.take_all(),
        }
        .expect("the frontier is handed out");
        assert_eq!(commit.resume, vec![p0()]);
    }

    #[test]
    fn a_held_prefix_keeps_its_partition_paused_and_another_is_not_resumed() {
        let settlement = budgeted_hourly_settlement_of_10_events_resuming_under_8();
        let p1 = TopicPartition::new("events", 1);
        charge(&settlement, &p0(), 10, 5);
        assert_eq!(charge(&settlement, &p0(), 11, 5), Some(Pause));
        charge(&settlement, &p1, 20, 1);

        settlement.settle_run(&p0(), 0, &[Offset(11)]).unwrap();
        settlement.settle_run(&p1, 0, &[Offset(20)]).unwrap();
        let commit = settlement.take_all().expect("partition 1 is due");
        assert_eq!(commit.offsets, HashMap::from([(p1, Offset(21))]));
        assert!(
            commit.resume.is_empty(),
            "offset 10 still holds partition 0"
        );

        settlement.settle_run(&p0(), 0, &[Offset(10)]).unwrap();
        assert_eq!(
            settlement.take_all().expect("partition 0 is due").resume,
            vec![p0()]
        );
    }

    #[test]
    fn a_revoked_paused_partition_is_never_resumed() {
        let settlement = budgeted_hourly_settlement_of_10_events_resuming_under_8();
        assert_eq!(charge(&settlement, &p0(), 10, 10), Some(Pause));
        settlement.settle_run(&p0(), 0, &[Offset(10)]).unwrap();

        settlement.forget_partitions(&[p0()]);

        assert!(settlement.take_all().is_none());
        settlement.settle_run(&p0(), 0, &[Offset(10)]).unwrap();
        assert!(
            settlement.take_all().is_none(),
            "the stale run moves nothing"
        );
    }
}
