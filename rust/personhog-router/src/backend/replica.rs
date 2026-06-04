use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use personhog_proto::personhog::replica::v1::person_hog_replica_client::PersonHogReplicaClient;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembershipResponse, CountCohortMembersRequest,
    CountCohortMembersResponse, CountGroupTypeMappingsRequest, CountGroupTypeMappingsResponse,
    CreateGroupRequest, CreateGroupResponse, DeleteCohortMemberRequest, DeleteCohortMemberResponse,
    DeleteCohortMembersBulkRequest, DeleteCohortMembersBulkResponse, DeleteGroupTypeMappingRequest,
    DeleteGroupTypeMappingResponse, DeleteGroupTypeMappingsBatchForTeamRequest,
    DeleteGroupTypeMappingsBatchForTeamResponse, DeleteGroupsBatchForTeamRequest,
    DeleteGroupsBatchForTeamResponse, DeleteHashKeyOverridesByTeamsRequest,
    DeleteHashKeyOverridesByTeamsResponse, DeletePersonsBatchForTeamRequest,
    DeletePersonsBatchForTeamResponse, DeletePersonsRequest, DeletePersonsResponse,
    GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest, GetDistinctIdsForPersonsResponse, GetGroupRequest,
    GetGroupResponse, GetGroupTypeMappingByDashboardIdRequest,
    GetGroupTypeMappingByDashboardIdResponse, GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest, GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest, GetGroupsBatchRequest, GetGroupsBatchResponse,
    GetGroupsRequest, GetHashKeyOverrideContextRequest, GetHashKeyOverrideContextResponse,
    GetPersonByDistinctIdRequest, GetPersonByUuidRequest, GetPersonRequest, GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest, GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest,
    GetPersonsRequest, GroupTypeMappingsBatchResponse, GroupTypeMappingsResponse, GroupsResponse,
    InsertCohortMembersRequest, InsertCohortMembersResponse, ListCohortMemberIdsRequest,
    ListCohortMemberIdsResponse, ListGroupsRequest, ListGroupsResponse,
    PersonsByDistinctIdsInTeamResponse, PersonsByDistinctIdsResponse, PersonsResponse,
    UpdateGroupRequest, UpdateGroupResponse, UpdateGroupTypeMappingRequest,
    UpdateGroupTypeMappingResponse, UpsertHashKeyOverridesRequest, UpsertHashKeyOverridesResponse,
};
use std::time::Duration;
use tonic::codec::CompressionEncoding;
use tonic::transport::{Channel, Endpoint};
use tonic::{Request, Status};
use tracing::info;

use personhog_common::grpc::{current_caller_tag, current_client_name};

use super::retry::with_retry;
use super::PersonHogBackend;
use crate::config::RetryConfig;

pub struct ReplicaBackend {
    clients: Vec<PersonHogReplicaClient<Channel>>,
    channels: Vec<Channel>,
    next_idx: AtomicUsize,
    retry_config: RetryConfig,
}

#[derive(Clone)]
pub struct ReplicaDnsConfig {
    pub url: String,
    pub timeout: Duration,
    pub retry_config: RetryConfig,
    pub keepalive_interval: Option<Duration>,
    pub keepalive_timeout: Option<Duration>,
    pub max_send_message_size: usize,
    pub max_recv_message_size: usize,
    pub num_channels: usize,
}

fn build_dns_endpoint(config: &ReplicaDnsConfig) -> Endpoint {
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

fn wrap_client(
    channel: &Channel,
    max_send_message_size: usize,
    max_recv_message_size: usize,
) -> PersonHogReplicaClient<Channel> {
    PersonHogReplicaClient::new(channel.clone())
        .max_encoding_message_size(max_send_message_size)
        .max_decoding_message_size(max_recv_message_size)
        .send_compressed(CompressionEncoding::Zstd)
        .accept_compressed(CompressionEncoding::Zstd)
}

impl ReplicaBackend {
    /// DNS discovery: opens multiple lazy channels to the ClusterIP service URL
    /// with round-robin selection across them.
    pub fn new_dns(config: ReplicaDnsConfig) -> Self {
        let num = config.num_channels.max(1);
        let channels: Vec<Channel> = (0..num)
            .map(|_| build_dns_endpoint(&config).connect_lazy())
            .collect();
        let clients: Vec<_> = channels
            .iter()
            .map(|ch| {
                wrap_client(
                    ch,
                    config.max_send_message_size,
                    config.max_recv_message_size,
                )
            })
            .collect();

        info!(
            url = config.url,
            num_channels = num,
            mode = "dns",
            "created replica backend"
        );

        Self {
            clients,
            channels,
            next_idx: AtomicUsize::new(0),
            retry_config: config.retry_config,
        }
    }

    /// K8s discovery: single balanced channel fed by an EndpointDiscovery task
    /// that watches EndpointSlices. Tower's p2c balancer handles per-request
    /// load distribution, so a single channel is sufficient.
    pub fn new_k8s(
        channel: Channel,
        retry_config: RetryConfig,
        max_send_message_size: usize,
        max_recv_message_size: usize,
    ) -> Self {
        let client = wrap_client(&channel, max_send_message_size, max_recv_message_size);

        info!(mode = "k8s", "created replica backend");

        Self {
            clients: vec![client],
            channels: vec![channel],
            next_idx: AtomicUsize::new(0),
            retry_config,
        }
    }

    fn client(&self) -> PersonHogReplicaClient<Channel> {
        let idx = self.next_idx.fetch_add(1, Ordering::Relaxed) % self.clients.len();
        self.clients[idx].clone()
    }

    pub fn channel(&self) -> Channel {
        let idx = self.next_idx.fetch_add(1, Ordering::Relaxed) % self.channels.len();
        self.channels[idx].clone()
    }

    pub fn retry_config(&self) -> &RetryConfig {
        &self.retry_config
    }
}

macro_rules! retry_call {
    ($self:expr, $method:ident, $request:expr) => {{
        with_retry(&$self.retry_config, stringify!($method), || {
            let mut client = $self.client();
            let req = $request.clone();
            let client_name = current_client_name();
            let caller_tag = current_caller_tag();
            async move {
                let mut request = Request::new(req);
                if let Ok(val) = client_name.parse() {
                    request.metadata_mut().insert("x-client-name", val);
                }
                if let Ok(val) = caller_tag.parse() {
                    request.metadata_mut().insert("x-caller-tag", val);
                }
                client.$method(request).await.map(|r| r.into_inner())
            }
        })
        .await
    }};
}

/// RPCs that bypass the replica channel pools entirely (routed to leader via
/// typed proxy in proxy.rs). Excluded from the retry_call! coverage check.
#[cfg(test)]
const LEADER_ONLY_METHODS: &[&str] = &["UpdatePersonProperties"];

#[async_trait]
impl PersonHogBackend for ReplicaBackend {
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

    async fn list_groups(&self, request: ListGroupsRequest) -> Result<ListGroupsResponse, Status> {
        retry_call!(self, list_groups, request)
    }

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

    async fn count_group_type_mappings(
        &self,
        request: CountGroupTypeMappingsRequest,
    ) -> Result<CountGroupTypeMappingsResponse, Status> {
        retry_call!(self, count_group_type_mappings, request)
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        request: GetGroupTypeMappingByDashboardIdRequest,
    ) -> Result<GetGroupTypeMappingByDashboardIdResponse, Status> {
        retry_call!(self, get_group_type_mapping_by_dashboard_id, request)
    }

    async fn create_group(
        &self,
        request: CreateGroupRequest,
    ) -> Result<CreateGroupResponse, Status> {
        retry_call!(self, create_group, request)
    }

    async fn update_group(
        &self,
        request: UpdateGroupRequest,
    ) -> Result<UpdateGroupResponse, Status> {
        retry_call!(self, update_group, request)
    }

    async fn delete_groups_batch_for_team(
        &self,
        request: DeleteGroupsBatchForTeamRequest,
    ) -> Result<DeleteGroupsBatchForTeamResponse, Status> {
        retry_call!(self, delete_groups_batch_for_team, request)
    }

    async fn update_group_type_mapping(
        &self,
        request: UpdateGroupTypeMappingRequest,
    ) -> Result<UpdateGroupTypeMappingResponse, Status> {
        retry_call!(self, update_group_type_mapping, request)
    }

    async fn delete_group_type_mapping(
        &self,
        request: DeleteGroupTypeMappingRequest,
    ) -> Result<DeleteGroupTypeMappingResponse, Status> {
        retry_call!(self, delete_group_type_mapping, request)
    }

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        request: DeleteGroupTypeMappingsBatchForTeamRequest,
    ) -> Result<DeleteGroupTypeMappingsBatchForTeamResponse, Status> {
        retry_call!(self, delete_group_type_mappings_batch_for_team, request)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::proxy::KNOWN_METHODS;

    fn make_backend() -> ReplicaBackend {
        ReplicaBackend::new_dns(ReplicaDnsConfig {
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
            num_channels: 4,
        })
    }

    #[tokio::test]
    async fn channel_is_cloneable() {
        let backend = make_backend();
        let _ch1 = backend.channel();
        let _ch2 = backend.channel();
    }

    fn snake_to_pascal(s: &str) -> String {
        s.split('_')
            .map(|part| {
                let mut chars = part.chars();
                match chars.next() {
                    Some(c) => c.to_uppercase().to_string() + chars.as_str(),
                    None => String::new(),
                }
            })
            .collect()
    }

    #[test]
    fn retry_call_annotations_cover_all_known_methods() {
        let source = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/src/backend/replica.rs"
        ))
        .expect("failed to read replica.rs");

        let mut typed_methods: Vec<String> = Vec::new();

        let mut in_macro = false;
        let mut macro_buf = String::new();

        for line in source.lines() {
            let trimmed = line.trim();
            if !in_macro {
                if let Some(rest) = trimmed.strip_prefix("retry_call!(") {
                    if rest.ends_with(')') {
                        macro_buf = rest.trim_end_matches(')').to_string();
                    } else {
                        macro_buf = rest.to_string();
                        in_macro = true;
                        continue;
                    }
                } else {
                    continue;
                }
            } else if trimmed == ")" {
                in_macro = false;
            } else {
                macro_buf.push(' ');
                macro_buf.push_str(trimmed);
                continue;
            }

            let args: Vec<&str> = macro_buf.split(',').collect();
            if args.len() >= 2 {
                let method_snake = args[1].trim();
                typed_methods.push(snake_to_pascal(method_snake));
            }
            macro_buf.clear();
        }

        typed_methods.sort();

        assert!(
            !typed_methods.is_empty(),
            "parser found no retry_call! invocations — source formatting may have changed"
        );

        let mut all_known: Vec<&str> = KNOWN_METHODS.to_vec();
        all_known.retain(|m| !LEADER_ONLY_METHODS.contains(m));
        all_known.sort();

        assert_eq!(
            typed_methods, all_known,
            "retry_call! annotations don't cover all known methods (minus leader-only ones)"
        );
    }
}
