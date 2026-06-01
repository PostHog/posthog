use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use personhog_proto::personhog::{
    service::v1::person_hog_service_server::{PersonHogService, PersonHogServiceServer},
    types::v1::*,
};
use tokio::net::TcpListener;
use tonic::{Request, Response, Status};

use property_defs_rs::{
    group_type_resolver::GroupTypeResolver,
    types::{GroupType, PropertyParentType, Update},
};

// -- mock server --------------------------------------------------------

struct MockPersonHogService {
    mappings_by_team: Vec<GroupTypeMappingsByKey>,
    fail: bool,
    call_count: Arc<AtomicUsize>,
}

impl MockPersonHogService {
    fn with_mappings(mappings_by_team: Vec<GroupTypeMappingsByKey>) -> Self {
        Self {
            mappings_by_team,
            fail: false,
            call_count: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn with_mappings_counted(
        mappings_by_team: Vec<GroupTypeMappingsByKey>,
        call_count: Arc<AtomicUsize>,
    ) -> Self {
        Self {
            mappings_by_team,
            fail: false,
            call_count,
        }
    }

    fn failing() -> Self {
        Self {
            mappings_by_team: vec![],
            fail: true,
            call_count: Arc::new(AtomicUsize::new(0)),
        }
    }
}

#[tonic::async_trait]
impl PersonHogService for MockPersonHogService {
    async fn get_group_type_mappings_by_team_ids(
        &self,
        _req: Request<GetGroupTypeMappingsByTeamIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        self.call_count.fetch_add(1, Ordering::SeqCst);
        if self.fail {
            return Err(Status::internal("mock failure"));
        }
        Ok(Response::new(GroupTypeMappingsBatchResponse {
            results: self.mappings_by_team.clone(),
        }))
    }

    // -- stubs for the rest of the trait (never called) ------------------

    async fn get_person(
        &self,
        _: Request<GetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_persons(
        &self,
        _: Request<GetPersonsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_person_by_uuid(
        &self,
        _: Request<GetPersonByUuidRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_persons_by_uuids(
        &self,
        _: Request<GetPersonsByUuidsRequest>,
    ) -> Result<Response<PersonsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_person_by_distinct_id(
        &self,
        _: Request<GetPersonByDistinctIdRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_persons_by_distinct_ids_in_team(
        &self,
        _: Request<GetPersonsByDistinctIdsInTeamRequest>,
    ) -> Result<Response<PersonsByDistinctIdsInTeamResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_persons_by_distinct_ids(
        &self,
        _: Request<GetPersonsByDistinctIdsRequest>,
    ) -> Result<Response<PersonsByDistinctIdsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_distinct_ids_for_person(
        &self,
        _: Request<GetDistinctIdsForPersonRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_distinct_ids_for_persons(
        &self,
        _: Request<GetDistinctIdsForPersonsRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_hash_key_override_context(
        &self,
        _: Request<GetHashKeyOverrideContextRequest>,
    ) -> Result<Response<GetHashKeyOverrideContextResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn upsert_hash_key_overrides(
        &self,
        _: Request<UpsertHashKeyOverridesRequest>,
    ) -> Result<Response<UpsertHashKeyOverridesResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn delete_hash_key_overrides_by_teams(
        &self,
        _: Request<DeleteHashKeyOverridesByTeamsRequest>,
    ) -> Result<Response<DeleteHashKeyOverridesByTeamsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn check_cohort_membership(
        &self,
        _: Request<CheckCohortMembershipRequest>,
    ) -> Result<Response<CohortMembershipResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn count_cohort_members(
        &self,
        _: Request<CountCohortMembersRequest>,
    ) -> Result<Response<CountCohortMembersResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn delete_cohort_member(
        &self,
        _: Request<DeleteCohortMemberRequest>,
    ) -> Result<Response<DeleteCohortMemberResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn delete_cohort_members_bulk(
        &self,
        _: Request<DeleteCohortMembersBulkRequest>,
    ) -> Result<Response<DeleteCohortMembersBulkResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn insert_cohort_members(
        &self,
        _: Request<InsertCohortMembersRequest>,
    ) -> Result<Response<InsertCohortMembersResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn list_cohort_member_ids(
        &self,
        _: Request<ListCohortMemberIdsRequest>,
    ) -> Result<Response<ListCohortMemberIdsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_group(
        &self,
        _: Request<GetGroupRequest>,
    ) -> Result<Response<GetGroupResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_groups(
        &self,
        _: Request<GetGroupsRequest>,
    ) -> Result<Response<GroupsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_groups_batch(
        &self,
        _: Request<GetGroupsBatchRequest>,
    ) -> Result<Response<GetGroupsBatchResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_group_type_mappings_by_team_id(
        &self,
        _: Request<GetGroupTypeMappingsByTeamIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_group_type_mappings_by_project_id(
        &self,
        _: Request<GetGroupTypeMappingsByProjectIdRequest>,
    ) -> Result<Response<GroupTypeMappingsResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_group_type_mappings_by_project_ids(
        &self,
        _: Request<GetGroupTypeMappingsByProjectIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn update_person_properties(
        &self,
        _: Request<UpdatePersonPropertiesRequest>,
    ) -> Result<Response<UpdatePersonPropertiesResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn delete_persons(
        &self,
        _: Request<DeletePersonsRequest>,
    ) -> Result<Response<DeletePersonsResponse>, Status> {
        Err(Status::unimplemented(""))
    }

    async fn delete_persons_batch_for_team(
        &self,
        _: Request<DeletePersonsBatchForTeamRequest>,
    ) -> Result<Response<DeletePersonsBatchForTeamResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        _: Request<GetGroupTypeMappingByDashboardIdRequest>,
    ) -> Result<Response<GetGroupTypeMappingByDashboardIdResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn create_group(
        &self,
        _: Request<CreateGroupRequest>,
    ) -> Result<Response<CreateGroupResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn update_group(
        &self,
        _: Request<UpdateGroupRequest>,
    ) -> Result<Response<UpdateGroupResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn delete_groups_batch_for_team(
        &self,
        _: Request<DeleteGroupsBatchForTeamRequest>,
    ) -> Result<Response<DeleteGroupsBatchForTeamResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn update_group_type_mapping(
        &self,
        _: Request<UpdateGroupTypeMappingRequest>,
    ) -> Result<Response<UpdateGroupTypeMappingResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn delete_group_type_mapping(
        &self,
        _: Request<DeleteGroupTypeMappingRequest>,
    ) -> Result<Response<DeleteGroupTypeMappingResponse>, Status> {
        Err(Status::unimplemented(""))
    }
    async fn delete_group_type_mappings_batch_for_team(
        &self,
        _: Request<DeleteGroupTypeMappingsBatchForTeamRequest>,
    ) -> Result<Response<DeleteGroupTypeMappingsBatchForTeamResponse>, Status> {
        Err(Status::unimplemented(""))
    }
}

// -- helpers ------------------------------------------------------------

async fn start_mock_server(service: MockPersonHogService) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        tonic::transport::Server::builder()
            .add_service(PersonHogServiceServer::new(service))
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });
    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    addr
}

fn make_config(addr: &str) -> property_defs_rs::config::Config {
    // Set env vars exactly once to avoid data races across concurrent test cases.
    static INIT_ENV: std::sync::Once = std::sync::Once::new();
    INIT_ENV.call_once(|| {
        std::env::set_var("KAFKA__BOOTSTRAP_SERVERS", "localhost:9092");
        std::env::set_var("KAFKA__TOPIC", "test_topic");
    });
    let mut config = property_defs_rs::config::Config::init_with_defaults().unwrap();
    config.personhog_addr = addr.to_string();
    config.personhog_timeout_ms = 5000;
    config.skip_writes = true;
    config.skip_reads = false;
    config
}

fn make_group_update(team_id: i32, group_name: &str) -> Update {
    Update::Property(property_defs_rs::types::PropertyDefinition {
        team_id,
        project_id: team_id as i64,
        name: format!("prop_{group_name}"),
        is_numerical: false,
        property_type: None,
        event_type: PropertyParentType::Group,
        group_type_index: Some(GroupType::Unresolved(group_name.to_string())),
        property_type_format: None,
        volume_30_day: None,
        query_usage_30_day: None,
    })
}

fn get_resolved_index(update: &Update) -> Option<i32> {
    match update {
        Update::Property(p) => match &p.group_type_index {
            Some(GroupType::Resolved(_, idx)) => Some(*idx),
            _ => None,
        },
        _ => None,
    }
}

// -- tests --------------------------------------------------------------

#[tokio::test]
async fn test_personhog_resolves_group_types() {
    let mock = MockPersonHogService::with_mappings(vec![GroupTypeMappingsByKey {
        key: 1,
        mappings: vec![
            GroupTypeMapping {
                id: 1,
                team_id: 1,
                project_id: 1,
                group_type: "organization".to_string(),
                group_type_index: 0,
                name_singular: None,
                name_plural: None,
                default_columns: None,
                detail_dashboard_id: None,
                created_at: None,
            },
            GroupTypeMapping {
                id: 2,
                team_id: 1,
                project_id: 1,
                group_type: "company".to_string(),
                group_type_index: 1,
                name_singular: None,
                name_plural: None,
                default_columns: None,
                detail_dashboard_id: None,
                created_at: None,
            },
        ],
    }]);

    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"));
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![
        make_group_update(1, "organization"),
        make_group_update(1, "company"),
    ];

    resolver.resolve(&mut updates).await.unwrap();

    assert_eq!(get_resolved_index(&updates[0]), Some(0));
    assert_eq!(get_resolved_index(&updates[1]), Some(1));
}

#[tokio::test]
async fn test_personhog_resolves_multiple_teams() {
    let mock = MockPersonHogService::with_mappings(vec![
        GroupTypeMappingsByKey {
            key: 10,
            mappings: vec![GroupTypeMapping {
                id: 1,
                team_id: 10,
                project_id: 10,
                group_type: "workspace".to_string(),
                group_type_index: 0,
                name_singular: None,
                name_plural: None,
                default_columns: None,
                detail_dashboard_id: None,
                created_at: None,
            }],
        },
        GroupTypeMappingsByKey {
            key: 20,
            mappings: vec![GroupTypeMapping {
                id: 2,
                team_id: 20,
                project_id: 20,
                group_type: "workspace".to_string(),
                group_type_index: 2,
                name_singular: None,
                name_plural: None,
                default_columns: None,
                detail_dashboard_id: None,
                created_at: None,
            }],
        },
    ]);

    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"));
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![
        make_group_update(10, "workspace"),
        make_group_update(20, "workspace"),
    ];

    resolver.resolve(&mut updates).await.unwrap();

    assert_eq!(get_resolved_index(&updates[0]), Some(0));
    assert_eq!(get_resolved_index(&updates[1]), Some(2));
}

#[tokio::test]
async fn test_personhog_unresolved_group_type_cleared() {
    let mock = MockPersonHogService::with_mappings(vec![GroupTypeMappingsByKey {
        key: 1,
        mappings: vec![],
    }]);

    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"));
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![make_group_update(1, "nonexistent")];

    resolver.resolve(&mut updates).await.unwrap();

    match &updates[0] {
        Update::Property(p) => assert!(p.group_type_index.is_none()),
        _ => panic!("expected Property update"),
    }
}

#[tokio::test]
async fn test_personhog_failure_returns_error() {
    let mock = MockPersonHogService::failing();
    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"));
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![make_group_update(1, "organization")];

    let result = resolver.resolve(&mut updates).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_personhog_caches_resolved_types() {
    let call_count = Arc::new(AtomicUsize::new(0));
    let mock = MockPersonHogService::with_mappings_counted(
        vec![GroupTypeMappingsByKey {
            key: 1,
            mappings: vec![GroupTypeMapping {
                id: 1,
                team_id: 1,
                project_id: 1,
                group_type: "organization".to_string(),
                group_type_index: 3,
                name_singular: None,
                name_plural: None,
                default_columns: None,
                detail_dashboard_id: None,
                created_at: None,
            }],
        }],
        call_count.clone(),
    );

    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"));
    let resolver = GroupTypeResolver::new(&config);

    // First call populates the cache
    let mut updates = vec![make_group_update(1, "organization")];
    resolver.resolve(&mut updates).await.unwrap();
    assert_eq!(get_resolved_index(&updates[0]), Some(3));
    assert_eq!(call_count.load(Ordering::SeqCst), 1);

    // Second call should resolve from cache — server must not be contacted again
    let mut updates2 = vec![make_group_update(1, "organization")];
    resolver.resolve(&mut updates2).await.unwrap();
    assert_eq!(get_resolved_index(&updates2[0]), Some(3));
    assert_eq!(call_count.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn test_no_personhog_client_returns_error() {
    // Empty addr = no personhog client created
    let config = make_config("");
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![make_group_update(1, "organization")];
    let result = resolver.resolve(&mut updates).await;

    assert!(result.is_err());
}
