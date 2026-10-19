//! Integration tests for the Kafka warming pipeline. Drives the real
//! warm against a mock Kafka cluster, producing
//! known Person messages and asserting the resulting cache state matches.

mod common;

use std::sync::Arc;
use std::time::Duration;

use common::{create_mock_kafka, test_warming_config, CHANGELOG_TOPIC, NUM_PARTITIONS};
use personhog_coordination::changelog::WarmSource;
use personhog_leader::cache::{CacheLookup, DirtyIndex, PartitionedCache, PersonCacheKey};
use personhog_leader::warming::{warm_from_sources, WarmClientPools, WarmingConfig};
use personhog_proto::personhog::types::v1::Person;
use prost::Message as ProtoMessage;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, CommitMode, Consumer};
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer, FutureRecord};
use rdkafka::types::{RDKafkaApiKey, RDKafkaRespErr};
use rdkafka::{Offset, TopicPartitionList};

/// Build a Person proto with deterministic fields — enough that the
/// warming pipeline's decode + JSON-parse + cache-write round-trip
/// covers every code path.
fn make_person(team_id: i64, person_id: i64) -> Person {
    Person {
        id: person_id,
        uuid: format!("00000000-0000-0000-0000-{person_id:012}"),
        team_id,
        properties: serde_json::to_vec(&serde_json::json!({
            "email": format!("p{person_id}@example.com"),
        }))
        .unwrap(),
        properties_last_updated_at: Vec::new(),
        properties_last_operation: Vec::new(),
        created_at: 1700000000,
        version: 1,
        is_identified: false,
        is_user_id: None,
        last_seen_at: None,
        is_deleted: false,
    }
}

/// Produce a Person to a specific partition. Uses the mock cluster's
/// producer; the warming consumer must point at the same broker.
async fn produce_person_to_partition(
    producer: &FutureProducer<common_kafka::kafka_producer::KafkaContext>,
    partition: i32,
    person: &Person,
) {
    let key = format!("{}:{}", person.team_id, person.id);
    let payload = person.encode_to_vec();
    let record = FutureRecord::to(CHANGELOG_TOPIC)
        .key(&key)
        .partition(partition)
        .payload(&payload);
    producer
        .send(record, Duration::from_secs(5))
        .await
        .expect("produce should succeed");
}

/// Produce a malformed message (raw bytes that don't decode as a Person
/// proto) to exercise the fail-loud decode branch.
async fn produce_garbage_to_partition(
    producer: &FutureProducer<common_kafka::kafka_producer::KafkaContext>,
    partition: i32,
) {
    let key = "garbage";
    // Payload that isn't valid Person proto: a long byte string of 0xFFs
    // — prost's varint decoder rejects these immediately.
    let payload = vec![0xFFu8; 32];
    let record = FutureRecord::to(CHANGELOG_TOPIC)
        .key(key)
        .partition(partition)
        .payload(&payload);
    producer
        .send(record, Duration::from_secs(5))
        .await
        .expect("produce should succeed");
}

fn warming_config_for(
    pod_name: &str,
    cluster: &MockCluster<'static, DefaultProducerContext>,
) -> (WarmingConfig, WarmClientPools) {
    let cfg = test_warming_config(pod_name, &cluster.bootstrap_servers());
    let pools = WarmClientPools::new(&cfg.kafka, pod_name, &cfg.writer_consumer_group);
    (cfg, pools)
}

/// A warm from the live topic alone.
async fn warm_live(
    cfg: &WarmingConfig,
    pools: &WarmClientPools,
    cache: &PartitionedCache,
    dirty_index: &DirtyIndex,
    partition: u32,
) -> personhog_coordination::error::Result<()> {
    let sources = [WarmSource::live(CHANGELOG_TOPIC, partition)];
    warm_from_sources(cfg, pools, cache, dirty_index, partition, &sources).await
}

/// Happy path: produce N messages to a partition, warm, assert every
/// record landed in the cache. Also asserts FIFO ordering by relying on
/// the cache's `put` semantics — later puts overwrite earlier ones, so
/// distinct `person_id`s produce distinct entries that we can count.
#[tokio::test]
async fn warming_populates_cache_from_kafka() {
    let (cluster, producer) = create_mock_kafka().await;

    // Produce 5 records to partition 0.
    for person_id in 1..=5 {
        let person = make_person(1, person_id);
        produce_person_to_partition(&producer, 0, &person).await;
    }

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-0", &cluster);

    warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), 0)
        .await
        .expect("warming should succeed");

    assert!(cache.has_partition(0), "partition 0 must be marked owned");
    for person_id in 1..=5 {
        let key = PersonCacheKey {
            team_id: 1,
            person_id,
        };
        match cache.get(0, &key) {
            CacheLookup::Found(entry) => {
                assert_eq!(entry.id, person_id);
                assert_eq!(entry.team_id, 1);
            }
            other => panic!(
                "expected Found for person_id={person_id}, got {:?}",
                std::mem::discriminant(&other)
            ),
        }
    }
}

/// Empty partition: no messages produced. Warming must mark the partition
/// owned (so future routes find a cache entry) but with no records.
#[tokio::test]
async fn warming_handles_empty_partition() {
    let (cluster, _producer) = create_mock_kafka().await;

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-empty", &cluster);

    warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), 0)
        .await
        .expect("warming an empty partition should succeed");

    assert!(
        cache.has_partition(0),
        "empty warming must still mark the partition owned"
    );
    let key = PersonCacheKey {
        team_id: 1,
        person_id: 99,
    };
    assert!(
        matches!(cache.get(0, &key), CacheLookup::PersonNotFound),
        "no records were produced, so cache must be empty"
    );

    // The empty path must return its consumer to the pool, not drop it —
    // a second empty warm reuses the same client instead of creating one.
    let created_after_first = pools.warming.created_count();
    cache.drop_partition(0);
    warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), 0)
        .await
        .expect("second empty warm should succeed");
    assert_eq!(
        pools.warming.created_count(),
        created_after_first,
        "an empty warm must give its pooled consumer back"
    );
}

/// Partition isolation: warming partition 0 must not populate cache
/// entries for any other partition. Proves the consumer's seek + assign
/// is correctly scoped.
#[tokio::test]
async fn warming_only_populates_target_partition() {
    let (cluster, producer) = create_mock_kafka().await;

    // Produce one record to partition 0 and one to partition 1.
    produce_person_to_partition(&producer, 0, &make_person(1, 100)).await;
    produce_person_to_partition(&producer, 1, &make_person(1, 200)).await;

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-iso", &cluster);

    warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), 0)
        .await
        .expect("warming partition 0 should succeed");

    assert!(cache.has_partition(0), "partition 0 was warmed");
    assert!(
        !cache.has_partition(1),
        "partition 1 must not be touched when warming partition 0"
    );
    let p0_key = PersonCacheKey {
        team_id: 1,
        person_id: 100,
    };
    assert!(
        matches!(cache.get(0, &p0_key), CacheLookup::Found(_)),
        "partition 0's record must be in cache"
    );
}

/// Decode failure: a single unparseable message in the warming range
/// must fail the entire warm with no observable cache mutation. The
/// atomic-commit invariant means a partial cache (only the records
/// before the bad one) would silently mask PG fallback reads.
#[tokio::test]
async fn warming_fails_loudly_on_decode_error_and_leaves_cache_clean() {
    let (cluster, producer) = create_mock_kafka().await;

    // Produce a valid record, then a garbage one. Warming should buffer
    // the valid record locally, hit the garbage on the next iteration,
    // and abort before flushing anything to the cache.
    produce_person_to_partition(&producer, 0, &make_person(1, 1)).await;
    produce_garbage_to_partition(&producer, 0).await;

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-decode", &cluster);

    let result = warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), 0).await;
    assert!(
        result.is_err(),
        "a malformed message must fail the entire warm"
    );
    assert!(
        !cache.has_partition(0),
        "atomic commit: cache must not have been touched on decode failure"
    );
}

/// All partitions exercised in sequence: verifies the warming pipeline
/// is reusable across the full partition set. Catches regressions where
/// per-partition consumer setup leaks state across calls.
#[tokio::test]
async fn warming_works_across_all_partitions() {
    let (cluster, producer) = create_mock_kafka().await;

    // Produce one record to each partition with a partition-specific
    // person_id so we can verify the right record landed in each cache
    // slot.
    for partition in 0..NUM_PARTITIONS {
        let person = make_person(1, (partition as i64 + 1) * 100);
        produce_person_to_partition(&producer, partition as i32, &person).await;
    }

    let cache = Arc::new(PartitionedCache::new(1 << 20));
    let (cfg, pools) = warming_config_for("warmer-all", &cluster);

    for partition in 0..NUM_PARTITIONS {
        warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), partition)
            .await
            .unwrap_or_else(|e| panic!("warming partition {partition} failed: {e}"));
    }

    for partition in 0..NUM_PARTITIONS {
        assert!(cache.has_partition(partition));
        let key = PersonCacheKey {
            team_id: 1,
            person_id: (partition as i64 + 1) * 100,
        };
        assert!(
            matches!(cache.get(partition, &key), CacheLookup::Found(_)),
            "partition {partition} should have its dedicated record"
        );
    }
}

/// Commit a specific offset for the writer's consumer group on a given
/// partition. Mirrors what the writer pod would do after persisting
/// records up through that offset to PG. The warming pipeline reads
/// this committed offset to bound the range it needs to repopulate.
fn commit_writer_offset_at(
    cluster: &MockCluster<'static, DefaultProducerContext>,
    writer_group: &str,
    partition: i32,
    offset: i64,
) {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", cluster.bootstrap_servers())
        .set("group.id", writer_group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("failed to create writer-group consumer");

    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(CHANGELOG_TOPIC, partition, Offset::Offset(offset))
        .expect("tpl add_partition_offset");
    consumer
        .commit(&tpl, CommitMode::Sync)
        .expect("writer-group commit");
}

/// Warming must consult the writer's committed offset and skip records
/// the writer has already durably persisted to PG. Produce 8 records;
/// commit the writer's offset at 5 (meaning records 0..4 are durable,
/// records 5..7 still need to be in cache), and assert only records with
/// offsets ≥ 5 land in the cache, each marked dirty.
#[tokio::test]
async fn warming_starts_from_writer_committed_offset() {
    let (cluster, producer) = create_mock_kafka().await;

    // Produce 8 records to partition 0. person_id matches offset for
    // easy assertion (offset N → person_id N+1).
    for i in 0..8 {
        let person = make_person(1, i + 1);
        produce_person_to_partition(&producer, 0, &person).await;
    }

    // Writer "committed" through offset 5 — meaning records at offsets
    // 0..4 are durable in PG, the records at 5..7 are still in flight
    // and must be warmed.
    commit_writer_offset_at(&cluster, "personhog-writer", 0, 5);

    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(1_000_000);
    let (cfg, pools) = warming_config_for("warmer-committed", &cluster);

    warm_live(&cfg, &pools, &cache, &dirty_index, 0)
        .await
        .expect("warming should succeed");
    assert_eq!(dirty_index.len(), 3);

    // Records 5..7 (person_ids 6, 7, 8) must be in cache.
    for person_id in 6..=8 {
        let key = PersonCacheKey {
            team_id: 1,
            person_id,
        };
        assert!(
            matches!(cache.get(0, &key), CacheLookup::Found(_)),
            "record after committed offset (person_id={person_id}) must be warmed"
        );
        let mark = dirty_index
            .get(&key)
            .expect("an unapplied record is marked");
        assert_eq!(mark.offset, person_id - 1);
    }

    // Records 0..4 (person_ids 1..5) must NOT be in cache — they're
    // durable in PG and warming correctly skipped them.
    for person_id in 1..=5 {
        let key = PersonCacheKey {
            team_id: 1,
            person_id,
        };
        assert!(
            matches!(cache.get(0, &key), CacheLookup::PersonNotFound),
            "record before committed offset (person_id={person_id}) must NOT be warmed"
        );
    }
}

/// Atomic-commit invariant: a Person whose proto decodes successfully
/// but whose `properties` field contains invalid JSON must fail the
/// entire warm. The proto-decode branch and the JSON-decode branch are
/// distinct error paths in the consume loop; the garbage-bytes test
/// only exercises the proto branch.
#[tokio::test]
async fn warming_fails_loudly_on_properties_json_error() {
    let (cluster, producer) = create_mock_kafka().await;

    // Valid record first so warming actually enters the consume loop
    // and buffers something before hitting the failure.
    produce_person_to_partition(&producer, 0, &make_person(1, 1)).await;

    // Person with invalid JSON in properties — proto decodes, but
    // `serde_json::from_slice` on `properties` fails.
    let bad = Person {
        id: 2,
        uuid: "00000000-0000-0000-0000-000000000002".to_string(),
        team_id: 1,
        properties: vec![0xFFu8; 16], // not valid JSON
        properties_last_updated_at: Vec::new(),
        properties_last_operation: Vec::new(),
        created_at: 1700000000,
        version: 1,
        is_identified: false,
        is_user_id: None,
        last_seen_at: None,
        is_deleted: false,
    };
    produce_person_to_partition(&producer, 0, &bad).await;

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-bad-props", &cluster);

    let dirty_index = DirtyIndex::new(1_000_000);
    let result = warm_live(&cfg, &pools, &cache, &dirty_index, 0).await;
    assert!(
        result.is_err(),
        "invalid JSON in properties must fail the entire warm"
    );
    let msg = result.unwrap_err().to_string();
    assert!(
        msg.contains("properties decode failed"),
        "error must point at the properties JSON branch, not proto decode: {msg}"
    );
    assert!(
        !cache.has_partition(0),
        "atomic commit: cache must not have been touched on JSON failure"
    );
    // Marks are written per record as the range streams; a failed warm
    // must clear them — orphaned marks for a partition this pod never
    // serves would pin memory and mislead a later owner's bookkeeping.
    assert_eq!(
        dirty_index.get(&PersonCacheKey {
            team_id: 1,
            person_id: 1,
        }),
        None,
        "a failed warm must leave no dirty marks behind"
    );
}

/// Last-write-wins: the changelog can contain multiple updates for the
/// same `person_id` (each update produces a new record). After warming,
/// the cache must reflect the *latest* update — proven by checking the
/// version field, which the writer increments per update.
#[tokio::test]
async fn warming_preserves_last_write_for_same_key() {
    let (cluster, producer) = create_mock_kafka().await;

    // Three sequential updates for the same person, each with an
    // incrementing version. Producing in order to the same partition
    // preserves Kafka's per-partition ordering.
    for version in 1..=3 {
        let mut person = make_person(1, 42);
        person.version = version;
        // Tag the email with the version so we can also verify the
        // properties payload matches the latest write.
        person.properties = serde_json::to_vec(&serde_json::json!({
            "email": format!("v{version}@example.com"),
        }))
        .unwrap();
        produce_person_to_partition(&producer, 0, &person).await;
    }

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-lww", &cluster);

    let dirty_index = DirtyIndex::new(1_000_000);
    warm_live(&cfg, &pools, &cache, &dirty_index, 0)
        .await
        .expect("warming should succeed");

    let key = PersonCacheKey {
        team_id: 1,
        person_id: 42,
    };
    match cache.get(0, &key) {
        CacheLookup::Found(entry) => {
            assert_eq!(
                entry.version, 3,
                "cache must reflect the latest update's version"
            );
            assert_eq!(
                entry.parse_properties().unwrap()["email"],
                "v3@example.com",
                "cache must reflect the latest update's properties"
            );
        }
        other => panic!("expected Found, got {:?}", std::mem::discriminant(&other)),
    }
    // The dirty mark must carry the latest version too: the buffer keys
    // by person, and a wrong-version-wins regression would surface here
    // as a stale mark even while the cache looks right.
    let mark = dirty_index.get(&key).expect("person must be marked dirty");
    assert_eq!(mark.version, 3, "dirty mark must carry the latest version");
}

/// Applied records, deaths included, leave no residue in the warmed cache;
/// an unapplied death record warms in, marked.
#[tokio::test]
async fn warming_skips_applied_death_records() {
    let (cluster, producer) = create_mock_kafka().await;

    // Key 1: live then death. Key 2: live only. Key 3: live, death,
    // then a revival record.
    produce_person_to_partition(&producer, 0, &make_person(1, 1)).await;
    let mut dead = make_person(1, 1);
    dead.is_deleted = true;
    dead.version = 2;
    produce_person_to_partition(&producer, 0, &dead).await;
    produce_person_to_partition(&producer, 0, &make_person(1, 2)).await;
    produce_person_to_partition(&producer, 0, &make_person(1, 3)).await;
    let mut dead3 = make_person(1, 3);
    dead3.is_deleted = true;
    dead3.version = 2;
    produce_person_to_partition(&producer, 0, &dead3).await;
    let mut revived3 = make_person(1, 3);
    revived3.version = 3;
    produce_person_to_partition(&producer, 0, &revived3).await;
    // Key 4: an unapplied death record (at the committed offset).
    let mut dead4 = make_person(1, 4);
    dead4.is_deleted = true;
    dead4.version = 2;
    produce_person_to_partition(&producer, 0, &dead4).await;

    // Records at offsets 0..6 are applied; key 4's death record is not.
    commit_writer_offset_at(&cluster, "personhog-writer", 0, 6);

    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(1_000_000);
    let (cfg, pools) = warming_config_for("warmer-skip-dead", &cluster);

    warm_live(&cfg, &pools, &cache, &dirty_index, 0)
        .await
        .expect("warming should succeed");

    let dead_key = PersonCacheKey {
        team_id: 1,
        person_id: 1,
    };
    let live_key = PersonCacheKey {
        team_id: 1,
        person_id: 2,
    };
    let revived_key = PersonCacheKey {
        team_id: 1,
        person_id: 3,
    };
    for key in [&dead_key, &live_key, &revived_key] {
        assert!(
            matches!(cache.get(0, key), CacheLookup::PersonNotFound),
            "an applied record must leave no residue"
        );
    }
    assert!(dirty_index.get(&dead_key).is_none());
    assert!(dirty_index.get(&live_key).is_none());
    assert!(dirty_index.get(&revived_key).is_none());
    // An unapplied death record warms in and is marked: the writer has
    // not applied it, so PG still holds the living person.
    let unapplied_dead_key = PersonCacheKey {
        team_id: 1,
        person_id: 4,
    };
    match cache.get(0, &unapplied_dead_key) {
        CacheLookup::Found(entry) => assert!(entry.is_deleted),
        other => panic!(
            "an unapplied death record must warm in, got {:?}",
            std::mem::discriminant(&other)
        ),
    }
    let mark = dirty_index
        .get(&unapplied_dead_key)
        .expect("an unapplied death record must be marked");
    assert!(mark.is_deleted);
}

/// Warming must seed the dirty index for every record the writer has not
/// applied — with no committed offset at all, that is every record — so a
/// post-warm eviction still recovers from the changelog instead of
/// trusting a PG row the writer never wrote.
#[tokio::test]
async fn warming_seeds_dirty_index_when_writer_has_no_commits() {
    let (cluster, producer) = create_mock_kafka().await;

    for person_id in 1..=3 {
        let person = make_person(1, person_id);
        produce_person_to_partition(&producer, 0, &person).await;
    }

    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(1_000_000);
    let (cfg, pools) = warming_config_for("warmer-seed", &cluster);

    warm_live(&cfg, &pools, &cache, &dirty_index, 0)
        .await
        .expect("warming should succeed");

    assert_eq!(
        dirty_index.len(),
        3,
        "every warmed record must be marked dirty when the writer has no commits"
    );
    // Marks carry the record offsets: 3 records at offsets 0..=2.
    let stream = personhog_leader::cache::Stream {
        topic: std::sync::Arc::from(CHANGELOG_TOPIC),
        partition: 0,
    };
    assert_eq!(dirty_index.max_offset(0, &stream), Some(2));
}

/// Sequential warms reuse pooled clients instead of rebuilding them:
/// client construction (connection, metadata, coordinator discovery) is
/// the dominant cost of a warm, so the pool's whole purpose is that the
/// created-count stays at pool size while operations keep flowing.
#[tokio::test]
async fn sequential_warms_reuse_pooled_clients() {
    let (cluster, producer) = create_mock_kafka().await;

    for person_id in 1..=3 {
        let person = make_person(1, person_id);
        produce_person_to_partition(&producer, 0, &person).await;
        produce_person_to_partition(&producer, 1, &person).await;
    }

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-pool", &cluster);

    for partition in [0u32, 1, 0, 1] {
        // A re-warm follows a release in production; drop to match.
        cache.drop_partition(partition);
        warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), partition)
            .await
            .expect("warming should succeed");
    }

    assert_eq!(
        pools.warming.created_count(),
        1,
        "four sequential warms must reuse one pooled warming consumer"
    );
    assert_eq!(
        pools.offsets.created_count(),
        1,
        "four offset queries must reuse one pooled offsets client"
    );
}

/// Prewarming must fill every slot with a distinct connected client —
/// returning clients to the pool mid-loop would hand the same one back
/// to each iteration, leaving all but one slot to be built cold on the
/// handoff path.
#[tokio::test]
async fn warm_up_fills_every_slot() {
    let (cluster, _producer) = create_mock_kafka().await;
    let (_cfg, pools) = warming_config_for("warmer-prewarm", &cluster);

    pools.warming.warm_up(3).await;

    assert_eq!(
        pools.warming.created_count(),
        3,
        "prewarming three slots must create three distinct clients"
    );
}

/// A broker blip inside the consume loop must not fail the warm.
/// librdkafka reports a still-reconnecting client through the same
/// channel as a dead one and marks the difference itself; treating the
/// non-fatal variant as a failed read aborted the warm, and because
/// event-triggered convergence is fatal to the run, one partition's blip
/// tore down every partition that pod was converging.
#[tokio::test]
async fn warming_tolerates_a_transient_consumer_error() {
    let (cluster, producer) = create_mock_kafka().await;

    for person_id in 1..=3 {
        let person = make_person(1, person_id);
        produce_person_to_partition(&producer, 0, &person).await;
    }

    // Fail the first attempt's fetches at the transport layer, the shape
    // an MSK coordinator reload produced in dev.
    cluster.request_errors(
        RDKafkaApiKey::Fetch,
        &[
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__TRANSPORT,
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__TRANSPORT,
        ],
    );

    let cache = PartitionedCache::new(1 << 20);
    let (cfg, pools) = warming_config_for("warmer-transient", &cluster);

    warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), 0)
        .await
        .expect("a non-fatal consumer error must not fail the warm");

    assert!(cache.has_partition(0), "partition 0 must be marked owned");
    for person_id in 1..=3 {
        let key = PersonCacheKey {
            team_id: 1,
            person_id,
        };
        assert!(
            matches!(cache.get(0, &key), CacheLookup::Found(_)),
            "person_id={person_id} must be warmed after the blip"
        );
    }
}

/// A persistent non-connection consumer error must still end the warm
/// inside the stall budget with nothing installed. Under the ride-out
/// pattern the cause surfaces via the counter and warn logs rather than
/// the error string, but the warm must never hang past its budget or
/// publish a partial cache.
#[tokio::test]
async fn warming_still_fails_on_a_persistent_stop_class_error() {
    let (cluster, producer) = create_mock_kafka().await;

    for person_id in 1..=3 {
        let person = make_person(1, person_id);
        produce_person_to_partition(&producer, 0, &person).await;
    }

    // An auth failure stops the partition's fetch rather than resolving
    // by reconnection; the warm rides the error events, goes quiet, and
    // the stall budget must end it.
    cluster.request_errors(
        RDKafkaApiKey::Fetch,
        &[RDKafkaRespErr::RD_KAFKA_RESP_ERR_TOPIC_AUTHORIZATION_FAILED; 64],
    );

    let cache = PartitionedCache::new(1 << 20);
    let (mut cfg, pools) = warming_config_for("warmer-stop-class", &cluster);
    cfg.recv_timeout = Duration::from_secs(2);

    let result = warm_live(&cfg, &pools, &cache, &DirtyIndex::new(1_000_000), 0).await;
    let err = result.expect_err("a persistent stop-class error must end the warm");
    // The stall path, not an immediate abort: riding the error out means
    // the warm ends only when the budget expires with no records read.
    assert!(
        err.to_string().contains("consumed 0 msgs"),
        "expected the stall budget to end the warm, got: {err}"
    );
    assert!(
        !cache.has_partition(0),
        "a failed warm must install nothing"
    );
}

/// The warm's memory contract: the build evicts under the partition's
/// byte budget, so a range larger than the budget still warms — with a
/// partial cache — while EVERY unapplied person gets a dirty mark. The
/// marks are what make the evictions safe: a miss on a marked person
/// recovers from the changelog instead of trusting a stale PG row, so
/// full mark coverage under eviction is the invariant that lets the
/// warm survive a backlog-sized range without holding it in memory.
#[tokio::test]
async fn warming_a_range_larger_than_the_budget_marks_every_person() {
    let (cluster, producer) = create_mock_kafka().await;

    // Forty persons with ~4KB of properties each — far past the tiny
    // budget below — with no writer committed offset, so every record
    // counts as unapplied.
    let persons = 40i64;
    for person_id in 1..=persons {
        let mut person = make_person(1, person_id);
        person.properties = serde_json::to_vec(&serde_json::json!({
            "email": format!("p{person_id}@example.com"),
            "padding": "x".repeat(4096),
        }))
        .unwrap();
        produce_person_to_partition(&producer, 0, &person).await;
    }

    let budget_bytes = 16 * 1024;
    let cache = PartitionedCache::new(budget_bytes);
    let (cfg, pools) = warming_config_for("warmer-bounded", &cluster);
    let dirty_index = DirtyIndex::new(1_000_000);

    warm_live(&cfg, &pools, &cache, &dirty_index, 0)
        .await
        .expect("a range larger than the budget must still warm");

    assert!(cache.has_partition(0), "the partition must publish");
    let mut resident = 0;
    for person_id in 1..=persons {
        let key = PersonCacheKey {
            team_id: 1,
            person_id,
        };
        if matches!(cache.get(0, &key), CacheLookup::Found(_)) {
            resident += 1;
        }
        assert!(
            dirty_index.get(&key).is_some(),
            "person {person_id} must be marked dirty even if evicted"
        );
    }
    assert!(
        resident < persons,
        "the budget must have evicted something ({resident}/{persons} resident) — \
         if everything fit, this test no longer exercises eviction"
    );
}

/// The tick settles a published partition's applied death mark, while a
/// warming partition keeps its marks until publish.
#[tokio::test]
async fn the_prune_tick_settles_published_partitions_only() {
    let (cluster, _producer) = create_mock_kafka().await;
    let (_cfg, pools) = warming_config_for("prune-tick", &cluster);

    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(1_000_000);
    let locks = dashmap::DashMap::new();

    let death_doc = |person_id: i64| {
        let mut person = make_person(1, person_id);
        person.is_deleted = true;
        person.version = 2;
        personhog_leader::cache::CachedPerson::try_from(person).unwrap()
    };
    let death_mark = |partition: u32| personhog_leader::cache::DirtyMark {
        version: 2,
        offset: 0,
        partition,
        stream: personhog_leader::cache::Stream {
            topic: std::sync::Arc::from("personhog_updates"),
            partition,
        },
        is_deleted: true,
    };
    let published_key = PersonCacheKey {
        team_id: 1,
        person_id: 1,
    };
    let warming_key = PersonCacheKey {
        team_id: 1,
        person_id: 2,
    };

    cache.create_partition(0);
    cache.put(0, published_key.clone(), death_doc(1));
    dirty_index.mark(published_key.clone(), death_mark(0));

    cache.begin_warm_partition(1);
    cache.warm_put(1, warming_key.clone(), death_doc(2));
    dirty_index.mark(warming_key.clone(), death_mark(1));

    commit_writer_offset_at(&cluster, "personhog-writer", 0, 1);
    commit_writer_offset_at(&cluster, "personhog-writer", 1, 1);

    personhog_leader::settle::prune_and_settle_tick(
        &dirty_index,
        &cache,
        &locks,
        &pools.offsets,
        Duration::from_secs(5),
        |_| false,
    )
    .await;

    assert!(dirty_index.get(&published_key).is_none());
    assert!(
        cache.peek(0, &published_key).is_none(),
        "the published partition's death document settles"
    );
    assert!(
        dirty_index.get(&warming_key).is_some(),
        "a warming partition keeps its marks until publish"
    );

    // After publish, the next tick settles the waiting mark.
    cache.publish_warmed_partition(1);
    personhog_leader::settle::prune_and_settle_tick(
        &dirty_index,
        &cache,
        &locks,
        &pools.offsets,
        Duration::from_secs(5),
        |_| false,
    )
    .await;
    assert!(dirty_index.get(&warming_key).is_none());
    assert!(cache.peek(1, &warming_key).is_none());
}

/// A retired stream's marks settle without the writer's offsets, death
/// documents included; a live stream's marks keep waiting for the writer.
#[tokio::test]
async fn the_prune_tick_settles_a_retired_streams_marks_without_offsets() {
    let (cluster, _producer) = create_mock_kafka().await;
    let (_cfg, pools) = warming_config_for("prune-tick-retired", &cluster);
    const RETIRED_TOPIC: &str = "personhog_updates_retired";

    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(1_000_000);
    let locks = dashmap::DashMap::new();
    cache.create_partition(0);

    let death_doc = |person_id: i64| {
        let mut person = make_person(1, person_id);
        person.is_deleted = true;
        person.version = 2;
        personhog_leader::cache::CachedPerson::try_from(person).unwrap()
    };
    let mark_on = |topic: &str, partition: u32| personhog_leader::cache::DirtyMark {
        version: 2,
        offset: 0,
        partition: 0,
        stream: personhog_leader::cache::Stream {
            topic: std::sync::Arc::from(topic),
            partition,
        },
        is_deleted: true,
    };
    let retired_key = PersonCacheKey {
        team_id: 1,
        person_id: 1,
    };
    let live_key = PersonCacheKey {
        team_id: 1,
        person_id: 2,
    };
    let moved_key = PersonCacheKey {
        team_id: 1,
        person_id: 3,
    };
    cache.put(0, retired_key.clone(), death_doc(1));
    dirty_index.mark(retired_key.clone(), mark_on(RETIRED_TOPIC, 3));
    cache.put(0, live_key.clone(), death_doc(2));
    dirty_index.mark(live_key.clone(), mark_on(CHANGELOG_TOPIC, 0));
    // Queued under the retired stream, but its live mark moved on.
    dirty_index.mark(moved_key.clone(), mark_on(RETIRED_TOPIC, 3));
    dirty_index.mark(moved_key.clone(), mark_on(CHANGELOG_TOPIC, 0));

    // The writer committed on neither topic.
    tokio::time::timeout(
        Duration::from_secs(30),
        personhog_leader::settle::prune_and_settle_tick(
            &dirty_index,
            &cache,
            &locks,
            &pools.offsets,
            Duration::from_secs(5),
            |topic| topic == RETIRED_TOPIC,
        ),
    )
    .await
    .expect("the tick must return once the retired stream is exhausted");

    assert!(dirty_index.get(&retired_key).is_none());
    assert_eq!(
        dirty_index
            .get(&moved_key)
            .map(|m| m.stream.topic.to_string()),
        Some(CHANGELOG_TOPIC.to_string()),
        "a key that moved to the live stream keeps waiting there"
    );
    assert!(
        cache.peek(0, &retired_key).is_none(),
        "the retired stream's death document settles"
    );
    assert!(
        dirty_index.get(&live_key).is_some(),
        "a live stream waits for the writer's offset"
    );
}

/// One tick drains a death backlog larger than a prune chunk: the chunk
/// loop must run to exhaustion, not stop after the first slice.
#[tokio::test]
async fn the_prune_tick_drains_a_multi_chunk_death_backlog() {
    let (cluster, _producer) = create_mock_kafka().await;
    let (_cfg, pools) = warming_config_for("prune-tick-backlog", &cluster);

    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(usize::MAX);
    let locks = dashmap::DashMap::new();
    cache.create_partition(0);

    let total = personhog_leader::cache::PRUNE_CHUNK as i64 + 1;
    for offset in 0..total {
        let mut person = make_person(1, offset);
        person.is_deleted = true;
        person.version = 2;
        let key = PersonCacheKey {
            team_id: 1,
            person_id: offset,
        };
        cache.put(
            0,
            key.clone(),
            personhog_leader::cache::CachedPerson::try_from(person).unwrap(),
        );
        dirty_index.mark(
            key,
            personhog_leader::cache::DirtyMark {
                version: 2,
                offset,
                partition: 0,
                stream: personhog_leader::cache::Stream {
                    topic: std::sync::Arc::from("personhog_updates"),
                    partition: 0,
                },
                is_deleted: true,
            },
        );
    }
    commit_writer_offset_at(&cluster, "personhog-writer", 0, total);

    personhog_leader::settle::prune_and_settle_tick(
        &dirty_index,
        &cache,
        &locks,
        &pools.offsets,
        Duration::from_secs(5),
        |_| false,
    )
    .await;

    assert!(dirty_index.is_empty(), "every mark settles in one tick");
    for person_id in [0, total / 2, total - 1] {
        let key = PersonCacheKey {
            team_id: 1,
            person_id,
        };
        assert!(
            cache.peek(0, &key).is_none(),
            "death document for person {person_id} must be dropped"
        );
    }
}

/// Produce a Person to a partition of any topic on the local broker.
async fn produce_to(
    producer: &FutureProducer<common_kafka::kafka_producer::KafkaContext>,
    topic: &str,
    partition: i32,
    person: &Person,
) {
    let key = format!("{}:{}", person.team_id, person.id);
    let payload = person.encode_to_vec();
    let record = FutureRecord::to(topic)
        .key(&key)
        .partition(partition)
        .payload(&payload);
    producer
        .send(record, Duration::from_secs(5))
        .await
        .expect("produce should succeed");
}

fn commit_group_offset(bootstrap: &str, group: &str, topic: &str, partition: i32, offset: i64) {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .create()
        .expect("failed to create writer-group consumer");
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(topic, partition, Offset::Offset(offset))
        .expect("tpl add_partition_offset");
    consumer.assign(&tpl).expect("assign");
    consumer
        .commit(&tpl, CommitMode::Sync)
        .expect("writer-group commit");
}

/// After a 2 → 4 flip, new partition 1 inherits half of old partition 1's tail.
#[tokio::test]
async fn a_restart_warms_the_old_generations_congruent_tail_for_its_keys() {
    use personhog_common::partitioning::partition_for_person;
    use personhog_coordination::changelog::KeyFilter;
    use personhog_leader::cache::Stream;

    let (new_topic, producer) = common::create_test_kafka_with_partitions(4).await;
    let old_topic = common::owned_broker_topic(2).await;
    let bootstrap = new_topic.bootstrap_servers();

    // Keys whose home under 4 partitions is 1 or 3 all live in old partition 1.
    let mut inherited = Vec::new();
    let mut strangers = Vec::new();
    for person_id in 1..=200 {
        match partition_for_person(1, person_id, 4) {
            1 => inherited.push(person_id),
            3 => strangers.push(person_id),
            _ => {}
        }
        if inherited.len() >= 5 && strangers.len() >= 5 {
            break;
        }
    }
    for person_id in inherited.iter().chain(&strangers) {
        assert_eq!(partition_for_person(1, *person_id, 2), 1);
        produce_to(&producer, &old_topic.topic, 1, &make_person(1, *person_id)).await;
    }
    // A group of this test's own: the shared broker may host live writers.
    let writer_group = format!("restart-writer-{}", uuid::Uuid::now_v7());
    // One record already applied by the writer: below its commit, no mark.
    commit_group_offset(&bootstrap, &writer_group, &old_topic.topic, 1, 1);

    let mut cfg = common::test_warming_config("restarter", &bootstrap);
    cfg.writer_consumer_group = writer_group.clone();
    let pools = WarmClientPools::new(&cfg.kafka, "restarter", &cfg.writer_consumer_group);
    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(1_000_000);
    let sources = [
        WarmSource {
            topic: Arc::from(old_topic.topic.as_str()),
            partition: 1,
            keep: Some(KeyFilter {
                modulus: 4,
                target: 1,
            }),
        },
        WarmSource::live(&new_topic.topic, 1),
    ];
    warm_from_sources(&cfg, &pools, &cache, &dirty_index, 1, &sources)
        .await
        .expect("warm from the old tail");

    let old_stream = Stream {
        topic: Arc::from(old_topic.topic.as_str()),
        partition: 1,
    };
    // The first record is below the writer's commit: applied, no mark.
    let applied = PersonCacheKey {
        team_id: 1,
        person_id: inherited[0],
    };
    assert!(dirty_index.get(&applied).is_none());
    for person_id in &inherited[1..] {
        let key = PersonCacheKey {
            team_id: 1,
            person_id: *person_id,
        };
        assert!(
            matches!(cache.get(1, &key), CacheLookup::Found(_)),
            "inherited person {person_id} must be warm"
        );
        assert!(
            dirty_index.get(&key).is_some(),
            "person {person_id} must be marked"
        );
    }
    for person_id in &strangers {
        let key = PersonCacheKey {
            team_id: 1,
            person_id: *person_id,
        };
        assert!(
            matches!(cache.get(1, &key), CacheLookup::PersonNotFound),
            "person {person_id} belongs to partition 3, not 1"
        );
    }
    let marked: Vec<_> = inherited
        .iter()
        .filter_map(|id| {
            dirty_index.get(&PersonCacheKey {
                team_id: 1,
                person_id: *id,
            })
        })
        .collect();
    assert_eq!(marked.len(), inherited.len() - 1);
    assert!(marked
        .iter()
        .all(|m| m.stream == old_stream && m.partition == 1));
    assert_eq!(
        dirty_index.streams_with_marks(),
        vec![(1, old_stream.clone())]
    );

    // The writer finishes the old partition: its marks settle.
    commit_group_offset(&bootstrap, &writer_group, &old_topic.topic, 1, 1_000);
    let locks = dashmap::DashMap::new();
    personhog_leader::settle::prune_and_settle_tick(
        &dirty_index,
        &cache,
        &locks,
        &pools.offsets,
        Duration::from_secs(5),
        |_| false,
    )
    .await;
    assert!(dirty_index.is_empty(), "every old-stream mark settles");
}

/// An applied old-generation record never warms, so it cannot shadow the
/// same person's newer record that the writer already applied on the live
/// topic, which a warm from the live commit does not replay.
#[tokio::test]
async fn an_applied_old_record_never_shadows_a_newer_applied_live_one() {
    use personhog_common::partitioning::partition_for_person;
    use personhog_coordination::changelog::KeyFilter;

    let (new_topic, producer) = common::create_test_kafka_with_partitions(2).await;
    let old_topic = common::owned_broker_topic(2).await;
    let bootstrap = new_topic.bootstrap_servers();

    let person_id = (1..)
        .find(|id| partition_for_person(1, *id, 2) == 0)
        .expect("a person on partition 0");
    produce_to(&producer, &old_topic.topic, 0, &make_person(1, person_id)).await;
    let mut newer = make_person(1, person_id);
    newer.version = 2;
    produce_to(&producer, &new_topic.topic, 0, &newer).await;
    for filler in 1..=3 {
        produce_to(&producer, &new_topic.topic, 0, &make_person(2, filler)).await;
    }
    // The writer drained the old partition and applied the live one's records.
    let writer_group = format!("shadow-writer-{}", uuid::Uuid::now_v7());
    commit_group_offset(&bootstrap, &writer_group, &old_topic.topic, 0, 1);
    commit_group_offset(&bootstrap, &writer_group, &new_topic.topic, 0, 4);

    let mut cfg = common::test_warming_config("shadow-warmer", &bootstrap);
    cfg.writer_consumer_group = writer_group.clone();
    let pools = WarmClientPools::new(&cfg.kafka, "shadow-warmer", &cfg.writer_consumer_group);
    let cache = PartitionedCache::new(1 << 20);
    let dirty_index = DirtyIndex::new(1_000_000);
    let sources = [
        WarmSource {
            topic: Arc::from(old_topic.topic.as_str()),
            partition: 0,
            keep: Some(KeyFilter {
                modulus: 2,
                target: 0,
            }),
        },
        WarmSource::live(&new_topic.topic, 0),
    ];
    warm_from_sources(&cfg, &pools, &cache, &dirty_index, 0, &sources)
        .await
        .expect("warm across generations");

    let key = PersonCacheKey {
        team_id: 1,
        person_id,
    };
    assert!(
        matches!(cache.get(0, &key), CacheLookup::PersonNotFound),
        "a miss must load the newer row from PG"
    );
    assert!(dirty_index.get(&key).is_none());
}
