mod common;

use common::TestContext;
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, GetDistinctIdsForPersonRequest, GetGroupRequest,
    GetGroupTypeMappingsByTeamIdRequest, GetGroupsRequest, GetPersonByDistinctIdRequest,
    GetPersonByUuidRequest, GetPersonRequest, GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByDistinctIdsRequest, GetPersonsRequest, GroupIdentifier, TeamDistinctId,
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
