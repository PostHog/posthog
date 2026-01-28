use std::collections::HashMap;
use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembership, CohortMembershipResponse,
    DistinctIdWithVersion, GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest, GetDistinctIdsForPersonsResponse,
    GetExistingPersonIdsWithOverrideKeysRequest, GetExistingPersonIdsWithOverrideKeysResponse,
    GetGroupRequest, GetGroupResponse, GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest, GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest, GetGroupsBatchRequest, GetGroupsBatchResponse,
    GetGroupsRequest, GetPersonByDistinctIdRequest, GetPersonByUuidRequest,
    GetPersonIdsAndHashKeyOverridesRequest, GetPersonIdsAndHashKeyOverridesResponse,
    GetPersonRequest, GetPersonResponse, GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest, GetPersonsRequest, Group, GroupKey,
    GroupTypeMapping, GroupTypeMappingsBatchResponse, GroupTypeMappingsByKey,
    GroupTypeMappingsResponse, GroupWithKey, GroupsResponse, HashKeyOverride, Person,
    PersonDistinctIds, PersonIdWithOverrideKeys, PersonIdWithOverrides, PersonWithDistinctIds,
    PersonWithTeamDistinctId, PersonsByDistinctIdsInTeamResponse, PersonsByDistinctIdsResponse,
    PersonsResponse, TeamDistinctId,
};
use tonic::{Request, Response, Status};
use tracing::error;
use uuid::Uuid;

use crate::storage::{self, FullStorage};

pub struct PersonHogReplicaService {
    storage: Arc<dyn FullStorage>,
}

impl PersonHogReplicaService {
    pub fn new(storage: Arc<dyn FullStorage>) -> Self {
        Self { storage }
    }
}

// ============================================================
// Conversion functions: storage types -> proto types
// ============================================================

fn person_to_proto(person: storage::Person) -> Person {
    Person {
        id: person.id,
        uuid: person.uuid.to_string(),
        team_id: person.team_id,
        properties: serde_json::to_vec(&person.properties).unwrap_or_default(),
        properties_last_updated_at: person
            .properties_last_updated_at
            .map(|v| serde_json::to_vec(&v).unwrap_or_default())
            .unwrap_or_default(),
        properties_last_operation: person
            .properties_last_operation
            .map(|v| serde_json::to_vec(&v).unwrap_or_default())
            .unwrap_or_default(),
        created_at: person.created_at.timestamp_millis(),
        version: person.version.unwrap_or(0),
        is_identified: person.is_identified,
        is_user_id: person.is_user_id.unwrap_or(false),
    }
}

fn group_to_proto(group: storage::Group) -> Group {
    Group {
        id: group.id,
        team_id: group.team_id,
        group_type_index: group.group_type_index,
        group_key: group.group_key,
        group_properties: serde_json::to_vec(&group.group_properties).unwrap_or_default(),
        created_at: group.created_at.timestamp_millis(),
        properties_last_updated_at: group
            .properties_last_updated_at
            .map(|v| serde_json::to_vec(&v).unwrap_or_default())
            .unwrap_or_default(),
        properties_last_operation: group
            .properties_last_operation
            .map(|v| serde_json::to_vec(&v).unwrap_or_default())
            .unwrap_or_default(),
        version: group.version,
    }
}

fn group_type_mapping_to_proto(mapping: storage::GroupTypeMapping) -> GroupTypeMapping {
    GroupTypeMapping {
        id: mapping.id,
        team_id: mapping.team_id,
        project_id: mapping.project_id,
        group_type: mapping.group_type,
        group_type_index: mapping.group_type_index,
        name_singular: mapping.name_singular,
        name_plural: mapping.name_plural,
        default_columns: mapping
            .default_columns
            .map(|v| serde_json::to_vec(&v).unwrap_or_default()),
        detail_dashboard_id: mapping.detail_dashboard_id,
        created_at: mapping.created_at.map(|t| t.timestamp_millis()),
    }
}

fn log_and_convert_error(err: storage::StorageError, operation: &str) -> Status {
    let status = match &err {
        // Connection/pool errors are transient - signal client to retry
        storage::StorageError::Connection(msg) => {
            error!(operation, error = %msg, "Database connection error");
            Status::unavailable(format!("Database unavailable: {msg}"))
        }
        storage::StorageError::PoolExhausted => {
            error!(operation, "Database pool exhausted");
            Status::unavailable("Database pool exhausted")
        }
        // Query errors are internal server errors
        storage::StorageError::Query(msg) => {
            error!(operation, error = %msg, "Database query error");
            Status::internal(format!("Database error: {msg}"))
        }
    };
    status
}

#[tonic::async_trait]
impl PersonHogReplica for PersonHogReplicaService {
    // ============================================================
    // Person lookups by ID/UUID
    // ============================================================

    async fn get_person(
        &self,
        request: Request<GetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let req = request.into_inner();

        let person = self
            .storage
            .get_person_by_id(req.team_id, req.person_id)
            .await
            .map_err(|e| log_and_convert_error(e, "get_person"))?;

        Ok(Response::new(GetPersonResponse {
            person: person.map(person_to_proto),
        }))
    }

    async fn get_persons(
        &self,
        request: Request<GetPersonsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        let req = request.into_inner();

        let persons = self
            .storage
            .get_persons_by_ids(req.team_id, &req.person_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_persons"))?;

        let found_ids: std::collections::HashSet<i64> = persons.iter().map(|p| p.id).collect();
        let missing_ids: Vec<i64> = req
            .person_ids
            .into_iter()
            .filter(|id| !found_ids.contains(id))
            .collect();

        Ok(Response::new(PersonsResponse {
            persons: persons.into_iter().map(person_to_proto).collect(),
            missing_ids,
        }))
    }

    async fn get_person_by_uuid(
        &self,
        request: Request<GetPersonByUuidRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let req = request.into_inner();

        let uuid = Uuid::parse_str(&req.uuid)
            .map_err(|e| Status::invalid_argument(format!("Invalid UUID: {e}")))?;

        let person = self
            .storage
            .get_person_by_uuid(req.team_id, uuid)
            .await
            .map_err(|e| log_and_convert_error(e, "get_person_by_uuid"))?;

        Ok(Response::new(GetPersonResponse {
            person: person.map(person_to_proto),
        }))
    }

    async fn get_persons_by_uuids(
        &self,
        request: Request<GetPersonsByUuidsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        let req = request.into_inner();

        let uuids: Vec<Uuid> = req
            .uuids
            .iter()
            .map(|s| Uuid::parse_str(s))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| Status::invalid_argument(format!("Invalid UUID: {e}")))?;

        let persons = self
            .storage
            .get_persons_by_uuids(req.team_id, &uuids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_persons_by_uuids"))?;

        Ok(Response::new(PersonsResponse {
            persons: persons.into_iter().map(person_to_proto).collect(),
            missing_ids: Vec::new(),
        }))
    }

    // ============================================================
    // Person lookups by Distinct ID (HIGHEST VOLUME)
    // ============================================================

    async fn get_person_by_distinct_id(
        &self,
        request: Request<GetPersonByDistinctIdRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let req = request.into_inner();

        let person = self
            .storage
            .get_person_by_distinct_id(req.team_id, &req.distinct_id)
            .await
            .map_err(|e| log_and_convert_error(e, "get_person_by_distinct_id"))?;

        Ok(Response::new(GetPersonResponse {
            person: person.map(person_to_proto),
        }))
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: Request<GetPersonsByDistinctIdsInTeamRequest>,
    ) -> Result<Response<PersonsByDistinctIdsInTeamResponse>, Status> {
        let req = request.into_inner();

        let results = self
            .storage
            .get_persons_by_distinct_ids_in_team(req.team_id, &req.distinct_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_persons_by_distinct_ids_in_team"))?;

        Ok(Response::new(PersonsByDistinctIdsInTeamResponse {
            results: results
                .into_iter()
                .map(|(distinct_id, person)| PersonWithDistinctIds {
                    distinct_id,
                    person: person.map(person_to_proto),
                })
                .collect(),
        }))
    }

    async fn get_persons_by_distinct_ids(
        &self,
        request: Request<GetPersonsByDistinctIdsRequest>,
    ) -> Result<Response<PersonsByDistinctIdsResponse>, Status> {
        let req = request.into_inner();

        let team_distinct_ids: Vec<(i64, String)> = req
            .team_distinct_ids
            .into_iter()
            .map(|tdi| (tdi.team_id, tdi.distinct_id))
            .collect();

        let results = self
            .storage
            .get_persons_by_distinct_ids_cross_team(&team_distinct_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_persons_by_distinct_ids"))?;

        Ok(Response::new(PersonsByDistinctIdsResponse {
            results: results
                .into_iter()
                .map(
                    |((team_id, distinct_id), person)| PersonWithTeamDistinctId {
                        key: Some(TeamDistinctId {
                            team_id,
                            distinct_id,
                        }),
                        person: person.map(person_to_proto),
                    },
                )
                .collect(),
        }))
    }

    // ============================================================
    // Distinct ID operations
    // ============================================================

    async fn get_distinct_ids_for_person(
        &self,
        request: Request<GetDistinctIdsForPersonRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonResponse>, Status> {
        let req = request.into_inner();

        let distinct_ids = self
            .storage
            .get_distinct_ids_for_person(req.team_id, req.person_id)
            .await
            .map_err(|e| log_and_convert_error(e, "get_distinct_ids_for_person"))?;

        Ok(Response::new(GetDistinctIdsForPersonResponse {
            distinct_ids: distinct_ids
                .into_iter()
                .map(|d| DistinctIdWithVersion {
                    distinct_id: d.distinct_id,
                    version: d.version,
                })
                .collect(),
        }))
    }

    async fn get_distinct_ids_for_persons(
        &self,
        request: Request<GetDistinctIdsForPersonsRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonsResponse>, Status> {
        let req = request.into_inner();

        let mappings = self
            .storage
            .get_distinct_ids_for_persons(req.team_id, &req.person_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_distinct_ids_for_persons"))?;

        // Group by person_id
        let mut by_person: HashMap<i64, Vec<DistinctIdWithVersion>> = HashMap::new();
        for mapping in mappings {
            by_person
                .entry(mapping.person_id)
                .or_default()
                .push(DistinctIdWithVersion {
                    distinct_id: mapping.distinct_id,
                    version: None, // This endpoint doesn't return version per distinct_id
                });
        }

        let person_distinct_ids = by_person
            .into_iter()
            .map(|(person_id, distinct_ids)| PersonDistinctIds {
                person_id,
                distinct_ids,
            })
            .collect();

        Ok(Response::new(GetDistinctIdsForPersonsResponse {
            person_distinct_ids,
        }))
    }

    // ============================================================
    // Feature Flag support
    // ============================================================

    async fn get_person_ids_and_hash_key_overrides(
        &self,
        request: Request<GetPersonIdsAndHashKeyOverridesRequest>,
    ) -> Result<Response<GetPersonIdsAndHashKeyOverridesResponse>, Status> {
        let req = request.into_inner();

        let results = self
            .storage
            .get_person_ids_and_hash_key_overrides(req.team_id, &req.distinct_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_person_ids_and_hash_key_overrides"))?;

        Ok(Response::new(GetPersonIdsAndHashKeyOverridesResponse {
            results: results
                .into_iter()
                .map(|r| PersonIdWithOverrides {
                    person_id: r.person_id,
                    distinct_id: r.distinct_id,
                    overrides: r
                        .overrides
                        .into_iter()
                        .map(|o| HashKeyOverride {
                            feature_flag_key: o.feature_flag_key,
                            hash_key: o.hash_key,
                        })
                        .collect(),
                })
                .collect(),
        }))
    }

    async fn get_existing_person_ids_with_override_keys(
        &self,
        request: Request<GetExistingPersonIdsWithOverrideKeysRequest>,
    ) -> Result<Response<GetExistingPersonIdsWithOverrideKeysResponse>, Status> {
        let req = request.into_inner();

        let results = self
            .storage
            .get_existing_person_ids_with_override_keys(req.team_id, &req.distinct_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_existing_person_ids_with_override_keys"))?;

        Ok(Response::new(
            GetExistingPersonIdsWithOverrideKeysResponse {
                results: results
                    .into_iter()
                    .map(|r| PersonIdWithOverrideKeys {
                        person_id: r.person_id,
                        existing_feature_flag_keys: r.existing_feature_flag_keys,
                    })
                    .collect(),
            },
        ))
    }

    // ============================================================
    // Cohort membership
    // ============================================================

    async fn check_cohort_membership(
        &self,
        request: Request<CheckCohortMembershipRequest>,
    ) -> Result<Response<CohortMembershipResponse>, Status> {
        let req = request.into_inner();

        let memberships = self
            .storage
            .check_cohort_membership(req.person_id, &req.cohort_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "check_cohort_membership"))?;

        Ok(Response::new(CohortMembershipResponse {
            memberships: memberships
                .into_iter()
                .map(|m| CohortMembership {
                    cohort_id: m.cohort_id,
                    is_member: m.is_member,
                })
                .collect(),
        }))
    }

    // ============================================================
    // Groups
    // ============================================================

    async fn get_group(
        &self,
        request: Request<GetGroupRequest>,
    ) -> Result<Response<GetGroupResponse>, Status> {
        let req = request.into_inner();

        let group = self
            .storage
            .get_group(req.team_id, req.group_type_index, &req.group_key)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group"))?;

        Ok(Response::new(GetGroupResponse {
            group: group.map(group_to_proto),
        }))
    }

    async fn get_groups(
        &self,
        request: Request<GetGroupsRequest>,
    ) -> Result<Response<GroupsResponse>, Status> {
        let req = request.into_inner();

        let identifiers: Vec<storage::GroupIdentifier> = req
            .group_identifiers
            .iter()
            .map(|gi| storage::GroupIdentifier {
                group_type_index: gi.group_type_index,
                group_key: gi.group_key.clone(),
            })
            .collect();

        let groups = self
            .storage
            .get_groups(req.team_id, &identifiers)
            .await
            .map_err(|e| log_and_convert_error(e, "get_groups"))?;

        // Find missing groups
        let found_keys: std::collections::HashSet<(i32, String)> = groups
            .iter()
            .map(|g| (g.group_type_index, g.group_key.clone()))
            .collect();

        let missing_groups = req
            .group_identifiers
            .into_iter()
            .filter(|gi| !found_keys.contains(&(gi.group_type_index, gi.group_key.clone())))
            .collect();

        Ok(Response::new(GroupsResponse {
            groups: groups.into_iter().map(group_to_proto).collect(),
            missing_groups,
        }))
    }

    async fn get_groups_batch(
        &self,
        request: Request<GetGroupsBatchRequest>,
    ) -> Result<Response<GetGroupsBatchResponse>, Status> {
        let req = request.into_inner();

        let keys: Vec<storage::GroupKey> = req
            .keys
            .iter()
            .map(|k| storage::GroupKey {
                team_id: k.team_id,
                group_type_index: k.group_type_index,
                group_key: k.group_key.clone(),
            })
            .collect();

        let results = self
            .storage
            .get_groups_batch(&keys)
            .await
            .map_err(|e| log_and_convert_error(e, "get_groups_batch"))?;

        // Build a map of found groups
        let found: HashMap<(i64, i32, String), storage::Group> = results
            .into_iter()
            .map(|(k, g)| ((k.team_id, k.group_type_index, k.group_key), g))
            .collect();

        // Return results for all requested keys
        let results = req
            .keys
            .into_iter()
            .map(|k| {
                let key = (k.team_id, k.group_type_index, k.group_key.clone());
                GroupWithKey {
                    key: Some(GroupKey {
                        team_id: k.team_id,
                        group_type_index: k.group_type_index,
                        group_key: k.group_key,
                    }),
                    group: found.get(&key).cloned().map(group_to_proto),
                }
            })
            .collect();

        Ok(Response::new(GetGroupsBatchResponse { results }))
    }

    // ============================================================
    // Group Type Mappings
    // ============================================================

    async fn get_group_type_mappings_by_team_id(
        &self,
        request: Request<GetGroupTypeMappingsByTeamIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        let req = request.into_inner();

        let mappings = self
            .storage
            .get_group_type_mappings_by_team_id(req.team_id)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_team_id"))?;

        Ok(Response::new(GroupTypeMappingsResponse {
            mappings: mappings
                .into_iter()
                .map(group_type_mapping_to_proto)
                .collect(),
        }))
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        request: Request<GetGroupTypeMappingsByTeamIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        let req = request.into_inner();

        let all_mappings = self
            .storage
            .get_group_type_mappings_by_team_ids(&req.team_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_team_ids"))?;

        // Group by team_id
        let mut by_team: HashMap<i64, Vec<GroupTypeMapping>> = HashMap::new();
        for mapping in all_mappings {
            by_team
                .entry(mapping.team_id)
                .or_default()
                .push(group_type_mapping_to_proto(mapping));
        }

        let results = req
            .team_ids
            .into_iter()
            .map(|team_id| GroupTypeMappingsByKey {
                key: team_id,
                mappings: by_team.remove(&team_id).unwrap_or_default(),
            })
            .collect();

        Ok(Response::new(GroupTypeMappingsBatchResponse { results }))
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        request: Request<GetGroupTypeMappingsByProjectIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        let req = request.into_inner();

        let mappings = self
            .storage
            .get_group_type_mappings_by_project_id(req.project_id)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_project_id"))?;

        Ok(Response::new(GroupTypeMappingsResponse {
            mappings: mappings
                .into_iter()
                .map(group_type_mapping_to_proto)
                .collect(),
        }))
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        request: Request<GetGroupTypeMappingsByProjectIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        let req = request.into_inner();

        let all_mappings = self
            .storage
            .get_group_type_mappings_by_project_ids(&req.project_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_project_ids"))?;

        // Group by project_id
        let mut by_project: HashMap<i64, Vec<GroupTypeMapping>> = HashMap::new();
        for mapping in all_mappings {
            by_project
                .entry(mapping.project_id)
                .or_default()
                .push(group_type_mapping_to_proto(mapping));
        }

        let results = req
            .project_ids
            .into_iter()
            .map(|project_id| GroupTypeMappingsByKey {
                key: project_id,
                mappings: by_project.remove(&project_id).unwrap_or_default(),
            })
            .collect();

        Ok(Response::new(GroupTypeMappingsBatchResponse { results }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use personhog_proto::personhog::types::v1::{
        GetGroupRequest, GetPersonRequest, GetPersonsByDistinctIdsInTeamRequest,
    };

    /// Mock storage that returns configurable errors for unit testing error handling
    struct FailingStorage {
        error: storage::StorageError,
    }

    impl FailingStorage {
        fn with_connection_error() -> Self {
            Self {
                error: storage::StorageError::Connection("connection refused".to_string()),
            }
        }

        fn with_pool_exhausted() -> Self {
            Self {
                error: storage::StorageError::PoolExhausted,
            }
        }

        fn with_query_error() -> Self {
            Self {
                error: storage::StorageError::Query("syntax error at position 42".to_string()),
            }
        }
    }

    #[async_trait]
    impl storage::PersonLookup for FailingStorage {
        async fn get_person_by_id(
            &self,
            _team_id: i64,
            _person_id: i64,
        ) -> storage::StorageResult<Option<storage::Person>> {
            Err(self.error.clone())
        }

        async fn get_person_by_uuid(
            &self,
            _team_id: i64,
            _uuid: Uuid,
        ) -> storage::StorageResult<Option<storage::Person>> {
            Err(self.error.clone())
        }

        async fn get_persons_by_ids(
            &self,
            _team_id: i64,
            _person_ids: &[i64],
        ) -> storage::StorageResult<Vec<storage::Person>> {
            Err(self.error.clone())
        }

        async fn get_persons_by_uuids(
            &self,
            _team_id: i64,
            _uuids: &[Uuid],
        ) -> storage::StorageResult<Vec<storage::Person>> {
            Err(self.error.clone())
        }

        async fn get_person_by_distinct_id(
            &self,
            _team_id: i64,
            _distinct_id: &str,
        ) -> storage::StorageResult<Option<storage::Person>> {
            Err(self.error.clone())
        }

        async fn get_persons_by_distinct_ids_in_team(
            &self,
            _team_id: i64,
            _distinct_ids: &[String],
        ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
            Err(self.error.clone())
        }

        async fn get_persons_by_distinct_ids_cross_team(
            &self,
            _team_distinct_ids: &[(i64, String)],
        ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
            Err(self.error.clone())
        }
    }

    #[async_trait]
    impl storage::DistinctIdLookup for FailingStorage {
        async fn get_distinct_ids_for_person(
            &self,
            _team_id: i64,
            _person_id: i64,
        ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
            Err(self.error.clone())
        }

        async fn get_distinct_ids_for_persons(
            &self,
            _team_id: i64,
            _person_ids: &[i64],
        ) -> storage::StorageResult<Vec<storage::DistinctIdMapping>> {
            Err(self.error.clone())
        }
    }

    #[async_trait]
    impl storage::FeatureFlagStorage for FailingStorage {
        async fn get_person_ids_and_hash_key_overrides(
            &self,
            _team_id: i64,
            _distinct_ids: &[String],
        ) -> storage::StorageResult<Vec<storage::PersonIdWithOverrides>> {
            Err(self.error.clone())
        }

        async fn get_existing_person_ids_with_override_keys(
            &self,
            _team_id: i64,
            _distinct_ids: &[String],
        ) -> storage::StorageResult<Vec<storage::PersonIdWithOverrideKeys>> {
            Err(self.error.clone())
        }
    }

    #[async_trait]
    impl storage::CohortStorage for FailingStorage {
        async fn check_cohort_membership(
            &self,
            _person_id: i64,
            _cohort_ids: &[i64],
        ) -> storage::StorageResult<Vec<storage::CohortMembership>> {
            Err(self.error.clone())
        }
    }

    #[async_trait]
    impl storage::GroupStorage for FailingStorage {
        async fn get_group(
            &self,
            _team_id: i64,
            _group_type_index: i32,
            _group_key: &str,
        ) -> storage::StorageResult<Option<storage::Group>> {
            Err(self.error.clone())
        }

        async fn get_groups(
            &self,
            _team_id: i64,
            _identifiers: &[storage::GroupIdentifier],
        ) -> storage::StorageResult<Vec<storage::Group>> {
            Err(self.error.clone())
        }

        async fn get_groups_batch(
            &self,
            _keys: &[storage::GroupKey],
        ) -> storage::StorageResult<Vec<(storage::GroupKey, storage::Group)>> {
            Err(self.error.clone())
        }

        async fn get_group_type_mappings_by_team_id(
            &self,
            _team_id: i64,
        ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
            Err(self.error.clone())
        }

        async fn get_group_type_mappings_by_team_ids(
            &self,
            _team_ids: &[i64],
        ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
            Err(self.error.clone())
        }

        async fn get_group_type_mappings_by_project_id(
            &self,
            _project_id: i64,
        ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
            Err(self.error.clone())
        }

        async fn get_group_type_mappings_by_project_ids(
            &self,
            _project_ids: &[i64],
        ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
            Err(self.error.clone())
        }
    }

    #[tokio::test]
    async fn test_connection_error_returns_unavailable() {
        let storage = Arc::new(FailingStorage::with_connection_error());
        let service = PersonHogReplicaService::new(storage);

        let result = service
            .get_person(Request::new(GetPersonRequest {
                team_id: 1,
                person_id: 1,
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
            .get_persons_by_distinct_ids_in_team(Request::new(
                GetPersonsByDistinctIdsInTeamRequest {
                    team_id: 1,
                    distinct_ids: vec!["user1".to_string(), "user2".to_string()],
                },
            ))
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
            }))
            .await;

        let status = result.unwrap_err();
        assert_eq!(status.code(), tonic::Code::Internal);
    }
}
