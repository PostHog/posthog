#![allow(dead_code, clippy::type_complexity)]

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use personhog_common::async_gzip::{AsyncGzipConfig, AsyncGzipLayer};
use personhog_proto::personhog::leader::v1::person_hog_leader_server::{
    PersonHogLeader, PersonHogLeaderServer,
};
use personhog_proto::personhog::leader::v1::LeaderGetPersonRequest;
use personhog_proto::personhog::replica::v1::person_hog_replica_server::{
    PersonHogReplica, PersonHogReplicaServer,
};
use personhog_proto::personhog::service::v1::person_hog_service_client::PersonHogServiceClient;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembershipResponse, CountCohortMembersRequest,
    CountCohortMembersResponse, CountGroupTypeMappingsRequest, CountGroupTypeMappingsResponse,
    CreateGroupRequest, CreateGroupResponse, DeleteCohortMemberRequest, DeleteCohortMemberResponse,
    DeleteCohortMembersBulkRequest, DeleteCohortMembersBulkResponse, DeleteGroupTypeMappingRequest,
    DeleteGroupTypeMappingResponse, DeleteGroupTypeMappingsBatchForTeamRequest,
    DeleteGroupTypeMappingsBatchForTeamResponse, DeleteGroupsBatchForTeamRequest,
    DeleteGroupsBatchForTeamResponse, DeleteHashKeyOverridesByTeamsRequest,
    DeleteHashKeyOverridesByTeamsResponse, DeletePersonlessDistinctIdsBatchForTeamRequest,
    DeletePersonlessDistinctIdsBatchForTeamResponse, DeletePersonsBatchForTeamRequest,
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
    ListCohortMemberIdsResponse, ListGroupsRequest, ListGroupsResponse, Person,
    PersonsByDistinctIdsInTeamResponse, PersonsByDistinctIdsResponse, PersonsResponse,
    SetPersonDistinctIdVersionFloorRequest, SetPersonDistinctIdVersionFloorResponse,
    SetPersonVersionFloorRequest, SetPersonVersionFloorResponse, SplitPersonRequest,
    SplitPersonResponse, UpdateGroupRequest, UpdateGroupResponse, UpdateGroupTypeMappingRequest,
    UpdateGroupTypeMappingResponse, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
    UpsertHashKeyOverridesRequest, UpsertHashKeyOverridesResponse,
};
use personhog_router::backend::{
    LeaderBackend, LeaderBackendConfig, ReplicaBackend, ReplicaDnsConfig, StashTable,
};
use personhog_router::config::RetryConfig;
use personhog_router::proxy::RawProxyService;
use tokio::net::TcpListener;
use tokio::sync::RwLock;
use tonic::codec::CompressionEncoding;
use tonic::transport::{Channel, Server};
use tonic::{Request, Response, Status};
use tower::Service;

use personhog_proto::personhog::types::v1::{
    CohortMembership, Group, GroupTypeMapping, HashKeyOverrideContext, PersonWithDistinctIds,
};

/// A configurable replica service implementation for integration tests.
/// Supports setting up responses for different RPC methods.
pub struct TestReplicaService {
    pub person: Option<Person>,
    pub persons_by_distinct_id: Vec<PersonWithDistinctIds>,
    pub cohort_memberships: Vec<CohortMembership>,
    pub hash_key_override_contexts: Vec<HashKeyOverrideContext>,
    pub upsert_inserted_count: i64,
    pub groups: Vec<Group>,
    pub group_type_mappings: Vec<GroupTypeMapping>,
}

impl TestReplicaService {
    pub fn new() -> Self {
        Self {
            person: None,
            persons_by_distinct_id: vec![],
            cohort_memberships: vec![],
            hash_key_override_contexts: vec![],
            upsert_inserted_count: 0,
            groups: vec![],
            group_type_mappings: vec![],
        }
    }

    pub fn with_person(person: Person) -> Self {
        Self {
            person: Some(person),
            ..Self::new()
        }
    }

    pub fn with_persons_by_distinct_id(mut self, persons: Vec<PersonWithDistinctIds>) -> Self {
        self.persons_by_distinct_id = persons;
        self
    }

    pub fn with_cohort_memberships(mut self, memberships: Vec<CohortMembership>) -> Self {
        self.cohort_memberships = memberships;
        self
    }

    pub fn with_hash_key_override_contexts(
        mut self,
        contexts: Vec<HashKeyOverrideContext>,
    ) -> Self {
        self.hash_key_override_contexts = contexts;
        self
    }

    pub fn with_upsert_inserted_count(mut self, count: i64) -> Self {
        self.upsert_inserted_count = count;
        self
    }

    pub fn with_groups(mut self, groups: Vec<Group>) -> Self {
        self.groups = groups;
        self
    }

    pub fn with_group_type_mappings(mut self, mappings: Vec<GroupTypeMapping>) -> Self {
        self.group_type_mappings = mappings;
        self
    }
}

#[tonic::async_trait]
impl PersonHogReplica for TestReplicaService {
    async fn get_person(
        &self,
        _request: Request<GetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        Ok(Response::new(GetPersonResponse {
            person: self.person.clone(),
        }))
    }

    async fn get_persons(
        &self,
        _request: Request<GetPersonsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        Ok(Response::new(PersonsResponse {
            persons: self.person.clone().into_iter().collect(),
            missing_ids: vec![],
        }))
    }

    async fn get_person_by_uuid(
        &self,
        _request: Request<GetPersonByUuidRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        Ok(Response::new(GetPersonResponse {
            person: self.person.clone(),
        }))
    }

    async fn get_persons_by_uuids(
        &self,
        _request: Request<GetPersonsByUuidsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        Ok(Response::new(PersonsResponse {
            persons: self.person.clone().into_iter().collect(),
            missing_ids: vec![],
        }))
    }

    async fn get_person_by_distinct_id(
        &self,
        _request: Request<GetPersonByDistinctIdRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        Ok(Response::new(GetPersonResponse {
            person: self.person.clone(),
        }))
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        _request: Request<GetPersonsByDistinctIdsInTeamRequest>,
    ) -> Result<Response<PersonsByDistinctIdsInTeamResponse>, Status> {
        Ok(Response::new(PersonsByDistinctIdsInTeamResponse {
            results: self.persons_by_distinct_id.clone(),
        }))
    }

    async fn get_persons_by_distinct_ids(
        &self,
        _request: Request<GetPersonsByDistinctIdsRequest>,
    ) -> Result<Response<PersonsByDistinctIdsResponse>, Status> {
        Ok(Response::new(PersonsByDistinctIdsResponse {
            results: vec![],
        }))
    }

    async fn get_distinct_ids_for_person(
        &self,
        _request: Request<GetDistinctIdsForPersonRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonResponse>, Status> {
        Ok(Response::new(GetDistinctIdsForPersonResponse {
            distinct_ids: vec![],
        }))
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _request: Request<GetDistinctIdsForPersonsRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonsResponse>, Status> {
        Ok(Response::new(GetDistinctIdsForPersonsResponse {
            person_distinct_ids: vec![],
        }))
    }

    async fn get_hash_key_override_context(
        &self,
        _request: Request<GetHashKeyOverrideContextRequest>,
    ) -> Result<Response<GetHashKeyOverrideContextResponse>, Status> {
        Ok(Response::new(GetHashKeyOverrideContextResponse {
            results: self.hash_key_override_contexts.clone(),
        }))
    }

    async fn upsert_hash_key_overrides(
        &self,
        _request: Request<UpsertHashKeyOverridesRequest>,
    ) -> Result<Response<UpsertHashKeyOverridesResponse>, Status> {
        Ok(Response::new(UpsertHashKeyOverridesResponse {
            inserted_count: self.upsert_inserted_count,
        }))
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _request: Request<DeleteHashKeyOverridesByTeamsRequest>,
    ) -> Result<Response<DeleteHashKeyOverridesByTeamsResponse>, Status> {
        Ok(Response::new(DeleteHashKeyOverridesByTeamsResponse {
            deleted_count: 0,
        }))
    }

    async fn check_cohort_membership(
        &self,
        _request: Request<CheckCohortMembershipRequest>,
    ) -> Result<Response<CohortMembershipResponse>, Status> {
        Ok(Response::new(CohortMembershipResponse {
            memberships: self.cohort_memberships.clone(),
        }))
    }

    async fn count_cohort_members(
        &self,
        _request: Request<CountCohortMembersRequest>,
    ) -> Result<Response<CountCohortMembersResponse>, Status> {
        Ok(Response::new(CountCohortMembersResponse { count: 0 }))
    }

    async fn delete_cohort_member(
        &self,
        _request: Request<DeleteCohortMemberRequest>,
    ) -> Result<Response<DeleteCohortMemberResponse>, Status> {
        Ok(Response::new(DeleteCohortMemberResponse { deleted: false }))
    }

    async fn delete_cohort_members_bulk(
        &self,
        _request: Request<DeleteCohortMembersBulkRequest>,
    ) -> Result<Response<DeleteCohortMembersBulkResponse>, Status> {
        Ok(Response::new(DeleteCohortMembersBulkResponse {
            deleted_count: 0,
        }))
    }

    async fn insert_cohort_members(
        &self,
        _request: Request<InsertCohortMembersRequest>,
    ) -> Result<Response<InsertCohortMembersResponse>, Status> {
        Ok(Response::new(InsertCohortMembersResponse {
            inserted_count: 0,
        }))
    }

    async fn list_cohort_member_ids(
        &self,
        _request: Request<ListCohortMemberIdsRequest>,
    ) -> Result<Response<ListCohortMemberIdsResponse>, Status> {
        Ok(Response::new(ListCohortMemberIdsResponse {
            person_ids: vec![],
            next_cursor: 0,
        }))
    }

    async fn get_group(
        &self,
        _request: Request<GetGroupRequest>,
    ) -> Result<Response<GetGroupResponse>, Status> {
        Ok(Response::new(GetGroupResponse { group: None }))
    }

    async fn get_groups(
        &self,
        _request: Request<GetGroupsRequest>,
    ) -> Result<Response<GroupsResponse>, Status> {
        Ok(Response::new(GroupsResponse {
            groups: self.groups.clone(),
            missing_groups: vec![],
        }))
    }

    async fn get_groups_batch(
        &self,
        _request: Request<GetGroupsBatchRequest>,
    ) -> Result<Response<GetGroupsBatchResponse>, Status> {
        Ok(Response::new(GetGroupsBatchResponse { results: vec![] }))
    }

    async fn list_groups(
        &self,
        _request: Request<ListGroupsRequest>,
    ) -> Result<Response<ListGroupsResponse>, Status> {
        Ok(Response::new(ListGroupsResponse {
            groups: vec![],
            has_more: false,
        }))
    }

    async fn get_group_type_mappings_by_team_id(
        &self,
        _request: Request<GetGroupTypeMappingsByTeamIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        Ok(Response::new(GroupTypeMappingsResponse {
            mappings: self.group_type_mappings.clone(),
        }))
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        _request: Request<GetGroupTypeMappingsByTeamIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        Ok(Response::new(GroupTypeMappingsBatchResponse {
            results: vec![],
        }))
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        _request: Request<GetGroupTypeMappingsByProjectIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        Ok(Response::new(GroupTypeMappingsResponse {
            mappings: self.group_type_mappings.clone(),
        }))
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        _request: Request<GetGroupTypeMappingsByProjectIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        Ok(Response::new(GroupTypeMappingsBatchResponse {
            results: vec![],
        }))
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        _request: Request<GetGroupTypeMappingByDashboardIdRequest>,
    ) -> Result<Response<GetGroupTypeMappingByDashboardIdResponse>, Status> {
        Ok(Response::new(GetGroupTypeMappingByDashboardIdResponse {
            mapping: None,
        }))
    }

    async fn count_group_type_mappings(
        &self,
        _request: Request<CountGroupTypeMappingsRequest>,
    ) -> Result<Response<CountGroupTypeMappingsResponse>, Status> {
        Ok(Response::new(CountGroupTypeMappingsResponse {
            counts: vec![],
        }))
    }

    async fn create_group(
        &self,
        _request: Request<CreateGroupRequest>,
    ) -> Result<Response<CreateGroupResponse>, Status> {
        Ok(Response::new(CreateGroupResponse { group: None }))
    }

    async fn update_group(
        &self,
        _request: Request<UpdateGroupRequest>,
    ) -> Result<Response<UpdateGroupResponse>, Status> {
        Ok(Response::new(UpdateGroupResponse {
            group: None,
            updated: false,
        }))
    }

    async fn delete_groups_batch_for_team(
        &self,
        _request: Request<DeleteGroupsBatchForTeamRequest>,
    ) -> Result<Response<DeleteGroupsBatchForTeamResponse>, Status> {
        Ok(Response::new(DeleteGroupsBatchForTeamResponse {
            deleted_count: 0,
        }))
    }

    async fn update_group_type_mapping(
        &self,
        _request: Request<UpdateGroupTypeMappingRequest>,
    ) -> Result<Response<UpdateGroupTypeMappingResponse>, Status> {
        Ok(Response::new(UpdateGroupTypeMappingResponse {
            mapping: None,
        }))
    }

    async fn delete_group_type_mapping(
        &self,
        _request: Request<DeleteGroupTypeMappingRequest>,
    ) -> Result<Response<DeleteGroupTypeMappingResponse>, Status> {
        Ok(Response::new(DeleteGroupTypeMappingResponse {
            deleted: false,
        }))
    }

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        _request: Request<DeleteGroupTypeMappingsBatchForTeamRequest>,
    ) -> Result<Response<DeleteGroupTypeMappingsBatchForTeamResponse>, Status> {
        Ok(Response::new(DeleteGroupTypeMappingsBatchForTeamResponse {
            deleted_count: 0,
        }))
    }

    async fn delete_persons(
        &self,
        _request: Request<DeletePersonsRequest>,
    ) -> Result<Response<DeletePersonsResponse>, Status> {
        Ok(Response::new(DeletePersonsResponse { deleted_count: 0 }))
    }

    async fn delete_persons_batch_for_team(
        &self,
        _request: Request<DeletePersonsBatchForTeamRequest>,
    ) -> Result<Response<DeletePersonsBatchForTeamResponse>, Status> {
        Ok(Response::new(DeletePersonsBatchForTeamResponse {
            deleted_count: 0,
        }))
    }

    async fn delete_personless_distinct_ids_batch_for_team(
        &self,
        _request: Request<DeletePersonlessDistinctIdsBatchForTeamRequest>,
    ) -> Result<Response<DeletePersonlessDistinctIdsBatchForTeamResponse>, Status> {
        Ok(Response::new(
            DeletePersonlessDistinctIdsBatchForTeamResponse { deleted_count: 0 },
        ))
    }

    async fn split_person(
        &self,
        _request: Request<SplitPersonRequest>,
    ) -> Result<Response<SplitPersonResponse>, Status> {
        Ok(Response::new(SplitPersonResponse { splits: vec![] }))
    }

    async fn set_person_distinct_id_version_floor(
        &self,
        _request: Request<SetPersonDistinctIdVersionFloorRequest>,
    ) -> Result<Response<SetPersonDistinctIdVersionFloorResponse>, Status> {
        Ok(Response::new(SetPersonDistinctIdVersionFloorResponse {
            person: None,
        }))
    }

    async fn set_person_version_floor(
        &self,
        _request: Request<SetPersonVersionFloorRequest>,
    ) -> Result<Response<SetPersonVersionFloorResponse>, Status> {
        Ok(Response::new(SetPersonVersionFloorResponse {
            updated: false,
        }))
    }
}

/// Start a test replica server on a random port and return its address
pub async fn start_test_replica(service: TestReplicaService) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        Server::builder()
            .add_service(
                PersonHogReplicaServer::new(service)
                    .accept_compressed(CompressionEncoding::Zstd)
                    .send_compressed(CompressionEncoding::Zstd),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    // Give the server a moment to start
    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}

/// Start a test replica that uses `AsyncGzipLayer` for response compression,
/// matching the production configuration where gzip is offloaded to a blocking
/// thread instead of running inline on the tokio runtime.
pub async fn start_test_replica_with_async_gzip(service: TestReplicaService) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        Server::builder()
            .layer(AsyncGzipLayer::new(AsyncGzipConfig {
                enabled: true,
                min_payload_size: 0,
                ..AsyncGzipConfig::default()
            }))
            .add_service(
                PersonHogReplicaServer::new(service)
                    .accept_compressed(CompressionEncoding::Zstd)
                    .send_compressed(CompressionEncoding::Zstd),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}

/// Start a test replica with `AsyncGzipLayer` disabled, verifying the flag
/// prevents compression even when clients advertise gzip support.
pub async fn start_test_replica_with_async_gzip_disabled(
    service: TestReplicaService,
) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        Server::builder()
            .layer(AsyncGzipLayer::new(AsyncGzipConfig::default()))
            .add_service(
                PersonHogReplicaServer::new(service)
                    .accept_compressed(CompressionEncoding::Zstd)
                    .send_compressed(CompressionEncoding::Zstd),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}

/// Create a client connected to the router
pub async fn create_client(router_addr: SocketAddr) -> PersonHogServiceClient<Channel> {
    let url = format!("http://{}", router_addr);
    PersonHogServiceClient::connect(url).await.unwrap()
}

/// Create a client that sends Zstd-compressed requests.
pub async fn create_compressed_client(router_addr: SocketAddr) -> PersonHogServiceClient<Channel> {
    let url = format!("http://{}", router_addr);
    let channel = Channel::from_shared(url).unwrap().connect().await.unwrap();
    PersonHogServiceClient::new(channel)
        .send_compressed(CompressionEncoding::Zstd)
        .accept_compressed(CompressionEncoding::Zstd)
}

/// Send a raw gRPC unary request with `grpc-accept-encoding: gzip` and return
/// the response headers and body bytes. Uses tonic's Channel as HTTP/2
/// transport but bypasses the gRPC codec layer so we can inspect the wire
/// format — this matches the production scenario where the client is Django's
/// grpcio, not a tonic client.
pub async fn raw_grpc_call_with_gzip_accept(
    addr: SocketAddr,
    path: &str,
    proto_msg: &impl prost::Message,
) -> (http::HeaderMap, bytes::Bytes) {
    use bytes::{BufMut, BytesMut};
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    // Encode protobuf into a gRPC frame: [flag=0][length][protobuf]
    let proto_bytes = proto_msg.encode_to_vec();
    let mut frame = BytesMut::with_capacity(5 + proto_bytes.len());
    frame.put_u8(0);
    frame.put_u32(proto_bytes.len() as u32);
    frame.extend_from_slice(&proto_bytes);

    let mut channel = Channel::from_shared(format!("http://{}", addr))
        .unwrap()
        .connect()
        .await
        .unwrap();

    let body = http_body_util::combinators::UnsyncBoxBody::new(
        http_body_util::Full::new(frame.freeze())
            .map_err(|_: std::convert::Infallible| tonic::Status::internal("unreachable")),
    );
    let request = http::Request::builder()
        .method("POST")
        .uri(format!("http://{}{}", addr, path))
        .header("content-type", "application/grpc")
        .header("te", "trailers")
        .header("grpc-accept-encoding", "gzip")
        .body(body)
        .unwrap();

    let response = ServiceExt::ready(&mut channel)
        .await
        .unwrap()
        .call(request)
        .await
        .unwrap();

    let headers = response.headers().clone();
    let body = response.into_body().collect().await.unwrap().to_bytes();
    (headers, body)
}

pub fn create_test_person() -> Person {
    Person {
        id: 42,
        team_id: 1,
        uuid: "00000000-0000-0000-0000-000000000042".to_string(),
        properties: b"{}".to_vec(),
        properties_last_updated_at: vec![],
        properties_last_operation: vec![],
        created_at: 0,
        version: 1,
        is_identified: true,
        is_user_id: None,
        last_seen_at: None,
    }
}

// ============================================================
// Leader test helpers
// ============================================================

/// A simple in-memory leader service for integration tests.
/// Stores persons keyed by (team_id, person_id), ignoring partition for lookups.
pub struct TestLeaderService {
    persons: DashMap<(i64, i64), Person>,
}

impl TestLeaderService {
    pub fn new() -> Self {
        Self {
            persons: DashMap::new(),
        }
    }

    pub fn with_person(self, person: Person) -> Self {
        self.persons.insert((person.team_id, person.id), person);
        self
    }
}

#[tonic::async_trait]
impl PersonHogLeader for TestLeaderService {
    async fn get_person(
        &self,
        request: Request<LeaderGetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let req = request.into_inner();
        let person = self
            .persons
            .get(&(req.team_id, req.person_id))
            .map(|entry| entry.value().clone());

        match person {
            Some(p) => Ok(Response::new(GetPersonResponse { person: Some(p) })),
            None => Err(Status::not_found(format!(
                "person not found: team_id={}, person_id={}",
                req.team_id, req.person_id
            ))),
        }
    }

    async fn update_person_properties(
        &self,
        request: Request<UpdatePersonPropertiesRequest>,
    ) -> Result<Response<UpdatePersonPropertiesResponse>, Status> {
        let req = request.into_inner();
        let key = (req.team_id, req.person_id);

        let mut person = self
            .persons
            .get(&key)
            .map(|entry| entry.value().clone())
            .ok_or_else(|| {
                Status::not_found(format!(
                    "person not found: team_id={}, person_id={}",
                    req.team_id, req.person_id
                ))
            })?;

        // Merge $set properties into existing properties
        if !req.set_properties.is_empty() {
            let set: serde_json::Value =
                serde_json::from_slice(&req.set_properties).unwrap_or_default();
            let mut existing: serde_json::Value =
                serde_json::from_slice(&person.properties).unwrap_or_default();
            if let (Some(existing_map), Some(set_map)) = (existing.as_object_mut(), set.as_object())
            {
                for (k, v) in set_map {
                    existing_map.insert(k.clone(), v.clone());
                }
            }
            person.properties = serde_json::to_vec(&existing).unwrap_or_default();
        }

        person.version += 1;
        self.persons.insert(key, person.clone());

        Ok(Response::new(UpdatePersonPropertiesResponse {
            person: Some(person),
            updated: true,
        }))
    }
}

/// Start a test leader server on a random port and return its address.
pub async fn start_test_leader(service: TestLeaderService) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        // The production `LeaderBackend` configures its gRPC client with
        // `send_compressed(Zstd) + accept_compressed(Zstd)`, so the test
        // leader must accept (and may send) Zstd-compressed payloads to
        // mirror real wire behavior. Without this the LeaderBackend
        // forwards a Zstd-compressed body and the server returns
        // `Unimplemented: Content is compressed with zstd which isn't supported`.
        Server::builder()
            .add_service(
                PersonHogLeaderServer::new(service)
                    .accept_compressed(CompressionEncoding::Zstd)
                    .send_compressed(CompressionEncoding::Zstd),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}

// ============================================================
// Raw proxy test helpers
// ============================================================

fn make_replica_backend(replica_addr: SocketAddr) -> Arc<ReplicaBackend> {
    let retry_config = RetryConfig {
        max_retries: 1,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    };
    Arc::new(ReplicaBackend::new_dns(ReplicaDnsConfig {
        url: format!("http://{}", replica_addr),
        timeout: Duration::from_secs(5),
        retry_config,
        keepalive_interval: None,
        keepalive_timeout: None,
        num_channels: 1,
    }))
}

fn make_leader_backend(leader_addr: SocketAddr, num_partitions: u32) -> Arc<LeaderBackend> {
    let retry_config = RetryConfig {
        max_retries: 1,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    };
    let mut routing = HashMap::new();
    for p in 0..num_partitions {
        routing.insert(p, "leader-0".to_string());
    }
    let routing_table = Arc::new(RwLock::new(routing));
    let leader_url = format!("http://{}", leader_addr);
    let address_resolver: Arc<dyn Fn(&str) -> Option<String> + Send + Sync> =
        Arc::new(move |_pod_name| Some(leader_url.clone()));
    Arc::new(LeaderBackend::new(
        routing_table,
        address_resolver,
        LeaderBackendConfig {
            num_partitions,
            timeout: Duration::from_secs(5),
            retry_config,
            max_send_message_size: 4 * 1024 * 1024,
            max_recv_message_size: 4 * 1024 * 1024,
        },
        StashTable::with_bounds(usize::MAX, usize::MAX),
    ))
}

/// Start a raw proxy router (replica only, no leader).
pub async fn start_test_router_raw(replica_addr: SocketAddr) -> SocketAddr {
    start_test_router_raw_with_max_recv(replica_addr, 4 * 1024 * 1024).await
}

/// Start a raw proxy router with a custom max receive message size.
pub async fn start_test_router_raw_with_max_recv(
    replica_addr: SocketAddr,
    max_recv_message_size: usize,
) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let replica = make_replica_backend(replica_addr);
    let retry_config = RetryConfig {
        max_retries: 1,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    };
    let proxy = RawProxyService::new(replica, None, retry_config, max_recv_message_size, 0);

    tokio::spawn(async move {
        Server::builder()
            .add_service(proxy)
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;
    addr
}

/// Start a raw proxy router with both replica and leader backends.
pub async fn start_test_router_raw_with_leader(
    replica_addr: SocketAddr,
    leader_addr: SocketAddr,
    num_partitions: u32,
) -> SocketAddr {
    start_test_router_raw_with_leader_and_max_recv(
        replica_addr,
        leader_addr,
        num_partitions,
        4 * 1024 * 1024,
    )
    .await
}

/// Start a raw proxy router with both backends and a custom max receive message size.
pub async fn start_test_router_raw_with_leader_and_max_recv(
    replica_addr: SocketAddr,
    leader_addr: SocketAddr,
    num_partitions: u32,
    max_recv_message_size: usize,
) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let replica = make_replica_backend(replica_addr);
    let leader = make_leader_backend(leader_addr, num_partitions);
    let retry_config = RetryConfig {
        max_retries: 1,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    };
    let proxy = RawProxyService::new(
        replica,
        Some(leader),
        retry_config,
        max_recv_message_size,
        0,
    );

    tokio::spawn(async move {
        Server::builder()
            .add_service(proxy)
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;
    addr
}
