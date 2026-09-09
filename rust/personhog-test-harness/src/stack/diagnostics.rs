use std::collections::{HashMap, HashSet};
use std::fmt::Write as _;
use std::fs;
use std::io::Write as _;
use std::path::Path;
use std::time::{Duration, Instant};

use personhog_coordination::protocol::{
    drain_satisfied, freeze_quorum_met, missing_freeze_ackers, warm_satisfied,
};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::{
    HandoffPhase, HandoffState, LeaderInfo, PartitionAssignment, PodDrainedAck, PodWarmedAck,
    RegisteredPod, RegisteredRouter, RouterFreezeAck,
};

/// Appends one line. Writing to a `String` cannot fail, so the discard
/// lives here instead of on every call.
macro_rules! emit {
    ($out:expr, $($arg:tt)*) => {{
        let _ = writeln!($out, $($arg)*);
    }};
}

/// Budget for the reads. An unresponsive etcd is a leading explanation
/// for a convergence timeout, so the dump says it could not read rather
/// than hanging the run behind the same problem.
const DUMP_DEADLINE: Duration = Duration::from_secs(10);

/// What the harness believes about the processes it spawned. etcd cannot
/// answer this: a registration outlives its process until the lease
/// lapses, so an owner that looks healthy in etcd can already be gone.
pub struct ProcessView {
    pub live_leaders: Vec<String>,
    pub paused_leaders: Vec<String>,
    pub routers: Vec<String>,
    pub retired: Vec<String>,
}

/// One read of coordination state, taken before anything is rendered so
/// the reads run concurrently and the rendering stays pure.
#[derive(Default)]
struct Coordination {
    leader: Option<LeaderInfo>,
    leader_lease: String,
    routers: Vec<RegisteredRouter>,
    pods: Vec<RegisteredPod>,
    assignments: Vec<PartitionAssignment>,
    handoffs: Vec<HandoffState>,
    /// Acks and quorum membership per in-flight handoff, by partition.
    acks: HashMap<u32, HandoffAcks>,
    /// Rendered lease state per registered name.
    pod_leases: HashMap<String, String>,
    router_leases: HashMap<String, String>,
    /// Reads that failed, so a missing section does not read as an
    /// empty one.
    errors: Vec<String>,
}

#[derive(Default)]
struct HandoffAcks {
    freeze: Vec<RouterFreezeAck>,
    drained: Vec<PodDrainedAck>,
    warmed: Vec<PodWarmedAck>,
    quorum: Option<Vec<String>>,
    unreadable: Vec<String>,
}

/// Snapshot pod registrations, their etcd leases, and coordinator state
/// (election holder, assignments, and what each in-flight handoff still
/// waits on). The text is returned for the failure message and appended
/// to `coordination-dump.txt` in the log directory, which CI uploads
/// with the service logs.
///
/// The dump answers what a bare timeout cannot: whether the leases
/// lapsed together because the runner starved the whole stack, or the
/// coordinator holds live pods and still will not advance.
pub async fn dump(
    store: &PersonhogStore,
    partitions: u32,
    view: &ProcessView,
    reason: &str,
    log_dir: &Path,
) -> String {
    let started = Instant::now();
    let state = tokio::time::timeout(DUMP_DEADLINE, gather(store))
        .await
        .unwrap_or_else(|_| Coordination {
            errors: vec![format!("etcd answered nothing within {DUMP_DEADLINE:?}")],
            ..Coordination::default()
        });

    let mut report = format!("=== coordination dump: {reason} ===\n");
    report.push_str(&host_line());
    report.push_str(&harness_line(view));
    report.push_str(&render(
        &state,
        partitions,
        view,
        chrono::Utc::now().timestamp_millis(),
    ));
    emit!(
        report,
        "etcd reads took {}ms",
        started.elapsed().as_millis()
    );

    let path = log_dir.join("coordination-dump.txt");
    let written = fs::File::options()
        .create(true)
        .append(true)
        .open(&path)
        .and_then(|mut file| file.write_all(report.as_bytes()));
    match written {
        Ok(()) => emit!(report, "(dump also written to {})", path.display()),
        Err(e) => emit!(report, "(dump not written to {}: {e})", path.display()),
    }
    report
}

/// Every read the dump needs, in two concurrent stages. Serialized,
/// the per-registration lease lookups and per-handoff ack lists would
/// dominate the round trips, on exactly the slow etcd that makes the
/// dump necessary.
async fn gather(store: &PersonhogStore) -> Coordination {
    let mut state = Coordination::default();
    let (leader, routers, pods, assignments, handoffs) = tokio::join!(
        store.get_leader(),
        store.list_routers(),
        store.list_pods(),
        store.list_assignments(),
        store.list_handoffs(),
    );
    state.leader = take("coordinator election", leader, &mut state.errors);
    state.routers = take("routers", routers, &mut state.errors);
    state.pods = take("pods", pods, &mut state.errors);
    state.assignments = take("assignments", assignments, &mut state.errors);
    state.handoffs = take("handoffs", handoffs, &mut state.errors);

    let (leader_lease, pod_leases, router_leases, acks) = tokio::join!(
        async {
            match &state.leader {
                Some(leader) => lease_state(store, leader.lease_id).await,
                None => String::new(),
            }
        },
        futures::future::join_all(state.pods.iter().map(|pod| async {
            let key = store.pod_registration_key(&pod.pod_name);
            (pod.pod_name.clone(), registration_lease(store, &key).await)
        })),
        futures::future::join_all(state.routers.iter().map(|router| async {
            let key = store.router_registration_key(&router.router_name);
            (
                router.router_name.clone(),
                registration_lease(store, &key).await,
            )
        })),
        futures::future::join_all(state.handoffs.iter().map(|h| handoff_acks(store, h))),
    );
    state.leader_lease = leader_lease;
    state.pod_leases = pod_leases.into_iter().collect();
    state.router_leases = router_leases.into_iter().collect();
    state.acks = state
        .handoffs
        .iter()
        .map(|h| h.partition)
        .zip(acks)
        .collect();
    state
}

async fn handoff_acks(store: &PersonhogStore, handoff: &HandoffState) -> HandoffAcks {
    let (freeze, drained, warmed, quorum) = tokio::join!(
        store.list_freeze_acks(handoff.partition),
        store.list_drained_acks(handoff.partition),
        store.list_warmed_acks(handoff.partition),
        store.resolve_freeze_quorum(handoff),
    );
    let mut acks = HandoffAcks::default();
    acks.freeze = take("freeze acks", freeze, &mut acks.unreadable);
    acks.drained = take("drained acks", drained, &mut acks.unreadable);
    acks.warmed = take("warmed acks", warmed, &mut acks.unreadable);
    acks.quorum = take("freeze quorum", quorum, &mut acks.unreadable);
    acks
}

/// The value, or the default with `what` recorded as unread. A read that
/// failed must not render as a state that is merely empty.
fn take<T: Default, E: std::fmt::Display>(
    what: &str,
    result: Result<T, E>,
    errors: &mut Vec<String>,
) -> T {
    match result {
        Ok(value) => value,
        Err(e) => {
            errors.push(format!("{what} ({e})"));
            T::default()
        }
    }
}

fn render(state: &Coordination, partitions: u32, view: &ProcessView, now_ms: i64) -> String {
    let now = now_ms / 1000;
    let mut out = String::new();

    match &state.leader {
        Some(leader) => emit!(
            out,
            "coordinator election: {} holds it, {}",
            leader.holder,
            state.leader_lease
        ),
        None => emit!(out, "coordinator election: vacant"),
    }

    emit!(out, "routers registered ({}):", state.routers.len());
    for router in &state.routers {
        emit!(
            out,
            "  {}  registered {}s ago  {}",
            router.router_name,
            now.saturating_sub(router.registered_at),
            lease_of(&state.router_leases, &router.router_name),
        );
    }

    emit!(out, "pods registered ({}):", state.pods.len());
    for pod in &state.pods {
        emit!(
            out,
            "  {}  {:?}  registered {}s ago  addr {}  {}  harness says {}",
            pod.pod_name,
            pod.status,
            now.saturating_sub(pod.registered_at),
            pod.advertise_address.as_deref().unwrap_or("-"),
            lease_of(&state.pod_leases, &pod.pod_name),
            harness_verdict(view, &pod.pod_name),
        );
    }

    emit!(
        out,
        "assignments ({} of {partitions}):",
        state.assignments.len()
    );
    for assignment in &state.assignments {
        emit!(
            out,
            "  partition {}  owner {}  {:?}  owner process {}",
            assignment.partition,
            assignment.owner,
            assignment.status,
            harness_verdict(view, &assignment.owner),
        );
    }
    let assigned: HashSet<u32> = state.assignments.iter().map(|a| a.partition).collect();
    let unassigned: Vec<String> = (0..partitions)
        .filter(|p| !assigned.contains(p))
        .map(|p| p.to_string())
        .collect();
    if !unassigned.is_empty() {
        emit!(out, "  unassigned partitions: {}", unassigned.join(","));
    }

    emit!(out, "handoffs in flight ({}):", state.handoffs.len());
    let empty = HandoffAcks::default();
    for handoff in &state.handoffs {
        emit!(
            out,
            "  partition {}  {:?}  {} -> {}  id {}  created {} ago  in phase for {}",
            handoff.partition,
            handoff.phase,
            handoff.old_owner.as_deref().unwrap_or("-"),
            handoff.new_owner,
            if handoff.handoff_id.is_empty() {
                "-"
            } else {
                &handoff.handoff_id
            },
            age(handoff.created_at_ms, handoff.started_at, now_ms),
            age(handoff.phase_entered_at_ms, handoff.started_at, now_ms),
        );
        let acks = state.acks.get(&handoff.partition).unwrap_or(&empty);
        emit!(out, "    {}", waiting_on(handoff, state, acks));
    }

    for error in &state.errors {
        emit!(out, "unread: {error}");
    }
    out
}

/// What a handoff still needs, judged with the coordinator's own advance
/// predicates. A phase whose predicate already holds is waiting on the
/// coordinator, which is what separates a stuck participant from a stuck
/// coordinator.
fn waiting_on(handoff: &HandoffState, state: &Coordination, acks: &HandoffAcks) -> String {
    let quorum = acks.quorum.as_deref();
    let mut line = match handoff.phase {
        HandoffPhase::Freezing => {
            if freeze_quorum_met(&state.routers, &acks.freeze, handoff, quorum) {
                "freeze quorum met; the coordinator has not advanced it".to_string()
            } else {
                format!(
                    "no freeze ack from {}",
                    missing_freeze_ackers(&state.routers, &acks.freeze, handoff, quorum).join(","),
                )
            }
        }
        HandoffPhase::Draining => {
            if drain_satisfied(&state.pods, &acks.drained, handoff) {
                "drain satisfied; the coordinator has not advanced it".to_string()
            } else {
                format!(
                    "no drained ack from old owner {}",
                    handoff.old_owner.as_deref().unwrap_or("-"),
                )
            }
        }
        HandoffPhase::Warming => {
            if warm_satisfied(&acks.warmed, handoff) {
                "warm satisfied; the coordinator has not completed it".to_string()
            } else {
                format!("no warmed ack from new owner {}", handoff.new_owner)
            }
        }
        HandoffPhase::Complete => "complete; the coordinator has not cleaned it up".to_string(),
    };
    if !acks.unreadable.is_empty() {
        let _ = write!(line, "  unread: {}", acks.unreadable.join(", "));
    }
    line
}

async fn registration_lease(store: &PersonhogStore, key: &str) -> String {
    let client = store.inner().client();
    let resp = match client.clone().get(key, None).await {
        Ok(resp) => resp,
        Err(e) => return format!("lease unread ({e})"),
    };
    let Some(kv) = resp.kvs().first() else {
        // Listed a moment ago, and already gone.
        return "registration key already gone".to_string();
    };
    match kv.lease() {
        0 => "no lease attached".to_string(),
        lease_id => lease_state(store, lease_id).await,
    }
}

async fn lease_state(store: &PersonhogStore, lease_id: i64) -> String {
    match store
        .inner()
        .client()
        .clone()
        .lease_time_to_live(lease_id, None)
        .await
    {
        Ok(lease) if lease.ttl() > 0 => format!(
            "lease {lease_id} ({}s of {}s left)",
            lease.ttl(),
            lease.granted_ttl()
        ),
        Ok(_) => format!("lease {lease_id} expired"),
        Err(e) => format!("lease {lease_id} ttl unread ({e})"),
    }
}

fn lease_of<'a>(leases: &'a HashMap<String, String>, name: &str) -> &'a str {
    leases
        .get(name)
        .map(String::as_str)
        .unwrap_or("lease unread")
}

fn harness_verdict(view: &ProcessView, pod_name: &str) -> &'static str {
    if view.live_leaders.iter().any(|name| name == pod_name) {
        "live"
    } else if view.paused_leaders.iter().any(|name| name == pod_name) {
        "paused (SIGSTOP)"
    } else {
        "gone"
    }
}

fn harness_line(view: &ProcessView) -> String {
    format!(
        "harness view: live leaders [{}], paused leaders [{}], routers [{}], retired [{}]\n",
        view.live_leaders.join(","),
        view.paused_leaders.join(","),
        view.routers.join(","),
        view.retired.join(","),
    )
}

/// Load average against CPU count. The gate shares a 4-vCPU runner with
/// Postgres, Kafka, etcd and the whole spawned stack, where scheduling
/// starvation stops every lease renewal at once and reads exactly like a
/// coordination wedge.
fn host_line() -> String {
    let cpus = std::thread::available_parallelism()
        .map(|n| n.get().to_string())
        .unwrap_or_else(|_| "?".to_string());
    match fs::read_to_string("/proc/loadavg") {
        Ok(raw) => {
            let load: Vec<&str> = raw.split_whitespace().take(3).collect();
            format!("host: load average {} across {cpus} cpus\n", load.join(" "))
        }
        Err(_) => format!("host: {cpus} cpus, load average unavailable\n"),
    }
}

/// Age from a millisecond stamp, falling back to the second-resolution
/// clock that predates it.
fn age(stamp_ms: i64, started_at_secs: i64, now_ms: i64) -> String {
    let stamp_ms = match (stamp_ms, started_at_secs) {
        (0, 0) => return "an unknown time".to_string(),
        (0, secs) => secs.saturating_mul(1000),
        (ms, _) => ms,
    };
    format!("{:.1}s", (now_ms - stamp_ms) as f64 / 1000.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use personhog_coordination::types::{
        AssignmentStatus, PodStatus, RegisteredPod, RegisteredRouter,
    };
    use uuid::Uuid;

    /// The dump only ever runs on a failure, so nothing else exercises
    /// it: a panic, a wrong key, or a lease lookup that reads the state
    /// as empty would only surface on the run that most needs it. Needs
    /// the CI gate's etcd; run explicitly with `--ignored`.
    #[tokio::test]
    #[ignore = "needs a local etcd"]
    async fn dump_names_leases_election_and_what_a_handoff_waits_on() {
        let endpoints =
            std::env::var("ETCD_ENDPOINTS").unwrap_or_else(|_| "http://localhost:2379".to_string());
        // A per-run prefix and log dir: a prior run's records live only
        // as long as their leases, but fresh keys avoid waiting that out.
        let run = Uuid::new_v4();
        let store = super::super::etcd::connect(&endpoints, &format!("/personhog-dump-{run}/"))
            .await
            .unwrap();
        let log_dir = std::env::temp_dir().join(format!("personhog-dump-{run}"));
        fs::create_dir_all(&log_dir).unwrap();

        let now = chrono::Utc::now().timestamp();
        let pod_lease = store.inner().grant_lease(30).await.unwrap();
        let router_lease = store.inner().grant_lease(30).await.unwrap();
        store
            .register_pod(
                &RegisteredPod {
                    pod_name: "harness-leader-0".to_string(),
                    generation: String::new(),
                    status: PodStatus::Ready,
                    registered_at: now,
                    last_heartbeat: now,
                    controller: None,
                    advertise_address: Some("127.0.0.1:24060".to_string()),
                },
                pod_lease,
            )
            .await
            .unwrap();
        store
            .register_router(
                &RegisteredRouter {
                    router_name: "harness-router-0".to_string(),
                    registered_at: now,
                    last_heartbeat: now,
                },
                router_lease,
            )
            .await
            .unwrap();
        assert!(store
            .try_acquire_leadership("harness-router-0", router_lease)
            .await
            .unwrap());
        store
            .put_assignments(&[PartitionAssignment {
                partition: 0,
                owner: "harness-leader-0".to_string(),
                advertise_address: Some("127.0.0.1:24060".to_string()),
                status: AssignmentStatus::Active,
            }])
            .await
            .unwrap();
        // Freezing with no ack from the one registered router: the
        // quorum is unmet, so the dump must name the router it waits on.
        store
            .put_handoff(&HandoffState {
                partition: 1,
                old_owner: Some("harness-leader-0".to_string()),
                new_owner: "harness-leader-1".to_string(),
                new_owner_address: None,
                phase: HandoffPhase::Freezing,
                started_at: now,
                handoff_id: "handoff-1".to_string(),
                freeze_quorum: None,
                freeze_quorum_ref: None,
                created_at_ms: chrono::Utc::now().timestamp_millis(),
                phase_entered_at_ms: chrono::Utc::now().timestamp_millis(),
            })
            .await
            .unwrap();

        let view = ProcessView {
            live_leaders: vec!["harness-leader-0".to_string()],
            paused_leaders: vec!["harness-leader-1".to_string()],
            routers: vec!["harness-router-0".to_string()],
            retired: vec!["leader-2".to_string()],
        };
        let report = dump(&store, 2, &view, "test timeout", &log_dir).await;

        assert!(
            report.contains("coordinator election: harness-router-0 holds it"),
            "{report}"
        );
        assert!(report.contains("of 30s left"), "{report}");
        assert!(
            report.contains("harness-leader-0  Ready") && report.contains("harness says live"),
            "{report}"
        );
        assert!(
            report.contains("assignments (1 of 2)") && report.contains("unassigned partitions: 1"),
            "{report}"
        );
        assert!(
            report.contains("harness-leader-0 -> harness-leader-1")
                && report.contains("no freeze ack from harness-router-0"),
            "{report}"
        );
        assert!(!report.contains("unread:"), "{report}");
        // The artifact copy is the point of writing it at all.
        let written = fs::read_to_string(log_dir.join("coordination-dump.txt")).unwrap();
        assert!(written.contains("handoffs in flight (1)"), "{written}");
    }
}
