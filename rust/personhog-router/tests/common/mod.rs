#![allow(dead_code, clippy::type_complexity)]

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use dashmap::DashMap;
use personhog_common::async_gzip::{AsyncGzipConfig, AsyncGzipLayer};
use personhog_proto::personhog::leader::v1::person_hog_leader_server::{
    PersonHogLeader, PersonHogLeaderServer,
};
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
                PersonHogReplicaServer::new(service).accept_compressed(CompressionEncoding::Gzip),
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
                PersonHogReplicaServer::new(service).accept_compressed(CompressionEncoding::Gzip),
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
                PersonHogReplicaServer::new(service).accept_compressed(CompressionEncoding::Gzip),
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

/// Create a client that sends gzip-compressed requests, matching a
/// production client with request compression opted in.
pub async fn create_compressed_client(router_addr: SocketAddr) -> PersonHogServiceClient<Channel> {
    let url = format!("http://{}", router_addr);
    let channel = Channel::from_shared(url).unwrap().connect().await.unwrap();
    PersonHogServiceClient::new(channel).send_compressed(CompressionEncoding::Gzip)
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
        is_deleted: false,
    }
}

// ============================================================
// Leader test helpers
// ============================================================

/// A simple in-memory leader service for integration tests.
/// Stores persons keyed by (team_id, person_id). Mirrors the real leader's
/// `x-partition` handling — fail closed when the metadata is missing or
/// malformed — so tests through the router prove the router actually
/// stamps the header, not just that the body arrives intact.
pub struct TestLeaderService {
    persons: DashMap<(i64, i64), Person>,
    /// While true, writes are rejected with FailedPrecondition, mimicking
    /// a leader whose partition is write-fenced for a handoff. Shared and
    /// runtime-toggleable so tests can clear the fence mid-drain, the way
    /// a real fence clears in watch-propagation time.
    fenced: Arc<AtomicBool>,
    /// The lifecycle operation holding this person, if any. Unlike the
    /// partition fence above this one names its holder, which is the fact
    /// the refusal has to carry all the way back to ingestion.
    person_fence_op: Arc<Mutex<Option<String>>>,
}

/// The creator event uuid the simulated person fence carries, asserted
/// forwarded end to end by the raw-proxy tests.
pub const SIM_FENCE_CREATOR: &str = "0189f0e0-1111-7000-8000-000000000000";

impl TestLeaderService {
    pub fn new() -> Self {
        Self {
            persons: DashMap::new(),
            fenced: Arc::new(AtomicBool::new(false)),
            person_fence_op: Arc::new(Mutex::new(None)),
        }
    }

    /// Refuse every write for this person the way the leader refuses one
    /// held by a lifecycle operation: FAILED_PRECONDITION carrying the
    /// fence keys and the holding op's id.
    pub fn person_fenced_by(self, op_id: &str) -> Self {
        *self.person_fence_op.lock().unwrap() = Some(op_id.to_string());
        self
    }

    pub fn with_person(self, person: Person) -> Self {
        self.persons.insert((person.team_id, person.id), person);
        self
    }

    pub fn fenced(self) -> Self {
        self.fenced.store(true, Ordering::SeqCst);
        self
    }

    /// Handle for flipping the fence after the service has been moved
    /// into the server.
    pub fn fence_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.fenced)
    }
}

/// Extract the routing partition from `x-partition` metadata, matching the
/// real leader's `partition_from_metadata` semantics.
#[allow(clippy::result_large_err)]
fn require_partition_metadata<T>(request: &Request<T>) -> Result<u32, Status> {
    request
        .metadata()
        .get("x-partition")
        .ok_or_else(|| Status::invalid_argument("missing x-partition metadata"))?
        .to_str()
        .map_err(|_| Status::invalid_argument("x-partition metadata is not valid ASCII"))?
        .parse::<u32>()
        .map_err(|_| Status::invalid_argument("x-partition metadata is not a valid u32"))
}

#[tonic::async_trait]
impl PersonHogLeader for TestLeaderService {
    async fn fence_person(
        &self,
        request: Request<personhog_proto::personhog::types::v1::FencePersonRequest>,
    ) -> Result<Response<personhog_proto::personhog::types::v1::FencePersonResponse>, Status> {
        require_partition_metadata(&request)?;
        Err(Status::unimplemented("not exercised by router tests"))
    }

    async fn release_fence(
        &self,
        request: Request<personhog_proto::personhog::types::v1::ReleaseFenceRequest>,
    ) -> Result<Response<personhog_proto::personhog::types::v1::ReleaseFenceResponse>, Status> {
        require_partition_metadata(&request)?;
        Err(Status::unimplemented("not exercised by router tests"))
    }

    async fn fold_person_document(
        &self,
        request: Request<personhog_proto::personhog::types::v1::FoldPersonDocumentRequest>,
    ) -> Result<Response<personhog_proto::personhog::types::v1::FoldPersonDocumentResponse>, Status>
    {
        require_partition_metadata(&request)?;
        // Mimics the real leader's fail-closed mark refusal: a definitive
        // FAILED_PRECONDITION marked as semantic, which the router must
        // deliver rather than bounce.
        let mut status =
            Status::failed_precondition("op holds no live target mark for this person");
        status.metadata_mut().insert(
            personhog_common::grpc::SEMANTIC_REFUSAL_METADATA_KEY,
            "fold-unverified".parse().expect("static slug parses"),
        );
        Err(status)
    }

    async fn get_person(
        &self,
        request: Request<GetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        require_partition_metadata(&request)?;
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
        require_partition_metadata(&request)?;
        let req = request.into_inner();
        if self.fenced.load(Ordering::SeqCst) {
            return Err(Status::failed_precondition(
                "partition is fenced for handoff; writes are rejected",
            ));
        }
        if let Some(op_id) = self.person_fence_op.lock().unwrap().clone() {
            let mut status = Status::failed_precondition("person is held by a lifecycle operation");
            // The real leader carries the op-type string here, never a
            // boolean; see fenced_status in personhog-leader/src/fence.rs.
            status
                .metadata_mut()
                .insert("x-person-fenced", "merge".parse().unwrap());
            status
                .metadata_mut()
                .insert("x-person-fenced-op-id", op_id.parse().unwrap());
            status.metadata_mut().insert(
                "x-person-fenced-creator",
                SIM_FENCE_CREATOR.parse().unwrap(),
            );
            return Err(status);
        }
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
    serve_test_leader(listener, service);
    tokio::time::sleep(Duration::from_millis(10)).await;
    addr
}

/// Start the test leader on a specific address. Used by tests that
/// reserve an address up front so the backend can dial it — and fail at
/// the transport layer — before the leader exists.
pub async fn start_test_leader_at(addr: SocketAddr, service: TestLeaderService) {
    let listener = TcpListener::bind(addr)
        .await
        .expect("reserved leader address must be bindable");
    serve_test_leader(listener, service);
    tokio::time::sleep(Duration::from_millis(10)).await;
}

fn serve_test_leader(listener: TcpListener, service: TestLeaderService) {
    tokio::spawn(async move {
        Server::builder()
            .add_service(
                PersonHogLeaderServer::new(service).accept_compressed(CompressionEncoding::Gzip),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });
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
        },
        StashTable::with_bounds(usize::MAX, usize::MAX),
    ))
}

/// A leader backend whose pod answers once and is then unreachable: the
/// resolver hands out the real address for the first resolution and a dead
/// port after it. Models a leader that refuses a request and then dies,
/// which is the only way to follow one bounce reason with another.
fn make_dying_leader_backend(leader_addr: SocketAddr, num_partitions: u32) -> Arc<LeaderBackend> {
    let mut routing = HashMap::new();
    for p in 0..num_partitions {
        routing.insert(p, "leader-0".to_string());
    }
    let routing_table = Arc::new(RwLock::new(routing));
    let leader_url = format!("http://{}", leader_addr);
    let resolutions = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let address_resolver: Arc<dyn Fn(&str) -> Option<String> + Send + Sync> =
        Arc::new(move |_pod_name| {
            if resolutions.fetch_add(1, Ordering::SeqCst) == 0 {
                Some(leader_url.clone())
            } else {
                // Reserved-for-documentation address, so nothing can be listening.
                Some("http://192.0.2.1:1".to_string())
            }
        });
    Arc::new(LeaderBackend::new(
        routing_table,
        address_resolver,
        LeaderBackendConfig {
            num_partitions,
            timeout: Duration::from_millis(200),
        },
        StashTable::with_bounds(usize::MAX, usize::MAX),
    ))
}

/// Raw proxy router whose leader answers one request and is then gone.
pub async fn start_test_router_raw_with_dying_leader(
    replica_addr: SocketAddr,
    leader_addr: SocketAddr,
    num_partitions: u32,
) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let proxy = RawProxyService::new(
        make_replica_backend(replica_addr),
        Some(make_dying_leader_backend(leader_addr, num_partitions)),
        RetryConfig {
            max_retries: 1,
            initial_backoff_ms: 1,
            max_backoff_ms: 1,
        },
        4 * 1024 * 1024,
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
