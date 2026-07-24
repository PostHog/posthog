use chrono::{DateTime, Utc};
use flags_consumer::benchmark::plancheck;
use flags_consumer::storage::{
    postgres::PostgresStorage,
    types::{
        DistinctIdAssignmentData, DistinctIdDeletionData, PersonDeletionData, PersonLookupData,
        PersonUpdateData,
    },
};
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

async fn upsert_person(
    storage: &PostgresStorage,
    team_id: i32,
    person_uuid: Uuid,
    properties: Value,
    version: i64,
) -> u64 {
    storage
        .batch_upsert_persons(&[PersonUpdateData {
            team_id,
            person_uuid,
            properties,
            version,
        }])
        .await
        .unwrap()
}

async fn person_row(
    pool: &PgPool,
    team_id: i32,
    person_uuid: Uuid,
) -> (Value, i64, Option<DateTime<Utc>>) {
    sqlx::query_as(
        "SELECT properties, person_version, deleted_at FROM flags_person WHERE team_id = $1 AND person_uuid = $2",
    )
    .bind(team_id)
    .bind(person_uuid)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn assign_distinct_id(
    storage: &PostgresStorage,
    team_id: i32,
    person_uuid: Uuid,
    distinct_id: &str,
    version: i64,
) -> u64 {
    storage
        .batch_upsert_distinct_ids(&[DistinctIdAssignmentData {
            team_id,
            person_uuid,
            distinct_id: distinct_id.into(),
            version,
        }])
        .await
        .unwrap()
}

async fn delete_distinct_id(
    storage: &PostgresStorage,
    team_id: i32,
    person_uuid: Uuid,
    distinct_id: &str,
    version: i64,
) -> u64 {
    storage
        .batch_delete_distinct_ids(&[DistinctIdDeletionData {
            team_id,
            person_uuid,
            distinct_id: distinct_id.into(),
            version,
        }])
        .await
        .unwrap()
}

#[sqlx::test(migrations = "../flags_read_store_migrations")]
async fn person_write_guards_preserve_newer_state_and_tombstone_ties(pool: PgPool) {
    let storage = PostgresStorage::new(pool.clone());
    let team_id = 1;

    let deleted_person_uuid = Uuid::new_v4();
    let deleted = storage
        .batch_delete_persons(&[PersonDeletionData {
            team_id,
            person_uuid: deleted_person_uuid,
            version: 110,
        }])
        .await
        .unwrap();
    let stale_update = upsert_person(
        &storage,
        team_id,
        deleted_person_uuid,
        json!({ "stale": true }),
        10,
    )
    .await;

    // A tombstone outranks an update carrying the same version, mirroring the delete guard.
    let tied_update = upsert_person(
        &storage,
        team_id,
        deleted_person_uuid,
        json!({ "tied": true }),
        110,
    )
    .await;

    assert_eq!(deleted, 1);
    assert_eq!(stale_update, 0);
    assert_eq!(tied_update, 0);
    let (properties, version, deleted_at) = person_row(&pool, team_id, deleted_person_uuid).await;
    assert_eq!(properties, json!({}));
    assert_eq!(version, 110);
    assert!(deleted_at.is_some());

    let tied_person_uuid = Uuid::new_v4();
    upsert_person(
        &storage,
        team_id,
        tied_person_uuid,
        json!({ "live": true }),
        20,
    )
    .await;
    let equal_version_delete = storage
        .batch_delete_persons(&[PersonDeletionData {
            team_id,
            person_uuid: tied_person_uuid,
            version: 20,
        }])
        .await
        .unwrap();
    assert_eq!(equal_version_delete, 1);
    assert!(person_row(&pool, team_id, tied_person_uuid)
        .await
        .2
        .is_some());

    let live_person_uuid = Uuid::new_v4();
    upsert_person(
        &storage,
        team_id,
        live_person_uuid,
        json!({ "newer": true }),
        30,
    )
    .await;
    let stale_delete = storage
        .batch_delete_persons(&[PersonDeletionData {
            team_id,
            person_uuid: live_person_uuid,
            version: 29,
        }])
        .await
        .unwrap();
    assert_eq!(stale_delete, 0);
    let (properties, version, deleted_at) = person_row(&pool, team_id, live_person_uuid).await;
    assert_eq!(properties, json!({ "newer": true }));
    assert_eq!(version, 30);
    assert!(deleted_at.is_none());
}

#[sqlx::test(migrations = "../flags_read_store_migrations")]
async fn distinct_id_write_guards_are_order_independent(pool: PgPool) {
    let storage = PostgresStorage::new(pool.clone());
    let team_id = 1;
    let old_person_uuid = Uuid::new_v4();
    let new_person_uuid = Uuid::new_v4();
    let new_properties = json!({ "owner": "new" });
    upsert_person(
        &storage,
        team_id,
        old_person_uuid,
        json!({ "owner": "old" }),
        10,
    )
    .await;
    upsert_person(
        &storage,
        team_id,
        new_person_uuid,
        new_properties.clone(),
        11,
    )
    .await;

    assign_distinct_id(&storage, team_id, old_person_uuid, "assign-first", 10).await;
    assign_distinct_id(&storage, team_id, new_person_uuid, "assign-first", 11).await;
    let old_owner_delete =
        delete_distinct_id(&storage, team_id, old_person_uuid, "assign-first", 110).await;
    assert_eq!(old_owner_delete, 0);

    assign_distinct_id(&storage, team_id, old_person_uuid, "delete-first", 10).await;
    delete_distinct_id(&storage, team_id, old_person_uuid, "delete-first", 110).await;
    let replacement =
        assign_distinct_id(&storage, team_id, new_person_uuid, "delete-first", 11).await;
    assert_eq!(replacement, 1);

    for distinct_id in ["assign-first", "delete-first"] {
        assert_eq!(
            storage
                .get_person_by_distinct_id(team_id, distinct_id)
                .await
                .unwrap(),
            Some(PersonLookupData {
                person_uuid: new_person_uuid,
                properties: new_properties.clone(),
            })
        );
    }

    assign_distinct_id(&storage, team_id, old_person_uuid, "version-guard", 20).await;
    let stale_assignment =
        assign_distinct_id(&storage, team_id, old_person_uuid, "version-guard", 19).await;
    let stale_delete =
        delete_distinct_id(&storage, team_id, old_person_uuid, "version-guard", 19).await;
    let tied_delete =
        delete_distinct_id(&storage, team_id, old_person_uuid, "version-guard", 20).await;
    assert_eq!(stale_assignment, 0);
    assert_eq!(stale_delete, 0);
    assert_eq!(tied_delete, 1);
    assert_eq!(
        storage
            .get_person_by_distinct_id(team_id, "version-guard")
            .await
            .unwrap(),
        None
    );
}

/// A tombstone carries the old owner's version plus 100, so a later assignment to a
/// different person only wins while its own version outruns that underlying version.
#[sqlx::test(migrations = "../flags_read_store_migrations")]
async fn cross_owner_assignment_wins_only_against_an_older_tombstone(pool: PgPool) {
    let storage = PostgresStorage::new(pool.clone());
    let team_id = 1;
    let old_person_uuid = Uuid::new_v4();
    let new_person_uuid = Uuid::new_v4();
    upsert_person(&storage, team_id, new_person_uuid, json!({}), 1).await;

    // (assignment version, whether it should replace a tombstone left at owner version 10)
    for (version, expected) in [(9, 0), (10, 0), (11, 1)] {
        let distinct_id = format!("bound-{version}");
        assign_distinct_id(&storage, team_id, old_person_uuid, &distinct_id, 10).await;
        delete_distinct_id(&storage, team_id, old_person_uuid, &distinct_id, 110).await;

        let replacement =
            assign_distinct_id(&storage, team_id, new_person_uuid, &distinct_id, version).await;

        assert_eq!(replacement, expected, "assignment at version {version}");
        assert_eq!(
            storage
                .get_person_by_distinct_id(team_id, &distinct_id)
                .await
                .unwrap()
                .is_some(),
            expected == 1,
            "visibility after assignment at version {version}"
        );
    }
}

#[sqlx::test(migrations = "../flags_read_store_migrations")]
async fn migrated_schema_passes_storage_plan_checks(pool: PgPool) {
    sqlx::query(
        r#"
        INSERT INTO flags_person (team_id, person_uuid, properties, person_version)
        SELECT 1, md5(value::text)::uuid, '{}'::jsonb, 1
        FROM generate_series(1, 10000) AS value
        "#,
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        r#"
        INSERT INTO flags_distinct_id_map (team_id, distinct_id, person_uuid, version)
        SELECT 1, 'seed-' || value, md5(value::text)::uuid, 1
        FROM generate_series(1, 10000) AS value
        "#,
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("ANALYZE flags_person, flags_distinct_id_map")
        .execute(&pool)
        .await
        .unwrap();

    let evidence = plancheck::verify_storage_plans(&pool).await.unwrap();

    assert_eq!(evidence.len(), 5);
    assert_eq!(
        evidence.iter().map(|plan| plan.name).collect::<Vec<_>>(),
        vec![
            "canonical_read",
            "person_upsert",
            "person_tombstone",
            "distinct_id_upsert",
            "distinct_id_tombstone",
        ]
    );
}
