use std::time::{Duration, Instant};

use tokio::sync::mpsc;
use tonic::{Status, Streaming};
use tracing::{debug, warn};

use cymbal::error::UnhandledError;
use cymbal::langs::apple::AppleDebugImage;
use cymbal::stages::resolution::exception::ExceptionResolver;
use cymbal::stages::resolution::frame::FrameResolver;
use cymbal::stages::resolution::ResolutionStage;
use cymbal::types::Exception;
use cymbal_proto::cymbal::resolution::v1::{
    resolve_outcome, Done, Error as ItemError, ResolveItem, ResolveOutcome,
};

use super::codes;
use crate::load_monitor::LoadMonitor;

// Per-stream lifecycle counter — increments once per Resolve gRPC stream when
// it closes. Use the gRPC layer's `grpc_server_request_duration_ms` for
// stream-level latency; this counter only distinguishes how the stream ended.
const RESOLVE_STREAMS_TOTAL: &str = "cymbal_resolution_resolve_streams_total";
// Per-item completion counter — increments once per item that flows through
// `process_item`, labelled by `result` and source `lang`. Use for throughput
// and success-ratio queries.
const ITEMS_TOTAL: &str = "cymbal_resolution_items_total";
// Per-item processing time, labelled by source `lang`. Buckets are widened in
// `main.rs` because symbol fetches can push the tail past 10s.
const ITEM_DURATION_MS: &str = "cymbal_resolution_item_duration_ms";
// Per-item error counter — increments only on error paths, labelled by error
// `kind` (proto enum) and source `lang`.
const ERRORS_TOTAL: &str = "cymbal_resolution_errors_total";

pub const ITEM_DURATION_BUCKETS_MS: &[f64] = &[
    1.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 30000.0,
];

pub(super) async fn run_resolve(
    mut input: Streaming<ResolveItem>,
    stage: ResolutionStage,
    tx: mpsc::Sender<Result<ResolveOutcome, Status>>,
    load_monitor: LoadMonitor,
) {
    loop {
        let item = tokio::select! {
            _ = tx.closed() => {
                record_stream_outcome("cancelled");
                return;
            }
            maybe_item = input.message() => {
                match maybe_item {
                    Ok(Some(item)) => item,
                    Ok(None) => break,
                    Err(err) => {
                        warn!(error = %err, "resolve input stream failed");
                        record_stream_outcome("input_error");
                        return;
                    }
                }
            }
        };

        if item.deadline_ms == 0 {
            if !send_overloaded(&tx, item.id, "item deadline expired").await {
                record_stream_outcome("cancelled");
                return;
            }
            continue;
        }

        if !load_monitor.try_admit() {
            if !send_overloaded(&tx, item.id, "server overloaded").await {
                record_stream_outcome("cancelled");
                return;
            }
            continue;
        }

        let item_tx = tx.clone();
        let item_stage = stage.clone();
        let in_flight_guard = InFlightGuard::new(load_monitor.clone());
        tokio::spawn(async move {
            let processed = process_item(item_stage, item, in_flight_guard).await;
            let _ignored = item_tx
                .send(Ok(ResolveOutcome {
                    id: processed.id,
                    result: Some(processed.result),
                }))
                .await;
        });
    }

    record_stream_outcome("completed");
}

async fn send_overloaded(
    tx: &mpsc::Sender<Result<ResolveOutcome, Status>>,
    id: u64,
    message: impl Into<String>,
) -> bool {
    // Pre-admission rejects never see the payload, so language is unknown.
    let result = error_result(codes::ErrorKind::Overloaded, message.into(), "unknown");
    record_item("error", "unknown", None);
    tx.send(Ok(ResolveOutcome {
        id,
        result: Some(result),
    }))
    .await
    .is_ok()
}

struct ProcessedItem {
    id: u64,
    result: resolve_outcome::Result,
}

struct InFlightGuard {
    load_monitor: LoadMonitor,
}

impl InFlightGuard {
    fn new(load_monitor: LoadMonitor) -> Self {
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
    item: ResolveItem,
    in_flight_guard: InFlightGuard,
) -> ProcessedItem {
    let id = item.id;
    let deadline = Duration::from_millis(item.deadline_ms as u64);
    let _in_flight_guard = in_flight_guard;
    let lang = detect_lang(&item.exception_json);
    let started_at = Instant::now();

    let result = match tokio::time::timeout(deadline, resolve_item(&stage, &item)).await {
        Ok(Ok(resolved)) => resolve_outcome::Result::Done(Done {
            resolved_exception_json: resolved,
        }),
        Ok(Err(ItemFailure::InvalidPayload(msg))) => {
            debug!(
                id,
                error = %msg,
                "rejecting item with invalid payload",
            );
            error_result(codes::ErrorKind::InvalidPayload, msg, lang)
        }
        Ok(Err(ItemFailure::Overloaded(msg))) => {
            warn!(id, "limiter closed mid-request, asking caller to retry");
            error_result(codes::ErrorKind::Overloaded, msg, lang)
        }
        Ok(Err(ItemFailure::Unhandled(err))) => {
            warn!(
                id,
                error = %err,
                "unhandled error during resolution",
            );
            error_result(codes::ErrorKind::Unhandled, err, lang)
        }
        Err(_) => error_result(
            codes::ErrorKind::Overloaded,
            "item deadline expired".to_string(),
            lang,
        ),
    };

    let result_label = if matches!(result, resolve_outcome::Result::Done(_)) {
        "ok"
    } else {
        "error"
    };
    record_item(result_label, lang, Some(started_at.elapsed()));

    ProcessedItem { id, result }
}

fn error_result(
    kind: codes::ErrorKind,
    message: String,
    lang: &'static str,
) -> resolve_outcome::Result {
    metrics::counter!(ERRORS_TOTAL, "kind" => error_kind_label(kind), "lang" => lang).increment(1);
    resolve_outcome::Result::Error(ItemError {
        kind: kind as i32,
        message,
        details_json: Vec::new(),
    })
}

fn error_kind_label(kind: codes::ErrorKind) -> &'static str {
    match kind {
        codes::ErrorKind::Unspecified => "unspecified",
        codes::ErrorKind::InvalidPayload => "invalid_payload",
        codes::ErrorKind::Poison => "poison",
        codes::ErrorKind::Unhandled => "unhandled",
        codes::ErrorKind::Overloaded => "overloaded",
    }
}

fn record_stream_outcome(outcome: &'static str) {
    metrics::counter!(RESOLVE_STREAMS_TOTAL, "outcome" => outcome).increment(1);
}

fn record_item(result: &'static str, lang: &'static str, duration: Option<Duration>) {
    metrics::counter!(ITEMS_TOTAL, "result" => result, "lang" => lang).increment(1);
    if let Some(d) = duration {
        metrics::histogram!(ITEM_DURATION_MS, "lang" => lang).record(d.as_secs_f64() * 1000.0);
    }
}

/// Cheap probe of the exception payload to label per-item metrics by source
/// language. Reads `stack.frames[0].platform` (the RawFrame serde tag) without
/// fully parsing the Exception type. Any failure — malformed JSON, missing
/// stack, unknown variant — collapses to `"unknown"` so the metric never
/// rejects on a quirky payload.
fn detect_lang(exception_json: &[u8]) -> &'static str {
    let parsed: serde_json::Value = match serde_json::from_slice(exception_json) {
        Ok(v) => v,
        Err(_) => return "unknown",
    };
    let platform = parsed
        .get("stack")
        .and_then(|s| s.get("frames"))
        .and_then(|f| f.as_array())
        .and_then(|f| f.first())
        .and_then(|f| f.get("platform"))
        .and_then(|p| p.as_str());

    match platform {
        Some("python") => "python",
        Some("ruby") => "ruby",
        Some("web:javascript") | Some("javascript") => "javascript",
        Some("node:javascript") => "node",
        Some("go") => "go",
        Some("php") => "php",
        Some("hermes") => "hermes",
        Some("java") => "java",
        Some("dart") => "dart",
        Some("apple") => "apple",
        Some("custom") => "custom",
        _ => "unknown",
    }
}

enum ItemFailure {
    InvalidPayload(String),
    Overloaded(String),
    Unhandled(String),
}

async fn resolve_item(stage: &ResolutionStage, item: &ResolveItem) -> Result<Vec<u8>, ItemFailure> {
    let exception: Exception = serde_json::from_slice(&item.exception_json)
        .map_err(|e| ItemFailure::InvalidPayload(format!("invalid exception_json: {e}")))?;

    let debug_images = apple_debug_images_from_metadata(&item.metadata)?;

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

fn apple_debug_images_from_metadata(metadata: &[u8]) -> Result<Vec<AppleDebugImage>, ItemFailure> {
    if metadata.is_empty() {
        return Ok(Vec::new());
    }

    let metadata: serde_json::Value = serde_json::from_slice(metadata)
        .map_err(|e| ItemFailure::InvalidPayload(format!("invalid metadata: {e}")))?;
    let Some(debug_images) = metadata.get("apple_debug_images_json") else {
        return Ok(Vec::new());
    };
    serde_json::from_value(debug_images.clone()).map_err(|e| {
        ItemFailure::InvalidPayload(format!("invalid metadata.apple_debug_images_json: {e}"))
    })
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
