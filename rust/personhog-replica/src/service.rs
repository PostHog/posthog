use std::collections::HashMap;
use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use tracing::error;
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
    GroupTypeMapping, PersonsByDistinctIdsResponse,
    GroupTypeMappingsBatchResponse, GroupTypeMappingsByKey, GroupTypeMappingsResponse,
    GroupWithKey, GroupsResponse, HashKeyOverride, Person, PersonDistinctIds,
    PersonIdWithOverrideKeys, PersonIdWithOverrides, PersonWithDistinctIds,
    PersonWithTeamDistinctId, PersonsByDistinctIdsInTeamResponse, PersonsResponse, TeamDistinctId,
};
use tonic::{Request, Response, Status};
use uuid::Uuid;

use crate::storage::{self, PersonStorage};

pub struct PersonHogReplicaService {
    storage: Arc<dyn PersonStorage>,
}

impl PersonHogReplicaService {
    pub fn new(storage: Arc<dyn PersonStorage>) -> Self {
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
                .map(|((team_id, distinct_id), person)| PersonWithTeamDistinctId {
                    key: Some(TeamDistinctId {
                        team_id,
                        distinct_id,
                    }),
                    person: person.map(person_to_proto),
                })
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

        Ok(Response::new(GetExistingPersonIdsWithOverrideKeysResponse {
            results: results
                .into_iter()
                .map(|r| PersonIdWithOverrideKeys {
                    person_id: r.person_id,
                    existing_feature_flag_keys: r.existing_feature_flag_keys,
                })
                .collect(),
        }))
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
    use crate::storage::postgres::PostgresStorage;
    use personhog_proto::personhog::types::v1::{GroupIdentifier as ProtoGroupIdentifier, TeamDistinctId};
    use rand::Rng;
    use sqlx::postgres::PgPool;

    // ============================================================
    // Error handling tests with mock storage
    // ============================================================

    mod error_handling {
        use super::*;
        use async_trait::async_trait;

        /// Mock storage that returns configurable errors
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
        impl storage::PersonStorage for FailingStorage {
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

            async fn check_cohort_membership(
                &self,
                _person_id: i64,
                _cohort_ids: &[i64],
            ) -> storage::StorageResult<Vec<storage::CohortMembership>> {
                Err(self.error.clone())
            }

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

        // Make StorageError cloneable for the mock
        impl Clone for storage::StorageError {
            fn clone(&self) -> Self {
                match self {
                    Self::Connection(msg) => Self::Connection(msg.clone()),
                    Self::Query(msg) => Self::Query(msg.clone()),
                    Self::PoolExhausted => Self::PoolExhausted,
                }
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

    /// Test context for service-level testing.
    /// Provides a configured service instance and helpers for test data setup.
    struct ServiceTestContext {
        pool: Arc<PgPool>,
        pub service: PersonHogReplicaService,
        pub team_id: i64,
    }

    impl ServiceTestContext {
        async fn new() -> Self {
            let database_url =
                std::env::var("DATABASE_URL")
                    .unwrap_or_else(|_| "postgres://posthog:posthog@localhost:5432/posthog_persons".to_string());

            let pool = PgPool::connect(&database_url)
                .await
                .expect("Failed to connect to test database");
            let pool = Arc::new(pool);

            let storage = Arc::new(PostgresStorage::new(pool.clone()));
            let service = PersonHogReplicaService::new(storage);
            let team_id = rand::thread_rng().gen_range(1_000_000i64..100_000_000i64);

            Self { pool, service, team_id }
        }

        fn random_person_id() -> i64 {
            rand::thread_rng().gen_range(1_000_000i64..100_000_000i64)
        }

        /// Insert a test person with a distinct ID
        async fn insert_person(
            &self,
            distinct_id: &str,
            properties: Option<serde_json::Value>,
        ) -> (i64, Uuid) {
            let person_id = Self::random_person_id();
            let uuid = Uuid::now_v7();
            let properties = properties.unwrap_or_else(|| serde_json::json!({}));

            sqlx::query(
                r#"INSERT INTO posthog_person
                (id, uuid, team_id, properties, properties_last_updated_at,
                 properties_last_operation, created_at, version, is_identified, is_user_id)
                VALUES ($1, $2, $3, $4, '{}', '{}', NOW(), 0, false, NULL)
                ON CONFLICT DO NOTHING"#,
            )
            .bind(person_id)
            .bind(uuid)
            .bind(self.team_id)
            .bind(&properties)
            .execute(&*self.pool)
            .await
            .expect("Failed to insert person");

            sqlx::query(
                r#"INSERT INTO posthog_persondistinctid
                (distinct_id, person_id, team_id, version)
                VALUES ($1, $2, $3, 0)
                ON CONFLICT DO NOTHING"#,
            )
            .bind(distinct_id)
            .bind(person_id)
            .bind(self.team_id)
            .execute(&*self.pool)
            .await
            .expect("Failed to insert distinct ID");

            (person_id, uuid)
        }

        /// Insert a test group
        async fn insert_group(&self, group_type_index: i32, group_key: &str) -> i32 {
            let result = sqlx::query_scalar::<_, i32>(
                r#"INSERT INTO posthog_group
                (team_id, group_type_index, group_key, group_properties, created_at, version)
                VALUES ($1, $2, $3, '{}', NOW(), 0)
                ON CONFLICT (team_id, group_type_index, group_key) DO UPDATE SET version = posthog_group.version
                RETURNING id"#,
            )
            .bind(self.team_id)
            .bind(group_type_index)
            .bind(group_key)
            .fetch_one(&*self.pool)
            .await
            .expect("Failed to insert group");

            result
        }

        /// Insert a group type mapping
        async fn insert_group_type_mapping(&self, group_type: &str, group_type_index: i32) {
            sqlx::query(
                r#"INSERT INTO posthog_grouptypemapping
                (team_id, project_id, group_type, group_type_index, name_singular, name_plural)
                VALUES ($1, $2, $3, $4, NULL, NULL)
                ON CONFLICT DO NOTHING"#,
            )
            .bind(self.team_id)
            .bind(self.team_id)
            .bind(group_type)
            .bind(group_type_index)
            .execute(&*self.pool)
            .await
            .expect("Failed to insert group type mapping");
        }

        /// Add a person to a cohort
        async fn add_person_to_cohort(&self, person_id: i64, cohort_id: i64) {
            sqlx::query(
                r#"INSERT INTO posthog_cohortpeople
                (person_id, cohort_id, version)
                VALUES ($1, $2, 1)
                ON CONFLICT DO NOTHING"#,
            )
            .bind(person_id)
            .bind(cohort_id)
            .execute(&*self.pool)
            .await
            .expect("Failed to add person to cohort");
        }

        /// Clean up all test data for this context's team_id
        async fn cleanup(&self) {
            sqlx::query(
                "DELETE FROM posthog_cohortpeople WHERE person_id IN (SELECT id FROM posthog_person WHERE team_id = $1)",
            )
            .bind(self.team_id)
            .execute(&*self.pool)
            .await
            .ok();

            sqlx::query("DELETE FROM posthog_persondistinctid WHERE team_id = $1")
                .bind(self.team_id)
                .execute(&*self.pool)
                .await
                .ok();

            sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
                .bind(self.team_id)
                .execute(&*self.pool)
                .await
                .ok();

            sqlx::query("DELETE FROM posthog_group WHERE team_id = $1")
                .bind(self.team_id)
                .execute(&*self.pool)
                .await
                .ok();

            sqlx::query("DELETE FROM posthog_grouptypemapping WHERE team_id = $1")
                .bind(self.team_id)
                .execute(&*self.pool)
                .await
                .ok();
        }
    }

    // ============================================================
    // Person lookup tests
    // ============================================================

    #[tokio::test]
    async fn test_get_person_returns_person_when_found() {
        let ctx = ServiceTestContext::new().await;
        let (person_id, uuid) = ctx.insert_person("test@example.com", None).await;

        let response = ctx
            .service
            .get_person(Request::new(GetPersonRequest {
                team_id: ctx.team_id,
                person_id,
            }))
            .await
            .expect("RPC failed");

        let person = response.into_inner().person.expect("Person should be present");
        assert_eq!(person.id, person_id);
        assert_eq!(person.uuid, uuid.to_string());
        assert_eq!(person.team_id, ctx.team_id);

        ctx.cleanup().await;
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

        ctx.cleanup().await;
    }

    #[tokio::test]
    async fn test_get_person_by_uuid_returns_person() {
        let ctx = ServiceTestContext::new().await;
        let (person_id, uuid) = ctx.insert_person("uuid_test@example.com", None).await;

        let response = ctx
            .service
            .get_person_by_uuid(Request::new(GetPersonByUuidRequest {
                team_id: ctx.team_id,
                uuid: uuid.to_string(),
            }))
            .await
            .expect("RPC failed");

        let person = response.into_inner().person.expect("Person should be present");
        assert_eq!(person.id, person_id);

        ctx.cleanup().await;
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

        ctx.cleanup().await;
    }

    #[tokio::test]
    async fn test_get_persons_returns_found_and_missing() {
        let ctx = ServiceTestContext::new().await;
        let (person_id_1, _) = ctx.insert_person("batch1@example.com", None).await;
        let (person_id_2, _) = ctx.insert_person("batch2@example.com", None).await;
        let missing_id = 999999999i64;

        let response = ctx
            .service
            .get_persons(Request::new(GetPersonsRequest {
                team_id: ctx.team_id,
                person_ids: vec![person_id_1, person_id_2, missing_id],
            }))
            .await
            .expect("RPC failed");

        let inner = response.into_inner();
        assert_eq!(inner.persons.len(), 2);
        assert_eq!(inner.missing_ids, vec![missing_id]);

        ctx.cleanup().await;
    }

    // ============================================================
    // Distinct ID lookup tests
    // ============================================================

    #[tokio::test]
    async fn test_get_person_by_distinct_id_returns_person() {
        let ctx = ServiceTestContext::new().await;
        let distinct_id = "unique_distinct_id_123";
        let (person_id, _) = ctx.insert_person(distinct_id, None).await;

        let response = ctx
            .service
            .get_person_by_distinct_id(Request::new(GetPersonByDistinctIdRequest {
                team_id: ctx.team_id,
                distinct_id: distinct_id.to_string(),
            }))
            .await
            .expect("RPC failed");

        let person = response.into_inner().person.expect("Person should be present");
        assert_eq!(person.id, person_id);

        ctx.cleanup().await;
    }

    #[tokio::test]
    async fn test_get_persons_by_distinct_ids_in_team() {
        let ctx = ServiceTestContext::new().await;
        let (person_id_1, _) = ctx.insert_person("did_1", None).await;
        let (person_id_2, _) = ctx.insert_person("did_2", None).await;

        let response = ctx
            .service
            .get_persons_by_distinct_ids_in_team(Request::new(GetPersonsByDistinctIdsInTeamRequest {
                team_id: ctx.team_id,
                distinct_ids: vec!["did_1".to_string(), "did_2".to_string(), "did_missing".to_string()],
            }))
            .await
            .expect("RPC failed");

        let results = response.into_inner().results;
        assert_eq!(results.len(), 3);

        let found_ids: Vec<i64> = results
            .iter()
            .filter_map(|r| r.person.as_ref().map(|p| p.id))
            .collect();
        assert!(found_ids.contains(&person_id_1));
        assert!(found_ids.contains(&person_id_2));

        let missing = results.iter().find(|r| r.distinct_id == "did_missing").unwrap();
        assert!(missing.person.is_none());

        ctx.cleanup().await;
    }

    #[tokio::test]
    async fn test_get_persons_by_distinct_ids_cross_team() {
        let ctx = ServiceTestContext::new().await;
        let (person_id, _) = ctx.insert_person("cross_team_did", None).await;

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

        let found = results.iter().find(|r| {
            r.key.as_ref().map(|k| k.distinct_id.as_str()) == Some("cross_team_did")
        }).unwrap();
        assert_eq!(found.person.as_ref().unwrap().id, person_id);

        ctx.cleanup().await;
    }

    #[tokio::test]
    async fn test_get_distinct_ids_for_person() {
        let ctx = ServiceTestContext::new().await;
        let (person_id, _) = ctx.insert_person("primary_did", None).await;

        let response = ctx
            .service
            .get_distinct_ids_for_person(Request::new(GetDistinctIdsForPersonRequest {
                team_id: ctx.team_id,
                person_id,
            }))
            .await
            .expect("RPC failed");

        let distinct_ids = response.into_inner().distinct_ids;
        assert_eq!(distinct_ids.len(), 1);
        assert_eq!(distinct_ids[0].distinct_id, "primary_did");

        ctx.cleanup().await;
    }

    // ============================================================
    // Group tests
    // ============================================================

    #[tokio::test]
    async fn test_get_group_returns_group_when_found() {
        let ctx = ServiceTestContext::new().await;
        ctx.insert_group(0, "company_abc").await;

        let response = ctx
            .service
            .get_group(Request::new(GetGroupRequest {
                team_id: ctx.team_id,
                group_type_index: 0,
                group_key: "company_abc".to_string(),
            }))
            .await
            .expect("RPC failed");

        let group = response.into_inner().group.expect("Group should be present");
        assert_eq!(group.group_key, "company_abc");
        assert_eq!(group.group_type_index, 0);

        ctx.cleanup().await;
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

        ctx.cleanup().await;
    }

    #[tokio::test]
    async fn test_get_groups_returns_found_and_missing() {
        let ctx = ServiceTestContext::new().await;
        ctx.insert_group(0, "group_a").await;
        ctx.insert_group(1, "group_b").await;

        let response = ctx
            .service
            .get_groups(Request::new(GetGroupsRequest {
                team_id: ctx.team_id,
                group_identifiers: vec![
                    ProtoGroupIdentifier { group_type_index: 0, group_key: "group_a".to_string() },
                    ProtoGroupIdentifier { group_type_index: 1, group_key: "group_b".to_string() },
                    ProtoGroupIdentifier { group_type_index: 2, group_key: "missing".to_string() },
                ],
            }))
            .await
            .expect("RPC failed");

        let inner = response.into_inner();
        assert_eq!(inner.groups.len(), 2);
        assert_eq!(inner.missing_groups.len(), 1);
        assert_eq!(inner.missing_groups[0].group_key, "missing");

        ctx.cleanup().await;
    }

    // ============================================================
    // Group type mapping tests
    // ============================================================

    #[tokio::test]
    async fn test_get_group_type_mappings_by_team_id() {
        let ctx = ServiceTestContext::new().await;
        ctx.insert_group_type_mapping("organization", 0).await;
        ctx.insert_group_type_mapping("project", 1).await;

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

        ctx.cleanup().await;
    }

    // ============================================================
    // Cohort membership tests
    // ============================================================

    #[tokio::test]
    async fn test_check_cohort_membership() {
        let ctx = ServiceTestContext::new().await;
        let (person_id, _) = ctx.insert_person("cohort_user", None).await;

        let cohort_member = 1001i64;
        let cohort_not_member = 1002i64;
        ctx.add_person_to_cohort(person_id, cohort_member).await;

        let response = ctx
            .service
            .check_cohort_membership(Request::new(CheckCohortMembershipRequest {
                person_id,
                cohort_ids: vec![cohort_member, cohort_not_member],
            }))
            .await
            .expect("RPC failed");

        let memberships = response.into_inner().memberships;
        assert_eq!(memberships.len(), 2);

        let member = memberships.iter().find(|m| m.cohort_id == cohort_member).unwrap();
        let not_member = memberships.iter().find(|m| m.cohort_id == cohort_not_member).unwrap();

        assert!(member.is_member);
        assert!(!not_member.is_member);

        ctx.cleanup().await;
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
        let (person_id, _) = ctx.insert_person("props_user", Some(props.clone())).await;

        let response = ctx
            .service
            .get_person(Request::new(GetPersonRequest {
                team_id: ctx.team_id,
                person_id,
            }))
            .await
            .expect("RPC failed");

        let person = response.into_inner().person.unwrap();
        let deserialized: serde_json::Value = serde_json::from_slice(&person.properties)
            .expect("Properties should be valid JSON");

        assert_eq!(deserialized["email"], "props@example.com");
        assert_eq!(deserialized["plan"], "enterprise");
        assert_eq!(deserialized["nested"]["key"], "value");

        ctx.cleanup().await;
    }

    // ============================================================
    // gRPC transport smoke tests
    //
    // These tests verify proto serialization works end-to-end by
    // spinning up a real gRPC server and making calls through a client.
    // ============================================================

    mod grpc_transport {
        use super::*;
        use personhog_proto::personhog::replica::v1::person_hog_replica_client::PersonHogReplicaClient;
        use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplicaServer;
        use tokio::net::TcpListener;
        use tonic::transport::Server;

        /// Test context that includes a running gRPC server and client
        struct GrpcTestContext {
            pool: Arc<PgPool>,
            client: PersonHogReplicaClient<tonic::transport::Channel>,
            team_id: i64,
            _shutdown: tokio::sync::oneshot::Sender<()>,
        }

        impl GrpcTestContext {
            async fn new() -> Self {
                let database_url = std::env::var("DATABASE_URL")
                    .unwrap_or_else(|_| "postgres://posthog:posthog@localhost:5432/posthog_persons".to_string());

                let pool = PgPool::connect(&database_url)
                    .await
                    .expect("Failed to connect to test database");
                let pool = Arc::new(pool);

                let storage = Arc::new(PostgresStorage::new(pool.clone()));
                let service = PersonHogReplicaService::new(storage);
                let team_id = rand::thread_rng().gen_range(1_000_000i64..100_000_000i64);

                // Bind to random port
                let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
                let addr = listener.local_addr().unwrap();

                // Shutdown channel
                let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

                // Start server in background
                tokio::spawn(async move {
                    Server::builder()
                        .add_service(PersonHogReplicaServer::new(service))
                        .serve_with_incoming_shutdown(
                            tokio_stream::wrappers::TcpListenerStream::new(listener),
                            async { shutdown_rx.await.ok(); },
                        )
                        .await
                        .ok();
                });

                // Give server a moment to start
                tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;

                // Connect client
                let client = PersonHogReplicaClient::connect(format!("http://{addr}"))
                    .await
                    .expect("Failed to connect to gRPC server");

                Self {
                    pool,
                    client,
                    team_id,
                    _shutdown: shutdown_tx,
                }
            }

            async fn insert_person(&self, distinct_id: &str) -> (i64, Uuid) {
                let person_id = rand::thread_rng().gen_range(1_000_000i64..100_000_000i64);
                let uuid = Uuid::now_v7();

                sqlx::query(
                    r#"INSERT INTO posthog_person
                    (id, uuid, team_id, properties, properties_last_updated_at,
                     properties_last_operation, created_at, version, is_identified, is_user_id)
                    VALUES ($1, $2, $3, '{}', '{}', '{}', NOW(), 0, false, NULL)
                    ON CONFLICT DO NOTHING"#,
                )
                .bind(person_id)
                .bind(uuid)
                .bind(self.team_id)
                .execute(&*self.pool)
                .await
                .expect("Failed to insert person");

                sqlx::query(
                    r#"INSERT INTO posthog_persondistinctid
                    (distinct_id, person_id, team_id, version)
                    VALUES ($1, $2, $3, 0)
                    ON CONFLICT DO NOTHING"#,
                )
                .bind(distinct_id)
                .bind(person_id)
                .bind(self.team_id)
                .execute(&*self.pool)
                .await
                .expect("Failed to insert distinct ID");

                (person_id, uuid)
            }

            async fn cleanup(&self) {
                sqlx::query("DELETE FROM posthog_persondistinctid WHERE team_id = $1")
                    .bind(self.team_id)
                    .execute(&*self.pool)
                    .await
                    .ok();

                sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
                    .bind(self.team_id)
                    .execute(&*self.pool)
                    .await
                    .ok();
            }
        }

        #[tokio::test]
        async fn test_grpc_get_person_roundtrip() {
            let mut ctx = GrpcTestContext::new().await;
            let (person_id, uuid) = ctx.insert_person("grpc_test@example.com").await;

            let response = ctx
                .client
                .get_person(GetPersonRequest {
                    team_id: ctx.team_id,
                    person_id,
                })
                .await
                .expect("gRPC call failed");

            let person = response.into_inner().person.expect("Person should exist");
            assert_eq!(person.id, person_id);
            assert_eq!(person.uuid, uuid.to_string());
            assert_eq!(person.team_id, ctx.team_id);

            ctx.cleanup().await;
        }

        #[tokio::test]
        async fn test_grpc_batch_lookup_roundtrip() {
            let mut ctx = GrpcTestContext::new().await;
            let (person_id_1, _) = ctx.insert_person("grpc_batch_1").await;
            let (person_id_2, _) = ctx.insert_person("grpc_batch_2").await;

            let response = ctx
                .client
                .get_persons_by_distinct_ids_in_team(GetPersonsByDistinctIdsInTeamRequest {
                    team_id: ctx.team_id,
                    distinct_ids: vec![
                        "grpc_batch_1".to_string(),
                        "grpc_batch_2".to_string(),
                        "grpc_batch_missing".to_string(),
                    ],
                })
                .await
                .expect("gRPC call failed");

            let results = response.into_inner().results;
            assert_eq!(results.len(), 3);

            let found: Vec<i64> = results
                .iter()
                .filter_map(|r| r.person.as_ref().map(|p| p.id))
                .collect();
            assert!(found.contains(&person_id_1));
            assert!(found.contains(&person_id_2));
            assert_eq!(found.len(), 2);

            ctx.cleanup().await;
        }

        #[tokio::test]
        async fn test_grpc_invalid_uuid_returns_error() {
            let mut ctx = GrpcTestContext::new().await;

            let result = ctx
                .client
                .get_person_by_uuid(GetPersonByUuidRequest {
                    team_id: ctx.team_id,
                    uuid: "not-a-valid-uuid".to_string(),
                })
                .await;

            assert!(result.is_err());
            let status = result.unwrap_err();
            assert_eq!(status.code(), tonic::Code::InvalidArgument);

            ctx.cleanup().await;
        }
    }
}
