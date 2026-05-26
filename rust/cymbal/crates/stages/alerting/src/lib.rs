//! Cymbal alerting stage crate.
//!
//! This crate owns spike-detection business logic and stage orchestration behind
//! explicit dependencies. Signal emission is intentionally represented as an
//! `AlertingSideEffects` hook, so runtime/notification wiring can decide how to
//! emit signals without making alerting depend on HTTP clients or tokenizers.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use async_trait::async_trait;
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use common_redis::Client;
use cymbal_core::{
    run_buffered, PipelineStage, StageConcurrencyLimiter, StageError, StageInput, StagePayload,
    StageType,
};
use cymbal_domain::{EventResult, ExceptionProcessingOptions, OutputErrProps};
use cymbal_repositories::Issue;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

pub const ALERTING_STAGE_ID: &str = "alerting:v1";
pub const ALERTING_STAGE_TYPE: StageType = StageType {
    namespace: "cymbal.stage",
    name: "alerting",
    version: 1,
};

const ISSUE_BUCKET_TTL_SECONDS: usize = 60 * 60;
const ISSUE_BUCKET_INTERVAL_MINUTES: i64 = 5;
const NUM_BUCKETS: usize = 12;
const MIN_HISTORICAL_BUCKETS_FOR_ISSUE_BASELINE: usize = 1;

const SPIKE_ACQUIRE_LOCKS_TIME: &str = "cymbal_spike_acquire_locks_time";
const SPIKE_EMIT_EVENTS_TIME: &str = "cymbal_spike_emit_events_time";
const SPIKE_GET_SPIKING_ISSUES_TIME: &str = "cymbal_spike_get_spiking_issues_time";
const SPIKE_INCREMENT_ISSUE_BUCKETS_TIME: &str = "cymbal_spike_increment_issue_buckets_time";
const SPIKE_INCREMENT_TEAM_BUCKETS_TIME: &str = "cymbal_spike_increment_team_buckets_time";
const SPIKE_ISSUES_BLOCKED_BY_COOLDOWN: &str = "cymbal_spike_issues_blocked_by_cooldown";
const SPIKE_ISSUES_CHECKED: &str = "cymbal_spike_issues_checked";
const SPIKE_ISSUES_SPIKING: &str = "cymbal_spike_issues_spiking";

const DEFAULT_SPIKE_MULTIPLIER: f64 = 10.0;
const DEFAULT_MIN_SPIKE_THRESHOLD: i64 = 500;
const DEFAULT_SPIKE_ALERT_COOLDOWN_SECONDS: usize = 10 * 60;
const DEFAULT_ALERTING_STAGE_CONCURRENCY: usize = 4;
const DEFAULT_ALERTING_STAGE_BATCH_SIZE: usize = 500;

#[derive(Debug, Clone, PartialEq)]
pub struct SpikeDetectionConfig {
    pub multiplier: f64,
    pub threshold: i64,
    pub snooze_duration_seconds: usize,
}

impl Default for SpikeDetectionConfig {
    fn default() -> Self {
        Self {
            multiplier: DEFAULT_SPIKE_MULTIPLIER,
            threshold: DEFAULT_MIN_SPIKE_THRESHOLD,
            snooze_duration_seconds: DEFAULT_SPIKE_ALERT_COOLDOWN_SECONDS,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SpikeAlertInput {
    pub issue: Issue,
    pub props: Option<OutputErrProps>,
}

#[derive(Debug, Clone)]
pub struct SpikingIssue {
    pub issue: Issue,
    pub props: OutputErrProps,
    pub computed_baseline: f64,
    pub current_bucket_value: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AlertingEvent {
    pub result: EventResult,
    pub spike_alert_input: Option<SpikeAlertInput>,
}

impl StagePayload for AlertingEvent {
    const TYPE: StageType = StageType {
        namespace: "cymbal.alerting",
        name: "AlertingEvent",
        version: 1,
    };
}

#[derive(Debug, Error)]
pub enum AlertingError {
    #[error("redis error: {0}")]
    Redis(#[from] common_redis::CustomRedisError),
    #[error("repository error: {0}")]
    Repository(String),
    #[error("side effect error: {0}")]
    SideEffect(String),
}

#[async_trait]
pub trait SpikeConfigRepository: Send + Sync {
    async fn spike_detection_configs(
        &self,
        team_ids: Vec<i32>,
    ) -> Result<HashMap<i32, SpikeDetectionConfig>, AlertingError>;
}

#[async_trait]
pub trait AlertingSideEffects: Send + Sync {
    async fn persist_spike_event(
        &self,
        _spike: &SpikingIssue,
        _detected_at: DateTime<Utc>,
    ) -> Result<(), AlertingError> {
        Ok(())
    }

    async fn emit_issue_spiking_signal(&self, _spike: &SpikingIssue) -> Result<(), AlertingError> {
        Ok(())
    }

    async fn emit_internal_spiking_event(
        &self,
        _spike: &SpikingIssue,
    ) -> Result<(), AlertingError> {
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct DefaultSpikeConfigRepository;

#[async_trait]
impl SpikeConfigRepository for DefaultSpikeConfigRepository {
    async fn spike_detection_configs(
        &self,
        team_ids: Vec<i32>,
    ) -> Result<HashMap<i32, SpikeDetectionConfig>, AlertingError> {
        Ok(team_ids
            .into_iter()
            .map(|team_id| (team_id, SpikeDetectionConfig::default()))
            .collect())
    }
}

#[derive(Debug, Default)]
pub struct NoopAlertingSideEffects;

#[async_trait]
impl AlertingSideEffects for NoopAlertingSideEffects {}

#[derive(Clone)]
pub struct AlertingDeps {
    pub redis: Arc<dyn Client + Send + Sync>,
    pub spike_config_repository: Arc<dyn SpikeConfigRepository>,
    pub side_effects: Arc<dyn AlertingSideEffects>,
    pub enabled_team_ids: Option<HashSet<i32>>,
}

impl std::fmt::Debug for AlertingDeps {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AlertingDeps")
            .field("redis", &"<dyn Client>")
            .field("spike_config_repository", &"<dyn SpikeConfigRepository>")
            .field("side_effects", &"<dyn AlertingSideEffects>")
            .field("enabled_team_ids", &self.enabled_team_ids)
            .finish()
    }
}

impl AlertingDeps {
    pub fn new(redis: Arc<dyn Client + Send + Sync>) -> Self {
        Self {
            redis,
            spike_config_repository: Arc::new(DefaultSpikeConfigRepository),
            side_effects: Arc::new(NoopAlertingSideEffects),
            enabled_team_ids: None,
        }
    }

    pub fn with_spike_config_repository(
        mut self,
        spike_config_repository: Arc<dyn SpikeConfigRepository>,
    ) -> Self {
        self.spike_config_repository = spike_config_repository;
        self
    }

    pub fn with_side_effects(mut self, side_effects: Arc<dyn AlertingSideEffects>) -> Self {
        self.side_effects = side_effects;
        self
    }

    pub fn with_enabled_team_ids(mut self, enabled_team_ids: Option<HashSet<i32>>) -> Self {
        self.enabled_team_ids = enabled_team_ids;
        self
    }
}

#[derive(Debug, Clone)]
pub struct AlertingStage {
    deps: Option<AlertingDeps>,
    stage_concurrency_limiter: StageConcurrencyLimiter,
    stage_batch_size: usize,
}

impl Default for AlertingStage {
    fn default() -> Self {
        Self::new()
    }
}

impl AlertingStage {
    pub fn new() -> Self {
        Self {
            deps: None,
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_ALERTING_STAGE_CONCURRENCY,
            ),
            stage_batch_size: DEFAULT_ALERTING_STAGE_BATCH_SIZE,
        }
    }

    pub fn with_deps(deps: AlertingDeps) -> Self {
        Self {
            deps: Some(deps),
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_ALERTING_STAGE_CONCURRENCY,
            ),
            stage_batch_size: DEFAULT_ALERTING_STAGE_BATCH_SIZE,
        }
    }

    /// Cap the number of concurrent spike-detection folds running through this
    /// stage on the pod. Alerting is a batch-fold stage, so each permit covers
    /// one chunk of up to `stage_batch_size` events rather than one event.
    pub fn with_stage_concurrency(mut self, stage_concurrency: usize) -> Self {
        self.stage_concurrency_limiter = StageConcurrencyLimiter::new(stage_concurrency);
        self
    }

    /// Set the ideal number of events per spike-detection fold. Larger stage
    /// inputs are split into chunks of this size before being processed.
    pub fn with_stage_batch_size(mut self, stage_batch_size: usize) -> Self {
        self.stage_batch_size = stage_batch_size.max(1);
        self
    }

    async fn process_events(
        &self,
        events: Vec<AlertingEvent>,
        processing_options: ExceptionProcessingOptions,
    ) -> Result<Vec<EventResult>, StageError> {
        if let Some(deps) = &self.deps {
            let inputs = events
                .iter()
                .filter_map(|event| event.spike_alert_input.clone())
                .collect();
            run_spike_detection_for_inputs(deps.clone(), inputs, processing_options)
                .await
                .map_err(alerting_error_to_stage_error)?;
        }

        Ok(events.into_iter().map(|event| event.result).collect())
    }
}

#[async_trait]
impl PipelineStage for AlertingStage {
    type Input = AlertingEvent;
    type Output = EventResult;

    fn id(&self) -> StageType {
        ALERTING_STAGE_TYPE
    }

    async fn process(
        &self,
        input: StageInput<Self::Input>,
    ) -> Result<Vec<Self::Output>, StageError> {
        let stage = self.clone();
        let processing_options = ExceptionProcessingOptions::from_metadata(&input.context.metadata);
        let chunks = input
            .items
            .chunks(self.stage_batch_size.max(1))
            .map(<[AlertingEvent]>::to_vec)
            .collect::<Vec<_>>();

        let chunk_outputs = run_buffered(&self.stage_concurrency_limiter, chunks, move |events| {
            let stage = stage.clone();
            async move { stage.process_events(events, processing_options).await }
        })
        .await?;

        Ok(chunk_outputs.into_iter().flatten().collect())
    }
}

pub async fn run_spike_detection_for_inputs(
    deps: AlertingDeps,
    inputs: Vec<SpikeAlertInput>,
    processing_options: ExceptionProcessingOptions,
) -> Result<(), AlertingError> {
    if inputs.is_empty() {
        return Ok(());
    }

    let mut issue_counts: HashMap<Uuid, u32> = HashMap::new();
    let mut issue_props_by_id: HashMap<Uuid, OutputErrProps> = HashMap::new();
    let mut issues_by_id: HashMap<Uuid, Issue> = HashMap::new();

    for input in inputs {
        let issue_id = input.issue.id;
        *issue_counts.entry(issue_id).or_insert(0) += 1;
        if let Some(props) = input.props {
            issue_props_by_id.entry(issue_id).or_insert(props);
        }
        issues_by_id.insert(issue_id, input.issue);
    }

    do_spike_detection(
        deps,
        issues_by_id,
        issue_props_by_id,
        issue_counts,
        processing_options,
    )
    .await
}

pub async fn do_spike_detection(
    deps: AlertingDeps,
    issues_by_id: HashMap<Uuid, Issue>,
    issue_props_by_id: HashMap<Uuid, OutputErrProps>,
    issue_counts: HashMap<Uuid, u32>,
    processing_options: ExceptionProcessingOptions,
) -> Result<(), AlertingError> {
    if issue_counts.is_empty() {
        return Ok(());
    }

    let issues_by_id = match &deps.enabled_team_ids {
        Some(ids) => issues_by_id
            .into_iter()
            .filter(|(_, issue)| ids.contains(&issue.team_id))
            .collect(),
        None => issues_by_id,
    };

    if issues_by_id.is_empty() {
        return Ok(());
    }

    let issue_counts = issue_counts
        .into_iter()
        .filter(|(id, _)| issues_by_id.contains_key(id))
        .collect::<HashMap<_, _>>();
    let team_ids = issues_by_id
        .values()
        .map(|issue| issue.team_id)
        .collect::<HashSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let team_configs = deps
        .spike_config_repository
        .spike_detection_configs(team_ids)
        .await?;

    let issue_buckets_timer = common_metrics::timing_guard(SPIKE_INCREMENT_ISSUE_BUCKETS_TIME, &[]);
    try_increment_issue_buckets(&*deps.redis, &issue_counts).await;
    issue_buckets_timer.fin();

    let team_buckets_timer = common_metrics::timing_guard(SPIKE_INCREMENT_TEAM_BUCKETS_TIME, &[]);
    try_increment_team_buckets(&*deps.redis, &issues_by_id, &issue_counts).await;
    team_buckets_timer.fin();

    metrics::counter!(SPIKE_ISSUES_CHECKED).increment(issues_by_id.len() as u64);

    let get_spiking_timer = common_metrics::timing_guard(SPIKE_GET_SPIKING_ISSUES_TIME, &[]);
    let spiking = get_spiking_issues(
        &*deps.redis,
        &issues_by_id,
        &issue_props_by_id,
        &team_configs,
    )
    .await;
    get_spiking_timer.fin();
    let spiking = spiking?;

    metrics::counter!(SPIKE_ISSUES_SPIKING).increment(spiking.len() as u64);
    emit_spiking_events(&deps, spiking, &team_configs, processing_options).await;

    Ok(())
}

fn issue_bucket_key(issue_id: &Uuid, timestamp: &str) -> String {
    format!("issue-buckets:{issue_id}-{timestamp}")
}

fn team_bucket_key(team_id: i32, timestamp: &str) -> String {
    format!("team-buckets:{team_id}-{timestamp}")
}

fn team_issue_set_key(team_id: i32, timestamp: &str) -> String {
    format!("team-issue-set:{team_id}-{timestamp}")
}

fn cooldown_key(issue_id: &Uuid) -> String {
    format!("spike-cooldown:{issue_id}")
}

fn round_datetime_to_minutes(datetime: DateTime<Utc>, minutes: i64) -> DateTime<Utc> {
    assert!(minutes > 0, "minutes must be > 0");
    let bucket_seconds = minutes * 60;
    let now_ts = datetime.timestamp();
    let rounded_ts = now_ts - now_ts.rem_euclid(bucket_seconds);
    DateTime::<Utc>::from_timestamp(rounded_ts, 0).expect("rounded timestamp is always valid")
}

fn get_rounded_to_minutes(datetime: DateTime<Utc>, minutes: i64) -> String {
    round_datetime_to_minutes(datetime, minutes).to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn get_now_rounded_to_minutes(minutes: i64) -> String {
    get_rounded_to_minutes(Utc::now(), minutes)
}

async fn try_increment_issue_buckets(
    redis: &(dyn Client + Send + Sync),
    issue_counts: &HashMap<Uuid, u32>,
) {
    if issue_counts.is_empty() {
        return;
    }

    let now_rounded_to_minutes = get_now_rounded_to_minutes(ISSUE_BUCKET_INTERVAL_MINUTES);
    let items = issue_counts
        .iter()
        .map(|(issue_id, count)| {
            (
                issue_bucket_key(issue_id, &now_rounded_to_minutes),
                *count as i64,
            )
        })
        .collect();

    if let Err(err) = redis
        .batch_incr_by_expire_nx(items, ISSUE_BUCKET_TTL_SECONDS)
        .await
    {
        tracing::warn!("Failed to increment issue buckets batch: {err}");
    }
}

async fn try_increment_team_buckets(
    redis: &(dyn Client + Send + Sync),
    issues_by_id: &HashMap<Uuid, Issue>,
    issue_counts: &HashMap<Uuid, u32>,
) {
    if issue_counts.is_empty() {
        return;
    }

    let now_rounded_to_minutes = get_now_rounded_to_minutes(ISSUE_BUCKET_INTERVAL_MINUTES);
    let team_counts = issue_counts
        .iter()
        .fold(HashMap::new(), |mut counts, (issue_id, count)| {
            if let Some(issue) = issues_by_id.get(issue_id) {
                *counts.entry(issue.team_id).or_insert(0) += count;
            }
            counts
        });

    let items = team_counts
        .iter()
        .map(|(team_id, count)| {
            (
                team_bucket_key(*team_id, &now_rounded_to_minutes),
                *count as i64,
            )
        })
        .collect();

    if let Err(err) = redis
        .batch_incr_by_expire_nx(items, ISSUE_BUCKET_TTL_SECONDS)
        .await
    {
        tracing::warn!("Failed to increment team buckets batch: {err}");
    }

    let issue_set_items = issue_counts
        .keys()
        .filter_map(|issue_id| {
            let issue = issues_by_id.get(issue_id)?;
            Some((
                team_issue_set_key(issue.team_id, &now_rounded_to_minutes),
                issue_id.to_string(),
            ))
        })
        .collect();

    if let Err(err) = redis
        .batch_sadd_expire(issue_set_items, ISSUE_BUCKET_TTL_SECONDS)
        .await
    {
        tracing::warn!("Failed to add issues to team sets: {err}");
    }
}

async fn acquire_cooldown_locks(
    redis: &(dyn Client + Send + Sync),
    items: &[(String, usize)],
) -> Result<Vec<bool>, common_redis::CustomRedisError> {
    redis
        .batch_set_nx_ex(
            items
                .iter()
                .map(|(key, ttl)| (key.clone(), "1".to_string(), *ttl))
                .collect(),
        )
        .await
}

async fn emit_spiking_events(
    deps: &AlertingDeps,
    spiking: Vec<SpikingIssue>,
    team_configs: &HashMap<i32, SpikeDetectionConfig>,
    processing_options: ExceptionProcessingOptions,
) {
    if spiking.is_empty() {
        return;
    }

    let locks_timer = common_metrics::timing_guard(SPIKE_ACQUIRE_LOCKS_TIME, &[]);
    let (spiking, cooldown_items): (Vec<SpikingIssue>, Vec<(String, usize)>) = spiking
        .into_iter()
        .map(|spike| {
            let config = team_configs
                .get(&spike.issue.team_id)
                .expect("team config always present - verified in get_spiking_issues");
            let key = cooldown_key(&spike.issue.id);
            (spike, (key, config.snooze_duration_seconds))
        })
        .unzip();

    let lock_results = match acquire_cooldown_locks(&*deps.redis, &cooldown_items).await {
        Ok(results) => results,
        Err(error) => {
            locks_timer.fin();
            tracing::warn!("Failed to acquire spike cooldown locks: {error}");
            return;
        }
    };

    let blocked_count = lock_results.iter().filter(|&&acquired| !acquired).count();
    metrics::counter!(SPIKE_ISSUES_BLOCKED_BY_COOLDOWN).increment(blocked_count as u64);

    let acquired_locks = spiking
        .into_iter()
        .zip(lock_results)
        .filter_map(|(spike, acquired)| acquired.then_some(spike))
        .collect::<Vec<_>>();
    locks_timer.fin();

    if acquired_locks.is_empty() {
        return;
    }

    let emit_timer = common_metrics::timing_guard(SPIKE_EMIT_EVENTS_TIME, &[]);
    let mut failed_keys = Vec::new();
    for spike in &acquired_locks {
        let detected_at = Utc::now();
        let result = async {
            deps.side_effects
                .persist_spike_event(spike, detected_at)
                .await?;
            if processing_options.emit_signals {
                deps.side_effects.emit_issue_spiking_signal(spike).await?;
            }
            if processing_options.emit_internal_events {
                deps.side_effects.emit_internal_spiking_event(spike).await?;
            }
            Result::<(), AlertingError>::Ok(())
        }
        .await;
        if let Err(error) = result {
            tracing::warn!("Failed to emit spiking event: {error}");
            failed_keys.push(cooldown_key(&spike.issue.id));
        }
    }

    if !failed_keys.is_empty() {
        if let Err(error) = deps.redis.batch_del(failed_keys).await {
            tracing::warn!("Failed to release cooldown locks after alerting failure: {error}");
        }
    }
    emit_timer.fin();
}

fn get_bucket_timestamps() -> Vec<String> {
    let now = Utc::now();
    (0..NUM_BUCKETS)
        .map(|i| {
            let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
            get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES)
        })
        .collect()
}

fn compute_team_baseline(exception_values: &[Option<i64>], issue_counts: &[u64]) -> f64 {
    let bucket_rates = exception_values
        .iter()
        .zip(issue_counts.iter())
        .filter_map(|(exceptions_opt, &issue_count)| {
            let exceptions = (*exceptions_opt)?;
            if issue_count > 0 {
                Some(exceptions as f64 / issue_count as f64)
            } else {
                None
            }
        })
        .collect::<Vec<_>>();

    if bucket_rates.is_empty() {
        0.0
    } else {
        bucket_rates.iter().sum::<f64>() / bucket_rates.len() as f64
    }
}

fn compute_issue_baseline(historical_buckets: &[Option<i64>], team_baseline: f64) -> f64 {
    let non_empty_count = historical_buckets
        .iter()
        .filter(|value| value.is_some())
        .count();

    if non_empty_count >= MIN_HISTORICAL_BUCKETS_FOR_ISSUE_BASELINE {
        let sum: i64 = historical_buckets.iter().filter_map(|value| *value).sum();
        sum as f64 / non_empty_count as f64
    } else {
        team_baseline
    }
}

fn is_spiking(current_value: i64, baseline: f64, config: &SpikeDetectionConfig) -> bool {
    if current_value < config.threshold {
        return false;
    }
    current_value as f64 > baseline * config.multiplier
}

async fn get_spiking_issues(
    redis: &(dyn Client + Send + Sync),
    issues_by_id: &HashMap<Uuid, Issue>,
    issue_props_by_id: &HashMap<Uuid, OutputErrProps>,
    team_configs: &HashMap<i32, SpikeDetectionConfig>,
) -> Result<Vec<SpikingIssue>, AlertingError> {
    if issues_by_id.is_empty() {
        return Ok(Vec::new());
    }

    let issue_ids = issues_by_id.keys().copied().collect::<Vec<_>>();
    let bucket_timestamps = get_bucket_timestamps();
    let unique_team_ids = issues_by_id
        .values()
        .map(|issue| issue.team_id)
        .collect::<HashSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();

    let (issue_buckets, team_buckets) =
        fetch_bucket_data(redis, &issue_ids, &unique_team_ids, &bucket_timestamps).await?;
    let team_baselines = compute_team_baselines(&team_buckets);

    let mut spiking = Vec::new();
    for bucket in &issue_buckets {
        let Some(issue) = issues_by_id.get(&bucket.issue_id) else {
            continue;
        };

        let current_value = bucket.values[0].unwrap_or(0);
        let historical = &bucket.values[1..];
        let team_baseline = *team_baselines.get(&issue.team_id).unwrap_or(&0.0);
        let baseline = compute_issue_baseline(historical, team_baseline);
        let config = team_configs.get(&issue.team_id).ok_or_else(|| {
            AlertingError::Repository(format!(
                "No spike detection config for team {}",
                issue.team_id
            ))
        })?;

        if is_spiking(current_value, baseline, config) {
            spiking.push(SpikingIssue {
                issue: issue.clone(),
                props: issue_props_by_id
                    .get(&bucket.issue_id)
                    .cloned()
                    .unwrap_or_default(),
                computed_baseline: baseline,
                current_bucket_value: current_value,
            });
        }
    }

    Ok(spiking)
}

struct IssueBuckets {
    issue_id: Uuid,
    values: Vec<Option<i64>>,
}

struct TeamBuckets {
    team_id: i32,
    exception_counts: Vec<Option<i64>>,
    unique_issue_counts: Vec<u64>,
}

async fn fetch_bucket_data(
    redis: &(dyn Client + Send + Sync),
    issue_ids: &[Uuid],
    team_ids: &[i32],
    timestamps: &[String],
) -> Result<(Vec<IssueBuckets>, Vec<TeamBuckets>), common_redis::CustomRedisError> {
    let issue_keys = issue_ids
        .iter()
        .flat_map(|id| {
            timestamps
                .iter()
                .map(move |timestamp| issue_bucket_key(id, timestamp))
        })
        .collect::<Vec<_>>();
    let team_bucket_keys = team_ids
        .iter()
        .flat_map(|id| {
            timestamps
                .iter()
                .map(move |timestamp| team_bucket_key(*id, timestamp))
        })
        .collect::<Vec<_>>();
    let team_issue_set_keys = team_ids
        .iter()
        .flat_map(|id| {
            timestamps
                .iter()
                .map(move |timestamp| team_issue_set_key(*id, timestamp))
        })
        .collect::<Vec<_>>();

    let all_keys = issue_keys.into_iter().chain(team_bucket_keys).collect();
    let all_values = redis.mget(all_keys).await?;
    let team_issue_counts = redis.scard_multiple(team_issue_set_keys).await?;
    let all_values = all_values
        .into_iter()
        .map(|value| value.and_then(|bytes| std::str::from_utf8(&bytes).ok()?.parse().ok()))
        .collect::<Vec<_>>();

    let bucket_count = timestamps.len();
    let issue_buckets = issue_ids
        .iter()
        .enumerate()
        .map(|(index, id)| {
            let start = index * bucket_count;
            IssueBuckets {
                issue_id: *id,
                values: all_values[start..start + bucket_count].to_vec(),
            }
        })
        .collect::<Vec<_>>();

    let team_buckets = team_ids
        .iter()
        .enumerate()
        .map(|(index, id)| {
            let start = index * bucket_count;
            let values_start = issue_ids.len() * bucket_count + start;
            TeamBuckets {
                team_id: *id,
                exception_counts: all_values[values_start..values_start + bucket_count].to_vec(),
                unique_issue_counts: team_issue_counts[start..start + bucket_count].to_vec(),
            }
        })
        .collect::<Vec<_>>();

    Ok((issue_buckets, team_buckets))
}

fn compute_team_baselines(team_buckets: &[TeamBuckets]) -> HashMap<i32, f64> {
    team_buckets
        .iter()
        .map(|bucket| {
            let historical_exceptions = if bucket.exception_counts.len() > 1 {
                &bucket.exception_counts[1..]
            } else {
                &bucket.exception_counts[..]
            };
            let historical_issue_counts = if bucket.unique_issue_counts.len() > 1 {
                &bucket.unique_issue_counts[1..]
            } else {
                &bucket.unique_issue_counts[..]
            };
            (
                bucket.team_id,
                compute_team_baseline(historical_exceptions, historical_issue_counts),
            )
        })
        .collect()
}

fn alerting_error_to_stage_error(error: AlertingError) -> StageError {
    StageError::Transient(error.to_string())
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use chrono::TimeZone;
    use common_redis::{CustomRedisError, MockRedisClient};
    use cymbal_core::{BatchContext, Metadata, StageError};
    use cymbal_domain::EventOutcome;

    use super::*;

    struct FailingPersistSideEffects;

    #[async_trait]
    impl AlertingSideEffects for FailingPersistSideEffects {
        async fn persist_spike_event(
            &self,
            _spike: &SpikingIssue,
            _detected_at: DateTime<Utc>,
        ) -> Result<(), AlertingError> {
            Err(AlertingError::SideEffect(
                "persist_spike_event intentionally failed".to_string(),
            ))
        }
    }

    fn bytes(value: i64) -> Vec<u8> {
        value.to_string().into_bytes()
    }

    #[derive(Default)]
    struct StaticSpikeConfigRepository {
        configs: HashMap<i32, SpikeDetectionConfig>,
    }

    #[async_trait]
    impl SpikeConfigRepository for StaticSpikeConfigRepository {
        async fn spike_detection_configs(
            &self,
            team_ids: Vec<i32>,
        ) -> Result<HashMap<i32, SpikeDetectionConfig>, AlertingError> {
            Ok(team_ids
                .into_iter()
                .map(|team_id| {
                    (
                        team_id,
                        self.configs.get(&team_id).cloned().unwrap_or_default(),
                    )
                })
                .collect())
        }
    }

    #[derive(Default)]
    struct RecordingSideEffects {
        persisted: Mutex<Vec<Uuid>>,
        signals: Mutex<Vec<Uuid>>,
        internal_events: Mutex<Vec<Uuid>>,
    }

    #[async_trait]
    impl AlertingSideEffects for RecordingSideEffects {
        async fn persist_spike_event(
            &self,
            spike: &SpikingIssue,
            _detected_at: DateTime<Utc>,
        ) -> Result<(), AlertingError> {
            self.persisted.lock().unwrap().push(spike.issue.id);
            Ok(())
        }

        async fn emit_issue_spiking_signal(
            &self,
            spike: &SpikingIssue,
        ) -> Result<(), AlertingError> {
            self.signals.lock().unwrap().push(spike.issue.id);
            Ok(())
        }

        async fn emit_internal_spiking_event(
            &self,
            spike: &SpikingIssue,
        ) -> Result<(), AlertingError> {
            self.internal_events.lock().unwrap().push(spike.issue.id);
            Ok(())
        }
    }

    fn make_issue(issue_id: Uuid, team_id: i32) -> Issue {
        Issue {
            id: issue_id,
            team_id,
            status: cymbal_repositories::IssueStatus::Active,
            name: Some("Test Issue".to_string()),
            description: Some("Test Description".to_string()),
            created_at: Utc::now(),
        }
    }

    fn setup_issue_buckets(redis: &mut MockRedisClient, issue_id: Uuid, values: &[Option<i64>]) {
        let now = Utc::now();
        for index in 0..NUM_BUCKETS {
            let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * index as i64);
            let timestamp = get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES);
            let key = issue_bucket_key(&issue_id, &timestamp);
            redis.mget_ret(&key, values.get(index).copied().flatten().map(bytes));
        }
    }

    fn setup_team_buckets(
        redis: &mut MockRedisClient,
        team_id: i32,
        exception_values: &[Option<i64>],
        issue_counts: &[u64],
    ) {
        let now = Utc::now();
        for index in 0..NUM_BUCKETS {
            let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * index as i64);
            let timestamp = get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES);
            let bucket_key = team_bucket_key(team_id, &timestamp);
            redis.mget_ret(
                &bucket_key,
                exception_values.get(index).copied().flatten().map(bytes),
            );
            let issue_set_key = team_issue_set_key(team_id, &timestamp);
            redis.scard_ret(
                &issue_set_key,
                Ok(issue_counts.get(index).copied().unwrap_or(0)),
            );
        }
    }

    #[test]
    fn rounding_floors_to_interval() {
        let datetime = Utc.with_ymd_and_hms(2025, 12, 16, 12, 34, 56).unwrap();

        assert_eq!(get_rounded_to_minutes(datetime, 5), "2025-12-16T12:30:00Z");
    }

    #[test]
    fn computes_issue_baseline_when_history_exists() {
        assert_eq!(
            compute_issue_baseline(&[Some(10), Some(20), None], 100.0),
            15.0
        );
    }

    #[test]
    fn falls_back_to_team_baseline_without_issue_history() {
        assert_eq!(compute_issue_baseline(&[None, None], 42.0), 42.0);
    }

    #[test]
    fn detects_spike_only_above_threshold_and_multiplier() {
        let config = SpikeDetectionConfig {
            multiplier: 2.0,
            threshold: 10,
            snooze_duration_seconds: 60,
        };

        for (current, baseline, expected) in [(21, 10.0, true), (20, 10.0, false), (9, 1.0, false)]
        {
            assert_eq!(is_spiking(current, baseline, &config), expected);
        }
    }

    #[tokio::test]
    async fn spike_detection_emits_side_effects_for_spiking_issue() {
        let mut redis = MockRedisClient::new();
        let issue_id = Uuid::now_v7();
        let team_id = 1;
        setup_issue_buckets(&mut redis, issue_id, &[Some(30), Some(1), Some(1)]);
        setup_team_buckets(
            &mut redis,
            team_id,
            &[Some(30), Some(1), Some(1)],
            &[1, 1, 1],
        );
        redis.batch_incr_by_expire_nx_ret(Ok(()));
        redis.set_nx_ex_ret(&cooldown_key(&issue_id), Ok(true));
        let redis = Arc::new(redis);

        let side_effects = Arc::new(RecordingSideEffects::default());
        let deps = AlertingDeps::new(redis)
            .with_spike_config_repository(Arc::new(StaticSpikeConfigRepository {
                configs: HashMap::from([(
                    team_id,
                    SpikeDetectionConfig {
                        multiplier: 2.0,
                        threshold: 10,
                        snooze_duration_seconds: 60,
                    },
                )]),
            }))
            .with_side_effects(side_effects.clone());

        run_spike_detection_for_inputs(
            deps,
            vec![SpikeAlertInput {
                issue: make_issue(issue_id, team_id),
                props: None,
            }],
            ExceptionProcessingOptions::default(),
        )
        .await
        .unwrap();

        assert_eq!(&*side_effects.persisted.lock().unwrap(), &vec![issue_id]);
        assert_eq!(&*side_effects.signals.lock().unwrap(), &vec![issue_id]);
        assert_eq!(
            &*side_effects.internal_events.lock().unwrap(),
            &vec![issue_id]
        );
    }

    #[tokio::test]
    async fn processing_options_can_disable_alerting_signals_and_internal_events() {
        let mut redis = MockRedisClient::new();
        let issue_id = Uuid::now_v7();
        let team_id = 1;
        setup_issue_buckets(&mut redis, issue_id, &[Some(30), Some(1), Some(1)]);
        setup_team_buckets(
            &mut redis,
            team_id,
            &[Some(30), Some(1), Some(1)],
            &[1, 1, 1],
        );
        redis.batch_incr_by_expire_nx_ret(Ok(()));
        redis.set_nx_ex_ret(&cooldown_key(&issue_id), Ok(true));
        let redis = Arc::new(redis);

        let side_effects = Arc::new(RecordingSideEffects::default());
        let deps = AlertingDeps::new(redis)
            .with_spike_config_repository(Arc::new(StaticSpikeConfigRepository {
                configs: HashMap::from([(
                    team_id,
                    SpikeDetectionConfig {
                        multiplier: 2.0,
                        threshold: 10,
                        snooze_duration_seconds: 60,
                    },
                )]),
            }))
            .with_side_effects(side_effects.clone());

        run_spike_detection_for_inputs(
            deps,
            vec![SpikeAlertInput {
                issue: make_issue(issue_id, team_id),
                props: None,
            }],
            ExceptionProcessingOptions {
                emit_internal_events: false,
                emit_signals: false,
                ..Default::default()
            },
        )
        .await
        .unwrap();

        assert_eq!(&*side_effects.persisted.lock().unwrap(), &vec![issue_id]);
        assert!(side_effects.signals.lock().unwrap().is_empty());
        assert!(side_effects.internal_events.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn alerting_stage_chunks_large_batches_and_preserves_order() {
        let stage = AlertingStage::new()
            .with_stage_batch_size(2)
            .with_stage_concurrency(1);
        let results = (0..5)
            .map(|index| EventResult {
                event_id: format!("event-{index}"),
                outcome: EventOutcome::Next {
                    properties: None,
                    metadata: Metadata::new(),
                },
            })
            .collect::<Vec<_>>();
        let input = StageInput::from_items(
            BatchContext {
                batch_id: "batch".to_string(),
                metadata: Metadata::new(),
            },
            results
                .iter()
                .cloned()
                .map(|result| AlertingEvent {
                    result,
                    spike_alert_input: None,
                })
                .collect(),
        );

        let output: Vec<EventResult> = stage.process(input).await.unwrap();

        assert_eq!(output, results);
    }

    #[tokio::test]
    async fn alerting_stage_runs_detection_and_returns_original_results() {
        let mut redis = MockRedisClient::new();
        let issue_id = Uuid::now_v7();
        let team_id = 1;
        setup_issue_buckets(&mut redis, issue_id, &[Some(30), Some(1), Some(1)]);
        setup_team_buckets(
            &mut redis,
            team_id,
            &[Some(30), Some(1), Some(1)],
            &[1, 1, 1],
        );
        redis.batch_incr_by_expire_nx_ret(Ok(()));
        redis.set_nx_ex_ret(&cooldown_key(&issue_id), Ok(true));
        let redis = Arc::new(redis);

        let side_effects = Arc::new(RecordingSideEffects::default());
        let stage = AlertingStage::with_deps(
            AlertingDeps::new(redis)
                .with_spike_config_repository(Arc::new(StaticSpikeConfigRepository {
                    configs: HashMap::from([(
                        team_id,
                        SpikeDetectionConfig {
                            multiplier: 2.0,
                            threshold: 10,
                            snooze_duration_seconds: 60,
                        },
                    )]),
                }))
                .with_side_effects(side_effects.clone()),
        );
        let result = EventResult {
            event_id: "event-1".to_string(),
            outcome: EventOutcome::Next {
                properties: None,
                metadata: Metadata::new(),
            },
        };
        let input = StageInput::from_items(
            BatchContext {
                batch_id: "batch".to_string(),
                metadata: Metadata::new(),
            },
            vec![AlertingEvent {
                result: result.clone(),
                spike_alert_input: Some(SpikeAlertInput {
                    issue: make_issue(issue_id, team_id),
                    props: None,
                }),
            }],
        );

        let output: Vec<EventResult> = stage.process(input).await.unwrap();

        assert_eq!(output, vec![result]);
        assert_eq!(&*side_effects.persisted.lock().unwrap(), &vec![issue_id]);
    }

    /// When `enabled_team_ids` is set and an issue's team is not in the list, spike
    /// detection is skipped entirely and no side effects are triggered.
    #[tokio::test]
    async fn alerting_team_not_in_enabled_ids_skips_spike_detection() {
        let redis = Arc::new(MockRedisClient::new());
        let side_effects = Arc::new(RecordingSideEffects::default());
        let deps = AlertingDeps::new(redis)
            .with_enabled_team_ids(Some(HashSet::from([999]))) // team 1 not included
            .with_side_effects(side_effects.clone());

        run_spike_detection_for_inputs(
            deps,
            vec![SpikeAlertInput {
                issue: make_issue(Uuid::now_v7(), 1),
                props: None,
            }],
            ExceptionProcessingOptions::default(),
        )
        .await
        .unwrap();

        assert!(side_effects.persisted.lock().unwrap().is_empty());
        assert!(side_effects.signals.lock().unwrap().is_empty());
        assert!(side_effects.internal_events.lock().unwrap().is_empty());
    }

    /// When a spike is detected but the cooldown lock is already held (another pod or a
    /// recent alert), `batch_set_nx_ex` returns `false` and no side effects are emitted.
    #[tokio::test]
    async fn cooldown_prevents_duplicate_spike_alerts() {
        let mut redis = MockRedisClient::new();
        let issue_id = Uuid::now_v7();
        let team_id = 1;
        setup_issue_buckets(&mut redis, issue_id, &[Some(30), Some(1), Some(1)]);
        setup_team_buckets(
            &mut redis,
            team_id,
            &[Some(30), Some(1), Some(1)],
            &[1, 1, 1],
        );
        redis.batch_incr_by_expire_nx_ret(Ok(()));
        // Cooldown key not in set_nx_ex_ret → MockRedisClient returns false (already held).
        let redis = Arc::new(redis);

        let side_effects = Arc::new(RecordingSideEffects::default());
        let deps = AlertingDeps::new(redis)
            .with_spike_config_repository(Arc::new(StaticSpikeConfigRepository {
                configs: HashMap::from([(
                    team_id,
                    SpikeDetectionConfig {
                        multiplier: 2.0,
                        threshold: 10,
                        snooze_duration_seconds: 60,
                    },
                )]),
            }))
            .with_side_effects(side_effects.clone());

        run_spike_detection_for_inputs(
            deps,
            vec![SpikeAlertInput {
                issue: make_issue(issue_id, team_id),
                props: None,
            }],
            ExceptionProcessingOptions::default(),
        )
        .await
        .unwrap();

        assert!(
            side_effects.persisted.lock().unwrap().is_empty(),
            "cooldown must suppress side effects"
        );
        assert!(side_effects.signals.lock().unwrap().is_empty());
        assert!(side_effects.internal_events.lock().unwrap().is_empty());
    }

    /// When the Redis `mget` call that reads historical buckets fails, the alerting stage
    /// returns a `StageError::Transient` so the batch can be retried.
    #[tokio::test]
    async fn redis_mget_failure_causes_stage_transient_error() {
        let mut redis = MockRedisClient::new();
        let issue_id = Uuid::now_v7();
        let team_id = 1;
        redis.batch_incr_by_expire_nx_ret(Ok(()));
        redis.mget_error(CustomRedisError::Timeout);
        let redis = Arc::new(redis);

        let stage = AlertingStage::with_deps(
            AlertingDeps::new(redis)
                .with_spike_config_repository(Arc::new(DefaultSpikeConfigRepository)),
        );
        let input = StageInput::from_items(
            BatchContext {
                batch_id: "batch".to_string(),
                metadata: Metadata::new(),
            },
            vec![AlertingEvent {
                result: EventResult {
                    event_id: "e1".to_string(),
                    outcome: EventOutcome::Next {
                        properties: None,
                        metadata: Metadata::new(),
                    },
                },
                spike_alert_input: Some(SpikeAlertInput {
                    issue: make_issue(issue_id, team_id),
                    props: None,
                }),
            }],
        );

        let result: Result<Vec<EventResult>, StageError> = stage.process(input).await;

        assert!(
            matches!(result, Err(StageError::Transient(_))),
            "Redis mget failure must surface as StageError::Transient"
        );
    }

    /// When a side effect (persist_spike_event) fails after acquiring the cooldown lock,
    /// the lock must be released via `batch_del` so future spikes are not silently blocked.
    #[tokio::test]
    async fn side_effect_failure_releases_cooldown_lock() {
        let mut redis = MockRedisClient::new();
        let issue_id = Uuid::now_v7();
        let team_id = 1;
        setup_issue_buckets(&mut redis, issue_id, &[Some(30), Some(1), Some(1)]);
        setup_team_buckets(
            &mut redis,
            team_id,
            &[Some(30), Some(1), Some(1)],
            &[1, 1, 1],
        );
        redis.batch_incr_by_expire_nx_ret(Ok(()));
        redis.set_nx_ex_ret(&cooldown_key(&issue_id), Ok(true));
        let redis_for_calls = redis.clone();
        let redis = Arc::new(redis);

        let deps = AlertingDeps::new(redis)
            .with_spike_config_repository(Arc::new(StaticSpikeConfigRepository {
                configs: HashMap::from([(
                    team_id,
                    SpikeDetectionConfig {
                        multiplier: 2.0,
                        threshold: 10,
                        snooze_duration_seconds: 60,
                    },
                )]),
            }))
            .with_side_effects(Arc::new(FailingPersistSideEffects));

        run_spike_detection_for_inputs(
            deps,
            vec![SpikeAlertInput {
                issue: make_issue(issue_id, team_id),
                props: None,
            }],
            ExceptionProcessingOptions::default(),
        )
        .await
        .unwrap();

        let calls = redis_for_calls.get_calls();
        let batch_del_calls: Vec<_> = calls.iter().filter(|c| c.op == "batch_del").collect();
        assert!(
            !batch_del_calls.is_empty(),
            "batch_del must be called to release the cooldown lock after a side-effect failure"
        );
    }

    /// Events whose `spike_alert_input` is `None` (Drop, Error, or any outcome without
    /// associated issue data) must pass through the alerting stage unchanged without
    /// triggering any spike-detection side effects.
    #[tokio::test]
    async fn drop_and_error_events_without_spike_input_pass_through() {
        let redis = Arc::new(MockRedisClient::new());
        let side_effects = Arc::new(RecordingSideEffects::default());
        let stage = AlertingStage::with_deps(
            AlertingDeps::new(redis).with_side_effects(side_effects.clone()),
        );

        let drop_result = EventResult {
            event_id: "drop-event".to_string(),
            outcome: EventOutcome::Drop {
                reason: "some_reason".to_string(),
            },
        };
        let error_result = EventResult {
            event_id: "error-event".to_string(),
            outcome: EventOutcome::Error {
                message: "some error".to_string(),
                code: None,
                retryable: Some(false),
            },
        };
        let input = StageInput::from_items(
            BatchContext {
                batch_id: "batch".to_string(),
                metadata: Metadata::new(),
            },
            vec![
                AlertingEvent {
                    result: drop_result.clone(),
                    spike_alert_input: None,
                },
                AlertingEvent {
                    result: error_result.clone(),
                    spike_alert_input: None,
                },
            ],
        );

        let output: Vec<EventResult> = stage.process(input).await.unwrap();

        assert_eq!(output, vec![drop_result, error_result]);
        assert!(side_effects.persisted.lock().unwrap().is_empty());
        assert!(side_effects.signals.lock().unwrap().is_empty());
        assert!(side_effects.internal_events.lock().unwrap().is_empty());
    }
}
