use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use etcd_client::EventType;
use tokio::sync::mpsc::error::TrySendError;
use tokio_util::sync::CancellationToken;

use crate::consumer_registry::ConsumerRegistry;
use crate::error::{Error, Result};
use crate::store::{self, KafkaAssignerStore};
use crate::types::{
    AssignmentEvent, HandoffPhase, HandoffState, PartitionAssignment, TopicPartition,
};

const INITIAL_BACKOFF: Duration = Duration::from_secs(1);
const MAX_BACKOFF: Duration = Duration::from_secs(30);

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
    // Run both watch loops independently so one failing doesn't stop the other.
    // Each loop self-heals on transient etcd errors with exponential backoff.
    tokio::join!(
        relay_with_reconnect("assignments", &store, &registry, &cancel, |s, r, c| {
            Box::pin(relay_assignments(s, r, c))
        }),
        relay_with_reconnect("handoffs", &store, &registry, &cancel, |s, r, c| {
            Box::pin(relay_handoffs(s, r, c))
        }),
    );
    Ok(())
}

async fn relay_with_reconnect<F>(
    name: &str,
    store: &Arc<KafkaAssignerStore>,
    registry: &Arc<ConsumerRegistry>,
    cancel: &CancellationToken,
    relay_fn: F,
) where
    F: Fn(
        Arc<KafkaAssignerStore>,
        Arc<ConsumerRegistry>,
        CancellationToken,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send>>,
{
    let mut backoff = INITIAL_BACKOFF;

    loop {
        match relay_fn(Arc::clone(store), Arc::clone(registry), cancel.clone()).await {
            Ok(()) => return, // Clean shutdown via cancellation
            Err(e) => {
                if cancel.is_cancelled() {
                    return;
                }
                tracing::error!(
                    relay = name,
                    error = %e,
                    backoff_secs = backoff.as_secs(),
                    "relay watch failed, reconnecting"
                );
                tokio::select! {
                    _ = cancel.cancelled() => return,
                    _ = tokio::time::sleep(backoff) => {}
                }
                backoff = (backoff * 2).min(MAX_BACKOFF);
            }
        }
    }
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

/// Watch handoff changes and push batched `Warm`/`Release` events to affected consumers.
///
/// Like `relay_assignments`, this batches events per-consumer from each watch
/// response. Without batching, a rebalance moving hundreds of partitions would
/// send one event per partition, overflowing the consumer channel.
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

                let mut warms: HashMap<String, Vec<HandoffState>> = HashMap::new();
                let mut releases: HashMap<String, Vec<HandoffState>> = HashMap::new();

                for event in resp.events() {
                    if event.event_type() == EventType::Put {
                        match store::parse_watch_value::<HandoffState>(event) {
                            Ok(handoff) => match handoff.phase {
                                HandoffPhase::Warming => {
                                    warms
                                        .entry(handoff.new_owner.clone())
                                        .or_default()
                                        .push(handoff);
                                }
                                HandoffPhase::Complete => {
                                    releases
                                        .entry(handoff.old_owner.clone())
                                        .or_default()
                                        .push(handoff);
                                }
                                // Ready is a consumer → leader signal, not relayed.
                                HandoffPhase::Ready => {}
                            },
                            Err(e) => {
                                tracing::error!(error = %e, "failed to parse handoff event");
                            }
                        }
                    }
                }

                for (consumer, handoffs) in warms {
                    if let Some(sender) = registry.get_sender(&consumer) {
                        match sender.try_send(AssignmentEvent::Warm(handoffs)) {
                            Ok(()) => {}
                            Err(TrySendError::Full(_)) => {
                                tracing::warn!(consumer = %consumer, "consumer channel full, dropping warm batch");
                            }
                            Err(TrySendError::Closed(_)) => {
                                tracing::debug!(consumer = %consumer, "consumer channel closed, skipping warm batch");
                            }
                        }
                    }
                }

                for (consumer, handoffs) in releases {
                    if let Some(sender) = registry.get_sender(&consumer) {
                        match sender.try_send(AssignmentEvent::Release(handoffs)) {
                            Ok(()) => {}
                            Err(TrySendError::Full(_)) => {
                                tracing::warn!(consumer = %consumer, "consumer channel full, dropping release batch");
                            }
                            Err(TrySendError::Closed(_)) => {
                                tracing::debug!(consumer = %consumer, "consumer channel closed, skipping release batch");
                            }
                        }
                    }
                }
            }
        }
    }
}
