use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::json;

use tokio::sync::mpsc;
use tonic::{Status, Streaming};
use tracing::{debug, warn};

use crate::error::UnhandledError;
use crate::langs::native::DebugImage;
use crate::stages::resolution::exception::ExceptionResolver;
use crate::stages::resolution::frame::FrameResolver;
use crate::stages::resolution::ResolutionStage;
use crate::types::Exception;
use cymbal_proto::cymbal::resolution::v1::{
    resolve_outcome, Accepted, Done, Error as ItemError, ResolveItem, ResolveOutcome, Retry,
};

use super::codes;
use crate::modes::resolution::load_monitor::LoadMonitor;

/// Retry `code` surfaced to the caller for a transient infra failure. Callers
/// treat any `Retry` outcome as retryable regardless of the code; this is a
/// human-readable diagnostic tag only.
const TRANSIENT_RETRY_CODE: &str = "transient_infra_error";

const RESOLVE_REQUEST_DURATION_MS: &str = "cymbal_remote_resolution_server_request_duration_ms";
const SERVER_ERROR_KINDS: &str = "cymbal_remote_resolution_server_error_kinds_total";
const SERVER_ITEM_DURATION_MS: &str = "cymbal_remote_resolution_server_item_duration_ms";
const SERVER_ITEMS_TOTAL: &str = "cymbal_remote_resolution_server_items_total";

pub(super) async fn run_resolve(
    mut input: Streaming<ResolveItem>,
    stage: ResolutionStage,
    tx: mpsc::Sender<Result<ResolveOutcome, Status>>,
    load_monitor: LoadMonitor,
) {
    let started_at = Instant::now();

    loop {
        let item = tokio::select! {
            _ = tx.closed() => {
                record_resolve_duration(started_at, "cancelled");
                return;
            }
            maybe_item = input.message() => {
                match maybe_item {
                    Ok(Some(item)) => item,
                    Ok(None) => break,
                    Err(err) => {
                        warn!(error = %err, "resolve input stream failed");
                        record_resolve_duration(started_at, "input_error");
                        return;
                    }
                }
            }
        };

        let item_started_at = Instant::now();

        if item.deadline_ms == 0 {
            record_item_metrics(item_started_at, "error", "timeout");
            if !send_overloaded(&tx, item.id, "item deadline expired", 0).await {
                record_resolve_duration(started_at, "cancelled");
                return;
            }
            continue;
        }

        if !load_monitor.try_admit() {
            record_item_metrics(item_started_at, "error", "overloaded");
            if !send_overloaded(&tx, item.id, "server overloaded", 0).await {
                record_resolve_duration(started_at, "cancelled");
                return;
            }
            continue;
        }

        let item_tx = tx.clone();
        let item_stage = stage.clone();
        if !send_accepted(&tx, item.id).await {
            load_monitor.decrement_in_flight();
            record_resolve_duration(started_at, "cancelled");
            return;
        }
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

    record_resolve_duration(started_at, "completed");
}

async fn send_accepted(tx: &mpsc::Sender<Result<ResolveOutcome, Status>>, id: u64) -> bool {
    tx.send(Ok(ResolveOutcome {
        id,
        result: Some(resolve_outcome::Result::Accepted(Accepted {})),
    }))
    .await
    .is_ok()
}

async fn send_overloaded(
    tx: &mpsc::Sender<Result<ResolveOutcome, Status>>,
    id: u64,
    message: impl Into<String>,
    _retry_after_ms: u32,
) -> bool {
    tx.send(Ok(ResolveOutcome {
        id,
        result: Some(error_result(codes::ErrorKind::Overloaded, message.into())),
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
    let started_at = Instant::now();
    let id = item.id;
    let deadline = Duration::from_millis(item.deadline_ms as u64);
    let _in_flight_guard = in_flight_guard;

    let (result, outcome, kind) =
        match tokio::time::timeout(deadline, resolve_item(&stage, &item)).await {
            Ok(Ok(resolved)) => (
                resolve_outcome::Result::Done(Done {
                    resolved_exception_json: resolved,
                }),
                "done",
                "ok",
            ),
            Ok(Err(failure)) => failure_to_outcome(id, failure),
            Err(_) => (
                error_result(
                    codes::ErrorKind::Overloaded,
                    "item deadline expired".to_string(),
                ),
                "error",
                "timeout",
            ),
        };
    record_item_metrics(started_at, outcome, kind);

    ProcessedItem { id, result }
}

/// Map a failed item to its wire outcome plus (item_outcome, item_kind) metric
/// labels. Transient infra failures become a `Retry` outcome so the caller
/// reroutes/retries that single item instead of failing the whole batch; only
/// genuinely unhandled logic errors stay terminal.
fn failure_to_outcome(
    id: u64,
    failure: ItemFailure,
) -> (resolve_outcome::Result, &'static str, &'static str) {
    match failure {
        ItemFailure::InvalidPayload(msg) => {
            debug!(id, error = %msg, "rejecting item with invalid payload");
            (
                error_result(codes::ErrorKind::InvalidPayload, msg),
                "error",
                "invalid_payload",
            )
        }
        ItemFailure::Overloaded(msg) => {
            warn!(id, "limiter closed mid-request, asking caller to retry");
            (
                error_result(codes::ErrorKind::Overloaded, msg),
                "error",
                "overloaded",
            )
        }
        ItemFailure::Transient(msg) => {
            warn!(id, error = %msg, "transient infra error during resolution, asking caller to retry item");
            (retry_result(TRANSIENT_RETRY_CODE, msg), "retry", "transient")
        }
        ItemFailure::Unhandled(err) => {
            warn!(id, error = %err, "unhandled error during resolution");
            (
                error_result(codes::ErrorKind::Unhandled, err),
                "error",
                "unhandled",
            )
        }
    }
}

fn error_result(kind: codes::ErrorKind, message: String) -> resolve_outcome::Result {
    metrics::counter!(SERVER_ERROR_KINDS, "kind" => kind.metric_label()).increment(1);
    resolve_outcome::Result::Error(ItemError {
        kind: kind as i32,
        message,
        details_json: Vec::new(),
    })
}

fn retry_result(code: &str, message: String) -> resolve_outcome::Result {
    resolve_outcome::Result::Retry(Retry {
        code: code.to_string(),
        message,
        // No server hint; the caller applies its own backoff policy.
        retry_after_ms: 0,
    })
}

fn record_resolve_duration(started_at: Instant, outcome: &'static str) {
    metrics::histogram!(RESOLVE_REQUEST_DURATION_MS, "outcome" => outcome)
        .record(started_at.elapsed().as_secs_f64() * 1000.0);
}

fn record_item_metrics(started_at: Instant, outcome: &'static str, kind: &'static str) {
    metrics::counter!(SERVER_ITEMS_TOTAL, "outcome" => outcome, "kind" => kind).increment(1);
    metrics::histogram!(SERVER_ITEM_DURATION_MS, "outcome" => outcome, "kind" => kind)
        .record(started_at.elapsed().as_secs_f64() * 1000.0);
}

#[derive(Debug)]
enum ItemFailure {
    InvalidPayload(String),
    Overloaded(String),
    // Transient infra failure (e.g. S3/IO). Retryable: the caller reroutes the
    // single item instead of failing the batch.
    Transient(String),
    Unhandled(String),
}

async fn resolve_item(stage: &ResolutionStage, item: &ResolveItem) -> Result<Vec<u8>, ItemFailure> {
    let exception: Exception = serde_json::from_slice(&item.exception_json)
        .map_err(|e| ItemFailure::InvalidPayload(format!("invalid exception_json: {e}")))?;

    let debug_images = debug_images_from_metadata(&item.metadata)?;

    let resolved = resolve_one_exception(stage.clone(), item.team_id, exception, debug_images)
        .await
        .map_err(|e| match e {
            ResolveOneError::Overloaded => {
                ItemFailure::Overloaded("symbol-resolution limiter unavailable".to_string())
            }
            ResolveOneError::Transient(err) => ItemFailure::Transient(err),
            ResolveOneError::Unhandled(err) => ItemFailure::Unhandled(err),
        })?;

    serde_json::to_vec(&resolved)
        .map_err(|e| ItemFailure::Unhandled(format!("serialize resolved exception: {e}")))
}

fn debug_images_from_metadata(metadata: &[u8]) -> Result<Vec<DebugImage>, ItemFailure> {
    if metadata.is_empty() {
        return Ok(Vec::new());
    }

    let metadata: serde_json::Value = serde_json::from_slice(metadata)
        .map_err(|e| ItemFailure::InvalidPayload(format!("invalid metadata: {e}")))?;
    let Some(debug_images) = metadata.get("debug_images_json") else {
        return Ok(Vec::new());
    };
    serde_json::from_value(debug_images.clone()).map_err(|e| {
        ItemFailure::InvalidPayload(format!("invalid metadata.debug_images_json: {e}"))
    })
}

enum ResolveOneError {
    Overloaded,
    // Transient infra failure (e.g. S3/IO) that should be retried/rerouted
    // rather than captured as an unhandled exception or failing the batch.
    Transient(String),
    Unhandled(String),
}

async fn resolve_one_exception(
    stage: ResolutionStage,
    team_id: i32,
    exception: Exception,
    debug_images: Vec<DebugImage>,
) -> Result<Exception, ResolveOneError> {
    let exception = if ExceptionResolver::is_java_exception(&exception) {
        let _permit = acquire_permit(&stage).await?;
        stage
            .symbol_resolver
            .resolve_java_exception(team_id, exception)
            .await
            .map_err(|err| capture_unhandled(team_id, err))?
    } else if ExceptionResolver::is_dart_exception(&exception) {
        let _permit = acquire_permit(&stage).await?;
        stage
            .symbol_resolver
            .resolve_dart_exception(team_id, exception)
            .await
            .map_err(|err| capture_unhandled(team_id, err))?
    } else {
        exception
    };

    FrameResolver::resolve_exception_frames(team_id, exception, Arc::new(debug_images), stage)
        .await
        .map_err(|err| capture_unhandled(team_id, err))
}

async fn acquire_permit(
    stage: &ResolutionStage,
) -> Result<tokio::sync::OwnedSemaphorePermit, ResolveOneError> {
    stage
        .acquire_symbol_resolution_permit()
        .await
        .map_err(|_| ResolveOneError::Overloaded)
}

fn capture_unhandled(team_id: i32, err: UnhandledError) -> ResolveOneError {
    // A transient infra blip (e.g. S3) is retryable and self-recovering, so we
    // don't capture it as an unhandled exception (that only adds noise) and we
    // tell the caller to reroute/retry this item rather than fail the batch.
    if err.is_transient() {
        return ResolveOneError::Transient(err.to_string());
    }
    let err = Arc::new(err);
    common_posthog::capture_exception(err.clone(), [("team_id", json!(team_id))]);
    ResolveOneError::Unhandled(err.to_string())
}

#[cfg(test)]
mod test {
    use super::*;

    fn images_json(debug_id: &str) -> serde_json::Value {
        serde_json::json!([{
            "debug_id": debug_id,
            "image_addr": "0x100000000",
            "image_size": 4096,
            "type": "macho",
        }])
    }

    #[test]
    fn metadata_reads_debug_images_key() {
        let metadata = serde_json::to_vec(&serde_json::json!({
            "debug_images_json": images_json("img-1"),
        }))
        .unwrap();

        let images = debug_images_from_metadata(&metadata).unwrap();
        assert_eq!(images.len(), 1);
        assert_eq!(images[0].debug_id, "img-1");
    }

    #[test]
    fn metadata_without_debug_images_key_is_empty() {
        // The legacy apple-specific key is no longer read, so it is ignored.
        let metadata =
            serde_json::to_vec(&serde_json::json!({"apple_debug_images_json": images_json("x")}))
                .unwrap();
        assert!(debug_images_from_metadata(&metadata).unwrap().is_empty());
        assert!(debug_images_from_metadata(&[]).unwrap().is_empty());
    }

    #[test]
    fn transient_failure_becomes_retry_outcome() {
        // A transient infra blip must not become a terminal Error the caller
        // treats as batch-failing; it must be a retryable Retry outcome.
        let (result, outcome, kind) =
            failure_to_outcome(7, ItemFailure::Transient("s3 unavailable".to_string()));
        assert!(matches!(
            result,
            resolve_outcome::Result::Retry(Retry { ref code, ref message, retry_after_ms: 0 })
                if code == TRANSIENT_RETRY_CODE && message == "s3 unavailable"
        ));
        assert_eq!(outcome, "retry");
        assert_eq!(kind, "transient");
    }

    #[test]
    fn unhandled_failure_stays_terminal_error() {
        let (result, _, kind_label) =
            failure_to_outcome(7, ItemFailure::Unhandled("logic bug".to_string()));
        assert!(matches!(
            result,
            resolve_outcome::Result::Error(ItemError { kind, .. })
                if kind == codes::ErrorKind::Unhandled as i32
        ));
        assert_eq!(kind_label, "unhandled");
    }

    #[test]
    fn invalid_debug_images_key_errors() {
        let metadata =
            serde_json::to_vec(&serde_json::json!({"debug_images_json": "not-a-list"})).unwrap();

        assert!(matches!(
            debug_images_from_metadata(&metadata),
            Err(ItemFailure::InvalidPayload(msg)) if msg.contains("debug_images_json")
        ));
    }
}
