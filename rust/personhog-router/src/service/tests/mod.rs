mod mocks;

use std::sync::Arc;

use mocks::MockBackend;
use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogService;
use personhog_proto::personhog::types::v1::{
    ConsistencyLevel, GetPersonByDistinctIdRequest, GetPersonRequest, Person, ReadOptions,
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
        is_user_id: false,
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
    assert!(status.message().contains("personhog-leader"));
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
