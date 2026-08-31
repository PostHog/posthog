//! The rdkafka consumer context: turns rebalance callbacks into events on the
//! loop's channel, and exports librdkafka statistics.
//!
//! rdkafka runs the rebalance callback synchronously inside `poll`, on the
//! task that awaits `recv()` — the consumer loop's own task. So the callback
//! never waits: on assign it applies the assignment at once (there is nothing
//! to wait for) and reports it; on revoke it only reports, and the loop hands
//! the partitions back with `incremental_unassign` once their drain ends.
//!
//! One exception: while `closing` is set, a revoke is answered inline.
//! Closing the consumer revokes the whole assignment through this same
//! callback and rdkafka's `Drop` polls until the close completes, so a
//! deferred answer there would spin forever.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use rdkafka::consumer::{BaseConsumer, Consumer, ConsumerContext};
use rdkafka::error::KafkaError;
use rdkafka::types::RDKafkaRespErr;
use rdkafka::{ClientContext, Statistics, TopicPartitionList};
use tokio::sync::mpsc;
use tracing::warn;

use crate::stats;
use crate::types::{AssignmentEpoch, Partition};

/// What the callback tells the loop.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RebalanceEvent {
    /// Partitions added to the assignment, already applied to rdkafka.
    Assigned {
        partitions: Vec<Partition>,
        epoch: AssignmentEpoch,
    },
    /// Partitions leaving the assignment. `handed_back` is true when the
    /// callback already called `incremental_unassign` (closing, or the
    /// assignment was lost); otherwise the loop must, after the drain.
    Revoked {
        partitions: Vec<Partition>,
        lost: bool,
        handed_back: bool,
    },
    /// librdkafka reported a rebalance failure; the assignment was cleared.
    Error(KafkaError),
}

pub struct LoopContext {
    events: mpsc::UnboundedSender<RebalanceEvent>,
    /// The process's one assignment epoch counter, shared with the transport
    /// side through `ConsumerLoop::epoch_counter`.
    epoch: Arc<AtomicU64>,
    closing: Arc<AtomicBool>,
}

impl LoopContext {
    pub fn new(
        events: mpsc::UnboundedSender<RebalanceEvent>,
        closing: Arc<AtomicBool>,
        epoch: Arc<AtomicU64>,
    ) -> LoopContext {
        LoopContext {
            events,
            epoch,
            closing,
        }
    }

    fn send(&self, event: RebalanceEvent) {
        // The receiver is the loop; if it is gone the process is exiting.
        drop(self.events.send(event));
    }
}

impl ClientContext for LoopContext {
    /// Fired on a librdkafka thread every `statistics.interval.ms`; disabled
    /// when that is 0.
    fn stats(&self, statistics: Statistics) {
        stats::export(&statistics);
    }
}

impl ConsumerContext for LoopContext {
    fn rebalance(
        &self,
        base: &BaseConsumer<Self>,
        err: RDKafkaRespErr,
        tpl: &mut TopicPartitionList,
    ) {
        let partitions: Vec<Partition> = tpl
            .elements()
            .iter()
            .map(|e| Partition(e.partition()))
            .collect();
        match err {
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS => {
                if let Err(err) = base.incremental_assign(tpl) {
                    warn!(error = %err, "incremental_assign failed");
                }
                if partitions.is_empty() {
                    return;
                }
                let epoch = AssignmentEpoch(self.epoch.fetch_add(1, Ordering::Relaxed) + 1);
                self.send(RebalanceEvent::Assigned { partitions, epoch });
            }
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS => {
                let lost = base.assignment_lost();
                let inline = lost || self.closing.load(Ordering::SeqCst);
                if inline {
                    if let Err(err) = base.incremental_unassign(tpl) {
                        warn!(error = %err, "incremental_unassign failed");
                    }
                }
                if partitions.is_empty() {
                    return;
                }
                self.send(RebalanceEvent::Revoked {
                    partitions,
                    lost,
                    handed_back: inline,
                });
            }
            other => {
                let code = other.into();
                warn!(error = ?code, "rebalance error; clearing the assignment");
                // librdkafka requires assign(NULL) here to synchronize state.
                if let Err(err) = base.unassign() {
                    warn!(error = %err, "unassign after rebalance error failed");
                }
                self.send(RebalanceEvent::Error(KafkaError::Rebalance(code)));
            }
        }
    }
}
