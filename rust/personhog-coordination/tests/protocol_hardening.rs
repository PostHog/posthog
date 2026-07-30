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
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{Mutex, RwLock};
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use async_trait::async_trait;
use common::{
    revoke_lease_of_key, start_coordinator, start_coordinator_named, start_pod, start_pod_gated,
    start_pod_with_lease_ttl, start_router_with_lease_ttl, test_store, test_store_with_prefix,
    wait_for_condition, CutoverEvent, HandoffEvent, MockCutoverHandler, POLL_INTERVAL,
    WAIT_TIMEOUT,
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
