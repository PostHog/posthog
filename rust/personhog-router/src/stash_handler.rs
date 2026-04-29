use std::sync::Arc;

use async_trait::async_trait;
use personhog_coordination::error::Result as CoordResult;
use personhog_coordination::routing_table::StashHandler;

use crate::backend::{LeaderBackend, LeaderOps};

/// Stash handler for the router. Reacts to handoff phase transitions:
///
/// * `Freezing` -> `begin_stash`: start buffering writes for the partition in
///   the shared `StashTable`. New writes park in a per-partition queue until
///   we see `Complete`.
/// * `Complete` -> `drain_stash`: flush the queue to the new owner in FIFO
///   order, then clear the stash so subsequent writes route normally via the
///   routing table.
///
/// We also clear the cached gRPC client for the new owner so the first
/// post-handoff request opens a fresh connection to the new leader pod.
pub struct RouterStashHandler {
    leader_backend: Arc<LeaderBackend>,
}

impl RouterStashHandler {
    pub fn new(leader_backend: Arc<LeaderBackend>) -> Self {
        Self { leader_backend }
    }
}

#[async_trait]
impl StashHandler for RouterStashHandler {
    async fn begin_stash(&self, partition: u32, new_owner: &str) -> CoordResult<()> {
        tracing::info!(
            partition,
            new_owner,
            "beginning stash for partition handoff"
        );
        self.leader_backend
            .stash_table()
            .begin_stash(partition)
            .await;
        Ok(())
    }

    async fn drain_stash(&self, partition: u32, new_owner: &str) -> CoordResult<()> {
        let drain_start = std::time::Instant::now();
        let stashed = self.leader_backend.stash_table().drain(partition).await;
        let batch_size = stashed.len();
        tracing::info!(
            partition,
            new_owner,
            stashed_count = batch_size,
            "draining stash to new owner"
        );
        metrics::histogram!("personhog_router_stash_drain_batch_size").record(batch_size as f64);

        // Drop the cached gRPC client for the new owner so the first
        // post-handoff request opens a fresh connection. The old owner's
        // client entry will simply age out — the routing table no longer
        // points at it, so it's never reused.
        self.leader_backend.clear_client_cache(new_owner);

        // Drain through the same forwarding path as live requests. By the
        // time this runs the routing table has already been updated to the
        // new owner (inline at handoff Complete in the routing table's
        // watch_handoffs_loop), so the standard partition lookup resolves
        // to the same pod we'd otherwise target explicitly. This also
        // gives drained requests the same retry-on-transient behavior as
        // normal traffic.
        for stashed_req in stashed {
            let wait_ms = stashed_req.enqueued_at.elapsed().as_secs_f64() * 1000.0;
            metrics::histogram!("personhog_router_stash_wait_duration_ms").record(wait_ms);

            let result = self
                .leader_backend
                .update_person_properties(stashed_req.request)
                .await;
            let outcome = if result.is_ok() { "success" } else { "error" };
            metrics::counter!(
                "personhog_router_stash_drained_total",
                "outcome" => outcome
            )
            .increment(1);

            // Receiver may have been dropped if the client disconnected;
            // the send error just carries the result back. Track that as
            // a separate signal — callers giving up on stashed requests
            // is operationally interesting (suggests stash latency
            // exceeded ingestion timeouts).
            if stashed_req.reply.send(result).is_err() {
                metrics::counter!("personhog_router_stash_dropped_total").increment(1);
            }
        }

        let drain_ms = drain_start.elapsed().as_secs_f64() * 1000.0;
        metrics::histogram!("personhog_router_stash_drain_duration_ms").record(drain_ms);
        Ok(())
    }
}
