use std::sync::Arc;

use common_kafka_consumer::{Offset, Rejection, TopicOffsetLedger, TopicPartition};
use metrics::counter;
use tracing::warn;

use super::{hand_over_frontier, ChargedSlice, Settlement};
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
            // Unreachable while batches require messages to be spawned; counted
            // so "no empty commits" is a measurable guarantee, not an assumption.
            counter!("ingestion_consumer_commit_violations_total", "kind" => "empty").increment(1);
            warn!("Poll settled with no partitions");
            return;
        }

        let outcome = settle_slices(&self.ledger, &self.pacer, slices);

        if outcome.advanced == 0 {
            // `rejected`: the ledger dropped every slice, expected around a
            // rebalance. `no_frontier`: a slice landed, but an earlier batch
            // is still incomplete at the front of every window it settled.
            let reason = if outcome.settled == 0 {
                "rejected"
            } else {
                "no_frontier"
            };
            counter!("ingestion_consumer_commits_skipped_total", "reason" => reason).increment(1);
            warn!(
                reason,
                "No ledger frontier available for completed offsets; skipping commit"
            );
        }
    }

    fn pacer(&self) -> &Arc<CommitPacer> {
        &self.pacer
    }
}

struct Outcome {
    settled: usize,
    advanced: usize,
}

fn settle_slices(
    ledger: &TopicOffsetLedger,
    pacer: &CommitPacer,
    slices: &[ChargedSlice<'_>],
) -> Outcome {
    let mut outcome = Outcome {
        settled: 0,
        advanced: 0,
    };
    for slice in slices {
        let Ok(frontier) = settle(ledger, slice) else {
            continue;
        };
        outcome.settled += 1;
        if frontier.is_some() && hand_over_frontier(ledger, pacer, slice.topic_partition) {
            outcome.advanced += 1;
        }
    }
    outcome
}

/// Settle one slice against the ledger and report the frontier it reached.
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

    /// A poll's slice of one partition, charged to the ledger under the
    /// partition's current generation.
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

        let outcome = settle_slices(&ledger, &pacer, &[slice(&tp, &charged)]);

        assert_eq!((outcome.settled, outcome.advanced), (1, 1));
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

        let outcome = settle_slices(&ledger, &pacer, &[slice(&tp, &charged)]);

        assert_eq!((outcome.settled, outcome.advanced), (0, 0));
        assert!(pacer.take_due(Instant::now()).is_none());
    }

    #[test]
    fn a_poll_behind_an_incomplete_one_hands_nothing_to_the_pacer() {
        let (ledger, pacer, _) = settlement();
        let tp = TopicPartition::new("test", 0);
        let _older = charged(&ledger, &tp, 10, 11);
        let newer = charged(&ledger, &tp, 12, 13);

        let outcome = settle_slices(&ledger, &pacer, &[slice(&tp, &newer)]);

        assert_eq!((outcome.settled, outcome.advanced), (1, 0));
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
