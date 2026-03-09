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

    // Every cutover should move from writer-0 to writer-1
    for event in router_events.iter() {
        assert_eq!(event.old_owner, "writer-0");
        assert_eq!(event.new_owner, "writer-1");
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
    let r0_partitions: std::collections::HashSet<u32> =
        r0_events.iter().map(|e| e.partition).collect();
    let r1_partitions: std::collections::HashSet<u32> =
        r1_events.iter().map(|e| e.partition).collect();
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
