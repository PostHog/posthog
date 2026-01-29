mod common;

use common::TestContext;
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, DeleteHashKeyOverridesByTeamsRequest,
    GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonsRequest, GetGroupRequest,
    GetGroupTypeMappingsByProjectIdRequest, GetGroupTypeMappingsByProjectIdsRequest,
    GetGroupTypeMappingsByTeamIdRequest, GetGroupTypeMappingsByTeamIdsRequest,
    GetGroupsBatchRequest, GetGroupsRequest, GetHashKeyOverrideContextRequest,
    GetPersonByDistinctIdRequest, GetPersonByUuidRequest, GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest, GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest,
    GetPersonsRequest, GroupIdentifier, GroupKey, HashKeyOverrideInput, TeamDistinctId,
    UpsertHashKeyOverridesRequest,
};
use personhog_replica::service::PersonHogReplicaService;
use tonic::Request;

/// Test context that wraps TestContext and adds a service instance.
pub struct ServiceTestContext {
    ctx: TestContext,
    pub service: PersonHogReplicaService,
}

impl std::ops::Deref for ServiceTestContext {
    type Target = TestContext;
    fn deref(&self) -> &Self::Target {
        &self.ctx
    }
}

impl ServiceTestContext {
    pub async fn new() -> Self {
        let ctx = TestContext::new().await;
        let service = PersonHogReplicaService::new(ctx.storage.clone());
        Self { ctx, service }
    }

    pub async fn cleanup(&self) -> Result<(), sqlx::Error> {
        self.ctx.cleanup().await
    }
}

// ============================================================
// Person lookup tests
// ============================================================

#[tokio::test]
async fn test_get_person_returns_person_when_found() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("test@example.com", None).await.unwrap();

    let response = ctx
        .service
        .get_person(Request::new(GetPersonRequest {
            team_id: ctx.team_id,
            person_id: person.id,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let proto_person = response
        .into_inner()
        .person
        .expect("Person should be present");
    assert_eq!(proto_person.id, person.id);
    assert_eq!(proto_person.uuid, person.uuid.to_string());
    assert_eq!(proto_person.team_id, ctx.team_id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_person_returns_none_when_not_found() {
    let ctx = ServiceTestContext::new().await;

    let response = ctx
        .service
        .get_person(Request::new(GetPersonRequest {
            team_id: ctx.team_id,
            person_id: 999999999,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    assert!(response.into_inner().person.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_person_by_uuid_returns_person() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx
        .insert_person("uuid_test@example.com", None)
        .await
        .unwrap();

    let response = ctx
        .service
        .get_person_by_uuid(Request::new(GetPersonByUuidRequest {
            team_id: ctx.team_id,
            uuid: person.uuid.to_string(),
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let proto_person = response
        .into_inner()
        .person
        .expect("Person should be present");
    assert_eq!(proto_person.id, person.id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_person_by_uuid_invalid_uuid_returns_error() {
    let ctx = ServiceTestContext::new().await;

    let result = ctx
        .service
        .get_person_by_uuid(Request::new(GetPersonByUuidRequest {
            team_id: ctx.team_id,
            uuid: "not-a-valid-uuid".to_string(),
            read_options: None,
        }))
        .await;

    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::InvalidArgument);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_returns_found_and_missing() {
    let ctx = ServiceTestContext::new().await;
    let person1 = ctx.insert_person("batch1@example.com", None).await.unwrap();
    let person2 = ctx.insert_person("batch2@example.com", None).await.unwrap();
    let missing_id = 999999999i64;

    let response = ctx
        .service
        .get_persons(Request::new(GetPersonsRequest {
            team_id: ctx.team_id,
            person_ids: vec![person1.id, person2.id, missing_id],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let inner = response.into_inner();
    assert_eq!(inner.persons.len(), 2);
    assert_eq!(inner.missing_ids, vec![missing_id]);

    ctx.cleanup().await.ok();
}

// ============================================================
// Distinct ID lookup tests
// ============================================================

#[tokio::test]
async fn test_get_person_by_distinct_id_returns_person() {
    let ctx = ServiceTestContext::new().await;
    let distinct_id = "unique_distinct_id_123";
    let person = ctx.insert_person(distinct_id, None).await.unwrap();

    let response = ctx
        .service
        .get_person_by_distinct_id(Request::new(GetPersonByDistinctIdRequest {
            team_id: ctx.team_id,
            distinct_id: distinct_id.to_string(),
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let proto_person = response
        .into_inner()
        .person
        .expect("Person should be present");
    assert_eq!(proto_person.id, person.id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_in_team() {
    let ctx = ServiceTestContext::new().await;
    let person1 = ctx.insert_person("did_1", None).await.unwrap();
    let person2 = ctx.insert_person("did_2", None).await.unwrap();

    let response = ctx
        .service
        .get_persons_by_distinct_ids_in_team(Request::new(GetPersonsByDistinctIdsInTeamRequest {
            team_id: ctx.team_id,
            distinct_ids: vec![
                "did_1".to_string(),
                "did_2".to_string(),
                "did_missing".to_string(),
            ],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 3);

    let found_ids: Vec<i64> = results
        .iter()
        .filter_map(|r| r.person.as_ref().map(|p| p.id))
        .collect();
    assert!(found_ids.contains(&person1.id));
    assert!(found_ids.contains(&person2.id));

    let missing = results
        .iter()
        .find(|r| r.distinct_id == "did_missing")
        .unwrap();
    assert!(missing.person.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_cross_team() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("cross_team_did", None).await.unwrap();

    let response = ctx
        .service
        .get_persons_by_distinct_ids(Request::new(GetPersonsByDistinctIdsRequest {
            team_distinct_ids: vec![
                TeamDistinctId {
                    team_id: ctx.team_id,
                    distinct_id: "cross_team_did".to_string(),
                },
                TeamDistinctId {
                    team_id: ctx.team_id,
                    distinct_id: "nonexistent".to_string(),
                },
            ],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 2);

    let found = results
        .iter()
        .find(|r| r.key.as_ref().map(|k| k.distinct_id.as_str()) == Some("cross_team_did"))
        .unwrap();
    assert_eq!(found.person.as_ref().unwrap().id, person.id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_distinct_ids_for_person() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("primary_did", None).await.unwrap();

    let response = ctx
        .service
        .get_distinct_ids_for_person(Request::new(GetDistinctIdsForPersonRequest {
            team_id: ctx.team_id,
            person_id: person.id,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let distinct_ids = response.into_inner().distinct_ids;
    assert_eq!(distinct_ids.len(), 1);
    assert_eq!(distinct_ids[0].distinct_id, "primary_did");

    ctx.cleanup().await.ok();
}

// ============================================================
// Group tests
// ============================================================

#[tokio::test]
async fn test_get_group_returns_group_when_found() {
    let ctx = ServiceTestContext::new().await;
    ctx.insert_group(0, "company_abc", None).await.unwrap();

    let response = ctx
        .service
        .get_group(Request::new(GetGroupRequest {
            team_id: ctx.team_id,
            group_type_index: 0,
            group_key: "company_abc".to_string(),
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let group = response
        .into_inner()
        .group
        .expect("Group should be present");
    assert_eq!(group.group_key, "company_abc");
    assert_eq!(group.group_type_index, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group_returns_none_when_not_found() {
    let ctx = ServiceTestContext::new().await;

    let response = ctx
        .service
        .get_group(Request::new(GetGroupRequest {
            team_id: ctx.team_id,
            group_type_index: 0,
            group_key: "nonexistent".to_string(),
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    assert!(response.into_inner().group.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_groups_returns_found_and_missing() {
    let ctx = ServiceTestContext::new().await;
    ctx.insert_group(0, "group_a", None).await.unwrap();
    ctx.insert_group(1, "group_b", None).await.unwrap();

    let response = ctx
        .service
        .get_groups(Request::new(GetGroupsRequest {
            team_id: ctx.team_id,
            group_identifiers: vec![
                GroupIdentifier {
                    group_type_index: 0,
                    group_key: "group_a".to_string(),
                },
                GroupIdentifier {
                    group_type_index: 1,
                    group_key: "group_b".to_string(),
                },
                GroupIdentifier {
                    group_type_index: 2,
                    group_key: "missing".to_string(),
                },
            ],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let inner = response.into_inner();
    assert_eq!(inner.groups.len(), 2);
    assert_eq!(inner.missing_groups.len(), 1);
    assert_eq!(inner.missing_groups[0].group_key, "missing");

    ctx.cleanup().await.ok();
}

// ============================================================
// Group type mapping tests
// ============================================================

#[tokio::test]
async fn test_get_group_type_mappings_by_team_id() {
    let ctx = ServiceTestContext::new().await;
    ctx.insert_group_type_mapping("organization", 0)
        .await
        .unwrap();
    ctx.insert_group_type_mapping("project", 1).await.unwrap();

    let response = ctx
        .service
        .get_group_type_mappings_by_team_id(Request::new(GetGroupTypeMappingsByTeamIdRequest {
            team_id: ctx.team_id,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let mappings = response.into_inner().mappings;
    assert_eq!(mappings.len(), 2);

    let group_types: Vec<&str> = mappings.iter().map(|m| m.group_type.as_str()).collect();
    assert!(group_types.contains(&"organization"));
    assert!(group_types.contains(&"project"));

    ctx.cleanup().await.ok();
}

// ============================================================
// Cohort membership tests
// ============================================================

#[tokio::test]
async fn test_check_cohort_membership() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("cohort_user", None).await.unwrap();

    let cohort_member = 1001i64;
    let cohort_not_member = 1002i64;
    ctx.add_person_to_cohort(person.id, cohort_member)
        .await
        .unwrap();

    let response = ctx
        .service
        .check_cohort_membership(Request::new(CheckCohortMembershipRequest {
            person_id: person.id,
            cohort_ids: vec![cohort_member, cohort_not_member],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let memberships = response.into_inner().memberships;
    assert_eq!(memberships.len(), 2);

    let member = memberships
        .iter()
        .find(|m| m.cohort_id == cohort_member)
        .unwrap();
    let not_member = memberships
        .iter()
        .find(|m| m.cohort_id == cohort_not_member)
        .unwrap();

    assert!(member.is_member);
    assert!(!not_member.is_member);

    ctx.cleanup().await.ok();
}

// ============================================================
// Proto conversion tests
// ============================================================

#[tokio::test]
async fn test_person_properties_are_serialized_correctly() {
    let ctx = ServiceTestContext::new().await;
    let props = serde_json::json!({
        "email": "props@example.com",
        "plan": "enterprise",
        "nested": {"key": "value"}
    });
    let person = ctx
        .insert_person("props_user", Some(props.clone()))
        .await
        .unwrap();

    let response = ctx
        .service
        .get_person(Request::new(GetPersonRequest {
            team_id: ctx.team_id,
            person_id: person.id,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let proto_person = response.into_inner().person.unwrap();
    let deserialized: serde_json::Value =
        serde_json::from_slice(&proto_person.properties).expect("Properties should be valid JSON");

    assert_eq!(deserialized["email"], "props@example.com");
    assert_eq!(deserialized["plan"], "enterprise");
    assert_eq!(deserialized["nested"]["key"], "value");

    ctx.cleanup().await.ok();
}

// ============================================================
// Additional person lookup tests
// ============================================================

#[tokio::test]
async fn test_get_persons_by_uuids() {
    let ctx = ServiceTestContext::new().await;
    let person1 = ctx.insert_person("uuid1@example.com", None).await.unwrap();
    let person2 = ctx.insert_person("uuid2@example.com", None).await.unwrap();
    let nonexistent_uuid = uuid::Uuid::now_v7().to_string();

    let response = ctx
        .service
        .get_persons_by_uuids(Request::new(GetPersonsByUuidsRequest {
            team_id: ctx.team_id,
            uuids: vec![
                person1.uuid.to_string(),
                person2.uuid.to_string(),
                nonexistent_uuid,
            ],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let inner = response.into_inner();
    assert_eq!(inner.persons.len(), 2);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_distinct_ids_for_persons() {
    let ctx = ServiceTestContext::new().await;
    let person1 = ctx.insert_person("person1_did", None).await.unwrap();
    let person2 = ctx.insert_person("person2_did", None).await.unwrap();

    // Add an extra distinct ID to person1
    ctx.add_distinct_id_to_person(person1.id, "person1_did_extra")
        .await
        .unwrap();

    let response = ctx
        .service
        .get_distinct_ids_for_persons(Request::new(GetDistinctIdsForPersonsRequest {
            team_id: ctx.team_id,
            person_ids: vec![person1.id, person2.id],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let person_distinct_ids = response.into_inner().person_distinct_ids;
    assert_eq!(person_distinct_ids.len(), 2);

    let person1_entry = person_distinct_ids
        .iter()
        .find(|p| p.person_id == person1.id)
        .expect("Person1 should be present");
    assert_eq!(person1_entry.distinct_ids.len(), 2);

    let person2_entry = person_distinct_ids
        .iter()
        .find(|p| p.person_id == person2.id)
        .expect("Person2 should be present");
    assert_eq!(person2_entry.distinct_ids.len(), 1);

    ctx.cleanup().await.ok();
}

// ============================================================
// Additional group tests
// ============================================================

#[tokio::test]
async fn test_get_groups_batch() {
    let ctx = ServiceTestContext::new().await;
    ctx.insert_group(0, "company_x", None).await.unwrap();
    ctx.insert_group(1, "org_y", None).await.unwrap();

    let response = ctx
        .service
        .get_groups_batch(Request::new(GetGroupsBatchRequest {
            keys: vec![
                GroupKey {
                    team_id: ctx.team_id,
                    group_type_index: 0,
                    group_key: "company_x".to_string(),
                },
                GroupKey {
                    team_id: ctx.team_id,
                    group_type_index: 1,
                    group_key: "org_y".to_string(),
                },
                GroupKey {
                    team_id: ctx.team_id,
                    group_type_index: 2,
                    group_key: "missing".to_string(),
                },
            ],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 3);

    let found_count = results.iter().filter(|r| r.group.is_some()).count();
    assert_eq!(found_count, 2);

    let missing = results
        .iter()
        .find(|r| r.key.as_ref().map(|k| k.group_key.as_str()) == Some("missing"))
        .unwrap();
    assert!(missing.group.is_none());

    ctx.cleanup().await.ok();
}

// ============================================================
// Additional group type mapping tests
// ============================================================

#[tokio::test]
async fn test_get_group_type_mappings_by_team_ids() {
    let ctx = ServiceTestContext::new().await;
    ctx.insert_group_type_mapping("company", 0).await.unwrap();
    ctx.insert_group_type_mapping("project", 1).await.unwrap();

    let response = ctx
        .service
        .get_group_type_mappings_by_team_ids(Request::new(GetGroupTypeMappingsByTeamIdsRequest {
            team_ids: vec![ctx.team_id],
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key, ctx.team_id);
    assert_eq!(results[0].mappings.len(), 2);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_id() {
    let ctx = ServiceTestContext::new().await;
    ctx.insert_group_type_mapping("workspace", 0).await.unwrap();

    let response = ctx
        .service
        .get_group_type_mappings_by_project_id(Request::new(
            GetGroupTypeMappingsByProjectIdRequest {
                project_id: ctx.team_id, // insert_group_type_mapping uses team_id as project_id
                read_options: None,
            },
        ))
        .await
        .expect("RPC failed");

    let mappings = response.into_inner().mappings;
    assert_eq!(mappings.len(), 1);
    assert_eq!(mappings[0].group_type, "workspace");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_ids() {
    let ctx = ServiceTestContext::new().await;
    ctx.insert_group_type_mapping("team", 0).await.unwrap();
    ctx.insert_group_type_mapping("department", 1)
        .await
        .unwrap();

    let response = ctx
        .service
        .get_group_type_mappings_by_project_ids(Request::new(
            GetGroupTypeMappingsByProjectIdsRequest {
                project_ids: vec![ctx.team_id],
                read_options: None,
            },
        ))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key, ctx.team_id);
    assert_eq!(results[0].mappings.len(), 2);

    ctx.cleanup().await.ok();
}

// ============================================================
// Feature flag hash key override context tests
// ============================================================

#[tokio::test]
async fn test_get_hash_key_override_context_with_overrides() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("hash_override_user", None).await.unwrap();

    ctx.insert_hash_key_override(person.id, "beta-feature", "custom_hash_1")
        .await
        .unwrap();
    ctx.insert_hash_key_override(person.id, "new-ui", "custom_hash_2")
        .await
        .unwrap();

    let response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["hash_override_user".to_string(), "nonexistent".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 1);

    let person_result = &results[0];
    assert_eq!(person_result.person_id, person.id);
    assert_eq!(person_result.distinct_id, "hash_override_user");
    assert_eq!(person_result.overrides.len(), 2);
    assert_eq!(person_result.existing_feature_flag_keys.len(), 2);

    let override_keys: Vec<&str> = person_result
        .overrides
        .iter()
        .map(|o| o.feature_flag_key.as_str())
        .collect();
    assert!(override_keys.contains(&"beta-feature"));
    assert!(override_keys.contains(&"new-ui"));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_hash_key_override_context_no_overrides() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx
        .insert_person("user_without_overrides", None)
        .await
        .unwrap();

    let response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["user_without_overrides".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].person_id, person.id);
    assert!(results[0].overrides.is_empty());
    assert!(results[0].existing_feature_flag_keys.is_empty());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_hash_key_override_context_with_check_person_exists() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx
        .insert_person("existing_person_user", None)
        .await
        .unwrap();

    ctx.insert_hash_key_override(person.id, "feature-a", "hash_a")
        .await
        .unwrap();

    let response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["existing_person_user".to_string()],
            check_person_exists: true,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = response.into_inner().results;
    assert_eq!(results.len(), 1);

    let person_result = &results[0];
    assert_eq!(person_result.person_id, person.id);
    assert_eq!(person_result.existing_feature_flag_keys.len(), 1);
    assert!(person_result
        .existing_feature_flag_keys
        .contains(&"feature-a".to_string()));

    ctx.cleanup().await.ok();
}

// ============================================================
// Upsert hash key overrides tests
// ============================================================

#[tokio::test]
async fn test_upsert_hash_key_overrides_single_override() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("upsert_user_1", None).await.unwrap();

    let response = ctx
        .service
        .upsert_hash_key_overrides(Request::new(UpsertHashKeyOverridesRequest {
            team_id: ctx.team_id,
            overrides: vec![HashKeyOverrideInput {
                person_id: person.id,
                feature_flag_key: "test-flag".to_string(),
            }],
            hash_key: "my_hash_key".to_string(),
        }))
        .await
        .expect("RPC failed");

    assert_eq!(response.into_inner().inserted_count, 1);

    // Verify the override was created by reading it back
    let context_response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["upsert_user_1".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = context_response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].overrides.len(), 1);
    assert_eq!(results[0].overrides[0].feature_flag_key, "test-flag");
    assert_eq!(results[0].overrides[0].hash_key, "my_hash_key");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_multiple_flags_same_hash_key() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("upsert_user_2", None).await.unwrap();

    let response = ctx
        .service
        .upsert_hash_key_overrides(Request::new(UpsertHashKeyOverridesRequest {
            team_id: ctx.team_id,
            overrides: vec![
                HashKeyOverrideInput {
                    person_id: person.id,
                    feature_flag_key: "flag-a".to_string(),
                },
                HashKeyOverrideInput {
                    person_id: person.id,
                    feature_flag_key: "flag-b".to_string(),
                },
                HashKeyOverrideInput {
                    person_id: person.id,
                    feature_flag_key: "flag-c".to_string(),
                },
            ],
            hash_key: "shared_hash".to_string(),
        }))
        .await
        .expect("RPC failed");

    assert_eq!(response.into_inner().inserted_count, 3);

    // Verify all overrides share the same hash_key
    let context_response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["upsert_user_2".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = context_response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].overrides.len(), 3);

    for override_entry in &results[0].overrides {
        assert_eq!(override_entry.hash_key, "shared_hash");
    }

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_empty_returns_zero() {
    let ctx = ServiceTestContext::new().await;

    let response = ctx
        .service
        .upsert_hash_key_overrides(Request::new(UpsertHashKeyOverridesRequest {
            team_id: ctx.team_id,
            overrides: vec![],
            hash_key: "unused".to_string(),
        }))
        .await
        .expect("RPC failed");

    assert_eq!(response.into_inner().inserted_count, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_on_conflict_do_nothing() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx
        .insert_person("upsert_conflict_user", None)
        .await
        .unwrap();

    // Insert initial override
    ctx.insert_hash_key_override(person.id, "existing-flag", "original_hash")
        .await
        .unwrap();

    // Try to upsert with a different hash_key - should be ignored due to ON CONFLICT DO NOTHING
    let response = ctx
        .service
        .upsert_hash_key_overrides(Request::new(UpsertHashKeyOverridesRequest {
            team_id: ctx.team_id,
            overrides: vec![HashKeyOverrideInput {
                person_id: person.id,
                feature_flag_key: "existing-flag".to_string(),
            }],
            hash_key: "different_hash".to_string(),
        }))
        .await
        .expect("RPC failed");

    // No rows inserted due to conflict
    assert_eq!(response.into_inner().inserted_count, 0);

    // Verify the original hash_key is preserved
    let context_response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["upsert_conflict_user".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = context_response.into_inner().results;
    assert_eq!(results[0].overrides.len(), 1);
    assert_eq!(results[0].overrides[0].hash_key, "original_hash");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_multiple_persons() {
    let ctx = ServiceTestContext::new().await;
    let person1 = ctx.insert_person("multi_person_1", None).await.unwrap();
    let person2 = ctx.insert_person("multi_person_2", None).await.unwrap();

    let response = ctx
        .service
        .upsert_hash_key_overrides(Request::new(UpsertHashKeyOverridesRequest {
            team_id: ctx.team_id,
            overrides: vec![
                HashKeyOverrideInput {
                    person_id: person1.id,
                    feature_flag_key: "shared-flag".to_string(),
                },
                HashKeyOverrideInput {
                    person_id: person2.id,
                    feature_flag_key: "shared-flag".to_string(),
                },
            ],
            hash_key: "common_hash".to_string(),
        }))
        .await
        .expect("RPC failed");

    assert_eq!(response.into_inner().inserted_count, 2);

    // Verify both persons have the override
    let context_response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["multi_person_1".to_string(), "multi_person_2".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = context_response.into_inner().results;
    assert_eq!(results.len(), 2);

    for result in &results {
        assert_eq!(result.overrides.len(), 1);
        assert_eq!(result.overrides[0].feature_flag_key, "shared-flag");
        assert_eq!(result.overrides[0].hash_key, "common_hash");
    }

    ctx.cleanup().await.ok();
}

// ============================================================
// Delete hash key overrides by teams tests
// ============================================================

#[tokio::test]
async fn test_delete_hash_key_overrides_by_teams_single_team() {
    let ctx = ServiceTestContext::new().await;
    let person = ctx.insert_person("delete_svc_user", None).await.unwrap();

    // Insert overrides
    ctx.insert_hash_key_override(person.id, "flag-to-delete", "hash_val")
        .await
        .unwrap();

    let response = ctx
        .service
        .delete_hash_key_overrides_by_teams(Request::new(DeleteHashKeyOverridesByTeamsRequest {
            team_ids: vec![ctx.team_id],
        }))
        .await
        .expect("RPC failed");

    assert_eq!(response.into_inner().deleted_count, 1);

    // Verify deletion
    let context_response = ctx
        .service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: ctx.team_id,
            distinct_ids: vec!["delete_svc_user".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC failed");

    let results = context_response.into_inner().results;
    assert_eq!(results.len(), 1);
    assert!(results[0].overrides.is_empty());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_hash_key_overrides_by_teams_empty_returns_zero() {
    let ctx = ServiceTestContext::new().await;

    let response = ctx
        .service
        .delete_hash_key_overrides_by_teams(Request::new(DeleteHashKeyOverridesByTeamsRequest {
            team_ids: vec![],
        }))
        .await
        .expect("RPC failed");

    assert_eq!(response.into_inner().deleted_count, 0);

    ctx.cleanup().await.ok();
}
