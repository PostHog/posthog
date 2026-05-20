mod common;

use common::{
    create_client, create_test_person, start_test_leader, start_test_replica,
    start_test_router_raw, start_test_router_raw_with_leader,
    start_test_router_raw_with_leader_and_max_recv, start_test_router_raw_with_max_recv,
    TestLeaderService, TestReplicaService,
};
use personhog_proto::personhog::service::v1::person_hog_service_client::PersonHogServiceClient;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembership, ConsistencyLevel, DeletePersonsRequest,
    GetGroupTypeMappingsByTeamIdRequest, GetGroupsRequest, GetHashKeyOverrideContextRequest,
    GetPersonByDistinctIdRequest, GetPersonByUuidRequest, GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest, Group, GroupIdentifier, GroupTypeMapping,
    HashKeyOverride, HashKeyOverrideContext, Person, PersonWithDistinctIds, ReadOptions,
    UpdatePersonPropertiesRequest,
};
use tonic::transport::Channel;
use tonic::Request;

const NUM_PARTITIONS: u32 = 8;

fn with_consistency<T>(req: T, consistency: &str) -> Request<T> {
    let mut request = Request::new(req);
    request
        .metadata_mut()
        .insert("x-read-consistency", consistency.parse().unwrap());
    request
}

// ============================================================
// 1. Replica routing — raw byte pass-through
// ============================================================

#[tokio::test]
async fn raw_proxy_eventual_get_person_routes_to_replica() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "eventual",
        ))
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_get_person_default_routes_to_replica() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());
    let leader_service = TestLeaderService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        })
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_get_person_by_distinct_id_routes_to_replica() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person_by_distinct_id(with_consistency(
            GetPersonByDistinctIdRequest {
                team_id: 1,
                distinct_id: "test-distinct-id".to_string(),
                read_options: None,
            },
            "eventual",
        ))
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_get_groups_routes_to_replica() {
    let groups = vec![Group {
        id: 1,
        team_id: 1,
        group_type_index: 0,
        group_key: "company-abc".to_string(),
        group_properties: b"{}".to_vec(),
        properties_last_updated_at: vec![],
        properties_last_operation: vec![],
        created_at: 0,
        version: 1,
    }];
    let replica_service = TestReplicaService::new().with_groups(groups);
    let leader_service = TestLeaderService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_groups(with_consistency(
            GetGroupsRequest {
                team_id: 1,
                group_identifiers: vec![GroupIdentifier {
                    group_type_index: 0,
                    group_key: "company-abc".to_string(),
                }],
                read_options: None,
            },
            "eventual",
        ))
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.groups.len(), 1);
    assert_eq!(result.groups[0].group_key, "company-abc");
}

#[tokio::test]
async fn raw_proxy_check_cohort_membership_routes_to_replica() {
    let memberships = vec![CohortMembership {
        cohort_id: 1,
        is_member: true,
    }];
    let replica_service = TestReplicaService::new().with_cohort_memberships(memberships.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .check_cohort_membership(CheckCohortMembershipRequest {
            person_id: 42,
            cohort_ids: vec![1],
            read_options: None,
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.memberships.len(), 1);
    assert_eq!(result.memberships[0].cohort_id, 1);
    assert!(result.memberships[0].is_member);
}

#[tokio::test]
async fn raw_proxy_delete_persons_routes_to_replica() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .delete_persons(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec!["00000000-0000-0000-0000-000000000042".to_string()],
        })
        .await;

    assert!(response.is_ok());
}

// ============================================================
// 2. Leader routing — typed deserialization
// ============================================================

#[tokio::test]
async fn raw_proxy_strong_get_person_routes_to_leader() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::new();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "strong",
        ))
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_update_person_properties_routes_to_leader() {
    let test_person = create_test_person();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"name": "Test User"})).unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
            partition: 0,
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    assert_eq!(result.person.unwrap().version, test_person.version + 1);
}

#[tokio::test]
async fn raw_proxy_write_then_strong_read_roundtrip() {
    let test_person = create_test_person();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"email": "new@example.com"}))
                .unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
            partition: 0,
        })
        .await
        .unwrap();

    let response = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "strong",
        ))
        .await
        .unwrap();

    let person = response.into_inner().person.unwrap();
    assert_eq!(person.version, test_person.version + 1);

    let props: serde_json::Value = serde_json::from_slice(&person.properties).unwrap();
    assert_eq!(props["email"], "new@example.com");
}

// ============================================================
// 3. Error cases — no leader configured
// ============================================================

#[tokio::test]
async fn raw_proxy_strong_get_person_no_leader_returns_unimplemented() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let result = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "strong",
        ))
        .await;

    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unimplemented);
    assert!(status.message().contains("leader"));
}

#[tokio::test]
async fn raw_proxy_update_person_properties_no_leader_returns_unimplemented() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let result = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: vec![],
            set_once_properties: vec![],
            unset_properties: vec![],
            partition: 0,
        })
        .await;

    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unimplemented);
    assert!(status.message().contains("leader"));
}

// ============================================================
// 4. Behavioral parity with typed path — replica
// ============================================================

/// Shared fixture: starts a replica with rich test data and both router types.
/// Returns (typed_client, raw_client).
async fn parity_replica_fixture(
    replica_service: TestReplicaService,
) -> (
    PersonHogServiceClient<Channel>,
    PersonHogServiceClient<Channel>,
) {
    let replica_addr = start_test_replica(replica_service).await;
    let typed_addr = common::start_test_router(replica_addr).await;
    let raw_addr = start_test_router_raw(replica_addr).await;
    (
        create_client(typed_addr).await,
        create_client(raw_addr).await,
    )
}

fn complex_properties() -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "email": "test@example.com",
        "nested": {"deeply": {"value": 42}},
        "unicode": "日本語テスト",
        "special_chars": "quotes\"and\\backslashes",
        "empty_string": "",
        "null_value": null,
        "array": [1, "two", true],
    }))
    .unwrap()
}

#[tokio::test]
async fn parity_get_person_with_complex_properties() {
    let person = Person {
        properties: complex_properties(),
        properties_last_updated_at: br#"{"email":1700000000,"nested":1700000001}"#.to_vec(),
        properties_last_operation: br#"{"email":"$set"}"#.to_vec(),
        ..create_test_person()
    };
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::with_person(person)).await;

    let req = || GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: None,
    };

    let t = typed.get_person(req()).await.unwrap().into_inner();
    let r = raw.get_person(req()).await.unwrap().into_inner();
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_get_person_not_found() {
    let (mut typed, mut raw) = parity_replica_fixture(TestReplicaService::new()).await;

    let req = || GetPersonRequest {
        team_id: 1,
        person_id: 999,
        read_options: None,
    };

    let t = typed.get_person(req()).await.unwrap().into_inner();
    let r = raw.get_person(req()).await.unwrap().into_inner();
    assert!(t.person.is_none());
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_get_person_by_distinct_id() {
    let person = Person {
        properties: complex_properties(),
        ..create_test_person()
    };
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::with_person(person)).await;

    let req = || GetPersonByDistinctIdRequest {
        team_id: 1,
        distinct_id: "user-abc".to_string(),
        read_options: None,
    };

    let t = typed
        .get_person_by_distinct_id(req())
        .await
        .unwrap()
        .into_inner();
    let r = raw
        .get_person_by_distinct_id(req())
        .await
        .unwrap()
        .into_inner();
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_get_person_by_uuid() {
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::with_person(create_test_person())).await;

    let req = || GetPersonByUuidRequest {
        team_id: 1,
        uuid: "00000000-0000-0000-0000-000000000042".to_string(),
        read_options: None,
    };

    let t = typed.get_person_by_uuid(req()).await.unwrap().into_inner();
    let r = raw.get_person_by_uuid(req()).await.unwrap().into_inner();
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_get_persons_by_distinct_ids_in_team() {
    let persons = vec![
        PersonWithDistinctIds {
            distinct_id: "user-1".to_string(),
            person: Some(create_test_person()),
        },
        PersonWithDistinctIds {
            distinct_id: "user-2".to_string(),
            person: None,
        },
    ];
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::new().with_persons_by_distinct_id(persons))
            .await;

    let req = || GetPersonsByDistinctIdsInTeamRequest {
        team_id: 1,
        distinct_ids: vec!["user-1".to_string(), "user-2".to_string()],
        read_options: None,
    };

    let t = typed
        .get_persons_by_distinct_ids_in_team(req())
        .await
        .unwrap()
        .into_inner();
    let r = raw
        .get_persons_by_distinct_ids_in_team(req())
        .await
        .unwrap()
        .into_inner();
    assert_eq!(t.results.len(), 2);
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_get_groups_multiple() {
    let groups = vec![
        Group {
            id: 1,
            team_id: 1,
            group_type_index: 0,
            group_key: "company-abc".to_string(),
            group_properties: complex_properties(),
            properties_last_updated_at: vec![],
            properties_last_operation: vec![],
            created_at: 1700000000,
            version: 3,
        },
        Group {
            id: 2,
            team_id: 1,
            group_type_index: 1,
            group_key: "project-xyz".to_string(),
            group_properties: b"{}".to_vec(),
            properties_last_updated_at: vec![],
            properties_last_operation: vec![],
            created_at: 1700000001,
            version: 1,
        },
    ];
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::new().with_groups(groups)).await;

    let req = || GetGroupsRequest {
        team_id: 1,
        group_identifiers: vec![
            GroupIdentifier {
                group_type_index: 0,
                group_key: "company-abc".to_string(),
            },
            GroupIdentifier {
                group_type_index: 1,
                group_key: "project-xyz".to_string(),
            },
        ],
        read_options: None,
    };

    let t = typed.get_groups(req()).await.unwrap().into_inner();
    let r = raw.get_groups(req()).await.unwrap().into_inner();
    assert_eq!(t.groups.len(), 2);
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_get_group_type_mappings_by_team_id() {
    let mappings = vec![
        GroupTypeMapping {
            id: 1,
            team_id: 1,
            project_id: 100,
            group_type: "company".to_string(),
            group_type_index: 0,
            name_singular: Some("Company".to_string()),
            name_plural: Some("Companies".to_string()),
            default_columns: None,
            detail_dashboard_id: Some(42),
            created_at: Some(1700000000),
        },
        GroupTypeMapping {
            id: 2,
            team_id: 1,
            project_id: 100,
            group_type: "project".to_string(),
            group_type_index: 1,
            name_singular: None,
            name_plural: None,
            default_columns: Some(b"[\"name\"]".to_vec()),
            detail_dashboard_id: None,
            created_at: None,
        },
    ];
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::new().with_group_type_mappings(mappings)).await;

    let req = || GetGroupTypeMappingsByTeamIdRequest {
        team_id: 1,
        read_options: None,
    };

    let t = typed
        .get_group_type_mappings_by_team_id(req())
        .await
        .unwrap()
        .into_inner();
    let r = raw
        .get_group_type_mappings_by_team_id(req())
        .await
        .unwrap()
        .into_inner();
    assert_eq!(t.mappings.len(), 2);
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_check_cohort_membership_multiple() {
    let memberships = vec![
        CohortMembership {
            cohort_id: 1,
            is_member: true,
        },
        CohortMembership {
            cohort_id: 2,
            is_member: false,
        },
        CohortMembership {
            cohort_id: 3,
            is_member: true,
        },
    ];
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::new().with_cohort_memberships(memberships))
            .await;

    let req = || CheckCohortMembershipRequest {
        person_id: 42,
        cohort_ids: vec![1, 2, 3],
        read_options: None,
    };

    let t = typed
        .check_cohort_membership(req())
        .await
        .unwrap()
        .into_inner();
    let r = raw
        .check_cohort_membership(req())
        .await
        .unwrap()
        .into_inner();
    assert_eq!(t.memberships.len(), 3);
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_get_hash_key_override_context() {
    let contexts = vec![HashKeyOverrideContext {
        person_id: 42,
        distinct_id: "user-abc".to_string(),
        overrides: vec![HashKeyOverride {
            feature_flag_key: "flag-1".to_string(),
            hash_key: "override-key".to_string(),
        }],
        existing_feature_flag_keys: vec!["flag-1".to_string(), "flag-2".to_string()],
    }];
    let (mut typed, mut raw) =
        parity_replica_fixture(TestReplicaService::new().with_hash_key_override_contexts(contexts))
            .await;

    let req = || GetHashKeyOverrideContextRequest {
        team_id: 1,
        distinct_ids: vec!["user-abc".to_string()],
        check_person_exists: false,
        read_options: None,
    };

    let t = typed
        .get_hash_key_override_context(req())
        .await
        .unwrap()
        .into_inner();
    let r = raw
        .get_hash_key_override_context(req())
        .await
        .unwrap()
        .into_inner();
    assert_eq!(t.results.len(), 1);
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_delete_persons() {
    let (mut typed, mut raw) = parity_replica_fixture(TestReplicaService::new()).await;

    let req = || DeletePersonsRequest {
        team_id: 1,
        person_uuids: vec!["00000000-0000-0000-0000-000000000042".to_string()],
    };

    let t = typed.delete_persons(req()).await.unwrap().into_inner();
    let r = raw.delete_persons(req()).await.unwrap().into_inner();
    assert_eq!(t, r);
}

// ============================================================
// 5. Behavioral parity with typed path — leader
// ============================================================

#[tokio::test]
async fn parity_leader_strong_get_person() {
    let person = Person {
        properties: complex_properties(),
        ..create_test_person()
    };
    let leader_service = TestLeaderService::new().with_person(person);
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let typed_addr =
        common::start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let raw_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut typed = create_client(typed_addr).await;
    let mut raw = create_client(raw_addr).await;

    let typed_req = GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: Some(ReadOptions {
            consistency: ConsistencyLevel::Strong.into(),
        }),
    };
    let raw_req = with_consistency(
        GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        },
        "strong",
    );

    let t = typed.get_person(typed_req).await.unwrap().into_inner();
    let r = raw.get_person(raw_req).await.unwrap().into_inner();
    assert_eq!(t, r);
}

#[tokio::test]
async fn parity_leader_update_person_properties() {
    let leader_service = TestLeaderService::new().with_person(create_test_person());
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let typed_addr =
        common::start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let raw_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut typed = create_client(typed_addr).await;
    let mut raw = create_client(raw_addr).await;

    let req = || UpdatePersonPropertiesRequest {
        team_id: 1,
        person_id: 42,
        event_name: "$set".to_string(),
        set_properties: serde_json::to_vec(&serde_json::json!({"name": "Test"})).unwrap(),
        set_once_properties: vec![],
        unset_properties: vec![],
        partition: 0,
    };

    let t = typed
        .update_person_properties(req())
        .await
        .unwrap()
        .into_inner();
    let r = raw
        .update_person_properties(req())
        .await
        .unwrap()
        .into_inner();
    assert!(t.updated);
    assert!(r.updated);
    // Both should have version 2 (incremented from 1), but they hit the same
    // leader so the second call sees version 2 and produces version 3.
    // Compare structure: both should have person with updated=true.
    assert_eq!(t.updated, r.updated);
    assert!(t.person.is_some());
    assert!(r.person.is_some());
}

#[tokio::test]
async fn parity_leader_person_not_found() {
    let leader_service = TestLeaderService::new();
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let typed_addr =
        common::start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let raw_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut typed = create_client(typed_addr).await;
    let mut raw = create_client(raw_addr).await;

    let typed_req = GetPersonRequest {
        team_id: 1,
        person_id: 999,
        read_options: Some(ReadOptions {
            consistency: ConsistencyLevel::Strong.into(),
        }),
    };
    let raw_req = with_consistency(
        GetPersonRequest {
            team_id: 1,
            person_id: 999,
            read_options: None,
        },
        "strong",
    );

    let t = typed.get_person(typed_req).await;
    let r = raw.get_person(raw_req).await;
    assert!(t.is_err());
    assert!(r.is_err());
    assert_eq!(t.unwrap_err().code(), r.unwrap_err().code());
}

// ============================================================
// 6. Request body size limits
// ============================================================

#[tokio::test]
async fn raw_proxy_rejects_oversized_replica_request() {
    let replica_service = TestReplicaService::new();
    let replica_addr = start_test_replica(replica_service).await;
    // 1 KiB limit — small enough that a normal-looking request can exceed it
    let router_addr = start_test_router_raw_with_max_recv(replica_addr, 1024).await;
    let mut client = create_client(router_addr).await;

    let result = client
        .get_persons_by_distinct_ids_in_team(GetPersonsByDistinctIdsInTeamRequest {
            team_id: 1,
            distinct_ids: (0..200).map(|i| format!("distinct-id-{i:0>50}")).collect(),
            read_options: None,
        })
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::ResourceExhausted);
}

#[tokio::test]
async fn raw_proxy_rejects_oversized_leader_request() {
    let replica_service = TestReplicaService::new();
    let leader_service = TestLeaderService::new().with_person(create_test_person());

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr = start_test_router_raw_with_leader_and_max_recv(
        replica_addr,
        leader_addr,
        NUM_PARTITIONS,
        1024,
    )
    .await;
    let mut client = create_client(router_addr).await;

    let oversized_props = vec![0u8; 2048];
    let result = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: oversized_props,
            set_once_properties: vec![],
            unset_properties: vec![],
            partition: 0,
        })
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::ResourceExhausted);
}

#[tokio::test]
async fn raw_proxy_accepts_request_within_limit() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());
    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw_with_max_recv(replica_addr, 1024).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        })
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}
