//! Lifecycle fence semantics over the real gRPC surface: the fence is a
//! document write, so these tests assert both the RPC behavior and the
//! changelog records it produces.

mod common;

use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;

use common::{
    create_leader_client, create_test_kafka, seed_person, test_cached_person, test_recovery,
    unique_team_id, CHANGELOG_TOPIC, NUM_PARTITIONS,
};
use personhog_common::partitioning::partition_for_person;
use personhog_leader::cache::{CachedPerson, DirtyIndex, PartitionedCache, PersonCacheKey};
use personhog_leader::emitted::EmittedVersions;
use personhog_leader::fence::{
    FENCED_CREATOR_METADATA_KEY, FENCED_METADATA_KEY, FENCED_OP_ID_METADATA_KEY,
};
use personhog_leader::inflight::InflightTracker;
use personhog_leader::pg::PgFallback;
use personhog_leader::service::{PersonHogLeaderService, PropertySizeLimits};
use personhog_leader::warnings::WarningsProducer;
use personhog_proto::personhog::leader::v1::person_hog_leader_client::PersonHogLeaderClient;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FoldPersonDocumentRequest, GetPersonRequest, LifecycleOpType, Person,
    ReleaseFenceRequest, ReleaseOutcome, SealedSourceSnapshot, UpdatePersonPropertiesRequest,
};
use prost::Message;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::{ClientConfig, Message as KafkaMessage, TopicPartitionList};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use tonic::transport::Channel;
use tonic::transport::Server;
use tonic::{Code, Request};
use uuid::Uuid;

fn with_partition<T>(req: T, partition: u32) -> Request<T> {
    let mut request = Request::new(req);
    request
        .metadata_mut()
        .insert("x-partition", partition.to_string().parse().unwrap());
    request
}

fn fence_request(team_id: i64, person_id: i64, op_id: &Uuid) -> FencePersonRequest {
    FencePersonRequest {
        team_id,
        person_id,
        op_id: op_id.to_string(),
        op_type: LifecycleOpType::Delete.into(),
        creator_event_uuid: String::new(),
    }
}

fn update_request(team_id: i64, person_id: i64) -> UpdatePersonPropertiesRequest {
    UpdatePersonPropertiesRequest {
        team_id,
        person_id,
        event_name: "$set".to_string(),
        set_properties: serde_json::to_vec(&serde_json::json!({"name": "after-fence"})).unwrap(),
        set_once_properties: vec![],
        unset_properties: vec![],
        is_identified: None,
        last_seen_at: None,
    }
}

/// A leader service over a mock Kafka cluster with one seeded person, served
/// on a local socket. Returns the client, the seeded person's partition, its
/// id, and the consumer-facing bootstrap for changelog assertions.
struct FenceHarness {
    client: PersonHogLeaderClient<Channel>,
    team_id: i64,
    partition: u32,
    person_id: i64,
    bootstrap: String,
    cache: Arc<PartitionedCache>,
    inflight: Arc<InflightTracker>,
    emitted_versions: Arc<EmittedVersions>,
    _cancel: CancellationToken,
    _mock_cluster:
        rdkafka::mocking::MockCluster<'static, rdkafka::producer::DefaultProducerContext>,
}

async fn start_fence_harness(mut seed: CachedPerson, fallback: Option<PgFallback>) -> FenceHarness {
    let (mock_cluster, kafka_producer) = create_test_kafka().await;
    let bootstrap = mock_cluster.bootstrap_servers();

    // Every harness gets its own team, so concurrent tests — and leftover
    // rows from a failed earlier run — can never stomp on each other's
    // lifecycle marks.
    let team_id = unique_team_id();
    seed.team_id = team_id;
    let person_id = seed.id;
    let partition = partition_for_person(team_id, person_id, NUM_PARTITIONS);

    let cache = Arc::new(PartitionedCache::new(1 << 20));
    let inflight = Arc::new(InflightTracker::new());
    let emitted_versions = Arc::new(EmittedVersions::new(1_000_000));
    // Recovery consumes the same mock cluster so a post-death cache miss
    // can recover the death document.
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer.clone(),
        CHANGELOG_TOPIC.to_string(),
        fallback,
        Arc::new(DashMap::new()),
        Arc::clone(&inflight),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(&bootstrap),
        PropertySizeLimits::new(655360, 524288),
        WarningsProducer::new(kafka_producer, "clickhouse_ingestion_warnings".to_string()),
        Arc::new(DashMap::new()),
        None,
        None,
        Arc::clone(&emitted_versions),
    );

    cache.create_partition(partition);
    seed_person(&cache, partition, seed);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
    let token = cancel.child_token();
    tokio::spawn(async move {
        Server::builder()
            .add_service(PersonHogLeaderServer::new(service))
            .serve_with_incoming_shutdown(
                tokio_stream::wrappers::TcpListenerStream::new(listener),
                token.cancelled(),
            )
            .await
            .unwrap();
    });
    tokio::time::sleep(Duration::from_millis(10)).await;

    FenceHarness {
        client: create_leader_client(addr).await,
        team_id,
        partition,
        person_id,
        bootstrap,
        cache,
        inflight,
        emitted_versions,
        _cancel: cancel,
        _mock_cluster: mock_cluster,
    }
}

/// All changelog records currently on the person's partition, oldest first.
fn changelog_records(harness: &FenceHarness) -> Vec<Person> {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", &harness.bootstrap)
        .set("group.id", format!("fence-test-{}", Uuid::new_v4()))
        .create()
        .expect("failed to create consumer");
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(
        CHANGELOG_TOPIC,
        harness.partition as i32,
        rdkafka::Offset::Beginning,
    )
    .unwrap();
    consumer.assign(&tpl).unwrap();

    // The first poll can come back empty while the assignment settles, so
    // keep polling until the partition has been quiet after producing at
    // least one record, bounded by an overall deadline.
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    let mut records = Vec::new();
    loop {
        match consumer.poll(Duration::from_millis(300)) {
            Some(result) => {
                let msg = result.expect("kafka error");
                records
                    .push(Person::decode(msg.payload().unwrap()).expect("decode changelog record"));
            }
            None if !records.is_empty() || std::time::Instant::now() >= deadline => break,
            None => {}
        }
    }
    records
}

#[tokio::test]
async fn fencing_seals_and_blocks_writes_until_an_aborted_release() {
    let mut harness = start_fence_harness(test_cached_person(), None).await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let op = Uuid::now_v7();

    // Fence + seal in one call: the sealed state is the person's current
    // state — fencing produces nothing and does not advance the version.
    let sealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fence succeeds")
        .into_inner()
        .sealed
        .expect("sealed state returned");
    assert_eq!(
        sealed.version, 1,
        "the seal is the current version, not a write"
    );

    // Writes are rejected with the typed error while the fence holds.
    let status = harness
        .client
        .update_person_properties(with_partition(
            update_request(team_id, person_id),
            partition,
        ))
        .await
        .expect_err("fenced person rejects writes");
    assert_eq!(status.code(), Code::FailedPrecondition);
    assert_eq!(
        status.metadata().get(FENCED_METADATA_KEY).unwrap(),
        "delete"
    );
    assert_eq!(
        status.metadata().get(FENCED_OP_ID_METADATA_KEY).unwrap(),
        op.to_string().as_str()
    );

    // Reads are unaffected.
    let read = harness
        .client
        .get_person(with_partition(
            GetPersonRequest {
                team_id,
                person_id,
                read_options: None,
            },
            partition,
        ))
        .await
        .expect("reads flow while fenced");
    assert_eq!(read.into_inner().person.unwrap().version, 1);

    // Re-fencing with the same op re-seals with fresh state (the saga's
    // seal step is safe to repeat); a different op is rejected.
    let resealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("same-op re-fence succeeds")
        .into_inner()
        .sealed
        .unwrap();
    assert_eq!(
        resealed.version, 1,
        "nothing changed, so the fresh seal matches"
    );

    let other_op = Uuid::now_v7();
    let status = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &other_op),
            partition,
        ))
        .await
        .expect_err("at most one op holds a person");
    assert_eq!(status.code(), Code::FailedPrecondition);

    // An aborted release clears the fence with a document write and the
    // person resumes normal life.
    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid: String::new(),
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Aborted.into(),
                sealed_version: None,
                created_at: 0,
            },
            partition,
        ))
        .await
        .expect("aborted release succeeds");

    let updated = harness
        .client
        .update_person_properties(with_partition(
            update_request(team_id, person_id),
            partition,
        ))
        .await
        .expect("writes resume after the aborted release")
        .into_inner();
    assert!(updated.updated);
    let person = updated.person.unwrap();
    assert_eq!(
        person.version, 2,
        "fencing and the aborted release left no trace in the version"
    );
}

#[tokio::test]
async fn a_fence_with_a_creator_echoes_it_on_rejections() {
    let mut harness = start_fence_harness(test_cached_person(), None).await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let op = Uuid::now_v7();
    let creator = Uuid::now_v7();

    let mut request = fence_request(team_id, person_id, &op);
    request.creator_event_uuid = creator.to_string();
    harness
        .client
        .fence_person(with_partition(request, partition))
        .await
        .expect("fence succeeds");

    // The refusal names the creator, so the event's own caller can
    // recognise its fence without reconstructing the op-id derivation.
    let status = harness
        .client
        .update_person_properties(with_partition(
            update_request(team_id, person_id),
            partition,
        ))
        .await
        .expect_err("fenced person rejects writes");
    assert_eq!(
        status.metadata().get(FENCED_CREATOR_METADATA_KEY).unwrap(),
        creator.to_string().as_str()
    );

    // A fence installed without one carries no key at all, which a caller
    // reads as "fall back to the op id".
    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid: String::new(),
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Aborted.into(),
                sealed_version: None,
                created_at: 0,
            },
            partition,
        ))
        .await
        .expect("aborted release succeeds");
    harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &Uuid::now_v7()),
            partition,
        ))
        .await
        .expect("creator-less fence succeeds");
    let status = harness
        .client
        .update_person_properties(with_partition(
            update_request(team_id, person_id),
            partition,
        ))
        .await
        .expect_err("fenced person rejects writes");
    assert!(status.metadata().get(FENCED_CREATOR_METADATA_KEY).is_none());
}

#[tokio::test]
async fn a_committed_release_produces_the_death_document_above_every_version() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let person_uuid = test_cached_person().uuid;
    let op = Uuid::now_v7();

    // The mark rows the committed release verifies against — committed by
    // the saga before the fence in the real flow.
    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'delete', $2, 'sealed', '{}'::jsonb)",
    )
    .bind(op)
    .bind(team_id as i32)
    .execute(&pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'sealed')",
    )
    .bind(op)
    .bind(team_id as i32)
    .bind(person_id)
    .execute(&pool)
    .await
    .expect("insert mark");

    let sealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fence succeeds")
        .into_inner()
        .sealed
        .unwrap();
    let sealed_version = sealed.version;

    // Simulate a write that slipped through an unfenced window (leader
    // amnesia after a handoff): the cached person advances past the seal
    // without the fence.
    seed_person(
        &harness.cache,
        partition,
        CachedPerson {
            team_id,
            version: sealed_version + 3,
            ..test_cached_person()
        },
    );

    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid: person_uuid.clone(),
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Committed.into(),
                sealed_version: Some(sealed_version),
                created_at: sealed.created_at,
            },
            partition,
        ))
        .await
        .expect("committed release succeeds");

    let records = changelog_records(&harness);
    let death = records.last().expect("death document produced");
    assert!(death.is_deleted);
    assert_eq!(
        death.version,
        sealed_version + 4,
        "death version outranks the slipped write, not just the seal"
    );
    assert_eq!(death.uuid, person_uuid);
    assert_eq!(
        death.created_at, sealed.created_at,
        "the death document carries the sealed creation time, not a cold-path zero"
    );
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&death.properties).unwrap(),
        serde_json::json!({}),
        "death documents carry no properties"
    );

    // The death document stays cached, so reads answer an authoritative
    // not-found from memory — no changelog recovery, no PG fallback.
    match harness.cache.get(
        partition,
        &personhog_leader::cache::PersonCacheKey { team_id, person_id },
    ) {
        personhog_leader::cache::CacheLookup::Found(entry) => {
            assert!(entry.is_deleted, "the cached entry is the death document")
        }
        _ => panic!("the death document must stay cached"),
    }
    let status = harness
        .client
        .get_person(with_partition(
            GetPersonRequest {
                team_id,
                person_id,
                read_options: None,
            },
            partition,
        ))
        .await
        .expect_err("a destroyed person reads as not-found");
    assert_eq!(status.code(), Code::NotFound);

    // A duplicate committed release is absorbed without a second death
    // document.
    let records_before = changelog_records(&harness).len();
    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid,
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Committed.into(),
                sealed_version: Some(sealed_version),
                created_at: sealed.created_at,
            },
            partition,
        ))
        .await
        .expect("duplicate release is idempotent");
    assert_eq!(changelog_records(&harness).len(), records_before);

    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(op)
        .execute(&pool)
        .await
        .expect("cleanup");
}

/// A pre-fence write with an indeterminate produce outcome spends a
/// version the cache never learned of. The seal must cover it: sealed
/// below the spent version, the death document would derive at a version
/// that may already be live in the changelog.
#[tokio::test]
async fn the_seal_covers_versions_emitted_without_an_outcome() {
    let mut harness = start_fence_harness(test_cached_person(), None).await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;

    let spent = test_cached_person().version + 4;
    harness.emitted_versions.raise_for_test(
        partition,
        PersonCacheKey { team_id, person_id },
        spent,
    );

    let sealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &Uuid::now_v7()),
            partition,
        ))
        .await
        .expect("fence succeeds")
        .into_inner()
        .sealed
        .unwrap();
    assert_eq!(
        sealed.version, spent,
        "the seal must cover the emitted floor, not just the cache's version"
    );
}

/// The release-side counterpart: a post-seal write that slipped through an
/// unfenced window (leader amnesia after a handoff) with an indeterminate
/// outcome raises the floor without touching the cache. The death version
/// must clear that floor, or the death document lands at the same version
/// as a record that may already be in the changelog.
#[tokio::test]
async fn a_committed_release_derives_the_death_version_above_the_emitted_floor() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let person_uuid = test_cached_person().uuid;
    let op = Uuid::now_v7();

    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'delete', $2, 'sealed', '{}'::jsonb)",
    )
    .bind(op)
    .bind(team_id as i32)
    .execute(&pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'sealed')",
    )
    .bind(op)
    .bind(team_id as i32)
    .bind(person_id)
    .execute(&pool)
    .await
    .expect("insert mark");

    let sealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fence succeeds")
        .into_inner()
        .sealed
        .unwrap();

    let spent = sealed.version + 3;
    harness.emitted_versions.raise_for_test(
        partition,
        PersonCacheKey { team_id, person_id },
        spent,
    );

    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid,
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Committed.into(),
                sealed_version: Some(sealed.version),
                created_at: sealed.created_at,
            },
            partition,
        ))
        .await
        .expect("committed release succeeds");

    let records = changelog_records(&harness);
    let death = records.last().expect("death document produced");
    assert!(death.is_deleted);
    assert_eq!(
        death.version,
        spent + 1,
        "the death version must clear the emitted floor, not just the seal"
    );

    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(op)
        .execute(&pool)
        .await
        .expect("cleanup");
}

/// A fresh person stub is created at version 0, so 0 is a sealed version
/// the committed release must accept — a presence check that treats 0 as
/// "unset" fences the stub forever.
#[tokio::test]
async fn a_stub_sealed_at_version_zero_can_be_released() {
    let pool = common::create_persons_pool().await;
    let stub = CachedPerson {
        version: 0,
        ..test_cached_person()
    };
    let mut harness = start_fence_harness(
        stub,
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let op = Uuid::now_v7();

    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'delete', $2, 'sealed', '{}'::jsonb)",
    )
    .bind(op)
    .bind(team_id as i32)
    .execute(&pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'sealed')",
    )
    .bind(op)
    .bind(team_id as i32)
    .bind(person_id)
    .execute(&pool)
    .await
    .expect("insert mark");

    let sealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fence succeeds")
        .into_inner()
        .sealed
        .unwrap();
    assert_eq!(sealed.version, 0, "the stub seals at its real version");

    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid: sealed.uuid.clone(),
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Committed.into(),
                sealed_version: Some(0),
                created_at: sealed.created_at,
            },
            partition,
        ))
        .await
        .expect("a sealed version of 0 is presence, not absence");

    let records = changelog_records(&harness);
    let death = records.last().expect("death document produced");
    assert!(death.is_deleted);
    assert_eq!(death.version, 1, "the death version clears the seal");

    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(op)
        .execute(&pool)
        .await
        .expect("cleanup");
}

/// A fence whose op has already settled its mark row is a ghost: its
/// release was acked elsewhere and no retry is coming. A write rejected
/// by it must trigger the lazy heal, so a retry goes through instead of
/// the person staying frozen until the partition changes hands.
#[tokio::test]
async fn a_ghost_fence_heals_after_a_rejected_write() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let op = Uuid::now_v7();

    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'delete', $2, 'sealed', '{}'::jsonb)",
    )
    .bind(op)
    .bind(team_id as i32)
    .execute(&pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'sealed')",
    )
    .bind(op)
    .bind(team_id as i32)
    .bind(person_id)
    .execute(&pool)
    .await
    .expect("insert mark");

    harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fence succeeds");

    // The op settles (release acked to the saga, mark rows cleaned up)
    // without this leader hearing about it — the ghost scenario.
    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(op)
        .execute(&pool)
        .await
        .expect("settle the op");

    // The first write bounces on the ghost and triggers the heal; a
    // retry then goes through once the background check drops the fence.
    let status = harness
        .client
        .update_person_properties(with_partition(
            update_request(team_id, person_id),
            partition,
        ))
        .await
        .expect_err("the first write still bounces on the ghost");
    assert_eq!(status.code(), Code::FailedPrecondition);

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    loop {
        match harness
            .client
            .update_person_properties(with_partition(
                update_request(team_id, person_id),
                partition,
            ))
            .await
        {
            Ok(_) => break,
            Err(status) if status.code() == Code::FailedPrecondition => {
                assert!(
                    tokio::time::Instant::now() < deadline,
                    "the ghost fence was never healed"
                );
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            Err(other) => panic!("unexpected rejection: {other}"),
        }
    }
}

/// A contender's FencePerson bouncing on a ghost must trigger the same
/// lazy heal as a rejected write: on a low-traffic person no other
/// caller ever observes the ghost, so the contending op would retry
/// forever.
#[tokio::test]
async fn a_ghost_fence_heals_after_a_rejected_fence_attempt() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let ghost_op = Uuid::now_v7();
    let contender_op = Uuid::now_v7();

    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'delete', $2, 'sealed', '{}'::jsonb)",
    )
    .bind(ghost_op)
    .bind(team_id as i32)
    .execute(&pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'sealed')",
    )
    .bind(ghost_op)
    .bind(team_id as i32)
    .bind(person_id)
    .execute(&pool)
    .await
    .expect("insert mark");

    harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &ghost_op),
            partition,
        ))
        .await
        .expect("fence succeeds");

    // The op settles (release acked to the saga, mark rows cleaned up)
    // without this leader hearing about it — the ghost scenario.
    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(ghost_op)
        .execute(&pool)
        .await
        .expect("settle the op");

    let status = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &contender_op),
            partition,
        ))
        .await
        .expect_err("the first fence attempt still bounces on the ghost");
    assert_eq!(status.code(), Code::FailedPrecondition);

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    loop {
        match harness
            .client
            .fence_person(with_partition(
                fence_request(team_id, person_id, &contender_op),
                partition,
            ))
            .await
        {
            Ok(_) => break,
            Err(status) if status.code() == Code::FailedPrecondition => {
                assert!(
                    tokio::time::Instant::now() < deadline,
                    "the ghost fence was never healed"
                );
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            Err(other) => panic!("unexpected rejection: {other}"),
        }
    }
}

/// The heal's safety half: a fence whose op holds a live mark is not a
/// ghost, and heal checks triggered by a contender's rejected fence
/// attempts must never clear it.
#[tokio::test]
async fn a_live_marked_fence_survives_heal_attempts() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let holder_op = Uuid::now_v7();
    let contender_op = Uuid::now_v7();

    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'delete', $2, 'sealed', '{}'::jsonb)",
    )
    .bind(holder_op)
    .bind(team_id as i32)
    .execute(&pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'sealed')",
    )
    .bind(holder_op)
    .bind(team_id as i32)
    .bind(person_id)
    .execute(&pool)
    .await
    .expect("insert live mark");

    harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &holder_op),
            partition,
        ))
        .await
        .expect("fence succeeds");

    // A wrong clear would let a later attempt succeed and fail the loop.
    let deadline = tokio::time::Instant::now() + Duration::from_millis(500);
    while tokio::time::Instant::now() < deadline {
        let status = harness
            .client
            .fence_person(with_partition(
                fence_request(team_id, person_id, &contender_op),
                partition,
            ))
            .await
            .expect_err("the live fence keeps rejecting the contender");
        assert_eq!(status.code(), Code::FailedPrecondition);
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

/// The fail-closed half of the committed release: the request — even with
/// a fence the caller installed itself — is never enough to destroy a
/// person. Without a live mark row vouching for the op, the release is
/// refused and the person is untouched.
#[tokio::test]
async fn a_committed_release_without_a_live_mark_is_refused() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool,
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let op = Uuid::now_v7();

    // Fencing succeeds — the fence RPC does not verify the op…
    let sealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fence succeeds")
        .into_inner()
        .sealed
        .expect("sealed state returned");

    // …but the committed release must find the live mark, and there is
    // none: no lifecycle_op_person row was ever committed for this op.
    let status = harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid: test_cached_person().uuid,
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Committed.into(),
                sealed_version: Some(sealed.version),
                created_at: sealed.created_at,
            },
            partition,
        ))
        .await
        .expect_err("a release with no live mark is refused");
    assert_eq!(status.code(), Code::FailedPrecondition);
    assert!(
        status
            .metadata()
            .get(personhog_common::grpc::SEMANTIC_REFUSAL_METADATA_KEY)
            .is_some(),
        "the refusal must be marked semantic for router pass-through"
    );

    // The person is untouched: had a death document been produced, the
    // entry would have been evicted and this read would answer not-found.
    let read = harness
        .client
        .get_person(with_partition(
            GetPersonRequest {
                team_id,
                person_id,
                read_options: None,
            },
            partition,
        ))
        .await
        .expect("the person is still alive");
    assert_eq!(read.into_inner().person.unwrap().version, sealed.version);
}

/// Neither fence RPC may succeed on a pod that does not serve the
/// partition. A release that removed nothing and returned OK would leave
/// the real owner's fence standing while the saga believes it released —
/// a person frozen with no retry coming.
#[tokio::test]
async fn the_fence_rpcs_refuse_a_partition_this_pod_does_not_serve() {
    let mut harness = start_fence_harness(test_cached_person(), None).await;
    let team_id = harness.team_id;
    // A person on a partition the harness never created.
    let mut foreign_id: i64 = harness.person_id + 1;
    while partition_for_person(team_id, foreign_id, NUM_PARTITIONS) == harness.partition {
        foreign_id += 1;
    }
    let foreign_partition = partition_for_person(team_id, foreign_id, NUM_PARTITIONS);
    let op = Uuid::now_v7();

    let status = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, foreign_id, &op),
            foreign_partition,
        ))
        .await
        .expect_err("fencing an unserved partition is refused");
    assert_eq!(status.code(), Code::FailedPrecondition);

    let status = harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id: foreign_id,
                person_uuid: String::new(),
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Aborted.into(),
                sealed_version: None,
                created_at: 0,
            },
            foreign_partition,
        ))
        .await
        .expect_err("an aborted release must not vacuously succeed elsewhere");
    assert_eq!(status.code(), Code::FailedPrecondition);
}

/// A drained (deposed) pod must refuse FencePerson: a fence accepted
/// there lands in a map the new owner never consults and is silently
/// discarded at release, leaving the saga with a seal that protects
/// nothing. The refusal is what forces the saga's retry onto the current
/// owner.
#[tokio::test]
async fn fencing_is_refused_while_the_partition_is_handoff_fenced() {
    let mut harness = start_fence_harness(test_cached_person(), None).await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let op = Uuid::now_v7();

    harness.inflight.fence(partition);
    let status = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect_err("a handoff-fenced partition refuses FencePerson");
    assert_eq!(status.code(), Code::FailedPrecondition);
    assert!(
        status.metadata().get(FENCED_METADATA_KEY).is_none(),
        "a handoff rejection is not a person-fence rejection"
    );

    // Re-admission (a cancelled handoff, or a fresh warm) restores fencing.
    harness.inflight.unfence(partition);
    harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fencing resumes once the partition is re-admitted");
}

#[tokio::test]
async fn a_destroyed_person_rejects_fencing_and_writes_with_not_found() {
    let harness = start_fence_harness(
        CachedPerson {
            is_deleted: true,
            ..test_cached_person()
        },
        None,
    )
    .await;
    let mut client = harness.client.clone();
    let team_id = harness.team_id;
    let op = Uuid::now_v7();

    let status = client
        .fence_person(with_partition(
            fence_request(team_id, harness.person_id, &op),
            harness.partition,
        ))
        .await
        .expect_err("cannot fence a destroyed person");
    assert_eq!(status.code(), Code::NotFound);

    let status = client
        .update_person_properties(with_partition(
            update_request(team_id, harness.person_id),
            harness.partition,
        ))
        .await
        .expect_err("cannot write to a destroyed person");
    assert_eq!(status.code(), Code::NotFound);

    let status = client
        .get_person(with_partition(
            GetPersonRequest {
                team_id,
                person_id: harness.person_id,
                read_options: None,
            },
            harness.partition,
        ))
        .await
        .expect_err("a destroyed person reads as not-found");
    assert_eq!(status.code(), Code::NotFound);
}

/// The takeover scan: a leader acquiring a partition rebuilds its fence map
/// from the live marks in Postgres, keeping only its partition's rows and
/// excluding merge targets (claimed, never fenced). Release drops exactly
/// the partition's entries. Runs against the real persons DB.
#[tokio::test]
async fn the_takeover_scan_rebuilds_exactly_the_partitions_live_fences() {
    use personhog_leader::fence::{drop_partition_fences, rebuild_partition_fences, FenceMap};

    let pool = common::create_persons_pool().await;
    let team_id = unique_team_id();
    let op_id = Uuid::now_v7();
    let creator = Uuid::now_v7();

    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'merge', $2, 'claimed', jsonb_build_object('creator_event_uuid', $3::text))",
    )
    .bind(op_id)
    .bind(team_id as i32)
    .bind(creator.to_string())
    .execute(&pool)
    .await
    .expect("insert op");

    // Two live marks on different partitions, one merge target, one
    // already-settled row: only the live non-target marks are fences.
    let fenced_a: i64 = 1; // some partition
    let mut fenced_b: i64 = 2;
    while partition_for_person(team_id, fenced_b, NUM_PARTITIONS)
        == partition_for_person(team_id, fenced_a, NUM_PARTITIONS)
    {
        fenced_b += 1;
    }
    let target: i64 = 100;
    let settled: i64 = 101;
    for (person_id, role, status) in [
        (fenced_a, "source", "marked"),
        (fenced_b, "victim", "sealed"),
        (target, "target", "marked"),
        (settled, "victim", "deleted"),
    ] {
        sqlx::query(
            "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
             VALUES ($1, $2, $3, gen_random_uuid(), $4, $5)",
        )
        .bind(op_id)
        .bind(team_id as i32)
        .bind(person_id)
        .bind(role)
        .bind(status)
        .execute(&pool)
        .await
        .expect("insert mark");
    }

    let partition_a = partition_for_person(team_id, fenced_a, NUM_PARTITIONS);
    let fences: FenceMap = Arc::new(DashMap::new());
    let installed = rebuild_partition_fences(&pool, &fences, partition_a, NUM_PARTITIONS)
        .await
        .expect("scan runs");

    let key = |person_id| personhog_leader::cache::PersonCacheKey { team_id, person_id };
    assert!(installed >= 1, "the partition's live mark was installed");
    let entry = fences
        .get(&key(fenced_a))
        .expect("live mark became a fence");
    assert_eq!(entry.op_id, op_id);
    assert_eq!(
        entry.creator_event_uuid,
        Some(creator),
        "the rebuilt fence recovers the creator from the frozen request"
    );
    drop(entry);
    assert!(
        fences.get(&key(fenced_b)).is_none(),
        "another partition's mark is not ours"
    );
    assert!(
        fences.get(&key(target)).is_none(),
        "merge targets are claimed, never fenced"
    );
    assert!(
        fences.get(&key(settled)).is_none(),
        "settled rows are outside the mark set"
    );

    // A re-warm converges on the marks rather than accumulating: an entry
    // a previous warm left behind for a person no longer marked is gone.
    // (A handoff cancelled after warming, then re-acquired, takes this
    // path — nothing else would ever clear that entry.)
    let ghost = fenced_a + 1_000_000;
    let ghost_partition = partition_for_person(team_id, ghost, NUM_PARTITIONS);
    fences.insert(
        key(ghost),
        personhog_leader::fence::FenceState {
            op_id: Uuid::now_v7(),
            op_type: personhog_proto::personhog::types::v1::LifecycleOpType::Delete,
            creator_event_uuid: None,
        },
    );
    let reinstalled = rebuild_partition_fences(&pool, &fences, ghost_partition, NUM_PARTITIONS)
        .await
        .expect("re-warm runs");
    assert!(
        fences.get(&key(ghost)).is_none(),
        "a re-warm drops entries the marks no longer justify"
    );
    if ghost_partition == partition_a {
        assert_eq!(
            reinstalled, installed,
            "re-warming the same partition installs the same set"
        );
    }

    let dropped = drop_partition_fences(&fences, partition_a, NUM_PARTITIONS);
    assert!(dropped >= 1);
    assert!(
        fences.get(&key(fenced_a)).is_none(),
        "release drops the partition's fences"
    );

    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .execute(&pool)
        .await
        .expect("cleanup");
}

/// The fence map's memory fuse: at capacity, a new fence sheds with
/// RESOURCE_EXHAUSTED (backpressure the saga retries), while a re-seal of
/// an already-fenced person still succeeds — refusing it would free
/// nothing.
#[tokio::test]
async fn at_capacity_new_fences_shed_but_reseals_succeed() {
    use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeader;

    let team_id = unique_team_id();
    let cache = Arc::new(PartitionedCache::new(1 << 20));
    let (_mock_cluster, kafka_producer) = create_test_kafka().await;
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer.clone(),
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(&_mock_cluster.bootstrap_servers()),
        PropertySizeLimits::new(655360, 524288),
        WarningsProducer::new(kafka_producer, "clickhouse_ingestion_warnings".to_string()),
        Arc::new(DashMap::new()),
        None,
        None,
        Arc::new(personhog_leader::emitted::EmittedVersions::new(1_000_000)),
    )
    .with_fence_capacity(1);

    let (first_id, second_id) = (5000, 5001);
    for id in [first_id, second_id] {
        let partition = partition_for_person(team_id, id, NUM_PARTITIONS);
        // Both persons can share a partition; re-creating it would wipe
        // the first seed.
        if !cache.has_partition(partition) {
            cache.create_partition(partition);
        }
        seed_person(
            &cache,
            partition,
            CachedPerson {
                id,
                team_id,
                ..test_cached_person()
            },
        );
    }
    let (first_op, second_op) = (Uuid::now_v7(), Uuid::now_v7());

    let fence = |person_id: i64, op: Uuid| {
        let partition = partition_for_person(team_id, person_id, NUM_PARTITIONS);
        with_partition(fence_request(team_id, person_id, &op), partition)
    };

    service
        .fence_person(fence(first_id, first_op))
        .await
        .expect("the first fence fits");

    let status = service
        .fence_person(fence(second_id, second_op))
        .await
        .expect_err("a new fence past the cap must shed");
    assert_eq!(status.code(), Code::ResourceExhausted);

    service
        .fence_person(fence(first_id, first_op))
        .await
        .expect("a re-seal of an already-fenced person is exempt from the cap");
}

// ============================================================
// FoldPersonDocument: the merge saga's document write
// ============================================================

fn snapshot(properties: serde_json::Value, version: i64, created_at: i64) -> Person {
    Person {
        properties: serde_json::to_vec(&properties).unwrap(),
        version,
        created_at,
        ..Default::default()
    }
}

fn fold_request(
    team_id: i64,
    person_id: i64,
    op_id: &Uuid,
    snapshots: Vec<Person>,
    event_set: serde_json::Value,
    event_set_once: serde_json::Value,
) -> FoldPersonDocumentRequest {
    // List position becomes the ordinal, so tests read naturally:
    // earlier in the list = higher precedence.
    let with_ordinals = snapshots
        .into_iter()
        .enumerate()
        .map(|(index, person)| (person, index as i32))
        .collect();
    fold_request_with_ordinals(
        team_id,
        person_id,
        op_id,
        with_ordinals,
        event_set,
        event_set_once,
    )
}

fn fold_request_with_ordinals(
    team_id: i64,
    person_id: i64,
    op_id: &Uuid,
    snapshots: Vec<(Person, i32)>,
    event_set: serde_json::Value,
    event_set_once: serde_json::Value,
) -> FoldPersonDocumentRequest {
    // Unset identity fields get the target's team and a distinct source
    // id, mirroring what FencePerson seals; tests probing the identity
    // checks set them explicitly.
    let sealed_snapshots = snapshots
        .into_iter()
        .map(|(mut person, ordinal)| {
            if person.team_id == 0 {
                person.team_id = team_id;
            }
            if person.id == 0 {
                person.id = person_id + 1_000 + i64::from(ordinal);
            }
            SealedSourceSnapshot {
                person: Some(person),
                ordinal,
            }
        })
        .collect();
    FoldPersonDocumentRequest {
        team_id,
        person_id,
        sealed_snapshots,
        event_set: serde_json::to_vec(&event_set).unwrap(),
        event_set_once: serde_json::to_vec(&event_set_once).unwrap(),
        op_id: op_id.to_string(),
    }
}

fn person_properties(person: &Person) -> serde_json::Value {
    serde_json::from_slice(&person.properties).expect("changelog properties parse")
}

/// The mark rows the fold verifies against — committed by the merge saga
/// before it fences the sources in the real flow.
async fn seed_target_mark(
    pool: &sqlx::PgPool,
    op: &Uuid,
    team_id: i64,
    person_id: i64,
    status: &str,
) {
    // A far-future lease keeps these never-completed ops out of the
    // identity sweeper's abandoned-op scan (it resumes NULL-lease and
    // expired-lease rows), so runs against a shared database cannot
    // poison the engine tests.
    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at) \
         VALUES ($1, 'merge', $2, 'folding', '{}'::jsonb, now() + interval '100 years')",
    )
    .bind(op)
    .bind(team_id as i32)
    .execute(pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'target', $4)",
    )
    .bind(op)
    .bind(team_id as i32)
    .bind(person_id)
    .bind(status)
    .execute(pool)
    .await
    .expect("insert target mark");
}

/// A fold-ready harness: lifecycle database attached and a live 'marked'
/// target row for `op` — the state the merge saga guarantees before it
/// calls the fold.
async fn start_marked_fold_harness(seed: CachedPerson, op: &Uuid) -> FenceHarness {
    let pool = common::create_persons_pool().await;
    let harness = start_fence_harness(
        seed,
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    seed_target_mark(&pool, op, harness.team_id, harness.person_id, "marked").await;
    harness
}

#[tokio::test]
async fn a_fold_applies_precedence_and_scalars_and_lands_in_the_changelog() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({"a": "target", "b": "target"}))
                .unwrap(),
            created_at: 1_700_000_000,
            version: 3,
            is_identified: false,
            last_seen_at: Some(1_700_000_000_000),
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![
                    // The first snapshot beats the second; both lose to the
                    // target; sealed versions, created_at, and last_seen_at
                    // feed the fold.
                    Person {
                        last_seen_at: Some(1_750_000_000_000),
                        ..snapshot(
                            serde_json::json!({"b": "s1", "c": "s1", "d": "s1"}),
                            7,
                            1_600_000_000,
                        )
                    },
                    snapshot(serde_json::json!({"c": "s2", "e": "s2"}), 5, 1_650_000_000),
                ],
                serde_json::json!({"a": "event"}),
                serde_json::json!({"b": "event-ignored", "f": "event"}),
            ),
            harness.partition,
        ))
        .await
        .expect("fold succeeds")
        .into_inner()
        .person
        .expect("fold returns the document");

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({
            "a": "event",   // event $set overrides the target
            "b": "target",  // target beats snapshots; $set_once cannot override
            "c": "s1",      // earlier snapshot beats later
            "d": "s1",
            "e": "s2",
            "f": "event",   // $set_once fills the absent key
        })
    );
    assert_eq!(
        folded.created_at, 1_600_000_000,
        "min over target and snapshots"
    );
    assert!(folded.is_identified, "a merge is an identify");
    assert_eq!(
        folded.last_seen_at,
        Some(1_750_000_000_000),
        "max over target and snapshots"
    );
    assert_eq!(folded.version, 8, "max(target 3, sealed 7) + 1");

    // The response is the changelog record, not just a view of the cache.
    let records = changelog_records(&harness);
    let produced = records.last().expect("the fold produced a record");
    assert_eq!(person_properties(produced), person_properties(&folded));
    assert_eq!(produced.version, folded.version);
    assert!(produced.is_identified);
}

#[tokio::test]
async fn refolding_changes_no_content_and_only_bumps_the_version() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(test_cached_person(), &op).await;
    let request = fold_request(
        harness.team_id,
        harness.person_id,
        &op,
        vec![snapshot(
            serde_json::json!({"plan": "free"}),
            4,
            1_650_000_000,
        )],
        serde_json::json!({"source": "identify"}),
        serde_json::json!({}),
    );

    let first = harness
        .client
        .fold_person_document(with_partition(request.clone(), harness.partition))
        .await
        .expect("first fold succeeds")
        .into_inner()
        .person
        .unwrap();
    let second = harness
        .client
        .fold_person_document(with_partition(request, harness.partition))
        .await
        .expect("a re-driven fold succeeds")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(person_properties(&second), person_properties(&first));
    assert_eq!(second.created_at, first.created_at);
    assert_eq!(second.is_identified, first.is_identified);
    assert_eq!(second.version, first.version + 1);
}

#[tokio::test]
async fn event_set_overrides_and_set_once_respects_snapshot_contributed_keys() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({"target_only": "t"})).unwrap(),
            version: 2,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(
                    serde_json::json!({"from_snapshot": "snap", "contested": "snap"}),
                    5,
                    1_650_000_000,
                )],
                serde_json::json!({"contested": "set-wins"}),
                serde_json::json!({"from_snapshot": "ignored", "fresh": "once"}),
            ),
            harness.partition,
        ))
        .await
        .expect("fold succeeds")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({
            "target_only": "t",
            "from_snapshot": "snap",   // event_set_once cannot override snapshot-contributed key
            "contested": "set-wins",   // event_set overrides snapshot-contributed key
            "fresh": "once",           // event_set_once fills truly absent key
        })
    );
}

#[tokio::test]
async fn fold_with_empty_target_properties_fills_from_snapshots_and_event() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({})).unwrap(),
            created_at: 1_700_000_000,
            version: 10,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(serde_json::json!({"a": "snap"}), 3, 1_650_000_000)],
                serde_json::json!({"b": "set"}),
                serde_json::json!({"a": "ignored", "c": "once"}),
            ),
            harness.partition,
        ))
        .await
        .expect("fold succeeds")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({"a": "snap", "b": "set", "c": "once"})
    );
    assert_eq!(
        folded.version, 11,
        "target version 10 > sealed 3, so max(10, 3) + 1"
    );
}

#[tokio::test]
async fn created_at_ignores_non_positive_snapshot_timestamps_and_target_can_be_earliest() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({})).unwrap(),
            created_at: 1_500_000_000,
            version: 1,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![
                    snapshot(serde_json::json!({}), 2, 0),
                    snapshot(serde_json::json!({}), 3, 1_600_000_000),
                ],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("fold succeeds")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        folded.created_at, 1_500_000_000,
        "target is earliest; snapshot with created_at=0 is filtered out"
    );
}

#[tokio::test]
async fn a_fold_through_a_foreign_fence_is_rejected_until_released() {
    let delete_op = Uuid::now_v7();
    let merge_op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(test_cached_person(), &merge_op).await;

    harness
        .client
        .fence_person(with_partition(
            fence_request(harness.team_id, harness.person_id, &delete_op),
            harness.partition,
        ))
        .await
        .expect("the delete op fences the person");

    let request = fold_request(
        harness.team_id,
        harness.person_id,
        &merge_op,
        vec![snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000)],
        serde_json::json!({}),
        serde_json::json!({}),
    );
    let status = harness
        .client
        .fold_person_document(with_partition(request.clone(), harness.partition))
        .await
        .expect_err("a foreign fence blocks the fold");
    assert_eq!(status.code(), Code::FailedPrecondition);
    assert_eq!(
        status.metadata().get(FENCED_METADATA_KEY).unwrap(),
        "delete"
    );

    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id: harness.team_id,
                person_id: harness.person_id,
                person_uuid: String::new(),
                op_id: delete_op.to_string(),
                outcome: ReleaseOutcome::Aborted.into(),
                sealed_version: None,
                created_at: 0,
            },
            harness.partition,
        ))
        .await
        .expect("the delete op releases its fence");

    harness
        .client
        .fold_person_document(with_partition(request, harness.partition))
        .await
        .expect("the fold goes through once the fence is gone");
}

#[tokio::test]
async fn a_destroyed_target_refuses_the_fold() {
    let mut harness = start_fence_harness(
        CachedPerson {
            is_deleted: true,
            ..test_cached_person()
        },
        None,
    )
    .await;

    let status = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &Uuid::now_v7(),
                vec![snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000)],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect_err("a death document cannot be folded into");
    assert_eq!(status.code(), Code::NotFound);
}

#[tokio::test]
async fn invalid_fold_requests_are_rejected_before_any_work() {
    let mut harness = start_fence_harness(test_cached_person(), None).await;
    let op = Uuid::now_v7();
    let valid_snapshot = || vec![snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000)];

    let no_snapshots = fold_request(
        harness.team_id,
        harness.person_id,
        &op,
        vec![],
        serde_json::json!({}),
        serde_json::json!({}),
    );
    let bad_op_id = FoldPersonDocumentRequest {
        op_id: "not-a-uuid".to_string(),
        ..fold_request(
            harness.team_id,
            harness.person_id,
            &op,
            valid_snapshot(),
            serde_json::json!({}),
            serde_json::json!({}),
        )
    };
    let non_object_event_set = FoldPersonDocumentRequest {
        event_set: serde_json::to_vec(&serde_json::json!(["not", "a", "map"])).unwrap(),
        ..fold_request(
            harness.team_id,
            harness.person_id,
            &op,
            valid_snapshot(),
            serde_json::json!({}),
            serde_json::json!({}),
        )
    };

    let duplicate_ordinals = fold_request_with_ordinals(
        harness.team_id,
        harness.person_id,
        &op,
        vec![
            (snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000), 0),
            (snapshot(serde_json::json!({"y": "2"}), 3, 1_650_000_000), 0),
        ],
        serde_json::json!({}),
        serde_json::json!({}),
    );
    let missing_person = FoldPersonDocumentRequest {
        sealed_snapshots: vec![SealedSourceSnapshot {
            person: None,
            ordinal: 0,
        }],
        ..fold_request(
            harness.team_id,
            harness.person_id,
            &op,
            valid_snapshot(),
            serde_json::json!({}),
            serde_json::json!({}),
        )
    };
    let wrong_team = fold_request(
        harness.team_id,
        harness.person_id,
        &op,
        vec![Person {
            team_id: harness.team_id + 1,
            ..snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000)
        }],
        serde_json::json!({}),
        serde_json::json!({}),
    );
    let snapshot_is_target = fold_request(
        harness.team_id,
        harness.person_id,
        &op,
        vec![Person {
            id: harness.person_id,
            ..snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000)
        }],
        serde_json::json!({}),
        serde_json::json!({}),
    );
    let death_document_snapshot = fold_request(
        harness.team_id,
        harness.person_id,
        &op,
        vec![Person {
            is_deleted: true,
            ..snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000)
        }],
        serde_json::json!({}),
        serde_json::json!({}),
    );

    for (label, request) in [
        ("empty snapshots", no_snapshots),
        ("malformed op_id", bad_op_id),
        ("non-object event_set", non_object_event_set),
        ("duplicate ordinals", duplicate_ordinals),
        ("snapshot missing its person", missing_person),
        ("wrong-team snapshot", wrong_team),
        ("snapshot is the target", snapshot_is_target),
        ("death-document snapshot", death_document_snapshot),
    ] {
        let status = harness
            .client
            .fold_person_document(with_partition(request, harness.partition))
            .await
            .expect_err(label);
        assert_eq!(status.code(), Code::InvalidArgument, "{label}");
    }
}

/// The fail-closed half of the fold: the request — even with a well-formed
/// op id — is never enough to write to the target. Without a live 'marked'
/// target row vouching for the op, the fold is refused and the target is
/// untouched: a superseded or settled saga runner's late fold must land
/// nowhere.
#[tokio::test]
async fn a_fold_whose_op_holds_no_live_target_mark_is_refused() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let op = Uuid::now_v7();
    let request = fold_request(
        harness.team_id,
        harness.person_id,
        &op,
        vec![snapshot(serde_json::json!({"x": "1"}), 2, 1_650_000_000)],
        serde_json::json!({}),
        serde_json::json!({}),
    );

    // No mark row at all: the op never claimed the person. The refusal
    // carries the semantic-refusal marker so the router delivers it
    // instead of bouncing it into a retriable UNAVAILABLE.
    let status = harness
        .client
        .fold_person_document(with_partition(request.clone(), harness.partition))
        .await
        .expect_err("a fold with no mark is refused");
    assert_eq!(status.code(), Code::FailedPrecondition);
    assert!(
        status
            .metadata()
            .get(personhog_common::grpc::SEMANTIC_REFUSAL_METADATA_KEY)
            .is_some(),
        "the refusal must be marked semantic for router pass-through"
    );

    // A settled op: the target row was cleared when the saga completed.
    seed_target_mark(&pool, &op, harness.team_id, harness.person_id, "cleared").await;
    let status = harness
        .client
        .fold_person_document(with_partition(request.clone(), harness.partition))
        .await
        .expect_err("a settled op's re-driven fold is refused");
    assert_eq!(status.code(), Code::FailedPrecondition);

    // The wrong role: the op holds the person, but not as its target —
    // folding into it would be a saga bug.
    sqlx::query(
        "UPDATE lifecycle_op_person SET role = 'victim', status = 'marked' WHERE op_id = $1",
    )
    .bind(op)
    .execute(&pool)
    .await
    .expect("update mark");
    let status = harness
        .client
        .fold_person_document(with_partition(request.clone(), harness.partition))
        .await
        .expect_err("a non-target mark does not authorize the fold");
    assert_eq!(status.code(), Code::FailedPrecondition);

    // The target was untouched through all three refusals.
    let read = harness
        .client
        .get_person(with_partition(
            GetPersonRequest {
                team_id: harness.team_id,
                person_id: harness.person_id,
                read_options: None,
            },
            harness.partition,
        ))
        .await
        .expect("the person is still readable");
    assert_eq!(read.into_inner().person.unwrap().version, 1);

    // With the live target mark restored, the same request folds — the
    // mark was the only thing missing.
    sqlx::query("UPDATE lifecycle_op_person SET role = 'target' WHERE op_id = $1")
        .bind(op)
        .execute(&pool)
        .await
        .expect("restore mark");
    harness
        .client
        .fold_person_document(with_partition(request, harness.partition))
        .await
        .expect("the fold goes through with a live target mark");
}

/// An oversized fold trims only what the fold contributed: the target's
/// own keys — state admission already accepted — survive even when they
/// sort first alphabetically, and the contributed keys absorb the trim.
#[tokio::test]
async fn an_oversized_fold_trims_the_contribution_not_the_targets_keys() {
    let op = Uuid::now_v7();
    let target_value = "x".repeat(500_000);
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({"aa_target": target_value.clone()}))
                .unwrap(),
            version: 3,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(
                    serde_json::json!({"zz_snapshot": "y".repeat(200_000)}),
                    7,
                    1_650_000_000,
                )],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("an oversized fold still completes")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({"aa_target": target_value}),
        "the target's key survives; the contributed key absorbed the trim"
    );
}

/// When trimming the fold's contribution cannot get the document under the
/// limit, the fold discards the contribution entirely and keeps the
/// target's document byte for byte — it never dips into keys a
/// within-limit target already owned. The scalar fold still applies.
#[tokio::test]
async fn an_unremediable_fold_keeps_the_targets_document_untouched() {
    let op = Uuid::now_v7();
    // Over the trim target but under the threshold: admitted state that
    // leaves no room for any contribution.
    let target_value = "x".repeat(600_000);
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({"tt_target": target_value.clone()}))
                .unwrap(),
            version: 3,
            is_identified: false,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(
                    serde_json::json!({"ss_snapshot": "y".repeat(100_000)}),
                    7,
                    1_650_000_000,
                )],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("an unremediable fold still completes")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({"tt_target": target_value})
    );
    assert_eq!(
        folded.version, 8,
        "the version still folds: max(target 3, sealed 7) + 1"
    );
    assert!(folded.is_identified, "the scalar fold still applies");
}

/// When the hysteresis trim target is unreachable, the trim retries
/// against the hard ceiling: a document in the band between them is
/// still applyable by the writer, so an already-oversized target folds
/// to an applyable document instead of discarding to its oversized
/// stored state — which the writer would refuse to commit past.
#[tokio::test]
async fn an_oversized_targets_fold_trims_to_the_hard_ceiling() {
    let op = Uuid::now_v7();
    let email_value = "e".repeat(550_000);
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            // email is protected and alone overshoots the trim target;
            // tt_target is trimmable overflow above the ceiling.
            properties: serde_json::to_vec(&serde_json::json!({"email": email_value.clone(), "tt_target": "x".repeat(200_000)})).unwrap(),
            version: 3,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(
                    serde_json::json!({"zz_snapshot": "y".repeat(10_000)}),
                    7,
                    1_650_000_000,
                )],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("the fold completes")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({"email": email_value}),
        "trimmed to the ceiling: protected key kept, overflow dropped"
    );
    assert_eq!(folded.version, 8, "max(target 3, sealed 7) + 1");
}

/// When no applyable document exists at all — the target's stored
/// protected keys alone exceed the hard ceiling — the fold completes
/// without producing: committing the oversized document would halt the
/// writer, and rejecting would wedge the saga's re-drive loop. The
/// person comes back unchanged, fold effects skipped.
#[tokio::test]
async fn an_unapplyable_fold_completes_without_producing() {
    let op = Uuid::now_v7();
    let email_value = "e".repeat(700_000);
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({"email": email_value.clone()}))
                .unwrap(),
            version: 3,
            is_identified: false,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let person = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(
                    serde_json::json!({"zz_snapshot": "y".repeat(10_000)}),
                    7,
                    1_650_000_000,
                )],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("an unapplyable fold still completes")
        .into_inner()
        .person
        .unwrap();

    // An unchanged version proves nothing was produced: every commit
    // bumps it.
    assert_eq!(person.version, 3, "no document was produced");
    assert!(!person.is_identified, "scalar effects are skipped too");
    assert_eq!(
        person_properties(&person),
        serde_json::json!({"email": email_value})
    );
}

/// A target whose stored properties are not an object folds as an empty
/// document on every path: the unremediable arm must restore the
/// normalized form, not the raw stored value.
#[tokio::test]
async fn a_non_object_target_stays_an_object_through_the_unremediable_path() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!("legacy-scalar")).unwrap(),
            ..test_cached_person()
        },
        &op,
    )
    .await;

    // The only contribution is protected, so nothing is trimmable and the
    // contribution is discarded wholesale.
    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(
                    serde_json::json!({"$initial_utm_source": "y".repeat(700_000)}),
                    2,
                    1_650_000_000,
                )],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("the fold completes")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(person_properties(&folded), serde_json::json!({}));
}

/// Precedence follows the recorded ordinals, not the request order: the
/// same sources listed differently fold to the same document — the
/// convergence a re-driven saga step depends on.
#[tokio::test]
async fn precedence_follows_ordinals_not_request_order() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({})).unwrap(),
            version: 1,
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let winner = snapshot(
        serde_json::json!({"contested": "winner", "a": "winner"}),
        4,
        1_600_000_000,
    );
    let loser = snapshot(
        serde_json::json!({"contested": "loser", "b": "loser"}),
        5,
        1_650_000_000,
    );

    // The request lists the lower-precedence source first; the ordinals,
    // not the list order, decide the contested key.
    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request_with_ordinals(
                harness.team_id,
                harness.person_id,
                &op,
                vec![(loser, 1), (winner, 0)],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("fold succeeds")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({
            "contested": "winner",
            "a": "winner",
            "b": "loser",
        })
    );
}

/// Cache dirt on the target — state loaded from Postgres or warmed from
/// records that predate sanitization — is rewritten like every other
/// fold input, so the committed document is measured in stored form.
#[tokio::test]
async fn a_folds_target_cache_dirt_is_sanitized() {
    let op = Uuid::now_v7();
    let mut harness = start_marked_fold_harness(
        CachedPerson {
            properties: serde_json::to_vec(&serde_json::json!({"dirty": "a\u{0000}b"})).unwrap(),
            ..test_cached_person()
        },
        &op,
    )
    .await;

    let folded = harness
        .client
        .fold_person_document(with_partition(
            fold_request(
                harness.team_id,
                harness.person_id,
                &op,
                vec![snapshot(serde_json::json!({}), 2, 1_650_000_000)],
                serde_json::json!({}),
                serde_json::json!({}),
            ),
            harness.partition,
        ))
        .await
        .expect("fold succeeds")
        .into_inner()
        .person
        .unwrap();

    assert_eq!(
        person_properties(&folded),
        serde_json::json!({"dirty": "a\u{FFFD}b"})
    );
}

/// The saga's unmap writes the person tombstone straight to PG before the
/// release runs, and cache pressure can evict the fenced victim in that
/// window (nothing pins fenced entries). The release's cache miss must not
/// mistake that direct tombstone for an already-emitted death document.
/// Today this holds because the PG fallback load filters `is_deleted =
/// false`, so the release sees no person and takes the cold-leader path,
/// re-deriving the document from the sealed version — this test pins that
/// composed behavior against either side changing (the load filter, or the
/// duplicate-release absorb).
#[tokio::test]
async fn a_release_after_a_cache_eviction_still_produces_the_death_document() {
    let pool = common::create_persons_pool().await;
    let mut harness = start_fence_harness(
        test_cached_person(),
        Some(PgFallback {
            pool: pool.clone(),
            table: "posthog_person".to_string(),
        }),
    )
    .await;
    let team_id = harness.team_id;
    let partition = harness.partition;
    let person_id = harness.person_id;
    let person_uuid = test_cached_person().uuid;
    let op = Uuid::now_v7();

    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request) \
         VALUES ($1, 'delete', $2, 'unmapped', '{}'::jsonb)",
    )
    .bind(op)
    .bind(team_id as i32)
    .execute(&pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, $4::uuid, 'victim', 'sealed')",
    )
    .bind(op)
    .bind(team_id as i32)
    .bind(person_id)
    .bind(&person_uuid)
    .execute(&pool)
    .await
    .expect("insert mark");

    let sealed = harness
        .client
        .fence_person(with_partition(
            fence_request(team_id, person_id, &op),
            partition,
        ))
        .await
        .expect("fence succeeds")
        .into_inner()
        .sealed
        .unwrap();
    let sealed_version = sealed.version;

    // The unmap transaction's direct tombstone: scrubbed, parked at
    // sealed + 1.
    sqlx::query(
        "INSERT INTO posthog_person \
             (id, team_id, uuid, properties, created_at, version, is_identified, is_deleted) \
         VALUES ($1, $2, $3::uuid, '{}'::jsonb, now(), $4, false, true)",
    )
    .bind(person_id)
    .bind(team_id as i32)
    .bind(&person_uuid)
    .bind(sealed_version + 1)
    .execute(&pool)
    .await
    .expect("insert unmap tombstone");

    // The eviction: Foyer may drop any entry under capacity pressure, and
    // nothing pins a fenced victim.
    harness.cache.remove(
        partition,
        &personhog_leader::cache::PersonCacheKey { team_id, person_id },
    );

    harness
        .client
        .release_fence(with_partition(
            ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid: person_uuid.clone(),
                op_id: op.to_string(),
                outcome: ReleaseOutcome::Committed.into(),
                sealed_version: Some(sealed_version),
                created_at: sealed.created_at,
            },
            partition,
        ))
        .await
        .expect("committed release succeeds");

    let records = changelog_records(&harness);
    let death = records.last().expect("the death document must be produced");
    assert!(death.is_deleted);
    assert_eq!(death.uuid, person_uuid);
    assert_eq!(
        death.version,
        sealed_version + 1,
        "the death document confirms the direct tombstone at the same version"
    );

    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(op)
        .execute(&pool)
        .await
        .expect("cleanup op");
    sqlx::query("DELETE FROM posthog_person WHERE team_id = $1 AND id = $2")
        .bind(team_id as i32)
        .bind(person_id)
        .execute(&pool)
        .await
        .expect("cleanup person");
}
