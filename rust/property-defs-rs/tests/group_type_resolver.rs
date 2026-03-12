use std::net::SocketAddr;

use personhog_proto::personhog::{
    service::v1::person_hog_service_server::{PersonHogService, PersonHogServiceServer},
    types::v1::*,
};
use sqlx::PgPool;
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
}

impl MockPersonHogService {
    fn with_mappings(mappings_by_team: Vec<GroupTypeMappingsByKey>) -> Self {
        Self {
            mappings_by_team,
            fail: false,
        }
    }

    fn failing() -> Self {
        Self {
            mappings_by_team: vec![],
            fail: true,
        }
    }
}

#[tonic::async_trait]
impl PersonHogService for MockPersonHogService {
    async fn get_group_type_mappings_by_team_ids(
        &self,
        _req: Request<GetGroupTypeMappingsByTeamIdsRequest>,
    ) -> Result<Response<GroupTypeMappingsBatchResponse>, Status> {
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

fn make_config(addr: &str, rollout: u32) -> property_defs_rs::config::Config {
    // Set env vars exactly once to avoid data races across concurrent #[sqlx::test] cases.
    static INIT_ENV: std::sync::Once = std::sync::Once::new();
    INIT_ENV.call_once(|| {
        std::env::set_var("KAFKA__BOOTSTRAP_SERVERS", "localhost:9092");
        std::env::set_var("KAFKA__TOPIC", "test_topic");
    });
    let mut config = property_defs_rs::config::Config::init_with_defaults().unwrap();
    config.personhog_addr = addr.to_string();
    config.personhog_rollout_percentage = rollout;
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

async fn seed_group_mapping(
    db: &PgPool,
    id: i32,
    group_type: &str,
    group_type_index: i32,
    team_id: i32,
    project_id: i32,
) {
    sqlx::query(
        "INSERT INTO posthog_grouptypemapping (id, group_type, group_type_index, team_id, project_id)
            VALUES($1, $2, $3, $4, $5)",
    )
    .bind(id)
    .bind(group_type)
    .bind(group_type_index)
    .bind(team_id)
    .bind(project_id)
    .execute(db)
    .await
    .unwrap();
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

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_personhog_resolves_group_types(db: PgPool) {
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
    let config = make_config(&format!("http://{addr}"), 100);
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![
        make_group_update(1, "organization"),
        make_group_update(1, "company"),
    ];

    resolver.resolve(&mut updates, &db, None).await.unwrap();

    assert_eq!(get_resolved_index(&updates[0]), Some(0));
    assert_eq!(get_resolved_index(&updates[1]), Some(1));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_personhog_resolves_multiple_teams(db: PgPool) {
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
    let config = make_config(&format!("http://{addr}"), 100);
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![
        make_group_update(10, "workspace"),
        make_group_update(20, "workspace"),
    ];

    resolver.resolve(&mut updates, &db, None).await.unwrap();

    assert_eq!(get_resolved_index(&updates[0]), Some(0));
    assert_eq!(get_resolved_index(&updates[1]), Some(2));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_personhog_unresolved_group_type_cleared(db: PgPool) {
    let mock = MockPersonHogService::with_mappings(vec![GroupTypeMappingsByKey {
        key: 1,
        mappings: vec![],
    }]);

    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"), 100);
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![make_group_update(1, "nonexistent")];

    resolver.resolve(&mut updates, &db, None).await.unwrap();

    match &updates[0] {
        Update::Property(p) => assert!(p.group_type_index.is_none()),
        _ => panic!("expected Property update"),
    }
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_personhog_failure_falls_back_to_db(db: PgPool) {
    // Seed the DB with a mapping so the fallback path can resolve it
    seed_group_mapping(&db, 1, "organization", 0, 1, 1).await;

    let mock = MockPersonHogService::failing();
    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"), 100);
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![make_group_update(1, "organization")];

    resolver.resolve(&mut updates, &db, None).await.unwrap();

    assert_eq!(get_resolved_index(&updates[0]), Some(0));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_personhog_caches_resolved_types(db: PgPool) {
    let mock = MockPersonHogService::with_mappings(vec![GroupTypeMappingsByKey {
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
    }]);

    let addr = start_mock_server(mock).await;
    let config = make_config(&format!("http://{addr}"), 100);
    let resolver = GroupTypeResolver::new(&config);

    // First call populates the cache
    let mut updates = vec![make_group_update(1, "organization")];
    resolver.resolve(&mut updates, &db, None).await.unwrap();
    assert_eq!(get_resolved_index(&updates[0]), Some(3));

    // Second call should resolve from cache even though the server is the same.
    // We verify by checking that a fresh unresolved update also gets index 3.
    let mut updates2 = vec![make_group_update(1, "organization")];
    resolver.resolve(&mut updates2, &db, None).await.unwrap();
    assert_eq!(get_resolved_index(&updates2[0]), Some(3));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_no_personhog_client_uses_db(db: PgPool) {
    seed_group_mapping(&db, 1, "organization", 5, 1, 1).await;

    // Empty addr = no personhog client created
    let config = make_config("", 100);
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![make_group_update(1, "organization")];
    resolver.resolve(&mut updates, &db, None).await.unwrap();

    assert_eq!(get_resolved_index(&updates[0]), Some(5));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_zero_rollout_uses_db(db: PgPool) {
    seed_group_mapping(&db, 1, "organization", 7, 1, 1).await;

    // Rollout 0 = always DB, even with a valid personhog addr.
    // We point at a non-existent server; if personhog were called it would fail.
    let config = make_config("http://127.0.0.1:1", 0);
    let resolver = GroupTypeResolver::new(&config);

    let mut updates = vec![make_group_update(1, "organization")];
    resolver.resolve(&mut updates, &db, None).await.unwrap();

    assert_eq!(get_resolved_index(&updates[0]), Some(7));
}
