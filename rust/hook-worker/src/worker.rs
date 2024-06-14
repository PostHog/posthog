use std::collections;
use std::sync::Arc;
use std::time;

use chrono::Utc;
use futures::future::join_all;
use health::HealthHandle;
use hook_common::pgqueue::PgTransactionBatch;
use hook_common::{
    pgqueue::{Job, PgQueue, PgQueueJob, PgTransactionJob, RetryError, RetryInvalidError},
    retry::RetryPolicy,
    webhook::{HttpMethod, WebhookJobError, WebhookJobMetadata, WebhookJobParameters},
};
use http::StatusCode;
use reqwest::{header, Client};
use tokio::sync;
use tracing::error;

use crate::dns::{NoPublicIPv4Error, PublicIPv4Resolver};
use crate::error::{
    is_error_source, WebhookError, WebhookParseError, WebhookRequestError, WorkerError,
};
use crate::util::first_n_bytes_of_response;

/// A WebhookJob is any `PgQueueJob` with `WebhookJobParameters` and `WebhookJobMetadata`.
trait WebhookJob: PgQueueJob + std::marker::Send {
    fn parameters(&self) -> &WebhookJobParameters;
    fn metadata(&self) -> &WebhookJobMetadata;
    fn job(&self) -> &Job<WebhookJobParameters, WebhookJobMetadata>;

    fn attempt(&self) -> i32 {
        self.job().attempt
    }

    fn queue(&self) -> String {
        self.job().queue.to_owned()
    }

    fn target(&self) -> String {
        self.job().target.to_owned()
    }
}

impl WebhookJob for PgTransactionJob<'_, WebhookJobParameters, WebhookJobMetadata> {
    fn parameters(&self) -> &WebhookJobParameters {
        &self.job.parameters
    }

    fn metadata(&self) -> &WebhookJobMetadata {
        &self.job.metadata
    }

    fn job(&self) -> &Job<WebhookJobParameters, WebhookJobMetadata> {
        &self.job
    }
}

/// A worker to poll `PgQueue` and spawn tasks to process webhooks when a job becomes available.
pub struct WebhookWorker<'p> {
    /// An identifier for this worker. Used to mark jobs we have consumed.
    name: String,
    /// The queue we will be dequeuing jobs from.
    queue: &'p PgQueue,
    /// The maximum number of jobs to dequeue in one query.
    dequeue_batch_size: u32,
    /// The interval for polling the queue.
    poll_interval: time::Duration,
    /// The client used for HTTP requests.
    client: reqwest::Client,
    /// Maximum number of concurrent jobs being processed.
    max_concurrent_jobs: usize,
    /// The retry policy used to calculate retry intervals when a job fails with a retryable error.
    retry_policy: RetryPolicy,
    /// The liveness check handle, to call on a schedule to report healthy
    liveness: HealthHandle,
}

pub fn build_http_client(
    request_timeout: time::Duration,
    allow_internal_ips: bool,
) -> reqwest::Result<Client> {
    let mut headers = header::HeaderMap::new();
    headers.insert(
        header::CONTENT_TYPE,
        header::HeaderValue::from_static("application/json"),
    );
    let mut client_builder = reqwest::Client::builder()
        .default_headers(headers)
        .user_agent("PostHog Webhook Worker")
        .timeout(request_timeout);
    if !allow_internal_ips {
        client_builder = client_builder.dns_resolver(Arc::new(PublicIPv4Resolver {}))
    }
    client_builder.build()
}

impl<'p> WebhookWorker<'p> {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        name: &str,
        queue: &'p PgQueue,
        dequeue_batch_size: u32,
        poll_interval: time::Duration,
        request_timeout: time::Duration,
        max_concurrent_jobs: usize,
        retry_policy: RetryPolicy,
        allow_internal_ips: bool,
        liveness: HealthHandle,
    ) -> Self {
        let client = build_http_client(request_timeout, allow_internal_ips)
            .expect("failed to construct reqwest client for webhook worker");

        Self {
            name: name.to_owned(),
            queue,
            dequeue_batch_size,
            poll_interval,
            client,
            max_concurrent_jobs,
            retry_policy,
            liveness,
        }
    }

    /// Wait until at least one job becomes available in our queue in transactional mode.
    async fn wait_for_jobs_tx<'a>(
        &self,
    ) -> PgTransactionBatch<'a, WebhookJobParameters, WebhookJobMetadata> {
        let mut interval = tokio::time::interval(self.poll_interval);

        loop {
            interval.tick().await;
            self.liveness.report_healthy().await;

            match self
                .queue
                .dequeue_tx(&self.name, self.dequeue_batch_size)
                .await
            {
                Ok(Some(batch)) => return batch,
                Ok(None) => continue,
                Err(error) => {
                    error!("error while trying to dequeue_tx job: {}", error);
                    continue;
                }
            }
        }
    }

    /// Run this worker to continuously process any jobs that become available.
    pub async fn run(&self) {
        let semaphore = Arc::new(sync::Semaphore::new(self.max_concurrent_jobs));
        let report_semaphore_utilization = || {
            metrics::gauge!("webhook_worker_saturation_percent")
                .set(1f64 - semaphore.available_permits() as f64 / self.max_concurrent_jobs as f64);
        };

        let dequeue_batch_size_histogram = metrics::histogram!("webhook_dequeue_batch_size");

        loop {
            report_semaphore_utilization();
            // TODO: We could grab semaphore permits here using something like:
            //   `min(semaphore.available_permits(), dequeue_batch_size)`
            // And then dequeue only up to that many jobs. We'd then need to hand back the
            // difference in permits based on how many jobs were dequeued.
            let mut batch = self.wait_for_jobs_tx().await;
            dequeue_batch_size_histogram.record(batch.jobs.len() as f64);

            // Get enough permits for the jobs before spawning a task.
            let permits = semaphore
                .clone()
                .acquire_many_owned(batch.jobs.len() as u32)
                .await
                .expect("semaphore has been closed");

            let client = self.client.clone();
            let retry_policy = self.retry_policy.clone();

            tokio::spawn(async move {
                let mut futures = Vec::new();

                // We have to `take` the Vec of jobs from the batch to avoid a borrow checker
                // error below when we commit.
                for job in std::mem::take(&mut batch.jobs) {
                    let client = client.clone();
                    let retry_policy = retry_policy.clone();

                    let future =
                        async move { process_webhook_job(client, job, &retry_policy).await };

                    futures.push(future);
                }

                let results = join_all(futures).await;
                for result in results {
                    if let Err(e) = result {
                        error!("error processing webhook job: {}", e);
                    }
                }

                let _ = batch.commit().await.map_err(|e| {
                    error!("error committing transactional batch: {}", e);
                });

                drop(permits);
            });
        }
    }
}

/// Process a webhook job by transitioning it to its appropriate state after its request is sent.
/// After we finish, the webhook job will be set as completed (if the request was successful), retryable (if the request
/// was unsuccessful but we can still attempt a retry), or failed (if the request was unsuccessful and no more retries
/// may be attempted).
///
/// A webhook job is considered retryable after a failing request if:
/// 1. The job has attempts remaining (i.e. hasn't reached `max_attempts`), and...
/// 2. The status code indicates retrying at a later point could resolve the issue. This means: 429 and any 5XX.
///
/// # Arguments
///
/// * `client`: An HTTP client to execute the webhook job request.
/// * `webhook_job`: The webhook job to process as dequeued from `hook_common::pgqueue::PgQueue`.
/// * `retry_policy`: The retry policy used to set retry parameters if a job fails and has remaining attempts.
async fn process_webhook_job<W: WebhookJob>(
    client: reqwest::Client,
    webhook_job: W,
    retry_policy: &RetryPolicy,
) -> Result<(), WorkerError> {
    let parameters = webhook_job.parameters();

    let labels = [("queue", webhook_job.queue())];
    metrics::counter!("webhook_jobs_total", &labels).increment(1);

    let now = tokio::time::Instant::now();

    let send_result = send_webhook(
        client,
        &parameters.method,
        &parameters.url,
        &parameters.headers,
        parameters.body.clone(),
    )
    .await;

    let elapsed = now.elapsed().as_secs_f64();

    match send_result {
        Ok(_) => {
            let created_at = webhook_job.job().created_at;
            let retries = webhook_job.job().attempt - 1;
            let labels_with_retries = [
                ("queue", webhook_job.queue()),
                ("retries", retries.to_string()),
            ];

            webhook_job.complete().await.map_err(|error| {
                metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                error
            })?;

            let insert_to_complete_duration = Utc::now() - created_at;
            metrics::histogram!(
                "webhook_jobs_insert_to_complete_duration_seconds",
                &labels_with_retries
            )
            .record((insert_to_complete_duration.num_milliseconds() as f64) / 1_000_f64);
            metrics::counter!("webhook_jobs_completed", &labels).increment(1);
            metrics::histogram!("webhook_jobs_processing_duration_seconds", &labels)
                .record(elapsed);

            Ok(())
        }
        Err(WebhookError::Parse(WebhookParseError::ParseHeadersError(e))) => {
            webhook_job
                .fail(WebhookJobError::new_parse(&e.to_string()))
                .await
                .map_err(|job_error| {
                    metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                    job_error
                })?;

            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

            Ok(())
        }
        Err(WebhookError::Parse(WebhookParseError::ParseHttpMethodError(e))) => {
            webhook_job
                .fail(WebhookJobError::new_parse(&e))
                .await
                .map_err(|job_error| {
                    metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                    job_error
                })?;

            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

            Ok(())
        }
        Err(WebhookError::Parse(WebhookParseError::ParseUrlError(e))) => {
            webhook_job
                .fail(WebhookJobError::new_parse(&e.to_string()))
                .await
                .map_err(|job_error| {
                    metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                    job_error
                })?;

            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

            Ok(())
        }
        Err(WebhookError::Request(request_error)) => {
            let webhook_job_error = WebhookJobError::from(&request_error);

            match request_error {
                WebhookRequestError::RetryableRequestError {
                    error, retry_after, ..
                } => {
                    let retry_interval =
                        retry_policy.retry_interval(webhook_job.attempt() as u32, retry_after);
                    let current_queue = webhook_job.queue();
                    let retry_queue = retry_policy.retry_queue(&current_queue);

                    match webhook_job
                        .retry(webhook_job_error, retry_interval, retry_queue)
                        .await
                    {
                        Ok(_) => {
                            metrics::counter!("webhook_jobs_retried", &labels).increment(1);

                            Ok(())
                        }
                        Err(RetryError::RetryInvalidError(RetryInvalidError {
                            job: webhook_job,
                            ..
                        })) => {
                            webhook_job
                                .fail(WebhookJobError::from(&error))
                                .await
                                .map_err(|job_error| {
                                    metrics::counter!("webhook_jobs_database_error", &labels)
                                        .increment(1);
                                    job_error
                                })?;

                            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

                            Ok(())
                        }
                        Err(RetryError::DatabaseError(job_error)) => {
                            metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                            Err(WorkerError::from(job_error))
                        }
                    }
                }
                WebhookRequestError::NonRetryableRetryableRequestError { .. } => {
                    webhook_job
                        .fail(webhook_job_error)
                        .await
                        .map_err(|job_error| {
                            metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                            job_error
                        })?;

                    metrics::counter!("webhook_jobs_failed", &labels).increment(1);

                    Ok(())
                }
            }
        }
    }
}

/// Make an HTTP request to a webhook endpoint.
///
/// # Arguments
///
/// * `client`: An HTTP client to execute the HTTP request.
/// * `method`: The HTTP method to use in the HTTP request.
/// * `url`: The URL we are targetting with our request. Parsing this URL fail.
/// * `headers`: Key, value pairs of HTTP headers in a `std::collections::HashMap`. Can fail if headers are not valid.
/// * `body`: The body of the request. Ownership is required.
async fn send_webhook(
    client: reqwest::Client,
    method: &HttpMethod,
    url: &str,
    headers: &collections::HashMap<String, String>,
    body: String,
) -> Result<reqwest::Response, WebhookError> {
    let method: http::Method = method.into();
    let url: reqwest::Url = (url).parse().map_err(WebhookParseError::ParseUrlError)?;
    let headers: reqwest::header::HeaderMap = (headers)
        .try_into()
        .map_err(WebhookParseError::ParseHeadersError)?;
    let body = reqwest::Body::from(body);

    let response = client
        .request(method, url)
        .headers(headers)
        .body(body)
        .send()
        .await
        .map_err(|e| {
            if is_error_source::<NoPublicIPv4Error>(&e) {
                WebhookRequestError::NonRetryableRetryableRequestError {
                    error: e,
                    response: None,
                }
            } else {
                WebhookRequestError::RetryableRequestError {
                    error: e,
                    response: None,
                    retry_after: None,
                }
            }
        })?;

    let retry_after = parse_retry_after_header(response.headers());

    match response.error_for_status_ref() {
        Ok(_) => Ok(response),
        Err(err) => {
            if is_retryable_status(
                err.status()
                    .expect("status code is set as error is generated from a response"),
            ) {
                Err(WebhookError::Request(
                    WebhookRequestError::RetryableRequestError {
                        error: err,
                        // TODO: Make amount of bytes configurable.
                        response: first_n_bytes_of_response(response, 10 * 1024).await.ok(),
                        retry_after,
                    },
                ))
            } else {
                Err(WebhookError::Request(
                    WebhookRequestError::NonRetryableRetryableRequestError {
                        error: err,
                        response: first_n_bytes_of_response(response, 10 * 1024).await.ok(),
                    },
                ))
            }
        }
    }
}

fn is_retryable_status(status: StatusCode) -> bool {
    status == StatusCode::TOO_MANY_REQUESTS || status.is_server_error()
}

/// Attempt to parse a chrono::Duration from a Retry-After header, returning None if not possible.
/// Retry-After header can specify a date in RFC2822 or a number of seconds; we try to parse both.
/// If a Retry-After header is not present in the provided `header_map`, `None` is returned.
///
/// # Arguments
///
/// * `header_map`: A `&reqwest::HeaderMap` of response headers that could contain Retry-After.
fn parse_retry_after_header(header_map: &reqwest::header::HeaderMap) -> Option<time::Duration> {
    let retry_after_header = header_map.get(reqwest::header::RETRY_AFTER);

    let retry_after = match retry_after_header {
        Some(header_value) => match header_value.to_str() {
            Ok(s) => s,
            Err(_) => {
                return None;
            }
        },
        None => {
            return None;
        }
    };

    if let Ok(u) = retry_after.parse::<u64>() {
        let duration = time::Duration::from_secs(u);
        return Some(duration);
    }

    if let Ok(dt) = chrono::DateTime::parse_from_rfc2822(retry_after) {
        let duration =
            chrono::DateTime::<chrono::offset::Utc>::from(dt) - chrono::offset::Utc::now();

        // This can only fail when negative, in which case we return None.
        return duration.to_std().ok();
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    // Note we are ignoring some warnings in this module.
    // This is due to a long-standing cargo bug that reports imports and helper functions as unused.
    // See: https://github.com/rust-lang/rust/issues/46379.
    use health::HealthRegistry;
    use hook_common::pgqueue::{DatabaseError, NewJob};
    use sqlx::PgPool;

    /// Use process id as a worker id for tests.
    fn worker_id() -> String {
        std::process::id().to_string()
    }

    /// Get a request client or panic
    fn localhost_client() -> Client {
        build_http_client(Duration::from_secs(1), true).expect("failed to create client")
    }

    async fn enqueue_job(
        queue: &PgQueue,
        max_attempts: i32,
        job_parameters: WebhookJobParameters,
        job_metadata: WebhookJobMetadata,
    ) -> Result<(), DatabaseError> {
        let job_target = job_parameters.url.to_owned();
        let new_job = NewJob::new(max_attempts, job_metadata, job_parameters, &job_target);
        queue.enqueue(new_job).await?;
        Ok(())
    }

    #[test]
    fn test_is_retryable_status() {
        assert!(!is_retryable_status(http::StatusCode::FORBIDDEN));
        assert!(!is_retryable_status(http::StatusCode::BAD_REQUEST));
        assert!(is_retryable_status(http::StatusCode::TOO_MANY_REQUESTS));
        assert!(is_retryable_status(http::StatusCode::INTERNAL_SERVER_ERROR));
    }

    #[test]
    fn test_parse_retry_after_header() {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(reqwest::header::RETRY_AFTER, "120".parse().unwrap());

        let duration = parse_retry_after_header(&headers).unwrap();
        assert_eq!(duration, time::Duration::from_secs(120));

        headers.remove(reqwest::header::RETRY_AFTER);

        let duration = parse_retry_after_header(&headers);
        assert_eq!(duration, None);

        headers.insert(
            reqwest::header::RETRY_AFTER,
            "Wed, 21 Oct 2015 07:28:00 GMT".parse().unwrap(),
        );

        let duration = parse_retry_after_header(&headers);
        assert_eq!(duration, None);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn test_wait_for_job(db: PgPool) {
        let worker_id = worker_id();
        let queue_name = "test_wait_for_job".to_string();
        let queue = PgQueue::new_from_pool(&queue_name, db).await;

        let webhook_job_parameters = WebhookJobParameters {
            body: "a webhook job body. much wow.".to_owned(),
            headers: collections::HashMap::new(),
            method: HttpMethod::POST,
            url: "localhost".to_owned(),
        };
        let webhook_job_metadata = WebhookJobMetadata {
            team_id: 1,
            plugin_id: 2,
            plugin_config_id: 3,
        };
        let registry = HealthRegistry::new("liveness");
        let liveness = registry
            .register("worker".to_string(), ::time::Duration::seconds(30))
            .await;
        // enqueue takes ownership of the job enqueued to avoid bugs that can cause duplicate jobs.
        // Normally, a separate application would be enqueueing jobs for us to consume, so no ownership
        // conflicts would arise. However, in this test we need to do the enqueueing ourselves.
        // So, we clone the job to keep it around and assert the values returned by wait_for_job.
        enqueue_job(
            &queue,
            1,
            webhook_job_parameters.clone(),
            webhook_job_metadata,
        )
        .await
        .expect("failed to enqueue job");
        let worker = WebhookWorker::new(
            &worker_id,
            &queue,
            1,
            time::Duration::from_millis(100),
            time::Duration::from_millis(5000),
            10,
            RetryPolicy::default(),
            false,
            liveness,
        );

        let mut batch = worker.wait_for_jobs_tx().await;
        let consumed_job = batch.jobs.pop().unwrap();

        assert_eq!(consumed_job.job.attempt, 1);
        assert!(consumed_job.job.attempted_by.contains(&worker_id));
        assert_eq!(consumed_job.job.attempted_by.len(), 1);
        assert_eq!(consumed_job.job.max_attempts, 1);
        assert_eq!(
            *consumed_job.job.parameters.as_ref(),
            webhook_job_parameters
        );
        assert_eq!(consumed_job.job.target, webhook_job_parameters.url);

        consumed_job
            .complete()
            .await
            .expect("job not successfully completed");
        batch.commit().await.expect("failed to commit batch");

        assert!(registry.get_status().healthy)
    }

    #[tokio::test]
    async fn test_send_webhook() {
        let method = HttpMethod::POST;
        let url = "http://localhost:18081/echo";
        let headers = collections::HashMap::new();
        let body = "a very relevant request body";

        let response = send_webhook(localhost_client(), &method, url, &headers, body.to_owned())
            .await
            .expect("send_webhook failed");

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.text().await.expect("failed to read response body"),
            body.to_owned(),
        );
    }

    #[tokio::test]
    async fn test_error_message_contains_response_body() {
        let method = HttpMethod::POST;
        let url = "http://localhost:18081/fail";
        let headers = collections::HashMap::new();
        let body = "this is an error message";

        let err = send_webhook(localhost_client(), &method, url, &headers, body.to_owned())
            .await
            .err()
            .expect("request didn't fail when it should have failed");

        assert!(matches!(err, WebhookError::Request(..)));
        if let WebhookError::Request(request_error) = err {
            assert_eq!(request_error.status(), Some(StatusCode::BAD_REQUEST));
            assert!(request_error.to_string().contains(body));
            // This is the display implementation of reqwest. Just checking it is still there.
            // See: https://github.com/seanmonstar/reqwest/blob/master/src/error.rs
            assert!(request_error.to_string().contains(
                "HTTP status client error (400 Bad Request) for url (http://localhost:18081/fail)"
            ));
        }
    }

    #[tokio::test]
    async fn test_error_message_contains_up_to_n_bytes_of_response_body() {
        let method = HttpMethod::POST;
        let url = "http://localhost:18081/fail";
        let headers = collections::HashMap::new();
        // This is double the current hardcoded amount of bytes.
        // TODO: Make this configurable and change it here too.
        let body = (0..20 * 1024).map(|_| "a").collect::<Vec<_>>().concat();

        let err = send_webhook(localhost_client(), &method, url, &headers, body.to_owned())
            .await
            .err()
            .expect("request didn't fail when it should have failed");

        assert!(matches!(err, WebhookError::Request(..)));
        if let WebhookError::Request(request_error) = err {
            assert_eq!(request_error.status(), Some(StatusCode::BAD_REQUEST));
            assert!(request_error.to_string().contains(&body[0..10 * 1024]));
            // The 81 bytes account for the reqwest erorr message as described below.
            assert_eq!(request_error.to_string().len(), 10 * 1024 + 81);
            // This is the display implementation of reqwest. Just checking it is still there.
            // See: https://github.com/seanmonstar/reqwest/blob/master/src/error.rs
            assert!(request_error.to_string().contains(
                "HTTP status client error (400 Bad Request) for url (http://localhost:18081/fail)"
            ));
        }
    }

    #[tokio::test]
    async fn test_private_ips_denied() {
        let method = HttpMethod::POST;
        let url = "http://localhost:18081/echo";
        let headers = collections::HashMap::new();
        let body = "a very relevant request body";
        let filtering_client =
            build_http_client(Duration::from_secs(1), false).expect("failed to create client");

        let err = send_webhook(filtering_client, &method, url, &headers, body.to_owned())
            .await
            .err()
            .expect("request didn't fail when it should have failed");

        assert!(matches!(err, WebhookError::Request(..)));
        if let WebhookError::Request(request_error) = err {
            assert_eq!(request_error.status(), None);
            assert!(request_error
                .to_string()
                .contains("No public IPv4 found for specified host"));
            if let WebhookRequestError::RetryableRequestError { .. } = request_error {
                panic!("error should not be retryable")
            }
        } else {
            panic!("unexpected error type {:?}", err)
        }
    }
}
