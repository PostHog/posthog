use std::{cmp::min, collections::HashMap, sync::Arc};

use chrono::{DateTime, Duration, Utc};
use cyclotron_core::{
    base_ops::{Job, JobState, WaitingOn},
    error::QueueError,
    worker::Worker,
};
use futures::StreamExt;
use health::HealthHandle;
use http::StatusCode;
use reqwest::Response;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};
use tracing::error;

// TODO - a lot of these should maybe be configurable
pub const DEAD_LETTER_QUEUE: &str = "fetch-dead-letter";
pub const ABSOLUTE_MAX_RETRIES: u32 = 10;
pub const DEFAULT_RETRIES: u32 = 3;
pub const DEFAULT_ON_FINISH: OnFinish = OnFinish::Return;
pub const EXP_BACKOFF_BASE: i64 = 4;
pub const MAX_RESPONSE_SIZE: usize = 1024 * 1024;

// Exclusively for errors in the worker - these will
// never be serialised into the job queue, and indicate
// bad worker health. As a general rule, if one of these
// is produced, we should let the worker fall over (as in,
// the outer worker loop should exit).
#[derive(Error, Debug)]
pub enum WorkerError {
    #[error("timeout fetching jobs")]
    JobFetchTimeout,
    #[error(transparent)]
    QueueError(#[from] QueueError),
    // TRICKY - in most cases, serde errors are a FetchError (something coming from the queue was
    // invalid), but this is used in cases where /we/ fail to serialise something /to/ the queue
    #[error(transparent)]
    SerdeError(#[from] serde_json::Error),
}

#[derive(Debug, Serialize, Deserialize, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum HttpMethod {
    Get,
    Post,
    Patch,
    Put,
    Delete,
}

impl From<&HttpMethod> for http::Method {
    fn from(method: &HttpMethod) -> Self {
        match method {
            HttpMethod::Get => http::Method::GET,
            HttpMethod::Post => http::Method::POST,
            HttpMethod::Patch => http::Method::PATCH,
            HttpMethod::Put => http::Method::PUT,
            HttpMethod::Delete => http::Method::DELETE,
        }
    }
}

// What does someone need to give us to execute a fetch?
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "lowercase")]
pub struct FetchParameters {
    url: String,
    method: HttpMethod,
    return_worker: WaitingOn,
    return_queue: Option<String>, // Defaults to the original queue
    header: Option<HashMap<String, String>>,
    body: Option<String>,
    max_tries: Option<u32>,        // Defaults to 3
    fetch_timeout_ms: Option<u64>, // Defaults to 1000
    on_finish: Option<OnFinish>,   // Defaults to Return
}

// What should we do when we get a result, or run out of tries for a given job?
// Return means re-queue to the return_worker, Complete means mark as Completed/Failed
#[derive(Debug, Serialize, Deserialize, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum OnFinish {
    Return,
    Complete,
}

// Internal bookkeeping for a fetch job
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "lowercase")]
pub struct FetchMetadata {
    tries: u32,
    // The history of failures seen with this job
    trace: Vec<FetchFailure>,
}

// This is what we put in the parameters of the job queue for the next
// worker to pick up
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(tag = "status", rename_all = "lowercase")]
pub enum FetchResult {
    Success { response: FetchResponse },
    Failure { trace: Vec<FetchFailure> }, // If we failed entirely to fetch the job, we return the trace for user debugging
}

impl FetchResult {
    pub fn is_success(&self) -> bool {
        matches!(self, FetchResult::Completed { .. })
    }
}

// We distinguish between a "fetch failure" and a "worker failure" -
// worker failures are internal-only, and do not count against the
// retries of a job (generally, on worker failure, the job is either
// moved to the dead letter queue, or dropped and left to the janitor to
// reset). Feture failures are, after retries, returned to the queue, and
// represent the result of the fetch operation.
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "lowercase")]
pub struct FetchFailure {
    pub kind: FetchFailureKind,
    pub message: String,
    pub body: Option<String>, // If we have a body, we include it in the failure
    pub headers: Option<HashMap<String, String>>, // If we have headers, we include them in the failure
    pub status: Option<u16>, // If we have a status, we include it in the failure
    pub timestamp: DateTime<Utc>, // Useful for users to correlate logs when debugging
}

impl FetchFailure {
    pub fn new(kind: FetchFailureKind, message: impl AsRef<str>) -> Self {
        Self {
            kind,
            message: message.as_ref().to_string(),
            timestamp: Utc::now(),
            body: None,
            headers: None,
            status: None,
        }
    }

    pub fn failure_status(status: StatusCode) -> Self {
        Self {
            kind: FetchFailureKind::FailureStatus,
            message: format!("Received failure status: {}", status),
            timestamp: Utc::now(),
            body: None,
            headers: None,
            status: Some(status.as_u16()),
        }
    }

    pub fn with_body(self, body: String) -> Self {
        Self {
            message: format!("{} - body: {}", self.message, body),
            ..self
        }
    }

    pub fn with_headers(self, headers: HashMap<String, String>) -> Self {
        Self {
            message: format!("{} - headers: {:?}", self.message, headers),
            ..self
        }
    }

    pub fn with_status(self, status: u16) -> Self {
        Self {
            message: format!("{} - status: {}", self.message, status),
            ..self
        }
    }
}

impl From<reqwest::Error> for FetchFailure {
    fn from(e: reqwest::Error) -> Self {
        let kind = if e.is_timeout() {
            FetchFailureKind::Timeout
        } else {
            FetchFailureKind::RequestError
        };
        Self {
            kind,
            message: e.to_string(),
            timestamp: Utc::now(),
            body: None,
            headers: None,
            status: None,
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum FetchFailureKind {
    Timeout,
    TimeoutGettingBody,
    MissingParameters,
    InvalidParameters,
    RequestError,
    FailureStatus,
    InvalidBody, // Generally means the body could not be parsed toa  utf8 string
    ResponseTooLarge,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "lowercase")]
pub struct FetchResponse {
    pub status: u16,
    pub body: String,
}

pub struct FetchWorker {
    pub id: String,
    pub worker: Worker,
    pub client: reqwest::Client,
    pub job_poll_interval: Duration,
    pub concurrency_limit: Arc<Semaphore>,
    pub fetch_timeout: Duration,
    pub liveness: HealthHandle,
    pub queue_served: String,
    pub batch_size: usize,
}

pub fn report_worker_saturation(worker: &FetchWorker) {
    metrics::gauge!("fetch_worker_available_permits")
        .set(worker.concurrency_limit.available_permits() as f64);
}

// Blocks until at least one job is available. Reports healthy while waiting, and is
// guaranteed to 1) return at least one job and 2) report healthy at least once.
pub async fn wait_for_jobs(worker: &FetchWorker, max_jobs: usize) -> Result<Vec<Job>, WorkerError> {
    let mut interval = tokio::time::interval(worker.job_poll_interval.to_std().unwrap());
    loop {
        worker.liveness.report_healthy().await;

        let jobs = worker
            .worker
            .dequeue_jobs(worker.queue_served.as_str(), WaitingOn::Fetch, max_jobs)
            .await?;

        if !jobs.is_empty() {
            return Ok(jobs);
        }

        interval.tick().await;
    }
}

pub async fn tick(worker: Arc<FetchWorker>) -> Result<usize, WorkerError> {
    report_worker_saturation(&worker);

    let max_jobs = min(
        worker.concurrency_limit.available_permits(),
        worker.batch_size,
    );

    let jobs = wait_for_jobs(&worker, max_jobs).await?;

    let num_jobs = jobs.len();

    for job in jobs {
        let worker = worker.clone();
        let permit = worker
            .concurrency_limit
            .clone()
            .acquire_owned()
            .await
            .unwrap();
        tokio::spawn(async move {
            // TODO - since worker errors are never an indication of a fetch failure,
            // only of some internal worker issue, we should report unhealthy or fall
            // over or something here.
            if let Err(e) = run_job(worker.clone(), job, permit).await {
                error!("Error running job: {:?}", e);
            }
        });
    }

    Ok(num_jobs)
}

struct FetchJob<'a> {
    _job: &'a Job,
    metadata: FetchMetadata,
    parameters: FetchParameters,
}

impl<'a> TryFrom<&'a Job> for FetchJob<'a> {
    type Error = FetchFailure;

    fn try_from(job: &'a Job) -> Result<Self, Self::Error> {
        let Some(parameters) = &job.parameters else {
            return Err(FetchFailure::new(
                FetchFailureKind::MissingParameters,
                "Job is missing parameters",
            ));
        };
        let parameters: FetchParameters = match serde_json::from_str(parameters) {
            Ok(p) => p,
            Err(e) => {
                return Err(FetchFailure::new(
                    FetchFailureKind::InvalidParameters,
                    format!("Failed to parse parameters: {}", e),
                ))
            }
        };
        let metadata = match &job.metadata {
            Some(m) => match serde_json::from_str(m) {
                Ok(m) => m,
                Err(e) => {
                    return Err(FetchFailure::new(
                        FetchFailureKind::InvalidParameters,
                        format!("Failed to parse metadata: {}", e),
                    ))
                }
            },
            None => FetchMetadata {
                tries: 0,
                trace: vec![],
            },
        };
        Ok(Self {
            _job: job,
            metadata,
            parameters,
        })
    }
}

pub async fn run_job(
    worker: Arc<FetchWorker>,
    job: Job,
    _permit: OwnedSemaphorePermit,
) -> Result<(), WorkerError> {
    let parsed: FetchJob = match (&job).try_into() {
        Ok(p) => p,
        Err(e) => return dead_letter_job(&worker.worker, job, vec![e]).await,
    };

    let start = Utc::now();
    let method: http::Method = (&parsed.parameters.method).into();

    // Parsing errors are always dead letters - it /will/ fail every time, so dump it
    // TODO - We should probably decide whether to dead letter or return Failed on the basis of OnFinish,
    // in case the caller wants to do any cleanup on broken jobs
    let url: reqwest::Url = match (parsed.parameters.url).parse() {
        Ok(u) => u,
        Err(e) => {
            return dead_letter_job(
                &worker.worker,
                job,
                vec![FetchFailure::new(
                    FetchFailureKind::InvalidParameters,
                    format!("Invalid url: {}", e),
                )],
            )
            .await;
        }
    };
    let headers: reqwest::header::HeaderMap =
        match (&parsed.parameters.header.unwrap_or_default()).try_into() {
            Ok(h) => h,
            Err(e) => {
                return dead_letter_job(
                    &worker.worker,
                    job,
                    vec![FetchFailure::new(
                        FetchFailureKind::InvalidParameters,
                        format!("Invalid headers: {}", e),
                    )],
                )
                .await;
            }
        };

    let body = reqwest::Body::from(parsed.parameters.body.unwrap_or_default());

    let send_fut = worker
        .client
        .request(method, url)
        .headers(headers)
        .body(body)
        .send();

    let mut send_fut = Box::pin(send_fut);

    let res = loop {
        tokio::select! {
            res = &mut send_fut => {
                break res
            }
            _ = tokio::time::sleep(Duration::milliseconds(500).to_std().unwrap()) => {
                worker.worker.heartbeat(job.id).await?;
            }
        }
    };

    // We want to ensure at least 1 heartbeat during the initial request
    worker.worker.heartbeat(job.id).await?;

    let res = match res {
        Ok(r) => r,
        Err(e) => {
            return handle_fetch_failure(
                &worker,
                &job,
                &parsed.metadata,
                parsed.parameters.max_tries.unwrap_or(DEFAULT_RETRIES),
                parsed.parameters.return_worker,
                parsed.parameters.return_queue,
                parsed.parameters.on_finish.unwrap_or(DEFAULT_ON_FINISH),
                e,
            )
            .await
        }
    };

    // Grab the response metadata, since getting the body moves it
    let status = res.status();
    let headers: HashMap<String, String> = res
        .headers()
        .iter()
        .map(|(k, v)| {
            (
                k.as_str().to_string(),
                v.to_str().unwrap_or_default().to_string(),
            )
        })
        .collect();

    // We pre-emptively get the response body, because we incldued it in the failure trace, even if we got a failure status
    let body = first_n_bytes_of_response(&worker.worker, &job, res, MAX_RESPONSE_SIZE).await?;
    let body = match body {
        Ok(b) => b,
        Err(e) => {
            // Tag the status and headers onto the failure
            let e = e.with_status(status.as_u16()).with_headers(headers);
            return handle_fetch_failure(
                &worker,
                &job,
                &parsed.metadata,
                parsed.parameters.max_tries.unwrap_or(DEFAULT_RETRIES),
                parsed.parameters.return_worker,
                parsed.parameters.return_queue,
                parsed.parameters.on_finish.unwrap_or(DEFAULT_ON_FINISH),
                e,
            )
            .await;
        }
    };

    // TODO - we should handle "retryable" and "permanent" failures differently, mostly
    // to be polite - retrying a permanent failure isn't a correctness problem, but it's
    // rude (and inefficient)
    if !status.is_success() {
        let failure = FetchFailure::failure_status(status)
            .with_body(body)
            .with_headers(headers);
        return handle_fetch_failure(
            &worker,
            &job,
            &parsed.metadata,
            parsed.parameters.max_tries.unwrap_or(DEFAULT_RETRIES),
            parsed.parameters.return_worker,
            parsed.parameters.return_queue,
            parsed.parameters.on_finish.unwrap_or(DEFAULT_ON_FINISH),
            failure,
        )
        .await;
    }

    todo!()
}

// Checks if the retry limit has been reached, and does one of:
// - Schedule the job for retry, doing metadata bookkeeping
// - Complete the job, with the failure trace
#[allow(clippy::too_many_arguments)]
pub async fn handle_fetch_failure<F>(
    worker: &FetchWorker,
    job: &Job,
    metadata: &FetchMetadata,
    max_tries: u32,
    return_worker: WaitingOn,
    return_queue: Option<String>,
    on_finish: OnFinish,
    failure: F,
) -> Result<(), WorkerError>
where
    F: Into<FetchFailure>,
{
    let failure = failure.into();
    let mut metadata = metadata.clone();
    metadata.tries += 1;
    metadata.trace.push(failure);

    // TODO - right now we treat all failures as retryable, but we should probably be more aggressive in
    // culling retries for permanent failures (this is less of a correctness issue and more of an efficiency/
    // politeness one). We might also want to make backoff configurable.
    if metadata.tries <= min(max_tries, ABSOLUTE_MAX_RETRIES) {
        let next_available = Utc::now() + Duration::seconds(EXP_BACKOFF_BASE.pow(metadata.tries));
        // We back off for at most an hour (since callers can configure max retries to be very high)
        let next_available = min(next_available, Utc::now() + Duration::hours(1));
        // Add some seconds of jitter
        let next_available =
            next_available + Duration::seconds((rand::random::<u64>() % 30) as i64);

        // Set us up for a retry - update metadata, reschedule, and put back in the queue we pulled from
        worker
            .worker
            .set_metadata(job.id, Some(serde_json::to_string(&metadata)?))?;
        worker.worker.set_state(job.id, JobState::Available)?;
        worker.worker.set_queue(job.id, &job.queue_name)?;
        worker.worker.set_scheduled_at(job.id, next_available)?;

        // We downgrade the priority of jobs that fail, so first attempts at jobs get better QoS
        worker.worker.set_priority(job.id, job.priority + 1)?;

        worker.worker.flush_job(job.id).await?;
    } else {
        // Complete the job, with a Failed result
        let result = FetchResult::Failure {
            trace: metadata.trace.clone(),
        };
        complete_job(
            &worker.worker,
            job,
            return_worker,
            return_queue,
            on_finish,
            result,
        )
        .await?;
    }

    Ok(())
}

// Complete the job, either because we got a good response, or because the jobs retries
// have been exceeded.
pub async fn complete_job(
    worker: &Worker,
    job: &Job,
    return_worker: WaitingOn,
    return_queue: Option<String>,
    on_finish: OnFinish,
    result: FetchResult,
) -> Result<(), WorkerError> {
    // If we fail any serde, we just want to flush to the DLQ and bail
    worker.set_state(job.id, JobState::Available)?;
    worker.set_queue(job.id, DEAD_LETTER_QUEUE)?;

    let is_success = result.is_success();

    let result = match serde_json::to_string(&result) {
        Ok(r) => r,
        Err(e) => {
            // Leave behind a hint for debugging
            worker.set_metadata(job.id, Some(format!("Failed to serialise result: {}", e)))?;
            worker.flush_job(job.id).await?;
            return Err(WorkerError::SerdeError(e));
        }
    };

    worker.set_queue(
        job.id,
        &return_queue.unwrap_or_else(|| job.queue_name.clone()),
    )?;
    worker.set_waiting_on(job.id, return_worker)?;

    match (is_success, on_finish) {
        (true, _) | (false, OnFinish::Return) => {
            worker.set_state(job.id, JobState::Available)?;
        }
        (false, OnFinish::Complete) => {
            worker.set_state(job.id, JobState::Failed)?;
        }
    }

    worker.set_parameters(job.id, Some(result))?;
    worker.set_metadata(job.id, None)?; // We're finished with the job, so clear our internal state
    worker.flush_job(job.id).await?;

    Ok(())
}

// This moves the job to a dead letter queue, and sets the state to Available (to prevent it
// from being deleted by the janitor). This is for debugging purposes, and only really jobs
// that have some parsing failure on dequeue end up here (as they indicate a programming error
// in the caller, or the worker)
pub async fn dead_letter_job(
    worker: &Worker,
    job: Job,
    errors: Vec<FetchFailure>,
) -> Result<(), WorkerError> {
    worker.set_state(job.id, JobState::Available)?;
    worker.set_queue(job.id, DEAD_LETTER_QUEUE)?;

    let result = FetchResult::Failure { trace: errors };
    let result = match serde_json::to_string(&result) {
        Ok(r) => r,
        Err(e) => {
            worker.set_metadata(
                job.id,
                Some(format!(
                    "Failed to serialise result during DLQ write: {}",
                    e
                )),
            )?;
            worker.flush_job(job.id).await?;
            return Err(WorkerError::SerdeError(e));
        }
    };

    worker.set_parameters(job.id, Some(result))?;

    worker.flush_job(job.id).await?;

    Ok(())
}

// Pulls the body, while maintaining the job heartbeat.
pub async fn first_n_bytes_of_response(
    worker: &Worker,
    job: &Job,
    response: Response,
    n: usize,
) -> Result<Result<String, FetchFailure>, WorkerError> {
    let mut body = response.bytes_stream();
    // We deserialize into a vec<u8>, and then parse to a string
    let mut buffer = Vec::with_capacity(n);

    worker.heartbeat(job.id).await?;

    loop {
        tokio::select! {
            chunk = body.next() => {
                let chunk = match chunk {
                    Some(Ok(c)) => c,
                    Some(Err(e)) => return Ok(Err(FetchFailure::from(e))),
                    None => break,
                };

                buffer.extend_from_slice(&chunk);

                if buffer.len() >= n {
                    return Ok(Err(
                        FetchFailure::new(FetchFailureKind::ResponseTooLarge, "Response too large")
                    ));
                };
            }
            _ = tokio::time::sleep(std::time::Duration::from_millis(500)) => {}
        }
        // Heartbeat every time we get a new body chunk, or every 500ms
        worker.heartbeat(job.id).await?;
    }

    let Ok(body) = String::from_utf8(buffer) else {
        return Ok(Err(FetchFailure::new(
            FetchFailureKind::InvalidBody,
            "Body could not be parsed as utf8",
        )));
    };

    Ok(Ok(body))
}
