use std::collections::{HashMap, HashSet};
use std::time::Instant;

use chrono::{DateTime, Utc};
use metrics::histogram;
use uuid::Uuid;

use super::constants::{
    CAPTURE_V1_DISTINCT_ID_MAX_SIZE, CAPTURE_V1_EVENTS_DROPPED,
    CAPTURE_V1_EVENTS_REROUTED_HISTORICAL, CAPTURE_V1_EVENTS_RESTRICTED,
    CAPTURE_V1_EVENT_ADJUSTMENTS_APPLIED, CAPTURE_V1_MAX_EVENT_NAME_LENGTH,
    CAPTURE_V1_OVERFLOW_ROUTED, CAPTURE_V1_PARSED_EVENTS, CAPTURE_V1_PROCESSING_DURATION_SECONDS,
    CAPTURE_V1_RATE_LIMITER, DETAIL_EVENT_RESTRICTION_DROP, DETAIL_INVALID_OPTIONS,
    DETAIL_PERSON_PROCESSING_DISABLED, FUTURE_EVENT_HOURS_CUTOFF_MS, ILLEGAL_DISTINCT_IDS,
};
use super::response::BatchResponse;
use super::types::{Batch, Event, EventResult, Options, WrappedEvent};
use crate::event_restrictions::{EventContext, EventRestrictionService};
use crate::global_rate_limiter::{GlobalRateLimitKey, GlobalRateLimiter};
use crate::v0_request::DataType;
use limiters::overflow::{OverflowLimiter, OverflowLimiterResult};
use tracing::Level;

use super::context::Context;
use crate::router;
use crate::v1::context::RequestContext;
use crate::v1::sinks::event::Event as SinkEvent;
use crate::v1::sinks::types::SinkResult;
use crate::v1::sinks::{serialize_batch, Destination};
use crate::v1::Error;

/// Maps event name to its Kafka destination, mirroring legacy DataType assignment.
///
/// Unlike legacy capture, v1 does NOT split heatmap/scroll-depth properties out of
/// non-$$heatmap events (e.g. $pageview) into a synthetic redirect. We keep properties
/// as opaque RawValue to avoid deserialization. The Node.js events subpipeline
/// (extractHeatmapDataStep) handles extraction when `skip_heatmap_processing` is unset
/// in Kafka headers — removing that fallback would break scroll-depth heatmaps for v1.
fn destination_for_event_name(name: &str) -> Destination {
    match name {
        "$exception" => Destination::ExceptionErrorTracking,
        "$$heatmap" => Destination::HeatmapMain,
        "$$client_ingestion_warning" => Destination::ClientIngestionWarning,
        _ => Destination::AnalyticsMain,
    }
}

pub async fn process_batch(
    state: &router::State,
    context: &mut Context,
    batch: Batch,
) -> Result<BatchResponse, Error> {
    let processing_start = Instant::now();
    crate::ctx_log!(Level::INFO, context, "process_batch called");

    validate_batch(&batch)?;
    context.set_batch_metadata(&batch);

    let mut events = validate_events(context, batch)?;

    // Nothing left to process — return 200 with per-event drops.
    if events.iter().all(|ev| ev.result != EventResult::Ok) {
        return Ok(BatchResponse::build(context, &events));
    }

    // Verify gateway provenance before the quota limiter so verified events can
    // be exempted from the llm_events meter (they're wallet-billed, not AIO).
    apply_gateway_provenance(state, context, &mut events);

    crate::v1::quota_limiter_shim::apply_quota_limits(
        &state.quota_limiter,
        &context.api_token,
        &mut events,
    )
    .await?;

    if let Some(ref service) = state.event_restriction_service {
        apply_restrictions(
            service,
            &context.api_token,
            context.server_received_at.timestamp(),
            &mut events,
        )
        .await;
    }

    apply_historical_rerouting(&state.historical_cfg, context, &mut events);

    // Overflow and global rate limit are independent checks on different axes:
    // overflow reroutes bursting keys; global rate limit disables person processing.
    if let Some(ref limiter) = state.overflow_limiter {
        apply_overflow_stamping(limiter, context, &mut events);
    }

    if let Some(ref limiter) = state.global_rate_limiter_token_distinctid {
        apply_token_distinct_id_limits(limiter, context, &mut events).await;
    }

    histogram!(
        CAPTURE_V1_PROCESSING_DURATION_SECONDS,
        "path" => context.path,
    )
    .record(processing_start.elapsed().as_secs_f64());

    // Serialize (hoisted out of the sink; parallel for large batches), then
    // publish and merge results before building the response.
    let sink_router = state
        .v1_sink_router
        .as_ref()
        .ok_or_else(|| Error::ServiceUnavailable("v1 sink router not configured".into()))?;

    // serialize_batch consumes the events and hands them back, so we can keep
    // correlating results to them and build the response.
    let (mut events, serialized) =
        serialize_batch(events, context, state.capture_v1_scatter_gather_min_batch).await;

    let sink_results = sink_router
        .publish_batch(sink_router.default_sink(), context, &serialized.prepared)
        .await
        .map_err(|e| Error::InternalError(e.to_string()))?;

    // Serialize-step failures and sink results are both per-event SinkResults;
    // merge them together so serialization drops surface in the response.
    let mut all_results = serialized.failures;
    all_results.extend(sink_results);
    merge_sink_results(&mut events, &all_results);

    Ok(BatchResponse::build(context, &events))
}

// Verify gateway provenance on each `$ai_*` event: a fresh, valid signature stamps
// the trusted marker and exempts it from the llm_events meter; anything else has its
// `$ai_gateway*` props stripped. The strip path skips the parse unless the raw bytes
// plausibly carry a gateway key, so ordinary traffic stays off the hot path.
fn apply_gateway_provenance(state: &router::State, context: &Context, events: &mut [WrappedEvent]) {
    use crate::v1::gateway_provenance as gp;

    let secret = state
        .ai_gateway_signing_secret
        .as_deref()
        .filter(|s| !s.is_empty());
    let now = context.server_received_at;

    for ev in events.iter_mut() {
        if ev.result != EventResult::Ok || !ev.event.event.starts_with("$ai_") {
            continue;
        }

        let sig = context.gateway_signature.as_ref();
        let outcome = match (secret, sig) {
            (Some(secret), Some(sig)) => gp::verify(
                secret.as_bytes(),
                &context.api_token,
                &ev.event.distinct_id,
                sig,
                now,
            ),
            // No secret or no signature — nothing to trust.
            _ => gp::Provenance::Invalid,
        };

        // Trust needs a non-empty request_id — billing dedups exemptions by it.
        let request_id = sig.map(|s| s.request_id.as_str()).unwrap_or_default();
        let trusted = outcome == gp::Provenance::Verified && !request_id.is_empty();

        if trusted {
            match gp::stamp_verified_raw(&ev.event.properties, request_id) {
                gp::StampOutcome::Stamped(props) => {
                    ev.event.properties = props;
                    ev.is_gateway_verified = true;
                    metrics::counter!(gp::PROVENANCE_METRIC, "reason" => "verified").increment(1);
                }
                gp::StampOutcome::Unparseable => drop_unparseable_gateway_props(ev),
            }
        } else if gp::has_gateway_props(&ev.event.properties) {
            match gp::strip_gateway_raw(&ev.event.properties) {
                gp::StripOutcome::Stripped { props, forged } => {
                    ev.event.properties = props;
                    let reason = if forged {
                        // A client-supplied $ai_gateway_verified — a real forgery.
                        "forged"
                    } else if outcome == gp::Provenance::Stale {
                        "stale" // valid HMAC, outside the window — clock skew
                    } else {
                        "stripped" // leftover $ai_gateway* prop, no marker — benign
                    };
                    metrics::counter!(gp::PROVENANCE_METRIC, "reason" => reason).increment(1);
                }
                gp::StripOutcome::Unchanged => {}
                gp::StripOutcome::Unparseable => drop_unparseable_gateway_props(ev),
            }
        }
    }
}

/// Drop a `$ai_*` event whose properties carry a gateway key but can't be parsed to
/// strip or stamp it. `RawValue` and ClickHouse accept JSON the typed parse rejects,
/// so a forged marker we can't remove would otherwise survive to billing — fail closed.
fn drop_unparseable_gateway_props(ev: &mut WrappedEvent) {
    ev.result = EventResult::Drop;
    ev.destination = Destination::Drop;
    ev.details = Some("gateway_props_unparseable");
    metrics::counter!(
        crate::v1::gateway_provenance::PROVENANCE_METRIC,
        "reason" => "dropped_unparseable"
    )
    .increment(1);
}

// ---------------------------------------------------------------------------
// SinkResult → WrappedEvent merge
// ---------------------------------------------------------------------------

/// Correlate per-event `SinkResult`s back to the batch of `WrappedEvent`s by UUID.
///
/// Events that were not published (`should_publish() == false`) are untouched.
/// Published events receive updated `result` and `details` based on the sink outcome:
/// - `Outcome::Success` → keep existing result (Ok or Warning)
/// - `Outcome::RetriableError` | `Outcome::Timeout` → `EventResult::Retry`
/// - `Outcome::FatalError` → `EventResult::Drop`
pub fn merge_sink_results(events: &mut [WrappedEvent], sink_results: &[Box<dyn SinkResult>]) {
    use crate::v1::sinks::types::Outcome;

    let results_by_uuid: HashMap<Uuid, &dyn SinkResult> =
        sink_results.iter().map(|r| (r.key(), r.as_ref())).collect();

    for event in events.iter_mut() {
        if !event.should_publish() {
            continue;
        }

        let Some(result) = results_by_uuid.get(&event.uuid) else {
            continue;
        };

        match result.outcome() {
            Outcome::Success => {
                // Leave event.result as-is (Ok or Warning from upstream processing)
            }
            Outcome::RetriableError | Outcome::Timeout => {
                event.result = EventResult::Retry;
                event.details = Some("not_persisted");
            }
            Outcome::FatalError => {
                event.result = EventResult::Drop;
                let cause = result.cause().unwrap_or("rejected");
                event.details = Some(match cause {
                    "serialization_failed" | "event_too_big" => cause,
                    _ => "rejected",
                });
            }
        }
    }
}

/// Records a whole-batch validation abort. These errors reject the batch as a
/// unit, so every event in it is dropped — but the request only ever ticks one
/// `capture_v1_analytics_error`, leaving the event count invisible. Charge the
/// full batch length to `capture_v1_events_dropped` so dup/oversize/invalid-uuid
/// rejections show real per-event loss. Returns `err` for use at the call site.
fn count_validation_abort(err: Error, batch_len: usize) -> Error {
    metrics::counter!(
        CAPTURE_V1_EVENTS_DROPPED,
        "reason" => err.tag(),
        "stage" => "validation_abort",
    )
    .increment(batch_len as u64);
    err
}

fn validate_batch(batch: &Batch) -> Result<(), Error> {
    let batch_len = batch.batch.len();
    if batch.batch.is_empty() {
        return Err(count_validation_abort(Error::EmptyBatch, batch_len));
    }

    DateTime::parse_from_rfc3339(&batch.created_at).map_err(|_| {
        count_validation_abort(
            Error::InvalidBatch(format!(
                "created_at is not valid RFC 3339: {}",
                batch.created_at
            )),
            batch_len,
        )
    })?;

    Ok(())
}

fn validate_events(context: &RequestContext, batch: Batch) -> Result<Vec<WrappedEvent>, Error> {
    let batch_len = batch.batch.len();
    let mut events: Vec<WrappedEvent> = Vec::with_capacity(batch_len);
    let mut seen: HashSet<Uuid> = HashSet::with_capacity(batch_len);
    let mut illegal_distinct_id_count: u64 = 0;

    for event in batch.batch.into_iter() {
        if event.uuid.is_empty() {
            return Err(count_validation_abort(Error::MissingEventUuid, batch_len));
        }
        let uuid = Uuid::parse_str(&event.uuid).map_err(|_| {
            count_validation_abort(Error::InvalidEventUuid(event.uuid.clone()), batch_len)
        })?;
        if !seen.insert(uuid) {
            return Err(count_validation_abort(
                Error::DuplicateEventUuid(event.uuid.clone()),
                batch_len,
            ));
        }

        let destination = destination_for_event_name(&event.event);

        match validate_event(&event) {
            Ok(raw_ts) => {
                // Options validation: coerce known fields or drop the event.
                // The malformed-event metric (CAPTURE_V1_PARSED_EVENTS{malformed})
                // is emitted uniformly by observe_malformed_events, matching the
                // other validate-stage drops. Per-field detail is deferred to the
                // sampled verbose-logging mode rather than logged per-event here.
                let options = match event.options.validate() {
                    Ok(opts) => opts,
                    Err(_) => {
                        events.push(WrappedEvent {
                            event,
                            uuid,
                            options: Options::default(),
                            adjusted_timestamp: None,
                            result: EventResult::Drop,
                            details: Some(DETAIL_INVALID_OPTIONS),
                            destination,
                            force_disable_person_processing: false,
                            is_gateway_verified: false,
                        });
                        continue;
                    }
                };

                metrics::counter!(CAPTURE_V1_PARSED_EVENTS, "result" => "valid").increment(1);
                let adjusted = normalize_timestamp(
                    context,
                    options.disable_skew_correction.unwrap_or(false),
                    raw_ts,
                );
                let illegal = is_distinct_id_illegal(&event.distinct_id);
                if illegal {
                    illegal_distinct_id_count += 1;
                }
                events.push(WrappedEvent {
                    event,
                    uuid,
                    options,
                    adjusted_timestamp: Some(adjusted),
                    result: EventResult::Ok,
                    details: if illegal {
                        Some(DETAIL_PERSON_PROCESSING_DISABLED)
                    } else {
                        None
                    },
                    destination,
                    force_disable_person_processing: illegal,
                    is_gateway_verified: false,
                });
            }
            Err(err) => {
                events.push(WrappedEvent {
                    event,
                    uuid,
                    options: Options::default(),
                    adjusted_timestamp: None,
                    result: EventResult::Drop,
                    details: Some(err.tag()),
                    destination,
                    force_disable_person_processing: false,
                    is_gateway_verified: false,
                });
            }
        }
    }

    if illegal_distinct_id_count > 0 {
        metrics::counter!(CAPTURE_V1_EVENT_ADJUSTMENTS_APPLIED, "reason" => "person_processing_disabled")
            .increment(illegal_distinct_id_count);
        crate::ctx_log!(
            Level::INFO,
            context,
            count = illegal_distinct_id_count,
            "events with illegal distinct_id -- person processing disabled"
        );
    }

    if events.iter().any(|e| e.result != EventResult::Ok) {
        observe_malformed_events(context, &events);
    }

    Ok(events)
}

fn observe_malformed_events(context: &RequestContext, events: &[WrappedEvent]) {
    let mut malformed: HashMap<&'static str, u64> = HashMap::new();

    for event in events.iter() {
        if event.result != EventResult::Ok {
            if let Some(tag) = event.details {
                *malformed.entry(tag).or_insert(0) += 1;
            }
        }
    }

    for (error_tag, count) in &malformed {
        metrics::counter!(CAPTURE_V1_PARSED_EVENTS, "result" => "malformed", "error" => *error_tag)
            .increment(*count);
    }

    let summary: String = malformed
        .iter()
        .map(|(tag, count)| format!("{tag}={count}"))
        .collect::<Vec<_>>()
        .join(", ");

    crate::ctx_log!(Level::WARN, context, "malformed events: {summary}");
}

/// Expects a pre-trimmed distinct_id (`Event.distinct_id` is trimmed at
/// deserialization).
fn is_distinct_id_illegal(distinct_id: &str) -> bool {
    ILLEGAL_DISTINCT_IDS
        .iter()
        .any(|id| distinct_id.eq_ignore_ascii_case(id))
}

fn validate_event(event: &Event) -> Result<DateTime<Utc>, Error> {
    if event.event == "$performance_event" {
        return Err(Error::DroppedPerformanceEvent);
    }
    if event.event.is_empty() {
        return Err(Error::MissingEventName);
    }
    if event.event.len() > CAPTURE_V1_MAX_EVENT_NAME_LENGTH {
        return Err(Error::EventNameTooLong);
    }
    if event.distinct_id.is_empty() {
        return Err(Error::MissingDistinctId);
    }
    if event.distinct_id.len() > CAPTURE_V1_DISTINCT_ID_MAX_SIZE {
        return Err(Error::DistinctIdTooLarge);
    }

    let ts = DateTime::parse_from_rfc3339(&event.timestamp)
        .map(|dt| dt.with_timezone(&Utc))
        .map_err(|_| Error::InvalidEventTimestamp)?;

    if event.properties.get().as_bytes().first() != Some(&b'{') {
        return Err(Error::MalformedEventProperties);
    }

    Ok(ts)
}

fn normalize_timestamp(
    context: &RequestContext,
    disable_skew_correction: bool,
    raw_event_ts: DateTime<Utc>,
) -> DateTime<Utc> {
    if disable_skew_correction {
        return raw_event_ts;
    }

    let adjusted = raw_event_ts - context.clock_skew();
    let now = context.server_received_at;
    if adjusted.signed_duration_since(now).num_milliseconds() > FUTURE_EVENT_HOURS_CUTOFF_MS {
        metrics::counter!(CAPTURE_V1_EVENT_ADJUSTMENTS_APPLIED, "reason" => "future_timestamp_clamp")
            .increment(1);
        return now;
    }
    adjusted
}

fn apply_historical_rerouting(
    cfg: &router::HistoricalConfig,
    context: &RequestContext,
    events: &mut [WrappedEvent],
) {
    for event in events.iter_mut() {
        if event.result != EventResult::Ok || event.destination != Destination::AnalyticsMain {
            continue;
        }

        // Batch-level flag: all events in a historical migration batch are historical
        if context.historical_migration {
            event.destination = Destination::AnalyticsHistorical;
            metrics::counter!(CAPTURE_V1_EVENTS_REROUTED_HISTORICAL, "reason" => "batch_flag")
                .increment(1);
            continue;
        }

        // Timestamp-based: reroute old events when the feature is enabled
        if let Some(ts) = event.adjusted_timestamp {
            if cfg.should_reroute(crate::v0_request::DataType::AnalyticsMain, ts) {
                event.destination = Destination::AnalyticsHistorical;
                metrics::counter!(
                    CAPTURE_V1_EVENTS_REROUTED_HISTORICAL,
                    "reason" => "timestamp"
                )
                .increment(1);
            }
        }
    }
}

fn apply_overflow_stamping(
    limiter: &OverflowLimiter,
    ctx: &RequestContext,
    events: &mut [WrappedEvent],
) {
    for event in events.iter_mut() {
        if event.destination != Destination::AnalyticsMain {
            continue;
        }
        if event.result == EventResult::Drop {
            continue;
        }

        let key = event.partition_key(ctx);

        match limiter.is_limited(&key) {
            OverflowLimiterResult::ForceLimited => {
                event.destination = Destination::Overflow;
                // Disables person processing AND nulls partition key at sink.
                event.force_disable_person_processing = true;
                metrics::counter!(CAPTURE_V1_OVERFLOW_ROUTED, "reason" => "force_limited")
                    .increment(1);
            }
            OverflowLimiterResult::Limited => {
                event.destination = Destination::Overflow;
                if !limiter.should_preserve_locality() {
                    // Nulls partition key at sink -- spreads across partitions.
                    event.force_disable_person_processing = true;
                }
                metrics::counter!(CAPTURE_V1_OVERFLOW_ROUTED, "reason" => "rate_limited")
                    .increment(1);
            }
            OverflowLimiterResult::NotLimited => {}
        }
    }
}

async fn apply_restrictions(
    service: &EventRestrictionService,
    token: &str,
    now_ts: i64,
    events: &mut [WrappedEvent],
) {
    for event in events.iter_mut() {
        if event.result != EventResult::Ok {
            continue;
        }

        // Derive the pipeline from the event name so each event is matched
        // against the correct restriction slice (Analytics vs ErrorTracking).
        // `pipeline() == None` for heatmaps / ingestion warnings / snapshots
        // → they pass through unrestricted, exactly as v0 does.
        let Some(pipeline) = DataType::from_event_name(&event.event.event, false).pipeline() else {
            continue;
        };

        let event_ctx = EventContext {
            distinct_id: Some(&event.event.distinct_id),
            session_id: event.event.session_id.as_deref(),
            event_name: Some(&event.event.event),
            event_uuid: Some(&event.event.uuid),
            now_ts,
        };

        let applied = service.get_restrictions(token, &event_ctx, pipeline).await;

        if applied.should_drop() {
            event.result = EventResult::Drop;
            event.details = Some(DETAIL_EVENT_RESTRICTION_DROP);
            event.destination = Destination::Drop;
            metrics::counter!(CAPTURE_V1_EVENTS_DROPPED, "reason" => "event_restriction")
                .increment(1);
            continue;
        }

        // Priority: overflow < custom topic < DLQ (DLQ wins, applied last)
        // Overflow only applies to AnalyticsMain: AnalyticsHistorical must never
        // overflow (legacy sink invariant). Today this stage runs before
        // historical rerouting so the destination is always AnalyticsMain here;
        // the explicit guard makes the invariant ordering-independent.
        if applied.force_overflow() && event.destination == Destination::AnalyticsMain {
            event.destination = Destination::Overflow;
            metrics::counter!(CAPTURE_V1_EVENTS_RESTRICTED, "action" => "force_overflow")
                .increment(1);
        }
        if let Some(topic) = applied.redirect_to_topic() {
            event.destination = Destination::Custom(topic.to_string());
            metrics::counter!(CAPTURE_V1_EVENTS_RESTRICTED, "action" => "redirect_to_topic")
                .increment(1);
        }
        if applied.redirect_to_dlq() {
            event.destination = Destination::Dlq;
            metrics::counter!(CAPTURE_V1_EVENTS_RESTRICTED, "action" => "redirect_to_dlq")
                .increment(1);
        }

        if applied.skip_person_processing() {
            event.force_disable_person_processing = true;
            metrics::counter!(CAPTURE_V1_EVENTS_RESTRICTED, "action" => "skip_person_processing")
                .increment(1);
        }
    }
}

async fn apply_token_distinct_id_limits(
    limiter: &GlobalRateLimiter,
    context: &RequestContext,
    events: &mut [WrappedEvent],
) {
    let mut limited_distinct_ids: HashSet<&str> = HashSet::new();
    let mut allowed_count: u64 = 0;

    for event in events.iter_mut() {
        if event.result != EventResult::Ok || event.force_disable_person_processing {
            continue;
        }
        let cache_key =
            GlobalRateLimitKey::TokenDistinctId(&context.api_token, &event.event.distinct_id)
                .to_cache_key();
        if limiter.is_limited(&cache_key, 1).await.is_some() {
            event.result = EventResult::Warning;
            // Disables person processing -- sink will null partition key for Main/Overflow.
            event.force_disable_person_processing = true;
            event.details = Some(DETAIL_PERSON_PROCESSING_DISABLED);
            // Reroute to overflow to spread a hot token:distinct_id across
            // partitions. Gated to AnalyticsMain only: this stage runs after
            // historical rerouting, and AnalyticsHistorical must never overflow
            // (matches the legacy sink invariant). Other lanes (exceptions,
            // heatmaps, etc.) keep their own destination.
            if event.destination == Destination::AnalyticsMain {
                event.destination = Destination::Overflow;
            }
            limited_distinct_ids.insert(event.event.distinct_id.as_str());
        } else {
            allowed_count += 1;
        }
    }

    if allowed_count > 0 {
        metrics::counter!(
            CAPTURE_V1_RATE_LIMITER,
            "limiter" => "token_distinct_id",
            "outcome" => "allowed",
        )
        .increment(allowed_count);
    }

    if !limited_distinct_ids.is_empty() {
        let limited_count = limited_distinct_ids.len();
        let ids: Vec<&str> = limited_distinct_ids.iter().copied().collect();
        let preview: String = if ids.len() > 10 {
            format!("{}...", ids[..10].join(", "))
        } else {
            ids.join(", ")
        };

        metrics::counter!(
            CAPTURE_V1_RATE_LIMITER,
            "limiter" => "token_distinct_id",
            "outcome" => "limited",
        )
        .increment(limited_count as u64);

        crate::ctx_log!(Level::WARN, context,
            limited_count = limited_count,
            distinct_ids = %preview,
            "events rate limited by distinct_id -- person processing disabled"
        );
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration as StdDuration;

    use chrono::{DateTime, Duration, Utc};
    use uuid::Uuid;

    use super::*;
    use crate::event_restrictions::{
        Pipeline, Restriction, RestrictionManager, RestrictionScope, RestrictionType,
    };
    use crate::v1::analytics::constants::CAPTURE_V1_PATH;
    use crate::v1::analytics::types::{Batch, Event};
    use crate::v1::sinks::{Destination, DEFAULT_SCATTER_GATHER_MIN_BATCH};
    use crate::v1::test_utils::{
        self, find_by_did, malformed_wrapped_event, raw_obj, valid_event, wrapped_event,
        wrapped_event_at,
    };
    use crate::v1::Error;

    fn valid_batch(events: Vec<Event>) -> Batch {
        Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: events,
        }
    }

    /// Build an Event through serde — the production entry point — so the
    /// trim-at-deserialization invariant on uuid/distinct_id applies.
    fn deserialized_event(uuid: &str, distinct_id: &str) -> Event {
        let json = serde_json::json!({
            "event": "$pageview",
            "uuid": uuid,
            "distinct_id": distinct_id,
            "timestamp": "2026-03-19T14:29:58.123Z",
        });
        serde_json::from_str(&json.to_string()).unwrap()
    }

    /// Runs `f` under a local metrics recorder and returns the recorded
    /// `capture_v1_events_dropped` counter for the given `reason`+`stage` labels,
    /// so whole-batch-abort tests can assert the exact per-event drop count.
    fn dropped_count(reason: &str, stage: &str, f: impl FnOnce()) -> Option<u64> {
        use metrics_util::debugging::{DebugValue, DebuggingRecorder};

        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        f();

        snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find_map(|(key, _, _, value)| {
                if key.key().name() != CAPTURE_V1_EVENTS_DROPPED {
                    return None;
                }
                let labels: std::collections::HashMap<&str, &str> =
                    key.key().labels().map(|l| (l.key(), l.value())).collect();
                if labels.get("reason") != Some(&reason) || labels.get("stage") != Some(&stage) {
                    return None;
                }
                match value {
                    DebugValue::Counter(v) => Some(v),
                    _ => None,
                }
            })
    }

    // --- validate_batch ---

    #[test]
    fn batch_valid() {
        let batch = valid_batch(vec![valid_event()]);
        assert!(validate_batch(&batch).is_ok());
    }

    #[test]
    fn batch_empty() {
        let batch = valid_batch(vec![]);
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::EmptyBatch));
    }

    #[test]
    fn batch_bad_created_at() {
        let batch = Batch {
            created_at: "not-a-timestamp".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![valid_event()],
        };
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::InvalidBatch(_)));
    }

    // --- validate_event ---

    #[test]
    fn event_valid() {
        let event = valid_event();
        let ts = validate_event(&event);
        assert!(ts.is_ok());
        assert_eq!(
            ts.unwrap(),
            DateTime::parse_from_rfc3339("2026-03-19T14:29:58.123Z")
                .unwrap()
                .with_timezone(&Utc)
        );
    }

    #[test]
    fn event_empty_name() {
        let mut event = valid_event();
        event.event = String::new();
        assert!(matches!(
            validate_event(&event),
            Err(Error::MissingEventName)
        ));
    }

    #[test]
    fn event_name_too_long() {
        let mut event = valid_event();
        event.event = "x".repeat(CAPTURE_V1_MAX_EVENT_NAME_LENGTH + 1);
        assert!(matches!(
            validate_event(&event),
            Err(Error::EventNameTooLong)
        ));
    }

    #[test]
    fn event_name_at_max_length_ok() {
        let mut event = valid_event();
        event.event = "x".repeat(CAPTURE_V1_MAX_EVENT_NAME_LENGTH);
        assert!(validate_event(&event).is_ok());
    }

    #[test]
    fn event_empty_distinct_id() {
        let mut event = valid_event();
        event.distinct_id = String::new();
        assert!(matches!(
            validate_event(&event),
            Err(Error::MissingDistinctId)
        ));
    }

    #[test]
    fn event_distinct_id_too_large() {
        let mut event = valid_event();
        event.distinct_id = "d".repeat(CAPTURE_V1_DISTINCT_ID_MAX_SIZE + 1);
        assert!(matches!(
            validate_event(&event),
            Err(Error::DistinctIdTooLarge)
        ));
    }

    #[test]
    fn event_distinct_id_at_max_size_ok() {
        let mut event = valid_event();
        event.distinct_id = "d".repeat(CAPTURE_V1_DISTINCT_ID_MAX_SIZE);
        assert!(validate_event(&event).is_ok());
    }

    #[test]
    fn event_whitespace_only_distinct_id_rejected() {
        let event = deserialized_event(&Uuid::new_v4().to_string(), "   ");
        assert_eq!(event.distinct_id, "");
        assert!(matches!(
            validate_event(&event),
            Err(Error::MissingDistinctId)
        ));
    }

    #[test]
    fn event_padded_distinct_id_ok() {
        let event = deserialized_event(&Uuid::new_v4().to_string(), "  user-42  ");
        assert_eq!(event.distinct_id, "user-42");
        assert!(validate_event(&event).is_ok());
    }

    #[test]
    fn event_distinct_id_length_checked_after_trim() {
        let uuid = Uuid::new_v4().to_string();
        let event = deserialized_event(
            &uuid,
            &format!("  {}  ", "d".repeat(CAPTURE_V1_DISTINCT_ID_MAX_SIZE)),
        );
        assert!(validate_event(&event).is_ok());

        let event = deserialized_event(
            &uuid,
            &format!("  {}  ", "d".repeat(CAPTURE_V1_DISTINCT_ID_MAX_SIZE + 1)),
        );
        assert!(matches!(
            validate_event(&event),
            Err(Error::DistinctIdTooLarge)
        ));
    }

    #[test]
    fn event_illegal_distinct_ids_pass_validation() {
        let illegal_ids = [
            "anonymous",
            "ANONYMOUS",
            "null",
            "NULL",
            "0",
            "  undefined  ",
            "[object Object]",
            "NaN",
            "GUEST",
            "none",
            "00000000-0000-0000-0000-000000000000",
            "  guest  ",
            "true",
            "FALSE",
            "distinct_id",
            "not_authenticated",
        ];
        for id in illegal_ids {
            let event = deserialized_event(&Uuid::new_v4().to_string(), id);
            assert!(
                validate_event(&event).is_ok(),
                "expected Ok for illegal distinct_id={id:?} (flagging happens in validate_events)"
            );
        }
    }

    #[test]
    fn event_legal_distinct_ids_accepted() {
        let legal_ids = [
            "user-42",
            "my-email@foo.com",
            "1",
            "anon-abc123",
            "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
            "01",
            "nope",
        ];
        for id in legal_ids {
            let mut event = valid_event();
            event.distinct_id = id.to_string();
            assert!(
                validate_event(&event).is_ok(),
                "expected Ok for distinct_id={id:?}"
            );
        }
    }

    #[test]
    fn event_bad_timestamp() {
        let mut event = valid_event();
        event.timestamp = "yesterday".to_string();
        assert!(matches!(
            validate_event(&event),
            Err(Error::InvalidEventTimestamp)
        ));
    }

    #[test]
    fn event_empty_timestamp() {
        let mut event = valid_event();
        event.timestamp = String::new();
        assert!(matches!(
            validate_event(&event),
            Err(Error::InvalidEventTimestamp)
        ));
    }

    #[test]
    fn event_performance_event_rejected() {
        let mut event = valid_event();
        event.event = "$performance_event".to_string();
        assert!(matches!(
            validate_event(&event),
            Err(Error::DroppedPerformanceEvent)
        ));
    }

    #[test]
    fn event_malformed_properties() {
        let mut event = valid_event();
        event.properties = raw_obj("[1,2,3]");
        assert!(matches!(
            validate_event(&event),
            Err(Error::MalformedEventProperties)
        ));
    }

    #[test]
    fn validate_events_performance_event_dropped_others_ok() {
        let ctx = test_utils::test_context();
        let perf = Event {
            event: "$performance_event".to_string(),
            ..valid_event()
        };
        let perf_uuid = Uuid::parse_str(&perf.uuid).unwrap();
        let normal = valid_event();
        let normal_uuid = Uuid::parse_str(&normal.uuid).unwrap();
        let batch = valid_batch(vec![perf, normal]);
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events.len(), 2);
        // Vec preserves input order: perf first, normal second.
        let p = &events[0];
        assert_eq!(p.uuid, perf_uuid);
        assert_eq!(p.result, EventResult::Drop);
        assert_eq!(p.details, Some("dropped_performance_event"));
        let n = &events[1];
        assert_eq!(n.uuid, normal_uuid);
        assert_eq!(n.result, EventResult::Ok);
    }

    #[test]
    fn validate_events_all_performance_events_dropped() {
        let ctx = test_utils::test_context();
        let p1 = Event {
            event: "$performance_event".to_string(),
            ..valid_event()
        };
        let p2 = Event {
            event: "$performance_event".to_string(),
            ..valid_event()
        };
        let batch = valid_batch(vec![p1, p2]);
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events.len(), 2);
        for ev in &events {
            assert_eq!(ev.result, EventResult::Drop);
            assert_eq!(ev.details, Some("dropped_performance_event"));
        }
    }

    #[test]
    fn validate_events_illegal_distinct_id_flags_person_processing_disabled() {
        for id in ILLEGAL_DISTINCT_IDS {
            let ctx = test_utils::test_context();
            let mut illegal_event = valid_event();
            illegal_event.distinct_id = id.to_string();
            let legal_event = valid_event();
            let batch = valid_batch(vec![illegal_event, legal_event]);
            let events = validate_events(&ctx, batch).unwrap();
            assert_eq!(events.len(), 2, "id={id:?}");

            let flagged = &events[0];
            assert_eq!(flagged.result, EventResult::Ok, "id={id:?}");
            assert!(flagged.force_disable_person_processing, "id={id:?}");
            assert_eq!(
                flagged.details,
                Some(DETAIL_PERSON_PROCESSING_DISABLED),
                "id={id:?}"
            );
            assert_ne!(flagged.destination, Destination::Drop, "id={id:?}");

            let normal = &events[1];
            assert_eq!(normal.result, EventResult::Ok, "id={id:?}");
            assert!(!normal.force_disable_person_processing, "id={id:?}");
            assert!(normal.details.is_none(), "id={id:?}");
        }
    }

    #[test]
    fn validate_events_padded_illegal_distinct_id_still_flagged() {
        let ctx = test_utils::test_context();
        let event = deserialized_event(&Uuid::new_v4().to_string(), "  NULL  ");
        let batch = valid_batch(vec![event]);
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events[0].result, EventResult::Ok);
        assert!(events[0].force_disable_person_processing);
        assert_eq!(events[0].details, Some(DETAIL_PERSON_PROCESSING_DISABLED));
    }

    #[test]
    fn validate_events_illegal_distinct_id_still_publishable() {
        for id in ILLEGAL_DISTINCT_IDS {
            let ctx = test_utils::test_context();
            let mut illegal_event = valid_event();
            illegal_event.distinct_id = id.to_string();
            let batch = valid_batch(vec![illegal_event]);
            let events = validate_events(&ctx, batch).unwrap();
            assert_eq!(events.len(), 1, "id={id:?}");
            assert!(events[0].should_publish(), "id={id:?}");
        }
    }

    // --- validate_events ---

    #[test]
    fn validate_events_duplicate_uuid_bails_batch() {
        let ctx = test_utils::test_context();
        let shared_uuid = Uuid::new_v4().to_string();
        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![
                Event {
                    uuid: shared_uuid.clone(),
                    ..valid_event()
                },
                Event {
                    uuid: shared_uuid,
                    ..valid_event()
                },
            ],
        };
        let err = validate_events(&ctx, batch).unwrap_err();
        assert!(matches!(err, Error::DuplicateEventUuid(_)));
    }

    #[test]
    fn validate_events_invalid_uuid_bails_batch() {
        let ctx = test_utils::test_context();
        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![Event {
                uuid: "not-a-uuid".to_string(),
                ..valid_event()
            }],
        };
        let err = validate_events(&ctx, batch).unwrap_err();
        assert!(matches!(err, Error::InvalidEventUuid(_)));
    }

    #[test]
    fn validate_events_empty_uuid_bails_batch() {
        let ctx = test_utils::test_context();
        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![Event {
                uuid: String::new(),
                ..valid_event()
            }],
        };
        let err = validate_events(&ctx, batch).unwrap_err();
        assert!(matches!(err, Error::MissingEventUuid));
    }

    // --- whole-batch abort drop counting ---
    // Each abort rejects the entire batch, so the dropped-events counter must be
    // charged the FULL batch length (not 1, and not just the events seen before
    // the bad one) — that is the per-event loss the single request-level
    // capture_v1_analytics_error tick can't show.

    #[test]
    fn duplicate_uuid_abort_counts_whole_batch() {
        let ctx = test_utils::test_context();
        let shared = Uuid::new_v4().to_string();
        // dup is only detected at index 2, but all 3 events are lost.
        let batch = valid_batch(vec![
            Event {
                uuid: shared.clone(),
                ..valid_event()
            },
            Event {
                uuid: Uuid::new_v4().to_string(),
                ..valid_event()
            },
            Event {
                uuid: shared,
                ..valid_event()
            },
        ]);

        let count = dropped_count("duplicate_event_uuid", "validation_abort", || {
            assert!(matches!(
                validate_events(&ctx, batch).unwrap_err(),
                Error::DuplicateEventUuid(_)
            ));
        });
        assert_eq!(count, Some(3));
    }

    #[test]
    fn invalid_uuid_abort_counts_whole_batch() {
        let ctx = test_utils::test_context();
        // bad uuid at index 0; the 2 trailing valid events are lost too.
        let batch = valid_batch(vec![
            Event {
                uuid: "not-a-uuid".to_string(),
                ..valid_event()
            },
            valid_event(),
            valid_event(),
        ]);

        let count = dropped_count("invalid_event_uuid", "validation_abort", || {
            assert!(matches!(
                validate_events(&ctx, batch).unwrap_err(),
                Error::InvalidEventUuid(_)
            ));
        });
        assert_eq!(count, Some(3));
    }

    #[test]
    fn missing_uuid_abort_counts_whole_batch() {
        let ctx = test_utils::test_context();
        let batch = valid_batch(vec![
            Event {
                uuid: String::new(),
                ..valid_event()
            },
            valid_event(),
        ]);

        let count = dropped_count("missing_event_uuid", "validation_abort", || {
            assert!(matches!(
                validate_events(&ctx, batch).unwrap_err(),
                Error::MissingEventUuid
            ));
        });
        assert_eq!(count, Some(2));
    }

    #[test]
    fn invalid_batch_abort_counts_whole_batch() {
        let batch = Batch {
            created_at: "not-a-timestamp".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![valid_event(), valid_event(), valid_event()],
        };

        let count = dropped_count("invalid_batch", "validation_abort", || {
            assert!(matches!(
                validate_batch(&batch).unwrap_err(),
                Error::InvalidBatch(_)
            ));
        });
        assert_eq!(count, Some(3));
    }

    #[test]
    fn empty_batch_abort_counts_zero() {
        // An empty batch loses no events, so the drop counter must not be
        // inflated (0, whether the series is registered or absent).
        let batch = valid_batch(vec![]);

        let count = dropped_count("empty_batch", "validation_abort", || {
            assert!(matches!(
                validate_batch(&batch).unwrap_err(),
                Error::EmptyBatch
            ));
        });
        assert_eq!(count.unwrap_or(0), 0);
    }

    #[test]
    fn validate_events_uuid_with_whitespace_trimmed_successfully() {
        let ctx = test_utils::test_context();
        let inner_uuid = Uuid::new_v4();
        let padded_uuid = format!("  {}  ", inner_uuid);
        let event = deserialized_event(&padded_uuid, "user-42");
        assert_eq!(event.uuid, inner_uuid.to_string());
        let batch = valid_batch(vec![event]);
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].uuid, inner_uuid);
    }

    #[test]
    fn validate_events_malformed_properties() {
        let ctx = test_utils::test_context();
        let bad_event = Event {
            properties: raw_obj("[1,2,3]"),
            ..valid_event()
        };
        let uuid = Uuid::parse_str(&bad_event.uuid).unwrap();
        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![bad_event],
        };
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events.len(), 1);
        let event = &events[0];
        assert_eq!(event.uuid, uuid);
        assert_eq!(event.result, EventResult::Drop);
        assert_eq!(event.details, Some("malformed_event_properties"));
    }

    #[test]
    fn validate_events_invalid_options_drops_single_event() {
        use crate::v1::analytics::types::RawOptions;

        let ctx = test_utils::test_context();
        let mut good = valid_event();
        good.uuid = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d".to_string();

        let mut bad = valid_event();
        bad.uuid = "b1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5e".to_string();
        bad.options = RawOptions(serde_json::json!({"cookieless_mode": [1, 2, 3]}));

        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![good, bad],
        };
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events.len(), 2);

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(events[0].details, None);

        assert_eq!(events[1].result, EventResult::Drop);
        assert_eq!(events[1].details, Some("invalid_options"));
    }

    #[test]
    fn validate_events_invalid_options_does_not_fail_batch() {
        use crate::v1::analytics::types::RawOptions;

        let ctx = test_utils::test_context();
        let mut ev1 = valid_event();
        ev1.uuid = "c1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5f".to_string();
        ev1.options = RawOptions(serde_json::json!({"disable_skew_correction": "not_a_bool"}));

        let mut ev2 = valid_event();
        ev2.uuid = "d1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c60".to_string();
        ev2.options = RawOptions(serde_json::json!({"disable_skew_correction": true}));

        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![ev1, ev2],
        };
        let result = validate_events(&ctx, batch);
        assert!(result.is_ok());
        let events = result.unwrap();
        assert_eq!(events[0].result, EventResult::Drop);
        assert_eq!(events[1].result, EventResult::Ok);
    }

    #[test]
    fn validate_events_coerced_options_used_for_skew_correction() {
        use crate::v1::analytics::types::RawOptions;

        let ctx = test_utils::test_context();
        let mut ev = valid_event();
        ev.uuid = "e1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c61".to_string();
        ev.options = RawOptions(serde_json::json!({"disable_skew_correction": 1}));

        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![ev],
        };
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(events[0].options.disable_skew_correction, Some(true));
    }

    #[test]
    fn validate_events_structural_error_takes_precedence_over_invalid_options() {
        use crate::v1::analytics::types::RawOptions;

        // An event with BOTH a structural error (empty event name) and
        // uncoercible options must drop for the structural reason: options
        // validation only runs after validate_event() passes.
        let ctx = test_utils::test_context();
        let mut ev = valid_event();
        ev.uuid = "f1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c62".to_string();
        ev.event = String::new();
        ev.options = RawOptions(serde_json::json!({"cookieless_mode": [1, 2, 3]}));

        let batch = Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            historical_migration: false,
            capture_internal: None,
            batch: vec![ev],
        };
        let events = validate_events(&ctx, batch).unwrap();
        assert_eq!(events[0].result, EventResult::Drop);
        assert_eq!(events[0].details, Some("missing_event_name"));
    }

    // --- normalize_timestamp ---

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    fn ctx_with_skew(server_received_at: DateTime<Utc>, skew: Duration) -> RequestContext {
        RequestContext {
            api_token: "phc_test".to_string(),
            user_agent: "test/1.0".to_string(),
            content_type: "application/json".to_string(),
            content_encoding: None,
            sdk_info: "test/1.0".to_string(),
            attempt: 1,
            request_id: Uuid::new_v4(),
            client_timestamp: server_received_at + skew,
            client_ip: std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST),
            raw_query: None,
            method: axum::http::Method::POST,
            path: CAPTURE_V1_PATH,
            server_received_at,
            created_at: None,
            capture_internal: false,
            historical_migration: false,
            gateway_signature: None,
        }
    }

    #[test]
    fn normalize_no_skew() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::zero());
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, false, event_ts);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_positive_skew_client_ahead() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, false, event_ts);
        assert_eq!(result, dt("2026-03-19T10:59:50Z"));
    }

    #[test]
    fn normalize_negative_skew_client_behind() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(-10));
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, false, event_ts);
        assert_eq!(result, dt("2026-03-19T11:00:10Z"));
    }

    #[test]
    fn normalize_clamps_far_future() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::zero());
        let event_ts = dt("2026-03-21T12:00:00Z");
        let result = normalize_timestamp(&ctx, false, event_ts);
        assert_eq!(result, now);
    }

    #[test]
    fn normalize_allows_near_future() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::zero());
        let event_ts = dt("2026-03-20T10:00:00Z");
        let result = normalize_timestamp(&ctx, false, event_ts);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_disable_skew_correction_skips_adjustment() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, true, event_ts);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_disable_skew_correction_false_still_adjusts() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, false, event_ts);
        assert_eq!(result, dt("2026-03-19T10:59:50Z"));
    }

    // --- apply_restrictions ---

    async fn restriction_service(
        token: &str,
        restrictions: Vec<Restriction>,
    ) -> EventRestrictionService {
        restriction_service_for_pipeline(Pipeline::Analytics, token, restrictions).await
    }

    async fn restriction_service_for_pipeline(
        pipeline: Pipeline,
        token: &str,
        restrictions: Vec<Restriction>,
    ) -> EventRestrictionService {
        let pipelines = Pipeline::for_capture_mode(crate::config::CaptureMode::Events);
        let service = EventRestrictionService::new(pipelines, StdDuration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(pipeline, token, restrictions);
        service.update(manager).await;
        service
    }

    #[tokio::test]
    async fn restrictions_no_restrictions_passthrough() {
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], StdDuration::from_secs(300));
        service.update(RestrictionManager::new()).await;

        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::AnalyticsMain);
        assert!(!ev.force_disable_person_processing);
    }

    #[tokio::test]
    async fn restrictions_drop_event() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        for ev in &events {
            assert_eq!(ev.result, EventResult::Drop);
            assert_eq!(ev.destination, Destination::Drop);
        }
    }

    #[tokio::test]
    async fn restrictions_skip_malformed_events() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let malformed = malformed_wrapped_event();
        let malformed_did = malformed.event.distinct_id.clone();
        let mut events = vec![malformed, wrapped_event("$pageview", "user-valid")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        // malformed event stays Drop with original destination, not re-evaluated
        let mal = find_by_did(&events, &malformed_did);
        assert_eq!(mal.result, EventResult::Drop);
        assert_eq!(mal.destination, Destination::AnalyticsMain);
        // valid event gets dropped by restriction
        let valid = find_by_did(&events, "user-valid");
        assert_eq!(valid.result, EventResult::Drop);
        assert_eq!(valid.destination, Destination::Drop);
    }

    #[tokio::test]
    async fn restrictions_force_overflow() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::Overflow);
    }

    #[tokio::test]
    async fn restrictions_redirect_to_dlq() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToDlq,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::Dlq);
    }

    #[tokio::test]
    async fn restrictions_redirect_to_custom_topic() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToTopic,
                scope: RestrictionScope::AllEvents,
                args: Some(serde_json::json!({"topic": "custom_analytics"})),
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(
            ev.destination,
            Destination::Custom("custom_analytics".to_string())
        );
    }

    #[tokio::test]
    async fn restrictions_force_disable_person_processing() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::AnalyticsMain);
        assert!(ev.force_disable_person_processing);
    }

    #[tokio::test]
    async fn restrictions_dlq_wins_over_overflow_and_custom() {
        let service = restriction_service(
            "phc_token",
            vec![
                Restriction {
                    restriction_type: RestrictionType::ForceOverflow,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
                Restriction {
                    restriction_type: RestrictionType::RedirectToTopic,
                    scope: RestrictionScope::AllEvents,
                    args: Some(serde_json::json!({"topic": "custom_topic"})),
                },
                Restriction {
                    restriction_type: RestrictionType::RedirectToDlq,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
            ],
        )
        .await;

        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::Dlq);
    }

    #[tokio::test]
    async fn restrictions_unmatched_token_passthrough() {
        let service = restriction_service(
            "phc_other_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::AnalyticsMain);
    }

    // --- destination_for_event_name ---

    #[rstest::rstest]
    #[case("$exception", Destination::ExceptionErrorTracking)]
    #[case("$$heatmap", Destination::HeatmapMain)]
    #[case("$$client_ingestion_warning", Destination::ClientIngestionWarning)]
    #[case("$pageview", Destination::AnalyticsMain)]
    #[case("custom_event", Destination::AnalyticsMain)]
    #[case("$autocapture", Destination::AnalyticsMain)]
    fn destination_for_event_name_mapping(#[case] event_name: &str, #[case] expected: Destination) {
        assert_eq!(destination_for_event_name(event_name), expected);
    }

    // --- restrictions bypass pipeline-less events ---
    // Events whose name maps to DataType::pipeline() == None (heatmaps,
    // ingestion warnings) pass through unrestricted regardless of what
    // restrictions are configured.

    #[rstest::rstest]
    #[case("$$heatmap", Destination::HeatmapMain)]
    #[case("$$client_ingestion_warning", Destination::ClientIngestionWarning)]
    #[tokio::test]
    async fn restrictions_skip_pipeline_less_events(
        #[case] event_name: &str,
        #[case] expected_dest: Destination,
    ) {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut ev = wrapped_event(event_name, "user-1");
        ev.destination = expected_dest.clone();
        let mut events = vec![ev];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(events[0].destination, expected_dest);
    }

    // --- pipeline isolation: analytics drop doesn't cross into errortracking ---

    #[tokio::test]
    async fn restrictions_analytics_drop_does_not_cross_into_errortracking() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$exception", "user-2"),
        ];
        events[1].destination = Destination::ExceptionErrorTracking;
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        // Analytics event gets dropped by analytics-pipeline restriction
        assert_eq!(events[0].result, EventResult::Drop);
        assert_eq!(events[0].destination, Destination::Drop);
        // Exception event is untouched — it's on the ErrorTracking pipeline,
        // which has no restrictions configured here.
        assert_eq!(events[1].result, EventResult::Ok);
        assert_eq!(events[1].destination, Destination::ExceptionErrorTracking);
    }

    // --- errortracking pipeline restrictions ---
    // Mirrors v0's test_process_events_errortracking_drop_only_affects_exceptions
    // and _analytics_drop_does_not_cross_into_errortracking.

    #[tokio::test]
    async fn restrictions_errortracking_drop_only_affects_exceptions() {
        let service = restriction_service_for_pipeline(
            Pipeline::ErrorTracking,
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![
            wrapped_event("$exception", "user-1"),
            wrapped_event("$pageview", "user-2"),
        ];
        events[0].destination = Destination::ExceptionErrorTracking;
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(
            events[0].result,
            EventResult::Drop,
            "exception should be dropped"
        );
        assert_eq!(events[0].destination, Destination::Drop);
        assert_eq!(events[1].result, EventResult::Ok, "pageview should be kept");
        assert_eq!(events[1].destination, Destination::AnalyticsMain);
    }

    #[tokio::test]
    async fn restrictions_exception_force_overflow_ignored() {
        let service = restriction_service_for_pipeline(
            Pipeline::ErrorTracking,
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$exception", "user-1")];
        events[0].destination = Destination::ExceptionErrorTracking;
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(
            events[0].destination,
            Destination::ExceptionErrorTracking,
            "ForceOverflow is gated to AnalyticsMain; exception stays on its own lane"
        );
    }

    #[tokio::test]
    async fn restrictions_exception_skip_person_processing() {
        let service = restriction_service_for_pipeline(
            Pipeline::ErrorTracking,
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$exception", "user-1")];
        events[0].destination = Destination::ExceptionErrorTracking;
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(events[0].destination, Destination::ExceptionErrorTracking);
        assert!(events[0].force_disable_person_processing);
    }

    #[tokio::test]
    async fn restrictions_exception_redirect_to_dlq() {
        let service = restriction_service_for_pipeline(
            Pipeline::ErrorTracking,
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToDlq,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$exception", "user-1")];
        events[0].destination = Destination::ExceptionErrorTracking;
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(events[0].destination, Destination::Dlq);
    }

    #[tokio::test]
    async fn restrictions_exception_redirect_to_custom_topic() {
        let service = restriction_service_for_pipeline(
            Pipeline::ErrorTracking,
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToTopic,
                scope: RestrictionScope::AllEvents,
                args: Some(serde_json::json!({"topic": "custom_exceptions"})),
            }],
        )
        .await;

        let mut events = vec![wrapped_event("$exception", "user-1")];
        events[0].destination = Destination::ExceptionErrorTracking;
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(
            events[0].destination,
            Destination::Custom("custom_exceptions".to_string())
        );
    }

    #[tokio::test]
    async fn restrictions_exception_dlq_wins_over_custom_topic() {
        let service = restriction_service_for_pipeline(
            Pipeline::ErrorTracking,
            "phc_token",
            vec![
                Restriction {
                    restriction_type: RestrictionType::RedirectToTopic,
                    scope: RestrictionScope::AllEvents,
                    args: Some(serde_json::json!({"topic": "custom_exceptions"})),
                },
                Restriction {
                    restriction_type: RestrictionType::RedirectToDlq,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
            ],
        )
        .await;

        let mut events = vec![wrapped_event("$exception", "user-1")];
        events[0].destination = Destination::ExceptionErrorTracking;
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(events[0].destination, Destination::Dlq);
    }

    // --- apply_token_distinct_id_limits ---

    use async_trait::async_trait;
    use limiters::global_rate_limiter::{
        EvalResult, GlobalRateLimitResponse, GlobalRateLimiter as CommonGlobalRateLimiterTrait,
    };
    use std::collections::HashSet;

    struct MockLimiter {
        limited_keys: HashSet<String>,
    }

    impl MockLimiter {
        fn new(limited_keys: HashSet<String>) -> Self {
            Self { limited_keys }
        }
    }

    #[async_trait]
    impl CommonGlobalRateLimiterTrait for MockLimiter {
        async fn check_limit(
            &self,
            key: &str,
            _count: u64,
            _timestamp: Option<DateTime<Utc>>,
        ) -> EvalResult {
            if self.limited_keys.contains(key) {
                EvalResult::Limited(GlobalRateLimitResponse {
                    key: key.to_string(),
                    current_count: 100.0,
                    threshold: 10,
                    window_interval: StdDuration::from_secs(60),
                    sync_interval: StdDuration::from_secs(15),
                    is_custom_limited: false,
                })
            } else {
                EvalResult::Allowed
            }
        }

        async fn check_custom_limit(
            &self,
            _key: &str,
            _count: u64,
            _timestamp: Option<DateTime<Utc>>,
        ) -> EvalResult {
            EvalResult::NotApplicable
        }

        fn is_custom_key(&self, _key: &str) -> bool {
            false
        }

        fn shutdown(&mut self) {}
    }

    fn mock_limiter(limited_keys: Vec<&str>) -> GlobalRateLimiter {
        let keys: HashSet<String> = limited_keys.into_iter().map(String::from).collect();
        GlobalRateLimiter::new_with(MockLimiter::new(keys))
    }

    fn td_context() -> RequestContext {
        let mut ctx = test_utils::test_context();
        ctx.api_token = "phc_tok".to_string();
        ctx
    }

    #[tokio::test]
    async fn td_limits_under_limit_all_pass() {
        let limiter = mock_limiter(vec![]);
        let ctx = td_context();
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ];

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        for ev in &events {
            assert_eq!(ev.result, EventResult::Ok);
            assert_eq!(ev.destination, Destination::AnalyticsMain);
            assert!(ev.details.is_none());
        }
    }

    #[tokio::test]
    async fn td_limits_one_distinct_id_over_limit() {
        let limiter = mock_limiter(vec!["phc_tok:user-2"]);
        let ctx = td_context();
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ];

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        let ok_ev = find_by_did(&events, "user-1");
        assert_eq!(ok_ev.result, EventResult::Ok);
        assert_eq!(ok_ev.destination, Destination::AnalyticsMain);
        assert!(ok_ev.details.is_none());
        let limited_ev = find_by_did(&events, "user-2");
        assert_eq!(limited_ev.result, EventResult::Warning);
        // AnalyticsMain event over the limit is rerouted to overflow.
        assert_eq!(limited_ev.destination, Destination::Overflow);
        assert!(limited_ev.force_disable_person_processing);
        assert_eq!(limited_ev.details, Some(DETAIL_PERSON_PROCESSING_DISABLED));
    }

    #[tokio::test]
    async fn td_limits_skips_already_invalid_events() {
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let ctx = td_context();
        let mut events = vec![malformed_wrapped_event()];

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        let ev = &events[0];
        assert_eq!(ev.result, EventResult::Drop);
        assert_eq!(ev.destination, Destination::default());
        assert!(ev.details.is_some());
    }

    #[tokio::test]
    async fn td_limits_multiple_events_same_distinct_id_all_limited() {
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let ctx = td_context();
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-1"),
            wrapped_event("$click", "user-1"),
        ];

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        for ev in &events {
            assert_eq!(ev.result, EventResult::Warning, "should be Warning");
            assert_eq!(
                ev.destination,
                Destination::Overflow,
                "should be rerouted to overflow"
            );
            assert!(
                ev.force_disable_person_processing,
                "should skip person processing"
            );
            assert_eq!(
                ev.details,
                Some(DETAIL_PERSON_PROCESSING_DISABLED),
                "should have details"
            );
        }
    }

    #[tokio::test]
    async fn td_limits_mixed_valid_and_pre_dropped_events() {
        let limiter = mock_limiter(vec!["phc_tok:user-2"]);
        let ctx = td_context();
        let pre_drop = wrapped_event("$pageview", "user-1");
        let pre_drop_uuid = pre_drop.uuid;
        let mut events = vec![pre_drop, wrapped_event("$identify", "user-2")];
        // Simulate event already dropped by restrictions
        let pd = events.iter_mut().find(|e| e.uuid == pre_drop_uuid).unwrap();
        pd.result = EventResult::Drop;
        pd.destination = Destination::Drop;

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        // Pre-dropped event untouched
        let dropped = find_by_did(&events, "user-1");
        assert_eq!(dropped.result, EventResult::Drop);
        assert_eq!(dropped.destination, Destination::Drop);
        // Other event rate-limited (person processing disabled, rerouted to overflow)
        let limited = find_by_did(&events, "user-2");
        assert_eq!(limited.result, EventResult::Warning);
        assert_eq!(limited.destination, Destination::Overflow);
        assert!(limited.force_disable_person_processing);
        assert_eq!(limited.details, Some(DETAIL_PERSON_PROCESSING_DISABLED));
    }

    #[tokio::test]
    async fn td_limits_skips_events_already_flagged_force_disable_pp() {
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let ctx = td_context();
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ];
        // Simulate illegal distinct_id flagging from validate_events
        events[0].force_disable_person_processing = true;
        events[0].details = Some(DETAIL_PERSON_PROCESSING_DISABLED);

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        // Already-flagged event not re-evaluated: result stays Ok, details unchanged
        let flagged = find_by_did(&events, "user-1");
        assert_eq!(flagged.result, EventResult::Ok);
        assert!(flagged.force_disable_person_processing);
        assert_eq!(flagged.details, Some(DETAIL_PERSON_PROCESSING_DISABLED));
        // Unflagged event passes (not in limiter's limited keys)
        let normal = find_by_did(&events, "user-2");
        assert_eq!(normal.result, EventResult::Ok);
        assert!(!normal.force_disable_person_processing);
        assert!(normal.details.is_none());
    }

    #[tokio::test]
    async fn td_limits_historical_event_not_rerouted_to_overflow() {
        // Invariant: AnalyticsHistorical must never be rerouted to Overflow.
        // A globally rate-limited historical event still gets person processing
        // disabled, but stays on the historical lane (matches the legacy sink,
        // where the AnalyticsHistorical arm never overflows).
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let ctx = td_context();
        let mut events =
            vec![wrapped_event("$pageview", "user-1")
                .with_destination(Destination::AnalyticsHistorical)];

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Warning);
        assert_eq!(
            ev.destination,
            Destination::AnalyticsHistorical,
            "historical events must not be rerouted to overflow"
        );
        assert!(ev.force_disable_person_processing);
        assert_eq!(ev.details, Some(DETAIL_PERSON_PROCESSING_DISABLED));
    }

    // --- apply_historical_rerouting ---

    #[test]
    fn historical_batch_flag_reroutes_all_events() {
        let cfg = router::HistoricalConfig::new(false, 1);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        for ev in &events {
            assert_eq!(ev.destination, Destination::AnalyticsHistorical);
        }
    }

    #[test]
    fn historical_timestamp_reroutes_old_event() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_utils::test_context();
        let old_ts = Utc::now() - Duration::days(60);
        let mut events = vec![wrapped_event_at(old_ts)];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = &events[0];
        assert_eq!(ev.destination, Destination::AnalyticsHistorical);
    }

    #[test]
    fn historical_timestamp_keeps_recent_event() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_utils::test_context();
        let recent_ts = Utc::now() - Duration::hours(1);
        let mut events = vec![wrapped_event_at(recent_ts)];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = &events[0];
        assert_eq!(ev.destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_rerouting_disabled_no_change() {
        let cfg = router::HistoricalConfig::new(false, 30);
        let ctx = test_utils::test_context();
        let old_ts = Utc::now() - Duration::days(60);
        let mut events = vec![wrapped_event_at(old_ts)];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = &events[0];
        assert_eq!(ev.destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_skips_non_analytics_main() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let ev = wrapped_event("$pageview", "user-1");
        let ev_uuid = ev.uuid;
        let mut events = vec![ev];
        events
            .iter_mut()
            .find(|e| e.uuid == ev_uuid)
            .unwrap()
            .destination = Destination::Overflow;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(
            events
                .iter()
                .find(|e| e.uuid == ev_uuid)
                .unwrap()
                .destination,
            Destination::Overflow
        );
    }

    #[test]
    fn historical_skips_dropped_events() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let ev = wrapped_event("$pageview", "user-1");
        let ev_uuid = ev.uuid;
        let mut events = vec![ev];
        let e = events.iter_mut().find(|e| e.uuid == ev_uuid).unwrap();
        e.result = EventResult::Drop;
        e.destination = Destination::Drop;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(
            events
                .iter()
                .find(|e| e.uuid == ev_uuid)
                .unwrap()
                .destination,
            Destination::Drop
        );
    }

    #[test]
    fn historical_skips_malformed_events() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let mut events = vec![malformed_wrapped_event()];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = &events[0];
        assert_eq!(ev.destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_mixed_batch_flag_and_already_redirected() {
        let cfg = router::HistoricalConfig::new(false, 1);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let dlq_ev = wrapped_event("$identify", "user-2");
        let dlq_uuid = dlq_ev.uuid;
        let mut events = vec![wrapped_event("$pageview", "user-1"), dlq_ev];
        events
            .iter_mut()
            .find(|e| e.uuid == dlq_uuid)
            .unwrap()
            .destination = Destination::Dlq;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let main_ev = find_by_did(&events, "user-1");
        assert_eq!(main_ev.destination, Destination::AnalyticsHistorical);
        // DLQ event untouched
        assert_eq!(
            events
                .iter()
                .find(|e| e.uuid == dlq_uuid)
                .unwrap()
                .destination,
            Destination::Dlq
        );
    }

    // --- ordering preservation regressions ---
    // Pin in-batch order through each stage and end-to-end (regressions
    // against the old HashMap pipeline that silently shuffled events).

    fn distinct_id_sequence(events: &[WrappedEvent]) -> Vec<&str> {
        events
            .iter()
            .map(|e| e.event.distinct_id.as_str())
            .collect()
    }

    #[test]
    fn validate_events_preserves_input_order() {
        let ctx = test_utils::test_context();
        // Mix valid + invalid to hit both match branches.
        let perf = Event {
            event: "$performance_event".to_string(),
            distinct_id: "user-pos-1".to_string(),
            ..valid_event()
        };
        let normal_a = Event {
            distinct_id: "user-pos-0".to_string(),
            ..valid_event()
        };
        let normal_b = Event {
            distinct_id: "user-pos-2".to_string(),
            ..valid_event()
        };
        let normal_c = Event {
            distinct_id: "user-pos-3".to_string(),
            ..valid_event()
        };
        let batch = valid_batch(vec![normal_a, perf, normal_b, normal_c]);

        let events = validate_events(&ctx, batch).unwrap();

        assert_eq!(
            distinct_id_sequence(&events),
            vec!["user-pos-0", "user-pos-1", "user-pos-2", "user-pos-3"],
        );
    }

    #[test]
    fn validate_events_duplicate_uuid_via_realistic_pair() {
        // Two distinct events (name / distinct_id / props) colliding on uuid.
        let ctx = test_utils::test_context();
        let (first, second) = test_utils::realistic_dup_uuid_pair();
        let batch = valid_batch(vec![first, second]);
        let err = validate_events(&ctx, batch).unwrap_err();
        assert!(matches!(err, Error::DuplicateEventUuid(_)));
    }

    #[tokio::test]
    async fn apply_historical_rerouting_preserves_order() {
        // Interleave old + recent so the timestamp branch flips some events.
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_utils::test_context();
        let now = Utc::now();
        let mut e0 = wrapped_event_at(now - Duration::days(60));
        e0.event.distinct_id = "user-pos-0".to_string();
        let mut e1 = wrapped_event_at(now - Duration::hours(1));
        e1.event.distinct_id = "user-pos-1".to_string();
        let mut e2 = wrapped_event_at(now - Duration::days(90));
        e2.event.distinct_id = "user-pos-2".to_string();
        let mut e3 = wrapped_event_at(now - Duration::minutes(5));
        e3.event.distinct_id = "user-pos-3".to_string();
        let mut events = vec![e0, e1, e2, e3];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(
            distinct_id_sequence(&events),
            vec!["user-pos-0", "user-pos-1", "user-pos-2", "user-pos-3"],
        );
        assert_eq!(events[0].destination, Destination::AnalyticsHistorical);
        assert_eq!(events[1].destination, Destination::AnalyticsMain);
        assert_eq!(events[2].destination, Destination::AnalyticsHistorical);
        assert_eq!(events[3].destination, Destination::AnalyticsMain);
    }

    #[tokio::test]
    async fn apply_restrictions_preserves_order() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![
            wrapped_event("$pageview", "user-pos-0"),
            wrapped_event("$identify", "user-pos-1"),
            wrapped_event("$click", "user-pos-2"),
        ];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(
            distinct_id_sequence(&events),
            vec!["user-pos-0", "user-pos-1", "user-pos-2"],
        );
        for ev in &events {
            assert_eq!(ev.result, EventResult::Drop);
            assert_eq!(ev.destination, Destination::Drop);
        }
    }

    #[tokio::test]
    async fn apply_token_distinct_id_limits_preserves_order_with_interleaved_limits() {
        // Limit slots 1 and 3 only — verifies interleaved limited/non-limited
        // entries don't shuffle.
        let limiter = mock_limiter(vec!["phc_tok:user-pos-1", "phc_tok:user-pos-3"]);
        let ctx = td_context();
        let mut events = vec![
            wrapped_event("$pageview", "user-pos-0"),
            wrapped_event("$pageview", "user-pos-1"),
            wrapped_event("$pageview", "user-pos-2"),
            wrapped_event("$pageview", "user-pos-3"),
            wrapped_event("$pageview", "user-pos-4"),
        ];

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        assert_eq!(
            distinct_id_sequence(&events),
            vec![
                "user-pos-0",
                "user-pos-1",
                "user-pos-2",
                "user-pos-3",
                "user-pos-4",
            ],
        );
        assert!(!events[0].force_disable_person_processing);
        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        assert!(events[1].force_disable_person_processing);
        assert_eq!(events[1].result, EventResult::Warning);
        assert_eq!(events[1].destination, Destination::Overflow);
        assert_eq!(events[1].details, Some(DETAIL_PERSON_PROCESSING_DISABLED));
        assert!(!events[2].force_disable_person_processing);
        assert_eq!(events[2].destination, Destination::AnalyticsMain);
        assert!(events[3].force_disable_person_processing);
        assert_eq!(events[3].result, EventResult::Warning);
        assert_eq!(events[3].destination, Destination::Overflow);
        assert_eq!(events[3].details, Some(DETAIL_PERSON_PROCESSING_DISABLED));
        assert!(!events[4].force_disable_person_processing);
        assert_eq!(events[4].destination, Destination::AnalyticsMain);
    }

    #[tokio::test]
    async fn pipeline_preserves_order_through_all_stages() {
        // End-to-end pin across every &mut [WrappedEvent] stage.
        // apply_quota_limits is covered in v1::quota_limiter_shim tests.
        let mut events = test_utils::realistic_ordered_mixed_batch();
        let expected = [
            "user-pos-0",
            "user-pos-1",
            "user-pos-2",
            "user-pos-3",
            "user-pos-4",
            "user-pos-5",
        ];

        // Stage 1: historical rerouting (batch flag on).
        let cfg = router::HistoricalConfig::new(false, 1);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        apply_historical_rerouting(&cfg, &ctx, &mut events);
        assert_eq!(
            distinct_id_sequence(&events),
            expected,
            "order changed after apply_historical_rerouting",
        );

        // Stage 2: restrictions (no rules → passthrough, still iterates).
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], StdDuration::from_secs(300));
        service.update(RestrictionManager::new()).await;
        let now_ts = Utc::now().timestamp();
        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;
        assert_eq!(
            distinct_id_sequence(&events),
            expected,
            "order changed after apply_restrictions",
        );

        // Stage 3: token+distinct_id limits — limit one Ok mid-batch.
        let mut tdctx = test_utils::test_context();
        tdctx.api_token = "phc_tok".to_string();
        let limiter = mock_limiter(vec!["phc_tok:user-pos-2"]);
        apply_token_distinct_id_limits(&limiter, &tdctx, &mut events).await;
        assert_eq!(
            distinct_id_sequence(&events),
            expected,
            "order changed after apply_token_distinct_id_limits",
        );
    }

    // --- apply_overflow_stamping ---

    fn overflow_limiter(per_second: u32, burst: u32, force_keys: Option<&str>) -> OverflowLimiter {
        use std::num::NonZeroU32;
        OverflowLimiter::new(
            NonZeroU32::new(per_second).unwrap(),
            NonZeroU32::new(burst).unwrap(),
            force_keys.map(String::from),
            false,
        )
    }

    fn overflow_limiter_preserving(per_second: u32, burst: u32) -> OverflowLimiter {
        use std::num::NonZeroU32;
        OverflowLimiter::new(
            NonZeroU32::new(per_second).unwrap(),
            NonZeroU32::new(burst).unwrap(),
            None,
            true,
        )
    }

    #[test]
    fn overflow_not_limited() {
        let ctx = test_utils::test_context();
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let limiter = overflow_limiter(100, 100, None);

        apply_overflow_stamping(&limiter, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        assert!(!events[0].force_disable_person_processing);
    }

    #[test]
    fn overflow_force_limited_by_full_key() {
        let mut ctx = test_utils::test_context();
        ctx.api_token = "phc_tok".to_string();
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let limiter = overflow_limiter(100, 100, Some("phc_tok:user-1"));

        apply_overflow_stamping(&limiter, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::Overflow);
        assert!(events[0].force_disable_person_processing);
    }

    #[test]
    fn overflow_force_limited_by_token_only() {
        let mut ctx = test_utils::test_context();
        ctx.api_token = "phc_tok".to_string();
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let limiter = overflow_limiter(100, 100, Some("phc_tok"));

        apply_overflow_stamping(&limiter, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::Overflow);
        assert!(events[0].force_disable_person_processing);
    }

    #[test]
    fn overflow_rate_limited_disables_person_processing() {
        let mut ctx = test_utils::test_context();
        ctx.api_token = "phc_tok".to_string();
        // burst=1 means only 1 event allowed, the second will be limited
        let limiter = overflow_limiter(1, 1, None);
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$pageview", "user-1"),
        ];

        apply_overflow_stamping(&limiter, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        assert!(!events[0].force_disable_person_processing);
        assert_eq!(events[1].destination, Destination::Overflow);
        assert!(events[1].force_disable_person_processing);
    }

    #[test]
    fn overflow_rate_limited_preserves_locality_when_configured() {
        let mut ctx = test_utils::test_context();
        ctx.api_token = "phc_tok".to_string();
        let limiter = overflow_limiter_preserving(1, 1);
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$pageview", "user-1"),
        ];

        apply_overflow_stamping(&limiter, &ctx, &mut events);

        assert_eq!(events[1].destination, Destination::Overflow);
        assert!(
            !events[1].force_disable_person_processing,
            "preserve_locality=true means person processing stays enabled"
        );
    }

    #[test]
    fn overflow_skips_non_analytics_main() {
        let ctx = test_utils::test_context();
        let limiter = overflow_limiter(100, 100, Some("phc_test_token:user-1"));
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        events[0].destination = Destination::AnalyticsHistorical;

        apply_overflow_stamping(&limiter, &ctx, &mut events);

        assert_eq!(
            events[0].destination,
            Destination::AnalyticsHistorical,
            "non-AnalyticsMain events are not overflow-checked"
        );
    }

    #[test]
    fn overflow_skips_dropped_events() {
        let ctx = test_utils::test_context();
        let limiter = overflow_limiter(100, 100, Some("phc_test_token:user-1"));
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        events[0].result = EventResult::Drop;

        apply_overflow_stamping(&limiter, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsMain);
    }
    // =========================================================================
    // apply_gateway_provenance tests — the verify→billing wiring
    // =========================================================================

    use crate::v1::gateway_provenance::{sign_for_test, GatewaySignature};
    use crate::v1::test_utils::TestStateBuilder;

    const GW_SECRET: &str = "test-signing-secret";

    /// Analytics context with `now` as the capture time, an api_token, and an
    /// optional gateway signature — the inputs `apply_gateway_provenance` reads.
    fn gateway_context(token: &str, now: DateTime<Utc>, sig: Option<GatewaySignature>) -> Context {
        let mut ctx = test_utils::test_analytics_context();
        ctx.req.api_token = token.to_string();
        ctx.req.server_received_at = now;
        ctx.req.gateway_signature = sig;
        ctx
    }

    fn ai_event(distinct_id: &str, properties: &str) -> WrappedEvent {
        wrapped_event("$ai_generation", distinct_id).with_properties(properties)
    }

    #[tokio::test]
    async fn gateway_provenance_leaves_non_ai_events_untouched() {
        let token = "phc_test_token";
        let now = Utc::now();
        let state = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build()
            .state;
        let signed_at = now.to_rfc3339();
        let sig = GatewaySignature {
            signature: sign_for_test(GW_SECRET.as_bytes(), token, "user-1", "req-1", &signed_at),
            signed_at,
            request_id: "req-1".to_string(),
        };
        let ctx = gateway_context(token, now, Some(sig));

        // A valid signature is present, but a non-$ai_ event must be skipped: its
        // client `$ai_gateway*` props are neither stamped nor stripped.
        let mut events =
            vec![wrapped_event("$pageview", "user-1").with_properties(r#"{"$ai_gateway": true}"#)];
        apply_gateway_provenance(&state, &ctx, &mut events);

        assert!(!events[0].is_gateway_verified);
        assert!(events[0].event.properties.get().contains("$ai_gateway"));
    }

    #[tokio::test]
    async fn gateway_provenance_verifies_and_stamps_a_valid_signature() {
        let token = "phc_test_token";
        let distinct_id = "user-1";
        let now = Utc::now();
        let state = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build()
            .state;
        let signed_at = now.to_rfc3339();
        let sig = GatewaySignature {
            signature: sign_for_test(
                GW_SECRET.as_bytes(),
                token,
                distinct_id,
                "req-1",
                &signed_at,
            ),
            signed_at,
            request_id: "req-1".to_string(),
        };
        let ctx = gateway_context(token, now, Some(sig));

        // Client supplies its own request_id — the signed one must win.
        let mut events = vec![ai_event(
            distinct_id,
            r#"{"$ai_model": "claude", "$ai_gateway_request_id": "client-fake"}"#,
        )];
        apply_gateway_provenance(&state, &ctx, &mut events);

        assert!(events[0].is_gateway_verified);
        let props: serde_json::Value =
            serde_json::from_str(events[0].event.properties.get()).unwrap();
        assert_eq!(props["$ai_gateway_verified"], serde_json::Value::Bool(true));
        assert_eq!(
            props["$ai_gateway_request_id"],
            serde_json::Value::String("req-1".to_string()),
            "the signed request_id must overwrite the client value"
        );
    }

    #[tokio::test]
    async fn gateway_provenance_strips_forged_props_and_does_not_verify() {
        let token = "phc_test_token";
        let distinct_id = "user-1";
        let now = Utc::now();
        let state = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build()
            .state;
        // No signature on the request: a client-set `$ai_gateway_verified` must be
        // stripped and the event must not be marked verified.
        let ctx = gateway_context(token, now, None);

        let mut events = vec![ai_event(
            distinct_id,
            r#"{"$ai_gateway_verified": true, "$ai_gateway": "forged", "$ai_model": "claude"}"#,
        )];
        apply_gateway_provenance(&state, &ctx, &mut events);

        assert!(!events[0].is_gateway_verified);
        let raw = events[0].event.properties.get();
        assert!(
            !raw.contains("$ai_gateway"),
            "gateway props must be stripped"
        );
        assert!(raw.contains("$ai_model"), "non-gateway props must survive");
    }

    /// The signature binds `distinct_id`, so in a batch where it's signed for only
    /// one event, only that event is verified — the other's forged marker is
    /// stripped, even sharing one request-level signature.
    #[tokio::test]
    async fn gateway_provenance_verifies_only_the_signed_distinct_id_in_a_batch() {
        let token = "phc_test_token";
        let signed_id = "user-signed";
        let now = Utc::now();
        let state = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build()
            .state;
        let signed_at = now.to_rfc3339();
        let sig = GatewaySignature {
            signature: sign_for_test(GW_SECRET.as_bytes(), token, signed_id, "req-1", &signed_at),
            signed_at,
            request_id: "req-1".to_string(),
        };
        let ctx = gateway_context(token, now, Some(sig));

        let mut events = vec![
            ai_event(signed_id, r#"{"$ai_model": "claude"}"#),
            // Different distinct_id, riding the same request signature, with a
            // forged marker — must not verify against a sig bound to `signed_id`.
            ai_event(
                "user-other",
                r#"{"$ai_gateway_verified": true, "$ai_model": "gpt"}"#,
            ),
        ];
        apply_gateway_provenance(&state, &ctx, &mut events);

        assert!(events[0].is_gateway_verified, "signed distinct_id verifies");
        assert!(
            !events[1].is_gateway_verified,
            "unsigned distinct_id must not verify"
        );
        assert!(
            !events[1].event.properties.get().contains("$ai_gateway"),
            "the other event's forged marker must be stripped"
        );
    }

    /// Fail closed: an unverified event whose props carry a forged marker but can't
    /// be parsed to strip it (RawValue accepts an out-of-range number serde rejects)
    /// is dropped, so the marker can't reach billing via ClickHouse's lenient reader.
    #[tokio::test]
    async fn gateway_provenance_drops_event_with_unparseable_forged_props() {
        let token = "phc_test_token";
        let now = Utc::now();
        let state = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build()
            .state;
        let ctx = gateway_context(token, now, None);

        let mut events = vec![ai_event(
            "user-1",
            r#"{"$ai_gateway_verified": true, "x": 1e500}"#,
        )];
        apply_gateway_provenance(&state, &ctx, &mut events);

        assert_eq!(events[0].result, EventResult::Drop);
        assert_eq!(events[0].details, Some("gateway_props_unparseable"));
        assert!(!events[0].is_gateway_verified);
    }

    /// Fail closed on the verified path too: a valid signature can't excuse props we
    /// can't parse to stamp, since a forged marker hidden in them would survive.
    #[tokio::test]
    async fn gateway_provenance_drops_verified_event_with_unparseable_props() {
        let token = "phc_test_token";
        let distinct_id = "user-1";
        let now = Utc::now();
        let state = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build()
            .state;
        let signed_at = now.to_rfc3339();
        let sig = GatewaySignature {
            signature: sign_for_test(
                GW_SECRET.as_bytes(),
                token,
                distinct_id,
                "req-1",
                &signed_at,
            ),
            signed_at,
            request_id: "req-1".to_string(),
        };
        let ctx = gateway_context(token, now, Some(sig));

        let mut events = vec![ai_event(distinct_id, r#"{"$ai_model": "x", "y": 1e500}"#)];
        apply_gateway_provenance(&state, &ctx, &mut events);

        assert_eq!(events[0].result, EventResult::Drop);
        assert_eq!(events[0].details, Some("gateway_props_unparseable"));
        assert!(!events[0].is_gateway_verified);
    }

    /// process_batch wiring: a valid signature is verified ahead of the limiter
    /// and the trusted marker survives serialization into the published payload.
    #[tokio::test]
    async fn process_batch_stamps_verified_gateway_event_into_published_payload() {
        let token = "phc_test_token";
        let distinct_id = "user-1";
        let now = Utc::now();
        let ts = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build();
        let signed_at = now.to_rfc3339();
        let sig = GatewaySignature {
            signature: sign_for_test(
                GW_SECRET.as_bytes(),
                token,
                distinct_id,
                "req-1",
                &signed_at,
            ),
            signed_at,
            request_id: "req-1".to_string(),
        };
        let mut ctx = gateway_context(token, now, Some(sig));
        let batch = valid_batch(vec![Event {
            event: "$ai_generation".to_string(),
            distinct_id: distinct_id.to_string(),
            properties: test_utils::raw_obj(r#"{"$ai_model":"claude"}"#),
            ..valid_event()
        }]);

        process_batch(&ts.state, &mut ctx, batch).await.unwrap();

        ts.mock_producer.with_records(|records| {
            assert_eq!(records.len(), 1, "the verified event must be published");
            assert!(
                records[0].payload.contains("$ai_gateway_verified"),
                "verified marker must reach the published payload"
            );
        });
    }

    /// process_batch wiring: a client-set marker with no signature is stripped
    /// before the event is serialized, so it never reaches the meter as trusted.
    #[tokio::test]
    async fn process_batch_strips_forged_gateway_marker_from_published_payload() {
        let token = "phc_test_token";
        let now = Utc::now();
        let ts = TestStateBuilder::new()
            .with_ai_gateway_signing_secret(GW_SECRET)
            .build();
        let mut ctx = gateway_context(token, now, None);
        let batch = valid_batch(vec![Event {
            event: "$ai_generation".to_string(),
            distinct_id: "user-1".to_string(),
            properties: test_utils::raw_obj(
                r#"{"$ai_gateway_verified":true,"$ai_model":"claude"}"#,
            ),
            ..valid_event()
        }]);

        process_batch(&ts.state, &mut ctx, batch).await.unwrap();

        ts.mock_producer.with_records(|records| {
            assert_eq!(
                records.len(),
                1,
                "the event is still published, just untrusted"
            );
            assert!(
                !records[0].payload.contains("$ai_gateway"),
                "forged marker must be stripped before publish"
            );
            assert!(records[0].payload.contains("$ai_model"));
        });
    }

    // =========================================================================
    // merge_sink_results tests
    // =========================================================================

    use crate::v1::test_utils::MockSinkResult;

    fn mock_result(uuid: Uuid, outcome: &str, cause: &'static str) -> Box<dyn SinkResult> {
        match outcome {
            "success" => MockSinkResult::success(uuid),
            "retriable" => MockSinkResult::retriable(uuid, cause),
            "timeout" => MockSinkResult::timeout(uuid),
            "fatal" => MockSinkResult::fatal(uuid, cause),
            "fatal_no_cause" => MockSinkResult::fatal_no_cause(uuid),
            _ => panic!("unknown outcome: {outcome}"),
        }
    }

    #[rstest::rstest]
    #[case::success("success", "", EventResult::Ok, None)]
    #[case::retriable("retriable", "queue_full", EventResult::Retry, Some("not_persisted"))]
    #[case::timeout("timeout", "", EventResult::Retry, Some("not_persisted"))]
    #[case::fatal_serialization(
        "fatal",
        "serialization_failed",
        EventResult::Drop,
        Some("serialization_failed")
    )]
    #[case::fatal_event_too_big("fatal", "event_too_big", EventResult::Drop, Some("event_too_big"))]
    #[case::fatal_generic("fatal", "rdkafka_other", EventResult::Drop, Some("rejected"))]
    #[case::fatal_no_cause("fatal_no_cause", "", EventResult::Drop, Some("rejected"))]
    fn merge_single_outcome(
        #[case] outcome: &str,
        #[case] cause: &'static str,
        #[case] expected_result: EventResult,
        #[case] expected_details: Option<&'static str>,
    ) {
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        let results: Vec<Box<dyn SinkResult>> = vec![mock_result(events[0].uuid, outcome, cause)];

        merge_sink_results(&mut events, &results);

        assert_eq!(
            events[0].result, expected_result,
            "result for {outcome}:{cause}"
        );
        assert_eq!(
            events[0].details, expected_details,
            "details for {outcome}:{cause}"
        );
    }

    #[test]
    fn merge_preserves_warning_result_on_success() {
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        events[0].result = EventResult::Warning;
        events[0].details = Some("person_processing_disabled");

        let results: Vec<Box<dyn SinkResult>> = vec![MockSinkResult::success(events[0].uuid)];
        merge_sink_results(&mut events, &results);

        assert_eq!(events[0].result, EventResult::Warning);
        assert_eq!(events[0].details, Some("person_processing_disabled"));
    }

    #[test]
    fn merge_skips_events_not_published() {
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$pageview", "user-2"),
        ];
        events[0].result = EventResult::Drop;
        events[0].details = Some("billing_limit_exceeded");
        events[0].destination = Destination::Drop;

        // Only one sink result (for the published event)
        let results: Vec<Box<dyn SinkResult>> = vec![MockSinkResult::success(events[1].uuid)];

        merge_sink_results(&mut events, &results);

        // Dropped event unchanged
        assert_eq!(events[0].result, EventResult::Drop);
        assert_eq!(events[0].details, Some("billing_limit_exceeded"));
        // Published event left alone
        assert_eq!(events[1].result, EventResult::Ok);
        assert!(events[1].details.is_none());
    }

    #[test]
    fn merge_mixed_outcomes() {
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
            wrapped_event("custom", "user-3"),
        ];

        let results: Vec<Box<dyn SinkResult>> = vec![
            MockSinkResult::success(events[0].uuid),
            MockSinkResult::retriable(events[1].uuid, "queue_full"),
            MockSinkResult::fatal(events[2].uuid, "serialization_error"),
        ];

        merge_sink_results(&mut events, &results);

        assert_eq!(events[0].result, EventResult::Ok);
        assert!(events[0].details.is_none());
        assert_eq!(events[1].result, EventResult::Retry);
        assert_eq!(events[1].details, Some("not_persisted"));
        assert_eq!(events[2].result, EventResult::Drop);
        assert_eq!(events[2].details, Some("rejected"));
    }

    #[test]
    fn merge_uuid_correlation_no_crosstalk() {
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$pageview", "user-2"),
        ];

        // Deliberately swap: result for event[1] is retriable, event[0] is success
        let results: Vec<Box<dyn SinkResult>> = vec![
            MockSinkResult::retriable(events[1].uuid, "queue_full"),
            MockSinkResult::success(events[0].uuid),
        ];

        merge_sink_results(&mut events, &results);

        assert_eq!(events[0].result, EventResult::Ok);
        assert!(events[0].details.is_none());
        assert_eq!(events[1].result, EventResult::Retry);
        assert_eq!(events[1].details, Some("not_persisted"));
    }

    #[test]
    fn merge_empty_sink_results_leaves_all_intact() {
        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$pageview", "user-2"),
        ];
        // All events published but no sink results (edge case - shouldn't
        // happen in practice but should be safe)
        let results: Vec<Box<dyn SinkResult>> = vec![];

        merge_sink_results(&mut events, &results);

        assert_eq!(events[0].result, EventResult::Ok);
        assert_eq!(events[1].result, EventResult::Ok);
    }

    #[test]
    fn merge_pre_drop_not_mutated_even_if_result_present() {
        let mut events = vec![wrapped_event("$pageview", "user-1")];
        events[0].result = EventResult::Drop;
        events[0].details = Some("missing_event_name");

        // Should be unreachable in practice (dropped events aren't published
        // so they won't have a SinkResult), but even if a result exists for
        // this UUID, the event shouldn't be touched because should_publish is false
        let results: Vec<Box<dyn SinkResult>> =
            vec![MockSinkResult::retriable(events[0].uuid, "queue_full")];

        merge_sink_results(&mut events, &results);

        assert_eq!(events[0].result, EventResult::Drop);
        assert_eq!(events[0].details, Some("missing_event_name"));
    }

    #[tokio::test]
    async fn process_batch_returns_service_unavailable_when_no_sink_router() {
        let test_state = crate::v1::test_utils::TestStateBuilder::new().build();
        let mut state = test_state.state;
        state.v1_sink_router = None;

        let mut ctx = test_utils::test_analytics_context();
        let batch = valid_batch(vec![valid_event()]);

        let err = process_batch(&state, &mut ctx, batch).await.unwrap_err();
        assert!(
            matches!(err, Error::ServiceUnavailable(_)),
            "expected ServiceUnavailable, got: {err:?}"
        );
    }

    #[tokio::test]
    async fn process_batch_all_validation_dropped_returns_200_not_402() {
        let test_state = crate::v1::test_utils::TestStateBuilder::new().build();
        let state = test_state.state;

        let mut ctx = test_utils::test_analytics_context();
        // Every event is invalid — empty name, empty distinct_id, bad timestamp.
        let batch = valid_batch(vec![
            Event {
                event: String::new(),
                ..valid_event()
            },
            Event {
                distinct_id: String::new(),
                ..valid_event()
            },
            Event {
                timestamp: "not-a-date".to_string(),
                ..valid_event()
            },
        ]);

        let resp = process_batch(&state, &mut ctx, batch).await.unwrap();
        assert_eq!(resp.entries().len(), 3);
        for (_, entry) in resp.entries() {
            assert_eq!(
                entry.result,
                EventResult::Drop,
                "all-invalid batch must return 200 with per-event drops, not 402"
            );
        }
    }

    // =========================================================================
    // Integration-style tests: publish → merge → response flow
    // =========================================================================
    // These tests exercise the same code path as the wired process_batch, but
    // call the sink router directly rather than constructing a full State.

    use std::collections::HashMap as StdHashMap;
    use std::sync::Arc;

    use crate::config::CaptureMode;
    use crate::v1::sinks::kafka::mock::MockProducer;
    use crate::v1::sinks::kafka::sink::KafkaSink;
    use crate::v1::sinks::router::Router as SinkRouter;
    use crate::v1::sinks::sink::Sink;
    use crate::v1::sinks::{Config as SinkConfig, SinkName};

    use super::BatchResponse;
    use crate::v1::test_utils::{
        batch_payload, event_with_all_options, event_with_empty_options, WrappedEventMut,
    };

    fn test_sink_router() -> (SinkRouter, lifecycle::Handle, lifecycle::MonitorGuard) {
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .build();
        let handle = manager.register("process_integ", lifecycle::ComponentOptions::new());
        handle.report_healthy();
        let monitor = manager.monitor_background();

        let producer = Arc::new(MockProducer::new(SinkName::Msk, handle.clone()));
        let config = SinkConfig {
            produce_timeout: StdDuration::from_secs(30),
            kafka: test_utils::test_kafka_config(),
        };
        let sink: Box<dyn Sink> = Box::new(KafkaSink::new(
            SinkName::Msk,
            producer,
            config,
            CaptureMode::Events,
            handle.clone(),
        ));
        let sinks: StdHashMap<SinkName, Box<dyn Sink>> =
            [(SinkName::Msk, sink)].into_iter().collect();
        let router = SinkRouter::new(SinkName::Msk, sinks);
        (router, handle, monitor)
    }

    #[tokio::test]
    async fn integration_happy_path_all_ok() {
        let (router, _handle, _monitor) = test_sink_router();
        let mut ctx = test_utils::test_context();
        ctx.created_at = None;

        let events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
            wrapped_event("button_clicked", "user-3"),
        ];

        let (mut events, serialized) =
            serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        let sink_results = router
            .publish_batch(router.default_sink(), &ctx, &serialized.prepared)
            .await
            .unwrap();

        let mut all_results = serialized.failures;
        all_results.extend(sink_results);
        merge_sink_results(&mut events, &all_results);
        let resp = BatchResponse::build(&ctx, &events);

        assert!(!resp.has_retry);
        assert_eq!(resp.entries().len(), 3);
        for (_, status) in resp.entries() {
            assert_eq!(status.result, EventResult::Ok);
            assert!(status.details.is_none());
        }
    }

    #[tokio::test]
    async fn integration_mixed_pre_drop_and_publish() {
        let (router, _handle, _monitor) = test_sink_router();
        let mut ctx = test_utils::test_context();
        ctx.created_at = None;

        let events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$pageview", "user-2")
                .with_result(EventResult::Drop, Some("billing_limit_exceeded")),
            wrapped_event("$pageview", "user-3")
                .with_result(EventResult::Warning, Some("person_processing_disabled")),
        ];

        let (mut events, serialized) =
            serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        assert_eq!(serialized.prepared.len(), 2); // only Ok + Warning are published

        let sink_results = router
            .publish_batch(router.default_sink(), &ctx, &serialized.prepared)
            .await
            .unwrap();

        let mut all_results = serialized.failures;
        all_results.extend(sink_results);
        merge_sink_results(&mut events, &all_results);
        let resp = BatchResponse::build(&ctx, &events);

        assert!(!resp.has_retry);
        assert_eq!(resp.entries().len(), 3);
        assert_eq!(resp.entries()[0].1.result, EventResult::Ok);
        assert_eq!(resp.entries()[1].1.result, EventResult::Drop);
        assert_eq!(resp.entries()[1].1.details, Some("billing_limit_exceeded"));
        assert_eq!(resp.entries()[2].1.result, EventResult::Warning);
        assert_eq!(
            resp.entries()[2].1.details,
            Some("person_processing_disabled")
        );
    }

    #[tokio::test]
    async fn integration_all_events_pre_dropped_empty_publish() {
        let (router, _handle, _monitor) = test_sink_router();
        let mut ctx = test_utils::test_context();
        ctx.created_at = None;

        let events = vec![
            wrapped_event("$pageview", "user-1")
                .with_result(EventResult::Drop, Some("billing_limit_exceeded")),
            wrapped_event("$pageview", "user-2")
                .with_result(EventResult::Drop, Some("billing_limit_exceeded")),
        ];

        let (mut events, serialized) =
            serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        assert!(serialized.prepared.is_empty());

        let sink_results = router
            .publish_batch(router.default_sink(), &ctx, &serialized.prepared)
            .await
            .unwrap();

        let mut all_results = serialized.failures;
        all_results.extend(sink_results);
        merge_sink_results(&mut events, &all_results);
        let resp = BatchResponse::build(&ctx, &events);

        assert!(!resp.has_retry);
        assert_eq!(resp.entries().len(), 2);
        assert_eq!(resp.entries()[0].1.result, EventResult::Drop);
        assert_eq!(resp.entries()[1].1.result, EventResult::Drop);
    }

    #[tokio::test]
    async fn integration_overflow_destination_published_ok() {
        let (router, _handle, _monitor) = test_sink_router();
        let mut ctx = test_utils::test_context();
        ctx.created_at = None;

        let events =
            vec![wrapped_event("$pageview", "user-1").with_destination(Destination::Overflow)];

        let (mut events, serialized) =
            serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        let sink_results = router
            .publish_batch(router.default_sink(), &ctx, &serialized.prepared)
            .await
            .unwrap();

        let mut all_results = serialized.failures;
        all_results.extend(sink_results);
        merge_sink_results(&mut events, &all_results);
        let resp = BatchResponse::build(&ctx, &events);

        assert!(!resp.has_retry);
        assert_eq!(resp.entries()[0].1.result, EventResult::Ok);
    }

    #[test]
    fn integration_payload_round_trip_empty_options() {
        let events = vec![event_with_empty_options()];
        let payload = batch_payload(&events);
        let batch: Batch = serde_json::from_slice(&payload).unwrap();
        assert_eq!(batch.batch.len(), 1);
        let opts = batch.batch[0].options.validate().unwrap();
        assert_eq!(opts.cookieless_mode, None);
        assert_eq!(opts.disable_skew_correction, None);
        assert_eq!(opts.product_tour_id, None);
        assert_eq!(opts.process_person_profile, None);
    }

    #[test]
    fn integration_payload_round_trip_all_options() {
        let events = vec![event_with_all_options()];
        let payload = batch_payload(&events);
        let batch: Batch = serde_json::from_slice(&payload).unwrap();
        assert_eq!(batch.batch.len(), 1);
        let opts = batch.batch[0].options.validate().unwrap();
        assert_eq!(opts.cookieless_mode, Some(true));
        assert_eq!(opts.disable_skew_correction, Some(true));
        assert_eq!(opts.product_tour_id.as_deref(), Some("tour-v2"));
        assert_eq!(opts.process_person_profile, Some(false));
    }

    #[cfg(test)]
    #[test]
    fn integration_compressed_payload_gzip() {
        use crate::v1::test_utils::compressed_payload;
        let events = vec![valid_event()];
        let raw = batch_payload(&events);
        let compressed = compressed_payload(&raw, "gzip");
        assert!(compressed.len() < raw.len());
        // Decompress and verify
        use flate2::read::GzDecoder;
        use std::io::Read;
        let mut decoder = GzDecoder::new(compressed.as_slice());
        let mut decompressed = Vec::new();
        decoder.read_to_end(&mut decompressed).unwrap();
        assert_eq!(decompressed, raw);
    }

    #[cfg(test)]
    #[test]
    fn integration_compressed_payload_zstd() {
        use crate::v1::test_utils::compressed_payload;
        let events = vec![valid_event()];
        let raw = batch_payload(&events);
        let compressed = compressed_payload(&raw, "zstd");
        assert!(compressed.len() < raw.len());
        let decompressed = zstd::decode_all(std::io::Cursor::new(&compressed)).unwrap();
        assert_eq!(decompressed, raw);
    }

    #[cfg(test)]
    #[test]
    fn integration_compressed_payload_deflate() {
        use crate::v1::test_utils::compressed_payload;
        let events = vec![valid_event()];
        let raw = batch_payload(&events);
        let compressed = compressed_payload(&raw, "deflate");
        assert!(compressed.len() < raw.len());
        use flate2::read::DeflateDecoder;
        use std::io::Read;
        let mut decoder = DeflateDecoder::new(compressed.as_slice());
        let mut decompressed = Vec::new();
        decoder.read_to_end(&mut decompressed).unwrap();
        assert_eq!(decompressed, raw);
    }

    #[cfg(test)]
    #[test]
    fn integration_compressed_payload_brotli() {
        use crate::v1::test_utils::compressed_payload;
        let events = vec![valid_event()];
        let raw = batch_payload(&events);
        let compressed = compressed_payload(&raw, "br");
        assert!(!compressed.is_empty());
        let mut decompressed = Vec::new();
        brotli::BrotliDecompress(&mut std::io::Cursor::new(&compressed), &mut decompressed)
            .unwrap();
        assert_eq!(decompressed, raw);
    }
}
