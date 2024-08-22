use std::sync::Arc;

use chrono::{Duration, Utc};

use cyclotron_core::{Job, JobInit, QueueError, Worker};
use cyclotron_fetch::{
    config::AppConfig,
    context::AppContext,
    fetch::{FetchParameters, HttpMethod},
};
use sqlx::PgPool;
use tokio::sync::Semaphore;

const FETCH_QUEUE: &str = "fetch";
const RETURN_QUEUE: &str = "return";

pub async fn get_app_test_context(db: PgPool) -> AppContext {
    let worker = Worker::from_pool(db.clone());
    let client = reqwest::Client::new();
    let concurrency_limit = Arc::new(Semaphore::new(1));
    let health = health::HealthRegistry::new("test");
    let liveness = health
        .register("test".to_string(), Duration::seconds(30).to_std().unwrap())
        .await;

    let config = AppConfig {
        fetch_timeout: Duration::seconds(10),
        concurrent_requests_limit: 1,
        host: "localhost".to_string(),
        port: 16,
        worker_id: "test".to_string(),
        job_poll_interval: Duration::seconds(10),
        max_retry_attempts: 3,
        queue_served: FETCH_QUEUE.to_string(),
        batch_size: 1000,
        max_response_bytes: 1024 * 1024,
        retry_backoff_base: Duration::milliseconds(1000),
        allow_internal_ips: true,
    };

    AppContext {
        worker,
        client,
        concurrency_limit,
        liveness,
        config,
        metric_labels: Default::default(),
    }
}

pub fn construct_params(url: String, method: HttpMethod) -> FetchParameters {
    FetchParameters {
        url,
        method,
        return_queue: RETURN_QUEUE.to_string(),
        headers: None,
        body: None,
        max_tries: None,
        on_finish: None,
    }
}

pub fn construct_job(parameters: FetchParameters) -> JobInit {
    JobInit {
        team_id: 1,
        queue_name: FETCH_QUEUE.to_string(),
        priority: 0,
        scheduled: Utc::now() - Duration::seconds(1),
        function_id: None,
        vm_state: None,
        parameters: Some(serde_json::to_string(&parameters).unwrap()),
        metadata: None,
    }
}

pub async fn wait_on_return(
    worker: &Worker,
    count: usize,
    with_vm: bool,
) -> Result<Vec<Job>, QueueError> {
    let timeout = Duration::seconds(1);
    let start = Utc::now();
    let mut returned = vec![];
    while start + timeout > Utc::now() {
        let mut jobs = if with_vm {
            worker.dequeue_with_vm_state(RETURN_QUEUE, 1).await?
        } else {
            worker.dequeue_jobs(RETURN_QUEUE, 1).await?
        };
        returned.append(&mut jobs);
        if returned.len() == count {
            return Ok(returned);
        }
        if returned.len() > count {
            panic!("Too many jobs returned");
        }
    }
    panic!("Timeout waiting for jobs to return");
}

pub async fn wait_on_no_running(pool: &PgPool, max_time: Duration) {
    let start = Utc::now();
    loop {
        let running: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM cyclotron_jobs WHERE state = 'running'")
                .fetch_one(pool)
                .await
                .unwrap();
        if running == 0 {
            return;
        }
        if Utc::now() - start > max_time {
            panic!("Timeout waiting for jobs to finish");
        }
    }
}

pub async fn make_immediately_available(pool: &PgPool) {
    sqlx::query(
        "UPDATE cyclotron_jobs SET scheduled = NOW() - INTERVAL '1 second' WHERE state = 'available'",
    )
    .execute(pool)
    .await
    .unwrap();
}
