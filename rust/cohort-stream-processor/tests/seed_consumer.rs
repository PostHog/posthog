//! End-to-end tests for the backfill seed path against a **real** Kafka broker: the keyed
//! `cohort_stream_seed_events` produce, the assignment-mirrored seed follower (5-topic
//! co-assignment), the apply fence, and the worker-affined tile apply with `origin` tagging —
//! wired like `main.rs` with the seed gate on.
//!
//! `#[ignore]`d by default (group joins and `incremental_assign` semantics the in-process
//! `MockCluster` does not exercise faithfully). All topics are created with the production
//! partition count (64) because the routing invariant is the thing under test. Run against a local
//! stack serially:
//!
//! ```sh
//! cargo test -p cohort-stream-processor --test seed_consumer -- --ignored --test-threads=1
//! ```

use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::num::NonZeroU32;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono_tz::UTC;
use cohort_core::seed::{
    BehavioralShapeHash, ClaimEpoch, ConditionHash, ReconcileTile, RunId, SChunkMs, SeedTile,
};
use cohort_stream_processor::consumers::{
    CascadeRoute, CohortStreamEventsConsumer, EventDispatcher, FollowerConsumer, MergeRoute,
    SeedFollowerConsumer, TransferRoute,
};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{
    merge_partition_key, partition_for, partition_of, run_rebalance_worker, CohortConsumerContext,
    ConsumerPauser, Follower, FollowerSet, LiveWatermarks, OffsetTracker, PartitionPauser,
    PartitionRouter, COHORT_PARTITION_COUNT,
};
use cohort_stream_processor::producer::{
    CascadeSink, ChangeOrigin, CohortMembershipChange, KafkaCascadeSink, KafkaMembershipSink,
    KafkaSeedTileSink, KafkaStreamEventSink, KafkaTransferSink, MembershipSink, MembershipStatus,
    ReconcileCompleteMarker, SeedTileSink, StreamEventSink, TransferSink,
};
use cohort_stream_processor::stage1::bucket_tz::day_idx_in_tz;
use cohort_stream_processor::stage2::state::Stage2State;
use cohort_stream_processor::store::{
    CohortStore, OffloadConfig, OffloadMode, ReadLane, Stage2Key, StagedBatch, StoreConfig,
    StoreHandle,
};
use cohort_stream_processor::workers::{
    CascadeConfig, MergeWorkerDeps, ReconcileBacklog, ReconcileDeps, TransferRetryPolicy,
    DEFAULT_MERGE_GC_SCAN_LIMIT,
};
use common_kafka::config::KafkaConfig;
use futures::FutureExt;
use lifecycle::{ComponentOptions, Handle, Manager};
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
use tokio::task::JoinHandle;
use uuid::Uuid;

const TEAM: i32 = 7;
const COHORT: i32 = 1;
const FILTERS_HASH: &str = "0123456789abcdef";
const NUM_PARTITIONS: i32 = COHORT_PARTITION_COUNT as i32;
const COMMIT_INTERVAL: Duration = Duration::from_millis(250);
const RECV_TIMEOUT: Duration = Duration::from_millis(200);
/// Effectively never: the idle probe must not open a fence behind an assertion's back.
const PROBE_NEVER: Duration = Duration::from_secs(3_600);

fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

/// One single-leaf behavioral cohort sharing the tile's condition hash.
fn seed_catalog() -> CatalogHandle {
    let leaf = json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "time_value": 7, "time_interval": "day",
        "conditionHash": FILTERS_HASH,
        "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
    });
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(COHORT),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [leaf] } }),
        )
        .expect("add cohort");
    builder.set_behavioral_shape_hash(
        CohortId(COHORT),
        BehavioralShapeHash::parse(FILTERS_HASH).expect("valid test behavioral hash"),
    );
    CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(TEAM),
        builder.freeze(UTC),
    )]))
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

async fn with_topics_cleanup<F: Future<Output = ()>>(topics: &[&str], body: F) {
    let result = AssertUnwindSafe(body).catch_unwind().await;
    delete_topics(topics).await;
    if let Err(panic) = result {
        std::panic::resume_unwind(panic);
    }
}

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
        kafka_producer_acks: None,
        kafka_producer_retries: None,
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

/// Read up to `expected` messages (all partitions from the beginning). Assigned explicitly — no
/// group join, no commit.
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

/// The seed group's committed next-offset for `partition`, read without joining the group.
fn seed_group_committed(group: &str, topic: &str, partition: i32) -> Option<i64> {
    seed_group_committed_offsets(group, topic)
        .get(&partition)
        .copied()
}

/// Every concrete committed next-offset for the seed topic, read in one coordinator request.
fn seed_group_committed_offsets(group: &str, topic: &str) -> HashMap<i32, i64> {
    let consumer: StreamConsumer = follower_client_config(group)
        .create()
        .expect("create committed-offset verifier");
    let mut tpl = TopicPartitionList::new();
    for partition in 0..NUM_PARTITIONS {
        tpl.add_partition(topic, partition);
    }
    let committed = consumer
        .committed_offsets(tpl, Duration::from_secs(10))
        .expect("query seed-group committed offsets");
    committed
        .elements_for_topic(topic)
        .iter()
        .filter_map(|elem| match elem.offset() {
            Offset::Offset(next) => Some((elem.partition(), next)),
            _ => None,
        })
        .collect()
}

/// A name-mismatched warm-up event: folds (advancing the watermark) without flipping anything.
fn warm_envelope(person: Uuid, source_offset: i64) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "team_id": TEAM,
        "person_id": person.to_string(),
        "distinct_id": "d",
        "uuid": Uuid::from_u128(0xE0_0000 + source_offset as u128).to_string(),
        "event": "$warm",
        "timestamp": "2026-06-10 12:34:56.789000",
        "properties": "{}",
        "person_properties": null,
        "elements_chain": null,
        "source_offset": source_offset,
        "source_partition": 0,
    }))
    .expect("serialize envelope")
}

async fn produce_warm_event(
    producer: &FutureProducer,
    topic: &str,
    person: Uuid,
    offset: i64,
    broker_timestamp_ms: i64,
) {
    let key = merge_partition_key(TeamId(TEAM), &person);
    let payload = warm_envelope(person, offset);
    let (partition, _) = producer
        .send(
            FutureRecord::to(topic)
                .key(&key)
                .payload(&payload)
                .timestamp(broker_timestamp_ms),
            Timeout::After(Duration::from_secs(10)),
        )
        .await
        .expect("produce warm event");
    assert_eq!(partition as u16, part(person), "event must co-partition");
}

fn tile(person: Uuid, s_chunk_ms: i64) -> SeedTile {
    SeedTile::new(
        TeamId(TEAM),
        person,
        ConditionHash::parse("0123456789abcdef").unwrap(),
        NonZeroU32::new(2).unwrap(),
        day_idx_in_tz(chrono::Utc::now().timestamp_millis(), UTC),
        SChunkMs(s_chunk_ms),
        RunId(Uuid::from_u128(0xBF)),
        ClaimEpoch(1),
    )
}

/// Produce a tile through the production sink (the same keying the seeder and the re-key path use).
async fn produce_tile(seed_sink: &KafkaSeedTileSink, produced: SeedTile) {
    let acks = seed_sink.produce(vec![produced]).await;
    assert!(acks.iter().all(Result::is_ok), "tile produce must ack");
}

async fn produce_reconcile(
    producer: &FutureProducer,
    topic: &str,
    partition: i32,
    tile: &ReconcileTile,
) -> i64 {
    let key = format!("reconcile:{TEAM}:{COHORT}:{partition}");
    let payload = serde_json::to_vec(tile).expect("serialize reconcile control");
    let (ack_partition, offset) = producer
        .send(
            FutureRecord::to(topic)
                .partition(partition)
                .key(&key)
                .payload(&payload),
            Timeout::After(Duration::from_secs(10)),
        )
        .await
        .expect("produce reconcile control");
    assert_eq!(
        ack_partition, partition,
        "broker acked the targeted partition"
    );
    offset
}

fn open_store(dir: &TempDir) -> CohortStore {
    CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store")
}

struct Topics {
    events: String,
    merges: String,
    transfers: String,
    cascade: String,
    seeds: String,
    shadow: String,
}

impl Topics {
    fn unique(suffix: &Uuid) -> Self {
        Self {
            events: format!("cohort_stream_events_seed_{suffix}"),
            merges: format!("person_merge_events_{suffix}"),
            transfers: format!("cohort_merge_state_transfer_{suffix}"),
            cascade: format!("cohort_cascade_events_{suffix}"),
            seeds: format!("cohort_stream_seed_events_{suffix}"),
            shadow: format!("cohort_membership_changed_{suffix}"),
        }
    }

    async fn create(&self) {
        for topic in self.names() {
            create_topic(topic, NUM_PARTITIONS).await;
        }
    }

    fn names(&self) -> [&str; 6] {
        [
            &self.events,
            &self.merges,
            &self.transfers,
            &self.cascade,
            &self.seeds,
            &self.shadow,
        ]
    }
}

struct Groups {
    events: String,
    merges: String,
    transfers: String,
    cascade: String,
    seeds: String,
}

impl Groups {
    fn unique(suffix: &Uuid) -> Self {
        Self {
            events: format!("cohort-stream-processor-{suffix}"),
            merges: format!("cohort-stream-merges-{suffix}"),
            transfers: format!("cohort-stream-merge-apply-{suffix}"),
            cascade: format!("cohort-stream-cascade-{suffix}"),
            seeds: format!("cohort-stream-seeds-{suffix}"),
        }
    }
}

fn register_instance(manager: &mut Manager) -> [Handle; 5] {
    let options = || ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15));
    [
        manager.register("consumer", options()),
        manager.register("merge-follower", options()),
        manager.register("transfer-follower", options()),
        manager.register("cascade-follower", options()),
        manager.register("seed-follower", options()),
    ]
}

struct Instance {
    dispatcher: Arc<EventDispatcher>,
    store: StoreHandle,
    reconcile_backlog: Arc<ReconcileBacklog>,
    seed_tracker: Arc<OffsetTracker>,
    seed_consumer: Arc<StreamConsumer>,
    live_watermarks: Arc<LiveWatermarks>,
    tasks: Vec<JoinHandle<()>>,
}

impl Instance {
    fn owned(&self) -> HashSet<i32> {
        self.dispatcher.owned_partitions().into_iter().collect()
    }

    async fn put_stage2(&self, key: &Stage2Key, state: &Stage2State) {
        let mut staged = StagedBatch::default();
        staged.put_stage2(key, &state.encode());
        self.store
            .commit(staged)
            .await
            .expect("write test Stage 2 state");
    }

    async fn stage2(&self, key: &Stage2Key) -> Stage2State {
        let bytes = self
            .store
            .get_stage2(key, ReadLane::Maintenance)
            .await
            .expect("read test Stage 2 state")
            .expect("test Stage 2 row exists");
        Stage2State::decode(&bytes).expect("decode test Stage 2 state")
    }

    fn seed_committable(&self, partition: u16) -> Option<i64> {
        self.seed_tracker
            .committable_offsets()
            .get(&(partition as i32))
            .copied()
    }

    fn seed_position(&self, topic: &str, partition: u16) -> Option<i64> {
        let positions = self
            .seed_consumer
            .position()
            .expect("query seed-consumer positions");
        positions
            .elements_for_topic(topic)
            .iter()
            .find(|elem| elem.partition() == partition as i32)
            .and_then(|elem| match elem.offset() {
                Offset::Offset(next) => Some(next),
                _ => None,
            })
    }

    fn live_watermark(&self, partition: u16) -> Option<i64> {
        self.live_watermarks
            .get(partition as i32)
            .map(|watermark| watermark.0)
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
    handles: [Handle; 5],
    fence_margin_ms: i64,
) -> Instance {
    let [events_handle, merge_handle, transfer_handle, cascade_handle, seed_handle] = handles;
    let kafka_config = producer_kafka_config();
    let store = StoreHandle::new(
        store,
        OffloadConfig {
            mode: OffloadMode::All,
            event_read_permits: 16,
            maintenance_permits: 6,
        },
    );
    let reconcile_backlog = Arc::new(ReconcileBacklog::default());
    let seed_tracker = Arc::new(OffsetTracker::new());
    let live_watermarks = Arc::new(LiveWatermarks::new());

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
    let cascade_sink: Arc<dyn CascadeSink> = Arc::new(
        KafkaCascadeSink::new(&kafka_config, topics.cascade.clone())
            .await
            .expect("create cascade sink"),
    );
    let seed_tile_sink: Arc<dyn SeedTileSink> = Arc::new(
        KafkaSeedTileSink::new(&kafka_config, topics.seeds.clone())
            .await
            .expect("create seed re-key sink"),
    );
    let membership_sink: Arc<dyn MembershipSink> = Arc::new(
        KafkaMembershipSink::new(&kafka_config, topics.shadow.clone())
            .await
            .expect("create membership sink"),
    );
    let merge_deps = Arc::new(MergeWorkerDeps {
        transfer_sink,
        stream_event_sink,
        merge_tracker: Arc::new(OffsetTracker::new()),
        transfer_tracker: Arc::new(OffsetTracker::new()),
        retry: TransferRetryPolicy::default(),
        gc_scan_limit: DEFAULT_MERGE_GC_SCAN_LIMIT,
        stage2_orphan_gc_enabled: true,
        cascade_sink,
        cascade_tracker: Arc::new(OffsetTracker::new()),
        cascade: CascadeConfig::default(),
        partition_count: COHORT_PARTITION_COUNT,
        seed_tile_sink,
        seed_tracker: seed_tracker.clone(),
        live_watermarks: live_watermarks.clone(),
        register_transfer_enabled: false,
        reconcile: ReconcileDeps {
            enabled: true,
            scan_page: 1,
            backlog: reconcile_backlog.clone(),
        },
    });

    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        store.clone(),
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
    let cascade_consumer: Arc<StreamConsumer> = Arc::new(
        follower_client_config(&groups.cascade)
            .create()
            .expect("create cascade follower consumer"),
    );
    let seeds_consumer: Arc<StreamConsumer> = Arc::new(
        follower_client_config(&groups.seeds)
            .create()
            .expect("create seed follower consumer"),
    );
    let followers = Arc::new(FollowerSet::new([
        Follower::new(merges_consumer.clone(), topics.merges.clone()),
        Follower::new(transfers_consumer.clone(), topics.transfers.clone()),
        Follower::new(cascade_consumer.clone(), topics.cascade.clone()),
        Follower::new(seeds_consumer.clone(), topics.seeds.clone()),
    ]));

    let (context, rebalance_rx) = CohortConsumerContext::new(dispatcher.clone());
    let events_client: StreamConsumer<CohortConsumerContext> = events_client_config(&groups.events)
        .create_with_context(context)
        .expect("create events consumer");
    events_client
        .subscribe(&[topics.events.as_str()])
        .expect("subscribe events");
    let events_client = Arc::new(events_client);

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

    let seed_pauser: Arc<dyn PartitionPauser> = Arc::new(ConsumerPauser::new(
        seeds_consumer.clone(),
        topics.seeds.clone(),
    ));
    let seed_follower = SeedFollowerConsumer::new(
        seeds_consumer.clone(),
        topics.seeds.clone(),
        events_client.clone(),
        topics.events.clone(),
        dispatcher.clone(),
        seed_handle,
        seed_pauser,
        100,
        RECV_TIMEOUT,
        COMMIT_INTERVAL,
        fence_margin_ms,
        PROBE_NEVER,
    );
    tasks.push(tokio::spawn(seed_follower.process()));

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
        dispatcher,
        store,
        reconcile_backlog,
        seed_tracker,
        seed_consumer: seeds_consumer,
        live_watermarks,
        tasks,
    }
}

/// A tile lands on its owning worker via the 5-topic co-assignment, applies behind an open
/// fence, emits a tagged change, and the seed group's commits reach the produced high-water mark.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn seed_tile_applies_on_the_owning_worker_and_commits_to_the_hwm() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        let mut manager = Manager::builder("seed-e2e-itest")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager);
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let dir = TempDir::new().unwrap();
        let instance = spawn_instance(
            &topics,
            &groups,
            open_store(&dir),
            seed_catalog(),
            handles,
            2_000,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        let alice = Uuid::from_u128(0xA11CE);
        // One folded live event opens the fence for the hour-old scan point.
        let producer = murmur2_producer();
        produce_warm_event(
            &producer,
            &topics.events,
            alice,
            0,
            chrono::Utc::now().timestamp_millis(),
        )
        .await;

        let seed_sink = KafkaSeedTileSink::new(&producer_kafka_config(), topics.seeds.clone())
            .await
            .expect("create test seed sink");
        let s_chunk = chrono::Utc::now().timestamp_millis() - 3_600_000;
        produce_tile(&seed_sink, tile(alice, s_chunk)).await;

        wait_for(
            "the seeded flip on the shadow topic",
            Duration::from_secs(60),
            || topic_message_count(&topics.shadow) == 1,
        )
        .await;
        let (partition, payload) = consume_all(&topics.shadow, 1, Duration::from_secs(30))
            .await
            .into_iter()
            .next()
            .expect("one membership change");
        let change: CohortMembershipChange = serde_json::from_slice(&payload).unwrap();
        assert_eq!(change.person_id, alice.to_string());
        assert_eq!(change.cohort_id, 1);
        assert_eq!(change.status, MembershipStatus::Entered);
        assert_eq!(change.origin, Some(ChangeOrigin::Seed));
        assert_eq!(change.run_id, Some(RunId(Uuid::from_u128(0xBF))));
        // The shadow topic is person-id keyed, so it does not co-partition with the owning
        // worker; only the keying is assertable.
        assert_eq!(
            partition as u32,
            partition_for(&alice.to_string(), COHORT_PARTITION_COUNT),
            "the change is person-id keyed on the shadow topic",
        );

        // Run-completion precondition: committed ⇒ durably applied, reaching the produced HWM.
        let seed_partition = part(alice) as i32;
        wait_for(
            "the seed group's committed offset to reach the produced HWM",
            Duration::from_secs(30),
            || seed_group_committed(&groups.seeds, &topics.seeds, seed_partition) == Some(1),
        )
        .await;

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}

/// Partition-targeted controls drain a full 64-partition snapshot, repair a stale membership bit,
/// and release each seed offset only after that partition's completion marker is acknowledged.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn reconcile_snapshot_repairs_stale_state_and_commits_after_markers() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        let mut manager = Manager::builder("reconcile-e2e-itest")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager);
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let dir = TempDir::new().unwrap();
        let instance = spawn_instance(
            &topics,
            &groups,
            open_store(&dir),
            seed_catalog(),
            handles,
            2_000,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        // This person has no leaf state, so current membership is false. The injected true
        // register bit models an at-most-once output loss or an edit-path stale row.
        let person = Uuid::from_u128(0xDEC0DE);
        let person_partition = part(person);
        let stage2_key = Stage2Key {
            partition_id: person_partition,
            team_id: TEAM as u64,
            cohort_id: COHORT as u64,
            person_id: person,
        };
        instance
            .put_stage2(
                &stage2_key,
                &Stage2State {
                    in_cohort: true,
                    last_evaluated_at_ms: 1,
                },
            )
            .await;
        assert!(instance.stage2(&stage2_key).await.in_cohort);

        let run_id = RunId(Uuid::from_u128(0xB4));
        let reconcile = ReconcileTile::new(
            TeamId(TEAM),
            CohortId(COHORT),
            BehavioralShapeHash::parse(FILTERS_HASH).unwrap(),
            run_id,
        );
        let producer = murmur2_producer();

        for partition in 0..NUM_PARTITIONS {
            assert_eq!(
                produce_reconcile(&producer, &topics.seeds, partition, &reconcile).await,
                0,
                "a unique topic starts every partition at offset zero",
            );
        }
        wait_for(
            "all partition-targeted reconcile controls to be admitted",
            Duration::from_secs(30),
            || instance.reconcile_backlog.len() == i64::from(NUM_PARTITIONS),
        )
        .await;
        let before_first_tick = seed_group_committed_offsets(&groups.seeds, &topics.seeds);
        assert!(
            before_first_tick.is_empty(),
            "no reconcile control commits before draining starts",
        );
        assert!((0..NUM_PARTITIONS)
            .all(|partition| { instance.seed_committable(partition as u16).is_none() }));

        // scan_page=1 makes the stale row consume a whole first page. Every empty partition can
        // emit its marker immediately, while this partition remains pinned after emitting `left`.
        instance.dispatcher.route_reconcile_drain().await;
        wait_for(
            "63 empty-partition markers and one stale-row repair",
            Duration::from_secs(60),
            || topic_message_count(&topics.shadow) == NUM_PARTITIONS as i64,
        )
        .await;
        wait_for(
            "only the stale-row partition to remain queued",
            Duration::from_secs(30),
            || instance.reconcile_backlog.len() == 1,
        )
        .await;
        assert_ne!(
            seed_group_committed(&groups.seeds, &topics.seeds, person_partition as i32),
            Some(1),
            "the reconcile seed offset stays pinned before its marker",
        );
        assert_eq!(
            instance.seed_committable(person_partition),
            None,
            "the production tracker stays pinned immediately after the row and before its marker",
        );
        assert!(!instance.stage2(&stage2_key).await.in_cohort);

        let first_page = consume_all(
            &topics.shadow,
            NUM_PARTITIONS as usize,
            Duration::from_secs(30),
        )
        .await;
        let mut first_changes = Vec::new();
        let mut first_markers = Vec::new();
        for (_, payload) in first_page {
            let value: serde_json::Value = serde_json::from_slice(&payload).unwrap();
            if value.get("type").and_then(serde_json::Value::as_str) == Some("reconcile_complete") {
                first_markers
                    .push(serde_json::from_slice::<ReconcileCompleteMarker>(&payload).unwrap());
            } else {
                first_changes
                    .push(serde_json::from_slice::<CohortMembershipChange>(&payload).unwrap());
            }
        }
        assert_eq!(first_changes.len(), 1);
        assert_eq!(first_changes[0].person_id, person.to_string());
        assert_eq!(first_changes[0].status, MembershipStatus::Left);
        assert_eq!(first_changes[0].origin, Some(ChangeOrigin::Reconcile));
        assert_eq!(first_changes[0].run_id, Some(run_id));
        assert_eq!(first_markers.len(), NUM_PARTITIONS as usize - 1);
        assert!(!first_markers
            .iter()
            .any(|marker| marker.partition() == person_partition));

        instance.dispatcher.route_reconcile_drain().await;
        wait_for(
            "the final partition marker",
            Duration::from_secs(30),
            || topic_message_count(&topics.shadow) == i64::from(NUM_PARTITIONS) + 1,
        )
        .await;
        wait_for(
            "all reconcile jobs to complete",
            Duration::from_secs(30),
            || instance.reconcile_backlog.is_empty(),
        )
        .await;
        wait_for(
            "every seed partition commit to advance past its marker",
            Duration::from_secs(30),
            || {
                let offsets = seed_group_committed_offsets(&groups.seeds, &topics.seeds);
                (0..NUM_PARTITIONS).all(|partition| offsets.get(&partition) == Some(&1))
            },
        )
        .await;
        assert!((0..NUM_PARTITIONS)
            .all(|partition| { instance.seed_committable(partition as u16) == Some(1) }));

        let first_snapshot = consume_all(
            &topics.shadow,
            NUM_PARTITIONS as usize + 1,
            Duration::from_secs(30),
        )
        .await;
        let mut marker_partitions = HashSet::new();
        let mut snapshot_changes = Vec::new();
        for (_, payload) in first_snapshot {
            let value: serde_json::Value = serde_json::from_slice(&payload).unwrap();
            if value.get("type").and_then(serde_json::Value::as_str) == Some("reconcile_complete") {
                let marker: ReconcileCompleteMarker = serde_json::from_slice(&payload).unwrap();
                assert_eq!(marker.team_id(), TeamId(TEAM));
                assert_eq!(marker.cohort_id(), CohortId(COHORT));
                assert_eq!(marker.run_id(), run_id);
                marker_partitions.insert(marker.partition());
            } else {
                snapshot_changes
                    .push(serde_json::from_slice::<CohortMembershipChange>(&payload).unwrap());
            }
        }
        let expected_marker_partitions: HashSet<u16> = (0..COHORT_PARTITION_COUNT)
            .map(|partition| partition as u16)
            .collect();
        assert_eq!(marker_partitions, expected_marker_partitions);
        assert_eq!(snapshot_changes.len(), 1);
        assert_eq!(snapshot_changes[0].status, MembershipStatus::Left);

        // A duplicate manual dispatch emits the same full snapshot and certificate set, leaves the
        // repaired bit unchanged, and advances every partition by exactly one more seed offset.
        for partition in 0..NUM_PARTITIONS {
            assert_eq!(
                produce_reconcile(&producer, &topics.seeds, partition, &reconcile).await,
                1,
            );
        }
        wait_for(
            "the duplicate reconcile controls to be admitted",
            Duration::from_secs(30),
            || instance.reconcile_backlog.len() == i64::from(NUM_PARTITIONS),
        )
        .await;
        instance.dispatcher.route_reconcile_drain().await;
        wait_for(
            "the duplicate snapshot first page",
            Duration::from_secs(60),
            || topic_message_count(&topics.shadow) == i64::from(NUM_PARTITIONS) * 2 + 1,
        )
        .await;
        assert_eq!(
            seed_group_committed(&groups.seeds, &topics.seeds, person_partition as i32),
            Some(1),
            "redispatch stays pinned at the prior next-offset until its new marker",
        );
        assert_eq!(
            instance.seed_committable(person_partition),
            Some(1),
            "the production tracker stays at the prior next-offset before the new marker",
        );
        instance.dispatcher.route_reconcile_drain().await;
        wait_for(
            "the duplicate snapshot marker set",
            Duration::from_secs(30),
            || topic_message_count(&topics.shadow) == i64::from(NUM_PARTITIONS) * 2 + 2,
        )
        .await;
        wait_for(
            "every redispatched seed partition commit to advance",
            Duration::from_secs(30),
            || {
                let offsets = seed_group_committed_offsets(&groups.seeds, &topics.seeds);
                (0..NUM_PARTITIONS).all(|partition| offsets.get(&partition) == Some(&2))
            },
        )
        .await;
        assert!((0..NUM_PARTITIONS)
            .all(|partition| { instance.seed_committable(partition as u16) == Some(2) }));
        assert!(!instance.stage2(&stage2_key).await.in_cohort);

        let converged = consume_all(
            &topics.shadow,
            (NUM_PARTITIONS as usize * 2) + 2,
            Duration::from_secs(30),
        )
        .await;
        let mut marker_counts = HashMap::<u16, usize>::new();
        let mut reconcile_changes = Vec::new();
        for (_, payload) in converged {
            let value: serde_json::Value = serde_json::from_slice(&payload).unwrap();
            if value.get("type").and_then(serde_json::Value::as_str) == Some("reconcile_complete") {
                let marker: ReconcileCompleteMarker = serde_json::from_slice(&payload).unwrap();
                assert_eq!(marker.team_id(), TeamId(TEAM));
                assert_eq!(marker.cohort_id(), CohortId(COHORT));
                assert_eq!(marker.run_id(), run_id);
                *marker_counts.entry(marker.partition()).or_default() += 1;
            } else {
                reconcile_changes
                    .push(serde_json::from_slice::<CohortMembershipChange>(&payload).unwrap());
            }
        }
        assert_eq!(
            marker_counts.keys().copied().collect::<HashSet<_>>(),
            expected_marker_partitions,
        );
        assert!(marker_counts.values().all(|count| *count == 2));
        assert_eq!(reconcile_changes.len(), 2);
        assert!(reconcile_changes.iter().all(|change| {
            change.person_id == person.to_string()
                && change.status == MembershipStatus::Left
                && change.origin == Some(ChangeOrigin::Reconcile)
                && change.run_id == Some(run_id)
        }));

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}

/// A tile scanned "now" stays fenced until live consumption flows past `s_chunk + margin`.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn fence_holds_a_fresh_tile_until_live_consumption_passes_its_scan_point() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        // Put both same-partition records on the broker before the follower starts so its first
        // receive batch can observe the closed tile and the FIFO suffix together.
        let alice = Uuid::from_u128(0xA11CE);
        let fence_margin_ms = 5_000;
        let producer = murmur2_producer();
        let seed_sink = KafkaSeedTileSink::new(&producer_kafka_config(), topics.seeds.clone())
            .await
            .expect("create test seed sink");
        let s_chunk = chrono::Utc::now().timestamp_millis();
        produce_tile(&seed_sink, tile(alice, s_chunk)).await;
        let run_id = RunId(Uuid::from_u128(0x0F3E_CEC0));
        let reconcile = ReconcileTile::new(
            TeamId(TEAM),
            CohortId(COHORT),
            BehavioralShapeHash::parse(FILTERS_HASH).unwrap(),
            run_id,
        );
        assert_eq!(
            produce_reconcile(&producer, &topics.seeds, part(alice) as i32, &reconcile,).await,
            1,
            "the reconcile control follows the closed data tile in the same partition",
        );

        let mut manager = Manager::builder("seed-fence-itest")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager);
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let dir = TempDir::new().unwrap();
        let instance = spawn_instance(
            &topics,
            &groups,
            open_store(&dir),
            seed_catalog(),
            handles,
            fence_margin_ms,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        // No watermark at all: wait until Kafka has delivered both records, then give the follower
        // a full receive/commit cycle to expose any accidental reconcile admission.
        wait_for(
            "the seed consumer to fetch the closed tile and its FIFO suffix",
            Duration::from_secs(30),
            || instance.seed_position(&topics.seeds, part(alice)) == Some(2),
        )
        .await;
        tokio::time::sleep(COMMIT_INTERVAL + RECV_TIMEOUT + Duration::from_millis(250)).await;
        assert_eq!(
            topic_message_count(&topics.shadow),
            0,
            "the fenced tile must not apply",
        );
        assert_eq!(
            seed_group_committed(&groups.seeds, &topics.seeds, part(alice) as i32),
            None,
            "a held tile's offset must never commit",
        );
        assert!(
            instance.reconcile_backlog.is_empty(),
            "reconcile must not leapfrog a closed data tile",
        );
        assert_eq!(instance.seed_committable(part(alice)), None);

        // A live event at the exact bound still leaves the fence closed. Its explicit broker
        // timestamp makes the assertion independent of manager startup and machine speed.
        let closed_watermark = s_chunk + fence_margin_ms;
        produce_warm_event(&producer, &topics.events, alice, 0, closed_watermark).await;
        wait_for(
            "the below-threshold live watermark to fold",
            Duration::from_secs(30),
            || instance.live_watermark(part(alice)) == Some(closed_watermark),
        )
        .await;
        assert_eq!(
            topic_message_count(&topics.shadow),
            0,
            "a watermark below s_chunk + margin keeps the fence closed",
        );
        assert!(instance.reconcile_backlog.is_empty());

        // One millisecond past the bound, a newer live fold opens the fence for the tile and then
        // admits the reconcile control behind it. The tile materializes the scan register first.
        produce_warm_event(&producer, &topics.events, alice, 1, closed_watermark + 1).await;
        wait_for(
            "the fence to open and the held tile to apply",
            Duration::from_secs(60),
            || topic_message_count(&topics.shadow) == 1,
        )
        .await;
        wait_for(
            "the reconcile control behind the opened tile to be admitted",
            Duration::from_secs(30),
            || instance.reconcile_backlog.len() == 1,
        )
        .await;
        assert_eq!(
            instance.seed_committable(part(alice)),
            Some(1),
            "the applied data tile advances to the following deferred control",
        );

        instance.dispatcher.route_reconcile_drain().await;
        wait_for(
            "the reconcile membership row",
            Duration::from_secs(30),
            || topic_message_count(&topics.shadow) == 2,
        )
        .await;
        assert_eq!(instance.reconcile_backlog.len(), 1);
        assert_eq!(
            instance.seed_committable(part(alice)),
            Some(1),
            "the control remains deferred after its row and before its marker",
        );

        instance.dispatcher.route_reconcile_drain().await;
        wait_for(
            "the reconcile completion marker",
            Duration::from_secs(30),
            || topic_message_count(&topics.shadow) == 3,
        )
        .await;
        assert!(instance.reconcile_backlog.is_empty());
        assert_eq!(instance.seed_committable(part(alice)), Some(2));
        wait_for(
            "the seed group to commit both FIFO messages",
            Duration::from_secs(30),
            || seed_group_committed(&groups.seeds, &topics.seeds, part(alice) as i32) == Some(2),
        )
        .await;

        let outputs = consume_all(&topics.shadow, 3, Duration::from_secs(30)).await;
        let mut changes = Vec::new();
        let mut markers = Vec::new();
        for (_, payload) in outputs {
            let value: serde_json::Value = serde_json::from_slice(&payload).unwrap();
            if value.get("type").and_then(serde_json::Value::as_str) == Some("reconcile_complete") {
                markers.push(serde_json::from_slice::<ReconcileCompleteMarker>(&payload).unwrap());
            } else {
                changes.push(serde_json::from_slice::<CohortMembershipChange>(&payload).unwrap());
            }
        }
        assert_eq!(changes.len(), 2);
        assert!(changes.iter().any(|change| {
            change.person_id == alice.to_string() && change.origin == Some(ChangeOrigin::Seed)
        }));
        assert!(changes.iter().any(|change| {
            change.person_id == alice.to_string()
                && change.status == MembershipStatus::Entered
                && change.origin == Some(ChangeOrigin::Reconcile)
                && change.run_id == Some(run_id)
        }));
        assert_eq!(markers.len(), 1);
        assert_eq!(markers[0].partition(), part(alice));
        assert_eq!(markers[0].run_id(), run_id);

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}
