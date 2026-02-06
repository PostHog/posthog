mod consistency;
mod error;
mod types;

#[cfg(test)]
mod tests;

use std::collections::HashMap;
use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembership, CohortMembershipResponse,
    DeleteHashKeyOverridesByTeamsRequest, DeleteHashKeyOverridesByTeamsResponse,
    DistinctIdWithVersion, GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest, GetDistinctIdsForPersonsResponse, GetGroupRequest,
    GetGroupResponse, GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest, GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest, GetGroupsBatchRequest, GetGroupsBatchResponse,
    GetGroupsRequest, GetHashKeyOverrideContextRequest, GetHashKeyOverrideContextResponse,
    GetPersonByDistinctIdRequest, GetPersonByUuidRequest, GetPersonRequest, GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest, GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest,
    GetPersonsRequest, GroupKey, GroupTypeMapping, GroupTypeMappingsBatchResponse,
    GroupTypeMappingsByKey, GroupTypeMappingsResponse, GroupWithKey, GroupsResponse,
    HashKeyOverride, HashKeyOverrideContext as ProtoHashKeyOverrideContext, PersonDistinctIds,
    PersonWithDistinctIds, PersonWithTeamDistinctId, PersonsByDistinctIdsInTeamResponse,
    PersonsByDistinctIdsResponse, PersonsResponse, TeamDistinctId, UpsertHashKeyOverridesRequest,
    UpsertHashKeyOverridesResponse,
};
use tonic::{Request, Response, Status};
use uuid::Uuid;

use crate::storage::{self, FullStorage};

use consistency::{reject_strong_consistency, to_storage_consistency};
use error::log_and_convert_error;

pub struct PersonHogReplicaService {
    storage: Arc<dyn FullStorage>,
}

impl PersonHogReplicaService {
    pub fn new(storage: Arc<dyn FullStorage>) -> Self {
        Self { storage }
    }
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
        reject_strong_consistency(&req.read_options)?;

        let person = self
            .storage
            .get_person_by_id(req.team_id, req.person_id)
            .await
            .map_err(|e| log_and_convert_error(e, "get_person"))?;

        Ok(Response::new(GetPersonResponse {
            person: person.map(Into::into),
        }))
    }

    async fn get_persons(
        &self,
        request: Request<GetPersonsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        let req = request.into_inner();
        reject_strong_consistency(&req.read_options)?;

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
            persons: persons.into_iter().map(Into::into).collect(),
            missing_ids,
        }))
    }

    async fn get_person_by_uuid(
        &self,
        request: Request<GetPersonByUuidRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let req = request.into_inner();
        reject_strong_consistency(&req.read_options)?;

        let uuid = Uuid::parse_str(&req.uuid)
            .map_err(|e| Status::invalid_argument(format!("Invalid UUID: {e}")))?;

        let person = self
            .storage
            .get_person_by_uuid(req.team_id, uuid)
            .await
            .map_err(|e| log_and_convert_error(e, "get_person_by_uuid"))?;

        Ok(Response::new(GetPersonResponse {
            person: person.map(Into::into),
        }))
    }

    async fn get_persons_by_uuids(
        &self,
        request: Request<GetPersonsByUuidsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        let req = request.into_inner();
        reject_strong_consistency(&req.read_options)?;

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
            persons: persons.into_iter().map(Into::into).collect(),
            missing_ids: Vec::new(),
        }))
    }

    // ============================================================
    // Person lookups by Distinct ID
    // ============================================================

    async fn get_person_by_distinct_id(
        &self,
        request: Request<GetPersonByDistinctIdRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let req = request.into_inner();
        reject_strong_consistency(&req.read_options)?;

        let person = self
            .storage
            .get_person_by_distinct_id(req.team_id, &req.distinct_id)
            .await
            .map_err(|e| log_and_convert_error(e, "get_person_by_distinct_id"))?;

        Ok(Response::new(GetPersonResponse {
            person: person.map(Into::into),
        }))
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: Request<GetPersonsByDistinctIdsInTeamRequest>,
    ) -> Result<Response<PersonsByDistinctIdsInTeamResponse>, Status> {
        let req = request.into_inner();
        reject_strong_consistency(&req.read_options)?;

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
                    person: person.map(Into::into),
                })
                .collect(),
        }))
    }

    async fn get_persons_by_distinct_ids(
        &self,
        request: Request<GetPersonsByDistinctIdsRequest>,
    ) -> Result<Response<PersonsByDistinctIdsResponse>, Status> {
        let req = request.into_inner();
        reject_strong_consistency(&req.read_options)?;

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
                        person: person.map(Into::into),
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
        let consistency = to_storage_consistency(&req.read_options);

        let distinct_ids = self
            .storage
            .get_distinct_ids_for_person(req.team_id, req.person_id, consistency)
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
        let consistency = to_storage_consistency(&req.read_options);

        let mappings = self
            .storage
            .get_distinct_ids_for_persons(req.team_id, &req.person_ids, consistency)
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

    async fn get_hash_key_override_context(
        &self,
        request: Request<GetHashKeyOverrideContextRequest>,
    ) -> Result<Response<GetHashKeyOverrideContextResponse>, Status> {
        let req = request.into_inner();

        // Strong consistency routes to the primary database, which is important for this endpoint:
        // 1. The caller has just written hash key overrides and needs to read them back
        // 2. The caller needs the latest person existence state (e.g., for write validation)
        //
        // Note: This implementation queries person data on the primary database directly to attain strong consistency.
        // When personhog-leader is implemented, person table data will be cached on leader pods.
        // At that point, strong consistency for person data will require routing to the leader
        // service rather than the primary database.
        // Once that service is implemented and in use, using personhog-replica for this query will have to be
        // re-assessed as its consistency guarantee will be broken
        let consistency = to_storage_consistency(&req.read_options);

        let results = self
            .storage
            .get_hash_key_override_context(
                req.team_id,
                &req.distinct_ids,
                req.check_person_exists,
                consistency,
            )
            .await
            .map_err(|e| log_and_convert_error(e, "get_hash_key_override_context"))?;

        Ok(Response::new(GetHashKeyOverrideContextResponse {
            results: results
                .into_iter()
                .map(|r| ProtoHashKeyOverrideContext {
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
                    existing_feature_flag_keys: r.existing_feature_flag_keys,
                })
                .collect(),
        }))
    }

    async fn upsert_hash_key_overrides(
        &self,
        request: Request<UpsertHashKeyOverridesRequest>,
    ) -> Result<Response<UpsertHashKeyOverridesResponse>, Status> {
        let req = request.into_inner();

        let overrides: Vec<storage::HashKeyOverrideInput> = req
            .overrides
            .into_iter()
            .map(|o| storage::HashKeyOverrideInput {
                person_id: o.person_id,
                feature_flag_key: o.feature_flag_key,
            })
            .collect();

        let inserted_count = self
            .storage
            .upsert_hash_key_overrides(req.team_id, &overrides, &req.hash_key)
            .await
            .map_err(|e| log_and_convert_error(e, "upsert_hash_key_overrides"))?;

        Ok(Response::new(UpsertHashKeyOverridesResponse {
            inserted_count,
        }))
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        request: Request<DeleteHashKeyOverridesByTeamsRequest>,
    ) -> Result<Response<DeleteHashKeyOverridesByTeamsResponse>, Status> {
        let req = request.into_inner();

        let deleted_count = self
            .storage
            .delete_hash_key_overrides_by_teams(&req.team_ids)
            .await
            .map_err(|e| log_and_convert_error(e, "delete_hash_key_overrides_by_teams"))?;

        Ok(Response::new(DeleteHashKeyOverridesByTeamsResponse {
            deleted_count,
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
        let consistency = to_storage_consistency(&req.read_options);

        let memberships = self
            .storage
            .check_cohort_membership(req.person_id, &req.cohort_ids, consistency)
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
        let consistency = to_storage_consistency(&req.read_options);

        let group = self
            .storage
            .get_group(
                req.team_id,
                req.group_type_index,
                &req.group_key,
                consistency,
            )
            .await
            .map_err(|e| log_and_convert_error(e, "get_group"))?;

        Ok(Response::new(GetGroupResponse {
            group: group.map(Into::into),
        }))
    }

    async fn get_groups(
        &self,
        request: Request<GetGroupsRequest>,
    ) -> Result<Response<GroupsResponse>, Status> {
        let req = request.into_inner();
        let consistency = to_storage_consistency(&req.read_options);

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
            .get_groups(req.team_id, &identifiers, consistency)
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
            groups: groups.into_iter().map(Into::into).collect(),
            missing_groups,
        }))
    }

    async fn get_groups_batch(
        &self,
        request: Request<GetGroupsBatchRequest>,
    ) -> Result<Response<GetGroupsBatchResponse>, Status> {
        let req = request.into_inner();
        let consistency = to_storage_consistency(&req.read_options);

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
            .get_groups_batch(&keys, consistency)
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
                    group: found.get(&key).cloned().map(Into::into),
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
        let consistency = to_storage_consistency(&req.read_options);

        let mappings = self
            .storage
            .get_group_type_mappings_by_team_id(req.team_id, consistency)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_team_id"))?;

        Ok(Response::new(GroupTypeMappingsResponse {
            mappings: mappings.into_iter().map(Into::into).collect(),
        }))
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        request: Request<GetGroupTypeMappingsByTeamIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        let req = request.into_inner();
        let consistency = to_storage_consistency(&req.read_options);

        let all_mappings = self
            .storage
            .get_group_type_mappings_by_team_ids(&req.team_ids, consistency)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_team_ids"))?;

        // Group by team_id
        let mut by_team: HashMap<i64, Vec<GroupTypeMapping>> = HashMap::new();
        for mapping in all_mappings {
            by_team
                .entry(mapping.team_id)
                .or_default()
                .push(Into::into(mapping));
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
        let consistency = to_storage_consistency(&req.read_options);

        let mappings = self
            .storage
            .get_group_type_mappings_by_project_id(req.project_id, consistency)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_project_id"))?;

        Ok(Response::new(GroupTypeMappingsResponse {
            mappings: mappings.into_iter().map(Into::into).collect(),
        }))
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        request: Request<GetGroupTypeMappingsByProjectIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        let req = request.into_inner();
        let consistency = to_storage_consistency(&req.read_options);

        let all_mappings = self
            .storage
            .get_group_type_mappings_by_project_ids(&req.project_ids, consistency)
            .await
            .map_err(|e| log_and_convert_error(e, "get_group_type_mappings_by_project_ids"))?;

        // Group by project_id
        let mut by_project: HashMap<i64, Vec<GroupTypeMapping>> = HashMap::new();
        for mapping in all_mappings {
            by_project
                .entry(mapping.project_id)
                .or_default()
                .push(Into::into(mapping));
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
