mod mocks;
mod routing;

use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    DeletePersonsBatchForTeamRequest, DeletePersonsRequest, GetGroupRequest, GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest,
};
use rstest::rstest;
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

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_delete_persons_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec!["00000000-0000-0000-0000-000000000001".to_string()],
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[rstest]
#[case::too_many_uuids(
    (0..1001).map(|i| format!("00000000-0000-0000-0000-{i:012}")).collect(),
    "1000"
)]
#[case::invalid_uuid(vec!["not-a-valid-uuid".to_string()], "Invalid UUID")]
#[tokio::test]
async fn test_delete_persons_invalid_input(
    #[case] person_uuids: Vec<String>,
    #[case] expected_message: &str,
) {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids,
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains(expected_message));
}

#[tokio::test]
async fn test_delete_persons_empty_uuids_returns_zero() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec![],
        }))
        .await;

    assert_eq!(result.unwrap().get_ref().deleted_count, 0);
}

#[rstest]
#[case::single_uuid(vec!["00000000-0000-0000-0000-000000000001".to_string()])]
#[case::exactly_1000((0..1000).map(|i| format!("00000000-0000-0000-0000-{i:012}")).collect())]
#[tokio::test]
async fn test_delete_persons_success(#[case] person_uuids: Vec<String>) {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_persons(Request::new(DeletePersonsRequest {
            team_id: 1,
            person_uuids,
        }))
        .await;

    assert!(result.is_ok());
}

// ============================================================
// DeletePersonsBatchForTeam tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::pool_exhausted(FailingStorage::with_pool_exhausted(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_delete_persons_batch_for_team_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .delete_persons_batch_for_team(Request::new(DeletePersonsBatchForTeamRequest {
            team_id: 1,
            batch_size: 100,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[rstest]
#[case::zero(0)]
#[case::negative(-1)]
#[case::exceeds_max(50001)]
#[tokio::test]
async fn test_delete_persons_batch_for_team_invalid_batch_size(#[case] batch_size: i64) {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .delete_persons_batch_for_team(Request::new(DeletePersonsBatchForTeamRequest {
            team_id: 1,
            batch_size,
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("batch_size"));
}

#[tokio::test]
async fn test_delete_persons_batch_for_team_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_persons_batch_for_team(Request::new(DeletePersonsBatchForTeamRequest {
            team_id: 1,
            batch_size: 1000,
        }))
        .await;

    assert!(result.is_ok());
}
