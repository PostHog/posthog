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

use super::retry::with_retry;
use super::PersonHogBackend;
use crate::config::RetryConfig;

/// Backend implementation that forwards requests to a personhog-replica service.
pub struct ReplicaBackend {
    client: PersonHogReplicaClient<Channel>,
    retry_config: RetryConfig,
}

impl ReplicaBackend {
    /// Create a new replica backend with a lazy connection to the given URL.
    pub fn new(
        url: &str,
        timeout: Duration,
        retry_config: RetryConfig,
    ) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let channel = Channel::from_shared(url.to_string())?
            .timeout(timeout)
            .connect_lazy();

        Ok(Self {
            client: PersonHogReplicaClient::new(channel),
            retry_config,
        })
    }
}

/// Wraps a gRPC call with retry logic. Clones the request for each attempt.
macro_rules! retry_call {
    ($self:expr, $method:ident, $request:expr) => {
        with_retry(&$self.retry_config, stringify!($method), || {
            let mut client = $self.client.clone();
            let req = $request.clone();
            async move {
                client
                    .$method(Request::new(req))
                    .await
                    .map(|r| r.into_inner())
            }
        })
        .await
    };
}

#[async_trait]
impl PersonHogBackend for ReplicaBackend {
    // Person lookups by ID

    async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status> {
        retry_call!(self, get_person, request)
    }

    async fn get_persons(&self, request: GetPersonsRequest) -> Result<PersonsResponse, Status> {
        retry_call!(self, get_persons, request)
    }

    async fn get_person_by_uuid(
        &self,
        request: GetPersonByUuidRequest,
    ) -> Result<GetPersonResponse, Status> {
        retry_call!(self, get_person_by_uuid, request)
    }

    async fn get_persons_by_uuids(
        &self,
        request: GetPersonsByUuidsRequest,
    ) -> Result<PersonsResponse, Status> {
        retry_call!(self, get_persons_by_uuids, request)
    }

    // Person lookups by distinct ID

    async fn get_person_by_distinct_id(
        &self,
        request: GetPersonByDistinctIdRequest,
    ) -> Result<GetPersonResponse, Status> {
        retry_call!(self, get_person_by_distinct_id, request)
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: GetPersonsByDistinctIdsInTeamRequest,
    ) -> Result<PersonsByDistinctIdsInTeamResponse, Status> {
        retry_call!(self, get_persons_by_distinct_ids_in_team, request)
    }

    async fn get_persons_by_distinct_ids(
        &self,
        request: GetPersonsByDistinctIdsRequest,
    ) -> Result<PersonsByDistinctIdsResponse, Status> {
        retry_call!(self, get_persons_by_distinct_ids, request)
    }

    // Distinct ID operations

    async fn get_distinct_ids_for_person(
        &self,
        request: GetDistinctIdsForPersonRequest,
    ) -> Result<GetDistinctIdsForPersonResponse, Status> {
        retry_call!(self, get_distinct_ids_for_person, request)
    }

    async fn get_distinct_ids_for_persons(
        &self,
        request: GetDistinctIdsForPersonsRequest,
    ) -> Result<GetDistinctIdsForPersonsResponse, Status> {
        retry_call!(self, get_distinct_ids_for_persons, request)
    }

    // Feature flag hash key override support

    async fn get_hash_key_override_context(
        &self,
        request: GetHashKeyOverrideContextRequest,
    ) -> Result<GetHashKeyOverrideContextResponse, Status> {
        retry_call!(self, get_hash_key_override_context, request)
    }

    async fn upsert_hash_key_overrides(
        &self,
        request: UpsertHashKeyOverridesRequest,
    ) -> Result<UpsertHashKeyOverridesResponse, Status> {
        retry_call!(self, upsert_hash_key_overrides, request)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        request: DeleteHashKeyOverridesByTeamsRequest,
    ) -> Result<DeleteHashKeyOverridesByTeamsResponse, Status> {
        retry_call!(self, delete_hash_key_overrides_by_teams, request)
    }

    // Cohort membership

    async fn check_cohort_membership(
        &self,
        request: CheckCohortMembershipRequest,
    ) -> Result<CohortMembershipResponse, Status> {
        retry_call!(self, check_cohort_membership, request)
    }

    // Groups

    async fn get_group(&self, request: GetGroupRequest) -> Result<GetGroupResponse, Status> {
        retry_call!(self, get_group, request)
    }

    async fn get_groups(&self, request: GetGroupsRequest) -> Result<GroupsResponse, Status> {
        retry_call!(self, get_groups, request)
    }

    async fn get_groups_batch(
        &self,
        request: GetGroupsBatchRequest,
    ) -> Result<GetGroupsBatchResponse, Status> {
        retry_call!(self, get_groups_batch, request)
    }

    // Group type mappings

    async fn get_group_type_mappings_by_team_id(
        &self,
        request: GetGroupTypeMappingsByTeamIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        retry_call!(self, get_group_type_mappings_by_team_id, request)
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        request: GetGroupTypeMappingsByTeamIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        retry_call!(self, get_group_type_mappings_by_team_ids, request)
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        request: GetGroupTypeMappingsByProjectIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        retry_call!(self, get_group_type_mappings_by_project_id, request)
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        request: GetGroupTypeMappingsByProjectIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        retry_call!(self, get_group_type_mappings_by_project_ids, request)
    }
}
