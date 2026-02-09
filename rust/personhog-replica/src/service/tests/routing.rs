//! Consistency Level Routing Tests
//!
//! These tests define the expected behavior for consistency level routing:
//!
//! 1. Person-related endpoints (touch posthog_person table for data retrieval):
//!    - MUST reject STRONG consistency with FailedPrecondition
//!    - The replica service cannot serve strong consistency for person data
//!      because the person table is cached/managed by the leader service
//!
//! 2. Non-person endpoints (groups, cohorts, distinct_ids, group_type_mappings):
//!    - MUST accept both EVENTUAL and STRONG consistency
//!    - STRONG routes to primary, EVENTUAL routes to replica
//!
//! 3. Feature flag get_hash_key_override_context is an exception to the above rules:
//!    - Accepts both consistency levels regardless of check_person_exists
//!    - STRONG routes to primary (for read-after-write scenarios)
//!    - EVENTUAL routes to replica
//!    - Note: This is an exception because the check_person_exists queries hit the person
//!      table on the primary database. When personhog-leader is implemented, this will no
//!      longer be a consistent read and may need to change
//!
//! 4. Write endpoints (upsert/delete):
//!    - Always go to primary, no read_options needed

use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonsRequest,
    GetGroupRequest, GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest, GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest, GetGroupsBatchRequest, GetGroupsRequest,
    GetHashKeyOverrideContextRequest, GetPersonByDistinctIdRequest, GetPersonByUuidRequest,
    GetPersonRequest, GetPersonsByDistinctIdsInTeamRequest, GetPersonsByDistinctIdsRequest,
    GetPersonsByUuidsRequest, GetPersonsRequest, TeamDistinctId,
};
use tonic::Request;

use super::mocks::{ConsistencyTrackingStorage, SuccessStorage};
use crate::service::PersonHogReplicaService;
use crate::storage;

fn strong_consistency() -> Option<personhog_proto::personhog::types::v1::ReadOptions> {
    Some(personhog_proto::personhog::types::v1::ReadOptions {
        consistency: personhog_proto::personhog::types::v1::ConsistencyLevel::Strong.into(),
    })
}

fn eventual_consistency() -> Option<personhog_proto::personhog::types::v1::ReadOptions> {
    Some(personhog_proto::personhog::types::v1::ReadOptions {
        consistency: personhog_proto::personhog::types::v1::ConsistencyLevel::Eventual.into(),
    })
}

// ============================================================
// Person endpoints: rejects STRONG consistency
// ============================================================

#[tokio::test]
async fn test_get_person_rejects_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_person(Request::new(GetPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: strong_consistency(),
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);
    assert!(status.message().contains("strong consistency"));
}

#[tokio::test]
async fn test_get_person_accepts_eventual_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_person(Request::new(GetPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: eventual_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_person_accepts_unspecified_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_person(Request::new(GetPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: None,
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_persons_rejects_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_persons(Request::new(GetPersonsRequest {
            team_id: 1,
            person_ids: vec![1, 2],
            read_options: strong_consistency(),
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);
}

#[tokio::test]
async fn test_get_person_by_uuid_rejects_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_person_by_uuid(Request::new(GetPersonByUuidRequest {
            team_id: 1,
            uuid: "00000000-0000-0000-0000-000000000000".to_string(),
            read_options: strong_consistency(),
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);
}

#[tokio::test]
async fn test_get_persons_by_uuids_rejects_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_persons_by_uuids(Request::new(GetPersonsByUuidsRequest {
            team_id: 1,
            uuids: vec!["00000000-0000-0000-0000-000000000000".to_string()],
            read_options: strong_consistency(),
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);
}

#[tokio::test]
async fn test_get_person_by_distinct_id_rejects_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_person_by_distinct_id(Request::new(GetPersonByDistinctIdRequest {
            team_id: 1,
            distinct_id: "user1".to_string(),
            read_options: strong_consistency(),
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_in_team_rejects_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_persons_by_distinct_ids_in_team(Request::new(GetPersonsByDistinctIdsInTeamRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string()],
            read_options: strong_consistency(),
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_rejects_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_persons_by_distinct_ids(Request::new(GetPersonsByDistinctIdsRequest {
            team_distinct_ids: vec![TeamDistinctId {
                team_id: 1,
                distinct_id: "user1".to_string(),
            }],
            read_options: strong_consistency(),
        }))
        .await;

    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);
}

// ============================================================
// Non-person endpoints: accepts both EVENTUAL and STRONG consistency reads
// ============================================================

#[tokio::test]
async fn test_get_group_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_group(Request::new(GetGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test".to_string(),
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_group_accepts_eventual_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_group(Request::new(GetGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test".to_string(),
            read_options: eventual_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_groups_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_groups(Request::new(GetGroupsRequest {
            team_id: 1,
            group_identifiers: vec![],
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_groups_batch_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_groups_batch(Request::new(GetGroupsBatchRequest {
            keys: vec![],
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_check_cohort_membership_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .check_cohort_membership(Request::new(CheckCohortMembershipRequest {
            person_id: 1,
            cohort_ids: vec![1],
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_distinct_ids_for_person_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_distinct_ids_for_person(Request::new(GetDistinctIdsForPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_distinct_ids_for_persons_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_distinct_ids_for_persons(Request::new(GetDistinctIdsForPersonsRequest {
            team_id: 1,
            person_ids: vec![1],
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_group_type_mappings_by_team_id_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_group_type_mappings_by_team_id(Request::new(GetGroupTypeMappingsByTeamIdRequest {
            team_id: 1,
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_group_type_mappings_by_team_ids_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_group_type_mappings_by_team_ids(Request::new(GetGroupTypeMappingsByTeamIdsRequest {
            team_ids: vec![1],
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_id_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_group_type_mappings_by_project_id(Request::new(
            GetGroupTypeMappingsByProjectIdRequest {
                project_id: 1,
                read_options: strong_consistency(),
            },
        ))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_ids_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_group_type_mappings_by_project_ids(Request::new(
            GetGroupTypeMappingsByProjectIdsRequest {
                project_ids: vec![1],
                read_options: strong_consistency(),
            },
        ))
        .await;

    assert!(result.is_ok());
}

// ============================================================
// Feature flag get_hash_key_override_context: accepts both consistency levels
// ============================================================
//
// Unlike person-related endpoints, get_hash_key_override_context accepts strong consistency
// regardless of check_person_exists. Strong consistency routes to the primary database
// for read-after-write scenarios (e.g., reading hash key overrides after writing them).
//
// Note: When personhog-leader is implemented, strong consistency for person data will
// require routing to the leader service. The current implementation queries the primary
// database directly as an interim solution.

#[tokio::test]
async fn test_get_hash_key_override_context_without_person_check_accepts_strong_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string()],
            check_person_exists: false,
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_hash_key_override_context_with_person_check_accepts_strong_consistency() {
    // Strong consistency is allowed for get_hash_key_override_context even with check_person_exists=true.
    // This routes to the primary database for read-after-write scenarios.
    //
    // Note: When personhog-leader is implemented, strong consistency for person data will
    // require routing to the leader service. This test documents the current behavior where
    // we query the primary database directly as an interim solution.
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string()],
            check_person_exists: true,
            read_options: strong_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_get_hash_key_override_context_with_person_check_accepts_eventual_consistency() {
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let result = service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string()],
            check_person_exists: true,
            read_options: eventual_consistency(),
        }))
        .await;

    assert!(result.is_ok());
}

// ============================================================
// Consistency Level Routing Verification Tests
// ============================================================
//
// These tests verify that the service correctly passes the consistency
// level from read_options to the storage layer. Each domain (distinct_id,
// cohort, group, feature_flag) should correctly route based on consistency.

// ============================================================
// Distinct ID domain routing tests
// ============================================================

#[tokio::test]
async fn test_get_distinct_ids_for_person_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_distinct_ids_for_person(Request::new(GetDistinctIdsForPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_distinct_ids_for_person_routes_eventual_to_replica() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_distinct_ids_for_person(Request::new(GetDistinctIdsForPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: eventual_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Eventual)
    );
}

#[tokio::test]
async fn test_get_distinct_ids_for_person_routes_unspecified_to_replica() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_distinct_ids_for_person(Request::new(GetDistinctIdsForPersonRequest {
            team_id: 1,
            person_id: 1,
            read_options: None,
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Eventual)
    );
}

#[tokio::test]
async fn test_get_distinct_ids_for_persons_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_distinct_ids_for_persons(Request::new(GetDistinctIdsForPersonsRequest {
            team_id: 1,
            person_ids: vec![1],
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

// ============================================================
// Cohort domain routing tests
// ============================================================

#[tokio::test]
async fn test_check_cohort_membership_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .check_cohort_membership(Request::new(CheckCohortMembershipRequest {
            person_id: 1,
            cohort_ids: vec![1],
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_check_cohort_membership_routes_eventual_to_replica() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .check_cohort_membership(Request::new(CheckCohortMembershipRequest {
            person_id: 1,
            cohort_ids: vec![1],
            read_options: eventual_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Eventual)
    );
}

// ============================================================
// Group domain routing tests
// ============================================================

#[tokio::test]
async fn test_get_group_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_group(Request::new(GetGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test".to_string(),
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_group_routes_eventual_to_replica() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_group(Request::new(GetGroupRequest {
            team_id: 1,
            group_type_index: 0,
            group_key: "test".to_string(),
            read_options: eventual_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Eventual)
    );
}

#[tokio::test]
async fn test_get_groups_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_groups(Request::new(GetGroupsRequest {
            team_id: 1,
            group_identifiers: vec![],
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_groups_batch_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_groups_batch(Request::new(GetGroupsBatchRequest {
            keys: vec![],
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_group_type_mappings_by_team_id_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_group_type_mappings_by_team_id(Request::new(GetGroupTypeMappingsByTeamIdRequest {
            team_id: 1,
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_group_type_mappings_by_team_ids_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_group_type_mappings_by_team_ids(Request::new(GetGroupTypeMappingsByTeamIdsRequest {
            team_ids: vec![1],
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_id_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_group_type_mappings_by_project_id(Request::new(
            GetGroupTypeMappingsByProjectIdRequest {
                project_id: 1,
                read_options: strong_consistency(),
            },
        ))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_ids_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_group_type_mappings_by_project_ids(Request::new(
            GetGroupTypeMappingsByProjectIdsRequest {
                project_ids: vec![1],
                read_options: strong_consistency(),
            },
        ))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

// ============================================================
// Feature flag domain routing tests
// ============================================================

#[tokio::test]
async fn test_get_hash_key_override_context_routes_strong_to_primary() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string()],
            check_person_exists: false,
            read_options: strong_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Strong)
    );
}

#[tokio::test]
async fn test_get_hash_key_override_context_routes_eventual_to_replica() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string()],
            check_person_exists: false,
            read_options: eventual_consistency(),
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Eventual)
    );
}

#[tokio::test]
async fn test_get_hash_key_override_context_routes_unspecified_to_replica() {
    let tracking_storage = Arc::new(ConsistencyTrackingStorage::new());
    let service = PersonHogReplicaService::new(tracking_storage.clone());

    service
        .get_hash_key_override_context(Request::new(GetHashKeyOverrideContextRequest {
            team_id: 1,
            distinct_ids: vec!["user1".to_string()],
            check_person_exists: false,
            read_options: None,
        }))
        .await
        .expect("RPC should succeed");

    assert_eq!(
        tracking_storage.last_consistency(),
        Some(storage::postgres::ConsistencyLevel::Eventual)
    );
}
