//! Regression tests for the handoff-protocol hardening pass: self-fencing
//! on lease loss, post-drain write fencing, identity-based freeze quorum,
//! pod state convergence (startup reconcile + event-driven re-derivation),
//! the coordinator's reconcile tick, revision-anchored watches,
//! ack-to-handoff correlation, and cleanup scoped to dead new owners.
//!
//! All tests run against a real etcd at localhost:2379 with per-test key
//! prefixes, matching the conventions in `integration.rs`.

mod common;

use std::collections::HashMap;
use std::future::pending;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{Mutex, RwLock};
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use async_trait::async_trait;
use common::{
    revoke_lease_of_key, start_coordinator, start_coordinator_named,
    start_coordinator_reconcile_parked, start_pod, start_pod_gated, start_pod_with_lease_ttl,
    start_router_with_lease_ttl, store_at, test_store, test_store_with_prefix, wait_for_condition,
    CutoverEvent, FlakyProxy, HandoffEvent, MockCutoverHandler, MockHandoffHandler, ETCD_ENDPOINT,
    POLL_INTERVAL, WAIT_TIMEOUT,
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
        handoff_id: format!("test-handoff-{partition}"),
        freeze_quorum: None,
        created_at_ms: 0,
        phase_entered_at_ms: 0,
        new_owner_address: None,
    };
    // Raw put on purpose: fixtures force arbitrary handoff states,
    // including overwriting an existing one, which the guarded
    // plan-application path rightly refuses.
    store.put_handoff(&handoff).await.expect("write handoff");
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
async fn pod_self_fences_locally_and_rejoins_after_lease_loss() {
    let (store, prefix) = test_store_with_prefix("pod-self-fence").await;
    let cancel = CancellationToken::new();

    // lease_ttl 5 → 1s heartbeat interval, so the keepalive observes the
    // revocation within ~a second.
    let pod = start_pod_with_lease_ttl(Arc::clone(&store), "fence-pod-0", 5, cancel.clone());

    // Wait until the pod has registered, then hand it a partition so
    // the self-fence has something real to release.
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
    put_handoff(&store, 0, None, "fence-pod-0", HandoffPhase::Warming).await;
    let warmed_count = |events: Arc<Mutex<Vec<HandoffEvent>>>| async move {
        events
            .lock()
            .await
            .iter()
            .filter(|e| matches!(e, HandoffEvent::Warmed(0)))
            .count()
    };
    let events = Arc::clone(&pod.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { warmed_count(events).await >= 1 }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}pods/fence-pod-0")).await;

    // Lease loss must self-fence: the held partition is released
    // locally before any rejoin, because the coordinator already treats
    // the expired lease as death and may be reassigning. The fence must
    // drain before it releases — release alone unfences and drops the
    // cache without waiting, letting an already-admitted write ack
    // after the replacement owner's warm — so `Drained` must precede
    // `Released` in the fence sequence.
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events
                .lock()
                .await
                .iter()
                .any(|e| matches!(e, HandoffEvent::Released(0)))
        }
    })
    .await;
    {
        let events = events.lock().await;
        let drained = events
            .iter()
            .position(|e| matches!(e, HandoffEvent::Drained(0)));
        let released = events
            .iter()
            .position(|e| matches!(e, HandoffEvent::Released(0)));
        assert!(
            matches!((drained, released), (Some(d), Some(r)) if d < r),
            "the self-fence must drain (fence + quiesce) before releasing: {events:?}"
        );
    }

    // The supervisor then rejoins as a fresh participant instead of
    // dying: the pod re-registers, and startup convergence re-warms the
    // still-Warming partition it just released.
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
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { warmed_count(events).await >= 2 }
    })
    .await;

    cancel.cancel();
}

/// A router whose lease is revoked must likewise exit: the coordinator
/// has already dropped it from the freeze quorum, so if it keeps serving
/// it can forward writes to a draining old owner without stashing.
#[tokio::test]
async fn router_rejoins_with_a_fresh_lease_after_revocation() {
    let (store, prefix) = test_store_with_prefix("router-self-fence").await;
    let cancel = CancellationToken::new();

    let _router =
        start_router_with_lease_ttl(Arc::clone(&store), "fence-router-0", 5, cancel.clone());

    let registered = |store: Arc<PersonhogStore>| async move {
        store
            .list_routers()
            .await
            .map(|routers| routers.iter().any(|r| r.router_name == "fence-router-0"))
            .unwrap_or(false)
    };
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        registered(Arc::clone(&check_store))
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}routers/fence-router-0")).await;

    // The failed attempt tears down (the revoked lease already removed
    // the registration, so freeze quorums stop counting the router) and
    // the supervisor rejoins with a fresh lease instead of dying.
    // Serving through the gap is safe: any handoff created while the
    // router is unregistered excludes it from the freeze quorum, so the
    // old owner fences before a new owner warms and stale forwards
    // bounce rather than land.
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { !registered(store).await }
    })
    .await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        registered(Arc::clone(&check_store))
    })
    .await;

    cancel.cancel();
}

/// A leader whose election lease is revoked externally must abdicate and
/// re-campaign, not keep coordinating as a zombie on a dead lease. Unlike
/// pods and routers, the coordinator's run loop survives lease loss by
/// design — so the observable contract is in etcd: with a single
/// candidate, the leader key can only reappear if the old leader noticed
/// the loss and ran a fresh campaign; a zombie leaves it absent forever.
#[tokio::test]
async fn coordinator_abdicates_and_recampaigns_when_election_lease_revoked() {
    let (store, prefix) = test_store_with_prefix("coordinator-abdicate").await;
    let cancel = CancellationToken::new();

    // lease_ttl 5 → 1s keepalive, so the loss is observed within ~a second.
    let handle = start_coordinator_named(
        Arc::clone(&store),
        "abdicate-coordinator-0",
        5,
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.get_leader().await.ok().flatten().is_some() }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}coordinator/leader")).await;

    // Keepalive notices within ~1s, abdication plus the 1s campaign retry
    // re-creates the key — well inside 10s against local etcd.
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(10), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.get_leader().await.ok().flatten().is_some() }
    })
    .await;

    cancel.cancel();
    tokio::time::timeout(Duration::from_secs(10), handle)
        .await
        .expect("coordinator must exit promptly on cancellation")
        .expect("coordinator task must not panic")
        .expect("graceful cancellation must exit cleanly after an abdication cycle");
}

// ============================================================
// Cancelled handoffs converge on the durable state
// ============================================================
//
// Draining fences the partition against writes on the old owner. When a
// handoff is cancelled (the coordinator replaces the record — e.g. the
// new owner died mid-warm and a reaffirm resolves it), the pod re-derives
// its state from what etcd now says: if the record names it, it resumes
// serving (routers drain their stashes back to it); if nothing assigns it, it
// releases whatever half-acquired state it holds.

/// A handoff deleted mid-flight (after this pod drained as old owner)
/// must trigger `resume_partition` on the pod the assignment still names.
#[tokio::test]
async fn pod_resumes_partition_when_cancelled_handoff_leaves_it_assigned() {
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

    // Give the pod ownership of partition 0 through the real acquisition
    // path: warm via an initial-assignment handoff, then complete it
    // (which writes the assignment atomically) and clean up the record.
    put_handoff(&store, 0, None, "resume-pod-a", HandoffPhase::Warming).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;
    assert!(
        store.complete_handoff(0).await.expect("complete"),
        "complete_handoff must succeed"
    );
    store.delete_handoff(0).await.expect("cleanup");

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

    // The handoff is cancelled (new owner gone). The assignment still
    // names this pod, so it must resume the partition.
    store.delete_handoff(0).await.expect("delete handoff");
    wait_for_event(&pod.events, HandoffEvent::Resumed(0)).await;

    cancel.cancel();
}

/// A cancelled acquisition converges the other way: the pod warmed as new
/// owner, but the assignment never flipped to it (that happens only at
/// Complete), so on cancellation it must release the half-acquired
/// partition rather than serve a partition nothing routes to.
#[tokio::test]
async fn pod_releases_partition_when_cancelled_handoff_leaves_it_unassigned() {
    let store = test_store("handoff-cancel-release").await;
    let cancel = CancellationToken::new();

    let pod = start_pod(Arc::clone(&store), "release-pod-a", cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "release-pod-a"))
                .unwrap_or(false)
        }
    })
    .await;

    // Mid-acquisition: warmed as new owner, no assignment written yet.
    put_handoff(&store, 0, None, "release-pod-a", HandoffPhase::Warming).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;

    // Cancellation deletes the record; nothing assigns the partition to
    // this pod, so it must drop what it warmed.
    store.delete_handoff(0).await.expect("delete handoff");
    wait_for_event(&pod.events, HandoffEvent::Released(0)).await;
    assert!(
        !pod.events.lock().await.contains(&HandoffEvent::Resumed(0)),
        "an unassigned partition must not be resumed"
    );

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
// Pod state convergence: local state is derived from etcd
// ============================================================
//
// A crash-restart inside the lease TTL preserves a pod's registration and
// assignments but wipes its memory (cache, fences), and — because nothing
// in etcd changed — no event ever arrives to repair the divergence. The
// pod therefore re-derives its per-partition state from the durable state
// at startup and on every handoff event, instead of accumulating it from
// remembered events.

/// A pod that crash-restarts within its lease TTL must re-warm the
/// partitions etcd assigns it. Without the startup reconcile, the same-name
/// re-registration changes nothing in etcd, so no handoff is ever created
/// and the pod would serve errors for its own partitions forever.
#[tokio::test]
async fn restarted_pod_rewarms_assigned_partitions() {
    let store = test_store("restart-rewarm").await;
    let cancel = CancellationToken::new();

    store
        .put_assignments(&[
            PartitionAssignment {
                partition: 0,
                owner: "phoenix-pod".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            },
            PartitionAssignment {
                partition: 1,
                owner: "phoenix-pod".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            },
        ])
        .await
        .expect("write assignments");

    // First incarnation warms its assigned partitions at startup.
    let mut pod = start_pod(Arc::clone(&store), "phoenix-pod", cancel.clone());
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(1)).await;

    // Crash: abort the run loop — no graceful drain, no lease revoke, so
    // the registration and assignments survive untouched.
    pod.join_handle.take().expect("join handle").abort();

    // Second incarnation, same name, empty memory. It must converge back
    // to warm on both partitions from the durable state alone.
    let pod2 = start_pod(Arc::clone(&store), "phoenix-pod", cancel.clone());
    wait_for_event(&pod2.events, HandoffEvent::Warmed(0)).await;
    wait_for_event(&pod2.events, HandoffEvent::Warmed(1)).await;

    cancel.cancel();
}

/// The full comment-2 scenario: a pod crash-restarts while its outbound
/// handoff is Draining, participates in the drain from cold (fence + ack,
/// deliberately without warming), and when the handoff is cancelled it
/// converges back to Serving — warming the partition it never held in
/// this process lifetime.
#[tokio::test]
async fn restarted_old_owner_serves_again_after_handoff_cancelled() {
    let store = test_store("restart-cancel-serve").await;
    let cancel = CancellationToken::new();

    store
        .put_assignments(&[PartitionAssignment {
            partition: 0,
            owner: "victim-pod".to_string(),
            status: AssignmentStatus::Active,
            advertise_address: None,
        }])
        .await
        .expect("write assignment");
    put_handoff(
        &store,
        0,
        Some("victim-pod"),
        "other-pod",
        HandoffPhase::Draining,
    )
    .await;

    // The pod boots cold with the handoff already Draining: it must fence
    // and ack — but not warm, since the partition is on its way out.
    let pod = start_pod(Arc::clone(&store), "victim-pod", cancel.clone());
    wait_for_event(&pod.events, HandoffEvent::Drained(0)).await;
    assert!(
        !pod.events.lock().await.contains(&HandoffEvent::Warmed(0)),
        "a draining partition must not be warmed on the way out"
    );
    let acks = store.list_drained_acks(0).await.expect("list acks");
    assert!(
        acks.iter()
            .any(|a| a.pod_name == "victim-pod" && a.handoff_id == "test-handoff-0"),
        "drained ack must be written and correlated to the handoff"
    );

    // Cancellation: the assignment still names this pod, so it converges
    // to Serving — which from cold means warming.
    store.delete_handoff(0).await.expect("delete handoff");
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;

    cancel.cancel();
}

/// A pod restarting while its outbound handoff is already in Warming must
/// re-fence (its predecessor's fence died with it) without re-acking — the
/// coordinator consumed the DrainedAck to reach Warming, and a late re-ack
/// could outlive the handoff's cleanup and orphan into a future handoff.
#[tokio::test]
async fn restarted_old_owner_refences_when_handoff_in_warming() {
    let store = test_store("restart-refence").await;
    let cancel = CancellationToken::new();

    store
        .put_assignments(&[PartitionAssignment {
            partition: 0,
            owner: "frozen-pod".to_string(),
            status: AssignmentStatus::Active,
            advertise_address: None,
        }])
        .await
        .expect("write assignment");
    put_handoff(
        &store,
        0,
        Some("frozen-pod"),
        "other-pod",
        HandoffPhase::Warming,
    )
    .await;

    let pod = start_pod(Arc::clone(&store), "frozen-pod", cancel.clone());
    wait_for_event(&pod.events, HandoffEvent::Drained(0)).await;

    let acks = store.list_drained_acks(0).await.expect("list acks");
    assert!(
        acks.is_empty(),
        "no DrainedAck may be written once the phase has advanced past Draining"
    );

    cancel.cancel();
}

// ============================================================
// Cleanup deletes are guarded against recreation
// ============================================================

/// A cleanup delete acting on a stale snapshot must not destroy a
/// successor handoff recreated at the same key (cancellation followed by
/// an immediate rebalance). The guard must be etcd `mod_revision`, not
/// the per-key `version`: version resets to 1 on recreation, so both
/// incarnations of a once-written key look identical to a version guard.
#[tokio::test]
async fn guarded_handoff_delete_skips_recreated_handoff() {
    let store = test_store("guarded-delete").await;

    // First incarnation, snapshotted by a would-be deleter.
    put_handoff(&store, 0, Some("pod-a"), "pod-dead", HandoffPhase::Freezing).await;
    let (_, stale_revision) = store
        .get_handoff_with_mod_revision(0)
        .await
        .expect("read")
        .expect("handoff exists");

    // Concurrent cancel + recreate at the same key, with an ack belonging
    // to the successor.
    store.delete_handoff(0).await.expect("cancel");
    put_handoff(&store, 0, Some("pod-a"), "pod-live", HandoffPhase::Freezing).await;
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "router-0".to_string(),
            partition: 0,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: "test-handoff-0".to_string(),
        })
        .await
        .expect("successor ack");

    // The stale deleter must skip: the successor and its acks survive.
    let deleted = store
        .delete_handoff_and_acks_if_unchanged(0, stale_revision)
        .await
        .expect("guarded delete");
    assert!(!deleted, "stale snapshot must not delete the successor");
    let survivor = store
        .get_handoff(0)
        .await
        .expect("read")
        .expect("successor must survive");
    assert_eq!(survivor.new_owner, "pod-live");
    assert_eq!(
        store.list_freeze_acks(0).await.expect("acks").len(),
        1,
        "successor's acks must survive"
    );

    // A fresh read deletes record and acks atomically.
    let (_, fresh_revision) = store
        .get_handoff_with_mod_revision(0)
        .await
        .expect("read")
        .expect("handoff exists");
    assert!(store
        .delete_handoff_and_acks_if_unchanged(0, fresh_revision)
        .await
        .expect("guarded delete"));
    assert!(store.get_handoff(0).await.expect("read").is_none());
    assert!(store.list_freeze_acks(0).await.expect("acks").is_empty());
}

// ============================================================
// Acks correlate to their handoff
// ============================================================

/// An ack from the right participant but a previous handoff attempt must
/// not satisfy the quorum: acks race the coordinator's cleanup, so an
/// orphaned ack for the same partition can survive into the next handoff
/// and would otherwise skip a drain or warm that never happened.
#[tokio::test]
async fn ack_for_previous_handoff_does_not_satisfy_quorum() {
    let store = test_store("ack-correlation").await;
    let cancel = CancellationToken::new();

    // A live, registered router (registered directly so no watch loop
    // acks on its behalf).
    let lease_id = store.grant_lease(30).await.expect("lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "r-live".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            lease_id,
        )
        .await
        .expect("register router");

    // An ack from this same router, but echoing a previous handoff's id —
    // the orphan a cleanup race can leave behind.
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "r-live".to_string(),
            partition: 0,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: "a-previous-handoff".to_string(),
        })
        .await
        .expect("write stale ack");

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

    // Identity matches, id doesn't: the quorum must not be satisfied.
    tokio::time::sleep(Duration::from_secs(2)).await;
    let handoff = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert_eq!(
        handoff.phase,
        HandoffPhase::Freezing,
        "an ack from a previous handoff attempt must not satisfy this one's quorum"
    );

    // The correlated ack clears the quorum.
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "r-live".to_string(),
            partition: 0,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: "test-handoff-0".to_string(),
        })
        .await
        .expect("write correlated ack");

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

/// A freeze whose quorum is held open by a registered-but-silent router
/// must advance the moment that router's registration disappears —
/// event-driven via the router-departure watch, not rescued later by
/// the reconcile tick (parked here to prove the distinction). This is
/// the deploy path: a router deregisters at shutdown, or its lease
/// expires after a crash, while handoffs sit frozen on its ack.
#[tokio::test]
async fn router_departure_advances_a_waiting_freeze() {
    let store = test_store("router-departure").await;
    let cancel = CancellationToken::new();

    // Two registered routers: one will ack, one never will — its process
    // is gone and only its registration remains, on its own lease.
    let live_lease = store.grant_lease(30).await.expect("lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "r-live".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            live_lease,
        )
        .await
        .expect("register live router");
    let dead_lease = store.grant_lease(30).await.expect("lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "r-dead".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            dead_lease,
        )
        .await
        .expect("register dead router");

    let _coord = start_coordinator_reconcile_parked(
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
            router_name: "r-live".to_string(),
            partition: 0,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: "test-handoff-0".to_string(),
        })
        .await
        .expect("write ack");

    // The live ack alone must not satisfy the quorum while the silent
    // router is still registered.
    tokio::time::sleep(Duration::from_secs(2)).await;
    let handoff = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert_eq!(
        handoff.phase,
        HandoffPhase::Freezing,
        "a registered router that has not acked must hold the freeze"
    );

    // The silent router departs. Revoke stands in for both shutdown
    // deregistration and crash-side lease expiry — the same Delete event.
    store.revoke_lease(dead_lease).await.expect("revoke");

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

/// An ack written by a pre-`handoff_id` binary (the JSON has no
/// `handoff_id` field, so it deserializes to "") must not satisfy the
/// quorum of a handoff carrying a real id. This is the rolling-upgrade
/// skew case: mixed fleets must fail safe by stalling until the
/// participant re-acks with the correct id, never by advancing on a
/// legacy ack.
#[tokio::test]
async fn legacy_ack_without_handoff_id_does_not_satisfy_quorum() {
    let (store, prefix) = test_store_with_prefix("legacy-ack").await;
    let cancel = CancellationToken::new();

    let lease_id = store.grant_lease(30).await.expect("lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "r-legacy".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            lease_id,
        )
        .await
        .expect("register router");

    // Write the ack exactly as an old binary would: raw JSON with no
    // `handoff_id` field at all.
    let mut raw = etcd_client::Client::connect([common::ETCD_ENDPOINT], None)
        .await
        .expect("connect raw etcd client");
    raw.put(
        format!("{prefix}freeze_acks/0/r-legacy"),
        r#"{"router_name":"r-legacy","partition":0,"acked_at":0}"#,
        None,
    )
    .await
    .expect("write legacy ack");

    // The legacy JSON must deserialize (serde default fills ""), not error.
    let acks = store.list_freeze_acks(0).await.expect("list acks");
    assert_eq!(acks.len(), 1);
    assert_eq!(acks[0].handoff_id, "");

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

    // Router name matches, id ("") doesn't: quorum must not be satisfied.
    tokio::time::sleep(Duration::from_secs(2)).await;
    let handoff = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert_eq!(
        handoff.phase,
        HandoffPhase::Freezing,
        "a legacy ack without a handoff_id must not satisfy an id-bearing handoff's quorum"
    );

    // A correlated re-ack (what the router writes once upgraded) clears it.
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "r-legacy".to_string(),
            partition: 0,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: "test-handoff-0".to_string(),
        })
        .await
        .expect("write correlated ack");

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
// Cleanup owns only unprogressable handoffs
// ============================================================
//
// A handoff whose OLD owner is dead progresses on its own: Freezing waits
// on routers (not the old owner), and Draining treats an absent old owner
// as vacuously drained. Cancelling such handoffs would be a second,
// competing mechanism for the same state — racing the advance path and
// tearing down a healthy in-flight warm so the plan could recreate it
// from scratch. The planner's cancellation trigger is only the handoff that
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
                advertise_address: None,
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
                advertise_address: None,
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

/// A pod's startup reconcile takes two snapshots (assignments, then
/// handoffs) and anchors its handoff watch to the *lower* of the two
/// revisions. This pins the contract that anchoring at the lower revision
/// replays a write that lands between the two reads — anchoring at the
/// higher one (an easy `min`→`max` typo in `reconcile_all`) would let the
/// watch skip it.
#[tokio::test]
async fn watch_anchored_to_lower_snapshot_revision_replays_interleaved_write() {
    let store = test_store("min-rev-anchor").await;

    // First snapshot: assignments, at rev_a.
    let (_, rev_a) = store
        .list_assignments_with_revision()
        .await
        .expect("assignments snapshot");

    // A handoff lands between the two snapshot reads.
    put_handoff(&store, 3, None, "minrev-pod", HandoffPhase::Freezing).await;

    // Second snapshot: handoffs, at rev_h > rev_a. The interleaved write
    // is included here, so converging from this snapshot is fine — but a
    // watch anchored past rev_a must still redeliver it, because a future
    // reordering of the two reads would otherwise silently drop it.
    let (handoffs, rev_h) = store
        .list_handoffs_with_revision()
        .await
        .expect("handoffs snapshot");
    assert!(handoffs.iter().any(|h| h.partition == 3));
    assert!(
        rev_h > rev_a,
        "the interleaved write must bump the revision"
    );

    let mut stream = store
        .watch_handoffs_from(rev_a.min(rev_h) + 1)
        .await
        .expect("anchored watch");

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    loop {
        let resp = tokio::time::timeout_at(deadline, stream.message())
            .await
            .expect("watch anchored at min(rev_a, rev_h) must replay the interleaved write")
            .expect("watch stream")
            .expect("watch response");
        if let Some(handoff) = resp
            .events()
            .iter()
            .find_map(|e| parse_watch_value::<HandoffState>(e).ok())
        {
            assert_eq!(handoff.partition, 3);
            assert_eq!(handoff.new_owner, "minrev-pod");
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
            acked_at_ms: 0,
            handoff_id: "test-handoff-0".to_string(),
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
// registration, so no dead-new-owner cancellation fires and no new Put
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
            acked_at_ms: 0,
            handoff_id: "test-handoff-0".to_string(),
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
            acked_at_ms: 0,
            handoff_id: "test-handoff-0".to_string(),
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

    async fn drain_stash(
        &self,
        _partition: u32,
        _target: &str,
        _cancel: CancellationToken,
    ) -> Result<()> {
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
    assert!(store
        .create_assignments_and_handoffs(
            &[PartitionAssignment {
                partition: 0,
                owner: "pod-old".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            }],
            &[],
            &[],
        )
        .await
        .expect("write assignment"));
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
            reconcile_interval: Duration::from_secs(86_400),
            ..RoutingTableConfig::default()
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

// ============================================================
// Cancellation disposal: drain back only to a live owner
// ============================================================

/// Shared fixture for the cancellation-disposal tests: an assignment for
/// partition 0 owned by `pod-old`, an in-flight Freezing handoff toward
/// `pod-new`, and a running routing table with a recording stash handler.
/// Returns the recorded events and the shutdown token.
async fn start_router_with_frozen_handoff(
    store: &Arc<PersonhogStore>,
    router_name: &str,
) -> (Arc<Mutex<Vec<CutoverEvent>>>, CancellationToken) {
    assert!(store
        .create_assignments_and_handoffs(
            &[PartitionAssignment {
                partition: 0,
                owner: "pod-old".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            }],
            &[],
            &[],
        )
        .await
        .expect("write assignment"));
    put_handoff(store, 0, Some("pod-old"), "pod-new", HandoffPhase::Freezing).await;

    let router = RoutingTable::new(
        Arc::clone(store),
        RoutingTableConfig {
            router_name: router_name.to_string(),
            reconcile_interval: Duration::from_secs(86_400),
            ..RoutingTableConfig::default()
        },
    );
    let (handler, events) = MockCutoverHandler::new();
    let cancel = CancellationToken::new();
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(handler)).await });

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { !events.lock().await.is_empty() }
    })
    .await;

    (events, cancel)
}

/// A raw deletion of a non-terminal handoff is out-of-protocol under
/// cancellation-by-replacement, and the router treats it as inert: no
/// drain fires toward anyone. The stash stays parked until the record
/// that resolves it arrives — here the successor's Complete, which
/// drains it to the pod that actually won ownership.
#[tokio::test]
async fn a_raw_deletion_is_inert_and_the_successor_resolves_the_stash() {
    let store = test_store("cancel-dead-owner").await;

    // `pod-old` is never registered: it is dead.
    let (events, cancel) = start_router_with_frozen_handoff(&store, "cdo-router").await;

    store.delete_handoff(0).await.expect("cancel handoff");

    // The successor handoff completes toward a different pod; its drain
    // is the next stash event. Waiting for it (rather than a negative
    // wait) also proves no drain-back squeezed in before it: events are
    // recorded in order and asserted exactly below.
    put_handoff(
        &store,
        0,
        Some("pod-old"),
        "pod-new-2",
        HandoffPhase::Complete,
    )
    .await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events.lock().await.contains(&CutoverEvent::StashDrained {
                partition: 0,
                target: "pod-new-2".to_string(),
            })
        }
    })
    .await;

    let recorded = events.lock().await.clone();
    assert_eq!(
        recorded,
        vec![
            CutoverEvent::StashBegan {
                partition: 0,
                new_owner: "pod-new".to_string(),
            },
            CutoverEvent::StashDrained {
                partition: 0,
                target: "pod-new-2".to_string(),
            },
        ],
        "stash must not drain toward the dead owner"
    );

    cancel.cancel();
}

/// Records drain starts like `MockCutoverHandler`, then parks forever —
/// ignoring even its cancellation token. The worst-case drain.
struct BlockedDrainHandler {
    events: Arc<Mutex<Vec<CutoverEvent>>>,
}

#[async_trait]
impl StashHandler for BlockedDrainHandler {
    async fn begin_stash(&self, partition: u32, new_owner: &str) -> Result<()> {
        self.events.lock().await.push(CutoverEvent::StashBegan {
            partition,
            new_owner: new_owner.to_string(),
        });
        Ok(())
    }

    async fn drain_stash(
        &self,
        partition: u32,
        target: &str,
        _cancel: CancellationToken,
    ) -> Result<()> {
        self.events.lock().await.push(CutoverEvent::StashDrained {
            partition,
            target: target.to_string(),
        });
        pending::<Result<()>>().await
    }
}

/// A drain's duration is data-plane work — queue depth, arrival rate,
/// target health — so even a drain that never finishes must not stall
/// the watch loop: freeze acks are on the critical path of every handoff
/// in the cluster, and a router that stops acking wedges them all.
#[tokio::test]
async fn a_blocked_drain_does_not_stall_freeze_acks_for_other_partitions() {
    let store = test_store("blocked-drain").await;

    // Partition 0's owner is live and registered, so the cancellation
    // below drains back to it — and parks forever in this handler.
    let lease = store.grant_lease(60).await.expect("lease");
    store
        .register_pod(
            &RegisteredPod {
                pod_name: "pod-old".to_string(),
                generation: String::new(),
                status: PodStatus::Ready,
                registered_at: 0,
                last_heartbeat: 0,
                controller: None,
                advertise_address: None,
            },
            lease,
        )
        .await
        .expect("register pod-old");
    assert!(store
        .create_assignments_and_handoffs(
            &[PartitionAssignment {
                partition: 0,
                owner: "pod-old".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            }],
            &[],
            &[],
        )
        .await
        .expect("write assignment"));
    put_handoff(
        &store,
        0,
        Some("pod-old"),
        "pod-new",
        HandoffPhase::Freezing,
    )
    .await;

    let router = RoutingTable::new(
        Arc::clone(&store),
        RoutingTableConfig {
            router_name: "bd-router".to_string(),
            reconcile_interval: Duration::from_secs(86_400),
            ..RoutingTableConfig::default()
        },
    );
    let events = Arc::new(Mutex::new(Vec::new()));
    let handler = BlockedDrainHandler {
        events: Arc::clone(&events),
    };
    let cancel = CancellationToken::new();
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(handler)).await });

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { !events.lock().await.is_empty() }
    })
    .await;

    // Replace the handoff with a reaffirm toward the live owner and
    // wait until the resulting drain has started (and parked).
    put_handoff(&store, 0, None, "pod-old", HandoffPhase::Complete).await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events.lock().await.contains(&CutoverEvent::StashDrained {
                partition: 0,
                target: "pod-old".to_string(),
            })
        }
    })
    .await;

    // A Freezing handoff for another partition must still get this
    // router's freeze ack.
    put_handoff(&store, 1, None, "pod-new", HandoffPhase::Freezing).await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            store
                .list_freeze_acks(1)
                .await
                .expect("list acks")
                .iter()
                .any(|ack| ack.router_name == "bd-router")
        }
    })
    .await;

    cancel.cancel();
}

/// Passes partition 0 through and parks forever on any other partition —
/// pins the block inside the watch loop (partition 1 only ever arrives
/// through it, never through startup catch-up, once partition 0's ack
/// proves the initial snapshot has been taken).
struct PartitionOneParker;

#[async_trait]
impl StashHandler for PartitionOneParker {
    async fn begin_stash(&self, partition: u32, _new_owner: &str) -> Result<()> {
        if partition == 0 {
            return Ok(());
        }
        pending::<Result<()>>().await
    }

    async fn drain_stash(
        &self,
        _partition: u32,
        _target: &str,
        _cancel: CancellationToken,
    ) -> Result<()> {
        Ok(())
    }
}

/// A router whose watch loop stalls stays registered — its lease
/// keepalive is a separate, healthy task — and is counted in every
/// freeze quorum while never acking. The watchdog must notice the
/// missing progress stamps, fail the run, and deregister the router so
/// quorums stop counting it.
#[tokio::test]
async fn a_stalled_watch_loop_trips_the_watchdog_and_deregisters() {
    let store = test_store("stall-watchdog").await;

    let router = RoutingTable::new(
        Arc::clone(&store),
        RoutingTableConfig {
            router_name: "wd-router".to_string(),
            participant_stall_threshold: Some(Duration::from_secs(1)),
            reconcile_interval: Duration::from_secs(86_400),
            // Budget 1 pins the watchdog's fatal path: one tripped
            // attempt fails the whole run. The rebuild-in-place path is
            // covered by the supervisor tests.
            run_retry_budget: 1,
            ..RoutingTableConfig::default()
        },
    );
    let cancel = CancellationToken::new();
    let token = cancel.child_token();
    let run = tokio::spawn(async move { router.run(token, Arc::new(PartitionOneParker)).await });

    // Partition 0's ack proves the router is up and past its startup
    // catch-up; partition 1's handoff then arrives via the watch loop
    // and parks it.
    put_handoff(&store, 0, None, "pod-new", HandoffPhase::Freezing).await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            store
                .list_freeze_acks(0)
                .await
                .expect("list acks")
                .iter()
                .any(|ack| ack.router_name == "wd-router")
        }
    })
    .await;
    put_handoff(&store, 1, None, "pod-new", HandoffPhase::Freezing).await;

    let result = tokio::time::timeout(WAIT_TIMEOUT, run)
        .await
        .expect("watchdog should fail the run before the timeout")
        .expect("run task must not panic");
    assert!(
        result.is_err(),
        "a stalled watch loop must fail the run, not linger as a zombie participant"
    );

    // Deregistered on the way down: freeze quorums stop counting it.
    let routers = store.list_routers().await.expect("list routers");
    assert!(
        !routers.iter().any(|r| r.router_name == "wd-router"),
        "the failed router must deregister"
    );

    cancel.cancel();
}

/// The reaffirm shape: cancelling a handoff whose current owner is
/// alive replaces the record with a Complete toward that owner
/// (`old_owner: None` — naming the owner on both sides would derive
/// Released at the pod). The router resolves it through its ordinary
/// Complete handling: parked requests drain straight home.
#[tokio::test]
async fn a_reaffirm_resolves_the_stash_back_to_the_owner() {
    let store = test_store("cancel-live-owner").await;

    let lease = store.grant_lease(60).await.expect("lease");
    store
        .register_pod(
            &RegisteredPod {
                pod_name: "pod-old".to_string(),
                generation: String::new(),
                status: PodStatus::Ready,
                registered_at: 0,
                last_heartbeat: 0,
                controller: None,
                advertise_address: None,
            },
            lease,
        )
        .await
        .expect("register pod-old");

    let (events, cancel) = start_router_with_frozen_handoff(&store, "clo-router").await;

    // The coordinator's replacement, written directly: a reaffirm
    // Complete toward the live current owner.
    put_handoff(&store, 0, None, "pod-old", HandoffPhase::Complete).await;

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events.lock().await.contains(&CutoverEvent::StashDrained {
                partition: 0,
                target: "pod-old".to_string(),
            })
        }
    })
    .await;

    cancel.cancel();
}

/// Build a router with a fast reconcile pass, over an assignment for
/// partition 0 owned by `pod-old` and an in-flight Freezing handoff.
async fn start_reconciling_router(
    store: &Arc<PersonhogStore>,
    router_name: &str,
) -> (Arc<Mutex<Vec<CutoverEvent>>>, CancellationToken) {
    assert!(store
        .create_assignments_and_handoffs(
            &[PartitionAssignment {
                partition: 0,
                owner: "pod-old".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            }],
            &[],
            &[],
        )
        .await
        .expect("write assignment"));
    put_handoff(store, 0, Some("pod-old"), "pod-new", HandoffPhase::Freezing).await;

    let router = RoutingTable::new(
        Arc::clone(store),
        RoutingTableConfig {
            router_name: router_name.to_string(),
            reconcile_interval: Duration::from_millis(200),
            ..RoutingTableConfig::default()
        },
    );
    let (handler, events) = MockCutoverHandler::new();
    let cancel = CancellationToken::new();
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(handler)).await });

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { !events.lock().await.is_empty() }
    })
    .await;

    (events, cancel)
}

/// The reconcile pass derives stash disposal from durable state: after
/// an out-of-protocol raw deletion leaves a stash parked (the Delete
/// event itself is inert), the next pass observes a partition with an
/// assignment and no handoff and drains the stash to the assignment
/// owner. This is the healing no event-driven path can provide.
#[tokio::test]
async fn the_reconcile_pass_heals_an_out_of_protocol_deletion() {
    let store = test_store("reconcile-heals-deletion").await;
    let (events, cancel) = start_reconciling_router(&store, "rhd-router").await;

    store.delete_handoff(0).await.expect("raw delete");

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events.lock().await.contains(&CutoverEvent::StashDrained {
                partition: 0,
                target: "pod-old".to_string(),
            })
        }
    })
    .await;

    cancel.cancel();
}

/// The reconcile pass re-derives freeze acks from the snapshot, so an
/// ack lost out-of-protocol — or a Freezing event lost to a dead watch
/// stream — is repaired on the next pass instead of wedging the quorum
/// until the deadline.
#[tokio::test]
async fn the_reconcile_pass_reasserts_freeze_acks() {
    let (store, prefix) = test_store_with_prefix("reconcile-reasserts-acks").await;
    let (_events, cancel) = start_reconciling_router(&store, "rra-router").await;

    let ack_present = |store: Arc<PersonhogStore>| async move {
        store
            .list_freeze_acks(0)
            .await
            .expect("list acks")
            .iter()
            .any(|a| a.router_name == "rra-router")
    };
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        ack_present(Arc::clone(&store))
    })
    .await;

    let mut raw = etcd_client::Client::connect(["http://localhost:2379"], None)
        .await
        .expect("raw client");
    raw.delete(format!("{prefix}freeze_acks/0/rra-router"), None)
        .await
        .expect("delete ack");

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        ack_present(Arc::clone(&store))
    })
    .await;

    cancel.cancel();
}

/// A handoff handler whose `warm_partition` fails while the flag is
/// set — the injection point for pod attempt failures that do not
/// involve the lease.
struct FlakyHandoffHandler {
    events: Arc<Mutex<Vec<HandoffEvent>>>,
    fail_warm: Arc<AtomicBool>,
    warm_failures: Arc<AtomicUsize>,
}

#[async_trait]
impl personhog_coordination::pod::HandoffHandler for FlakyHandoffHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        if self.fail_warm.load(Ordering::SeqCst) {
            self.warm_failures.fetch_add(1, Ordering::SeqCst);
            return Err(personhog_coordination::error::Error::invalid_state(
                "injected warm failure".to_string(),
            ));
        }
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// A pod attempt failure that does not involve the lease must retry with
/// the registration preserved and the held partitions untouched: the
/// coordinator keeps seeing a live pod (no dead-owner reassignment can
/// start against a process that is still serving), no partition is
/// released, and — the cache-preservation proof — nothing is re-warmed
/// on recovery. This pins the deregistered-but-serving hole closed: an
/// earlier design revoked the lease on every failed attempt, handing
/// the coordinator a dead owner while the process kept accepting
/// writes.
#[tokio::test]
async fn a_pod_attempt_failure_preserves_registration_and_partitions() {
    let store = test_store("pod-attempt-preserves").await;
    let cancel = CancellationToken::new();

    let events: Arc<Mutex<Vec<HandoffEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let fail_warm = Arc::new(AtomicBool::new(false));
    let handler = FlakyHandoffHandler {
        events: Arc::clone(&events),
        fail_warm: Arc::clone(&fail_warm),
        warm_failures: Arc::new(AtomicUsize::new(0)),
    };
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "flaky-pod-0".to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
            reconcile_interval: Duration::from_secs(86_400),
            run_retry_backoff: Duration::from_millis(100),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    let registered = |store: Arc<PersonhogStore>| async move {
        store
            .list_pods()
            .await
            .map(|pods| pods.iter().any(|p| p.pod_name == "flaky-pod-0"))
            .unwrap_or(false)
    };
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        registered(Arc::clone(&store))
    })
    .await;

    // The pod acquires partition 0 healthily.
    put_handoff(&store, 0, None, "flaky-pod-0", HandoffPhase::Warming).await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events
                .lock()
                .await
                .iter()
                .any(|e| matches!(e, HandoffEvent::Warmed(0)))
        }
    })
    .await;

    // Break warming, then hand the pod a second partition: the event
    // kills the attempt, and re-attempts keep failing at convergence
    // while the flag holds.
    fail_warm.store(true, std::sync::atomic::Ordering::SeqCst);
    put_handoff(&store, 1, None, "flaky-pod-0", HandoffPhase::Warming).await;

    // Let several failed attempts elapse (100ms backoff base), then
    // assert the invariants of the failure window: still registered
    // (the session was never given up), partition 0 never released.
    tokio::time::sleep(Duration::from_millis(800)).await;
    assert!(
        registered(Arc::clone(&store)).await,
        "attempt failures must not cost the pod its registration"
    );
    assert!(
        !events
            .lock()
            .await
            .iter()
            .any(|e| matches!(e, HandoffEvent::Released(_))),
        "attempt failures must not release held partitions"
    );

    // Recovery: partition 1 warms; partition 0 was never re-warmed —
    // its cache and warm state survived every failed attempt.
    fail_warm.store(false, std::sync::atomic::Ordering::SeqCst);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events
                .lock()
                .await
                .iter()
                .any(|e| matches!(e, HandoffEvent::Warmed(1)))
        }
    })
    .await;
    let warmed_zero = events
        .lock()
        .await
        .iter()
        .filter(|e| matches!(e, HandoffEvent::Warmed(0)))
        .count();
    assert_eq!(
        warmed_zero, 1,
        "the held partition must never re-warm across failed attempts"
    );

    cancel.cancel();
}

/// A cutover handler whose `begin_stash` fails while the flag is set —
/// the injection point for reconcile-pass failures, since the pass calls
/// it for every non-terminal handoff before writing the freeze ack.
struct FlakyCutoverHandler {
    events: Arc<Mutex<Vec<CutoverEvent>>>,
    fail: Arc<AtomicBool>,
}

#[async_trait]
impl StashHandler for FlakyCutoverHandler {
    async fn begin_stash(&self, partition: u32, new_owner: &str) -> Result<()> {
        if self.fail.load(Ordering::SeqCst) {
            return Err(personhog_coordination::error::Error::invalid_state(
                "injected begin_stash failure".to_string(),
            ));
        }
        self.events.lock().await.push(CutoverEvent::StashBegan {
            partition,
            new_owner: new_owner.to_string(),
        });
        Ok(())
    }

    async fn drain_stash(
        &self,
        partition: u32,
        target: &str,
        _cancel: CancellationToken,
    ) -> Result<()> {
        self.events.lock().await.push(CutoverEvent::StashDrained {
            partition,
            target: target.to_string(),
        });
        Ok(())
    }
}

/// Start a router over the standard fixture (assignment for partition 0,
/// Freezing handoff) with a failure-injectable handler and the given
/// reconcile failure budget.
async fn start_flaky_router(
    store: &Arc<PersonhogStore>,
    router_name: &str,
    budget: u32,
) -> (Arc<AtomicBool>, CancellationToken) {
    assert!(store
        .create_assignments_and_handoffs(
            &[PartitionAssignment {
                partition: 0,
                owner: "pod-old".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            }],
            &[],
            &[],
        )
        .await
        .expect("write assignment"));
    put_handoff(store, 0, Some("pod-old"), "pod-new", HandoffPhase::Freezing).await;

    let router = RoutingTable::new(
        Arc::clone(store),
        RoutingTableConfig {
            router_name: router_name.to_string(),
            reconcile_interval: Duration::from_millis(200),
            reconcile_failure_budget: budget,
            run_retry_backoff: Duration::from_millis(100),
            ..RoutingTableConfig::default()
        },
    );
    let fail = Arc::new(AtomicBool::new(false));
    let handler = FlakyCutoverHandler {
        events: Arc::new(Mutex::new(Vec::new())),
        fail: Arc::clone(&fail),
    };
    let cancel = CancellationToken::new();
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(handler)).await });
    (fail, cancel)
}

/// Reconcile-pass failures within the budget must not kill the run: the
/// router stays registered while passes fail, and the first successful
/// pass afterward heals what went unrepaired in the meantime (here, a
/// freeze ack deleted out-of-protocol). Without tolerance, a brief etcd
/// blip observed by the 5-second tick would restart every router in the
/// fleet simultaneously.
#[tokio::test]
async fn reconcile_failures_within_budget_are_tolerated_and_heal() {
    let (store, prefix) = test_store_with_prefix("reconcile-tolerates-failures").await;
    let (fail, cancel) = start_flaky_router(&store, "rtf-router", 12).await;

    let ack_present = |store: Arc<PersonhogStore>| async move {
        store
            .list_freeze_acks(0)
            .await
            .expect("list acks")
            .iter()
            .any(|a| a.router_name == "rtf-router")
    };
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        ack_present(Arc::clone(&store))
    })
    .await;

    // Break the handler and delete the ack out-of-protocol. Reconcile is
    // the only healer (no new events arrive), and its passes now fail
    // before reaching the ack write, so the ack must stay absent while
    // the run survives the failures.
    fail.store(true, Ordering::SeqCst);
    let mut raw = etcd_client::Client::connect(["http://localhost:2379"], None)
        .await
        .expect("raw client");
    raw.delete(format!("{prefix}freeze_acks/0/rtf-router"), None)
        .await
        .expect("delete ack");

    // Observe at least four failed ticks' worth of time.
    tokio::time::sleep(Duration::from_millis(900)).await;
    assert!(
        !ack_present(Arc::clone(&store)).await,
        "failing passes must not have healed the ack"
    );
    let registered = store
        .list_routers()
        .await
        .expect("list routers")
        .iter()
        .any(|r| r.router_name == "rtf-router");
    assert!(
        registered,
        "the run must survive reconcile failures within the budget"
    );

    // Recovery: the next successful pass re-asserts the ack.
    fail.store(false, Ordering::SeqCst);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        ack_present(Arc::clone(&store))
    })
    .await;

    cancel.cancel();
}

/// Past the consecutive-failure budget the run must fail — the escape
/// hatch for the partial mode where snapshot reads fail while the lease
/// stays healthy, which unbounded tolerance would hide forever. Failing
/// the run deregisters the router so it restarts as a healthy
/// participant.
#[tokio::test]
async fn reconcile_failures_past_the_budget_fail_the_run() {
    let store = test_store("reconcile-budget-exhaustion").await;
    let (fail, cancel) = start_flaky_router(&store, "rbe-router", 3).await;

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            store
                .list_routers()
                .await
                .expect("list routers")
                .iter()
                .any(|r| r.router_name == "rbe-router")
        }
    })
    .await;

    fail.store(true, Ordering::SeqCst);

    // Three failed passes exhaust the budget; the run's teardown
    // deregisters the router.
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            !store
                .list_routers()
                .await
                .expect("list routers")
                .iter()
                .any(|r| r.router_name == "rbe-router")
        }
    })
    .await;

    cancel.cancel();
}

/// A failed coordination attempt must rebuild in place, not kill the
/// run: while the handler (standing in for etcd trouble) fails, attempts
/// tear down and back off; once it recovers, the next attempt
/// re-registers and catches up on everything missed in the gap — here, a
/// handoff created while coordination was down gets its freeze ack.
#[tokio::test]
async fn a_failed_coordination_attempt_rebuilds_in_place() {
    let store = test_store("run-rebuilds-in-place").await;
    let (fail, cancel) = start_flaky_router(&store, "rip-router", 12).await;

    let ack_present = |store: Arc<PersonhogStore>, partition: u32| async move {
        store
            .list_freeze_acks(partition)
            .await
            .expect("list acks")
            .iter()
            .any(|a| a.router_name == "rip-router")
    };
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        ack_present(Arc::clone(&store), 0)
    })
    .await;

    // Break the handler, then deliver an event: the event arm fails the
    // attempt, and re-bootstraps keep failing while the handler is down.
    // The teardown of the failed attempt deregisters the router.
    fail.store(true, std::sync::atomic::Ordering::SeqCst);
    put_handoff(&store, 1, None, "keeper-pod", HandoffPhase::Freezing).await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            !store
                .list_routers()
                .await
                .expect("list routers")
                .iter()
                .any(|r| r.router_name == "rip-router")
        }
    })
    .await;

    // Recovery: the next attempt bootstraps, re-registers, and the
    // fresh load acks the handoff that arrived during the outage.
    fail.store(false, std::sync::atomic::Ordering::SeqCst);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        ack_present(Arc::clone(&store), 1)
    })
    .await;

    cancel.cancel();
}

/// A cutover handler whose stash has fully settled: `stash_pending`
/// reports no entry, the way the router does once a drain has evicted
/// the partition from its stash table.
struct SettledCutoverHandler {
    events: Arc<Mutex<Vec<CutoverEvent>>>,
}

#[async_trait]
impl StashHandler for SettledCutoverHandler {
    async fn begin_stash(&self, partition: u32, new_owner: &str) -> Result<()> {
        self.events.lock().await.push(CutoverEvent::StashBegan {
            partition,
            new_owner: new_owner.to_string(),
        });
        Ok(())
    }

    async fn drain_stash(
        &self,
        partition: u32,
        target: &str,
        _cancel: CancellationToken,
    ) -> Result<()> {
        self.events.lock().await.push(CutoverEvent::StashDrained {
            partition,
            target: target.to_string(),
        });
        Ok(())
    }

    fn stash_pending(&self, _partition: u32) -> bool {
        false
    }
}

/// A settled partition must not have drains respawned by every reconcile
/// tick: its finished lane can never absorb (a finished drain may have
/// yielded with backlog), so without the `stash_pending` gate the pass
/// would spawn a fresh no-op drain for every quiet assigned partition,
/// every tick. The Freezing handoff on partition 1 acts as the pass
/// counter — `begin_stash` is re-asserted unconditionally each pass — so
/// the assertion is provably non-vacuous across multiple passes.
#[tokio::test]
async fn the_reconcile_pass_skips_drains_for_settled_partitions() {
    let store = test_store("reconcile-skips-settled").await;
    assert!(store
        .create_assignments_and_handoffs(
            &[PartitionAssignment {
                partition: 0,
                owner: "pod-old".to_string(),
                status: AssignmentStatus::Active,
                advertise_address: None,
            }],
            &[],
            &[],
        )
        .await
        .expect("write assignment"));
    put_handoff(&store, 1, None, "keeper-pod", HandoffPhase::Freezing).await;

    let router = RoutingTable::new(
        Arc::clone(&store),
        RoutingTableConfig {
            router_name: "rss-router".to_string(),
            reconcile_interval: Duration::from_millis(200),
            ..RoutingTableConfig::default()
        },
    );
    let events = Arc::new(Mutex::new(Vec::new()));
    let handler = SettledCutoverHandler {
        events: Arc::clone(&events),
    };
    let cancel = CancellationToken::new();
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(handler)).await });

    // Wait until partition 1's begin_stash has been asserted at least
    // three times — proof that multiple reconcile passes have evaluated
    // partition 0's bare assignment.
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            events
                .lock()
                .await
                .iter()
                .filter(|e| matches!(e, CutoverEvent::StashBegan { partition: 1, .. }))
                .count()
                >= 3
        }
    })
    .await;

    let drained = events
        .lock()
        .await
        .iter()
        .filter(|e| matches!(e, CutoverEvent::StashDrained { partition: 0, .. }))
        .count();
    assert_eq!(
        drained, 0,
        "a settled partition must not have drains respawned by reconcile ticks"
    );

    cancel.cancel();
}

// ============================================================
// Convergence lanes: partitions converge concurrently,
// single-flight per partition
// ============================================================
//
// The pod's watch loop runs convergence single-flight per partition but
// concurrently across partitions. A deploy moving several partitions
// onto one pod must warm them in parallel — serialized warming is what
// made stash waits scale with the number of simultaneous inbound
// handoffs — while two convergences for the same partition must never
// interleave (concurrent warms for one partition could install a stale
// cache over a fresh one).

/// Variant of `put_handoff` with an explicit handoff id, for forcing a
/// re-warm: a warm installed for one handoff id does not satisfy a later
/// handoff with a different id.
async fn put_handoff_with_id(
    store: &PersonhogStore,
    partition: u32,
    new_owner: &str,
    phase: HandoffPhase,
    handoff_id: &str,
) {
    let handoff = HandoffState {
        partition,
        old_owner: None,
        new_owner: new_owner.to_string(),
        phase,
        started_at: 0,
        handoff_id: handoff_id.to_string(),
        freeze_quorum: None,
        created_at_ms: 0,
        phase_entered_at_ms: 0,
        new_owner_address: None,
    };
    store.put_handoff(&handoff).await.expect("write handoff");
}

/// Wait until the pod has a warmed ack for the partition in etcd.
async fn wait_for_warmed_ack(store: &Arc<PersonhogStore>, partition: u32, pod: &str) {
    let check_store = Arc::clone(store);
    let pod = pod.to_string();
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, move || {
        let store = Arc::clone(&check_store);
        let pod = pod.clone();
        async move {
            store
                .list_warmed_acks(partition)
                .await
                .map(|acks| acks.iter().any(|a| a.pod_name == pod))
                .unwrap_or(false)
        }
    })
    .await;
}

/// With one partition's warm parked, another partition's handoff must
/// still warm and ack. Serialized convergence would queue the second
/// warm behind the parked one and its ack would never arrive.
#[tokio::test]
async fn concurrent_inbound_handoffs_warm_in_parallel() {
    let store = test_store("pod-parallel-warm").await;
    let cancel = CancellationToken::new();

    let pod = start_pod_gated(Arc::clone(&store), "parallel-warm-pod", 4, cancel.clone());

    put_handoff(&store, 0, None, "parallel-warm-pod", HandoffPhase::Warming).await;
    put_handoff(&store, 1, None, "parallel-warm-pod", HandoffPhase::Warming).await;

    // Partition 0 stays parked; partition 1 must complete regardless.
    pod.gates.open(1);
    wait_for_warmed_ack(&store, 1, "parallel-warm-pod").await;

    // The parked warm really is still parked — nothing acked for it.
    let acks = store.list_warmed_acks(0).await.expect("list acks");
    assert!(
        acks.is_empty(),
        "partition 0's warm is parked; its ack must not exist yet"
    );

    pod.gates.open(0);
    wait_for_warmed_ack(&store, 0, "parallel-warm-pod").await;

    cancel.cancel();
}

/// Two convergences for the same partition must never run concurrently,
/// even when a new handoff arrives while the partition's warm is parked.
/// The second handoff (a different id, so it demands its own warm) must
/// wait for the first convergence to finish, then re-warm.
#[tokio::test]
async fn convergences_for_one_partition_never_interleave() {
    let store = test_store("pod-single-flight").await;
    let cancel = CancellationToken::new();

    let pod = start_pod_gated(Arc::clone(&store), "single-flight-pod", 4, cancel.clone());

    put_handoff_with_id(
        &store,
        0,
        "single-flight-pod",
        HandoffPhase::Warming,
        "era-a",
    )
    .await;

    // Wait until the first warm is parked inside the handler.
    let in_flight = Arc::clone(&pod.warms_in_flight);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, move || {
        let in_flight = Arc::clone(&in_flight);
        async move { in_flight.lock().unwrap().get(&0).copied() == Some(1) }
    })
    .await;

    // A new era for the same partition while the warm is parked. The
    // convergence for it must coalesce behind the in-flight one, not
    // start a second concurrent warm.
    put_handoff_with_id(
        &store,
        0,
        "single-flight-pod",
        HandoffPhase::Warming,
        "era-b",
    )
    .await;

    pod.gates.open(0);

    // The era-b convergence releases the era-a warm and re-warms; two
    // Warmed events mark both warms having completed.
    let events = Arc::clone(&pod.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, move || {
        let events = Arc::clone(&events);
        async move {
            events
                .lock()
                .await
                .iter()
                .filter(|e| **e == HandoffEvent::Warmed(0))
                .count()
                == 2
        }
    })
    .await;

    assert_eq!(
        pod.max_concurrent_same_partition.load(Ordering::SeqCst),
        1,
        "convergences for one partition must never overlap"
    );

    cancel.cancel();
}

/// Concurrent warms are bounded by `warm_concurrency`: with the bound at
/// 2 and four inbound handoffs parked, exactly two warms enter the
/// handler; the rest queue on the semaphore until a slot frees.
#[tokio::test]
async fn concurrent_warms_are_bounded_by_warm_concurrency() {
    let store = test_store("pod-warm-bound").await;
    let cancel = CancellationToken::new();

    let pod = start_pod_gated(Arc::clone(&store), "warm-bound-pod", 2, cancel.clone());

    for partition in 0..4 {
        put_handoff(
            &store,
            partition,
            None,
            "warm-bound-pod",
            HandoffPhase::Warming,
        )
        .await;
    }

    // Both slots fill and park; the other two handoffs wait on the bound.
    let in_flight = Arc::clone(&pod.warms_in_flight);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, move || {
        let in_flight = Arc::clone(&in_flight);
        async move { in_flight.lock().unwrap().values().sum::<usize>() == 2 }
    })
    .await;

    for partition in 0..4 {
        pod.gates.open(partition);
    }
    for partition in 0..4 {
        wait_for_warmed_ack(&store, partition, "warm-bound-pod").await;
    }

    assert_eq!(
        pod.max_concurrent_warms.load(Ordering::SeqCst),
        2,
        "warms in the handler at once must equal the configured bound"
    );

    cancel.cancel();
}

// ============================================================
// Lease loss is observed promptly at every live-lease await
// ============================================================
//
// The session's keepalive task fails fast when the lease dies, but a
// signal only fences if the supervisor is listening. Every await the
// session makes while holding a lease must race the heartbeat handle:
// an unraced await defers the self-fence for its full duration, and the
// coordinator — which starts reassigning at TTL expiry — does not wait.
// These pin the two awaits that were unraced: the backoff nap between
// failed attempts, and the graceful drain.

/// A lease revoked while the supervisor naps between failed attempts
/// must self-fence when the keepalive notices — not when the nap ends.
/// The nap here is far longer than the assertion window, so this fails
/// if detection waits out the backoff.
#[tokio::test]
async fn lease_loss_during_attempt_backoff_self_fences_promptly() {
    let (store, prefix) = test_store_with_prefix("pod-backoff-fence").await;
    let cancel = CancellationToken::new();

    let events: Arc<Mutex<Vec<HandoffEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let fail_warm = Arc::new(AtomicBool::new(false));
    let handler = FlakyHandoffHandler {
        events: Arc::clone(&events),
        fail_warm: Arc::clone(&fail_warm),
        warm_failures: Arc::new(AtomicUsize::new(0)),
    };
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "backoff-fence-pod".to_string(),
            lease_ttl: 5,
            heartbeat_interval: Duration::from_secs(1),
            reconcile_interval: Duration::from_secs(86_400),
            // One failed attempt naps 8s — far past the 4s assertion
            // window below.
            run_retry_backoff: Duration::from_secs(8),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    // Acquire partition 0 healthily so the self-fence has something to
    // release.
    put_handoff(&store, 0, None, "backoff-fence-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    // A failing warm for partition 1 kills the attempt; the supervisor
    // enters its nap. The sleep positions the revocation inside the 8s
    // nap — if it ever lands before the nap instead, the attempt-select
    // race detects it and the test still passes, just via the path that
    // was already covered.
    fail_warm.store(true, Ordering::SeqCst);
    put_handoff(&store, 1, None, "backoff-fence-pod", HandoffPhase::Warming).await;
    tokio::time::sleep(Duration::from_millis(500)).await;

    revoke_lease_of_key(&format!("{prefix}pods/backoff-fence-pod")).await;

    // Well inside the nap: the self-fence must already have run.
    wait_for_condition(Duration::from_secs(4), POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { events.lock().await.contains(&HandoffEvent::Released(0)) }
    })
    .await;

    cancel.cancel();
}

/// A lease revoked during the graceful drain must switch to the local
/// self-fence immediately: the pod serves its partitions until their
/// handoffs complete, and with the lease gone the coordinator is
/// already reassigning them via the dead-owner path. Draining leaseless
/// until the drain timeout is the same zombie window the attempt-path
/// fence closes.
#[tokio::test]
async fn lease_loss_during_graceful_drain_self_fences_promptly() {
    let (store, prefix) = test_store_with_prefix("pod-drain-fence").await;
    let cancel = CancellationToken::new();

    let (handler, events) = MockHandoffHandler::new();
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "drain-fence-pod".to_string(),
            lease_ttl: 5,
            heartbeat_interval: Duration::from_secs(1),
            reconcile_interval: Duration::from_secs(86_400),
            // No coordinator completes the handoffs, so an undetected
            // lease loss would leave the drain waiting out this full
            // timeout.
            drain_timeout: Duration::from_secs(30),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );
    let token = cancel.child_token();
    let join = tokio::spawn(async move { pod.run(token).await });

    put_handoff(&store, 0, None, "drain-fence-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    // Graceful shutdown: the pod flips to Draining and waits for its
    // partition's outbound handoff, which never comes.
    cancel.cancel();
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, move || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| {
                    pods.iter()
                        .any(|p| p.pod_name == "drain-fence-pod" && p.status == PodStatus::Draining)
                })
                .unwrap_or(false)
        }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}pods/drain-fence-pod")).await;

    // Well inside the 30s drain timeout: the self-fence must have
    // released the partition and the run must have exited.
    wait_for_condition(Duration::from_secs(4), POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { events.lock().await.contains(&HandoffEvent::Released(0)) }
    })
    .await;
    tokio::time::timeout(Duration::from_secs(5), join)
        .await
        .expect("run exits promptly after the drain-time self-fence")
        .expect("run task")
        .expect("run returns Ok on graceful shutdown");
}

// ============================================================
// Keepalive: connection blips are not lease loss
// ============================================================
//
// The lease lives in etcd's replicated keyspace and stays valid until
// its TTL passes without renewal — a broken keepalive stream is a fact
// about one connection, not about the lease. The keepalive therefore
// rebuilds and retries through connection trouble while the last
// confirmed renewal is recent, and only declares loss on etcd's
// authoritative TTL<=0 answer or when the renewal margin (two thirds of
// the TTL, reserving the final third for the fence) runs out. These run
// a pod through a fault-injecting TCP proxy: a severed connection with
// runway left must not fence; a blackholed one must fence at the
// margin, not immediately and not never.

/// A routine single-member blip: the pod's etcd connection breaks and
/// immediately becomes reconnectable. The pod must keep its lease, its
/// registration, and its partitions — no self-fence, no re-warm.
#[tokio::test]
async fn a_connection_blip_does_not_fence_the_pod() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-keepalive-blip-{}/", uuid::Uuid::new_v4());
    let pod_store = store_at(&proxy.endpoint, &prefix).await;
    let direct_store = store_at(ETCD_ENDPOINT, &prefix).await;

    let cancel = CancellationToken::new();
    let (handler, events) = MockHandoffHandler::new();
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&pod_store),
        personhog_coordination::pod::PodConfig {
            pod_name: "blip-pod".to_string(),
            lease_ttl: 9,
            heartbeat_interval: Duration::from_secs(1),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    put_handoff(&direct_store, 0, None, "blip-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    proxy.sever();

    // Old behavior fences within a heartbeat tick of the blip. With the
    // renewal margin, the keepalive rebuilds its stream instead.
    tokio::time::sleep(Duration::from_secs(2)).await;
    assert!(
        !events.lock().await.contains(&HandoffEvent::Released(0)),
        "a reconnectable blip must not self-fence"
    );

    // Well past the original TTL from the last pre-blip renewal: the
    // registration only survives if renewals resumed through the
    // rebuilt stream.
    tokio::time::sleep(Duration::from_secs(8)).await;
    assert!(
        !events.lock().await.contains(&HandoffEvent::Released(0)),
        "the pod must hold its partition through the blip"
    );
    let pods = direct_store.list_pods().await.expect("list pods");
    assert!(
        pods.iter().any(|p| p.pod_name == "blip-pod"),
        "the lease must have been renewed through the rebuilt stream"
    );

    cancel.cancel();
}

/// A sustained etcd outage: the connection breaks and stays broken. The
/// pod must keep retrying while the lease still has runway — fencing
/// early buys no safety, the coordinator cannot have reassigned anything
/// — and must fence when the renewal margin runs out, leaving the final
/// third of the TTL for the fence to complete before expiry.
#[tokio::test]
async fn a_sustained_outage_fences_at_the_renewal_margin() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-keepalive-margin-{}/", uuid::Uuid::new_v4());
    let pod_store = store_at(&proxy.endpoint, &prefix).await;
    let direct_store = store_at(ETCD_ENDPOINT, &prefix).await;

    let cancel = CancellationToken::new();
    let (handler, events) = MockHandoffHandler::new();
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&pod_store),
        personhog_coordination::pod::PodConfig {
            pod_name: "margin-pod".to_string(),
            lease_ttl: 9,
            heartbeat_interval: Duration::from_secs(1),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    put_handoff(&direct_store, 0, None, "margin-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    proxy.set_blackholed(true);
    proxy.sever();

    // Inside the margin (two thirds of the 6s TTL): still retrying, not
    // fenced — the lease is still valid and the coordinator cannot have
    // moved anything.
    tokio::time::sleep(Duration::from_secs(2)).await;
    assert!(
        !events.lock().await.contains(&HandoffEvent::Released(0)),
        "fencing inside the margin trades availability for nothing"
    );

    // Margin exhausted: the self-fence must run, well before the pod
    // could be confused with one that never notices.
    wait_for_condition(Duration::from_secs(8), POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move { events.lock().await.contains(&HandoffEvent::Released(0)) }
    })
    .await;

    cancel.cancel();
}

/// The run budget bounds crash loops, not lifetime failures: an attempt
/// that did real work before failing resets the consecutive count. The
/// reset is keyed on measured progress, not elapsed time — a time
/// threshold silently exempts every failure detector slower than it
/// (the reconcile budget and the stall watchdog both take a minute),
/// letting wedged components rebuild in place forever. Here a pod
/// alternates real work and one fast failure more times than its
/// budget; each failure follows progress, so the run must stay alive
/// throughout.
#[tokio::test]
async fn progress_between_failures_keeps_the_run_alive() {
    let store = test_store("pod-progress-reset").await;
    let cancel = CancellationToken::new();

    let events: Arc<Mutex<Vec<HandoffEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let fail_warm = Arc::new(AtomicBool::new(false));
    let warm_failures = Arc::new(AtomicUsize::new(0));
    let handler = FlakyHandoffHandler {
        events: Arc::clone(&events),
        fail_warm: Arc::clone(&fail_warm),
        warm_failures: Arc::clone(&warm_failures),
    };
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "progress-pod".to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
            reconcile_interval: Duration::from_secs(86_400),
            run_retry_budget: 3,
            // Long enough that each cycle's injected failure is observed
            // and cleared before the rebuild retries — exactly one
            // no-progress failure per cycle.
            run_retry_backoff: Duration::from_secs(2),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    // Five work-then-fail cycles against a budget of three: only the
    // progress reset keeps the run alive past the third.
    for i in 0..5u32 {
        fail_warm.store(true, Ordering::SeqCst);
        put_handoff(&store, i, None, "progress-pod", HandoffPhase::Warming).await;
        let observed = Arc::clone(&warm_failures);
        let target = (i + 1) as usize;
        wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, move || {
            let observed = Arc::clone(&observed);
            async move { observed.load(Ordering::SeqCst) >= target }
        })
        .await;
        fail_warm.store(false, Ordering::SeqCst);
        // The rebuilt attempt re-converges the same handoff and warms it
        // — the progress that must reset the budget.
        wait_for_event(&events, HandoffEvent::Warmed(i)).await;
    }

    cancel.cancel();
}

/// Exhausting the run budget must fence before the registration
/// disappears, and no-op convergences must not reset the budget on the
/// way there. The pod holds partition 0 settled while every attempt
/// dies on a poisoned partition-1 warm with no applied work in between:
/// the budget must actually exhaust (settled partition 0's successful
/// no-op re-convergence on every attempt is a read, not progress), and
/// the exit must release partition 0 before the teardown revokes the
/// lease — revocation deregisters instantly, and the dead-owner path it
/// triggers has no fence of its own.
#[tokio::test]
async fn budget_exhaustion_fences_before_deregistering() {
    let store = test_store("pod-fatal-fence").await;
    let cancel = CancellationToken::new();

    let events: Arc<Mutex<Vec<HandoffEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let fail_warm = Arc::new(AtomicBool::new(false));
    let handler = FlakyHandoffHandler {
        events: Arc::clone(&events),
        fail_warm: Arc::clone(&fail_warm),
        warm_failures: Arc::new(AtomicUsize::new(0)),
    };
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "fatal-fence-pod".to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
            reconcile_interval: Duration::from_secs(86_400),
            run_retry_budget: 3,
            run_retry_backoff: Duration::from_millis(50),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );
    let token = cancel.child_token();
    let join = tokio::spawn(async move { pod.run(token).await });

    put_handoff(&store, 0, None, "fatal-fence-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    fail_warm.store(true, Ordering::SeqCst);
    put_handoff(&store, 1, None, "fatal-fence-pod", HandoffPhase::Warming).await;

    let result = tokio::time::timeout(Duration::from_secs(15), join)
        .await
        .expect("the budget must exhaust — no-op convergences must not keep resetting it")
        .expect("run task");
    assert!(result.is_err(), "budget exhaustion must surface the error");
    assert!(
        events.lock().await.contains(&HandoffEvent::Released(0)),
        "the held partition must be fenced and released before the lease is revoked"
    );
    let pods = store.list_pods().await.expect("list pods");
    assert!(
        !pods.iter().any(|p| p.pod_name == "fatal-fence-pod"),
        "the teardown must deregister on the way out"
    );
}
