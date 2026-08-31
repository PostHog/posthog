use std::collections::HashMap;
use std::time::{Duration, Instant};

use crate::accumulator::{Accumulator, GroupCompletion, PolledMessage};
use crate::charge::Charge;
use crate::partition::PartitionDriver;
use crate::types::{Advance, AssignmentEpoch, DrainHarvest, Partition};

/// The domain side's root: assignment lifecycle plus the offset ledgers. Owns
/// every partition driver; nothing transport-shaped, no per-key state, and no
/// clock of its own.
#[derive(Debug)]
pub struct PartitionManager {
    partitions: HashMap<Partition, PartitionDriver>,
    stall_timeout: Duration,
}

impl PartitionManager {
    pub fn new(stall_timeout: Duration) -> PartitionManager {
        PartitionManager {
            partitions: HashMap::new(),
            stall_timeout,
        }
    }

    pub fn assign(&mut self, p: Partition, epoch: AssignmentEpoch, now: Instant) {
        let previous = self
            .partitions
            .insert(p, PartitionDriver::new(p, epoch, now, self.stall_timeout));
        assert!(
            previous.is_none(),
            "partition {p} assigned while already assigned"
        );
    }

    /// Drain begun: the driver stays — its ledger must absorb the completions
    /// still in flight.
    pub fn revoking(&mut self, p: Partition) {
        if let Some(driver) = self.partitions.get_mut(&p) {
            driver.begin_revoke();
        }
    }

    /// The drain's end: remove the driver and take its last word.
    pub fn drained(&mut self, p: Partition) -> DrainHarvest {
        let driver = self
            .partitions
            .remove(&p)
            .expect("Drained for an unassigned partition");
        let (frontier, dropped) = driver.drained();
        DrainHarvest {
            partition: p,
            frontier,
            dropped,
        }
    }

    /// One poll, demuxed to its partitions; returns the poll's debit for `B`.
    /// Messages must arrive grouped per partition in offset order, as rdkafka
    /// delivers them.
    pub fn accept<M>(
        &mut self,
        polled: Vec<(Partition, Vec<PolledMessage<M>>)>,
        acc: &mut Accumulator<M>,
    ) -> Charge {
        let mut charge = Charge::ZERO;
        for (p, msgs) in polled {
            let driver = self
                .partitions
                .get_mut(&p)
                .expect("poll delivered a message for an unassigned partition");
            charge += driver.accept(msgs, acc);
        }
        charge
    }

    /// One ACKed request's groups, distributed to their ledgers. Stragglers
    /// from before a reassignment die here by epoch; mid-drain completions
    /// land.
    pub fn complete(&mut self, completed: Vec<GroupCompletion>, now: Instant) -> Vec<Advance> {
        completed
            .into_iter()
            .filter_map(|c| {
                let driver = self.partitions.get_mut(&c.partition)?;
                if c.epoch != driver.epoch() {
                    return None;
                }
                driver.complete(&c.offsets, now)
            })
            .collect()
    }

    /// Driven by the loop's housekeeping tick; returns the stalled partitions.
    pub fn stalled(&self, now: Instant) -> Vec<Partition> {
        self.partitions
            .iter()
            .filter(|(_, d)| d.is_stalled(now))
            .map(|(p, _)| *p)
            .collect()
    }

    pub fn is_assigned(&self, p: Partition) -> bool {
        self.partitions.contains_key(&p)
    }

    pub fn is_revoking(&self, p: Partition) -> bool {
        self.partitions.get(&p).is_some_and(|d| d.revoking())
    }

    pub fn epoch(&self, p: Partition) -> Option<AssignmentEpoch> {
        self.partitions.get(&p).map(|d| d.epoch())
    }

    /// Every assigned partition, drains included, in ascending order.
    pub fn assigned(&self) -> Vec<Partition> {
        let mut assigned: Vec<Partition> = self.partitions.keys().copied().collect();
        assigned.sort();
        assigned
    }

    pub fn len(&self) -> usize {
        self.partitions.len()
    }

    pub fn is_empty(&self) -> bool {
        self.partitions.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::accumulator::Group;
    use crate::types::Offset;

    fn msg(offset: i64, key: &str) -> PolledMessage<()> {
        PolledMessage {
            offset: Offset(offset),
            key: Some(key.as_bytes().to_vec()),
            charge: Charge {
                events: 1,
                bytes: 1,
            },
            inner: (),
        }
    }

    fn completions(groups: &[Group<()>]) -> Vec<GroupCompletion> {
        groups.iter().map(Group::completion).collect()
    }

    fn poll(
        manager: &mut PartitionManager,
        p: Partition,
        msgs: Vec<PolledMessage<()>>,
    ) -> Vec<Group<()>> {
        let mut acc = Accumulator::default();
        manager.accept(vec![(p, msgs)], &mut acc);
        acc.into_groups()
    }

    #[test]
    fn completions_with_a_dead_epoch_drop() {
        let now = Instant::now();
        let mut manager = PartitionManager::new(Duration::from_secs(60));
        manager.assign(Partition(0), AssignmentEpoch(1), now);
        let groups = poll(&mut manager, Partition(0), vec![msg(0, "a")]);

        // The partition is revoked, drained, and reassigned under a new epoch
        // while the group is still out.
        manager.revoking(Partition(0));
        manager.drained(Partition(0));
        manager.assign(Partition(0), AssignmentEpoch(2), now);

        // The straggler dies by epoch: no advance, no ledger touch.
        assert_eq!(manager.complete(completions(&groups), now), vec![]);
    }

    #[test]
    fn drained_returns_the_final_frontier_and_the_dropped_charge() {
        let now = Instant::now();
        let mut manager = PartitionManager::new(Duration::from_secs(60));
        manager.assign(Partition(0), AssignmentEpoch(1), now);
        let mut groups = poll(
            &mut manager,
            Partition(0),
            vec![msg(0, "a"), msg(1, "b"), msg(2, "c")],
        );

        // Only "a" lands before the drain.
        let first = groups.remove(0);
        let advances = manager.complete(vec![first.completion()], now);
        assert_eq!(advances.len(), 1);
        assert_eq!(advances[0].frontier, Offset(0));

        manager.revoking(Partition(0));
        let harvest = manager.drained(Partition(0));
        assert_eq!(harvest.frontier, Some(Offset(0)));
        assert_eq!(
            harvest.dropped,
            Charge {
                events: 2,
                bytes: 2
            }
        );
        assert!(!manager.is_assigned(Partition(0)));
    }

    #[test]
    fn stall_check_fires_only_on_pending_work_and_stands_down_mid_drain() {
        let now = Instant::now();
        let stall = Duration::from_secs(60);
        let mut manager = PartitionManager::new(stall);
        manager.assign(Partition(0), AssignmentEpoch(1), now);
        manager.assign(Partition(1), AssignmentEpoch(1), now);
        let groups = poll(&mut manager, Partition(0), vec![msg(0, "a")]);
        poll(&mut manager, Partition(1), vec![msg(0, "x")]);

        let later = now + stall + Duration::from_secs(1);
        assert_eq!(
            manager.stalled(later).len(),
            2,
            "pending work past the deadline stalls"
        );

        // Progress on partition 0 resets its deadline; partition 1 stays stalled.
        manager.complete(completions(&groups), later);
        assert_eq!(manager.stalled(later), vec![Partition(1)]);

        // A draining partition stands down.
        manager.revoking(Partition(1));
        assert_eq!(manager.stalled(later), vec![]);
    }
}
