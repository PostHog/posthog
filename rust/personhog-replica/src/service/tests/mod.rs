mod mocks;
mod routing;

use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    DeletePersonsRequest, GetGroupRequest, GetPersonRequest, GetPersonsByDistinctIdsInTeamRequest,
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

// ============================================================
// DeletePersons tests
// ============================================================

#[tokio::test]
async fn test_delete_persons_connection_error_returns_unavailable() {
    let storage = Arc::new(FailingStorage::with_connection_error());
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec!["00000000-0000-0000-0000-000000000001".to_string()],
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);
}

#[tokio::test]
async fn test_delete_persons_query_error_returns_internal() {
    let storage = Arc::new(FailingStorage::with_query_error());
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec!["00000000-0000-0000-0000-000000000001".to_string()],
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Internal);
}

#[tokio::test]
async fn test_delete_persons_empty_uuids_returns_zero() {
    let storage = Arc::new(mocks::SuccessStorage);
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec![],
        }))
        .await;

    let response = result.unwrap();
    assert_eq!(response.get_ref().deleted_count, 0);
}

#[tokio::test]
async fn test_delete_persons_too_many_uuids_returns_invalid_argument() {
    let storage = Arc::new(mocks::SuccessStorage);
    let service = PersonHogReplicaService::new(storage);

    let uuids: Vec<String> = (0..1001)
        .map(|i| format!("00000000-0000-0000-0000-{i:012}"))
        .collect();

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: uuids,
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("1000"));
}

#[tokio::test]
async fn test_delete_persons_invalid_uuid_returns_invalid_argument() {
    let storage = Arc::new(mocks::SuccessStorage);
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec!["not-a-valid-uuid".to_string()],
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("Invalid UUID"));
}

#[tokio::test]
async fn test_delete_persons_success() {
    let storage = Arc::new(mocks::SuccessStorage);
    let service = PersonHogReplicaService::new(storage);

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec!["00000000-0000-0000-0000-000000000001".to_string()],
        }))
        .await;

    let response = result.unwrap();
    assert_eq!(response.get_ref().deleted_count, 0); // SuccessStorage returns 0
}

#[tokio::test]
async fn test_delete_persons_exactly_1000_uuids_succeeds() {
    let storage = Arc::new(mocks::SuccessStorage);
    let service = PersonHogReplicaService::new(storage);

    let uuids: Vec<String> = (0..1000)
        .map(|i| format!("00000000-0000-0000-0000-{i:012}"))
        .collect();

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: uuids,
        }))
        .await;

    assert!(result.is_ok());
}
