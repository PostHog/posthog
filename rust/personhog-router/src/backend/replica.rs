use async_trait::async_trait;
use personhog_proto::personhog::replica::v1::person_hog_replica_client::PersonHogReplicaClient;
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
    PersonsResponse, UpsertHashKeyOverridesRequest, UpsertHashKeyOverridesResponse,
};
use std::time::Duration;
use tonic::transport::Channel;
use tonic::{Request, Status};

use personhog_common::grpc::current_client_name;

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
        keepalive_interval: Option<Duration>,
        keepalive_timeout: Option<Duration>,
        max_send_message_size: usize,
        max_recv_message_size: usize,
    ) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let mut endpoint = Channel::from_shared(url.to_string())?
            .timeout(timeout)
            .tcp_nodelay(true);
        if let Some(interval) = keepalive_interval {
            endpoint = endpoint
                .http2_keep_alive_interval(interval)
                .keep_alive_while_idle(true);
        }
        if let Some(timeout) = keepalive_timeout {
            endpoint = endpoint.keep_alive_timeout(timeout);
        }
        let channel = endpoint.connect_lazy();

        Ok(Self {
            client: PersonHogReplicaClient::new(channel)
                .max_encoding_message_size(max_send_message_size)
                .max_decoding_message_size(max_recv_message_size),
            retry_config,
        })
    }
}

/// Wraps a gRPC call with retry logic. Clones the request for each attempt.
/// Forwards the `x-client-name` header so the downstream service can
/// attribute metrics to the originating client.
macro_rules! retry_call {
    ($self:expr, $method:ident, $request:expr) => {
        with_retry(&$self.retry_config, stringify!($method), || {
            let mut client = $self.client.clone();
            let req = $request.clone();
            let client_name = current_client_name();
            async move {
                let mut request = Request::new(req);
                if let Ok(val) = client_name.parse() {
                    request.metadata_mut().insert("x-client-name", val);
                }
                client.$method(request).await.map(|r| r.into_inner())
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

    // Person deletes

    async fn delete_persons(
        &self,
        request: DeletePersonsRequest,
    ) -> Result<DeletePersonsResponse, Status> {
        retry_call!(self, delete_persons, request)
    }

    async fn delete_persons_batch_for_team(
        &self,
        request: DeletePersonsBatchForTeamRequest,
    ) -> Result<DeletePersonsBatchForTeamResponse, Status> {
        retry_call!(self, delete_persons_batch_for_team, request)
    }

    // Cohort membership

    async fn check_cohort_membership(
        &self,
        request: CheckCohortMembershipRequest,
    ) -> Result<CohortMembershipResponse, Status> {
        retry_call!(self, check_cohort_membership, request)
    }

    async fn count_cohort_members(
        &self,
        request: CountCohortMembersRequest,
    ) -> Result<CountCohortMembersResponse, Status> {
        retry_call!(self, count_cohort_members, request)
    }

    async fn delete_cohort_member(
        &self,
        request: DeleteCohortMemberRequest,
    ) -> Result<DeleteCohortMemberResponse, Status> {
        retry_call!(self, delete_cohort_member, request)
    }

    async fn delete_cohort_members_bulk(
        &self,
        request: DeleteCohortMembersBulkRequest,
    ) -> Result<DeleteCohortMembersBulkResponse, Status> {
        retry_call!(self, delete_cohort_members_bulk, request)
    }

    async fn insert_cohort_members(
        &self,
        request: InsertCohortMembersRequest,
    ) -> Result<InsertCohortMembersResponse, Status> {
        retry_call!(self, insert_cohort_members, request)
    }

    async fn list_cohort_member_ids(
        &self,
        request: ListCohortMemberIdsRequest,
    ) -> Result<ListCohortMemberIdsResponse, Status> {
        retry_call!(self, list_cohort_member_ids, request)
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
