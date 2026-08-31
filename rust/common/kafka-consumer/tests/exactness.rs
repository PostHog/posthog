//! The §8.2 accounting invariant: every message's charge is debited once at
//! poll and refunded exactly once — at the commit that covers it, or as a
//! drain's `dropped` — so after any schedule ends with every partition
//! drained, the budget returns to zero.

use std::time::{Duration, Instant};

use proptest::prelude::*;

use common_kafka_consumer::accumulator::{Accumulator, Group, PolledMessage};
use common_kafka_consumer::charge::{Budget, Charge};
use common_kafka_consumer::commit::CommitManager;
use common_kafka_consumer::manager::PartitionManager;
use common_kafka_consumer::types::{AssignmentEpoch, Offset, Partition};

const PARTITIONS: i32 = 3;
const COMMIT_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Debug, Clone)]
enum Op {
    /// Deliver `count` messages to the partition, skipping an offset first
    /// when `gap` (a transaction control record).
    Poll {
        partition: i32,
        count: u8,
        gap: bool,
    },
    /// Complete the outstanding group at `index % outstanding.len()`.
    Complete { index: u8 },
    /// Advance time and give the commit manager its clock.
    Tick,
    /// Revoke the partition, drain it, and reassign it under a new epoch.
    RevokeAndReassign { partition: i32 },
}

fn op_strategy() -> impl Strategy<Value = Op> {
    prop_oneof![
        4 => (0..PARTITIONS, 1u8..8, any::<bool>())
            .prop_map(|(partition, count, gap)| Op::Poll { partition, count, gap }),
        4 => any::<u8>().prop_map(|index| Op::Complete { index }),
        1 => Just(Op::Tick),
        1 => (0..PARTITIONS).prop_map(|partition| Op::RevokeAndReassign { partition }),
    ]
}

proptest! {
    #[test]
    fn budget_returns_to_zero_after_any_schedule(ops in prop::collection::vec(op_strategy(), 1..80)) {
        let mut now = Instant::now();
        let mut manager = PartitionManager::new(Duration::from_secs(3600));
        let mut commits = CommitManager::new(COMMIT_INTERVAL);
        let mut budget = Budget::new(Charge { events: u64::MAX, bytes: u64::MAX });

        let mut epoch = 0u64;
        let mut next_offset = vec![0i64; PARTITIONS as usize];
        let mut outstanding: Vec<Group<u8>> = Vec::new();
        let mut issue = |_: &[(Partition, Offset)]| {};

        for p in 0..PARTITIONS {
            manager.assign(Partition(p), AssignmentEpoch(epoch), now);
        }

        for op in ops {
            now += Duration::from_secs(1);
            match op {
                Op::Poll { partition, count, gap } => {
                    let offset = &mut next_offset[partition as usize];
                    if gap {
                        *offset += 1;
                    }
                    let msgs: Vec<PolledMessage<u8>> = (0..count)
                        .map(|i| {
                            let o = *offset + i as i64;
                            PolledMessage {
                                offset: Offset(o),
                                // A few keys so groups span multiple offsets;
                                // key 0 is null (a free group per message).
                                key: (o % 4 != 0).then(|| vec![(o % 4) as u8]),
                                charge: Charge { events: 1, bytes: 1 + (o as u64 % 7) },
                                inner: 0,
                            }
                        })
                        .collect();
                    *offset += count as i64;
                    let mut acc = Accumulator::default();
                    budget.charge(manager.accept(vec![(Partition(partition), msgs)], &mut acc));
                    outstanding.extend(acc.into_groups());
                }
                Op::Complete { index } => {
                    if outstanding.is_empty() {
                        continue;
                    }
                    let group = outstanding.remove(index as usize % outstanding.len());
                    let advances = manager.complete(vec![group.completion()], now);
                    budget.refund(commits.progress(advances, now, &mut issue));
                }
                Op::Tick => {
                    now += COMMIT_INTERVAL;
                    budget.refund(commits.tick(now, &mut issue));
                }
                Op::RevokeAndReassign { partition } => {
                    let p = Partition(partition);
                    manager.revoking(p);
                    budget.refund(commits.finish_revoke(manager.drained(p), now, &mut issue));
                    epoch += 1;
                    manager.assign(p, AssignmentEpoch(epoch), now);
                    // Offsets replay from the frontier in reality; delivering
                    // fresh offsets instead keeps the model simple and still
                    // exercises the accounting (a replay is just a poll).
                }
            }
        }

        // Straggler completions from before any reassignment die by epoch.
        for group in outstanding.drain(..) {
            let advances = manager.complete(vec![group.completion()], now);
            budget.refund(commits.progress(advances, now, &mut issue));
        }
        // Drain everything: whatever the frontiers never walked over comes
        // back as `dropped`.
        for p in 0..PARTITIONS {
            let p = Partition(p);
            manager.revoking(p);
            budget.refund(commits.finish_revoke(manager.drained(p), now, &mut issue));
        }

        prop_assert_eq!(budget.used(), Charge::ZERO);
    }
}
