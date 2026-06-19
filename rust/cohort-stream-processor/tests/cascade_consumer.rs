//! End-to-end tests for the cascade transport against a **real** Kafka broker: the keyed
//! `cohort_cascade_events` produce, the assignment-mirrored cascade follower, and the worker-affined
//! re-evaluation of referrer cohorts — wired like `main.rs` with the gate on.
//!
//! `#[ignore]`d by default (group joins and `incremental_assign` semantics the in-process
//! `MockCluster` does not exercise faithfully). All topics are created with the production partition
//! count (64) because the routing invariant is the thing under test. Run against a local stack
//! serially:
//!
//! ```sh
//! cargo test -p cohort-stream-processor --test cascade_consumer -- --ignored --test-threads=1
//! ```
//!
//! Each test deletes its topics on the way out via `with_topics_cleanup`.

use std::collections::HashSet;
use std::future::Future;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono_tz::UTC;
use cohort_stream_processor::cascade::{first_cascade, CascadeMessage};
use cohort_stream_processor::consumers::{
    CascadeRoute, CohortStreamEventsConsumer, EventDispatcher, FollowerConsumer, MergeRoute,
    TransferRoute,
};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{
    merge_partition_key, partition_of, run_rebalance_worker, CohortConsumerContext, Follower,
    FollowerSet, OffsetTracker, PartitionRouter, COHORT_PARTITION_COUNT,
};
use cohort_stream_processor::producer::{
    CascadeSink, CohortMembershipChange, KafkaCascadeSink, KafkaMembershipSink,
    KafkaStreamEventSink, KafkaTransferSink, MembershipSink, MembershipStatus, StreamEventSink,
    TransferSink,
};
use cohort_stream_processor::store::{CohortStore, StoreConfig};
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
const A_HASH: &str = "aaaaaaaaaaaaaaaa";
const NUM_PARTITIONS: i32 = COHORT_PARTITION_COUNT as i32;
const TS: &str = "2026-06-10 12:34:56.789000";
const COMMIT_INTERVAL: Duration = Duration::from_millis(250);
const RECV_TIMEOUT: Duration = Duration::from_millis(200);

fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

/// Cohort 2 (A): single `performed_event` on `$a`. Cohort 1 (B): pure cohort-ref to A.
/// With the cascade gate on, B is `Stage2ComposableRef` — only a cascade from A can flip it,
/// never its own event.
fn cascade_catalog() -> CatalogHandle {
    let a_leaf = json!({
        "type": "behavioral", "value": "performed_event", "key": "$a",
        "time_value": 7, "time_interval": "day",
        "conditionHash": A_HASH,
        "bytecode": ["_H", 1, 32, "$a", 32, "event", 1, 1, 11],
    });
    let ref_leaf = json!({ "type": "cohort", "value": 2, "negation": false });
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(2),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [a_leaf] } }),
        )
        .expect("add cohort A");
    builder
        .add_cohort(
            CohortId(1),
            TeamId(TEAM),
            &json!({ "properties": { "type": "AND", "values": [ref_leaf] } }),
        )
        .expect("add cohort B");
    CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(TEAM),
        builder.freeze_with(UTC, true),
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

/// Read up to `expected` messages (all partitions from the beginning). Assigned explicitly — no group
/// join, no commit.
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

fn envelope(person: Uuid, event: &str, source_offset: i64) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "team_id": TEAM,
        "person_id": person.to_string(),
        "distinct_id": "d",
        "uuid": Uuid::from_u128(0xE0_0000 + source_offset as u128).to_string(),
        "event": event,
        "timestamp": TS,
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
    event: &str,
    source_offset: i64,
) {
    let key = merge_partition_key(TeamId(TEAM), &person);
    let payload = envelope(person, event, source_offset);
    let (partition, _offset) = producer
        .send(
            FutureRecord::to(topic).key(&key).payload(&payload),
            Timeout::After(Duration::from_secs(10)),
        )
        .await
        .expect("produce event");
    assert_eq!(partition as u16, part(person), "event must co-partition");
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
    shadow: String,
}

impl Topics {
    fn unique(suffix: &Uuid) -> Self {
        Self {
            events: format!("cohort_stream_events_cascade_{suffix}"),
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

fn register_instance(manager: &mut Manager) -> [Handle; 4] {
    let options = || ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15));
    [
        manager.register("consumer", options()),
        manager.register("merge-follower", options()),
        manager.register("transfer-follower", options()),
        manager.register("cascade-follower", options()),
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
    handles: [Handle; 4],
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
        cascade: CascadeConfig {
            enabled: true,
            depth_cap: 8,
            fanout_cap: 1000,
        },
        partition_count: COHORT_PARTITION_COUNT,
    });

    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        store,
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
        None,
    );
    tasks.push(tokio::spawn(events_consumer.process()));

    Instance { dispatcher, tasks }
}

/// Cascade produces must co-partition with `partition_of(team, person)` so a flip lands on the worker
/// that owns the person's `cf_stage2` row.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn cascade_producer_co_partitions_with_events() {
    let suffix = Uuid::new_v4();
    let cascade_topic = format!("cascade_routing_{suffix}");
    with_topics_cleanup(&[&cascade_topic], async {
        create_topic(&cascade_topic, NUM_PARTITIONS).await;

        let sink = KafkaCascadeSink::new(&producer_kafka_config(), cascade_topic.clone())
            .await
            .expect("create cascade sink");

        let mut spread = HashSet::new();
        let messages: Vec<CascadeMessage> = [2i32, 7, 42, 99]
            .into_iter()
            .flat_map(|team| {
                (1..=24u128).map(move |n| {
                    let person = Uuid::from_u128(((team as u128) << 64) | n);
                    first_cascade(
                        CohortMembershipChange {
                            team_id: team,
                            cohort_id: 91204,
                            person_id: person.to_string(),
                            last_updated: TS.to_string(),
                            status: MembershipStatus::Entered,
                        },
                        n as i64,
                    )
                })
            })
            .collect();
        let total = messages.len();
        let acks = sink.produce(messages).await;
        assert!(acks.iter().all(Result::is_ok), "all cascade produces ack");

        let on_wire = consume_all(&cascade_topic, total, Duration::from_secs(30)).await;
        assert_eq!(on_wire.len(), total, "all produced cascades are readable");
        for (partition, payload) in &on_wire {
            let message: CascadeMessage = serde_json::from_slice(payload).unwrap();
            let person = Uuid::parse_str(&message.change.person_id).unwrap();
            assert_eq!(
                *partition as u32,
                partition_of(
                    TeamId(message.change.team_id),
                    &person,
                    COHORT_PARTITION_COUNT
                ),
                "cascade for ({}, {person}) landed off its partition",
                message.change.team_id,
            );
            spread.insert(*partition);
        }
        assert!(
            spread.len() >= 16,
            "{total} cascades should cover many partitions, got {}",
            spread.len(),
        );
    })
    .await;
}

/// One `$a` event flips A (cohort 2); the first-hop cascade re-evaluates B (cohort 1, a pure ref),
/// which flips and emits an external change plus a depth-2 onward cascade.
/// External bytes are exactly the five-key `CohortMembershipChange` shape.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn cascade_reevaluates_a_referrer_end_to_end() {
    let suffix = Uuid::new_v4();
    let topics = Topics::unique(&suffix);
    let groups = Groups::unique(&suffix);
    with_topics_cleanup(&topics.names(), async {
        topics.create().await;

        let mut manager = Manager::builder("cascade-e2e-itest")
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
            cascade_catalog(),
            handles,
        )
        .await;
        wait_for(
            "the consumer to own every partition",
            Duration::from_secs(30),
            || instance.owned().len() == NUM_PARTITIONS as usize,
        )
        .await;

        let alice = Uuid::from_u128(0xA11CE);
        let producer = murmur2_producer();
        produce_event(&producer, &topics.events, alice, "$a", 0).await;

        wait_for(
            "both cohort flips on the shadow topic",
            Duration::from_secs(60),
            || topic_message_count(&topics.shadow) == 2,
        )
        .await;

        let changes: Vec<CohortMembershipChange> =
            consume_all(&topics.shadow, 2, Duration::from_secs(30))
                .await
                .iter()
                .map(|(_, payload)| serde_json::from_slice(payload).expect("decode change"))
                .collect();
        let entered: HashSet<i32> = changes
            .iter()
            .filter(|c| c.person_id == alice.to_string() && c.status == MembershipStatus::Entered)
            .map(|c| c.cohort_id)
            .collect();
        assert_eq!(
            entered,
            HashSet::from([1, 2]),
            "A entered from the event and B entered from the cascade re-evaluation",
        );

        let (_, payload) = consume_all(&topics.shadow, 1, Duration::from_secs(10))
            .await
            .into_iter()
            .next()
            .expect("one external change");
        let value: serde_json::Value = serde_json::from_slice(&payload).unwrap();
        let mut keys: Vec<&str> = value
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            vec![
                "cohort_id",
                "last_updated",
                "person_id",
                "status",
                "team_id"
            ],
            "external topic carries exactly the five-key shape, no cascade fields",
        );

        // Cascade topic carries depth-1 (A) and depth-2 (B) hops, both keyed on alice's partition.
        wait_for(
            "the depth-1 and depth-2 cascades on the wire",
            Duration::from_secs(60),
            || topic_message_count(&topics.cascade) == 2,
        )
        .await;
        let cascades: Vec<(i32, CascadeMessage)> =
            consume_all(&topics.cascade, 2, Duration::from_secs(30))
                .await
                .iter()
                .map(|(p, payload)| (*p, serde_json::from_slice(payload).expect("decode cascade")))
                .collect();
        for (partition, message) in &cascades {
            assert_eq!(
                *partition as u16,
                part(alice),
                "cascade keyed on alice's partition"
            );
            assert_eq!(
                message.originating_cohort_id, 2,
                "the chain originated at A"
            );
        }
        let by_cohort: HashSet<(i32, u8)> = cascades
            .iter()
            .map(|(_, m)| (m.change.cohort_id, m.depth))
            .collect();
        assert_eq!(
            by_cohort,
            HashSet::from([(2, 1), (1, 2)]),
            "first hop is A at depth 1, the onward hop is B at depth 2",
        );

        shutdown.request_shutdown();
        instance.join().await;
    })
    .await;
}
