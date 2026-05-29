use std::collections::HashMap;
use std::time::Instant;

use futures::StreamExt;
use tokio::sync::mpsc;
use tonic::Status;
use tracing::{debug, warn};

use cymbal::error::UnhandledError;
use cymbal::langs::apple::AppleDebugImage;
use cymbal::stages::resolution::exception::ExceptionResolver;
use cymbal::stages::resolution::frame::FrameResolver;
use cymbal::stages::resolution::ResolutionStage;
use cymbal::types::Exception;
use cymbal_proto::cymbal::resolution::v1::{
    item_outcome, outcome, BatchSummary, Done, Error as ItemError, ItemOutcome, ItemReference,
    Outcome, ResolveRequest, Retry,
};

use super::codes;
use crate::item_limiter::ItemLimiter;
use crate::load_monitor::LoadMonitor;

const RESOLVE_REQUEST_DURATION_MS: &str = "cymbal_remote_resolution_server_request_duration_ms";

pub(super) async fn run_resolve(
    req: ResolveRequest,
    stage: ResolutionStage,
    tx: mpsc::Sender<Result<Outcome, Status>>,
    item_limiter: ItemLimiter,
    load_monitor: LoadMonitor,
) {
    let batch_id = req.batch_id;
    let submitted_items = req.items.len() as u32;
    let started_at = Instant::now();

    let mut sequence: u64 = 0;
    let mut next_sequence = || {
        sequence += 1;
        sequence
    };

    // Per-RPC scheduling width: never spawn more concurrent item futures
    // than the global cap could ever satisfy. The semaphore is the true
    // gate; this just keeps a single huge batch from filling memory with
    // permit waiters.
    let scheduling_width = item_limiter.max_permits();

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

    let guarded_items: Vec<_> = req
        .items
        .into_iter()
        .map(|item| (item, InFlightGuard::new(load_monitor.clone())))
        .collect();

    // The item limiter is the real cap on cross-request parallelism. The
    // outer `buffer_unordered` width is bounded by `scheduling_width` so a
    // single huge batch doesn't fill memory with permit waiters; the semaphore
    // ensures total active item processing across all RPCs never exceeds the cap.
    let mut processed_items =
        futures::stream::iter(guarded_items.into_iter().map(|(item, in_flight_guard)| {
            let stage = stage.clone();
            let item_limiter = item_limiter.clone();
            async move { process_item(stage, item, item_limiter, in_flight_guard).await }
        }))
        .buffer_unordered(scheduling_width);

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

struct InFlightGuard {
    load_monitor: LoadMonitor,
}

impl InFlightGuard {
    fn new(load_monitor: LoadMonitor) -> Self {
        load_monitor.increment_in_flight();
        Self { load_monitor }
    }
}

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        self.load_monitor.decrement_in_flight();
    }
}

async fn process_item(
    stage: ResolutionStage,
    item: cymbal_proto::cymbal::resolution::v1::ExceptionResolutionItem,
    item_limiter: ItemLimiter,
    in_flight_guard: InFlightGuard,
) -> ProcessedItem {
    let item_id = item.item_id.clone();
    let item_index = item.item_index;
    let _in_flight_guard = in_flight_guard;

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
