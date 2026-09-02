use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use metrics::{counter, histogram};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub use assignment_coordination::util::{now_millis, now_seconds};

use crate::authority::AuthorityClock;
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

/// Record one supervisor-level failure against the consecutive budget;
/// returns `false` when it is exhausted. Progress resets the count
/// first, and INVARIANT: progress means *applied* work (a completed
/// convergence, an applied snapshot or event) — never a read that
/// changed nothing, which stays available in exactly the wedges the
/// budget exists for. Measured rather than time-based, because a
/// "healthy after N seconds" threshold exempts every failure detector
/// slower than N.
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

/// Log and count a coordination-run failure for a component with no
/// budget to spend. The coordinator is the one such component: it fails
/// over to a peer for free, a restart cannot mend an unwell etcd, and
/// its process also serves person writes and strong reads — so it
/// retries indefinitely and surfaces every failure.
pub(crate) fn record_run_failure(
    component: &'static str,
    name: &str,
    consecutive: u32,
    err: &Error,
) {
    counter!(
        "personhog_coordination_run_restarts_total",
        "component" => component
    )
    .increment(1);
    tracing::warn!(
        component,
        name,
        error = %err,
        consecutive,
        "coordination run failed; retrying while the data plane keeps serving"
    );
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
/// split-brain on the other face. The margin clock is anchored at each
/// renewal's *send* — the server restarts its countdown only after
/// that, when it processes the request — so the local measurement never
/// overstates how much lease is left, and every await in the loop is
/// bounded by the time left so a hang can never defer the verdict past
/// the moment the fence must begin.
#[allow(clippy::too_many_arguments)]
pub async fn run_lease_keepalive(
    store: Arc<PersonhogStore>,
    lease_id: i64,
    interval: Duration,
    lease_ttl: i64,
    granted_at: Instant,
    component: &'static str,
    // Published on every confirmed renewal, so the data plane can judge
    // its own authority without depending on this task being alive to
    // tell it. `None` for components that serve nothing.
    authority: Option<Arc<AuthorityClock>>,
    cancel: CancellationToken,
) -> Result<()> {
    let renewal_margin = AuthorityClock::renewal_margin(lease_ttl);
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
            // The renewal is anchored at its send: etcd restarts the
            // lease countdown when it processes the request, which can
            // only be after this instant, so measuring age from here
            // never overstates how much lease is left. Anchoring at the
            // response would credit the round-trip delay to the lease.
            let sent = Instant::now();
            // Renewals never pass through the store, so without this the
            // fleet's highest-rate etcd call is absent from both the call
            // attribution and the op-duration histogram — and after this
            // crate stopped candidates polling the election, renewals are
            // what is left at the top.
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
            let outcome = {
                // Scoped to the round alone. A timer living to the end of
                // the iteration would drop after the pacing sleep below
                // and record that instead — the interval, every time,
                // whatever etcd actually did. The round is abandoned at
                // `left.min(interval)` either way, so this measures
                // renewal latency up to that bound and cannot show one
                // beyond it; the margin, not this histogram, is what
                // catches those.
                crate::store::count_call("keep_alive_renewal");
                let _renewal = assignment_coordination::store::OpTimer::new("keep_alive_renewal");
                match tokio::time::timeout(left.min(interval), round).await {
                    Ok(r) => r,
                    Err(_) => Err(Error::invalid_state(format!(
                        "keepalive round unanswered within {:?}",
                        left.min(interval)
                    ))),
                }
            };
            match outcome {
                Ok(true) => {
                    // The gap between confirmations is the headroom
                    // question in one number: how close routine
                    // operation runs to the margin at which a pod stops
                    // being able to vouch for what it serves. Recorded
                    // whether or not anything is gating on it, so the
                    // distribution is known before it is enforced.
                    histogram!(
                        "personhog_coordination_lease_renewal_interval_ms",
                        "component" => component
                    )
                    .record(last_renewed.elapsed().as_secs_f64() * 1000.0);
                    last_renewed = sent;
                    if let Some(authority) = &authority {
                        authority.confirm(sent);
                    }
                }
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

/// The watch responses a live watcher can still deliver on. etcd
/// cancels a watcher with an ordinary response and delivers nothing to
/// it afterwards, so a loop that keeps awaiting is parked forever at
/// reconcile-tick latency with no error; surfacing the cancel as an
/// error routes it into the same retry that heals a broken stream.
pub(crate) fn live_watch_response(
    resp: Option<etcd_client::WatchResponse>,
    what: &str,
) -> Result<etcd_client::WatchResponse> {
    let resp = resp.ok_or_else(|| Error::invalid_state(format!("{what} watch stream ended")))?;
    if resp.canceled() {
        return Err(Error::invalid_state(format!(
            "{what} watcher cancelled by etcd (reason: {:?}, compact_revision: {})",
            resp.cancel_reason(),
            resp.compact_revision(),
        )));
    }
    Ok(resp)
}

/// Count one resolution that found no record — not one record lost: a
/// single missing record resolves once per frozen partition per pass,
/// so read it as a rate (how much work is degraded to the fallback),
/// never as a population.
pub fn record_unresolved_freeze_quorum() {
    metrics::counter!("personhog_coordination_unresolved_freeze_quorums_total").increment(1);
}

/// Count a handoff watch event by what this pod did with it. An event
/// the pod could not read must not land in `skipped`, or a fleet whose
/// records this binary cannot parse reads as scoping working perfectly.
pub fn record_handoff_event_disposition(disposition: &'static str) {
    metrics::counter!(
        "personhog_coordination_handoff_events_total",
        "disposition" => disposition
    )
    .increment(1);
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
    metrics::counter!("personhog_coordination_election_campaigns_total").increment(0);
    metrics::counter!("personhog_coordination_abdications_total").increment(0);
    metrics::counter!("personhog_coordination_election_observation_failures_total").increment(0);
    metrics::counter!("personhog_coordination_election_watch_interruptions_total").increment(0);
    for stage in ["list", "delete"] {
        metrics::counter!(
            "personhog_coordination_freeze_quorum_sweep_failures_total",
            "stage" => stage
        )
        .increment(0);
    }
    metrics::counter!("personhog_coordination_freeze_quorums_collected_total").increment(0);
    // The plan histograms are deliberately absent here. A counter
    // preregisters for free, but a histogram has no zero-observation
    // form: recording one would put a zero-byte plan into the very
    // series that exists to say how large plans get. They appear with
    // the first plan instead, and the first plan is not the one anybody
    // is watching for.
    metrics::counter!("personhog_coordination_store_calls_total", "site" => "apply_plan")
        .increment(0);
    // The coordinator's escalation story spans four series — this one
    // for terms that failed outright, `abdications_total` for terms
    // that lost leadership (a lease that cannot renew lands there, not
    // here, and it is the common bad ending under etcd degradation),
    // `election_observation_failures_total` for a candidate that
    // cannot read the election at all (a dark etcd), and
    // `election_watch_interruptions_total` for watches etcd cancels or
    // drops (a flapping etcd lands only there, with reads still
    // passing). Failures arrive in correlated bursts with quiet days
    // between — exactly the delta a lazily-registered counter loses.
    metrics::counter!(
        "personhog_coordination_run_restarts_total",
        "component" => "coordinator"
    )
    .increment(0);
    metrics::counter!("personhog_coordination_unresolved_freeze_quorums_total").increment(0);
    // Phase transitions fire only while handoffs are moving — the
    // flagship deploy-burst series, and the one most exposed to losing
    // its first delta. Freezing advances to Draining, or straight to
    // Warming when there is no old owner to drain.
    for (from, to) in [
        ("freezing", "draining"),
        ("freezing", "warming"),
        ("draining", "warming"),
        ("warming", "complete"),
    ] {
        metrics::counter!(
            "personhog_coordination_handoff_transitions_total",
            "from" => from,
            "to" => to,
        )
        .increment(0);
    }
    // Burst-shaped: these fire only during a mass cancellation, which is
    // exactly the delta a lazily-registered series loses.
    for reason in ["phase_deadline", "dead_new_owner"] {
        metrics::counter!("personhog_coordination_handoffs_cancelled_total", "reason" => reason)
            .increment(0);
    }
    for disposition in ["successor", "reaffirm", "delete"] {
        metrics::counter!(
            "personhog_coordination_handoffs_replaced_total",
            "disposition" => disposition
        )
        .increment(0);
    }
    metrics::gauge!("personhog_coordination_generation_hold_pods").set(0.0);
    metrics::gauge!("personhog_coordination_generation_capped_pods").set(0.0);
}

/// Same as [`preregister_coordinator_metrics`], for the counters a
/// writer pod's coordination layer emits.
pub fn preregister_pod_metrics() {
    // Emitted by the pod, so it belongs here rather than beside the
    // coordinator's counters — they run in different binaries, and a
    // series registered where nothing emits it is a permanent zero.
    metrics::counter!("personhog_coordination_partition_releases_total").increment(0);
    metrics::counter!(
        "personhog_coordination_run_restarts_total",
        "component" => "pod"
    )
    .increment(0);
    metrics::counter!(
        "personhog_coordination_keepalive_retries_total",
        "component" => "pod"
    )
    .increment(0);
    for disposition in ["converged", "skipped", "unreadable"] {
        metrics::counter!(
            "personhog_coordination_handoff_events_total",
            "disposition" => disposition
        )
        .increment(0);
    }
    // All burst-shaped: they fire during etcd blips and deploy churn
    // with quiet days between, which is when a lazily-registered series
    // loses its first delta.
    metrics::counter!(
        "personhog_coordination_reconcile_failures_total",
        "component" => "pod"
    )
    .increment(0);
    for outcome in ["run", "suppressed"] {
        metrics::counter!(
            "personhog_coordination_repair_passes_total",
            "outcome" => outcome
        )
        .increment(0);
    }
    metrics::counter!("personhog_coordination_registration_deleted_total").increment(0);
}

/// Same as [`preregister_coordinator_metrics`], for the counters the
/// router's coordination layer emits.
pub fn preregister_router_coordination_metrics() {
    for component in ["router", "coordinator"] {
        metrics::counter!(
            "personhog_coordination_keepalive_retries_total",
            "component" => component
        )
        .increment(0);
    }
    metrics::counter!(
        "personhog_coordination_run_restarts_total",
        "component" => "router"
    )
    .increment(0);
    metrics::counter!(
        "personhog_coordination_reconcile_failures_total",
        "component" => "router"
    )
    .increment(0);
    for outcome in ["revoked", "revoke_failed"] {
        metrics::counter!(
            "personhog_coordination_router_deregistered_total",
            "outcome" => outcome
        )
        .increment(0);
    }
    metrics::counter!("personhog_coordination_freeze_acks_written_total").increment(0);
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::sync::atomic::{AtomicBool, Ordering};

    use super::{new_handoff_id, note_run_failure};
    use crate::error::Error;

    /// Losing the election lease ends a leadership term but says nothing
    /// about this process's health — a successor takes over and
    /// reconciles. The coordinator's run loop tells the two apart on
    /// this predicate: an abdication is paced and counted, an error is
    /// paced and reported, and neither ends the process.
    #[test]
    fn an_abdication_is_not_a_process_failure() {
        assert!(Error::leadership_lost().is_leadership_lost());
        assert!(!Error::invalid_state("etcd unreachable").is_leadership_lost());
        assert!(!Error::NotFound("handoffs/7".to_string()).is_leadership_lost());
    }

    /// Applied work has to clear the count, or sporadic errors spread
    /// over hours add up to a restart of a healthy component. This is
    /// the pod's and router's supervisor — both serve continuously, so a
    /// stretch with no applied work is itself a symptom. The coordinator
    /// does not use it: it idles legitimately, and it never gives up.
    #[test]
    fn applied_work_clears_the_failure_count() {
        let progress = AtomicBool::new(false);
        let err = Error::invalid_state("etcd unreachable");
        let mut consecutive = 0u32;

        for attempt in 1..3 {
            assert!(
                note_run_failure(&mut consecutive, &progress, 3, "pod", "p", &err),
                "attempt {attempt} is within budget"
            );
        }

        progress.store(true, Ordering::SeqCst);
        assert!(
            note_run_failure(&mut consecutive, &progress, 3, "pod", "p", &err),
            "applied work resets the count"
        );
        assert_eq!(consecutive, 1);
    }

    /// And it must escalate when nothing succeeds in between — this is
    /// the wedge it exists for: winning the election and then failing the
    /// coordination loop returns an error every single time.
    #[test]
    fn an_unbroken_run_of_failures_exhausts_the_budget() {
        let progress = AtomicBool::new(false);
        let err = Error::invalid_state("list_handoffs failed");
        let mut consecutive = 0u32;

        assert!(note_run_failure(
            &mut consecutive,
            &progress,
            2,
            "pod",
            "p",
            &err
        ));
        assert!(
            !note_run_failure(&mut consecutive, &progress, 2, "pod", "p", &err),
            "the budget is spent, so the caller must stop retrying"
        );
    }

    /// Quorum correlation and cancellation detection hang off id
    /// uniqueness; ids minted in the same instant (a handoff cancelled
    /// and recreated within one millisecond) must never collide.
    #[test]
    fn new_handoff_id_is_unique_within_same_instant() {
        let ids: HashSet<String> = (0..1000).map(|_| new_handoff_id()).collect();
        assert_eq!(ids.len(), 1000);
    }
}
