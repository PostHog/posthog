use std::collections::HashMap;
use std::sync::Arc;

use etcd_client::EventType;
use tokio::sync::mpsc::error::TrySendError;
use tokio_util::sync::CancellationToken;

use crate::consumer_registry::ConsumerRegistry;
use crate::error::{Error, Result};
use crate::store::{self, KafkaAssignerStore};
use crate::types::{
    AssignmentEvent, HandoffPhase, HandoffState, PartitionAssignment, TopicPartition,
};

/// Watches etcd for assignment and handoff changes, relaying commands
/// to consumers connected to this instance.
///
/// Every assigner instance runs one relay. It only pushes events to
/// consumers in its local `ConsumerRegistry`; consumers connected to
/// other instances are served by their own relay.
///
/// Consumers must handle assignment events idempotently — the relay
/// forwards all etcd updates, which may include redundant notifications
/// for partitions the consumer already owns.
pub async fn run_relay(
    store: Arc<KafkaAssignerStore>,
    registry: Arc<ConsumerRegistry>,
    cancel: CancellationToken,
) -> Result<()> {
    tokio::try_join!(
        relay_assignments(store.clone(), registry.clone(), cancel.clone()),
        relay_handoffs(store, registry, cancel),
    )?;
    Ok(())
}

/// Watch assignment changes and push `Assignment` events to affected consumers.
///
/// When the leader writes assignments in a batch transaction, the relay
/// receives all changes in a single `WatchResponse`. We batch them
/// per-consumer so each consumer gets one `Assignment` event per
/// watch response, not one per partition.
async fn relay_assignments(
    store: Arc<KafkaAssignerStore>,
    registry: Arc<ConsumerRegistry>,
    cancel: CancellationToken,
) -> Result<()> {
    let mut stream = store.watch_assignments().await?;

    loop {
        tokio::select! {
            _ = cancel.cancelled() => return Ok(()),
            msg = stream.message() => {
                let resp = msg?.ok_or_else(|| Error::invalid_state("assignment watch stream ended"))?;

                let mut per_consumer: HashMap<String, Vec<TopicPartition>> = HashMap::new();
                for event in resp.events() {
                    if event.event_type() == EventType::Put {
                        match store::parse_watch_value::<PartitionAssignment>(event) {
                            Ok(assignment) => {
                                per_consumer
                                    .entry(assignment.owner.clone())
                                    .or_default()
                                    .push(assignment.topic_partition());
                            }
                            Err(e) => {
                                tracing::error!(error = %e, "failed to parse assignment event");
                            }
                        }
                    }
                }

                for (consumer, partitions) in per_consumer {
                    if let Some(sender) = registry.get_sender(&consumer) {
                        let event = AssignmentEvent::Assignment {
                            assigned: partitions,
                            unassigned: vec![],
                        };
                        match sender.try_send(event) {
                            Ok(()) => {}
                            Err(TrySendError::Full(_)) => {
                                tracing::warn!(consumer = %consumer, "consumer channel full, dropping assignment");
                            }
                            Err(TrySendError::Closed(_)) => {
                                tracing::debug!(consumer = %consumer, "consumer channel closed, skipping assignment");
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Watch handoff changes and push `Warm`/`Release` events to affected consumers.
async fn relay_handoffs(
    store: Arc<KafkaAssignerStore>,
    registry: Arc<ConsumerRegistry>,
    cancel: CancellationToken,
) -> Result<()> {
    let mut stream = store.watch_handoffs().await?;

    loop {
        tokio::select! {
            _ = cancel.cancelled() => return Ok(()),
            msg = stream.message() => {
                let resp = msg?.ok_or_else(|| Error::invalid_state("handoff watch stream ended"))?;

                for event in resp.events() {
                    if event.event_type() == EventType::Put {
                        match store::parse_watch_value::<HandoffState>(event) {
                            Ok(handoff) => {
                                relay_handoff_event(&registry, &handoff);
                            }
                            Err(e) => {
                                tracing::error!(error = %e, "failed to parse handoff event");
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Route a single handoff event to the appropriate consumer.
fn relay_handoff_event(registry: &ConsumerRegistry, handoff: &HandoffState) {
    match handoff.phase {
        HandoffPhase::Warming => {
            if let Some(sender) = registry.get_sender(&handoff.new_owner) {
                match sender.try_send(AssignmentEvent::Warm(handoff.clone())) {
                    Ok(()) => {}
                    Err(TrySendError::Full(_)) => {
                        tracing::warn!(consumer = %handoff.new_owner, "consumer channel full, dropping warm");
                    }
                    Err(TrySendError::Closed(_)) => {
                        tracing::debug!(consumer = %handoff.new_owner, "consumer channel closed, skipping warm");
                    }
                }
            }
        }
        HandoffPhase::Complete => {
            if let Some(sender) = registry.get_sender(&handoff.old_owner) {
                match sender.try_send(AssignmentEvent::Release(handoff.clone())) {
                    Ok(()) => {}
                    Err(TrySendError::Full(_)) => {
                        tracing::warn!(consumer = %handoff.old_owner, "consumer channel full, dropping release");
                    }
                    Err(TrySendError::Closed(_)) => {
                        tracing::debug!(consumer = %handoff.old_owner, "consumer channel closed, skipping release");
                    }
                }
            }
        }
        // Ready is a consumer → leader signal, not relayed to consumers.
        HandoffPhase::Ready => {}
    }
}
