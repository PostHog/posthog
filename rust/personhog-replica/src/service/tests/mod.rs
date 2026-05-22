mod mocks;
mod routing;

use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    CountCohortMembersRequest, CreateGroupRequest, DeleteCohortMemberRequest,
    DeleteCohortMembersBulkRequest, DeleteGroupTypeMappingRequest,
    DeleteGroupTypeMappingsBatchForTeamRequest, DeleteGroupsBatchForTeamRequest,
    DeletePersonsBatchForTeamRequest, DeletePersonsRequest, GetGroupRequest, GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest, InsertCohortMembersRequest, ListCohortMemberIdsRequest,
    UpdateGroupRequest, UpdateGroupTypeMappingRequest,
};
use rstest::rstest;
use tonic::Request;

use mocks::FailingStorage;

use super::{PersonHogReplicaService, MAX_BATCH_DELETE_SIZE};

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
#[case::exceeds_max(MAX_BATCH_DELETE_SIZE + 1)]
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

// ============================================================
// CountCohortMembers tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_count_cohort_members_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .count_cohort_members(Request::new(CountCohortMembersRequest {
            cohort_ids: vec![1],
            read_options: None,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_count_cohort_members_empty_cohort_ids_returns_zero() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .count_cohort_members(Request::new(CountCohortMembersRequest {
            cohort_ids: vec![],
            read_options: None,
        }))
        .await;

    assert_eq!(result.unwrap().get_ref().count, 0);
}

#[tokio::test]
async fn test_count_cohort_members_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .count_cohort_members(Request::new(CountCohortMembersRequest {
            cohort_ids: vec![1, 2, 3],
            read_options: None,
        }))
        .await;

    assert!(result.is_ok());
}

// ============================================================
// DeleteCohortMember tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::pool_exhausted(FailingStorage::with_pool_exhausted(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_delete_cohort_member_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .delete_cohort_member(Request::new(DeleteCohortMemberRequest {
            cohort_id: 1,
            person_id: 42,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_delete_cohort_member_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_cohort_member(Request::new(DeleteCohortMemberRequest {
            cohort_id: 1,
            person_id: 42,
        }))
        .await;

    let response = result.unwrap().into_inner();
    assert!(!response.deleted);
}

// ============================================================
// DeleteCohortMembersBulk tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::pool_exhausted(FailingStorage::with_pool_exhausted(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_delete_cohort_members_bulk_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .delete_cohort_members_bulk(Request::new(DeleteCohortMembersBulkRequest {
            cohort_ids: vec![1],
            batch_size: 1000,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[rstest]
#[case::zero(0)]
#[case::negative(-1)]
#[case::exceeds_max(10001)]
#[tokio::test]
async fn test_delete_cohort_members_bulk_invalid_batch_size(#[case] batch_size: i32) {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .delete_cohort_members_bulk(Request::new(DeleteCohortMembersBulkRequest {
            cohort_ids: vec![1],
            batch_size,
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("batch_size"));
}

#[tokio::test]
async fn test_delete_cohort_members_bulk_empty_cohort_ids_returns_zero() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_cohort_members_bulk(Request::new(DeleteCohortMembersBulkRequest {
            cohort_ids: vec![],
            batch_size: 1000,
        }))
        .await;

    assert_eq!(result.unwrap().get_ref().deleted_count, 0);
}

#[tokio::test]
async fn test_delete_cohort_members_bulk_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_cohort_members_bulk(Request::new(DeleteCohortMembersBulkRequest {
            cohort_ids: vec![1, 2],
            batch_size: 5000,
        }))
        .await;

    assert!(result.is_ok());
}

// ============================================================
// InsertCohortMembers tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::pool_exhausted(FailingStorage::with_pool_exhausted(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_insert_cohort_members_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .insert_cohort_members(Request::new(InsertCohortMembersRequest {
            cohort_id: 1,
            person_ids: vec![42],
            version: None,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_insert_cohort_members_too_many_person_ids() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .insert_cohort_members(Request::new(InsertCohortMembersRequest {
            cohort_id: 1,
            person_ids: (0..10001).collect(),
            version: None,
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("10000"));
}

#[tokio::test]
async fn test_insert_cohort_members_empty_person_ids_returns_zero() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .insert_cohort_members(Request::new(InsertCohortMembersRequest {
            cohort_id: 1,
            person_ids: vec![],
            version: None,
        }))
        .await;

    assert_eq!(result.unwrap().get_ref().inserted_count, 0);
}

#[rstest]
#[case::single_person(vec![42])]
#[case::exactly_10000((0..10000).collect())]
#[tokio::test]
async fn test_insert_cohort_members_success(#[case] person_ids: Vec<i64>) {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let expected_count = person_ids.len() as i64;
    let result = service
        .insert_cohort_members(Request::new(InsertCohortMembersRequest {
            cohort_id: 1,
            person_ids,
            version: Some(1),
        }))
        .await;

    assert_eq!(result.unwrap().get_ref().inserted_count, expected_count);
}

// ============================================================
// ListCohortMemberIds tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_list_cohort_member_ids_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .list_cohort_member_ids(Request::new(ListCohortMemberIdsRequest {
            cohort_id: 1,
            cursor: 0,
            limit: 100,
            read_options: None,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_list_cohort_member_ids_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .list_cohort_member_ids(Request::new(ListCohortMemberIdsRequest {
            cohort_id: 1,
            cursor: 0,
            limit: 100,
            read_options: None,
        }))
        .await;

    let response = result.unwrap().into_inner();
    assert!(response.person_ids.is_empty());
    assert_eq!(response.next_cursor, 0);
}

#[tokio::test]
async fn test_list_cohort_member_ids_clamps_invalid_limit() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .list_cohort_member_ids(Request::new(ListCohortMemberIdsRequest {
            cohort_id: 1,
            cursor: 0,
            limit: 0,
            read_options: None,
        }))
        .await;

    assert!(result.is_ok());
}

// ============================================================
// CreateGroup tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_create_group_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .create_group(Request::new(CreateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            group_properties: b"{}".to_vec(),
            created_at: Some(1000),
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_create_group_invalid_timestamp() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .create_group(Request::new(CreateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            group_properties: b"{}".to_vec(),
            created_at: Some(i64::MIN),
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("created_at"));
}

#[tokio::test]
async fn test_create_group_invalid_json() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .create_group(Request::new(CreateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            group_properties: b"not json".to_vec(),
            created_at: Some(1000),
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("group_properties"));
}

#[tokio::test]
async fn test_create_group_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .create_group(Request::new(CreateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            group_properties: b"{}".to_vec(),
            created_at: Some(1000),
        }))
        .await;

    let response = result.unwrap().into_inner();
    assert!(response.group.is_some());
}

#[tokio::test]
async fn test_create_group_defaults_created_at_to_now() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .create_group(Request::new(CreateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            group_properties: b"{}".to_vec(),
            created_at: None,
        }))
        .await;

    let response = result.unwrap().into_inner();
    assert!(response.group.is_some());
}

// ============================================================
// UpdateGroup tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_update_group_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .update_group(Request::new(UpdateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            update_mask: vec!["group_properties".to_string()],
            group_properties: Some(b"{}".to_vec()),
            ..Default::default()
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_update_group_invalid_json() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .update_group(Request::new(UpdateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            update_mask: vec!["group_properties".to_string()],
            group_properties: Some(b"bad".to_vec()),
            ..Default::default()
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
}

#[tokio::test]
async fn test_update_group_invalid_mask_field() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .update_group(Request::new(UpdateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            update_mask: vec!["nonexistent_field".to_string()],
            ..Default::default()
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
}

#[tokio::test]
async fn test_update_group_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .update_group(Request::new(UpdateGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test-key".to_string(),
            update_mask: vec!["group_properties".to_string()],
            group_properties: Some(b"{}".to_vec()),
            ..Default::default()
        }))
        .await;

    let response = result.unwrap().into_inner();
    assert!(!response.updated);
}

// ============================================================
// DeleteGroupsBatchForTeam tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::pool_exhausted(FailingStorage::with_pool_exhausted(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_delete_groups_batch_for_team_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .delete_groups_batch_for_team(Request::new(DeleteGroupsBatchForTeamRequest {
            team_id: 1,
            batch_size: 100,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[rstest]
#[case::zero(0)]
#[case::negative(-1)]
#[case::exceeds_max(MAX_BATCH_DELETE_SIZE + 1)]
#[tokio::test]
async fn test_delete_groups_batch_for_team_invalid_batch_size(#[case] batch_size: i64) {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .delete_groups_batch_for_team(Request::new(DeleteGroupsBatchForTeamRequest {
            team_id: 1,
            batch_size,
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("batch_size"));
}

#[tokio::test]
async fn test_delete_groups_batch_for_team_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_groups_batch_for_team(Request::new(DeleteGroupsBatchForTeamRequest {
            team_id: 1,
            batch_size: 1000,
        }))
        .await;

    assert!(result.is_ok());
}

// ============================================================
// UpdateGroupTypeMapping tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_update_group_type_mapping_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .update_group_type_mapping(Request::new(UpdateGroupTypeMappingRequest {
            project_id: 1,
            group_type_index: 0,
            update_mask: vec!["name_singular".to_string()],
            name_singular: Some("Company".to_string()),
            name_plural: None,
            detail_dashboard_id: None,
            default_columns: None,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_update_group_type_mapping_invalid_mask_field() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .update_group_type_mapping(Request::new(UpdateGroupTypeMappingRequest {
            project_id: 1,
            group_type_index: 0,
            update_mask: vec!["invalid_field".to_string()],
            name_singular: None,
            name_plural: None,
            detail_dashboard_id: None,
            default_columns: None,
        }))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("invalid_field"));
}

#[tokio::test]
async fn test_update_group_type_mapping_not_found() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .update_group_type_mapping(Request::new(UpdateGroupTypeMappingRequest {
            project_id: 999,
            group_type_index: 0,
            update_mask: vec!["name_singular".to_string()],
            name_singular: Some("Company".to_string()),
            name_plural: None,
            detail_dashboard_id: None,
            default_columns: None,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), tonic::Code::NotFound);
}

// ============================================================
// DeleteGroupTypeMapping tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::pool_exhausted(FailingStorage::with_pool_exhausted(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_delete_group_type_mapping_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .delete_group_type_mapping(Request::new(DeleteGroupTypeMappingRequest {
            project_id: 1,
            group_type_index: 0,
        }))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[tokio::test]
async fn test_delete_group_type_mapping_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_group_type_mapping(Request::new(DeleteGroupTypeMappingRequest {
            project_id: 1,
            group_type_index: 0,
        }))
        .await;

    let response = result.unwrap().into_inner();
    assert!(!response.deleted);
}

// ============================================================
// DeleteGroupTypeMappingsBatchForTeam tests
// ============================================================

#[rstest]
#[case::connection_error(FailingStorage::with_connection_error(), tonic::Code::Unavailable)]
#[case::pool_exhausted(FailingStorage::with_pool_exhausted(), tonic::Code::Unavailable)]
#[case::query_error(FailingStorage::with_query_error(), tonic::Code::Internal)]
#[tokio::test]
async fn test_delete_group_type_mappings_batch_for_team_storage_error(
    #[case] storage: FailingStorage,
    #[case] expected_code: tonic::Code,
) {
    let service = PersonHogReplicaService::new(Arc::new(storage));

    let result = service
        .delete_group_type_mappings_batch_for_team(Request::new(
            DeleteGroupTypeMappingsBatchForTeamRequest {
                team_id: 1,
                batch_size: 100,
            },
        ))
        .await;

    assert_eq!(result.unwrap_err().code(), expected_code);
}

#[rstest]
#[case::zero(0)]
#[case::negative(-1)]
#[case::exceeds_max(MAX_BATCH_DELETE_SIZE + 1)]
#[tokio::test]
async fn test_delete_group_type_mappings_batch_for_team_invalid_batch_size(
    #[case] batch_size: i64,
) {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let status = service
        .delete_group_type_mappings_batch_for_team(Request::new(
            DeleteGroupTypeMappingsBatchForTeamRequest {
                team_id: 1,
                batch_size,
            },
        ))
        .await
        .unwrap_err();

    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("batch_size"));
}

#[tokio::test]
async fn test_delete_group_type_mappings_batch_for_team_success() {
    let service = PersonHogReplicaService::new(Arc::new(mocks::SuccessStorage));

    let result = service
        .delete_group_type_mappings_batch_for_team(Request::new(
            DeleteGroupTypeMappingsBatchForTeamRequest {
                team_id: 1,
                batch_size: 1000,
            },
        ))
        .await;

    assert!(result.is_ok());
}
