use std::sync::Arc;

use common_kafka_consumer::{Offset, Rejection, TopicOffsetLedger, TopicPartition};
use metrics::counter;
use tracing::warn;

use super::{ChargedSlice, Settlement};
use crate::commit_pacer::CommitPacer;
use crate::ledger_rejection::{warn_rejection, RejectedSlice};

pub(crate) struct PollSettlement {
    ledger: Arc<TopicOffsetLedger>,
    pacer: Arc<CommitPacer>,
}

impl PollSettlement {
    pub(crate) fn new(ledger: Arc<TopicOffsetLedger>) -> Self {
        Self {
            ledger,
            pacer: Arc::new(CommitPacer::immediate()),
        }
    }
}

impl Settlement for PollSettlement {
    fn settle_run(&self, _topic_partition: &TopicPartition, _generation: u64, _offsets: &[Offset]) {
    }

    fn settle_poll(&self, slices: &[ChargedSlice<'_>]) {
        if slices.is_empty() {
            // Unreachable: a batch always holds a message. Counted so that "no
            // empty commits" is measured, not assumed.
            counter!("ingestion_consumer_commit_violations_total", "kind" => "empty").increment(1);
            warn!("Poll settled with no partitions");
            return;
        }

        if let Err(no_frontier) = settle_slices(&self.ledger, &self.pacer, slices) {
            let reason = no_frontier.reason();
            counter!("ingestion_consumer_commits_skipped_total", "reason" => reason).increment(1);
            warn!(reason, "Poll handed over no frontier; nothing to commit");
        }
    }

    fn pacer(&self) -> &Arc<CommitPacer> {
        &self.pacer
    }
}

#[derive(Debug, PartialEq, Eq)]
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
    ledger: &TopicOffsetLedger,
    pacer: &CommitPacer,
    slices: &[ChargedSlice<'_>],
) -> Result<(), NoFrontier> {
    let mut settled = false;
    let mut handed_over = false;
    for slice in slices {
        let Ok(frontier) = settle(ledger, slice) else {
            continue;
        };
        settled = true;
        if frontier.is_none() {
            continue;
        }
        if let Some(taken) = ledger.take_frontier(slice.topic_partition) {
            pacer.advance_frontier(slice.topic_partition, taken);
            handed_over = true;
        }
    }
    match (handed_over, settled) {
        (true, _) => Ok(()),
        (false, true) => Err(NoFrontier::BehindAnEarlierPoll),
        (false, false) => Err(NoFrontier::EveryPartitionRejected),
    }
}

/// `Err` when the ledger rejected the slice, which it has already counted
/// and this logs.
fn settle(
    ledger: &TopicOffsetLedger,
    slice: &ChargedSlice<'_>,
) -> Result<Option<Offset>, Rejection> {
    ledger
        .settle(
            slice.topic_partition,
            slice.generation,
            slice.charges.iter().map(|(offset, _)| *offset),
        )
        .inspect_err(|rejection| {
            warn_rejection(
                "settle",
                slice.topic_partition,
                *rejection,
                RejectedSlice::settled(&slice.span),
            )
        })
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::Instant;

    use common_kafka_consumer::Charge;

    use super::*;
    use crate::order_sentinel::OffsetSpan;

    fn settlement() -> (Arc<TopicOffsetLedger>, Arc<CommitPacer>, PollSettlement) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement = PollSettlement::new(Arc::clone(&ledger));
        let pacer = Arc::clone(settlement.pacer());
        (ledger, pacer, settlement)
    }

    fn charged(
        ledger: &TopicOffsetLedger,
        topic_partition: &TopicPartition,
        first: i64,
        last: i64,
    ) -> (u64, OffsetSpan, Vec<(Offset, Charge)>) {
        let generation = ledger.generation(topic_partition);
        let charges: Vec<(Offset, Charge)> = (first..=last)
            .map(|offset| (Offset(offset), Charge::ZERO))
            .collect();
        ledger
            .charge(topic_partition, generation, charges.iter().copied())
            .expect("charge");
        (generation, OffsetSpan { first, last }, charges)
    }

    fn slice<'a>(
        topic_partition: &'a TopicPartition,
        charged: &'a (u64, OffsetSpan, Vec<(Offset, Charge)>),
    ) -> ChargedSlice<'a> {
        ChargedSlice {
            topic_partition,
            generation: charged.0,
            span: charged.1,
            charges: &charged.2,
        }
    }

    #[test]
    fn a_settled_poll_hands_its_frontier_to_the_pacer() {
        let (ledger, pacer, _) = settlement();
        let tp = TopicPartition::new("test", 0);
        let charged = charged(&ledger, &tp, 10, 11);

        assert_eq!(
            settle_slices(&ledger, &pacer, &[slice(&tp, &charged)]),
            Ok(())
        );
        assert_eq!(
            pacer.take_due(Instant::now()),
            Some(HashMap::from([(tp, Offset(12))]))
        );
    }

    #[test]
    fn a_rejected_slice_hands_nothing_to_the_pacer() {
        let (ledger, pacer, _) = settlement();
        let tp = TopicPartition::new("test", 0);
        let charged = charged(&ledger, &tp, 10, 11);
        // The partition left and came back while the poll was in flight.
        ledger.forget_partitions([("test", 0)]);

        assert_eq!(
            settle_slices(&ledger, &pacer, &[slice(&tp, &charged)]),
            Err(NoFrontier::EveryPartitionRejected)
        );
        assert!(pacer.take_due(Instant::now()).is_none());
    }

    #[test]
    fn a_poll_behind_an_incomplete_one_hands_nothing_to_the_pacer() {
        let (ledger, pacer, _) = settlement();
        let tp = TopicPartition::new("test", 0);
        let _older = charged(&ledger, &tp, 10, 11);
        let newer = charged(&ledger, &tp, 12, 13);

        assert_eq!(
            settle_slices(&ledger, &pacer, &[slice(&tp, &newer)]),
            Err(NoFrontier::BehindAnEarlierPoll)
        );
        assert!(pacer.take_due(Instant::now()).is_none());
    }

    #[test]
    fn an_accepted_run_settles_nothing_before_its_poll_retires() {
        let (ledger, pacer, settlement) = settlement();
        let tp = TopicPartition::new("test", 0);
        let charged = charged(&ledger, &tp, 10, 11);

        settlement.settle_run(&tp, charged.0, &[Offset(10), Offset(11)]);
        assert!(pacer.take_due(Instant::now()).is_none());

        settlement.settle_poll(&[slice(&tp, &charged)]);
        assert_eq!(
            pacer.take_due(Instant::now()),
            Some(HashMap::from([(tp, Offset(12))]))
        );
    }
}
