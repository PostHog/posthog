use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    GetGroupsBatchRequest, GetGroupsRequest, GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest, GetPersonsRequest, GroupIdentifier,
    GroupKey, ListGroupsRequest, ReadOptions, TeamDistinctId,
};
use rstest::rstest;
use tonic::Request;

use super::super::PersonHogReplicaService;
use super::mocks::PopulatedStorage;

fn read_options_with_mask(fields: &[&str]) -> Option<ReadOptions> {
    Some(ReadOptions {
        field_mask: fields.iter().map(|s| s.to_string()).collect(),
        ..Default::default()
    })
}

// ============================================================
// get_persons field mask tests
// ============================================================

#[rstest]
#[case::no_read_options(None)]
#[tokio::test]
async fn get_persons_without_field_mask_returns_all_person_fields_populated(
    #[case] read_options: Option<ReadOptions>,
) {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_persons(Request::new(GetPersonsRequest {
            team_id: 1,
            person_ids: vec![42],
            read_options,
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.persons.len(), 1);
    let person = &response.persons[0];
    assert_ne!(person.id, 0, "id should be populated");
    assert!(!person.uuid.is_empty(), "uuid should be populated");
    assert_ne!(person.team_id, 0, "team_id should be populated");
    assert!(
        !person.properties.is_empty(),
        "properties should be populated"
    );
    assert!(
        !person.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be populated"
    );
    assert!(
        !person.properties_last_operation.is_empty(),
        "properties_last_operation should be populated"
    );
    assert_ne!(person.created_at, 0, "created_at should be populated");
    assert_ne!(person.version, 0, "version should be populated");
    assert!(person.is_identified, "is_identified should be populated");
    assert!(
        person.is_user_id.is_some(),
        "is_user_id should be populated"
    );
    assert!(
        person.last_seen_at.is_some(),
        "last_seen_at should be populated"
    );
}

#[rstest]
#[case::id_and_uuid(&["id", "uuid"])]
#[tokio::test]
async fn get_persons_with_id_and_uuid_mask_returns_only_those_fields(#[case] mask_fields: &[&str]) {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_persons(Request::new(GetPersonsRequest {
            team_id: 1,
            person_ids: vec![42],
            read_options: read_options_with_mask(mask_fields),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.persons.len(), 1);
    let person = &response.persons[0];
    assert_ne!(person.id, 0, "id should be preserved");
    assert!(!person.uuid.is_empty(), "uuid should be preserved");
    assert_eq!(person.team_id, 0, "team_id should be zeroed");
    assert!(person.properties.is_empty(), "properties should be zeroed");
    assert!(
        person.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        person.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
    assert_eq!(person.created_at, 0, "created_at should be zeroed");
    assert_eq!(person.version, 0, "version should be zeroed");
    assert!(!person.is_identified, "is_identified should be zeroed");
    assert!(person.is_user_id.is_none(), "is_user_id should be zeroed");
    assert!(
        person.last_seen_at.is_none(),
        "last_seen_at should be zeroed"
    );
}

#[rstest]
#[case::properties_only(&["properties"])]
#[tokio::test]
async fn get_persons_with_properties_mask_returns_only_properties(#[case] mask_fields: &[&str]) {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_persons(Request::new(GetPersonsRequest {
            team_id: 1,
            person_ids: vec![42],
            read_options: read_options_with_mask(mask_fields),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.persons.len(), 1);
    let person = &response.persons[0];
    assert!(
        !person.properties.is_empty(),
        "properties should be preserved"
    );
    assert_eq!(person.id, 0, "id should be zeroed");
    assert!(person.uuid.is_empty(), "uuid should be zeroed");
    assert_eq!(person.team_id, 0, "team_id should be zeroed");
    assert_eq!(person.created_at, 0, "created_at should be zeroed");
    assert_eq!(person.version, 0, "version should be zeroed");
    assert!(!person.is_identified, "is_identified should be zeroed");
    assert!(person.is_user_id.is_none(), "is_user_id should be zeroed");
    assert!(
        person.last_seen_at.is_none(),
        "last_seen_at should be zeroed"
    );
}

#[rstest]
#[case::non_property_fields(&["id", "team_id", "created_at", "version", "is_identified", "is_user_id", "last_seen_at"])]
#[tokio::test]
async fn get_persons_with_non_property_mask_zeros_property_fields(#[case] mask_fields: &[&str]) {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_persons(Request::new(GetPersonsRequest {
            team_id: 1,
            person_ids: vec![42],
            read_options: read_options_with_mask(mask_fields),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.persons.len(), 1);
    let person = &response.persons[0];
    assert_ne!(person.id, 0, "id should be preserved");
    assert_ne!(person.team_id, 0, "team_id should be preserved");
    assert_ne!(person.created_at, 0, "created_at should be preserved");
    assert_ne!(person.version, 0, "version should be preserved");
    assert!(person.is_identified, "is_identified should be preserved");
    assert!(
        person.is_user_id.is_some(),
        "is_user_id should be preserved"
    );
    assert!(
        person.last_seen_at.is_some(),
        "last_seen_at should be preserved"
    );
    assert!(person.uuid.is_empty(), "uuid should be zeroed");
    assert!(person.properties.is_empty(), "properties should be zeroed");
    assert!(
        person.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        person.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
}

// ============================================================
// get_persons_by_uuids field mask tests
// ============================================================

#[tokio::test]
async fn get_persons_by_uuids_with_id_and_uuid_mask_applies_masking() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_persons_by_uuids(Request::new(GetPersonsByUuidsRequest {
            team_id: 1,
            uuids: vec!["00000000-0000-0000-0000-000000000042".to_string()],
            read_options: read_options_with_mask(&["id", "uuid"]),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.persons.len(), 1);
    let person = &response.persons[0];
    assert_ne!(person.id, 0, "id should be preserved");
    assert!(!person.uuid.is_empty(), "uuid should be preserved");
    assert_eq!(person.team_id, 0, "team_id should be zeroed");
    assert!(person.properties.is_empty(), "properties should be zeroed");
    assert_eq!(person.created_at, 0, "created_at should be zeroed");
    assert_eq!(person.version, 0, "version should be zeroed");
    assert!(!person.is_identified, "is_identified should be zeroed");
    assert!(person.is_user_id.is_none(), "is_user_id should be zeroed");
    assert!(
        person.last_seen_at.is_none(),
        "last_seen_at should be zeroed"
    );
}

// ============================================================
// get_persons_by_distinct_ids_in_team field mask tests
// ============================================================

#[tokio::test]
async fn get_persons_by_distinct_ids_in_team_with_id_mask_returns_only_id() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_persons_by_distinct_ids_in_team(Request::new(GetPersonsByDistinctIdsInTeamRequest {
            team_id: 1,
            distinct_ids: vec!["user-1".to_string()],
            read_options: read_options_with_mask(&["id"]),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.results.len(), 1);
    let person = response.results[0]
        .person
        .as_ref()
        .expect("person should be present");
    assert_ne!(person.id, 0, "id should be preserved");
    assert!(person.uuid.is_empty(), "uuid should be zeroed");
    assert_eq!(person.team_id, 0, "team_id should be zeroed");
    assert!(person.properties.is_empty(), "properties should be zeroed");
    assert!(
        person.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        person.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
    assert_eq!(person.created_at, 0, "created_at should be zeroed");
    assert_eq!(person.version, 0, "version should be zeroed");
    assert!(!person.is_identified, "is_identified should be zeroed");
    assert!(person.is_user_id.is_none(), "is_user_id should be zeroed");
    assert!(
        person.last_seen_at.is_none(),
        "last_seen_at should be zeroed"
    );
}

// ============================================================
// get_persons_by_distinct_ids_cross_team field mask tests
// ============================================================

#[tokio::test]
async fn get_persons_by_distinct_ids_cross_team_with_id_mask_returns_only_id() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_persons_by_distinct_ids(Request::new(GetPersonsByDistinctIdsRequest {
            team_distinct_ids: vec![TeamDistinctId {
                team_id: 1,
                distinct_id: "user-1".to_string(),
            }],
            read_options: read_options_with_mask(&["id"]),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.results.len(), 1);
    let person = response.results[0]
        .person
        .as_ref()
        .expect("person should be present");
    assert_ne!(person.id, 0, "id should be preserved");
    assert!(person.uuid.is_empty(), "uuid should be zeroed");
    assert_eq!(person.team_id, 0, "team_id should be zeroed");
    assert!(person.properties.is_empty(), "properties should be zeroed");
    assert!(
        person.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        person.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
    assert_eq!(person.created_at, 0, "created_at should be zeroed");
    assert_eq!(person.version, 0, "version should be zeroed");
    assert!(!person.is_identified, "is_identified should be zeroed");
    assert!(person.is_user_id.is_none(), "is_user_id should be zeroed");
    assert!(
        person.last_seen_at.is_none(),
        "last_seen_at should be zeroed"
    );
}

// ============================================================
// get_groups field mask tests
// ============================================================

#[rstest]
#[case::no_read_options(None)]
#[tokio::test]
async fn get_groups_without_field_mask_returns_all_group_fields_populated(
    #[case] read_options: Option<ReadOptions>,
) {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_groups(Request::new(GetGroupsRequest {
            team_id: 1,
            group_identifiers: vec![GroupIdentifier {
                group_type_index: 0,
                group_key: "org-1".to_string(),
            }],
            read_options,
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.groups.len(), 1);
    let group = &response.groups[0];
    assert_ne!(group.id, 0, "id should be populated");
    assert_ne!(group.team_id, 0, "team_id should be populated");
    assert!(!group.group_key.is_empty(), "group_key should be populated");
    assert!(
        !group.group_properties.is_empty(),
        "group_properties should be populated"
    );
    assert!(
        !group.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be populated"
    );
    assert!(
        !group.properties_last_operation.is_empty(),
        "properties_last_operation should be populated"
    );
    assert_ne!(group.created_at, 0, "created_at should be populated");
    assert_ne!(group.version, 0, "version should be populated");
}

#[rstest]
#[case::id_and_group_key(&["id", "group_key"])]
#[tokio::test]
async fn get_groups_with_id_and_group_key_mask_returns_only_those_fields(
    #[case] mask_fields: &[&str],
) {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_groups(Request::new(GetGroupsRequest {
            team_id: 1,
            group_identifiers: vec![GroupIdentifier {
                group_type_index: 0,
                group_key: "org-1".to_string(),
            }],
            read_options: read_options_with_mask(mask_fields),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.groups.len(), 1);
    let group = &response.groups[0];
    assert_ne!(group.id, 0, "id should be preserved");
    assert!(!group.group_key.is_empty(), "group_key should be preserved");
    assert_eq!(group.team_id, 0, "team_id should be zeroed");
    assert_eq!(
        group.group_type_index, 0,
        "group_type_index should be zeroed"
    );
    assert!(
        group.group_properties.is_empty(),
        "group_properties should be zeroed"
    );
    assert!(
        group.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        group.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
    assert_eq!(group.created_at, 0, "created_at should be zeroed");
    assert_eq!(group.version, 0, "version should be zeroed");
}

#[rstest]
#[case::group_properties_only(&["group_properties"])]
#[tokio::test]
async fn get_groups_with_group_properties_mask_returns_only_group_properties(
    #[case] mask_fields: &[&str],
) {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_groups(Request::new(GetGroupsRequest {
            team_id: 1,
            group_identifiers: vec![GroupIdentifier {
                group_type_index: 0,
                group_key: "org-1".to_string(),
            }],
            read_options: read_options_with_mask(mask_fields),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.groups.len(), 1);
    let group = &response.groups[0];
    assert!(
        !group.group_properties.is_empty(),
        "group_properties should be preserved"
    );
    assert_eq!(group.id, 0, "id should be zeroed");
    assert_eq!(group.team_id, 0, "team_id should be zeroed");
    assert_eq!(
        group.group_type_index, 0,
        "group_type_index should be zeroed"
    );
    assert!(group.group_key.is_empty(), "group_key should be zeroed");
    assert!(
        group.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        group.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
    assert_eq!(group.created_at, 0, "created_at should be zeroed");
    assert_eq!(group.version, 0, "version should be zeroed");
}

// ============================================================
// get_groups_batch field mask tests
// ============================================================

#[tokio::test]
async fn get_groups_batch_with_id_and_group_key_mask_applies_masking() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .get_groups_batch(Request::new(GetGroupsBatchRequest {
            keys: vec![GroupKey {
                team_id: 1,
                group_type_index: 0,
                group_key: "org-1".to_string(),
            }],
            read_options: read_options_with_mask(&["id", "group_key"]),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.results.len(), 1);
    let group = response.results[0]
        .group
        .as_ref()
        .expect("group should be present");
    assert_ne!(group.id, 0, "id should be preserved");
    assert!(!group.group_key.is_empty(), "group_key should be preserved");
    assert_eq!(group.team_id, 0, "team_id should be zeroed");
    assert_eq!(
        group.group_type_index, 0,
        "group_type_index should be zeroed"
    );
    assert!(
        group.group_properties.is_empty(),
        "group_properties should be zeroed"
    );
    assert!(
        group.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        group.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
    assert_eq!(group.created_at, 0, "created_at should be zeroed");
    assert_eq!(group.version, 0, "version should be zeroed");
}

// ============================================================
// list_groups field mask tests
// ============================================================

#[tokio::test]
async fn list_groups_with_id_and_team_id_mask_applies_masking() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let response = service
        .list_groups(Request::new(ListGroupsRequest {
            team_id: 1,
            group_type_index: 0,
            read_options: read_options_with_mask(&["id", "team_id"]),
            ..Default::default()
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(response.groups.len(), 1);
    let group = &response.groups[0];
    assert_ne!(group.id, 0, "id should be preserved");
    assert_ne!(group.team_id, 0, "team_id should be preserved");
    assert_eq!(
        group.group_type_index, 0,
        "group_type_index should be zeroed"
    );
    assert!(group.group_key.is_empty(), "group_key should be zeroed");
    assert!(
        group.group_properties.is_empty(),
        "group_properties should be zeroed"
    );
    assert!(
        group.properties_last_updated_at.is_empty(),
        "properties_last_updated_at should be zeroed"
    );
    assert!(
        group.properties_last_operation.is_empty(),
        "properties_last_operation should be zeroed"
    );
    assert_eq!(group.created_at, 0, "created_at should be zeroed");
    assert_eq!(group.version, 0, "version should be zeroed");
}
