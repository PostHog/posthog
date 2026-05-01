mod leader;
mod replica;
mod retry;
mod stash;

pub use leader::{AddressResolver, LeaderBackend, LeaderBackendConfig};
pub use replica::{ReplicaBackend, ReplicaBackendConfig};
pub use stash::{StashDecision, StashTable, StashedRequest};

use async_trait::async_trait;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembershipResponse, CountCohortMembersRequest,
    CountCohortMembersResponse, DeleteCohortMemberRequest, DeleteCohortMemberResponse,
    DeleteCohortMembersBulkRequest, DeleteCohortMembersBulkResponse,
    DeleteHashKeyOverridesByTeamsRequest, DeleteHashKeyOverridesByTeamsResponse,
    DeletePersonsBatchForTeamRequest, DeletePersonsBatchForTeamResponse, DeletePersonsRequest,
    DeletePersonsResponse, GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest, GetDistinctIdsForPersonsResponse, GetGroupRequest,
    GetGroupResponse, GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest, GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest, GetGroupsBatchRequest, GetGroupsBatchResponse,
    GetGroupsRequest, GetHashKeyOverrideContextRequest, GetHashKeyOverrideContextResponse,
    GetPersonByDistinctIdRequest, GetPersonByUuidRequest, GetPersonRequest, GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest, GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest,
    GetPersonsRequest, GroupTypeMappingsBatchResponse, GroupTypeMappingsResponse, GroupsResponse,
    InsertCohortMembersRequest, InsertCohortMembersResponse, ListCohortMemberIdsRequest,
    ListCohortMemberIdsResponse, PersonsByDistinctIdsInTeamResponse, PersonsByDistinctIdsResponse,
    PersonsResponse, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
    UpsertHashKeyOverridesRequest, UpsertHashKeyOverridesResponse,
};
use tonic::Status;

/// Trait for leader-specific operations: strong-consistency reads and writes.
/// Only the leader backend implements this (partition-aware routing to leader pods).
#[async_trait]
pub trait LeaderOps: Send + Sync {
    async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status>;
    async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status>;
}

/// Trait defining the replica backend interface for read operations.
/// The replica serves eventual-consistency reads from Postgres replicas.
#[async_trait]
pub trait PersonHogBackend: Send + Sync {
    // Person lookups by ID
    async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status>;
    async fn get_persons(&self, request: GetPersonsRequest) -> Result<PersonsResponse, Status>;
    async fn get_person_by_uuid(
        &self,
        request: GetPersonByUuidRequest,
    ) -> Result<GetPersonResponse, Status>;
    async fn get_persons_by_uuids(
        &self,
        request: GetPersonsByUuidsRequest,
    ) -> Result<PersonsResponse, Status>;

    // Person lookups by distinct ID
    async fn get_person_by_distinct_id(
        &self,
        request: GetPersonByDistinctIdRequest,
    ) -> Result<GetPersonResponse, Status>;
    async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: GetPersonsByDistinctIdsInTeamRequest,
    ) -> Result<PersonsByDistinctIdsInTeamResponse, Status>;
    async fn get_persons_by_distinct_ids(
        &self,
        request: GetPersonsByDistinctIdsRequest,
    ) -> Result<PersonsByDistinctIdsResponse, Status>;

    // Distinct ID operations
    async fn get_distinct_ids_for_person(
        &self,
        request: GetDistinctIdsForPersonRequest,
    ) -> Result<GetDistinctIdsForPersonResponse, Status>;
    async fn get_distinct_ids_for_persons(
        &self,
        request: GetDistinctIdsForPersonsRequest,
    ) -> Result<GetDistinctIdsForPersonsResponse, Status>;

    // Feature flag hash key override support
    async fn get_hash_key_override_context(
        &self,
        request: GetHashKeyOverrideContextRequest,
    ) -> Result<GetHashKeyOverrideContextResponse, Status>;
    async fn upsert_hash_key_overrides(
        &self,
        request: UpsertHashKeyOverridesRequest,
    ) -> Result<UpsertHashKeyOverridesResponse, Status>;
    async fn delete_hash_key_overrides_by_teams(
        &self,
        request: DeleteHashKeyOverridesByTeamsRequest,
    ) -> Result<DeleteHashKeyOverridesByTeamsResponse, Status>;

    // Person deletes
    async fn delete_persons(
        &self,
        request: DeletePersonsRequest,
    ) -> Result<DeletePersonsResponse, Status>;
    async fn delete_persons_batch_for_team(
        &self,
        request: DeletePersonsBatchForTeamRequest,
    ) -> Result<DeletePersonsBatchForTeamResponse, Status>;

    // Cohort membership
    async fn check_cohort_membership(
        &self,
        request: CheckCohortMembershipRequest,
    ) -> Result<CohortMembershipResponse, Status>;
    async fn count_cohort_members(
        &self,
        request: CountCohortMembersRequest,
    ) -> Result<CountCohortMembersResponse, Status>;
    async fn delete_cohort_member(
        &self,
        request: DeleteCohortMemberRequest,
    ) -> Result<DeleteCohortMemberResponse, Status>;
    async fn delete_cohort_members_bulk(
        &self,
        request: DeleteCohortMembersBulkRequest,
    ) -> Result<DeleteCohortMembersBulkResponse, Status>;
    async fn insert_cohort_members(
        &self,
        request: InsertCohortMembersRequest,
    ) -> Result<InsertCohortMembersResponse, Status>;
    async fn list_cohort_member_ids(
        &self,
        request: ListCohortMemberIdsRequest,
    ) -> Result<ListCohortMemberIdsResponse, Status>;

    // Groups
    async fn get_group(&self, request: GetGroupRequest) -> Result<GetGroupResponse, Status>;
    async fn get_groups(&self, request: GetGroupsRequest) -> Result<GroupsResponse, Status>;
    async fn get_groups_batch(
        &self,
        request: GetGroupsBatchRequest,
    ) -> Result<GetGroupsBatchResponse, Status>;

    // Group type mappings
    async fn get_group_type_mappings_by_team_id(
        &self,
        request: GetGroupTypeMappingsByTeamIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status>;
    async fn get_group_type_mappings_by_team_ids(
        &self,
        request: GetGroupTypeMappingsByTeamIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status>;
    async fn get_group_type_mappings_by_project_id(
        &self,
        request: GetGroupTypeMappingsByProjectIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status>;
    async fn get_group_type_mappings_by_project_ids(
        &self,
        request: GetGroupTypeMappingsByProjectIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status>;
}
