use stateright::Checker;
use stateright::Model;

use personhog_stateright::model::HandoffModel;
use personhog_stateright::types::{ModelConfig, ProtocolVariant};

/// Run the checker to completion, return (property_name, has_counterexample) pairs.
fn check_model(config: ModelConfig) -> Vec<(&'static str, bool)> {
    let model = HandoffModel::new(config);
    let checker = model.checker().spawn_bfs().join();
    let discoveries = checker.discoveries();
    let properties = checker.model().properties();

    properties
        .iter()
        .map(|p| (p.name, discoveries.contains_key(p.name)))
        .collect()
}

fn property_holds(results: &[(&str, bool)], name: &str) -> bool {
    results
        .iter()
        .find(|(n, _)| *n == name)
        .map_or(false, |(_, has_counterexample)| !has_counterexample)
}

// ============================================================
// Scenario 1: Scale-up with 1 router
// ============================================================

#[test]
fn current_protocol_scale_up_1_router_split_ownership() {
    let config = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 1,
        allow_crashes: false,
        protocol: ProtocolVariant::Current,
    };
    let results = check_model(config);

    assert!(
        !property_holds(&results, "single_pod_ownership"),
        "Current protocol should violate single_pod_ownership"
    );
}

#[test]
fn early_release_scale_up_1_router_no_split() {
    let config = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 1,
        allow_crashes: false,
        protocol: ProtocolVariant::EarlyRelease,
    };
    let results = check_model(config);

    assert!(
        property_holds(&results, "single_pod_ownership"),
        "EarlyRelease protocol should satisfy single_pod_ownership"
    );

    assert!(
        property_holds(&results, "no_split_writes"),
        "EarlyRelease protocol should satisfy no_split_writes"
    );

    let writes_to_owners = property_holds(&results, "writes_only_to_owners");
    println!(
        "EarlyRelease writes_only_to_owners (1 router): {}",
        if writes_to_owners {
            "PASS"
        } else {
            "FAIL (expected - stale routing window)"
        }
    );
}

// ============================================================
// Scenario 2: Multi-router scale-up
// 2 routers widens the split window in Current protocol
// ============================================================

#[test]
fn current_protocol_scale_up_2_routers_split_writes() {
    let config = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 2,
        allow_crashes: false,
        protocol: ProtocolVariant::Current,
    };
    let results = check_model(config);

    assert!(
        !property_holds(&results, "single_pod_ownership"),
        "Current protocol should violate single_pod_ownership"
    );

    assert!(
        !property_holds(&results, "no_split_writes"),
        "Current protocol should violate no_split_writes with 2 routers"
    );
}

#[test]
fn early_release_scale_up_2_routers_no_split() {
    let config = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 2,
        allow_crashes: false,
        protocol: ProtocolVariant::EarlyRelease,
    };
    let results = check_model(config);

    assert!(
        property_holds(&results, "single_pod_ownership"),
        "EarlyRelease should satisfy single_pod_ownership with 2 routers"
    );

    assert!(
        property_holds(&results, "no_split_writes"),
        "EarlyRelease should satisfy no_split_writes with 2 routers"
    );

    assert!(
        property_holds(&results, "router_agreement_when_stable"),
        "Routers should agree with etcd when no handoffs in flight"
    );
}

// ============================================================
// Scenario 3: Scale-up with 3 partitions (more handoff targets)
// ============================================================

#[test]
fn early_release_3_partitions() {
    let config = ModelConfig {
        num_partitions: 3,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 1,
        allow_crashes: false,
        protocol: ProtocolVariant::EarlyRelease,
    };
    let results = check_model(config);

    assert!(
        property_holds(&results, "single_pod_ownership"),
        "EarlyRelease should satisfy single_pod_ownership with 3 partitions"
    );

    assert!(
        property_holds(&results, "no_split_writes"),
        "EarlyRelease should satisfy no_split_writes with 3 partitions"
    );
}

// ============================================================
// Scenario 4: Scale down (3 pods, one drains)
// ============================================================

#[test]
fn early_release_scale_down() {
    let config = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 3,
        num_scaling_pods: 0,
        num_routers: 1,
        allow_crashes: false,
        protocol: ProtocolVariant::EarlyRelease,
    };
    let results = check_model(config);

    assert!(
        property_holds(&results, "single_pod_ownership"),
        "EarlyRelease should satisfy single_pod_ownership during scale-down"
    );

    assert!(
        property_holds(&results, "no_split_writes"),
        "EarlyRelease should satisfy no_split_writes during scale-down"
    );
}

// ============================================================
// Scenario 5: Pod crash during handoff
// ============================================================

#[test]
fn early_release_crash_during_handoff() {
    let config = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 1,
        allow_crashes: true,
        protocol: ProtocolVariant::EarlyRelease,
    };
    let results = check_model(config);

    assert!(
        property_holds(&results, "single_pod_ownership"),
        "EarlyRelease should satisfy single_pod_ownership even with crashes"
    );

    assert!(
        property_holds(&results, "no_split_writes"),
        "EarlyRelease should satisfy no_split_writes even with crashes"
    );

    let orphaned = property_holds(&results, "no_orphaned_partitions");
    println!(
        "EarlyRelease with crashes - no_orphaned_partitions: {}",
        if orphaned {
            "PASS"
        } else {
            "FAIL (may be expected during crash recovery)"
        }
    );
}

#[test]
fn current_protocol_crash_during_handoff() {
    let config = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 1,
        allow_crashes: true,
        protocol: ProtocolVariant::Current,
    };
    let results = check_model(config);

    assert!(
        !property_holds(&results, "single_pod_ownership"),
        "Current protocol should violate single_pod_ownership"
    );
}

// ============================================================
// Scenario 6: Draining pod targeted by in-flight handoff
// A pod that was Ready when a handoff started can transition
// to Draining while the handoff is still in flight.
// ============================================================

#[test]
fn draining_pod_as_handoff_target_both_protocols() {
    // This scenario: pod 0 owns all, pod 1 joins, coordinator creates
    // handoffs to pod 1, then pod 1 starts draining mid-handoff.
    for protocol in [ProtocolVariant::Current, ProtocolVariant::EarlyRelease] {
        let config = ModelConfig {
            num_partitions: 2,
            num_initial_pods: 1,
            num_scaling_pods: 1,
            num_routers: 1,
            allow_crashes: false,
            protocol,
        };
        let results = check_model(config);

        assert!(
            !property_holds(&results, "draining_pod_gains_no_partitions"),
            "{protocol:?}: should find counterexample where draining pod is handoff target"
        );
    }
}

// ============================================================
// Scenario 7: Assignment-ownership divergence after crash
// When a pod crashes mid-handoff (EarlyRelease), the old owner
// may have already released the partition. Cleaning up the stale
// handoff leaves the assignment pointing at the old owner who
// no longer has it in pod_owned.
// ============================================================

#[test]
fn crash_causes_assignment_ownership_divergence() {
    for protocol in [ProtocolVariant::Current, ProtocolVariant::EarlyRelease] {
        let config = ModelConfig {
            num_partitions: 2,
            num_initial_pods: 1,
            num_scaling_pods: 1,
            num_routers: 1,
            allow_crashes: true,
            protocol,
        };
        let results = check_model(config);

        let holds = property_holds(&results, "assignment_ownership_agreement");
        println!(
            "{protocol:?} with crashes - assignment_ownership_agreement: {}",
            if holds { "PASS" } else { "FAIL" }
        );
    }
}

// ============================================================
// Scenario 8: Larger cluster (3 initial + 1 scaling, 2 routers)
// Tests that the new invariants hold at larger scale.
// ============================================================

#[test]
fn early_release_larger_cluster() {
    let config = ModelConfig {
        num_partitions: 3,
        num_initial_pods: 2,
        num_scaling_pods: 1,
        num_routers: 2,
        allow_crashes: false,
        protocol: ProtocolVariant::EarlyRelease,
    };
    let results = check_model(config);

    assert!(
        property_holds(&results, "no_split_writes"),
        "EarlyRelease should satisfy no_split_writes with larger cluster"
    );
    assert!(
        property_holds(&results, "single_pod_ownership"),
        "EarlyRelease should satisfy single_pod_ownership with larger cluster"
    );
    assert!(
        property_holds(&results, "handoff_consistent_with_assignment"),
        "Handoff should be consistent with assignment in larger cluster"
    );
    assert!(
        property_holds(&results, "no_write_to_unregistered_pod"),
        "No writes to unregistered pods in larger cluster"
    );
}

// ============================================================
// Summary: print results for both protocols side by side
// ============================================================

#[test]
fn protocol_comparison_summary() {
    let invariants = [
        "no_split_writes",
        "writes_only_to_owners",
        "no_orphaned_partitions",
        "valid_handoff_state",
        "single_pod_ownership",
        "router_agreement_when_stable",
        "no_write_to_unregistered_pod",
        "assignment_ownership_agreement",
        "handoff_consistent_with_assignment",
        "draining_pod_gains_no_partitions",
        "converges_to_stable",
    ];

    println!();
    println!("============================================================");
    println!("Protocol Comparison");
    println!("============================================================");

    // --- 2 partitions, 1+1 pods, 1 router ---
    let base = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 1,
        allow_crashes: false,
        protocol: ProtocolVariant::Current,
    };
    let current_1r = check_model(base.clone());
    let early_1r = check_model(ModelConfig {
        protocol: ProtocolVariant::EarlyRelease,
        ..base
    });

    let print_table = |label: &str, current: &[(&str, bool)], early: &[(&str, bool)]| {
        println!(
            "\n{:<40} {:>10} {:>14}",
            label, "Current", "EarlyRelease"
        );
        println!("{:-<40} {:-<10} {:-<14}", "", "", "");
        for name in &invariants {
            let c = if property_holds(current, name) {
                "PASS"
            } else {
                "FAIL"
            };
            let e = if property_holds(early, name) {
                "PASS"
            } else {
                "FAIL"
            };
            println!("{:<40} {:>10} {:>14}", name, c, e);
        }
    };

    print_table(
        "2 partitions, 2 pods, 1 router",
        &current_1r,
        &early_1r,
    );

    // --- 2 partitions, 1+1 pods, 2 routers ---
    let base2 = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 2,
        allow_crashes: false,
        protocol: ProtocolVariant::Current,
    };
    let current_2r = check_model(base2.clone());
    let early_2r = check_model(ModelConfig {
        protocol: ProtocolVariant::EarlyRelease,
        ..base2
    });

    print_table(
        "2 partitions, 2 pods, 2 routers",
        &current_2r,
        &early_2r,
    );

    // --- With crashes ---
    let base_crash = ModelConfig {
        num_partitions: 2,
        num_initial_pods: 1,
        num_scaling_pods: 1,
        num_routers: 1,
        allow_crashes: true,
        protocol: ProtocolVariant::Current,
    };
    let current_crash = check_model(base_crash.clone());
    let early_crash = check_model(ModelConfig {
        protocol: ProtocolVariant::EarlyRelease,
        ..base_crash
    });

    print_table(
        "2 part, 2 pods, 1 rtr, crashes",
        &current_crash,
        &early_crash,
    );

    println!();
}
