//! Regression tests for the handoff-protocol hardening pass: self-fencing
//! on lease loss, post-drain write fencing, identity-based freeze quorum,
//! pod state convergence (startup reconcile + event-driven re-derivation),
//! the coordinator's reconcile tick, revision-anchored watches,
//! ack-to-handoff correlation, and cleanup scoped to dead new owners.
//!
//! All tests run against a real etcd at localhost:2379 with per-test key
//! prefixes, matching the conventions in `integration.rs`.

use etcd_client::EventType;
use personhog_coordination::authority::AuthorityClock;
mod common;

use std::collections::{HashMap, HashSet};
use std::future::pending;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{Mutex, Notify, RwLock};
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use async_trait::async_trait;
use common::{
    revoke_lease_of_key, start_coordinator, start_coordinator_named,
    start_coordinator_reconcile_parked, start_pod, start_pod_gated, start_pod_with_failing_release,
    start_pod_with_flaky_release, start_pod_with_flaky_resume, start_pod_with_hanging_drain,
    start_pod_with_lease_ttl, start_pod_with_stuck_drain, start_router_with_lease_ttl, store_at,
    test_store, test_store_with_prefix, wait_for_condition, wait_for_condition_named, CutoverEvent,
    FlakyProxy, HandoffEvent, MockCutoverHandler, MockHandoffHandler, ETCD_ENDPOINT, POLL_INTERVAL,
    WAIT_TIMEOUT,
};
use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::error::Result;
use personhog_coordination::protocol::freeze_quorum_met;
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
        freeze_quorum_ref: None,
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
    // drain before it releases — draining leaves nothing in flight, so
    // the release that follows unfences a partition with no admitted
    // write remaining and drops a cache no handler is still using — so
    // `Drained` must precede `Released` in the fence sequence.
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "the lease-loss self-fence to release the held partition",
        || {
            let events = Arc::clone(&events);
            async move {
                events
                    .lock()
                    .await
                    .iter()
                    .any(|e| matches!(e, HandoffEvent::Released(0)))
            }
        },
    )
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
    let warming = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert!(
        store
            .complete_handoff(0, &warming.handoff_id, HandoffPhase::Warming)
            .await
            .expect("complete"),
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
            128
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
            128
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
            128
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
            128
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
        Arc::new(AuthorityClock::unclaimed()),
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
            128
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
            128
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
        freeze_quorum_ref: None,
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
        Arc::new(AuthorityClock::unclaimed()),
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
        Arc::new(AuthorityClock::unclaimed()),
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
        Arc::new(AuthorityClock::unclaimed()),
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
        Arc::new(AuthorityClock::unclaimed()),
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
        Arc::new(AuthorityClock::unclaimed()),
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
        Arc::new(AuthorityClock::unclaimed()),
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

/// A resume that fails must leave the partition still marked fenced, so
/// a later convergence retries it. Clearing the local fence before the
/// handler succeeds strands the data plane fenced with no branch left to
/// re-enter: writes rejected forever while every convergence reports
/// success and no budget escalates.
#[tokio::test]
async fn pod_retries_resume_after_a_failed_attempt() {
    let store = test_store("handoff-cancel-resume-retry").await;
    let cancel = CancellationToken::new();

    let pod = start_pod_with_flaky_resume(Arc::clone(&store), "resume-flaky-a", 1, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "resume-flaky-a"))
                .unwrap_or(false)
        }
    })
    .await;

    put_handoff(&store, 0, None, "resume-flaky-a", HandoffPhase::Warming).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;
    let warmed = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert!(store
        .complete_handoff(0, &warmed.handoff_id, HandoffPhase::Warming)
        .await
        .expect("complete"));
    store.delete_handoff(0).await.expect("cleanup");

    put_handoff(
        &store,
        0,
        Some("resume-flaky-a"),
        "resume-flaky-b",
        HandoffPhase::Draining,
    )
    .await;
    wait_for_event(&pod.events, HandoffEvent::Drained(0)).await;

    // Cancel the handoff. The first resume fails; the pod must come back
    // to it rather than treating the partition as resumed.
    store.delete_handoff(0).await.expect("delete handoff");
    wait_for_event(&pod.events, HandoffEvent::Resumed(0)).await;

    cancel.cancel();
}

/// The authority clock is what the data plane reads to decide whether it
/// may still answer as a partition's owner, so it has to lapse on the
/// strength of missing renewals alone — no coordination task has to run
/// for it to become invalid. This severs etcd and watches the claim
/// expire while the process is otherwise perfectly healthy.
#[tokio::test]
async fn authority_lapses_when_renewals_stop() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-authority-lapse-{}/", uuid::Uuid::new_v4());
    let pod_store = store_at(&proxy.endpoint, &prefix).await;

    let cancel = CancellationToken::new();
    let (handler, events) = MockHandoffHandler::new();
    let authority = Arc::new(AuthorityClock::unclaimed());
    // TTL 9 puts the renewal margin at 6s, so the lapse is observable
    // well inside the test's patience.
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&pod_store),
        personhog_coordination::pod::PodConfig {
            pod_name: "lapse-pod".to_string(),
            lease_ttl: 9,
            heartbeat_interval: Duration::from_secs(1),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::clone(&authority),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    let store = store_at(ETCD_ENDPOINT, &prefix).await;
    put_handoff(&store, 0, None, "lapse-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;
    assert!(
        authority.is_valid(),
        "a registered pod renewing normally must hold authority"
    );

    // A reconnectable blip must not cost the pod its claim: the lease is
    // alive in etcd and the keepalive rebuilds its stream. Waiting past
    // the renewal margin (6s at this TTL) is what makes the assertion
    // mean something — surviving it requires renewals to have been
    // confirmed *and* published through the rebuilt stream, not merely
    // the stamp taken when the session began.
    proxy.sever();
    tokio::time::sleep(Duration::from_secs(8)).await;
    assert!(
        authority.is_valid(),
        "authority must survive a blip the keepalive can ride out, on the strength of \
         renewals published through the rebuilt stream"
    );

    // Now a real outage: new connections are refused too, so no renewal
    // can be confirmed however hard the keepalive tries.
    proxy.set_blackholed(true);
    proxy.sever();

    // Past the renewal margin, nothing confirms the lease any more.
    //
    // This deliberately does not assert *how* the claim went: with a
    // keepalive still running, the stamp ages out and the keepalive
    // declares lease loss at the same margin — they are the same
    // fraction of the same TTL — so surrender and staleness coincide and
    // no assertion here can separate them. The case where they diverge
    // is a keepalive that is not running at all, which no amount of
    // network fault injection produces, and which
    // `authority_lapses_without_renewal` covers directly against the
    // clock.
    wait_for_condition(Duration::from_secs(15), POLL_INTERVAL, || {
        let authority = Arc::clone(&authority);
        async move { !authority.is_valid() }
    })
    .await;

    // And it must have *surrendered*, not merely aged out. With etcd
    // dark the registration watch dies without seeing a deletion, so the
    // only thing that can set this is the lease-loss branch giving the
    // claim up before it drains — which is what stops the pod acking
    // writes for a partition the coordinator may already be reassigning.
    assert!(
        authority.is_surrendered(),
        "losing the lease must give the claim up, not just let it go stale"
    );

    cancel.cancel();
}

/// A lease revoked out from under a pod deletes its registration at once,
/// but the keepalive only learns on its next round — and the coordinator,
/// which sees the deletion immediately, can reassign inside that gap. The
/// pod must stop claiming ownership on the deletion, not a heartbeat
/// later.
#[tokio::test]
async fn authority_is_surrendered_when_the_registration_is_deleted() {
    let prefix = format!("/test-registration-delete-{}/", uuid::Uuid::new_v4());
    let store = store_at(ETCD_ENDPOINT, &prefix).await;

    let cancel = CancellationToken::new();
    let (handler, events) = MockHandoffHandler::new();
    let authority = Arc::new(AuthorityClock::unclaimed());
    // A long heartbeat is the point: without the watch, nothing would
    // notice for this long, and the test would time out.
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "revoked-pod".to_string(),
            lease_ttl: 60,
            heartbeat_interval: Duration::from_secs(20),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::clone(&authority),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    put_handoff(&store, 0, None, "revoked-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;
    assert!(authority.is_valid(), "a registered pod holds authority");

    revoke_lease_of_key(&format!("{prefix}pods/revoked-pod")).await;

    wait_for_condition(Duration::from_secs(10), POLL_INTERVAL, || {
        let authority = Arc::clone(&authority);
        async move { !authority.is_valid() }
    })
    .await;
    // The margin here is forty seconds, so nothing could have aged out in
    // ten — this is the watch giving the claim up on the deletion.
    assert!(
        authority.is_surrendered(),
        "a deleted registration must surrender the claim, not wait for it to lapse"
    );

    cancel.cancel();
}

/// A deleted registration must put the pod back to work, not just stop
/// it serving.
///
/// Surrendering alone would leave a pod holding a live lease, refusing
/// every read, and never registering again — idle with nothing to
/// escalate. Ending the session is what makes it re-register and take
/// partitions back.
#[tokio::test]
async fn a_deleted_registration_starts_a_new_session() {
    let prefix = format!("/test-registration-resession-{}/", uuid::Uuid::new_v4());
    let store = store_at(ETCD_ENDPOINT, &prefix).await;

    let cancel = CancellationToken::new();
    let (handler, events) = MockHandoffHandler::new();
    let authority = Arc::new(AuthorityClock::unclaimed());
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "resession-pod".to_string(),
            lease_ttl: 60,
            // Long enough that the keepalive cannot be what notices.
            heartbeat_interval: Duration::from_secs(20),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::clone(&authority),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    put_handoff(&store, 0, None, "resession-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    revoke_lease_of_key(&format!("{prefix}pods/resession-pod")).await;

    // The pod must come back: a fresh session re-registers and claims
    // authority again.
    let check = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(20), POLL_INTERVAL, || {
        let store = Arc::clone(&check);
        let authority = Arc::clone(&authority);
        async move {
            let registered = store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "resession-pod"))
                .unwrap_or(false);
            registered && authority.is_valid()
        }
    })
    .await;

    cancel.cancel();
}

/// The watch is a prefix watch, so it sees every deletion under
/// `pods/`. Only the pod's own registration key may cost it the session
/// — matching anything looser (say, a final path segment) would let an
/// unrelated key deletion release and re-warm every partition the pod
/// holds.
#[tokio::test]
async fn a_foreign_deletion_under_the_pods_prefix_does_not_cost_the_session() {
    let prefix = format!("/test-registration-foreign-{}/", uuid::Uuid::new_v4());
    let store = store_at(ETCD_ENDPOINT, &prefix).await;

    let cancel = CancellationToken::new();
    let (handler, events) = MockHandoffHandler::new();
    let authority = Arc::new(AuthorityClock::unclaimed());
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "exact-pod".to_string(),
            lease_ttl: 60,
            // Long enough that only the watch could be reacting.
            heartbeat_interval: Duration::from_secs(20),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::clone(&authority),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    put_handoff(&store, 0, None, "exact-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    // A key under the prefix whose final segment matches the pod's name,
    // but which is not its registration.
    let mut raw = etcd_client::Client::connect([common::ETCD_ENDPOINT], None)
        .await
        .expect("connect raw etcd client");
    let decoy = format!("{prefix}pods/decoy/exact-pod");
    raw.put(decoy.as_str(), "{}", None)
        .await
        .expect("put decoy");
    raw.delete(decoy.as_str(), None)
        .await
        .expect("delete decoy");

    // The deletion must pass through the watch without costing the
    // session: no release, and the claim stays standing. The window is a
    // bounded observation, long enough for the watch to have delivered
    // the decoy event many times over.
    let observe_until = std::time::Instant::now() + Duration::from_millis(1_500);
    while std::time::Instant::now() < observe_until {
        assert!(
            authority.is_valid(),
            "an unrelated deletion under the prefix must not surrender the claim"
        );
        assert!(
            !events.lock().await.contains(&HandoffEvent::Released(0)),
            "an unrelated deletion under the prefix must not end the session"
        );
        tokio::time::sleep(POLL_INTERVAL).await;
    }

    // And the watch must still be live and exact: deleting the real
    // registration ends the session.
    raw.delete(format!("{prefix}pods/exact-pod").as_str(), None)
        .await
        .expect("delete the registration");
    wait_for_event(&events, HandoffEvent::Released(0)).await;

    cancel.cancel();
}

/// A registration deleted out from under a live lease (an operator
/// `del`, not a revoke) lands the pod on the lease-loss branch with the
/// lease still standing. The branch must revoke it: otherwise the next
/// session grants a second lease while the first sits alive and
/// unreferenced for its full TTL.
#[tokio::test]
async fn an_operator_delete_of_a_live_registration_revokes_its_lease() {
    let prefix = format!("/test-registration-operator-del-{}/", uuid::Uuid::new_v4());
    let store = store_at(ETCD_ENDPOINT, &prefix).await;

    let cancel = CancellationToken::new();
    let (handler, events) = MockHandoffHandler::new();
    let authority = Arc::new(AuthorityClock::unclaimed());
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "operator-del-pod".to_string(),
            // Long enough that an unrevoked lease would outlive the test
            // by a wide margin — the assertion below can only pass
            // because the branch revoked it.
            lease_ttl: 60,
            heartbeat_interval: Duration::from_secs(20),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::clone(&authority),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    put_handoff(&store, 0, None, "operator-del-pod", HandoffPhase::Warming).await;
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    let key = format!("{prefix}pods/operator-del-pod");
    let mut raw = etcd_client::Client::connect([common::ETCD_ENDPOINT], None)
        .await
        .expect("connect raw etcd client");
    let resp = raw.get(key.as_str(), None).await.expect("get registration");
    let orphaned_lease = resp.kvs().first().expect("registration exists").lease();
    assert_ne!(orphaned_lease, 0, "the registration is lease-backed");

    // The operator's `del`: the key goes, the lease stays.
    raw.delete(key.as_str(), None)
        .await
        .expect("delete the registration");

    // The pod notices via the watch, takes the lease-loss branch, and
    // must revoke the now-orphaned lease on its way to a new session.
    wait_for_condition(Duration::from_secs(15), POLL_INTERVAL, || {
        let mut raw = raw.clone();
        async move {
            raw.lease_time_to_live(orphaned_lease, None)
                .await
                .map(|resp| resp.ttl() <= 0)
                .unwrap_or(false)
        }
    })
    .await;

    // And the new session is live on a fresh lease.
    let check = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(20), POLL_INTERVAL, || {
        let store = Arc::clone(&check);
        let authority = Arc::clone(&authority);
        async move {
            let registered = store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "operator-del-pod"))
                .unwrap_or(false);
            registered && authority.is_valid()
        }
    })
    .await;

    cancel.cancel();
}

/// A drain that cannot quiesce must not keep the pod serving everything
/// else it no longer owns.
///
/// Self-fencing runs because the pod has lost the right to serve, so the
/// release is the point of it. Returning on the first drain failure left
/// every other held partition still served by a pod with no lease —
/// precisely the zombie the fence exists to prevent.
#[tokio::test]
async fn a_stuck_drain_does_not_strand_the_other_partitions_on_lease_loss() {
    let (store, prefix) = test_store_with_prefix("stuck-drain-fence").await;
    let cancel = CancellationToken::new();
    let pod = start_pod_with_stuck_drain(Arc::clone(&store), "stuck-pod-0", 1, 5, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "stuck-pod-0"))
                .unwrap_or(false)
        }
    })
    .await;

    // Two partitions: one whose drain refuses, one ordinary.
    for partition in [0, 1] {
        put_handoff(
            &store,
            partition,
            None,
            "stuck-pod-0",
            HandoffPhase::Warming,
        )
        .await;
    }
    let events = Arc::clone(&pod.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            let seen = events.lock().await;
            [0u32, 1u32].iter().all(|p| {
                seen.iter()
                    .any(|e| matches!(e, HandoffEvent::Warmed(w) if w == p))
            })
        }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}pods/stuck-pod-0")).await;

    // Partition 0's drain succeeds and 1's never will, so 0 must still
    // be given up.
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "partition 0 to be released despite partition 1's drain refusing",
        || {
            let events = Arc::clone(&events);
            async move {
                events
                    .lock()
                    .await
                    .iter()
                    .any(|e| matches!(e, HandoffEvent::Released(0)))
            }
        },
    )
    .await;

    // And 1 must not be. Its writes are still in flight and will ack
    // whatever we do — so releasing would unfence fresh admissions on a
    // leaseless pod, drop the cache out from under those handlers, and
    // erase the one record that the partition was never given up.
    assert!(
        !events
            .lock()
            .await
            .iter()
            .any(|e| matches!(e, HandoffEvent::Released(1))),
        "a partition whose drain never quiesced must stay held, not be released"
    );

    cancel.cancel();
}

/// A drain that outlives the self-fence's bound is a failure, not a
/// quiesce.
///
/// The timeout arm is the only exit for in-flight work that never
/// finishes, and it must not count the partition as drained: its writes
/// are still in flight and will ack whatever happens next, so releasing
/// would unfence fresh admissions on a leaseless pod, drop the cache
/// out from under the handlers still using it, and erase the one record
/// that the partition was never given up. The timed-out partition stays
/// held, and the recorded failure ends the run so the process restart
/// clears the stuck work by death.
#[tokio::test]
async fn a_drain_that_times_out_is_a_failure_not_a_quiesce() {
    let (store, prefix) = test_store_with_prefix("hung-drain-fence").await;
    let cancel = CancellationToken::new();
    let mut pod =
        start_pod_with_hanging_drain(Arc::clone(&store), "hung-pod-0", 1, 5, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "hung-pod-0"))
                .unwrap_or(false)
        }
    })
    .await;

    // Two partitions: one whose drain hangs past the bound, one ordinary.
    for partition in [0, 1] {
        put_handoff(&store, partition, None, "hung-pod-0", HandoffPhase::Warming).await;
    }
    let events = Arc::clone(&pod.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            let seen = events.lock().await;
            [0u32, 1u32].iter().all(|p| {
                seen.iter()
                    .any(|e| matches!(e, HandoffEvent::Warmed(w) if w == p))
            })
        }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}pods/hung-pod-0")).await;

    // The run must end: a partition it could neither drain nor release
    // still has its cache and authority, so in-place recovery is refused.
    // Under a timeout that counts as a quiesce there is no failure to
    // report, the pod starts a new session, and this bound expires.
    let run = pod.join_handle.take().expect("the pod is running");
    let outcome = tokio::time::timeout(WAIT_TIMEOUT, run)
        .await
        .expect("a pod whose drain timed out must stop rather than start a new session")
        .expect("the pod task must not panic");
    assert!(
        outcome.is_err(),
        "a drain cut off by the self-fence bound must end the run, not recover in place"
    );

    // The ordinary partition was still given up, and the hung one was
    // not: release without a quiesce is the acked-write loss the drain
    // phase exists to prevent.
    let seen = events.lock().await;
    assert!(
        seen.iter().any(|e| matches!(e, HandoffEvent::Released(0))),
        "partition 0 quiesced and must be released despite partition 1 hanging: {seen:?}"
    );
    assert!(
        !seen.iter().any(|e| matches!(e, HandoffEvent::Released(1))),
        "a partition whose drain timed out must stay held, not be released: {seen:?}"
    );
    drop(seen);

    cancel.cancel();
}

/// A drain that fails must still leave the partition recorded as fenced.
///
/// The handler fences the data plane as its first act and can fail
/// afterwards. `resume_partition` — the only branch that lifts that
/// fence — is reachable only through `fenced_partitions`, so a record
/// written only on success leaves writes rejected with no branch left to
/// re-enter, while reads carry on and the convergence reports healthy.
#[tokio::test]
async fn a_failed_drain_still_leaves_a_partition_that_can_be_resumed() {
    let (store, _prefix) = test_store_with_prefix("failed-drain-resume").await;
    let cancel = CancellationToken::new();
    let pod = start_pod_with_stuck_drain(Arc::clone(&store), "stuck-pod-1", 0, 30, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "stuck-pod-1"))
                .unwrap_or(false)
        }
    })
    .await;

    // Own it, then start a handoff away whose drain refuses.
    put_handoff(&store, 0, None, "stuck-pod-1", HandoffPhase::Warming).await;
    let events = Arc::clone(&pod.events);
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;
    put_handoff(
        &store,
        0,
        Some("stuck-pod-1"),
        "other-pod",
        HandoffPhase::Draining,
    )
    .await;

    // Sequence on the failed attempt, not the write: overwriting the
    // handoff before the pod has observed Draining would skip the drain
    // entirely, and with it the fence record this test exists to check.
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "the pod to attempt (and fail) the drain, recording the partition as fenced",
        || {
            let events = Arc::clone(&events);
            async move {
                events
                    .lock()
                    .await
                    .iter()
                    .any(|e| matches!(e, HandoffEvent::DrainFailed(0)))
            }
        },
    )
    .await;

    // Cancel the handoff. The pod is serving again, so it must resume —
    // which it can only do if the failed drain was still recorded.
    put_handoff(&store, 0, None, "stuck-pod-1", HandoffPhase::Complete).await;
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "the partition to resume, which needs the failed drain to have been recorded as fenced",
        || {
            let events = Arc::clone(&events);
            async move {
                events
                    .lock()
                    .await
                    .iter()
                    .any(|e| matches!(e, HandoffEvent::Resumed(0)))
            }
        },
    )
    .await;

    cancel.cancel();
}

/// A release that fails must not stop the pod giving up the rest.
///
/// Phase 2 is the point of self-fencing: it drops each partition's cache
/// and serving authority. Returning on the first release failure leaves
/// every partition after it in the loop still served by a pod with no
/// lease — the same zombie the drain phase collects its failures to
/// avoid, one phase later.
#[tokio::test]
async fn a_failing_release_does_not_stop_the_pod_giving_up_the_rest() {
    let (store, prefix) = test_store_with_prefix("failing-release-fence").await;
    let cancel = CancellationToken::new();
    let (pod, attempts) =
        start_pod_with_failing_release(Arc::clone(&store), "failing-rel-0", 5, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "failing-rel-0"))
                .unwrap_or(false)
        }
    })
    .await;

    for partition in [0, 1] {
        put_handoff(
            &store,
            partition,
            None,
            "failing-rel-0",
            HandoffPhase::Warming,
        )
        .await;
    }
    let events = Arc::clone(&pod.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&events);
        async move {
            let seen = events.lock().await;
            [0u32, 1u32].iter().all(|p| {
                seen.iter()
                    .any(|e| matches!(e, HandoffEvent::Warmed(w) if w == p))
            })
        }
    })
    .await;

    revoke_lease_of_key(&format!("{prefix}pods/failing-rel-0")).await;

    // Both partitions must be asked, not just whichever the release loop
    // reached first. Polled by hand rather than through
    // `wait_for_condition` so the failure names what was missing instead
    // of reporting a bare timeout.
    let mut tried = Vec::new();
    for _ in 0..(WAIT_TIMEOUT.as_millis() / POLL_INTERVAL.as_millis()) {
        tried = attempts.lock().await.clone();
        if tried.contains(&0) && tried.contains(&1) {
            break;
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
    assert!(
        tried.contains(&0) && tried.contains(&1),
        "a failed release must not strand the partitions after it; only {tried:?} of [0, 1] \
         were ever attempted"
    );

    cancel.cancel();
}

/// A self-fence that could not finish must refuse in-place recovery.
///
/// The pod's serving state no longer matches what it owns — a partition
/// it could neither drain nor release still has its cache and its
/// authority. Starting a fresh session on top of that is the zombie the
/// fence exists to prevent, so the run has to end and let the process
/// restart clear it. Reporting the failure is what sets that flag; the
/// release loop above runs first precisely so the report is not what
/// stops it.
#[tokio::test]
async fn a_self_fence_that_could_not_finish_refuses_in_place_recovery() {
    let (store, prefix) = test_store_with_prefix("poisoned-self-fence").await;
    let cancel = CancellationToken::new();
    let mut pod =
        start_pod_with_stuck_drain(Arc::clone(&store), "poisoned-pod-0", 0, 5, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "poisoned-pod-0"))
                .unwrap_or(false)
        }
    })
    .await;

    put_handoff(&store, 0, None, "poisoned-pod-0", HandoffPhase::Warming).await;
    let events = Arc::clone(&pod.events);
    wait_for_event(&events, HandoffEvent::Warmed(0)).await;

    revoke_lease_of_key(&format!("{prefix}pods/poisoned-pod-0")).await;

    let run = pod.join_handle.take().expect("the pod is running");
    let outcome = tokio::time::timeout(WAIT_TIMEOUT, run)
        .await
        .expect("a pod whose self-fence failed must stop rather than start a new session")
        .expect("the pod task must not panic");
    assert!(
        outcome.is_err(),
        "a pod that could not give up a partition must end its run, not recover in place"
    );

    cancel.cancel();
}

/// A release that fails must leave the pod still remembering it holds
/// the partition, so the retry can release it.
///
/// The arm used to forget first — remove from both ownership maps, then
/// call the handler — so a failed (or torn-down) release left the
/// partition in neither map, where no convergence ever dispatched for it
/// again: its cache, version floors, and installed producer leaked for
/// the life of the process, and a stale-tabled router was served from
/// the leaked cache instead of the bounce dropping it exists to produce.
#[tokio::test]
async fn a_failed_release_is_retried_rather_than_forgotten() {
    let (store, _prefix) = test_store_with_prefix("flaky-release").await;
    let cancel = CancellationToken::new();
    let pod =
        start_pod_with_flaky_release(Arc::clone(&store), "flaky-release-pod", 1, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "flaky-release-pod"))
                .unwrap_or(false)
        }
    })
    .await;

    put_handoff(&store, 0, None, "flaky-release-pod", HandoffPhase::Warming).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;

    put_handoff(
        &store,
        0,
        Some("flaky-release-pod"),
        "other-pod",
        HandoffPhase::Complete,
    )
    .await;

    // The first attempt fails and the convergence retries. The retry can
    // only release what the pod still remembers holding.
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "the retried release to succeed, which needs the failed attempt to not have \
         forgotten the partition",
        || {
            let events = Arc::clone(&pod.events);
            async move {
                events
                    .lock()
                    .await
                    .iter()
                    .any(|e| matches!(e, HandoffEvent::Released(0)))
            }
        },
    )
    .await;

    cancel.cancel();
}

/// Completion must apply to the handoff whose warm was verified, not to
/// whatever record is at the key when the write lands.
///
/// The coordinator reads a handoff, checks its warmed acks, and then
/// completes it. In between, cancellation can replace the record with a
/// successor and delete the old acks in one transaction. Completing that
/// successor would write the assignment to a pod that never froze,
/// drained, or warmed — while the old owner is still admitting writes —
/// and routers would cut over to it. A `mod_revision` guard cannot see
/// this: it only proves nothing changed since the store's own re-read.
#[tokio::test]
async fn completion_refuses_a_handoff_that_was_replaced() {
    let store = test_store("complete-replaced").await;

    // The attempt the caller validated.
    put_handoff(&store, 0, Some("pod-a"), "pod-b", HandoffPhase::Warming).await;
    let validated = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");

    // Cancellation replaces it with a successor carrying a fresh id,
    // exactly as `handle_pod_change_static` does.
    store.delete_handoff(0).await.expect("delete");
    put_handoff_with_id(&store, 0, "pod-c", HandoffPhase::Freezing, "successor").await;

    let completed = store
        .complete_handoff(0, &validated.handoff_id, HandoffPhase::Warming)
        .await
        .expect("complete_handoff");
    assert!(
        !completed,
        "a replaced handoff must not be completed by its predecessor's verification"
    );

    // The successor must still be Freezing, and no assignment written.
    let current = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert_eq!(current.phase, HandoffPhase::Freezing);
    assert!(
        store
            .get_assignment(0)
            .await
            .expect("get assignment")
            .is_none(),
        "no assignment may be written for a handoff that never completed"
    );
}

/// The same guard on the phase advances: a successor at the same phase
/// must not inherit its predecessor's verification.
#[tokio::test]
async fn phase_advance_refuses_a_handoff_that_was_replaced() {
    let store = test_store("advance-replaced").await;

    put_handoff(&store, 0, Some("pod-a"), "pod-b", HandoffPhase::Freezing).await;
    let validated = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");

    store.delete_handoff(0).await.expect("delete");
    // Same phase, different attempt: the id is the only thing that can
    // tell them apart, which is the point.
    put_handoff_with_id(&store, 0, "pod-c", HandoffPhase::Freezing, "successor").await;

    let advanced = store
        .cas_handoff_phase(
            0,
            &validated.handoff_id,
            HandoffPhase::Freezing,
            HandoffPhase::Draining,
        )
        .await
        .expect("cas_handoff_phase");
    assert!(
        !advanced,
        "a replaced handoff must not be advanced by its predecessor's quorum"
    );
}

/// Records `verify_serving` calls — the repair a data-plane repair
/// request exists to trigger.
struct RepairProbeHandler {
    events: Arc<Mutex<Vec<HandoffEvent>>>,
    verified: Arc<AtomicUsize>,
}

#[async_trait]
impl personhog_coordination::pod::HandoffHandler for RepairProbeHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn verify_serving(&self, _partition: u32) -> Result<bool> {
        self.verified.fetch_add(1, Ordering::SeqCst);
        Ok(false)
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

/// A data-plane repair nudge must converge immediately. The
/// condemned-producer incident this pins: every write on the partition
/// bounces until `verify_serving` re-takes the fence, and with the
/// reconcile tick as the only trigger that wait is a whole interval.
/// Here reconcile is parked at a day and no etcd event fires, so the
/// only thing that can drive the second `verify_serving` is the nudge
/// arm itself.
#[tokio::test]
async fn a_repair_nudge_converges_without_waiting_for_reconcile() {
    let store = test_store("repair-request-converges").await;
    let cancel = CancellationToken::new();

    store
        .put_assignments(&[PartitionAssignment {
            partition: 0,
            owner: "repair-pod".to_string(),
            status: AssignmentStatus::Active,
            advertise_address: None,
        }])
        .await
        .expect("write assignment");

    let events: Arc<Mutex<Vec<HandoffEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let verified = Arc::new(AtomicUsize::new(0));
    let handler = RepairProbeHandler {
        events: Arc::clone(&events),
        verified: Arc::clone(&verified),
    };
    let nudge = Arc::new(Notify::new());
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "repair-pod".to_string(),
            // A session restart re-runs the seed convergence, which also
            // bumps `verified`; a 30s lease keeps restarts out of this
            // test's window so only the repair arm can move the counter.
            lease_ttl: 30,
            heartbeat_interval: Duration::from_secs(10),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    )
    .with_repair_nudge(Arc::clone(&nudge));
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    // The seed convergence serves the partition and runs the first
    // verification on its way.
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let verified = Arc::clone(&verified);
        async move { verified.load(Ordering::SeqCst) >= 1 }
    })
    .await;
    let baseline = verified.load(Ordering::SeqCst);

    nudge.notify_one();

    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "repair nudge drives a convergence",
        || {
            let verified = Arc::clone(&verified);
            async move { verified.load(Ordering::SeqCst) > baseline }
        },
    )
    .await;

    // A second nudge inside the cooldown must not run another pass: the
    // condemn-heal-condemn flap would otherwise drive passes at broker
    // speed, resetting the budgets that exist to catch it. The cooldown
    // is the reconcile interval, parked at a day here, so nothing but
    // the suppression can be holding the counter still.
    let after_first = verified.load(Ordering::SeqCst);
    nudge.notify_one();
    tokio::time::sleep(Duration::from_millis(1_500)).await;
    assert_eq!(
        verified.load(Ordering::SeqCst),
        after_first,
        "a nudge inside the cooldown must fall to the reconcile tick"
    );

    cancel.cancel();
}

/// Records `prepare_acquire` calls — the pending-ownership hint.
struct PrepareProbeHandler {
    events: Arc<Mutex<Vec<HandoffEvent>>>,
    prepared: Arc<AtomicUsize>,
}

#[async_trait]
impl personhog_coordination::pod::HandoffHandler for PrepareProbeHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn prepare_acquire(&self, _partition: u32) {
        self.prepared.fetch_add(1, Ordering::SeqCst);
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

/// The incoming owner of a handoff still freezing or draining must see
/// the pending-ownership hint — the window where connection setup can
/// run ahead of the fence — while warming stays forbidden until the
/// phase says the HWM is stable.
#[tokio::test]
async fn a_pending_new_owner_is_hinted_but_not_warmed() {
    let store = test_store("pending-owner-hint").await;
    let cancel = CancellationToken::new();

    store
        .put_assignments(&[PartitionAssignment {
            partition: 0,
            owner: "old-pod".to_string(),
            status: AssignmentStatus::Active,
            advertise_address: None,
        }])
        .await
        .expect("write assignment");

    let events: Arc<Mutex<Vec<HandoffEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let prepared = Arc::new(AtomicUsize::new(0));
    let handler = PrepareProbeHandler {
        events: Arc::clone(&events),
        prepared: Arc::clone(&prepared),
    };
    let pod = personhog_coordination::pod::PodHandle::new(
        Arc::clone(&store),
        personhog_coordination::pod::PodConfig {
            pod_name: "pre-pod".to_string(),
            lease_ttl: 30,
            heartbeat_interval: Duration::from_secs(10),
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });

    put_handoff(
        &store,
        0,
        Some("old-pod"),
        "pre-pod",
        HandoffPhase::Draining,
    )
    .await;

    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "pending new owner receives the prepare hint",
        || {
            let prepared = Arc::clone(&prepared);
            async move { prepared.load(Ordering::SeqCst) >= 1 }
        },
    )
    .await;
    assert!(
        !events
            .lock()
            .await
            .iter()
            .any(|e| matches!(e, HandoffEvent::Warmed(0))),
        "a draining handoff must hint the new owner without warming it"
    );

    cancel.cancel();
}

/// A standby waits on the leader key rather than campaigning at its
/// retry interval — a campaign costs etcd writes per candidate per
/// retry, so standing by must cost nothing until the key goes away.
///
/// The fallback re-read is set beyond the test's timeouts and a
/// successor reclaims the key instantly, so only the delete event can
/// end the wait. The read-to-attach gap is pinned separately by
/// `a_leader_that_goes_between_the_read_and_the_watch_is_still_delivered`.
#[tokio::test]
async fn a_standby_waits_on_the_leader_key_rather_than_campaigning() {
    let prefix = format!("/test-standby-watch-{}/", uuid::Uuid::new_v4());
    let store = store_at(ETCD_ENDPOINT, &prefix).await;

    let standby = Arc::new(Coordinator::new(
        Arc::clone(&store),
        CoordinatorConfig {
            name: "standby".to_string(),
            standby_poll_interval: Duration::from_secs(600),
            ..Default::default()
        },
        Arc::new(StickyBalancedStrategy),
        None,
    ));
    let cancel = CancellationToken::new();

    // With no leader recorded, the election is open and the wait is over
    // before it starts.
    tokio::time::timeout(WAIT_TIMEOUT, standby.await_election_opening(&cancel))
        .await
        .expect("an unheld election must not make a candidate wait")
        .expect("reading the leader key must succeed");

    // The lease only serves to take the key. The test drives the key
    // directly from there, because revoking the lease can only produce a
    // delete, and the first thing to prove is that a write which is not
    // a delete leaves the candidate parked. Nothing renews it, so its
    // TTL sits far above the assertion window: an expiry mid-test would
    // deliver the delete this test exists to prove is the only waker.
    let lease_id = store.grant_lease(60).await.unwrap();
    assert!(
        store
            .try_acquire_leadership("incumbent", lease_id)
            .await
            .unwrap(),
        "the test's own leader must take the key"
    );

    // An incumbent holds it, so the candidate parks. The wait runs as a
    // task from here on, with the fallback re-read set past every
    // timeout in this test, so nothing but the delete can end it.
    let waiting = {
        let standby = Arc::clone(&standby);
        let cancel = cancel.clone();
        tokio::spawn(async move { standby.await_election_opening(&cancel).await })
    };
    // Generous, because the point of the window is to let the wait
    // reach its read and park: a runner slow enough to still be reading
    // when the revoke lands would see the read return no leader and
    // finish for the wrong reason.
    tokio::time::sleep(Duration::from_secs(2)).await;
    assert!(
        !waiting.is_finished(),
        "a candidate must not enter an election another coordinator holds"
    );

    // A write to the key that is not a deletion must not end the wait.
    // Overwriting it in place produces a Put and no Delete, which is
    // exactly what a predicate matching the wrong event type would
    // accept. No coordinator writes the key that way — campaigning is a
    // create, guarded on the key being absent — so the event is built
    // here rather than provoked, to hold the discriminator itself.
    let leader_key = format!("{prefix}coordinator/leader");
    let mut raw = etcd_client::Client::connect([ETCD_ENDPOINT], None)
        .await
        .expect("connect raw etcd client");
    raw.put(
        leader_key.clone(),
        r#"{"holder":"incumbent","lease_id":0}"#,
        None,
    )
    .await
    .expect("overwrite the leader key");
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert!(
        !waiting.is_finished(),
        "a write that is not a deletion must not open the election"
    );

    // Now the deletion, with a successor taking the key back at once so
    // a re-read can never be what ends the wait — only the delete event
    // can. etcd rejects a delete and a put of one key in a single
    // transaction, so a one-round-trip window remains; a defect large
    // enough to matter here needs seconds, not that.
    raw.delete(leader_key, None)
        .await
        .expect("delete the leader key");
    let successor_lease = store.grant_lease(60).await.expect("grant lease");
    assert!(
        store
            .try_acquire_leadership("successor", successor_lease)
            .await
            .expect("successor campaign"),
        "the successor must take the key back"
    );
    tokio::time::timeout(WAIT_TIMEOUT, waiting)
        .await
        .expect("the watch must wake the candidate when the leader goes")
        .expect("the waiting task must not panic")
        .expect("watching the leader key must succeed");
}

/// A handoff replaced in place — cancelled and re-issued in one
/// transaction — must still reach a pod the successor no longer names.
/// The old owner sees a single put naming two other pods; only what it
/// still holds locally says the fence should come off, and a pod that
/// skipped the event would reject writes until the reconcile tick.
///
/// Pins the local-state disjunct as a whole (warm and fence held
/// together); the individual terms are held by
/// `restarted_old_owner_serves_again_after_handoff_cancelled` and
/// `pod_releases_partition_when_cancelled_handoff_leaves_it_unassigned`.
#[tokio::test]
async fn a_replaced_handoff_reaches_the_old_owner_it_no_longer_names() {
    let store = test_store("handoff-replaced-old-owner").await;
    let cancel = CancellationToken::new();

    let pod = start_pod(Arc::clone(&store), "replaced-pod-a", cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "replaced-pod-a"))
                .unwrap_or(false)
        }
    })
    .await;

    // Take ownership of partition 0 through the real acquisition path, so
    // the assignment names this pod.
    put_handoff(&store, 0, None, "replaced-pod-a", HandoffPhase::Warming).await;
    wait_for_event(&pod.events, HandoffEvent::Warmed(0)).await;
    let warming = store
        .get_handoff(0)
        .await
        .expect("get handoff")
        .expect("handoff exists");
    assert!(
        store
            .complete_handoff(0, &warming.handoff_id, HandoffPhase::Warming)
            .await
            .expect("complete"),
        "complete_handoff must succeed"
    );
    store.delete_handoff(0).await.expect("cleanup");

    // Move the partition away, leaving this pod drained and fenced.
    put_handoff(
        &store,
        0,
        Some("replaced-pod-a"),
        "replaced-pod-b",
        HandoffPhase::Draining,
    )
    .await;
    wait_for_event(&pod.events, HandoffEvent::Drained(0)).await;

    // The successor is written over the same key and names neither this
    // pod nor anything it holds. The assignment still names it, so it
    // must resume rather than stay fenced.
    put_handoff(
        &store,
        0,
        Some("replaced-pod-b"),
        "replaced-pod-c",
        HandoffPhase::Freezing,
    )
    .await;
    wait_for_event(&pod.events, HandoffEvent::Resumed(0)).await;

    cancel.cancel();
}

/// A plan records its freeze-quorum membership once and points its
/// handoffs at it, rather than writing the router fleet into each one.
///
/// Inlining made a handoff record grow with the fleet and a plan
/// transaction grow with the fleet times the partition count. At a few
/// hundred of each that exceeded etcd's maximum request size, so the
/// transaction was rejected and no partition moved at all. The same
/// bytes were paid again by every list of handoffs.
///
/// The sweep is the other half: membership records outlive nothing, so
/// without collection they accumulate one per plan forever.
#[tokio::test]
async fn a_plan_records_its_freeze_quorum_once_and_collects_it_after() {
    let store = test_store("freeze-quorum-by-reference").await;
    store.set_total_partitions(2).await.expect("set partitions");
    let cancel = CancellationToken::new();

    // A registered router that never acks parks every handoff in
    // Freezing, so the records under test stay put while the test reads
    // them.
    let lease_id = store.grant_lease(60).await.expect("grant lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "fqr-router".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            lease_id,
        )
        .await
        .expect("register router");

    let _pod = start_pod(Arc::clone(&store), "fqr-pod", cancel.clone());
    let _coordinator = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    let check = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check);
        async move {
            store
                .list_handoffs()
                .await
                .map(|handoffs| {
                    !handoffs.is_empty()
                        && handoffs.iter().all(|h| h.phase == HandoffPhase::Freezing)
                })
                .unwrap_or(false)
        }
    })
    .await;

    let handoffs = store.list_handoffs().await.expect("list handoffs");
    let referenced: HashSet<String> = handoffs
        .iter()
        .filter_map(|h| h.freeze_quorum_ref.clone())
        .collect();
    assert_eq!(
        referenced.len(),
        1,
        "every handoff of one plan must point at the same membership record"
    );
    for handoff in &handoffs {
        assert!(
            handoff.freeze_quorum.is_none(),
            "the membership must not also be written into the handoff"
        );
    }

    let id = referenced.into_iter().next().expect("a referenced id");
    let members = store
        .get_freeze_quorum(&id)
        .await
        .expect("read membership")
        .expect("the plan must write the record it points at");
    assert_eq!(
        members,
        vec!["fqr-router".to_string()],
        "the record must hold the routers registered when the plan ran"
    );

    // Nothing refers to it once the handoffs are gone, so the sweep on
    // the coordinator's reconcile tick must take it.
    for handoff in &handoffs {
        store
            .delete_handoff(handoff.partition)
            .await
            .expect("delete handoff");
    }
    let check = Arc::clone(&store);
    let swept_id = id.clone();
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check);
        let id = swept_id.clone();
        async move {
            store
                .get_freeze_quorum(&id)
                .await
                .map(|members| members.is_none())
                .unwrap_or(false)
        }
    })
    .await;

    cancel.cancel();
}

/// A freeze-quorum reference that no longer resolves must read as
/// "membership unknown", never as "membership empty".
///
/// The two are one `Option` apart and sit on opposite sides of the
/// safety argument. Unknown falls back to requiring every live router,
/// which can only delay a handoff. Empty requires nobody, which would
/// advance a handoff out of Freezing before any router had stopped
/// routing to the old owner — the state the freeze exists to prevent.
#[tokio::test]
async fn a_freeze_quorum_reference_that_is_gone_requires_every_live_router() {
    let store = test_store("freeze-quorum-dangling-ref").await;

    let mut handoff = HandoffState {
        partition: 0,
        old_owner: Some("pod-old".to_string()),
        new_owner: "pod-new".to_string(),
        new_owner_address: None,
        phase: HandoffPhase::Freezing,
        started_at: 0,
        handoff_id: "handoff-dangling".to_string(),
        freeze_quorum: None,
        freeze_quorum_ref: Some("never-written".to_string()),
        created_at_ms: 0,
        phase_entered_at_ms: 0,
    };

    let quorum = store
        .resolve_freeze_quorum(&handoff)
        .await
        .expect("resolving must not error");
    assert!(
        quorum.is_none(),
        "a reference with no record must resolve to unknown, not to an empty membership"
    );

    let routers = [
        RegisteredRouter {
            router_name: "router-0".to_string(),
            registered_at: 0,
            last_heartbeat: 0,
        },
        RegisteredRouter {
            router_name: "router-1".to_string(),
            registered_at: 0,
            last_heartbeat: 0,
        },
    ];
    let acks = [RouterFreezeAck {
        router_name: "router-0".to_string(),
        partition: 0,
        acked_at: 0,
        acked_at_ms: 0,
        handoff_id: handoff.handoff_id.clone(),
    }];
    assert!(
        !freeze_quorum_met(&routers, &acks, &handoff, quorum.as_deref()),
        "one ack of two live routers must not satisfy an unresolvable membership"
    );

    // An inline membership on an older record still resolves to itself.
    handoff.freeze_quorum_ref = None;
    handoff.freeze_quorum = Some(vec!["router-0".to_string()]);
    let quorum = store
        .resolve_freeze_quorum(&handoff)
        .await
        .expect("resolving must not error");
    assert!(
        freeze_quorum_met(&routers, &acks, &handoff, quorum.as_deref()),
        "a record carrying its membership inline must still be judged by it"
    );
}

/// A handoff cancelled while its new owner is still warming must reach
/// that pod.
///
/// A new owner records its warm only once `warm_partition` returns, and
/// it holds no fence, so for the whole replay it holds no local state
/// for the partition — and a long warm is exactly what a deadline
/// cancels. Deciding involvement from local state alone drops the
/// deletion there, leaving the pod to finish a warm for a handoff that
/// no longer exists and hold the cache until a reconcile tick notices.
/// This pod's reconcile tick is parked, so only the event path can
/// produce the release.
#[tokio::test]
async fn a_handoff_cancelled_mid_warm_reaches_the_pod_still_warming() {
    let store = test_store("cancel-mid-warm").await;
    let cancel = CancellationToken::new();

    let pod = start_pod_gated(Arc::clone(&store), "mid-warm-pod", 4, cancel.clone());

    let check = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "mid-warm-pod"))
                .unwrap_or(false)
        }
    })
    .await;

    // Acquire partition 0 as the new owner of a fresh assignment. The
    // gate is shut, so the warm parks and the pod holds nothing for the
    // partition yet.
    put_handoff(&store, 0, None, "mid-warm-pod", HandoffPhase::Warming).await;
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let in_flight = Arc::clone(&pod.warms_in_flight);
        async move {
            in_flight
                .lock()
                .expect("warms in flight lock poisoned")
                .get(&0)
                .is_some_and(|count| *count > 0)
        }
    })
    .await;
    assert!(
        !pod.events.lock().await.contains(&HandoffEvent::Warmed(0)),
        "the warm must still be parked at the gate"
    );

    // Cancel it out from under the warm, then let the warm finish.
    store.delete_handoff(0).await.expect("delete handoff");
    pod.gates.open(0);

    // Nothing assigns the partition to this pod, so converging on the
    // deletion must release what the warm installed.
    wait_for_event(&pod.events, HandoffEvent::Released(0)).await;

    cancel.cancel();
}

/// A leader that disappears between a standby's read and its watch is
/// still delivered to that watch. Anchoring the watch at the revision
/// the read returned replays that deletion; anchoring at "now" drops
/// it, which looks identical in any test that lets the watch attach
/// first.
///
/// Driven through the two store calls in order rather than the loop —
/// no amount of racing the loop lands the deletion between them on
/// demand. What this pins is the store contract the loop depends on.
#[tokio::test]
async fn a_leader_that_goes_between_the_read_and_the_watch_is_still_delivered() {
    let store = test_store("standby-watch-anchor").await;

    let lease_id = store.grant_lease(60).await.unwrap();
    assert!(
        store
            .try_acquire_leadership("incumbent", lease_id)
            .await
            .unwrap(),
        "the test's own leader must take the key"
    );

    // The read a standby makes, then the deletion, then the watch.
    let (leader, revision) = store
        .get_leader_with_revision()
        .await
        .expect("reading the leader key must succeed");
    assert!(
        leader.is_some(),
        "the incumbent must be visible to the read"
    );

    store.revoke_lease(lease_id).await.unwrap();

    let mut stream = store
        .watch_leader_from(revision + 1)
        .await
        .expect("watching the leader key must succeed");

    let delivered = tokio::time::timeout(WAIT_TIMEOUT, async {
        loop {
            let Ok(Some(response)) = stream.message().await else {
                return false;
            };
            if response
                .events()
                .iter()
                .any(|event| event.event_type() == EventType::Delete)
            {
                return true;
            }
        }
    })
    .await
    .expect("the watch must deliver the deletion it missed, not wait for a new one");

    assert!(
        delivered,
        "a watch anchored on the read's revision must replay the deletion"
    );
}

/// The sweep must spare a membership record a live handoff refers to.
///
/// Its safety rests on the filter, and on reading the record ids before
/// the handoffs so anything written in between is not a candidate. Drop
/// the filter and the sweep deletes memberships out from under handoffs
/// still in Freezing; each then falls back to requiring every live
/// router, so a rebalance slows to whichever router is slowest to ack.
///
/// This pins the filter. The read ordering it does not pin — the window
/// is a single round trip and the ordering lives at the call site, not
/// in the swept function — so reversing those two reads passes here.
#[tokio::test]
async fn the_sweep_spares_a_membership_a_live_handoff_refers_to() {
    let store = test_store("freeze-quorum-sweep-spares").await;
    store.set_total_partitions(2).await.expect("set partitions");
    let cancel = CancellationToken::new();

    // A registered router that never acks parks the handoffs in
    // Freezing, so their membership stays referenced while the sweep
    // runs against it repeatedly.
    let lease_id = store.grant_lease(60).await.expect("grant lease");
    store
        .register_router(
            &RegisteredRouter {
                router_name: "sweep-router".to_string(),
                registered_at: 0,
                last_heartbeat: 0,
            },
            lease_id,
        )
        .await
        .expect("register router");

    let _pod = start_pod(Arc::clone(&store), "sweep-pod", cancel.clone());
    let _coordinator = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    let check = Arc::clone(&store);
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "a referenced membership",
        || {
            let store = Arc::clone(&check);
            async move {
                store
                    .list_handoffs()
                    .await
                    .map(|handoffs| {
                        !handoffs.is_empty()
                            && handoffs.iter().all(|h| {
                                h.phase == HandoffPhase::Freezing && h.freeze_quorum_ref.is_some()
                            })
                    })
                    .unwrap_or(false)
            }
        },
    )
    .await;

    let id = store
        .list_handoffs()
        .await
        .expect("list handoffs")
        .first()
        .and_then(|h| h.freeze_quorum_ref.clone())
        .expect("a referenced membership id");

    // The coordinator's reconcile tick sweeps every 500ms in these
    // tests, so this spans several passes over a record that is still
    // referenced throughout.
    for _ in 0..6 {
        tokio::time::sleep(Duration::from_millis(250)).await;
        assert!(
            store
                .get_freeze_quorum(&id)
                .await
                .expect("reading the membership must succeed")
                .is_some(),
            "the sweep must not collect a membership a Freezing handoff still refers to"
        );
    }

    cancel.cancel();
}

/// A coordinator that cannot reach etcd keeps trying, and still stops
/// promptly when asked to.
///
/// It has no budget: coordination fails over to a peer for free on every
/// term ending, a restart cannot mend an unwell etcd, and the process it
/// would take down also serves person writes and strong reads. So the
/// contract is retry-and-report, and both halves matter — a coordinator
/// that gave up would shed routing capacity during an etcd event, and
/// one that ignored cancellation would hold shutdown past its grace
/// period.
#[tokio::test]
async fn a_coordinator_that_cannot_reach_etcd_keeps_trying_and_still_stops_on_request() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-coordinator-retries-{}/", uuid::Uuid::new_v4());
    // Connect while the proxy is healthy: the failure under test is a
    // connection that dies later, not one that never opened.
    let store = store_at(&proxy.endpoint, &prefix).await;

    let coordinator = Coordinator::new(
        Arc::clone(&store),
        CoordinatorConfig {
            name: "retrying-coordinator".to_string(),
            // A candidate that cannot read the election climbs the
            // observation ladder rather than the ending pace — it never
            // held a term. Both bases are small so the attempt count
            // this test needs fits inside its timeout even at the
            // ladder's cap.
            standby_poll_interval: Duration::from_millis(20),
            run_retry_backoff: Duration::from_millis(1),
            ..Default::default()
        },
        Arc::new(StickyBalancedStrategy),
        None,
    );
    // Blackholed before the coordinator starts, so its very first
    // campaign fails: otherwise a campaign that slips through ends its
    // term by abdication, which is a different arm from the one under
    // test.
    proxy.set_blackholed(true);
    let cancel = CancellationToken::new();
    let token = cancel.clone();
    let running = tokio::spawn(async move { coordinator.run(token).await });

    // Counting attempts rather than waiting a fixed span, because a span
    // cannot tell "still trying" from "gave up quietly". Each failed
    // attempt opens one connection through the blackholed proxy, so the
    // threshold below is twelve of them.
    //
    // What this pins is narrower than it looks. A blackholed etcd fails
    // in `await_election_opening`, so these are observation failures:
    // they never reach the ending arm and never touch its counter. A
    // budget re-added there would leave this test green. What the twelve
    // rules out is a coordinator that stops retrying at all — which is
    // the half of the contract this path can speak to. The ending arm's
    // own pacing is pinned by the unit tests over `pace_after_ending`.
    let before = proxy.accepted();
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "more attempts than the budget that once passed this test",
        || {
            let seen = proxy.accepted().saturating_sub(before);
            async move { seen >= 12 }
        },
    )
    .await;
    assert!(
        !running.is_finished(),
        "an unreachable etcd must not make the coordinator give up"
    );

    cancel.cancel();
    tokio::time::timeout(WAIT_TIMEOUT, running)
        .await
        .expect("cancellation must stop the coordinator promptly")
        .expect("the coordinator task must not panic");
}

/// A standby drained while etcd is unreachable stops when asked, rather
/// than waiting out the transport.
///
/// Standing by means sitting inside one of two etcd calls almost all the
/// time, and the store sets no request timeout of its own — so unraced,
/// each runs to the transport's own bound, several times the graceful
/// shutdown budget this component is given. The lifecycle manager then
/// abandons it, and the work that would have followed a clean exit does
/// not happen.
#[tokio::test]
async fn a_standby_stops_promptly_when_etcd_is_dark() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-standby-cancel-{}/", uuid::Uuid::new_v4());
    // Connected and used while healthy: the failure under test is a call
    // that cannot complete, not a store that never opened.
    let store = store_at(&proxy.endpoint, &prefix).await;
    let lease_id = store.grant_lease(30).await.expect("grant");
    assert!(
        store
            .try_acquire_leadership("incumbent", lease_id)
            .await
            .expect("acquire"),
        "the test's own leader must take the key, so the candidate stands by"
    );

    let standby = Arc::new(Coordinator::new(
        Arc::clone(&store),
        CoordinatorConfig {
            name: "cancelled-standby".to_string(),
            // Far beyond the assertion window, so a fallback re-read can
            // never be what ends the wait.
            standby_poll_interval: Duration::from_secs(600),
            ..Default::default()
        },
        Arc::new(StickyBalancedStrategy),
        None,
    ));

    // Live connections cut, and new ones accepted but never answered, so
    // a caller must reconnect and then wait. A refused connection would
    // not do: that errors promptly, and an error is not the failure under
    // test.
    proxy.set_hanging(true);
    proxy.sever();
    // The severed connection reports a broken pipe promptly the first
    // time or two. Drain that here, so the call under test is one that
    // opens a fresh connection and gets no answer — confirmed by a probe
    // that fails to complete rather than by assuming a fixed number.
    let mut hanging = false;
    for _ in 0..5 {
        if tokio::time::timeout(Duration::from_millis(200), store.get_leader_with_revision())
            .await
            .is_err()
        {
            hanging = true;
            break;
        }
    }
    assert!(
        hanging,
        "the proxy must reach a state where an etcd call gets no answer"
    );

    let cancel = CancellationToken::new();
    let token = cancel.clone();
    let waiting = tokio::spawn(async move { standby.await_election_opening(&token).await });

    // Long enough to be inside the call, short enough that the assertion
    // window below is still well under the transport's own bound.
    tokio::time::sleep(Duration::from_millis(300)).await;
    cancel.cancel();
    tokio::time::timeout(Duration::from_secs(2), waiting)
        .await
        .expect("a cancelled standby must not wait out the transport")
        .expect("the standby task must not panic")
        .expect("cancellation is not an error");
}

/// A standby whose watch is severed still takes an open election at
/// the next fallback deadline.
///
/// A lost watch waits out its window and then re-reads rather than
/// trusting the stream further. The proxy severs the live connection
/// so the stream errors while etcd itself stays healthy for the
/// re-read; a loss path that wedged on the dead stream, or surfaced it
/// as a run failure, fails the bound here.
#[tokio::test]
async fn a_standby_with_a_severed_watch_still_takes_an_open_election() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-severed-watch-{}/", uuid::Uuid::new_v4());
    let direct = store_at(ETCD_ENDPOINT, &prefix).await;
    let watched = store_at(&proxy.endpoint, &prefix).await;

    let lease_id = direct.grant_lease(60).await.expect("lease");
    assert!(
        direct
            .try_acquire_leadership("incumbent", lease_id)
            .await
            .expect("acquire"),
        "the test's own leader must take the key"
    );

    let standby = Coordinator::new(
        Arc::clone(&watched),
        CoordinatorConfig {
            name: "severed-standby".to_string(),
            standby_poll_interval: Duration::from_secs(2),
            ..Default::default()
        },
        Arc::new(StickyBalancedStrategy),
        None,
    );
    let cancel = CancellationToken::new();
    let waiting = {
        let cancel = cancel.clone();
        tokio::spawn(async move { standby.await_election_opening(&cancel).await })
    };

    // Let the standby read and establish its watch, then cut it and
    // open the election. Only a re-read can observe the opening: the
    // severed watch is gone, and its successor is created only after
    // the re-read below runs.
    tokio::time::sleep(Duration::from_millis(500)).await;
    proxy.sever();
    tokio::time::sleep(Duration::from_millis(300)).await;
    direct
        .revoke_lease(lease_id)
        .await
        .expect("depose incumbent");

    // The lost watch waits out its ~2s window, re-reads, and finds the
    // election open — well inside this bound.
    tokio::time::timeout(Duration::from_secs(5), waiting)
        .await
        .expect("a standby with a severed watch must re-read at its deadline")
        .expect("the standby task must not panic")
        .expect("an open election is not an error");
}

/// A pod asked to shut down while etcd hangs exits inside its bounds
/// instead of waiting out the transport.
///
/// The graceful path's etcd calls — the drain's bookkeeping and the
/// final revoke — are each bounded, and this is what the bounds buy: a
/// store that accepts connections and answers nothing (the silent
/// partition, not the fast error) cannot hold the teardown past the
/// budget the lifecycle manager gives it. The lease TTL is 30s here so
/// the keepalive margin (20s) cannot preempt the path under test: with
/// the bounds the teardown finishes well before it; without them the
/// setup call alone would hang to the margin, which is what the
/// assertion window excludes.
#[tokio::test]
async fn a_pod_asked_to_stop_while_etcd_hangs_exits_inside_its_bounds() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-pod-teardown-{}/", uuid::Uuid::new_v4());
    let store = store_at(&proxy.endpoint, &prefix).await;
    let cancel = CancellationToken::new();

    let mut pod = start_pod_with_lease_ttl(Arc::clone(&store), "teardown-pod", 30, cancel.clone());
    let check = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check);
        async move {
            store
                .list_pods()
                .await
                .map(|pods| pods.iter().any(|p| p.pod_name == "teardown-pod"))
                .unwrap_or(false)
        }
    })
    .await;

    proxy.set_hanging(true);
    proxy.sever();
    // The severed connection errors fast once or twice before the
    // channel re-establishes onto a parked socket; a call that fails
    // fast never exercises the bounds under test. The pod shares this
    // store's channel, so probing until a call hangs puts its calls in
    // the same state.
    let mut hanging = false;
    for _ in 0..5 {
        if tokio::time::timeout(Duration::from_millis(200), store.list_pods())
            .await
            .is_err()
        {
            hanging = true;
            break;
        }
    }
    assert!(hanging, "the store must reach a state where calls hang");
    cancel.cancel();

    // Setup bound (5s) + fence (prompt: nothing held) + heartbeat join
    // (one round, ≤10s) + revoke bound (5s), with slack — far under the
    // ~20s the unbounded setup alone would take to reach the margin.
    let join = pod.join_handle.take().expect("join handle");
    tokio::time::timeout(Duration::from_secs(17), join)
        .await
        .expect("a hung etcd must not hold the pod's shutdown past its bounds")
        .expect("the pod task must not panic")
        .expect("a cancelled run is not an error");
}

/// A router asked to shut down while etcd hangs exits inside its bounds.
///
/// The teardown's one etcd call — the deregistration revoke — is
/// bounded, and the drain-lane joins race cancellation, so the whole
/// exit is prompt against a store that answers nothing.
#[tokio::test]
async fn a_router_asked_to_stop_while_etcd_hangs_exits_inside_its_bounds() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-router-teardown-{}/", uuid::Uuid::new_v4());
    let store = store_at(&proxy.endpoint, &prefix).await;
    let cancel = CancellationToken::new();

    let mut router =
        start_router_with_lease_ttl(Arc::clone(&store), "teardown-router", 30, cancel.clone());
    let check = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check);
        async move {
            store
                .list_routers()
                .await
                .map(|routers| routers.iter().any(|r| r.router_name == "teardown-router"))
                .unwrap_or(false)
        }
    })
    .await;

    proxy.set_hanging(true);
    proxy.sever();
    // As in the pod test above: fast failures on the severed connection
    // are drained until a call genuinely hangs, so the teardown's revoke
    // meets the failure under test rather than a prompt error.
    let mut hanging = false;
    for _ in 0..5 {
        if tokio::time::timeout(Duration::from_millis(200), store.list_routers())
            .await
            .is_err()
        {
            hanging = true;
            break;
        }
    }
    assert!(hanging, "the store must reach a state where calls hang");
    cancel.cancel();

    // Lane joins race cancellation; the heartbeat join is bounded by
    // one keepalive round (≤10s at this test's 30s TTL); the revoke is
    // bounded at 2s. An unbounded revoke, by contrast, waits out the
    // hang indefinitely — which is what the window refutes.
    let join = router.join_handle.take().expect("join handle");
    let outcome = tokio::time::timeout(Duration::from_secs(15), join)
        .await
        .expect("a hung etcd must not hold the router's shutdown past its bounds")
        .expect("the router task must not panic");
    // Ok or Err are both legitimate endings here: cancellation racing an
    // attempt that the severed stream already failed may surface the
    // store error. The bound is what this test holds, not the exit code.
    drop(outcome);
}

/// A recorded membership narrows the freeze requirement to its members —
/// a registered router outside it must not hold the freeze.
///
/// This is the direction nothing else pins. Every other quorum test
/// either injects the membership straight into the predicate or parks
/// its handoff where the fallback and the membership are
/// indistinguishable, so a resolution that silently degraded to
/// "require every live router" — the safe-but-wasteful direction — would
/// leave the whole suite green while every freeze in production waited
/// on routers its plan deliberately excluded.
#[tokio::test]
async fn a_recorded_membership_advances_past_a_router_outside_it() {
    let store = test_store("membership-narrows").await;
    let cancel = CancellationToken::new();

    // Two live routers, but the membership names only one of them: the
    // other joined after the plan, so its ack must be neither obtainable
    // nor required.
    for router in ["r-member", "r-outsider"] {
        let lease = store.grant_lease(60).await.expect("lease");
        store
            .register_router(
                &RegisteredRouter {
                    router_name: router.to_string(),
                    registered_at: 0,
                    last_heartbeat: 0,
                },
                lease,
            )
            .await
            .expect("register router");
    }
    store
        .inner()
        .put(
            &format!("{}freeze_quorums/narrow-membership", store.inner().prefix()),
            &vec!["r-member".to_string()],
            None,
        )
        .await
        .expect("write membership");

    let _coord = start_coordinator_reconcile_parked(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    let handoff = HandoffState {
        partition: 0,
        old_owner: Some("pod-old".to_string()),
        new_owner: "pod-new".to_string(),
        new_owner_address: None,
        phase: HandoffPhase::Freezing,
        started_at: 0,
        handoff_id: "narrowed-handoff".to_string(),
        freeze_quorum: None,
        freeze_quorum_ref: Some("narrow-membership".to_string()),
        created_at_ms: 0,
        phase_entered_at_ms: 0,
    };
    store.put_handoff(&handoff).await.expect("write handoff");
    store
        .put_freeze_ack(&RouterFreezeAck {
            router_name: "r-member".to_string(),
            partition: 0,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: "narrowed-handoff".to_string(),
        })
        .await
        .expect("write ack");

    // The member's ack alone must advance the freeze while the outsider
    // stays registered and silent. A resolution degraded to the
    // require-everybody fallback parks here forever.
    let check_store = Arc::clone(&store);
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "the membership's one ack to advance the freeze",
        || {
            let store = Arc::clone(&check_store);
            async move {
                store
                    .get_handoff(0)
                    .await
                    .ok()
                    .flatten()
                    .is_some_and(|h| h.phase != HandoffPhase::Freezing)
            }
        },
    )
    .await;

    cancel.cancel();
}

/// A coordinator whose terms keep ending badly keeps campaigning — there
/// is no budget on endings.
///
/// The blackholed-proxy test cannot pin this: a candidate that cannot
/// reach etcd fails to observe the election, which retries on the
/// standby interval and never touches the ending arm. Here every ending
/// is real — the term's lease is revoked out from under it — and the
/// candidate must take the election back each time. Three consecutive
/// endings inside one decay window rule out a budget of three or fewer
/// on the arm the removed escalation used to live in; the honest limit
/// of this shape is that a larger budget would still pass.
#[tokio::test]
async fn a_coordinator_keeps_campaigning_through_repeated_term_endings() {
    let store = test_store("endings-no-budget").await;
    let cancel = CancellationToken::new();

    let _coord = start_coordinator_reconcile_parked(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    let mut deposed = Vec::new();
    for round in 1..=3 {
        let check_store = Arc::clone(&store);
        let already = deposed.clone();
        wait_for_condition_named(
            WAIT_TIMEOUT,
            POLL_INTERVAL,
            "a fresh term to hold the election",
            || {
                let store = Arc::clone(&check_store);
                let already = already.clone();
                async move {
                    store
                        .get_leader()
                        .await
                        .ok()
                        .flatten()
                        .is_some_and(|leader| !already.contains(&leader.lease_id))
                }
            },
        )
        .await;
        let leader = store
            .get_leader()
            .await
            .expect("read leader")
            .expect("a leader holds the election");
        deposed.push(leader.lease_id);
        // End the term from outside: the keepalive sees TTL 0 on its
        // next round and the coordinator abdicates — the ending arm,
        // not the observation arm.
        store
            .revoke_lease(leader.lease_id)
            .await
            .unwrap_or_else(|_| panic!("revoke the round-{round} lease"));
    }

    // After the third deposition it must still come back.
    let check_store = Arc::clone(&store);
    wait_for_condition_named(
        WAIT_TIMEOUT,
        POLL_INTERVAL,
        "a fourth term after three consecutive endings",
        || {
            let store = Arc::clone(&check_store);
            let deposed = deposed.clone();
            async move {
                store
                    .get_leader()
                    .await
                    .ok()
                    .flatten()
                    .is_some_and(|leader| !deposed.contains(&leader.lease_id))
            }
        },
    )
    .await;

    cancel.cancel();
}

/// A membership the cache has learned is absent still requires every
/// live router, and does not read as "requires nobody".
///
/// Those are one `Option` apart and sit on opposite sides of the safety
/// rule: absent means unknown, which widens the requirement, while an
/// empty membership is a real snapshot that narrows it to nobody.
/// Caching the second in place of the first would advance a handoff out
/// of Freezing before any router had stopped routing to the old owner —
/// and it would do so on the second resolution, not the first, so a test
/// that resolves once would not see it.
#[tokio::test]
async fn a_cached_absent_membership_still_requires_every_live_router() {
    let store = test_store("freeze-quorum-cached-absence").await;

    let handoff = HandoffState {
        partition: 0,
        old_owner: Some("pod-old".to_string()),
        new_owner: "pod-new".to_string(),
        new_owner_address: None,
        phase: HandoffPhase::Freezing,
        started_at: 0,
        handoff_id: "handoff-cached-absence".to_string(),
        freeze_quorum: None,
        freeze_quorum_ref: Some("never-written".to_string()),
        created_at_ms: 0,
        phase_entered_at_ms: 0,
    };

    let routers = [
        RegisteredRouter {
            router_name: "router-0".to_string(),
            registered_at: 0,
            last_heartbeat: 0,
        },
        RegisteredRouter {
            router_name: "router-1".to_string(),
            registered_at: 0,
            last_heartbeat: 0,
        },
    ];
    let acks = [RouterFreezeAck {
        router_name: "router-0".to_string(),
        partition: 0,
        acked_at: 0,
        acked_at_ms: 0,
        handoff_id: handoff.handoff_id.clone(),
    }];

    // Resolve twice: absence is never cached, so both are reads — and
    // both must say the same thing.
    for pass in 1..=2 {
        let quorum = store
            .resolve_freeze_quorum(&handoff)
            .await
            .expect("resolving must not error");
        assert!(
            quorum.is_none(),
            "pass {pass}: an absent record must stay unknown, not become an empty membership"
        );
        assert!(
            !freeze_quorum_met(&routers, &acks, &handoff, quorum.as_deref()),
            "pass {pass}: one ack of two live routers must not satisfy an absent membership"
        );
    }
}

/// A batch of freeze acks lands every key, across the transaction
/// chunk boundary.
///
/// Acks are written in chunks of at most 128 ops — etcd's default
/// transaction ceiling — so the regression worth pinning is the tail:
/// a batch one chunk past the boundary that quietly drops its last
/// chunk leaves quorum members unacked and every affected freeze
/// parked at its deadline.
#[tokio::test]
async fn a_freeze_ack_batch_lands_every_key_across_the_chunk_boundary() {
    let prefix = format!("/test-ack-batch-{}/", uuid::Uuid::new_v4());
    let store = store_at(ETCD_ENDPOINT, &prefix).await;

    let acks: Vec<RouterFreezeAck> = (0u32..130)
        .map(|partition| RouterFreezeAck {
            router_name: "batch-router".to_string(),
            partition,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: format!("h-{partition}"),
        })
        .collect();
    store
        .put_freeze_acks(&acks, 128)
        .await
        .expect("batch write");

    for partition in [0u32, 127, 128, 129] {
        let listed = store.list_freeze_acks(partition).await.expect("list acks");
        assert_eq!(listed.len(), 1, "partition {partition} must carry its ack");
        assert_eq!(listed[0].handoff_id, format!("h-{partition}"));
        assert!(
            listed[0].acked_at_ms > 0,
            "the store stamps the batch's clock"
        );
    }

    // An empty batch is a no-op, not an error.
    store.put_freeze_acks(&[], 128).await.expect("empty batch");
}

/// A membership already read is answered from memory, not read again.
///
/// This is the whole point of holding it: every frozen partition of one
/// plan shares an id, so resolving per handoff per reconcile pass is the
/// read the cache exists to remove. Nothing else pins that it caches at
/// all — the absence test passes just as well against a store that
/// re-reads every time.
///
/// Deleting the record behind the cache is what makes the difference
/// observable: a re-read would find nothing and widen the requirement,
/// so still getting the membership proves it came from memory.
#[tokio::test]
async fn a_membership_already_read_is_answered_without_reading_again() {
    let store = test_store("freeze-quorum-cache-hit").await;

    let id = "cached-membership";
    let members = vec!["router-0".to_string(), "router-1".to_string()];
    store
        .inner()
        .put(
            &format!("{}freeze_quorums/{id}", store.inner().prefix()),
            &members,
            None,
        )
        .await
        .expect("write the membership");

    let handoff = HandoffState {
        partition: 0,
        old_owner: Some("pod-old".to_string()),
        new_owner: "pod-new".to_string(),
        new_owner_address: None,
        phase: HandoffPhase::Freezing,
        started_at: 0,
        handoff_id: "handoff-cache-hit".to_string(),
        freeze_quorum: None,
        freeze_quorum_ref: Some(id.to_string()),
        created_at_ms: 0,
        phase_entered_at_ms: 0,
    };

    assert_eq!(
        store
            .resolve_freeze_quorum(&handoff)
            .await
            .expect("first resolution"),
        Some(members.clone()),
        "the first resolution reads the record"
    );

    let (_, mod_revision) = store
        .list_freeze_quorum_ids()
        .await
        .expect("list memberships")
        .into_iter()
        .find(|(listed, _)| listed == id)
        .expect("the membership is listed");
    assert!(store
        .delete_freeze_quorum_if_unchanged(id, mod_revision)
        .await
        .expect("delete the membership"));
    assert!(
        store
            .get_freeze_quorum(id)
            .await
            .expect("read after delete")
            .is_none(),
        "the record must really be gone from etcd"
    );

    assert_eq!(
        store
            .resolve_freeze_quorum(&handoff)
            .await
            .expect("second resolution"),
        Some(members),
        "the second resolution must come from memory, not from etcd"
    );
}

// ── Plan chunking against the server txn budget ─────────────────────

/// The 256→1 collapse shape: a plan of 256 creations carries two
/// compares per partition, quadruple etcd's default `--max-txn-ops` of
/// 128 (which this suite's etcd runs). Unchunked, the server rejects
/// the transaction outright — a hard error, not a failed guard — and a
/// coordinator retrying the same plan re-earns it forever, with every
/// partition unassigned. Chunked to the budget, every handoff lands.
#[tokio::test]
async fn a_plan_past_the_server_txn_budget_still_applies() {
    use personhog_coordination::types::AssignmentPrecondition;

    let store = test_store("plan-past-txn-budget").await;
    let total: u32 = 256;

    let quorum_id = "large-plan-quorum";
    let quorum = vec!["router-0".to_string()];
    let now = 1_000_i64;
    let handoffs: Vec<HandoffState> = (0..total)
        .map(|partition| HandoffState {
            partition,
            old_owner: Some(format!("pod-{partition}")),
            new_owner: "pod-survivor".to_string(),
            new_owner_address: None,
            phase: HandoffPhase::Freezing,
            started_at: now,
            handoff_id: format!("handoff-{partition}"),
            freeze_quorum: None,
            freeze_quorum_ref: Some(quorum_id.to_string()),
            created_at_ms: now * 1000,
            phase_entered_at_ms: now * 1000,
        })
        .collect();
    let preconditions: Vec<AssignmentPrecondition> = (0..total)
        .map(|partition| AssignmentPrecondition::Absent { partition })
        .collect();

    let application = store
        .apply_plan(
            &[],
            &handoffs,
            &[],
            &preconditions,
            Some((quorum_id, &quorum)),
            128,
        )
        .await
        .expect("a plan larger than the server txn budget must apply in chunks");

    assert_eq!(application.applied.len(), total as usize);
    assert!(application.conflicted.is_empty());
    let written = store.list_handoffs().await.unwrap();
    assert_eq!(
        written.len(),
        total as usize,
        "every handoff must be durable"
    );
    assert_eq!(
        store.get_freeze_quorum(quorum_id).await.unwrap().as_deref(),
        Some(quorum.as_slice()),
        "the shared quorum record must be durable alongside its handoffs"
    );
}

/// Guards keep their bite across chunks: a partition whose handoff key
/// already exists stands down alone, without dragging the rest of its
/// chunk — or the plan — with it.
#[tokio::test]
async fn a_conflicted_partition_stands_down_alone() {
    use personhog_coordination::types::AssignmentPrecondition;

    let store = test_store("plan-conflict-isolated").await;
    let total: u32 = 100;

    let make = |partition: u32, id: &str| HandoffState {
        partition,
        old_owner: None,
        new_owner: "pod-survivor".to_string(),
        new_owner_address: None,
        phase: HandoffPhase::Freezing,
        started_at: 1_000,
        handoff_id: id.to_string(),
        freeze_quorum: Some(Vec::new()),
        freeze_quorum_ref: None,
        created_at_ms: 1_000_000,
        phase_entered_at_ms: 1_000_000,
    };

    // Partition 40 already has a handoff — a concurrent planner won it.
    let winner = make(40, "handoff-winner");
    let first = store
        .apply_plan(&[], std::slice::from_ref(&winner), &[], &[], None, 128)
        .await
        .unwrap();
    assert_eq!(first.applied, vec![40]);

    let handoffs: Vec<HandoffState> = (0..total)
        .map(|p| make(p, &format!("handoff-{p}")))
        .collect();
    let preconditions: Vec<AssignmentPrecondition> = (0..total)
        .map(|partition| AssignmentPrecondition::Absent { partition })
        .collect();
    let application = store
        .apply_plan(&[], &handoffs, &[], &preconditions, None, 128)
        .await
        .unwrap();

    assert_eq!(
        application.conflicted,
        vec![40],
        "only the won partition stands down"
    );
    assert_eq!(application.applied.len(), (total - 1) as usize);
    let ids: HashMap<u32, String> = store
        .list_handoffs()
        .await
        .unwrap()
        .into_iter()
        .map(|h| (h.partition, h.handoff_id))
        .collect();
    assert_eq!(
        ids[&40], "handoff-winner",
        "the winner's record must survive"
    );
    assert_eq!(ids.len(), total as usize);
}

/// The stale-quorum sweep's delete is guarded on the revision it listed:
/// a chunked plan re-puts its record with every chunk, and a re-put
/// after the sweep's read must win — otherwise the sweep collects a
/// record the chunk it never saw still references.
#[tokio::test]
async fn a_swept_quorum_delete_loses_to_a_concurrent_re_put() {
    use personhog_coordination::types::AssignmentPrecondition;

    let store = test_store("quorum-sweep-guarded").await;
    let quorum_id = "shared-quorum";
    let quorum = vec!["router-0".to_string()];
    let handoff = |partition: u32| HandoffState {
        partition,
        old_owner: None,
        new_owner: "pod-new".to_string(),
        new_owner_address: None,
        phase: HandoffPhase::Freezing,
        started_at: 0,
        handoff_id: format!("handoff-{partition}"),
        freeze_quorum: None,
        freeze_quorum_ref: Some(quorum_id.to_string()),
        created_at_ms: 0,
        phase_entered_at_ms: 0,
    };
    let listed_revision = |store: Arc<personhog_coordination::store::PersonhogStore>| async move {
        store
            .list_freeze_quorum_ids()
            .await
            .unwrap()
            .into_iter()
            .find(|(id, _)| id == quorum_id)
            .map(|(_, rev)| rev)
    };

    // The sweep's read: the first chunk wrote the record.
    store
        .apply_plan(
            &[],
            &[handoff(0)],
            &[],
            &[AssignmentPrecondition::Absent { partition: 0 }],
            Some((quorum_id, &quorum)),
            128,
        )
        .await
        .unwrap();
    let swept = listed_revision(Arc::clone(&store)).await.expect("listed");

    // A later chunk re-puts it before the sweep deletes.
    store
        .apply_plan(
            &[],
            &[handoff(1)],
            &[],
            &[AssignmentPrecondition::Absent { partition: 1 }],
            Some((quorum_id, &quorum)),
            128,
        )
        .await
        .unwrap();

    assert!(
        !store
            .delete_freeze_quorum_if_unchanged(quorum_id, swept)
            .await
            .unwrap(),
        "a delete guarded on the pre-chunk revision must lose"
    );
    assert_eq!(
        store.get_freeze_quorum(quorum_id).await.unwrap(),
        Some(quorum.clone()),
        "the record the later chunk references must survive"
    );

    let current = listed_revision(Arc::clone(&store)).await.expect("listed");
    assert!(
        store
            .delete_freeze_quorum_if_unchanged(quorum_id, current)
            .await
            .unwrap(),
        "a delete guarded on the current revision applies"
    );
}

/// A missing membership record is not remembered as missing: a chunked
/// plan can re-create a swept record, and a pinned absence would hold
/// every later resolution on the every-live-router fallback.
#[tokio::test]
async fn a_missing_membership_is_resolved_again_once_written() {
    use personhog_coordination::types::AssignmentPrecondition;

    let store = test_store("quorum-absence-not-cached").await;
    let quorum_id = "late-written";
    let quorum = vec!["router-0".to_string()];
    let handoff = HandoffState {
        partition: 0,
        old_owner: None,
        new_owner: "pod-new".to_string(),
        new_owner_address: None,
        phase: HandoffPhase::Freezing,
        started_at: 0,
        handoff_id: "handoff-late".to_string(),
        freeze_quorum: None,
        freeze_quorum_ref: Some(quorum_id.to_string()),
        created_at_ms: 0,
        phase_entered_at_ms: 0,
    };

    assert!(store
        .resolve_freeze_quorum(&handoff)
        .await
        .unwrap()
        .is_none());

    store
        .apply_plan(
            &[],
            std::slice::from_ref(&handoff),
            &[],
            &[AssignmentPrecondition::Absent { partition: 0 }],
            Some((quorum_id, &quorum)),
            128,
        )
        .await
        .unwrap();

    assert_eq!(
        store.resolve_freeze_quorum(&handoff).await.unwrap(),
        Some(quorum),
        "a record written after a miss must resolve on the next look"
    );
}

/// A configured budget above the server's live `--max-txn-ops` (values
/// drift, a member not yet restarted with the raised flag) must degrade
/// to per-partition transactions rather than hand the planner a
/// rejection it would retry forever.
#[tokio::test]
async fn an_over_server_budget_chunk_degrades_to_per_unit_transactions() {
    use personhog_coordination::types::AssignmentPrecondition;

    let store = test_store("plan-over-server-budget").await;
    let total: u32 = 100;
    let handoffs: Vec<HandoffState> = (0..total)
        .map(|partition| HandoffState {
            partition,
            old_owner: None,
            new_owner: "pod-survivor".to_string(),
            new_owner_address: None,
            phase: HandoffPhase::Freezing,
            started_at: 0,
            handoff_id: format!("handoff-{partition}"),
            freeze_quorum: Some(Vec::new()),
            freeze_quorum_ref: None,
            created_at_ms: 0,
            phase_entered_at_ms: 0,
        })
        .collect();
    let preconditions: Vec<AssignmentPrecondition> = (0..total)
        .map(|partition| AssignmentPrecondition::Absent { partition })
        .collect();

    // 200 compares in one chunk against the suite's default-limits etcd.
    let application = store
        .apply_plan(&[], &handoffs, &[], &preconditions, None, 100_000)
        .await
        .expect("an over-budget chunk must fall back, not fail");

    assert_eq!(
        application.over_budget_chunks, 1,
        "the server must have refused the single chunk, or this test pins nothing"
    );
    assert_eq!(application.applied.len(), total as usize);
    assert!(application.conflicted.is_empty());
    assert_eq!(store.list_handoffs().await.unwrap().len(), total as usize);
}
