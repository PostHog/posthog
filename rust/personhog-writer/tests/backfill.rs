mod common;

use std::sync::Arc;

use personhog_property_store::object_store::local::LocalFileSystem;
use personhog_property_store::object_store::path::Path as ObjectPath;
use personhog_property_store::object_store::{ObjectStore, ObjectStoreExt, PutPayload};
use personhog_property_store::{
    PropertyReader, PropertyStoreConfig, PropertyWriter, StoredProperties,
};
use personhog_writer::backfill::{self, Counts, Outcome, Progress, Scan};
use sqlx::PgPool;

const PARTITIONS: u32 = 4;
const SHARDS: u32 = 8;

fn store_config() -> PropertyStoreConfig {
    PropertyStoreConfig::local("props", SHARDS)
}

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

async fn stored(
    store: &Arc<dyn ObjectStore>,
    team_id: i64,
    person_id: i64,
) -> Option<StoredProperties> {
    let reader = PropertyReader::new(&store_config(), Arc::clone(store));
    let read = reader.get_fresh(team_id, person_id).await.unwrap();
    reader.close().await;
    read
}

async fn backfill(
    pool: &PgPool,
    store: &Arc<dyn ObjectStore>,
    table: &str,
    team_id: Option<i64>,
    run_id: &str,
    page_size: i64,
) -> Outcome {
    let config = store_config();
    let scan = Scan::new(pool.clone(), table, team_id, page_size).unwrap();
    let writer = PropertyWriter::new(&config, Arc::clone(store));
    let progress = Progress::new(Arc::clone(store), &config.prefix, run_id).unwrap();
    let outcome = backfill::run(&scan, &writer, &progress, "changelog", PARTITIONS, SHARDS)
        .await
        .unwrap();
    writer.close().await;
    outcome
}

#[tokio::test(flavor = "multi_thread")]
async fn a_team_lands_at_its_postgres_versions_and_no_other_team_does() {
    let pool = pool().await;
    let dir = tempfile::tempdir().unwrap();
    let store: Arc<dyn ObjectStore> =
        Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
    let (team, other) = (unique_team(), unique_team());
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
    let deleted = insert(&pool, common::TARGET_TABLE, team, Some(5), true, "{}").await;
    let elsewhere = insert(
        &pool,
        common::TARGET_TABLE,
        other,
        Some(1),
        false,
        r#"{"c": 2}"#,
    )
    .await;

    let outcome = backfill(&pool, &store, common::TARGET_TABLE, Some(team), "full", 2).await;

    let Outcome::Finished(counts) = outcome else {
        panic!("a fresh run reported itself already done");
    };
    assert_eq!(
        counts,
        Counts {
            read: 3,
            written: 3,
            deleted: 1,
            rejected: 0
        }
    );
    let live = stored(&store, team, live).await.unwrap();
    assert_eq!(
        (live.version, live.deleted, &live.properties[..]),
        (3, false, &br#"{"a":1}"#[..])
    );
    let unversioned = stored(&store, team, unversioned).await.unwrap();
    assert_eq!(
        (unversioned.version, &unversioned.properties[..]),
        (0, &br#"{"b":"x"}"#[..])
    );
    let deleted = stored(&store, team, deleted).await.unwrap();
    assert_eq!((deleted.version, deleted.deleted), (5, true));
    assert!(stored(&store, other, elsewhere).await.is_none());
    cleanup(&pool, &[team, other]).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_rerun_resumes_after_its_last_durable_page_and_a_finished_run_does_nothing() {
    let pool = pool().await;
    let dir = tempfile::tempdir().unwrap();
    let store: Arc<dyn ObjectStore> =
        Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
    let team = unique_team();
    let first = insert(
        &pool,
        common::TARGET_TABLE,
        team,
        Some(1),
        false,
        r#"{"n": 1}"#,
    )
    .await;
    let second = insert(
        &pool,
        common::TARGET_TABLE,
        team,
        Some(1),
        false,
        r#"{"n": 2}"#,
    )
    .await;
    let third = insert(
        &pool,
        common::TARGET_TABLE,
        team,
        Some(1),
        false,
        r#"{"n": 3}"#,
    )
    .await;
    store
        .put(
            &ObjectPath::from("props/maintenance/backfill/resumed/cursor"),
            PutPayload::from(
                format!(
                    r#"{{"after_team_id":{team},"after_person_id":{first},"read":1,"written":1,"deleted":0,"rejected":0}}"#
                )
                .into_bytes(),
            ),
        )
        .await
        .unwrap();

    let resumed = backfill(
        &pool,
        &store,
        common::TARGET_TABLE,
        Some(team),
        "resumed",
        1,
    )
    .await;

    let Outcome::Finished(counts) = resumed else {
        panic!("a resumed run reported itself already done");
    };
    assert_eq!(counts.read, 3);
    assert!(
        stored(&store, team, first).await.is_none(),
        "the recorded page was read again"
    );
    assert!(stored(&store, team, second).await.is_some());
    assert!(stored(&store, team, third).await.is_some());

    let again = backfill(
        &pool,
        &store,
        common::TARGET_TABLE,
        Some(team),
        "resumed",
        1,
    )
    .await;
    assert!(matches!(again, Outcome::AlreadyDone(done) if done == counts));
    cleanup(&pool, &[team]).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn without_a_team_every_team_lands_and_a_resume_crosses_into_the_next_team() {
    let pool = pool().await;
    let table = format!("backfill_all_{}", common::unique_team_id());
    sqlx::query(&format!(
        "CREATE TABLE {table} (LIKE personhog_person_tmp INCLUDING DEFAULTS, PRIMARY KEY (team_id, id))"
    ))
    .execute(&pool)
    .await
    .unwrap();
    let dir = tempfile::tempdir().unwrap();
    let store: Arc<dyn ObjectStore> =
        Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
    let first_team_a = insert(&pool, &table, 1, Some(1), false, r#"{"t": "a"}"#).await;
    let last_team_a = insert(&pool, &table, 1, Some(1), false, r#"{"t": "a"}"#).await;
    let first_team_b = insert(&pool, &table, 2, Some(1), false, r#"{"t": "b"}"#).await;
    let last_team_b = insert(&pool, &table, 2, Some(1), false, r#"{"t": "b"}"#).await;
    store
        .put(
            &ObjectPath::from("props/maintenance/backfill/all/cursor"),
            PutPayload::from(
                format!(
                    r#"{{"after_team_id":1,"after_person_id":{first_team_a},"read":1,"written":1,"deleted":0,"rejected":0}}"#
                )
                .into_bytes(),
            ),
        )
        .await
        .unwrap();

    let outcome = backfill(&pool, &store, &table, None, "all", 1).await;

    sqlx::query(&format!("DROP TABLE {table}"))
        .execute(&pool)
        .await
        .unwrap();
    let Outcome::Finished(counts) = outcome else {
        panic!("a resumed run reported itself already done");
    };
    assert_eq!(counts.read, 4);
    assert!(stored(&store, 1, first_team_a).await.is_none());
    for (team, person) in [(1, last_team_a), (2, first_team_b), (2, last_team_b)] {
        assert!(
            stored(&store, team, person).await.is_some(),
            "team {team} person {person}"
        );
    }
}
