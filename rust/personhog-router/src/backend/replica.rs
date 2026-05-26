use async_trait::async_trait;
use personhog_proto::personhog::replica::v1::person_hog_replica_client::PersonHogReplicaClient;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembershipResponse, CountCohortMembersRequest,
    CountCohortMembersResponse, CreateGroupRequest, CreateGroupResponse, DeleteCohortMemberRequest,
    DeleteCohortMemberResponse, DeleteCohortMembersBulkRequest, DeleteCohortMembersBulkResponse,
    DeleteGroupTypeMappingRequest, DeleteGroupTypeMappingResponse,
    DeleteGroupTypeMappingsBatchForTeamRequest, DeleteGroupTypeMappingsBatchForTeamResponse,
    DeleteGroupsBatchForTeamRequest, DeleteGroupsBatchForTeamResponse,
    DeleteHashKeyOverridesByTeamsRequest, DeleteHashKeyOverridesByTeamsResponse,
    DeletePersonsBatchForTeamRequest, DeletePersonsBatchForTeamResponse, DeletePersonsRequest,
    DeletePersonsResponse, GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonResponse,
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
/// using separate heavy/light gRPC channel pools with round-robin selection.
///
/// Heavy channels carry RPCs that return Person/Group objects with large JSON
/// property blobs. Light channels carry everything else (group type mappings,
/// cohort checks, scalar responses). This isolation prevents TCP head-of-line
/// blocking from large responses stalling small ones on shared HTTP/2 connections.
///
/// Connection lifecycle is managed server-side via `max_connection_age` on the
/// replica's gRPC server, which sends GOAWAY to trigger transparent client
/// reconnects — no client-side recycling needed.
pub struct ReplicaBackend {
    heavy_clients: Vec<PersonHogReplicaClient<Channel>>,
    heavy_raw_channels: Vec<Channel>,
    heavy_next_idx: AtomicUsize,
    light_clients: Vec<PersonHogReplicaClient<Channel>>,
    light_raw_channels: Vec<Channel>,
    light_next_idx: AtomicUsize,
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
    pub num_light_channels: usize,
}

/// RPCs whose responses contain only small/scalar data (no Person/Group objects
/// with JSON property blobs). These are routed to dedicated light channels to
/// isolate them from TCP head-of-line blocking caused by large responses.
///
/// Must be sorted — used with binary_search.
const LIGHT_METHODS: &[&str] = &[
    "CheckCohortMembership",
    "CountCohortMembers",
    "DeleteCohortMember",
    "DeleteCohortMembersBulk",
    "DeleteGroupTypeMapping",
    "DeleteGroupTypeMappingsBatchForTeam",
    "DeleteGroupsBatchForTeam",
    "DeleteHashKeyOverridesByTeams",
    "DeletePersons",
    "DeletePersonsBatchForTeam",
    "GetDistinctIdsForPerson",
    "GetGroupTypeMappingByDashboardId",
    "GetGroupTypeMappingsByProjectId",
    "GetGroupTypeMappingsByProjectIds",
    "GetGroupTypeMappingsByTeamId",
    "GetGroupTypeMappingsByTeamIds",
    "GetHashKeyOverrideContext",
    "InsertCohortMembers",
    "UpdateGroupTypeMapping",
    "UpsertHashKeyOverrides",
];

pub fn is_light_method(method: &str) -> bool {
    LIGHT_METHODS.binary_search(&method).is_ok()
}

/// RPCs that bypass the replica channel pools entirely (routed to leader via
/// typed proxy in proxy.rs). Excluded from the retry_call! coverage check.
#[cfg(test)]
const LEADER_ONLY_METHODS: &[&str] = &["UpdatePersonProperties"];

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

fn create_channels(config: &ReplicaBackendConfig) -> Vec<Channel> {
    (0..config.num_channels)
        .map(|_| build_endpoint(config).connect_lazy())
        .collect()
}

fn wrap_clients(
    channels: &[Channel],
    config: &ReplicaBackendConfig,
) -> Vec<PersonHogReplicaClient<Channel>> {
    channels
        .iter()
        .map(|channel| {
            PersonHogReplicaClient::new(channel.clone())
                .max_encoding_message_size(config.max_send_message_size)
                .max_decoding_message_size(config.max_recv_message_size)
                .send_compressed(CompressionEncoding::Zstd)
                .accept_compressed(CompressionEncoding::Zstd)
        })
        .collect()
}

impl ReplicaBackend {
    pub fn new(config: ReplicaBackendConfig) -> Self {
        let retry_config = config.retry_config;
        let num_heavy = config.num_channels.max(1);
        let num_light = config.num_light_channels.max(1);

        let heavy_config = ReplicaBackendConfig {
            num_channels: num_heavy,
            ..config.clone()
        };
        let light_config = ReplicaBackendConfig {
            num_channels: num_light,
            ..config
        };

        let heavy_raw_channels = create_channels(&heavy_config);
        let heavy_clients = wrap_clients(&heavy_raw_channels, &heavy_config);

        let light_raw_channels = create_channels(&light_config);
        let light_clients = wrap_clients(&light_raw_channels, &light_config);

        info!(
            num_heavy,
            num_light,
            url = heavy_config.url,
            "created replica backend channels"
        );

        Self {
            heavy_clients,
            heavy_raw_channels,
            heavy_next_idx: AtomicUsize::new(0),
            light_clients,
            light_raw_channels,
            light_next_idx: AtomicUsize::new(0),
            retry_config,
        }
    }

    fn next_heavy_client(&self) -> PersonHogReplicaClient<Channel> {
        let idx = self.heavy_next_idx.fetch_add(1, Ordering::Relaxed) % self.heavy_clients.len();
        self.heavy_clients[idx].clone()
    }

    fn next_light_client(&self) -> PersonHogReplicaClient<Channel> {
        let idx = self.light_next_idx.fetch_add(1, Ordering::Relaxed) % self.light_clients.len();
        self.light_clients[idx].clone()
    }

    /// Get the next raw channel for byte-level proxying, routed by method weight.
    pub fn next_raw_channel_for(&self, method: &str) -> Channel {
        if is_light_method(method) {
            let idx =
                self.light_next_idx.fetch_add(1, Ordering::Relaxed) % self.light_raw_channels.len();
            self.light_raw_channels[idx].clone()
        } else {
            let idx =
                self.heavy_next_idx.fetch_add(1, Ordering::Relaxed) % self.heavy_raw_channels.len();
            self.heavy_raw_channels[idx].clone()
        }
    }

    pub fn retry_config(&self) -> &RetryConfig {
        &self.retry_config
    }
}

/// Wraps a gRPC call with retry logic. Clones the request for each attempt.
/// Forwards the `x-client-name` header so the downstream service can
/// attribute metrics to the originating client.
///
/// The `$client_fn` parameter selects the channel pool: `next_heavy_client`
/// for RPCs returning large Person/Group payloads, `next_light_client` for
/// small/scalar responses.
macro_rules! retry_call {
    ($self:expr, $client_fn:ident, $method:ident, $request:expr) => {{
        with_retry(&$self.retry_config, stringify!($method), || {
            let mut client = $self.$client_fn();
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
    // ── Heavy: Person lookups (return Person objects with properties) ───

    async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status> {
        retry_call!(self, next_heavy_client, get_person, request)
    }

    async fn get_persons(&self, request: GetPersonsRequest) -> Result<PersonsResponse, Status> {
        retry_call!(self, next_heavy_client, get_persons, request)
    }

    async fn get_person_by_uuid(
        &self,
        request: GetPersonByUuidRequest,
    ) -> Result<GetPersonResponse, Status> {
        retry_call!(self, next_heavy_client, get_person_by_uuid, request)
    }

    async fn get_persons_by_uuids(
        &self,
        request: GetPersonsByUuidsRequest,
    ) -> Result<PersonsResponse, Status> {
        retry_call!(self, next_heavy_client, get_persons_by_uuids, request)
    }

    async fn get_person_by_distinct_id(
        &self,
        request: GetPersonByDistinctIdRequest,
    ) -> Result<GetPersonResponse, Status> {
        retry_call!(self, next_heavy_client, get_person_by_distinct_id, request)
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        request: GetPersonsByDistinctIdsInTeamRequest,
    ) -> Result<PersonsByDistinctIdsInTeamResponse, Status> {
        retry_call!(
            self,
            next_heavy_client,
            get_persons_by_distinct_ids_in_team,
            request
        )
    }

    async fn get_persons_by_distinct_ids(
        &self,
        request: GetPersonsByDistinctIdsRequest,
    ) -> Result<PersonsByDistinctIdsResponse, Status> {
        retry_call!(
            self,
            next_heavy_client,
            get_persons_by_distinct_ids,
            request
        )
    }

    // ── Light: Distinct ID for single person (bounded string list) ───

    async fn get_distinct_ids_for_person(
        &self,
        request: GetDistinctIdsForPersonRequest,
    ) -> Result<GetDistinctIdsForPersonResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            get_distinct_ids_for_person,
            request
        )
    }

    // ── Heavy: Distinct IDs for multiple persons (p99: 540 rows EU) ──

    async fn get_distinct_ids_for_persons(
        &self,
        request: GetDistinctIdsForPersonsRequest,
    ) -> Result<GetDistinctIdsForPersonsResponse, Status> {
        retry_call!(
            self,
            next_heavy_client,
            get_distinct_ids_for_persons,
            request
        )
    }

    // ── Light: Feature flag hash key overrides (small structs/scalars) ─

    async fn get_hash_key_override_context(
        &self,
        request: GetHashKeyOverrideContextRequest,
    ) -> Result<GetHashKeyOverrideContextResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            get_hash_key_override_context,
            request
        )
    }

    async fn upsert_hash_key_overrides(
        &self,
        request: UpsertHashKeyOverridesRequest,
    ) -> Result<UpsertHashKeyOverridesResponse, Status> {
        retry_call!(self, next_light_client, upsert_hash_key_overrides, request)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        request: DeleteHashKeyOverridesByTeamsRequest,
    ) -> Result<DeleteHashKeyOverridesByTeamsResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            delete_hash_key_overrides_by_teams,
            request
        )
    }

    // ── Light: Person deletes (scalar responses) ─────────────────────

    async fn delete_persons(
        &self,
        request: DeletePersonsRequest,
    ) -> Result<DeletePersonsResponse, Status> {
        retry_call!(self, next_light_client, delete_persons, request)
    }

    async fn delete_persons_batch_for_team(
        &self,
        request: DeletePersonsBatchForTeamRequest,
    ) -> Result<DeletePersonsBatchForTeamResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            delete_persons_batch_for_team,
            request
        )
    }

    // ── Light: Cohort membership (small/scalar responses) ────────────

    async fn check_cohort_membership(
        &self,
        request: CheckCohortMembershipRequest,
    ) -> Result<CohortMembershipResponse, Status> {
        retry_call!(self, next_light_client, check_cohort_membership, request)
    }

    async fn count_cohort_members(
        &self,
        request: CountCohortMembersRequest,
    ) -> Result<CountCohortMembersResponse, Status> {
        retry_call!(self, next_light_client, count_cohort_members, request)
    }

    async fn delete_cohort_member(
        &self,
        request: DeleteCohortMemberRequest,
    ) -> Result<DeleteCohortMemberResponse, Status> {
        retry_call!(self, next_light_client, delete_cohort_member, request)
    }

    async fn delete_cohort_members_bulk(
        &self,
        request: DeleteCohortMembersBulkRequest,
    ) -> Result<DeleteCohortMembersBulkResponse, Status> {
        retry_call!(self, next_light_client, delete_cohort_members_bulk, request)
    }

    async fn insert_cohort_members(
        &self,
        request: InsertCohortMembersRequest,
    ) -> Result<InsertCohortMembersResponse, Status> {
        retry_call!(self, next_light_client, insert_cohort_members, request)
    }

    // ── Heavy: ListCohortMemberIds (unbounded repeated int64) ────────

    async fn list_cohort_member_ids(
        &self,
        request: ListCohortMemberIdsRequest,
    ) -> Result<ListCohortMemberIdsResponse, Status> {
        retry_call!(self, next_heavy_client, list_cohort_member_ids, request)
    }

    // ── Heavy: Group reads (return Group objects with properties) ─────

    async fn get_group(&self, request: GetGroupRequest) -> Result<GetGroupResponse, Status> {
        retry_call!(self, next_heavy_client, get_group, request)
    }

    async fn get_groups(&self, request: GetGroupsRequest) -> Result<GroupsResponse, Status> {
        retry_call!(self, next_heavy_client, get_groups, request)
    }

    async fn get_groups_batch(
        &self,
        request: GetGroupsBatchRequest,
    ) -> Result<GetGroupsBatchResponse, Status> {
        retry_call!(self, next_heavy_client, get_groups_batch, request)
    }

    async fn list_groups(&self, request: ListGroupsRequest) -> Result<ListGroupsResponse, Status> {
        retry_call!(self, next_heavy_client, list_groups, request)
    }

    // ── Light: Group type mappings (small struct rows, no JSON blobs) ─

    async fn get_group_type_mappings_by_team_id(
        &self,
        request: GetGroupTypeMappingsByTeamIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            get_group_type_mappings_by_team_id,
            request
        )
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        request: GetGroupTypeMappingsByTeamIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            get_group_type_mappings_by_team_ids,
            request
        )
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        request: GetGroupTypeMappingsByProjectIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            get_group_type_mappings_by_project_id,
            request
        )
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        request: GetGroupTypeMappingsByProjectIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            get_group_type_mappings_by_project_ids,
            request
        )
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        request: GetGroupTypeMappingByDashboardIdRequest,
    ) -> Result<GetGroupTypeMappingByDashboardIdResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            get_group_type_mapping_by_dashboard_id,
            request
        )
    }

    // ── Heavy: Group writes (return Group objects with properties) ────

    async fn create_group(
        &self,
        request: CreateGroupRequest,
    ) -> Result<CreateGroupResponse, Status> {
        retry_call!(self, next_heavy_client, create_group, request)
    }

    async fn update_group(
        &self,
        request: UpdateGroupRequest,
    ) -> Result<UpdateGroupResponse, Status> {
        retry_call!(self, next_heavy_client, update_group, request)
    }

    // ── Light: Group batch delete (scalar response) ──────────────────

    async fn delete_groups_batch_for_team(
        &self,
        request: DeleteGroupsBatchForTeamRequest,
    ) -> Result<DeleteGroupsBatchForTeamResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            delete_groups_batch_for_team,
            request
        )
    }

    // ── Light: Group type mapping writes (small struct/scalar) ───────

    async fn update_group_type_mapping(
        &self,
        request: UpdateGroupTypeMappingRequest,
    ) -> Result<UpdateGroupTypeMappingResponse, Status> {
        retry_call!(self, next_light_client, update_group_type_mapping, request)
    }

    async fn delete_group_type_mapping(
        &self,
        request: DeleteGroupTypeMappingRequest,
    ) -> Result<DeleteGroupTypeMappingResponse, Status> {
        retry_call!(self, next_light_client, delete_group_type_mapping, request)
    }

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        request: DeleteGroupTypeMappingsBatchForTeamRequest,
    ) -> Result<DeleteGroupTypeMappingsBatchForTeamResponse, Status> {
        retry_call!(
            self,
            next_light_client,
            delete_group_type_mappings_batch_for_team,
            request
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::proxy::KNOWN_METHODS;

    fn make_backend(num_heavy: usize, num_light: usize) -> ReplicaBackend {
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
            num_channels: num_heavy,
            num_light_channels: num_light,
        })
    }

    #[tokio::test]
    async fn heavy_client_round_robins_across_channels() {
        let backend = make_backend(4, 2);
        for round in 0..3u64 {
            for ch in 0..4u64 {
                backend.next_heavy_client();
                let expected = round * 4 + ch + 1;
                assert_eq!(
                    backend.heavy_next_idx.load(Ordering::Relaxed),
                    expected as usize
                );
            }
        }
    }

    #[tokio::test]
    async fn light_client_round_robins_across_channels() {
        let backend = make_backend(4, 2);
        for round in 0..3u64 {
            for ch in 0..2u64 {
                backend.next_light_client();
                let expected = round * 2 + ch + 1;
                assert_eq!(
                    backend.light_next_idx.load(Ordering::Relaxed),
                    expected as usize
                );
            }
        }
    }

    #[tokio::test]
    async fn heavy_and_light_pools_are_independent() {
        let backend = make_backend(4, 2);
        for _ in 0..5 {
            backend.next_heavy_client();
        }
        assert_eq!(backend.heavy_next_idx.load(Ordering::Relaxed), 5);
        assert_eq!(backend.light_next_idx.load(Ordering::Relaxed), 0);

        for _ in 0..3 {
            backend.next_light_client();
        }
        assert_eq!(backend.heavy_next_idx.load(Ordering::Relaxed), 5);
        assert_eq!(backend.light_next_idx.load(Ordering::Relaxed), 3);
    }

    #[tokio::test]
    async fn heavy_client_wraps_around() {
        let backend = make_backend(3, 2);
        for _ in 0..3 {
            backend.next_heavy_client();
        }
        let idx_before = backend.heavy_next_idx.load(Ordering::Relaxed);
        backend.next_heavy_client();
        assert_eq!(idx_before % backend.heavy_clients.len(), 0);
    }

    #[tokio::test]
    async fn num_channels_floors_to_one() {
        let backend = make_backend(0, 0);
        assert_eq!(backend.heavy_clients.len(), 1);
        assert_eq!(backend.light_clients.len(), 1);
    }

    #[test]
    fn light_methods_is_sorted() {
        for window in LIGHT_METHODS.windows(2) {
            assert!(
                window[0] < window[1],
                "LIGHT_METHODS is not sorted: {:?} should come after {:?}",
                window[0],
                window[1],
            );
        }
    }

    #[test]
    fn light_methods_are_all_known() {
        for method in LIGHT_METHODS {
            assert!(
                KNOWN_METHODS.contains(method),
                "LIGHT_METHODS contains unknown method: {method}"
            );
        }
    }

    #[test]
    fn classification_correctness() {
        // Light methods
        assert!(is_light_method("GetGroupTypeMappingsByProjectIds"));
        assert!(is_light_method("GetGroupTypeMappingsByTeamIds"));
        assert!(is_light_method("CheckCohortMembership"));
        assert!(is_light_method("GetHashKeyOverrideContext"));
        assert!(is_light_method("DeletePersons"));
        assert!(is_light_method("GetDistinctIdsForPerson"));

        // Heavy methods
        assert!(!is_light_method("GetPerson"));
        assert!(!is_light_method("GetPersonsByDistinctIds"));
        assert!(!is_light_method("GetGroupsBatch"));
        assert!(!is_light_method("GetGroups"));
        assert!(!is_light_method("GetDistinctIdsForPersons"));
        assert!(!is_light_method("ListCohortMemberIds"));
        assert!(!is_light_method("CreateGroup"));

        // Unknown methods default to heavy
        assert!(!is_light_method("FakeMethod"));
        assert!(!is_light_method(""));
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
    fn typed_proxy_annotations_match_light_methods() {
        let source = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/src/backend/replica.rs"
        ))
        .expect("failed to read replica.rs");

        let mut typed_light: Vec<String> = Vec::new();
        let mut typed_heavy: Vec<String> = Vec::new();

        // Collect retry_call! invocations spanning multiple lines by accumulating
        // text between `retry_call!(` and the closing `)`.
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
            if args.len() >= 3 {
                let client_fn = args[1].trim();
                let method_snake = args[2].trim();
                let method = snake_to_pascal(method_snake);
                match client_fn {
                    "next_light_client" => typed_light.push(method),
                    "next_heavy_client" => typed_heavy.push(method),
                    _ => {}
                }
            }
            macro_buf.clear();
        }

        typed_light.sort();
        typed_heavy.sort();

        assert!(
            !typed_light.is_empty() && !typed_heavy.is_empty(),
            "parser found no retry_call! invocations — source formatting may have changed"
        );

        for method in &typed_light {
            assert!(
                is_light_method(method),
                "retry_call! uses next_light_client for '{method}' but it's not in LIGHT_METHODS"
            );
        }

        for method in &typed_heavy {
            assert!(
                !is_light_method(method),
                "retry_call! uses next_heavy_client for '{method}' but it IS in LIGHT_METHODS"
            );
        }

        let mut all_typed: Vec<&str> = typed_light
            .iter()
            .chain(typed_heavy.iter())
            .map(|s| s.as_str())
            .collect();
        all_typed.sort();

        let mut all_known: Vec<&str> = KNOWN_METHODS.to_vec();
        all_known.retain(|m| !LEADER_ONLY_METHODS.contains(m));
        all_known.sort();

        assert_eq!(
            all_typed, all_known,
            "retry_call! annotations don't cover all known methods (minus leader-only ones)"
        );

        assert_eq!(
            typed_light.len(),
            LIGHT_METHODS.len(),
            "number of next_light_client annotations ({}) doesn't match LIGHT_METHODS ({})",
            typed_light.len(),
            LIGHT_METHODS.len(),
        );
    }

    #[tokio::test]
    async fn raw_channel_routes_by_method() {
        let backend = make_backend(4, 2);

        backend.next_raw_channel_for("GetGroupTypeMappingsByProjectIds");
        assert_eq!(backend.light_next_idx.load(Ordering::Relaxed), 1);
        assert_eq!(backend.heavy_next_idx.load(Ordering::Relaxed), 0);

        backend.next_raw_channel_for("GetGroupsBatch");
        assert_eq!(backend.light_next_idx.load(Ordering::Relaxed), 1);
        assert_eq!(backend.heavy_next_idx.load(Ordering::Relaxed), 1);

        backend.next_raw_channel_for("UnknownMethod");
        assert_eq!(backend.light_next_idx.load(Ordering::Relaxed), 1);
        assert_eq!(backend.heavy_next_idx.load(Ordering::Relaxed), 2);
    }
}
