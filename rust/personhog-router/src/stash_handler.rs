use std::sync::Arc;
use std::time::{Duration, Instant};
use std::vec::IntoIter;

use async_trait::async_trait;
use futures::future::join_all;
use keyed_stash::Entry;
use personhog_coordination::error::Result as CoordResult;
use personhog_coordination::routing_table::StashHandler;
use tokio_util::sync::CancellationToken;
use tonic::Code;

use crate::backend::{
    BounceReason, DrainSession, ForwardDecision, ForwardPath, LeaderBackend, StashKey,
    StashedRequest, TakenKeyRun, BOUNCE_BACKOFF, MAX_CONSECUTIVE_BOUNCES,
};
use crate::grpc_http::{grpc_error_response, is_grpc_error_response};

/// Stash handler for the router. Reacts to handoff phase transitions:
///
/// * `Freezing` / `Draining` / `Warming` → `begin_stash`: start (or
///   re-confirm) buffering leader-path requests — writes and strong
///   reads — for the partition in the shared `StashTable`. The
///   routing-table layer calls `begin_stash` on every non-terminal phase
///   the router observes, so the call must be idempotent —
///   `StashTable::begin_stash` no-ops if the entry is already live. New
///   leader-path requests park in per-key queues while the handoff
///   progresses through `Freezing → Draining → Warming`.
/// * `Complete` → `drain_stash`: forward the buffered requests to the
///   new owner, each to the method it arrived on, through a
///   `DrainSession`. The drain loops taking per-key front runs until it
///   observes the queue fully settled; any request that arrives during
///   the drain lands on the same queue and is picked up by a later take.
///
/// Every stashed request ends in exactly one of two ways: a definitive
/// outcome delivered to its client (the forwarded response, an expiry
/// `UNAVAILABLE`, or a terminal error), or a put-back that re-parks it
/// at its admission position for a later attempt. Nothing is failed
/// merely because a particular drain attempt could not finish. The
/// policies layered on the session:
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
/// 2. **Per-key concurrent forwarding.** Each wave takes up to
///    `drain_concurrency` keys' front runs — the leader's per-key
///    serialization boundary (`(team_id, person_id)`, the same key the
///    leader's per-person mutex uses) — and forwards them in parallel,
///    sequential within each key. This shrinks drain wall-clock duration
///    without breaking per-key ordering at the leader.
///
/// 3. **Bounce and retry.** A classified forward attempt (see
///    `LeaderBackend::forward_classified`, the single reading of leader
///    responses shared with the direct path) can conclude no outcome
///    exists: a `FailedPrecondition` from the target (its fence or
///    ownership is still settling — a reaffirm's drain racing the
///    owner's resume, or a completion's drain racing the new owner's
///    cutover), an unroutable target (a table or address gap the
///    reconcile pass will heal), or a transport failure (the target pod
///    restarting or briefly unreachable). The bounced request and the rest of its key
///    run are put back, the drain backs off `BOUNCE_BACKOFF` and
///    retries; after `MAX_CONSECUTIVE_BOUNCES` bounced waves it yields
///    the lane and lets the reconcile pass re-request the drain.
///    Clients never see a bounce — their requests simply stay parked
///    until the condition clears or their deadline expires. A transport
///    bounce marks the request `possibly_applied` (the leader may have
///    processed it without us seeing the response); re-forwarding it is
///    an at-least-once replay, counted by
///    `personhog_router_stash_replayed_total` and covered by the
///    redelivery contract in `personhog-leader`'s README. A
///    response the leader actually produced is never bounced — even an
///    error status is a real outcome, and `UNAVAILABLE` from the leader
///    is its backpressure signal, which parking would invert.
///
/// 4. **Cooperative cancellation.** A paused or superseded drain stops
///    at the next request boundary and puts everything it took back:
///    unprocessed entries stay parked, in order, for the successor
///    drain. Cancellation is a routing decision, not a request outcome,
///    so it is invisible to clients.
///
/// We also clear the cached gRPC client for the new owner so the first
/// post-handoff request opens a fresh connection to the new leader pod.
pub struct RouterStashHandler {
    leader_backend: Arc<LeaderBackend>,
    /// Per-request deadline for stashed writes. Past-deadline requests
    /// fail fast with `UNAVAILABLE` during drain instead of forwarding.
    max_stash_wait: Duration,
    /// Maximum keys forwarded in parallel within a single drain wave.
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

/// What a single drain forward attempt decided.
enum Disposition {
    /// The request has a definitive outcome: reply to the client with
    /// this response and complete the entry under the given label.
    Reply {
        response: http::Response<tonic::body::BoxBody>,
        outcome: &'static str,
    },
    /// No outcome exists; the entry (and the rest of its key run) must
    /// be put back for a later attempt.
    Bounce(BounceReason),
}

/// Attempt one stashed request without consuming it. Applies the
/// per-request deadline first: a past-deadline request gets a definitive
/// `UNAVAILABLE` so the client retries with a fresh request rather than
/// waiting out a response that may exceed its gRPC timeout. Otherwise
/// the attempt is one classified forward — the same shared reading of
/// leader responses the direct path uses (see
/// `LeaderBackend::forward_classified`), so the two paths cannot drift
/// in what counts as an outcome versus a bounce.
async fn forward_one(
    leader_backend: &LeaderBackend,
    max_stash_wait: Duration,
    partition: u32,
    req: &StashedRequest,
) -> Disposition {
    if req.enqueued_at.elapsed() > max_stash_wait {
        return Disposition::Reply {
            response: grpc_error_response(
                Code::Unavailable,
                "stash wait exceeded; retry through new owner",
            ),
            outcome: "expired",
        };
    }
    if req.possibly_applied {
        metrics::counter!("personhog_router_stash_replayed_total").increment(1);
    }

    // Forward the buffered frame straight to the new owner. The router
    // stamps `x-partition` and the leader serializes per key, so replaying
    // here preserves arrival order without re-entering the stash.
    match leader_backend
        .forward_classified(
            ForwardPath::Stash,
            req.method,
            partition,
            &req.headers,
            &req.frame,
        )
        .await
    {
        ForwardDecision::Delivered { response, .. } => {
            let outcome = if is_grpc_error_response(&response) {
                "error"
            } else {
                "success"
            };
            Disposition::Reply { response, outcome }
        }
        ForwardDecision::Bounced(reason) => Disposition::Bounce(reason),
    }
}

/// What one key run's attempt produced, aggregated per wave to drive the
/// bounce backoff.
struct KeyRunOutcome {
    completed: u64,
    bounced: bool,
}

/// Put an interrupted key run's remainder back at its admission
/// positions: the entry whose attempt was cut short plus everything not
/// yet attempted. Retry accounting stays with the callers — only an
/// actually-attempted head counts as a stash-path retry, so the
/// never-attempted tail goes back uncounted.
async fn put_back_rest(
    session: &DrainSession,
    key: StashKey,
    head: Entry<StashedRequest>,
    rest: IntoIter<Entry<StashedRequest>>,
) {
    let mut entries = vec![head];
    entries.extend(rest);
    session.put_back(key, entries).await;
}

/// Forward one key's front run sequentially, recording a definitive
/// outcome per delivered entry. Stops early on cancellation or a
/// bounce, putting the remainder back in order.
async fn forward_key_run(
    leader_backend: &LeaderBackend,
    session: &DrainSession,
    max_stash_wait: Duration,
    partition: u32,
    cancel: &CancellationToken,
    run: TakenKeyRun,
) -> KeyRunOutcome {
    let mut outcome = KeyRunOutcome {
        completed: 0,
        bounced: false,
    };
    let mut entries = run.entries.into_iter();
    while let Some(mut entry) = entries.next() {
        if cancel.is_cancelled() {
            put_back_rest(session, run.key, entry, entries).await;
            return outcome;
        }
        // Race the forward against cancellation: an in-flight call can
        // otherwise hold this lane for the full backend timeout, and at
        // router shutdown the drain-lane join sits between cancellation
        // and the lease revoke — a slow forward there delays
        // deregistration, stalling every freeze that counts this router.
        let forwarded = tokio::select! {
            biased;
            _ = cancel.cancelled() => None,
            d = forward_one(leader_backend, max_stash_wait, partition, &entry.item) => Some(d),
        };
        let Some(disposition) = forwarded else {
            // The abandoned call may already be on the wire, so the
            // outcome is unknown — same ambiguity as a transport bounce,
            // same conservative marking.
            entry.item.possibly_applied = true;
            metrics::counter!(
                "personhog_router_forward_retries_total",
                "path" => ForwardPath::Stash.label(),
                "reason" => "cancelled"
            )
            .increment(1);
            put_back_rest(session, run.key, entry, entries).await;
            return outcome;
        };
        match disposition {
            Disposition::Reply {
                response,
                outcome: label,
            } => {
                let size = entry.item.approximate_size();
                metrics::histogram!("personhog_router_stash_wait_duration_ms")
                    .record(entry.item.enqueued_at.elapsed().as_secs_f64() * 1000.0);
                if entry.item.reply.send(response).is_err() {
                    metrics::counter!(
                        "personhog_router_stash_dropped_total",
                        "reason" => "receiver_gone"
                    )
                    .increment(1);
                }
                metrics::counter!(
                    "personhog_router_stash_drained_total",
                    "outcome" => label
                )
                .increment(1);
                session.complete(run.key, size).await;
                outcome.completed += 1;
            }
            Disposition::Bounce(reason) => {
                if matches!(reason, BounceReason::Transport) {
                    entry.item.possibly_applied = true;
                }
                metrics::counter!(
                    "personhog_router_forward_retries_total",
                    "path" => ForwardPath::Stash.label(),
                    "reason" => reason.label()
                )
                .increment(1);
                put_back_rest(session, run.key, entry, entries).await;
                outcome.bounced = true;
                return outcome;
            }
        }
    }
    outcome
}

#[async_trait]
impl StashHandler for RouterStashHandler {
    fn stash_pending(&self, partition: u32) -> bool {
        self.leader_backend.stash_table().has_entry(partition)
    }

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

    async fn drain_stash(
        &self,
        partition: u32,
        new_owner: &str,
        cancel: CancellationToken,
    ) -> CoordResult<()> {
        let stash_table = self.leader_backend.stash_table();
        let Some(session) = stash_table.drain_session(partition) else {
            // Nothing stashed — the partition never froze, or a prior
            // drain already settled it.
            return Ok(());
        };
        let drain_start = Instant::now();
        tracing::info!(partition, new_owner, "draining stash to new owner");

        // Drop the cached gRPC client for the new owner so the first
        // post-handoff request opens a fresh connection. The old
        // owner's entry stays in the cache unused — the routing table
        // no longer points at it — and is reclaimed only if that
        // address is ever resolved again; the cache has no eviction.
        self.leader_backend.clear_client_cache(new_owner);

        let mut completed_total: u64 = 0;
        let mut bounced_waves: u32 = 0;
        loop {
            if cancel.is_cancelled() {
                // Paused or superseded between waves: nothing is in
                // flight, the backlog stays parked for the successor.
                break;
            }
            let taken = session.take_for_attempt(self.drain_concurrency).await;
            if taken.is_empty() {
                if session.finish_if_settled().await {
                    break;
                }
                // An arrival raced the settle check; take again.
                continue;
            }

            let outcomes = join_all(taken.into_iter().map(|run| {
                forward_key_run(
                    &self.leader_backend,
                    &session,
                    self.max_stash_wait,
                    partition,
                    &cancel,
                    run,
                )
            }))
            .await;
            completed_total += outcomes.iter().map(|o| o.completed).sum::<u64>();

            if outcomes.iter().any(|o| o.bounced) {
                bounced_waves += 1;
                if bounced_waves >= MAX_CONSECUTIVE_BOUNCES {
                    tracing::info!(
                        partition,
                        new_owner,
                        waves = bounced_waves,
                        "target still bouncing after repeated waves; \
                         yielding drain lane to the reconcile pass"
                    );
                    break;
                }
                tokio::select! {
                    _ = cancel.cancelled() => break,
                    _ = tokio::time::sleep(BOUNCE_BACKOFF) => {}
                }
            } else {
                bounced_waves = 0;
            }
        }

        metrics::histogram!("personhog_router_stash_drain_batch_size")
            .record(completed_total as f64);
        let drain_ms = drain_start.elapsed().as_secs_f64() * 1000.0;
        metrics::histogram!("personhog_router_stash_drain_duration_ms").record(drain_ms);
        tracing::info!(
            partition,
            new_owner,
            stashed_count = completed_total,
            drain_ms,
            "drain finished"
        );
        Ok(())
    }
}
