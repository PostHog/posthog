//! Orchestrator-level metrics, structured logs, and sampled per-item warning
//! helpers for Cymbal pipeline + stage execution.
//!
//! Every stage invocation (local or remote) is wrapped by [`metered_stage`] so
//! that dashboards see a uniform shape regardless of where the work ran. The
//! pipeline-batch boundary uses [`record_pipeline_batch`]. Per-item retry /
//! error warnings are sampled through [`should_log_item_failure`] to avoid
//! drowning logs when a whole batch turns red.

use std::collections::HashMap;
use std::future::Future;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use cymbal_api::cymbal::v1::StageLoad;
use cymbal_domain::{EventOutcome, EventResult, RateLimitGateOutput};
use tonic::metadata::MetadataMap;

/// Metric: histogram of per-stage wall time in seconds, labelled by
/// `{stage, execution, outcome}`. Outcome ∈ {ok, error, timeout, fail_open}.
pub const STAGE_DURATION: &str = "cymbal_stage_duration_seconds";

/// Metric: counter of per-item outcomes, labelled by `{stage, execution, outcome}`.
/// Outcome ∈ {success, drop, retry, error}.
pub const STAGE_ITEMS: &str = "cymbal_stage_items_total";

/// Metric: histogram of input batch size per stage call, labelled by
/// `{stage, execution}`.
pub const STAGE_BATCH_SIZE: &str = "cymbal_stage_batch_size";

/// Metric: counter of synthesized per-item retry failures emitted by the
/// remote-stage transport, labelled by `{stage, target, reason}`.
/// Reason ∈ {transport_error, timeout, remote_item_error}.
pub const REMOTE_STAGE_RETRIES: &str = "cymbal_remote_stage_retries_total";

/// Metric: histogram of total wall time for `process_exception_batch`, in seconds.
pub const PIPELINE_BATCH_DURATION: &str = "cymbal_pipeline_batch_duration_seconds";

/// Metric: histogram of input event counts per `process_exception_batch` call.
pub const PIPELINE_BATCH_EVENTS: &str = "cymbal_pipeline_batch_events";

/// Metric: gauge of currently executing public pipeline batches and internal
/// stage batches. This is the same counter the shutdown path waits on.
pub const IN_FLIGHT_BATCHES: &str = "cymbal_in_flight_batches";

/// Metric: gauge of each remote target circuit breaker state.
/// Values are `0=closed`, `1=open`, `2=half_open`.
pub const REMOTE_CIRCUIT_STATE: &str = "cymbal_remote_circuit_state";

/// Metric: counter emitted when a remote target circuit transitions to open,
/// labelled by `{target, reason}`.
pub const REMOTE_CIRCUIT_OPENED: &str = "cymbal_remote_circuit_opened_total";

/// Metric: counter of remote endpoint load observations emitted by stage pods,
/// labelled by `{stage, target, endpoint, overloaded}`.
pub const REMOTE_ENDPOINT_LOAD_OBSERVATIONS: &str =
    "cymbal_remote_stage_endpoint_load_observations_total";

/// Metric: gauge of observed remote endpoint in-flight stage batches, labelled
/// by `{stage, target, endpoint, kind}` where kind ∈ {current, max}.
pub const REMOTE_ENDPOINT_IN_FLIGHT_BATCHES: &str =
    "cymbal_remote_stage_endpoint_in_flight_batches";

/// Metric: gauge of observed remote endpoint in-flight stage items/events,
/// labelled by `{stage, target, endpoint, kind}` where kind ∈ {current, max}.
pub const REMOTE_ENDPOINT_IN_FLIGHT_ITEMS: &str = "cymbal_remote_stage_endpoint_in_flight_items";

/// Metric: counter of stage-side item/event admission rejections, labelled by
/// `{stage, reason}`.
pub const STAGE_ITEM_ADMISSION_REJECTIONS: &str = "cymbal_stage_item_admission_rejections_total";

/// Metric: counter for routing decisions where observed load caused the stable
/// affinity primary to be skipped, labelled by `{stage, target, endpoint}`.
pub const REMOTE_ENDPOINT_LOAD_SKIPPED_PRIMARY: &str =
    "cymbal_remote_stage_load_skipped_primary_total";

pub const STAGE_LOAD_CURRENT_IN_FLIGHT_METADATA: &str =
    "cymbal-stage-load-current-in-flight-batches";
pub const STAGE_LOAD_MAX_IN_FLIGHT_METADATA: &str = "cymbal-stage-load-max-in-flight-batches";
pub const STAGE_LOAD_OVERLOADED_METADATA: &str = "cymbal-stage-load-overloaded";
pub const STAGE_LOAD_CURRENT_IN_FLIGHT_ITEMS_METADATA: &str =
    "cymbal-stage-load-current-in-flight-items";
pub const STAGE_LOAD_MAX_IN_FLIGHT_ITEMS_METADATA: &str = "cymbal-stage-load-max-in-flight-items";
pub const STAGE_LOAD_DRAINING_METADATA: &str = "cymbal-stage-load-draining";
/// Comma-separated list of stage IDs the responding pod serves. Carried as a
/// trailer so it reaches the dispatcher even on error statuses (where the
/// response body is absent). See `StageLoad.served_stage_ids` in stage.proto.
pub const STAGE_LOAD_SERVED_STAGE_IDS_METADATA: &str = "cymbal-stage-load-served-stage-ids";

/// 1-in-N sampling rate for per-item retry / error warning logs.
///
/// Sized to keep noise tractable when a whole batch turns red while still
/// producing enough samples to be actionable. Each call to
/// [`should_log_item_failure`] advances a global counter and returns `true`
/// once every `ITEM_LOG_SAMPLE_RATE` calls.
pub const ITEM_LOG_SAMPLE_RATE: u64 = 64;

static ITEM_LOG_SAMPLER: AtomicU64 = AtomicU64::new(0);

/// Returns `true` once every [`ITEM_LOG_SAMPLE_RATE`] calls (process-wide).
pub fn should_log_item_failure() -> bool {
    let n = ITEM_LOG_SAMPLER.fetch_add(1, Ordering::Relaxed);
    n.is_multiple_of(ITEM_LOG_SAMPLE_RATE)
}

#[derive(Debug, Clone)]
pub struct InFlightBatchTracker {
    counter: Arc<AtomicUsize>,
    max_in_flight: usize,
}

impl InFlightBatchTracker {
    pub fn new(counter: Arc<AtomicUsize>, max_in_flight: usize) -> Self {
        Self {
            counter,
            max_in_flight: max_in_flight.max(1),
        }
    }

    pub fn standalone(max_in_flight: usize) -> Self {
        Self::new(Arc::new(AtomicUsize::new(0)), max_in_flight)
    }

    pub fn counter(&self) -> Arc<AtomicUsize> {
        self.counter.clone()
    }

    pub fn current(&self) -> usize {
        self.counter.load(Ordering::Acquire)
    }

    pub fn max_in_flight(&self) -> usize {
        self.max_in_flight
    }

    pub fn load_snapshot(&self) -> StageLoad {
        let current = self.current() as u64;
        let max = self.max_in_flight as u64;
        StageLoad {
            current_in_flight_stage_batches: current,
            max_in_flight_stage_batches: max,
            overloaded: current >= max,
            current_in_flight_items: 0,
            max_in_flight_items: 0,
            draining: false,
            // The shared batch-level tracker doesn't know which stages this pod
            // hosts; per-stage snapshots in `CymbalStageService` populate this.
            served_stage_ids: Vec::new(),
        }
    }

    pub fn try_acquire(
        &self,
        scope: &'static str,
    ) -> Result<InFlightBatchGuard, InFlightLimitExceeded> {
        let mut current = self.counter.load(Ordering::Acquire);
        loop {
            if current >= self.max_in_flight {
                return Err(InFlightLimitExceeded {
                    current,
                    max: self.max_in_flight,
                    scope,
                });
            }

            match self.counter.compare_exchange_weak(
                current,
                current + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    record_in_flight_gauge(current + 1);
                    return Ok(InFlightBatchGuard {
                        counter: self.counter.clone(),
                    });
                }
                Err(observed) => current = observed,
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct InFlightItemTracker {
    counters: Arc<Mutex<HashMap<String, Arc<AtomicUsize>>>>,
}

impl InFlightItemTracker {
    pub fn new() -> Self {
        Self {
            counters: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn current(&self, stage_id: &str) -> usize {
        self.counter_for(stage_id).load(Ordering::Acquire)
    }

    pub fn try_acquire(
        &self,
        stage_id: &str,
        count: usize,
        max_in_flight: usize,
    ) -> Result<InFlightItemGuard, InFlightItemLimitExceeded> {
        let max_in_flight = max_in_flight.max(1);
        if count > max_in_flight {
            return Err(InFlightItemLimitExceeded {
                current: self.current(stage_id),
                requested: count,
                max: max_in_flight,
            });
        }

        let counter = self.counter_for(stage_id);
        let mut current = counter.load(Ordering::Acquire);
        loop {
            let Some(next) = current.checked_add(count) else {
                return Err(InFlightItemLimitExceeded {
                    current,
                    requested: count,
                    max: max_in_flight,
                });
            };
            if next > max_in_flight {
                return Err(InFlightItemLimitExceeded {
                    current,
                    requested: count,
                    max: max_in_flight,
                });
            }

            match counter.compare_exchange_weak(current, next, Ordering::AcqRel, Ordering::Acquire)
            {
                Ok(_) => {
                    return Ok(InFlightItemGuard { counter, count });
                }
                Err(observed) => current = observed,
            }
        }
    }

    fn counter_for(&self, stage_id: &str) -> Arc<AtomicUsize> {
        let mut counters = self.counters.lock().expect("in-flight item mutex poisoned");
        counters
            .entry(stage_id.to_string())
            .or_insert_with(|| Arc::new(AtomicUsize::new(0)))
            .clone()
    }
}

impl Default for InFlightItemTracker {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InFlightItemLimitExceeded {
    pub current: usize,
    pub requested: usize,
    pub max: usize,
}

impl std::fmt::Display for InFlightItemLimitExceeded {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "too many in-flight Cymbal stage items: current={current}, requested={requested}, max={max}",
            current = self.current,
            requested = self.requested,
            max = self.max
        )
    }
}

#[derive(Debug)]
pub struct InFlightItemGuard {
    counter: Arc<AtomicUsize>,
    count: usize,
}

impl Drop for InFlightItemGuard {
    fn drop(&mut self) {
        self.counter.fetch_sub(self.count, Ordering::AcqRel);
    }
}

impl Default for InFlightBatchTracker {
    fn default() -> Self {
        Self::standalone(64)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InFlightLimitExceeded {
    pub current: usize,
    pub max: usize,
    pub scope: &'static str,
}

impl std::fmt::Display for InFlightLimitExceeded {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "too many in-flight Cymbal {scope} batches: current={current}, max={max}",
            scope = self.scope,
            current = self.current,
            max = self.max
        )
    }
}

#[derive(Debug)]
pub struct InFlightBatchGuard {
    counter: Arc<AtomicUsize>,
}

impl Drop for InFlightBatchGuard {
    fn drop(&mut self) {
        let previous = self.counter.fetch_sub(1, Ordering::AcqRel);
        let current = previous.saturating_sub(1);
        record_in_flight_gauge(current);
    }
}

pub fn record_in_flight_gauge(current: usize) {
    metrics::gauge!(IN_FLIGHT_BATCHES).set(current as f64);
}

pub fn insert_stage_load_metadata(metadata: &mut MetadataMap, load: &StageLoad) {
    if let Ok(value) = load.current_in_flight_stage_batches.to_string().parse() {
        metadata.insert(STAGE_LOAD_CURRENT_IN_FLIGHT_METADATA, value);
    }
    if let Ok(value) = load.max_in_flight_stage_batches.to_string().parse() {
        metadata.insert(STAGE_LOAD_MAX_IN_FLIGHT_METADATA, value);
    }
    if let Ok(value) = load.overloaded.to_string().parse() {
        metadata.insert(STAGE_LOAD_OVERLOADED_METADATA, value);
    }
    if let Ok(value) = load.current_in_flight_items.to_string().parse() {
        metadata.insert(STAGE_LOAD_CURRENT_IN_FLIGHT_ITEMS_METADATA, value);
    }
    if let Ok(value) = load.max_in_flight_items.to_string().parse() {
        metadata.insert(STAGE_LOAD_MAX_IN_FLIGHT_ITEMS_METADATA, value);
    }
    if let Ok(value) = load.draining.to_string().parse() {
        metadata.insert(STAGE_LOAD_DRAINING_METADATA, value);
    }
    if !load.served_stage_ids.is_empty() {
        if let Ok(value) = load.served_stage_ids.join(",").parse() {
            metadata.insert(STAGE_LOAD_SERVED_STAGE_IDS_METADATA, value);
        }
    }
}

pub fn stage_load_from_metadata(metadata: &MetadataMap) -> Option<StageLoad> {
    let current = metadata
        .get(STAGE_LOAD_CURRENT_IN_FLIGHT_METADATA)?
        .to_str()
        .ok()?
        .parse()
        .ok()?;
    let max = metadata
        .get(STAGE_LOAD_MAX_IN_FLIGHT_METADATA)?
        .to_str()
        .ok()?
        .parse()
        .ok()?;
    let overloaded = metadata
        .get(STAGE_LOAD_OVERLOADED_METADATA)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse().ok())
        .unwrap_or(false);
    let current_in_flight_items = metadata
        .get(STAGE_LOAD_CURRENT_IN_FLIGHT_ITEMS_METADATA)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse().ok())
        .unwrap_or(0);
    let max_in_flight_items = metadata
        .get(STAGE_LOAD_MAX_IN_FLIGHT_ITEMS_METADATA)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse().ok())
        .unwrap_or(0);
    let draining = metadata
        .get(STAGE_LOAD_DRAINING_METADATA)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse().ok())
        .unwrap_or(false);
    let served_stage_ids = metadata
        .get(STAGE_LOAD_SERVED_STAGE_IDS_METADATA)
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            value
                .split(',')
                .map(str::trim)
                .filter(|id| !id.is_empty())
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default();

    Some(StageLoad {
        current_in_flight_stage_batches: current,
        max_in_flight_stage_batches: max,
        overloaded,
        current_in_flight_items,
        max_in_flight_items,
        draining,
        served_stage_ids,
    })
}

pub fn record_stage_item_admission_rejection(stage_id: &str, reason: &'static str) {
    metrics::counter!(
        STAGE_ITEM_ADMISSION_REJECTIONS,
        "stage" => stage_id.to_string(),
        "reason" => reason,
    )
    .increment(1);
}

pub async fn wait_for_in_flight_drain(
    counter: Arc<AtomicUsize>,
    max_wait: Duration,
    log_interval: Duration,
) -> bool {
    let started_at = Instant::now();
    let log_interval = log_interval.max(Duration::from_millis(1));

    loop {
        let in_flight = counter.load(Ordering::Acquire);
        if in_flight == 0 {
            tracing::info!(
                waited_ms = started_at.elapsed().as_millis(),
                "cymbal in-flight batches drained"
            );
            return true;
        }

        let elapsed = started_at.elapsed();
        if elapsed >= max_wait {
            tracing::warn!(
                in_flight,
                waited_ms = elapsed.as_millis(),
                max_wait_ms = max_wait.as_millis(),
                "timed out waiting for Cymbal in-flight batches to drain"
            );
            return false;
        }

        tracing::info!(
            in_flight,
            waited_ms = elapsed.as_millis(),
            max_wait_ms = max_wait.as_millis(),
            "waiting for Cymbal in-flight batches to drain"
        );

        let remaining = max_wait.saturating_sub(elapsed);
        tokio::time::sleep(log_interval.min(remaining)).await;
    }
}

/// Where a stage call ran. Both variants carry a stable `execution` label
/// ("local" / "remote") for metrics; `Remote` additionally carries a target
/// name used as a metric label on remote-only counters.
#[derive(Clone, Copy, Debug)]
pub enum StageExecutionKind<'a> {
    Local,
    Remote { target: &'a str },
}

impl<'a> StageExecutionKind<'a> {
    pub fn label(&self) -> &'static str {
        match self {
            StageExecutionKind::Local => "local",
            StageExecutionKind::Remote { .. } => "remote",
        }
    }

    pub fn target(&self) -> Option<&'a str> {
        match self {
            StageExecutionKind::Local => None,
            StageExecutionKind::Remote { target } => Some(target),
        }
    }
}

/// Stage-level outcome label written to [`STAGE_DURATION`].
///
/// * `Ok` — stage call returned without a transport / orchestration error.
/// * `Error` — stage call returned a `Status::*` to the orchestrator.
/// * `Timeout` — remote stage exceeded its configured per-call timeout.
/// * `FailOpen` — remote stage failed but the orchestrator fell back to
///   passing inputs through unchanged (currently rate-limiting).
#[derive(Clone, Copy, Debug)]
pub enum StageOutcomeLabel {
    Ok,
    Error,
    Timeout,
    FailOpen,
}

impl StageOutcomeLabel {
    pub fn label(&self) -> &'static str {
        match self {
            StageOutcomeLabel::Ok => "ok",
            StageOutcomeLabel::Error => "error",
            StageOutcomeLabel::Timeout => "timeout",
            StageOutcomeLabel::FailOpen => "fail_open",
        }
    }
}

/// Per-item outcome counts emitted as separate `cymbal_stage_items_total`
/// counter increments. The four buckets match the public `EventOutcome`
/// variants: `success` (Next), `drop` (Drop), `retry` (Retry), `error` (Error).
#[derive(Clone, Copy, Debug, Default)]
pub struct StageItemCounts {
    pub success: usize,
    pub drop: usize,
    pub retry: usize,
    pub error: usize,
}

impl StageItemCounts {
    pub fn all_success(count: usize) -> Self {
        Self {
            success: count,
            ..Default::default()
        }
    }

    pub fn from_event_results(results: &[EventResult]) -> Self {
        let mut counts = StageItemCounts::default();
        for result in results {
            counts.record_event_outcome(&result.outcome);
        }
        counts
    }

    pub fn from_rate_limit_outputs(outputs: &[RateLimitGateOutput]) -> Self {
        let mut counts = StageItemCounts::default();
        for output in outputs {
            match output {
                RateLimitGateOutput::Allowed(_) => counts.success += 1,
                RateLimitGateOutput::Terminal(result) => {
                    counts.record_event_outcome(&result.outcome)
                }
            }
        }
        counts
    }

    fn record_event_outcome(&mut self, outcome: &EventOutcome) {
        match outcome {
            EventOutcome::Next { .. } => self.success += 1,
            EventOutcome::Drop { .. } => self.drop += 1,
            EventOutcome::Retry { .. } => self.retry += 1,
            EventOutcome::Error { .. } => self.error += 1,
        }
    }
}

/// Result of the closure passed to [`metered_stage`]. The closure does the
/// actual work and reports the value plus how to label the outcome.
pub struct MeteredStageResult<T> {
    pub value: T,
    pub outcome: StageOutcomeLabel,
    pub counts: StageItemCounts,
}

/// Wrap a stage invocation with uniform metrics + a "stage finished"
/// structured log line.
///
/// On success: records [`STAGE_BATCH_SIZE`], [`STAGE_DURATION`], one
/// [`STAGE_ITEMS`] counter increment per non-zero bucket, and an `info!` log
/// matching the batch-level shape in `pipeline.rs`.
///
/// On error: records [`STAGE_BATCH_SIZE`], [`STAGE_DURATION`] with
/// `outcome="error"`, an [`STAGE_ITEMS`] error counter equal to the input
/// count (every input failed), and a `warn!` log with the error message.
pub async fn metered_stage<F, T, E>(
    stage_id: &'static str,
    execution: StageExecutionKind<'_>,
    batch_id: &str,
    input_count: usize,
    fut: F,
) -> Result<T, E>
where
    F: Future<Output = Result<MeteredStageResult<T>, E>>,
    E: std::fmt::Display,
{
    let execution_label = execution.label();
    metrics::histogram!(
        STAGE_BATCH_SIZE,
        "stage" => stage_id,
        "execution" => execution_label,
    )
    .record(input_count as f64);

    let started_at = Instant::now();
    let result = fut.await;
    let elapsed = started_at.elapsed();
    let duration_seconds = elapsed.as_secs_f64();
    let duration_ms = elapsed.as_millis() as u64;
    let target = execution.target();

    match result {
        Ok(metered) => {
            let outcome_label = metered.outcome.label();
            metrics::histogram!(
                STAGE_DURATION,
                "stage" => stage_id,
                "execution" => execution_label,
                "outcome" => outcome_label,
            )
            .record(duration_seconds);
            record_item_counts(stage_id, execution_label, &metered.counts);
            log_stage_finished(StageFinishedLog {
                stage_id,
                execution: execution_label,
                target,
                batch_id,
                items: input_count,
                duration_ms,
                outcome: outcome_label,
                counts: Some(&metered.counts),
                error: None,
            });
            Ok(metered.value)
        }
        Err(error) => {
            metrics::histogram!(
                STAGE_DURATION,
                "stage" => stage_id,
                "execution" => execution_label,
                "outcome" => "error",
            )
            .record(duration_seconds);
            if input_count > 0 {
                metrics::counter!(
                    STAGE_ITEMS,
                    "stage" => stage_id,
                    "execution" => execution_label,
                    "outcome" => "error",
                )
                .increment(input_count as u64);
            }
            let error_text = error.to_string();
            log_stage_finished(StageFinishedLog {
                stage_id,
                execution: execution_label,
                target,
                batch_id,
                items: input_count,
                duration_ms,
                outcome: "error",
                counts: None,
                error: Some(&error_text),
            });
            Err(error)
        }
    }
}

fn record_item_counts(stage_id: &'static str, execution: &'static str, counts: &StageItemCounts) {
    let buckets = [
        ("success", counts.success),
        ("drop", counts.drop),
        ("retry", counts.retry),
        ("error", counts.error),
    ];
    for (outcome_label, count) in buckets {
        if count > 0 {
            metrics::counter!(
                STAGE_ITEMS,
                "stage" => stage_id,
                "execution" => execution,
                "outcome" => outcome_label,
            )
            .increment(count as u64);
        }
    }
}

/// All fields recorded by the structured `cymbal stage finished` log line.
/// Grouped into one struct so callers don't have to thread eight scalars
/// through two metric branches.
struct StageFinishedLog<'a> {
    stage_id: &'static str,
    execution: &'static str,
    target: Option<&'a str>,
    batch_id: &'a str,
    items: usize,
    duration_ms: u64,
    outcome: &'static str,
    counts: Option<&'a StageItemCounts>,
    error: Option<&'a str>,
}

fn log_stage_finished(log: StageFinishedLog<'_>) {
    let StageFinishedLog {
        stage_id,
        execution,
        target,
        batch_id,
        items,
        duration_ms,
        outcome,
        counts,
        error,
    } = log;
    let success = counts.map(|c| c.success).unwrap_or(0);
    let drops = counts.map(|c| c.drop).unwrap_or(0);
    let retries = counts.map(|c| c.retry).unwrap_or(0);
    let errors = counts
        .map(|c| c.error)
        .unwrap_or(if error.is_some() { items } else { 0 });

    if error.is_some() {
        tracing::warn!(
            stage_id,
            execution,
            target,
            batch_id,
            items,
            duration_ms,
            outcome,
            success,
            drops,
            retries,
            errors,
            error,
            "cymbal stage finished"
        );
    } else {
        tracing::info!(
            stage_id,
            execution,
            target,
            batch_id,
            items,
            duration_ms,
            outcome,
            success,
            drops,
            retries,
            errors,
            "cymbal stage finished"
        );
    }
}

/// Record the public `process_exception_batch` boundary in
/// [`PIPELINE_BATCH_DURATION`] + [`PIPELINE_BATCH_EVENTS`].
pub fn record_pipeline_batch(events: usize, duration: std::time::Duration, outcome: &'static str) {
    metrics::histogram!(PIPELINE_BATCH_EVENTS, "outcome" => outcome).record(events as f64);
    metrics::histogram!(
        PIPELINE_BATCH_DURATION,
        "outcome" => outcome,
    )
    .record(duration.as_secs_f64());
}

/// Reason label written to [`REMOTE_STAGE_RETRIES`].
#[derive(Clone, Copy, Debug)]
pub enum RemoteRetryReason {
    TransportError,
    Timeout,
    RemoteItemError,
}

impl RemoteRetryReason {
    pub fn label(&self) -> &'static str {
        match self {
            RemoteRetryReason::TransportError => "transport_error",
            RemoteRetryReason::Timeout => "timeout",
            RemoteRetryReason::RemoteItemError => "remote_item_error",
        }
    }
}

/// Increment [`REMOTE_STAGE_RETRIES`] by `count` for the given `(stage, target, reason)`.
pub fn record_remote_retries(
    stage_id: &str,
    target: &str,
    reason: RemoteRetryReason,
    count: usize,
) {
    if count == 0 {
        return;
    }
    metrics::counter!(
        REMOTE_STAGE_RETRIES,
        "stage" => stage_id.to_string(),
        "target" => target.to_string(),
        "reason" => reason.label(),
    )
    .increment(count as u64);
}

#[cfg(test)]
mod tests {
    use std::time::{Duration, Instant};

    use cymbal_domain::{
        EventOutcome, EventResult, InputEvent, RateLimitDecision, RateLimitGateOutput,
    };

    use super::*;

    #[tokio::test]
    async fn wait_for_in_flight_drain_waits_until_batch_finishes() {
        let tracker = InFlightBatchTracker::standalone(4);
        let counter = tracker.counter();
        let guard = tracker.try_acquire("test").unwrap();

        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(30)).await;
            drop(guard);
        });

        let started_at = Instant::now();
        let drained =
            wait_for_in_flight_drain(counter, Duration::from_secs(1), Duration::from_millis(5))
                .await;

        assert!(drained);
        assert!(started_at.elapsed() >= Duration::from_millis(25));
    }

    #[test]
    fn in_flight_tracker_rejects_when_limit_is_reached() {
        let tracker = InFlightBatchTracker::standalone(1);
        let _guard = tracker.try_acquire("test").unwrap();

        let error = tracker.try_acquire("test").unwrap_err();

        assert_eq!(error.current, 1);
        assert_eq!(error.max, 1);
    }

    #[test]
    fn stage_load_metadata_roundtrips_served_stage_ids() {
        let load = StageLoad {
            current_in_flight_stage_batches: 1,
            max_in_flight_stage_batches: 4,
            overloaded: false,
            current_in_flight_items: 0,
            max_in_flight_items: 0,
            draining: false,
            served_stage_ids: vec!["resolution:v1".to_string(), "linking:v1".to_string()],
        };
        let mut metadata = tonic::metadata::MetadataMap::new();
        insert_stage_load_metadata(&mut metadata, &load);
        let recovered = stage_load_from_metadata(&metadata).expect("decoded");

        assert_eq!(recovered.served_stage_ids, load.served_stage_ids);
    }

    #[test]
    fn stage_load_metadata_omits_served_stage_ids_when_empty() {
        // Older pods that don't advertise capability must not stamp the
        // metadata header at all — an empty header would deserialize to
        // `vec![""]` and downstream filtering treats that as "advertises one
        // empty stage_id", which would be wrong.
        let load = StageLoad {
            current_in_flight_stage_batches: 0,
            max_in_flight_stage_batches: 0,
            overloaded: false,
            current_in_flight_items: 0,
            max_in_flight_items: 0,
            draining: false,
            served_stage_ids: Vec::new(),
        };
        let mut metadata = tonic::metadata::MetadataMap::new();
        insert_stage_load_metadata(&mut metadata, &load);

        assert!(metadata.get(STAGE_LOAD_SERVED_STAGE_IDS_METADATA).is_none());

        let recovered = stage_load_from_metadata(&metadata).expect("decoded");
        assert!(recovered.served_stage_ids.is_empty());
    }

    #[test]
    fn in_flight_item_tracker_reserves_all_items_or_none() {
        let tracker = InFlightItemTracker::new();

        let guard = tracker.try_acquire("resolution:v1", 2, 3).unwrap();
        assert_eq!(tracker.current("resolution:v1"), 2);
        assert!(tracker.try_acquire("resolution:v1", 2, 3).is_err());
        assert_eq!(tracker.current("resolution:v1"), 2);

        drop(guard);
        assert_eq!(tracker.current("resolution:v1"), 0);
    }

    #[test]
    fn item_counts_buckets_event_outcomes() {
        let results = vec![
            EventResult {
                event_id: "a".into(),
                outcome: EventOutcome::Next {
                    properties: None,
                    metadata: Default::default(),
                },
            },
            EventResult {
                event_id: "b".into(),
                outcome: EventOutcome::Drop { reason: "x".into() },
            },
            EventResult {
                event_id: "c".into(),
                outcome: EventOutcome::Retry {
                    reason: "x".into(),
                    retry_after_ms: None,
                },
            },
            EventResult {
                event_id: "d".into(),
                outcome: EventOutcome::Error {
                    message: "x".into(),
                    code: None,
                    retryable: None,
                },
            },
        ];

        let counts = StageItemCounts::from_event_results(&results);

        assert_eq!(counts.success, 1);
        assert_eq!(counts.drop, 1);
        assert_eq!(counts.retry, 1);
        assert_eq!(counts.error, 1);
    }

    #[test]
    fn item_counts_buckets_rate_limit_outputs() {
        let outputs = vec![
            RateLimitGateOutput::allowed(
                InputEvent {
                    event_id: "a".into(),
                    team_id: 1,
                    properties: Default::default(),
                },
                RateLimitDecision::Disabled,
            ),
            RateLimitGateOutput::drop("b".into(), "rate_limited:team_id".into()),
        ];

        let counts = StageItemCounts::from_rate_limit_outputs(&outputs);

        assert_eq!(counts.success, 1);
        assert_eq!(counts.drop, 1);
    }

    #[test]
    fn item_log_sampler_fires_predictably() {
        // Sampler is process-global; we only assert the modulo cadence over a
        // small window rather than the exact starting phase, which depends on
        // whatever other tests in the binary have already advanced it.
        let mut fired = 0;
        for _ in 0..(ITEM_LOG_SAMPLE_RATE * 4) {
            if should_log_item_failure() {
                fired += 1;
            }
        }
        assert_eq!(fired, 4);
    }
}
