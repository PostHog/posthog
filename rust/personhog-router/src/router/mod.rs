mod routing;

pub use routing::{DataCategory, OperationType, RouteDecision};

use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use personhog_proto::personhog::leader::v1::{
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembershipResponse, DeleteHashKeyOverridesByTeamsRequest,
    DeleteHashKeyOverridesByTeamsResponse, GetDistinctIdsForPersonRequest,
    GetDistinctIdsForPersonResponse, GetDistinctIdsForPersonsRequest,
    GetDistinctIdsForPersonsResponse, GetGroupRequest, GetGroupResponse,
    GetGroupTypeMappingsByProjectIdRequest, GetGroupTypeMappingsByProjectIdsRequest,
    GetGroupTypeMappingsByTeamIdRequest, GetGroupTypeMappingsByTeamIdsRequest,
    GetGroupsBatchRequest, GetGroupsBatchResponse, GetGroupsRequest,
    GetHashKeyOverrideContextRequest, GetHashKeyOverrideContextResponse,
    GetPersonByDistinctIdRequest, GetPersonByUuidRequest, GetPersonRequest, GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest, GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest,
    GetPersonsRequest, GroupTypeMappingsBatchResponse, GroupTypeMappingsResponse, GroupsResponse,
    PersonsByDistinctIdsInTeamResponse, PersonsByDistinctIdsResponse, PersonsResponse,
    UpsertHashKeyOverridesRequest, UpsertHashKeyOverridesResponse,
};
use tonic::Status;

use crate::backend::{LeaderOps, PersonHogBackend};
use routing::{get_consistency, route_request};

/// Calls a replica backend method with timing instrumentation.
macro_rules! call_backend {
    ($self:expr, $method_name:expr, $method:ident, $request:expr) => {{
        counter!(
            "personhog_router_backend_requests_total",
            "method" => $method_name,
            "backend" => "replica"
        )
        .increment(1);

        let start = Instant::now();
        let result = $self.replica_backend.$method($request).await;
        let duration_ms = start.elapsed().as_secs_f64() * 1000.0;

        histogram!(
            "personhog_router_backend_duration_ms",
            "method" => $method_name,
            "backend" => "replica"
        )
        .record(duration_ms);

        if result.is_err() {
            counter!(
                "personhog_router_backend_errors_total",
                "method" => $method_name,
                "backend" => "replica"
            )
            .increment(1);
        }

        result
    }};
}

/// Macro to call a leader operation with timing instrumentation.
macro_rules! call_leader {
    ($self:expr, $method_name:expr, $method:ident, $request:expr) => {{
        let leader = $self.leader_ops.as_ref().ok_or_else(|| {
            Status::unimplemented("leader backend not configured for this router")
        })?;

        counter!(
            "personhog_router_backend_requests_total",
            "method" => $method_name,
            "backend" => "leader"
        )
        .increment(1);

        let start = Instant::now();
        let result = leader.$method($request).await;
        let duration_ms = start.elapsed().as_secs_f64() * 1000.0;

        histogram!(
            "personhog_router_backend_duration_ms",
            "method" => $method_name,
            "backend" => "leader"
        )
        .record(duration_ms);

        if result.is_err() {
            counter!(
                "personhog_router_backend_errors_total",
                "method" => $method_name,
                "backend" => "leader"
            )
            .increment(1);
        }

        result
    }};
}

/// PersonHogRouter coordinates routing requests to the appropriate backend.
///
/// # Routing Logic
///
/// | Data Type       | Operation | Consistency | Target Backend           |
/// |-----------------|-----------|-------------|--------------------------|
/// | Person data     | Read      | EVENTUAL    | personhog-replica        |
/// | Person data     | Read      | STRONG      | personhog-leader (Phase 2) |
/// | Person data     | Write     | -           | personhog-leader (Phase 2) |
/// | Non-person data | Read      | EVENTUAL    | personhog-replica        |
/// | Non-person data | Read      | STRONG      | personhog-replica (primary) |
/// | Non-person data | Write     | -           | personhog-replica        |
///
/// Non-person data includes: hash key overrides, cohort membership, groups, group type mappings
///
/// # Metrics
///
/// Records backend-specific metrics:
/// - `personhog_router_backend_requests_total` - counter by method and backend
/// - `personhog_router_backend_duration_ms` - histogram by method and backend
/// - `personhog_router_backend_errors_total` - counter by method and backend
pub struct PersonHogRouter {
    replica_backend: Arc<dyn PersonHogBackend>,
    leader_ops: Option<Arc<dyn LeaderOps>>,
}

impl PersonHogRouter {
    pub fn new(replica_backend: Arc<dyn PersonHogBackend>) -> Self {
        Self {
            replica_backend,
            leader_ops: None,
        }
    }

    pub fn with_leader(mut self, leader_ops: Arc<dyn LeaderOps>) -> Self {
        self.leader_ops = Some(leader_ops);
        self
    }

    /// Validate that a read request routes to replica (not leader).
    /// Person data reads with STRONG consistency require the leader, but only
    /// `get_person` supports that. All other person data reads must use EVENTUAL.
    #[allow(clippy::result_large_err)]
    fn require_replica(
        &self,
        category: DataCategory,
        read_options: &Option<personhog_proto::personhog::types::v1::ReadOptions>,
    ) -> Result<(), Status> {
        let decision = route_request(category, OperationType::Read, get_consistency(read_options))?;
        if decision == RouteDecision::Leader {
            return Err(Status::unimplemented(
                "strong consistency reads are only supported for get_person",
            ));
        }
        Ok(())
    }

    // ============================================================
    // Person lookups by ID - Person data, read operations
    // ============================================================

    pub async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        match decision {
            RouteDecision::Leader => call_leader!(self, "GetPerson", get_person, request),
            RouteDecision::Replica => {
                call_backend!(self, "GetPerson", get_person, request)
            }
        }
    }

    pub async fn get_persons(&self, request: GetPersonsRequest) -> Result<PersonsResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(self, "GetPersons", get_persons, request)
    }

    pub async fn get_person_by_uuid(
        &self,
        request: GetPersonByUuidRequest,
    ) -> Result<GetPersonResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(self, "GetPersonByUuid", get_person_by_uuid, request)
    }

    pub async fn get_persons_by_uuids(
        &self,
        request: GetPersonsByUuidsRequest,
    ) -> Result<PersonsResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(self, "GetPersonsByUuids", get_persons_by_uuids, request)
    }

    // ============================================================
    // Person lookups by distinct ID - Person data, read operations
    // ============================================================

    pub async fn get_person_by_distinct_id(
        &self,
        request: GetPersonByDistinctIdRequest,
    ) -> Result<GetPersonResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(
            self,
            "GetPersonByDistinctId",
            get_person_by_distinct_id,
            request
        )
    }

    pub async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: GetPersonsByDistinctIdsInTeamRequest,
    ) -> Result<PersonsByDistinctIdsInTeamResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(
            self,
            "GetPersonsByDistinctIdsInTeam",
            get_persons_by_distinct_ids_in_team,
            request
        )
    }

    pub async fn get_persons_by_distinct_ids(
        &self,
        request: GetPersonsByDistinctIdsRequest,
    ) -> Result<PersonsByDistinctIdsResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(
            self,
            "GetPersonsByDistinctIds",
            get_persons_by_distinct_ids,
            request
        )
    }

    // ============================================================
    // Distinct ID operations - Person data, read operations
    // ============================================================

    pub async fn get_distinct_ids_for_person(
        &self,
        request: GetDistinctIdsForPersonRequest,
    ) -> Result<GetDistinctIdsForPersonResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(
            self,
            "GetDistinctIdsForPerson",
            get_distinct_ids_for_person,
            request
        )
    }

    pub async fn get_distinct_ids_for_persons(
        &self,
        request: GetDistinctIdsForPersonsRequest,
    ) -> Result<GetDistinctIdsForPersonsResponse, Status> {
        self.require_replica(DataCategory::PersonData, &request.read_options)?;
        call_backend!(
            self,
            "GetDistinctIdsForPersons",
            get_distinct_ids_for_persons,
            request
        )
    }

    // ============================================================
    // Feature flag hash key overrides - Non-person data
    // ============================================================

    pub async fn get_hash_key_override_context(
        &self,
        request: GetHashKeyOverrideContextRequest,
    ) -> Result<GetHashKeyOverrideContextResponse, Status> {
        call_backend!(
            self,
            "GetHashKeyOverrideContext",
            get_hash_key_override_context,
            request
        )
    }

    pub async fn upsert_hash_key_overrides(
        &self,
        request: UpsertHashKeyOverridesRequest,
    ) -> Result<UpsertHashKeyOverridesResponse, Status> {
        call_backend!(
            self,
            "UpsertHashKeyOverrides",
            upsert_hash_key_overrides,
            request
        )
    }

    pub async fn delete_hash_key_overrides_by_teams(
        &self,
        request: DeleteHashKeyOverridesByTeamsRequest,
    ) -> Result<DeleteHashKeyOverridesByTeamsResponse, Status> {
        call_backend!(
            self,
            "DeleteHashKeyOverridesByTeams",
            delete_hash_key_overrides_by_teams,
            request
        )
    }

    // ============================================================
    // Cohort membership - Non-person data
    // ============================================================

    pub async fn check_cohort_membership(
        &self,
        request: CheckCohortMembershipRequest,
    ) -> Result<CohortMembershipResponse, Status> {
        call_backend!(
            self,
            "CheckCohortMembership",
            check_cohort_membership,
            request
        )
    }

    // ============================================================
    // Groups - Non-person data
    // ============================================================

    pub async fn get_group(&self, request: GetGroupRequest) -> Result<GetGroupResponse, Status> {
        call_backend!(self, "GetGroup", get_group, request)
    }

    pub async fn get_groups(&self, request: GetGroupsRequest) -> Result<GroupsResponse, Status> {
        call_backend!(self, "GetGroups", get_groups, request)
    }

    pub async fn get_groups_batch(
        &self,
        request: GetGroupsBatchRequest,
    ) -> Result<GetGroupsBatchResponse, Status> {
        call_backend!(self, "GetGroupsBatch", get_groups_batch, request)
    }

    // ============================================================
    // Group type mappings - Non-person data
    // ============================================================

    pub async fn get_group_type_mappings_by_team_id(
        &self,
        request: GetGroupTypeMappingsByTeamIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        call_backend!(
            self,
            "GetGroupTypeMappingsByTeamId",
            get_group_type_mappings_by_team_id,
            request
        )
    }

    pub async fn get_group_type_mappings_by_team_ids(
        &self,
        request: GetGroupTypeMappingsByTeamIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        call_backend!(
            self,
            "GetGroupTypeMappingsByTeamIds",
            get_group_type_mappings_by_team_ids,
            request
        )
    }

    pub async fn get_group_type_mappings_by_project_id(
        &self,
        request: GetGroupTypeMappingsByProjectIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        call_backend!(
            self,
            "GetGroupTypeMappingsByProjectId",
            get_group_type_mappings_by_project_id,
            request
        )
    }

    pub async fn get_group_type_mappings_by_project_ids(
        &self,
        request: GetGroupTypeMappingsByProjectIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        call_backend!(
            self,
            "GetGroupTypeMappingsByProjectIds",
            get_group_type_mappings_by_project_ids,
            request
        )
    }

    // ============================================================
    // Person property updates - Person data, write operations
    // ============================================================

    pub async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        call_leader!(
            self,
            "UpdatePersonProperties",
            update_person_properties,
            request
        )
    }
}
