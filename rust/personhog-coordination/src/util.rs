use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use metrics::counter;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub use assignment_coordination::util::{now_millis, now_seconds};

use crate::error::{Error, Result};
use crate::store::PersonhogStore;

/// Generate a handoff id unique across handoff attempts. The uuid makes
/// uniqueness structural — ids cannot collide across coordinator
/// failovers even if the wall clock steps backward — while the millis
/// prefix keeps ids sortable and debuggable.
pub fn new_handoff_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!("{}-{}", millis, Uuid::new_v4())
}

/// Record one supervisor-level failure (a bootstrap, an attempt, or a
/// lost lease) against the consecutive budget. Returns `false` when the
/// budget is exhausted. A failure that follows real progress — applied
/// work only: the pod on a completed convergence, the router on a
/// completed reconcile pass or an applied handoff event; never a mere
/// successful read, which stays available in wedges where convergence
/// itself is what fails — resets the count first: the budget bounds crash
/// loops, not the lifetime of a component that keeps doing useful work
/// between failures. Progress is measured rather than inferred from
/// elapsed time, because any fixed "healthy after N seconds" threshold
/// silently exempts every failure detector slower than N — the
/// reconcile failure budget and the participant stall watchdog both
/// take a minute to fire, so a time threshold in that range would let
/// exactly the wedged-but-slowly-failing states the budget exists for
/// rebuild in place forever.
pub(crate) fn note_run_failure(
    consecutive: &mut u32,
    progress: &AtomicBool,
    budget: u32,
    component: &'static str,
    name: &str,
    err: &Error,
) -> bool {
    if progress.swap(false, Ordering::SeqCst) {
        *consecutive = 1;
    } else {
        *consecutive += 1;
    }
    counter!(
        "personhog_coordination_run_restarts_total",
        "component" => component
    )
    .increment(1);
    tracing::warn!(
        component,
        name,
        error = %err,
        consecutive = *consecutive,
        budget,
        "coordination run failed; rebuilding in place while the data plane keeps serving"
    );
    *consecutive < budget
}

/// Maintain a lease keepalive until cancelled, treating connection
/// trouble and lease loss as the different things they are. A broken or
/// silent keepalive stream is evidence about one connection — the lease
/// itself lives in etcd's replicated keyspace and remains valid until
/// its TTL passes without a renewal. Ambiguous failures (stream errors,
/// unanswered rounds, failure to establish the stream) therefore
/// rebuild the stream and retry — the endpoint is a service, so a fresh
/// connection reaches a healthy member — for as long as the last
/// confirmed renewal is recent enough that the lease cannot be near
/// expiry.
///
/// Only two things end the keepalive with an error. etcd answering a
/// round with TTL <= 0 is an authoritative statement that the lease is
/// revoked or expired — immediate. And the renewal margin running out:
/// after two thirds of the TTL without a confirmed renewal, the caller
/// must fence *now* so the fence completes inside the final third,
/// before the coordinator can possibly treat the lease as expired.
/// Retrying past the margin would win availability on a coin flip and
/// split-brain on the other face. The margin clock starts at response
/// receipt — strictly after the server reset its own countdown — so the
/// local measurement is conservative, and every await in the loop is
/// bounded by the time left so a hang can never defer the verdict past
/// the moment the fence must begin.
pub async fn run_lease_keepalive(
    store: Arc<PersonhogStore>,
    lease_id: i64,
    interval: Duration,
    lease_ttl: i64,
    granted_at: Instant,
    component: &'static str,
    cancel: CancellationToken,
) -> Result<()> {
    let renewal_margin = Duration::from_secs(lease_ttl.max(0) as u64).mul_f64(2.0 / 3.0);
    // `clamp` panics when min > max, and sub-250ms intervals are
    // constructible from zero-valued env config; floor the pace instead.
    let retry_pace = (interval / 4)
        .max(Duration::from_millis(250))
        .min(interval.max(Duration::from_millis(250)));
    // Anchored at the grant, where the server's countdown started — not
    // at task spawn, which would overstate the first window's runway by
    // however long registration took.
    let mut last_renewed = granted_at;

    let margin_exhausted = || {
        Error::invalid_state(format!(
            "lease renewal margin exhausted: no confirmed renewal in {renewal_margin:?}"
        ))
    };

    'stream: loop {
        // (Re)establish the keepalive stream, bounded by the margin.
        let (mut keeper, mut stream) = loop {
            let left = renewal_margin.saturating_sub(last_renewed.elapsed());
            if left.is_zero() {
                return Err(margin_exhausted());
            }
            let attempt = tokio::time::timeout(left.min(interval), store.keep_alive(lease_id));
            let failure = tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                r = attempt => match r {
                    Ok(Ok(pair)) => break pair,
                    Ok(Err(e)) => e,
                    Err(_) => Error::invalid_state(
                        "keepalive stream establishment timed out".to_string(),
                    ),
                },
            };
            counter!(
                "personhog_coordination_keepalive_retries_total",
                "component" => component
            )
            .increment(1);
            tracing::warn!(
                lease_id,
                component,
                error = %failure,
                since_renewal = ?last_renewed.elapsed(),
                margin = ?renewal_margin,
                "keepalive stream failed; retrying within the lease margin"
            );
            let pace = retry_pace.min(renewal_margin.saturating_sub(last_renewed.elapsed()));
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tokio::time::sleep(pace) => {}
            }
        };

        // Renew immediately on a fresh stream: if it was rebuilt after
        // failures, the margin is already burning.
        loop {
            let left = renewal_margin.saturating_sub(last_renewed.elapsed());
            if left.is_zero() {
                return Err(margin_exhausted());
            }
            let round = async {
                keeper.keep_alive().await?;
                match stream.message().await? {
                    // Stream end is a connection fact, not a lease fact:
                    // etcd reports a revoked or expired lease as a normal
                    // response with TTL 0, so closure alone is ambiguous.
                    None => Err(Error::invalid_state("keepalive stream ended".to_string())),
                    Some(resp) if resp.ttl() <= 0 => Ok(false),
                    Some(_) => Ok(true),
                }
            };
            let outcome = match tokio::time::timeout(left.min(interval), round).await {
                Ok(r) => r,
                Err(_) => Err(Error::invalid_state(format!(
                    "keepalive round unanswered within {:?}",
                    left.min(interval)
                ))),
            };
            match outcome {
                Ok(true) => last_renewed = Instant::now(),
                // Authoritative: the lease is gone, no margin applies.
                Ok(false) => return Err(Error::leadership_lost()),
                Err(e) => {
                    counter!(
                        "personhog_coordination_keepalive_retries_total",
                        "component" => component
                    )
                    .increment(1);
                    tracing::warn!(
                        lease_id,
                        component,
                        error = %e,
                        since_renewal = ?last_renewed.elapsed(),
                        margin = ?renewal_margin,
                        "keepalive round failed; retrying within the lease margin"
                    );
                    let pace =
                        retry_pace.min(renewal_margin.saturating_sub(last_renewed.elapsed()));
                    tokio::select! {
                        _ = cancel.cancelled() => return Ok(()),
                        _ = tokio::time::sleep(pace) => {}
                    }
                    continue 'stream;
                }
            }
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tokio::time::sleep(interval) => {}
            }
        }
    }
}

/// Records how long a handoff phase write took to reach this observer's
/// watch stream. Only the non-terminal phases are recorded — those are
/// the writes whose propagation gates protocol progress, while Complete
/// puts (including cancellation reaffirms) arrive in floods that would
/// drown the signal. Same-cluster clocks make millisecond skew
/// negligible for the diagnostic purpose; records stamped by
/// pre-instrumentation writers (zero) are skipped.
pub fn record_phase_watch_delivery(
    observer: &'static str,
    phase: crate::types::HandoffPhase,
    phase_entered_at_ms: i64,
) {
    if phase == crate::types::HandoffPhase::Complete || phase_entered_at_ms <= 0 {
        return;
    }
    let lag = now_millis().saturating_sub(phase_entered_at_ms).max(0);
    metrics::histogram!(
        "personhog_coordination_phase_watch_delivery_ms",
        "observer" => observer
    )
    .record(lag as f64);
}

/// Records the coordinator's reaction lag: from the newest ack that
/// satisfied a quorum to the phase advance it triggered. Zero-stamped
/// acks (pre-instrumentation writers) are excluded.
pub fn record_ack_to_advance(phase: &'static str, ack_stamps_ms: impl Iterator<Item = i64>) {
    let Some(latest) = ack_stamps_ms.filter(|&t| t > 0).max() else {
        return;
    };
    let lag = now_millis().saturating_sub(latest).max(0);
    metrics::histogram!(
        "personhog_coordination_ack_to_advance_ms",
        "phase" => phase
    )
    .record(lag as f64);
}

/// Touch the coordinator's deploy-burst counters so their series exist
/// with zero samples before any burst. metrics registration is lazy: a
/// counter that first fires between two scrapes materializes with the
/// burst already inside it, and no rate function can recover a delta
/// that precedes a series' first sample.
pub fn preregister_coordinator_metrics() {
    for kind in ["fresh", "move"] {
        metrics::counter!("personhog_coordination_handoffs_created_total", "kind" => kind)
            .increment(0);
    }
    metrics::counter!("personhog_coordination_elections_won_total").increment(0);
    metrics::counter!("personhog_coordination_partition_releases_total").increment(0);
}

/// Same as [`preregister_coordinator_metrics`], for the counters the
/// router's coordination layer emits.
pub fn preregister_router_coordination_metrics() {
    for outcome in ["revoked", "revoke_failed"] {
        metrics::counter!(
            "personhog_coordination_router_deregistered_total",
            "outcome" => outcome
        )
        .increment(0);
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use super::new_handoff_id;

    /// Quorum correlation and cancellation detection hang off id
    /// uniqueness; ids minted in the same instant (a handoff cancelled
    /// and recreated within one millisecond) must never collide.
    #[test]
    fn new_handoff_id_is_unique_within_same_instant() {
        let ids: HashSet<String> = (0..1000).map(|_| new_handoff_id()).collect();
        assert_eq!(ids.len(), 1000);
    }
}
