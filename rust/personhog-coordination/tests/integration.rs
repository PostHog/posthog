mod common;

use std::sync::Arc;

use tokio_util::sync::CancellationToken;

use std::time::Duration;

use common::{
    start_coordinator, start_coordinator_named, start_coordinator_with_debounce, start_pod,
    start_pod_blocking, start_pod_slow, start_pod_with_lease_ttl, start_router, test_store,
    wait_for_condition, HandoffEvent, PodHandles, POLL_INTERVAL, WAIT_TIMEOUT,
};
use personhog_coordination::strategy::{
    AssignmentStrategy, JumpHashStrategy, StickyBalancedStrategy,
};

const NUM_PARTITIONS: u32 = 8;
const MANY_PARTITIONS: u32 = 12;

/// Generates `#[tokio::test]` functions for each strategy variant.
/// Each test runs inside a `sticky_balanced` or `jump_hash` module.
///
/// Test functions receive `(test_name, strategy, evenly_distributed)` where
/// `evenly_distributed` indicates whether the strategy guarantees perfectly
/// balanced partition counts across pods.
macro_rules! strategy_tests {
    ($( $(#[$meta:meta])* $name:ident ),* $(,)?) => {
        mod sticky_balanced {
            use super::*;
            $(
                $(#[$meta])*
                #[tokio::test]
                async fn $name() {
                    super::$name(
                        concat!(stringify!($name), "-sticky"),
                        Arc::new(StickyBalancedStrategy),
                        true,
                    ).await;
                }
            )*
        }

        mod jump_hash {
            use super::*;
            $(
                $(#[$meta])*
                #[tokio::test]
                async fn $name() {
                    super::$name(
                        concat!(stringify!($name), "-jump"),
                        Arc::new(JumpHashStrategy),
                        false,
                    ).await;
                }
            )*
        }
    };
}

// Add tests here in order to test them for each strategy variant.
strategy_tests! {
    single_pod_gets_all_partitions,
    scale_up_triggers_handoff,
    pod_crash_reassigns_partitions,
    leader_failover,
    multi_router_ack_quorum,
    pod_crash_during_warming_restores_assignments,
    scale_down_to_one_pod,
    rapid_pod_joins,
    rolling_update,
    coordinator_starts_after_pods,
    debounce_batches_rapid_pod_changes,
    graceful_drain_transfers_partitions,
}

async fn single_pod_gets_all_partitions(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _pod = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for the full bootstrap to settle: assignments written AND
    // handoffs cleaned up. Under the unified protocol, initial assignments
    // also go through a handoff cycle that finishes by deleting the
    // handoff record.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-0")
                && handoffs.is_empty()
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);
    for a in &assignments {
        assert_eq!(a.owner, "writer-0");
    }

    let handoffs = store.list_handoffs().await.unwrap();
    assert!(handoffs.is_empty());

    cancel.cancel();
}

async fn scale_up_triggers_handoff(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Start coordinator, one pod, and one router
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());
    let router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Wait for initial assignment: all partitions to writer-0
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-0")
        }
    })
    .await;

    // Add a second pod — triggers rebalance
    let pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());

    // Wait for assignments to be split between both pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let has_pod0 = assignments.iter().any(|a| a.owner == "writer-0");
            let has_pod1 = assignments.iter().any(|a| a.owner == "writer-1");
            assignments.len() == NUM_PARTITIONS as usize && has_pod0 && has_pod1
        }
    })
    .await;

    // Wait for all handoffs to complete (deleted from etcd)
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Verify: pod1 warmed the partitions it received
    let pod1_events = pod1.events.lock().await;
    let warmed: Vec<u32> = pod1_events
        .iter()
        .filter_map(|e| match e {
            HandoffEvent::Warmed(p) => Some(*p),
            _ => None,
        })
        .collect();
    assert!(
        !warmed.is_empty(),
        "pod1 should have warmed at least one partition"
    );

    // Verify: pod0 released the partitions that moved away
    let pod0_events = pod0.events.lock().await;
    let released: Vec<u32> = pod0_events
        .iter()
        .filter_map(|e| match e {
            HandoffEvent::Released(p) => Some(*p),
            _ => None,
        })
        .collect();
    assert!(
        !released.is_empty(),
        "pod0 should have released at least one partition"
    );

    // Verify: router executed cutovers
    let router_events = router.events.lock().await;
    assert!(
        !router_events.is_empty(),
        "router should have executed at least one cutover"
    );

    // Under the unified protocol, the router observes handoff events for
    // both the initial assignment (new_owner=writer-0) and the subsequent
    // reassignment (new_owner=writer-1). All targets must be a known live
    // pod; we just need to see at least one cutover involving writer-1 to
    // prove the scale-up reassignment actually happened.
    let saw_writer1_target = router_events.iter().any(|e| match e {
        common::CutoverEvent::StashBegan { new_owner, .. } => new_owner == "writer-1",
        common::CutoverEvent::StashDrained { target, .. } => target == "writer-1",
    });
    assert!(
        saw_writer1_target,
        "router should have observed at least one cutover targeting writer-1"
    );
    for event in router_events.iter() {
        match event {
            common::CutoverEvent::StashBegan { new_owner, .. } => {
                assert!(
                    new_owner == "writer-0" || new_owner == "writer-1",
                    "stash-began target should be a known pod, got {new_owner}"
                );
            }
            common::CutoverEvent::StashDrained { target, .. } => {
                assert!(
                    target == "writer-0" || target == "writer-1",
                    "stash-drained target should be a known pod, got {target}"
                );
            }
        }
    }

    // Router's internal routing table should match etcd assignments
    let final_assignments = store.list_assignments().await.unwrap();
    let expected: std::collections::HashMap<u32, String> = final_assignments
        .iter()
        .map(|a| (a.partition, a.owner.clone()))
        .collect();
    let router_table = router.table.read().await;
    assert_eq!(
        *router_table, expected,
        "router routing table should match etcd assignments"
    );

    cancel.cancel();
}

async fn pod_crash_reassigns_partitions(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Start coordinator and two pods (short lease so crash is detected fast)
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Use a short lease for pod0 so crash is detected quickly
    let pod0_cancel = CancellationToken::new();
    let _pod0 = start_pod_with_lease_ttl(Arc::clone(&store), "writer-0", 2, pod0_cancel.clone());
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());

    // Wait for balanced assignment across both pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let has_both = assignments.iter().any(|a| a.owner == "writer-0")
                && assignments.iter().any(|a| a.owner == "writer-1");
            assignments.len() == NUM_PARTITIONS as usize && has_both
        }
    })
    .await;

    // Wait for handoffs from initial rebalance to settle
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Kill pod0 — its lease will expire and keys will be deleted
    pod0_cancel.cancel();

    // Wait for the pod registration to disappear (lease expiry)
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            pods.len() == 1 && pods[0].pod_name == "writer-1"
        }
    })
    .await;

    // Wait for all partitions to be reassigned to the surviving pod
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-1")
        }
    })
    .await;

    cancel.cancel();
}

async fn leader_failover(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Start coordinator-0 with short lease so failover is fast
    let leader_cancel = CancellationToken::new();
    let _leader = start_coordinator_named(
        Arc::clone(&store),
        "coordinator-0",
        2,
        Arc::clone(&strategy),
        leader_cancel.clone(),
    );

    // Start a pod and router
    let _pod = start_pod(Arc::clone(&store), "writer-0", cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Wait for coordinator-0 to become leader and write assignments
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let is_leader = store
                .get_leader()
                .await
                .ok()
                .flatten()
                .is_some_and(|l| l.holder == "coordinator-0");
            let has_assignments =
                store.list_assignments().await.unwrap_or_default().len() == NUM_PARTITIONS as usize;
            is_leader && has_assignments
        }
    })
    .await;

    // Now start the standby — coordinator-0 already holds the leader key
    let _standby = start_coordinator_named(
        Arc::clone(&store),
        "coordinator-1",
        10,
        strategy,
        cancel.clone(),
    );

    // Kill the leader
    leader_cancel.cancel();

    // Wait for the standby to win the election
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .get_leader()
                .await
                .ok()
                .flatten()
                .is_some_and(|l| l.holder == "coordinator-1")
        }
    })
    .await;

    // Add a second pod — the new leader must handle this
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());

    // Wait for rebalance across both pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let has_both = assignments.iter().any(|a| a.owner == "writer-0")
                && assignments.iter().any(|a| a.owner == "writer-1");
            assignments.len() == NUM_PARTITIONS as usize && has_both
        }
    })
    .await;

    cancel.cancel();
}

async fn multi_router_ack_quorum(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());
    let router0 = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let router1 = start_router(Arc::clone(&store), "router-1", cancel.clone());

    // Wait for initial assignment and both routers to register.
    // Routers must have their handoff watch streams active before any
    // handoffs are created, otherwise they miss the Ready event.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assigned =
                store.list_assignments().await.unwrap_or_default().len() == NUM_PARTITIONS as usize;
            let routers = store.list_routers().await.unwrap_or_default().len() == 2;
            assigned && routers
        }
    })
    .await;

    // Add second pod to trigger handoffs
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());

    // Wait for assignments to be split between both pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let has_pod0 = assignments.iter().any(|a| a.owner == "writer-0");
            let has_pod1 = assignments.iter().any(|a| a.owner == "writer-1");
            assignments.len() == NUM_PARTITIONS as usize && has_pod0 && has_pod1
        }
    })
    .await;

    // Wait for handoff cleanup to complete
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Both routers should have executed cutovers
    let r0_events = router0.events.lock().await;
    let r1_events = router1.events.lock().await;
    assert!(
        !r0_events.is_empty(),
        "router-0 should have executed cutovers"
    );
    assert!(
        !r1_events.is_empty(),
        "router-1 should have executed cutovers"
    );

    // Both routers should have cut over the same partitions
    fn event_partition(e: &common::CutoverEvent) -> u32 {
        match e {
            common::CutoverEvent::StashBegan { partition, .. }
            | common::CutoverEvent::StashDrained { partition, .. } => *partition,
        }
    }
    let r0_partitions: std::collections::HashSet<u32> =
        r0_events.iter().map(event_partition).collect();
    let r1_partitions: std::collections::HashSet<u32> =
        r1_events.iter().map(event_partition).collect();
    assert_eq!(r0_partitions, r1_partitions);

    // Both routers should have identical routing tables matching etcd assignments
    let final_assignments = store.list_assignments().await.unwrap();
    let expected: std::collections::HashMap<u32, String> = final_assignments
        .iter()
        .map(|a| (a.partition, a.owner.clone()))
        .collect();

    let r0_table = router0.table.read().await;
    let r1_table = router1.table.read().await;
    assert_eq!(
        *r0_table, expected,
        "router-0 routing table should match etcd assignments"
    );
    assert_eq!(
        *r1_table, expected,
        "router-1 routing table should match etcd assignments"
    );

    cancel.cancel();
}

async fn pod_crash_during_warming_restores_assignments(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(MANY_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Start 5 pods
    let mut pods: Vec<PodHandles> = Vec::new();
    for i in 0..5 {
        pods.push(start_pod(
            Arc::clone(&store),
            &format!("writer-{i}"),
            cancel.clone(),
        ));
    }

    // Wait for all partitions to be assigned across 5 pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            if assignments.len() != MANY_PARTITIONS as usize {
                return false;
            }
            // All 5 pods should have at least 1 partition
            (0..5).all(|i| {
                let name = format!("writer-{i}");
                assignments.iter().any(|a| a.owner == name)
            })
        }
    })
    .await;

    // Wait for any initial handoffs to settle
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Snapshot the stable assignments before adding the 6th pod
    let stable_assignments: std::collections::HashMap<u32, String> = store
        .list_assignments()
        .await
        .unwrap()
        .into_iter()
        .map(|a| (a.partition, a.owner))
        .collect();

    // Add a 6th pod with a blocking warm handler and short lease.
    // The blocking handler ensures the handoff stays at Warming when pod-5 dies.
    let pod5_cancel = CancellationToken::new();
    let _pod5 = start_pod_blocking(Arc::clone(&store), "writer-5", 2, pod5_cancel.clone());

    // Wait for writer-5 to register
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            store
                .list_pods()
                .await
                .unwrap_or_default()
                .iter()
                .any(|p| p.pod_name == "writer-5")
        }
    })
    .await;

    // Kill pod-5 immediately — it should still be in the Warming phase
    pod5_cancel.cancel();

    // Wait for writer-5's lease to expire
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            !store
                .list_pods()
                .await
                .unwrap_or_default()
                .iter()
                .any(|p| p.pod_name == "writer-5")
        }
    })
    .await;

    // Stale handoffs targeting the dead pod should be cleaned up
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Assignments should be back to the original 5-pod distribution
    let final_assignments: std::collections::HashMap<u32, String> = store
        .list_assignments()
        .await
        .unwrap()
        .into_iter()
        .map(|a| (a.partition, a.owner))
        .collect();

    assert_eq!(
        final_assignments, stable_assignments,
        "assignments should revert to pre-crash state"
    );

    // No partition should be owned by the dead pod
    assert!(
        !final_assignments.values().any(|v| v == "writer-5"),
        "dead pod should not own any partitions"
    );

    cancel.cancel();
}

async fn scale_down_to_one_pod(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(MANY_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Start 3 pods with short leases so crash detection is fast
    let pod0_cancel = CancellationToken::new();
    let _pod0 = start_pod_with_lease_ttl(Arc::clone(&store), "writer-0", 2, pod0_cancel.clone());
    let pod1_cancel = CancellationToken::new();
    let _pod1 = start_pod_with_lease_ttl(Arc::clone(&store), "writer-1", 2, pod1_cancel.clone());
    let _pod2 = start_pod(Arc::clone(&store), "writer-2", cancel.clone());

    // Wait for balanced assignment across all 3 pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == MANY_PARTITIONS as usize
                && ["writer-0", "writer-1", "writer-2"]
                    .iter()
                    .all(|name| assignments.iter().any(|a| a.owner == *name))
        }
    })
    .await;

    // Wait for initial handoffs to settle
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Kill pod-0
    pod0_cancel.cancel();

    // Wait for pod-0 to disappear and its partitions to move
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            !pods.iter().any(|p| p.pod_name == "writer-0")
                && assignments.len() == MANY_PARTITIONS as usize
                && !assignments.iter().any(|a| a.owner == "writer-0")
                && handoffs.is_empty()
        }
    })
    .await;

    // Kill pod-1
    pod1_cancel.cancel();

    // Wait for all partitions to converge to the sole survivor
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            pods.len() == 1
                && assignments.len() == MANY_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-2")
                && handoffs.is_empty()
        }
    })
    .await;

    cancel.cancel();
}

async fn rapid_pod_joins(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(MANY_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(Arc::clone(&store), Arc::clone(&strategy), cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Start with one pod and wait for it to get all partitions + router registered
    let _pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let routers = store.list_routers().await.unwrap_or_default();
            assignments.len() == MANY_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-0")
                && routers.len() == 1
        }
    })
    .await;

    // Rapidly add 3 more pods without waiting between them
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());
    let _pod2 = start_pod(Arc::clone(&store), "writer-2", cancel.clone());
    let _pod3 = start_pod(Arc::clone(&store), "writer-3", cancel.clone());

    let pod_names: Vec<String> = (0..4).map(|i| format!("writer-{i}")).collect();

    // Wait until the strategy is satisfied: all partitions assigned, no handoffs,
    // every pod owns partitions, and the strategy would make no further changes.
    let check_store = Arc::clone(&store);
    let check_strategy = Arc::clone(&strategy);
    let check_pods = pod_names.clone();
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        let strategy = Arc::clone(&check_strategy);
        let pods = check_pods.clone();
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            if assignments.len() != MANY_PARTITIONS as usize || !handoffs.is_empty() {
                return false;
            }
            let current: std::collections::HashMap<u32, String> = assignments
                .iter()
                .map(|a| (a.partition, a.owner.clone()))
                .collect();
            let desired = strategy.compute_assignments(&current, &pods, MANY_PARTITIONS);
            assignment_coordination::util::compute_required_handoffs(&current, &desired).is_empty()
        }
    })
    .await;

    // Verify every pod owns at least one partition
    let assignments = store.list_assignments().await.unwrap();
    for name in &pod_names {
        assert!(
            assignments.iter().any(|a| a.owner == *name),
            "{name} should own at least one partition"
        );
    }

    if evenly_distributed {
        let per_pod = MANY_PARTITIONS as usize / pod_names.len();
        for name in &pod_names {
            assert_eq!(
                assignments.iter().filter(|a| a.owner == *name).count(),
                per_pod,
                "expected even distribution for {name}"
            );
        }
    }

    cancel.cancel();
}

/// Simulates a Kubernetes rolling update: 3 old pods are replaced one at a time
/// by 3 new pods. Each time an old pod dies, a new pod spawns immediately.
///
/// Flow: start old-{0,1,2} -> for each i: new-i starts, old-i dies, new-(i+1) starts...
/// Final state: all partitions on new-{0,1,2}.
async fn rolling_update(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(MANY_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Start 3 "old generation" pods with short leases for fast crash detection
    let old_cancels: Vec<CancellationToken> = (0..3).map(|_| CancellationToken::new()).collect();
    let mut _old_pods: Vec<PodHandles> = Vec::new();
    for (i, old_cancel) in old_cancels.iter().enumerate() {
        _old_pods.push(start_pod_with_lease_ttl(
            Arc::clone(&store),
            &format!("old-{i}"),
            2,
            old_cancel.clone(),
        ));
    }

    // Wait for router to register and balanced assignment across all 3 old pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let routers = store.list_routers().await.unwrap_or_default();
            assignments.len() == MANY_PARTITIONS as usize
                && routers.len() == 1
                && (0..3).all(|i| {
                    let name = format!("old-{i}");
                    assignments.iter().any(|a| a.owner == name)
                })
        }
    })
    .await;

    // Wait for initial handoffs to settle
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Rolling replacement: for each old pod, start a new pod then kill the old one.
    // The next new pod spawns as soon as the old pod dies.
    let mut _new_pods: Vec<PodHandles> = Vec::new();
    for (i, old_cancel) in old_cancels.iter().enumerate() {
        // New pod comes up (temporarily 4 pods)
        _new_pods.push(start_pod(
            Arc::clone(&store),
            &format!("new-{i}"),
            cancel.clone(),
        ));

        // Wait for the new pod to register and handoffs from scale-up to settle
        let check_store = Arc::clone(&store);
        let new_name = format!("new-{i}");
        wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
            let store = Arc::clone(&check_store);
            let new_name = new_name.clone();
            async move {
                let pods = store.list_pods().await.unwrap_or_default();
                let handoffs = store.list_handoffs().await.unwrap_or_default();
                pods.iter().any(|p| p.pod_name == new_name) && handoffs.is_empty()
            }
        })
        .await;

        // Kill the old pod (back to 3 pods)
        old_cancel.cancel();

        // Wait for old pod lease to expire, reassignment, and handoffs to settle
        let check_store = Arc::clone(&store);
        let old_name = format!("old-{i}");
        wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
            let store = Arc::clone(&check_store);
            let old_name = old_name.clone();
            async move {
                let pods = store.list_pods().await.unwrap_or_default();
                let assignments = store.list_assignments().await.unwrap_or_default();
                let handoffs = store.list_handoffs().await.unwrap_or_default();
                !pods.iter().any(|p| p.pod_name == old_name)
                    && !assignments.iter().any(|a| a.owner == old_name)
                    && assignments.len() == MANY_PARTITIONS as usize
                    && handoffs.is_empty()
            }
        })
        .await;
    }

    // Final state: all partitions exclusively on new-{0,1,2}
    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), MANY_PARTITIONS as usize);

    let new_pod_names: std::collections::HashSet<&str> =
        ["new-0", "new-1", "new-2"].into_iter().collect();
    for a in &assignments {
        assert!(
            new_pod_names.contains(a.owner.as_str()),
            "partition {} owned by '{}', expected one of {:?}",
            a.partition,
            a.owner,
            new_pod_names,
        );
    }

    // No old pods should be registered
    let pods = store.list_pods().await.unwrap();
    assert_eq!(pods.len(), 3);
    for pod in &pods {
        assert!(
            pod.pod_name.starts_with("new-"),
            "expected only new pods, found '{}'",
            pod.pod_name,
        );
    }

    cancel.cancel();
}

async fn coordinator_starts_after_pods(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Start pods and router BEFORE the coordinator
    let _pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Wait for both pods and router to register
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            let routers = store.list_routers().await.unwrap_or_default();
            pods.len() == 2 && routers.len() == 1
        }
    })
    .await;

    // No assignments yet — nobody is coordinating
    let assignments = store.list_assignments().await.unwrap();
    assert!(
        assignments.is_empty(),
        "no coordinator means no assignments"
    );

    // Now start the coordinator — it should discover existing pods
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());

    // Wait for assignments to be split between both pods
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let has_pod0 = assignments.iter().any(|a| a.owner == "writer-0");
            let has_pod1 = assignments.iter().any(|a| a.owner == "writer-1");
            assignments.len() == NUM_PARTITIONS as usize
                && has_pod0
                && has_pod1
                && handoffs.is_empty()
        }
    })
    .await;

    cancel.cancel();
}

/// Tests that the debounce window batches rapid pod registrations into fewer
/// rebalances, and that the system converges correctly even when handoffs take
/// longer than the debounce interval.
///
/// Setup: 500ms debounce, 300ms warm delay per partition.
/// 1. Start pod-0, wait for all partitions assigned
/// 2. Rapidly add pod-1, pod-2, pod-3 (within debounce window)
/// 3. Verify convergence: all pods own partitions, no handoffs stuck
async fn debounce_batches_rapid_pod_changes(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(MANY_PARTITIONS).await.unwrap();

    let _coord = start_coordinator_with_debounce(
        Arc::clone(&store),
        Arc::clone(&strategy),
        Duration::from_millis(500),
        cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Pod-0 uses a slow handler: 300ms per partition warm
    let warm_delay = Duration::from_millis(300);
    let _pod0 = start_pod_slow(Arc::clone(&store), "writer-0", warm_delay, cancel.clone());

    // Wait for initial assignment + router registered
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let routers = store.list_routers().await.unwrap_or_default();
            assignments.len() == MANY_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-0")
                && routers.len() == 1
        }
    })
    .await;

    // Rapidly add 3 more slow pods — all within the 500ms debounce window
    let _pod1 = start_pod_slow(Arc::clone(&store), "writer-1", warm_delay, cancel.clone());
    let _pod2 = start_pod_slow(Arc::clone(&store), "writer-2", warm_delay, cancel.clone());
    let _pod3 = start_pod_slow(Arc::clone(&store), "writer-3", warm_delay, cancel.clone());

    let pod_names: Vec<String> = (0..4).map(|i| format!("writer-{i}")).collect();

    // Wait for the strategy to be satisfied (no further handoffs needed).
    // Longer timeout: slow warm (300ms * partitions) + debounce (500ms) + handoff rounds
    let check_store = Arc::clone(&store);
    let check_strategy = Arc::clone(&strategy);
    let check_pods = pod_names.clone();
    wait_for_condition(Duration::from_secs(30), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        let strategy = Arc::clone(&check_strategy);
        let pods = check_pods.clone();
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            if assignments.len() != MANY_PARTITIONS as usize || !handoffs.is_empty() {
                return false;
            }
            let current: std::collections::HashMap<u32, String> = assignments
                .iter()
                .map(|a| (a.partition, a.owner.clone()))
                .collect();
            let desired = strategy.compute_assignments(&current, &pods, MANY_PARTITIONS);
            assignment_coordination::util::compute_required_handoffs(&current, &desired).is_empty()
        }
    })
    .await;

    // Verify every pod owns at least one partition
    let assignments = store.list_assignments().await.unwrap();
    for name in &pod_names {
        assert!(
            assignments.iter().any(|a| a.owner == *name),
            "{name} should own at least one partition"
        );
    }

    if evenly_distributed {
        let per_pod = MANY_PARTITIONS as usize / pod_names.len();
        for name in &pod_names {
            assert_eq!(
                assignments.iter().filter(|a| a.owner == *name).count(),
                per_pod,
                "expected even distribution for {name}"
            );
        }
    }

    cancel.cancel();
}

/// Verify that a pod going through graceful drain (SIGTERM) hands off its
/// partitions to surviving pods before exiting.
///
/// Flow:
/// 1. Two pods share partitions.
/// 2. Pod-0 receives cancel (simulating SIGTERM) → sets status to Draining.
/// 3. Coordinator sees Draining, creates handoffs to pod-1.
/// 4. Pod-0 releases partitions after handoff completes.
/// 5. Pod-1 ends up owning all partitions.
async fn graceful_drain_transfers_partitions(
    test_name: &str,
    strategy: Arc<dyn AssignmentStrategy>,
    _evenly_distributed: bool,
) {
    let store = test_store(test_name).await;
    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let coord_cancel = CancellationToken::new();
    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::clone(&strategy),
        coord_cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", coord_cancel.clone());

    // Start two pods, each with its own cancel token
    let pod0_cancel = CancellationToken::new();
    let pod0 = start_pod(Arc::clone(&store), "writer-0", pod0_cancel.clone());
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", coord_cancel.clone());

    // Wait for both pods to have partitions assigned
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().any(|a| a.owner == "writer-0")
                && assignments.iter().any(|a| a.owner == "writer-1")
                && handoffs.is_empty()
        }
    })
    .await;

    // Cancel pod-0 (simulates SIGTERM) — it should drain gracefully
    pod0_cancel.cancel();

    // Wait for pod-0 to transition away from Ready
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            !pods.iter().any(|p| {
                p.pod_name == "writer-0"
                    && p.status == personhog_coordination::types::PodStatus::Ready
            })
        }
    })
    .await;

    // Wait for all partitions to be owned by pod-1 (handoffs complete)
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-1")
                && handoffs.is_empty()
        }
    })
    .await;

    // Wait for pod-0 to record Released events (may lag behind handoff deletion)
    let check_events = Arc::clone(&pod0.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_events);
        async move {
            events
                .lock()
                .await
                .iter()
                .any(|e| matches!(e, HandoffEvent::Released(_)))
        }
    })
    .await;

    // Verify all partitions belong to pod-1
    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);
    for a in &assignments {
        assert_eq!(
            a.owner, "writer-1",
            "partition {} should be owned by writer-1",
            a.partition
        );
    }

    coord_cancel.cancel();
}

/// Verify that when the drain status write to etcd fails (e.g. pod key was
/// already deleted), the pod exits cleanly without hanging or panicking.
/// It falls back to lease-based cleanup.
#[tokio::test]
async fn drain_status_write_failure_exits_cleanly() {
    let store = test_store("drain-write-fail").await;
    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let coord_cancel = CancellationToken::new();
    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::clone(&strategy),
        coord_cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", coord_cancel.clone());

    let pod0_cancel = CancellationToken::new();
    let pod0 = start_pod(Arc::clone(&store), "writer-0", pod0_cancel.clone());

    // Wait for pod-0 to get all partitions
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-0")
        }
    })
    .await;

    // Delete the pod's key from etcd before cancelling. This simulates
    // the lease expiring or etcd state being lost. When drain() tries
    // update_pod_status(), it will fail with NotFound.
    store.delete_pod("writer-0").await.unwrap();

    // Cancel pod-0 (simulates SIGTERM)
    pod0_cancel.cancel();

    // The pod should exit cleanly within a reasonable time, not hang.
    let join_handle = pod0.join_handle.unwrap();
    let result = tokio::time::timeout(Duration::from_secs(5), join_handle)
        .await
        .expect("pod should exit within 5s, not hang")
        .expect("pod task should not panic");
    // drain() failure is logged as a warning, run() still returns Ok
    assert!(
        result.is_ok(),
        "pod should exit cleanly despite drain failure"
    );

    coord_cancel.cancel();
}

// ── New protocol tests (Patch 5: unified handoff) ───────────────────────

/// Initial assignments go through the full handoff protocol with
/// `old_owner = None`, not a direct-write path. Verifies the handoff
/// transitions through Freezing → Warming → Complete and that the pod
/// observes a Warmed event but never a Drained event (no old owner).
#[tokio::test]
async fn initial_assignment_creates_handoff_with_no_old_owner() {
    let store = test_store("initial-no-old-owner").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let pod = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for full bootstrap to settle
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize && handoffs.is_empty()
        }
    })
    .await;

    // The pod should have warmed every partition but never been asked to
    // drain (no partition had an old_owner).
    let events = pod.events.lock().await;
    let warmed_count = events
        .iter()
        .filter(|e| matches!(e, HandoffEvent::Warmed(_)))
        .count();
    let drained_count = events
        .iter()
        .filter(|e| matches!(e, HandoffEvent::Drained(_)))
        .count();
    let released_count = events
        .iter()
        .filter(|e| matches!(e, HandoffEvent::Released(_)))
        .count();

    assert_eq!(
        warmed_count, NUM_PARTITIONS as usize,
        "pod should have warmed every partition"
    );
    assert_eq!(
        drained_count, 0,
        "pod should not have been asked to drain (no old owner)"
    );
    assert_eq!(
        released_count, 0,
        "pod should not have released (no old owner)"
    );

    cancel.cancel();
}

/// During Freezing/Warming, the old owner retains its partition. It only
/// releases at Complete. This test starts a 2-pod cluster, adds a 3rd pod
/// to trigger reassignments, and asserts that Released events for the old
/// owner only fire after the corresponding Warmed events for the new owner.
#[tokio::test]
async fn old_owner_retains_partition_through_warming() {
    let store = test_store("retain-through-warming").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for writer-0 to own all partitions
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize && handoffs.is_empty()
        }
    })
    .await;

    // Add writer-1 — triggers reassignments
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());

    // Wait for the reassignments to fully complete
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let has_both = assignments.iter().any(|a| a.owner == "writer-0")
                && assignments.iter().any(|a| a.owner == "writer-1");
            assignments.len() == NUM_PARTITIONS as usize && has_both && handoffs.is_empty()
        }
    })
    .await;

    // For each partition that writer-0 released, the corresponding Drained
    // event must precede the Released event. (Released only fires at
    // Complete, while Drained fires at Freezing — earlier in the protocol.)
    let events = pod0.events.lock().await;
    for (i, event) in events.iter().enumerate() {
        if let HandoffEvent::Released(p) = event {
            let drained_index = events[..i]
                .iter()
                .position(|e| matches!(e, HandoffEvent::Drained(q) if q == p));
            assert!(
                drained_index.is_some(),
                "partition {p} was Released without a prior Drained event"
            );
        }
    }

    cancel.cancel();
}

/// When the routing table sees a handoff `Delete` event (because
/// cleanup_stale_handoffs deleted a stuck handoff), the router must drain
/// its stash back to the current routing-table owner. This proves the
/// `EventType::Delete` branch of `watch_handoffs_loop` works.
///
/// Verified by manually injecting and deleting a handoff via the store —
/// avoids the flakiness of relying on a blocking pod's lease to expire,
/// which is brittle because the pod's cancellation can't preempt a stuck
/// `warm_partition`.
#[tokio::test]
async fn handoff_delete_drains_stash_to_current_owner() {
    use personhog_coordination::types::{HandoffPhase, HandoffState};

    let store = test_store("delete-drains-stash").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let _pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for writer-0 to own all partitions
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize && handoffs.is_empty()
        }
    })
    .await;

    // Inject a Freezing handoff for partition 0, targeting a fictitious
    // pod that will never write a WarmedAck. This simulates a "stuck"
    // handoff without needing a real blocking pod.
    let stuck_handoff = HandoffState {
        partition: 0,
        old_owner: Some("writer-0".to_string()),
        new_owner: "phantom-pod".to_string(),
        phase: HandoffPhase::Freezing,
        started_at: 0,
    };
    store.put_handoff(&stuck_handoff).await.unwrap();

    // Wait for the router to observe the handoff and call begin_stash
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            events
                .lock()
                .await
                .iter()
                .any(|e| matches!(e, common::CutoverEvent::StashBegan { partition: 0, .. }))
        }
    })
    .await;

    // Snapshot drain count *before* the Delete. The router has
    // already observed any drain_stash calls produced by the
    // bootstrap (each initial handoff completes via the Complete
    // path, which calls drain_stash with target=writer-0), so a
    // strict count comparison — not an event-existence check — is
    // required to attribute the next drain to the Delete event.
    let drains_before = router
        .events
        .lock()
        .await
        .iter()
        .filter(|e| matches!(e, common::CutoverEvent::StashDrained { .. }))
        .count();

    // Now delete the handoff to simulate cleanup_stale_handoffs firing.
    store.delete_handoff(0).await.unwrap();

    // Wait for the drain *count* to grow past `drains_before`. An
    // event-existence check would race the bootstrap drains: those
    // already record `StashDrained{partition: 0, target: writer-0}`,
    // so any "does an event matching this exist" predicate would
    // return true immediately without waiting for the Delete-driven
    // drain to fire.
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            let count = events
                .lock()
                .await
                .iter()
                .filter(|e| matches!(e, common::CutoverEvent::StashDrained { .. }))
                .count();
            count > drains_before
        }
    })
    .await;

    // Sanity-check that the latest drain landed on the right target.
    // Because the count is now strictly larger than the bootstrap
    // baseline, at least one additional `StashDrained` must exist;
    // the Delete branch always targets the routing-table's current
    // owner, which is `writer-0` for partition 0.
    let events = router.events.lock().await;
    let post_delete_drain = events
        .iter()
        .rev()
        .find(|e| matches!(e, common::CutoverEvent::StashDrained { partition: 0, .. }))
        .expect("a Delete-triggered drain for partition 0 must exist");
    match post_delete_drain {
        common::CutoverEvent::StashDrained { target, .. } => {
            assert_eq!(target, "writer-0", "drain must target the current owner");
        }
        _ => unreachable!(),
    }

    cancel.cancel();
}

/// When the routing table sees a handoff Complete, it should update the
/// table to point at the new owner inline. This proves the inline routing
/// update inside `handle_handoff_put` runs (the assignment watch is gone).
#[tokio::test]
async fn routing_table_updated_at_handoff_complete() {
    let store = test_store("routing-table-inline").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let _pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for initial bootstrap
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize && handoffs.is_empty()
        }
    })
    .await;

    // Router's table should match etcd
    let table = router.table.read().await;
    assert_eq!(
        table.len(),
        NUM_PARTITIONS as usize,
        "router table should have entries for all partitions"
    );
    assert!(
        table.values().all(|v| v == "writer-0"),
        "router table should point at writer-0"
    );
    drop(table);

    // Add writer-1, triggering handoffs
    let _pod1 = start_pod(Arc::clone(&store), "writer-1", cancel.clone());

    // Wait for assignments to be split across both pods AND handoffs to clear
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let has_both = assignments.iter().any(|a| a.owner == "writer-0")
                && assignments.iter().any(|a| a.owner == "writer-1");
            assignments.len() == NUM_PARTITIONS as usize && has_both && handoffs.is_empty()
        }
    })
    .await;

    // Router's table should now reflect the new owner distribution.
    // This is the crucial assertion — without the inline update inside
    // watch_handoffs_loop's Complete handler, the table would not have
    // been updated (we removed watch_assignments_loop).
    let final_assignments = store.list_assignments().await.unwrap();
    let expected: std::collections::HashMap<u32, String> = final_assignments
        .iter()
        .map(|a| (a.partition, a.owner.clone()))
        .collect();
    let table = router.table.read().await;
    assert_eq!(
        *table, expected,
        "router table must match etcd assignments after handoffs complete"
    );

    cancel.cancel();
}

/// A router that joins after a handoff has already entered Warming should
/// observe the Warming event in `load_initial` and call begin_stash. It
/// should NOT write a FreezeAck — the Freezing quorum has already been
/// collected. Verified by injecting a Warming handoff directly into etcd
/// before starting the late-joining router.
#[tokio::test]
async fn late_joining_router_during_warming_begins_stash() {
    use personhog_coordination::types::{HandoffPhase, HandoffState};

    let store = test_store("late-router-warming").await;
    let cancel = CancellationToken::new();

    // Inject a handoff already in Warming — old_owner=writer-0,
    // new_owner=writer-1. This simulates the state a late-joining router
    // sees if it starts up after the freeze quorum is already collected.
    let warming_handoff = HandoffState {
        partition: 3,
        old_owner: Some("writer-0".to_string()),
        new_owner: "writer-1".to_string(),
        phase: HandoffPhase::Warming,
        started_at: 0,
    };
    store.put_handoff(&warming_handoff).await.unwrap();

    // Start the late-joining router
    let router = start_router(Arc::clone(&store), "router-1", cancel.clone());

    // It should observe the Warming handoff via load_initial and begin
    // stashing, despite never having seen a Freezing event for it.
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            events.lock().await.iter().any(|e| {
                matches!(
                    e,
                    common::CutoverEvent::StashBegan { partition: 3, new_owner }
                        if new_owner == "writer-1"
                )
            })
        }
    })
    .await;

    // The router must NOT have written a FreezeAck — the Freezing quorum
    // has already been satisfied (the handoff is past Freezing). Acking
    // here would be incorrect.
    let freeze_acks = store.list_freeze_acks(3).await.unwrap();
    let router1_acks = freeze_acks
        .iter()
        .filter(|a| a.router_name == "router-1")
        .count();
    assert_eq!(
        router1_acks, 0,
        "late-joining router must not write a FreezeAck for a Warming handoff"
    );

    cancel.cancel();
}

/// When a Freezing handoff has a dead `old_owner` (one that's not a
/// registered pod), `cleanup_stale_handoffs` should delete it so the
/// handoff doesn't stall waiting for a `PodDrainedAck` that will never
/// come. Verified by injecting a stale handoff into etcd and triggering
/// a pod-change event.
#[tokio::test]
async fn dead_old_owner_in_freezing_triggers_cleanup() {
    use personhog_coordination::types::{HandoffPhase, HandoffState};

    let store = test_store("dead-old-owner-freezing").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Inject a stale Freezing handoff: old_owner=phantom-old (never
    // registered as a pod), new_owner=writer-0 (will be registered next).
    // The DrainedAck for phantom-old will never be written, so without
    // cleanup the handoff would stall in Freezing forever.
    let stale = HandoffState {
        partition: 4,
        old_owner: Some("phantom-old".to_string()),
        new_owner: "writer-0".to_string(),
        phase: HandoffPhase::Freezing,
        started_at: 0,
    };
    store.put_handoff(&stale).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Starting writer-0 fires a pod-change event which calls
    // handle_pod_change_static → cleanup_stale_handoffs. The dead
    // old_owner check should detect the phantom and delete the handoff.
    let _pod = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for the stale handoff to be deleted and the system to settle.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            // The stale handoff for partition 4 should be gone; full set
            // of assignments should be present once normal bootstrap
            // completes (independent of partition 4's stale handoff).
            !handoffs
                .iter()
                .any(|h| h.partition == 4 && h.old_owner.as_deref() == Some("phantom-old"))
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "writer-0")
        }
    })
    .await;

    cancel.cancel();
}

/// Symmetric to `late_joining_router_during_warming_begins_stash`, but for a
/// router that comes up while a handoff is still in `Freezing`. The router
/// must both call `begin_stash` AND write a `RouterFreezeAck` — the freeze
/// quorum has not yet been collected, so the router's ack is required for
/// the coordinator to advance.
#[tokio::test]
async fn late_joining_router_during_freezing_acks_and_stashes() {
    use personhog_coordination::types::{HandoffPhase, HandoffState};

    let store = test_store("late-router-freezing").await;
    let cancel = CancellationToken::new();

    // Inject a Freezing handoff before any router is up. This is the state
    // a router sees if it joins after the coordinator created the handoff
    // but before any freeze quorum has been collected.
    let freezing_handoff = HandoffState {
        partition: 5,
        old_owner: Some("writer-0".to_string()),
        new_owner: "writer-1".to_string(),
        phase: HandoffPhase::Freezing,
        started_at: 0,
    };
    store.put_handoff(&freezing_handoff).await.unwrap();

    // Start the late-joining router.
    let router = start_router(Arc::clone(&store), "router-late", cancel.clone());

    // It must call begin_stash for the partition (observed via load_initial).
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            events.lock().await.iter().any(|e| {
                matches!(
                    e,
                    common::CutoverEvent::StashBegan { partition: 5, new_owner }
                        if new_owner == "writer-1"
                )
            })
        }
    })
    .await;

    // It must also write a FreezeAck — the freeze quorum is still open.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let acks = store.list_freeze_acks(5).await.unwrap_or_default();
            acks.iter().any(|a| a.router_name == "router-late")
        }
    })
    .await;

    cancel.cancel();
}

/// Symmetric to `handoff_delete_drains_stash_to_current_owner`, but with the
/// handoff in `Warming` instead of `Freezing` when it's deleted. Exercises
/// the same `EventType::Delete` branch in `watch_handoffs_loop`, but from
/// the post-freeze state — the router has already begun stashing and the
/// freeze quorum has been collected.
#[tokio::test]
async fn handoff_delete_during_warming_drains_to_current_owner() {
    use personhog_coordination::types::{HandoffPhase, HandoffState};

    let store = test_store("delete-during-warming").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let _pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for writer-0 to own all partitions cleanly.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize && handoffs.is_empty()
        }
    })
    .await;

    // Inject a Warming handoff for partition 0 targeting a phantom new
    // owner. We use Warming directly so the router observes it as a
    // post-freeze handoff: load_initial calls begin_stash, but no
    // FreezeAck is written.
    let stuck = HandoffState {
        partition: 0,
        old_owner: Some("writer-0".to_string()),
        new_owner: "phantom-pod".to_string(),
        phase: HandoffPhase::Warming,
        started_at: 0,
    };
    store.put_handoff(&stuck).await.unwrap();

    // Wait for the router to observe the handoff and begin stashing.
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            events
                .lock()
                .await
                .iter()
                .any(|e| matches!(e, common::CutoverEvent::StashBegan { partition: 0, .. }))
        }
    })
    .await;

    // Snapshot drain count *before* the Delete. The bootstrap's
    // initial handoffs each completed via the Complete path, which
    // calls drain_stash with target=writer-0 for every partition —
    // including 0. A strict count comparison (not event-existence)
    // is required to attribute the next drain to the Delete event.
    let drains_before = router
        .events
        .lock()
        .await
        .iter()
        .filter(|e| matches!(e, common::CutoverEvent::StashDrained { .. }))
        .count();

    // Delete the Warming handoff. The Delete branch must drain the stash
    // back to the current routing-table owner (writer-0), independent of
    // the phase the handoff was in when deleted.
    store.delete_handoff(0).await.unwrap();

    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            let count = events
                .lock()
                .await
                .iter()
                .filter(|e| matches!(e, common::CutoverEvent::StashDrained { .. }))
                .count();
            count > drains_before
        }
    })
    .await;

    let events = router.events.lock().await;
    let post_delete_drain = events
        .iter()
        .rev()
        .find(|e| matches!(e, common::CutoverEvent::StashDrained { partition: 0, .. }))
        .expect("a Delete-triggered drain for partition 0 must exist");
    match post_delete_drain {
        common::CutoverEvent::StashDrained { target, .. } => {
            assert_eq!(target, "writer-0", "drain must target the current owner");
        }
        _ => unreachable!(),
    }

    cancel.cancel();
}

/// `reconcile_pending_handoffs` must nudge handoffs whose preconditions are
/// already satisfied — the coordinator's ack-watch only fires on Put
/// events, so any acks written before the coordinator came up are invisible
/// to it. Without reconcile, a Warming handoff with a pre-existing
/// `WarmedAck` would stall forever.
///
/// Setup: pre-stage a Warming handoff plus a WarmedAck for its new owner,
/// without a coordinator running. Then start the coordinator and assert
/// the handoff advances to Complete (which deletes the record and writes
/// the new assignment).
#[tokio::test]
async fn reconcile_advances_warming_with_pre_staged_warmed_ack() {
    use personhog_coordination::types::{HandoffPhase, HandoffState, PodWarmedAck};

    let store = test_store("reconcile-pre-staged-ack").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Pre-stage a Warming handoff for partition 6 with no coordinator
    // running. New owner already "warmed" (we inject the ack directly).
    // This is the state the coordinator would face if it crashed right
    // after the new owner wrote its WarmedAck but before the coordinator
    // observed the Put event.
    let warming = HandoffState {
        partition: 6,
        old_owner: Some("writer-0".to_string()),
        new_owner: "writer-1".to_string(),
        phase: HandoffPhase::Warming,
        started_at: 0,
    };
    store.put_handoff(&warming).await.unwrap();
    store
        .put_warmed_ack(&PodWarmedAck {
            pod_name: "writer-1".to_string(),
            partition: 6,
            acked_at: 0,
        })
        .await
        .unwrap();

    // Start the coordinator. Reconcile-on-startup must call
    // `check_phase_advance` for the pre-staged handoff, see the existing
    // WarmedAck, and advance Warming → Complete via the atomic txn.
    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());

    // Once Complete fires, `handle_handoff_update_static` deletes the
    // handoff record and the partition's assignment is written to
    // `writer-1`. Wait for both.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            let p6_owner = assignments
                .iter()
                .find(|a| a.partition == 6)
                .map(|a| a.owner.as_str());
            !handoffs.iter().any(|h| h.partition == 6) && p6_owner == Some("writer-1")
        }
    })
    .await;

    cancel.cancel();
}

/// A `Draining` pod is still alive (lease present, heartbeating) and is
/// still capable of running its handoff handler and writing a `DrainedAck`.
/// `check_phase_advance` must therefore wait for that ack rather than
/// treating the pod as dead and bypassing the drain. Regression test for
/// the case where gating on `PodStatus::Ready` instead of registration
/// presence let Freezing → Warming advance with potentially in-flight
/// writes still being produced by the old owner.
#[tokio::test]
async fn draining_old_owner_blocks_phase_advance() {
    use personhog_coordination::types::{
        HandoffPhase, HandoffState, PodDrainedAck, PodStatus, RegisteredPod,
    };

    let store = test_store("draining-blocks-advance").await;
    let cancel = CancellationToken::new();

    // Register a Draining pod directly. This simulates a pod that was
    // healthy, started shutting down, and now sits in Draining while
    // working through its remaining handlers.
    let lease = store.grant_lease(30).await.unwrap();
    let draining_pod = RegisteredPod {
        pod_name: "writer-draining".to_string(),
        generation: String::new(),
        status: PodStatus::Draining,
        registered_at: 0,
        last_heartbeat: 0,
        controller: None,
    };
    store.register_pod(&draining_pod, lease).await.unwrap();

    // Inject a Freezing handoff with the Draining pod as old_owner.
    let handoff = HandoffState {
        partition: 7,
        old_owner: Some("writer-draining".to_string()),
        new_owner: "writer-new".to_string(),
        phase: HandoffPhase::Freezing,
        started_at: 0,
    };
    store.put_handoff(&handoff).await.unwrap();

    // Start the coordinator. Reconcile-on-startup will call
    // `check_phase_advance`. With no routers registered, the freeze
    // quorum is vacuously satisfied (zero acks needed) so the handoff
    // immediately advances Freezing → Draining. It must then sit in
    // Draining until the (still-alive) Draining pod writes a
    // DrainedAck — without the registration-presence check it would
    // wrongly treat the pod as dead and advance straight to Warming.
    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());

    // Give the coordinator time to advance Freezing → Draining and to
    // run subsequent ack-watch firings. The handoff must reach Draining
    // and remain there.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            matches!(
                store.get_handoff(7).await.unwrap(),
                Some(ref s) if s.phase == HandoffPhase::Draining
            )
        }
    })
    .await;
    for _ in 0..10 {
        tokio::time::sleep(POLL_INTERVAL).await;
        let h = store.get_handoff(7).await.unwrap();
        assert!(
            matches!(h, Some(ref s) if s.phase == HandoffPhase::Draining),
            "handoff must stay in Draining while old_owner is registered and unacked: {h:?}"
        );
    }

    // Once the Draining pod writes its DrainedAck, the handoff should
    // advance to Warming. The handoff watch's nudge picks up the ack-watch
    // event and re-runs `check_phase_advance`.
    store
        .put_drained_ack(&PodDrainedAck {
            pod_name: "writer-draining".to_string(),
            partition: 7,
            acked_at: 0,
        })
        .await
        .unwrap();

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            matches!(
                store.get_handoff(7).await.unwrap(),
                Some(ref s) if s.phase == HandoffPhase::Warming
            )
        }
    })
    .await;

    cancel.cancel();
}

/// `cleanup_stale_handoffs` must use registration presence, not Ready
/// status, when judging whether a pod is gone. Otherwise a `Draining` pod
/// in the middle of a handoff would have its handoff record deleted
/// before it could write its `DrainedAck`. Regression test for that
/// scenario.
#[tokio::test]
async fn draining_old_owner_does_not_trigger_cleanup() {
    use personhog_coordination::types::{HandoffPhase, HandoffState, PodStatus, RegisteredPod};

    let store = test_store("draining-no-cleanup").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Register a Draining pod with no DrainedAck written yet — the most
    // failure-prone state for `cleanup_stale_handoffs`.
    let lease = store.grant_lease(30).await.unwrap();
    let draining_pod = RegisteredPod {
        pod_name: "writer-draining".to_string(),
        generation: String::new(),
        status: PodStatus::Draining,
        registered_at: 0,
        last_heartbeat: 0,
        controller: None,
    };
    store.register_pod(&draining_pod, lease).await.unwrap();

    // Inject a Freezing handoff with the Draining pod as old_owner.
    let handoff = HandoffState {
        partition: 2,
        old_owner: Some("writer-draining".to_string()),
        new_owner: "writer-new".to_string(),
        phase: HandoffPhase::Freezing,
        started_at: 0,
    };
    store.put_handoff(&handoff).await.unwrap();

    // Start the coordinator and a real pod. The new pod registering
    // triggers a pod-change event and runs `cleanup_stale_handoffs`. With
    // the bug, the Draining pod is "not active" and the handoff is
    // deleted as stuck-on-dead-old-owner. With the fix, the handoff
    // survives because the Draining pod's etcd key is still present.
    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let _new_pod = start_pod(Arc::clone(&store), "writer-new", cancel.clone());

    // Give pod-change handling time to run several times.
    for _ in 0..10 {
        tokio::time::sleep(POLL_INTERVAL).await;
        let h = store.get_handoff(2).await.unwrap();
        assert!(
            h.is_some(),
            "handoff for Draining old_owner must not be deleted by cleanup"
        );
    }

    cancel.cancel();
}

/// The two-phase split (Freezing → Draining → Warming) ensures the old
/// owner only begins draining inflight handlers AFTER every router has
/// freeze-acked. Without the split, a slow router could send a final
/// request to the old owner after the old owner observed inflight=0 and
/// wrote DrainedAck, advancing Kafka HWM past the point warming
/// snapshots and leaving the new owner with a stale cache.
///
/// This test verifies the gate by injecting a Freezing handoff with a
/// registered router that never acks. The handoff must remain in
/// Freezing — it cannot advance to Draining without the freeze quorum,
/// and the old pod must not start draining yet.
#[tokio::test]
async fn freezing_blocks_until_routers_ack_before_draining() {
    use personhog_coordination::types::{HandoffPhase, HandoffState, PodStatus, RegisteredPod};

    let store = test_store("freezing-gates-draining").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Register both old and new owner pods so `cleanup_stale_handoffs`
    // doesn't delete the injected handoff. They don't run real
    // handlers — we just need their etcd registrations to exist.
    let old_lease = store.grant_lease(60).await.unwrap();
    let new_lease = store.grant_lease(60).await.unwrap();
    for (name, lease) in [("writer-old", old_lease), ("writer-new", new_lease)] {
        let pod = RegisteredPod {
            pod_name: name.to_string(),
            generation: String::new(),
            status: PodStatus::Ready,
            registered_at: 0,
            last_heartbeat: 0,
            controller: None,
        };
        store.register_pod(&pod, lease).await.unwrap();
    }

    // Register a router that will be slow — never write a FreezeAck —
    // so the freeze quorum cannot complete on its own. We register it
    // by hand because no real router process is started.
    let router_lease = store.grant_lease(60).await.unwrap();
    let slow_router = personhog_coordination::types::RegisteredRouter {
        router_name: "slow-router".to_string(),
        registered_at: 0,
        last_heartbeat: 0,
    };
    store
        .register_router(&slow_router, router_lease)
        .await
        .unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());

    // Inject a Freezing handoff. With the slow router never acking,
    // the coordinator cannot advance.
    let handoff = HandoffState {
        partition: 1,
        old_owner: Some("writer-old".to_string()),
        new_owner: "writer-new".to_string(),
        phase: HandoffPhase::Freezing,
        started_at: 0,
    };
    store.put_handoff(&handoff).await.unwrap();

    // The handoff must stay in Freezing for as long as the slow router
    // hasn't acked, regardless of any other state. This prevents the
    // race where the old pod could be told to drain while a router is
    // still able to forward writes to it.
    for _ in 0..10 {
        tokio::time::sleep(POLL_INTERVAL).await;
        let h = store.get_handoff(1).await.unwrap();
        assert!(
            matches!(h, Some(ref s) if s.phase == HandoffPhase::Freezing),
            "handoff must stay in Freezing without freeze-ack quorum: {h:?}"
        );
    }

    // Once the router acks, the handoff advances to Draining (waiting
    // on the old owner) — not directly to Warming.
    store
        .put_freeze_ack(&personhog_coordination::types::RouterFreezeAck {
            router_name: "slow-router".to_string(),
            partition: 1,
            acked_at: 0,
        })
        .await
        .unwrap();

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            matches!(
                store.get_handoff(1).await.unwrap(),
                Some(ref s) if s.phase == HandoffPhase::Draining
            )
        }
    })
    .await;

    cancel.cancel();
}

/// Initial assignments — handoffs with `old_owner == None` — have
/// nothing to drain and must skip the Draining phase entirely. They
/// advance straight from Freezing to Warming once router quorum is
/// satisfied. Without this short-circuit, every fresh partition
/// assignment would stall in Draining waiting for a DrainedAck that
/// will never arrive.
#[tokio::test]
async fn initial_assignment_skips_draining_phase() {
    use personhog_coordination::types::{HandoffPhase, HandoffState, PodStatus, RegisteredPod};

    let store = test_store("initial-skips-draining").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Register the new_owner pod so `cleanup_stale_handoffs` doesn't
    // delete the injected handoff for missing-target reasons.
    let lease = store.grant_lease(60).await.unwrap();
    let new_pod = RegisteredPod {
        pod_name: "writer-new".to_string(),
        generation: String::new(),
        status: PodStatus::Ready,
        registered_at: 0,
        last_heartbeat: 0,
        controller: None,
    };
    store.register_pod(&new_pod, lease).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());

    // Inject a Freezing handoff with no old_owner. With no routers
    // registered, the freeze quorum is vacuously met — the handoff
    // should advance straight from Freezing to Warming, never visiting
    // Draining.
    let handoff = HandoffState {
        partition: 0,
        old_owner: None,
        new_owner: "writer-new".to_string(),
        phase: HandoffPhase::Freezing,
        started_at: 0,
    };
    store.put_handoff(&handoff).await.unwrap();

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            matches!(
                store.get_handoff(0).await.unwrap(),
                Some(ref s) if s.phase == HandoffPhase::Warming
            )
        }
    })
    .await;

    cancel.cancel();
}

/// If the old owner dies *during* Draining (lease expiry, pod crash),
/// the handoff must still progress — either by advancing via
/// `check_phase_advance`'s "old_owner not registered" branch, or by
/// being cleaned up and replaced via rebalance. Either way the
/// partition must end up assigned to a healthy pod, not stuck in
/// Draining indefinitely.
///
/// The actual path is racy: pod-change events run
/// `cleanup_stale_handoffs` (which may delete) while ack-watch events
/// can fire `check_phase_advance` (which may advance). The test
/// asserts the end state — partition has an active assignment and no
/// lingering Draining handoff — which both paths converge to.
#[tokio::test]
async fn dead_old_owner_in_draining_recovers() {
    use personhog_coordination::types::{HandoffPhase, HandoffState, PodStatus, RegisteredPod};

    let store = test_store("dead-old-owner-draining").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Register both old and new owner. We need both initially so the
    // injected Draining handoff isn't immediately cleaned up.
    let old_lease = store.grant_lease(60).await.unwrap();
    let new_lease = store.grant_lease(60).await.unwrap();
    for (name, lease) in [("writer-old", old_lease), ("writer-new", new_lease)] {
        let pod = RegisteredPod {
            pod_name: name.to_string(),
            generation: String::new(),
            status: PodStatus::Ready,
            registered_at: 0,
            last_heartbeat: 0,
            controller: None,
        };
        store.register_pod(&pod, lease).await.unwrap();
    }

    // Inject a Draining handoff (past Freezing, no DrainedAck yet).
    let handoff = HandoffState {
        partition: 3,
        old_owner: Some("writer-old".to_string()),
        new_owner: "writer-new".to_string(),
        phase: HandoffPhase::Draining,
        started_at: 0,
    };
    store.put_handoff(&handoff).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());

    // Wait for the coordinator to settle — the handoff must be in
    // Draining (no DrainedAck written, old_owner still registered).
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            matches!(
                store.get_handoff(3).await.unwrap(),
                Some(ref s) if s.phase == HandoffPhase::Draining
            )
        }
    })
    .await;

    // Kill the old owner. From this point, recovery must converge
    // regardless of which mechanism wins — direct advance via
    // check_phase_advance OR cleanup_stale_handoffs followed by
    // rebalance.
    store.delete_pod("writer-old").await.unwrap();

    // End-state assertion: no Draining handoff lingers for partition
    // 3, and partition 3 ends up assigned to a registered pod.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let p3_still_draining = handoffs
                .iter()
                .any(|h| h.partition == 3 && h.phase == HandoffPhase::Draining);
            if p3_still_draining {
                return false;
            }
            // Partition is either fully resolved (assignment present,
            // handoff complete or absent) or progressing (handoff has
            // moved past Draining toward Warming/Complete).
            let assignments = store.list_assignments().await.unwrap_or_default();
            let p3_assigned = assignments
                .iter()
                .any(|a| a.partition == 3 && a.owner == "writer-new");
            let p3_handoff_progressing = handoffs
                .iter()
                .any(|h| h.partition == 3 && h.phase != HandoffPhase::Draining);
            p3_assigned || p3_handoff_progressing
        }
    })
    .await;

    cancel.cancel();
}

/// Reconcile-on-startup must be able to advance a Draining handoff
/// whose preconditions were satisfied before the coordinator came up.
/// Two pre-stages exercise this: a DrainedAck already in etcd, or the
/// old_owner already absent. Either way the coordinator's reconcile
/// pass should drive the handoff to Warming via `check_phase_advance`,
/// since the ack-watch only fires on Put events and missed pre-existing
/// state.
#[tokio::test]
async fn reconcile_advances_draining_with_pre_staged_drained_ack() {
    use personhog_coordination::types::{
        HandoffPhase, HandoffState, PodDrainedAck, PodStatus, RegisteredPod,
    };

    let store = test_store("reconcile-draining-ack").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    // Pre-stage both pods (so cleanup doesn't fire on either) plus a
    // Draining handoff plus a matching DrainedAck — all before the
    // coordinator starts. Reconcile must observe this state and
    // advance Draining → Warming.
    for name in ["writer-old", "writer-new"] {
        let lease = store.grant_lease(60).await.unwrap();
        let pod = RegisteredPod {
            pod_name: name.to_string(),
            generation: String::new(),
            status: PodStatus::Ready,
            registered_at: 0,
            last_heartbeat: 0,
            controller: None,
        };
        store.register_pod(&pod, lease).await.unwrap();
    }

    let handoff = HandoffState {
        partition: 5,
        old_owner: Some("writer-old".to_string()),
        new_owner: "writer-new".to_string(),
        phase: HandoffPhase::Draining,
        started_at: 0,
    };
    store.put_handoff(&handoff).await.unwrap();

    store
        .put_drained_ack(&PodDrainedAck {
            pod_name: "writer-old".to_string(),
            partition: 5,
            acked_at: 0,
        })
        .await
        .unwrap();

    // Now start the coordinator. Without reconcile-driven advancement,
    // the pre-staged DrainedAck would be invisible (the ack-watch only
    // fires on Put events delivered after the watch is established) and
    // the handoff would stall. Reconcile re-runs `check_phase_advance`
    // for every existing handoff, which picks up the pre-staged ack and
    // advances to Warming.
    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            matches!(
                store.get_handoff(5).await.unwrap(),
                Some(ref s) if s.phase == HandoffPhase::Warming
            )
        }
    })
    .await;

    cancel.cancel();
}

/// Symmetric to `late_joining_router_during_warming_begins_stash`, but
/// for a router that comes up while the handoff is in `Draining`. The
/// router must call `begin_stash` (so future writes for the partition
/// are buffered) and must NOT write a `FreezeAck` — the freeze quorum
/// has already been collected, and a late ack could miscount toward a
/// future handoff for the same partition.
#[tokio::test]
async fn late_joining_router_during_draining_begins_stash_no_ack() {
    use personhog_coordination::types::{HandoffPhase, HandoffState};

    let store = test_store("late-router-draining").await;
    let cancel = CancellationToken::new();

    // Inject a Draining handoff before any router is up.
    let draining_handoff = HandoffState {
        partition: 2,
        old_owner: Some("writer-0".to_string()),
        new_owner: "writer-1".to_string(),
        phase: HandoffPhase::Draining,
        started_at: 0,
    };
    store.put_handoff(&draining_handoff).await.unwrap();

    // Start the late-joining router.
    let router = start_router(Arc::clone(&store), "router-late", cancel.clone());

    // It must call begin_stash for the partition (observed via
    // load_initial).
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            events.lock().await.iter().any(|e| {
                matches!(
                    e,
                    common::CutoverEvent::StashBegan { partition: 2, new_owner }
                        if new_owner == "writer-1"
                )
            })
        }
    })
    .await;

    // The router must NOT have written a FreezeAck — the freeze
    // quorum closed when the coordinator advanced Freezing → Draining,
    // and a late ack would either be redundant or risk being counted
    // toward the next handoff for this partition.
    tokio::time::sleep(POLL_INTERVAL * 3).await;
    let freeze_acks = store.list_freeze_acks(2).await.unwrap();
    let router1_acks = freeze_acks
        .iter()
        .filter(|a| a.router_name == "router-late")
        .count();
    assert_eq!(
        router1_acks, 0,
        "late-joining router must not write a FreezeAck for a Draining handoff"
    );

    cancel.cancel();
}

/// Symmetric to `handoff_delete_drains_stash_to_current_owner` and
/// `handoff_delete_during_warming_drains_to_current_owner`, but for a
/// handoff in `Draining` when it's deleted. The Delete branch in
/// `watch_handoffs_loop` is phase-agnostic, so this exercises the same
/// code path; the test confirms the recovery is uniform across phases.
#[tokio::test]
async fn handoff_delete_during_draining_drains_to_current_owner() {
    use personhog_coordination::types::{HandoffPhase, HandoffState};

    let store = test_store("delete-during-draining").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let strategy: Arc<dyn AssignmentStrategy> = Arc::new(StickyBalancedStrategy);
    let _coord = start_coordinator(Arc::clone(&store), strategy, cancel.clone());
    let router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let _pod0 = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    // Wait for the bootstrap assignment to settle so the router's
    // table points at writer-0 for every partition.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize && handoffs.is_empty()
        }
    })
    .await;

    // Inject a Draining handoff for partition 0 targeting a phantom
    // new owner. Inserting at Draining (rather than Freezing) lets us
    // exercise the Delete-during-Draining branch directly.
    let stuck = HandoffState {
        partition: 0,
        old_owner: Some("writer-0".to_string()),
        new_owner: "phantom-pod".to_string(),
        phase: HandoffPhase::Draining,
        started_at: 0,
    };
    store.put_handoff(&stuck).await.unwrap();

    // Wait for the router to observe the handoff and begin stashing.
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            events
                .lock()
                .await
                .iter()
                .any(|e| matches!(e, common::CutoverEvent::StashBegan { partition: 0, .. }))
        }
    })
    .await;

    // Snapshot drain count before the Delete (see the Freezing
    // variant's comment for why a strict count, not event-existence,
    // is required).
    let drains_before = router
        .events
        .lock()
        .await
        .iter()
        .filter(|e| matches!(e, common::CutoverEvent::StashDrained { .. }))
        .count();

    // Delete the Draining handoff. The Delete branch must drain the
    // stash back to the current routing-table owner (writer-0),
    // independent of the phase the handoff was in when deleted.
    store.delete_handoff(0).await.unwrap();

    // Wait for the drain *count* to grow past `drains_before`.
    // Bootstrap drains for partition 0 already exist (each initial
    // handoff completes via Complete and calls drain_stash with
    // target=writer-0), so an event-existence predicate would race
    // and return true before the Delete-triggered drain fires.
    let check_router = Arc::clone(&router.events);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let events = Arc::clone(&check_router);
        async move {
            let count = events
                .lock()
                .await
                .iter()
                .filter(|e| matches!(e, common::CutoverEvent::StashDrained { .. }))
                .count();
            count > drains_before
        }
    })
    .await;

    let events = router.events.lock().await;
    let post_delete_drain = events
        .iter()
        .rev()
        .find(|e| matches!(e, common::CutoverEvent::StashDrained { partition: 0, .. }))
        .expect("a Delete-triggered drain for partition 0 must exist");
    match post_delete_drain {
        common::CutoverEvent::StashDrained { target, .. } => {
            assert_eq!(target, "writer-0", "drain must target the current owner");
        }
        _ => unreachable!(),
    }

    cancel.cancel();
}
