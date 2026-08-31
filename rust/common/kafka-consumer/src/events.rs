//! The loop's observer: the event points an adopter can subscribe to (a debug
//! recorder, a liveness heartbeat) without the crate depending on it.

use crate::charge::Charge;
use crate::types::{AssignmentEpoch, DrainHarvest, Offset, Partition};

/// Loop-side event points. Every method has a no-op default; implement the
/// ones you need. All are called from the consumer loop's task and must not
/// block.
#[allow(unused_variables)]
pub trait Observer: Send + 'static {
    /// Called once per loop iteration, whichever arm ran. Wire this to the
    /// process's liveness heartbeat.
    fn alive(&self) {}

    /// The loop subscribed and is polling.
    fn started(&self, group_id: &str, topic: &str) {}

    /// One poll accepted: `messages` demuxed, `charge` debited from `B`.
    fn poll_accepted(&self, messages: usize, charge: Charge) {}

    fn assigned(&self, partitions: &[Partition], epoch: AssignmentEpoch) {}

    /// A drain has begun for these partitions. `lost` means the broker
    /// already fenced them: no final commit will be issued.
    fn revoked(&self, partitions: &[Partition], lost: bool) {}

    /// A partition's drain ended and its final commit issued (or was
    /// abandoned, when `committed` is false).
    fn drained(&self, harvest: &DrainHarvest, committed: bool) {}

    /// A commit issued for these `(partition, next offset)` pairs.
    fn committed(&self, offsets: &[(Partition, Offset)]) {}

    /// The stall watchdog fired; the loop is about to exit.
    fn stalled(&self, partitions: &[Partition]) {}

    /// The poll gate closed (`true`) or reopened (`false`).
    fn gate_closed(&self, closed: bool, used: Charge) {}
}

/// The observer that observes nothing.
#[derive(Debug, Default, Clone, Copy)]
pub struct NoopObserver;

impl Observer for NoopObserver {}
