mod common;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use personhog_common::partitioning::partition_for_person;
use personhog_property_store::bytes::Bytes;
use personhog_property_store::object_store::local::LocalFileSystem;
use personhog_property_store::object_store::path::Path as ObjectPath;
use personhog_property_store::object_store::{ObjectStore, ObjectStoreExt, PutPayload};
use personhog_property_store::{
    PartitionKey, PropertyReader, PropertyRecord, PropertyStoreConfig, PropertyWriter,
};
use personhog_proto::personhog::types::v1::Person;
use personhog_writer::backfill::scanner::{
    self as backfill, Counts, Cursor, KeyRange, Outcome, Run, Scan, SizeLimits, TopicSink,
};
use personhog_writer::backfill::verify::{Verification, Verifier};
use prost::Message;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::error::KafkaError;
use rdkafka::message::Message as KafkaMessage;
use rdkafka::mocking::MockCluster;
use rdkafka::producer::DefaultProducerContext;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use sqlx::PgPool;

const BACKFILL_TOPIC: &str = "personhog_backfill";
const PARTITIONS: i32 = 4;

fn unique_team() -> i64 {
    i64::from(common::unique_team_id())
}

async fn pool() -> PgPool {
    PgPool::connect(common::PERSONS_DB_URL).await.unwrap()
}

async fn insert(
    pool: &PgPool,
    table: &str,
    team_id: i64,
    version: Option<i64>,
    deleted: bool,
    properties: &str,
) -> i64 {
    sqlx::query_scalar(&format!(
        "INSERT INTO {table} \
         (created_at, properties, team_id, uuid, version, is_deleted) \
         VALUES (now(), $1::jsonb, $2, $3, $4, $5) RETURNING id"
    ))
    .bind(properties)
    .bind(team_id as i32)
    .bind(uuid::Uuid::new_v4())
    .bind(version)
    .bind(deleted)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn cleanup(pool: &PgPool, teams: &[i64]) {
    for team in teams {
        sqlx::query("DELETE FROM personhog_person_tmp WHERE team_id = $1")
            .bind(*team as i32)
            .execute(pool)
            .await
            .unwrap();
    }
}

fn local_store() -> (tempfile::TempDir, Arc<dyn ObjectStore>) {
    let dir = tempfile::tempdir().unwrap();
    let store: Arc<dyn ObjectStore> =
        Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
    (dir, store)
}

async fn mock_topic() -> (MockCluster<'static, DefaultProducerContext>, TopicSink) {
    let (cluster, producer) = common_kafka::test::create_mock_kafka().await;
    cluster.create_topic(BACKFILL_TOPIC, PARTITIONS, 1).unwrap();
    let sink = TopicSink::new(producer, BACKFILL_TOPIC.to_string(), PARTITIONS as u32);
    (cluster, sink)
}

fn published(cluster: &MockCluster<'static, DefaultProducerContext>) -> Vec<(i32, Person)> {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", cluster.bootstrap_servers())
        .set("group.id", "backfill-test-reader")
        .set("enable.partition.eof", "true")
        .create()
        .unwrap();
    let mut tpl = TopicPartitionList::new();
    for partition in 0..PARTITIONS {
        tpl.add_partition_offset(BACKFILL_TOPIC, partition, Offset::Beginning)
            .unwrap();
    }
    consumer.assign(&tpl).unwrap();
    let mut ended = 0;
    let mut records = Vec::new();
    while ended < PARTITIONS {
        match consumer
            .poll(Duration::from_secs(10))
            .expect("the topic keeps reading")
        {
            Ok(message) => records.push((
                message.partition(),
                Person::decode(message.payload().unwrap()).unwrap(),
            )),
            Err(KafkaError::PartitionEOF(_)) => ended += 1,
            Err(e) => panic!("{e}"),
        }
    }
    records
}

fn team_range(team_id: i64) -> KeyRange {
    KeyRange {
        table: common::TARGET_TABLE.to_string(),
        after: Some(Cursor {
            team_id: team_id - 1,
            person_id: i64::MAX,
        }),
        through: Some(Cursor {
            team_id,
            person_id: i64::MAX,
        }),
    }
}

fn limits() -> SizeLimits {
    SizeLimits {
        message_bytes: 1_000_000,
        trim_target: 524_288,
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn rows_reach_the_changelog_partition_at_their_postgres_versions() {
    let pool = pool().await;
    let (_dir, store) = local_store();
    let (cluster, sink) = mock_topic().await;
    let (team, next) = (unique_team(), unique_team());
    let live = insert(
        &pool,
        common::TARGET_TABLE,
        team,
        Some(3),
        false,
        r#"{"a": 1}"#,
    )
    .await;
    let unversioned = insert(
        &pool,
        common::TARGET_TABLE,
        team,
        None,
        false,
        r#"{"b": "x"}"#,
    )
    .await;
    let deleted = insert(
        &pool,
        common::TARGET_TABLE,
        team,
        Some(5),
        true,
        r#"{"c": 1}"#,
    )
    .await;
    insert(&pool, common::TARGET_TABLE, next, Some(1), false, "{}").await;
    let scan = Scan::new(pool.clone(), team_range(team), 2, limits()).unwrap();
    let run = Run::new(Arc::clone(&store), "encoded").unwrap();

    let outcome = backfill::run_range(&scan, &sink, &run.range(0))
        .await
        .unwrap();

    let Outcome::Finished(counts) = outcome else {
        panic!("a fresh range reported itself already done");
    };
    assert_eq!(
        counts,
        Counts {
            read: 3,
            written: 3,
            deleted: 1,
            trimmed: 0,
            rejected: 0
        }
    );
    let by_person: HashMap<i64, (i32, Person)> = published(&cluster)
        .into_iter()
        .map(|(partition, person)| (person.id, (partition, person)))
        .collect();
    assert_eq!(by_person.len(), 3, "only the range's team is published");
    for (id, version, deleted, properties) in [
        (live, 3, false, &br#"{"a":1}"#[..]),
        (unversioned, 0, false, &br#"{"b":"x"}"#[..]),
        (deleted, 5, true, &b""[..]),
    ] {
        let (partition, person) = &by_person[&id];
        assert_eq!(
            *partition as u32,
            partition_for_person(team, id, PARTITIONS as u32)
        );
        assert_eq!(
            (
                person.team_id,
                person.version,
                person.is_deleted,
                &person.properties[..]
            ),
            (team, version, deleted, properties)
        );
    }
    cleanup(&pool, &[team, next]).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_range_resumes_after_its_last_published_page_and_a_finished_range_does_nothing() {
    let pool = pool().await;
    let (_dir, store) = local_store();
    let (cluster, sink) = mock_topic().await;
    let team = unique_team();
    let mut ids = Vec::new();
    for n in 1..=3 {
        let properties = format!(r#"{{"n": {n}}}"#);
        ids.push(
            insert(
                &pool,
                common::TARGET_TABLE,
                team,
                Some(1),
                false,
                &properties,
            )
            .await,
        );
    }
    store
        .put(
            &ObjectPath::from("backfill/resumed/ranges/00000/cursor"),
            PutPayload::from(
                format!(
                    r#"{{"after_team_id":{team},"after_person_id":{},"read":1,"written":1,"deleted":0,"trimmed":0,"rejected":0}}"#,
                    ids[0]
                )
                .into_bytes(),
            ),
        )
        .await
        .unwrap();
    let scan = Scan::new(pool.clone(), team_range(team), 1, limits()).unwrap();
    let run = Run::new(Arc::clone(&store), "resumed").unwrap();

    let resumed = backfill::run_range(&scan, &sink, &run.range(0))
        .await
        .unwrap();
    let again = backfill::run_range(&scan, &sink, &run.range(0))
        .await
        .unwrap();

    let Outcome::Finished(counts) = resumed else {
        panic!("a resumed range reported itself already done");
    };
    assert_eq!(counts.read, 3);
    assert!(matches!(again, Outcome::AlreadyDone(done) if done == counts));
    let mut published: Vec<i64> = published(&cluster).into_iter().map(|(_, p)| p.id).collect();
    published.sort_unstable();
    assert_eq!(
        published,
        ids[1..],
        "the recorded page is not published again"
    );
    cleanup(&pool, &[team]).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn planned_ranges_publish_every_row_of_a_partitioned_table_once() {
    let pool = pool().await;
    let (_dir, store) = local_store();
    let (cluster, sink) = mock_topic().await;
    let table = format!("backfill_plan_{}", common::unique_team_id());
    sqlx::query(&format!(
        "CREATE TABLE {table} (LIKE personhog_person_tmp INCLUDING DEFAULTS, PRIMARY KEY (team_id, id)) \
         PARTITION BY HASH (team_id)"
    ))
    .execute(&pool)
    .await
    .unwrap();
    for remainder in 0..3 {
        sqlx::query(&format!(
            "CREATE TABLE {table}_p{remainder} PARTITION OF {table} \
             FOR VALUES WITH (modulus 3, remainder {remainder})"
        ))
        .execute(&pool)
        .await
        .unwrap();
    }
    sqlx::query(&format!(
        "INSERT INTO {table} (created_at, properties, team_id, uuid, version, is_deleted) \
         SELECT now(), '{{}}'::jsonb, team, gen_random_uuid(), 1, false \
         FROM generate_series(1, 12) team, generate_series(1, 50)"
    ))
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(&format!("ANALYZE {table}"))
        .execute(&pool)
        .await
        .unwrap();
    let run = Run::new(Arc::clone(&store), "planned").unwrap();

    let plan = backfill::plan(&pool, &table, 60).await.unwrap();
    run.save_plan(&plan).await.unwrap();
    let workers = 3;
    for index in 0..workers {
        backfill::run_worker(&pool, &sink, &run, index, workers, 25, limits())
            .await
            .unwrap();
    }

    let expected: i64 = sqlx::query_scalar(&format!("SELECT count(*) FROM {table}"))
        .fetch_one(&pool)
        .await
        .unwrap();
    sqlx::query(&format!("DROP TABLE {table}"))
        .execute(&pool)
        .await
        .unwrap();
    let tables: std::collections::HashSet<_> = plan
        .ranges
        .iter()
        .map(|range| range.table.clone())
        .collect();
    assert_eq!(tables.len(), 3, "each partition is planned on its own");
    assert!(
        plan.ranges.len() > tables.len(),
        "a partition larger than a range is split: {plan:?}"
    );
    let mut seen: HashMap<(i64, i64), usize> = HashMap::new();
    for (_, person) in published(&cluster) {
        *seen.entry((person.team_id, person.id)).or_default() += 1;
    }
    assert_eq!(seen.len() as i64, expected, "every row is published");
    assert!(seen.values().all(|&n| n == 1), "no row is published twice");
    assert!(
        run.save_plan(&plan).await.is_err(),
        "a run keeps the plan its cursors refer to"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn verification_judges_each_person_by_version() {
    let pool = pool().await;
    let team = unique_team();
    let table = common::TARGET_TABLE;
    let matched = insert(&pool, table, team, Some(4), false, r#"{"plan": "paid"}"#).await;
    let differs = insert(&pool, table, team, Some(4), false, r#"{"plan": "paid"}"#).await;
    let behind = insert(&pool, table, team, Some(4), false, "{}").await;
    let _missing = insert(&pool, table, team, Some(4), false, "{}").await;
    let newer = insert(&pool, table, team, Some(4), false, "{}").await;
    let _stub = insert(&pool, table, team, Some(0), false, "{}").await;
    // The leader's bytes as Postgres stored them, which prints these floats as integers.
    let printed = insert(
        &pool,
        table,
        team,
        Some(4),
        false,
        r#"{"n":1.7e18,"m":1.2345678901234568e18}"#,
    )
    .await;
    let big = insert(
        &pool,
        table,
        team,
        Some(4),
        false,
        r#"{"n":9007199254740993}"#,
    )
    .await;
    let huge = insert(
        &pool,
        table,
        team,
        Some(4),
        false,
        r#"{"n":12345678901234567890123}"#,
    )
    .await;
    let (_dir, store) = local_store();
    let config = PropertyStoreConfig {
        reader_poll_ms: 20,
        ..PropertyStoreConfig::local("props", 1)
    };
    let writer = PropertyWriter::new(&config, Arc::clone(&store));
    let key = PartitionKey {
        topic: Arc::from("changelog"),
        partition: 0,
    };
    writer.assign(&key, 1, 1, || true).await.unwrap();
    let record = |id, version, properties: &str| PropertyRecord {
        team_id: team,
        person_id: id,
        version,
        deleted: false,
        created_at: 0,
        properties: Bytes::copy_from_slice(properties.as_bytes()),
    };
    writer
        .put(
            &key,
            1,
            &[
                record(matched, 4, r#"{"plan":"paid"}"#),
                record(differs, 4, r#"{"plan":"free"}"#),
                record(behind, 3, "{}"),
                record(newer, 5, "{}"),
                record(printed, 4, r#"{"n":1.7e18,"m":1.2345678901234568e18}"#),
                record(big, 4, r#"{"n":9007199254740992}"#),
                record(huge, 4, r#"{"n":1.2345678901234568e22}"#),
            ],
        )
        .await
        .unwrap();
    let reader = PropertyReader::new(&config, Arc::clone(&store));
    let deadline = Instant::now() + Duration::from_secs(10);
    while reader.get(team, newer).await.unwrap().map(|s| s.version) != Some(5) {
        assert!(Instant::now() < deadline, "the reader never caught up");
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let run = Run::new(Arc::clone(&store), "verify-test").unwrap();
    run.save_plan(&backfill::Plan {
        ranges: vec![team_range(team)],
    })
    .await
    .unwrap();

    let verification = Verification::new(Arc::clone(&store), "verify-test").unwrap();
    let verifier = Verifier {
        pool: &pool,
        reader: &reader,
        verification: &verification,
        limits: limits(),
    };
    let counts = verifier.run_worker(&run, 0, 1, 1000, 1).await.unwrap();
    assert_eq!(
        (
            counts.checked,
            counts.matched,
            counts.differs,
            counts.behind,
            counts.missing,
            counts.newer_in_slatedb,
        ),
        (9, 4, 2, 1, 1, 1)
    );
    assert_eq!(
        verifier.run_worker(&run, 0, 1, 1000, 1).await.unwrap(),
        counts,
        "a finished range is reported, not redone"
    );

    reader.close().await;
    writer.close().await;
    cleanup(&pool, &[team]).await;
}
