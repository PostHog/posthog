use async_trait::async_trait;
use personhog_proto::personhog::replica::v1::person_hog_replica_client::PersonHogReplicaClient;
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
use std::time::Duration;
use tonic::transport::Channel;
use tonic::{Request, Status};

use super::PersonHogBackend;

/// Backend implementation that forwards requests to a personhog-replica service.
pub struct ReplicaBackend {
    client: PersonHogReplicaClient<Channel>,
}

impl ReplicaBackend {
    /// Create a new replica backend with a lazy connection to the given URL.
    pub fn new(
        url: &str,
        timeout: Duration,
    ) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let channel = Channel::from_shared(url.to_string())?
            .timeout(timeout)
            .connect_lazy();

        Ok(Self {
            client: PersonHogReplicaClient::new(channel),
        })
    }
}

#[async_trait]
impl PersonHogBackend for ReplicaBackend {
    // Person lookups by ID

    async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status> {
        self.client
            .clone()
            .get_person(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_persons(&self, request: GetPersonsRequest) -> Result<PersonsResponse, Status> {
        self.client
            .clone()
            .get_persons(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_person_by_uuid(
        &self,
        request: GetPersonByUuidRequest,
    ) -> Result<GetPersonResponse, Status> {
        self.client
            .clone()
            .get_person_by_uuid(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_persons_by_uuids(
        &self,
        request: GetPersonsByUuidsRequest,
    ) -> Result<PersonsResponse, Status> {
        self.client
            .clone()
            .get_persons_by_uuids(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    // Person lookups by distinct ID

    async fn get_person_by_distinct_id(
        &self,
        request: GetPersonByDistinctIdRequest,
    ) -> Result<GetPersonResponse, Status> {
        self.client
            .clone()
            .get_person_by_distinct_id(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: GetPersonsByDistinctIdsInTeamRequest,
    ) -> Result<PersonsByDistinctIdsInTeamResponse, Status> {
        self.client
            .clone()
            .get_persons_by_distinct_ids_in_team(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_persons_by_distinct_ids(
        &self,
        request: GetPersonsByDistinctIdsRequest,
    ) -> Result<PersonsByDistinctIdsResponse, Status> {
        self.client
            .clone()
            .get_persons_by_distinct_ids(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    // Distinct ID operations

    async fn get_distinct_ids_for_person(
        &self,
        request: GetDistinctIdsForPersonRequest,
    ) -> Result<GetDistinctIdsForPersonResponse, Status> {
        self.client
            .clone()
            .get_distinct_ids_for_person(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        request: GetDistinctIdsForPersonsRequest,
    ) -> Result<GetDistinctIdsForPersonsResponse, Status> {
        self.client
            .clone()
            .get_distinct_ids_for_persons(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    // Feature flag hash key override support

    async fn get_hash_key_override_context(
        &self,
        request: GetHashKeyOverrideContextRequest,
    ) -> Result<GetHashKeyOverrideContextResponse, Status> {
        self.client
            .clone()
            .get_hash_key_override_context(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn upsert_hash_key_overrides(
        &self,
        request: UpsertHashKeyOverridesRequest,
    ) -> Result<UpsertHashKeyOverridesResponse, Status> {
        self.client
            .clone()
            .upsert_hash_key_overrides(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        request: DeleteHashKeyOverridesByTeamsRequest,
    ) -> Result<DeleteHashKeyOverridesByTeamsResponse, Status> {
        self.client
            .clone()
            .delete_hash_key_overrides_by_teams(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    // Cohort membership

    async fn check_cohort_membership(
        &self,
        request: CheckCohortMembershipRequest,
    ) -> Result<CohortMembershipResponse, Status> {
        self.client
            .clone()
            .check_cohort_membership(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    // Groups

    async fn get_group(&self, request: GetGroupRequest) -> Result<GetGroupResponse, Status> {
        self.client
            .clone()
            .get_group(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_groups(&self, request: GetGroupsRequest) -> Result<GroupsResponse, Status> {
        self.client
            .clone()
            .get_groups(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_groups_batch(
        &self,
        request: GetGroupsBatchRequest,
    ) -> Result<GetGroupsBatchResponse, Status> {
        self.client
            .clone()
            .get_groups_batch(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    // Group type mappings

    async fn get_group_type_mappings_by_team_id(
        &self,
        request: GetGroupTypeMappingsByTeamIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        self.client
            .clone()
            .get_group_type_mappings_by_team_id(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        request: GetGroupTypeMappingsByTeamIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        self.client
            .clone()
            .get_group_type_mappings_by_team_ids(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        request: GetGroupTypeMappingsByProjectIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        self.client
            .clone()
            .get_group_type_mappings_by_project_id(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        request: GetGroupTypeMappingsByProjectIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        self.client
            .clone()
            .get_group_type_mappings_by_project_ids(Request::new(request))
            .await
            .map(|r| r.into_inner())
    }
}
