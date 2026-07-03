//! End-to-end tests for the cross-partition merge protocol against a **real** Kafka broker: the two
//! follower consumers, the assignment mirror, the keyed transfer / re-key produces, and the
//! per-topic offset commits, wired exactly like `main.rs`.
//!
//! `#[ignore]`d by default (group joins, committed-offset round-trips, and `incremental_assign`
//! semantics that the in-process `MockCluster` does not exercise faithfully). All topics are created
//! with the production partition count (64) because the protocol's partition arithmetic is the thing
//! under test. Run against a local stack serially:
//!
//! ```sh
//! cargo test -p cohort-stream-processor --test merge_consumer -- --ignored --test-threads=1
//! ```
//!
//! Each test deletes its topics on the way out via `with_topics_cleanup`. If that never runs
//! (killed process), sweep leftovers with:
//!
//! ```sh
//! docker exec posthog-kafka-1 sh -c 'rpk topic list | awk "{print \$1}" \
//!   | grep -E "_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$" \
//!   | xargs -r rpk topic delete'
//! ```

// This test drives the store directly through `CohortStore` for seeding and assertions — the
// sanctioned direct-store surface for tests.
#![allow(clippy::disallowed_methods)]

use std::collections::HashSet;
use std::future::Future;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono_tz::UTC;
use cohort_stream_processor::consumers::{
    CohortStreamEvent, CohortStreamEventsConsumer, EventDispatcher, FollowerConsumer, MergeRoute,
    TransferRoute,
};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::merge::transfer::{
    MergeStateTransfer, PersonMergeEvent, Tombstone, MERGE_EVENT_SCHEMA_VERSION,
};
use cohort_stream_processor::partitions::{
    merge_partition_key, partition_of, run_rebalance_worker, CohortConsumerContext, Follower,
    FollowerSet, OffsetTracker, PartitionRouter, COHORT_PARTITION_COUNT,
};
use cohort_stream_processor::producer::{
    CaptureCascadeSink, CaptureSink, CohortMembershipChange, KafkaMembershipSink,
    KafkaStreamEventSink, KafkaTransferSink, MembershipSink, MembershipStatus, StreamEventSink,
    TransferSink,
};
use cohort_stream_processor::stage1::{Stage1State, StateVariant, StatefulRecord};
use cohort_stream_processor::store::{
    CohortStore, LeafStateKey, OffloadConfig, OffloadMode, Stage1Key, StoreConfig, StoreHandle,
    TombstoneKey,
};
use cohort_stream_processor::workers::{
    CascadeConfig, MergeWorkerDeps, TransferRetryPolicy, DEFAULT_MERGE_GC_SCAN_LIMIT,
};
use common_kafka::config::KafkaConfig;
use futures::FutureExt;
use lifecycle::{ComponentOptions, Handle, Manager};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use serde_json::json;
use tempfile::TempDir;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use uuid::Uuid;

const TEAM: i32 = 7;
const HASH: [u8; 16] = *b"0123456789abcdef";
const NUM_PARTITIONS: i32 = COHORT_PARTITION_COUNT as i32;
const TS: &str = "2026-06-10 12:34:56.789000";
const TS_LATER: &str = "2026-06-10 13:34:56.789000";
const MERGED_AT: i64 = 1_770_000_000_000;
const COMMIT_INTERVAL: Duration = Duration::from_millis(250);
const RECV_TIMEOUT: Duration = Duration::from_millis(200);

fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

/// Cohort 1: `performed_event` single. Cohort 2: `performed_event_multiple gte 2` daily.
/// Both share one `$pageview` conditionHash; daily bucket counts make a double-apply observable.
fn merge_catalog() -> CatalogHandle {
    let single = json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "time_value": 7, "time_interval": "day",
        "conditionHash": "0123456789abcdef",
        "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
    });
    let daily = json!({
        "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
        "time_value": 7, "time_interval": "day", "operator": "gte", "operator_value": 2,
        "conditionHash": "0123456789abcdef",
        "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
    });
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(1),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [single] } }),
        )
        .expect("add single cohort");
    builder
        .add_cohort(
            CohortId(2),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [daily] } }),
        )
        .expect("add daily cohort");
    CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(TEAM),
        builder.freeze(UTC),
    )]))
}

fn behavioral_lsks(catalog: &CatalogHandle) -> (LeafStateKey, LeafStateKey) {
    let snapshot = catalog.load();
    let team = snapshot.team(TeamId(TEAM)).expect("team in catalog");
    let pick = |variant: StateVariant| {
        team.by_condition_to_lsk[&HASH]
            .iter()
            .copied()
            .find(|lsk| team.by_lsk[lsk].variant == variant)
            .unwrap_or_else(|| panic!("no LSK for {variant:?}"))
    };
    (
        pick(StateVariant::BehavioralSingle),
        pick(StateVariant::BehavioralDailyBuckets),
    )
}

async fn create_topic(topic: &str, partitions: i32) {
    let admin: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .create()
        .expect("create admin client");
    let new_topic = NewTopic::new(topic, partitions, TopicReplication::Fixed(1));
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
    let verifier: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", format!("metadata-verifier-{}", Uuid::new_v4()))
        .create()
        .expect("create metadata verifier");
    let start = Instant::now();
    loop {
        let ready = verifier
            .fetch_metadata(Some(topic), Duration::from_secs(5))
            .ok()
            .is_some_and(|metadata| {
                metadata.topics().iter().any(|meta| {
                    meta.name() == topic
                        && meta.error().is_none()
                        && meta.partitions().len() == partitions as usize
                })
            });
        if ready {
            break;
        }
        assert!(
            start.elapsed() < Duration::from_secs(30),
            "timed out waiting for topic {topic} metadata to propagate",
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

async fn delete_topics(topics: &[&str]) {
    let admin: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .create()
        .expect("create admin client");
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));
    if let Err(err) = admin.delete_topics(topics, &opts).await {
        eprintln!("topic cleanup failed; leaked {topics:?}: {err}");
    }
}

/// Run a test body, delete `topics` whether it passed or panicked, then re-propagate any panic.
async fn with_topics_cleanup<F: Future<Output = ()>>(topics: &[&str], body: F) {
    let result = AssertUnwindSafe(body).catch_unwind().await;
    delete_topics(topics).await;
    if let Err(panic) = result {
        std::panic::resume_unwind(panic);
    }
}

/// `murmur2_random` is required so keyed produces co-partition with `partition_of`.
fn producer_kafka_config() -> KafkaConfig {
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

fn murmur2_producer() -> FutureProducer {
    ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("message.timeout.ms", "10000")
        .set("partitioner", "murmur2_random")
        .create()
        .expect("create murmur2 producer")
}

fn events_client_config(group: &str) -> ClientConfig {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest")
        .set("partition.assignment.strategy", "cooperative-sticky")
        .set("session.timeout.ms", "6000");
    config
}

fn follower_client_config(group: &str) -> ClientConfig {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest")
        .set("socket.timeout.ms", "10000");
    config
}

fn group_verifier(group: &str) -> StreamConsumer {
    ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("create group verifier")
}

/// Sum of committed offsets across all partitions (committed == next-offset-to-consume on a fresh topic).
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

fn topic_message_count(topic: &str) -> i64 {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", format!("watermark-verifier-{}", Uuid::new_v4()))
        .create()
        .expect("create watermark verifier");
    (0..NUM_PARTITIONS)
        .map(|partition| {
            let (low, high) = consumer
                .fetch_watermarks(topic, partition, Duration::from_secs(10))
                .expect("fetch watermarks");
            high - low
        })
        .sum()
}

/// Read up to `expected` messages (all partitions from the beginning). Assigned explicitly — no group
/// join, no commit — so committed offsets the test asserts on are never perturbed.
async fn consume_all(topic: &str, expected: usize, deadline: Duration) -> Vec<(i32, Vec<u8>)> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", format!("scan-verifier-{}", Uuid::new_v4()))
        .set("enable.auto.commit", "false")
        .create()
        .expect("create scan verifier");
    let mut tpl = TopicPartitionList::new();
    for partition in 0..NUM_PARTITIONS {
        tpl.add_partition_offset(topic, partition, Offset::Beginning)
            .expect("add partition to scan TPL");
    }
    consumer.assign(&tpl).expect("assign scan verifier");

    let mut messages = Vec::new();
    let start = Instant::now();
    while messages.len() < expected && start.elapsed() < deadline {
        match tokio::time::timeout(Duration::from_secs(2), consumer.recv()).await {
            Ok(Ok(message)) => {
                if let Some(payload) = message.payload() {
                    messages.push((message.partition(), payload.to_vec()));
                }
            }
            Ok(Err(err)) => panic!("scan verifier recv error: {err}"),
            Err(_) => {}
        }
    }
    messages
}

async fn wait_for(what: &str, deadline: Duration, mut condition: impl FnMut() -> bool) {
    let start = Instant::now();
    while !condition() {
        assert!(
            start.elapsed() < deadline,
            "timed out after {deadline:?} waiting for {what}",
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

fn part(person: Uuid) -> u16 {
    partition_of(TeamId(TEAM), &person, COHORT_PARTITION_COUNT) as u16
}

struct PersonAlloc(u128);

impl PersonAlloc {
    fn new() -> Self {
        Self(0xA1CE_0000)
    }

    fn next_on(&mut self, accept: impl Fn(u16) -> bool) -> Uuid {
        loop {
            self.0 += 1;
            let person = Uuid::from_u128(self.0);
            if accept(part(person)) {
                return person;
            }
        }
    }

    fn next(&mut self) -> Uuid {
        self.next_on(|_| true)
    }

    /// A `(P_old, P_new)` pair hashing to different partitions — the cross-partition slow path.
    fn cross_partition_pair(&mut self) -> (Uuid, Uuid) {
        let old = self.next();
        let new = self.next_on(|p| p != part(old));
        (old, new)
    }
}

fn envelope(person: Uuid, ts: &str, source_offset: i64) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "team_id": TEAM,
        "person_id": person.to_string(),
        "distinct_id": "d",
        "uuid": Uuid::from_u128(0xE0_0000 + source_offset as u128).to_string(),
        "event": "$pageview",
        "timestamp": ts,
        "properties": "{}",
        "person_properties": null,
        "elements_chain": null,
        "source_offset": source_offset,
        "source_partition": 0,
    }))
    .expect("serialize envelope")
}

async fn produce_event(
    producer: &FutureProducer,
    topic: &str,
    person: Uuid,
    ts: &str,
    source_offset: i64,
) {
    let key = merge_partition_key(TeamId(TEAM), &person);
    let payload = envelope(person, ts, source_offset);
    let (partition, _offset) = producer
        .send(
            FutureRecord::to(topic).key(&key).payload(&payload),
            Timeout::After(Duration::from_secs(10)),
        )
        .await
        .expect("produce event");
    assert_eq!(
        partition as u32,
        partition_of(TeamId(TEAM), &person, COHORT_PARTITION_COUNT),
        "seed event must co-partition with the merge protocol's arithmetic",
    );
}

fn merge_event(old: Uuid, new: Uuid) -> PersonMergeEvent {
    PersonMergeEvent {
        team_id: TEAM,
        old_person_uuid: old,
        new_person_uuid: new,
        merged_at_ms: MERGED_AT,
        schema_version: MERGE_EVENT_SCHEMA_VERSION,
    }
}

async fn produce_merge(producer: &FutureProducer, topic: &str, event: &PersonMergeEvent) {
    let key = merge_partition_key(TeamId(event.team_id), &event.old_person_uuid);
    let payload = event.encode();
    let (partition, _offset) = producer
        .send(
            FutureRecord::to(topic).key(&key).payload(&payload),
            Timeout::After(Duration::from_secs(10)),
        )
        .await
        .expect("produce merge event");
    assert_eq!(
        partition as u32,
        partition_of(
            TeamId(event.team_id),
            &event.old_person_uuid,
            COHORT_PARTITION_COUNT
        ),
        "merge trigger must land on P_old's partition",
    );
}

fn open_store(dir: &TempDir) -> CohortStore {
    CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store")
}

fn stage1_state(
    store: &CohortStore,
    partition_id: u16,
    lsk: LeafStateKey,
    person: Uuid,
) -> Option<Stage1State> {
    let key = Stage1Key {
        partition_id,
        team_id: TEAM as u64,
        leaf_state_key: lsk,
        person_id: person,
    };
    store
        .get_stage1(&key)
        .unwrap()
        .map(|bytes| StatefulRecord::decode(&bytes).unwrap().state)
}

/// The daily leaf's bucket sum for `person` on its own partition's slice, or `None` if absent.
fn daily_total(store: &CohortStore, lsk: LeafStateKey, person: Uuid) -> Option<u64> {
    match stage1_state(store, part(person), lsk, person)? {
        Stage1State::BehavioralDailyBuckets { buckets, .. } => {
            Some(buckets.iter().map(|&count| count as u64).sum())
        }
        other => panic!("expected daily buckets for {person}, got {other:?}"),
    }
}

fn single_matches(store: &CohortStore, lsk: LeafStateKey, person: Uuid) -> Option<bool> {
    match stage1_state(store, part(person), lsk, person)? {
        Stage1State::BehavioralSingle { has_match, .. } => Some(has_match),
        other => panic!("expected single state for {person}, got {other:?}"),
    }
}

fn tombstone_for(store: &CohortStore, person: Uuid) -> Option<Tombstone> {
    store
        .get_tombstone(&TombstoneKey {
            partition_id: part(person),
            team_id: TEAM as u64,
            person,
        })
        .unwrap()
        .map(|bytes| Tombstone::decode(&bytes).unwrap())
}

struct Topics {
    events: String,
    merges: String,
    transfers: String,
}

impl Topics {
    fn unique(suffix: &Uuid) -> Self {
        Self {
            events: format!("cohort_stream_events_merge_{suffix}"),
            merges: format!("person_merge_events_{suffix}"),
            transfers: format!("cohort_merge_state_transfer_{suffix}"),
        }
    }

    async fn create(&self) {
        create_topic(&self.events, NUM_PARTITIONS).await;
        create_topic(&self.merges, NUM_PARTITIONS).await;
        create_topic(&self.transfers, NUM_PARTITIONS).await;
    }

    fn names(&self) -> [&str; 3] {
        [&self.events, &self.merges, &self.transfers]
    }
}

struct Groups {
    events: String,
    merges: String,
    transfers: String,
}

impl Groups {
    fn unique(suffix: &Uuid) -> Self {
        Self {
            events: format!("cohort-stream-processor-{suffix}"),
            merges: format!("cohort-stream-merges-{suffix}"),
            transfers: format!("cohort-stream-merge-apply-{suffix}"),
        }
    }
}

fn register_instance(manager: &mut Manager, name: &str) -> [Handle; 3] {
    let options = || ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15));
    [
        manager.register(&format!("consumer-{name}"), options()),
        manager.register(&format!("merge-follower-{name}"), options()),
        manager.register(&format!("transfer-follower-{name}"), options()),
    ]
}

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

struct Instance {
    store: CohortStore,
    dispatcher: Arc<EventDispatcher>,
    tasks: Vec<JoinHandle<()>>,
}

impl Instance {
    fn owned(&self) -> HashSet<i32> {
        self.dispatcher.owned_partitions().into_iter().collect()
    }

    async fn join(self) {
        for task in self.tasks {
            task.await.expect("instance task panicked");
        }
    }
}

async fn spawn_instance(
    topics: &Topics,
    groups: &Groups,
    store: CohortStore,
    catalog: CatalogHandle,
    membership_sink: Arc<dyn MembershipSink>,
    handles: [Handle; 3],
) -> Instance {
    let [events_handle, merge_handle, transfer_handle] = handles;
    let kafka_config = producer_kafka_config();

    let transfer_sink: Arc<dyn TransferSink> = Arc::new(
        KafkaTransferSink::new(&kafka_config, topics.transfers.clone())
            .await
            .expect("create transfer sink"),
    );
    let stream_event_sink: Arc<dyn StreamEventSink> = Arc::new(
        KafkaStreamEventSink::new(&kafka_config, topics.events.clone())
            .await
            .expect("create re-key sink"),
    );
    let merge_deps = Arc::new(MergeWorkerDeps {
        transfer_sink,
        stream_event_sink,
        merge_tracker: Arc::new(OffsetTracker::new()),
        transfer_tracker: Arc::new(OffsetTracker::new()),
        retry: TransferRetryPolicy::default(),
        gc_scan_limit: DEFAULT_MERGE_GC_SCAN_LIMIT,
        stage2_orphan_gc_enabled: true,
        cascade_sink: Arc::new(CaptureCascadeSink::new()),
        cascade_tracker: Arc::new(OffsetTracker::new()),
        cascade: CascadeConfig::default(),
        partition_count: COHORT_PARTITION_COUNT,
    });

    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        test_handle(&store),
        Arc::new(catalog),
        membership_sink,
        merge_deps,
    ));

    let merges_consumer: Arc<StreamConsumer> = Arc::new(
        follower_client_config(&groups.merges)
            .create()
            .expect("create merges follower consumer"),
    );
    let transfers_consumer: Arc<StreamConsumer> = Arc::new(
        follower_client_config(&groups.transfers)
            .create()
            .expect("create transfers follower consumer"),
    );
    let followers = Arc::new(FollowerSet::new([
        Follower::new(merges_consumer.clone(), topics.merges.clone()),
        Follower::new(transfers_consumer.clone(), topics.transfers.clone()),
    ]));

    let (context, rebalance_rx) = CohortConsumerContext::new(dispatcher.clone());
    let events_client: StreamConsumer<CohortConsumerContext> = events_client_config(&groups.events)
        .create_with_context(context)
        .expect("create events consumer");
    events_client
        .subscribe(&[topics.events.as_str()])
        .expect("subscribe events");

    let (command_tx, command_rx) = mpsc::unbounded_channel();
    let mut tasks = vec![tokio::spawn(run_rebalance_worker(
        rebalance_rx,
        dispatcher.clone(),
        followers,
        command_tx,
        events_handle.shutdown_token(),
    ))];

    let merge_follower = FollowerConsumer::<MergeRoute>::new(
        merges_consumer,
        topics.merges.clone(),
        dispatcher.clone(),
        merge_handle,
        100,
        RECV_TIMEOUT,
        COMMIT_INTERVAL,
    );
    tasks.push(tokio::spawn(merge_follower.process()));

    let transfer_follower = FollowerConsumer::<TransferRoute>::new(
        transfers_consumer,
        topics.transfers.clone(),
        dispatcher.clone(),
        transfer_handle,
        100,
        RECV_TIMEOUT,
        COMMIT_INTERVAL,
    );
    tasks.push(tokio::spawn(transfer_follower.process()));

    let events_consumer = CohortStreamEventsConsumer::new(
        events_client,
        topics.events.clone(),
        dispatcher.clone(),
        events_handle,
        100,
        RECV_TIMEOUT,
        COMMIT_INTERVAL,
        NUM_PARTITIONS as usize,
        command_rx,
        None,
    );
    tasks.push(tokio::spawn(events_consumer.process()));

    Instance {
        store,
        dispatcher,
        tasks,
    }
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn keyed_produces_agree_with_partition_of_live() {
    let suffix = Uuid::new_v4();
    let raw_topic = format!("merge_partitioner_raw_{suffix}");
    let transfer_topic = format!("merge_partitioner_transfer_{suffix}");
    let events_topic = format!("merge_partitioner_events_{suffix}");
    with_topics_cleanup(&[&raw_topic, &transfer_topic, &events_topic], async {
        create_topic(&raw_topic, NUM_PARTITIONS).await;
        create_topic(&transfer_topic, NUM_PARTITIONS).await;
        create_topic(&events_topic, NUM_PARTITIONS).await;

        let producer = murmur2_producer();
        let mut spread = HashSet::new();
        for team in [2i32, 7, 42, 99] {
            for n in 1..=50u128 {
                let person = Uuid::from_u128(((team as u128) << 64) | n);
                let key = merge_partition_key(TeamId(team), &person);
                let payload = PersonMergeEvent {
                    team_id: team,
                    old_person_uuid: person,
                    new_person_uuid: Uuid::from_u128(0xBEEF),
                    merged_at_ms: MERGED_AT,
                    schema_version: MERGE_EVENT_SCHEMA_VERSION,
                }
                .encode();
                let (partition, _offset) = producer
                    .send(
                        FutureRecord::to(&raw_topic).key(&key).payload(&payload),
                        Timeout::After(Duration::from_secs(10)),
                    )
                    .await
                    .expect("produce keyed message");
                assert_eq!(
                    partition as u32,
                    partition_of(TeamId(team), &person, COHORT_PARTITION_COUNT),
                    "murmur2_random delivery for ({team}, {person}) disagrees with partition_of",
                );
                spread.insert(partition);
            }
        }
        assert!(
            spread.len() >= 32,
            "200 pairs should cover many partitions, got {}",
            spread.len(),
        );

        // Transfer sink: keyed by P_new; verify each message lands on partition_of(P_new).
        let transfer_sink =
            KafkaTransferSink::new(&producer_kafka_config(), transfer_topic.clone())
                .await
                .expect("create transfer sink");
        let transfers: Vec<MergeStateTransfer> = (1..=96u128)
            .map(|n| MergeStateTransfer {
                team_id: TEAM,
                old_person_uuid: Uuid::from_u128(0xDEAD_0000 + n),
                new_person_uuid: Uuid::from_u128(0xBEEF_0000 + n),
                merged_at_ms: MERGED_AT,
                source_partition: 0,
                source_offset: n as i64,
                leaves: vec![],
                forward_hops: 0,
            })
            .collect();
        let acks = transfer_sink.produce(transfers).await;
        assert!(acks.iter().all(Result::is_ok), "all transfer produces ack");

        let messages = consume_all(&transfer_topic, 96, Duration::from_secs(30)).await;
        assert_eq!(messages.len(), 96, "all produced transfers are readable");
        for (partition, payload) in &messages {
            let transfer = MergeStateTransfer::decode(payload).unwrap();
            assert_eq!(
                *partition as u32,
                partition_of(
                    TeamId(transfer.team_id),
                    &transfer.new_person_uuid,
                    COHORT_PARTITION_COUNT
                ),
                "transfer for P_new {} landed off its partition",
                transfer.new_person_uuid,
            );
        }

        // Re-key sink: keyed by the rewritten target person.
        let event_sink = KafkaStreamEventSink::new(&producer_kafka_config(), events_topic.clone())
            .await
            .expect("create re-key sink");
        let events: Vec<CohortStreamEvent> = (1..=64u128)
            .map(|n| CohortStreamEvent {
                team_id: TEAM,
                person_id: Uuid::from_u128(0xCAFE_0000 + n).to_string(),
                distinct_id: "d".to_string(),
                uuid: Uuid::from_u128(0xE1_0000 + n).to_string(),
                event: "$pageview".to_string(),
                timestamp: TS.to_string(),
                properties: Some("{}".to_string()),
                person_properties: None,
                elements_chain: None,
                source_offset: n as i64,
                source_partition: 0,
                redirected_from: Some(Uuid::from_u128(1).to_string()),
                redirect_hops: 1,
            })
            .collect();
        let acks = event_sink.produce(events).await;
        assert!(acks.iter().all(Result::is_ok), "all re-key produces ack");

        let messages = consume_all(&events_topic, 64, Duration::from_secs(30)).await;
        assert_eq!(messages.len(), 64, "all produced re-keys are readable");
        for (partition, payload) in &messages {
            let event: CohortStreamEvent = serde_json::from_slice(payload).unwrap();
            let person = Uuid::parse_str(&event.person_id).unwrap();
            assert_eq!(
                *partition as u32,
                partition_of(TeamId(event.team_id), &person, COHORT_PARTITION_COUNT),
                "re-keyed event for {person} landed off its partition",
            );
        }
    })
    .await;
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn cross_partition_merge_completes_end_to_end_on_the_wire() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let shadow_topic = format!("cohort_membership_changed_merge_{suffix}");
    let groups = Groups::unique(&suffix);
    let [events, merges, transfers] = topics.names();
    with_topics_cleanup(&[events, merges, transfers, &shadow_topic], async {
        topics.create().await;
        create_topic(&shadow_topic, NUM_PARTITIONS).await;

        let catalog = merge_catalog();
        let (single_lsk, daily_lsk) = behavioral_lsks(&catalog);

        let mut manager = Manager::builder("merge-e2e-itest")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager, "a");
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let dir = TempDir::new().unwrap();
        let membership: Arc<dyn MembershipSink> = Arc::new(
            KafkaMembershipSink::new(&producer_kafka_config(), shadow_topic.clone())
                .await
                .expect("create shadow sink"),
        );
        let instance = spawn_instance(
            &topics,
            &groups,
            open_store(&dir),
            catalog,
            membership,
            handles,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        let mut alloc = PersonAlloc::new();
        let (p_old, p_new) = alloc.cross_partition_pair();

        let producer = murmur2_producer();
        produce_event(&producer, &topics.events, p_old, TS, 0).await;
        produce_event(&producer, &topics.events, p_old, TS, 1).await;
        wait_for("P_old's seeded state", Duration::from_secs(60), || {
            daily_total(&instance.store, daily_lsk, p_old) == Some(2)
        })
        .await;

        produce_merge(&producer, &topics.merges, &merge_event(p_old, p_new)).await;

        let merge_verifier = group_verifier(&groups.merges);
        let transfer_verifier = group_verifier(&groups.transfers);
        wait_for(
            "the merge group's offset to commit",
            Duration::from_secs(60),
            || committed_sum(&merge_verifier, &topics.merges) == 1,
        )
        .await;
        wait_for(
            "the transfer group's offset to commit",
            Duration::from_secs(60),
            || committed_sum(&transfer_verifier, &topics.transfers) == 1,
        )
        .await;

        assert_eq!(
            topic_message_count(&topics.transfers),
            1,
            "exactly one transfer message on the wire",
        );
        let transfer_messages = consume_all(&topics.transfers, 1, Duration::from_secs(30)).await;
        assert_eq!(transfer_messages.len(), 1, "the transfer is readable");
        let (transfer_partition, payload) = &transfer_messages[0];
        assert_eq!(
            *transfer_partition as u16,
            part(p_new),
            "transfer must land on P_new's partition",
        );
        let transfer = MergeStateTransfer::decode(payload).unwrap();
        assert_eq!(transfer.old_person_uuid, p_old);
        assert_eq!(transfer.new_person_uuid, p_new);
        assert_eq!(transfer.source_partition, part(p_old) as i32);
        assert_eq!(
            transfer.leaves.len(),
            2,
            "single + daily leaves transfer whole"
        );

        assert_eq!(
            single_matches(&instance.store, single_lsk, p_new),
            Some(true)
        );
        assert_eq!(daily_total(&instance.store, daily_lsk, p_new), Some(2));
        assert_eq!(single_matches(&instance.store, single_lsk, p_old), None);
        assert_eq!(daily_total(&instance.store, daily_lsk, p_old), None);
        let tombstone =
            tombstone_for(&instance.store, p_old).expect("tombstone written on P_old's slice");
        assert_eq!(tombstone.new_person, p_new);

        // The drain emits no Left for P_old.
        assert_eq!(
            topic_message_count(&shadow_topic),
            4,
            "exactly four membership changes on the wire (no Left for P_old)",
        );
        let changes: Vec<CohortMembershipChange> =
            consume_all(&shadow_topic, 4, Duration::from_secs(30))
                .await
                .iter()
                .map(|(_, payload)| {
                    serde_json::from_slice(payload).expect("decode membership change")
                })
                .collect();
        let entered_new: HashSet<i32> = changes
            .iter()
            .filter(|change| {
                change.person_id == p_new.to_string() && change.status == MembershipStatus::Entered
            })
            .map(|change| change.cohort_id)
            .collect();
        assert_eq!(
            entered_new,
            HashSet::from([1, 2]),
            "the apply emitted P_new's entry into both cohorts",
        );
        assert!(
            !changes
                .iter()
                .any(|change| change.person_id == p_old.to_string()
                    && change.status == MembershipStatus::Left),
            "the drain emits no Left for P_old",
        );

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn duplicate_merge_message_produces_exactly_one_transfer() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        let catalog = merge_catalog();
        let (_, daily_lsk) = behavioral_lsks(&catalog);

        let mut manager = Manager::builder("merge-dup-itest")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager, "a");
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let dir = TempDir::new().unwrap();
        let instance = spawn_instance(
            &topics,
            &groups,
            open_store(&dir),
            catalog,
            Arc::new(CaptureSink::new()),
            handles,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        let mut alloc = PersonAlloc::new();
        let (p_old, p_new) = alloc.cross_partition_pair();

        let producer = murmur2_producer();
        produce_event(&producer, &topics.events, p_old, TS, 0).await;
        produce_event(&producer, &topics.events, p_old, TS, 1).await;
        wait_for("P_old's seeded state", Duration::from_secs(60), || {
            daily_total(&instance.store, daily_lsk, p_old) == Some(2)
        })
        .await;

        let event = merge_event(p_old, p_new);
        produce_merge(&producer, &topics.merges, &event).await;
        produce_merge(&producer, &topics.merges, &event).await;

        let merge_verifier = group_verifier(&groups.merges);
        wait_for(
            "both merge copies to settle and commit",
            Duration::from_secs(60),
            || committed_sum(&merge_verifier, &topics.merges) == 2,
        )
        .await;

        assert_eq!(
            topic_message_count(&topics.transfers),
            1,
            "the replayed drain must not produce a second transfer",
        );

        let transfer_verifier = group_verifier(&groups.transfers);
        wait_for(
            "the transfer group's offset to commit",
            Duration::from_secs(60),
            || committed_sum(&transfer_verifier, &topics.transfers) == 1,
        )
        .await;
        assert_eq!(
            daily_total(&instance.store, daily_lsk, p_new),
            Some(2),
            "P_new's buckets applied exactly once, never summed twice",
        );

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn post_merge_straggler_re_keys_to_p_new_and_folds() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        let catalog = merge_catalog();
        let (single_lsk, daily_lsk) = behavioral_lsks(&catalog);

        let mut manager = Manager::builder("merge-straggler-itest")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager, "a");
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let dir = TempDir::new().unwrap();
        let instance = spawn_instance(
            &topics,
            &groups,
            open_store(&dir),
            catalog,
            Arc::new(CaptureSink::new()),
            handles,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        let mut alloc = PersonAlloc::new();
        let (p_old, p_new) = alloc.cross_partition_pair();

        let producer = murmur2_producer();
        produce_event(&producer, &topics.events, p_old, TS, 0).await;
        produce_event(&producer, &topics.events, p_old, TS, 1).await;
        wait_for("P_old's seeded state", Duration::from_secs(60), || {
            daily_total(&instance.store, daily_lsk, p_old) == Some(2)
        })
        .await;
        produce_merge(&producer, &topics.merges, &merge_event(p_old, p_new)).await;
        let merge_verifier = group_verifier(&groups.merges);
        wait_for("the merge to complete", Duration::from_secs(60), || {
            committed_sum(&merge_verifier, &topics.merges) == 1
                && daily_total(&instance.store, daily_lsk, p_new) == Some(2)
        })
        .await;

        produce_event(&producer, &topics.events, p_old, TS_LATER, 100).await;
        wait_for(
            "the straggler to fold into P_new",
            Duration::from_secs(60),
            || daily_total(&instance.store, daily_lsk, p_new) == Some(3),
        )
        .await;

        assert_eq!(
            topic_message_count(&topics.events),
            4,
            "seeds + straggler + exactly one re-key on the wire",
        );
        let messages = consume_all(&topics.events, 4, Duration::from_secs(30)).await;
        assert_eq!(messages.len(), 4, "all four events are readable");
        let re_keyed: Vec<(i32, CohortStreamEvent)> = messages
            .iter()
            .filter_map(|(partition, payload)| {
                let event: CohortStreamEvent = serde_json::from_slice(payload).ok()?;
                event
                    .redirected_from
                    .is_some()
                    .then_some((*partition, event))
            })
            .collect();
        assert_eq!(re_keyed.len(), 1, "exactly one re-keyed straggler");
        let (partition, event) = &re_keyed[0];
        assert_eq!(
            *partition as u16,
            part(p_new),
            "the re-key landed on P_new's partition",
        );
        assert_eq!(
            event.person_id,
            p_new.to_string(),
            "person rewritten to the target"
        );
        assert_eq!(
            event.redirected_from.as_deref(),
            Some(p_old.to_string().as_str()),
            "first-origin marker stamped",
        );
        assert_eq!(event.redirect_hops, 1, "one cross-partition hop counted");
        assert_eq!(
            (event.source_partition, event.source_offset),
            (0, 100),
            "original source coordinates preserved for redirect_dedup",
        );

        assert_eq!(single_matches(&instance.store, single_lsk, p_old), None);
        assert_eq!(daily_total(&instance.store, daily_lsk, p_old), None);

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}

/// `incremental_unassign` + `incremental_assign(Offset::Stored)` rewinds to the committed offset,
/// not the in-session fetch position.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn follower_re_establishes_consumption_from_the_committed_offset() {
    let suffix = Uuid::new_v4();
    let topic = format!("merge_follower_stored_{suffix}");
    with_topics_cleanup(&[&topic], async {
        create_topic(&topic, NUM_PARTITIONS).await;

        // Pin to partition 0 explicitly; partitioning itself is not the thing under test.
        let producer: FutureProducer = ClientConfig::new()
            .set("bootstrap.servers", bootstrap_servers())
            .set("message.timeout.ms", "10000")
            .create()
            .expect("create producer");
        for n in 1..=5u128 {
            let payload = merge_event(Uuid::from_u128(n), Uuid::from_u128(0xBEEF)).encode();
            producer
                .send(
                    FutureRecord::to(&topic)
                        .partition(0)
                        .key("k")
                        .payload(&payload),
                    Timeout::After(Duration::from_secs(10)),
                )
                .await
                .expect("produce merge payload");
        }

        let group = format!("cohort-stream-merges-stored-{suffix}");
        let consumer: StreamConsumer = follower_client_config(&group)
            .create()
            .expect("create follower consumer");

        let stored = |topic: &str| {
            let mut tpl = TopicPartitionList::new();
            tpl.add_partition_offset(topic, 0, Offset::Stored)
                .expect("stored TPL");
            tpl
        };

        // First acquire: no committed offset yet → Stored falls back to earliest.
        consumer
            .incremental_assign(&stored(&topic))
            .expect("incremental_assign");
        let mut offsets = Vec::new();
        for _ in 0..5 {
            let message = tokio::time::timeout(Duration::from_secs(15), consumer.recv())
                .await
                .expect("recv deadline")
                .expect("recv");
            offsets.push(message.offset());
        }
        assert_eq!(
            offsets,
            vec![0, 1, 2, 3, 4],
            "earliest fallback replays from 0"
        );

        // Commit offset 3 (processed through 2). Fetch position is already at 5.
        let mut commit_tpl = TopicPartitionList::new();
        commit_tpl
            .add_partition_offset(&topic, 0, Offset::Offset(3))
            .expect("commit TPL");
        consumer
            .commit(&commit_tpl, CommitMode::Sync)
            .expect("commit");

        // Revoke → re-acquire (mirrors the assignment-mirror protocol): unassign then re-assign at Stored.
        let mut bare = TopicPartitionList::new();
        bare.add_partition(&topic, 0);
        consumer
            .incremental_unassign(&bare)
            .expect("incremental_unassign");
        consumer
            .incremental_assign(&stored(&topic))
            .expect("re-assign at Offset::Stored");

        let next = tokio::time::timeout(Duration::from_secs(15), consumer.recv())
            .await
            .expect("recv deadline after re-assign")
            .expect("recv after re-assign");
        assert_eq!(
            next.offset(),
            3,
            "Offset::Stored must rewind to the committed offset, not keep the in-session position",
        );
        let after = tokio::time::timeout(Duration::from_secs(15), consumer.recv())
            .await
            .expect("recv deadline")
            .expect("recv");
        assert_eq!(after.offset(), 4, "and redeliver the rest of the window");
    })
    .await;
}

#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn cooperative_migration_mid_merge_stream_loses_no_merge() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        let catalog_a = merge_catalog();
        let catalog_b = merge_catalog();
        let (_, daily_lsk) = behavioral_lsks(&catalog_a);

        let mut manager = Manager::builder("merge-migrate-itest")
            .with_trap_signals(false)
            .build();
        let handles_a = register_instance(&mut manager, "a");
        let handles_b = register_instance(&mut manager, "b");
        let shutdown = handles_a[0].clone();
        let _monitor = manager.monitor_background();

        let dir_a = TempDir::new().unwrap();
        let dir_b = TempDir::new().unwrap();
        let sink_a = Arc::new(CaptureSink::new());
        let sink_b = Arc::new(CaptureSink::new());

        let a = spawn_instance(
            &topics,
            &groups,
            open_store(&dir_a),
            catalog_a,
            sink_a.clone(),
            handles_a,
        )
        .await;
        wait_for(
            "instance A to own every partition",
            Duration::from_secs(30),
            || a.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        let producer = murmur2_producer();
        let mut alloc = PersonAlloc::new();
        let mut source_offset = 0i64;
        let mut seed = |producer: &FutureProducer, topic: &str, person: Uuid| {
            let offsets = (source_offset, source_offset + 1);
            source_offset += 2;
            let topic = topic.to_string();
            let producer = producer.clone();
            async move {
                produce_event(&producer, &topic, person, TS, offsets.0).await;
                produce_event(&producer, &topic, person, TS, offsets.1).await;
            }
        };

        // Batch 1: seed and trigger against A alone, B joins while merges are in flight.
        let batch1: Vec<(Uuid, Uuid)> = (0..4).map(|_| alloc.cross_partition_pair()).collect();
        for (p_old, _) in &batch1 {
            seed(&producer, &topics.events, *p_old).await;
        }
        wait_for("batch 1 seed state", Duration::from_secs(60), || {
            batch1
                .iter()
                .all(|(p_old, _)| daily_total(&a.store, daily_lsk, *p_old) == Some(2))
        })
        .await;
        for (p_old, p_new) in &batch1 {
            produce_merge(&producer, &topics.merges, &merge_event(*p_old, *p_new)).await;
        }

        let b = spawn_instance(
            &topics,
            &groups,
            open_store(&dir_b),
            catalog_b,
            sink_b.clone(),
            handles_b,
        )
        .await;

        // Wait for a stable, disjoint full split.
        let (a_owned, b_owned) = {
            let deadline = Duration::from_secs(60);
            let start = Instant::now();
            loop {
                let a1 = a.owned();
                let b1 = b.owned();
                if !b1.is_empty()
                    && a1.is_disjoint(&b1)
                    && a1.len() + b1.len() == NUM_PARTITIONS as usize
                {
                    tokio::time::sleep(Duration::from_millis(750)).await;
                    if a.owned() == a1 && b.owned() == b1 {
                        break (a1, b1);
                    }
                }
                assert!(
                    start.elapsed() < deadline,
                    "timed out waiting for the cooperative split to settle (a={}, b={})",
                    a.owned().len(),
                    b.owned().len(),
                );
                tokio::time::sleep(Duration::from_millis(250)).await;
            }
        };

        // Batch 2: directed pairs (A→B, B→A) plus generic pairs to cover both transfer directions.
        let pair_ab = (
            alloc.next_on(|p| a_owned.contains(&(p as i32))),
            alloc.next_on(|p| b_owned.contains(&(p as i32))),
        );
        let pair_ba = (
            alloc.next_on(|p| b_owned.contains(&(p as i32))),
            alloc.next_on(|p| a_owned.contains(&(p as i32))),
        );
        let mut batch2 = vec![pair_ab, pair_ba];
        batch2.extend((0..4).map(|_| alloc.cross_partition_pair()));

        let in_either = |stores: [&CohortStore; 2], person: Uuid| {
            stores
                .iter()
                .filter_map(|store| daily_total(store, daily_lsk, person))
                .next()
        };

        for (p_old, _) in &batch2 {
            seed(&producer, &topics.events, *p_old).await;
        }
        wait_for("batch 2 seed state", Duration::from_secs(60), || {
            batch2
                .iter()
                .all(|(p_old, _)| in_either([&a.store, &b.store], *p_old) == Some(2))
        })
        .await;
        for (p_old, p_new) in &batch2 {
            produce_merge(&producer, &topics.merges, &merge_event(*p_old, *p_new)).await;
        }

        wait_for(
            "every batch 2 merge to complete",
            Duration::from_secs(90),
            || {
                batch2
                    .iter()
                    .all(|(_, p_new)| in_either([&a.store, &b.store], *p_new) == Some(2))
            },
        )
        .await;

        let total_merges = (batch1.len() + batch2.len()) as i64;
        let merge_verifier = group_verifier(&groups.merges);
        let transfer_verifier = group_verifier(&groups.transfers);
        wait_for(
            "merge commits to cover every merge",
            Duration::from_secs(90),
            || committed_sum(&merge_verifier, &topics.merges) == total_merges,
        )
        .await;
        // Batch 1 may produce empty re-drains after migration; batch 2 transfers are deterministic.
        let total_transfers = topic_message_count(&topics.transfers);
        let transfer_pairs: HashSet<(Uuid, Uuid)> = consume_all(
            &topics.transfers,
            total_transfers as usize,
            Duration::from_secs(30),
        )
        .await
        .iter()
        .map(|(_, payload)| {
            let transfer = MergeStateTransfer::decode(payload).expect("decode transfer");
            (transfer.old_person_uuid, transfer.new_person_uuid)
        })
        .collect();
        for (p_old, p_new) in &batch2 {
            assert!(
                transfer_pairs.contains(&(*p_old, *p_new)),
                "no transfer rode the wire for batch-2 merge {p_old} → {p_new}",
            );
        }
        wait_for(
            "transfer commits to cover every transfer",
            Duration::from_secs(90),
            || committed_sum(&transfer_verifier, &topics.transfers) == total_transfers,
        )
        .await;

        for (p_old, p_new) in &batch2 {
            let totals = [
                daily_total(&a.store, daily_lsk, *p_new),
                daily_total(&b.store, daily_lsk, *p_new),
            ];
            assert!(
                totals.contains(&Some(2)) && totals.contains(&None),
                "P_new {p_new} must hold the merged count in exactly one store, got {totals:?}",
            );
            assert_eq!(
                daily_total(&a.store, daily_lsk, *p_old),
                None,
                "P_old {p_old} drained in A"
            );
            assert_eq!(
                daily_total(&b.store, daily_lsk, *p_old),
                None,
                "P_old {p_old} drained in B"
            );

            let owner = if a_owned.contains(&(part(*p_old) as i32)) {
                &a.store
            } else {
                &b.store
            };
            let tombstone = tombstone_for(owner, *p_old)
                .unwrap_or_else(|| panic!("tombstone for {p_old} on its owner's slice"));
            assert_eq!(tombstone.new_person, *p_new);
        }

        assert_eq!(
            daily_total(&b.store, daily_lsk, pair_ab.1),
            Some(2),
            "the A-drained transfer applied on B",
        );
        assert_eq!(
            daily_total(&a.store, daily_lsk, pair_ba.1),
            Some(2),
            "the B-drained transfer applied on A",
        );

        // Batch 1 raced the migration; any surviving count must be exact (no double-apply).
        for (_, p_new) in &batch1 {
            for store in [&a.store, &b.store] {
                if let Some(total) = daily_total(store, daily_lsk, *p_new) {
                    assert_eq!(
                        total, 2,
                        "batch 1 P_new {p_new} was double-applied despite the dedup",
                    );
                }
            }
        }

        let entered: HashSet<String> = sink_a
            .changes()
            .into_iter()
            .chain(sink_b.changes())
            .filter(|change| change.status == MembershipStatus::Entered)
            .map(|change| change.person_id)
            .collect();
        for (_, p_new) in &batch2 {
            assert!(
                entered.contains(&p_new.to_string()),
                "P_new {p_new} entered on the shadow output",
            );
        }

        shutdown.request_shutdown();
        a.join().await;
        b.join().await;
    })
    .await;
}
