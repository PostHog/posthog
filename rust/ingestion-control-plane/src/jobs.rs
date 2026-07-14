use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use anyhow::Context;
use chrono::{DateTime, Utc};
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use tokio::sync::Semaphore;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use crate::config::{Config, ConsumerTarget};
use crate::kafka::analysis::Aggregates;
use crate::kafka::client;
use crate::kafka::fetch::{self, FetchParams, TruncatedReason};
use crate::kafka::lag::{self, PartitionBounds};
use crate::teams::TeamResolver;

/// Finished jobs kept around for the UI; older ones are evicted on insert.
const MAX_RETAINED_JOBS: usize = 20;
/// Running-plus-queued cap; submissions beyond it are rejected up front,
/// before any Kafka metadata work.
const MAX_PENDING_JOBS: usize = 8;
const MAX_JOB_AGE: Duration = Duration::from_secs(3600);
const TOP_K: usize = 50;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum AnalysisMode {
    /// Start at the group's committed offset: what the consumer is stuck on.
    #[default]
    Committed,
    /// Sample the last N messages before the high watermark: what's arriving now.
    Tail,
}

/// Fully resolved analysis parameters, echoed back on job status.
#[derive(Debug, Clone, Serialize)]
pub struct AnalysisSpec {
    pub group: String,
    pub topic: String,
    pub partition: i32,
    pub mode: AnalysisMode,
    pub start_offset: i64,
    pub end_offset_exclusive: i64,
    pub requested_messages: u64,
    pub low_watermark: i64,
    pub high_watermark: i64,
    pub committed_offset: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AnalysisResult {
    pub messages_analyzed: u64,
    pub next_offset: i64,
    pub truncated_reason: Option<TruncatedReason>,
    pub duration_ms: u64,
    #[serde(flatten)]
    pub aggregates: Aggregates,
}

pub struct Progress {
    fetched: AtomicU64,
    current_offset: AtomicI64,
    bytes_read: AtomicU64,
    target: u64,
}

impl Progress {
    fn new(start_offset: i64, target: u64) -> Self {
        Self {
            fetched: AtomicU64::new(0),
            current_offset: AtomicI64::new(start_offset),
            bytes_read: AtomicU64::new(0),
            target,
        }
    }

    pub fn record(&self, next_offset: i64, bytes: u64) {
        self.fetched.fetch_add(1, Ordering::Relaxed);
        self.current_offset.store(next_offset, Ordering::Relaxed);
        self.bytes_read.fetch_add(bytes, Ordering::Relaxed);
    }

    fn snapshot(&self) -> ProgressView {
        ProgressView {
            fetched: self.fetched.load(Ordering::Relaxed),
            target: self.target,
            current_offset: self.current_offset.load(Ordering::Relaxed),
            bytes_read: self.bytes_read.load(Ordering::Relaxed),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ProgressView {
    pub fetched: u64,
    pub target: u64,
    pub current_offset: i64,
    pub bytes_read: u64,
}

enum JobPhase {
    Running,
    Done(Box<AnalysisResult>),
    Failed(String),
}

pub struct Job {
    pub id: Uuid,
    pub spec: AnalysisSpec,
    pub created_at: DateTime<Utc>,
    pub progress: Progress,
    pub cancel: CancellationToken,
    phase: Mutex<JobPhase>,
}

impl Job {
    fn set_phase(&self, phase: JobPhase) {
        *self.phase.lock().expect("job phase mutex poisoned") = phase;
    }

    fn is_finished(&self) -> bool {
        !matches!(
            *self.phase.lock().expect("job phase mutex poisoned"),
            JobPhase::Running
        )
    }

    pub fn view(&self) -> JobView {
        let (state, result, error) = match &*self.phase.lock().expect("job phase mutex poisoned") {
            JobPhase::Running => ("running", None, None),
            JobPhase::Done(result) => ("done", Some(result.as_ref().clone()), None),
            JobPhase::Failed(message) => ("failed", None, Some(message.clone())),
        };
        JobView {
            id: self.id,
            state,
            spec: self.spec.clone(),
            created_at: self.created_at.to_rfc3339(),
            progress: self.progress.snapshot(),
            result,
            error,
        }
    }
}

#[derive(Serialize)]
pub struct JobView {
    pub id: Uuid,
    pub state: &'static str,
    pub spec: AnalysisSpec,
    pub created_at: String,
    pub progress: ProgressView,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<AnalysisResult>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct AnalysisRequest {
    pub group: String,
    pub partition: i32,
    #[serde(default)]
    pub mode: AnalysisMode,
    pub start_offset: Option<i64>,
    pub message_count: Option<u64>,
}

pub struct JobRegistry {
    jobs: DashMap<Uuid, Arc<Job>>,
    concurrency: Arc<Semaphore>,
}

impl JobRegistry {
    pub fn new(max_concurrent_jobs: usize) -> Self {
        Self {
            jobs: DashMap::new(),
            concurrency: Arc::new(Semaphore::new(max_concurrent_jobs.max(1))),
        }
    }

    pub fn get(&self, id: &Uuid) -> Option<Arc<Job>> {
        self.jobs.get(id).map(|entry| Arc::clone(entry.value()))
    }

    pub fn list(&self) -> Vec<JobView> {
        let mut views: Vec<JobView> = self.jobs.iter().map(|entry| entry.value().view()).collect();
        views.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        views
    }

    /// Whether a new submission is admitted right now (running + queued jobs
    /// below the cap).
    pub fn admits_new_job(&self) -> bool {
        self.jobs
            .iter()
            .filter(|entry| !entry.value().is_finished())
            .count()
            < MAX_PENDING_JOBS
    }

    pub fn cancel(&self, id: &Uuid) -> bool {
        match self.jobs.get(id) {
            Some(entry) => {
                entry.value().cancel.cancel();
                true
            }
            None => false,
        }
    }

    /// Evict finished jobs beyond the retention cap and anything past max age.
    fn evict(&self) {
        let now = Utc::now();
        let mut finished: Vec<(Uuid, DateTime<Utc>)> = self
            .jobs
            .iter()
            .filter(|entry| entry.value().is_finished())
            .map(|entry| (entry.value().id, entry.value().created_at))
            .collect();
        finished.sort_by_key(|(_, created_at)| *created_at);

        let excess = finished.len().saturating_sub(MAX_RETAINED_JOBS);
        for (id, created_at) in finished.iter() {
            let too_old = (now - *created_at).to_std().unwrap_or_default() > MAX_JOB_AGE;
            let over_cap = finished
                .iter()
                .position(|(fid, _)| fid == id)
                .is_some_and(|pos| pos < excess);
            if too_old || over_cap {
                self.jobs.remove(id);
            }
        }
    }

    /// Validate the request against fresh watermarks, register the job, and
    /// spawn its fetch task. Returns the job id immediately.
    pub async fn start(
        self: &Arc<Self>,
        config: Arc<Config>,
        teams: Arc<TeamResolver>,
        target: ConsumerTarget,
        request: AnalysisRequest,
    ) -> anyhow::Result<Uuid> {
        let timeout = Duration::from_millis(config.kafka_metadata_timeout_ms);
        let bounds = {
            let config = Arc::clone(&config);
            let target = target.clone();
            let partition = request.partition;
            tokio::task::spawn_blocking(move || {
                lag::fetch_partition_bounds_blocking(&config, &target, partition, timeout)
            })
            .await
            .context("bounds task panicked")??
        };

        let requested_messages = request
            .message_count
            .unwrap_or(config.analysis_message_count)
            .clamp(1, 1_000_000);
        let (start_offset, end_offset_exclusive) = resolve_offsets(
            request.mode,
            request.start_offset,
            requested_messages,
            bounds,
        );

        let spec = AnalysisSpec {
            group: target.group.clone(),
            topic: target.topic.clone(),
            partition: request.partition,
            mode: request.mode,
            start_offset,
            end_offset_exclusive,
            requested_messages,
            low_watermark: bounds.low_watermark,
            high_watermark: bounds.high_watermark,
            committed_offset: bounds.committed_offset,
        };

        let job = Arc::new(Job {
            id: Uuid::new_v4(),
            spec: spec.clone(),
            created_at: Utc::now(),
            progress: Progress::new(
                start_offset,
                (end_offset_exclusive - start_offset).max(0) as u64,
            ),
            cancel: CancellationToken::new(),
            phase: Mutex::new(JobPhase::Running),
        });

        let job_id = job.id;
        self.evict();
        self.jobs.insert(job_id, Arc::clone(&job));

        let registry = Arc::clone(self);
        tokio::spawn(async move {
            let _permit = registry
                .concurrency
                .acquire()
                .await
                .expect("job semaphore closed");
            run_job(config, teams, job).await;
        });

        Ok(job_id)
    }
}

async fn run_job(config: Arc<Config>, teams: Arc<TeamResolver>, job: Arc<Job>) {
    let params = FetchParams {
        topic: job.spec.topic.clone(),
        partition: job.spec.partition,
        start_offset: job.spec.start_offset,
        end_offset_exclusive: job.spec.end_offset_exclusive,
        requested_end_offset: job.spec.start_offset + job.spec.requested_messages as i64,
        deadline: Duration::from_secs(config.analysis_deadline_secs),
        max_bytes: config.analysis_max_fetch_bytes,
        poll_timeout: Duration::from_millis(config.kafka_fetch_poll_timeout_ms),
    };

    let outcome = {
        let job = Arc::clone(&job);
        let config = Arc::clone(&config);
        tokio::task::spawn_blocking(move || {
            let consumer = client::fetch_consumer(&config).context("create fetch client")?;
            fetch::run_fetch(&consumer, &params, &job.progress, &job.cancel)
        })
        .await
        .context("fetch task panicked")
        .and_then(|res| res)
    };

    match outcome {
        Ok(outcome) => {
            let mut aggregates = outcome.aggregator.finish(TOP_K);
            let tokens: Vec<String> = aggregates
                .top_tokens
                .iter()
                .map(|t| t.token.clone())
                .collect();
            let team_ids = teams.resolve(&tokens).await;
            for token_count in &mut aggregates.top_tokens {
                token_count.team_id = team_ids.get(&token_count.token).copied().flatten();
            }
            job.set_phase(JobPhase::Done(Box::new(AnalysisResult {
                messages_analyzed: aggregates.messages,
                next_offset: outcome.next_offset,
                truncated_reason: outcome.truncated_reason,
                duration_ms: outcome.duration_ms,
                aggregates,
            })));
        }
        Err(e) => {
            tracing::warn!(job_id = %job.id, error = %e, "analysis job failed");
            job.set_phase(JobPhase::Failed(format!("{e:#}")));
        }
    }
}

/// Resolve the fetch range for a request. An explicit `start_offset` wins;
/// otherwise `committed` mode starts at the group's committed offset (falling
/// back to the low watermark when the group never committed) and `tail` mode
/// starts `count` messages before the high watermark. Everything is clamped
/// to the retained `[low, high]` range.
fn resolve_offsets(
    mode: AnalysisMode,
    explicit_start: Option<i64>,
    count: u64,
    bounds: PartitionBounds,
) -> (i64, i64) {
    let low = bounds.low_watermark;
    let high = bounds.high_watermark;
    let start = match (explicit_start, mode) {
        (Some(start), _) => start,
        (None, AnalysisMode::Committed) => bounds.committed_offset.unwrap_or(low),
        (None, AnalysisMode::Tail) => high.saturating_sub(count as i64),
    }
    .clamp(low, high);
    let end = (start + count as i64).min(high);
    (start, end)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bounds(low: i64, high: i64, committed: Option<i64>) -> PartitionBounds {
        PartitionBounds {
            low_watermark: low,
            high_watermark: high,
            committed_offset: committed,
        }
    }

    #[test]
    fn committed_mode_starts_at_committed_offset() {
        let (start, end) = resolve_offsets(
            AnalysisMode::Committed,
            None,
            100,
            bounds(0, 1000, Some(400)),
        );
        assert_eq!((start, end), (400, 500));
    }

    #[test]
    fn committed_mode_falls_back_to_low_watermark() {
        let (start, end) =
            resolve_offsets(AnalysisMode::Committed, None, 100, bounds(50, 1000, None));
        assert_eq!((start, end), (50, 150));
    }

    #[test]
    fn tail_mode_samples_before_high_watermark() {
        let (start, end) =
            resolve_offsets(AnalysisMode::Tail, None, 100, bounds(0, 1000, Some(400)));
        assert_eq!((start, end), (900, 1000));
    }

    #[test]
    fn tail_mode_clamps_to_low_watermark() {
        let (start, end) = resolve_offsets(AnalysisMode::Tail, None, 500, bounds(700, 1000, None));
        assert_eq!((start, end), (700, 1000));
    }

    #[test]
    fn explicit_start_offset_wins_and_is_clamped() {
        let (start, end) = resolve_offsets(
            AnalysisMode::Committed,
            Some(5),
            100,
            bounds(10, 1000, Some(400)),
        );
        assert_eq!((start, end), (10, 110));
    }

    #[test]
    fn range_is_clamped_to_high_watermark() {
        let (start, end) = resolve_offsets(
            AnalysisMode::Committed,
            None,
            10_000,
            bounds(0, 100, Some(40)),
        );
        assert_eq!((start, end), (40, 100));
    }

    #[test]
    fn committed_at_high_watermark_yields_empty_range() {
        let (start, end) = resolve_offsets(
            AnalysisMode::Committed,
            None,
            100,
            bounds(0, 100, Some(100)),
        );
        assert_eq!((start, end), (100, 100));
    }
}
