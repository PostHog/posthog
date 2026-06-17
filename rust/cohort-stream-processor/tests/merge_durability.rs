//! End-to-end durability test for the merge protocol's column families **and** the cascade
//! (`cf_stage2`) state across a whole-DB checkpoint → S3 disaster restore, against a **real**
//! Kafka/Redpanda broker + S3-compatible store (MinIO / SeaweedFS).
//!
//! This is the first test that drives durability + merge + cascade together. Slice 2 shipped the
//! whole-DB checkpoint + [`OffsetManifest`] follower-offset capture/restore machinery, but inert
//! (cascade off ⇒ no merge/cascade traffic ⇒ the follower manifest maps are always empty). With the
//! cascade gate **on** and a single-pod static-membership deploy, this test pushes all four merge CFs
//! (`cf_pending_transfers`, `cf_merge_drains_applied`, `cf_merge_applied`, `cf_merge_tombstones`) plus
//! `cf_stage2` (via a cascade-flipped pure cohort-ref) through a [`CheckpointSweeper`] upload, then
//! loses the PVC, restores from S3, and asserts:
//!   - the restored [`OffsetManifest`] carries **non-empty follower maps** (merge + transfer topics),
//!   - the restored RocksDB state is **count-exact** (daily buckets, single match, tombstone redirect),
//!   - a post-restore straggler redirects via the restored `cf_merge_tombstones` (no rebuild, no
//!     double-count),
//!   - a replayed merge message produces no second transfer (restored marker dedup),
//!   - the events committed-sum stays exact (no skip / no re-fold),
//!   - cascade-origin shadow changes are at-least-once (the produce-before-state window may re-emit one
//!     idempotent duplicate on replay), while direct merge changes are exact.
//!
//! The load-bearing difference from the events-only S3 e2e
//! (`events_consumer::s3_restore_reseeds_state_resumes_at_manifest_offset_and_fires_a_dormant_left`):
//! the [`CheckpointSweeper`] is seeded from the **live** [`OffsetTracker`]s the running dispatcher
//! mutates (mirroring `main.rs:204-208`), so the manifest captures the three follower topics' offsets
//! with content. A fresh re-seeded tracker can only carry the events topic.
//!
//! `#[ignore]`d by default: needs a running broker + an S3-compatible store. Run serially:
//!
//! ```sh
//! export KAFKA_HOSTS=localhost:9092
//! export CHECKPOINT_S3_ENDPOINT=http://localhost:19000   # MinIO; or :8333 for SeaweedFS
//! export CHECKPOINT_S3_BUCKET=cohort-checkpoints          # must already exist
//! export CHECKPOINT_S3_ACCESS_KEY_ID=...                  # MinIO/SeaweedFS creds
//! export CHECKPOINT_S3_SECRET_ACCESS_KEY=...
//! cargo test -p cohort-stream-processor --test merge_durability -- --ignored --test-threads=1
//! ```
//!
//! The test deletes its 5 topics + S3 prefix on the way out via `with_topics_cleanup`. The cleanup is
//! NOT panic-safe across a killed process (a documented Slice-2 residual, bounded by the per-run UUID
//! suffix on every topic + S3 prefix). If a run is killed, sweep leaked topics with:
//!
//! ```sh
//! docker exec posthog-kafka-1 sh -c 'rpk topic list | awk "{print \$1}" \
//!   | grep -E "_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$" \
//!   | xargs -r rpk topic delete'
//! ```

use std::collections::HashSet;
use std::future::Future;
use std::panic::AssertUnwindSafe;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono_tz::UTC;
use cohort_stream_processor::config::Config;
use cohort_stream_processor::consumers::{
    CascadeRoute, CohortStreamEventsConsumer, EventDispatcher, FollowerConsumer, MergeRoute,
    TransferRoute,
};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::merge::transfer::{
    PersonMergeEvent, Tombstone, MERGE_EVENT_SCHEMA_VERSION,
};
use cohort_stream_processor::partitions::{
    merge_partition_key, partition_of, run_rebalance_worker, CohortConsumerContext, Follower,
    FollowerSet, OffsetTracker, PartitionRouter, COHORT_PARTITION_COUNT,
};
use cohort_stream_processor::producer::{
    CohortMembershipChange, KafkaCascadeSink, KafkaMembershipSink, KafkaStreamEventSink,
    KafkaTransferSink, MembershipSink, MembershipStatus, StreamEventSink, TransferSink,
};
use cohort_stream_processor::stage1::{Stage1State, StatefulRecord};
use cohort_stream_processor::store::durability::{
    run_boot_restore, upload_cadence, CheckpointExporter, CheckpointSweeper, OffsetManifest,
    RestoreSource, S3Uploader,
};
use cohort_stream_processor::store::{
    CohortStore, LeafStateKey, Stage1Key, StoreConfig, TombstoneKey,
};
use cohort_stream_processor::sweep::Sweeper;
use cohort_stream_processor::workers::{
    CascadeConfig, MergeWorkerDeps, TransferRetryPolicy, DEFAULT_MERGE_GC_SCAN_LIMIT,
};
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
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

/// Cohort ids. 1 = single, 2 = daily (the cascade referent), 3 = pure cohort-ref to the daily (B).
const COHORT_SINGLE: i32 = 1;
const COHORT_DAILY: i32 = 2;
const COHORT_REF: i32 = 3;

fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

/// Two single-leaf cohorts sharing one `$pageview` matcher (single + daily, from `merge_consumer`),
/// plus cohort B: a **pure cohort-ref** to the daily cohort. Frozen with `freeze_with(UTC, true)` so B
/// is [`Stage2ComposableRef`] — it owns no state-keyed leaf, so only a cascade from its referent (the
/// daily cohort) can flip it, never its own event. This makes the test sensitive to all four merge CFs
/// AND `cf_stage2` surviving the restore.
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
    // B's only leaf: a pure cohort-ref to the daily cohort. Flipped solely by a cascade from cohort 2.
    let ref_leaf = json!({ "type": "cohort", "value": COHORT_DAILY, "negation": false });
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(COHORT_SINGLE),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [single] } }),
        )
        .expect("add single cohort");
    builder
        .add_cohort(
            CohortId(COHORT_DAILY),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [daily] } }),
        )
        .expect("add daily cohort");
    builder
        .add_cohort(
            CohortId(COHORT_REF),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [ref_leaf] } }),
        )
        .expect("add cohort-ref B");
    CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(TEAM),
        // `cascade_enabled = true` ⇒ B becomes `Stage2ComposableRef` (a cascade flips it).
        builder.freeze_with(UTC, true),
    )]))
}

fn behavioral_lsks(catalog: &CatalogHandle) -> (LeafStateKey, LeafStateKey) {
    let snapshot = catalog.load();
    let team = snapshot.team(TeamId(TEAM)).expect("team in catalog");
    let pick = |variant: cohort_stream_processor::stage1::StateVariant| {
        team.by_condition_to_lsk[&HASH]
            .iter()
            .copied()
            .find(|lsk| team.by_lsk[lsk].variant == variant)
            .unwrap_or_else(|| panic!("no LSK for {variant:?}"))
    };
    (
        pick(cohort_stream_processor::stage1::StateVariant::BehavioralSingle),
        pick(cohort_stream_processor::stage1::StateVariant::BehavioralDailyBuckets),
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

/// Run a test body, delete `topics` + sweep the S3 prefix whether it passed or panicked, then
/// re-propagate any panic. NOT panic-safe across a killed process (documented residual; the per-run
/// UUID suffix bounds the leak).
async fn with_topics_cleanup<F: Future<Output = ()>>(topics: &[&str], config: &Config, body: F) {
    let result = AssertUnwindSafe(body).catch_unwind().await;
    delete_topics(topics).await;
    delete_s3_prefix(config).await;
    if let Err(panic) = result {
        std::panic::resume_unwind(panic);
    }
}

/// The `murmur2_random` partitioner must match production for keyed co-partitioning.
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

/// Sum of committed offsets across all partitions; for a fresh topic this equals the messages
/// consumed (committed == next-offset-to-consume).
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

/// Total messages on `topic` across all partitions, from the broker's watermarks.
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

/// Read every message on `topic` (up to `expected`, all partitions from the beginning), returning
/// `(partition, payload)` pairs. Assigned explicitly — no group join, no commit.
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
            Err(_) => {} // poll tick elapsed with no message; re-check the deadline
        }
    }
    messages
}

/// Decode every `CohortMembershipChange` currently on the shadow topic.
async fn shadow_changes(topic: &str, expected: usize) -> Vec<CohortMembershipChange> {
    consume_all(topic, expected, Duration::from_secs(30))
        .await
        .iter()
        .map(|(_, payload)| serde_json::from_slice(payload).expect("decode membership change"))
        .collect()
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

/// Allocates distinct persons, filtered by the partition they hash to.
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

    /// A `(Q_old, Q_new)` pair hashing to the **same** partition — the fast path.
    fn same_partition_pair(&mut self) -> (Uuid, Uuid) {
        let old = self.next();
        let new = self.next_on(|p| p == part(old));
        (old, new)
    }
}

/// A serialized `CohortStreamEvent` envelope, byte-for-byte what the shuffler emits.
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

/// Produce one `$pageview` for `person`, asserting it lands on the expected partition.
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

/// Produce one merge trigger keyed by P_old, asserting it lands on P_old's partition.
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

fn open_restored_store(path: &Path) -> CohortStore {
    CohortStore::open(&StoreConfig {
        path: path.to_path_buf(),
        wipe_on_start: false,
        ..StoreConfig::default()
    })
    .expect("open restored store")
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
    cascade: String,
    shadow: String,
}

impl Topics {
    fn unique(suffix: &Uuid) -> Self {
        Self {
            events: format!("cohort_stream_events_durable_{suffix}"),
            merges: format!("person_merge_events_{suffix}"),
            transfers: format!("cohort_merge_state_transfer_{suffix}"),
            cascade: format!("cohort_cascade_events_{suffix}"),
            shadow: format!("cohort_membership_changed_{suffix}"),
        }
    }

    async fn create(&self) {
        for topic in self.names() {
            create_topic(topic, NUM_PARTITIONS).await;
        }
    }

    fn names(&self) -> [&str; 5] {
        [
            &self.events,
            &self.merges,
            &self.transfers,
            &self.cascade,
            &self.shadow,
        ]
    }
}

struct Groups {
    events: String,
    merges: String,
    transfers: String,
    cascade: String,
}

impl Groups {
    fn unique(suffix: &Uuid) -> Self {
        Self {
            events: format!("cohort-stream-processor-{suffix}"),
            merges: format!("cohort-stream-merges-{suffix}"),
            transfers: format!("cohort-stream-merge-apply-{suffix}"),
            cascade: format!("cohort-stream-cascade-{suffix}"),
        }
    }
}

fn register_instance(manager: &mut Manager, name: &str) -> [Handle; 4] {
    let options = || ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15));
    [
        manager.register(&format!("consumer-{name}"), options()),
        manager.register(&format!("merge-follower-{name}"), options()),
        manager.register(&format!("transfer-follower-{name}"), options()),
        manager.register(&format!("cascade-follower-{name}"), options()),
    ]
}

/// One full processor instance wired like `main.rs` with the cascade gate **on** plus the merge
/// followers, holding the four **live** offset trackers the running dispatcher mutates so the test can
/// seed the [`CheckpointSweeper`] from them (the D2 seam — see the module docs).
struct Instance {
    store: CohortStore,
    dispatcher: Arc<EventDispatcher>,
    tasks: Vec<JoinHandle<()>>,
    /// The live trackers, cloned **before** the originals moved into `MergeWorkerDeps` /
    /// `EventDispatcher` (mirrors `main.rs:204-208`). Passed to `CheckpointSweeper::new` so the
    /// manifest captures the follower topics' offsets with content — the load-bearing difference from
    /// the events-only S3 e2e, which re-seeds a fresh tracker and can only carry the events topic.
    events_tracker: Arc<OffsetTracker>,
    merge_tracker: Arc<OffsetTracker>,
    transfer_tracker: Arc<OffsetTracker>,
    cascade_tracker: Arc<OffsetTracker>,
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

/// One full processor instance: events consumer, three follower consumers (merge/transfer/cascade),
/// real Kafka sinks for transfer/re-key/cascade/membership. Cascade gate **on**. Threads an optional
/// restore `manifest` into the events consumer (restore-seek) and seeds the follower groups from it
/// (mirroring `main.rs`'s `commit_follower_offsets_from_manifest`). No sweep or redrive loop — the
/// test drives the checkpoint directly.
#[allow(clippy::too_many_arguments)]
async fn spawn_instance(
    topics: &Topics,
    groups: &Groups,
    store: CohortStore,
    catalog: CatalogHandle,
    handles: [Handle; 4],
    durable_restore: bool,
    manifest: Option<OffsetManifest>,
) -> Instance {
    let [events_handle, merge_handle, transfer_handle, cascade_handle] = handles;
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
    let cascade_sink = Arc::new(
        KafkaCascadeSink::new(&kafka_config, topics.cascade.clone())
            .await
            .expect("create cascade sink"),
    );
    let membership_sink: Arc<dyn MembershipSink> = Arc::new(
        KafkaMembershipSink::new(&kafka_config, topics.shadow.clone())
            .await
            .expect("create membership sink"),
    );

    // The four live trackers. Each is cloned before it moves into the deps/dispatcher so the sweeper
    // can read the *same* tracker the running consumers mutate — mirrors `main.rs:204-208`.
    let events_tracker = Arc::new(OffsetTracker::new());
    let merge_tracker = Arc::new(OffsetTracker::new());
    let transfer_tracker = Arc::new(OffsetTracker::new());
    let cascade_tracker = Arc::new(OffsetTracker::new());

    let events_tracker_for_instance = events_tracker.clone();
    let merge_tracker_for_instance = merge_tracker.clone();
    let transfer_tracker_for_instance = transfer_tracker.clone();
    let cascade_tracker_for_instance = cascade_tracker.clone();

    let merge_deps = Arc::new(MergeWorkerDeps {
        transfer_sink,
        stream_event_sink,
        merge_tracker,
        transfer_tracker,
        retry: TransferRetryPolicy::default(),
        gc_scan_limit: DEFAULT_MERGE_GC_SCAN_LIMIT,
        cascade_sink,
        cascade_tracker,
        cascade: CascadeConfig {
            enabled: true,
            depth_cap: 8,
            fanout_cap: 1000,
        },
    });

    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        events_tracker,
        store.clone(),
        Arc::new(catalog),
        membership_sink,
        merge_deps,
    ));
    if durable_restore {
        dispatcher.enable_durable_restore();
    }

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
    let cascade_consumer: Arc<StreamConsumer> = Arc::new(
        follower_client_config(&groups.cascade)
            .create()
            .expect("create cascade follower consumer"),
    );

    // Seed each follower group's committed offset from the restore manifest before the rebalance
    // worker mirrors the assignment, so the follower `incremental_assign` at `Offset::Stored` resolves
    // to the manifest position. Mirrors `main.rs`'s `commit_follower_offsets_from_manifest`.
    if let Some(manifest) = manifest.as_ref() {
        commit_follower_offsets_from_manifest(&merges_consumer, &topics.merges, manifest);
        commit_follower_offsets_from_manifest(&transfers_consumer, &topics.transfers, manifest);
        commit_follower_offsets_from_manifest(&cascade_consumer, &topics.cascade, manifest);
    }

    let followers = Arc::new(FollowerSet::new([
        Follower::new(merges_consumer.clone(), topics.merges.clone()),
        Follower::new(transfers_consumer.clone(), topics.transfers.clone()),
        Follower::new(cascade_consumer.clone(), topics.cascade.clone()),
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

    let cascade_follower = FollowerConsumer::<CascadeRoute>::new(
        cascade_consumer,
        topics.cascade.clone(),
        dispatcher.clone(),
        cascade_handle,
        100,
        RECV_TIMEOUT,
        COMMIT_INTERVAL,
    );
    tasks.push(tokio::spawn(cascade_follower.process()));

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
        manifest,
    );
    tasks.push(tokio::spawn(events_consumer.process()));

    Instance {
        store,
        dispatcher,
        tasks,
        events_tracker: events_tracker_for_instance,
        merge_tracker: merge_tracker_for_instance,
        transfer_tracker: transfer_tracker_for_instance,
        cascade_tracker: cascade_tracker_for_instance,
    }
}

/// Seed a follower consumer group's committed offsets from the restore manifest, so its subsequent
/// `incremental_assign` at [`Offset::Stored`] resolves to the restored position. A strict no-op when
/// the manifest carries no entries for `topic`. Copy-adapted from `main.rs`'s
/// `commit_follower_offsets_from_manifest` (the production path the restore tenure exercises).
fn commit_follower_offsets_from_manifest(
    consumer: &StreamConsumer,
    topic: &str,
    manifest: &OffsetManifest,
) {
    let Some(partitions) = manifest.topics.get(topic) else {
        return;
    };
    if partitions.is_empty() {
        return;
    }
    let mut tpl = TopicPartitionList::new();
    for (&partition, &next_offset) in partitions {
        tpl.add_partition_offset(topic, partition, Offset::Offset(next_offset))
            .expect("add follower partition to manifest commit TPL");
    }
    if tpl.count() > 0 {
        consumer
            .commit(&tpl, CommitMode::Sync)
            .expect("seed follower group offsets from restore manifest");
    }
}

/// A `Config` for the merge durability e2e: the events-only `s3_restore_config` knobs **plus** the
/// merge/cascade/single-pod knobs that satisfy `Config::validate_durability_startup`
/// (`durable_restore_enabled && cohort_cascade_enabled` is allowed only when
/// `durable_restore_single_pod && pod_identity().is_some()`). Threads every topic/group name through
/// so the single instance owns all 64 partitions of the per-run-unique topology.
#[allow(clippy::too_many_arguments)]
fn merge_durability_config(
    store_path: &Path,
    checkpoint_dir: &Path,
    prefix: &str,
    topics: &Topics,
    groups: &Groups,
) -> Config {
    let mut env: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    env.insert("CHECKPOINT_ENABLED".into(), "true".into());
    env.insert("DURABLE_RESTORE_ENABLED".into(), "true".into());
    // The merge/cascade/single-pod combo: required to run durable restore with cascade on.
    env.insert("COHORT_CASCADE_ENABLED".into(), "true".into());
    env.insert("DURABLE_RESTORE_SINGLE_POD".into(), "true".into());
    env.insert(
        "POD_NAME".into(),
        format!("merge-durability-{}", Uuid::new_v4()),
    );
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
    // Per-run-unique topology so the single instance owns all 64 partitions cleanly.
    env.insert("COHORT_STREAM_EVENTS_TOPIC".into(), topics.events.clone());
    env.insert("PERSON_MERGE_EVENTS_TOPIC".into(), topics.merges.clone());
    env.insert(
        "COHORT_MERGE_STATE_TRANSFER_TOPIC".into(),
        topics.transfers.clone(),
    );
    env.insert("COHORT_CASCADE_EVENTS_TOPIC".into(), topics.cascade.clone());
    env.insert(
        "COHORT_MEMBERSHIP_CHANGED_TOPIC".into(),
        topics.shadow.clone(),
    );
    env.insert("KAFKA_CONSUMER_GROUP".into(), groups.events.clone());
    env.insert("KAFKA_MERGE_CONSUMER_GROUP".into(), groups.merges.clone());
    env.insert(
        "KAFKA_MERGE_APPLY_CONSUMER_GROUP".into(),
        groups.transfers.clone(),
    );
    env.insert(
        "KAFKA_CASCADE_CONSUMER_GROUP".into(),
        groups.cascade.clone(),
    );
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
    let config = Config::init_from_hashmap(&env).expect("build merge-durability config");
    // Fail fast if the combo is mis-specified (the production gate runs this in `async_main`).
    config
        .validate_durability_startup()
        .expect("merge-durability config must satisfy the durability startup guard");
    config
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

/// Drive one checkpoint tick against the **live** trackers + the running dispatcher (owning all 64
/// partitions), uploading to S3. `upload_every_n = 1` ⇒ the first tick uploads. The live trackers are
/// the load-bearing difference: the dispatcher's `owned_partitions()` is 64 and each follower tracker
/// carries committed offsets, so the captured manifest's follower maps are non-empty.
async fn checkpoint_to_s3(
    instance: &Instance,
    config: &Config,
    topics: &Topics,
    checkpoint_dir: &Path,
) {
    let uploader = S3Uploader::new(config.durability_config())
        .await
        .expect("build S3 uploader (is the bucket reachable?)");
    let exporter = CheckpointExporter::new(Box::new(uploader));
    let sweeper = CheckpointSweeper::new(
        instance.store.clone(),
        instance.dispatcher.clone(),
        vec![
            (topics.events.clone(), instance.events_tracker.clone()),
            (topics.merges.clone(), instance.merge_tracker.clone()),
            (topics.transfers.clone(), instance.transfer_tracker.clone()),
            (topics.cascade.clone(), instance.cascade_tracker.clone()),
        ],
        exporter,
        config.durability_config(),
        checkpoint_dir.to_path_buf(),
        upload_cadence(
            config.checkpoint_interval_ms,
            config.checkpoint_s3_upload_interval_ms,
        ),
    );
    sweeper.run_once().await;
}

/// Complete one cross-partition merge end-to-end: seed two `$pageview`s on `p_old`, wait its daily
/// state, produce the merge, wait both follower groups commit + the state moves + the tombstone +
/// the cascade flip of B for `p_new`. Returns once everything is durable on `p_new`'s slice.
#[allow(clippy::too_many_arguments)]
async fn complete_cross_partition_merge(
    instance: &Instance,
    producer: &FutureProducer,
    topics: &Topics,
    groups: &Groups,
    single_lsk: LeafStateKey,
    daily_lsk: LeafStateKey,
    p_old: Uuid,
    p_new: Uuid,
    seed_base_offset: i64,
) {
    produce_event(producer, &topics.events, p_old, TS, seed_base_offset).await;
    produce_event(producer, &topics.events, p_old, TS, seed_base_offset + 1).await;
    wait_for(
        "P_old's seeded daily state",
        Duration::from_secs(60),
        || daily_total(&instance.store, daily_lsk, p_old) == Some(2),
    )
    .await;

    produce_merge(producer, &topics.merges, &merge_event(p_old, p_new)).await;

    let merge_verifier = group_verifier(&groups.merges);
    let transfer_verifier = group_verifier(&groups.transfers);
    wait_for(
        "the merge + transfer to complete on P_new (state moved, tombstone, both groups committed)",
        Duration::from_secs(90),
        || {
            daily_total(&instance.store, daily_lsk, p_new) == Some(2)
                && single_matches(&instance.store, single_lsk, p_new) == Some(true)
                && tombstone_for(&instance.store, p_old).map(|t| t.new_person) == Some(p_new)
                && committed_sum(&merge_verifier, &topics.merges) >= 1
                && committed_sum(&transfer_verifier, &topics.transfers) >= 1
        },
    )
    .await;
}

#[tokio::test(flavor = "multi_thread")]
#[ignore = "requires Kafka + MinIO; run with --ignored --test-threads=1"]
async fn merge_and_cascade_state_survive_an_s3_disaster_restore() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    let prefix = format!("cohort-stream-checkpoints-merge-itest/{suffix}");

    // Store and checkpoint dirs must be sibling subtrees, never nested (rocksdb hard-links SSTs into
    // the checkpoint).
    let root = tempfile::TempDir::new().unwrap();
    let store_path = root.path().join("db");
    let checkpoint_dir = root.path().join("checkpoints");
    let config = merge_durability_config(&store_path, &checkpoint_dir, &prefix, &topics, &groups);

    let names = topics.names();
    let config_for_cleanup = config.clone();
    with_topics_cleanup(&names, &config_for_cleanup, async {
        topics.create().await;

        let catalog = merge_catalog();
        let (single_lsk, daily_lsk) = behavioral_lsks(&catalog);

        // === Tenure 1: drive merges through all CFs + the cascade, then checkpoint to S3. ===
        let mut manager = Manager::builder("merge-durability-itest-1")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager, "a");
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let store1 = CohortStore::open(&config.store_config()).expect("open tenure-1 store");
        let instance = spawn_instance(
            &topics,
            &groups,
            store1,
            catalog,
            handles,
            config.durable_restore_enabled,
            None,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        let mut alloc = PersonAlloc::new();

        // (1) Cross-partition merge: drain → cf_merge_drains_applied + tombstone, transfer + apply →
        //     cf_merge_applied, and the apply's Stage 2 + cascade flips B (cf_stage2).
        let (p_old, p_new) = alloc.cross_partition_pair();
        complete_cross_partition_merge(
            &instance, &murmur2_producer(), &topics, &groups, single_lsk, daily_lsk, p_old, p_new, 0,
        )
        .await;
        // The cascade flip of B (cohort 3) for P_new must be visible on the shadow topic. Direct flips
        // are cohorts 1 + 2; the cascade re-evaluates B (a pure ref to cohort 2) into cohort 3 — three
        // shadow changes for the cross-partition merge. Wait on the cheap broker watermark count, then
        // scan once and assert B's flip is among them (never a full broker scan inside a poll loop).
        wait_for(
            "all three shadow changes for the cross-partition merge (single + daily + B cascade)",
            Duration::from_secs(60),
            || topic_message_count(&topics.shadow) >= 3,
        )
        .await;
        assert!(
            shadow_changes(&topics.shadow, 3).await.iter().any(|change| {
                change.cohort_id == COHORT_REF
                    && change.person_id == p_new.to_string()
                    && change.status == MembershipStatus::Entered
            }),
            "the cascade re-evaluated B (cohort 3, a pure ref to cohort 2) into P_new's membership",
        );

        // (2) Same-partition merge: the fast path (P_old and P_new on one worker, no Kafka transfer).
        let (q_old, q_new) = alloc.same_partition_pair();
        assert_eq!(
            part(q_old),
            part(q_new),
            "same-partition pair must share a worker (fast path)",
        );
        let producer = murmur2_producer();
        produce_event(&producer, &topics.events, q_old, TS, 10).await;
        produce_event(&producer, &topics.events, q_old, TS, 11).await;
        wait_for("Q_old's seeded daily state", Duration::from_secs(60), || {
            daily_total(&instance.store, daily_lsk, q_old) == Some(2)
        })
        .await;
        produce_merge(&producer, &topics.merges, &merge_event(q_old, q_new)).await;
        wait_for(
            "the same-partition merge to move state to Q_new + tombstone Q_old",
            Duration::from_secs(90),
            || {
                daily_total(&instance.store, daily_lsk, q_new) == Some(2)
                    && single_matches(&instance.store, single_lsk, q_new) == Some(true)
                    && daily_total(&instance.store, daily_lsk, q_old).is_none()
                    && tombstone_for(&instance.store, q_old).map(|t| t.new_person) == Some(q_new)
            },
        )
        .await;

        // (3) F-E count-exactness control: each follower group's committed offset must EQUAL its
        //     produced count BEFORE the checkpoint, so the manifest cannot under-record. Two merges
        //     were produced; the cross-partition one produced exactly one transfer (the same-partition
        //     fast path produces none). Never sleep before a count assert — wait_for on the condition.
        let merge_count = topic_message_count(&topics.merges);
        let transfer_count = topic_message_count(&topics.transfers);
        assert_eq!(merge_count, 2, "two merge triggers on the wire");
        assert_eq!(
            transfer_count, 1,
            "exactly one transfer (cross-partition only; the same-partition merge is the fast path)",
        );
        let merge_verifier = group_verifier(&groups.merges);
        let transfer_verifier = group_verifier(&groups.transfers);
        wait_for(
            "every follower group's committed offset to equal its produced count before checkpoint",
            Duration::from_secs(90),
            || {
                committed_sum(&merge_verifier, &topics.merges) == merge_count
                    && committed_sum(&transfer_verifier, &topics.transfers) == transfer_count
            },
        )
        .await;

        // (4) Checkpoint + upload to S3 from the LIVE trackers while the dispatcher still owns 64
        //     partitions ⇒ the manifest's follower maps are non-empty (the load-bearing difference).
        assert_eq!(
            instance.owned().len(),
            NUM_PARTITIONS as usize,
            "the dispatcher must still own all 64 partitions at checkpoint time",
        );
        checkpoint_to_s3(&instance, &config, &topics, &checkpoint_dir).await;

        // (5) Now request shutdown + join tenure 1, releasing the RocksDB lock.
        shutdown.request_shutdown();
        instance.join().await;

        // === PVC loss: delete both the live store and the local checkpoint dir. ===
        std::fs::remove_dir_all(&store_path).expect("remove store_path (simulate PVC loss)");
        std::fs::remove_dir_all(&checkpoint_dir)
            .expect("remove checkpoint_local_dir (simulate PVC loss)");

        // === Tenure 2: restore from S3 + assert the manifest + restored state. ===
        let restore = run_boot_restore(&config, &store_path).await;
        assert!(
            matches!(restore.source, RestoreSource::S3),
            "with the live store and local checkpoint gone, the restore must come from S3 (got {:?})",
            restore.source,
        );
        let manifest = restore
            .manifest
            .clone()
            .expect("an S3 restore yields an offset manifest to seek");

        // (8/9) FIRST-EVER assertion the follower manifest maps are non-empty. Slice 2 shipped this
        //       inert; here cascade-on traffic populated the merge + transfer trackers, so the captured
        //       manifest carries their offsets. The merge landed on P_old's partition; the transfer on
        //       P_new's.
        assert!(
            manifest.offset_for(&topics.merges, part(p_old) as i32) >= Some(1),
            "the restored manifest must carry the merge follower's offset on P_old's partition \
             (non-empty follower map): {:?}",
            manifest.offset_for(&topics.merges, part(p_old) as i32),
        );
        assert!(
            manifest.offset_for(&topics.transfers, part(p_new) as i32) >= Some(1),
            "the restored manifest must carry the transfer follower's offset on P_new's partition: {:?}",
            manifest.offset_for(&topics.transfers, part(p_new) as i32),
        );

        // (10) Open the restored store and assert count-exact state for BOTH pairs.
        let store2 = open_restored_store(&store_path);
        assert_eq!(
            daily_total(&store2, daily_lsk, p_new),
            Some(2),
            "cross-partition P_new daily count restored exactly (a cold start would read None)",
        );
        assert_eq!(single_matches(&store2, single_lsk, p_new), Some(true));
        assert_eq!(
            tombstone_for(&store2, p_old).map(|t| t.new_person),
            Some(p_new),
            "cross-partition P_old's tombstone (cf_merge_tombstones) survived the restore",
        );
        assert_eq!(
            daily_total(&store2, daily_lsk, p_old),
            None,
            "cross-partition P_old's drained state stays drained after restore",
        );
        assert_eq!(
            daily_total(&store2, daily_lsk, q_new),
            Some(2),
            "same-partition Q_new daily count restored exactly",
        );
        assert_eq!(single_matches(&store2, single_lsk, q_new), Some(true));
        assert_eq!(
            tombstone_for(&store2, q_old).map(|t| t.new_person),
            Some(q_new),
            "same-partition Q_old's tombstone survived the restore",
        );
        assert_eq!(daily_total(&store2, daily_lsk, q_old), None);
        // B's cf_stage2 bit survived: re-membership is read from the restored store, not recomputed.
        assert!(
            stage2_in_cohort(&store2, COHORT_REF, p_new),
            "B's (cohort 3) cf_stage2 membership bit for P_new survived the restore",
        );

        // (11) Spawn a full tenure-2 instance threading the restore manifest (events restore-seek +
        //      follower pre-commit). The store handle is dropped first so the consumer reopens it live.
        drop(store2);
        let mut manager2 = Manager::builder("merge-durability-itest-2")
            .with_trap_signals(false)
            .build();
        let handles2 = register_instance(&mut manager2, "b");
        let shutdown2 = handles2[0].clone();
        let _monitor2 = manager2.monitor_background();

        let store2_live = open_restored_store(&store_path);
        let instance2 = spawn_instance(
            &topics,
            &groups,
            store2_live,
            merge_catalog(),
            handles2,
            config.durable_restore_enabled,
            Some(manifest.clone()),
        )
        .await;
        wait_for(
            "tenure 2 to own every partition (boot sweep + eager redrive + restore-seek settled)",
            Duration::from_secs(30),
            || instance2.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        // (12) F3-on-restore: a post-restore straggler for P_old must redirect via the restored
        //      cf_merge_tombstones — P_old NOT rebuilt and P_new NOT double-counted (redirect_dedup).
        produce_event(&producer, &topics.events, p_old, TS_LATER, 1000).await;
        wait_for(
            "the post-restore straggler to fold into P_new via the restored tombstone",
            Duration::from_secs(60),
            || daily_total(&instance2.store, daily_lsk, p_new) == Some(3),
        )
        .await;
        assert_eq!(
            daily_total(&instance2.store, daily_lsk, p_old),
            None,
            "the restored tombstone redirected the straggler; P_old state was never rebuilt",
        );
        assert_eq!(
            single_matches(&instance2.store, single_lsk, p_new),
            Some(true),
            "P_new's single match holds after the straggler",
        );

        // (13) Replay safety: re-produce the ORIGINAL merge message. The restored
        //      cf_merge_drains_applied / cf_merge_applied markers dedup it — no second transfer.
        produce_merge(&producer, &topics.merges, &merge_event(p_old, p_new)).await;
        let merge_verifier2 = group_verifier(&groups.merges);
        wait_for(
            "the replayed merge to settle (its commit advances) without a second transfer",
            Duration::from_secs(60),
            // The replay is the 3rd merge on the wire across both tenures.
            || committed_sum(&merge_verifier2, &topics.merges) >= 3,
        )
        .await;
        assert_eq!(
            topic_message_count(&topics.transfers),
            1,
            "the replayed merge produced no second transfer (restored drain marker dedups it)",
        );
        assert_eq!(
            daily_total(&instance2.store, daily_lsk, p_new),
            Some(3),
            "P_new's count is unchanged by the replayed merge (apply marker dedups it)",
        );

        // (14) Events committed-sum stays exact: the only events ever produced to the events topic are
        //      the four seeds (2 per pair) + the one straggler. The restore-seek must neither skip nor
        //      re-fold past the committed position. (The cross-partition straggler re-keys to P_new, so
        //      the events topic also carries that one re-key — hence 5 produced + 1 re-key = 6.)
        let events_verifier = group_verifier(&groups.events);
        wait_for(
            "the events committed-sum to reach every produced + re-keyed event",
            Duration::from_secs(60),
            || committed_sum(&events_verifier, &topics.events) == topic_message_count(&topics.events),
        )
        .await;
        assert_eq!(
            committed_sum(&events_verifier, &topics.events),
            topic_message_count(&topics.events),
            "events resumed exactly at the manifest offset — no skip, no re-fold",
        );

        // (15) Cascade is at-least-once (F-D). TESTED DECISION: a direct merge/single/daily membership
        //      change is exact (`==`), but a cascade-origin change (cohort B = COHORT_REF) is bounded
        //      `[expected, expected + 1]` — at-least-once tolerating at most ONE idempotent duplicate,
        //      so a *systematic* double (2× expected) STILL FAILS. This bound is applied identically to
        //      BOTH pairs (cross-partition P_new and same-partition Q_new), and the tolerance is
        //      symmetric for a concrete reason: the cascade produces B's flip to the shadow topic before
        //      it commits the cf_stage2 bit (produce-before-state, TDD §2.3 / SESSION.md), and the
        //      count-exactness control before the checkpoint waits only for the MERGE and TRANSFER groups
        //      to commit — NOT the cascade group. So the cascade follower's committed offset may lag at
        //      checkpoint time, and the tenure-2 restore can re-consume its seek window for EITHER pair,
        //      re-detecting the flip and re-emitting it once. (The duplicate is NOT the step-13 merge
        //      replay, which AlreadyDrained short-circuits before any apply or cascade.) Hence `>=`, not
        //      `==`, for B — and identically for both pairs; tightening Q_new to `==1` would flake on the
        //      lagging-cascade-commit interleaving.
        //
        //      Classify by cohort id: COHORT_REF ⇒ cascade-origin ⇒ at-least-once; COHORT_SINGLE /
        //      COHORT_DAILY ⇒ direct ⇒ exact.
        let total_shadow = topic_message_count(&topics.shadow) as usize;
        let changes = shadow_changes(&topics.shadow, total_shadow).await;

        // Direct flips are exact: each pair's P_new entered cohort 1 (single) and cohort 2 (daily)
        // exactly once. No Lefts (the drain emits no Left for the drained P_old).
        for cohort in [COHORT_SINGLE, COHORT_DAILY] {
            for p_new in [p_new, q_new] {
                let entered = changes
                    .iter()
                    .filter(|c| {
                        c.cohort_id == cohort
                            && c.person_id == p_new.to_string()
                            && c.status == MembershipStatus::Entered
                    })
                    .count();
                assert_eq!(
                    entered, 1,
                    "direct cohort {cohort} Entered for {p_new} must be exact (==1), got {entered}",
                );
            }
        }
        assert!(
            !changes
                .iter()
                .any(|c| c.status == MembershipStatus::Left
                    && (c.person_id == p_old.to_string() || c.person_id == q_old.to_string())),
            "the drain emits no Left for a drained P_old",
        );

        // Cascade-origin flips (cohort B) are at-least-once: exactly 1, or 2 if the tenure-2 restore
        // re-consumed the cascade follower's un-committed seek window and re-emitted the idempotent
        // duplicate (symmetric across both pairs — see (15)). A systematic double exceeds +1 and fails.
        for p_new in [p_new, q_new] {
            let b_entered = changes
                .iter()
                .filter(|c| {
                    c.cohort_id == COHORT_REF
                        && c.person_id == p_new.to_string()
                        && c.status == MembershipStatus::Entered
                })
                .count();
            assert!(
                (1..=2).contains(&b_entered),
                "cascade-origin cohort B (id {COHORT_REF}) Entered for {p_new} must be at-least-once \
                 with at most ONE idempotent replay duplicate ([1,2]); got {b_entered} — a systematic \
                 double is a bug",
            );
        }

        shutdown2.request_shutdown();
        instance2.join().await;
    })
    .await;
}

/// The stored `cf_stage2` membership bit for `(cohort, person)` on the person's partition, `false` if
/// absent. Used to assert B's cascade-set bit survived the restore.
fn stage2_in_cohort(store: &CohortStore, cohort: i32, person: Uuid) -> bool {
    use cohort_stream_processor::stage2::Stage2State;
    use cohort_stream_processor::store::Stage2Key;
    let key = Stage2Key {
        partition_id: part(person),
        team_id: TEAM as u64,
        cohort_id: cohort as u64,
        person_id: person,
    };
    store
        .get_stage2(&key)
        .unwrap()
        .map(|bytes| Stage2State::decode(&bytes).unwrap().in_cohort)
        .unwrap_or(false)
}
