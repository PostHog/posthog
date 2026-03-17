mod common;

use common::{
    create_client, create_test_person, start_test_leader, start_test_replica, start_test_router,
    start_test_router_with_leader, TestLeaderService, TestReplicaService,
};
use personhog_proto::personhog::leader::v1::UpdatePersonPropertiesRequest;
use personhog_proto::personhog::types::v1::{
    ConsistencyLevel, GetGroupsRequest, GetPersonRequest, GroupIdentifier, ReadOptions,
};

const NUM_PARTITIONS: u32 = 8;

// ============================================================
// Routing behavior tests
// ============================================================

#[tokio::test]
async fn eventual_read_routes_to_replica_not_leader() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());
    let leader_service = TestLeaderService::new(); // empty

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    // Default read (EVENTUAL) should go to replica
    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        })
        .await
        .unwrap();

    let person = response.into_inner().person.unwrap();
    assert_eq!(person.id, test_person.id);
}

#[tokio::test]
async fn strong_read_routes_to_leader() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::new(); // empty
    let leader_service = TestLeaderService::new().with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    // Strong consistency read should go to leader
    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: Some(ReadOptions {
                consistency: ConsistencyLevel::Strong.into(),
            }),
        })
        .await
        .unwrap();

    let person = response.into_inner().person.unwrap();
    assert_eq!(person.id, test_person.id);
}

#[tokio::test]
async fn write_routes_to_leader() {
    let test_person = create_test_person();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"name": "Test User"})).unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
            partition: 0, // will be overwritten by router
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    let person = result.person.unwrap();
    assert_eq!(person.version, test_person.version + 1);
}

#[tokio::test]
async fn write_then_strong_read_roundtrip() {
    let test_person = create_test_person();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    // Write
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

    // Strong read should see the update
    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: Some(ReadOptions {
                consistency: ConsistencyLevel::Strong.into(),
            }),
        })
        .await
        .unwrap();

    let person = response.into_inner().person.unwrap();
    assert_eq!(person.version, test_person.version + 1);

    let props: serde_json::Value = serde_json::from_slice(&person.properties).unwrap();
    assert_eq!(props["email"], "new@example.com");
}

// ============================================================
// Error cases: no leader configured
// ============================================================

#[tokio::test]
async fn write_fails_when_no_leader_configured() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await; // no leader
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
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unimplemented);
}

#[tokio::test]
async fn strong_read_fails_when_no_leader_configured() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await; // no leader
    let mut client = create_client(router_addr).await;

    let result = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: Some(ReadOptions {
                consistency: ConsistencyLevel::Strong.into(),
            }),
        })
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Unimplemented);
}

// ============================================================
// Non-person data always routes to replica
// ============================================================

#[tokio::test]
async fn non_person_data_always_routes_to_replica() {
    let groups = vec![personhog_proto::personhog::types::v1::Group {
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
    let leader_service = TestLeaderService::new(); // empty

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    // Even with Strong consistency, groups go to replica
    let response = client
        .get_groups(GetGroupsRequest {
            team_id: 1,
            group_identifiers: vec![GroupIdentifier {
                group_type_index: 0,
                group_key: "company-abc".to_string(),
            }],
            read_options: Some(ReadOptions {
                consistency: ConsistencyLevel::Strong.into(),
            }),
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.groups.len(), 1);
    assert_eq!(result.groups[0].group_key, "company-abc");
}

// ============================================================
// Leader NotFound
// ============================================================

#[tokio::test]
async fn leader_person_not_found_returns_not_found() {
    let replica_service = TestReplicaService::new();
    let leader_service = TestLeaderService::new(); // empty

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let result = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 999,
            read_options: Some(ReadOptions {
                consistency: ConsistencyLevel::Strong.into(),
            }),
        })
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::NotFound);
}
