mod mocks;

use std::sync::Arc;

use mocks::MockBackend;
use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogService;
use personhog_proto::personhog::types::v1::{
    ConsistencyLevel, CreateGroupRequest, DeleteGroupTypeMappingRequest,
    DeleteGroupTypeMappingsBatchForTeamRequest, DeleteGroupsBatchForTeamRequest,
    DeletePersonsRequest, GetPersonByDistinctIdRequest, GetPersonRequest, Person, ReadOptions,
    UpdateGroupRequest, UpdateGroupTypeMappingRequest,
};
use tonic::{Request, Status};

use crate::router::PersonHogRouter;

use super::PersonHogRouterService;

fn create_test_person() -> Person {
    Person {
        id: 1,
        team_id: 1,
        uuid: "00000000-0000-0000-0000-000000000001".to_string(),
        properties: b"{}".to_vec(),
        properties_last_updated_at: vec![],
        properties_last_operation: vec![],
        created_at: 0,
        version: 1,
        is_identified: true,
        is_user_id: None,
        last_seen_at: None,
    }
}

fn create_service_with_mock(mock: MockBackend) -> PersonHogRouterService {
    let router = PersonHogRouter::new(Arc::new(mock));
    PersonHogRouterService::new(Arc::new(router))
}

#[tokio::test]
async fn test_get_person_routes_to_replica_with_eventual_consistency() {
    let mock = MockBackend::new();
    mock.set_person_response(Some(create_test_person()));

    let service = create_service_with_mock(mock);

    let request = Request::new(GetPersonRequest {
        team_id: 1,
        person_id: 1,
        read_options: None, // Defaults to EVENTUAL
    });

    let response = service.get_person(request).await.unwrap();
    assert!(response.get_ref().person.is_some());
    assert_eq!(response.get_ref().person.as_ref().unwrap().id, 1);
}

#[tokio::test]
async fn test_get_person_returns_none_when_not_found() {
    let mock = MockBackend::new();
    mock.set_person_response(None);

    let service = create_service_with_mock(mock);

    let request = Request::new(GetPersonRequest {
        team_id: 1,
        person_id: 999,
        read_options: None,
    });

    let response = service.get_person(request).await.unwrap();
    assert!(response.get_ref().person.is_none());
}

#[tokio::test]
async fn test_get_person_by_distinct_id_routes_to_replica() {
    let mock = MockBackend::new();
    mock.set_person_response(Some(create_test_person()));

    let service = create_service_with_mock(mock);

    let request = Request::new(GetPersonByDistinctIdRequest {
        team_id: 1,
        distinct_id: "user-123".to_string(),
        read_options: None,
    });

    let response = service.get_person_by_distinct_id(request).await.unwrap();
    assert!(response.get_ref().person.is_some());
}

#[tokio::test]
async fn test_backend_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(GetPersonRequest {
        team_id: 1,
        person_id: 1,
        read_options: None,
    });

    let result = service.get_person(request).await;
    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);
}

#[tokio::test]
async fn test_get_person_with_strong_consistency_returns_unimplemented() {
    let mock = MockBackend::new();
    mock.set_person_response(Some(create_test_person()));

    let service = create_service_with_mock(mock);

    let request = Request::new(GetPersonRequest {
        team_id: 1,
        person_id: 1,
        read_options: Some(ReadOptions {
            consistency: ConsistencyLevel::Strong.into(),
        }),
    });

    let result = service.get_person(request).await;
    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unimplemented);
    assert!(status.message().contains("leader"));
}

#[tokio::test]
async fn test_get_person_with_explicit_eventual_consistency_succeeds() {
    let mock = MockBackend::new();
    mock.set_person_response(Some(create_test_person()));

    let service = create_service_with_mock(mock);

    let request = Request::new(GetPersonRequest {
        team_id: 1,
        person_id: 1,
        read_options: Some(ReadOptions {
            consistency: ConsistencyLevel::Eventual.into(),
        }),
    });

    let response = service.get_person(request).await.unwrap();
    assert!(response.get_ref().person.is_some());
}

// ============================================================
// DeletePersons tests
// ============================================================

#[tokio::test]
async fn test_delete_persons_routes_to_replica() {
    let mock = MockBackend::new();
    let service = create_service_with_mock(mock);

    let request = Request::new(DeletePersonsRequest {
        team_id: 1,
        person_uuids: vec!["00000000-0000-0000-0000-000000000001".to_string()],
    });

    let response = service.delete_persons(request).await.unwrap();
    assert_eq!(response.get_ref().deleted_count, 0);
}

#[tokio::test]
async fn test_delete_persons_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(DeletePersonsRequest {
        team_id: 1,
        person_uuids: vec!["00000000-0000-0000-0000-000000000001".to_string()],
    });

    let result = service.delete_persons(request).await;
    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);
}

// ============================================================
// CreateGroup tests
// ============================================================

#[tokio::test]
async fn test_create_group_routes_to_replica() {
    let mock = MockBackend::new();
    let service = create_service_with_mock(mock);

    let request = Request::new(CreateGroupRequest {
        team_id: 1,
        group_type_index: 0,
        group_key: "test-group".to_string(),
        group_properties: b"{}".to_vec(),
        created_at: Some(1700000000000),
    });

    let response = service.create_group(request).await.unwrap();
    assert!(response.get_ref().group.is_none());
}

#[tokio::test]
async fn test_create_group_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(CreateGroupRequest {
        team_id: 1,
        group_type_index: 0,
        group_key: "test-group".to_string(),
        group_properties: b"{}".to_vec(),
        created_at: Some(1700000000000),
    });

    let result = service.create_group(request).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
}

// ============================================================
// UpdateGroup tests
// ============================================================

#[tokio::test]
async fn test_update_group_routes_to_replica() {
    let mock = MockBackend::new();
    let service = create_service_with_mock(mock);

    let request = Request::new(UpdateGroupRequest {
        team_id: 1,
        group_type_index: 0,
        group_key: "test-group".to_string(),
        update_mask: vec!["group_properties".to_string()],
        group_properties: Some(b"{}".to_vec()),
        ..Default::default()
    });

    let response = service.update_group(request).await.unwrap();
    assert!(!response.get_ref().updated);
}

#[tokio::test]
async fn test_update_group_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(UpdateGroupRequest {
        team_id: 1,
        group_type_index: 0,
        group_key: "test-group".to_string(),
        update_mask: vec!["group_properties".to_string()],
        group_properties: Some(b"{}".to_vec()),
        ..Default::default()
    });

    let result = service.update_group(request).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
}

// ============================================================
// DeleteGroupsBatchForTeam tests
// ============================================================

#[tokio::test]
async fn test_delete_groups_batch_for_team_routes_to_replica() {
    let mock = MockBackend::new();
    let service = create_service_with_mock(mock);

    let request = Request::new(DeleteGroupsBatchForTeamRequest {
        team_id: 1,
        batch_size: 1000,
    });

    let response = service.delete_groups_batch_for_team(request).await.unwrap();
    assert_eq!(response.get_ref().deleted_count, 0);
}

#[tokio::test]
async fn test_delete_groups_batch_for_team_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(DeleteGroupsBatchForTeamRequest {
        team_id: 1,
        batch_size: 1000,
    });

    let result = service.delete_groups_batch_for_team(request).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
}

// ============================================================
// UpdateGroupTypeMapping tests
// ============================================================

#[tokio::test]
async fn test_update_group_type_mapping_routes_to_replica() {
    let mock = MockBackend::new();
    let service = create_service_with_mock(mock);

    let request = Request::new(UpdateGroupTypeMappingRequest {
        project_id: 1,
        group_type_index: 0,
        update_mask: vec!["name_singular".to_string()],
        name_singular: Some("Company".to_string()),
        name_plural: None,
        detail_dashboard_id: None,
        default_columns: None,
    });

    let response = service.update_group_type_mapping(request).await.unwrap();
    assert!(response.get_ref().mapping.is_none());
}

#[tokio::test]
async fn test_update_group_type_mapping_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(UpdateGroupTypeMappingRequest {
        project_id: 1,
        group_type_index: 0,
        update_mask: vec!["name_singular".to_string()],
        name_singular: Some("Company".to_string()),
        name_plural: None,
        detail_dashboard_id: None,
        default_columns: None,
    });

    let result = service.update_group_type_mapping(request).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
}

// ============================================================
// DeleteGroupTypeMapping tests
// ============================================================

#[tokio::test]
async fn test_delete_group_type_mapping_routes_to_replica() {
    let mock = MockBackend::new();
    let service = create_service_with_mock(mock);

    let request = Request::new(DeleteGroupTypeMappingRequest {
        project_id: 1,
        group_type_index: 0,
    });

    let response = service.delete_group_type_mapping(request).await.unwrap();
    assert!(!response.get_ref().deleted);
}

#[tokio::test]
async fn test_delete_group_type_mapping_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(DeleteGroupTypeMappingRequest {
        project_id: 1,
        group_type_index: 0,
    });

    let result = service.delete_group_type_mapping(request).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
}

// ============================================================
// DeleteGroupTypeMappingsBatchForTeam tests
// ============================================================

#[tokio::test]
async fn test_delete_group_type_mappings_batch_for_team_routes_to_replica() {
    let mock = MockBackend::new();
    let service = create_service_with_mock(mock);

    let request = Request::new(DeleteGroupTypeMappingsBatchForTeamRequest {
        team_id: 1,
        batch_size: 1000,
    });

    let response = service
        .delete_group_type_mappings_batch_for_team(request)
        .await
        .unwrap();
    assert_eq!(response.get_ref().deleted_count, 0);
}

#[tokio::test]
async fn test_delete_group_type_mappings_batch_for_team_error_passthrough() {
    let mock = MockBackend::new();
    mock.set_error(Status::unavailable("backend unavailable"));

    let service = create_service_with_mock(mock);

    let request = Request::new(DeleteGroupTypeMappingsBatchForTeamRequest {
        team_id: 1,
        batch_size: 1000,
    });

    let result = service
        .delete_group_type_mappings_batch_for_team(request)
        .await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
}
