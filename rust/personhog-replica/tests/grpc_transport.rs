//! gRPC transport smoke tests
//!
//! These tests verify proto serialization works end-to-end by
//! spinning up a real gRPC server and making calls through a client.

mod common;

use common::{TestContext, TestPerson};
use personhog_proto::personhog::replica::v1::person_hog_replica_client::PersonHogReplicaClient;
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplicaServer;
use personhog_proto::personhog::types::v1::{
    GetPersonByUuidRequest, GetPersonRequest, GetPersonsByDistinctIdsInTeamRequest,
};
use personhog_replica::service::PersonHogReplicaService;
use std::net::SocketAddr;
use tokio::net::TcpListener;
use tonic::transport::{Channel, Server};

/// Test context that spins up a real gRPC server and provides a client.
pub struct GrpcTestContext {
    ctx: TestContext,
    pub client: PersonHogReplicaClient<Channel>,
}

impl std::ops::Deref for GrpcTestContext {
    type Target = TestContext;
    fn deref(&self) -> &Self::Target {
        &self.ctx
    }
}

impl GrpcTestContext {
    pub async fn new() -> Self {
        let ctx = TestContext::new().await;
        let service = PersonHogReplicaService::new(ctx.storage.clone());

        // Bind to a random available port
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr: SocketAddr = listener.local_addr().unwrap();

        // Spawn the server
        tokio::spawn(async move {
            Server::builder()
                .add_service(PersonHogReplicaServer::new(service))
                .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        // Give the server a moment to start
        tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;

        // Create client
        let client = PersonHogReplicaClient::connect(format!("http://{addr}"))
            .await
            .expect("Failed to connect to test server");

        Self { ctx, client }
    }

    pub async fn insert_person(
        &self,
        distinct_id: &str,
        properties: Option<serde_json::Value>,
    ) -> Result<TestPerson, sqlx::Error> {
        self.ctx.insert_person(distinct_id, properties).await
    }

    pub async fn cleanup(&self) -> Result<(), sqlx::Error> {
        self.ctx.cleanup().await
    }
}

#[tokio::test]
async fn test_grpc_get_person_roundtrip() {
    let mut ctx = GrpcTestContext::new().await;
    let person = ctx
        .insert_person("grpc_test@example.com", None)
        .await
        .unwrap();
    let team_id = ctx.team_id;
    let person_id = person.id;
    let person_uuid = person.uuid;

    let response = ctx
        .client
        .get_person(GetPersonRequest { team_id, person_id })
        .await
        .expect("gRPC call failed");

    let proto_person = response.into_inner().person.expect("Person should exist");
    assert_eq!(proto_person.id, person_id);
    assert_eq!(proto_person.uuid, person_uuid.to_string());
    assert_eq!(proto_person.team_id, team_id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_grpc_batch_lookup_roundtrip() {
    let mut ctx = GrpcTestContext::new().await;
    let person1 = ctx.insert_person("grpc_batch_1", None).await.unwrap();
    let person2 = ctx.insert_person("grpc_batch_2", None).await.unwrap();
    let team_id = ctx.team_id;
    let person1_id = person1.id;
    let person2_id = person2.id;

    let response = ctx
        .client
        .get_persons_by_distinct_ids_in_team(GetPersonsByDistinctIdsInTeamRequest {
            team_id,
            distinct_ids: vec![
                "grpc_batch_1".to_string(),
                "grpc_batch_2".to_string(),
                "grpc_batch_missing".to_string(),
            ],
        })
        .await
        .expect("gRPC call failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 3);

    let found: Vec<i64> = results
        .iter()
        .filter_map(|r| r.person.as_ref().map(|p| p.id))
        .collect();
    assert!(found.contains(&person1_id));
    assert!(found.contains(&person2_id));
    assert_eq!(found.len(), 2);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_grpc_invalid_uuid_returns_error() {
    let mut ctx = GrpcTestContext::new().await;
    let team_id = ctx.team_id;

    let result = ctx
        .client
        .get_person_by_uuid(GetPersonByUuidRequest {
            team_id,
            uuid: "not-a-valid-uuid".to_string(),
        })
        .await;

    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::InvalidArgument);

    ctx.cleanup().await.ok();
}
