#[cfg(test)]
mod tests;

use std::sync::Arc;

use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogService;
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
use tonic::{Request, Response, Status};

use crate::router::PersonHogRouter;

pub struct PersonHogRouterService {
    router: Arc<PersonHogRouter>,
}

impl PersonHogRouterService {
    pub fn new(router: Arc<PersonHogRouter>) -> Self {
        Self { router }
    }
}

macro_rules! route_request {
    ($self:expr, $method:ident, $request:expr) => {{
        match $self.router.$method($request.into_inner()).await {
            Ok(response) => Ok(Response::new(response)),
            Err(status) => Err(status),
        }
    }};
}

#[tonic::async_trait]
impl PersonHogService for PersonHogRouterService {
    // Person lookups by ID

    async fn get_person(
        &self,
        request: Request<GetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        route_request!(self, get_person, request)
    }

    async fn get_persons(
        &self,
        request: Request<GetPersonsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        route_request!(self, get_persons, request)
    }

    async fn get_person_by_uuid(
        &self,
        request: Request<GetPersonByUuidRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        route_request!(self, get_person_by_uuid, request)
    }

    async fn get_persons_by_uuids(
        &self,
        request: Request<GetPersonsByUuidsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        route_request!(self, get_persons_by_uuids, request)
    }

    // Person lookups by distinct ID

    async fn get_person_by_distinct_id(
        &self,
        request: Request<GetPersonByDistinctIdRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        route_request!(self, get_person_by_distinct_id, request)
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: Request<GetPersonsByDistinctIdsInTeamRequest>,
    ) -> Result<Response<PersonsByDistinctIdsInTeamResponse>, Status> {
        route_request!(self, get_persons_by_distinct_ids_in_team, request)
    }

    async fn get_persons_by_distinct_ids(
        &self,
        request: Request<GetPersonsByDistinctIdsRequest>,
    ) -> Result<Response<PersonsByDistinctIdsResponse>, Status> {
        route_request!(self, get_persons_by_distinct_ids, request)
    }

    // Distinct ID operations

    async fn get_distinct_ids_for_person(
        &self,
        request: Request<GetDistinctIdsForPersonRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonResponse>, Status> {
        route_request!(self, get_distinct_ids_for_person, request)
    }

    async fn get_distinct_ids_for_persons(
        &self,
        request: Request<GetDistinctIdsForPersonsRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonsResponse>, Status> {
        route_request!(self, get_distinct_ids_for_persons, request)
    }

    // Feature flag hash key override support

    async fn get_hash_key_override_context(
        &self,
        request: Request<GetHashKeyOverrideContextRequest>,
    ) -> Result<Response<GetHashKeyOverrideContextResponse>, Status> {
        route_request!(self, get_hash_key_override_context, request)
    }

    async fn upsert_hash_key_overrides(
        &self,
        request: Request<UpsertHashKeyOverridesRequest>,
    ) -> Result<Response<UpsertHashKeyOverridesResponse>, Status> {
        route_request!(self, upsert_hash_key_overrides, request)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        request: Request<DeleteHashKeyOverridesByTeamsRequest>,
    ) -> Result<Response<DeleteHashKeyOverridesByTeamsResponse>, Status> {
        route_request!(self, delete_hash_key_overrides_by_teams, request)
    }

    // Cohort membership

    async fn check_cohort_membership(
        &self,
        request: Request<CheckCohortMembershipRequest>,
    ) -> Result<Response<CohortMembershipResponse>, Status> {
        route_request!(self, check_cohort_membership, request)
    }

    // Groups

    async fn get_group(
        &self,
        request: Request<GetGroupRequest>,
    ) -> Result<Response<GetGroupResponse>, Status> {
        route_request!(self, get_group, request)
    }

    async fn get_groups(
        &self,
        request: Request<GetGroupsRequest>,
    ) -> Result<Response<GroupsResponse>, Status> {
        route_request!(self, get_groups, request)
    }

    async fn get_groups_batch(
        &self,
        request: Request<GetGroupsBatchRequest>,
    ) -> Result<Response<GetGroupsBatchResponse>, Status> {
        route_request!(self, get_groups_batch, request)
    }

    // Group type mappings

    async fn get_group_type_mappings_by_team_id(
        &self,
        request: Request<GetGroupTypeMappingsByTeamIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        route_request!(self, get_group_type_mappings_by_team_id, request)
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        request: Request<GetGroupTypeMappingsByTeamIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        route_request!(self, get_group_type_mappings_by_team_ids, request)
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        request: Request<GetGroupTypeMappingsByProjectIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        route_request!(self, get_group_type_mappings_by_project_id, request)
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        request: Request<GetGroupTypeMappingsByProjectIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        route_request!(self, get_group_type_mappings_by_project_ids, request)
    }
}
