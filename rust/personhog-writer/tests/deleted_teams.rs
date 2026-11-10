mod common;

use std::sync::Arc;

use personhog_property_store::bytes::Bytes;
use personhog_property_store::object_store::local::LocalFileSystem;
use personhog_property_store::object_store::ObjectStore;
use personhog_property_store::{
    PartitionKey, PropertyReader, PropertyRecord, PropertyStoreConfig, PropertyWriter,
};
use personhog_writer::deleted_teams;

#[tokio::test(flavor = "multi_thread")]
async fn a_listed_team_is_erased_from_the_owned_shards() {
    let pool = common::create_test_pool().await;
    let deleted = i64::from(common::unique_team_id());
    let kept = i64::from(common::unique_team_id());
    sqlx::query("INSERT INTO personhog_deleted_teams (team_id) VALUES ($1) ON CONFLICT DO NOTHING")
        .bind(deleted as i32)
        .execute(&pool)
        .await
        .unwrap();
    let dir = tempfile::tempdir().unwrap();
    let store: Arc<dyn ObjectStore> =
        Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
    let config = PropertyStoreConfig::local("props", 2);
    let writer = PropertyWriter::new(&config, Arc::clone(&store));
    let key = PartitionKey {
        topic: Arc::from("changelog"),
        partition: 0,
    };
    writer.assign(&key, 1, 1, || true).await.unwrap();
    let record = |team_id, person_id| PropertyRecord {
        team_id,
        person_id,
        version: 1,
        deleted: false,
        created_at: 0,
        properties: Bytes::from_static(b"{}"),
    };
    writer
        .put(
            &key,
            1,
            &[record(deleted, 1), record(deleted, 2), record(kept, 1)],
        )
        .await
        .unwrap();

    let erased = deleted_teams::erase_listed(&pool, &writer).await.unwrap();

    assert_eq!(erased, 2, "only the listed team's keys go");
    let reader = PropertyReader::new(&config, store);
    assert_eq!(reader.get_fresh(deleted, 1).await.unwrap(), None);
    assert_eq!(reader.get_fresh(deleted, 2).await.unwrap(), None);
    assert!(reader.get_fresh(kept, 1).await.unwrap().is_some());

    sqlx::query("DELETE FROM personhog_deleted_teams WHERE team_id = $1")
        .bind(deleted as i32)
        .execute(&pool)
        .await
        .unwrap();
    reader.close().await;
    writer.close().await;
}
