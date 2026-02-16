mod mocks;
mod routing;

use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    GetGroupRequest, GetPersonRequest, GetPersonsByDistinctIdsInTeamRequest,
};
use tonic::Request;

use mocks::FailingStorage;

use super::PersonHogReplicaService;

#[tokio::test]
async fn test_connection_error_returns_unavailable() {
    let storage = Arc::new(FailingStorage::with_connection_error());
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .get_person(Request::new(GetPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: None,
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.message().contains("Database unavailable"));
    assert!(status.message().contains("connection refused"));
}

#[tokio::test]
async fn test_pool_exhausted_returns_unavailable() {
    let storage = Arc::new(FailingStorage::with_pool_exhausted());
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .get_person(Request::new(GetPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: None,
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.message().contains("pool exhausted"));
}

#[tokio::test]
async fn test_query_error_returns_internal() {
    let storage = Arc::new(FailingStorage::with_query_error());
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .get_person(Request::new(GetPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: None,
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Internal);
    assert!(status.message().contains("Database error"));
    assert!(status.message().contains("syntax error"));
}

#[tokio::test]
async fn test_connection_error_on_batch_operation_returns_unavailable() {
    let storage = Arc::new(FailingStorage::with_connection_error());
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .get_persons_by_distinct_ids_in_team(Request::new(GetPersonsByDistinctIdsInTeamRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string(), "user2".to_string()],
            read_options: None,
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);
}

#[tokio::test]
async fn test_query_error_on_group_operation_returns_internal() {
    let storage = Arc::new(FailingStorage::with_query_error());
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .get_group(Request::new(GetGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test".to_string(),
            read_options: None,
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Internal);
}
