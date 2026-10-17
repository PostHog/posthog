use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

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

    fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        super::release_taken(&self.ledger, self.pacer.take_due(now))
    }

    fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>> {
        super::release_taken(&self.ledger, self.pacer.take_all())
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.pacer.forget_partitions(topic_partitions);
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

        settlement.settle_poll(&[p0.slice(), p1.slice()]);

        assert_eq!(
            settlement.take_due(Instant::now()),
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

        settlement.settle_poll(&[newer.slice()]);
        assert!(settlement.take_due(Instant::now()).is_none());

        settlement.settle_poll(&[older.slice()]);
        assert_eq!(
            settlement.take_due(Instant::now()),
            Some(HashMap::from([(older.topic_partition, Offset(14))]))
        );
    }

    #[test]
    fn a_stale_poll_makes_nothing_due() {
        let (ledger, settlement) = settlement();
        let poll = charged(&ledger, 0, 10, 11);
        // The partition left and came back while the poll was in flight.
        ledger.forget_partitions([("test", 0)]);

        settlement.settle_poll(&[poll.slice()]);

        assert!(settlement.take_due(Instant::now()).is_none());
    }

    #[test]
    fn a_retired_poll_is_uncommitted_until_its_frontier_goes_out() {
        let (ledger, settlement) = settlement();
        let poll = charged(&ledger, 0, 10, 11);

        settlement.settle_poll(&[poll.slice()]);
        assert_eq!(ledger.uncommitted(&poll.topic_partition).offsets, 2);

        settlement.take_due(Instant::now());
        assert_eq!(ledger.uncommitted(&poll.topic_partition).offsets, 0);
    }

    #[test]
    fn an_accepted_run_settles_nothing_before_its_poll_retires() {
        let (ledger, settlement) = settlement();
        let poll = charged(&ledger, 0, 10, 11);

        settlement.settle_run(
            &poll.topic_partition,
            poll.generation,
            &[Offset(10), Offset(11)],
        );
        assert!(settlement.take_due(Instant::now()).is_none());

        settlement.settle_poll(&[poll.slice()]);
        assert_eq!(
            settlement.take_due(Instant::now()),
            Some(HashMap::from([(poll.topic_partition, Offset(12))]))
        );
    }
}
