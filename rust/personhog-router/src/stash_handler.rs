use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use futures::future::join_all;
use personhog_coordination::error::Result as CoordResult;
use personhog_coordination::routing_table::StashHandler;
use tonic::Code;

use crate::backend::{LeaderBackend, StashedRequest};
use crate::grpc_http::{grpc_error_response, grpc_status_code, is_grpc_error_response};

/// Stash handler for the router. Reacts to handoff phase transitions:
///
/// * `Freezing` / `Draining` / `Warming` → `begin_stash`: start (or
///   re-confirm) buffering leader-path requests — writes and strong
///   reads — for the partition in the shared `StashTable`. The routing-table layer calls `begin_stash` on
///   every non-terminal phase the router observes, so the call must
///   be idempotent — `StashTable::begin_stash` no-ops if the entry is
///   already live. New leader-path requests park in a per-partition
///   queue while the handoff progresses through
///   `Freezing → Draining → Warming`.
/// * `Complete` → `drain_stash`: forward the buffered requests to the
///   new owner, each to the method it arrived on. The drain runs as a loop over the queue; any request
///   that arrives during drain (the dashmap entry is still live until
///   drain observes the queue empty under the lock) is picked up by
///   the next iteration, preserving FIFO ordering across the cutover.
///
/// Two policies layer on top of the raw drain mechanism:
///
/// 1. **Per-request deadline.** Each stashed request carries an
///    `enqueued_at` timestamp; if its wait exceeds `max_stash_wait` we
///    fail it fast with `UNAVAILABLE` instead of forwarding. This caps
///    client-perceived latency during long drains and avoids the
///    silent-loss case where a stashed write completes at the leader
///    after the client's gRPC deadline expired (the client doesn't know
///    the outcome and may double-write on retry). With router-side
///    fail-fast under `UNAVAILABLE`, the client retries definitively.
///
/// 2. **Per-key concurrent forwarding.** Each drain batch is partitioned
///    by the leader's per-key serialization boundary
///    (`(team_id, person_id)`, the same key the leader's per-person
///    mutex uses). Requests for distinct keys forward in parallel
///    without affecting per-key ordering at the leader; requests for
///    the same key forward sequentially within a per-key sub-task.
///    This shrinks drain wall-clock duration without breaking
///    ordering guarantees.
///
/// We also clear the cached gRPC client for the new owner so the first
/// post-handoff request opens a fresh connection to the new leader pod.
pub struct RouterStashHandler {
    leader_backend: Arc<LeaderBackend>,
    /// Per-request deadline for stashed writes. Past-deadline requests
    /// fail fast with `UNAVAILABLE` during drain instead of forwarding.
    max_stash_wait: Duration,
    /// Maximum keys forwarded in parallel within a single drain batch.
    /// Per-key ordering is preserved (sequential within a key); across
    /// keys we fan out up to this many at once.
    drain_concurrency: usize,
}

impl RouterStashHandler {
    pub fn new(
        leader_backend: Arc<LeaderBackend>,
        max_stash_wait: Duration,
        drain_concurrency: usize,
    ) -> Self {
        // A drain_concurrency of 0 would mean "never forward" — treat
        // as 1 (fully sequential) to keep the contract sensible if
        // misconfigured.
        let drain_concurrency = drain_concurrency.max(1);
        Self {
            leader_backend,
            max_stash_wait,
            drain_concurrency,
        }
    }
}

/// Forward one stashed request, applying the per-request deadline. If
/// the request has been waiting longer than `max_stash_wait`, send back
/// `UNAVAILABLE` without forwarding so the client retries with a fresh
/// request. Otherwise forward via the unified routing path and pipe the
/// result through the oneshot. Tracks metrics for the five observable
/// outcomes (expired, success, fenced, error, dropped) so operators can
/// see stash-driven latency, drains racing a leader's fence or cutover,
/// leader failures during drain, and cases where the original caller
/// disconnected before the reply.
async fn forward_one(
    leader_backend: &LeaderBackend,
    max_stash_wait: Duration,
    partition: u32,
    stashed_req: StashedRequest,
) {
    let waited = stashed_req.enqueued_at.elapsed();
    metrics::histogram!("personhog_router_stash_wait_duration_ms")
        .record(waited.as_secs_f64() * 1000.0);

    if waited > max_stash_wait {
        // Past deadline — return a definitive UNAVAILABLE so the
        // client knows it must retry, instead of leaving them waiting
        // for a leader response that may exceed their gRPC timeout.
        let response = grpc_error_response(
            Code::Unavailable,
            "stash wait exceeded; retry through new owner",
        );
        if stashed_req.reply.send(response).is_err() {
            metrics::counter!("personhog_router_stash_dropped_total").increment(1);
        }
        metrics::counter!(
            "personhog_router_stash_drained_total",
            "outcome" => "expired"
        )
        .increment(1);
        return;
    }

    // Forward the buffered frame straight to the new owner. The router
    // stamps `x-partition` and the leader serializes per key, so replaying
    // here preserves arrival order without re-entering the stash. The
    // outcome label counts both transport failures and leader-returned
    // gRPC errors (trailers-only responses carry their status in the
    // headers, so no body poll is needed to classify them).
    let (response, outcome) = match leader_backend
        .forward_raw(
            stashed_req.method,
            partition,
            &stashed_req.headers,
            &stashed_req.frame,
        )
        .await
    {
        // A FailedPrecondition during drain means the target's fence or
        // ownership is still settling: a cancellation's drain-back races
        // the old owner's resume, and a completion's drain races the new
        // owner's cutover. The condition clears in watch-propagation
        // time, but FailedPrecondition reads as "do not retry" to
        // clients — remap it to the same definitive retry contract as
        // the deadline path above. Never silent: the write was never
        // acked.
        Ok((response, _call_ms))
            if grpc_status_code(&response) == Some(Code::FailedPrecondition as i32) =>
        {
            (
                grpc_error_response(
                    Code::Unavailable,
                    "leader transitioning during stash drain; retry",
                ),
                "fenced",
            )
        }
        Ok((response, _call_ms)) => {
            let outcome = if is_grpc_error_response(&response) {
                "error"
            } else {
                "success"
            };
            (response, outcome)
        }
        Err(status) => (
            grpc_error_response(status.code(), status.message()),
            "error",
        ),
    };
    metrics::counter!(
        "personhog_router_stash_drained_total",
        "outcome" => outcome
    )
    .increment(1);
    if stashed_req.reply.send(response).is_err() {
        metrics::counter!("personhog_router_stash_dropped_total").increment(1);
    }
}

/// Forward a single drain batch, fanning out across leader-side
/// serialization keys. Requests for the same `(team_id, person_id)`
/// forward sequentially in arrival order so the leader's per-person
/// lock processes them in the order routers received them; requests
/// for distinct keys forward in parallel, up to `concurrency` keys at
/// once. Returns when every request in the batch has been forwarded
/// (or fail-fasted by the deadline).
async fn forward_batch_by_key(
    leader_backend: Arc<LeaderBackend>,
    max_stash_wait: Duration,
    concurrency: usize,
    partition: u32,
    batch: Vec<StashedRequest>,
) {
    type Key = (i64, i64);
    let mut groups: HashMap<Key, Vec<StashedRequest>> = HashMap::new();
    for req in batch {
        groups.entry(req.key).or_default().push(req);
    }

    let mut groups_iter = groups.into_values();
    loop {
        let chunk: Vec<Vec<StashedRequest>> = (&mut groups_iter).take(concurrency).collect();
        if chunk.is_empty() {
            break;
        }
        let futures = chunk.into_iter().map(|group| {
            let leader = Arc::clone(&leader_backend);
            async move {
                for req in group {
                    forward_one(leader.as_ref(), max_stash_wait, partition, req).await;
                }
            }
        });
        join_all(futures).await;
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
        let drain_start = Instant::now();
        tracing::info!(partition, new_owner, "draining stash to new owner");

        // Drop the cached gRPC client for the new owner so the first
        // post-handoff request opens a fresh connection. The old
        // owner's client entry will simply age out — the routing table
        // no longer points at it, so it's never reused.
        self.leader_backend.clear_client_cache(new_owner);

        let leader_backend = Arc::clone(&self.leader_backend);
        let max_stash_wait = self.max_stash_wait;
        let drain_concurrency = self.drain_concurrency;
        let total_drained = Arc::new(std::sync::atomic::AtomicU64::new(0));
        let counter = Arc::clone(&total_drained);
        let stash_table = self.leader_backend.stash_table();

        // Drain loop: each batch the underlying `StashTable::drain`
        // hands us is forwarded with per-key fan-out. New requests
        // arriving during drain land on the same queue and are
        // delivered as a subsequent batch, preserving order.
        stash_table
            .drain(partition, |batch| {
                let leader = Arc::clone(&leader_backend);
                let counter = Arc::clone(&counter);
                async move {
                    let batch_size = batch.len() as u64;
                    forward_batch_by_key(
                        leader,
                        max_stash_wait,
                        drain_concurrency,
                        partition,
                        batch,
                    )
                    .await;
                    counter.fetch_add(batch_size, std::sync::atomic::Ordering::Relaxed);
                }
            })
            .await;

        let total = total_drained.load(std::sync::atomic::Ordering::Relaxed);
        metrics::histogram!("personhog_router_stash_drain_batch_size").record(total as f64);
        let drain_ms = drain_start.elapsed().as_secs_f64() * 1000.0;
        metrics::histogram!("personhog_router_stash_drain_duration_ms").record(drain_ms);
        tracing::info!(
            partition,
            new_owner,
            stashed_count = total,
            drain_ms,
            "drain complete"
        );
        Ok(())
    }
}
