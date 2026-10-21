//! End-to-end tests for the `cohort_stream_events` consumer against a **real** Kafka broker.
//!
//! `#[ignore]`d by default: the consumer commits a `TopicPartitionList` to its group and reads its
//! own committed offsets back, which the in-process `MockCluster` does not exercise faithfully. Run
//! against a local stack with:
//!
//! ```sh
//! cargo test -p cohort-stream-processor --test events_consumer -- --ignored
//! ```
//!
//! The S3/PVC disaster-recovery e2e
//! ([`s3_restore_replays_past_the_checkpoint_after_the_broker_moved_on`]) additionally
//! needs an S3-compatible store. The compose stack's SeaweedFS (`objectstorage`) serves one:
//!
//! ```sh
//! export KAFKA_HOSTS=localhost:9092
//! export CHECKPOINT_S3_ENDPOINT=http://localhost:19000
//! export CHECKPOINT_S3_REGION=us-east-1
//! export CHECKPOINT_S3_BUCKET=posthog
//! export CHECKPOINT_S3_ACCESS_KEY_ID=object_storage_root_user
//! export CHECKPOINT_S3_SECRET_ACCESS_KEY=object_storage_root_password
//! cargo test -p cohort-stream-processor --test events_consumer -- --ignored s3_restore
//! ```
//!
//! Every test creates 4-partition topics and deletes the Kafka topic on exit (a leaked high-partition
//! topic wedges later runs); the S3 e2e also sweeps its per-test S3 prefix on exit.

// Tests seed and assert through `CohortStore` directly — the sanctioned direct-store test surface.
#![allow(clippy::disallowed_methods)]

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::num::NonZeroU16;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono_tz::UTC;
use cohort_stream_processor::config::Config;
use cohort_stream_processor::consumers::{
    BootReadiness, CohortStreamEventsConsumer, EventDispatcher,
};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{
    AdmittedSplit, ClaimedSplit, CohortConsumerContext, InputGroups, InputTopic, OffsetTracker,
    PartitionOwnership, PartitionRouter, ShuffleMessage, SplitClaim, Stamp, StoreSource,
    WorkerInbox,
};
use cohort_stream_processor::producer::{
    CaptureSink, CohortMembershipChange, KafkaMembershipSink, MembershipSink, MembershipStatus,
};
use cohort_stream_processor::stage1::{Stage1State, StatefulRecord};
use cohort_stream_processor::store::durability::{
    open_store, CheckpointSweeper, PendingRestore, PodOrdinal, MARKER_FILENAME,
};
use cohort_stream_processor::store::{
    BehavioralKey, CohortStore, LeafStateKey, OffloadConfig, OffloadMode, StoreConfig, StoreHandle,
};
use cohort_stream_processor::sweep::Sweeper;

fn test_handle(store: &CohortStore) -> StoreHandle {
    StoreHandle::new(
        store.clone(),
        OffloadConfig {
            mode: OffloadMode::All,
            event_read_permits: 16,
            maintenance_permits: 6,
        },
    )
}
use cohort_stream_processor::workers::{EvictionRestore, MergeWorkerDeps, Stage1Worker};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::KafkaProduceError;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use serde_json::json;
use tempfile::TempDir;
use tokio::sync::mpsc;
use uuid::Uuid;

const TEAM: i32 = 7;
const HASH: [u8; 16] = *b"0123456789abcdef";
const NUM_PARTITIONS: i32 = 4;
const PERSONS: u128 = 3;
const EVENTS_PER_PERSON: usize = 3;
const BASE_TS: &str = "2026-05-26 12:34:56.789000";

fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

/// A team with a single `performed_event` behavioral leaf on `$pageview` — every `$pageview` enters.
fn behavioral_catalog() -> CatalogHandle {
    let leaf = json!({
        "type": "behavioral",
        "value": "performed_event",
        "key": "$pageview",
        "time_value": 7,
        "time_interval": "day",
        "conditionHash": "0123456789abcdef",
        "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
    });
    let cohort = json!({ "properties": { "type": "AND", "values": [leaf] } });
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(CohortId(1), TeamId(TEAM), &cohort)
        .expect("add cohort");
    CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(TEAM),
        builder.freeze(UTC),
    )]))
}

fn behavioral_lsk(catalog: &CatalogHandle) -> LeafStateKey {
    let snapshot = catalog.load();
    let team = snapshot.team(TeamId(TEAM)).expect("team in catalog");
    team.by_condition_to_lsk[&HASH][0]
}

fn person(n: u128) -> Uuid {
    Uuid::from_u128(0xA1CE_0000 + n)
}

/// A serialized `CohortStreamEvent` envelope, byte-for-byte what the shuffler emits.
fn envelope(person: Uuid, source_partition: i32, source_offset: i64) -> Vec<u8> {
    let value = json!({
        "team_id": TEAM,
        "person_id": person.to_string(),
        "distinct_id": "d",
        "uuid": Uuid::from_u128(0xE0_0000 + source_offset as u128).to_string(),
        "event": "$pageview",
        "timestamp": BASE_TS,
        "properties": "{}",
        "person_properties": null,
        "elements_chain": null,
        "source_offset": source_offset,
        "source_partition": source_partition,
    });
    serde_json::to_vec(&value).expect("serialize envelope")
}

async fn create_topic(topic: &str) {
    let admin: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .create()
        .expect("create admin client");
    let new_topic = NewTopic::new(topic, NUM_PARTITIONS, TopicReplication::Fixed(1));
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));
    let results = admin
        .create_topics(&[new_topic], &opts)
        .await
        .expect("create_topics");
    for result in results {
        match result {
            Ok(_) | Err((_, rdkafka::types::RDKafkaErrorCode::TopicAlreadyExists)) => {}
            Err((name, err)) => panic!("failed to create topic {name}: {err:?}"),
        }
    }
    // Let topic metadata propagate before producing.
    tokio::time::sleep(Duration::from_millis(500)).await;
}

/// Delete a topic on test exit. Best-effort: a missing topic or admin error is ignored so cleanup
/// never fails a passing test. Leaked topics (especially high-partition ones) wedge later runs.
async fn delete_topic(topic: &str) {
    let admin: AdminClient<DefaultClientContext> = match ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .create()
    {
        Ok(admin) => admin,
        Err(_) => return,
    };
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));
    let _result = admin.delete_topics(&[topic], &opts).await;
}

/// Keyed `"{team}:{person}"` so a person's events co-partition. Returns the total produced.
async fn produce_events(topic: &str) -> usize {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("message.timeout.ms", "10000")
        .create()
        .expect("create producer");

    let mut total = 0;
    let mut source_offset = 0i64;
    for n in 1..=PERSONS {
        let p = person(n);
        let key = format!("{TEAM}:{p}");
        for _ in 0..EVENTS_PER_PERSON {
            let payload = envelope(p, 0, source_offset);
            producer
                .send(
                    FutureRecord::to(topic).key(&key).payload(&payload),
                    Timeout::After(Duration::from_secs(10)),
                )
                .await
                .expect("produce event");
            source_offset += 1;
            total += 1;
        }
    }
    total
}

/// Persons that first appear after a restart, in the durable-restart test.
const NEW_PERSONS: u128 = 50;

/// One matching `$pageview` each for `count` persons after the [`PERSONS`] that [`produce_events`]
/// writes, at source offsets past its own. Returns the total produced.
async fn produce_new_persons(topic: &str, count: u128) -> usize {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("message.timeout.ms", "10000")
        .create()
        .expect("create producer");
    let first_offset = (PERSONS as usize * EVENTS_PER_PERSON) as i64;
    for n in 1..=count {
        let p = person(PERSONS + n);
        let key = format!("{TEAM}:{p}");
        let payload = envelope(p, 0, first_offset + n as i64);
        producer
            .send(
                FutureRecord::to(topic).key(&key).payload(&payload),
                Timeout::After(Duration::from_secs(10)),
            )
            .await
            .expect("produce event");
    }
    count as usize
}

/// The single pod's ownership of the test topics.
const SINGLE_POD: PartitionOwnership = PartitionOwnership::single(NUM_PARTITIONS as u16);

/// Admits `claim` through the ownership fence, as the processor does before it opens the store.
async fn admit(claim: SplitClaim, groups: &Arc<InputGroups>) -> AdmittedSplit {
    let groups = groups.clone();
    tokio::task::spawn_blocking(move || {
        AdmittedSplit::try_admit(claim, &groups).expect("the fence admits the split")
    })
    .await
    .expect("the admission panicked")
}

/// The claim the processor makes once the store is open.
async fn claim(admitted: AdmittedSplit, groups: &Arc<InputGroups>) -> ClaimedSplit {
    let groups = groups.clone();
    tokio::task::spawn_blocking(move || {
        admitted.claim(&groups).expect("claim the owned partitions")
    })
    .await
    .expect("the claim panicked")
}

/// Admits and claims `ownership` of `topic` for `group`. These tests read only the events topic,
/// so the follower groups, which the fence claims too, read it as well.
async fn claim_events(topic: &str, group: &str, ownership: PartitionOwnership) -> ClaimedSplit {
    let mut config = Config::init_from_hashmap(&HashMap::new()).expect("default config");
    config.kafka_hosts = bootstrap_servers();
    config.cohort_stream_events_topic = topic.to_owned();
    config.kafka_consumer_group = group.to_owned();
    config.person_merge_events_topic = topic.to_owned();
    config.kafka_merge_consumer_group = format!("{group}-merges");
    config.cohort_merge_state_transfer_topic = topic.to_owned();
    config.kafka_merge_apply_consumer_group = format!("{group}-transfers");
    let groups = Arc::new(InputGroups::new(&config));
    let split = SplitClaim::new(ownership, None).expect("a split outside a reshard");
    claim(admit(split, &groups).await, &groups).await
}

async fn build_consumer(
    topic: &str,
    group: &str,
    store: CohortStore,
    catalog: CatalogHandle,
    handle: lifecycle::Handle,
    sink: Arc<dyn MembershipSink>,
    offset_commit_interval: Duration,
) -> CohortStreamEventsConsumer {
    let claimed = claim_events(topic, group, SINGLE_POD).await;
    let (consumer, _dispatcher) = build_consumer_with_restore(
        topic,
        group,
        store,
        catalog,
        handle,
        sink,
        offset_commit_interval,
        &claimed,
        false,
        100,
    );
    consumer
}

#[allow(clippy::too_many_arguments)]
fn build_consumer_with_restore(
    topic: &str,
    group: &str,
    store: CohortStore,
    catalog: CatalogHandle,
    handle: lifecycle::Handle,
    sink: Arc<dyn MembershipSink>,
    offset_commit_interval: Duration,
    claimed: &ClaimedSplit,
    durable_restore: bool,
    recv_batch_size: usize,
) -> (CohortStreamEventsConsumer, Arc<EventDispatcher>) {
    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        test_handle(&store),
        Arc::new(catalog),
        sink,
        MergeWorkerDeps::capture(),
    ));
    if durable_restore {
        dispatcher.enable_durable_restore();
    }

    let events_consumer = CohortStreamEventsConsumer::new(
        Arc::new(events_client(group)),
        topic.to_string(),
        dispatcher.clone(),
        handle,
        recv_batch_size,
        Duration::from_millis(200),
        offset_commit_interval,
        claimed,
        None,
    )
    .expect("assign the owned partitions");
    (events_consumer, dispatcher)
}

fn events_client(group: &str) -> StreamConsumer<CohortConsumerContext> {
    ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest")
        .create_with_context(CohortConsumerContext)
        .expect("create consumer")
}

/// The `murmur2_random` partitioner must match production for keyed co-partitioning.
fn shadow_kafka_config() -> KafkaConfig {
    KafkaConfig {
        kafka_hosts: bootstrap_servers(),
        kafka_tls: false,
        kafka_client_rack: String::new(),
        kafka_client_id: String::new(),
        kafka_compression_codec: "none".to_string(),
        kafka_producer_partitioner: Some("murmur2_random".to_string()),
        kafka_producer_linger_ms: 20,
        kafka_producer_queue_mib: 400,
        kafka_producer_queue_messages: 10_000_000,
        kafka_message_timeout_ms: 20_000,
        kafka_producer_batch_size: None,
        kafka_producer_batch_num_messages: None,
        kafka_producer_enable_idempotence: None,
        kafka_producer_max_in_flight_requests_per_connection: None,
        kafka_producer_topic_metadata_refresh_interval_ms: None,
        kafka_producer_message_max_bytes: None,
        kafka_producer_sticky_partitioning_linger_ms: None,
        kafka_producer_acks: None,
        kafka_producer_retries: None,
    }
}

/// Drain up to `expected` membership changes off the shadow topic, or whatever arrives by deadline.
async fn drain_shadow_changes(topic: &str, expected: usize) -> Vec<CohortMembershipChange> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", format!("shadow-verifier-{}", Uuid::new_v4()))
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .create()
        .expect("create shadow verifier");
    consumer.subscribe(&[topic]).expect("subscribe shadow");

    let mut changes = Vec::new();
    let start = Instant::now();
    while changes.len() < expected && start.elapsed() < Duration::from_secs(30) {
        match tokio::time::timeout(Duration::from_secs(2), consumer.recv()).await {
            Ok(Ok(message)) => {
                if let Some(payload) = message.payload() {
                    changes.push(
                        serde_json::from_slice::<CohortMembershipChange>(payload)
                            .expect("decode shadow membership change"),
                    );
                }
            }
            Ok(Err(err)) => panic!("shadow recv error: {err}"),
            Err(_) => {} // poll tick elapsed with no message; re-check the deadline
        }
    }
    changes
}

/// Sum of committed offsets across partitions; for a fresh topic this equals the events consumed
/// (committed == next-offset-to-consume).
fn committed_sum(consumer: &StreamConsumer, topic: &str) -> i64 {
    let mut tpl = TopicPartitionList::new();
    for partition in 0..NUM_PARTITIONS {
        tpl.add_partition(topic, partition);
    }
    let committed = consumer
        .committed_offsets(tpl, Duration::from_secs(5))
        .expect("fetch committed offsets");
    (0..NUM_PARTITIONS)
        .filter_map(|partition| committed.find_partition(topic, partition))
        .map(|elem| match elem.offset() {
            Offset::Offset(value) => value,
            _ => 0,
        })
        .sum()
}

/// Scans every partition because a person's partition depends on the producer's key hash.
fn entered_persons(store: &CohortStore, lsk: LeafStateKey) -> usize {
    (1..=PERSONS)
        .filter(|&n| {
            let p = person(n);
            (0..NUM_PARTITIONS).any(|partition| {
                let key = BehavioralKey::new(partition as u16, TEAM as u64, p, lsk);
                matches!(
                    store
                        .get_behavioral(&key)
                        .unwrap()
                        .map(|bytes| StatefulRecord::decode(&bytes).unwrap().state),
                    Some(Stage1State::BehavioralSingle {
                        has_match: true,
                        ..
                    }),
                )
            })
        })
        .count()
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn consumes_routes_and_commits_end_to_end() {
    let suffix = Uuid::new_v4();
    let topic = format!("cohort_stream_events_itest_{suffix}");
    let group = format!("cohort-stream-processor-itest-{suffix}");

    create_topic(&topic).await;
    let total = produce_events(&topic).await;

    let dir = TempDir::new().unwrap();
    let store = CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store");
    let catalog = behavioral_catalog();
    let lsk = behavioral_lsk(&catalog);

    // Not subscribed: reads committed offsets via OffsetFetch without joining the group.
    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");

    let mut manager = Manager::builder("events-consumer-itest")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "consumer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let shutdown_handle = handle.clone();
    let _monitor = manager.monitor_background();

    let consumer = build_consumer(
        &topic,
        &group,
        store.clone(),
        catalog,
        handle,
        Arc::new(CaptureSink::new()),
        Duration::from_millis(250),
    )
    .await;
    let task = tokio::spawn(consumer.process());

    let deadline = Duration::from_secs(60);
    let start = Instant::now();
    loop {
        if committed_sum(&verifier, &topic) == total as i64 {
            break;
        }
        assert!(
            start.elapsed() < deadline,
            "timed out waiting for committed offsets to reach {total}; last sum {}",
            committed_sum(&verifier, &topic),
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    shutdown_handle.request_shutdown();
    task.await.expect("consumer task panicked");

    assert_eq!(
        entered_persons(&store, lsk),
        PERSONS as usize,
        "every produced person should have entered the behavioral leaf",
    );

    assert_eq!(
        committed_sum(&verifier, &topic),
        total as i64,
        "committed offsets should cover all {total} produced events",
    );
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn produces_membership_changes_and_commits_offsets() {
    let suffix = Uuid::new_v4();
    let input_topic = format!("cohort_stream_events_shadow_in_{suffix}");
    let shadow_topic = format!("cohort_membership_changed_shadow_{suffix}");
    let group = format!("cohort-stream-processor-shadow-{suffix}");

    create_topic(&input_topic).await;
    create_topic(&shadow_topic).await;
    let total = produce_events(&input_topic).await;

    let dir = TempDir::new().unwrap();
    let store = CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store");
    let catalog = behavioral_catalog();

    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");

    let sink: Arc<dyn MembershipSink> = Arc::new(
        KafkaMembershipSink::new(&shadow_kafka_config(), shadow_topic.clone())
            .await
            .expect("create shadow sink"),
    );

    let mut manager = Manager::builder("shadow-itest")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "consumer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let shutdown_handle = handle.clone();
    let _monitor = manager.monitor_background();

    let consumer = build_consumer(
        &input_topic,
        &group,
        store.clone(),
        catalog,
        handle,
        sink,
        Duration::from_millis(250),
    )
    .await;
    let task = tokio::spawn(consumer.process());

    let start = Instant::now();
    loop {
        if committed_sum(&verifier, &input_topic) == total as i64 {
            break;
        }
        assert!(
            start.elapsed() < Duration::from_secs(60),
            "timed out waiting for committed input offsets to reach {total}",
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    shutdown_handle.request_shutdown();
    task.await.expect("consumer task panicked");

    // One entered per person: the first `$pageview` enters, repeats are already members.
    let changes = drain_shadow_changes(&shadow_topic, PERSONS as usize).await;
    assert_eq!(
        changes.len(),
        PERSONS as usize,
        "one entered change per person on the shadow topic",
    );
    for change in &changes {
        assert_eq!(change.team_id, TEAM);
        assert_eq!(change.cohort_id, 1);
        assert_eq!(change.status, MembershipStatus::Entered);
        assert!(
            Uuid::parse_str(&change.person_id).is_ok(),
            "person_id is a UUID string",
        );
    }

    assert_eq!(committed_sum(&verifier, &input_topic), total as i64);
}

/// One event at a time with a `gap`, so sends straddle commit deadlines (the low-traffic pattern).
/// Each distinct person produces one matching `$pageview`. Returns the total produced.
async fn produce_events_trickle(topic: &str, n: usize, gap: Duration) -> usize {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("message.timeout.ms", "10000")
        .create()
        .expect("create producer");

    for i in 0..n {
        let p = person(i as u128 + 1);
        let key = format!("{TEAM}:{p}");
        let payload = envelope(p, 0, i as i64);
        producer
            .send(
                FutureRecord::to(topic).key(&key).payload(&payload),
                Timeout::After(Duration::from_secs(10)),
            )
            .await
            .expect("produce event");
        tokio::time::sleep(gap).await;
    }
    n
}

fn entered_persons_range(store: &CohortStore, lsk: LeafStateKey, n: usize) -> usize {
    (1..=n as u128)
        .filter(|&i| {
            let p = person(i);
            (0..NUM_PARTITIONS).any(|partition| {
                let key = BehavioralKey::new(partition as u16, TEAM as u64, p, lsk);
                matches!(
                    store
                        .get_behavioral(&key)
                        .unwrap()
                        .map(|bytes| StatefulRecord::decode(&bytes).unwrap().state),
                    Some(Stage1State::BehavioralSingle {
                        has_match: true,
                        ..
                    }),
                )
            })
        })
        .count()
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn trickled_events_are_never_silently_dropped() {
    const N: usize = 60;

    let suffix = Uuid::new_v4();
    let topic = format!("cohort_stream_events_trickle_{suffix}");
    let group = format!("cohort-stream-processor-trickle-{suffix}");

    create_topic(&topic).await;

    let dir = TempDir::new().unwrap();
    let store = CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store");
    let catalog = behavioral_catalog();
    let lsk = behavioral_lsk(&catalog);

    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");

    let mut manager = Manager::builder("trickle-itest")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "consumer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let shutdown_handle = handle.clone();
    let _monitor = manager.monitor_background();

    // Consumer must be live before producing so sends straddle commit boundaries.
    let consumer = build_consumer(
        &topic,
        &group,
        store.clone(),
        catalog,
        handle,
        Arc::new(CaptureSink::new()),
        Duration::from_millis(300),
    )
    .await;
    let task = tokio::spawn(consumer.process());

    let total = produce_events_trickle(&topic, N, Duration::from_millis(120)).await;

    let start = Instant::now();
    loop {
        if committed_sum(&verifier, &topic) == total as i64 {
            break;
        }
        assert!(
            start.elapsed() < Duration::from_secs(60),
            "timed out waiting for committed offsets to reach {total}; last sum {}",
            committed_sum(&verifier, &topic),
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    shutdown_handle.request_shutdown();
    task.await.expect("consumer task panicked");

    assert_eq!(
        entered_persons_range(&store, lsk, N),
        N,
        "every trickled person must have entered the behavioral leaf (no silent consume-side loss)",
    );
    assert_eq!(
        committed_sum(&verifier, &topic),
        total as i64,
        "committed offsets must cover all {total} produced events",
    );
}

/// Blocks its first flush until released, preventing the worker from marking its offset.
struct BarrierSink {
    entered: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
    first: AtomicBool,
    recorded: Arc<Mutex<Vec<CohortMembershipChange>>>,
}

impl BarrierSink {
    fn new() -> (
        Arc<Self>,
        Arc<tokio::sync::Notify>,
        Arc<tokio::sync::Notify>,
    ) {
        let entered = Arc::new(tokio::sync::Notify::new());
        let release = Arc::new(tokio::sync::Notify::new());
        let sink = Arc::new(Self {
            entered: entered.clone(),
            release: release.clone(),
            first: AtomicBool::new(true),
            recorded: Arc::new(Mutex::new(Vec::new())),
        });
        (sink, entered, release)
    }

    fn recorded_len(&self) -> usize {
        self.recorded.lock().expect("BarrierSink poisoned").len()
    }
}

#[async_trait]
impl MembershipSink for BarrierSink {
    async fn produce(
        &self,
        changes: Vec<CohortMembershipChange>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        if self.first.swap(false, Ordering::SeqCst) {
            self.entered.notify_one();
            self.release.notified().await;
        }
        let acks = (0..changes.len()).map(|_| Ok(())).collect();
        self.recorded
            .lock()
            .expect("BarrierSink poisoned")
            .extend(changes);
        acks
    }
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn does_not_commit_past_a_blocked_produce() {
    let suffix = Uuid::new_v4();
    let topic = format!("cohort_stream_events_barrier_{suffix}");
    let group = format!("cohort-stream-processor-barrier-{suffix}");

    create_topic(&topic).await;

    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("message.timeout.ms", "10000")
        .create()
        .expect("create producer");
    let p = person(1);
    let payload = envelope(p, 0, 0);
    producer
        .send(
            FutureRecord::to(&topic)
                .key(&format!("{TEAM}:{p}"))
                .payload(&payload),
            Timeout::After(Duration::from_secs(10)),
        )
        .await
        .expect("produce event");

    let dir = TempDir::new().unwrap();
    let store = CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store");
    let catalog = behavioral_catalog();

    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");

    let (sink, entered, release) = BarrierSink::new();

    let mut manager = Manager::builder("barrier-itest")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "consumer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let shutdown_handle = handle.clone();
    let _monitor = manager.monitor_background();

    let consumer = build_consumer(
        &topic,
        &group,
        store.clone(),
        catalog,
        handle,
        sink.clone(),
        Duration::from_millis(100),
    )
    .await;
    let task = tokio::spawn(consumer.process());

    tokio::time::timeout(Duration::from_secs(30), entered.notified())
        .await
        .expect("worker reached the produce barrier");

    // Several commit ticks fire while the produce is blocked.
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert_eq!(
        committed_sum(&verifier, &topic),
        0,
        "no offset may be committed before its produce is acked",
    );
    assert_eq!(
        sink.recorded_len(),
        0,
        "the blocked flush has recorded nothing yet",
    );

    release.notify_one();

    let start = Instant::now();
    loop {
        if committed_sum(&verifier, &topic) == 1 {
            break;
        }
        assert!(
            start.elapsed() < Duration::from_secs(30),
            "offset did not advance after releasing the produce",
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    assert_eq!(
        sink.recorded_len(),
        1,
        "the released flush recorded its change",
    );

    shutdown_handle.request_shutdown();
    task.await.expect("consumer task panicked");
}

/// Whether any of the first `persons` persons has behavioral state under `partition` in `store`.
fn partition_has_state(
    store: &CohortStore,
    partition: i32,
    lsk: LeafStateKey,
    persons: u128,
) -> bool {
    (1..=persons).any(|n| {
        let key = BehavioralKey::new(partition as u16, TEAM as u64, person(n), lsk);
        store.get_behavioral(&key).unwrap().is_some()
    })
}

/// Poll the group's committed-offset sum until it reaches `target` or the deadline elapses.
async fn wait_for_committed(
    consumer: &StreamConsumer,
    topic: &str,
    target: i64,
    deadline: Duration,
) {
    let start = Instant::now();
    loop {
        let sum = committed_sum(consumer, topic);
        if sum >= target {
            return;
        }
        assert!(
            start.elapsed() < deadline,
            "timed out waiting for committed sum to reach {target}; last {sum}",
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn two_pods_split_the_events_by_residue_class_and_commit_every_offset() {
    let suffix = Uuid::new_v4();
    let topic = format!("cohort_stream_events_split_{suffix}");
    let group = format!("cohort-stream-processor-split-{suffix}");
    create_topic(&topic).await;
    let total = produce_events(&topic).await + produce_new_persons(&topic, NEW_PERSONS).await;
    let persons = PERSONS + NEW_PERSONS;

    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier");

    let mut manager = Manager::builder("split-itest")
        .with_trap_signals(false)
        .build();
    let pods = std::num::NonZeroU16::new(2).unwrap();
    let handles: Vec<lifecycle::Handle> = (0..pods.get())
        .map(|ordinal| {
            manager.register(
                &format!("consumer-{ordinal}"),
                ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
            )
        })
        .collect();
    let _monitor = manager.monitor_background();
    let mut split = Vec::new();
    for (ordinal, handle) in (0..pods.get()).zip(handles) {
        let ownership =
            PartitionOwnership::new(pods, PodOrdinal::from(ordinal), NUM_PARTITIONS as u16)
                .unwrap();
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ownership,
            ..StoreConfig::default()
        })
        .expect("open store");
        let claimed = claim_events(&topic, &group, ownership).await;
        let (consumer, dispatcher) = build_consumer_with_restore(
            &topic,
            &group,
            store.clone(),
            behavioral_catalog(),
            handle.clone(),
            Arc::new(CaptureSink::new()),
            Duration::from_millis(250),
            &claimed,
            false,
            100,
        );
        let task = tokio::spawn(consumer.process());
        split.push((dir, store, dispatcher, handle, task));
    }

    wait_for_committed(&verifier, &topic, total as i64, Duration::from_secs(60)).await;
    let lsk = behavioral_lsk(&behavioral_catalog());
    for (_, _, _, handle, _) in &split {
        handle.request_shutdown();
    }
    let mut owned = Vec::new();
    let mut stores = Vec::new();
    for (dir, store, dispatcher, _, task) in split {
        task.await.expect("consumer panicked");
        let mut partitions: Vec<i32> = dispatcher.owned_partitions();
        partitions.sort_unstable();
        owned.push(partitions);
        stores.push((dir, store));
    }

    assert_eq!(
        owned,
        [vec![0, 2], vec![1, 3]],
        "each pod owns its residue class"
    );
    assert_eq!(
        committed_sum(&verifier, &topic),
        total as i64,
        "two member-less consumers commit every offset of the one group between them",
    );
    for partition in 0..NUM_PARTITIONS {
        let holders: Vec<usize> = stores
            .iter()
            .enumerate()
            .filter(|(_, (_, store))| partition_has_state(store, partition, lsk, persons))
            .map(|(pod, _)| pod)
            .collect();
        assert!(
            holders.iter().all(|&pod| pod == (partition % 2) as usize),
            "partition {partition} has state on pods {holders:?}, but only its owner may hold it",
        );
    }
    assert_eq!(
        stores
            .iter()
            .map(|(_, store)| entered_persons_range(store, lsk, persons as usize))
            .sum::<usize>(),
        persons as usize,
        "every person entered on exactly one pod",
    );

    delete_topic(&topic).await;
}

/// Reopen the store at `path` without wiping (durable restore), retrying briefly while the previous
/// tenure's rebalance-worker task finishes dropping its store handle and releases the RocksDB lock.
async fn reopen_store_live(path: std::path::PathBuf) -> CohortStore {
    let config = StoreConfig {
        path,
        wipe_on_start: false,
        ..StoreConfig::default()
    };
    let start = Instant::now();
    loop {
        match CohortStore::open(&config) {
            Ok(store) => return store,
            Err(_) if start.elapsed() < Duration::from_secs(10) => {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            Err(err) => panic!("failed to reopen store live: {err}"),
        }
    }
}

/// End-to-end through a real broker: a durable-restore consumer folds every person in and
/// fsync-commits; the store is reopened live (no wipe) and must (i) lose no Kafka offsets, (ii)
/// preserve every member's state — a wipe+replay would be empty, since the committed offset already
/// covers every event — (iii) fold every event that arrived while it was down, including the ones
/// polled during boot recovery, and (iv) fire each now-dormant member's `Left` from the rebuilt
/// queue.
///
/// This is the graceful-restart shape. The hard-crash hazard (a committed offset ahead of un-fsync'd
/// state) needs a separately killed process to observe `committed > durable`; a graceful in-process
/// drop always flushes RocksDB on close.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn durable_restart_reopens_live_state_and_fires_a_dormant_left() {
    let suffix = Uuid::new_v4();
    let topic = format!("cohort_stream_events_durable_{suffix}");
    let group = format!("cohort-stream-processor-durable-{suffix}");

    create_topic(&topic).await;
    let total = produce_events(&topic).await;

    let dir = TempDir::new().unwrap();
    let store_path = dir.path().join("db");
    let lsk = behavioral_lsk(&behavioral_catalog());

    // Reads committed offsets without joining the group.
    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");

    // --- Tenure 1: a durable-restore consumer folds every person in and fsync-commits. ---
    {
        let store = CohortStore::open(&StoreConfig {
            path: store_path.clone(),
            ..StoreConfig::default()
        })
        .expect("open store");
        let mut manager = Manager::builder("durable-itest-1")
            .with_trap_signals(false)
            .build();
        let handle = manager.register(
            "consumer",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
        );
        let shutdown_handle = handle.clone();
        let _monitor = manager.monitor_background();
        let claimed = claim_events(&topic, &group, SINGLE_POD).await;
        let (consumer, _dispatcher) = build_consumer_with_restore(
            &topic,
            &group,
            store.clone(),
            behavioral_catalog(),
            handle,
            Arc::new(CaptureSink::new()),
            Duration::from_millis(250),
            &claimed,
            true,
            100,
        );
        let task = tokio::spawn(consumer.process());

        let start = Instant::now();
        while committed_sum(&verifier, &topic) != total as i64 {
            assert!(
                start.elapsed() < Duration::from_secs(60),
                "tenure 1: timed out waiting for committed offsets to reach {total}",
            );
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        shutdown_handle.request_shutdown();
        task.await.expect("tenure-1 consumer panicked");
        assert_eq!(
            entered_persons(&store, lsk),
            PERSONS as usize,
            "tenure 1 folded every produced person into the behavioral leaf",
        );
    } // store drops here, releasing the RocksDB lock

    // --- Restart: reopen the same store live. ---
    let store2 = reopen_store_live(store_path).await;
    assert_eq!(
        entered_persons(&store2, lsk),
        PERSONS as usize,
        "reopen-live preserved every member across the restart (a wipe would read 0)",
    );
    assert_eq!(
        committed_sum(&verifier, &topic),
        total as i64,
        "no Kafka loss: committed offsets are unchanged across the restart",
    );

    // --- Tenure 2: events that arrived while the pod was down. A 10-event batch makes boot
    // recovery span several polls, so the polls it holds back carry events that must fold later. ---
    let total = total + produce_new_persons(&topic, NEW_PERSONS).await;
    {
        let mut manager = Manager::builder("durable-itest-2")
            .with_trap_signals(false)
            .build();
        let handle = manager.register(
            "consumer",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
        );
        let shutdown_handle = handle.clone();
        let _monitor = manager.monitor_background();
        let claimed = claim_events(&topic, &group, SINGLE_POD).await;
        let (consumer, _dispatcher) = build_consumer_with_restore(
            &topic,
            &group,
            store2.clone(),
            behavioral_catalog(),
            handle,
            Arc::new(CaptureSink::new()),
            Duration::from_millis(250),
            &claimed,
            true,
            10,
        );
        let task = tokio::spawn(consumer.process());
        wait_for_committed(&verifier, &topic, total as i64, Duration::from_secs(60)).await;
        shutdown_handle.request_shutdown();
        task.await.expect("tenure-2 consumer panicked");
    }
    let persons = (PERSONS + NEW_PERSONS) as usize;
    assert_eq!(
        entered_persons_range(&store2, lsk, persons),
        persons,
        "tenure 2 folded every event that arrived during the downtime",
    );
    assert_eq!(committed_sum(&verifier, &topic), total as i64);

    // --- Dormant Left: durable workers re-seed queues from cf_behavioral; a sweep past the window
    // evicts each member with no new events. ---
    let catalog = Arc::new(behavioral_catalog());
    let readiness = BootReadiness::new(catalog.clone());
    let sink = Arc::new(CaptureSink::new());
    let far_future = 4_000_000_000_000i64; // ~year 2096, well past every BASE_TS + 7d deadline
    for partition in 0..NUM_PARTITIONS {
        let (tx, rx) = mpsc::channel(4);
        let rx = WorkerInbox::live_only(rx);
        let worker = Stage1Worker::spawn(
            partition as u16,
            rx,
            test_handle(&store2),
            catalog.clone(),
            sink.clone(),
            Arc::new(OffsetTracker::new()),
            MergeWorkerDeps::capture(),
            EvictionRestore::Rebuild(readiness.rebuild_started()),
        );
        tx.send(vec![ShuffleMessage::Sweep {
            due_before_ms: far_future,
        }])
        .await
        .unwrap();
        drop(tx);
        worker.join().await.unwrap();
    }
    let lefts = sink
        .changes()
        .iter()
        .filter(|change| change.status == MembershipStatus::Left)
        .count();
    assert_eq!(
        lefts, persons,
        "every restored-then-dormant member emits a Left from the rebuilt eviction queue",
    );

    delete_topic(&topic).await;
}

// ===========================================================================================
// S3/PVC disaster-recovery e2e. Needs a broker AND an S3-compatible store; see the module docs.
// ===========================================================================================

/// Build a `Config` for the disaster-recovery e2e. `store_path` and `checkpoint_local_dir` must be
/// separate temp subtrees: rocksdb hard-links SSTs into the checkpoint, so it must be a *sibling* of
/// the store, never nested. Every input topic and group is the test's own.
fn s3_restore_config(
    store_path: &std::path::Path,
    checkpoint_dir: &std::path::Path,
    prefix: &str,
    topics: &RestoreTopics,
) -> Config {
    let mut env: HashMap<String, String> = HashMap::new();
    env.insert("CHECKPOINT_ENABLED".into(), "true".into());
    env.insert("DURABLE_RESTORE_ENABLED".into(), "true".into());
    env.insert("KAFKA_HOSTS".into(), bootstrap_servers());
    env.insert(
        "STORE_PATH".into(),
        store_path.to_string_lossy().into_owned(),
    );
    env.insert(
        "CHECKPOINT_LOCAL_DIR".into(),
        checkpoint_dir.to_string_lossy().into_owned(),
    );
    env.insert("CHECKPOINT_S3_PREFIX".into(), prefix.to_string());
    env.insert("CHECKPOINT_S3_FORCE_PATH_STYLE".into(), "true".into());
    // S3 connection from the runner's environment (MinIO/SeaweedFS).
    for key in [
        "CHECKPOINT_S3_BUCKET",
        "CHECKPOINT_S3_ENDPOINT",
        "CHECKPOINT_S3_REGION",
        "CHECKPOINT_S3_ACCESS_KEY_ID",
        "CHECKPOINT_S3_SECRET_ACCESS_KEY",
    ] {
        if let Ok(value) = std::env::var(key) {
            env.insert(key.into(), value);
        }
    }
    let mut config = Config::init_from_hashmap(&env).expect("build s3-restore config");
    config.cohort_partition_count = NUM_PARTITIONS as u32;
    config.cohort_stream_events_topic = topics.events.clone();
    config.kafka_consumer_group = topics.group.clone();
    config.person_merge_events_topic = topics.merges.clone();
    config.kafka_merge_consumer_group = format!("{}-merges", topics.group);
    config.cohort_merge_state_transfer_topic = topics.transfers.clone();
    config.kafka_merge_apply_consumer_group = format!("{}-transfers", topics.group);
    config
}

/// The e2e's own input topics: the events topic and the two follower topics every processor reads.
struct RestoreTopics {
    events: String,
    merges: String,
    transfers: String,
    group: String,
}

impl RestoreTopics {
    fn unique() -> Self {
        let suffix = Uuid::new_v4();
        Self {
            events: format!("cohort_stream_events_s3restore_{suffix}"),
            merges: format!("person_merge_events_s3restore_{suffix}"),
            transfers: format!("cohort_merge_state_transfer_s3restore_{suffix}"),
            group: format!("cohort-stream-processor-s3restore-{suffix}"),
        }
    }

    fn all(&self) -> [&str; 3] {
        [&self.events, &self.merges, &self.transfers]
    }
}

/// Like [`build_consumer_with_restore`] with durable restore on, but hands the consumer a pending
/// checkpoint restore to finish on boot.
#[allow(clippy::too_many_arguments)]
fn build_consumer_finishing_restore(
    topic: &str,
    group: &str,
    store: CohortStore,
    catalog: CatalogHandle,
    handle: lifecycle::Handle,
    sink: Arc<dyn MembershipSink>,
    offset_commit_interval: Duration,
    restore: PendingRestore,
    claimed: &ClaimedSplit,
) -> (CohortStreamEventsConsumer, Arc<EventDispatcher>) {
    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        test_handle(&store),
        Arc::new(catalog),
        sink,
        MergeWorkerDeps::capture(),
    ));
    dispatcher.enable_durable_restore();

    let consumer = CohortStreamEventsConsumer::new(
        Arc::new(events_client(group)),
        topic.to_string(),
        dispatcher.clone(),
        handle,
        100,
        Duration::from_millis(200),
        offset_commit_interval,
        claimed,
        Some(restore),
    )
    .expect("assign the owned partitions");
    (consumer, dispatcher)
}

/// Each partition's high watermark.
fn high_watermarks(consumer: &StreamConsumer, topic: &str) -> HashMap<i32, i64> {
    (0..NUM_PARTITIONS)
        .map(|partition| {
            let (_, high) = consumer
                .fetch_watermarks(topic, partition, Duration::from_secs(5))
                .expect("fetch watermarks");
            (partition, high)
        })
        .collect()
}

/// Delete every S3 object of the config's lineage under the configured prefix on test exit.
/// Best-effort: builds a throwaway `object_store` client from the durability config and sweeps the
/// per-test prefix. Any error building, listing, or deleting is ignored so cleanup never fails a
/// passing test.
async fn delete_s3_prefix(config: &Config) {
    use futures::StreamExt;
    use object_store::aws::AmazonS3Builder;
    use object_store::path::Path as ObjPath;
    use object_store::{ClientOptions, ObjectStore, ObjectStoreExt};

    let d = config.durability_config();
    let mut builder = AmazonS3Builder::from_env()
        .with_bucket_name(&d.s3_bucket)
        .with_client_options(ClientOptions::new());
    if let Some(region) = d.aws_region.as_deref() {
        builder = builder.with_region(region);
    }
    if let Some(endpoint) = d.s3_endpoint.as_deref() {
        builder = builder.with_endpoint(endpoint);
        if endpoint.starts_with("http://") {
            builder = builder.with_allow_http(true);
        }
    }
    if let (Some(ak), Some(sk)) = (
        d.s3_access_key_id.as_deref(),
        d.s3_secret_access_key.as_deref(),
    ) {
        builder = builder.with_access_key_id(ak).with_secret_access_key(sk);
    }
    if d.s3_force_path_style {
        builder = builder.with_virtual_hosted_style_request(false);
    }
    let store = match builder.build() {
        Ok(store) => store,
        Err(_) => return,
    };
    let Ok(lineage) = config.checkpoint_lineage() else {
        return;
    };
    let prefix = ObjPath::from(lineage.remote_dir(&d.s3_key_prefix).as_str());
    let mut stream = store.list(Some(&prefix));
    while let Some(entry) = stream.next().await {
        if let Ok(meta) = entry {
            let _result = store.delete(&meta.location).await;
        }
    }
}

/// Runbook item A's case through a real broker and S3: fold, checkpoint with positions read from
/// the broker, fold more and commit past the checkpoint, then lose the volume. The restore must
/// replay exactly the events after the checkpoint even though the events group already committed
/// past them, record the idle partition, finish by committing, and fire a dormant `Left` from the
/// eviction queue rebuilt over the restored `cf_behavioral`.
///
/// Asserting count-exact (not mere presence) sidesteps the documented fast-broker flake.
// Multi-threaded: finishing the restore commits with `block_in_place`.
#[tokio::test(flavor = "multi_thread")]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS) AND an S3-compatible store (CHECKPOINT_S3_*); see module docs"]
async fn s3_restore_replays_past_the_checkpoint_after_the_broker_moved_on() {
    let topics = RestoreTopics::unique();
    let topic = topics.events.clone();
    let group = topics.group.clone();
    let prefix = format!("cohort-stream-checkpoints-itest/{}", Uuid::new_v4());
    for name in topics.all() {
        create_topic(name).await;
    }
    let before_checkpoint = produce_events(&topic).await;
    // Nothing consumes the merges topic here, so its group never commits.
    produce_events(&topics.merges).await;

    // Store and checkpoint dirs must be sibling subtrees, never nested (see `s3_restore_config`).
    let root = TempDir::new().unwrap();
    let store_path = root.path().join("db");
    let checkpoint_dir = root.path().join("checkpoints");
    let config = s3_restore_config(&store_path, &checkpoint_dir, &prefix, &topics);
    let lineage = config.checkpoint_lineage().expect("standalone lineage");
    let groups = Arc::new(InputGroups::new(&config));
    let lsk = behavioral_lsk(&behavioral_catalog());
    let total_persons = (PERSONS + NEW_PERSONS) as usize;

    // Reads committed offsets without joining the group.
    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");
    // PERSONS keys over NUM_PARTITIONS partitions leave at least one partition without an event.
    let idle_partition = high_watermarks(&verifier, &topic)
        .into_iter()
        .find_map(|(partition, high)| (high == 0).then_some(partition))
        .expect("an events partition with no event");

    // --- Tenure 1: fold, checkpoint through the sweeper, then fold and commit past it. ---
    {
        let admitted = admit(config.split_claim().expect("a standalone split"), &groups).await;
        let store = CohortStore::open(&config.store_config(admitted.ownership()))
            .expect("open tenure-1 store");
        let claimed = claim(admitted, &groups).await;
        let mut manager = Manager::builder("s3restore-itest-1")
            .with_trap_signals(false)
            .build();
        let handle = manager.register(
            "consumer",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
        );
        let shutdown_handle = handle.clone();
        let _monitor = manager.monitor_background();
        let (consumer, dispatcher) = build_consumer_with_restore(
            &topic,
            &group,
            store.clone(),
            behavioral_catalog(),
            handle,
            Arc::new(CaptureSink::new()),
            Duration::from_millis(250),
            &claimed,
            true,
            100,
        );
        let task = tokio::spawn(consumer.process());

        let start = Instant::now();
        while committed_sum(&verifier, &topic) != before_checkpoint as i64 {
            assert!(
                start.elapsed() < Duration::from_secs(60),
                "tenure 1: timed out waiting for committed offsets to reach {before_checkpoint}",
            );
            tokio::time::sleep(Duration::from_millis(200)).await;
        }

        // upload_every_n = 1, so every tick uploads.
        let sweeper = |dispatcher| {
            CheckpointSweeper::new(
                store.clone(),
                dispatcher,
                groups.clone(),
                claimed.clone(),
                config.durability_config(),
                1,
                tokio_util::sync::CancellationToken::new(),
            )
        };
        let uploaded = lineage
            .local_dir(std::path::Path::new(&config.checkpoint_local_dir))
            .join("uploaded.json");
        let baseline = || -> serde_json::Value {
            serde_json::from_slice(
                &std::fs::read(&uploaded).expect("an upload records its baseline"),
            )
            .unwrap()
        };
        sweeper(dispatcher.clone()).run_once().await;
        let first = baseline();
        // A second sweeper over the same store stands in for a restarted process.
        sweeper(dispatcher).run_once().await;
        let second = baseline();
        assert_ne!(second["metadata"]["id"], first["metadata"]["id"]);
        assert_eq!(
            second["metadata"]["full_upload_at"], first["metadata"]["full_upload_at"],
            "a restarted process continues the upload chain of its store",
        );

        let total = before_checkpoint + produce_new_persons(&topic, NEW_PERSONS).await;
        let start = Instant::now();
        while committed_sum(&verifier, &topic) != total as i64 {
            assert!(
                start.elapsed() < Duration::from_secs(60),
                "tenure 1: timed out waiting for committed offsets to reach {total}",
            );
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        shutdown_handle.request_shutdown();
        task.await.expect("tenure-1 consumer panicked");
        assert_eq!(
            entered_persons_range(&store, lsk, total_persons),
            total_persons
        );
    } // tenure-1 store + dispatcher drop here, releasing the RocksDB lock
    let total = committed_sum(&verifier, &topic);

    // --- Volume loss: delete BOTH the live store and the local checkpoint dir. ---
    std::fs::remove_dir_all(&store_path).expect("remove store_path (simulate PVC loss)");
    std::fs::remove_dir_all(&checkpoint_dir)
        .expect("remove checkpoint_local_dir (simulate PVC loss)");

    // --- Tenure 2: the boot restores from S3, then the consumer finishes the restore. ---
    let admitted = admit(config.split_claim().expect("a standalone split"), &groups).await;
    let (store2, restore) = open_store(&config, &admitted, Some(lineage), groups.clone())
        .await
        .expect("open the restored store");
    let restore = restore
        .expect("with the live store and local checkpoint gone, the boot restores a checkpoint");
    assert_eq!(restore.source().label(), "s3");
    let resumed = restore
        .plan()
        .positions(&InputTopic::new(topic.as_str()), &SINGLE_POD);
    assert_eq!(
        resumed
            .get(&(idle_partition as u16))
            .map(|offset| offset.get()),
        Some(0),
        "the manifest records the idle partition at its low watermark",
    );
    let (merges_with_events, _) = high_watermarks(&verifier, &topics.merges)
        .into_iter()
        .find(|&(_, high)| high > 0)
        .expect("a merges partition holding events");
    assert_eq!(
        restore
            .plan()
            .positions(&InputTopic::new(topics.merges.as_str()), &SINGLE_POD)
            .get(&(merges_with_events as u16))
            .map(|offset| offset.get()),
        Some(0),
        "a group without a commit resumes at the low watermark, before the events it never read",
    );
    assert_eq!(
        resumed.len(),
        NUM_PARTITIONS as usize,
        "every partition resumes"
    );
    assert_eq!(
        entered_persons_range(&store2, lsk, total_persons),
        PERSONS as usize,
        "the restore holds exactly the state at the checkpoint",
    );

    let mut manager = Manager::builder("s3restore-itest-2")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "consumer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let shutdown_handle = handle.clone();
    let _monitor = manager.monitor_background();
    let claimed = claim(admitted, &groups).await;
    let (consumer, _dispatcher) = build_consumer_finishing_restore(
        &topic,
        &group,
        store2.clone(),
        behavioral_catalog(),
        handle,
        Arc::new(CaptureSink::new()),
        Duration::from_millis(250),
        restore,
        &claimed,
    );
    let task = tokio::spawn(consumer.process());

    let start = Instant::now();
    while entered_persons_range(&store2, lsk, total_persons) != total_persons {
        assert!(
            start.elapsed() < Duration::from_secs(60),
            "tenure 2: timed out replaying the events after the checkpoint",
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    shutdown_handle.request_shutdown();
    task.await.expect("tenure-2 consumer panicked");
    assert_eq!(
        committed_sum(&verifier, &topic),
        total,
        "the replay ends where tenure 1 committed: no skip, no event past the topic's end",
    );
    assert_eq!(
        entered_persons_range(&store2, lsk, total_persons),
        total_persons
    );
    assert!(
        !store_path.join(MARKER_FILENAME).exists(),
        "the restore finished after the events group committed",
    );

    // Dormant Left: workers re-seed the eviction queue from the restored cf_behavioral, then a sweep
    // past the window evicts every now-dormant member.
    let catalog = Arc::new(behavioral_catalog());
    let readiness = BootReadiness::new(catalog.clone());
    let left_sink = Arc::new(CaptureSink::new());
    let far_future = 4_000_000_000_000i64; // ~year 2096, past every BASE_TS + 7d deadline
    for partition in 0..NUM_PARTITIONS {
        let (tx, rx) = mpsc::channel(4);
        let rx = WorkerInbox::live_only(rx);
        let worker = Stage1Worker::spawn(
            partition as u16,
            rx,
            test_handle(&store2),
            catalog.clone(),
            left_sink.clone(),
            Arc::new(OffsetTracker::new()),
            MergeWorkerDeps::capture(),
            EvictionRestore::Rebuild(readiness.rebuild_started()),
        );
        tx.send(vec![ShuffleMessage::Sweep {
            due_before_ms: far_future,
        }])
        .await
        .unwrap();
        drop(tx);
        worker.join().await.unwrap();
    }
    let lefts = left_sink
        .changes()
        .iter()
        .filter(|change| change.status == MembershipStatus::Left)
        .count();
    assert_eq!(
        lefts, total_persons,
        "every restored-then-dormant member emits a Left from the eviction queue rebuilt over the S3-restored cf_behavioral",
    );

    // --- Cleanup: delete the topics and the S3 prefix. ---
    for name in topics.all() {
        delete_topic(name).await;
    }
    delete_s3_prefix(&config).await;
}

/// One matching `$pageview` for each of `persons`, at source offsets from `first_offset`. Returns
/// the total produced.
async fn produce_persons(
    topic: &str,
    persons: std::ops::RangeInclusive<u128>,
    first_offset: i64,
) -> usize {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("message.timeout.ms", "10000")
        .create()
        .expect("create producer");
    let mut total = 0;
    for (n, offset) in persons.zip(first_offset..) {
        let p = person(n);
        let key = format!("{TEAM}:{p}");
        producer
            .send(
                FutureRecord::to(topic)
                    .key(&key)
                    .payload(&envelope(p, 0, offset)),
                Timeout::After(Duration::from_secs(10)),
            )
            .await
            .expect("produce event");
        total += 1;
    }
    total
}

/// Each of the first `persons` whose state on one of `partitions` entered the cohort, with that
/// partition.
fn entered_by_partition(
    store: &CohortStore,
    partitions: impl Iterator<Item = u16> + Clone,
    lsk: LeafStateKey,
    persons: u128,
) -> BTreeMap<u128, u16> {
    (1..=persons)
        .filter_map(|n| {
            partitions.clone().find_map(|partition| {
                let key = BehavioralKey::new(partition, TEAM as u64, person(n), lsk);
                let state = store
                    .get_behavioral(&key)
                    .unwrap()
                    .map(|bytes| StatefulRecord::decode(&bytes).unwrap().state);
                matches!(
                    state,
                    Some(Stage1State::BehavioralSingle {
                        has_match: true,
                        ..
                    })
                )
                .then_some((n, partition))
            })
        })
        .collect()
}

/// Pod `ordinal` of two, resharded from one pod, with its own volume under `root`.
fn reshard_config(
    root: &std::path::Path,
    ordinal: u16,
    prefix: &str,
    topics: &RestoreTopics,
) -> Config {
    // Kubernetes mounts the pod's volume before the process starts.
    let volume = root.join(format!("pod-{ordinal}"));
    std::fs::create_dir_all(&volume).expect("create the pod's volume");
    let mut config = s3_restore_config(
        &volume.join("db"),
        &volume.join("checkpoints"),
        prefix,
        topics,
    );
    config.pod_name = Some(format!("cohort-stream-processor-{ordinal}"));
    config.cohort_pod_count = NonZeroU16::new(2).unwrap();
    config.cohort_reshard_from_pod_count = NonZeroU16::new(1);
    config
}

/// The split procedure through a real broker and S3. One pod folds every person and takes a
/// checkpoint, then stops. Two pods start with the reshard marker. Pod 0 reopens its store and drops
/// the odd partitions. Pod 1 waits for pod 0's claim, restores pod 0's checkpoint, and drops the even
/// ones. Every person the single pod held stays entered on the one pod that owns its partition, the
/// events after the split land on both, every commit carries its owner's stamp, and pod 1 uploads in
/// full under its own lineage.
// Multi-threaded: finishing the restore commits with `block_in_place`.
#[tokio::test(flavor = "multi_thread")]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS) AND an S3-compatible store (CHECKPOINT_S3_*); see module docs"]
async fn resharding_one_pod_into_two_keeps_every_member() {
    const BEFORE: u128 = PERSONS + NEW_PERSONS;
    const AFTER: u128 = BEFORE + 20;
    let topics = RestoreTopics::unique();
    let topic = topics.events.clone();
    let group = topics.group.clone();
    let prefix = format!("cohort-stream-checkpoints-itest/{}", Uuid::new_v4());
    for name in topics.all() {
        create_topic(name).await;
    }
    let produced = produce_events(&topic).await + produce_new_persons(&topic, NEW_PERSONS).await;

    let root = TempDir::new().unwrap();
    let single = {
        let volume = root.path().join("pod-0");
        s3_restore_config(
            &volume.join("db"),
            &volume.join("checkpoints"),
            &prefix,
            &topics,
        )
    };
    let groups = Arc::new(InputGroups::new(&single));
    let lsk = behavioral_lsk(&behavioral_catalog());
    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");
    let every_partition = || 0..NUM_PARTITIONS as u16;

    // --- Tenure 1, one pod: fold every person, checkpoint to S3, stop. ---
    let control = {
        let admitted = admit(single.split_claim().unwrap(), &groups).await;
        let store = CohortStore::open(&single.store_config(admitted.ownership()))
            .expect("open the single pod's store");
        let claimed = claim(admitted, &groups).await;
        let mut manager = Manager::builder("reshard-itest-1")
            .with_trap_signals(false)
            .build();
        let handle = manager.register(
            "consumer",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
        );
        let shutdown = handle.clone();
        let _monitor = manager.monitor_background();
        let (consumer, dispatcher) = build_consumer_with_restore(
            &topic,
            &group,
            store.clone(),
            behavioral_catalog(),
            handle,
            Arc::new(CaptureSink::new()),
            Duration::from_millis(250),
            &claimed,
            true,
            100,
        );
        let task = tokio::spawn(consumer.process());
        wait_for_committed(&verifier, &topic, produced as i64, Duration::from_secs(60)).await;
        CheckpointSweeper::new(
            store.clone(),
            dispatcher,
            groups.clone(),
            claimed,
            single.durability_config(),
            1,
            tokio_util::sync::CancellationToken::new(),
        )
        .run_once()
        .await;
        shutdown.request_shutdown();
        task.await.expect("the single pod panicked");
        entered_by_partition(&store, every_partition(), lsk, BEFORE)
    };
    assert_eq!(
        control.len(),
        BEFORE as usize,
        "the single pod entered every person"
    );

    // --- Tenure 2, two pods. The parent admits over its own stamps and reopens its store. ---
    let parent_config = reshard_config(root.path(), 0, &prefix, &topics);
    let child_config = reshard_config(root.path(), 1, &prefix, &topics);
    let admitted = admit(parent_config.split_claim().unwrap(), &groups).await;
    assert_eq!(admitted.source(), StoreSource::Own);
    let (parent_store, restore) = open_store(
        &parent_config,
        &admitted,
        Some(parent_config.checkpoint_lineage().unwrap()),
        groups.clone(),
    )
    .await
    .expect("the parent reopens its store");
    assert!(restore.is_none(), "the parent keeps its live store");
    let parent_claimed = claim(admitted, &groups).await;

    // The child takes over once the parent has claimed under the new split.
    let admitted = admit(child_config.split_claim().unwrap(), &groups).await;
    assert_eq!(
        admitted.source(),
        StoreSource::TakeOver {
            parent: PartitionOwnership::single(NUM_PARTITIONS as u16),
        }
    );
    let child_lineage = child_config.checkpoint_lineage().unwrap();
    let (child_store, restore) = open_store(
        &child_config,
        &admitted,
        Some(child_lineage),
        groups.clone(),
    )
    .await
    .expect("the child restores its parent's checkpoint");
    let restore = restore.expect("the child restores from the parent's lineage");
    let child_claimed = claim(admitted, &groups).await;

    let mut manager = Manager::builder("reshard-itest-2")
        .with_trap_signals(false)
        .build();
    let parent_handle = manager.register(
        "parent",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let child_handle = manager.register(
        "child",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let shutdown = parent_handle.clone();
    let _monitor = manager.monitor_background();
    let (parent, _) = build_consumer_with_restore(
        &topic,
        &group,
        parent_store.clone(),
        behavioral_catalog(),
        parent_handle,
        Arc::new(CaptureSink::new()),
        Duration::from_millis(250),
        &parent_claimed,
        true,
        100,
    );
    let (child, child_dispatcher) = build_consumer_finishing_restore(
        &topic,
        &group,
        child_store.clone(),
        behavioral_catalog(),
        child_handle,
        Arc::new(CaptureSink::new()),
        Duration::from_millis(250),
        restore,
        &child_claimed,
    );
    let tasks = [
        tokio::spawn(parent.process()),
        tokio::spawn(child.process()),
    ];

    let produced = produced + produce_persons(&topic, BEFORE + 1..=AFTER, 1_000).await;
    wait_for_committed(&verifier, &topic, produced as i64, Duration::from_secs(60)).await;
    CheckpointSweeper::new(
        child_store.clone(),
        child_dispatcher,
        groups.clone(),
        child_claimed,
        child_config.durability_config(),
        1,
        tokio_util::sync::CancellationToken::new(),
    )
    .run_once()
    .await;
    shutdown.request_shutdown();
    for task in tasks {
        task.await.expect("a pod panicked");
    }

    let owned = |ordinal: u16| every_partition().filter(move |p| p % 2 == ordinal);
    for (ordinal, store) in [(0, &parent_store), (1, &child_store)] {
        let given_away: Vec<u16> = owned(1 - ordinal)
            .filter(|&p| partition_has_state(store, i32::from(p), lsk, AFTER))
            .collect();
        assert!(
            given_away.is_empty(),
            "pod {ordinal} still holds the partitions it gave away: {given_away:?}",
        );
    }
    let mut entered = entered_by_partition(&parent_store, owned(0), lsk, AFTER);
    entered.extend(entered_by_partition(&child_store, owned(1), lsk, AFTER));
    let kept: BTreeMap<u128, u16> = entered
        .iter()
        .filter(|&(&n, _)| n <= BEFORE)
        .map(|(&n, &p)| (n, p))
        .collect();
    assert_eq!(kept, control, "every member stays on the partition it had");
    assert_eq!(
        entered.keys().copied().collect::<BTreeSet<u128>>(),
        (1..=AFTER).collect(),
        "the events after the split entered on both pods",
    );
    assert!(entered.values().any(|&p| p % 2 == 1) && entered.values().any(|&p| p % 2 == 0));

    let ledger = groups
        .ledger(&every_partition().collect())
        .expect("read the ledger");
    for input in ledger.inputs() {
        for (&partition, committed) in input.commits() {
            let owner = PartitionOwnership::new(
                NonZeroU16::new(2).unwrap(),
                PodOrdinal::from(partition % 2),
                NUM_PARTITIONS as u16,
            )
            .unwrap();
            assert_eq!(
                committed.stamp(),
                Some(&Stamp::Split(owner)),
                "{} partition {partition}",
                input.topic(),
            );
        }
    }

    let uploaded: serde_json::Value = serde_json::from_slice(
        &std::fs::read(
            child_lineage
                .local_dir(std::path::Path::new(&child_config.checkpoint_local_dir))
                .join("uploaded.json"),
        )
        .expect("the child uploads a checkpoint"),
    )
    .unwrap();
    assert_eq!(uploaded["metadata"]["ordinal"], 1, "under its own lineage");
    assert_eq!(
        uploaded["metadata"]["full_upload_at"], uploaded["metadata"]["attempt_timestamp"],
        "the child's first upload is full, so its chain names nothing in the parent's lineage",
    );

    for name in topics.all() {
        delete_topic(name).await;
    }
    delete_s3_prefix(&single).await;
    delete_s3_prefix(&child_config).await;
}
