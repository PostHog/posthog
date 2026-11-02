//! The seal duty against real etcd and Kafka: which partitions a leader
//! seals during a changelog migration, and what it acks.

mod common;

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use personhog_coordination::types::{
    AssignmentStatus, ChangelogTarget, MigrationPhase, MigrationState, PartitionAssignment,
    PodStatus, RegisteredPod,
};
use personhog_leader::migration::SealDuty;

use common::{owned_broker_topic, test_fenced_producers, test_store};

fn registered(pod_name: &str) -> RegisteredPod {
    RegisteredPod {
        pod_name: pod_name.to_string(),
        generation: String::new(),
        status: PodStatus::Ready,
        registered_at: 0,
        last_heartbeat: 0,
        controller: None,
        advertise_address: None,
    }
}

fn now_millis() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64
}

fn assignment(partition: u32, owner: &str) -> PartitionAssignment {
    PartitionAssignment {
        partition,
        owner: owner.to_string(),
        advertise_address: None,
        status: AssignmentStatus::Active,
    }
}

/// A holder restarted mid-Sealing owns partitions it never loaded. It still
/// seals them: its peers see a registered owner and leave them to it.
#[tokio::test]
async fn a_pod_seals_the_partitions_it_owns_by_assignment_without_a_capture() {
    let store = test_store("seal-duty-assignment").await;
    let old = owned_broker_topic(2).await;
    let lease = store.grant_lease(60).await.unwrap();
    for pod in ["leader-a", "leader-b"] {
        store.register_pod(&registered(pod), lease).await.unwrap();
    }
    store
        .put_assignments(&[assignment(0, "leader-a"), assignment(1, "leader-b")])
        .await
        .unwrap();
    let migration = MigrationState {
        id: "m-1".to_string(),
        from: ChangelogTarget {
            topic: old.topic.clone(),
            partitions: 2,
        },
        to: ChangelogTarget {
            topic: format!("{}_g2", old.topic),
            partitions: 4,
        },
        phase: MigrationPhase::Sealing,
        // Inside the seal grace, so peers still leave each other's partitions alone.
        created_at_ms: now_millis(),
        phase_entered_at_ms: now_millis(),
        blocking: Vec::new(),
        cancel_reason: None,
    };
    assert!(store.create_migration(&migration).await.unwrap());

    let duty = SealDuty {
        store: Arc::clone(&store),
        pod_name: "leader-a".to_string(),
        fenced: Arc::new(test_fenced_producers()),
    };
    let mut sealed = HashSet::new();
    duty.tick(&migration, &mut sealed, &mut None).await.unwrap();

    let acks = store.list_seal_acks().await.unwrap();
    let ack = acks
        .iter()
        .find(|a| a.pod_name == "leader-a")
        .expect("the pod acks its pass");
    assert!(
        ack.sealed.contains(&0),
        "its own partition is sealed although nothing is loaded: {ack:?}"
    );
    assert!(
        !ack.sealed.contains(&1),
        "a registered peer's partition is left to the peer: {ack:?}"
    );
}

/// A registered holder that cannot seal must not hold the fleet: once the
/// seal is overdue, its peers seal its partitions too.
#[tokio::test]
async fn a_registered_peers_partition_is_sealed_once_the_seal_is_overdue() {
    let store = test_store("seal-duty-overdue").await;
    let old = owned_broker_topic(2).await;
    let lease = store.grant_lease(60).await.unwrap();
    for pod in ["leader-a", "leader-b"] {
        store.register_pod(&registered(pod), lease).await.unwrap();
    }
    store
        .put_assignments(&[assignment(0, "leader-a"), assignment(1, "leader-b")])
        .await
        .unwrap();
    let now_ms = now_millis();
    let migration = MigrationState {
        id: "m-2".to_string(),
        from: ChangelogTarget {
            topic: old.topic.clone(),
            partitions: 2,
        },
        to: ChangelogTarget {
            topic: format!("{}_g2", old.topic),
            partitions: 4,
        },
        phase: MigrationPhase::Sealing,
        created_at_ms: now_ms - 20_000,
        phase_entered_at_ms: now_ms - 10_000,
        blocking: Vec::new(),
        cancel_reason: None,
    };
    assert!(store.create_migration(&migration).await.unwrap());
    let duty = SealDuty {
        store: Arc::clone(&store),
        pod_name: "leader-a".to_string(),
        fenced: Arc::new(test_fenced_producers()),
    };
    let mut sealed = HashSet::new();
    let mut acked = None;
    // Once its own ack reports the partition sealed, it is no longer overdue;
    // the report must keep it rather than flap between passes.
    let mut revision_after_first = None;
    for pass in 0..2 {
        duty.tick(&migration, &mut sealed, &mut acked)
            .await
            .unwrap();
        // An unchanged report is not rewritten, so it wakes no one.
        let revision = store.seal_ack_mod_revision("leader-a").await.unwrap();
        if pass == 0 {
            revision_after_first = revision;
        } else {
            assert_eq!(
                revision, revision_after_first,
                "the second pass wrote to etcd"
            );
        }
        let acks = store.list_seal_acks().await.unwrap();
        let ack = acks
            .iter()
            .find(|a| a.pod_name == "leader-a")
            .expect("the pod acks its pass");
        assert!(
            ack.sealed.contains(&1),
            "pass {pass}: the overdue peer's partition stays reported sealed: {ack:?}"
        );
    }
}

/// A seal is acked as it lands, so a pod still working through its partitions
/// does not look overdue to its peers.
#[tokio::test]
async fn each_seal_is_acked_before_the_pass_ends() {
    let store = test_store("seal-duty-early-ack").await;
    let old = owned_broker_topic(2).await;
    let lease = store.grant_lease(60).await.unwrap();
    store
        .register_pod(&registered("leader-a"), lease)
        .await
        .unwrap();
    store
        .put_assignments(&[assignment(0, "leader-a"), assignment(1, "leader-a")])
        .await
        .unwrap();
    let migration = MigrationState {
        id: "m-1".to_string(),
        from: ChangelogTarget {
            topic: old.topic.clone(),
            partitions: 2,
        },
        to: ChangelogTarget {
            topic: format!("{}_g2", old.topic),
            partitions: 4,
        },
        phase: MigrationPhase::Sealing,
        created_at_ms: now_millis(),
        phase_entered_at_ms: now_millis(),
        blocking: Vec::new(),
        cancel_reason: None,
    };
    assert!(store.create_migration(&migration).await.unwrap());

    let fenced = Arc::new(test_fenced_producers());
    // A dial in flight holds partition 1's seal until the init timeout.
    fenced.stage_connecting_for_test(1, Duration::ZERO);
    let duty = SealDuty {
        store: Arc::clone(&store),
        pod_name: "leader-a".to_string(),
        fenced,
    };
    let pass = tokio::spawn(async move {
        let mut sealed = HashSet::new();
        duty.tick(&migration, &mut sealed, &mut None).await.unwrap();
    });

    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let acks = store.list_seal_acks().await.unwrap();
            if acks.iter().any(|a| a.sealed.contains(&0)) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .expect("partition 0 is acked while partition 1 is still sealing");
    assert!(!pass.is_finished(), "the pass is still sealing partition 1");
    pass.abort();
}

/// A preconnect the fencing sweep discards is dialed again on the next pass.
#[tokio::test]
async fn a_swept_preconnect_is_dialed_again_on_the_next_pass() {
    let store = test_store("seal-duty-preconnect").await;
    let old = owned_broker_topic(1).await;
    let lease = store.grant_lease(60).await.unwrap();
    store
        .register_pod(&registered("leader-a"), lease)
        .await
        .unwrap();
    store
        .put_assignments(&[assignment(0, "leader-a")])
        .await
        .unwrap();
    let migration = MigrationState {
        id: "m-1".to_string(),
        from: ChangelogTarget {
            topic: old.topic.clone(),
            partitions: 1,
        },
        to: ChangelogTarget {
            topic: format!("{}_g2", old.topic),
            partitions: 2,
        },
        phase: MigrationPhase::Draining,
        created_at_ms: now_millis(),
        phase_entered_at_ms: now_millis(),
        blocking: Vec::new(),
        cancel_reason: None,
    };
    assert!(store.create_migration(&migration).await.unwrap());
    let fenced = Arc::new(test_fenced_producers());
    let duty = SealDuty {
        store: Arc::clone(&store),
        pod_name: "leader-a".to_string(),
        fenced: Arc::clone(&fenced),
    };
    let cancel = tokio_util::sync::CancellationToken::new();
    tokio::spawn(duty.run(cancel.clone()));
    let prepared = || async {
        tokio::time::timeout(Duration::from_secs(10), async {
            while !fenced.has_prepared(0) {
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        })
        .await
    };

    assert!(prepared().await.is_ok(), "the duty preconnects its target");
    fenced.sweep_prepared();
    assert!(!fenced.has_prepared(0));
    assert!(
        prepared().await.is_ok(),
        "the next pass dials the swept connection again"
    );
    cancel.cancel();
}
