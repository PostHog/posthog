mod common;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use common::{
    drive_handoffs_to_completion, kill_consumer, register_consumer, set_topic_config, signal_ready,
    signal_released, start_assigner, start_assigner_with_config, test_store, wait_for_condition,
    NUM_PARTITIONS, POLL_INTERVAL, WAIT_TIMEOUT,
};
use kafka_assigner::assigner::AssignerConfig;
use kafka_assigner::types::HandoffPhase;

// ── Basic scenarios ─────────────────────────────────────────────

#[tokio::test]
async fn single_consumer_gets_all_partitions() {
    let store = test_store("single-consumer").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let _c0 = register_consumer(&store, "c-0", 10).await;

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);
    for a in &assignments {
        assert_eq!(a.owner, "c-0");
    }

    let handoffs = store.list_handoffs().await.unwrap();
    assert!(handoffs.is_empty());

    cancel.cancel();
}

#[tokio::test]
async fn two_consumers_split_partitions() {
    let store = test_store("two-consumers").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;

    // Register both consumers before the assigner starts, so it sees
    // them together on its first pass — no handoffs needed.
    let _c0 = register_consumer(&store, "c-0", 10).await;
    let _c1 = register_consumer(&store, "c-1", 10).await;

    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let has_c0 = assignments.iter().any(|a| a.owner == "c-0");
            let has_c1 = assignments.iter().any(|a| a.owner == "c-1");
            assignments.len() == NUM_PARTITIONS as usize && has_c0 && has_c1
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);

    let c0_count = assignments.iter().filter(|a| a.owner == "c-0").count();
    let c1_count = assignments.iter().filter(|a| a.owner == "c-1").count();
    assert_eq!(c0_count, NUM_PARTITIONS as usize / 2);
    assert_eq!(c1_count, NUM_PARTITIONS as usize / 2);

    // First assignment with both consumers present — no handoffs needed.
    let handoffs = store.list_handoffs().await.unwrap();
    assert!(handoffs.is_empty());

    cancel.cancel();
}

#[tokio::test]
async fn scale_up_triggers_handoffs() {
    let store = test_store("scale-up").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let _c0 = register_consumer(&store, "c-0", 10).await;

    // Wait for c-0 to own all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Add second consumer — triggers rebalance with handoffs.
    let _c1 = register_consumer(&store, "c-1", 10).await;

    // Wait for handoffs to appear.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { !store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Drive handoffs to completion (simulate consumer behavior).
    drive_handoffs_to_completion(&store).await;

    // Verify even split.
    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);
    let c0_count = assignments.iter().filter(|a| a.owner == "c-0").count();
    let c1_count = assignments.iter().filter(|a| a.owner == "c-1").count();
    assert_eq!(c0_count, NUM_PARTITIONS as usize / 2);
    assert_eq!(c1_count, NUM_PARTITIONS as usize / 2);

    cancel.cancel();
}

#[tokio::test]
async fn full_handoff_lifecycle() {
    let store = test_store("handoff-lifecycle").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let _c0 = register_consumer(&store, "c-0", 10).await;

    // Wait for initial assignment.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Add second consumer.
    let _c1 = register_consumer(&store, "c-1", 10).await;

    // Step 1: Wait for Warming handoffs to appear.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            !handoffs.is_empty() && handoffs.iter().all(|h| h.phase == HandoffPhase::Warming)
        }
    })
    .await;

    let handoffs = store.list_handoffs().await.unwrap();
    assert!(handoffs
        .iter()
        .all(|h| h.old_owner == "c-0" && h.new_owner == "c-1"));

    // Step 2: Signal Ready for each handoff.
    for h in &handoffs {
        signal_ready(&store, &h.topic_partition()).await;
    }

    // Step 3: Wait for assigner to transition handoffs to Complete.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            !handoffs.is_empty() && handoffs.iter().all(|h| h.phase == HandoffPhase::Complete)
        }
    })
    .await;

    // Verify assignments have been updated to new owner.
    let handoffs = store.list_handoffs().await.unwrap();
    for h in &handoffs {
        let assignment = store.get_assignment(&h.topic_partition()).await.unwrap();
        assert_eq!(
            assignment.unwrap().owner,
            "c-1",
            "assignment should be updated to new owner after Complete"
        );
    }

    // Step 4: Signal Released for each handoff.
    for h in &handoffs {
        signal_released(&store, &h.topic_partition()).await;
    }

    // Step 5: All handoffs should be deleted.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    cancel.cancel();
}

#[tokio::test]
async fn multiple_topic_configs() {
    let store = test_store("multi-topic").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", 4).await;
    set_topic_config(&store, "clicks", 6).await;

    let _c0 = register_consumer(&store, "c-0", 10).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());

    // Wait for all 10 partitions (4 + 6) to be assigned.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == 10 && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    let events_count = assignments.iter().filter(|a| a.topic == "events").count();
    let clicks_count = assignments.iter().filter(|a| a.topic == "clicks").count();
    assert_eq!(events_count, 4);
    assert_eq!(clicks_count, 6);

    cancel.cancel();
}

#[tokio::test]
async fn no_consumers_no_assignments() {
    let store = test_store("no-consumers").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());

    // Give the assigner time to run its initial pass.
    tokio::time::sleep(Duration::from_secs(2)).await;

    let assignments = store.list_assignments().await.unwrap();
    assert!(assignments.is_empty());

    cancel.cancel();
}

#[tokio::test]
async fn no_topic_configs_no_assignments() {
    let store = test_store("no-topics").await;
    let cancel = CancellationToken::new();

    let _c0 = register_consumer(&store, "c-0", 10).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());

    // Give the assigner time to run its initial pass.
    tokio::time::sleep(Duration::from_secs(2)).await;

    let assignments = store.list_assignments().await.unwrap();
    assert!(assignments.is_empty());

    cancel.cancel();
}

#[tokio::test]
async fn assigner_starts_after_consumers() {
    let store = test_store("late-assigner").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _c0 = register_consumer(&store, "c-0", 10).await;
    let _c1 = register_consumer(&store, "c-1", 10).await;

    // No assigner yet — no assignments.
    let assignments = store.list_assignments().await.unwrap();
    assert!(assignments.is_empty());

    // Start the assigner — it should discover existing consumers.
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let has_c0 = assignments.iter().any(|a| a.owner == "c-0");
            let has_c1 = assignments.iter().any(|a| a.owner == "c-1");
            assignments.len() == NUM_PARTITIONS as usize && has_c0 && has_c1
        }
    })
    .await;

    cancel.cancel();
}

// ── Disaster scenarios ──────────────────────────────────────────

#[tokio::test]
async fn consumer_crash_reassigns_partitions() {
    let store = test_store("consumer-crash").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());

    // Register c-0 with a short lease (will be killed later).
    let c0 = register_consumer(&store, "c-0", 2).await;

    // Wait for c-0 to own all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Add second consumer — triggers rebalance with handoffs.
    let _c1 = register_consumer(&store, "c-1", 10).await;

    // Wait for balanced assignment, driving handoffs as they appear.
    // The assigner creates handoffs to move partitions from c-0 to c-1.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            for h in &handoffs {
                match h.phase {
                    HandoffPhase::Warming => {
                        signal_ready(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Complete => {
                        signal_released(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Ready => {}
                }
            }

            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().any(|a| a.owner == "c-0")
                && assignments.iter().any(|a| a.owner == "c-1")
        }
    })
    .await;

    // Kill c-0 — revoke lease immediately.
    kill_consumer(&store, c0).await;

    // Wait for c-0 to disappear from consumers.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let consumers = store.list_consumers().await.unwrap_or_default();
            consumers.len() == 1 && consumers[0].consumer_name == "c-1"
        }
    })
    .await;

    // Wait for all partitions to move to c-1, driving handoffs as they appear.
    // The assigner creates handoffs from dead c-0 to c-1. At the Complete
    // phase, cleanup_stale_handoffs auto-deletes them (old_owner is dead).
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            for h in &handoffs {
                match h.phase {
                    HandoffPhase::Warming => {
                        signal_ready(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Complete => {
                        signal_released(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Ready => {}
                }
            }

            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-1")
        }
    })
    .await;

    cancel.cancel();
}

#[tokio::test]
async fn consumer_crash_during_warming_cleans_up() {
    let store = test_store("crash-warming").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let _c0 = register_consumer(&store, "c-0", 10).await;

    // Wait for c-0 to own all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Snapshot the stable assignments.
    let stable_assignments: HashMap<u32, String> = store
        .list_assignments()
        .await
        .unwrap()
        .into_iter()
        .map(|a| (a.partition, a.owner))
        .collect();

    // Add c-1 with a short lease — do NOT drive handoffs.
    let c1 = register_consumer(&store, "c-1", 2).await;

    // Wait for Warming handoffs targeting c-1.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            !handoffs.is_empty()
                && handoffs
                    .iter()
                    .all(|h| h.new_owner == "c-1" && h.phase == HandoffPhase::Warming)
        }
    })
    .await;

    // Kill c-1 while handoffs are still at Warming.
    kill_consumer(&store, c1).await;

    // Stale handoffs targeting dead consumer should be cleaned up.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Assignments should revert to the pre-crash state (all owned by c-0).
    let final_assignments: HashMap<u32, String> = store
        .list_assignments()
        .await
        .unwrap()
        .into_iter()
        .map(|a| (a.partition, a.owner))
        .collect();
    assert_eq!(final_assignments, stable_assignments);
    assert!(
        !final_assignments.values().any(|v| v == "c-1"),
        "dead consumer should not own any partitions"
    );

    cancel.cancel();
}

#[tokio::test]
async fn rapid_scale_up_debounce() {
    let store = test_store("rapid-scale-up").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;

    let config = AssignerConfig {
        rebalance_debounce_interval: Duration::from_millis(500),
        ..Default::default()
    };
    let _assigner = start_assigner_with_config(Arc::clone(&store), config, cancel.clone());

    let _c0 = register_consumer(&store, "c-0", 10).await;

    // Wait for c-0 to get all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Rapidly register 3 more consumers (within the debounce window).
    let _c1 = register_consumer(&store, "c-1", 10).await;
    let _c2 = register_consumer(&store, "c-2", 10).await;
    let _c3 = register_consumer(&store, "c-3", 10).await;

    let consumer_names: Vec<String> = (0..4).map(|i| format!("c-{i}")).collect();

    // Drive handoffs as they appear and wait for convergence.
    let check_store = Arc::clone(&store);
    let check_names = consumer_names.clone();
    wait_for_condition(Duration::from_secs(30), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        let names = check_names.clone();
        async move {
            // Drive any pending handoffs.
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            for h in &handoffs {
                match h.phase {
                    HandoffPhase::Warming => {
                        signal_ready(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Complete => {
                        signal_released(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Ready => {}
                }
            }

            let assignments = store.list_assignments().await.unwrap_or_default();
            let all_assigned = assignments.len() == NUM_PARTITIONS as usize;
            let no_handoffs = store.list_handoffs().await.unwrap_or_default().is_empty();
            let all_consumers_have_partitions = names
                .iter()
                .all(|name| assignments.iter().any(|a| a.owner == *name));

            // Check strategy is satisfied (no more moves needed).
            if all_assigned && no_handoffs && all_consumers_have_partitions {
                let current: HashMap<u32, String> = assignments
                    .iter()
                    .map(|a| (a.partition, a.owner.clone()))
                    .collect();
                let strategy = kafka_assigner::strategy::StickyBalancedStrategy;
                let desired =
                    assignment_coordination::strategy::AssignmentStrategy::compute_assignments(
                        &strategy,
                        &current,
                        &names,
                        NUM_PARTITIONS,
                    );
                let moves =
                    assignment_coordination::util::compute_required_handoffs(&current, &desired);
                return moves.is_empty();
            }
            false
        }
    })
    .await;

    // Verify every consumer owns partitions.
    let assignments = store.list_assignments().await.unwrap();
    for name in &consumer_names {
        assert!(
            assignments.iter().any(|a| a.owner == *name),
            "{name} should own at least one partition"
        );
    }

    // StickyBalancedStrategy guarantees even distribution.
    let per_consumer = NUM_PARTITIONS as usize / consumer_names.len();
    for name in &consumer_names {
        assert_eq!(
            assignments.iter().filter(|a| a.owner == *name).count(),
            per_consumer,
            "expected even distribution for {name}"
        );
    }

    cancel.cancel();
}
