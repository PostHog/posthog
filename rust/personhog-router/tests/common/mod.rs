use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::{
    PersonHogReplica, PersonHogReplicaServer,
};
use personhog_proto::personhog::service::v1::person_hog_service_client::PersonHogServiceClient;
use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogServiceServer;
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
    Person, PersonsByDistinctIdsInTeamResponse, PersonsByDistinctIdsResponse, PersonsResponse,
    UpsertHashKeyOverridesRequest, UpsertHashKeyOverridesResponse,
};
use personhog_router::backend::ReplicaBackend;
use personhog_router::router::PersonHogRouter;
use personhog_router::service::PersonHogRouterService;
use tokio::net::TcpListener;
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
    let backend = ReplicaBackend::new(&replica_url, Duration::from_secs(5)).unwrap();
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
        is_user_id: false,
    }
}
