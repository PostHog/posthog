mod common;

use common::{
    create_client, create_test_person, start_test_replica, start_test_router, TestReplicaService,
};
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembership, ConsistencyLevel,
    GetGroupTypeMappingsByProjectIdRequest, GetGroupTypeMappingsByTeamIdRequest, GetGroupsRequest,
    GetHashKeyOverrideContextRequest, GetPersonByDistinctIdRequest, GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest, Group, GroupIdentifier, GroupTypeMapping,
    HashKeyOverride, HashKeyOverrideContext, HashKeyOverrideInput, Person, PersonWithDistinctIds,
    ReadOptions, UpsertHashKeyOverridesRequest,
};

#[tokio::test]
async fn test_get_person_roundtrip() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        })
        .await
        .unwrap();

    let person = response.into_inner().person;
    assert!(person.is_some());
    let person = person.unwrap();
    assert_eq!(person.id, test_person.id);
    assert_eq!(person.team_id, test_person.team_id);
    assert_eq!(person.uuid, test_person.uuid);
}

#[tokio::test]
async fn test_get_person_by_distinct_id_roundtrip() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person_by_distinct_id(GetPersonByDistinctIdRequest {
            team_id: 1,
            distinct_id: "user@example.com".to_string(),
            read_options: None,
        })
        .await
        .unwrap();

    let person = response.into_inner().person;
    assert!(person.is_some());
    let person = person.unwrap();
    assert_eq!(person.id, test_person.id);
}

#[tokio::test]
async fn test_get_person_not_found() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 999,
            read_options: None,
        })
        .await
        .unwrap();

    let person = response.into_inner().person;
    assert!(person.is_none());
}

// ============================================================
// Feature-flags behavior pattern tests
// ============================================================

/// Tests batch person lookup by distinct IDs within a team.
/// Feature-flags uses this to resolve multiple distinct IDs to persons in a single call.
#[tokio::test]
async fn test_get_persons_by_distinct_ids_in_team() {
    let test_person = Person {
        id: 42,
        team_id: 1,
        uuid: "00000000-0000-0000-0000-000000000042".to_string(),
        properties: b"{}".to_vec(),
        properties_last_updated_at: vec![],
        properties_last_operation: vec![],
        created_at: 0,
        version: 1,
        is_identified: true,
        is_user_id: false,
    };

    // Each PersonWithDistinctIds maps one distinct_id to one person
    let person_with_distinct_id = PersonWithDistinctIds {
        distinct_id: "user@example.com".to_string(),
        person: Some(test_person),
    };

    let replica_service =
        TestReplicaService::new().with_persons_by_distinct_id(vec![person_with_distinct_id]);

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_persons_by_distinct_ids_in_team(GetPersonsByDistinctIdsInTeamRequest {
            team_id: 1,
            distinct_ids: vec!["user@example.com".to_string()],
            read_options: None,
        })
        .await
        .unwrap();

    let results = response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].distinct_id, "user@example.com");
    assert!(results[0].person.is_some());
    assert_eq!(results[0].person.as_ref().unwrap().id, 42);
}

/// Tests cohort membership check - a batch operation that checks if a person
/// belongs to multiple cohorts at once.
/// Feature-flags uses this for cohort-based targeting.
#[tokio::test]
async fn test_check_cohort_membership() {
    let memberships = vec![
        CohortMembership {
            cohort_id: 100,
            is_member: true,
        },
        CohortMembership {
            cohort_id: 200,
            is_member: false,
        },
        CohortMembership {
            cohort_id: 300,
            is_member: true,
        },
    ];

    let replica_service = TestReplicaService::new().with_cohort_memberships(memberships);

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .check_cohort_membership(CheckCohortMembershipRequest {
            person_id: 42,
            cohort_ids: vec![100, 200, 300],
            read_options: None,
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.memberships.len(), 3);

    // Verify specific membership results
    let cohort_100 = result.memberships.iter().find(|m| m.cohort_id == 100);
    assert!(cohort_100.is_some());
    assert!(cohort_100.unwrap().is_member);

    let cohort_200 = result.memberships.iter().find(|m| m.cohort_id == 200);
    assert!(cohort_200.is_some());
    assert!(!cohort_200.unwrap().is_member);
}

/// Tests cohort membership for non-existent person returns empty (not error).
/// Feature-flags expects this behavior for graceful degradation.
#[tokio::test]
async fn test_check_cohort_membership_empty() {
    let replica_service = TestReplicaService::new(); // No memberships configured

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .check_cohort_membership(CheckCohortMembershipRequest {
            person_id: 999, // Non-existent person
            cohort_ids: vec![100, 200],
            read_options: None,
        })
        .await
        .unwrap();

    // Should succeed with empty memberships, not error
    let result = response.into_inner();
    assert!(result.memberships.is_empty());
}

/// Tests hash key override context lookup for experience continuity.
/// Feature-flags uses this to maintain consistent flag experiences across distinct IDs.
#[tokio::test]
async fn test_get_hash_key_override_context() {
    let contexts = vec![HashKeyOverrideContext {
        person_id: 42,
        distinct_id: "user@example.com".to_string(),
        overrides: vec![
            HashKeyOverride {
                feature_flag_key: "beta-feature".to_string(),
                hash_key: "consistent-hash-key".to_string(),
            },
            HashKeyOverride {
                feature_flag_key: "experiment-1".to_string(),
                hash_key: "experiment-hash".to_string(),
            },
        ],
        existing_feature_flag_keys: vec!["beta-feature".to_string(), "experiment-1".to_string()],
    }];

    let replica_service = TestReplicaService::new().with_hash_key_override_contexts(contexts);

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_hash_key_override_context(GetHashKeyOverrideContextRequest {
            team_id: 1,
            distinct_ids: vec!["user@example.com".to_string()],
            check_person_exists: false,
            read_options: None,
        })
        .await
        .unwrap();

    let results = response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].distinct_id, "user@example.com");
    assert_eq!(results[0].person_id, 42);
    assert_eq!(results[0].overrides.len(), 2);
}

/// Tests upsert hash key overrides - a write operation for experience continuity.
/// Returns the count of newly inserted overrides (ON CONFLICT DO NOTHING behavior).
#[tokio::test]
async fn test_upsert_hash_key_overrides() {
    let replica_service = TestReplicaService::new().with_upsert_inserted_count(3);

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .upsert_hash_key_overrides(UpsertHashKeyOverridesRequest {
            team_id: 1,
            overrides: vec![
                HashKeyOverrideInput {
                    person_id: 42,
                    feature_flag_key: "flag-1".to_string(),
                },
                HashKeyOverrideInput {
                    person_id: 42,
                    feature_flag_key: "flag-2".to_string(),
                },
                HashKeyOverrideInput {
                    person_id: 42,
                    feature_flag_key: "flag-3".to_string(),
                },
            ],
            hash_key: "consistent-hash".to_string(),
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.inserted_count, 3);
}

/// Tests batch group lookup.
/// Feature-flags uses this to resolve group properties for group-based targeting.
#[tokio::test]
async fn test_get_groups() {
    let groups = vec![
        Group {
            id: 1,
            team_id: 1,
            group_type_index: 0,
            group_key: "company-abc".to_string(),
            group_properties: b"{\"name\": \"Acme Corp\", \"plan\": \"enterprise\"}".to_vec(),
            properties_last_updated_at: vec![],
            properties_last_operation: vec![],
            created_at: 0,
            version: 1,
        },
        Group {
            id: 2,
            team_id: 1,
            group_type_index: 1,
            group_key: "project-xyz".to_string(),
            group_properties: b"{\"name\": \"Secret Project\"}".to_vec(),
            properties_last_updated_at: vec![],
            properties_last_operation: vec![],
            created_at: 0,
            version: 1,
        },
    ];

    let replica_service = TestReplicaService::new().with_groups(groups);

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_groups(GetGroupsRequest {
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
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.groups.len(), 2);
    assert!(result.missing_groups.is_empty());

    // Verify group data
    let company = result.groups.iter().find(|g| g.group_key == "company-abc");
    assert!(company.is_some());
    assert_eq!(company.unwrap().group_type_index, 0);
}

/// Tests group lookup when groups are not found returns empty (not error).
#[tokio::test]
async fn test_get_groups_not_found() {
    let replica_service = TestReplicaService::new(); // No groups configured

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_groups(GetGroupsRequest {
            team_id: 1,
            group_identifiers: vec![GroupIdentifier {
                group_type_index: 0,
                group_key: "nonexistent".to_string(),
            }],
            read_options: None,
        })
        .await
        .unwrap();

    // Should succeed with empty groups, not error
    let result = response.into_inner();
    assert!(result.groups.is_empty());
}

/// Tests group type mappings lookup by team ID.
/// Feature-flags uses this to map group type names to indices.
#[tokio::test]
async fn test_get_group_type_mappings_by_team_id() {
    let mappings = vec![
        GroupTypeMapping {
            id: 1,
            team_id: 1,
            project_id: 1,
            group_type: "company".to_string(),
            group_type_index: 0,
            name_singular: Some("company".to_string()),
            name_plural: Some("companies".to_string()),
            default_columns: None,
            detail_dashboard_id: None,
            created_at: None,
        },
        GroupTypeMapping {
            id: 2,
            team_id: 1,
            project_id: 1,
            group_type: "project".to_string(),
            group_type_index: 1,
            name_singular: Some("project".to_string()),
            name_plural: Some("projects".to_string()),
            default_columns: None,
            detail_dashboard_id: None,
            created_at: None,
        },
    ];

    let replica_service = TestReplicaService::new().with_group_type_mappings(mappings);

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_group_type_mappings_by_team_id(GetGroupTypeMappingsByTeamIdRequest {
            team_id: 1,
            read_options: None,
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.mappings.len(), 2);

    let company_mapping = result.mappings.iter().find(|m| m.group_type == "company");
    assert!(company_mapping.is_some());
    assert_eq!(company_mapping.unwrap().group_type_index, 0);
}

/// Tests that Unspecified consistency level routes to replica (same as Eventual).
#[tokio::test]
async fn test_get_person_with_unspecified_consistency() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: Some(ReadOptions {
                consistency: ConsistencyLevel::Unspecified.into(),
            }),
        })
        .await
        .unwrap();

    let person = response.into_inner().person;
    assert!(person.is_some());
    assert_eq!(person.unwrap().id, test_person.id);
}

/// Tests group type mappings lookup by project ID.
#[tokio::test]
async fn test_get_group_type_mappings_by_project_id() {
    let mappings = vec![
        GroupTypeMapping {
            id: 1,
            team_id: 1,
            project_id: 100,
            group_type: "organization".to_string(),
            group_type_index: 0,
            name_singular: Some("organization".to_string()),
            name_plural: Some("organizations".to_string()),
            default_columns: None,
            detail_dashboard_id: None,
            created_at: None,
        },
        GroupTypeMapping {
            id: 2,
            team_id: 1,
            project_id: 100,
            group_type: "workspace".to_string(),
            group_type_index: 1,
            name_singular: Some("workspace".to_string()),
            name_plural: Some("workspaces".to_string()),
            default_columns: None,
            detail_dashboard_id: None,
            created_at: None,
        },
    ];

    let replica_service = TestReplicaService::new().with_group_type_mappings(mappings);

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_group_type_mappings_by_project_id(GetGroupTypeMappingsByProjectIdRequest {
            project_id: 100,
            read_options: None,
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.mappings.len(), 2);

    let org_mapping = result
        .mappings
        .iter()
        .find(|m| m.group_type == "organization");
    assert!(org_mapping.is_some());
    assert_eq!(org_mapping.unwrap().group_type_index, 0);
    assert_eq!(org_mapping.unwrap().project_id, 100);
}
