//! The long-lived per-partition Stage 1 worker (TDD §2.3, §2.5).
//!
//! [`Stage1Worker::spawn`] takes ownership of one partition's channel `Receiver` (handed out by
//! [`PartitionRouter::add_partition`](crate::partitions::router::PartitionRouter::add_partition))
//! and drains it on a dedicated tokio task, applying each event through [`process_event`]. It
//! mirrors `kafka-deduplicator`'s `partition_worker.rs::run_worker`: a `while let Some(batch) =
//! recv().await` loop, sync state mutation inline (async WAL keeps writes sub-ms — no
//! `spawn_blocking` in M1), and **log-and-continue** on a store error so one bad event never wedges
//! the partition.
//!
//! ## Scope: no offset commit (PR 1.7)
//!
//! The worker deliberately does **not** call `mark_processed`. The `cohort_stream_events` consumer
//! offset is keyed by *that* topic's partition, while `ShuffleMessage::Event` only carries the
//! *upstream* `source_partition`/`source_offset` (used for per-key replay idempotence, a different
//! mechanism). The consumer that owns the real offsets — and therefore the commit loop — lands in
//! PR 1.7. PR 1.6 only drains, applies state, and surfaces transitions.

use std::time::Instant;

use metrics::{counter, histogram};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{info, warn};

use crate::consumers::events::CohortStreamEvent;
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::observability::metrics::{
    STAGE1_EVENTS_PROCESSED, STAGE1_EVENTS_SKIPPED, STAGE1_EVENT_PROCESS_DURATION,
    STAGE1_TRANSITIONS,
};
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::stage1::state::StateVariant;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::CohortStore;
use crate::workers::event_path::{process_event, SkipReason};
use std::sync::Arc;

/// A long-lived worker owning one partition's RocksDB-backed Stage 1 state. Spawned per assigned
/// partition; the task ends when the channel `Sender` is dropped (the router's shutdown signal).
pub struct Stage1Worker {
    partition_id: u16,
    handle: JoinHandle<()>,
}

impl Stage1Worker {
    /// Spawn a worker draining `receiver` for `partition_id`. `store` and `catalog` are shared
    /// handles (cheap `Arc` clones), so every partition's worker reads the same DB and the same
    /// atomically-swapped filter snapshot.
    pub fn spawn(
        partition_id: u16,
        receiver: mpsc::Receiver<Vec<ShuffleMessage>>,
        store: CohortStore,
        catalog: Arc<CatalogHandle>,
    ) -> Self {
        let handle = tokio::spawn(run_worker(partition_id, receiver, store, catalog));
        Self {
            partition_id,
            handle,
        }
    }

    /// The partition this worker owns.
    pub fn partition_id(&self) -> u16 {
        self.partition_id
    }

    /// Wait for the worker to finish draining and exit. Resolves once the channel `Sender` has been
    /// dropped and the loop has processed everything queued. Used by tests; PR 1.7's rebalance
    /// handler will own the production shutdown path.
    pub async fn join(self) -> Result<(), tokio::task::JoinError> {
        self.handle.await
    }
}

/// The drain loop. One batch at a time, one event at a time, in arrival order — the per-partition
/// ordering guarantee the affinity model rests on.
async fn run_worker(
    partition_id: u16,
    mut receiver: mpsc::Receiver<Vec<ShuffleMessage>>,
    store: CohortStore,
    catalog: Arc<CatalogHandle>,
) {
    info!(partition_id, "stage 1 worker started");

    while let Some(batch) = receiver.recv().await {
        for message in batch {
            match message {
                ShuffleMessage::Event(event) => {
                    handle_event(partition_id, &store, &catalog, &event);
                }
            }
        }
    }

    info!(partition_id, "stage 1 worker stopped");
}

/// Process one event end to end, emitting the event-level metrics. A team absent from the catalog
/// is the worker's own preflight skip; everything else flows through [`process_event`].
fn handle_event(
    partition_id: u16,
    store: &CohortStore,
    catalog: &CatalogHandle,
    event: &CohortStreamEvent,
) {
    let snapshot = catalog.load();
    let Some(team_filters) = snapshot.team(TeamId(event.team_id)) else {
        counter!(STAGE1_EVENTS_SKIPPED, "reason" => SkipReason::NoTeamFilters.as_str())
            .increment(1);
        return;
    };
    let filters: &TeamFilters = team_filters;

    let started = Instant::now();
    let result = process_event(partition_id, store, filters, event);
    histogram!(STAGE1_EVENT_PROCESS_DURATION).record(started.elapsed().as_secs_f64());

    match result {
        Ok(outcome) => {
            if let Some(reason) = outcome.skipped {
                counter!(STAGE1_EVENTS_SKIPPED, "reason" => reason.as_str()).increment(1);
                return;
            }
            counter!(STAGE1_EVENTS_PROCESSED).increment(1);
            for transition in &outcome.transitions {
                if let Some(kind) = transition_metric_label(filters, transition) {
                    counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
                }
            }
        }
        Err(error) => {
            // The store already counted the backend failure (store_errors_total); do not advance
            // any commit state — the event will be replayed once PR 1.7 owns offsets.
            warn!(
                partition_id,
                team_id = event.team_id,
                error = %error,
                "stage 1 store error; skipping event without advancing state",
            );
        }
    }
}

/// Map a transition to its `stage1_transitions_total{kind}` label by resolving the leaf's variant
/// in the current snapshot. `behavioral_left` is impossible in M1 (no eviction yet) and an unknown
/// LSK shouldn't occur, so those combinations emit no metric.
fn transition_metric_label(
    filters: &TeamFilters,
    transition: &LeafTransition,
) -> Option<&'static str> {
    let variant = filters.by_lsk.get(&transition.leaf_state_key)?.variant;
    match (variant, transition.kind) {
        (StateVariant::BehavioralSingle, TransitionKind::Entered) => Some("behavioral_entered"),
        (StateVariant::PersonProperty, TransitionKind::Entered) => Some("person_entered"),
        (StateVariant::PersonProperty, TransitionKind::Left) => Some("person_left"),
        (StateVariant::BehavioralSingle, TransitionKind::Left) => None,
    }
}
