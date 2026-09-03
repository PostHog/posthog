mod common;

use std::sync::Arc;
use std::time::Duration;

use common::sim_leader::SimLeader;
use sqlx::postgres::PgPoolOptions;
use tonic::{Code, Request};

use personhog_identity::config::IdentityTables;
use personhog_identity::lifecycle::engine::{Engine, EngineConfig};
use personhog_identity::lifecycle::validation::MAX_DELETE_BATCH_SIZE;
use personhog_identity::lifecycle::PersonHogLifecycleService;
use personhog_proto::personhog::lifecycle::v1::person_hog_lifecycle_server::PersonHogLifecycle;
use personhog_proto::personhog::lifecycle::v1::DeletePersonsRequest;

fn valid_request() -> DeletePersonsRequest {
    DeletePersonsRequest {
        team_id: 1,
        person_ids: vec![42],
        op_id: "018f6f60-8c5a-7000-8000-000000000000".to_string(),
    }
}

/// Validation rejects before the engine touches storage, so a lazy pool that
/// never connects is enough to construct the service.
async fn delete_status(request: DeletePersonsRequest) -> Code {
    let pool = PgPoolOptions::new()
        .connect_lazy("postgres://unused:unused@localhost:1/unused")
        .expect("lazy pool never connects");
    let engine = Arc::new(Engine::new(
        pool.clone(),
        EngineConfig {
            lease: Duration::from_secs(1),
            execute_timeout: Duration::from_secs(1),
            poll_interval: Duration::from_millis(10),
            attempt_alert_threshold: 5,
        },
    ));
    let tables = IdentityTables::real();
    let service = PersonHogLifecycleService::new(
        engine,
        Arc::new(SimLeader::new(pool, tables.person.clone())),
        tables,
    );
    service
        .delete_persons(Request::new(request))
        .await
        .expect_err("invalid requests are rejected")
        .code()
}

#[tokio::test]
async fn invalid_requests_are_rejected_before_the_saga() {
    let cases: Vec<(&str, DeletePersonsRequest)> = vec![
        (
            "zero team_id",
            DeletePersonsRequest {
                team_id: 0,
                ..valid_request()
            },
        ),
        (
            "team_id above i32 wraps in int4 storage",
            DeletePersonsRequest {
                team_id: i64::from(i32::MAX) + 1,
                ..valid_request()
            },
        ),
        (
            "empty person_ids",
            DeletePersonsRequest {
                person_ids: vec![],
                ..valid_request()
            },
        ),
        (
            "batch above cap",
            DeletePersonsRequest {
                person_ids: (1..=(MAX_DELETE_BATCH_SIZE as i64 + 1)).collect(),
                ..valid_request()
            },
        ),
        (
            "non-positive person id",
            DeletePersonsRequest {
                person_ids: vec![42, 0],
                ..valid_request()
            },
        ),
        (
            "op_id not a uuid",
            DeletePersonsRequest {
                op_id: "not-a-uuid".to_string(),
                ..valid_request()
            },
        ),
    ];

    for (name, request) in cases {
        assert_eq!(
            delete_status(request).await,
            Code::InvalidArgument,
            "case: {name}"
        );
    }
}
