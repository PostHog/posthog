use std::sync::Arc;
use std::time::{Duration, Instant};

use cymbal::error::UnhandledError;
use cymbal::langs::apple::AppleDebugImage;
use cymbal::stages::resolution::exception::ExceptionResolver;
use cymbal::stages::resolution::frame::FrameResolver;
use cymbal::stages::resolution::symbol::SymbolResolver;
use cymbal::stages::resolution::ResolutionStage;
use cymbal::types::Exception;

use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolution;
use cymbal_proto::cymbal::resolution::v1::{
    item_outcome, outcome, BatchSummary, Done, Error as ItemError, ItemOutcome, ItemReference,
    LoadEvent, Outcome, ResolveRequest, Retry, SubscribeRequest,
};

use futures::{Stream, StreamExt};
use std::collections::HashMap;
use std::pin::Pin;
use tokio::sync::mpsc;
use tokio::sync::Semaphore;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status};
use tracing::{debug, info, warn};

// Error and retry code constants surfaced to the caller in v1. Defined near the
// handler so test fixtures and client retry classification stay in sync as the
// taxonomy evolves. See cymbal-proto's ItemOutcome.Error/Retry for envelope.
pub mod codes {
    /// The caller-supplied exception/debug-image payload could not be parsed.
    pub const ERROR_INVALID_PAYLOAD: &str = "invalid_payload";
    /// The handler encountered an unhandled internal error while resolving.
    pub const ERROR_UNHANDLED: &str = "unhandled";
    /// The service refused the item because it could not acquire a
    /// symbol-resolution permit before its deadline. Cymbal may retry the
    /// item against another endpoint per caller-side policy.
    pub const RETRY_OVERLOADED: &str = "overloaded";
}

/// Channel buffer for streamed outcomes. Sized to absorb a short backlog while
/// the caller drains; not a queue replacement for backpressure.
const OUTCOME_CHANNEL_BUFFER: usize = 64;

/// Channel buffer for the Subscribe stream. Small on purpose — the stream is
/// monotonic ticks, so a slow consumer should rather pause than buffer.
const SUBSCRIBE_CHANNEL_BUFFER: usize = 4;

const RESOLVE_REQUEST_DURATION_MS: &str = "cymbal_remote_resolution_server_request_duration_ms";

/// Configuration handed to the gRPC service. Subset of [`crate::config::Config`]
/// that the handler actually needs; isolating it lets tests construct the
/// service without touching the env-var surface.
#[derive(Clone, Debug)]
pub struct ServiceConfig {
    pub default_tick_interval: Duration,
    pub min_tick_interval: Duration,
    pub max_tick_interval: Duration,
    /// Load ratio (in_flight / max_in_flight) at which the server flips
    /// `LoadEvent.degraded` so callers spill over to another pod before the
    /// admission queue load-sheds with UNAVAILABLE.
    pub degraded_load_ratio: f64,
}

impl From<&crate::config::Config> for ServiceConfig {
    fn from(cfg: &crate::config::Config) -> Self {
        Self {
            default_tick_interval: Duration::from_millis(cfg.subscribe_tick_interval_ms),
            min_tick_interval: Duration::from_millis(cfg.subscribe_min_tick_ms),
            max_tick_interval: Duration::from_millis(cfg.subscribe_max_tick_ms),
            degraded_load_ratio: cfg.degraded_load_ratio,
        }
    }
}

impl ServiceConfig {
    /// Resolve the effective tick cadence for a Subscribe stream given an
    /// optional caller hint. `0` means "use the server default"; other values
    /// are clamped to `[min, max]`.
    pub fn resolve_tick_interval(&self, hint_ms: u32) -> Duration {
        let candidate = if hint_ms == 0 {
            self.default_tick_interval
        } else {
            Duration::from_millis(hint_ms as u64)
        };
        let lo = self.min_tick_interval;
        let hi = self.max_tick_interval.max(lo);
        candidate.clamp(lo, hi)
    }

    /// Effective degraded threshold, clamped to `(0.0, 1.0]`. Values <= 0 or
    /// NaN fall back to a sentinel that never flips degraded; values above 1.0
    /// are clamped to 1.0 so the signal still fires at full saturation.
    pub fn effective_degraded_load_ratio(&self) -> f64 {
        if !self.degraded_load_ratio.is_finite() || self.degraded_load_ratio <= 0.0 {
            f64::INFINITY
        } else {
            self.degraded_load_ratio.min(1.0)
        }
    }
}

pub struct CymbalResolutionService {
    symbol_resolver: Arc<dyn SymbolResolver>,
    symbol_resolution_limiter: Arc<Semaphore>,
    item_limiter: Arc<Semaphore>,
    service_instance_id: Arc<str>,
    /// Total permits configured on `item_limiter`. Reported to callers via
    /// `LoadEvent.max_in_flight` so the pool can compute a load ratio without
    /// needing a separate config exchange. Also caps the per-request scheduling
    /// width in `run_resolve`.
    max_in_flight: u32,
    service_config: ServiceConfig,
}

impl CymbalResolutionService {
    pub fn new(
        symbol_resolver: Arc<dyn SymbolResolver>,
        symbol_resolution_limiter: Arc<Semaphore>,
        item_limiter: Arc<Semaphore>,
        service_instance_id: impl Into<Arc<str>>,
        max_in_flight: u32,
        service_config: ServiceConfig,
    ) -> Self {
        Self {
            symbol_resolver,
            symbol_resolution_limiter,
            item_limiter,
            service_instance_id: service_instance_id.into(),
            max_in_flight,
            service_config,
        }
    }

    fn resolution_stage(&self) -> ResolutionStage {
        ResolutionStage {
            symbol_resolver: self.symbol_resolver.clone(),
            symbol_resolution_limiter: self.symbol_resolution_limiter.clone(),
            // The cymbal-resolution server never enables remote mode itself;
            // it is the server side that cymbal talks to. Local resolution is
            // the only valid path here.
            remote: None,
        }
    }
}

type ResolveStream = Pin<Box<dyn Stream<Item = Result<Outcome, Status>> + Send>>;
type SubscribeStream = Pin<Box<dyn Stream<Item = Result<LoadEvent, Status>> + Send>>;

#[tonic::async_trait]
impl CymbalResolution for CymbalResolutionService {
    type ResolveStream = ResolveStream;
    type SubscribeStream = SubscribeStream;

    async fn resolve(
        &self,
        request: Request<ResolveRequest>,
    ) -> Result<Response<Self::ResolveStream>, Status> {
        let req = request.into_inner();

        let stage = self.resolution_stage();

        let (tx, rx) = mpsc::channel::<Result<Outcome, Status>>(OUTCOME_CHANNEL_BUFFER);

        let item_limiter = self.item_limiter.clone();
        // Per-RPC scheduling width: never spawn more concurrent item futures
        // than the global cap could ever satisfy. The semaphore is the true
        // gate; this just keeps a single huge batch from filling memory with
        // permit waiters.
        let scheduling_width = (self.max_in_flight as usize).max(1);

        tokio::spawn(async move {
            run_resolve(req, stage, tx, item_limiter, scheduling_width).await;
        });

        let stream = ReceiverStream::new(rx);
        let boxed: ResolveStream = Box::pin(stream);
        Ok(Response::new(boxed))
    }

    async fn subscribe(
        &self,
        request: Request<SubscribeRequest>,
    ) -> Result<Response<Self::SubscribeStream>, Status> {
        let req = request.into_inner();
        let tick = self.service_config.resolve_tick_interval(req.tick_hint_ms);
        let subscriber_id = if req.subscriber_id.is_empty() {
            "<anonymous>".to_string()
        } else {
            req.subscriber_id.clone()
        };
        info!(
            subscriber = %subscriber_id,
            tick_ms = tick.as_millis() as u64,
            "load event bus subscription opened",
        );

        let (tx, rx) = mpsc::channel::<Result<LoadEvent, Status>>(SUBSCRIBE_CHANNEL_BUFFER);
        let service_instance_id = self.service_instance_id.clone();
        // Report item-limiter pressure to callers: it is the new primary
        // admission gate and the right signal for routing/spillover. The
        // symbol limiter is downstream and bounds the noisier cache-miss path
        // independently.
        let limiter = self.item_limiter.clone();
        let max_in_flight = self.max_in_flight;
        let degraded_threshold = self.service_config.effective_degraded_load_ratio();

        tokio::spawn(async move {
            run_subscribe(
                tx,
                service_instance_id,
                limiter,
                max_in_flight,
                degraded_threshold,
                tick,
                subscriber_id,
            )
            .await;
        });

        let stream = ReceiverStream::new(rx);
        let boxed: SubscribeStream = Box::pin(stream);
        Ok(Response::new(boxed))
    }
}

async fn run_resolve(
    req: ResolveRequest,
    stage: ResolutionStage,
    tx: mpsc::Sender<Result<Outcome, Status>>,
    item_limiter: Arc<Semaphore>,
    scheduling_width: usize,
) {
    let batch_id = req.batch_id;
    let submitted_items = req.items.len() as u32;
    let started_at = Instant::now();

    let mut sequence: u64 = 0;
    let mut next_sequence = || {
        sequence += 1;
        sequence
    };

    // Track per-(item_id, item_index) emit counts so the terminal BatchSummary
    // can flag missing and duplicate items without re-walking the request.
    let mut emit_counts: HashMap<(String, u32), u32> = HashMap::new();
    let mut done_items: u32 = 0;
    let mut error_items: u32 = 0;
    let mut retry_items: u32 = 0;
    let mut item_outcomes_count: u32 = 0;

    let expected_items: Vec<ItemReference> = req
        .items
        .iter()
        .map(|item| ItemReference {
            item_id: item.item_id.clone(),
            item_index: item.item_index,
        })
        .collect();

    // The item limiter is the real cap on cross-request parallelism. The
    // outer `buffer_unordered` width is bounded by `scheduling_width` so a
    // single huge batch doesn't fill memory with permit waiters; the semaphore
    // ensures total in-flight items across all RPCs never exceeds the cap.
    let mut processed_items = futures::stream::iter(req.items.into_iter().map(|item| {
        let stage = stage.clone();
        let item_limiter = item_limiter.clone();
        async move { process_item(stage, item, item_limiter).await }
    }))
    .buffer_unordered(scheduling_width.max(1));

    loop {
        let processed = tokio::select! {
            _ = tx.closed() => {
                record_resolve_duration(started_at, "cancelled");
                return;
            }
            maybe_processed = processed_items.next() => {
                let Some(processed) = maybe_processed else {
                    break;
                };
                processed
            }
        };

        match &processed.result {
            item_outcome::Result::Done(_) => done_items += 1,
            item_outcome::Result::Error(_) => error_items += 1,
            item_outcome::Result::Retry(_) => retry_items += 1,
        }

        let entry = emit_counts
            .entry((processed.item_id.clone(), processed.item_index))
            .or_insert(0);
        *entry += 1;
        item_outcomes_count += 1;

        if tx
            .send(Ok(Outcome {
                batch_id: batch_id.clone(),
                sequence: next_sequence(),
                message: Some(outcome::Message::ItemOutcome(ItemOutcome {
                    item_id: processed.item_id,
                    item_index: processed.item_index,
                    result: Some(processed.result),
                })),
            }))
            .await
            .is_err()
        {
            record_resolve_duration(started_at, "cancelled");
            return;
        }
    }

    // Compute reconciliation from observed emissions rather than assuming the
    // happy path. That keeps the summary self-checking if a future change adds
    // skip/defer paths or cancellation-aware item handling.
    let duplicate_items: Vec<ItemReference> = emit_counts
        .iter()
        .filter(|(_, count)| **count > 1)
        .map(|((item_id, item_index), _)| ItemReference {
            item_id: item_id.clone(),
            item_index: *item_index,
        })
        .collect();
    let missing_items: Vec<ItemReference> = expected_items
        .into_iter()
        .filter(|item| {
            emit_counts
                .get(&(item.item_id.clone(), item.item_index))
                .copied()
                .unwrap_or(0)
                == 0
        })
        .collect();

    let summary = BatchSummary {
        submitted_items,
        item_outcomes: item_outcomes_count,
        done_items,
        error_items,
        retry_items,
        missing_items,
        duplicate_items,
    };

    let sent = tx
        .send(Ok(Outcome {
            batch_id,
            sequence: next_sequence(),
            message: Some(outcome::Message::BatchSummary(summary)),
        }))
        .await
        .is_ok();
    record_resolve_duration(started_at, if sent { "completed" } else { "cancelled" });
}

struct ProcessedItem {
    item_id: String,
    item_index: u32,
    result: item_outcome::Result,
}

async fn process_item(
    stage: ResolutionStage,
    item: cymbal_proto::cymbal::resolution::v1::ExceptionResolutionItem,
    item_limiter: Arc<Semaphore>,
) -> ProcessedItem {
    let item_id = item.item_id.clone();
    let item_index = item.item_index;

    // Acquire a global item permit before doing any per-item work. If the
    // semaphore has been closed (process shutting down), surface as Retry so
    // the caller can route the item elsewhere. The permit drops at function
    // exit, releasing the slot for the next waiter.
    let _item_permit = match item_limiter.acquire_owned().await {
        Ok(permit) => permit,
        Err(_) => {
            warn!(
                item_id = %item_id,
                item_index,
                "item limiter closed, asking caller to retry",
            );
            return ProcessedItem {
                item_id,
                item_index,
                result: item_outcome::Result::Retry(Retry {
                    code: codes::RETRY_OVERLOADED.to_string(),
                    message: "item limiter closed".to_string(),
                    retry_after_ms: 0,
                }),
            };
        }
    };

    let result = match resolve_item(&stage, &item).await {
        Ok(resolved) => item_outcome::Result::Done(Done {
            resolved_exception_json: resolved,
        }),
        Err(ItemFailure::Invalid(msg)) => {
            debug!(
                item_id = %item_id,
                item_index,
                error = %msg,
                "rejecting item with invalid payload",
            );
            item_outcome::Result::Error(ItemError {
                code: codes::ERROR_INVALID_PAYLOAD.to_string(),
                message: msg,
                details_json: Vec::new(),
            })
        }
        Err(ItemFailure::Overloaded(msg)) => {
            warn!(
                item_id = %item_id,
                item_index,
                "limiter closed mid-request, asking caller to retry",
            );
            item_outcome::Result::Retry(Retry {
                code: codes::RETRY_OVERLOADED.to_string(),
                message: msg,
                retry_after_ms: 0,
            })
        }
        Err(ItemFailure::Unhandled(err)) => {
            warn!(
                item_id = %item_id,
                item_index,
                error = %err,
                "unhandled error during resolution",
            );
            item_outcome::Result::Error(ItemError {
                code: codes::ERROR_UNHANDLED.to_string(),
                message: err,
                details_json: Vec::new(),
            })
        }
    };

    ProcessedItem {
        item_id,
        item_index,
        result,
    }
}

fn record_resolve_duration(started_at: Instant, outcome: &'static str) {
    metrics::histogram!(RESOLVE_REQUEST_DURATION_MS, "outcome" => outcome)
        .record(started_at.elapsed().as_secs_f64() * 1000.0);
}

async fn run_subscribe(
    tx: mpsc::Sender<Result<LoadEvent, Status>>,
    service_instance_id: Arc<str>,
    limiter: Arc<Semaphore>,
    max_in_flight: u32,
    degraded_threshold: f64,
    tick: Duration,
    subscriber_id: String,
) {
    let mut ticker = tokio::time::interval(tick);
    // First tick fires immediately so the caller sees state without waiting
    // a full period; thereafter Delay matches the pool's polling expectation
    // (skip missed ticks instead of bursting catch-up events).
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut sequence: u64 = 0;

    loop {
        ticker.tick().await;
        if tx.is_closed() {
            // Caller dropped the stream; exit before doing more work.
            info!(subscriber = %subscriber_id, "load event bus subscription closed");
            return;
        }

        sequence += 1;
        let available = limiter.available_permits() as u32;
        let in_flight = max_in_flight.saturating_sub(available);
        let degraded = compute_degraded(in_flight, max_in_flight, degraded_threshold);
        let event = LoadEvent {
            service_instance_id: service_instance_id.as_ref().to_string(),
            degraded,
            draining: false,
            in_flight,
            max_in_flight,
            sequence,
            message: String::new(),
            // Suggest the item-admission cap as the per-request batch ceiling.
            // A single request larger than this would, if it ran solo, fill
            // the entire item limiter and block parallelism from other RPCs.
            // The server can lower this under pressure in the future.
            suggested_max_batch_items: max_in_flight,
        };
        if tx.send(Ok(event)).await.is_err() {
            info!(subscriber = %subscriber_id, "load event bus subscription closed");
            return;
        }
    }
}

/// Flip degraded once in-flight ratio crosses the configured threshold. Kept
/// outside `run_subscribe` so a unit test can exercise the edges without
/// spinning up a ticker.
fn compute_degraded(in_flight: u32, max_in_flight: u32, threshold: f64) -> bool {
    if max_in_flight == 0 || !threshold.is_finite() {
        return false;
    }
    let ratio = in_flight as f64 / max_in_flight as f64;
    ratio >= threshold
}

enum ItemFailure {
    Invalid(String),
    Overloaded(String),
    Unhandled(String),
}

async fn resolve_item(
    stage: &ResolutionStage,
    item: &cymbal_proto::cymbal::resolution::v1::ExceptionResolutionItem,
) -> Result<Vec<u8>, ItemFailure> {
    let exception_payload = item
        .exception
        .as_ref()
        .ok_or_else(|| ItemFailure::Invalid("missing exception payload".to_string()))?;

    let exception: Exception = serde_json::from_slice(&exception_payload.exception_json)
        .map_err(|e| ItemFailure::Invalid(format!("invalid exception_json: {e}")))?;

    let debug_images: Vec<AppleDebugImage> = if exception_payload.apple_debug_images_json.is_empty()
    {
        Vec::new()
    } else {
        serde_json::from_slice(&exception_payload.apple_debug_images_json)
            .map_err(|e| ItemFailure::Invalid(format!("invalid apple_debug_images_json: {e}")))?
    };

    let resolved = resolve_one_exception(stage.clone(), item.team_id, exception, debug_images)
        .await
        .map_err(|e| match e {
            ResolveOneError::Overloaded => {
                ItemFailure::Overloaded("symbol-resolution limiter unavailable".to_string())
            }
            ResolveOneError::Unhandled(err) => ItemFailure::Unhandled(err),
        })?;

    serde_json::to_vec(&resolved)
        .map_err(|e| ItemFailure::Unhandled(format!("serialize resolved exception: {e}")))
}

enum ResolveOneError {
    Overloaded,
    Unhandled(String),
}

async fn resolve_one_exception(
    stage: ResolutionStage,
    team_id: i32,
    exception: Exception,
    debug_images: Vec<AppleDebugImage>,
) -> Result<Exception, ResolveOneError> {
    let exception = if ExceptionResolver::is_java_exception(&exception) {
        let _permit = acquire_permit(&stage).await?;
        stage
            .symbol_resolver
            .resolve_java_exception(team_id, exception)
            .await
            .map_err(to_unhandled)?
    } else if ExceptionResolver::is_dart_exception(&exception) {
        let _permit = acquire_permit(&stage).await?;
        stage
            .symbol_resolver
            .resolve_dart_exception(team_id, exception)
            .await
            .map_err(to_unhandled)?
    } else {
        exception
    };

    FrameResolver::resolve_exception_frames(team_id, exception, &debug_images, stage)
        .await
        .map_err(to_unhandled)
}

async fn acquire_permit(
    stage: &ResolutionStage,
) -> Result<tokio::sync::OwnedSemaphorePermit, ResolveOneError> {
    stage
        .acquire_symbol_resolution_permit()
        .await
        .map_err(|_| ResolveOneError::Overloaded)
}

fn to_unhandled(err: UnhandledError) -> ResolveOneError {
    ResolveOneError::Unhandled(err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_tick_interval_uses_default_when_hint_is_zero() {
        let cfg = ServiceConfig {
            default_tick_interval: Duration::from_millis(1000),
            min_tick_interval: Duration::from_millis(100),
            max_tick_interval: Duration::from_millis(5000),
            degraded_load_ratio: f64::INFINITY,
        };
        assert_eq!(cfg.resolve_tick_interval(0), Duration::from_millis(1000));
    }

    #[test]
    fn resolve_tick_interval_clamps_hint_to_bounds() {
        let cfg = ServiceConfig {
            default_tick_interval: Duration::from_millis(1000),
            min_tick_interval: Duration::from_millis(100),
            max_tick_interval: Duration::from_millis(5000),
            degraded_load_ratio: f64::INFINITY,
        };
        // Below the floor — clamped up.
        assert_eq!(cfg.resolve_tick_interval(10), Duration::from_millis(100));
        // Above the ceiling — clamped down.
        assert_eq!(
            cfg.resolve_tick_interval(60_000),
            Duration::from_millis(5000)
        );
        // Inside the band — taken as-is.
        assert_eq!(cfg.resolve_tick_interval(750), Duration::from_millis(750));
    }

    #[test]
    fn compute_degraded_flips_at_threshold() {
        // Below threshold: not degraded.
        assert!(!compute_degraded(7, 10, 0.8));
        // At threshold: degraded (>= comparison).
        assert!(compute_degraded(8, 10, 0.8));
        // Above threshold: degraded.
        assert!(compute_degraded(10, 10, 0.8));
        // Zero in-flight: never degraded.
        assert!(!compute_degraded(0, 10, 0.8));
    }

    #[test]
    fn compute_degraded_handles_degenerate_inputs() {
        // Zero capacity collapses to "never degraded" rather than divide-by-zero.
        assert!(!compute_degraded(5, 0, 0.5));
        // Non-finite threshold is treated as "never degraded" — this is how
        // `effective_degraded_load_ratio()` disables the signal.
        assert!(!compute_degraded(10, 10, f64::INFINITY));
        assert!(!compute_degraded(10, 10, f64::NAN));
    }

    #[test]
    fn effective_degraded_load_ratio_clamps_and_disables() {
        let mut cfg = ServiceConfig {
            default_tick_interval: Duration::from_millis(1000),
            min_tick_interval: Duration::from_millis(100),
            max_tick_interval: Duration::from_millis(5000),
            degraded_load_ratio: 0.8,
        };
        assert!((cfg.effective_degraded_load_ratio() - 0.8).abs() < f64::EPSILON);

        // Above 1.0 clamps to 1.0 — degraded fires at full saturation.
        cfg.degraded_load_ratio = 1.5;
        assert!((cfg.effective_degraded_load_ratio() - 1.0).abs() < f64::EPSILON);

        // Zero/negative/NaN disable the signal entirely.
        cfg.degraded_load_ratio = 0.0;
        assert!(cfg.effective_degraded_load_ratio().is_infinite());
        cfg.degraded_load_ratio = -0.1;
        assert!(cfg.effective_degraded_load_ratio().is_infinite());
        cfg.degraded_load_ratio = f64::NAN;
        assert!(cfg.effective_degraded_load_ratio().is_infinite());
    }
}
