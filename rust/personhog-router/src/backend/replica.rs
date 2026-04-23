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
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use tonic::codec::CompressionEncoding;
use tonic::transport::{Channel, Endpoint};
use tonic::{Request, Status};
use tracing::info;

use personhog_common::grpc::current_client_name;

use super::retry::with_retry;
use super::PersonHogBackend;
use crate::config::RetryConfig;

/// Backend implementation that forwards requests to a personhog-replica service
/// using multiple gRPC channels with round-robin selection.
///
/// Connection lifecycle is managed server-side via `max_connection_age` on the
/// replica's gRPC server, which sends GOAWAY to trigger transparent client
/// reconnects — no client-side recycling needed.
pub struct ReplicaBackend {
    clients: Vec<PersonHogReplicaClient<Channel>>,
    next_idx: AtomicUsize,
    retry_config: RetryConfig,
}

/// Configuration for creating replica backend channels.
#[derive(Clone)]
pub struct ReplicaBackendConfig {
    pub url: String,
    pub timeout: Duration,
    pub retry_config: RetryConfig,
    pub keepalive_interval: Option<Duration>,
    pub keepalive_timeout: Option<Duration>,
    pub max_send_message_size: usize,
    pub max_recv_message_size: usize,
    pub num_channels: usize,
}

fn build_endpoint(config: &ReplicaBackendConfig) -> Endpoint {
    let mut endpoint = Channel::from_shared(config.url.clone())
        .unwrap_or_else(|e| panic!("invalid replica URL '{}': {e}", config.url))
        .timeout(config.timeout)
        .tcp_nodelay(true);
    if let Some(interval) = config.keepalive_interval {
        endpoint = endpoint
            .http2_keep_alive_interval(interval)
            .keep_alive_while_idle(true);
    }
    if let Some(timeout) = config.keepalive_timeout {
        endpoint = endpoint.keep_alive_timeout(timeout);
    }
    endpoint
}

fn create_clients(config: &ReplicaBackendConfig) -> Vec<PersonHogReplicaClient<Channel>> {
    (0..config.num_channels)
        .map(|_| {
            let channel = build_endpoint(config).connect_lazy();
            PersonHogReplicaClient::new(channel)
                .max_encoding_message_size(config.max_send_message_size)
                .max_decoding_message_size(config.max_recv_message_size)
                .accept_compressed(CompressionEncoding::Zstd)
        })
        .collect()
}

impl ReplicaBackend {
    pub fn new(config: ReplicaBackendConfig) -> Self {
        let retry_config = config.retry_config;
        let num_channels = config.num_channels.max(1);
        let config = ReplicaBackendConfig {
            num_channels,
            ..config
        };

        let clients = create_clients(&config);
        info!(
            num_channels,
            url = config.url,
            "created replica backend channels"
        );

        Self {
            clients,
            next_idx: AtomicUsize::new(0),
            retry_config,
        }
    }

    fn next_client(&self) -> PersonHogReplicaClient<Channel> {
        let idx = self.next_idx.fetch_add(1, Ordering::Relaxed) % self.clients.len();
        self.clients[idx].clone()
    }
}

/// Wraps a gRPC call with retry logic. Clones the request for each attempt.
/// Forwards the `x-client-name` header so the downstream service can
/// attribute metrics to the originating client.
macro_rules! retry_call {
    ($self:expr, $method:ident, $request:expr) => {{
        with_retry(&$self.retry_config, stringify!($method), || {
            let mut client = $self.next_client();
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
    }};
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

#[cfg(test)]
mod tests {
    use super::*;

    fn make_backend(num_channels: usize) -> ReplicaBackend {
        ReplicaBackend::new(ReplicaBackendConfig {
            url: "http://localhost:50051".to_string(),
            timeout: Duration::from_secs(1),
            retry_config: RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
            keepalive_interval: None,
            keepalive_timeout: None,
            max_send_message_size: 4 * 1024 * 1024,
            max_recv_message_size: 4 * 1024 * 1024,
            num_channels,
        })
    }

    #[tokio::test]
    async fn next_client_round_robins_across_channels() {
        let backend = make_backend(4);
        for round in 0..3u64 {
            for ch in 0..4u64 {
                backend.next_client();
                let expected = round * 4 + ch + 1;
                assert_eq!(backend.next_idx.load(Ordering::Relaxed), expected as usize);
            }
        }
    }

    #[tokio::test]
    async fn next_client_wraps_around() {
        let backend = make_backend(3);
        for _ in 0..3 {
            backend.next_client();
        }
        // 4th call uses counter=3, so index = 3 % 3 = 0 (wraps back to first channel)
        let idx_before = backend.next_idx.load(Ordering::Relaxed);
        backend.next_client();
        assert_eq!(idx_before % backend.clients.len(), 0);
    }

    #[tokio::test]
    async fn num_channels_floors_to_one() {
        let backend = make_backend(0);
        assert_eq!(backend.clients.len(), 1);
    }
}
