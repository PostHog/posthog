//! End-to-end tests for the `cohort_stream_events` consumer against a **real** Kafka broker.
//!
//! `#[ignore]`d by default: the consumer joins a consumer group, commits a `TopicPartitionList`,
//! and reads its own committed offsets back, none of which the in-process `MockCluster` exercises
//! faithfully. Run against a local stack with:
//!
//! ```sh
//! cargo test -p cohort-stream-processor --test events_consumer -- --ignored
//! ```
//!
//! The S3/PVC disaster-recovery e2e
//! ([`s3_restore_reseeds_state_resumes_at_manifest_offset_and_fires_a_dormant_left`]) additionally
//! needs an S3-compatible store (MinIO / SeaweedFS). Point it at one with:
//!
//! ```sh
//! export KAFKA_HOSTS=localhost:9092
//! export CHECKPOINT_S3_ENDPOINT=http://localhost:19000   # MinIO; or :8333 for SeaweedFS
//! export CHECKPOINT_S3_BUCKET=cohort-checkpoints          # must already exist
//! export CHECKPOINT_S3_ACCESS_KEY_ID=...                  # MinIO/SeaweedFS creds
//! export CHECKPOINT_S3_SECRET_ACCESS_KEY=...
//! cargo test -p cohort-stream-processor --test events_consumer -- --ignored s3_restore
//! ```
//!
//! Every test creates 4-partition topics and deletes the Kafka topic on exit (a leaked high-partition
//! topic wedges later runs); the S3 e2e also sweeps its per-test S3 prefix on exit.

// Tests seed and assert through `CohortStore` directly — the sanctioned direct-store test surface.
#![allow(clippy::disallowed_methods)]

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono_tz::UTC;
use cohort_stream_processor::config::Config;
use cohort_stream_processor::consumers::{CohortStreamEventsConsumer, EventDispatcher};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{
    run_rebalance_worker, CohortConsumerContext, MeteredReceiver, OffsetTracker, PartitionMirror,
    PartitionRouter, ShuffleMessage,
};
use cohort_stream_processor::producer::{
    CaptureSink, CohortMembershipChange, KafkaMembershipSink, MembershipSink, MembershipStatus,
};
use cohort_stream_processor::stage1::{Stage1State, StatefulRecord};
use cohort_stream_processor::store::durability::{
    run_boot_restore, upload_cadence, CheckpointExporter, CheckpointSweeper, OffsetManifest,
    RestoreSource, S3Uploader,
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
use cohort_stream_processor::workers::{MergeWorkerDeps, Stage1Worker};
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

struct NoopMirror;

impl PartitionMirror for NoopMirror {
    fn assign(&self, _partitions: &[i32]) {}
    fn unassign(&self, _partitions: &[i32]) {}
}

fn build_consumer(
    topic: &str,
    group: &str,
    store: CohortStore,
    catalog: CatalogHandle,
    handle: lifecycle::Handle,
    sink: Arc<dyn MembershipSink>,
    offset_commit_interval: Duration,
) -> CohortStreamEventsConsumer {
    build_consumer_with_restore(
        topic,
        group,
        store,
        catalog,
        handle,
        sink,
        offset_commit_interval,
        false,
    )
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
    durable_restore: bool,
) -> CohortStreamEventsConsumer {
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

    let (context, rebalance_rx) = CohortConsumerContext::new(dispatcher.clone());
    let consumer: StreamConsumer<CohortConsumerContext> = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest")
        .set("partition.assignment.strategy", "cooperative-sticky")
        .set("session.timeout.ms", "6000")
        .create_with_context(context)
        .expect("create consumer");
    consumer.subscribe(&[topic]).expect("subscribe");

    let (consumer_command_tx, consumer_command_rx) = mpsc::unbounded_channel();
    tokio::spawn(run_rebalance_worker(
        rebalance_rx,
        dispatcher.clone(),
        Arc::new(NoopMirror),
        consumer_command_tx,
        handle.shutdown_token(),
    ));

    CohortStreamEventsConsumer::new(
        consumer,
        topic.to_string(),
        dispatcher,
        handle,
        100,
        Duration::from_millis(200),
        offset_commit_interval,
        NUM_PARTITIONS as usize,
        consumer_command_rx,
        None,
    )
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
    );
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
    );
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
    );
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
    );
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

/// Whether any produced person has behavioral state under `partition` in `store`.
fn partition_has_state(store: &CohortStore, partition: i32, lsk: LeafStateKey) -> bool {
    (1..=PERSONS).any(|n| {
        let key = BehavioralKey::new(partition as u16, TEAM as u64, person(n), lsk);
        store.get_behavioral(&key).unwrap().is_some()
    })
}

fn distinct_entered(changes: &[CohortMembershipChange]) -> usize {
    changes
        .iter()
        .filter(|change| change.status == MembershipStatus::Entered)
        .map(|change| change.person_id.clone())
        .collect::<std::collections::HashSet<_>>()
        .len()
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
async fn cooperative_sticky_migration_preserves_offsets_and_partition_colocation() {
    let suffix = Uuid::new_v4();
    let topic = format!("cohort_stream_events_migrate_{suffix}");
    let group = format!("cohort-stream-processor-migrate-{suffix}");
    create_topic(&topic).await;

    let catalog_a = behavioral_catalog();
    let catalog_b = behavioral_catalog();
    let lsk = behavioral_lsk(&catalog_a);

    let dir_a = TempDir::new().unwrap();
    let store_a = CohortStore::open(&StoreConfig {
        path: dir_a.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store A");
    let dir_b = TempDir::new().unwrap();
    let store_b = CohortStore::open(&StoreConfig {
        path: dir_b.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store B");

    let sink_a = Arc::new(CaptureSink::new());
    let sink_b = Arc::new(CaptureSink::new());

    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier");

    let mut manager = Manager::builder("migrate-itest")
        .with_trap_signals(false)
        .build();
    let handle_a = manager.register(
        "consumer-a",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let handle_b = manager.register(
        "consumer-b",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let shutdown = handle_a.clone();
    let _monitor = manager.monitor_background();

    // Batch 1: only A is up.
    let batch1 = produce_events(&topic).await;
    let consumer_a = build_consumer(
        &topic,
        &group,
        store_a.clone(),
        catalog_a,
        handle_a,
        sink_a.clone(),
        Duration::from_millis(250),
    );
    let task_a = tokio::spawn(consumer_a.process());
    wait_for_committed(&verifier, &topic, batch1 as i64, Duration::from_secs(60)).await;

    // B joins → cooperative-sticky moves ~half the partitions off A.
    let consumer_b = build_consumer(
        &topic,
        &group,
        store_b.clone(),
        catalog_b,
        handle_b,
        sink_b.clone(),
        Duration::from_millis(250),
    );
    let task_b = tokio::spawn(consumer_b.process());

    // Batch 2: split across both pods.
    let batch2 = produce_events(&topic).await;
    let total = (batch1 + batch2) as i64;
    wait_for_committed(&verifier, &topic, total, Duration::from_secs(60)).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    shutdown.request_shutdown();
    task_a.await.expect("consumer A panicked");
    task_b.await.expect("consumer B panicked");

    assert_eq!(
        committed_sum(&verifier, &topic),
        total,
        "committed offsets cover every produced event",
    );

    // Co-location: no partition's state lives in both pods at once.
    for partition in 0..NUM_PARTITIONS {
        assert!(
            !(partition_has_state(&store_a, partition, lsk)
                && partition_has_state(&store_b, partition, lsk)),
            "partition {partition} has state in both pods — affinity invariant violated",
        );
    }
    let entered_a = entered_persons(&store_a, lsk);
    let entered_b = entered_persons(&store_b, lsk);
    assert_eq!(
        entered_a + entered_b,
        PERSONS as usize,
        "every person has state in exactly one pod (a={entered_a}, b={entered_b})",
    );

    let mut changes = sink_a.changes();
    changes.extend(sink_b.changes());
    assert_eq!(
        distinct_entered(&changes),
        PERSONS as usize,
        "every person entered exactly once (idempotent re-produce aside)",
    );
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
/// covers every event — and (iii) fire each now-dormant member's `Left` from the rebuilt queue.
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
        let consumer = build_consumer_with_restore(
            &topic,
            &group,
            store.clone(),
            behavioral_catalog(),
            handle,
            Arc::new(CaptureSink::new()),
            Duration::from_millis(250),
            true,
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

    // --- Dormant Left: durable workers re-seed queues from cf_behavioral; a sweep past the window
    // evicts each member with no new events. ---
    let catalog = Arc::new(behavioral_catalog());
    let sink = Arc::new(CaptureSink::new());
    let far_future = 4_000_000_000_000i64; // ~year 2096, well past every BASE_TS + 7d deadline
    for partition in 0..NUM_PARTITIONS {
        let (tx, rx) = mpsc::channel(4);
        let rx = MeteredReceiver::unmetered(rx);
        let worker = Stage1Worker::spawn(
            partition as u16,
            rx,
            test_handle(&store2),
            catalog.clone(),
            sink.clone(),
            Arc::new(OffsetTracker::new()),
            MergeWorkerDeps::capture(),
            true,
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
        lefts, PERSONS as usize,
        "every restored-then-dormant member emits a Left from the rebuilt eviction queue",
    );

    delete_topic(&topic).await;
}

// ===========================================================================================
// S3/PVC disaster-recovery e2e. Needs a broker AND an S3-compatible store; see the module docs.
// ===========================================================================================

/// Build a `Config` for the disaster-recovery e2e. `store_path` and `checkpoint_local_dir` must be
/// separate temp subtrees: rocksdb hard-links SSTs into the checkpoint, so it must be a *sibling* of
/// the store, never nested.
fn s3_restore_config(
    store_path: &std::path::Path,
    checkpoint_dir: &std::path::Path,
    prefix: &str,
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
    Config::init_from_hashmap(&env).expect("build s3-restore config")
}

/// Like [`build_consumer_with_restore`], but threads the restore `manifest` into the consumer so it
/// seeks the events topic to the restored committed offsets on boot.
#[allow(clippy::too_many_arguments)]
fn build_consumer_with_manifest(
    topic: &str,
    group: &str,
    store: CohortStore,
    catalog: CatalogHandle,
    handle: lifecycle::Handle,
    sink: Arc<dyn MembershipSink>,
    offset_commit_interval: Duration,
    manifest: Option<OffsetManifest>,
) -> CohortStreamEventsConsumer {
    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        test_handle(&store),
        Arc::new(catalog),
        sink,
        MergeWorkerDeps::capture(),
    ));
    dispatcher.enable_durable_restore();

    let (context, rebalance_rx) = CohortConsumerContext::new(dispatcher.clone());
    let consumer: StreamConsumer<CohortConsumerContext> = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest")
        .set("partition.assignment.strategy", "cooperative-sticky")
        .set("session.timeout.ms", "6000")
        .create_with_context(context)
        .expect("create consumer");
    consumer.subscribe(&[topic]).expect("subscribe");

    let (consumer_command_tx, consumer_command_rx) = mpsc::unbounded_channel();
    tokio::spawn(run_rebalance_worker(
        rebalance_rx,
        dispatcher.clone(),
        Arc::new(NoopMirror),
        consumer_command_tx,
        handle.shutdown_token(),
    ));

    CohortStreamEventsConsumer::new(
        consumer,
        topic.to_string(),
        dispatcher,
        handle,
        100,
        Duration::from_millis(200),
        offset_commit_interval,
        NUM_PARTITIONS as usize,
        consumer_command_rx,
        manifest,
    )
}

/// Read each partition's committed offset from the broker into a `partition -> next-offset` map — the
/// next-to-consume position the manifest must carry.
fn committed_offsets_map(consumer: &StreamConsumer, topic: &str) -> HashMap<i32, i64> {
    let mut tpl = TopicPartitionList::new();
    for partition in 0..NUM_PARTITIONS {
        tpl.add_partition(topic, partition);
    }
    let committed = consumer
        .committed_offsets(tpl, Duration::from_secs(5))
        .expect("fetch committed offsets");
    (0..NUM_PARTITIONS)
        .filter_map(|partition| {
            committed
                .find_partition(topic, partition)
                .and_then(|elem| match elem.offset() {
                    Offset::Offset(value) => Some((partition, value)),
                    _ => None,
                })
        })
        .collect()
}

/// Delete every S3 object under the configured prefix on test exit. Best-effort: builds a throwaway
/// `object_store` client from the durability config and sweeps the per-test prefix. Any error
/// building, listing, or deleting is ignored so cleanup never fails a passing test.
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
    let prefix = ObjPath::from(d.s3_key_prefix.as_str());
    let mut stream = store.list(Some(&prefix));
    while let Some(entry) = stream.next().await {
        if let Ok(meta) = entry {
            let _result = store.delete(&meta.location).await;
        }
    }
}

/// Full disaster-recovery path through a real broker + S3: fold + checkpoint to S3 (tenure 1), delete
/// the store + checkpoint dirs (PVC loss), then restore from S3 and seek the manifest offsets (tenure
/// 2). Asserts state is restored (not cold-replayed), the resume neither skips nor re-folds, and a
/// dormant `Left` fires from the eviction queue rebuilt over the restored `cf_behavioral`.
///
/// Asserting count-exact (not mere presence) sidesteps the documented fast-broker flake.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS) AND an S3-compatible store (CHECKPOINT_S3_*); see module docs"]
async fn s3_restore_reseeds_state_resumes_at_manifest_offset_and_fires_a_dormant_left() {
    let suffix = Uuid::new_v4();
    let topic = format!("cohort_stream_events_s3restore_{suffix}");
    let group = format!("cohort-stream-processor-s3restore-{suffix}");
    let prefix = format!("cohort-stream-checkpoints-itest/{suffix}");

    create_topic(&topic).await;
    let total = produce_events(&topic).await;

    // Store and checkpoint dirs must be sibling subtrees, never nested (see `s3_restore_config`).
    let root = TempDir::new().unwrap();
    let store_path = root.path().join("db");
    let checkpoint_dir = root.path().join("checkpoints");
    let config = s3_restore_config(&store_path, &checkpoint_dir, &prefix);
    let lsk = behavioral_lsk(&behavioral_catalog());

    // Reads committed offsets without joining the group.
    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", &group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create verifier consumer");

    // --- Tenure 1: fold + fsync-commit, then checkpoint + upload to S3. ---
    {
        let store = CohortStore::open(&config.store_config()).expect("open tenure-1 store");
        let mut manager = Manager::builder("s3restore-itest-1")
            .with_trap_signals(false)
            .build();
        let handle = manager.register(
            "consumer",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
        );
        let shutdown_handle = handle.clone();
        let _monitor = manager.monitor_background();
        let consumer = build_consumer_with_restore(
            &topic,
            &group,
            store.clone(),
            behavioral_catalog(),
            handle,
            Arc::new(CaptureSink::new()),
            Duration::from_millis(250),
            true,
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
            "tenure 1 folded every produced person",
        );

        // Drive one checkpoint tick directly: a dispatcher owning all partitions + an events tracker
        // seeded from the broker's committed offsets, so the captured manifest carries the resume
        // positions. upload_every_n = 1 ⇒ the first tick uploads.
        let ckpt_dispatcher = Arc::new(EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            test_handle(&store),
            Arc::new(behavioral_catalog()),
            Arc::new(CaptureSink::new()),
            MergeWorkerDeps::capture(),
        ));
        let events_tracker = Arc::new(OffsetTracker::new());
        for (partition, next_offset) in committed_offsets_map(&verifier, &topic) {
            ckpt_dispatcher.assign_partition(partition);
            // Seed committed so `OffsetManifest::capture` (which reads committed_offset) records it.
            events_tracker.mark_dispatched(partition, next_offset);
            let _ = events_tracker.mark_processed(partition, next_offset);
            events_tracker.mark_committed(partition, next_offset);
        }
        let uploader = S3Uploader::new(config.durability_config())
            .await
            .expect("build S3 uploader (is the bucket reachable?)");
        let exporter = CheckpointExporter::new(Box::new(uploader));
        let sweeper = CheckpointSweeper::new(
            store.clone(),
            ckpt_dispatcher,
            vec![(topic.clone(), events_tracker)],
            exporter,
            config.durability_config(),
            checkpoint_dir.clone(),
            upload_cadence(
                config.checkpoint_interval_ms,
                config.checkpoint_s3_upload_interval_ms,
            ),
        );
        sweeper.run_once().await;
    } // tenure-1 store + dispatcher drop here, releasing the RocksDB lock

    // --- PVC loss: delete BOTH the live store and the local checkpoint dir. ---
    std::fs::remove_dir_all(&store_path).expect("remove store_path (simulate PVC loss)");
    std::fs::remove_dir_all(&checkpoint_dir)
        .expect("remove checkpoint_local_dir (simulate PVC loss)");

    // --- Tenure 2: restore from S3 + seek the manifest offsets. ---
    let restore = run_boot_restore(&config, &store_path).await;
    assert_eq!(
        restore.source,
        RestoreSource::S3,
        "with the live store and local checkpoint gone, the restore must come from S3",
    );
    let manifest = restore
        .manifest
        .clone()
        .expect("an S3 restore yields an offset manifest to seek");

    let store2 = CohortStore::open(&StoreConfig {
        path: store_path.clone(),
        wipe_on_start: false,
        ..StoreConfig::default()
    })
    .expect("open restored store");
    // (a) Full state present — restored from S3, not cold-replayed. Count-exact (not mere presence).
    assert_eq!(
        entered_persons(&store2, lsk),
        PERSONS as usize,
        "the S3 restore re-seeded every member's state (a cold start would read 0)",
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
    let consumer = build_consumer_with_manifest(
        &topic,
        &group,
        store2.clone(),
        behavioral_catalog(),
        handle,
        Arc::new(CaptureSink::new()),
        Duration::from_millis(250),
        Some(manifest),
    );
    let task = tokio::spawn(consumer.process());

    // (b) Resumes at the manifest offset: no skip and no re-fold. Let the loop settle, seek, and idle;
    // with no events past `total`, committed must stay exactly `total`.
    tokio::time::sleep(Duration::from_secs(5)).await;
    shutdown_handle.request_shutdown();
    task.await.expect("tenure-2 consumer panicked");
    assert_eq!(
        committed_sum(&verifier, &topic),
        total as i64,
        "resumed exactly at the manifest offset — no skip, no re-fold past the committed position",
    );
    assert_eq!(
        entered_persons(&store2, lsk),
        PERSONS as usize,
        "state count is still exact after the restore-seek resume",
    );

    // (c) Dormant Left: workers re-seed the eviction queue from the restored cf_behavioral, then a sweep
    // past the window evicts every now-dormant member.
    let catalog = Arc::new(behavioral_catalog());
    let left_sink = Arc::new(CaptureSink::new());
    let far_future = 4_000_000_000_000i64; // ~year 2096, past every BASE_TS + 7d deadline
    for partition in 0..NUM_PARTITIONS {
        let (tx, rx) = mpsc::channel(4);
        let rx = MeteredReceiver::unmetered(rx);
        let worker = Stage1Worker::spawn(
            partition as u16,
            rx,
            test_handle(&store2),
            catalog.clone(),
            left_sink.clone(),
            Arc::new(OffsetTracker::new()),
            MergeWorkerDeps::capture(),
            true,
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
        lefts, PERSONS as usize,
        "every restored-then-dormant member emits a Left from the eviction queue rebuilt over the S3-restored cf_behavioral",
    );

    // --- Cleanup: delete the topic and the S3 prefix. ---
    delete_topic(&topic).await;
    delete_s3_prefix(&config).await;
}
