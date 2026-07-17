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

use std::collections::HashSet;
use std::future::Future;
use std::num::NonZeroU32;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono_tz::UTC;
use cohort_core::seed::{ClaimEpoch, ConditionHash, RunId, SChunkMs, SeedTile};
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
    SeedTileSink, StreamEventSink, TransferSink,
};
use cohort_stream_processor::stage1::bucket_tz::day_idx_in_tz;
use cohort_stream_processor::store::{
    CohortStore, OffloadConfig, OffloadMode, StoreConfig, StoreHandle,
};
use cohort_stream_processor::workers::{
    CascadeConfig, MergeWorkerDeps, TransferRetryPolicy, DEFAULT_MERGE_GC_SCAN_LIMIT,
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
const NUM_PARTITIONS: i32 = COHORT_PARTITION_COUNT as i32;
const COMMIT_INTERVAL: Duration = Duration::from_millis(250);
const RECV_TIMEOUT: Duration = Duration::from_millis(200);
/// Effectively never: each test drives the watermark through live folds only, so the idle probe
/// cannot open a fence behind the assertion's back.
const PROBE_NEVER: Duration = Duration::from_secs(3_600);

fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

/// One single-leaf behavioral cohort: `performed_event` on `$pageview` over 7 days, sharing the
/// tile's condition hash.
fn seed_catalog() -> CatalogHandle {
    let leaf = json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "time_value": 7, "time_interval": "day",
        "conditionHash": "0123456789abcdef",
        "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
    });
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(1),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [leaf] } }),
        )
        .expect("add cohort");
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
    let consumer: StreamConsumer = follower_client_config(group)
        .create()
        .expect("create committed-offset verifier");
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition(topic, partition);
    let committed = consumer
        .committed_offsets(tpl, Duration::from_secs(10))
        .ok()?;
    committed
        .elements_for_topic(topic)
        .iter()
        .find(|elem| elem.partition() == partition)
        .and_then(|elem| match elem.offset() {
            Offset::Offset(next) => Some(next),
            _ => None,
        })
}

/// A `$pageview`-mismatched warm-up event: it folds (advancing the partition's live watermark)
/// without flipping any cohort.
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

async fn produce_warm_event(producer: &FutureProducer, topic: &str, person: Uuid, offset: i64) {
    let key = merge_partition_key(TeamId(TEAM), &person);
    let payload = warm_envelope(person, offset);
    let (partition, _) = producer
        .send(
            FutureRecord::to(topic).key(&key).payload(&payload),
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
    handles: [Handle; 5],
    fence_margin_ms: i64,
) -> Instance {
    let [events_handle, merge_handle, transfer_handle, cascade_handle, seed_handle] = handles;
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
        seed_tracker: Arc::new(OffsetTracker::new()),
        live_watermarks: Arc::new(LiveWatermarks::new()),
    });

    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        StoreHandle::new(
            store,
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        ),
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
        seeds_consumer,
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

    Instance { dispatcher, tasks }
}

/// A tile produced with the seeder's keying lands on its owning worker via the 5-topic
/// co-assignment, applies behind an already-open fence, emits an `origin: seed`-tagged membership
/// change, and the seed group's committed offsets reach the produced high-water mark — the
/// run-completion precondition.
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
        // Open alice's partition's fence: one folded live event establishes the watermark well
        // past the tile's hour-old scan point + 2 s margin.
        let producer = murmur2_producer();
        produce_warm_event(&producer, &topics.events, alice, 0).await;

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
        // The shadow topic is keyed by bare person id, not the "{team}:{person}" state key, so it
        // does not co-partition with the owning worker; only the keying itself is assertable here.
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

/// The apply fence end-to-end: a tile scanned "now" stays fenced (uncommitted, unapplied) until
/// live consumption on its partition flows past `s_chunk + margin`; then the held tile applies.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn fence_holds_a_fresh_tile_until_live_consumption_passes_its_scan_point() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        let mut manager = Manager::builder("seed-fence-itest")
            .with_trap_signals(false)
            .build();
        let handles = register_instance(&mut manager);
        let shutdown = handles[0].clone();
        let _monitor = manager.monitor_background();

        let fence_margin_ms = 5_000;
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

        let alice = Uuid::from_u128(0xA11CE);
        let seed_sink = KafkaSeedTileSink::new(&producer_kafka_config(), topics.seeds.clone())
            .await
            .expect("create test seed sink");
        let s_chunk = chrono::Utc::now().timestamp_millis();
        produce_tile(&seed_sink, tile(alice, s_chunk)).await;

        // Held: no live watermark at all on alice's partition (fail-closed), so nothing applies
        // and nothing commits.
        tokio::time::sleep(Duration::from_secs(3)).await;
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

        // A live event folded before `s_chunk + margin` has elapsed still leaves the fence closed.
        let producer = murmur2_producer();
        produce_warm_event(&producer, &topics.events, alice, 0).await;
        tokio::time::sleep(Duration::from_secs(2)).await;
        assert_eq!(
            topic_message_count(&topics.shadow),
            0,
            "a watermark below s_chunk + margin keeps the fence closed",
        );

        // Once wall-clock passes s_chunk + margin, a *newer* live fold opens the fence and the
        // held tile applies on the review cycle.
        tokio::time::sleep(Duration::from_millis(fence_margin_ms as u64 + 1_500)).await;
        produce_warm_event(&producer, &topics.events, alice, 1).await;
        wait_for(
            "the fence to open and the held tile to apply",
            Duration::from_secs(60),
            || topic_message_count(&topics.shadow) == 1,
        )
        .await;
        let (_, payload) = consume_all(&topics.shadow, 1, Duration::from_secs(30))
            .await
            .into_iter()
            .next()
            .expect("one membership change");
        let change: CohortMembershipChange = serde_json::from_slice(&payload).unwrap();
        assert_eq!(change.origin, Some(ChangeOrigin::Seed));
        assert_eq!(change.person_id, alice.to_string());

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}
