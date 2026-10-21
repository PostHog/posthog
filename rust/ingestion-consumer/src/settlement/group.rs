use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicOffsetLedger, TopicPartition};

use super::{ChargedSlice, Settlement, Uncommitted};
use crate::commit_pacer::CommitPacer;
use crate::ledger_rejection::{report_rejection, RejectedSlice};
use crate::order_sentinel::OffsetSpan;

pub(crate) struct GroupSettlement {
    uncommitted: Uncommitted,
}

impl GroupSettlement {
    pub(crate) fn new(ledger: Arc<TopicOffsetLedger>, commit_interval: Duration) -> Self {
        Self {
            uncommitted: Uncommitted::new(ledger, CommitPacer::every(commit_interval)),
        }
    }
}

impl Settlement for GroupSettlement {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Held, Rejection> {
        self.uncommitted
            .charge(topic_partition, generation, charges)
    }

    fn settle_run(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: &[Offset],
    ) -> anyhow::Result<()> {
        if let Err(rejection) =
            self.uncommitted
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

    fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        self.uncommitted.take_due(now)
    }

    fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>> {
        self.uncommitted.take_all()
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.uncommitted.forget_partitions(topic_partitions);
    }
}

#[cfg(test)]
mod tests {
    use super::super::charge_offsets;
    use super::*;

    fn settlement() -> (Arc<TopicOffsetLedger>, GroupSettlement) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement = GroupSettlement::new(Arc::clone(&ledger), Duration::ZERO);
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
            settlement.take_due(Instant::now()),
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
            settlement.take_due(Instant::now()),
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
            settlement.take_all(),
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
        let settlement = GroupSettlement::new(Arc::clone(&ledger), Duration::from_secs(3600));
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10, 11]);
        let now = Instant::now();

        settlement.settle_run(&p0, 0, &[Offset(10)]).unwrap();
        assert_eq!(
            settlement.take_due(now),
            Some(HashMap::from([(p0.clone(), Offset(11))]))
        );

        settlement.settle_run(&p0, 0, &[Offset(11)]).unwrap();
        assert!(settlement.take_due(now).is_none());
        assert_eq!(
            settlement.take_all(),
            Some(HashMap::from([(p0, Offset(12))]))
        );
    }

    #[test]
    fn a_revoked_partitions_pending_frontier_is_not_committed() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement = GroupSettlement::new(Arc::clone(&ledger), Duration::from_secs(3600));
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10]);
        settlement.settle_run(&p0, 0, &[Offset(10)]).unwrap();
        assert!(settlement.take_due(Instant::now()).is_some());

        charge_offsets(&ledger, &p0, 0, &[11]);
        settlement.settle_run(&p0, 0, &[Offset(11)]).unwrap();
        settlement.forget_partitions(&[p0]);

        assert!(settlement.take_all().is_none());
    }

    #[test]
    fn a_retired_poll_settles_nothing_more() {
        let (ledger, settlement) = settlement();
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10]);
        let charges = [(Offset(10), common_kafka_consumer::Charge::ZERO)];

        settlement
            .settle_poll(&[ChargedSlice {
                topic_partition: &p0,
                generation: 0,
                span: OffsetSpan {
                    first: 10,
                    last: 10,
                },
                charges: &charges,
            }])
            .unwrap();

        assert!(settlement.take_due(Instant::now()).is_none());
        assert_eq!(ledger.held(&p0).offsets, 1);
    }
}
