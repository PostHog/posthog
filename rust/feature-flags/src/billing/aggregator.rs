//! `BillingAggregator` — in-process per-pod aggregation with periodic flush.
//!
//! `record()` is synchronous, lock-scoped, and returns in microseconds. A
//! background task wakes every `flush_interval`, atomically swaps the inner
//! map, and issues pipelined `HINCRBY`s to Redis. On graceful shutdown a
//! final flush runs before the service exits.
//!
//! # Durability trade-off
//!
//! Aggregation defers writes until the next flush, so failure modes differ
//! from a per-request synchronous write:
//!
//! - **Redis error on a flush chunk** (normal tick): failing chunk plus
//!   any unattempted remainder are re-queued into `pending` and retried on
//!   the next tick. Re-queued entries are **rebucketed to the current
//!   bucket** so a sustained outage does not accumulate one new
//!   `AggregationKey` per (team, request_type, library) on every
//!   `CACHE_BUCKET_SIZE` rollover — cardinality stays bounded by the
//!   active (team × request_type × library) surface regardless of outage
//!   duration. Counts are conserved; per-bucket time attribution during
//!   the outage is reattributed to the bucket current at retry time. The
//!   `max_pending_entries` cap remains as a safety tripwire (not a
//!   working-set estimate) — `flags_billing_unflushed_requests_total{cause="cap_drop"}`
//!   firing now signals exotic failure (e.g. a single sustained-outage
//!   pod with cardinality already at cap before the outage), not the
//!   normal outage trajectory.
//! - **Graceful shutdown** (SIGTERM): a final best-effort flush runs
//!   within `shutdown_flush_timeout`. Anything not flushed is reported
//!   under `flags_billing_unflushed_requests_total{cause="shutdown_drop"}`.
//! - **Ungraceful termination** (SIGKILL past the grace window, OOM, node
//!   loss, panic): **up to one `flush_interval` of records is lost.** The
//!   `pending` map lives only in process memory; there is no WAL. The
//!   crashed pod cannot emit at the moment of loss, so detection relies
//!   on the **last scrape before the crash**: `flags_billing_pending_records`
//!   gauges the per-pod count of at-risk records, and a non-zero value
//!   correlated with a pod restart in
//!   `kube_pod_container_status_restarts_total` attributes the loss. The
//!   fleet-wide `flags_billing_records_total` vs.
//!   `flags_billing_entries_flushed_total` rate ratio is a secondary
//!   signal for the same gap.
//!
//! ## Detecting a wedged flusher before it drops counts
//!
//! - `flags_billing_pending_entries` — live gauge; sustained growth
//!   is the leading indicator.
//! - `flags_billing_seconds_since_successful_flush` — stale-flush
//!   alarm; rises even when `flags_billing_flush_errors_total` stays
//!   flat (the signature of a hung `execute_pipeline`).
//! - `flags_billing_flush_errors_total` — labeled by `error_type`;
//!   alert via `rate(flags_billing_flush_errors_total[1m]) > 0 for: 30s`
//!   to catch a wedged Redis link.
//!
//! ## Knob-sizing guidance
//!
//! `flush_interval` directly bounds the crash-loss window. Shorter = less
//! worst-case data loss, more Redis RTTs; longer = better aggregation,
//! bigger worst-case loss. The default (10s) is sized so a typical SIGKILL
//! loses well under a minute of billable activity per pod while still
//! giving the aggregation meaningful compression.
//!
//! See `validate` for knob bounds. Mis-setting any knob to zero silently
//! breaks billing in a different way (panic, cap every record, instant
//! shutdown loss) — `validate` rejects them at boot.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use common_metrics::{gauge, histogram, inc};
use common_redis::{Client as RedisClient, CustomRedisError, PipelineCommand};
use rand::Rng;
use tokio::sync::Notify;
use tokio::task::JoinHandle;

use crate::flags::flag_analytics::{
    current_bucket, get_team_request_library_shadow_key, get_team_request_shadow_key,
};
use crate::flags::flag_request::FlagRequestType;
use crate::handler::types::Library;
use crate::metrics::consts::{
    FLAGS_BILLING_ENTRIES_FLUSHED, FLAGS_BILLING_FLUSH_DURATION_MS, FLAGS_BILLING_FLUSH_ERRORS,
    FLAGS_BILLING_PENDING_ENTRIES, FLAGS_BILLING_PENDING_RECORDS, FLAGS_BILLING_RECORDS,
    FLAGS_BILLING_RECORD_DURATION_US, FLAGS_BILLING_SECONDS_SINCE_SUCCESSFUL_FLUSH,
    FLAGS_BILLING_UNFLUSHED_REQUESTS,
};

fn record_labels_for(request_type: FlagRequestType) -> Vec<(String, String)> {
    vec![(
        "request_type".to_string(),
        request_type.as_str().to_string(),
    )]
}

/// Cause label for `flags_billing_unflushed_requests_total`. Kept as a
/// closed enum so a typo can't quietly create a new label value.
#[derive(Debug, Clone, Copy)]
enum UnflushedCause {
    CapDrop,
    FlushDroppedOnError,
    ShutdownDrop,
    RedisError,
}

impl UnflushedCause {
    fn as_str(self) -> &'static str {
        match self {
            UnflushedCause::CapDrop => "cap_drop",
            UnflushedCause::FlushDroppedOnError => "flush_dropped_on_error",
            UnflushedCause::ShutdownDrop => "shutdown_drop",
            UnflushedCause::RedisError => "redis_error",
        }
    }
}

fn inc_unflushed(cause: UnflushedCause, count: u64) {
    if count == 0 {
        return;
    }
    inc(
        FLAGS_BILLING_UNFLUSHED_REQUESTS,
        &[("cause".to_string(), cause.as_str().to_string())],
        count,
    );
}

/// Key used to aggregate repeated `record()` calls in-process.
///
/// `bucket` is computed from the record time, not the flush time — late-flushed
/// records must still land in the bucket they arrived in.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AggregationKey {
    pub team_id: i32,
    pub request_type: FlagRequestType,
    pub library: Option<Library>,
    pub bucket: u64,
}

/// Policy for handling a chunk error during a flush. The flusher's normal
/// tick uses `BailOnError` (if Redis is rejecting, save RTTs and retry next
/// interval). The shutdown path uses `BestEffort` — it's our last chance to
/// land writes before the pod exits, so don't abandon trailing chunks over a
/// single transient failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FlushPolicy {
    BailOnError,
    BestEffort,
}

#[derive(Debug, Clone)]
pub struct BillingAggregatorConfig {
    /// Interval between flushes. Must be non-zero — see `validate`.
    pub flush_interval: Duration,
    /// Safety tripwire — expected steady-state size is orders of magnitude
    /// smaller. A non-zero rate of
    /// `flags_billing_unflushed_requests_total{cause="cap_drop"}` is an alert.
    /// Must be non-zero — see `validate`.
    pub max_pending_entries: usize,
    /// Must be non-zero — see `validate`.
    pub per_flush_batch_size: usize,
    /// Must be non-zero — see `validate`.
    pub shutdown_flush_timeout: Duration,
}

impl Default for BillingAggregatorConfig {
    fn default() -> Self {
        Self {
            flush_interval: Duration::from_secs(10),
            max_pending_entries: 500_000,
            per_flush_batch_size: 200,
            shutdown_flush_timeout: Duration::from_secs(15),
        }
    }
}

impl BillingAggregatorConfig {
    /// Reject zero/degenerate knob values that would break the flusher or
    /// silently disable billing. Called by `BillingAggregator::start` before
    /// spawning the background task so a misconfigured deploy fails loudly at
    /// boot instead of crashing the flusher task minutes later.
    pub fn validate(&self) -> Result<(), String> {
        if self.flush_interval.is_zero() {
            return Err("flush_interval must be > 0 (tokio::time::interval panics on zero)".into());
        }
        if self.max_pending_entries == 0 {
            return Err(
                "max_pending_entries must be > 0 (zero caps every new key immediately)".into(),
            );
        }
        if self.per_flush_batch_size == 0 {
            return Err("per_flush_batch_size must be > 0".into());
        }
        if self.shutdown_flush_timeout.is_zero() {
            return Err(
                "shutdown_flush_timeout must be > 0 (zero loses every pending count on shutdown)"
                    .into(),
            );
        }
        Ok(())
    }
}

/// In-process counter aggregation for billable flag requests.
pub struct BillingAggregator {
    inner: Arc<Inner>,
    flusher: Mutex<Option<JoinHandle<()>>>,
    metrics_sampler: Mutex<Option<JoinHandle<()>>>,
}

struct Inner {
    config: BillingAggregatorConfig,
    redis: Arc<dyn RedisClient + Send + Sync>,
    pending: Mutex<HashMap<AggregationKey, u64>>,
    /// Running sum of `pending.values()`. Updated under the `pending` lock so
    /// increments and the lock-protected HashMap mutation are guaranteed
    /// consistent. The flush drain swaps it to zero, the requeue path adds
    /// back what's reinjected, and shutdown reads it as the residual count of
    /// records still in `pending`.
    pending_total: AtomicU64,
    /// Counts drained from `pending` but not yet credited to any terminal
    /// counter (`entries_flushed_total` or
    /// `unflushed_requests_total{cause="flush_dropped_on_error"}`).
    /// Non-zero only while `flush_once` is mid-flight. If the flusher task is
    /// aborted mid-flush (e.g. shutdown timeout), this preserves the count of
    /// lost records so `record_shutdown_drops` can report it.
    in_flight_uncredited: AtomicU64,
    /// Unix epoch (ms) of the last successful flush. Zero = no successful
    /// flush has occurred yet. Read by the metrics sampler to compute
    /// `seconds_since_successful_flush`. A hung flusher shows up here as a
    /// monotonically increasing age while `flush_errors_total` stays at 0
    /// (a hung flush never completes its success/failure accounting).
    last_successful_flush_epoch_ms: AtomicU64,
    /// Per-request-type record counters. Bumped on every `record()` call and
    /// drained at flush time, so the hot path does one atomic increment
    /// instead of an `inc()` call that allocates label strings every time.
    record_count_decide: AtomicU64,
    record_count_flag_definitions: AtomicU64,
    shutdown_signal: Notify,
}

impl Inner {
    fn new(
        redis: Arc<dyn RedisClient + Send + Sync>,
        config: BillingAggregatorConfig,
    ) -> Arc<Self> {
        Arc::new(Self {
            config,
            redis,
            pending: Mutex::new(HashMap::new()),
            pending_total: AtomicU64::new(0),
            in_flight_uncredited: AtomicU64::new(0),
            last_successful_flush_epoch_ms: AtomicU64::new(0),
            record_count_decide: AtomicU64::new(0),
            record_count_flag_definitions: AtomicU64::new(0),
            shutdown_signal: Notify::new(),
        })
    }

    /// Sum any remaining entries in `pending` plus any drained-but-uncredited
    /// counts from an interrupted flush, and emit them as shutdown drops.
    fn record_shutdown_drops(&self) {
        let remaining_pending = self.pending_total.load(Ordering::Relaxed);
        let in_flight = self.in_flight_uncredited.load(Ordering::Relaxed);
        inc_unflushed(UnflushedCause::ShutdownDrop, remaining_pending + in_flight);
    }
}

impl BillingAggregator {
    /// Construct an aggregator and spawn its flusher task.
    ///
    /// The flusher ticks on `flush_interval + random jitter` so a fleet-wide
    /// deploy doesn't synchronize every pod's flush into the same Redis burst.
    pub fn start(
        redis: Arc<dyn RedisClient + Send + Sync>,
        config: BillingAggregatorConfig,
    ) -> Arc<Self> {
        // Fail fast on misconfiguration. A misconfigured FLAGS_BILLING_*
        // env var would otherwise panic the flusher task silently, or silently
        // disable billing — both worse than refusing to boot.
        if let Err(e) = config.validate() {
            panic!("invalid BillingAggregatorConfig: {e}");
        }

        let flush_interval_ms = config.flush_interval.as_millis() as u64;
        let max_pending_entries = config.max_pending_entries;
        let per_flush_batch_size = config.per_flush_batch_size;

        let inner = Inner::new(redis, config);
        let flusher = tokio::spawn(run_flusher(inner.clone()));
        let metrics_sampler = tokio::spawn(run_metrics_sampler(inner.clone()));

        tracing::info!(
            flush_interval_ms,
            max_pending_entries,
            per_flush_batch_size,
            "BillingAggregator started"
        );

        Arc::new(Self {
            inner,
            flusher: Mutex::new(Some(flusher)),
            metrics_sampler: Mutex::new(Some(metrics_sampler)),
        })
    }

    /// Record a single billable request. Non-blocking; no Redis I/O.
    ///
    /// **Lifecycle constraint:** must not be called after `shutdown()` has
    /// returned. The flusher task is consumed by shutdown, so a post-shutdown
    /// record lands in `pending` and is never flushed or accounted as a drop —
    /// it is silently lost with no metric. In the normal server lifecycle
    /// `serve()` calls `shutdown()` only after `axum::serve()` has fully
    /// drained, which means every request handler that holds the aggregator
    /// `Arc` has already returned. Background tasks or deferred work that
    /// outlive `axum::serve()` and still hold the aggregator `Arc` would
    /// violate this constraint — don't do that.
    pub fn record(&self, team_id: i32, request_type: FlagRequestType, library: Option<Library>) {
        // Time the body so the duration histogram can surface `pending` mutex
        // contention. Empty label slice so the per-call emission doesn't
        // allocate inside `apply_label_filter`.
        let start = std::time::Instant::now();

        // Bump the per-request-type atomic counter; the flusher emits the
        // `FLAGS_BILLING_RECORDS` metric in batches at flush time so the
        // hot path doesn't pay the per-call label clone in `inc()`.
        match request_type {
            FlagRequestType::Decide => &self.inner.record_count_decide,
            FlagRequestType::FlagDefinitions => &self.inner.record_count_flag_definitions,
        }
        .fetch_add(1, Ordering::Relaxed);

        let key = AggregationKey {
            team_id,
            request_type,
            library,
            bucket: current_bucket(),
        };

        {
            let mut pending = self.inner.pending.lock().unwrap();

            if pending.len() >= self.inner.config.max_pending_entries && !pending.contains_key(&key)
            {
                // Cap hit on a new key: drop the incoming record rather than
                // evicting an existing entry. Eviction would be O(n) under
                // the hot-path mutex (a scan to find the oldest bucket). The
                // cap is a tripwire, not a steady-state path —
                // `flags_billing_unflushed_requests_total{cause="cap_drop"}`
                // alerts on any non-zero rate — and the flusher drains the
                // map every `flush_interval`, so the cap state is transient.
                // Existing-key increments are always allowed (they don't
                // grow the map).
                inc_unflushed(UnflushedCause::CapDrop, 1);
            } else {
                *pending.entry(key).or_insert(0) += 1;
                // Update the running total under the same lock so a
                // concurrent reader can never observe `pending` and
                // `pending_total` out of step.
                self.inner.pending_total.fetch_add(1, Ordering::Relaxed);
            }
        }

        // `as_nanos() / 1000.0` preserves sub-microsecond resolution that
        // `as_micros()` would truncate, since uncontended record() is
        // typically a few hundred nanoseconds.
        let elapsed_us = start.elapsed().as_nanos() as f64 / 1000.0;
        histogram(FLAGS_BILLING_RECORD_DURATION_US, &[], elapsed_us);
    }

    /// Perform a final flush and stop the flusher task.
    ///
    /// Must be called after `axum::serve(...).await` resolves so all
    /// in-flight requests have already recorded. Times out after
    /// `shutdown_flush_timeout`; any remaining entries are counted in
    /// `flags_billing_unflushed_requests_total{cause="shutdown_drop"}`.
    ///
    /// Concurrent callers: only the first caller performs the flush; any
    /// other caller racing into `shutdown()` returns immediately without
    /// waiting for the first caller's flush to complete. If multiple tasks
    /// need to await flush completion, wrap the call in a `tokio::sync::OnceCell`
    /// (or similar) outer guard. Sequential calls are safe — the second is
    /// a no-op. Call exactly once from the task that owns the server lifecycle.
    pub async fn shutdown(&self) {
        // Sampler is best-effort emission — `abort` is fine; a lost last
        // tick doesn't matter operationally.
        if let Some(handle) = self.metrics_sampler.lock().unwrap().take() {
            handle.abort();
        }

        // `notify_one()` (not `notify_waiters()`): if the flusher happens to be
        // mid-tick when we fire, the notify must be stored so the next
        // `notified().await` returns immediately. `notify_waiters()` would be
        // a no-op in that window.
        self.inner.shutdown_signal.notify_one();

        let handle = self.flusher.lock().unwrap().take();
        if let Some(handle) = handle {
            // Hold onto an abort handle: dropping a `JoinHandle` does NOT
            // cancel the task, and we need to be sure a timed-out flusher
            // can't keep running after the process-level shutdown has moved
            // on (and can't later double-credit counts we just recorded as
            // shutdown drops).
            let abort_handle = handle.abort_handle();
            let timeout = self.inner.config.shutdown_flush_timeout;
            match tokio::time::timeout(timeout, handle).await {
                Ok(Ok(())) => {
                    tracing::info!("BillingAggregator: shutdown flush completed");
                }
                Ok(Err(join_err)) => {
                    tracing::error!(error = %join_err, "BillingAggregator flusher panicked during shutdown");
                    self.inner.record_shutdown_drops();
                }
                Err(_) => {
                    tracing::warn!(
                        timeout_ms = timeout.as_millis() as u64,
                        "BillingAggregator: shutdown flush timed out"
                    );
                    abort_handle.abort();
                    self.inner.record_shutdown_drops();
                }
            }
        }
    }

    #[cfg(test)]
    pub fn pending_len(&self) -> usize {
        self.inner.pending.lock().unwrap().len()
    }

    #[cfg(test)]
    pub fn in_flight_uncredited(&self) -> u64 {
        self.inner.in_flight_uncredited.load(Ordering::Relaxed)
    }

    #[cfg(test)]
    pub fn pending_total(&self) -> u64 {
        self.inner.pending_total.load(Ordering::Relaxed)
    }

    /// Tests sometimes need to set up `pending` directly (e.g. to inject
    /// non-`current_bucket()` buckets, or to construct an empty-drain
    /// scenario by clearing previously-recorded data). Going through this
    /// helper keeps `pending_total` in step with `pending` — `record()`
    /// maintains that invariant on the production path, and the metrics
    /// sampler reads `pending_total` lock-free assuming it holds.
    #[cfg(test)]
    fn seed_pending(&self, entries: impl IntoIterator<Item = (AggregationKey, u64)>) {
        let mut pending = self.inner.pending.lock().unwrap();
        let mut total = self.inner.pending_total.load(Ordering::Relaxed);
        for (key, count) in entries {
            *pending.entry(key).or_insert(0) += count;
            total += count;
        }
        self.inner.pending_total.store(total, Ordering::Relaxed);
    }

    /// Construct an aggregator without spawning the background flusher. For
    /// test harnesses that don't exercise periodic flushing — `record()` still
    /// fills the pending map, but counts only land in Redis if the test calls
    /// `flush_once` directly. `shutdown()` is a no-op (no task to join), so
    /// nothing leaks at runtime teardown. Not for production use.
    #[doc(hidden)]
    pub fn for_tests(
        redis: Arc<dyn RedisClient + Send + Sync>,
        config: BillingAggregatorConfig,
    ) -> Arc<Self> {
        Arc::new(Self {
            inner: Inner::new(redis, config),
            flusher: Mutex::new(None),
            metrics_sampler: Mutex::new(None),
        })
    }
}

/// Spawned task: tick → drain → flush, until the shutdown signal fires.
async fn run_flusher(inner: Arc<Inner>) {
    // Initial jitter desynchronizes fleet-wide flushes after a coordinated
    // deploy. Race it against shutdown so a quick SIGTERM doesn't wait for the
    // jitter to elapse before flushing.
    let jitter = pick_jitter(inner.config.flush_interval);
    tokio::select! {
        _ = tokio::time::sleep(jitter) => {}
        _ = inner.shutdown_signal.notified() => {
            flush_once(&inner, FlushPolicy::BestEffort).await;
            return;
        }
    }

    let mut interval = tokio::time::interval(inner.config.flush_interval);
    // `Delay` (not `Skip`): if a flush runs longer than the interval, the next
    // tick still fires — buffered records keep accumulating and the cap
    // tripwire handles unbounded growth. `Skip` would silently drop ticks
    // during sustained slowness, leaving counts stranded longer than
    // `flush_interval`.
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    // First tick fires immediately — swallow it so the first real flush
    // happens one interval from now, after traffic has had a chance to
    // accumulate.
    interval.tick().await;

    loop {
        tokio::select! {
            _ = interval.tick() => {
                flush_once(&inner, FlushPolicy::BailOnError).await;
            }
            _ = inner.shutdown_signal.notified() => {
                tracing::info!("BillingAggregator: shutdown signal received, performing final flush");
                flush_once(&inner, FlushPolicy::BestEffort).await;
                return;
            }
        }
    }
}

/// Outcome of a single pipeline-chunk execution. `ErrBail` is how
/// `flush_chunk` signals to its caller that the current flush should stop
/// attempting further chunks (the caller is responsible for requeuing any
/// entries it hadn't yet handed off).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ChunkOutcome {
    Ok,
    Err,
    ErrBail,
}

/// Execute one pipeline chunk and classify the result. Moves `chunk_entries`
/// into `requeue` on a `BailOnError` error so those entries retry next tick;
/// clears `chunk_entries` otherwise. `flushed_counts` is updated in place so
/// the caller can reconcile `in_flight_uncredited`. Dropped counts in
/// `BestEffort` mode are not tracked here — the residual in
/// `in_flight_uncredited` after the loop equals the total dropped, and the
/// caller credits it under `flush_dropped_on_error`.
///
/// Treats any `Ok(_)` from `execute_pipeline` as a fully-successful chunk —
/// per-command inner errors inside the returned vector are not inspected.
/// Safe today because every command in the pipeline is `HINCRBY` on a
/// pre-existing hash key, which cannot fail at the per-command level.
/// Adding non-`HINCRBY` operations to this pipeline requires revisiting this
/// assumption to avoid silent over-crediting of `entries_flushed_total`.
async fn flush_chunk(
    inner: &Arc<Inner>,
    commands: Vec<PipelineCommand>,
    chunk_counts: u64,
    chunk_entries: &mut Vec<(AggregationKey, u64)>,
    policy: FlushPolicy,
    flushed_counts: &mut u64,
    requeue: &mut Vec<(AggregationKey, u64)>,
) -> ChunkOutcome {
    match inner.redis.execute_pipeline(commands).await {
        Ok(_) => {
            *flushed_counts += chunk_counts;
            // Credit per-chunk so a shutdown abort between chunks doesn't
            // strand counts already written to Redis under an unincremented
            // `entries_flushed_total`.
            inc(FLAGS_BILLING_ENTRIES_FLUSHED, &[], chunk_counts);
            chunk_entries.clear();
            ChunkOutcome::Ok
        }
        Err(e) => {
            record_chunk_error(&e, chunk_counts, policy);
            match policy {
                FlushPolicy::BailOnError => {
                    requeue.append(chunk_entries);
                    ChunkOutcome::ErrBail
                }
                FlushPolicy::BestEffort => {
                    chunk_entries.clear();
                    ChunkOutcome::Err
                }
            }
        }
    }
}

/// Swap the pending map, flush the drained batch to Redis, record metrics.
///
/// Chunks at `AggregationKey` boundaries (never splits a key's team-level
/// and SDK-level writes across chunks). Per-chunk success credits
/// `entries_flushed_total` so successful chunks stay credited even when a
/// later chunk fails. `in_flight_uncredited` tracks what's still unaccounted
/// for so a mid-flush abort (e.g. shutdown timeout) is still reportable via
/// shutdown drops.
///
/// On a chunk error: `BailOnError` (normal tick) stops attempting further
/// chunks and merges the failing chunk's entries plus the unattempted
/// remainder back into `pending` for the next tick, bumping
/// `flush_requeued_total`. `BestEffort` (shutdown) keeps attempting and
/// records unrecoverable losses under
/// `unflushed_requests_total{cause="flush_dropped_on_error"}` — the process
/// is exiting, there is no next tick.
async fn flush_once(inner: &Arc<Inner>, policy: FlushPolicy) {
    // Drain the per-request-type record counters and emit
    // FLAGS_BILLING_RECORDS. Doing this here instead of in `record()`
    // keeps the hot path free of the per-call `apply_label_filter`
    // allocation that `inc()` triggers.
    let decide_records = inner.record_count_decide.swap(0, Ordering::Relaxed);
    if decide_records > 0 {
        inc(
            FLAGS_BILLING_RECORDS,
            &record_labels_for(FlagRequestType::Decide),
            decide_records,
        );
    }
    let flag_def_records = inner
        .record_count_flag_definitions
        .swap(0, Ordering::Relaxed);
    if flag_def_records > 0 {
        inc(
            FLAGS_BILLING_RECORDS,
            &record_labels_for(FlagRequestType::FlagDefinitions),
            flag_def_records,
        );
    }

    // Swap pending and zero `pending_total` under the same lock so a
    // concurrent reader can never see pending empty with the atomic non-zero
    // (or vice-versa). The atomic's value at swap time equals the sum of the
    // drained map's values, since they're maintained together.
    let (drained, total_counts): (HashMap<AggregationKey, u64>, u64) = {
        let mut pending = inner.pending.lock().unwrap();
        let drained = std::mem::take(&mut *pending);
        let total = inner.pending_total.swap(0, Ordering::Relaxed);
        (drained, total)
    };

    if drained.is_empty() {
        // An empty drain is still evidence the flusher loop is alive. Stamp
        // the epoch so an idle pod doesn't trip the stale-flush alarm — a
        // low-traffic pod that flushed once at boot and then went quiet
        // would otherwise show monotonically rising
        // `seconds_since_successful_flush` while remaining perfectly healthy.
        inner
            .last_successful_flush_epoch_ms
            .store(now_epoch_ms(), Ordering::Relaxed);
        return;
    }

    let start = std::time::Instant::now();
    // Publish in-flight *before* the first await so an abort anywhere in
    // the flush still reports the correct residual. `total_counts` came
    // from `pending_total.swap(0)` above, so it equals the sum of drained
    // values without re-walking them.
    inner
        .in_flight_uncredited
        .store(total_counts, Ordering::Relaxed);

    let batch_size = inner.config.per_flush_batch_size.max(1);
    // Each key produces 1-2 commands, so over-provision by 1 to avoid a
    // realloc when the last key pushes the buffer past batch_size.
    let mut buffer: Vec<PipelineCommand> = Vec::with_capacity(batch_size + 1);
    let mut chunk_entries: Vec<(AggregationKey, u64)> = Vec::with_capacity(batch_size);
    let mut buffer_counts: u64 = 0;
    let mut flushed_counts: u64 = 0;
    let mut any_error = false;
    let mut requeue: Vec<(AggregationKey, u64)> = Vec::new();

    let mut iter = drained.into_iter();
    while let Some((key, count)) = iter.next() {
        // Clamp to i64::MAX for the HINCRBY signed parameter. The pending
        // map's u64 counts are bounded by `max_pending_entries * (records
        // per key per flush interval)`, well below i64::MAX in practice.
        let count_i64 = i64::try_from(count).unwrap_or(i64::MAX);
        let field = key.bucket.to_string();
        // Push the library command first so the `field` String can be moved
        // into the team command without an extra clone.
        if let Some(library) = key.library {
            buffer.push(PipelineCommand::HIncrBy {
                key: get_team_request_library_shadow_key(key.team_id, key.request_type, library),
                field: field.clone(),
                count: count_i64,
            });
        }
        buffer.push(PipelineCommand::HIncrBy {
            key: get_team_request_shadow_key(key.team_id, key.request_type),
            field,
            count: count_i64,
        });
        chunk_entries.push((key, count));
        buffer_counts += count;

        if buffer.len() >= batch_size {
            let outcome = flush_chunk(
                inner,
                std::mem::take(&mut buffer),
                buffer_counts,
                &mut chunk_entries,
                policy,
                &mut flushed_counts,
                &mut requeue,
            )
            .await;
            buffer_counts = 0;
            buffer.reserve(batch_size + 1);
            match outcome {
                ChunkOutcome::Ok => {
                    inner
                        .in_flight_uncredited
                        .store(total_counts - flushed_counts, Ordering::Relaxed);
                }
                ChunkOutcome::Err => {
                    any_error = true;
                }
                ChunkOutcome::ErrBail => {
                    any_error = true;
                    // Drain the remainder of the iterator into requeue so
                    // unattempted entries retry on the next tick. Also emit
                    // `unflushed_requests_total{cause="redis_error"}` for the
                    // remainder so the rate reflects all requests blocked by
                    // the error, not just the chunk that hit Redis. These
                    // records aren't terminally lost (they'll retry next
                    // tick), but the metric is an incident-magnitude signal,
                    // and bail-mode otherwise hides everything past the
                    // first failing chunk.
                    let remainder: Vec<(AggregationKey, u64)> = iter.by_ref().collect();
                    let remainder_counts: u64 = remainder.iter().map(|(_, c)| *c).sum();
                    inc_unflushed(UnflushedCause::RedisError, remainder_counts);
                    requeue.extend(remainder);
                    break;
                }
            }
        }
    }

    // Trailing partial chunk. In bail mode we broke above with an empty
    // buffer; in best-effort mode this may reveal a final error.
    if !buffer.is_empty() {
        let outcome = flush_chunk(
            inner,
            std::mem::take(&mut buffer),
            buffer_counts,
            &mut chunk_entries,
            policy,
            &mut flushed_counts,
            &mut requeue,
        )
        .await;
        match outcome {
            ChunkOutcome::Ok => {
                inner
                    .in_flight_uncredited
                    .store(total_counts - flushed_counts, Ordering::Relaxed);
            }
            ChunkOutcome::Err | ChunkOutcome::ErrBail => {
                any_error = true;
            }
        }
    }

    let elapsed_ms = start.elapsed().as_millis() as f64;
    histogram(FLAGS_BILLING_FLUSH_DURATION_MS, &[], elapsed_ms);

    // Re-merge failed entries into `pending` so they retry next tick.
    // Ordering: drop `in_flight_uncredited` *before* inserting into
    // `pending`. A mid-requeue abort then under-counts (some entries in
    // neither place) rather than double-counting (counted in both). Under-
    // count is the preferable failure mode for billing.
    //
    // Lock discipline: the O(N) merge runs *outside* the pending lock.
    // We swap out the fresh pending (small — only records added during
    // the flush), merge locally, and swap back. This keeps the hot-path
    // `record()` critical section unblocked under a Redis outage, when
    // `requeue` can be up to `max_pending_entries` large.
    //
    // Rebucket-on-requeue: entries are reattributed to `current_bucket()`
    // before being merged. Without this, a sustained Redis outage would
    // accumulate one new `AggregationKey` per (team, request_type, library)
    // every `CACHE_BUCKET_SIZE` (120s) as the wall clock advances —
    // cardinality scales with outage minutes regardless of traffic, and the
    // `max_pending_entries` cap eventually trips `cap_drop` on new keys.
    // Collapsing forward bounds cardinality to (team × request_type ×
    // library) and conserves the count, at the cost of per-bucket time
    // attribution during the outage. Billing aggregates over months, so the
    // attribution slip is invisible at invoice time; per-bucket quota
    // enforcement during the outage itself is impossible anyway because
    // the data isn't in Redis.
    let requeued_counts: u64 = requeue.iter().map(|(_, c)| *c).sum();
    if !requeue.is_empty() {
        inner
            .in_flight_uncredited
            .fetch_sub(requeued_counts, Ordering::Relaxed);
        let mut merged: HashMap<AggregationKey, u64> = {
            let mut pending = inner.pending.lock().unwrap();
            std::mem::take(&mut *pending)
        };
        let now_bucket = current_bucket();
        for (mut key, count) in requeue {
            key.bucket = now_bucket;
            *merged.entry(key).or_insert(0) += count;
        }
        {
            let mut pending = inner.pending.lock().unwrap();
            // Reconcile any records that arrived during the merge.
            for (key, count) in pending.drain() {
                *merged.entry(key).or_insert(0) += count;
            }
            *pending = merged;
            // The requeued counts weren't in `pending_total` (they came from
            // `drained`, which already swapped to 0). Records that arrived
            // during the flush are already in `pending_total` from their
            // `record()` calls. Add the requeued sum back inside this lock so
            // a sampler tick can never see `pending_total` lagging the map.
            inner
                .pending_total
                .fetch_add(requeued_counts, Ordering::Relaxed);
        }
    }

    // Zero `in_flight_uncredited` *before* crediting `flush_dropped_on_error`
    // so a concurrent `record_shutdown_drops` cannot read both: a non-zero
    // residual *and* the about-to-happen FlushDroppedOnError credit. Without
    // this swap-before-credit ordering, a shutdown deadline firing between
    // the credit and the zero would re-credit `dropped_counts` as
    // `shutdown_drop`, double-counting in
    // `flags_billing_unflushed_requests_total`.
    //
    // After the swap, exactly one of the two paths sees the residual:
    //   - this thread credits FlushDroppedOnError(dropped),
    //   - or `record_shutdown_drops` reads in_flight=0 and credits only
    //     remaining_pending under ShutdownDrop.
    //
    // `AcqRel` because this is a read-modify-write whose Release half pairs
    // with any later observer of `in_flight_uncredited` — Relaxed would
    // permit the credit to be reordered before the swap on weak-memory
    // architectures, reintroducing the race the swap is meant to close.
    let in_flight_residual = inner.in_flight_uncredited.swap(0, Ordering::AcqRel);
    if any_error {
        inc_unflushed(UnflushedCause::FlushDroppedOnError, in_flight_residual);
    } else {
        // Record the successful-flush timestamp so the metrics sampler can
        // compute `seconds_since_successful_flush`. Stamp on any fully
        // error-free flush — a partial-success BestEffort flush still
        // dropped counts and shouldn't reset the "stale flush" alarm. The
        // empty-drain branch above stamps for the same reason: a tick with
        // nothing to flush is still proof the loop is alive.
        inner
            .last_successful_flush_epoch_ms
            .store(now_epoch_ms(), Ordering::Relaxed);
    }
}

/// Emit `FLUSH_ERRORS` (1 per failed chunk, classified by `error_type`) and
/// — under `BailOnError` only — `unflushed_requests_total{cause="redis_error"}`
/// for the chunk's aggregated request count, plus a warn-level log carrying
/// the raw error (never on a metric label — unbounded cardinality risk).
///
/// `requests_in_chunk` is the count of records affected by this chunk's
/// failure. Under `BailOnError`, `flush_once` separately emits the same cause
/// for the unattempted remainder so the rate reflects all requests blocked by
/// the error, not just the chunk that hit it. See the
/// `FLAGS_BILLING_UNFLUSHED_REQUESTS` cause docs in `metrics::consts` for why
/// `redis_error` is suppressed on the `BestEffort` (shutdown) path.
fn record_chunk_error(e: &CustomRedisError, requests_in_chunk: u64, policy: FlushPolicy) {
    inc(
        FLAGS_BILLING_FLUSH_ERRORS,
        &[(
            "error_type".to_string(),
            classify_redis_error(e).to_string(),
        )],
        1,
    );
    if policy == FlushPolicy::BailOnError {
        inc_unflushed(UnflushedCause::RedisError, requests_in_chunk);
    }
    tracing::warn!(
        error = %e,
        requests_in_chunk,
        "BillingAggregator: flush pipeline failed"
    );
}

pub(crate) fn classify_redis_error(err: &CustomRedisError) -> &'static str {
    // Exhaustive on purpose: a new `CustomRedisError` variant should produce a
    // compile error here so a new error type gets a deliberate
    // `error_type` label rather than disappearing into "other".
    match err {
        CustomRedisError::Timeout => "timeout",
        CustomRedisError::Redis(_) => "transport",
        CustomRedisError::NotFound => "not_found",
        CustomRedisError::ParseError(_) => "parse",
        CustomRedisError::InvalidConfiguration(_) => "config",
    }
}

/// Interval between live-gauge samples. Sized to the Prometheus scrape
/// cadence (15s default): faster sampling produces values nothing reads,
/// while still surfacing a wedged flusher within a couple of scrape
/// windows rather than waiting for the next flush interval. Each tick
/// briefly takes the `pending` mutex, which is the same lock `record()`
/// holds on the hot path, so cadence is a contention budget — not just a
/// CPU one.
const METRICS_SAMPLE_INTERVAL: Duration = Duration::from_secs(5);

fn now_epoch_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Spawned task: periodically samples `pending.len()`, `in_flight_uncredited`,
/// and time-since-last-successful-flush, and emits them as gauges.
///
/// Runs independently of `run_flusher` so a hung `execute_pipeline` can't
/// freeze these gauges — the whole point of sampling outside the flush
/// path is to surface a wedged flusher. Exits via `abort()` at shutdown.
async fn run_metrics_sampler(inner: Arc<Inner>) {
    let mut interval = tokio::time::interval(METRICS_SAMPLE_INTERVAL);
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    // Swallow the immediate first tick so startup doesn't emit zero-valued
    // samples before the aggregator has seen any traffic.
    interval.tick().await;

    loop {
        interval.tick().await;
        sample_metrics(&inner);
    }
}

fn sample_metrics(inner: &Arc<Inner>) {
    let pending_len = inner.pending.lock().unwrap().len();
    gauge(FLAGS_BILLING_PENDING_ENTRIES, &[], pending_len as f64);

    // Lock-free read: `pending_total` is maintained under the same lock as
    // `pending` mutations, so its value is a consistent snapshot from the
    // sampler's perspective. Slight skew vs. `pending_len` is fine — both
    // gauges are scrape-cadence approximations.
    let pending_records = inner.pending_total.load(Ordering::Relaxed);
    gauge(FLAGS_BILLING_PENDING_RECORDS, &[], pending_records as f64);

    let last_ms = inner.last_successful_flush_epoch_ms.load(Ordering::Relaxed);
    gauge(
        FLAGS_BILLING_SECONDS_SINCE_SUCCESSFUL_FLUSH,
        &[],
        compute_staleness_seconds(last_ms, now_epoch_ms()),
    );
}

/// Stale-flush gauge math, factored out so tests can pin the invariants
/// without observing global metric state. `last_ms == 0` means no successful
/// flush has happened yet — report 0 rather than "now - 0 = decades since
/// 1970", so a freshly booted pod with no traffic doesn't trip alerts.
/// `saturating_sub` clamps the backward-NTP-step case (`now < last`) to 0.
fn compute_staleness_seconds(last_ms: u64, now_ms: u64) -> f64 {
    if last_ms == 0 {
        0.0
    } else {
        now_ms.saturating_sub(last_ms) as f64 / 1000.0
    }
}

fn pick_jitter(flush_interval: Duration) -> Duration {
    // Up to 10% of the flush interval, capped at 1s — enough to desynchronize
    // fleet-wide flushes without leaving records stranded for multiple
    // seconds at startup.
    const MAX_JITTER_MS: u64 = 1_000;
    let max_jitter_ms = ((flush_interval.as_millis() / 10) as u64).clamp(1, MAX_JITTER_MS);
    let jitter_ms = rand::thread_rng().gen_range(0..max_jitter_ms);
    Duration::from_millis(jitter_ms)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_analytics::{
        get_team_request_library_shadow_key, get_team_request_shadow_key,
    };
    use common_redis::{MockRedisClient, MockRedisValue};
    use rstest::rstest;

    fn test_config() -> BillingAggregatorConfig {
        BillingAggregatorConfig {
            flush_interval: Duration::from_millis(50),
            max_pending_entries: 10_000,
            per_flush_batch_size: 200,
            shutdown_flush_timeout: Duration::from_secs(1),
        }
    }

    /// Build an aggregator without spawning the flusher, so tests can drive
    /// flushes deterministically via `flush_once`.
    fn new_test_aggregator(
        config: BillingAggregatorConfig,
    ) -> (Arc<MockRedisClient>, Arc<BillingAggregator>) {
        new_test_aggregator_with_redis(MockRedisClient::new(), config)
    }

    fn new_test_aggregator_with_redis(
        redis: MockRedisClient,
        config: BillingAggregatorConfig,
    ) -> (Arc<MockRedisClient>, Arc<BillingAggregator>) {
        let redis = Arc::new(redis);
        let agg = Arc::new(BillingAggregator {
            inner: Inner::new(redis.clone(), config),
            flusher: Mutex::new(None),
            metrics_sampler: Mutex::new(None),
        });
        (redis, agg)
    }

    fn hincrby_calls(redis: &MockRedisClient) -> Vec<(String, i64)> {
        redis
            .get_calls()
            .into_iter()
            .filter(|c| c.op == "pipeline_hincrby")
            .filter_map(|c| match c.value {
                MockRedisValue::I64(v) => Some((c.key, v)),
                _ => None,
            })
            .collect()
    }

    /// Poll a condition every 1ms up to 1s. For tests that need to observe
    /// a specific in-flight state of the flusher (e.g. "drain has happened
    /// and Redis is awaiting"). Sleeping a fixed wall-clock duration races
    /// scheduler latency on slow CI; polling on the deterministic signal
    /// is what `test_shutdown_timeout_credits_residual_to_in_flight`
    /// already does, factored out here so other race-window tests share
    /// the same pattern.
    async fn wait_until(mut cond: impl FnMut() -> bool) {
        for _ in 0..1000 {
            if cond() {
                return;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        panic!("wait_until: condition not satisfied within 1s");
    }

    /// Record `n` Decide requests for teams `1..=n` with the PosthogJs library.
    /// Each call generates one team-level + one library-level entry under the
    /// same bucket. Used by the flush-policy tests to set up a known shape.
    fn record_n_decide_with_library(agg: &Arc<BillingAggregator>, n: i32) {
        for team_id in 1..=n {
            agg.record(team_id, FlagRequestType::Decide, Some(Library::PosthogJs));
        }
    }

    #[rstest]
    // Repeated record on the same key collapses into one entry with the summed count.
    #[case::same_key_aggregates(
        &[(1, Some(Library::PosthogJs)), (1, Some(Library::PosthogJs)), (1, Some(Library::PosthogJs))],
        &[((1, Some(Library::PosthogJs)), 3)],
    )]
    // Same team but distinct libraries (including no library) split into separate keys.
    #[case::distinct_libraries_split(
        &[(1, Some(Library::PosthogJs)), (1, Some(Library::PosthogNode)), (1, None)],
        &[
            ((1, Some(Library::PosthogJs)), 1),
            ((1, Some(Library::PosthogNode)), 1),
            ((1, None), 1),
        ],
    )]
    fn test_record_aggregation(
        #[case] records: &[(i32, Option<Library>)],
        #[case] expected_counts: &[((i32, Option<Library>), u64)],
    ) {
        let (_, agg) = new_test_aggregator(test_config());

        for &(team_id, library) in records {
            agg.record(team_id, FlagRequestType::Decide, library);
        }

        assert_eq!(
            agg.pending_len(),
            expected_counts.len(),
            "pending_len must match number of expected distinct keys",
        );
        let bucket = current_bucket();
        let pending = agg.inner.pending.lock().unwrap();
        for &((team_id, library), expected) in expected_counts {
            let key = AggregationKey {
                team_id,
                request_type: FlagRequestType::Decide,
                library,
                bucket,
            };
            assert_eq!(
                pending.get(&key).copied(),
                Some(expected),
                "team {team_id} library {library:?} count mismatch",
            );
        }
    }

    /// `pending_total` is maintained alongside `pending` so the metrics
    /// sampler can read it lock-free. If `record()`, the flush drain, and
    /// the requeue path don't keep them in step, the `pending_counts` gauge
    /// drifts away from reality. This test pins the invariant
    /// `pending_total == sum(pending.values())` after each kind of
    /// transition.
    #[tokio::test]
    async fn test_pending_total_matches_pending_values_sum() {
        let (_, agg) = new_test_aggregator(test_config());

        let assert_consistent = |agg: &Arc<BillingAggregator>, label: &str| {
            let pending = agg.inner.pending.lock().unwrap();
            let walked: u64 = pending.values().sum();
            let atomic = agg.pending_total();
            assert_eq!(
                walked, atomic,
                "{label}: pending_total ({atomic}) drifted from pending.values().sum() ({walked})"
            );
        };

        // After records on distinct keys.
        agg.record(1, FlagRequestType::Decide, None);
        agg.record(2, FlagRequestType::Decide, None);
        assert_consistent(&agg, "after distinct-key records");

        // After repeated records on the same key.
        agg.record(1, FlagRequestType::Decide, None);
        agg.record(1, FlagRequestType::Decide, None);
        assert_consistent(&agg, "after repeated-key records");

        // After a successful flush.
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        assert_consistent(&agg, "after successful flush");
        assert_eq!(agg.pending_total(), 0, "pending_total must zero on drain");

        // After records following a flush.
        agg.record(3, FlagRequestType::FlagDefinitions, None);
        agg.record(3, FlagRequestType::FlagDefinitions, None);
        assert_consistent(&agg, "after post-flush records");
    }

    /// `pending_total` must absorb requeued counts when a flush bails out.
    /// Without this, a Redis outage would drain pending to "empty" while
    /// records actually pile back into `pending` from the requeue path.
    #[tokio::test]
    async fn test_pending_total_absorbs_requeued_counts_on_bail() {
        let mut mock = MockRedisClient::new();
        mock.pipeline_error(CustomRedisError::Timeout); // every flush attempt fails
        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock);
        let agg = BillingAggregator::for_tests(redis, test_config());

        // Three records on distinct keys (so they don't collapse).
        agg.record(1, FlagRequestType::Decide, None);
        agg.record(2, FlagRequestType::Decide, None);
        agg.record(3, FlagRequestType::Decide, None);
        assert_eq!(agg.pending_total(), 3);

        // BailOnError flush against an erroring mock: the failing chunk
        // and unattempted remainder both requeue. After flush, pending
        // should hold the same 3 records and pending_total should match.
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        let pending = agg.inner.pending.lock().unwrap();
        let walked: u64 = pending.values().sum();
        drop(pending);
        assert_eq!(
            walked,
            agg.pending_total(),
            "pending_total drifted from pending after bail+requeue"
        );
        assert_eq!(agg.pending_total(), 3, "all three records must requeue");
    }

    #[tokio::test]
    async fn test_flush_once_writes_pipelined_hincrby() {
        let (redis, agg) = new_test_aggregator(test_config());

        agg.record(42, FlagRequestType::Decide, Some(Library::PosthogJs));
        agg.record(42, FlagRequestType::Decide, Some(Library::PosthogJs));
        agg.record(7, FlagRequestType::Decide, None);

        let bucket = current_bucket();
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        let calls = hincrby_calls(&redis);
        // 3 HIncrBys: team-key for team 42, sdk-key for team 42, team-key for
        // team 7. Team 7 has no library, so no sdk-key.
        assert_eq!(calls.len(), 3);

        let expected_team_42_team = format!(
            "{}:{bucket}",
            get_team_request_shadow_key(42, FlagRequestType::Decide)
        );
        let expected_team_42_sdk = format!(
            "{}:{bucket}",
            get_team_request_library_shadow_key(42, FlagRequestType::Decide, Library::PosthogJs)
        );
        let expected_team_7_team = format!(
            "{}:{bucket}",
            get_team_request_shadow_key(7, FlagRequestType::Decide)
        );

        assert!(
            calls.contains(&(expected_team_42_team.clone(), 2)),
            "expected team 42 team key with count 2, got {:?}",
            calls
        );
        assert!(
            calls.contains(&(expected_team_42_sdk.clone(), 2)),
            "expected team 42 sdk key with count 2, got {:?}",
            calls
        );
        assert!(
            calls.contains(&(expected_team_7_team.clone(), 1)),
            "expected team 7 team key with count 1, got {:?}",
            calls
        );
    }

    #[tokio::test]
    async fn test_flush_once_writes_flag_definitions_keys() {
        let (redis, agg) = new_test_aggregator(test_config());

        agg.record(
            42,
            FlagRequestType::FlagDefinitions,
            Some(Library::PosthogJs),
        );

        let bucket = current_bucket();
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        let calls = hincrby_calls(&redis);
        let expected_team = format!("posthog:local_evaluation_requests:42:shadow:{bucket}");
        let expected_sdk =
            format!("posthog:local_evaluation_requests:sdk:42:posthog-js:shadow:{bucket}");
        assert_eq!(calls.len(), 2);
        assert!(calls.contains(&(expected_team, 1)));
        assert!(calls.contains(&(expected_sdk, 1)));
    }

    #[tokio::test]
    async fn test_flush_once_drains_pending() {
        let (_, agg) = new_test_aggregator(test_config());

        agg.record(1, FlagRequestType::Decide, None);
        assert_eq!(agg.pending_len(), 1);

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        assert_eq!(agg.pending_len(), 0);
    }

    #[tokio::test]
    async fn test_flush_chunks_commands_at_batch_size() {
        // per_flush_batch_size=2, 5 keys × 2 commands each = 10 commands → 5 chunks.
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 2,
            ..test_config()
        };
        let (redis, agg) = new_test_aggregator(config);

        record_n_decide_with_library(&agg, 5);

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        let hincrby_count = hincrby_calls(&redis).len();
        assert_eq!(
            hincrby_count, 10,
            "all commands should be flushed across chunks"
        );
    }

    #[rstest]
    // At cap, a new key (team 3) is dropped — the original two entries survive
    // unchanged, and team 3 never appears in pending.
    #[case::new_key_dropped_at_cap(3, &[(1, 1), (2, 1)])]
    // At cap, an existing key (team 1) still increments — pending_len is
    // unchanged but the count for team 1 grows.
    #[case::existing_key_increments_at_cap(1, &[(1, 2), (2, 1)])]
    fn test_cap_third_record(#[case] third_team: i32, #[case] expected_counts: &[(i32, u64)]) {
        let config = BillingAggregatorConfig {
            max_pending_entries: 2,
            ..test_config()
        };
        let (_, agg) = new_test_aggregator(config);

        agg.record(1, FlagRequestType::Decide, None);
        agg.record(2, FlagRequestType::Decide, None);
        assert_eq!(agg.pending_len(), 2);
        agg.record(third_team, FlagRequestType::Decide, None);

        // Length-equals-expected implicitly verifies that no extra team
        // (e.g. a capped-out team 3) snuck in.
        assert_eq!(
            agg.pending_len(),
            expected_counts.len(),
            "cap must hold pending_len at max_pending_entries",
        );
        let bucket = current_bucket();
        let pending = agg.inner.pending.lock().unwrap();
        for &(team_id, expected) in expected_counts {
            let key = AggregationKey {
                team_id,
                request_type: FlagRequestType::Decide,
                library: None,
                bucket,
            };
            assert_eq!(
                pending.get(&key).copied(),
                Some(expected),
                "team {team_id} count mismatch",
            );
        }
    }

    #[tokio::test]
    async fn test_shutdown_flushes_then_stops() {
        let redis = Arc::new(MockRedisClient::new());
        let agg = BillingAggregator::start(
            redis.clone(),
            BillingAggregatorConfig {
                // Slow tick so shutdown has to drive the flush itself.
                flush_interval: Duration::from_secs(60),
                ..test_config()
            },
        );

        agg.record(1, FlagRequestType::Decide, None);
        agg.record(1, FlagRequestType::Decide, None);

        let bucket = current_bucket();
        agg.shutdown().await;

        let calls = hincrby_calls(&redis);
        assert_eq!(calls.len(), 1, "shutdown should trigger one HIncrBy");
        let expected_key = format!(
            "{}:{bucket}",
            get_team_request_shadow_key(1, FlagRequestType::Decide)
        );
        assert_eq!(calls[0], (expected_key, 2));
    }

    #[tokio::test]
    async fn test_shutdown_is_idempotent_sequentially() {
        let redis = Arc::new(MockRedisClient::new());
        let agg = BillingAggregator::start(
            redis.clone(),
            BillingAggregatorConfig {
                flush_interval: Duration::from_secs(60),
                ..test_config()
            },
        );
        agg.record(1, FlagRequestType::Decide, None);

        // First call performs the flush. Second call must not panic and
        // must not double-flush.
        agg.shutdown().await;
        let calls_after_first = hincrby_calls(&redis).len();
        agg.shutdown().await;
        let calls_after_second = hincrby_calls(&redis).len();
        assert_eq!(calls_after_first, calls_after_second);
        assert_eq!(calls_after_first, 1);
    }

    #[tokio::test]
    async fn test_shutdown_timeout_does_not_hang() {
        // Redis pipeline blocks longer than `shutdown_flush_timeout`. Shutdown
        // must return within roughly the timeout, not the block duration.
        let mut mock = MockRedisClient::new();
        mock.pipeline_block(Duration::from_secs(5));
        let redis = Arc::new(mock);
        let agg = BillingAggregator::start(
            redis.clone(),
            BillingAggregatorConfig {
                flush_interval: Duration::from_secs(60),
                shutdown_flush_timeout: Duration::from_millis(100),
                ..test_config()
            },
        );
        agg.record(1, FlagRequestType::Decide, None);

        let start = std::time::Instant::now();
        agg.shutdown().await;
        let elapsed = start.elapsed();

        assert!(
            elapsed < Duration::from_secs(2),
            "shutdown should honour timeout, took {:?}",
            elapsed
        );
    }

    #[tokio::test]
    async fn test_flush_bail_mode_breaks_on_first_chunk_error() {
        // 5 keys with libraries = 10 commands. batch_size=2 → 5 chunks.
        // With an always-fail mock, the first chunk must be attempted and the
        // rest must NOT be attempted (bail-on-first-error — used by the
        // flusher's normal tick path).
        let mut mock = MockRedisClient::new();
        mock.pipeline_error(CustomRedisError::Timeout);
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 2,
            ..test_config()
        };
        let (redis, agg) = new_test_aggregator_with_redis(mock, config);

        record_n_decide_with_library(&agg, 5);

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        // Mock records commands before returning the connection error, so
        // exactly the failing first chunk's 2 commands appear in calls.
        let attempted = hincrby_calls(&redis).len();
        assert_eq!(
            attempted, 2,
            "only the first failing chunk should be attempted"
        );
    }

    #[tokio::test]
    async fn test_flush_bail_mode_requeues_failed_and_unattempted_entries() {
        // 5 keys × 2 cmds = 10 cmds at batch_size=2 → 5 chunks. Always-fail
        // mock: first chunk fails, remaining chunks are unattempted. Under
        // BailOnError, every drained entry must be re-queued into `pending`
        // so a later tick can retry — nothing should be silently dropped.
        //
        // Each team gets a distinct count (team T → T records) so the
        // assertion checks per-key identity, not just totals. A bug that
        // requeued the wrong 5 entries (e.g., duplicates of one chunk
        // rather than the actual leftover iterator) would otherwise pass.
        let mut mock = MockRedisClient::new();
        mock.pipeline_error(CustomRedisError::Timeout);
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 2,
            ..test_config()
        };
        let (_, agg) = new_test_aggregator_with_redis(mock, config);

        for team_id in 1..=5 {
            for _ in 0..team_id {
                agg.record(team_id, FlagRequestType::Decide, Some(Library::PosthogJs));
            }
        }
        assert_eq!(agg.pending_len(), 5);

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        assert_eq!(
            agg.pending_len(),
            5,
            "all failed+unattempted entries must be re-queued"
        );
        let pending = agg.inner.pending.lock().unwrap();
        let total: u64 = pending.values().sum();
        assert_eq!(
            total,
            1 + 2 + 3 + 4 + 5,
            "requeued counts must be preserved"
        );
        for (key, &count) in pending.iter() {
            assert_eq!(
                count, key.team_id as u64,
                "team {} requeued with wrong count {count}",
                key.team_id,
            );
        }
        // in-flight is cleared — requeued counts live in `pending`, not in
        // `in_flight_uncredited`, so shutdown drops can't double-count them.
        assert_eq!(agg.inner.in_flight_uncredited.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn test_flush_bail_mode_rebuckets_requeued_entries_to_current_bucket() {
        // Multiple stale-bucket entries for the same (team, request_type,
        // library) collapse into a single current-bucket entry on requeue.
        // Without rebucket-on-requeue, a sustained Redis outage would
        // accumulate one new key per CACHE_BUCKET_SIZE rollover, blowing
        // through `max_pending_entries` purely from the wall clock advancing.
        // After requeue, the count is conserved (3 + 5 + 7 = 15) and
        // cardinality is bounded by (team × request_type × library).
        let mut mock = MockRedisClient::new();
        mock.pipeline_error(CustomRedisError::Timeout);
        let (_, agg) = new_test_aggregator_with_redis(mock, test_config());

        // Seed three distinct old buckets for the same tuple. Pick buckets
        // far below `current_bucket()` so the test doesn't race a real
        // bucket boundary.
        let old_buckets = [10u64, 11, 12];
        let counts = [3u64, 5, 7];
        agg.seed_pending(old_buckets.iter().zip(counts.iter()).map(|(&b, &c)| {
            (
                AggregationKey {
                    team_id: 1,
                    request_type: FlagRequestType::Decide,
                    library: Some(Library::PosthogJs),
                    bucket: b,
                },
                c,
            )
        }));
        assert_eq!(agg.pending_len(), 3, "seeded three distinct-bucket keys");

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        let pending = agg.inner.pending.lock().unwrap();
        assert_eq!(
            pending.len(),
            1,
            "rebucket must collapse stale-bucket entries for the same tuple into one"
        );
        let (key, &count) = pending.iter().next().unwrap();
        assert_eq!(count, 3 + 5 + 7, "counts must be conserved across rebucket");
        assert_eq!(
            key.bucket,
            current_bucket(),
            "rebucketed key must carry the current bucket, not any stale bucket"
        );
        assert!(
            !old_buckets.contains(&key.bucket),
            "rebucketed key must not retain any stale bucket value"
        );
    }

    #[tokio::test]
    async fn test_flush_bail_mode_requeue_merges_with_concurrent_records() {
        // A record() arriving during an in-flight flush lands in the fresh
        // `pending` map the flusher just drained from. If that flush then
        // errors and requeues, the requeued entries must be *merged* into
        // the fresh map (not overwrite concurrent records, not lose them).
        let mut mock = MockRedisClient::new();
        mock.pipeline_block(Duration::from_millis(50));
        mock.pipeline_error(CustomRedisError::Timeout);
        let (_, agg) = new_test_aggregator_with_redis(mock, test_config());

        // One pre-flush record for team 1 — will be drained and requeued.
        agg.record(1, FlagRequestType::Decide, None);

        let agg_for_flush = agg.clone();
        let flush = tokio::spawn(async move {
            flush_once(&agg_for_flush.inner, FlushPolicy::BailOnError).await;
        });

        // Race a concurrent record for team 1 into the post-drain map
        // while the flusher is parked on the Redis error. Poll on
        // `in_flight_uncredited > 0` — the flusher writes that *before*
        // its first await, so observing it non-zero proves pending was
        // drained and the flusher is now parked on Redis. Sleeping a
        // fixed duration would race scheduler latency on slow CI.
        wait_until(|| agg.in_flight_uncredited() > 0).await;
        agg.record(1, FlagRequestType::Decide, None);
        flush.await.unwrap();

        // Both counts survive: the requeued pre-flush record + the racing
        // record merged under the same AggregationKey = 2.
        let pending = agg.inner.pending.lock().unwrap();
        let total: u64 = pending.values().sum();
        assert_eq!(total, 2, "requeue must merge, not overwrite or drop");
    }

    #[tokio::test]
    async fn test_flush_bail_mode_recovery_flushes_requeued() {
        // Fail only the first pipeline call. The first flush requeues its
        // drained entries; the second flush should find them in `pending`
        // and land them in Redis.
        let mut mock = MockRedisClient::new();
        mock.pipeline_error_at_call(0, CustomRedisError::Timeout);
        let (redis, agg) = new_test_aggregator_with_redis(mock, test_config());

        agg.record(1, FlagRequestType::Decide, None);
        agg.record(2, FlagRequestType::Decide, None);
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        // First flush errored; entries should be waiting in `pending`.
        assert_eq!(agg.pending_len(), 2, "first flush should requeue on error");
        let calls_after_first = hincrby_calls(&redis);

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        assert_eq!(agg.pending_len(), 0, "second flush should drain pending");

        // The mock records every attempted command even on errors, so we
        // must look at the calls added by the second flush only. That's
        // what actually reached Redis.
        let all_calls = hincrby_calls(&redis);
        let second_flush_calls: Vec<_> = all_calls[calls_after_first.len()..].to_vec();
        let total: i64 = second_flush_calls.iter().map(|(_, v)| *v).sum();
        assert_eq!(
            total, 2,
            "total recorded requests must reach Redis after recovery, got {second_flush_calls:?}"
        );
    }

    #[tokio::test]
    async fn test_flush_bail_mode_middle_chunk_failure_credits_successful_and_requeues_rest() {
        // 3 keys × 2 cmds = 6 cmds at batch_size=2 → 3 chunks. Fail only
        // chunk 2 (call index 1). Chunk 1's HINCRBYs landed in Redis and
        // its counts must NOT be requeued (would double-credit next tick).
        // Chunks 2 and 3+ go into `requeue` under BailOnError.
        let mut mock = MockRedisClient::new();
        mock.pipeline_error_at_call(1, CustomRedisError::Timeout);
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 2,
            ..test_config()
        };
        let (_, agg) = new_test_aggregator_with_redis(mock, config);

        record_n_decide_with_library(&agg, 3);

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        // Chunk 1 succeeded; its key is gone from `pending`. Chunks 2 & 3
        // are requeued = 2 keys. A regression that also requeued chunk 1's
        // already-credited entries would land 3 here.
        assert_eq!(
            agg.pending_len(),
            2,
            "successful chunk's entries must NOT be requeued",
        );
        let pending_total: u64 = agg.inner.pending.lock().unwrap().values().sum();
        assert_eq!(pending_total, 2);
        assert_eq!(agg.inner.in_flight_uncredited.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn test_flush_best_effort_mode_attempts_all_chunks_despite_errors() {
        // Same setup as the bail-mode test but with FlushPolicy::BestEffort.
        // Every chunk fails, yet every chunk must still be attempted —
        // shutdown's last-chance semantics.
        let mut mock = MockRedisClient::new();
        mock.pipeline_error(CustomRedisError::Timeout);
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 2,
            ..test_config()
        };
        let (redis, agg) = new_test_aggregator_with_redis(mock, config);

        record_n_decide_with_library(&agg, 5);

        flush_once(&agg.inner, FlushPolicy::BestEffort).await;

        let attempted = hincrby_calls(&redis).len();
        assert_eq!(
            attempted, 10,
            "all chunks should be attempted in best-effort mode"
        );
        // Accounting closed out: in-flight cleared.
        assert_eq!(agg.inner.in_flight_uncredited.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn test_flush_best_effort_credits_successful_chunks_around_error() {
        // Fail only the second pipeline call. Surrounding chunks should land
        // and credit their counts (exercises the partial-success path that's
        // the whole point of best-effort mode).
        let mut mock = MockRedisClient::new();
        mock.pipeline_error_at_call(1, CustomRedisError::Timeout);
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 2,
            ..test_config()
        };
        let (redis, agg) = new_test_aggregator_with_redis(mock, config);

        record_n_decide_with_library(&agg, 5);

        flush_once(&agg.inner, FlushPolicy::BestEffort).await;

        // All 5 chunks were attempted (the mock records commands even on
        // injected errors), proving we continued past the failing chunk.
        let attempted = hincrby_calls(&redis).len();
        assert_eq!(attempted, 10);
        // Accounting closed out.
        assert_eq!(agg.inner.in_flight_uncredited.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn test_flush_best_effort_flushes_trailing_partial_after_error() {
        // Best-effort mode attempts the trailing partial chunk even if earlier
        // chunks errored. 3 keys w/ libraries (6 cmds) + 1 key w/o library
        // (1 cmd) = 7 cmds at batch_size=3 → 2 full chunks + 1 trailing
        // 1-cmd chunk. Fail only the first pipeline call; assert the
        // trailing partial still got attempted.
        let mut mock = MockRedisClient::new();
        mock.pipeline_error_at_call(0, CustomRedisError::Timeout);
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 3,
            ..test_config()
        };
        let (redis, agg) = new_test_aggregator_with_redis(mock, config);

        for team_id in 1..=3 {
            agg.record(team_id, FlagRequestType::Decide, Some(Library::PosthogJs));
        }
        agg.record(99, FlagRequestType::Decide, None);

        flush_once(&agg.inner, FlushPolicy::BestEffort).await;

        // All 7 commands attempted despite the first chunk's error — proves
        // both that we continued past the error AND that the trailing partial
        // still ran.
        let attempted = hincrby_calls(&redis).len();
        assert_eq!(attempted, 7);
    }

    #[tokio::test]
    async fn test_shutdown_uses_best_effort_flush() {
        // When shutdown drives the flush, all chunks must be attempted even
        // if earlier ones error. With bail-on-error, only chunk 1 would land.
        let mut mock = MockRedisClient::new();
        mock.pipeline_error(CustomRedisError::Timeout);
        let redis = Arc::new(mock);
        let agg = BillingAggregator::start(
            redis.clone(),
            BillingAggregatorConfig {
                // Long interval so shutdown drives the flush, not a tick.
                flush_interval: Duration::from_secs(60),
                per_flush_batch_size: 2,
                ..test_config()
            },
        );

        record_n_decide_with_library(&agg, 5);

        agg.shutdown().await;

        let attempted = hincrby_calls(&redis).len();
        assert_eq!(
            attempted, 10,
            "shutdown should attempt all chunks in best-effort mode"
        );
    }

    #[tokio::test]
    async fn test_flush_clears_in_flight_uncredited_on_success() {
        let (_, agg) = new_test_aggregator(test_config());
        agg.record(1, FlagRequestType::Decide, None);
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        assert_eq!(agg.inner.in_flight_uncredited.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn test_flush_clears_in_flight_uncredited_on_error() {
        let mut mock = MockRedisClient::new();
        mock.pipeline_error(CustomRedisError::Timeout);
        let (_, agg) = new_test_aggregator_with_redis(mock, test_config());
        agg.record(1, FlagRequestType::Decide, None);
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        // On completed (even errored) flush, in-flight must be cleared so a
        // later shutdown drop doesn't double-count this batch.
        assert_eq!(agg.inner.in_flight_uncredited.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn test_empty_flush_does_no_work() {
        let (redis, agg) = new_test_aggregator(test_config());

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        let calls = redis.get_calls();
        assert!(
            calls.is_empty(),
            "flushing an empty map should make zero calls"
        );
    }

    #[tokio::test]
    async fn test_flush_preserves_distinct_buckets_per_key() {
        // Two records for the same (team, request_type, library) but in
        // different buckets must produce two separate HINCRBYs (distinct
        // `field` values), preserving late-flushed records in their original
        // bucket. Inject the keys directly so the test isn't dependent on
        // wall-clock crossing a bucket boundary.
        let (redis, agg) = new_test_aggregator(test_config());

        agg.seed_pending([
            (
                AggregationKey {
                    team_id: 1,
                    request_type: FlagRequestType::Decide,
                    library: None,
                    bucket: 100,
                },
                3,
            ),
            (
                AggregationKey {
                    team_id: 1,
                    request_type: FlagRequestType::Decide,
                    library: None,
                    bucket: 101,
                },
                5,
            ),
        ]);

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        // The mock records calls as "{key}:{field}", so a per-bucket HINCRBY
        // shows up under "{team_key}:{bucket}".
        let team_key = get_team_request_shadow_key(1, FlagRequestType::Decide);
        let calls = hincrby_calls(&redis);
        let bucket_100_key = format!("{team_key}:100");
        let bucket_101_key = format!("{team_key}:101");
        assert!(
            calls.iter().any(|(k, v)| k == &bucket_100_key && *v == 3),
            "bucket 100 must produce HINCRBY count=3, got {:?}",
            calls
        );
        assert!(
            calls.iter().any(|(k, v)| k == &bucket_101_key && *v == 5),
            "bucket 101 must produce HINCRBY count=5, got {:?}",
            calls
        );
    }

    #[tokio::test]
    async fn test_flush_conserves_total_count() {
        // Conservation invariant: the sum of HINCRBY values written to Redis
        // equals the total number of recorded requests. Catches drift in
        // the per-chunk accumulators and the in_flight_uncredited bookkeeping.
        let (redis, agg) = new_test_aggregator(test_config());

        let mut expected_total: i64 = 0;
        for team_id in 1..=10 {
            for _ in 0..(team_id as usize) {
                agg.record(team_id, FlagRequestType::Decide, None);
                expected_total += 1;
            }
        }

        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        // No library = one HINCRBY per key, so summing values gives the total.
        let actual_total: i64 = hincrby_calls(&redis).iter().map(|(_, v)| *v).sum();
        assert_eq!(
            actual_total, expected_total,
            "sum of HINCRBYs must equal recorded request count"
        );
        assert_eq!(agg.pending_len(), 0, "pending must be drained on success");
        assert_eq!(
            agg.in_flight_uncredited(),
            0,
            "in-flight must be cleared on success"
        );
    }

    #[tokio::test]
    async fn test_shutdown_timeout_credits_residual_to_in_flight() {
        // When the flush hangs and the shutdown timeout fires, the recorded
        // count must be fully accounted for: pending is drained into the
        // flush-local map (so pending_len == 0), and the count is parked in
        // `in_flight_uncredited` so record_shutdown_drops can credit it as a
        // drop. This is the invariant that
        // `flags_billing_unflushed_requests_total{cause="shutdown_drop"}` depends on.
        let mut mock = MockRedisClient::new();
        mock.pipeline_block(Duration::from_secs(60)); // outlasts the timeout
        let redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock);
        let config = BillingAggregatorConfig {
            flush_interval: Duration::from_millis(20),
            shutdown_flush_timeout: Duration::from_millis(50),
            ..test_config()
        };
        let agg = BillingAggregator::start(redis, config);

        for _ in 0..7 {
            agg.record(1, FlagRequestType::Decide, None);
        }
        // Wait for the flusher to drain `pending` and park the count in
        // `in_flight_uncredited` (which `flush_once` writes before its first
        // `.await`). Polling on `in_flight_uncredited` rather than sleeping
        // a fixed duration keeps the test deterministic on slow CI.
        for _ in 0..200 {
            if agg.in_flight_uncredited() == 7 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        assert_eq!(
            agg.pending_len(),
            0,
            "pending must be drained into the in-flight flush before shutdown"
        );
        assert_eq!(
            agg.in_flight_uncredited(),
            7,
            "drained count must be parked in in_flight_uncredited so the timeout path can credit it as a drop"
        );

        agg.shutdown().await;

        // After shutdown returns, all bookkeeping must close out: the
        // residual count was credited via `record_shutdown_drops`, and both
        // accumulators are zero. Without this assertion, a regression that
        // skipped `record_shutdown_drops` on the timeout path would still
        // pass — the residual would silently leak with no signal.
        assert_eq!(
            agg.pending_len(),
            0,
            "pending must remain empty after shutdown"
        );
        assert_eq!(
            agg.pending_total(),
            0,
            "pending_total must remain zero after shutdown"
        );
        assert_eq!(
            agg.in_flight_uncredited(),
            7,
            "in_flight_uncredited stays at the residual after shutdown — \
             record_shutdown_drops reads it but does not zero it. Any future \
             refactor that resets this on shutdown must also retain a way to \
             prove the drops were emitted; otherwise this test pin breaks."
        );
    }

    #[tokio::test]
    async fn test_record_during_in_flight_flush_lands_in_next_batch() {
        // The flusher releases the `pending` lock right after `mem::take`, so
        // a `record()` arriving while Redis is still in flight must land in
        // a fresh empty map and wait for the next flush. Regression guard
        // for any future change that inadvertently holds the lock across
        // `.await` — that would block `record()` for the duration of the
        // Redis round-trip on the request hot path.
        let mut mock = MockRedisClient::new();
        mock.pipeline_block(Duration::from_millis(100));
        let (redis, agg) = new_test_aggregator_with_redis(mock, test_config());

        agg.record(1, FlagRequestType::Decide, None);

        // Spawn the flush so we can race a `record()` against the in-flight
        // pipeline. Use a separate `Arc` clone for the task.
        let agg_for_flush = agg.clone();
        let flush = tokio::spawn(async move {
            flush_once(&agg_for_flush.inner, FlushPolicy::BailOnError).await;
        });

        // Wait until the flusher has drained `pending` and is parked on the
        // Redis await — `in_flight_uncredited` is set just before the first
        // `.await`, so observing it non-zero is the deterministic proof.
        // Polling beats sleeping a fixed duration: the latter would race
        // scheduler latency on slow CI.
        wait_until(|| agg.in_flight_uncredited() > 0).await;
        // The hot-path contract is that `record()` returns in microseconds
        // even while a flush is in flight. If a future change holds the
        // `pending` lock across the await, this call would block for the
        // remainder of the 100ms `pipeline_block` window. 25ms is generous
        // for a HashMap insert (~hundreds of ns) and tight enough to fail
        // hard if the lock is held.
        let record_start = std::time::Instant::now();
        agg.record(2, FlagRequestType::Decide, None);
        let record_elapsed = record_start.elapsed();
        assert!(
            record_elapsed < Duration::from_millis(25),
            "record() blocked for {record_elapsed:?} while a flush was in flight — \
             a regression that holds the pending lock across .await would block \
             the hot path for the duration of the Redis round-trip"
        );

        flush.await.unwrap();

        assert_eq!(
            agg.pending_len(),
            1,
            "record(2) must land in the post-drain map and wait for next flush"
        );
        let calls = hincrby_calls(&redis);
        assert_eq!(
            calls.len(),
            1,
            "only the in-flight chunk (record(1)) should have flushed, got {calls:?}"
        );
        assert_eq!(calls[0].1, 1, "the flushed HINCRBY count must be 1");
    }

    #[tokio::test]
    async fn test_empty_drain_stamps_last_successful_epoch() {
        // An idle pod runs the flusher tick with nothing to drain. That is
        // still evidence the loop is alive, so the staleness gauge must
        // reset — otherwise a low-traffic pod that flushed at boot would
        // show monotonically rising `seconds_since_successful_flush` and
        // trip the wedged-flusher alarm despite being healthy.
        let (_, agg) = new_test_aggregator(test_config());

        let before = now_epoch_ms();
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        let after = now_epoch_ms();

        let stamped = agg
            .inner
            .last_successful_flush_epoch_ms
            .load(Ordering::Relaxed);
        assert!(
            (before..=after).contains(&stamped),
            "empty drain stamp {stamped} must be in [{before}, {after}]",
        );
    }

    #[tokio::test]
    async fn test_successful_flush_stamps_last_successful_epoch() {
        let (_, agg) = new_test_aggregator(test_config());
        assert_eq!(
            agg.inner
                .last_successful_flush_epoch_ms
                .load(Ordering::Relaxed),
            0,
            "no flush yet → epoch stays zero"
        );

        let before = now_epoch_ms();
        agg.record(1, FlagRequestType::Decide, None);
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        let after = now_epoch_ms();

        let stamped = agg
            .inner
            .last_successful_flush_epoch_ms
            .load(Ordering::Relaxed);
        // `stamped > 0` would be true on any clock past 1970 even if the
        // code stored a stale or constant value. Bracketing pins the stamp
        // to the actual flush moment.
        assert!(
            (before..=after).contains(&stamped),
            "stamp {stamped} must be in [{before}, {after}]",
        );
    }

    #[tokio::test]
    async fn test_failed_flush_does_not_overwrite_prior_successful_epoch() {
        // Prime with a successful flush so the epoch holds a known
        // non-zero value, then run a failing flush. The failure must
        // leave the prior stamp intact (not zero it, not overwrite it).
        // A test that only verifies "still 0" can't distinguish "field
        // never written" from "field correctly preserved."
        let mut mock = MockRedisClient::new();
        mock.pipeline_error_at_call(1, CustomRedisError::Timeout);
        let (_, agg) = new_test_aggregator_with_redis(mock, test_config());

        agg.record(1, FlagRequestType::Decide, None);
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;
        let primed = agg
            .inner
            .last_successful_flush_epoch_ms
            .load(Ordering::Relaxed);
        assert!(primed > 0, "priming flush must stamp the epoch");

        agg.record(2, FlagRequestType::Decide, None);
        flush_once(&agg.inner, FlushPolicy::BailOnError).await;

        let after = agg
            .inner
            .last_successful_flush_epoch_ms
            .load(Ordering::Relaxed);
        assert_eq!(
            after, primed,
            "failed flush must not disturb the prior success stamp",
        );
    }

    #[tokio::test]
    async fn test_best_effort_partial_success_does_not_stamp_epoch() {
        // A BestEffort (shutdown) flush that succeeds on some chunks but
        // errors on others is not a "successful flush" — dropped_counts > 0
        // and the staleness gauge should keep ticking.
        let mut mock = MockRedisClient::new();
        mock.pipeline_error_at_call(1, CustomRedisError::Timeout);
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 2,
            ..test_config()
        };
        let (_, agg) = new_test_aggregator_with_redis(mock, config);

        record_n_decide_with_library(&agg, 5);
        flush_once(&agg.inner, FlushPolicy::BestEffort).await;

        assert_eq!(
            agg.inner
                .last_successful_flush_epoch_ms
                .load(Ordering::Relaxed),
            0,
            "partial-success flush must not stamp the epoch"
        );
    }

    #[test]
    fn test_sample_metrics_reads_live_pending_and_in_flight() {
        // Smoke test: sample_metrics doesn't panic on any inner state
        // (zero epoch, non-empty pending, live in-flight). The staleness
        // math is asserted directly via `compute_staleness_seconds` below.
        let (_, agg) = new_test_aggregator(test_config());
        agg.record(1, FlagRequestType::Decide, None);
        agg.record(2, FlagRequestType::Decide, None);
        agg.inner.in_flight_uncredited.store(42, Ordering::Relaxed);

        sample_metrics(&agg.inner);

        agg.inner
            .last_successful_flush_epoch_ms
            .store(now_epoch_ms(), Ordering::Relaxed);
        sample_metrics(&agg.inner);
    }

    #[test]
    fn test_staleness_is_zero_before_first_flush() {
        // A freshly booted pod with no traffic must not trip the
        // stale-flush alarm. `last_ms == 0` is the sentinel for "no
        // successful flush yet" and must collapse to 0 seconds, not
        // "decades since 1970".
        assert_eq!(compute_staleness_seconds(0, 1_700_000_000_000), 0.0);
        assert_eq!(compute_staleness_seconds(0, 0), 0.0);
    }

    #[test]
    fn test_staleness_reports_seconds_since_last_flush() {
        assert_eq!(
            compute_staleness_seconds(1_700_000_000_000, 1_700_000_005_500),
            5.5,
        );
        assert_eq!(
            compute_staleness_seconds(1_700_000_000_000, 1_700_000_000_001),
            0.001,
        );
    }

    #[test]
    fn test_staleness_saturates_on_backward_clock_skew() {
        // Backward NTP step: now < last. Saturating subtract clamps to 0
        // rather than wrapping into a huge positive value that would
        // misfire the staleness alarm.
        assert_eq!(
            compute_staleness_seconds(1_700_000_005_000, 1_700_000_000_000),
            0.0,
        );
    }

    #[test]
    fn test_config_validate_rejects_zero_flush_interval() {
        let config = BillingAggregatorConfig {
            flush_interval: Duration::ZERO,
            ..test_config()
        };
        let err = config.validate().unwrap_err();
        assert!(
            err.contains("flush_interval"),
            "error should name the bad knob, got: {err}"
        );
    }

    #[test]
    fn test_config_validate_rejects_zero_max_pending_entries() {
        let config = BillingAggregatorConfig {
            max_pending_entries: 0,
            ..test_config()
        };
        let err = config.validate().unwrap_err();
        assert!(err.contains("max_pending_entries"), "got: {err}");
    }

    #[test]
    fn test_config_validate_rejects_zero_per_flush_batch_size() {
        let config = BillingAggregatorConfig {
            per_flush_batch_size: 0,
            ..test_config()
        };
        let err = config.validate().unwrap_err();
        assert!(err.contains("per_flush_batch_size"), "got: {err}");
    }

    #[test]
    fn test_config_validate_rejects_zero_shutdown_flush_timeout() {
        let config = BillingAggregatorConfig {
            shutdown_flush_timeout: Duration::ZERO,
            ..test_config()
        };
        let err = config.validate().unwrap_err();
        assert!(err.contains("shutdown_flush_timeout"), "got: {err}");
    }

    #[test]
    fn test_config_validate_accepts_default() {
        assert!(BillingAggregatorConfig::default().validate().is_ok());
    }

    #[tokio::test]
    #[should_panic(expected = "invalid BillingAggregatorConfig")]
    async fn test_start_panics_on_invalid_config() {
        let redis = Arc::new(MockRedisClient::new());
        BillingAggregator::start(
            redis,
            BillingAggregatorConfig {
                flush_interval: Duration::ZERO,
                ..test_config()
            },
        );
    }
}
