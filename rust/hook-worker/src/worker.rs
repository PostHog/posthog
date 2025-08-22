use std::sync::Arc;
use std::time;
use std::{collections, iter};

use chrono::Utc;
use futures::channel::oneshot::Canceled;
use futures::future::join_all;
use health::HealthHandle;
use http::StatusCode;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{FutureProducer, FutureRecord};
use reqwest::{header, Client};
use serde_json::{json, Value};
use tokio::sync;
use tokio::time::{sleep, Duration};
use tracing::error;

use common_kafka::kafka_producer::KafkaContext;
use hook_common::pgqueue::PgTransactionBatch;
use hook_common::{
    pgqueue::{Job, PgQueue, PgQueueJob, PgTransactionJob, RetryError, RetryInvalidError},
    retry::RetryPolicy,
    webhook::{HttpMethod, WebhookJobError, WebhookJobParameters},
};

use crate::error::{
    is_error_source, WebhookError, WebhookParseError, WebhookRequestError, WorkerError,
};
use crate::util::first_n_bytes_of_response;
use common_dns::{NoPublicIPv4Error, PublicIPv4Resolver};

// TODO: Either make this configurable or adjust it once we don't produce results to Kafka, where
// our size limit is relatively low.
const MAX_RESPONSE_BODY: usize = 256 * 1024;

/// A WebhookJob is any `PgQueueJob` with `WebhookJobParameters` and `Value`.
trait WebhookJob: PgQueueJob + std::marker::Send {
    fn parameters(&self) -> &WebhookJobParameters;
    fn take_metadata(&mut self) -> Value;
    fn job(&self) -> &Job<WebhookJobParameters, Value>;

    fn attempt(&self) -> i32 {
        self.job().attempt
    }

    fn queue(&self) -> String {
        self.job().queue.to_owned()
    }

    #[allow(dead_code)]
    fn target(&self) -> String {
        self.job().target.to_owned()
    }
}

impl WebhookJob for PgTransactionJob<'_, WebhookJobParameters, Value> {
    fn parameters(&self) -> &WebhookJobParameters {
        &self.job.parameters
    }

    fn take_metadata(&mut self) -> Value {
        self.job.metadata.take()
    }

    fn job(&self) -> &Job<WebhookJobParameters, Value> {
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
    http_client: reqwest::Client,
    /// Maximum number of concurrent jobs being processed.
    max_concurrent_jobs: usize,
    /// The retry policy used to calculate retry intervals when a job fails with a retryable error.
    retry_policy: RetryPolicy,
    /// Kafka producer used to send results when in Hog mode
    kafka_producer: FutureProducer<KafkaContext>,
    /// The topic to send results to when in Hog mode
    cdp_function_callbacks_topic: &'static str,
    /// Whether we are running in Hog mode or not
    hog_mode: bool,
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
        kafka_producer: FutureProducer<KafkaContext>,
        cdp_function_callbacks_topic: String,
        hog_mode: bool,
        liveness: HealthHandle,
    ) -> Self {
        let http_client = build_http_client(request_timeout, allow_internal_ips)
            .expect("failed to construct reqwest client for webhook worker");

        Self {
            name: name.to_owned(),
            queue,
            dequeue_batch_size,
            poll_interval,
            http_client,
            max_concurrent_jobs,
            retry_policy,
            kafka_producer,
            cdp_function_callbacks_topic: cdp_function_callbacks_topic.leak(),
            hog_mode,
            liveness,
        }
    }

    /// Wait until at least one job becomes available in our queue in transactional mode.
    async fn wait_for_jobs_tx<'a>(&self) -> PgTransactionBatch<'a, WebhookJobParameters, Value> {
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
            let batch = self.wait_for_jobs_tx().await;
            dequeue_batch_size_histogram.record(batch.jobs.len() as f64);

            // Get enough permits for the jobs before spawning a task.
            let permits = semaphore
                .clone()
                .acquire_many_owned(batch.jobs.len() as u32)
                .await
                .expect("semaphore has been closed");

            let http_client = self.http_client.clone();
            let retry_policy = self.retry_policy.clone();
            let kafka_producer = self.kafka_producer.clone();
            let cdp_function_callbacks_topic = self.cdp_function_callbacks_topic;
            let hog_mode = self.hog_mode;

            tokio::spawn(async move {
                // Move `permits` into the closure so they will be dropped when the scope ends.
                let _permits = permits;

                process_batch(
                    batch,
                    http_client,
                    retry_policy,
                    kafka_producer,
                    cdp_function_callbacks_topic,
                    hog_mode,
                )
                .await
            });
        }
    }
}

async fn log_kafka_error_and_sleep(step: &str, error: Option<KafkaError>) {
    match error {
        Some(error) => error!("error sending hog message to kafka ({}): {}", step, error),
        None => error!("error sending hog message to kafka ({})", step),
    }

    // Errors producing to Kafka *should* be exceedingly rare, but when they happen we don't want
    // to enter a tight loop where we re-send the hook payload, fail to produce to Kafka, and
    // repeat over and over again. We also don't want to commit the job as done and not produce
    // something to Kafka, as the Hog task would then be lost.
    //
    // For this reason, we sleep before aborting the batch, in hopes that Kafka has recovered by the
    // time we retry.
    //
    // In the future we may want to consider dequeueing completed jobs from PG itself rather than
    // using a Kafka intermediary.
    sleep(Duration::from_secs(30)).await;
}

async fn process_batch<'a>(
    mut batch: PgTransactionBatch<'a, WebhookJobParameters, Value>,
    http_client: Client,
    retry_policy: RetryPolicy,
    kafka_producer: FutureProducer<KafkaContext>,
    cdp_function_callbacks_topic: &'static str,
    hog_mode: bool,
) {
    let mut futures = Vec::with_capacity(batch.jobs.len());
    let mut metadata_vec = Vec::with_capacity(batch.jobs.len());

    // We have to `take` the Vec of jobs from the batch to avoid a borrow checker
    // error below when we commit.
    for mut job in std::mem::take(&mut batch.jobs) {
        let http_client = http_client.clone();
        let retry_policy = retry_policy.clone();

        metadata_vec.push(job.take_metadata());

        let read_body = hog_mode;
        let future =
            async move { process_webhook_job(http_client, job, &retry_policy, read_body).await };

        futures.push(future);
    }

    let results = join_all(futures).await;

    if hog_mode
        && push_hoghook_results_to_kafka(
            results,
            metadata_vec,
            kafka_producer,
            cdp_function_callbacks_topic,
        )
        .await
        .is_err()
    {
        return;
    }

    let _ = batch.commit().await.map_err(|e| {
        error!("error committing transactional batch: {}", e);
    });
}

async fn push_hoghook_results_to_kafka(
    results: Vec<Result<WebhookResult, WorkerError>>,
    metadata_vec: Vec<Value>,
    kafka_producer: FutureProducer<KafkaContext>,
    cdp_function_callbacks_topic: &str,
) -> Result<(), ()> {
    let mut kafka_ack_futures = Vec::new();
    for (result, mut metadata) in iter::zip(results, metadata_vec) {
        match result {
            Ok(result) => {
                if let Some(payload) = create_hoghook_kafka_payload(result, &mut metadata).await {
                    match kafka_producer.send_result(FutureRecord {
                        topic: cdp_function_callbacks_topic,
                        payload: Some(&payload),
                        partition: None,
                        key: None::<&str>,
                        timestamp: None,
                        headers: None,
                    }) {
                        Ok(future) => kafka_ack_futures.push(future),
                        Err((
                            KafkaError::MessageProduction(RDKafkaErrorCode::MessageSizeTooLarge),
                            _,
                        )) => {
                            // HACK: While under development, we are dropping messages that
                            // are too large. This is temporary, as we expect the webhook
                            // handler for Hog to change soon. In the meantime, nobody needs
                            // to be alerted about this.
                            let team_id = metadata
                                .get("teamId")
                                .and_then(|t| t.as_number())
                                .map(|t| t.to_string())
                                .unwrap_or_else(|| "?".to_string());
                            let hog_function_id = metadata
                                .get("hogFunctionId")
                                .and_then(|h| h.as_str())
                                .map(|h| h.to_string())
                                .unwrap_or_else(|| "?".to_string());

                            error!("dropping message due to size limit, team_id: {}, hog_function_id: {}", team_id, hog_function_id);
                        }
                        Err((error, _)) => {
                            // Return early to avoid committing the batch.
                            return {
                                log_kafka_error_and_sleep("send", Some(error)).await;
                                Err(())
                            };
                        }
                    };
                }
            }
            Err(e) => {
                error!("error processing webhook job: {}", e)
            }
        }
    }

    for result in join_all(kafka_ack_futures).await {
        match result {
            Ok(Ok(_)) => {}
            Ok(Err((error, _))) => {
                // Return early to avoid committing the batch.
                return {
                    log_kafka_error_and_sleep("ack", Some(error)).await;
                    Err(())
                };
            }
            Err(Canceled) => {
                // Cancelled due to timeout while retrying
                // Return early to avoid committing the batch.
                return {
                    log_kafka_error_and_sleep("timeout", None).await;
                    Err(())
                };
            }
        }
    }

    Ok(())
}

async fn create_hoghook_kafka_payload(
    result: WebhookResult,
    metadata: &mut Value,
) -> Option<String> {
    if let Value::Object(ref mut object) = metadata {
        // Add the response or error in the `asyncFunctionResponse` field.
        match result {
            WebhookResult::Success(response) | WebhookResult::BadResponse(response) => {
                let async_function_response = json!({
                    "timings": [{
                        "kind": "async_function",
                        "duration_ms": response.duration.as_millis().try_into().unwrap_or(u32::MAX)
                    }],
                    "response": {
                        "status": response.status_code.as_u16(),
                        "body": response.body
                    }
                });

                object.insert("asyncFunctionResponse".to_owned(), async_function_response);
            }
            WebhookResult::Error(error) => {
                let async_function_response = json!({
                    "error": error,
                });

                object.insert("asyncFunctionResponse".to_owned(), async_function_response);
            }
            WebhookResult::WillRetry => {
                // Nothing to do, and we don't want to produce anything
                // to Kafka.
                return None;
            }
        }
    }

    Some(serde_json::to_string(&metadata).expect("unable to serialize metadata"))
}

struct WebhookResponse {
    duration: Duration,
    status_code: StatusCode,
    body: Option<String>,
}

enum WebhookResult {
    Success(WebhookResponse),
    BadResponse(WebhookResponse),
    WillRetry,
    Error(String),
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
    http_client: reqwest::Client,
    webhook_job: W,
    retry_policy: &RetryPolicy,
    read_body: bool,
) -> Result<WebhookResult, WorkerError> {
    let parameters = webhook_job.parameters();

    let labels = [("queue", webhook_job.queue())];
    metrics::counter!("webhook_jobs_total", &labels).increment(1);

    let now = tokio::time::Instant::now();

    let send_result = send_webhook(
        http_client,
        &parameters.method,
        &parameters.url,
        &parameters.headers,
        parameters.body.clone(),
    )
    .await;

    match send_result {
        Ok(response) => {
            let status = response.status();
            // First, read the body if needed so that the read time is included in `duration`.
            let body = if read_body {
                match first_n_bytes_of_response(response, MAX_RESPONSE_BODY).await {
                    Ok(body) => Some(body), // Once told me...
                    Err(_) => {
                        // TODO: Consolidate this retry-or-fail logic which is mostly repeated below.
                        let retry_interval =
                            retry_policy.retry_interval(webhook_job.attempt() as u32, None);
                        let current_queue = webhook_job.queue();
                        let retry_queue = retry_policy.retry_queue(&current_queue);

                        return match webhook_job
                            .retry(
                                WebhookJobError::new_timeout("timeout while reading response body"),
                                retry_interval,
                                retry_queue,
                            )
                            .await
                        {
                            Ok(_) => {
                                metrics::counter!("webhook_jobs_retried", &labels).increment(1);

                                Ok(WebhookResult::WillRetry)
                            }
                            Err(RetryError::RetryInvalidError(RetryInvalidError {
                                job: webhook_job,
                                ..
                            })) => {
                                webhook_job
                                    .fail(WebhookJobError::new_timeout(
                                        "timeout while reading response body",
                                    ))
                                    .await
                                    .inspect_err(|_| {
                                        metrics::counter!("webhook_jobs_database_error", &labels)
                                            .increment(1)
                                    })?;

                                metrics::counter!("webhook_jobs_failed", &labels).increment(1);

                                Ok(WebhookResult::Error(
                                    "timeout while reading response body".to_owned(),
                                ))
                            }
                            Err(RetryError::DatabaseError(job_error)) => {
                                metrics::counter!("webhook_jobs_database_error", &labels)
                                    .increment(1);
                                Err(WorkerError::from(job_error))
                            }
                        };
                    }
                }
            } else {
                // Caller didn't expect us to read the response body.
                None
            };

            let duration = now.elapsed();

            let created_at = webhook_job.job().created_at;
            let retries = webhook_job.job().attempt - 1;
            let labels_with_retries = [
                ("queue", webhook_job.queue()),
                ("retries", retries.to_string()),
            ];

            webhook_job.complete().await.inspect_err(|_| {
                metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
            })?;

            let insert_to_complete_duration = Utc::now() - created_at;
            metrics::histogram!(
                "webhook_jobs_insert_to_complete_duration_seconds",
                &labels_with_retries
            )
            .record((insert_to_complete_duration.num_milliseconds() as f64) / 1_000_f64);
            metrics::counter!("webhook_jobs_completed", &labels).increment(1);
            metrics::histogram!("webhook_jobs_processing_duration_seconds", &labels)
                .record(duration.as_secs_f64());

            Ok(WebhookResult::Success(WebhookResponse {
                status_code: status,
                duration,
                body,
            }))
        }
        Err(WebhookError::Parse(WebhookParseError::ParseHeadersError(e))) => {
            webhook_job
                .fail(WebhookJobError::new_parse(&e.to_string()))
                .await
                .inspect_err(|_| {
                    metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                })?;

            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

            Ok(WebhookResult::Error(e.to_string()))
        }
        Err(WebhookError::Parse(WebhookParseError::ParseHttpMethodError(e))) => {
            webhook_job
                .fail(WebhookJobError::new_parse(&e))
                .await
                .inspect_err(|_| {
                    metrics::counter!("webhook_jobs_database_error", &labels).increment(1)
                })?;

            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

            Ok(WebhookResult::Error(e.to_string()))
        }
        Err(WebhookError::Parse(WebhookParseError::ParseUrlError(e))) => {
            webhook_job
                .fail(WebhookJobError::new_parse(&e.to_string()))
                .await
                .inspect_err(|_| {
                    metrics::counter!("webhook_jobs_database_error", &labels).increment(1)
                })?;

            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

            Ok(WebhookResult::Error(e.to_string()))
        }
        Err(WebhookError::Request(request_error)) => {
            let webhook_job_error = WebhookJobError::from(&request_error);

            match request_error {
                WebhookRequestError::RetryableRequestError {
                    error,
                    retry_after,
                    response, // Grab the response so we can send it back to hog for debug
                    ..
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

                            Ok(WebhookResult::WillRetry)
                        }
                        Err(RetryError::RetryInvalidError(RetryInvalidError {
                            job: webhook_job,
                            ..
                        })) => {
                            webhook_job
                                .fail(WebhookJobError::from(&error))
                                .await
                                .inspect_err(|_| {
                                    metrics::counter!("webhook_jobs_database_error", &labels)
                                        .increment(1);
                                })?;

                            metrics::counter!("webhook_jobs_failed", &labels).increment(1);

                            match error.status() {
                                Some(status) => Ok(WebhookResult::BadResponse(WebhookResponse {
                                    duration: now.elapsed(),
                                    status_code: status,
                                    body: response,
                                })),
                                None => Ok(WebhookResult::Error(error.to_string())),
                            }
                        }
                        Err(RetryError::DatabaseError(job_error)) => {
                            metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                            Err(WorkerError::from(job_error))
                        }
                    }
                }
                WebhookRequestError::NonRetryableRetryableRequestError {
                    error, response, ..
                } => {
                    webhook_job.fail(webhook_job_error).await.inspect_err(|_| {
                        metrics::counter!("webhook_jobs_database_error", &labels).increment(1);
                    })?;

                    metrics::counter!("webhook_jobs_failed", &labels).increment(1);

                    match error.status() {
                        Some(status) => Ok(WebhookResult::BadResponse(WebhookResponse {
                            duration: now.elapsed(),
                            status_code: status,
                            body: response,
                        })),
                        None => Ok(WebhookResult::Error(error.to_string())),
                    }
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
                    status: None,
                    response: None,
                }
            } else {
                WebhookRequestError::RetryableRequestError {
                    error: e,
                    status: None,
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
                        status: Some(response.status()),
                        response: first_n_bytes_of_response(response, MAX_RESPONSE_BODY)
                            .await
                            .ok(),
                        retry_after,
                    },
                ))
            } else {
                Err(WebhookError::Request(
                    WebhookRequestError::NonRetryableRetryableRequestError {
                        error: err,
                        status: Some(response.status()),
                        response: first_n_bytes_of_response(response, MAX_RESPONSE_BODY)
                            .await
                            .ok(),
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
    use common_kafka::test::create_mock_kafka;
    use health::HealthRegistry;
    use hook_common::pgqueue::{DatabaseError, NewJob};
    use hook_common::webhook::WebhookJobMetadata;
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
        job_metadata: Value,
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
            serde_json::to_value(webhook_job_metadata).unwrap(),
        )
        .await
        .expect("failed to enqueue job");
        let (_mock_cluster, mock_producer) = create_mock_kafka().await;
        let hog_mode = false;
        let worker = WebhookWorker::new(
            &worker_id,
            &queue,
            1,
            time::Duration::from_millis(100),
            time::Duration::from_millis(5000),
            10,
            RetryPolicy::default(),
            false,
            mock_producer,
            "cdp_function_callbacks".to_string(),
            hog_mode,
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

    #[sqlx::test(migrations = "../migrations")]
    async fn test_hoghook_sends_kafka_payload_for_success(db: PgPool) {
        use httpmock::prelude::*;
        use rdkafka::consumer::{Consumer, StreamConsumer};
        use rdkafka::{ClientConfig, Message};

        let worker_id = worker_id();
        let queue_name = "test_hoghook_sends_kafka_payload".to_string();
        let queue = PgQueue::new_from_pool(&queue_name, db).await;
        let topic = "cdp_function_callbacks";

        let server = MockServer::start();

        let registry = HealthRegistry::new("liveness");
        let liveness = registry
            .register("worker".to_string(), ::time::Duration::seconds(30))
            .await;

        let (mock_cluster, mock_producer) = create_mock_kafka().await;
        let hog_mode = true;
        let worker = WebhookWorker::new(
            &worker_id,
            &queue,
            1,
            time::Duration::from_millis(100),
            time::Duration::from_millis(5000),
            10,
            RetryPolicy::default(),
            false,
            mock_producer,
            topic.to_string(),
            hog_mode,
            liveness,
        );

        // Enqueue and run a successful job.

        server.mock(|when, then| {
            when.method(POST).path("/200");
            then.status(200)
                .header("content-type", "application/json; charset=UTF-8")
                .body(r#"{"message": "hello, world"}"#);
        });

        let success_webhook_job_parameters = WebhookJobParameters {
            body: "".to_owned(),
            headers: collections::HashMap::new(),
            method: HttpMethod::POST,
            url: server.url("/200"),
        };

        enqueue_job(
            &queue,
            1,
            success_webhook_job_parameters.clone(),
            serde_json::to_value(json!({"someOtherField": true})).unwrap(),
        )
        .await
        .expect("failed to enqueue job");

        let batch = worker.wait_for_jobs_tx().await;

        process_batch(
            batch,
            worker.http_client.clone(),
            worker.retry_policy.clone(),
            worker.kafka_producer.clone(),
            worker.cdp_function_callbacks_topic,
            hog_mode,
        )
        .await;

        let consumer: StreamConsumer = ClientConfig::new()
            .set("bootstrap.servers", mock_cluster.bootstrap_servers())
            .set("group.id", "mock")
            .set("auto.offset.reset", "earliest")
            .create()
            .expect("failed to create mock consumer");
        consumer.subscribe(&[topic]).unwrap();

        let kafka_msg = consumer.recv().await.unwrap();
        let kafka_payload_str = String::from_utf8(kafka_msg.payload().unwrap().to_vec()).unwrap();

        let received = serde_json::from_str::<Value>(&kafka_payload_str).unwrap();

        // Verify data is passed through, and that response and timings are correct.
        assert!(received.get("someOtherField").unwrap().as_bool().unwrap());

        let async_function_response = received.get("asyncFunctionResponse").unwrap();
        let received_response = async_function_response.get("response").unwrap();
        assert_eq!(
            json!({
                "body": "{\"message\": \"hello, world\"}",
                "status": 200
            }),
            *received_response
        );

        let first_timing = async_function_response
            .get("timings")
            .unwrap()
            .as_array()
            .unwrap()
            .first()
            .unwrap();
        first_timing
            .get("duration_ms")
            .unwrap()
            .as_number()
            .unwrap();
        assert_eq!(
            "async_function",
            first_timing.get("kind").unwrap().as_str().unwrap()
        );
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn test_hoghook_sends_kafka_payload_for_bad_response(db: PgPool) {
        use httpmock::prelude::*;
        use rdkafka::consumer::{Consumer, StreamConsumer};
        use rdkafka::{ClientConfig, Message};

        let worker_id = worker_id();
        let queue_name = "test_hoghook_sends_kafka_payload".to_string();
        let queue = PgQueue::new_from_pool(&queue_name, db).await;
        let topic = "cdp_function_callbacks";

        let server = MockServer::start();

        let registry = HealthRegistry::new("liveness");
        let liveness = registry
            .register("worker".to_string(), ::time::Duration::seconds(30))
            .await;

        let (mock_cluster, mock_producer) = create_mock_kafka().await;
        let hog_mode = true;
        let worker = WebhookWorker::new(
            &worker_id,
            &queue,
            1,
            time::Duration::from_millis(100),
            time::Duration::from_millis(5000),
            10,
            RetryPolicy::default(),
            false,
            mock_producer,
            topic.to_string(),
            hog_mode,
            liveness,
        );

        // Enqueue and run a job that returns a bad HTTP response.

        server.mock(|when, then| {
            when.method(POST).path("/500");
            then.status(500)
                .header("content-type", "application/json; charset=UTF-8")
                .body(r#"{"message": "bad response"}"#);
        });

        let bad_webhook_job_parameters = WebhookJobParameters {
            body: "".to_owned(),
            headers: collections::HashMap::new(),
            method: HttpMethod::POST,
            url: server.url("/500"),
        };

        enqueue_job(
            &queue,
            1,
            bad_webhook_job_parameters.clone(),
            serde_json::to_value(json!({"someOtherField": true})).unwrap(),
        )
        .await
        .expect("failed to enqueue job");

        let batch = worker.wait_for_jobs_tx().await;

        process_batch(
            batch,
            worker.http_client.clone(),
            worker.retry_policy.clone(),
            worker.kafka_producer.clone(),
            worker.cdp_function_callbacks_topic,
            hog_mode,
        )
        .await;

        let consumer: StreamConsumer = ClientConfig::new()
            .set("bootstrap.servers", mock_cluster.bootstrap_servers())
            .set("group.id", "mock")
            .set("auto.offset.reset", "earliest")
            .create()
            .expect("failed to create mock consumer");
        consumer.subscribe(&[topic]).unwrap();

        let kafka_msg = consumer.recv().await.unwrap();
        let kafka_payload_str = String::from_utf8(kafka_msg.payload().unwrap().to_vec()).unwrap();

        let received = serde_json::from_str::<Value>(&kafka_payload_str).unwrap();

        // Verify data is passed through, and that response and timings are correct.
        assert!(received.get("someOtherField").unwrap().as_bool().unwrap());

        let async_function_response = received.get("asyncFunctionResponse").unwrap();
        let received_response = async_function_response.get("response").unwrap();
        assert_eq!(
            json!({
                "body": Some("{\"message\": \"bad response\"}"),
                "status": 500
            }),
            *received_response
        );

        let first_timing = async_function_response
            .get("timings")
            .unwrap()
            .as_array()
            .unwrap()
            .first()
            .unwrap();
        first_timing
            .get("duration_ms")
            .unwrap()
            .as_number()
            .unwrap();
        assert_eq!(
            "async_function",
            first_timing.get("kind").unwrap().as_str().unwrap()
        );
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn test_hoghook_drops_large_payloads(db: PgPool) {
        use httpmock::prelude::*;

        let worker_id = worker_id();
        let queue_name = "test_hoghook_drops_large_payloads".to_string();
        let queue = PgQueue::new_from_pool(&queue_name, db).await;
        let topic = "cdp_function_callbacks";

        let server = MockServer::start();

        server.mock(|when, then| {
            when.method(POST).path("/");
            then.status(200)
                .header("content-type", "application/json; charset=UTF-8")
                .body(r#"{"message": "hello, world"}"#);
        });

        let mock_url = server.url("/");

        let webhook_job_parameters = WebhookJobParameters {
            body: "".to_owned(),
            headers: collections::HashMap::new(),
            method: HttpMethod::POST,
            url: mock_url,
        };

        let webhook_job_metadata = json!({"hugeField": "a".repeat(2 * 1024 * 1024)});

        enqueue_job(
            &queue,
            1,
            webhook_job_parameters.clone(),
            serde_json::to_value(webhook_job_metadata).unwrap(),
        )
        .await
        .expect("failed to enqueue job");

        let registry = HealthRegistry::new("liveness");
        let liveness = registry
            .register("worker".to_string(), ::time::Duration::seconds(30))
            .await;

        let (_, mock_producer) = create_mock_kafka().await;
        let hog_mode = true;
        let worker = WebhookWorker::new(
            &worker_id,
            &queue,
            1,
            time::Duration::from_millis(100),
            time::Duration::from_millis(5000),
            10,
            RetryPolicy::default(),
            false,
            mock_producer,
            topic.to_string(),
            hog_mode,
            liveness,
        );

        let batch = worker.wait_for_jobs_tx().await;

        process_batch(
            batch,
            worker.http_client,
            worker.retry_policy,
            worker.kafka_producer,
            worker.cdp_function_callbacks_topic,
            hog_mode,
        )
        .await;
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
            .expect_err("request didn't fail when it should have failed");

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
        let body = (0..512 * 1024).map(|_| "a").collect::<Vec<_>>().concat();

        let err = send_webhook(localhost_client(), &method, url, &headers, body.to_owned())
            .await
            .expect_err("request didn't fail when it should have failed");

        assert!(matches!(err, WebhookError::Request(..)));
        if let WebhookError::Request(request_error) = err {
            assert_eq!(request_error.status(), Some(StatusCode::BAD_REQUEST));
            assert!(request_error.to_string().contains(&body[0..256 * 1024]));
            // The 81 bytes account for the reqwest error message as described below.
            assert_eq!(request_error.to_string().len(), 256 * 1024 + 81);
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
            .expect_err("request didn't fail when it should have failed");

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
            panic!("unexpected error type {err:?}")
        }
    }
}
