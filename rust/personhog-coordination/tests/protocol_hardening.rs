//! Regression tests for the handoff-protocol hardening pass: self-fencing
//! on lease loss, post-drain write fencing, identity-based freeze quorum,
//! pod startup catch-up, the coordinator's reconcile tick,
//! revision-anchored watches, and cleanup scoped to dead new owners.
//!
//! All tests run against a real etcd at localhost:2379 with per-test key
//! prefixes, matching the conventions in `integration.rs`.

mod common;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{Mutex, RwLock};
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use async_trait::async_trait;
use common::{
    revoke_lease_of_key, start_coordinator, start_pod, start_pod_with_lease_ttl,
    start_router_with_lease_ttl, test_store, test_store_with_prefix, wait_for_condition,
    HandoffEvent, POLL_INTERVAL, WAIT_TIMEOUT,
};
use personhog_coordination::error::Result;
use personhog_coordination::routing_table::{RoutingTable, RoutingTableConfig, StashHandler};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::StickyBalancedStrategy;
use personhog_coordination::types::{
    AssignmentStatus, HandoffPhase, HandoffState, PartitionAssignment, PodStatus, RegisteredPod,
    RegisteredRouter, RouterFreezeAck,
};

/// Write a handoff record directly, bypassing the coordinator — gives the
/// test full control over phase sequencing.
async fn put_handoff(
    store: &PersonhogStore,
    partition: u32,
    old_owner: Option<&str>,
    new_owner: &str,
    phase: HandoffPhase,
) {
    let handoff = HandoffState {
        partition,
        old_owner: old_owner.map(str::to_string),
        new_owner: new_owner.to_string(),
        phase,
        started_at: 0,
    };
    store
        .create_assignments_and_handoffs(&[], &[handoff])
        .await
        .expect("write handoff");
}

/// Wait until the pod's recorded events contain `expected`.
async fn wait_for_event(events: &Arc<Mutex<Vec<HandoffEvent>>>, expected: HandoffEvent) {
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(events);
        let expected = expected.clone();
        async move { events.lock().await.contains(&expected) }
    })
    .await;
}

// ============================================================
// Fix 1: components self-fence when their lease disappears
// ============================================================
//
// The coordinator treats lease expiry as component death: it reassigns a
// "dead" pod's partitions and drops a "dead" router from the freeze
// quorum. A component that keeps serving after losing its lease is a
// zombie — a pod can accept writes for partitions the protocol has
// already handed off (split-brain changelog produces), and a router can
// forward writes without stashing during a freeze. Losing the lease must
// therefore terminate the component's run loop so its process restarts
// through the normal lifecycle.

/// A pod whose lease is revoked externally (simulating expiry during an
/// etcd partition or missed heartbeats) must exit its run loop rather
/// than continue serving as a zombie owner.
#[tokio::test]
async fn pod_self_fences_when_lease_revoked() {
    let (store, prefix) = test_store_with_prefix("pod-self-fence").await;
    let cancel = CancellationToken::new();

    // lease_ttl 5 → 1s heartbeat interval, so the keepalive observes the
    // revocation within ~a second.
    let mut pod = start_pod_with_lease_ttl(Arc::clone(&store), "fence-pod-0", 5, cancel.clone());

    // Wait until the pod has registered (its lease-bound key exists).
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "fence-pod-0"))
                .unwrap_or(false)
        }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}pods/fence-pod-0")).await;

    // The run loop must observe the dead lease and exit with an error —
    // NOT keep serving. Generous timeout: one heartbeat tick plus slack.
    let join = pod.join_handle.take().expect("join handle");
    let result = tokio::time::timeout(Duration::from_secs(10), join)
        .await
        .expect("pod must self-fence after lease revocation instead of serving as a zombie")
        .expect("pod task must not panic");
    assert!(
        result.is_err(),
        "run() must surface the lease loss as an error so the process restarts"
    );

    cancel.cancel();
}

/// A router whose lease is revoked must likewise exit: the coordinator
/// has already dropped it from the freeze quorum, so if it keeps serving
/// it can forward writes to a draining old owner without stashing.
#[tokio::test]
async fn router_exits_when_lease_revoked() {
    let (store, prefix) = test_store_with_prefix("router-self-fence").await;
    let cancel = CancellationToken::new();

    let mut router =
        start_router_with_lease_ttl(Arc::clone(&store), "fence-router-0", 5, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_routers()
                .await
                .map(|routers| routers.iter().any(|r| r.router_name == "fence-router-0"))
                .unwrap_or(false)
        }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}routers/fence-router-0")).await;

    let join = router.join_handle.take().expect("join handle");
    let result = tokio::time::timeout(Duration::from_secs(10), join)
        .await
        .expect("router must exit after lease revocation instead of serving with a stale table")
        .expect("router task must not panic");
    assert!(
        result.is_err(),
        "run() must surface the lease loss as an error so the process restarts"
    );

    cancel.cancel();
}

// ============================================================
// Fix 2 (pod side): cancelled handoffs resume the partition
// ============================================================
//
// Draining fences the partition against writes on the old owner. When a
// handoff is cancelled (`cleanup_stale_handoffs` deletes the record — e.g.
// the new owner died mid-warm), the old owner keeps the partition and
// routers drain their stashes back to it — so the pod must observe the
// deletion and resume the partition, or it stays write-fenced forever.

/// A handoff deleted mid-flight (after this pod drained as old owner)
/// must trigger `resume_partition` on the still-owning pod.
#[tokio::test]
async fn pod_resumes_partition_when_handoff_cancelled() {
    let store = test_store("handoff-cancel-resume").await;
    let cancel = CancellationToken::new();

    let pod = start_pod(Arc::clone(&store), "resume-pod-a", cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "resume-pod-a"))
                .unwrap_or(false)
        }
    })
    .await;

    // Give the pod ownership of partition 0 through a normal warm.
    put_handoff(&store, 0, None, "resume-pod-a", HandoffPhase::Warming).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;

    // A later handoff moves the partition away; the pod drains (and, on
    // the real leader, fences writes).
    put_handoff(
        &store,
        0,
        Some("resume-pod-a"),
        "resume-pod-b",
        HandoffPhase::Draining,
    )
    .await;
    wait_for_event(&pod.events, HandoffEvent::Drained(0)).await;

    // The handoff is cancelled (new owner gone). The pod still owns the
    // partition and must resume it.
    store.delete_handoff(0).await.expect("delete handoff");
    wait_for_event(&pod.events, HandoffEvent::Resumed(0)).await;

    cancel.cancel();
}

/// The record deletion after a normal `Complete` is cleanup, not a
/// cancellation: the old owner has already released the partition and
/// must NOT resume it.
#[tokio::test]
async fn handoff_cleanup_after_complete_does_not_resume() {
    let store = test_store("handoff-cleanup-no-resume").await;
    let cancel = CancellationToken::new();

    let pod = start_pod(Arc::clone(&store), "cleanup-pod-a", cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "cleanup-pod-a"))
                .unwrap_or(false)
        }
    })
    .await;

    put_handoff(&store, 0, None, "cleanup-pod-a", HandoffPhase::Warming).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;

    // Normal completion: the pod releases the partition…
    put_handoff(
        &store,
        0,
        Some("cleanup-pod-a"),
        "cleanup-pod-b",
        HandoffPhase::Complete,
    )
    .await;
    wait_for_event(&pod.events, HandoffEvent::Released(0)).await;

    // …then the coordinator deletes the record. No resume may fire.
    store.delete_handoff(0).await.expect("delete handoff");
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert!(
        !pod.events.lock().await.contains(&HandoffEvent::Resumed(0)),
        "post-Complete cleanup must not resume a released partition"
    );

    cancel.cancel();
}

// ============================================================
// Cleanup owns only unprogressable handoffs
// ============================================================
//
// A handoff whose OLD owner is dead progresses on its own: Freezing waits
// on routers (not the old owner), and Draining treats an absent old owner
// as vacuously drained. `cleanup_stale_handoffs` deleting such handoffs
// was a second, competing mechanism for the same state — racing the
// advance path and tearing down a healthy in-flight warm so rebalance
// could recreate it from scratch. Cleanup's job is only the handoff that
// truly cannot proceed: a dead NEW owner, whose WarmedAck will never
// arrive.

/// A Draining handoff with a dead old owner and a live new owner must
/// advance in place (Draining → Warming, original record intact) rather
/// than being deleted and recreated by rebalance.
#[tokio::test]
async fn dead_old_owner_handoff_advances_in_place_not_cleaned_up() {
    let store = test_store("advance-not-cleanup").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(1).await.expect("partitions");

    // The new owner is registered (directly — it never warms, so the
    // handoff parks in Warming where we can observe it). The old owner
    // was never registered: it is dead.
    let lease = store.grant_lease(60).await.expect("lease");
    store
        .register_pod(
            &RegisteredPod {
                pod_name: "survivor".to_string(),
                generation: String::new(),
                status: PodStatus::Ready,
                registered_at: 0,
                last_heartbeat: 0,
                controller: None,
            },
            lease,
        )
        .await
        .expect("register survivor");

    put_handoff(
        &store,
        0,
        Some("ghost-pod"),
        "survivor",
        HandoffPhase::Draining,
    )
    .await;

    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    // The advance path must move the ORIGINAL record to Warming. A
    // cleanup-and-recreate also produces a Warming handoff, but with
    // old_owner None — so old_owner is the discriminator throughout.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .get_handoff(0)
                .await
                .ok()
                .flatten()
                .is_some_and(|h| h.phase == HandoffPhase::Warming)
        }
    })
    .await;

    // A pod-change event re-runs cleanup; the parked handoff must not be
    // touched. Register a bystander to trigger it, then hold the
    // assertion across several reconcile ticks (500ms in tests).
    let bystander_lease = store.grant_lease(60).await.expect("lease");
    store
        .register_pod(
            &RegisteredPod {
                pod_name: "bystander".to_string(),
                generation: String::new(),
                status: PodStatus::Ready,
                registered_at: 0,
                last_heartbeat: 0,
                controller: None,
            },
            bystander_lease,
        )
        .await
        .expect("register bystander");

    for _ in 0..20 {
        let handoff = store
            .get_handoff(0)
            .await
            .expect("get handoff")
            .expect("handoff must survive cleanup passes");
        assert_eq!(
            handoff.old_owner.as_deref(),
            Some("ghost-pod"),
            "must be the original record advanced in place, not a cleanup-and-recreate"
        );
        assert_eq!(handoff.phase, HandoffPhase::Warming);
        tokio::time::sleep(POLL_INTERVAL).await;
    }

    cancel.cancel();
}

// ============================================================
// Fix 6: revision-anchored watches (no snapshot→watch gap)
// ============================================================
//
// Every participant bootstraps by reading a snapshot and then creating a
// watch. An unanchored watch begins at "now": any event landing between
// the snapshot read and the watch attaching is in neither, and etcd never
// redelivers it — the protocol deadlocks waiting for a response to an
// event nobody saw. Anchoring the watch to the snapshot's revision makes
// the gap impossible: events ≤ rev are in the snapshot, events > rev are
// replayed by the watch no matter when it attaches. This is the race
// behind the `release_partition_stops_serving` CI flake, made
// deterministic here.

/// An event written after the snapshot but before the watch exists must
/// still be delivered when the watch is anchored to the snapshot revision.
#[tokio::test]
async fn anchored_watch_delivers_events_written_before_attach() {
    let store = test_store("anchored-watch").await;

    // Participant startup with the race made certain: snapshot first…
    let (handoffs, rev) = store
        .list_handoffs_with_revision()
        .await
        .expect("snapshot with revision");
    assert!(handoffs.is_empty());

    // …then the event lands while no watch exists…
    put_handoff(&store, 7, None, "anchored-pod", HandoffPhase::Freezing).await;

    // …and only now does the watch attach. Anchored to the snapshot
    // revision, it replays everything since — including this event, which
    // predates the watch's existence. (An unanchored watch would start at
    // "now" and never deliver it.)
    let mut stream = store
        .watch_handoffs_from(rev + 1)
        .await
        .expect("anchored watch");

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    loop {
        let resp = tokio::time::timeout_at(deadline, stream.message())
            .await
            .expect("anchored watch must deliver the pre-attach event")
            .expect("watch stream")
            .expect("watch response");
        // The first response may be the watch-created confirmation with no
        // events; keep reading until the handoff arrives.
        if let Some(handoff) = resp
            .events()
            .iter()
            .find_map(|e| parse_watch_value::<HandoffState>(e).ok())
        {
            assert_eq!(handoff.partition, 7);
            assert_eq!(handoff.new_owner, "anchored-pod");
            return;
        }
    }
}

// ============================================================
// Fix 5: coordinator reconcile tick (liveness backstop)
// ============================================================
//
// Phase advancement is driven exclusively by watch events on acks and
// handoffs — but some state changes produce no such event. Nothing
// watches router registrations: when the one router blocking a freeze
// quorum departs (lease expiry), the quorum becomes satisfiable but no
// event ever re-evaluates it, and the handoff sticks in Freezing forever.
// A periodic reconcile tick re-runs the phase check for in-flight
// handoffs, backstopping every no-event and missed-event case.

/// A Freezing handoff whose quorum becomes satisfied by a router's
/// departure (no ack/handoff event fires) must still advance.
#[tokio::test]
async fn freezing_handoff_advances_when_unacked_router_departs() {
    let store = test_store("reconcile-tick").await;
    let cancel = CancellationToken::new();

    // Two registered routers. One acks; the other stays silent and will
    // depart.
    let lease_acked = store.grant_lease(30).await.expect("lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "router-acked".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            lease_acked,
        )
        .await
        .expect("register acked router");

    let lease_vanishing = store.grant_lease(30).await.expect("lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "router-vanishing".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            lease_vanishing,
        )
        .await
        .expect("register vanishing router");

    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    put_handoff(
        &store,
        0,
        Some("pod-old"),
        "pod-new",
        HandoffPhase::Freezing,
    )
    .await;
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "router-acked".to_string(),
            partition: 0,
            acked_at: 0,
        })
        .await
        .expect("ack");

    // Quorum unmet: the handoff holds in Freezing.
    tokio::time::sleep(Duration::from_secs(1)).await;
    let handoff = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert_eq!(handoff.phase, HandoffPhase::Freezing);

    // The silent router departs. Its registration vanishes with the
    // lease — an event on the routers prefix, which nothing watches.
    store
        .revoke_lease(lease_vanishing)
        .await
        .expect("revoke lease");

    // Only a time-driven reconcile can advance the handoff now.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .get_handoff(0)
                .await
                .ok()
                .flatten()
                .is_some_and(|h| h.phase != HandoffPhase::Freezing)
        }
    })
    .await;

    cancel.cancel();
}

// ============================================================
// Fix 4: pod catches up on pre-existing handoffs at startup
// ============================================================
//
// A pod that crash-restarts quickly (within its lease TTL) keeps its etcd
// registration, so `cleanup_stale_handoffs` never fires and no new Put
// arrives for a handoff created before the restart. Without a startup
// scan the restarted pod never learns its part — the handoff stalls in
// Draining/Warming forever.

/// A Warming handoff naming this pod as new owner that predates the pod's
/// start must be discovered and acted on: warm, then ack.
#[tokio::test]
async fn pod_catches_up_on_existing_warming_handoff_at_startup() {
    let store = test_store("pod-startup-warm-catchup").await;
    let cancel = CancellationToken::new();

    // The handoff exists before the pod starts — as after a fast restart.
    put_handoff(&store, 3, None, "catchup-pod", HandoffPhase::Warming).await;

    let pod = start_pod(Arc::clone(&store), "catchup-pod", cancel.clone());

    wait_for_event(&pod.events, HandoffEvent::Warmed(3)).await;

    // The WarmedAck must reach etcd so the coordinator can complete.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_warmed_acks(3)
                .await
                .map(|acks| acks.iter().any(|a| a.pod_name == "catchup-pod"))
                .unwrap_or(false)
        }
    })
    .await;

    cancel.cancel();
}

/// The old-owner variant: a Draining handoff that predates the pod's
/// start must be drained and acked. The restarted process has no inflight
/// handlers, so what matters is the DrainedAck reaching etcd.
#[tokio::test]
async fn pod_catches_up_on_existing_draining_handoff_at_startup() {
    let store = test_store("pod-startup-drain-catchup").await;
    let cancel = CancellationToken::new();

    put_handoff(
        &store,
        4,
        Some("drain-catchup-pod"),
        "some-other-pod",
        HandoffPhase::Draining,
    )
    .await;

    let pod = start_pod(Arc::clone(&store), "drain-catchup-pod", cancel.clone());

    wait_for_event(&pod.events, HandoffEvent::Drained(4)).await;

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_drained_acks(4)
                .await
                .map(|acks| acks.iter().any(|a| a.pod_name == "drain-catchup-pod"))
                .unwrap_or(false)
        }
    })
    .await;

    cancel.cancel();
}

// ============================================================
// Fix 3a: freeze quorum must be identity-based, not count-based
// ============================================================
//
// Freeze acks are not lease-bound: an ack from a router that has since
// deregistered survives until end-of-handoff cleanup. With a count-based
// quorum (`acks.len() >= routers.len()`), a stale ack can stand in for a
// live router that hasn't stashed yet — advancing to Draining while that
// router still forwards writes to the old owner.

/// A stale ack from a departed router must not satisfy the quorum on
/// behalf of a registered router that hasn't acked. Once the registered
/// router does ack, the handoff advances.
#[tokio::test]
async fn stale_freeze_ack_does_not_satisfy_quorum_for_live_router() {
    let store = test_store("identity-quorum").await;
    let cancel = CancellationToken::new();

    // A stale ack left behind by a router that has since deregistered
    // (acks are deliberately not lease-bound, so this survives).
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "router-departed".to_string(),
            partition: 0,
            acked_at: 0,
        })
        .await
        .expect("write stale ack");

    // A live, registered router that has NOT acked yet (registered
    // directly so no watch loop acks on its behalf).
    let lease_id = store.grant_lease(30).await.expect("lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "router-silent".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            lease_id,
        )
        .await
        .expect("register router");

    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    // A reassignment handoff enters Freezing. Ack count (1, stale) equals
    // router count (1, silent) — identity says the quorum is NOT met.
    put_handoff(
        &store,
        0,
        Some("pod-old"),
        "pod-new",
        HandoffPhase::Freezing,
    )
    .await;

    // The handoff must hold in Freezing while the registered router
    // hasn't acked.
    tokio::time::sleep(Duration::from_secs(2)).await;
    let handoff = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert_eq!(
        handoff.phase,
        HandoffPhase::Freezing,
        "a stale ack from a departed router must not stand in for a live router"
    );

    // The silent router acks → quorum genuinely met → advance.
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "router-silent".to_string(),
            partition: 0,
            acked_at: 0,
        })
        .await
        .expect("write live ack");

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .get_handoff(0)
                .await
                .ok()
                .flatten()
                .is_some_and(|h| h.phase != HandoffPhase::Freezing)
        }
    })
    .await;

    cancel.cancel();
}

// ============================================================
// Fix 3b: router catches up on handoffs before serving its table
// ============================================================

/// Records whether the routing table already exposed the partition at the
/// moment `begin_stash` fired.
struct StashOrderProbe {
    table: Arc<RwLock<HashMap<u32, String>>>,
    observed: Arc<Mutex<Vec<(u32, bool)>>>,
}

#[async_trait]
impl StashHandler for StashOrderProbe {
    async fn begin_stash(&self, partition: u32, _new_owner: &str) -> Result<()> {
        let table_populated = self.table.read().await.contains_key(&partition);
        self.observed
            .lock()
            .await
            .push((partition, table_populated));
        Ok(())
    }

    async fn drain_stash(&self, _partition: u32, _target: &str) -> Result<()> {
        Ok(())
    }
}

/// A router joining mid-handoff must open its stash before its routing
/// table can route the partition. In the reverse order there is a window
/// where a write routes to the old owner with no stash open — after the
/// old owner may already have drained.
#[tokio::test]
async fn late_joining_router_stashes_before_populating_table() {
    let store = test_store("stash-before-table").await;
    let cancel = CancellationToken::new();

    // Pre-existing state: an assignment for partition 0 and an in-flight
    // Freezing handoff moving it.
    store
        .create_assignments_and_handoffs(
            &[PartitionAssignment {
                partition: 0,
                owner: "pod-old".to_string(),
                status: AssignmentStatus::Active,
            }],
            &[],
        )
        .await
        .expect("write assignment");
    put_handoff(
        &store,
        0,
        Some("pod-old"),
        "pod-new",
        HandoffPhase::Freezing,
    )
    .await;

    // A router joins now — its startup catch-up must stash before the
    // table exposes partition 0.
    let router = RoutingTable::new(
        Arc::clone(&store),
        RoutingTableConfig {
            router_name: "late-router".to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
        },
    );
    let observed = Arc::new(Mutex::new(Vec::new()));
    let probe = StashOrderProbe {
        table: router.table_handle(),
        observed: Arc::clone(&observed),
    };
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(probe)).await });

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let observed = Arc::clone(&observed);
        async move { !observed.lock().await.is_empty() }
    })
    .await;

    let calls = observed.lock().await.clone();
    assert!(
        calls.contains(&(0, false)),
        "begin_stash must fire before the table exposes the partition; observed: {calls:?}"
    );

    cancel.cancel();
}
