use chrono::{DateTime, Utc};
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

#[sqlx::test(migrations = "../flags_read_store_migrations")]
async fn cross_batch_version_guards_preserve_newer_state(pool: PgPool) {
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
    let stale_update = storage
        .batch_upsert_persons(&[PersonUpdateData {
            team_id,
            person_uuid: deleted_person_uuid,
            properties: json!({ "stale": true }),
            version: 10,
        }])
        .await
        .unwrap();

    assert_eq!(deleted, 1);
    assert_eq!(stale_update, 0);
    let (properties, version, deleted_at): (Value, i64, Option<DateTime<Utc>>) = sqlx::query_as(
        "SELECT properties, person_version, deleted_at FROM flags_person WHERE team_id = $1 AND person_uuid = $2",
    )
    .bind(team_id)
    .bind(deleted_person_uuid)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(properties, json!({}));
    assert_eq!(version, 110);
    assert!(deleted_at.is_some());

    let old_person_uuid = Uuid::new_v4();
    let new_person_uuid = Uuid::new_v4();
    let new_properties = json!({ "owner": "new" });
    storage
        .batch_upsert_persons(&[
            PersonUpdateData {
                team_id,
                person_uuid: old_person_uuid,
                properties: json!({ "owner": "old" }),
                version: 10,
            },
            PersonUpdateData {
                team_id,
                person_uuid: new_person_uuid,
                properties: new_properties.clone(),
                version: 11,
            },
        ])
        .await
        .unwrap();
    storage
        .batch_upsert_distinct_ids(&[DistinctIdAssignmentData {
            team_id,
            person_uuid: old_person_uuid,
            distinct_id: "shared-id".into(),
            version: 10,
        }])
        .await
        .unwrap();
    storage
        .batch_upsert_distinct_ids(&[DistinctIdAssignmentData {
            team_id,
            person_uuid: new_person_uuid,
            distinct_id: "shared-id".into(),
            version: 11,
        }])
        .await
        .unwrap();

    let old_owner_delete = storage
        .batch_delete_distinct_ids(&[DistinctIdDeletionData {
            team_id,
            person_uuid: old_person_uuid,
            distinct_id: "shared-id".into(),
            version: 110,
        }])
        .await
        .unwrap();

    assert_eq!(old_owner_delete, 0);
    assert_eq!(
        storage
            .get_person_by_distinct_id(team_id, "shared-id")
            .await
            .unwrap(),
        Some(PersonLookupData {
            person_uuid: new_person_uuid,
            properties: new_properties,
        })
    );
}
