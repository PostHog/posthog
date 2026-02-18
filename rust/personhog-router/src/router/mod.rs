mod routing;

pub use routing::{DataCategory, OperationType, RouteDecision, RoutingError};

use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
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

use crate::backend::PersonHogBackend;
use routing::{get_consistency, route_request};

/// Macro to call a backend method with timing instrumentation.
///
/// Records metrics:
/// - `personhog_router_backend_requests_total` - counter by method and backend
/// - `personhog_router_backend_duration_ms` - histogram by method and backend
/// - `personhog_router_backend_errors_total` - counter on errors
macro_rules! call_backend {
    ($self:expr, $decision:expr, $method_name:expr, $method:ident, $request:expr) => {{
        let backend = $self.get_backend($decision)?;
        let backend_name = match $decision {
            RouteDecision::Replica => "replica",
            RouteDecision::Leader => "leader",
        };

        counter!(
            "personhog_router_backend_requests_total",
            "method" => $method_name,
            "backend" => backend_name
        )
        .increment(1);

        let start = Instant::now();
        let result = backend.$method($request).await;
        let duration_ms = start.elapsed().as_secs_f64() * 1000.0;

        histogram!(
            "personhog_router_backend_duration_ms",
            "method" => $method_name,
            "backend" => backend_name
        )
        .record(duration_ms);

        if result.is_err() {
            counter!(
                "personhog_router_backend_errors_total",
                "method" => $method_name,
                "backend" => backend_name
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
    // Phase 2: Add leader_backend for person data writes and strong consistency reads
    // leader_backend: Option<Arc<dyn PersonHogBackend>>,
}

impl PersonHogRouter {
    pub fn new(replica_backend: Arc<dyn PersonHogBackend>) -> Self {
        Self { replica_backend }
    }

    /// Get the appropriate backend for a request based on routing decision.
    #[allow(clippy::result_large_err)] // tonic::Status is large but we can't change it
    fn get_backend(&self, decision: RouteDecision) -> Result<&dyn PersonHogBackend, Status> {
        match decision {
            RouteDecision::Replica => Ok(self.replica_backend.as_ref()),
            RouteDecision::Leader => {
                // Phase 2: Return leader backend when available
                Err(Status::unimplemented(
                    "Strong consistency for person data requires personhog-leader (not yet implemented)",
                ))
            }
        }
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
        call_backend!(self, decision, "GetPerson", get_person, request)
    }

    pub async fn get_persons(&self, request: GetPersonsRequest) -> Result<PersonsResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(self, decision, "GetPersons", get_persons, request)
    }

    pub async fn get_person_by_uuid(
        &self,
        request: GetPersonByUuidRequest,
    ) -> Result<GetPersonResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetPersonByUuid",
            get_person_by_uuid,
            request
        )
    }

    pub async fn get_persons_by_uuids(
        &self,
        request: GetPersonsByUuidsRequest,
    ) -> Result<PersonsResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetPersonsByUuids",
            get_persons_by_uuids,
            request
        )
    }

    // ============================================================
    // Person lookups by distinct ID - Person data, read operations
    // ============================================================

    pub async fn get_person_by_distinct_id(
        &self,
        request: GetPersonByDistinctIdRequest,
    ) -> Result<GetPersonResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetPersonByDistinctId",
            get_person_by_distinct_id,
            request
        )
    }

    pub async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: GetPersonsByDistinctIdsInTeamRequest,
    ) -> Result<PersonsByDistinctIdsInTeamResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetPersonsByDistinctIdsInTeam",
            get_persons_by_distinct_ids_in_team,
            request
        )
    }

    pub async fn get_persons_by_distinct_ids(
        &self,
        request: GetPersonsByDistinctIdsRequest,
    ) -> Result<PersonsByDistinctIdsResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
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
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetDistinctIdsForPerson",
            get_distinct_ids_for_person,
            request
        )
    }

    pub async fn get_distinct_ids_for_persons(
        &self,
        request: GetDistinctIdsForPersonsRequest,
    ) -> Result<GetDistinctIdsForPersonsResponse, Status> {
        let decision = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
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
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetHashKeyOverrideContext",
            get_hash_key_override_context,
            request
        )
    }

    pub async fn upsert_hash_key_overrides(
        &self,
        request: UpsertHashKeyOverridesRequest,
    ) -> Result<UpsertHashKeyOverridesResponse, Status> {
        let decision = route_request(DataCategory::NonPersonData, OperationType::Write, None)?;
        call_backend!(
            self,
            decision,
            "UpsertHashKeyOverrides",
            upsert_hash_key_overrides,
            request
        )
    }

    pub async fn delete_hash_key_overrides_by_teams(
        &self,
        request: DeleteHashKeyOverridesByTeamsRequest,
    ) -> Result<DeleteHashKeyOverridesByTeamsResponse, Status> {
        let decision = route_request(DataCategory::NonPersonData, OperationType::Write, None)?;
        call_backend!(
            self,
            decision,
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
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "CheckCohortMembership",
            check_cohort_membership,
            request
        )
    }

    // ============================================================
    // Groups - Non-person data
    // ============================================================

    pub async fn get_group(&self, request: GetGroupRequest) -> Result<GetGroupResponse, Status> {
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(self, decision, "GetGroup", get_group, request)
    }

    pub async fn get_groups(&self, request: GetGroupsRequest) -> Result<GroupsResponse, Status> {
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(self, decision, "GetGroups", get_groups, request)
    }

    pub async fn get_groups_batch(
        &self,
        request: GetGroupsBatchRequest,
    ) -> Result<GetGroupsBatchResponse, Status> {
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(self, decision, "GetGroupsBatch", get_groups_batch, request)
    }

    // ============================================================
    // Group type mappings - Non-person data
    // ============================================================

    pub async fn get_group_type_mappings_by_team_id(
        &self,
        request: GetGroupTypeMappingsByTeamIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetGroupTypeMappingsByTeamId",
            get_group_type_mappings_by_team_id,
            request
        )
    }

    pub async fn get_group_type_mappings_by_team_ids(
        &self,
        request: GetGroupTypeMappingsByTeamIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetGroupTypeMappingsByTeamIds",
            get_group_type_mappings_by_team_ids,
            request
        )
    }

    pub async fn get_group_type_mappings_by_project_id(
        &self,
        request: GetGroupTypeMappingsByProjectIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetGroupTypeMappingsByProjectId",
            get_group_type_mappings_by_project_id,
            request
        )
    }

    pub async fn get_group_type_mappings_by_project_ids(
        &self,
        request: GetGroupTypeMappingsByProjectIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        let decision = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            get_consistency(&request.read_options),
        )?;
        call_backend!(
            self,
            decision,
            "GetGroupTypeMappingsByProjectIds",
            get_group_type_mappings_by_project_ids,
            request
        )
    }
}
