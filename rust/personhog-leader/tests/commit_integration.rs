//! The write path's commit outlives the handler that started it.

mod common;

use std::sync::Arc;
use std::time::{Duration, Instant};

use common::{
    create_local_kafka_producer, seed_person, test_cached_person, test_kafka_config, test_recovery,
    unique_team_id, KAFKA_BOOTSTRAP,
};
use dashmap::DashMap;
use personhog_common::partitioning::partition_for_person;
use personhog_leader::cache::{DirtyIndex, PartitionedCache, PersonCacheKey};
use personhog_leader::emitted::EmittedVersions;
use personhog_leader::fencing::{FencedChangelogProducers, FencedProducerConfig};
use personhog_leader::inflight::InflightTracker;
use personhog_leader::service::{PersonHogLeaderService, PropertySizeLimits};
use personhog_leader::warnings::WarningsProducer;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeader;
use personhog_proto::personhog::types::v1::{
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use tokio::task::JoinHandle;
use tonic::{Request, Response, Status};

/// One partition, so the auto-created topic holds the person's partition.
const NUM_PARTITIONS: u32 = 1;

/// Comfortably above the test config's 5s `message.timeout.ms`, which
/// librdkafka requires the broker bound to cover.
const BROKER_TXN_TIMEOUT: Duration = Duration::from_secs(30);

type Write = JoinHandle<Result<Response<UpdatePersonPropertiesResponse>, Status>>;

struct Harness {
    service: Arc<PersonHogLeaderService>,
    fenced: Arc<FencedChangelogProducers>,
    cache: Arc<PartitionedCache>,
    key: PersonCacheKey,
    partition: u32,
}

/// A leader service over real fenced producers, with windows the test
/// closes itself so nothing here depends on a timer.
async fn start_harness() -> Harness {
    let topic = format!("commit_test_{}", uuid::Uuid::new_v4().simple());
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    let fenced = Arc::new(FencedChangelogProducers::new(FencedProducerConfig {
        kafka,
        topic: topic.clone(),
        init_timeout: Duration::from_secs(10),
        commit_timeout: Duration::from_secs(10),
        broker_txn_timeout: BROKER_TXN_TIMEOUT,
        window: Duration::from_secs(20),
        window_max_writes: 32,
        settle_budget: Duration::from_secs(5),
        lanes: 1,
    }));

    let mut seed = test_cached_person();
    seed.team_id = unique_team_id();
    let key = PersonCacheKey {
        team_id: seed.team_id,
        person_id: seed.id,
    };
    let partition = partition_for_person(key.team_id, key.person_id, NUM_PARTITIONS);
    fenced.acquire(partition).await.expect("acquire the fence");

    let cache = Arc::new(PartitionedCache::new(1 << 20));
    cache.create_partition(partition);
    seed_person(&cache, partition, seed);
    let producer = create_local_kafka_producer().await;
    let service = Arc::new(PersonHogLeaderService::new(
        Arc::clone(&cache),
        producer.clone(),
        topic,
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(KAFKA_BOOTSTRAP),
        PropertySizeLimits::new(655360, 524288),
        WarningsProducer::new(producer, "clickhouse_ingestion_warnings".to_string()),
        Arc::new(DashMap::new()),
        Some(Arc::clone(&fenced)),
        None,
        Arc::new(EmittedVersions::new(1_000_000)),
    ));
    Harness {
        service,
        fenced,
        cache,
        key,
        partition,
    }
}

fn spawn_write(harness: &Harness, properties: serde_json::Value) -> Write {
    let mut request = Request::new(UpdatePersonPropertiesRequest {
        force_update: false,
        team_id: harness.key.team_id,
        person_id: harness.key.person_id,
        event_name: "$set".to_string(),
        set_properties: serde_json::to_vec(&properties).unwrap(),
        set_once_properties: vec![],
        unset_properties: vec![],
        is_identified: None,
        last_seen_at: None,
    });
    request.metadata_mut().insert(
        "x-partition",
        harness.partition.to_string().parse().unwrap(),
    );
    let service = Arc::clone(&harness.service);
    tokio::spawn(async move { service.update_person_properties(request).await })
}

async fn wait_until(what: &str, condition: impl Fn() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(10);
    while !condition() {
        assert!(Instant::now() < deadline, "{what}");
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

/// Wait until the write's record is in the window awaiting the commit,
/// the point a client deadline interrupts.
async fn wait_for_ack_wait(harness: &Harness, write: &mut Write) {
    let deadline = Instant::now() + Duration::from_secs(10);
    while harness
        .fenced
        .waiting_writers_for_test(harness.partition, 0)
        == 0
    {
        if write.is_finished() {
            let outcome = write.await;
            panic!("the write ended before its ack wait: {outcome:?}");
        }
        assert!(
            Instant::now() < deadline,
            "the write never reached its ack wait"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

/// A write whose client gives up between the send and the ack still
/// lands in the cache, and the next write for the person builds on it
/// rather than on the state before it.
#[tokio::test]
async fn a_cancelled_handlers_write_lands_and_the_next_write_builds_on_it() {
    let harness = start_harness().await;

    let mut first = spawn_write(&harness, serde_json::json!({"a": 1}));
    wait_for_ack_wait(&harness, &mut first).await;
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    harness.fenced.close_window_for_test(harness.partition, 0);
    wait_until("the cancelled write must land in the cache", || {
        harness
            .cache
            .peek(harness.partition, &harness.key)
            .is_some_and(|person| person.version == 2)
    })
    .await;

    let mut second = spawn_write(&harness, serde_json::json!({"b": 2}));
    wait_for_ack_wait(&harness, &mut second).await;
    harness.fenced.close_window_for_test(harness.partition, 0);
    let second = second
        .await
        .expect("the write task must not panic")
        .expect("the write after the cancelled one succeeds")
        .into_inner()
        .person
        .expect("the response carries the person");
    let properties: serde_json::Value = serde_json::from_slice(&second.properties).unwrap();
    assert_eq!(
        second.version, 3,
        "versions advance past the cancelled write's"
    );
    assert_eq!(
        properties["a"], 1,
        "the cancelled write's property must be in the next document"
    );
    assert_eq!(properties["b"], 2);
}
