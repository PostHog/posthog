// Shared with the other test binaries, which use the helpers this one does not.
#[allow(dead_code)]
mod common;

use std::sync::Arc;
use std::time::{Duration, Instant};

use common::{TestContext, TestPerson};
use personhog_property_store::bytes::Bytes;
use personhog_property_store::object_store::local::LocalFileSystem;
use personhog_property_store::object_store::ObjectStore;
use personhog_property_store::{
    PartitionKey, PropertyReader, PropertyRecord, PropertyStoreConfig, PropertyWriter,
};
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    GetPersonByDistinctIdRequest, GetPersonsByDistinctIdsInTeamRequest,
};
use personhog_replica::service::PersonHogReplicaService;
use tonic::Request;

const STALE_POSTGRES_PROPERTIES: &str = r#"{"plan":"free"}"#;
const SLATEDB_PROPERTIES: &[u8] = br#"{"plan":"paid"}"#;

struct SlatedbReplica {
    ctx: TestContext,
    service: PersonHogReplicaService,
    writer: PropertyWriter,
    _dir: tempfile::TempDir,
}

fn config() -> PropertyStoreConfig {
    PropertyStoreConfig {
        reader_poll_ms: 20,
        ..PropertyStoreConfig::local("props", 1)
    }
}

impl SlatedbReplica {
    async fn new() -> Self {
        let ctx = TestContext::new().await;
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = PropertyWriter::new(&config(), Arc::clone(&store));
        writer.assign(&partition(), 1, 1, || true).await.unwrap();
        let reader = Arc::new(PropertyReader::new(&config(), store));
        let service =
            PersonHogReplicaService::new(ctx.storage.clone()).with_slatedb_properties(reader, 64);
        Self {
            ctx,
            service,
            writer,
            _dir: dir,
        }
    }

    async fn person(&self, distinct_id: &str, version: i64) -> TestPerson {
        let person = self
            .ctx
            .insert_person(
                distinct_id,
                Some(serde_json::from_str(STALE_POSTGRES_PROPERTIES).unwrap()),
            )
            .await
            .unwrap();
        sqlx::query("UPDATE posthog_person SET version = $1 WHERE id = $2")
            .bind(version)
            .bind(person.id)
            .execute(&self.ctx.pool)
            .await
            .unwrap();
        person
    }

    async fn store(&self, person: &TestPerson, version: i64, deleted: bool) {
        self.writer
            .put(
                &partition(),
                1,
                &[PropertyRecord {
                    team_id: self.ctx.team_id,
                    person_id: person.id,
                    version,
                    deleted,
                    created_at: 0,
                    properties: Bytes::from_static(SLATEDB_PROPERTIES),
                }],
            )
            .await
            .unwrap();
    }

    /// Waits until the replica's reader has polled past the last write.
    async fn read_by_distinct_id(
        &self,
        distinct_id: &str,
    ) -> Result<Option<personhog_proto::personhog::types::v1::Person>, tonic::Status> {
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            let read = self
                .service
                .get_person_by_distinct_id(Request::new(GetPersonByDistinctIdRequest {
                    team_id: self.ctx.team_id,
                    distinct_id: distinct_id.to_string(),
                    read_options: None,
                }))
                .await
                .map(|response| response.into_inner().person);
            let behind = matches!(&read, Err(status) if status.code() == tonic::Code::Unavailable);
            if !behind || Instant::now() > deadline {
                return read;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }
}

fn partition() -> PartitionKey {
    PartitionKey {
        topic: Arc::from("changelog"),
        partition: 0,
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn a_person_reads_its_properties_from_slatedb_not_postgres() {
    let replica = SlatedbReplica::new().await;
    let person = replica.person("did-live", 4).await;
    replica.store(&person, 4, false).await;

    let read = replica
        .read_by_distinct_id("did-live")
        .await
        .unwrap()
        .unwrap();

    assert_eq!(read.properties, SLATEDB_PROPERTIES);
    replica.writer.close().await;
    replica.ctx.cleanup().await.unwrap();
}

#[tokio::test(flavor = "multi_thread")]
async fn a_person_slatedb_has_deleted_reads_as_not_found() {
    let replica = SlatedbReplica::new().await;
    let person = replica.person("did-deleted", 4).await;
    replica.store(&person, 4, true).await;

    let single = replica.read_by_distinct_id("did-deleted").await.unwrap();
    let batch = replica
        .service
        .get_persons_by_distinct_ids_in_team(Request::new(GetPersonsByDistinctIdsInTeamRequest {
            team_id: replica.ctx.team_id,
            distinct_ids: vec!["did-deleted".to_string()],
            read_options: None,
        }))
        .await
        .unwrap()
        .into_inner();

    assert!(single.is_none());
    assert!(batch.results[0].person.is_none());
    replica.writer.close().await;
    replica.ctx.cleanup().await.unwrap();
}

#[tokio::test(flavor = "multi_thread")]
async fn a_person_missing_from_slatedb_fails_the_read_rather_than_reading_empty() {
    let replica = SlatedbReplica::new().await;
    replica.person("did-missing", 4).await;

    let status = replica
        .service
        .get_person_by_distinct_id(Request::new(GetPersonByDistinctIdRequest {
            team_id: replica.ctx.team_id,
            distinct_id: "did-missing".to_string(),
            read_options: None,
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::Unavailable);
    replica.writer.close().await;
    replica.ctx.cleanup().await.unwrap();
}
