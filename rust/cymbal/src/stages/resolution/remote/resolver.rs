use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use rand::Rng;

use cymbal_proto::cymbal::resolution::v1::{
    item_outcome, outcome, ExceptionResolution, ExceptionResolutionItem, Outcome, ResolveRequest,
};
use sha2::{Digest, Sha256};
use tracing::warn;

use crate::{
    error::UnhandledError,
    metric_consts::{
        REMOTE_RESOLUTION_ATTEMPTS_PER_REQUEST, REMOTE_RESOLUTION_LATENCY,
        REMOTE_RESOLUTION_REQUESTS, REMOTE_RESOLUTION_SAMPLING,
    },
    stages::{
        pipeline::ExceptionEventPipelineItem,
        resolution::{
            exception::ExceptionResolver, frame::FrameResolver, remote::pool::EndpointPool,
            ResolutionStage,
        },
    },
    types::{batch::Batch, exception_properties::ExceptionProperties, Exception, ExceptionList},
};

use super::client;
use super::config::RemoteResolutionConfig;

/// Context handed to the remote orchestration layer. Cheap to clone because
/// both the pool handle and config are `Arc`/`Clone`-friendly.
#[derive(Clone)]
pub struct RemoteResolutionContext {
    pub pool: Arc<EndpointPool>,
    pub config: RemoteResolutionConfig,
}

// ─────────────────────────────────────────────────────────────────────────────
// Top-level pipeline
// ─────────────────────────────────────────────────────────────────────────────

/// Resolve a whole stage batch through the remote pool.
///
/// Flow:
/// 1. Partition the batch into errored / empty-passthrough / local / remote.
/// 2. Resolve local events inline (same path as no-remote mode).
/// 3. Group remote events by routing key, chunk into event-atomic
///    `RemoteChunk`s, and run each chunk through the retry-aware RPC layer.
/// 4. Assemble back into the original batch order.
///
/// Each event passes through exactly one bucket and writes itself into the
/// output exactly once. There is no shared mutation across RPC boundaries.
pub async fn resolve_batch(
    batch: Batch<ExceptionEventPipelineItem>,
    ctx: RemoteResolutionContext,
    local_stage: ResolutionStage,
) -> Result<Batch<ExceptionEventPipelineItem>, UnhandledError> {
    let batch_len = batch.len();
    let partition = partition_batch(batch, ctx.config.sample_rate)?;

    let local_resolved = resolve_local_events(partition.local, local_stage).await?;
    let remote_resolved = resolve_remote_events(&ctx, partition.remote).await?;

    assemble_output(
        batch_len,
        partition.errors,
        partition.empty,
        local_resolved,
        remote_resolved,
    )
}

fn assemble_output(
    batch_len: usize,
    errors: Vec<(usize, ExceptionEventPipelineItem)>,
    empty: Vec<(usize, ExceptionEventPipelineItem)>,
    local: Vec<(usize, ExceptionEventPipelineItem)>,
    remote: Vec<(usize, ExceptionEventPipelineItem)>,
) -> Result<Batch<ExceptionEventPipelineItem>, UnhandledError> {
    let mut output: Vec<Option<ExceptionEventPipelineItem>> =
        (0..batch_len).map(|_| None).collect();
    for (idx, item) in errors.into_iter().chain(empty).chain(local).chain(remote) {
        output[idx] = Some(item);
    }
    let resolved: Vec<ExceptionEventPipelineItem> = output
        .into_iter()
        .enumerate()
        .map(|(idx, slot)| {
            slot.ok_or_else(|| {
                UnhandledError::Other(format!("remote resolution left output slot {idx} unfilled"))
            })
        })
        .collect::<Result<_, _>>()?;
    Ok(Batch::from(resolved))
}

// ─────────────────────────────────────────────────────────────────────────────
// Partition: split the batch into errored / empty / local / remote buckets
// ─────────────────────────────────────────────────────────────────────────────

struct Partition {
    errors: Vec<(usize, ExceptionEventPipelineItem)>,
    empty: Vec<(usize, ExceptionEventPipelineItem)>,
    local: Vec<(usize, ExceptionProperties)>,
    remote: Vec<RemoteEvent>,
}

/// A sampled-remote event with its wire payloads pre-serialized.
///
/// Owning the serialized bytes alongside the event means each `RemoteEvent`
/// moves through the chunk → RPC → apply pipeline by value. No shared
/// mutable state, no `Option<>` sentinels, no index-based bookkeeping.
struct RemoteEvent {
    batch_index: usize,
    evt: ExceptionProperties,
    /// One serialized exception per `evt.exception_list` entry, in order.
    exception_jsons: Vec<Vec<u8>>,
    /// Shared across this event's exceptions on the wire. The proto carries
    /// it per-item; this is the per-event source bytes we clone from.
    apple_debug_images_json: Vec<u8>,
}

impl RemoteEvent {
    fn item_count(&self) -> usize {
        self.evt.exception_list.len()
    }
}

fn partition_batch(
    batch: Batch<ExceptionEventPipelineItem>,
    sample_rate: f64,
) -> Result<Partition, UnhandledError> {
    let mut errors = Vec::new();
    let mut empty = Vec::new();
    let mut local = Vec::new();
    let mut remote = Vec::new();

    for (batch_index, item) in batch.into_iter().enumerate() {
        let evt = match item {
            Ok(evt) => evt,
            Err(err) => {
                errors.push((batch_index, Err(err)));
                continue;
            }
        };

        if evt.exception_list.is_empty() {
            empty.push((batch_index, Ok(evt)));
            continue;
        }

        if should_route_event_to_remote(&evt, sample_rate) {
            metrics::counter!(REMOTE_RESOLUTION_SAMPLING, "decision" => "remote").increment(1);
            remote.push(prepare_remote_event(batch_index, evt)?);
        } else {
            metrics::counter!(REMOTE_RESOLUTION_SAMPLING, "decision" => "local").increment(1);
            local.push((batch_index, evt));
        }
    }

    Ok(Partition {
        errors,
        empty,
        local,
        remote,
    })
}

fn prepare_remote_event(
    batch_index: usize,
    evt: ExceptionProperties,
) -> Result<RemoteEvent, UnhandledError> {
    let exception_jsons: Vec<Vec<u8>> = evt
        .exception_list
        .iter()
        .map(|exc| serde_json::to_vec(exc).map_err(UnhandledError::from))
        .collect::<Result<_, _>>()?;
    let apple_debug_images_json = if evt.debug_images.is_empty() {
        Vec::new()
    } else {
        serde_json::to_vec(&evt.debug_images).map_err(UnhandledError::from)?
    };
    Ok(RemoteEvent {
        batch_index,
        evt,
        exception_jsons,
        apple_debug_images_json,
    })
}

fn should_route_event_to_remote(evt: &ExceptionProperties, sample_rate: f64) -> bool {
    if sample_rate <= 0.0 {
        return false;
    }
    if sample_rate >= 1.0 {
        return true;
    }

    let mut hasher = Sha256::new();
    hasher.update(evt.team_id.to_be_bytes());
    hasher.update(evt.uuid.as_bytes());
    let digest = hasher.finalize();
    let bucket_bytes: [u8; 8] = digest[..8]
        .try_into()
        .expect("sha256 digest always contains at least 8 bytes");
    let bucket = u64::from_be_bytes(bucket_bytes) as f64 / ((u64::MAX as f64) + 1.0);
    bucket < sample_rate
}

// ─────────────────────────────────────────────────────────────────────────────
// Local resolution path (passthrough to the inline stage)
// ─────────────────────────────────────────────────────────────────────────────

async fn resolve_local_events(
    local_events: Vec<(usize, ExceptionProperties)>,
    local_stage: ResolutionStage,
) -> Result<Vec<(usize, ExceptionEventPipelineItem)>, UnhandledError> {
    if local_events.is_empty() {
        return Ok(Vec::new());
    }
    let (indexes, events): (Vec<usize>, Vec<ExceptionProperties>) =
        local_events.into_iter().unzip();
    let batch = Batch::from(events.into_iter().map(Ok).collect::<Vec<_>>())
        .apply_operator(ExceptionResolver, local_stage.clone())
        .await?
        .apply_operator(FrameResolver, local_stage)
        .await?;
    Ok(indexes.into_iter().zip(batch.into_iter()).collect())
}

// ─────────────────────────────────────────────────────────────────────────────
// Remote resolution path: chunk → RPC → apply
// ─────────────────────────────────────────────────────────────────────────────

/// A team-routed group of events to send as a single ResolveRequest.
///
/// The chunk OWNS its events. After `to_request()` ships them and the
/// retry loop returns resolved exceptions, `apply()` consumes the chunk
/// and stitches each event back together with its batch_index.
struct RemoteChunk {
    routing_key: String,
    chunk_index: usize,
    events: Vec<RemoteEvent>,
}

impl RemoteChunk {
    fn item_count(&self) -> usize {
        self.events.iter().map(RemoteEvent::item_count).sum()
    }

    fn batch_id(&self) -> String {
        format!(
            "{}:{}",
            routing_key_digest(&self.routing_key),
            self.chunk_index
        )
    }

    /// Item ids in request order — used by `summarize_outcomes` to validate
    /// that the server's outcome stream points at the items we submitted.
    fn expected_item_ids(&self) -> Vec<String> {
        let mut out = Vec::with_capacity(self.item_count());
        for event in &self.events {
            for exc_idx in 0..event.item_count() {
                out.push(format!("{}:{exc_idx}", event.evt.uuid));
            }
        }
        out
    }

    /// Build a fresh ResolveRequest. Called once per RPC attempt (cheap clone
    /// of pre-serialized bytes). The chunk itself stays available so the
    /// retry loop can re-issue without separate request-clone bookkeeping.
    fn to_request(&self) -> ResolveRequest {
        let mut items = Vec::with_capacity(self.item_count());
        let mut item_index: u32 = 0;
        for event in &self.events {
            for (exc_idx, exc_json) in event.exception_jsons.iter().enumerate() {
                items.push(ExceptionResolutionItem {
                    item_id: format!("{}:{exc_idx}", event.evt.uuid),
                    item_index,
                    team_id: event.evt.team_id,
                    exception: Some(ExceptionResolution {
                        exception_json: exc_json.clone(),
                        apple_debug_images_json: event.apple_debug_images_json.clone(),
                    }),
                });
                item_index += 1;
            }
        }
        ResolveRequest {
            batch_id: self.batch_id(),
            items,
        }
    }

    /// Consume the chunk and apply the resolved exceptions back to each
    /// event in order. Caller guarantees `resolved.len() == self.item_count()`
    /// (the retry loop only returns a Vec of that length on success).
    fn apply(self, resolved: Vec<Exception>) -> Vec<(usize, ExceptionEventPipelineItem)> {
        debug_assert_eq!(resolved.len(), self.item_count());
        let mut iter = resolved.into_iter();
        self.events
            .into_iter()
            .map(|mut event| {
                let n = event.item_count();
                let new_list: Vec<Exception> = (&mut iter).take(n).collect();
                event.evt.exception_list = ExceptionList::from(new_list);
                (event.batch_index, Ok(event.evt))
            })
            .collect()
    }
}

async fn resolve_remote_events(
    ctx: &RemoteResolutionContext,
    events: Vec<RemoteEvent>,
) -> Result<Vec<(usize, ExceptionEventPipelineItem)>, UnhandledError> {
    if events.is_empty() {
        return Ok(Vec::new());
    }
    // Effective batch size: take the smaller of the client's configured
    // ceiling and the server's current suggestion (across all fresh
    // snapshots). Server-driven sizing lets the pod ask callers to shrink
    // batches when it's pressured without needing a config redeploy. If no
    // pod has a usable suggestion (cold start, all stale), fall back to
    // the client config alone.
    let server_suggestion = ctx.pool.min_suggested_max_items().await;
    let effective_max_items = match server_suggestion {
        Some(suggested) => (suggested as usize).min(ctx.config.max_batch_items),
        None => ctx.config.max_batch_items,
    };
    let chunks = chunk_events_by_team(events, effective_max_items);
    let mut out = Vec::new();
    for chunk in chunks {
        let resolved = run_with_retries(ctx, &chunk).await?;
        out.extend(chunk.apply(resolved));
    }
    Ok(out)
}

/// Group events by routing key (per-team), then split each team's events
/// into event-atomic chunks bounded by `max_items`.
///
/// A single event with `> max_items` exceptions still gets its own chunk
/// (oversized but unsplittable). The server is the right place to feed back
/// a "send smaller batches" signal (future `LoadEvent` extension).
fn chunk_events_by_team(events: Vec<RemoteEvent>, max_items: usize) -> Vec<RemoteChunk> {
    let max_items = max_items.max(1);
    // Preserve insertion order via BTreeMap on the deterministic routing key.
    let mut by_key: BTreeMap<String, Vec<RemoteEvent>> = BTreeMap::new();
    for event in events {
        let key = routing_key_for_event(&event.evt);
        by_key.entry(key).or_default().push(event);
    }

    let mut chunks = Vec::new();
    for (routing_key, events_for_key) in by_key {
        let mut chunk_index = 0;
        let mut current: Vec<RemoteEvent> = Vec::new();
        let mut current_items = 0usize;

        for event in events_for_key {
            let event_items = event.item_count();
            if !current.is_empty() && current_items + event_items > max_items {
                chunks.push(RemoteChunk {
                    routing_key: routing_key.clone(),
                    chunk_index,
                    events: std::mem::take(&mut current),
                });
                chunk_index += 1;
                current_items = 0;
            }
            current_items += event_items;
            current.push(event);
        }
        if !current.is_empty() {
            chunks.push(RemoteChunk {
                routing_key,
                chunk_index,
                events: current,
            });
        }
    }
    chunks
}

fn routing_key_for_event(evt: &ExceptionProperties) -> String {
    // Per-team routing: every exception of an event hashes to the same pod
    // via rendezvous selection in `EndpointPool::select_for_key`. One team's
    // bursts land on one preferred pod with `degraded`-driven spillover when
    // that pod is overloaded.
    format!("team:{}", evt.team_id)
}

fn routing_key_digest(routing_key: &str) -> String {
    let digest = Sha256::digest(routing_key.as_bytes());
    digest[..8]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

// ─────────────────────────────────────────────────────────────────────────────
// Retry loop + outcome summarization
// ─────────────────────────────────────────────────────────────────────────────

async fn run_with_retries(
    ctx: &RemoteResolutionContext,
    chunk: &RemoteChunk,
) -> Result<Vec<Exception>, UnhandledError> {
    let routing_key = chunk.routing_key.as_str();
    let expected_item_ids = chunk.expected_item_ids();
    let max_attempts = ctx.config.max_retries.saturating_add(1);
    // Tracks the most recent retryable failure so the final exhaustion error
    // surfaces a concrete cause. Retained across cause classes (transport,
    // per-item retry, pool empty) so a mixed-cause exhaustion still reports
    // the last observable signal instead of being overwritten with `None`.
    let mut last_error: Option<String> = None;
    // Tracks the number of attempts actually issued so the per-request
    // histogram below reflects retry storm shape.
    let mut attempts_used: u32 = max_attempts;

    for attempt in 0..max_attempts {
        attempts_used = attempt + 1;

        // Sleep between attempts so a degraded upstream isn't bombarded
        // with every retry from every cymbal pod in lockstep. First attempt
        // skips the wait — backoff applies only to retries.
        if attempt > 0 {
            tokio::time::sleep(retry_backoff_for(ctx, attempt - 1)).await;
        }

        let handle = match ctx.pool.select_for_key(routing_key, attempt).await {
            Ok(handle) => handle,
            Err(err) => {
                metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "pool_empty")
                    .increment(1);
                // Pool empty can be transient (all pods briefly degraded,
                // DNS reconciling, pod rollouts). Use the retry budget rather
                // than failing the whole batch on a single moment of bad luck.
                last_error = Some(format!("pool unavailable: {err}"));
                continue;
            }
        };

        let endpoint = handle.addr;
        let start = Instant::now();
        let outcome = client::resolve(
            handle.channel.clone(),
            chunk.to_request(),
            ctx.config.request_deadline,
        )
        .await;
        let elapsed_ms = start.elapsed().as_millis() as f64;
        drop(handle);

        let outcomes = match outcome {
            Ok(outcomes) => outcomes,
            Err(err) if err.is_retryable() => {
                metrics::counter!(
                    REMOTE_RESOLUTION_REQUESTS,
                    "outcome" => "transport_retry",
                    "reason" => err.reason_tag(),
                )
                .increment(1);
                warn!(
                    endpoint = %endpoint,
                    attempt,
                    error = %err,
                    reason = err.reason_tag(),
                    "remote resolution transport-level retry"
                );
                last_error = Some(err.to_string());
                continue;
            }
            Err(err) => {
                metrics::counter!(
                    REMOTE_RESOLUTION_REQUESTS,
                    "outcome" => "terminal",
                    "reason" => err.reason_tag(),
                )
                .increment(1);
                metrics::histogram!(
                    REMOTE_RESOLUTION_ATTEMPTS_PER_REQUEST,
                    "outcome" => "terminal",
                )
                .record(attempts_used as f64);
                return Err(UnhandledError::Other(format!(
                    "remote resolution failed terminally: {err}"
                )));
            }
        };

        metrics::histogram!(REMOTE_RESOLUTION_LATENCY).record(elapsed_ms);
        let summary = summarize_outcomes(&expected_item_ids, &outcomes, &chunk.batch_id());

        // A clean stream end without a BatchSummary means the server unwound
        // before reaching its terminal send (task panic, tx.send error, kill).
        // Items it never produced look identical to client-side "missing" on
        // the wire and would silently downgrade to unresolved exceptions
        // without this signal.
        if !summary.has_summary {
            metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "no_summary").increment(1);
            warn!(
                endpoint = %endpoint,
                attempt,
                outcomes_received = outcomes.len(),
                "remote resolution stream ended without BatchSummary; retrying"
            );
            last_error = Some(format!("stream ended without BatchSummary from {endpoint}"));
            continue;
        }
        if summary.has_retryable_item {
            metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "retryable_item")
                .increment(1);
            warn!(
                endpoint = %endpoint,
                attempt,
                "remote resolution returned per-item Retry outcomes; retrying"
            );
            last_error = Some(format!("per-item Retry outcomes from {endpoint}"));
            continue;
        }
        if summary.missing > 0 {
            metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "missing_items")
                .increment(1);
            warn!(
                endpoint = %endpoint,
                missing = summary.missing,
                attempt,
                "remote resolution summary reported missing items; retrying"
            );
            last_error = Some(format!(
                "{} missing item(s) in summary from {endpoint}",
                summary.missing
            ));
            continue;
        }
        // All-or-nothing contract during rollout: a non-retryable per-item
        // failure (server `invalid_payload`/`unhandled` or a client-side
        // `invalid_done_payload` JSON parse error) must not silently downgrade
        // the affected exception to an unresolved one. Surface as a
        // batch-level UnhandledError so the upstream pipeline can DLQ rather
        // than emit half-baked events. Revisit when partial-failure semantics
        // are agreed.
        if let Some(preview) = summary.first_error_preview {
            metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "items_failed").increment(1);
            metrics::histogram!(
                REMOTE_RESOLUTION_ATTEMPTS_PER_REQUEST,
                "outcome" => "items_failed",
            )
            .record(attempts_used as f64);
            return Err(UnhandledError::Other(format!(
                "remote resolution returned {} item error(s) from {endpoint}; \
                 failing batch under all-or-nothing rollout policy (first: {preview})",
                summary.error,
            )));
        }

        // Success: every position holds a resolved Exception.
        let resolved: Vec<Exception> = summary
            .resolved
            .into_iter()
            .map(|slot| slot.expect("error == 0 guarantees every slot is filled"))
            .collect();
        metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "ok").increment(1);
        metrics::histogram!(REMOTE_RESOLUTION_ATTEMPTS_PER_REQUEST, "outcome" => "ok")
            .record(attempts_used as f64);
        return Ok(resolved);
    }

    metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "exhausted").increment(1);
    metrics::histogram!(REMOTE_RESOLUTION_ATTEMPTS_PER_REQUEST, "outcome" => "exhausted")
        .record(attempts_used as f64);
    Err(UnhandledError::Other(format!(
        "remote resolution exhausted retries ({max_attempts} attempt(s)): {}",
        last_error.unwrap_or_else(|| "no recorded cause".to_string()),
    )))
}

/// Exponential backoff with jitter for the n-th retry (0-indexed: 0 is the
/// wait BEFORE the first retry, i.e. after attempt 0 failed). Each step
/// doubles the base, capped at `retry_max_backoff`; up to ~50% random jitter
/// is added so a fleet of cymbal pods doesn't synchronize retries against a
/// briefly-degraded upstream.
fn retry_backoff_for(ctx: &RemoteResolutionContext, retry_index: u32) -> Duration {
    let base_ms = ctx.config.retry_backoff.as_millis() as u64;
    let cap_ms = ctx.config.retry_max_backoff.as_millis() as u64;
    let exp = retry_index.min(16);
    let scaled = base_ms.saturating_mul(1u64 << exp).min(cap_ms);
    let jitter = if scaled == 0 {
        0
    } else {
        rand::thread_rng().gen_range(0..=scaled / 2)
    };
    Duration::from_millis(scaled.saturating_add(jitter))
}

struct OutcomeSummary {
    /// Per-position: `Some(Exception)` if the server returned a parseable
    /// `Done` for that item, otherwise `None`. All `Some(...)` iff
    /// `error == 0 && missing == 0 && !has_retryable_item`.
    resolved: Vec<Option<Exception>>,
    /// Count of items that did NOT come back as a parseable `Done` (server
    /// `Error`, client-side `invalid_done_payload`, or missing-slot fill).
    /// Drives the all-or-nothing fail-batch gate.
    error: usize,
    /// First failed item's `"{code}: {message}"` for the batch-level error
    /// surface. Cheap to carry; avoids re-walking outcomes on the error path.
    first_error_preview: Option<String>,
    has_retryable_item: bool,
    /// Server-reported missing count from `BatchSummary.missing_items`.
    missing: u32,
    /// `true` when the server sent its terminal `BatchSummary` outcome.
    has_summary: bool,
}

fn summarize_outcomes(
    expected_item_ids: &[String],
    outcomes: &[Outcome],
    batch_id: &str,
) -> OutcomeSummary {
    let submitted = expected_item_ids.len();
    let mut resolved: Vec<Option<Exception>> = (0..submitted).map(|_| None).collect();
    let mut first_failed: Option<String> = None;
    let mut error: usize = 0;
    let mut has_retryable_item = false;
    let mut summary_missing: u32 = 0;
    let mut has_summary = false;

    for outcome in outcomes {
        match outcome.message.as_ref() {
            Some(outcome::Message::ItemOutcome(io)) => {
                let idx = io.item_index as usize;
                let Some(expected_item_id) = expected_item_ids.get(idx) else {
                    continue;
                };
                if io.item_id != *expected_item_id {
                    warn!(
                        batch_id = %batch_id,
                        item_index = idx,
                        expected_item_id = %expected_item_id,
                        actual_item_id = %io.item_id,
                        "remote resolution outcome item id mismatch; ignoring outcome"
                    );
                    continue;
                }
                let Some(result) = io.result.as_ref() else {
                    continue;
                };
                match result {
                    item_outcome::Result::Done(done) => {
                        match serde_json::from_slice::<Exception>(&done.resolved_exception_json) {
                            Ok(exc) => {
                                resolved[idx] = Some(exc);
                            }
                            Err(err) => {
                                if first_failed.is_none() {
                                    first_failed = Some(format!("invalid_done_payload: {err}"));
                                }
                            }
                        }
                    }
                    item_outcome::Result::Error(err) => {
                        if first_failed.is_none() {
                            first_failed = Some(format!("{}: {}", err.code, err.message));
                        }
                    }
                    item_outcome::Result::Retry(_) => {
                        has_retryable_item = true;
                    }
                }
            }
            Some(outcome::Message::BatchSummary(summary)) => {
                summary_missing = summary.missing_items.len() as u32;
                has_summary = true;
            }
            _ => {}
        }
    }

    // Count failures from the resolved-vec gaps. A gap can come from: server
    // Error, client JSON-parse failure, missing item, or per-item Retry. The
    // retry/missing/no_summary checks fire FIRST in the retry loop, so by the
    // time we look at `error` we know any gaps must be hard failures.
    for slot in &resolved {
        if slot.is_none() {
            error += 1;
        }
    }
    // If we have gaps but no captured first_failed (server emitted nothing for
    // some position), provide a generic preview.
    if error > 0 && first_failed.is_none() {
        first_failed = Some("missing: no outcome emitted for this item".to_string());
    }

    OutcomeSummary {
        resolved,
        error,
        first_error_preview: first_failed,
        has_retryable_item,
        missing: summary_missing,
        has_summary,
    }
}

#[cfg(test)]
mod tests {
    use cymbal_proto::cymbal::resolution::v1::{Done, ItemOutcome};
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    #[test]
    fn routing_key_is_per_team_regardless_of_exception_internals() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom",
                "stacktrace": {
                    "type": "raw",
                    "frames": [{
                        "platform": "web:javascript",
                        "filename": "https://example.com/app.js",
                        "function": "minified",
                        "lineno": 1,
                        "colno": 2,
                        "chunk_id": "chunk-a"
                    }]
                }
            }]
        }))
        .expect("valid exception properties");
        evt.team_id = 7;
        assert_eq!(routing_key_for_event(&evt), "team:7");
    }

    #[test]
    fn sampling_decision_is_stable_for_same_team_and_event_uuid() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom"
            }]
        }))
        .expect("valid exception properties");
        evt.team_id = 123;
        evt.uuid = Uuid::from_u128(0x123456789abcdef);

        let first = should_route_event_to_remote(&evt, 0.37);
        for _ in 0..100 {
            assert_eq!(should_route_event_to_remote(&evt, 0.37), first);
        }
    }

    #[test]
    fn sampling_decision_respects_rate_boundaries() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom"
            }]
        }))
        .expect("valid exception properties");
        evt.team_id = 123;
        evt.uuid = Uuid::from_u128(0x123456789abcdef);

        assert!(!should_route_event_to_remote(&evt, 0.0));
        assert!(should_route_event_to_remote(&evt, 1.0));
    }

    #[test]
    fn chunk_packs_events_event_atomic_up_to_max_items() {
        // Events of sizes (2, 2, 1) with max_items=2: each event is its own
        // chunk because no two adjacent events fit together within the cap.
        let events = vec![
            fake_remote_event(1, 0, 2),
            fake_remote_event(1, 1, 2),
            fake_remote_event(1, 2, 1),
        ];
        let chunks = chunk_events_by_team(events, 2);
        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].item_count(), 2);
        assert_eq!(chunks[1].item_count(), 2);
        assert_eq!(chunks[2].item_count(), 1);
    }

    #[test]
    fn chunk_packs_multiple_events_when_their_combined_items_fit() {
        // Events of sizes (1, 1, 1) with max_items=2: events 0+1 pack into
        // chunk 0; event 2 goes alone in chunk 1.
        let events = vec![
            fake_remote_event(1, 0, 1),
            fake_remote_event(1, 1, 1),
            fake_remote_event(1, 2, 1),
        ];
        let chunks = chunk_events_by_team(events, 2);
        assert_eq!(chunks.len(), 2);
        assert_eq!(chunks[0].item_count(), 2);
        assert_eq!(chunks[1].item_count(), 1);
    }

    #[test]
    fn chunk_never_splits_a_single_oversized_event() {
        // A single event with 5 exceptions and max_items=2 ships as one
        // oversized chunk — event-atomic chunking forbids splitting.
        let events = vec![fake_remote_event(1, 0, 5)];
        let chunks = chunk_events_by_team(events, 2);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].item_count(), 5);
    }

    #[test]
    fn chunk_separates_events_by_team_routing_key() {
        // Two teams, two events each (size 1). Each team gets its own chunks
        // even when items per chunk would fit together — routing affinity is
        // per-team.
        let events = vec![
            fake_remote_event(1, 0, 1),
            fake_remote_event(2, 1, 1),
            fake_remote_event(1, 2, 1),
            fake_remote_event(2, 3, 1),
        ];
        let chunks = chunk_events_by_team(events, 8);
        assert_eq!(chunks.len(), 2);
        // BTreeMap iteration order: "team:1" before "team:2"
        assert_eq!(chunks[0].routing_key, "team:1");
        assert_eq!(chunks[0].item_count(), 2);
        assert_eq!(chunks[1].routing_key, "team:2");
        assert_eq!(chunks[1].item_count(), 2);
    }

    #[test]
    fn summarize_outcomes_reorders_out_of_order_done_outcomes() {
        let ids: Vec<String> = (0..3).map(|i| format!("evt:{i}")).collect();
        let outcomes = vec![
            done_outcome("evt:2", 2, "ResolvedTwo"),
            done_outcome("evt:0", 0, "ResolvedZero"),
            done_outcome("evt:1", 1, "ResolvedOne"),
            batch_summary_outcome(3, 0),
        ];
        let summary = summarize_outcomes(&ids, &outcomes, "batch");
        assert_eq!(summary.error, 0);
        assert_eq!(
            summary.resolved[0].as_ref().unwrap().exception_type,
            "ResolvedZero"
        );
        assert_eq!(
            summary.resolved[1].as_ref().unwrap().exception_type,
            "ResolvedOne"
        );
        assert_eq!(
            summary.resolved[2].as_ref().unwrap().exception_type,
            "ResolvedTwo"
        );
        assert!(summary.has_summary);
    }

    #[test]
    fn summarize_outcomes_ignores_mismatched_item_id_at_index() {
        let ids = vec!["evt:0".to_string()];
        let outcomes = vec![
            done_outcome("stale-event:0", 0, "WrongException"),
            done_outcome("evt:0", 0, "RightException"),
            batch_summary_outcome(1, 0),
        ];
        let summary = summarize_outcomes(&ids, &outcomes, "batch");
        assert_eq!(summary.error, 0);
        assert_eq!(
            summary.resolved[0].as_ref().unwrap().exception_type,
            "RightException"
        );
    }

    #[test]
    fn summarize_outcomes_counts_missing_slots_as_errors() {
        let ids = vec!["evt:0".to_string(), "evt:1".to_string()];
        let outcomes = vec![
            done_outcome("evt:0", 0, "ResolvedZero"),
            batch_summary_outcome(2, 0),
        ];
        let summary = summarize_outcomes(&ids, &outcomes, "batch");
        assert_eq!(summary.error, 1);
        assert!(summary.first_error_preview.is_some());
        assert!(summary.has_summary);
    }

    #[test]
    fn summarize_outcomes_flags_missing_summary_when_stream_ends_early() {
        let ids = vec!["evt:0".to_string()];
        let outcomes = vec![done_outcome("evt:0", 0, "ResolvedZero")];
        let summary = summarize_outcomes(&ids, &outcomes, "batch");
        assert!(!summary.has_summary);
    }

    // ── Test helpers ────────────────────────────────────────────────────────

    fn fake_remote_event(team_id: i32, batch_index: usize, n_exceptions: usize) -> RemoteEvent {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": (0..n_exceptions)
                .map(|i| json!({
                    "type": "Error",
                    "value": format!("boom-{i}"),
                }))
                .collect::<Vec<_>>()
        }))
        .expect("valid exception properties");
        evt.team_id = team_id;
        evt.uuid = Uuid::from_u128(0xABCD_0000_0000_0000 ^ (batch_index as u128));

        let exception_jsons = evt
            .exception_list
            .iter()
            .map(|exc| serde_json::to_vec(exc).expect("serialize exception"))
            .collect();
        RemoteEvent {
            batch_index,
            evt,
            exception_jsons,
            apple_debug_images_json: Vec::new(),
        }
    }

    fn done_outcome(item_id: &str, item_index: u32, exception_type: &str) -> Outcome {
        Outcome {
            batch_id: "batch".to_string(),
            sequence: (item_index + 1) as u64,
            message: Some(outcome::Message::ItemOutcome(ItemOutcome {
                item_id: item_id.to_string(),
                item_index,
                result: Some(item_outcome::Result::Done(Done {
                    resolved_exception_json: serde_json::to_vec(&exception(exception_type))
                        .expect("valid exception"),
                })),
            })),
        }
    }

    fn batch_summary_outcome(item_outcomes: u32, missing_count: usize) -> Outcome {
        use cymbal_proto::cymbal::resolution::v1::{BatchSummary, ItemReference};
        Outcome {
            batch_id: "batch".to_string(),
            sequence: 999,
            message: Some(outcome::Message::BatchSummary(BatchSummary {
                submitted_items: item_outcomes + missing_count as u32,
                item_outcomes,
                done_items: item_outcomes,
                error_items: 0,
                retry_items: 0,
                missing_items: (0..missing_count)
                    .map(|i| ItemReference {
                        item_id: format!("missing:{i}"),
                        item_index: 1000 + i as u32,
                    })
                    .collect(),
                duplicate_items: vec![],
            })),
        }
    }

    fn exception(exception_type: &str) -> Exception {
        Exception {
            exception_id: None,
            exception_type: exception_type.to_string(),
            exception_message: "boom".to_string(),
            mechanism: None,
            module: None,
            thread_id: None,
            stack: None,
        }
    }
}
