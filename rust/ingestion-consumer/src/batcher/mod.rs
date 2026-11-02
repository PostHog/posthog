//! The worker batcher: the dispatch orchestration behind one boundary.
//!
//! The consumer loop submits one [`Accumulator`] per poll, in poll order, and
//! receives [`GroupCompletion`]s back, one per partition and generation of each
//! settled request. Everything in between is an implementation detail of this
//! module: the state machine queues each key's messages, packs ready keys into
//! requests for free worker slots, places each request on a worker as it is
//! sent, and retries failures; one task drives it and performs its effects. No
//! batch identity crosses the boundary: the consumer correlates completions by
//! partition and offset.
//!
//! Fatal orchestration failures (pending work that makes no progress for the
//! stall timeout, a worker whose accepted count differs from what it was sent)
//! are reported on an error channel; the consumer turns them into a process
//! failure, so the failure decision stays in the consumer loop.

mod driver;
pub mod governor;
pub mod in_flight;
pub mod key_queues;
pub mod packer;
pub mod request;
pub mod retry_policy;
pub mod state_machine;
#[cfg(test)]
pub(crate) mod test_support;
pub mod worker_assigner;
pub mod worker_pool;

use std::collections::HashMap;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use common_kafka_consumer::{GroupCompletion, Partition};
use tokio::sync::mpsc;

use self::driver::StateMachineDriver;
use self::governor::GovernorSnapshot;
use self::state_machine::{BatcherSnapshot, BatcherStateMachine};
use self::worker_pool::WorkerPoolSource;
use crate::debug_recorder::DebugRecorder;
use crate::grpc_transport::GrpcTransport;
use crate::order_sentinel::KeyOrderSentinel;
use crate::types::Accumulator;
use crate::worker_registry::WorkerId;

/// The batcher's output channels, held by the consumer loop.
pub struct BatcherOutputs {
    /// One completion per partition and generation of each settled request.
    pub completions: mpsc::UnboundedReceiver<GroupCompletion>,
    /// Fatal orchestration failures.
    pub errors: mpsc::UnboundedReceiver<String>,
}

pub struct Batcher {
    driver: StateMachineDriver,
}

impl Batcher {
    pub fn new(
        state_machine: BatcherStateMachine,
        pool_source: WorkerPoolSource,
        transport: Arc<GrpcTransport>,
        recorder: Option<Arc<DebugRecorder>>,
    ) -> (Self, BatcherOutputs) {
        let (driver, outputs) =
            StateMachineDriver::new(state_machine, pool_source, transport, recorder);
        (Self { driver }, outputs)
    }

    /// The per-key order sentinel, so the consumer can enable it.
    pub fn key_order_sentinel(&self) -> Arc<KeyOrderSentinel> {
        self.driver.key_order_sentinel()
    }

    /// The batcher's half of the consumer's revocation hook.
    pub fn revoker(&self) -> Revoker {
        Revoker(self.driver.revoke_sender())
    }

    /// Submit one poll's demuxed groups. Call on the consumer loop, in poll
    /// order. Each partition's completions carry its generation from
    /// `generations`. Returns the assignment epoch stamped on the poll's
    /// completions.
    pub fn submit(&self, accumulator: Accumulator, generations: &HashMap<Partition, u64>) -> u64 {
        self.driver.submit(accumulator, generations)
    }

    /// A read-only view of the batcher's load.
    pub fn observer(&self) -> BatcherObserver {
        BatcherObserver {
            load: self.driver.load(),
            snapshots: self.driver.snapshot_sender(),
        }
    }

    /// The consumer stopped polling. The state machine takes no new groups
    /// and stops once nothing is pending or in flight.
    pub fn begin_shutdown(&self) {
        self.driver.begin_shutdown();
    }
}

/// A read-only view of the batcher's load.
#[derive(Clone)]
pub struct BatcherObserver {
    /// Totals the batcher task publishes after every action.
    load: Arc<driver::Load>,
    snapshots: driver::SnapshotSender,
}

impl BatcherObserver {
    /// Whether the worker has sent, unresolved work.
    pub fn has_in_flight(&self, worker: &WorkerId) -> bool {
        self.load.busy_workers.lock().unwrap().contains(worker)
    }

    /// Messages queued for a later send.
    pub fn pending_messages(&self) -> usize {
        self.load.pending_messages.load(Ordering::Relaxed)
    }

    pub fn total_in_flight(&self) -> usize {
        self.load.in_flight_messages.load(Ordering::Relaxed)
    }

    /// The task's own view of its load, or only the published totals when
    /// it does not answer.
    pub async fn snapshot(&self) -> BatcherSnapshot {
        match self.snapshots.snapshot().await {
            Some(snapshot) => snapshot,
            None => BatcherSnapshot {
                pending_messages: self.pending_messages(),
                in_flight_messages: self.total_in_flight(),
                governor: GovernorSnapshot {
                    adaptation: self.load.adaptation,
                    ..GovernorSnapshot::default()
                },
                ..BatcherSnapshot::default()
            },
        }
    }
}

/// Purges revoked partitions from the batcher. Purged messages never
/// complete.
pub struct Revoker(driver::RevokeSender);

impl Revoker {
    pub fn purge_revoked(&self, partitions: &[(String, i32)]) {
        self.0.purge_revoked(partitions);
    }
}

pub(crate) fn make_batch_id() -> String {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let rand: u32 = rand::random();
    format!("{ts:x}-{rand:08x}")
}
