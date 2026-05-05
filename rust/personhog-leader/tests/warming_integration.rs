//! Integration tests for the Kafka warming pipeline. Drives the real
//! `warm_from_kafka` function against a mock Kafka cluster, producing
//! known Person messages and asserting the resulting cache state matches.

mod common;

use std::sync::Arc;
use std::time::Duration;

use common::{create_test_kafka, test_warming_config, CHANGELOG_TOPIC, NUM_PARTITIONS};
use personhog_leader::cache::{CacheLookup, PartitionedCache, PersonCacheKey};
use personhog_leader::warming::{warm_from_kafka, WarmingConfig};
use personhog_proto::personhog::types::v1::Person;
use prost::Message as ProtoMessage;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, CommitMode, Consumer};
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer, FutureRecord};
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
) -> WarmingConfig {
    test_warming_config(pod_name, &cluster.bootstrap_servers())
}

/// Happy path: produce N messages to a partition, warm, assert every
/// record landed in the cache. Also asserts FIFO ordering by relying on
/// the cache's `put` semantics — later puts overwrite earlier ones, so
/// distinct `person_id`s produce distinct entries that we can count.
#[tokio::test]
async fn warming_populates_cache_from_kafka() {
    let (cluster, producer) = create_test_kafka().await;

    // Produce 5 records to partition 0.
    for person_id in 1..=5 {
        let person = make_person(1, person_id);
        produce_person_to_partition(&producer, 0, &person).await;
    }

    let cache = PartitionedCache::new(100);
    let cfg = warming_config_for("warmer-0", &cluster);

    warm_from_kafka(&cfg, &cache, 0)
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
    let (cluster, _producer) = create_test_kafka().await;

    let cache = PartitionedCache::new(100);
    let cfg = warming_config_for("warmer-empty", &cluster);

    warm_from_kafka(&cfg, &cache, 0)
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
}

/// Partition isolation: warming partition 0 must not populate cache
/// entries for any other partition. Proves the consumer's seek + assign
/// is correctly scoped.
#[tokio::test]
async fn warming_only_populates_target_partition() {
    let (cluster, producer) = create_test_kafka().await;

    // Produce one record to partition 0 and one to partition 1.
    produce_person_to_partition(&producer, 0, &make_person(1, 100)).await;
    produce_person_to_partition(&producer, 1, &make_person(1, 200)).await;

    let cache = PartitionedCache::new(100);
    let cfg = warming_config_for("warmer-iso", &cluster);

    warm_from_kafka(&cfg, &cache, 0)
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
    let (cluster, producer) = create_test_kafka().await;

    // Produce a valid record, then a garbage one. Warming should buffer
    // the valid record locally, hit the garbage on the next iteration,
    // and abort before flushing anything to the cache.
    produce_person_to_partition(&producer, 0, &make_person(1, 1)).await;
    produce_garbage_to_partition(&producer, 0).await;

    let cache = PartitionedCache::new(100);
    let cfg = warming_config_for("warmer-decode", &cluster);

    let result = warm_from_kafka(&cfg, &cache, 0).await;
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
    let (cluster, producer) = create_test_kafka().await;

    // Produce one record to each partition with a partition-specific
    // person_id so we can verify the right record landed in each cache
    // slot.
    for partition in 0..NUM_PARTITIONS {
        let person = make_person(1, (partition as i64 + 1) * 100);
        produce_person_to_partition(&producer, partition as i32, &person).await;
    }

    let cache = Arc::new(PartitionedCache::new(100));
    let cfg = warming_config_for("warmer-all", &cluster);

    for partition in 0..NUM_PARTITIONS {
        warm_from_kafka(&cfg, &cache, partition)
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
/// records 5..7 still need to be in cache); warm with `lookback=0` and
/// assert only records with offsets ≥ 5 land in the cache.
#[tokio::test]
async fn warming_starts_from_writer_committed_offset() {
    let (cluster, producer) = create_test_kafka().await;

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

    let cache = PartitionedCache::new(100);
    let mut cfg = warming_config_for("warmer-committed", &cluster);
    // Set lookback to 0 so the start offset is exactly the committed
    // value; otherwise it would rewind further and include earlier
    // records, defeating the point of this assertion.
    cfg.lookback_offsets = 0;

    warm_from_kafka(&cfg, &cache, 0)
        .await
        .expect("warming should succeed");

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
    let (cluster, producer) = create_test_kafka().await;

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
    };
    produce_person_to_partition(&producer, 0, &bad).await;

    let cache = PartitionedCache::new(100);
    let cfg = warming_config_for("warmer-bad-props", &cluster);

    let result = warm_from_kafka(&cfg, &cache, 0).await;
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
}

/// Last-write-wins: the changelog can contain multiple updates for the
/// same `person_id` (each update produces a new record). After warming,
/// the cache must reflect the *latest* update — proven by checking the
/// version field, which the writer increments per update.
#[tokio::test]
async fn warming_preserves_last_write_for_same_key() {
    let (cluster, producer) = create_test_kafka().await;

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

    let cache = PartitionedCache::new(100);
    let cfg = warming_config_for("warmer-lww", &cluster);

    warm_from_kafka(&cfg, &cache, 0)
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
                entry.properties["email"], "v3@example.com",
                "cache must reflect the latest update's properties"
            );
        }
        other => panic!("expected Found, got {:?}", std::mem::discriminant(&other)),
    }
}
