#![allow(dead_code, clippy::type_complexity)]

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::{
    PersonHogLeader, PersonHogLeaderServer,
};
use personhog_proto::personhog::leader::v1::LeaderGetPersonRequest;
use personhog_proto::personhog::replica::v1::person_hog_replica_server::{
    PersonHogReplica, PersonHogReplicaServer,
};
use personhog_proto::personhog::service::v1::person_hog_service_client::PersonHogServiceClient;
use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogServiceServer;
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
    ListCohortMemberIdsResponse, Person, PersonsByDistinctIdsInTeamResponse,
    PersonsByDistinctIdsResponse, PersonsResponse, UpdatePersonPropertiesRequest,
    UpdatePersonPropertiesResponse, UpsertHashKeyOverridesRequest, UpsertHashKeyOverridesResponse,
};
use personhog_router::backend::{LeaderBackend, ReplicaBackend};
use personhog_router::config::RetryConfig;
use personhog_router::router::PersonHogRouter;
use personhog_router::service::PersonHogRouterService;
use tokio::net::TcpListener;
use tokio::sync::RwLock;
use tonic::transport::{Channel, Server};
use tonic::{Request, Response, Status};

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
}

/// Start a test replica server on a random port and return its address
pub async fn start_test_replica(service: TestReplicaService) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        Server::builder()
            .add_service(PersonHogReplicaServer::new(service))
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    // Give the server a moment to start
    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}

/// Start a test router server connected to the given replica address
pub async fn start_test_router(replica_addr: SocketAddr) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let replica_url = format!("http://{}", replica_addr);
    let retry_config = RetryConfig {
        max_retries: 1,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    };
    let backend = ReplicaBackend::new(
        &replica_url,
        Duration::from_secs(5),
        retry_config,
        None,
        None,
        4 * 1024 * 1024,
        4 * 1024 * 1024,
    )
    .unwrap();
    let router = PersonHogRouter::new(Arc::new(backend));
    let service = PersonHogRouterService::new(Arc::new(router));

    tokio::spawn(async move {
        Server::builder()
            .add_service(PersonHogServiceServer::new(service))
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    // Give the server a moment to start
    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}

/// Create a client connected to the router
pub async fn create_client(router_addr: SocketAddr) -> PersonHogServiceClient<Channel> {
    let url = format!("http://{}", router_addr);
    PersonHogServiceClient::connect(url).await.unwrap()
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
        Server::builder()
            .add_service(PersonHogLeaderServer::new(service))
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}

/// Start a test router with both replica and leader backends.
/// All partitions are mapped to the given leader address.
pub async fn start_test_router_with_leader(
    replica_addr: SocketAddr,
    leader_addr: SocketAddr,
    num_partitions: u32,
) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let retry_config = RetryConfig {
        max_retries: 1,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    };

    // Replica backend
    let replica_url = format!("http://{}", replica_addr);
    let replica = ReplicaBackend::new(
        &replica_url,
        Duration::from_secs(5),
        retry_config,
        None,
        None,
        4 * 1024 * 1024,
        4 * 1024 * 1024,
    )
    .unwrap();

    // Leader backend: all partitions → "leader-0", resolver → leader_addr
    let mut routing = HashMap::new();
    for p in 0..num_partitions {
        routing.insert(p, "leader-0".to_string());
    }
    let routing_table = Arc::new(RwLock::new(routing));
    let leader_url = format!("http://{}", leader_addr);
    let address_resolver: Arc<dyn Fn(&str) -> Option<String> + Send + Sync> =
        Arc::new(move |_pod_name| Some(leader_url.clone()));
    let leader = LeaderBackend::new(
        routing_table,
        address_resolver,
        num_partitions,
        Duration::from_secs(5),
        retry_config,
        4 * 1024 * 1024,
        4 * 1024 * 1024,
    );

    let router = PersonHogRouter::new(Arc::new(replica)).with_leader(Arc::new(leader));
    let service = PersonHogRouterService::new(Arc::new(router));

    tokio::spawn(async move {
        Server::builder()
            .add_service(PersonHogServiceServer::new(service))
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;

    addr
}
