use std::sync::Arc;

use chrono::Duration;
use cyclotron_core::{manager::QueueManager, worker::Worker};
use cyclotron_fetch::fetch::{tick, FetchResult, HttpMethod};
use httpmock::{Method, MockServer};
use sqlx::PgPool;
use utils::{
    construct_job, construct_params, get_app_test_context, make_immediately_available,
    wait_on_no_running, wait_on_return,
};

mod utils;

#[sqlx::test(migrations = "../cyclotron-core/migrations")]
pub async fn test_completes_fetch(db: PgPool) {
    let context = Arc::new(get_app_test_context(db.clone()).await);
    let producer = QueueManager::from_pool(db.clone());
    let return_worker = Worker::from_pool(db.clone());
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(Method::GET).path("/test");
        then.status(200).body("Hello, world!");
    });

    let params = construct_params(server.url("/test"), HttpMethod::Get);
    let job = construct_job(params);
    producer.create_job(job).await.unwrap();

    let started = tick(context).await.unwrap();

    assert_eq!(started, 1);

    let returned = wait_on_return(&return_worker, 1).await.unwrap();

    let response: FetchResult =
        serde_json::from_str(returned[0].parameters.as_ref().unwrap()).unwrap();

    let FetchResult::Success { response } = response else {
        panic!("Expected success response");
    };

    assert_eq!(response.status, 200);
    assert_eq!(response.body, "Hello, world!");

    mock.assert_hits(1);
}

#[sqlx::test(migrations = "../cyclotron-core/migrations")]
pub async fn test_returns_failure_after_retries(db: PgPool) {
    let context = Arc::new(get_app_test_context(db.clone()).await);
    let producer = QueueManager::from_pool(db.clone());
    let return_worker = Worker::from_pool(db.clone());
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(Method::GET).path("/test");
        then.status(500).body("test server error body");
    });

    let mut params = construct_params(server.url("/test"), HttpMethod::Get);
    params.max_tries = Some(2);

    let job = construct_job(params);
    producer.create_job(job).await.unwrap();

    // Tick twice for retry
    let started = tick(context.clone()).await.unwrap();
    assert_eq!(started, 1);
    wait_on_no_running(&db, Duration::milliseconds(100)).await;
    make_immediately_available(&db).await;
    let started = tick(context.clone()).await.unwrap();
    assert_eq!(started, 1);
    wait_on_no_running(&db, Duration::milliseconds(100)).await;

    let returned = wait_on_return(&return_worker, 1).await.unwrap();

    let response: FetchResult =
        serde_json::from_str(returned[0].parameters.as_ref().unwrap()).unwrap();

    let FetchResult::Failure { trace } = response else {
        panic!("Expected failure response");
    };

    assert!(trace.len() == 2);
    for attempt in trace {
        assert_eq!(attempt.status, Some(500));
        assert_eq!(attempt.body, Some("test server error body".to_string()));
    }

    mock.assert_hits(2);
}
