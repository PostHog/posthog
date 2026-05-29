//! End-to-end test for the `cohort_stream_events` consumer (PR 1.7) against a **real** Kafka broker.
//!
//! `#[ignore]`d by default — consistent with the crate's live-Postgres catalog test
//! (`filters::manager::tests::refresh_builds_catalog_from_live_postgres`). The consumer joins a
//! consumer group, commits a `TopicPartitionList`, and reads its own committed offsets back, none of
//! which the in-process `MockCluster` exercises faithfully. Run against a local stack with:
//!
//! ```sh
//! cargo test -p cohort-stream-processor --test events_consumer -- --ignored
//! ```
//!
//! It produces JSON `CohortStreamEvent` envelopes, runs the real consumer against a tempfile
//! `CohortStore` and an in-memory catalog seeded with a behavioral `$pageview` cohort, then asserts
//! the two acceptance points: (a) Stage 1 state rows are written for the matching events, and
//! (b) the committed offsets advance to cover every produced event.
//!
//! The routing / lazy-spawn / offset-marking logic is additionally covered by the CI-runnable
//! (no-Kafka) unit tests in `src/consumers/events.rs`; this proves the wiring end-to-end.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use cohort_stream_processor::consumers::{CohortStreamEventsConsumer, EventDispatcher};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{OffsetTracker, PartitionRouter};
use cohort_stream_processor::producer::{
    CaptureSink, CohortMembershipChange, KafkaMembershipSink, MembershipSink, MembershipStatus,
};
use cohort_stream_processor::stage1::{Stage1State, StatefulRecord};
use cohort_stream_processor::store::{CohortStore, LeafStateKey, Stage1Key, StoreConfig};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::KafkaProduceError;
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

/// A team with a single `performed_event` behavioral leaf on `$pageview` (window 7d) — every
/// `$pageview` matches and enters. Seeded straight into an in-memory catalog (no Postgres).
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
        builder.freeze(),
    )]))
}

/// The behavioral leaf's `LeafStateKey`, read back through the catalog the way the worker derives it.
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

/// Produce `EVENTS_PER_PERSON` events for each of `PERSONS` persons, keyed `"{team}:{person}"` so a
/// person's events co-partition. Returns the total produced.
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

/// Build the consumer under test: a fresh group reading from the start of the topic, a tempfile
/// store, the seeded catalog, and a fast commit cadence so committed offsets advance promptly.
fn build_consumer(
    topic: &str,
    group: &str,
    store: CohortStore,
    catalog: CatalogHandle,
    handle: lifecycle::Handle,
    sink: Arc<dyn MembershipSink>,
    offset_commit_interval: Duration,
) -> CohortStreamEventsConsumer {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .create()
        .expect("create consumer");
    consumer.subscribe(&[topic]).expect("subscribe");

    let dispatcher = EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        store,
        Arc::new(catalog),
        sink,
    );
    CohortStreamEventsConsumer::new(
        consumer,
        topic.to_string(),
        dispatcher,
        handle,
        100,
        Duration::from_millis(200),
        offset_commit_interval,
    )
}

/// Common Kafka config for the shadow producer in the broker-gated tests, mirroring the service's
/// `Config::build_kafka_config` (the `murmur2_random` partitioner is load-bearing).
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

/// Drain up to `expected` membership changes off the shadow topic, decoding each into a
/// [`CohortMembershipChange`]. Returns whatever it gathered before the deadline.
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
            Err(_) => {} // 2s poll tick elapsed with no message; re-check the deadline
        }
    }
    changes
}

/// Sum of `Offset::Offset` committed across every partition — equals the number of consumed events
/// for a fresh topic starting at offset 0 (committed = next-offset-to-consume).
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

/// Count persons whose behavioral leaf entered, scanning every topic partition (the store key's
/// `partition_id`) since a person's partition depends on the producer's key hash.
fn entered_persons(store: &CohortStore, lsk: LeafStateKey) -> usize {
    (1..=PERSONS)
        .filter(|&n| {
            let p = person(n);
            (0..NUM_PARTITIONS).any(|partition| {
                let key = Stage1Key {
                    partition_id: partition as u16,
                    team_id: TEAM as u64,
                    leaf_state_key: lsk,
                    person_id: p,
                };
                matches!(
                    store
                        .get_stage1(&key)
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

    // A standalone-but-not-subscribed consumer in the same group reads committed offsets without
    // triggering a rebalance of the consumer under test (an OffsetFetch RPC, not a group join).
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

    // This test asserts state rows + committed input offsets, not the shadow output, so a capture
    // sink (which always acks) suffices to drive the produce-before-commit offset marking.
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

    // (b) Wait until every produced event has been consumed, routed, and its offset committed.
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

    // Stop the consumer: dropping the router drains the workers (applying all routed state) before
    // the final commit, so state is durable by the time `process()` returns.
    shutdown_handle.request_shutdown();
    task.await.expect("consumer task panicked");

    // (a) Every person entered the behavioral leaf exactly once.
    assert_eq!(
        entered_persons(&store, lsk),
        PERSONS as usize,
        "every produced person should have entered the behavioral leaf",
    );

    // (b) The committed offsets cover every produced event (re-read after the final sync commit).
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

    // The real Kafka sink, producing to the shadow topic.
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

    // Wait until every produced input event has been consumed, produced downstream, and committed.
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

    // (a) Exactly one `entered` change per distinct person landed on the shadow topic: the first
    // `$pageview` per person enters the single-leaf cohort; the repeats are already members. Because
    // an offset is committed only after its produce is acked, every change is on the topic by now.
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

    // (b) Committed input offsets cover every produced event.
    assert_eq!(committed_sum(&verifier, &input_topic), total as i64);
}

/// A test [`MembershipSink`] that blocks its **first** flush until released, recording everything it
/// is given. Used to prove "produce before commit": while the first flush is parked, the worker has
/// not yet marked its offset, so no commit tick can advance the committed offset past the blocked
/// event.
struct BarrierSink {
    entered: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
    first: AtomicBool,
    recorded: Arc<Mutex<Vec<CohortMembershipChange>>>,
}

impl BarrierSink {
    /// Returns the sink plus the `entered` (worker reached the flush) and `release` (let it proceed)
    /// signals. `tokio::sync::Notify` is permit-based for `notify_one`, so the test and worker may
    /// signal in either order without losing the wake-up.
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

    // A single event, so exactly one worker performs exactly one (blocked) flush.
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

    // Fast commit cadence so a commit tick certainly fires while the produce is blocked.
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

    // Wait until the worker has reached the (blocked) flush.
    tokio::time::timeout(Duration::from_secs(30), entered.notified())
        .await
        .expect("worker reached the produce barrier");

    // Let several commit ticks fire while blocked. The worker has not marked its offset yet, so the
    // committed offset must NOT have advanced past the event whose produce is still in flight.
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

    // Release the flush; now the offset is allowed to advance.
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
