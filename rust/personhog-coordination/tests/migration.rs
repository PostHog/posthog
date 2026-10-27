mod common;

use std::sync::Arc;
use std::time::Duration;

use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::follow::{Follower, Reporter};
use personhog_coordination::pod::{PodConfig, PodHandle};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::StickyBalancedStrategy;
use personhog_coordination::types::{
    AssignmentPrecondition, AssignmentStatus, ChangelogConfig, ChangelogTarget, DrainReport,
    Generation, HandoffPhase, HandoffState, MigrationPhase, MigrationRequest, MigrationState,
    PartitionAssignment, SealAck,
};
use tokio_util::sync::CancellationToken;

use common::{
    coordinator_config, start_coordinator_with_config, start_coordinator_with_deadline, start_pod,
    start_pod_with_hanging_drain, start_router, test_store, wait_for_condition, HandoffEvent,
    MockHandoffHandler, PodHandles, POLL_INTERVAL, WAIT_TIMEOUT,
};

const PARTITIONS: u32 = 4;
const TOPIC: &str = "personhog_updates_test";

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock")
        .as_millis() as i64
}

fn handoff(partition: u32, pod: &str, phase: HandoffPhase, config_epoch: u64) -> HandoffState {
    let now_ms = now_ms();
    HandoffState {
        partition,
        old_owner: Some(pod.to_string()),
        new_owner: pod.to_string(),
        new_owner_address: None,
        phase,
        started_at: now_ms / 1000,
        handoff_id: format!("h-{partition}"),
        freeze_quorum: Some(Vec::new()),
        freeze_quorum_ref: None,
        created_at_ms: now_ms,
        phase_entered_at_ms: now_ms,
        held_by: None,
        config_epoch,
    }
}

fn assignment(partition: u32, owner: &str) -> PartitionAssignment {
    PartitionAssignment {
        partition,
        owner: owner.to_string(),
        advertise_address: None,
        status: AssignmentStatus::Active,
    }
}

fn start_ticking_pod(
    store: Arc<PersonhogStore>,
    name: &str,
    cancel: CancellationToken,
) -> PodHandles {
    let (handler, events) = MockHandoffHandler::new();
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
            reconcile_interval: Duration::from_millis(200),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

async fn events_of(pod: &PodHandles) -> Vec<HandoffEvent> {
    pod.events.lock().await.clone()
}

#[tokio::test]
async fn a_held_handoff_stops_in_draining_and_outlives_the_deadline() {
    let store = test_store("migration-held").await;
    let cancel = CancellationToken::new();
    store
        .seed_changelog_config(TOPIC, PARTITIONS, "personhog-writer")
        .await
        .unwrap();

    // Set up before the coordinator looks: a balanced world plans nothing.
    store
        .put_assignments(&[
            assignment(0, "writer-0"),
            assignment(1, "writer-ghost"),
            assignment(2, "writer-0"),
            assignment(3, "writer-0"),
        ])
        .await
        .unwrap();
    for (partition, holder) in [(0, "writer-0"), (1, "writer-ghost")] {
        let mut held = handoff(partition, holder, HandoffPhase::Freezing, 1);
        held.held_by = Some("m-1".to_string());
        store.put_handoff(&held).await.unwrap();
    }

    let deadline = Duration::from_millis(500);
    let _coord = start_coordinator_with_deadline(
        Arc::clone(&store),
        "coordinator-0",
        10,
        deadline,
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    let pod = start_pod(Arc::clone(&store), "writer-0", cancel.clone());

    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let pod_events = Arc::clone(&pod.events);
        async move { pod_events.lock().await.contains(&HandoffEvent::Drained(0)) }
    })
    .await;

    tokio::time::sleep(deadline * 4).await;
    let handoffs = store.list_handoffs().await.unwrap();
    assert_eq!(handoffs.len(), 2, "{handoffs:?}");
    for h in &handoffs {
        assert_eq!(h.phase, HandoffPhase::Draining, "partition {}", h.partition);
        assert_eq!(h.held_by.as_deref(), Some("m-1"));
        assert_eq!(h.handoff_id, format!("h-{}", h.partition));
    }
    let events = events_of(&pod).await;
    let drained_at = events
        .iter()
        .position(|e| *e == HandoffEvent::Drained(0))
        .unwrap();
    assert!(
        !events[drained_at..].contains(&HandoffEvent::Warmed(0)),
        "a held partition re-warmed: {events:?}"
    );
    cancel.cancel();
}

#[tokio::test]
async fn an_acquisition_parks_until_the_config_reaches_the_handoffs_epoch() {
    let store = test_store("migration-park").await;
    let cancel = CancellationToken::new();
    store
        .seed_changelog_config(TOPIC, PARTITIONS, "personhog-writer")
        .await
        .unwrap();
    let pod = start_ticking_pod(Arc::clone(&store), "writer-0", cancel.clone());

    let mut fresh = handoff(0, "writer-0", HandoffPhase::Warming, 2);
    fresh.old_owner = None;
    store.put_handoff(&fresh).await.unwrap();

    tokio::time::sleep(Duration::from_secs(1)).await;
    assert!(
        !events_of(&pod).await.contains(&HandoffEvent::Warmed(0)),
        "warmed under a config older than the handoff's epoch"
    );
    assert!(store.list_warmed_acks(0).await.unwrap().is_empty());

    store
        .put_changelog_config(&ChangelogConfig {
            topic: TOPIC.to_string(),
            partitions: PARTITIONS,
            epoch: 2,
            writer_group: String::new(),
            retire_groups: vec![],
            draining: Vec::new(),
        })
        .await
        .unwrap();
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move { !store.list_warmed_acks(0).await.unwrap().is_empty() }
    })
    .await;
    assert!(events_of(&pod).await.contains(&HandoffEvent::Warmed(0)));
    cancel.cancel();
}

// ── The saga ────────────────────────────────────────────────────

const TOPIC_V2: &str = "personhog_updates_test_v2";

fn migration(id: &str, to_partitions: u32) -> MigrationState {
    let now_ms = now_ms();
    MigrationState {
        id: id.to_string(),
        from: ChangelogTarget {
            topic: TOPIC.to_string(),
            partitions: PARTITIONS,
        },
        to: ChangelogTarget {
            topic: TOPIC_V2.to_string(),
            partitions: to_partitions,
        },
        phase: MigrationPhase::Freezing,
        created_at_ms: now_ms,
        phase_entered_at_ms: now_ms,
        blocking: vec![],
        cancel_reason: None,
    }
}

async fn wait_for_phase(store: &Arc<PersonhogStore>, phase: MigrationPhase) {
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(store);
        async move {
            store
                .get_migration()
                .await
                .unwrap()
                .is_some_and(|m| m.phase == phase)
        }
    })
    .await;
}

/// A request that never starts leaves no saga record; wait for its history entry.
async fn wait_for_rejection(store: &Arc<PersonhogStore>, id: &str) -> MigrationState {
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(store);
        let id = id.to_string();
        async move {
            store
                .list_migration_history()
                .await
                .unwrap()
                .iter()
                .any(|m| m.id == id)
        }
    })
    .await;
    store
        .list_migration_history()
        .await
        .unwrap()
        .into_iter()
        .find(|m| m.id == id)
        .expect("rejected record")
}

async fn wait_for_archive(store: &Arc<PersonhogStore>, id: &str) -> MigrationState {
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(store);
        async move { store.get_migration().await.unwrap().is_none() }
    })
    .await;
    store
        .list_migration_history()
        .await
        .unwrap()
        .into_iter()
        .find(|m| m.id == id)
        .expect("archived record")
}

async fn wait_for_steady_state(store: &Arc<PersonhogStore>, partitions: u32) {
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(store);
        async move {
            store.list_handoffs().await.unwrap().is_empty()
                && store.list_assignments().await.unwrap().len() == partitions as usize
        }
    })
    .await;
}

async fn ack_seal(store: &PersonhogStore, id: &str, pod: &str, partitions: std::ops::Range<u32>) {
    store
        .put_seal_ack(&SealAck {
            migration_id: id.to_string(),
            pod_name: pod.to_string(),
            sealed: partitions.collect(),
        })
        .await
        .unwrap();
}

/// Each pod acks every partition, as the leader duty does for its own and the orphaned ones.
async fn ack_seal_all(store: &PersonhogStore, id: &str, pods: &[&str]) {
    for pod in pods {
        ack_seal(store, id, pod, 0..PARTITIONS).await;
    }
}

async fn current_phase(store: &PersonhogStore) -> (MigrationPhase, Vec<String>) {
    let m = store
        .get_migration()
        .await
        .unwrap()
        .expect("migration in flight");
    (m.phase, m.blocking)
}

fn restarted(events: &[HandoffEvent], partition: u32) -> bool {
    let released = events
        .iter()
        .position(|e| *e == HandoffEvent::Released(partition));
    released.is_some_and(|at| events[at..].contains(&HandoffEvent::Warmed(partition)))
}

struct Fleet {
    store: Arc<PersonhogStore>,
    cancel: CancellationToken,
    pods: Vec<PodHandles>,
}

async fn fleet(test_name: &str) -> Fleet {
    let store = test_store(test_name).await;
    let cancel = CancellationToken::new();
    store
        .seed_changelog_config(TOPIC, PARTITIONS, "writer")
        .await
        .unwrap();
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let pods = vec![
        start_ticking_pod(Arc::clone(&store), "writer-0", cancel.clone()),
        start_ticking_pod(Arc::clone(&store), "writer-1", cancel.clone()),
    ];
    Fleet {
        store,
        cancel,
        pods,
    }
}

#[tokio::test]
async fn a_grow_migration_restarts_every_partition_over_the_new_changelog() {
    let Fleet {
        store,
        cancel,
        pods,
    } = fleet("migration-grow").await;
    let first = CancellationToken::new();
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        first.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;
    for group in ["relay", "relay", "writer", "gone"] {
        assert!(store.add_changelog_retire_group(group).await.unwrap());
    }
    for group in ["gone", "never-added"] {
        assert!(store.remove_changelog_retire_group(group).await.unwrap());
    }

    assert!(store.create_migration(&migration("m-1", 8)).await.unwrap());
    wait_for_phase(&store, MigrationPhase::Sealing).await;
    for h in store.list_handoffs().await.unwrap() {
        assert_eq!(h.held_by.as_deref(), Some("m-1"), "{h:?}");
        assert_eq!(h.phase, HandoffPhase::Draining, "{h:?}");
    }

    // A successor coordinator picks the saga up where it stands.
    first.cancel();
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-1", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    assert_eq!(
        store.get_changelog_config().await.unwrap().unwrap().epoch,
        1,
        "flipped before the seal"
    );
    ack_seal_all(&store, "m-1", &["writer-0", "writer-1"]).await;

    let archived = wait_for_archive(&store, "m-1").await;
    assert_eq!(archived.phase, MigrationPhase::Complete);
    let config = store.get_changelog_config().await.unwrap().unwrap();
    assert_eq!(config.topic, TOPIC_V2);
    assert_eq!(config.partitions, 8);
    assert_eq!(config.epoch, 2);
    assert_eq!(config.writer_group, "writer");
    assert_eq!(config.retire_groups, vec!["relay".to_string()]);
    assert_eq!(
        config.draining,
        vec![Generation {
            topic: TOPIC.to_string(),
            partitions: PARTITIONS,
            epoch: 1,
        }]
    );
    assert!(store.list_seal_acks().await.unwrap().is_empty());
    wait_for_steady_state(&store, 8).await;
    let mut events = Vec::new();
    for pod in &pods {
        events.extend(events_of(pod).await);
    }
    for partition in 0..PARTITIONS {
        assert!(
            restarted(&events, partition),
            "partition {partition} never restarted: {events:?}"
        );
        // The restart starts at Warming, so nothing drains after the release.
        let released = events
            .iter()
            .position(|e| *e == HandoffEvent::Released(partition))
            .unwrap();
        assert!(
            !events[released..].contains(&HandoffEvent::Drained(partition)),
            "partition {partition} drained again for its restart: {events:?}"
        );
    }
    // A retire lands only on the config its drain checks read.
    let (config, rev) = store
        .get_changelog_config_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    store.put_changelog_config(&config).await.unwrap();
    assert!(!store
        .retire_changelog_topic(&config, rev, TOPIC)
        .await
        .unwrap());
    let (config, rev) = store
        .get_changelog_config_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .retire_changelog_topic(&config, rev, TOPIC)
        .await
        .unwrap());
    assert!(store
        .get_changelog_config()
        .await
        .unwrap()
        .unwrap()
        .draining
        .is_empty());
    cancel.cancel();
}

#[tokio::test]
async fn a_shrink_migration_dissolves_the_partitions_past_the_new_space() {
    let Fleet {
        store,
        cancel,
        pods,
    } = fleet("migration-shrink").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;

    assert!(store.create_migration(&migration("m-1", 2)).await.unwrap());
    wait_for_phase(&store, MigrationPhase::Sealing).await;
    ack_seal_all(&store, "m-1", &["writer-0", "writer-1"]).await;

    let archived = wait_for_archive(&store, "m-1").await;
    assert_eq!(archived.phase, MigrationPhase::Complete);
    wait_for_steady_state(&store, 2).await;
    let owned: Vec<u32> = store
        .list_assignments()
        .await
        .unwrap()
        .iter()
        .map(|a| a.partition)
        .collect();
    assert_eq!(owned, vec![0, 1]);
    let mut events = Vec::new();
    for pod in &pods {
        events.extend(events_of(pod).await);
    }
    for partition in [2, 3] {
        assert!(
            events.contains(&HandoffEvent::Released(partition)),
            "{events:?}"
        );
        assert!(
            !restarted(&events, partition),
            "a dissolved partition re-warmed: {events:?}"
        );
    }
    cancel.cancel();
}

#[tokio::test]
async fn a_migration_past_its_pre_flip_deadline_cancels_and_resumes_in_place() {
    let store = test_store("migration-deadline").await;
    let cancel = CancellationToken::new();
    store
        .seed_changelog_config(TOPIC, PARTITIONS, "writer")
        .await
        .unwrap();
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());
    let pod = start_pod_with_hanging_drain(Arc::clone(&store), "writer-0", 0, 10, cancel.clone());
    let mut config = coordinator_config("coordinator-0", 10, Duration::from_secs(86_400));
    config.migration_pre_flip_deadline = Duration::from_secs(2);
    start_coordinator_with_config(
        Arc::clone(&store),
        config,
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;

    assert!(store.create_migration(&migration("m-1", 8)).await.unwrap());
    wait_for_phase(&store, MigrationPhase::Draining).await;
    let archived = wait_for_archive(&store, "m-1").await;
    assert_eq!(archived.phase, MigrationPhase::Cancelled);
    assert_eq!(archived.cancel_reason.as_deref(), Some("pre_flip_deadline"));
    assert_eq!(
        store.get_changelog_config().await.unwrap().unwrap().epoch,
        1
    );
    wait_for_steady_state(&store, PARTITIONS).await;
    let events = events_of(&pod).await;
    assert!(
        !events
            .iter()
            .any(|e| matches!(e, HandoffEvent::Released(_))),
        "a cancelled migration released a partition: {events:?}"
    );
    assert!(store.list_seal_acks().await.unwrap().is_empty());
    cancel.cancel();
}

#[tokio::test]
async fn a_holder_dying_during_sealing_is_sealed_by_its_peers_and_replaced() {
    let Fleet {
        store,
        cancel,
        pods,
    } = fleet("migration-holder-died").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;

    assert!(store.create_migration(&migration("m-1", 8)).await.unwrap());
    wait_for_phase(&store, MigrationPhase::Sealing).await;
    let mut victim = pods.into_iter().nth(1).unwrap();
    victim.join_handle.take().unwrap().abort();
    store.delete_pod("writer-1").await.unwrap();
    ack_seal_all(&store, "m-1", &["writer-0"]).await;

    let archived = wait_for_archive(&store, "m-1").await;
    assert_eq!(archived.phase, MigrationPhase::Complete);
    assert_eq!(
        store.get_changelog_config().await.unwrap().unwrap().epoch,
        2
    );
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            let assignments = store.list_assignments().await.unwrap();
            assignments.len() == 8
                && assignments.iter().all(|a| a.owner == "writer-0")
                && store.list_handoffs().await.unwrap().is_empty()
        }
    })
    .await;
    cancel.cancel();
}

/// A holder gone before the seal cancels the saga: its hold is deleted, the
/// live holds resume in place, and the planner reassigns its partition.
#[tokio::test]
async fn a_holder_dying_before_the_seal_cancels_the_saga() {
    let Fleet {
        store,
        cancel,
        pods,
    } = fleet("migration-holder-died-draining").await;
    let holders = [
        (0, "writer-0"),
        (1, "writer-1"),
        (2, "writer-0"),
        (3, "writer-gone"),
    ];
    let assignments: Vec<_> = holders
        .iter()
        .map(|(partition, holder)| assignment(*partition, holder))
        .collect();
    store.put_assignments(&assignments).await.unwrap();
    for (partition, holder) in holders {
        let mut held = handoff(partition, holder, HandoffPhase::Draining, 1);
        held.held_by = Some("m-1".to_string());
        store.put_handoff(&held).await.unwrap();
    }
    let draining = MigrationState {
        phase: MigrationPhase::Draining,
        ..migration("m-1", 8)
    };
    assert!(store.create_migration(&draining).await.unwrap());
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );

    let archived = wait_for_archive(&store, "m-1").await;
    assert_eq!(archived.phase, MigrationPhase::Cancelled);
    assert_eq!(archived.cancel_reason.as_deref(), Some("holder_died"));
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            let assignments = store.list_assignments().await.unwrap();
            assignments.len() == PARTITIONS as usize
                && assignments.iter().all(|a| a.owner != "writer-gone")
                && store.list_handoffs().await.unwrap().is_empty()
        }
    })
    .await;
    for pod in &pods {
        let events = events_of(pod).await;
        assert!(
            !events
                .iter()
                .any(|e| matches!(e, HandoffEvent::Released(_))),
            "a cancelled migration released a partition: {events:?}"
        );
    }
    assert_eq!(
        store.get_changelog_config().await.unwrap().unwrap().epoch,
        1
    );
    cancel.cancel();
}

#[tokio::test]
async fn a_request_that_fails_admission_is_rejected_with_its_reason() {
    let Fleet { store, cancel, .. } = fleet("migration-admission").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;

    let mut same_topic = request("m-1", 8);
    same_topic.to.topic = TOPIC.to_string();
    assert!(store.create_migration_request(&same_topic).await.unwrap());
    let archived = wait_for_rejection(&store, "m-1").await;
    assert_eq!(archived.phase, MigrationPhase::Cancelled);
    assert_eq!(archived.blocking, vec!["same_topic".to_string()]);
    assert!(store.list_handoffs().await.unwrap().is_empty());
    assert_eq!(
        store.get_changelog_config().await.unwrap().unwrap().epoch,
        1
    );
    cancel.cancel();
}

const TOPIC_V0: &str = "personhog_updates_test_v0";

fn draining_config(retire_groups: &[&str]) -> ChangelogConfig {
    ChangelogConfig {
        topic: TOPIC.to_string(),
        partitions: PARTITIONS,
        epoch: 1,
        writer_group: "writer".to_string(),
        retire_groups: retire_groups.iter().map(|g| g.to_string()).collect(),
        draining: vec![Generation {
            topic: TOPIC_V0.to_string(),
            partitions: PARTITIONS,
            epoch: 0,
        }],
    }
}

fn drain_report(topic: &str, group: &str) -> DrainReport {
    DrainReport {
        topic: topic.to_string(),
        group: group.to_string(),
        reported_by: format!("{group}-0"),
        reported_at_ms: now_ms(),
    }
}

async fn wait_for_request_waiting(store: &Arc<PersonhogStore>, waiting: &[&str]) {
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(store);
        let waiting: Vec<String> = waiting.iter().map(|w| w.to_string()).collect();
        async move {
            store
                .get_migration_request_with_mod_revision()
                .await
                .unwrap()
                .is_some_and(|(r, _)| r.waiting == waiting)
        }
    })
    .await;
}

/// A request made while a generation drains waits, naming the groups that have
/// not reported it; once every gated group has, the coordinator retires the
/// generation, drops its reports and late ones for other topics, and starts the request.
#[tokio::test]
async fn a_drained_generation_retires_once_every_gated_group_reports_it() {
    let Fleet { store, cancel, .. } = fleet("migration-auto-retire").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;
    store
        .put_changelog_config(&draining_config(&["relay"]))
        .await
        .unwrap();
    store
        .put_drain_report(&drain_report("personhog_updates_test_retired", "writer"))
        .await
        .unwrap();

    assert!(store
        .create_migration_request(&request("m-1", 8))
        .await
        .unwrap());
    wait_for_request_waiting(
        &store,
        &["personhog_updates_test_v0: waiting on drain reports from writer, relay"],
    )
    .await;

    store
        .put_drain_report(&drain_report(TOPIC_V0, "writer"))
        .await
        .unwrap();
    wait_for_request_waiting(
        &store,
        &["personhog_updates_test_v0: waiting on drain reports from relay"],
    )
    .await;
    assert_eq!(
        store
            .get_changelog_config()
            .await
            .unwrap()
            .unwrap()
            .draining
            .len(),
        1
    );

    store
        .put_drain_report(&drain_report(TOPIC_V0, "relay"))
        .await
        .unwrap();
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move { store.get_migration().await.unwrap().is_some() }
    })
    .await;
    let config = store.get_changelog_config().await.unwrap().unwrap();
    assert!(config.draining.is_empty());
    assert_eq!(config.epoch, 1);
    assert!(store.list_drain_reports().await.unwrap().is_empty());
    cancel.cancel();
}

/// The coordinator's retire lands only while no saga exists, and takes the
/// generation's drain reports with it.
#[tokio::test]
async fn a_retire_lands_only_while_no_saga_exists() {
    let store = test_store("migration-retire-guard").await;
    store
        .put_changelog_config(&draining_config(&[]))
        .await
        .unwrap();
    store
        .put_drain_report(&drain_report(TOPIC_V0, "writer"))
        .await
        .unwrap();
    assert!(store.create_migration(&migration("m-1", 8)).await.unwrap());

    let (config, rev) = store
        .get_changelog_config_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(!store
        .retire_changelog_topic(&config, rev, TOPIC_V0)
        .await
        .unwrap());
    assert_eq!(
        store
            .get_changelog_config()
            .await
            .unwrap()
            .unwrap()
            .draining
            .len(),
        1
    );

    let (migration, migration_rev) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .archive_migration(&migration, migration_rev, MigrationPhase::Cancelled)
        .await
        .unwrap());
    assert!(store
        .retire_changelog_topic(&config, rev, TOPIC_V0)
        .await
        .unwrap());
    assert!(store
        .get_changelog_config()
        .await
        .unwrap()
        .unwrap()
        .draining
        .is_empty());
    assert!(store.list_drain_reports().await.unwrap().is_empty());
}

#[tokio::test]
async fn the_flip_waits_for_every_partition_to_be_sealed_and_cannot_be_cancelled() {
    let Fleet { store, cancel, .. } = fleet("migration-gates").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;
    assert!(store.create_migration(&migration("m-1", 8)).await.unwrap());
    wait_for_phase(&store, MigrationPhase::Sealing).await;

    tokio::time::sleep(Duration::from_millis(500)).await;
    let (phase, blocking) = current_phase(&store).await;
    assert_eq!(phase, MigrationPhase::Sealing);
    assert_eq!(blocking.len(), PARTITIONS as usize, "{blocking:?}");
    assert_eq!(
        store.get_changelog_config().await.unwrap().unwrap().epoch,
        1
    );
    let (_, rev) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(!store
        .cancel_migration("m-1", rev, "operator")
        .await
        .unwrap());
    assert_eq!(current_phase(&store).await.0, MigrationPhase::Sealing);

    // The gate is the union across leaders: half from one pod leaves the rest blocking.
    ack_seal(&store, "m-1", "writer-0", 0..2).await;
    tokio::time::sleep(Duration::from_millis(500)).await;
    let (phase, blocking) = current_phase(&store).await;
    assert_eq!(phase, MigrationPhase::Sealing);
    assert_eq!(blocking.len(), 2, "{blocking:?}");
    assert_eq!(
        store.get_changelog_config().await.unwrap().unwrap().epoch,
        1
    );
    ack_seal(&store, "m-1", "writer-1", 2..PARTITIONS).await;
    let archived = wait_for_archive(&store, "m-1").await;
    assert_eq!(archived.phase, MigrationPhase::Complete);
    cancel.cancel();
}

/// A plan lands only on the basis it was read on, across a migration's start and a full migration.
#[tokio::test]
async fn a_plan_lands_only_on_the_basis_it_was_read_on() {
    let store = test_store("migration-plan-basis").await;
    assert!(store
        .seed_changelog_config(TOPIC, PARTITIONS, "personhog-writer")
        .await
        .unwrap());
    let absent = |partition| vec![AssignmentPrecondition::Absent { partition }];
    let fresh = |partition| HandoffState {
        old_owner: None,
        ..handoff(partition, "leader-a", HandoffPhase::Freezing, 1)
    };
    let apply = |basis, partition| {
        let store = Arc::clone(&store);
        async move {
            store
                .apply_plan_on(
                    &basis,
                    &[fresh(partition)],
                    &[],
                    &absent(partition),
                    None,
                    128,
                )
                .await
                .unwrap()
        }
    };

    // A saga starts after the read.
    let before = store.read_plan_basis().await.unwrap();
    assert!(store.create_migration(&migration("m-1", 8)).await.unwrap());
    let stale = apply(before.clone(), 3).await;
    assert_eq!(stale.stood_down, vec![3], "{stale:?}");

    // The driver's own writes to a live saga do not move the planner's basis.
    let during = store.read_plan_basis().await.unwrap();
    let (_, rev) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .set_migration_blocking(rev, vec!["partition 0: restarting".to_string()])
        .await
        .unwrap());
    assert_eq!(apply(during, 6).await.applied, vec![6]);
    store.delete_handoff(6).await.unwrap();

    // The saga flips and is archived: the migration key is absent again.
    let flipped = ChangelogConfig {
        topic: TOPIC_V2.to_string(),
        partitions: 8,
        epoch: 2,
        writer_group: String::new(),
        retire_groups: vec![],
        draining: vec![],
    };
    store.put_changelog_config(&flipped).await.unwrap();
    let (m, rev) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .archive_migration(&m, rev, MigrationPhase::Complete)
        .await
        .unwrap());
    let aba = apply(before, 4).await;
    assert_eq!(aba.stood_down, vec![4], "{aba:?}");
    assert!(store.list_handoffs().await.unwrap().is_empty());

    let current = store.read_plan_basis().await.unwrap();
    assert_eq!(apply(current, 5).await.applied, vec![5]);
}

/// A migration pass's writes land only on the record it read: a stalled pass
/// that wakes after a successor moved or archived the saga lands nothing.
#[tokio::test]
async fn a_migration_pass_lands_nothing_once_the_record_moved() {
    let store = test_store("migration-pass-authority").await;
    assert!(store.create_migration(&migration("m-1", 8)).await.unwrap());
    let absent = |partition| vec![AssignmentPrecondition::Absent { partition }];
    let hold = |partition| HandoffState {
        held_by: Some("m-1".to_string()),
        ..handoff(partition, "leader-a", HandoffPhase::Freezing, 1)
    };
    let apply = |mod_revision, partition| {
        let store = Arc::clone(&store);
        async move {
            store
                .apply_migration_plan(
                    mod_revision,
                    &[hold(partition)],
                    &[],
                    &absent(partition),
                    None,
                    128,
                )
                .await
                .unwrap()
        }
    };

    // A successor's write moves the record.
    let (_, read) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .set_migration_blocking(read, vec!["partition 0: drain".to_string()])
        .await
        .unwrap());
    assert_eq!(apply(read, 3).await.stood_down, vec![3]);

    // A plan split across chunks stands down whole.
    let holds: Vec<HandoffState> = (10..14).map(hold).collect();
    let preconditions: Vec<AssignmentPrecondition> = (10..14).flat_map(absent).collect();
    let split = store
        .apply_migration_plan(read, &holds, &[], &preconditions, None, 3)
        .await
        .unwrap();
    assert_eq!(split.stood_down, vec![10, 11, 12, 13], "{split:?}");
    assert!(split.applied.is_empty() && split.conflicted.is_empty());

    // A successor archives the saga; the stale hold must not outlive it.
    let (m, current) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(apply(current, 4).await.applied, vec![4]);
    store.delete_handoff(4).await.unwrap();
    let (_, current) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .archive_migration(&m, current, MigrationPhase::Cancelled)
        .await
        .unwrap());
    assert_eq!(apply(current, 5).await.stood_down, vec![5]);
    assert!(store.list_handoffs().await.unwrap().is_empty());
}

fn request(id: &str, to_partitions: u32) -> MigrationRequest {
    MigrationRequest {
        id: id.to_string(),
        from: ChangelogTarget {
            topic: TOPIC.to_string(),
            partitions: PARTITIONS,
        },
        to: ChangelogTarget {
            topic: TOPIC_V2.to_string(),
            partitions: to_partitions,
        },
        requested_at_ms: now_ms(),
        seen_at_ms: None,
        waiting: vec![],
    }
}

/// The saga starts only in a transaction that proves no handoff was created
/// or changed since the coordinator saw the fleet quiet.
#[tokio::test]
async fn a_migration_starts_only_from_a_fleet_seen_quiet() {
    let store = test_store("migration-quiet-start").await;
    assert!(store
        .create_migration_request(&request("m-1", 8))
        .await
        .unwrap());
    let (req, req_rev) = store
        .get_migration_request_with_mod_revision()
        .await
        .unwrap()
        .unwrap();

    // A handoff starts between the quiet read and the start.
    let (handoffs, quiet_at) = store.list_handoffs_with_revision().await.unwrap();
    assert!(handoffs.is_empty());
    store
        .apply_plan(
            &[],
            &[handoff(3, "leader-a", HandoffPhase::Freezing, 1)],
            &[],
            &[],
            None,
            128,
        )
        .await
        .unwrap();
    assert!(!store
        .start_migration(req_rev, quiet_at, &req.start(now_ms()))
        .await
        .unwrap());
    assert!(store.get_migration().await.unwrap().is_none());

    // Once it is gone the fleet is quiet again, and the start lands.
    store.delete_handoff(3).await.unwrap();
    let (_, quiet_at) = store.list_handoffs_with_revision().await.unwrap();
    assert!(store
        .start_migration(req_rev, quiet_at, &req.start(now_ms()))
        .await
        .unwrap());
    assert_eq!(store.get_migration().await.unwrap().unwrap().id, "m-1");
    assert!(store
        .get_migration_request_with_mod_revision()
        .await
        .unwrap()
        .is_none());

    // No second request while the saga runs.
    assert!(!store
        .create_migration_request(&request("m-2", 8))
        .await
        .unwrap());
}

/// Handoffs stuck on a pod that then dies: the request waits holding nothing,
/// the planner clears the dead pod's handoffs, and only then does the saga start.
#[tokio::test]
async fn a_request_waits_holding_nothing_until_the_fleet_is_quiet() {
    let Fleet { store, cancel, .. } = fleet("migration-request-waits").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;

    // A registered pod that never warms: the planner moves partitions to it and they stick.
    let lease = store.grant_lease(60).await.unwrap();
    store
        .register_pod(
            &personhog_coordination::types::RegisteredPod {
                pod_name: "stand-in".to_string(),
                generation: String::new(),
                status: personhog_coordination::types::PodStatus::Ready,
                registered_at: 0,
                last_heartbeat: 0,
                controller: None,
                advertise_address: None,
            },
            lease,
        )
        .await
        .unwrap();
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            store
                .list_handoffs()
                .await
                .unwrap()
                .iter()
                .any(|h| h.new_owner == "stand-in")
        }
    })
    .await;
    assert!(store
        .create_migration_request(&request("m-1", 8))
        .await
        .unwrap());

    // It reports what it waits on, and holds nothing meanwhile.
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            store
                .get_migration_request_with_mod_revision()
                .await
                .unwrap()
                .is_some_and(|(r, _)| !r.waiting.is_empty())
        }
    })
    .await;
    assert!(store.get_migration().await.unwrap().is_none());
    assert!(store
        .list_handoffs()
        .await
        .unwrap()
        .iter()
        .all(|h| !h.is_held()));

    // The stand-in dies; the planner clears its handoffs, then the saga starts quiet.
    store.revoke_lease(lease).await.unwrap();
    let started = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if store.get_migration().await.unwrap().is_some() {
                assert!(
                    store
                        .list_handoffs()
                        .await
                        .unwrap()
                        .iter()
                        .all(|h| h.is_held()),
                    "the saga started with an ordinary handoff in flight"
                );
                return;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await;
    assert!(started.is_ok(), "the saga never started");
    cancel.cancel();
}

/// A request left waiting past the expiry is rejected, never started late.
#[tokio::test]
async fn a_stale_request_is_rejected_with_its_reason() {
    let Fleet { store, cancel, .. } = fleet("migration-request-expires").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;
    // The coordinator first saw it ten minutes ago.
    let stale = MigrationRequest {
        seen_at_ms: Some(now_ms() - 600_000),
        ..request("m-1", 8)
    };
    assert!(store.create_migration_request(&stale).await.unwrap());
    let archived = wait_for_rejection(&store, "m-1").await;
    assert_eq!(archived.blocking[0], "request_expired");
    assert!(store.get_migration().await.unwrap().is_none());
    cancel.cancel();
}

/// Expiry runs on the coordinator's clock: a control plane whose clock is far
/// behind still gets its request started, not rejected on arrival.
#[tokio::test]
async fn a_request_from_a_skewed_clock_is_not_expired_on_arrival() {
    let Fleet { store, cancel, .. } = fleet("migration-request-skew").await;
    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;
    let skewed = MigrationRequest {
        requested_at_ms: now_ms() - 3_600_000,
        ..request("m-1", 8)
    };
    assert!(store.create_migration_request(&skewed).await.unwrap());
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move { store.get_migration().await.unwrap().is_some() }
    })
    .await;
    cancel.cancel();
}

/// Only a completed migration retires its source topic: a request back to it
/// is refused, while a source named only by a rejected request stays usable.
#[tokio::test]
async fn only_a_completed_migration_retires_its_source_topic() {
    let Fleet { store, cancel, .. } = fleet("migration-retired-topic").await;
    let target = |topic: &str| ChangelogTarget {
        topic: topic.to_string(),
        partitions: 8,
    };
    // History, written before any coordinator runs: one completed saga away
    // from "retired", one rejected request away from TOPIC_V2.
    let mut done = migration("m-done", 8);
    done.from = target("personhog_updates_retired");
    assert!(store.create_migration(&done).await.unwrap());
    let (m, rev) = store
        .get_migration_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .archive_migration(&m, rev, MigrationPhase::Complete)
        .await
        .unwrap());
    let rejected = MigrationRequest {
        from: target(TOPIC_V2),
        ..request("m-rejected", 8)
    };
    assert!(store.create_migration_request(&rejected).await.unwrap());
    let (r, rev) = store
        .get_migration_request_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(store
        .reject_migration_request(&r, rev, "test")
        .await
        .unwrap());

    start_coordinator_with_config(
        Arc::clone(&store),
        coordinator_config("coordinator-0", 10, Duration::from_secs(86_400)),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    wait_for_steady_state(&store, PARTITIONS).await;

    let back = MigrationRequest {
        to: target("personhog_updates_retired"),
        ..request("m-back", 8)
    };
    assert!(store.create_migration_request(&back).await.unwrap());
    let refused = wait_for_rejection(&store, "m-back").await;
    assert_eq!(refused.blocking, vec!["topic_already_retired".to_string()]);

    assert!(store
        .create_migration_request(&request("m-ok", 8))
        .await
        .unwrap());
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&store);
        async move {
            store
                .get_migration()
                .await
                .unwrap()
                .is_some_and(|m| m.id == "m-ok")
        }
    })
    .await;
    cancel.cancel();
}

/// An owner that is shutting down keeps a request waiting: the fleet is quiet
/// only when every old partition's owner is registered and Ready.
#[tokio::test]
async fn a_request_waits_while_an_owner_is_draining() {
    use personhog_coordination::migration::consider_request;
    use personhog_coordination::strategy::Member;
    use personhog_coordination::types::{PodStatus, RegisteredPod};

    let store = test_store("migration-request-draining-owner").await;
    assert!(store
        .seed_changelog_config(TOPIC, PARTITIONS, "personhog-writer")
        .await
        .unwrap());
    let pod = |name: &str, status: PodStatus| RegisteredPod {
        pod_name: name.to_string(),
        generation: String::new(),
        status,
        registered_at: 0,
        last_heartbeat: 0,
        controller: None,
        advertise_address: None,
    };
    let lease = store.grant_lease(60).await.unwrap();
    store
        .register_pod(&pod("p0", PodStatus::Ready), lease)
        .await
        .unwrap();
    store
        .register_pod(&pod("p1", PodStatus::Draining), lease)
        .await
        .unwrap();
    store
        .put_assignments(
            &(0..PARTITIONS)
                .map(|p| assignment(p, if p % 2 == 0 { "p0" } else { "p1" }))
                .collect::<Vec<_>>(),
        )
        .await
        .unwrap();
    assert!(store
        .create_migration_request(&request("m-1", 8))
        .await
        .unwrap());
    let members = Member::active_all(&["p0", "p1"]);
    let pass = || {
        let store = Arc::clone(&store);
        let members = members.clone();
        async move {
            let pods = store.list_pods().await.unwrap();
            let (req, rev) = store
                .get_migration_request_with_mod_revision()
                .await
                .unwrap()
                .unwrap();
            consider_request(&store, &members, &pods, req, rev, Vec::new())
                .await
                .unwrap();
        }
    };

    // First the sighting, then a pass that must wait on the draining owner.
    pass().await;
    pass().await;
    assert!(store.get_migration().await.unwrap().is_none());
    let (waiting, _) = store
        .get_migration_request_with_mod_revision()
        .await
        .unwrap()
        .unwrap();
    assert!(
        waiting
            .waiting
            .iter()
            .any(|w| w.contains("p1 is not ready")),
        "{:?}",
        waiting.waiting
    );

    store
        .register_pod(&pod("p1", PodStatus::Ready), lease)
        .await
        .unwrap();
    pass().await;
    assert_eq!(store.get_migration().await.unwrap().unwrap().id, "m-1");
}

/// A consumer that proves a generation drained, even one already drained when
/// it starts and never subscribed to, reports it for its group.
#[tokio::test]
async fn a_follower_reports_each_generation_it_proves_drained() {
    let store = test_store("migration-drain-report").await;
    let mut follower = Follower::default();
    let topic = follower
        .select_topic(&draining_config(&[]), |_| async { Ok(true) })
        .await
        .unwrap();
    assert_eq!(topic, TOPIC);

    let reporter = Reporter {
        group: "writer".to_string(),
        pod: "writer-0".to_string(),
    };
    follower.report(&store, &reporter).await;
    let reports = store.list_drain_reports().await.unwrap();
    assert_eq!(reports.len(), 1);
    assert_eq!(
        (reports[0].topic.as_str(), reports[0].group.as_str()),
        (TOPIC_V0, "writer")
    );
}
