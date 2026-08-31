use std::time::{Duration, Instant};

use crate::accumulator::{Accumulator, PolledMessage};
use crate::charge::Charge;
use crate::ledger::OffsetLedger;
use crate::types::{Advance, AssignmentEpoch, Offset, Partition};

/// The single owner of one partition's domain state: the offset ledger and
/// the stall deadline. Methods are synchronous and never block; the loop's
/// housekeeping tick drives the stall check.
#[derive(Debug)]
pub struct PartitionDriver {
    partition: Partition,
    epoch: AssignmentEpoch,
    ledger: OffsetLedger,
    stall_deadline: Instant,
    stall_timeout: Duration,
    /// Drain in progress: completions still land; the stall check stands down.
    revoking: bool,
}

impl PartitionDriver {
    pub fn new(
        partition: Partition,
        epoch: AssignmentEpoch,
        now: Instant,
        stall_timeout: Duration,
    ) -> PartitionDriver {
        PartitionDriver {
            partition,
            epoch,
            ledger: OffsetLedger::new(),
            stall_deadline: now + stall_timeout,
            stall_timeout,
            revoking: false,
        }
    }

    pub fn epoch(&self) -> AssignmentEpoch {
        self.epoch
    }

    pub fn revoking(&self) -> bool {
        self.revoking
    }

    pub fn begin_revoke(&mut self) {
        self.revoking = true;
    }

    /// One poll's messages for this partition, in offset order: record them
    /// in the ledger and push the demuxed groups into the lent accumulator.
    /// Returns the poll's debit for the budget.
    pub fn accept<M>(&mut self, msgs: Vec<PolledMessage<M>>, acc: &mut Accumulator<M>) -> Charge {
        let charge = self
            .ledger
            .add_pending(msgs.iter().map(|m| (m.offset, m.charge)));
        acc.push_demuxed(self.partition, self.epoch, msgs);
        charge
    }

    /// One ACKed group — the record of what landed. `None` when the frontier
    /// did not move.
    pub fn complete(&mut self, offsets: &[Offset], now: Instant) -> Option<Advance> {
        let (frontier, charge) = self.ledger.complete(offsets)?;
        self.stall_deadline = now + self.stall_timeout;
        Some(Advance {
            partition: self.partition,
            frontier,
            charge,
        })
    }

    /// Consumed at the drain's end: the final frontier to commit, and the
    /// charge the frontier never walked over.
    pub fn drained(self) -> (Option<Offset>, Charge) {
        (self.ledger.frontier(), self.ledger.pending_charge())
    }

    /// A frontier stuck for the timeout while work is pending. The caller
    /// decides what failing the process looks like; replay is bounded by `B`.
    pub fn is_stalled(&self, now: Instant) -> bool {
        !self.revoking && self.ledger.has_pending() && now > self.stall_deadline
    }
}
