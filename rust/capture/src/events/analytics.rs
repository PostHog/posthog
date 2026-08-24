//! Analytics event processing
//!
//! This module handles processing of regular analytics events (pageviews, custom events,
//! exceptions, etc.) as opposed to recordings (session replay).

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono::DateTime;
use common_ingestion_warnings::{
    WarningEmitter, CAPTURE_LEGACY_ANALYTICS, CAPTURE_LEGACY_RATE_LIMIT,
};
use common_types::{CapturedEvent, RawEvent};
use limiters::token_dropper::TokenDropper;
use metrics::counter;
use serde_json;
use tracing::{error, instrument, warn, Span};
use uuid::Uuid;

use limiters::overflow::OverflowLimiter;

use crate::{
    api::CaptureError,
    debug_or_info,
    event_restrictions::{EventContext as RestrictionEventContext, EventRestrictionService},
    events::{ai_byte_limit::drop_ai_byte_limited, overflow_stamping::stamp_overflow_reason},
    global_rate_limiter::{GlobalRateLimitKey, GlobalRateLimiter},
    ingestion_warnings::{
        emit_distinct_id_truncated_warning, emit_rate_limit_warning,
        legacy::{emit_processing_abort_warning, request_context},
    },
    prometheus::{report_clock_skew, report_dropped_events},
    router, sinks,
    utils::uuid_v7_from_datetime,
    v0_request::{
        exceeds_max_ai_event_bytes, DataType, OverflowReason, ProcessedEvent,
        ProcessedEventMetadata, ProcessingContext,
    },
};

/// Property keys the heatmap pipeline reads from a redirected event. The
/// redirect carries only these (plus `distinct_id` and `$cookieless_mode`,
/// which are needed for the routing key).
///
/// The `$raw_user_agent`, `$ip`, `$host`, `$timezone`, and `$cookieless_extra`
/// keys are not consumed by the heatmap extractor itself, but the ingestion
/// pipeline runs cookieless identity resolution against every event before
/// any extractor sees it. Cookieless-mode events with these properties
/// stripped get dropped with a `cookieless_missing_user_agent` warning
/// before the heatmap pipeline can run, so the redirect must preserve them
/// for cookieless customers' heatmap and scroll-depth data to survive.
const HEATMAP_PROPERTY_KEYS: &[&str] = &[
    "$heatmap_data",
    "$viewport_height",
    "$viewport_width",
    "$session_id",
    "$prev_pageview_pathname",
    "$prev_pageview_max_scroll",
    "$current_url",
    "$raw_user_agent",
    "$ip",
    "$host",
    "$timezone",
    "$cookieless_extra",
];

/// True when this event carries data that the heatmap extraction pipeline
/// would process — either an explicit `$heatmap_data` payload or the scroll
/// depth properties that the pipeline derives from a previous pageview.
fn has_heatmap_data(event: &RawEvent) -> bool {
    event.properties.contains_key("$heatmap_data")
        || (event.properties.contains_key("$prev_pageview_pathname")
            && event.properties.contains_key("$current_url"))
}

/// Build a stripped-down `$$heatmap` event from a non-`$$heatmap` event that
/// carries heatmap data. The redirect gets a fresh UUID so it does not
/// deduplicate against the original. Returns `Ok(None)` if the source event
/// has no resolvable `distinct_id` — the original event will fail validation
/// downstream anyway, so no point emitting a redirect that will also fail.
fn create_heatmap_redirect(
    event: &RawEvent,
    historical_cfg: router::HistoricalConfig,
    context: &ProcessingContext,
) -> Result<Option<ProcessedEvent>, CaptureError> {
    let Some(distinct_id) = event.extract_distinct_id() else {
        return Ok(None);
    };

    let mut properties = HashMap::new();
    for key in HEATMAP_PROPERTY_KEYS {
        if let Some(value) = event.properties.get(*key) {
            properties.insert((*key).to_string(), value.clone());
        }
    }
    // $cookieless_mode shapes the routing key (token:ip vs token:distinct_id);
    // extract_is_cookieless_mode reads it from properties.
    if let Some(value) = event.properties.get("$cookieless_mode") {
        properties.insert("$cookieless_mode".to_string(), value.clone());
    }

    let heatmap_event = RawEvent {
        token: event.token.clone(),
        distinct_id: Some(serde_json::Value::String(distinct_id)),
        // Leave unset so process_single_event seeds the UUID from the event timestamp.
        uuid: None,
        event: "$$heatmap".to_string(),
        properties,
        timestamp: event.timestamp.clone(),
        offset: event.offset,
        set: None,
        set_once: None,
    };

    process_single_event(&heatmap_event, historical_cfg, context).map(Some)
}

/// Process a single analytics event from RawEvent to ProcessedEvent.
#[instrument(skip_all, fields(event_name, request_id))]
pub fn process_single_event(
    event: &RawEvent,
    historical_cfg: router::HistoricalConfig,
    context: &ProcessingContext,
) -> Result<ProcessedEvent, CaptureError> {
    if event.event.is_empty() {
        return Err(CaptureError::MissingEventName);
    }
    Span::current().record("event_name", &event.event);
    Span::current().record("is_mirror_deploy", context.is_mirror_deploy);
    Span::current().record("request_id", &context.request_id);

    let data_type = DataType::from_event_name(&event.event, context.historical_migration);

    // Redact the IP address of internally-generated events when tagged as such
    let resolved_ip = if event.properties.contains_key("capture_internal") {
        "127.0.0.1".to_string()
    } else {
        context.client_ip.clone()
    };

    let data = serde_json::to_string(&event).map_err(|e| {
        error!("failed to encode data field: {e:#}");
        CaptureError::NonRetryableSinkError
    })?;

    // Compute the actual event timestamp using our timestamp parsing logic
    let sent_at_utc = context.sent_at.map(|sa| {
        DateTime::from_timestamp(sa.unix_timestamp(), sa.nanosecond()).unwrap_or_default()
    });
    let ignore_sent_at = event
        .properties
        .get("$ignore_sent_at")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    // Parse the event timestamp
    let parsed_timestamp = common_types::timestamp::parse_event_timestamp(
        event.timestamp.as_deref(),
        event.offset,
        sent_at_utc,
        ignore_sent_at,
        context.now,
    );
    if let Some(skew) = parsed_timestamp.clock_skew {
        report_clock_skew(skew);
    }

    let event_name = event.event.clone();

    let extracted_distinct_id = event
        .extract_distinct_id_checked()
        .ok_or(CaptureError::MissingDistinctId)?;

    let mut metadata = ProcessedEventMetadata {
        data_type,
        session_id: None,
        computed_timestamp: Some(parsed_timestamp.timestamp),
        event_name: event_name.clone(),
        force_overflow: false,
        skip_person_processing: false,
        redirect_to_dlq: false,
        redirect_to_topic: None,
        skip_heatmap_processing: false,
        overflow_reason: None,
        distinct_id_truncated_from: extracted_distinct_id.truncated_from_chars,
    };

    if historical_cfg.should_reroute(metadata.data_type, parsed_timestamp.timestamp) {
        metrics::counter!(
            "capture_events_rerouted_historical",
            &[("reason", "timestamp")]
        )
        .increment(1);
        metadata.data_type = DataType::AnalyticsHistorical;
    }

    let event = CapturedEvent {
        // Seed the UUIDv7 from the event timestamp, not ingestion time, so its embedded time tracks events.timestamp.
        uuid: event
            .uuid
            .unwrap_or_else(|| uuid_v7_from_datetime(parsed_timestamp.timestamp)),
        distinct_id: extracted_distinct_id.value,
        session_id: metadata.session_id.clone(),
        ip: resolved_ip,
        data,
        now: context
            .now
            .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        sent_at: context.sent_at,
        token: context.token.clone(),
        event: event_name,
        timestamp: parsed_timestamp.timestamp,
        is_cookieless_mode: event
            .extract_is_cookieless_mode()
            .ok_or(CaptureError::InvalidCookielessMode)?,
        historical_migration: metadata.data_type == DataType::AnalyticsHistorical,
    };

    Ok(ProcessedEvent { metadata, event })
}

/// Process a batch of analytics events.
///
/// All routing policy lives here: token dropping, AI lane assignment
/// (resolved into `DataType::AiEvents` at classification time), event
/// restrictions, the AI lane's per-project byte budget, global rate
/// limiting (per `token:distinct_id`), historical rerouting, and per-key
/// overflow rerouting via [`OverflowLimiter`]. Overflow stamping
/// goes through the shared [`stamp_overflow_reason`] helper, which the AI
/// (`ai_endpoint::ai_handler`) and OTEL (`otel::otel_handler`) paths also
/// call so every `DataType::AnalyticsMain` event gets identical limiter
/// semantics regardless of entry point. The kafka sink is a pure mechanism
/// layer — it reads `ProcessedEventMetadata::data_type`,
/// `overflow_reason`, `force_overflow`, `redirect_to_dlq`, and
/// `redirect_to_topic` to decide which topic and key to produce to.
#[instrument(skip_all, fields(events = events.len(), request_id))]
#[allow(clippy::too_many_arguments)]
pub async fn process_events(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    dropper: Arc<TokenDropper>,
    restriction_service: Option<EventRestrictionService>,
    historical_cfg: router::HistoricalConfig,
    global_rate_limiter: Option<Arc<GlobalRateLimiter>>,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    ai_events_overflow_limiter: Option<Arc<OverflowLimiter>>,
    ingestion_warning_emitter: Option<Arc<dyn WarningEmitter>>,
    events: Vec<RawEvent>,
    context: &ProcessingContext,
    ai_byte_rate_limiter: Option<Arc<GlobalRateLimiter>>,
) -> Result<(), CaptureError> {
    // The whole request fails on the first hard error, so the abort warning
    // charges the full batch, matching what the endpoint's
    // `report_dropped_events` records for the same failure. Emitting here
    // rather than at the endpoint keeps every legacy warning (aborts, rate
    // limit, and future per-event ones) in this module, mirroring where the
    // v1 pipeline emits.
    let event_count = events.len() as u64;
    let emitter = ingestion_warning_emitter.clone();
    let result = process_events_inner(
        sink,
        dropper,
        restriction_service,
        historical_cfg,
        global_rate_limiter,
        overflow_limiter,
        ai_events_overflow_limiter,
        ingestion_warning_emitter,
        events,
        context,
        ai_byte_rate_limiter,
    )
    .await;

    if let Err(ref err) = result {
        emit_processing_abort_warning(emitter.as_deref(), context, err, event_count);
    }
    result
}

#[allow(clippy::too_many_arguments)]
async fn process_events_inner(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    dropper: Arc<TokenDropper>,
    restriction_service: Option<EventRestrictionService>,
    historical_cfg: router::HistoricalConfig,
    global_rate_limiter: Option<Arc<GlobalRateLimiter>>,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    ai_events_overflow_limiter: Option<Arc<OverflowLimiter>>,
    ingestion_warning_emitter: Option<Arc<dyn WarningEmitter>>,
    events: Vec<RawEvent>,
    context: &ProcessingContext,
    ai_byte_rate_limiter: Option<Arc<GlobalRateLimiter>>,
) -> Result<(), CaptureError> {
    let chatty_debug_enabled = context.chatty_debug_enabled;

    Span::current().record("request_id", &context.request_id);
    Span::current().record("is_mirror_deploy", context.is_mirror_deploy);

    // Import mode ingests only historical backfills: drop any batch not
    // flagged `historical_migration` (a batch-level flag) and return Ok so the
    // endpoint responds 200 (accept-and-discard) — the batch-import-worker must
    // not retry. Non-batch legacy endpoints never set the flag, so they are
    // always dropped in Import mode, which is intended: imports only arrive via
    // `/batch` and the v1 endpoint.
    if context.capture_mode.requires_historical_migration() && !context.historical_migration {
        let dropped = events.len() as u64;
        // Same label value as the v1 path's capture_v1_events_dropped{reason=...}
        // so one alert expression covers both metric names.
        report_dropped_events("non_historical_import", dropped);
        warn!(
            token = context.token,
            dropped_events = dropped,
            "import mode dropped non-historical batch"
        );
        return Ok(());
    }

    // Build the processed batch one raw event at a time so we can split a
    // heatmap-carrying event into a stripped original + a `$$heatmap`
    // redirect *before* serialization happens inside `process_single_event`.
    // The original loses `$heatmap_data` and is flagged so the events
    // pipeline skips re-extracting; other heatmap-related properties
    // (`$prev_pageview_pathname`, `$current_url`) stay on it because web
    // analytics queries depend on them. If the redirect fails to construct,
    // we fall back to processing the original unchanged so the events
    // pipeline still extracts as before — no silent data loss.
    let raw_events = events;
    let mut events: Vec<ProcessedEvent> = Vec::with_capacity(raw_events.len());
    for mut raw in raw_events {
        if raw.event.starts_with("$ai_") {
            raw.properties
                .retain(|key, _| !key.starts_with(crate::gateway_provenance::GATEWAY_PREFIX));
        }
        if raw.event == "$$heatmap" || !has_heatmap_data(&raw) {
            events.push(process_single_event(&raw, historical_cfg, context)?);
            continue;
        }
        let mut redirect = match create_heatmap_redirect(&raw, historical_cfg, context) {
            Ok(Some(redirect)) => redirect,
            Ok(None) => {
                events.push(process_single_event(&raw, historical_cfg, context)?);
                continue;
            }
            Err(err) => {
                error!("failed to create heatmap redirect: {err:#}");
                events.push(process_single_event(&raw, historical_cfg, context)?);
                continue;
            }
        };
        raw.properties.remove("$heatmap_data");
        let mut processed = process_single_event(&raw, historical_cfg, context)?;
        processed.metadata.skip_heatmap_processing = true;
        events.push(processed);
        counter!("capture_heatmap_redirects_created").increment(1);
        // The redirect is a synthetic copy of the original, which already
        // carries the truncation; keeping it here would double-count the
        // submitted event in the warning tally below.
        redirect.metadata.distinct_id_truncated_from = None;
        events.push(redirect);
    }

    debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "created ProcessedEvents batch");

    // capture-ai serves only the AI paths and loads only AI restrictions (see
    // `Pipeline::for_capture_mode`), so an event on any other lane would run
    // ungoverned there. Reject the batch rather than dropping the offender: a
    // client sending non-AI events to an AI endpoint is misconfigured, and a
    // silent drop would hide that until someone went looking for the data. The
    // abort path emits an `invalid_ai_event` ingestion warning alongside the
    // 400, so the project owner sees it too.
    //
    // Lane membership is the `AI_EVENT_NAMES` allowlist, not an `$ai_` prefix,
    // so a prefixed-but-unlisted name is rejected here too — the Node AI
    // pipeline would DLQ it anyway.
    if context.capture_mode == crate::config::CaptureMode::Ai {
        if let Some(offender) = events
            .iter()
            .find(|e| e.metadata.data_type != DataType::AiEvents)
        {
            return Err(CaptureError::NonAiEventOnAiLane(
                offender.metadata.event_name.clone(),
            ));
        }
    }

    // Reject an AI-lane event past the deployment's ceiling before it can reach
    // the sink, where the producer's own cap would refuse it anyway — after
    // capture had read and processed the whole request. The whole request is
    // refused, matching how every other oversize check on this path behaves.
    //
    // The drop isn't counted here. The abort reaches the endpoint, which charges
    // the whole batch under this error's own `ai_event_too_big` tag; counting
    // locally too would report one more drop than the batch held, and split one
    // rejection across two `cause` labels.
    //
    // The uuid says which event to fix, since a batch can carry several of the
    // same name. It is only a handle for clients that send their own; the rest
    // get the one `process_single_event` minted, which identifies nothing they
    // can look up. The non-AI-event rejection above deliberately omits it: its
    // offender may be the `$$heatmap` event capture itself synthesized, and
    // naming a uuid the client never issued would misdirect them.
    if let Some(offender) = events.iter().find(|e| {
        e.metadata.data_type == DataType::AiEvents
            && exceeds_max_ai_event_bytes(e.event.data.len(), context.ai_max_event_bytes)
    }) {
        return Err(CaptureError::AiEventTooBig(format!(
            "AI event {} (uuid {}) is {} bytes, over the {}-byte limit",
            offender.metadata.event_name,
            offender.event.uuid,
            offender.event.data.len(),
            context.ai_max_event_bytes
        )));
    }

    events.retain(|e| {
        if dropper.should_drop(&e.event.token, &e.event.distinct_id) {
            report_dropped_events("token_dropper", 1);
            false
        } else {
            true
        }
    });

    debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "filtered by token_dropper");

    // Apply event restrictions, looking each event up under its `DataType`'s
    // pipeline. The single restriction service holds entries for all
    // pipelines its host capture deployment serves; the pipeline argument
    // selects which slice of restrictions applies to each event. A DropEvent
    // tagged only for `analytics` will never silently drop an exception event
    // on the way to the error tracking topic, and vice versa. Data types
    // without a pipeline (heatmaps, ingestion warnings, snapshots) flow
    // through unrestricted. `AiEvents` looks up the `ai` pipeline: a diverted
    // AI event is governed by ai-scoped restrictions (drop/DLQ/redirect still
    // win over the lane, redirect_to_topic beats the AI topic in the sink,
    // force_overflow keeps it on the AI lane) -- mirroring v1.
    if let Some(ref service) = restriction_service {
        let mut filtered_events = Vec::with_capacity(events.len());
        let now_ts = context.now.timestamp();

        for e in events {
            let Some(pipeline) = e.metadata.data_type.pipeline() else {
                filtered_events.push(e);
                continue;
            };

            let uuid_str = e.event.uuid.to_string();
            let event_ctx = RestrictionEventContext {
                distinct_id: Some(&e.event.distinct_id),
                session_id: e.event.session_id.as_deref(),
                event_name: Some(&e.event.event),
                event_uuid: Some(&uuid_str),
                now_ts,
            };

            let applied = service
                .get_restrictions(&e.event.token, &event_ctx, pipeline)
                .await;

            if applied.should_drop() {
                report_dropped_events("event_restriction_drop", 1);
                continue;
            }

            let mut event = e;
            event.metadata.force_overflow |= applied.force_overflow();
            event.metadata.skip_person_processing |= applied.skip_person_processing();
            event.metadata.redirect_to_dlq |= applied.redirect_to_dlq();
            if let Some(topic) = applied.redirect_to_topic() {
                event.metadata.redirect_to_topic = Some(topic.to_string());
            }

            filtered_events.push(event);
        }

        events = filtered_events;
        debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "filtered by event_restrictions");
    }

    // Charge the AI lane's per-project byte budget. This runs after event
    // restrictions so an event a `DropEvent` discards never spends the
    // project's budget on a send that was never going to happen. Events that
    // survive to here are charged whether or not the budget then sheds them:
    // those bytes crossed the wire either way.
    drop_ai_byte_limited(&mut events, ai_byte_rate_limiter.as_ref()).await;

    // Per-(token, distinct_id) global rate limiting: skip person processing for
    // hot distinct_ids and reroute AnalyticsMain events to overflow. Import mode
    // opts out entirely — historical backfills must never be throttled — so the
    // limiter is skipped even if one were wired.
    //
    // DIVERGENCE from v1 (`v1::analytics::process`), intentional and out of scope
    // to reconcile here — a future routing refactor must not assume parity:
    //   1. Ordering: legacy runs this GRL step BEFORE burst overflow stamping
    //      (`stamp_overflow_reason` below); v1 runs the GRL AFTER its overflow
    //      stamping. Both set overflow_reason on AnalyticsMain only, so the
    //      end state matches, but the pass order differs.
    //   2. Lane assignment is a single `DataType::from_event_name` match in
    //      legacy versus assign-then-reroute in v1.
    //   3. Events whose person processing was already off: v1 skips its stamps
    //      entirely (so such an event is never rerouted to overflow) and reports
    //      it as outcome="already_disabled". Legacy still stamps and reroutes it,
    //      and still counts it in the metric and log below; only the warning
    //      excludes it. So legacy's limited count can exceed its warned count,
    //      where v1's cannot.
    // Both paths consult the same shared limiter for every non-dropped event, so
    // per-key counts are identical regardless of which pipeline serves the key.
    // Import is unaffected by both: the GRL never runs (guard below) and no
    // overflowable lane is reachable, so behavior is identical across paths.
    if context.capture_mode.applies_global_rate_limit() {
        if let Some(ref limiter) = global_rate_limiter {
            let mut limited_distinct_ids: HashSet<&str> = HashSet::new();
            let mut limited_event_count: u64 = 0;
            // Narrower than the tallies above: events an upstream event
            // restriction had already taken person processing away from are
            // excluded. The limiter didn't change their fate, so telling the
            // customer we skipped person processing for them would inflate the
            // count and name distinct_ids the limit never affected. v1 draws the
            // same line via `already_disabled` in
            // `v1::analytics::process::apply_token_distinct_id_limits`.
            let mut warned_distinct_ids: HashSet<&str> = HashSet::new();
            let mut warned_event_count: u64 = 0;
            let mut already_disabled_event_count: u64 = 0;
            for event in events.iter_mut() {
                // Person processing is already off, which at this point can only
                // come from an event restriction: the burst limiter runs after
                // this stage in `stamp_overflow_reason`, and the limiter's own
                // stamp is set below. The limiter has nothing left to take away
                // from this event, so consulting it would change nothing and
                // still cost a local cache miss and a Redis round trip.
                if event.metadata.skip_person_processing {
                    already_disabled_event_count += 1;
                    continue;
                }
                let cache_key =
                    GlobalRateLimitKey::TokenDistinctId(&context.token, &event.event.distinct_id)
                        .to_cache_key();
                if limiter.is_limited(&cache_key, 1).await.is_some() {
                    let already_disabled = event.metadata.skip_person_processing;
                    event.metadata.skip_person_processing = true;
                    // Reroute the hot key to overflow. AnalyticsMain only: historical
                    // never overflows, the AI lane keeps its dedicated topic (v1
                    // gates the same way on Destination::AnalyticsMain), and only
                    // AnalyticsMain acts on overflow_reason.
                    if event.metadata.data_type == DataType::AnalyticsMain {
                        event.metadata.overflow_reason = Some(OverflowReason::ForceLimited);
                    }
                    limited_distinct_ids.insert(&event.event.distinct_id);
                    limited_event_count += 1;
                    if !already_disabled {
                        warned_distinct_ids.insert(&event.event.distinct_id);
                        warned_event_count += 1;
                    }
                }
            }
            if limited_event_count > 0 {
                let ids: Vec<&str> = limited_distinct_ids.iter().copied().collect();
                let preview: String = if ids.len() > 10 {
                    format!("{}...", ids[..10].join(", "))
                } else {
                    ids.join(", ")
                };
                counter!(
                    "capture_events_rate_limited_token_distinctid",
                    "reason" => "global_rate_limit_token_distinctid",
                )
                .increment(limited_event_count);
                warn!(
                    token = context.token,
                    limited_event_count = limited_event_count,
                    distinct_id_count = limited_distinct_ids.len(),
                    distinct_ids = %preview,
                    "events rate limited by distinct_id -- person processing disabled"
                );
            }

            if already_disabled_event_count > 0 {
                counter!(
                    "capture_global_rate_limiter_skipped",
                    "reason" => "person_processing_already_disabled",
                )
                .increment(already_disabled_event_count);
            }

            if warned_event_count > 0 {
                emit_rate_limit_warning(
                    ingestion_warning_emitter.as_deref(),
                    &request_context(context),
                    CAPTURE_LEGACY_RATE_LIMIT,
                    &warned_distinct_ids,
                    warned_event_count,
                );
            }
        }
    }

    // Overflow routing stage. This used to live in the kafka sink's
    // prepare_record; moving it here keeps the sink free of policy and
    // co-locates overflow with every other pipeline-level routing decision.
    // The stamping helper is shared with the AI (`ai_endpoint::ai_handler`)
    // and OTEL (`otel::otel_handler`) paths so every handler that emits
    // `DataType::AnalyticsMain` events gets identical limiter semantics and
    // metric labels — see `events::overflow_stamping`.
    stamp_overflow_reason(
        &mut events,
        overflow_limiter.as_ref(),
        ai_events_overflow_limiter.as_ref(),
    );

    // Tally truncated distinct_ids only now, after the membership filters
    // (token dropper, restrictions): the warning means "ingested with a
    // modified distinct_id", so an event those filters removed must not be
    // counted or named as the sample. The stages above this point reroute or
    // re-stamp events but never drop them. The warning itself is emitted only
    // after the sink accepts the batch, so a rejected request never reports
    // its events as ingested-but-modified either.
    let mut truncated_count: u64 = 0;
    let mut truncated_sample: Option<(String, usize, Uuid)> = None;
    for e in &events {
        if let Some(original_chars) = e.metadata.distinct_id_truncated_from {
            truncated_count += 1;
            if truncated_count == 1 {
                truncated_sample =
                    Some((e.event.distinct_id.clone(), original_chars, e.event.uuid));
            }
        }
    }

    if events.is_empty() {
        return Ok(());
    }

    if events.len() == 1 {
        sink.send(events[0].clone()).await?;
    } else {
        sink.send_batch(events).await?;
    }

    debug_or_info!(chatty_debug_enabled, context=?context, "sent analytics events");

    // A batch emptied by the filters above returns early and never reaches
    // this point, so an all-dropped request reports no truncation warning.
    if truncated_count > 0 {
        emit_distinct_id_truncated_warning(
            ingestion_warning_emitter.as_deref(),
            &request_context(context),
            CAPTURE_LEGACY_ANALYTICS,
            truncated_sample.filter(|_| truncated_count == 1),
            truncated_count,
        );
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ingestion_warnings::SdkAttribution;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{OverflowReason, ProcessingContext};
    use chrono::{DateTime, TimeZone, Utc};
    use common_ingestion_warnings::test_support::CollectingEmitter;
    use common_ingestion_warnings::WarningType;
    use common_types::RawEvent;
    use serde_json::json;
    use std::collections::HashMap;
    use std::num::NonZeroU32;
    use time::OffsetDateTime;

    fn create_test_context(
        now: DateTime<Utc>,
        sent_at: Option<OffsetDateTime>,
    ) -> ProcessingContext {
        ProcessingContext {
            user_agent: None,
            sent_at,
            token: "test_token".to_string(),
            now,
            client_ip: "127.0.0.1".to_string(),
            request_id: "test_request".to_string(),
            path: "/e/".to_string(),
            is_mirror_deploy: false,
            historical_migration: false,
            chatty_debug_enabled: false,
            capture_mode: crate::config::CaptureMode::Events,
            ai_max_event_bytes: 0,
            sdk_attribution: crate::ingestion_warnings::SdkAttribution::default(),
        }
    }

    fn create_test_event(
        timestamp: Option<String>,
        offset: Option<i64>,
        ignore_sent_at: Option<bool>,
    ) -> RawEvent {
        create_test_event_with_name("test_event", timestamp, offset, ignore_sent_at)
    }

    fn create_test_event_with_name(
        event_name: &str,
        timestamp: Option<String>,
        offset: Option<i64>,
        ignore_sent_at: Option<bool>,
    ) -> RawEvent {
        let mut properties = HashMap::new();
        if let Some(ignore) = ignore_sent_at {
            properties.insert("$ignore_sent_at".to_string(), json!(ignore));
        }
        properties.insert("distinct_id".to_string(), json!("test_user"));

        RawEvent {
            uuid: None,
            distinct_id: None,
            event: event_name.to_string(),
            properties,
            timestamp,
            offset,
            set: Some(HashMap::new()),
            set_once: Some(HashMap::new()),
            token: Some("test_token".to_string()),
        }
    }

    /// Named-field collaborators for `process_events`; tests override only
    /// the ones they exercise and take the rest from `Default`.
    struct PipelineOptions {
        dropper: Arc<TokenDropper>,
        restriction_service: Option<EventRestrictionService>,
        historical_cfg: router::HistoricalConfig,
        global_rate_limiter: Option<Arc<GlobalRateLimiter>>,
        overflow_limiter: Option<Arc<OverflowLimiter>>,
        ai_events_overflow_limiter: Option<Arc<OverflowLimiter>>,
        ingestion_warning_emitter: Option<Arc<dyn WarningEmitter>>,
        ai_byte_rate_limiter: Option<Arc<GlobalRateLimiter>>,
    }

    impl Default for PipelineOptions {
        fn default() -> Self {
            Self {
                dropper: Arc::new(TokenDropper::default()),
                restriction_service: None,
                historical_cfg: router::HistoricalConfig::new(false, 1),
                global_rate_limiter: None,
                overflow_limiter: None,
                ai_events_overflow_limiter: None,
                ingestion_warning_emitter: None,
                ai_byte_rate_limiter: None,
            }
        }
    }

    async fn run_pipeline(
        sink: Arc<dyn sinks::Event + Send + Sync>,
        events: Vec<RawEvent>,
        context: &ProcessingContext,
        options: PipelineOptions,
    ) -> Result<(), CaptureError> {
        process_events(
            sink,
            options.dropper,
            options.restriction_service,
            options.historical_cfg,
            options.global_rate_limiter,
            options.overflow_limiter,
            options.ai_events_overflow_limiter,
            options.ingestion_warning_emitter,
            events,
            context,
            options.ai_byte_rate_limiter,
        )
        .await
    }

    #[test]
    fn test_server_assigned_uuid_encodes_event_timestamp() {
        // Ingestion clock is in 2023, but the event's own timestamp is back in 2020.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);

        let mut properties = HashMap::new();
        properties.insert("distinct_id".to_string(), json!("test_user"));
        let event = RawEvent {
            uuid: None,
            distinct_id: None,
            event: "$pageview".to_string(),
            properties,
            timestamp: Some("2020-06-15T00:00:00Z".to_string()),
            offset: None,
            set: None,
            set_once: None,
            token: Some("test_token".to_string()),
        };

        let processed =
            process_single_event(&event, router::HistoricalConfig::new(false, 1), &context)
                .unwrap();

        let expected_millis = processed
            .metadata
            .computed_timestamp
            .unwrap()
            .timestamp_millis() as u128;
        // The high 48 bits of a UUIDv7 hold the Unix-millisecond timestamp.
        let uuid_millis = processed.event.uuid.as_u128() >> 80;
        assert_eq!(uuid_millis, expected_millis);
        assert!(now.timestamp_millis() as u128 - uuid_millis > 60_000_000_000);
    }

    #[test]
    fn test_server_assigned_uuid_floors_pre_epoch_event() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);

        let mut properties = HashMap::new();
        properties.insert("distinct_id".to_string(), json!("test_user"));
        // A pre-1970 timestamp has negative Unix millis, which can't fit the unsigned UUIDv7 time field.
        let event = RawEvent {
            uuid: None,
            distinct_id: None,
            event: "$pageview".to_string(),
            properties,
            timestamp: Some("1969-06-15T00:00:00Z".to_string()),
            offset: None,
            set: None,
            set_once: None,
            token: Some("test_token".to_string()),
        };

        let processed =
            process_single_event(&event, router::HistoricalConfig::new(false, 1), &context)
                .unwrap();

        // The event keeps its pre-epoch timestamp, but the uuid floors to the epoch rather than wrapping to garbage.
        assert!(
            processed
                .metadata
                .computed_timestamp
                .unwrap()
                .timestamp_millis()
                < 0
        );
        assert_eq!(processed.event.uuid.as_u128() >> 80, 0);
    }

    #[test]
    fn test_process_single_event_with_invalid_sent_at() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let context = create_test_context(now, None);
        let event = create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None);
        let result =
            process_single_event(&event, router::HistoricalConfig::new(false, 1), &context);

        assert!(result.is_ok());
        let processed = result.unwrap();
        let expected = DateTime::parse_from_rfc3339("2023-01-01T11:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(processed.metadata.computed_timestamp, Some(expected));
    }

    #[test]
    fn test_process_single_event_with_valid_sent_at() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let sent_at = OffsetDateTime::parse(
            "2023-01-01T12:00:05Z",
            &time::format_description::well_known::Rfc3339,
        )
        .unwrap();
        let context = create_test_context(now, Some(sent_at));

        let event = create_test_event(Some("2023-01-01T11:59:55Z".to_string()), None, None);

        let result =
            process_single_event(&event, router::HistoricalConfig::new(false, 1), &context);

        assert!(result.is_ok());
        let processed = result.unwrap();
        let expected = Utc.with_ymd_and_hms(2023, 1, 1, 11, 59, 50).unwrap();
        assert_eq!(processed.metadata.computed_timestamp, Some(expected));
    }

    #[test]
    fn test_process_single_event_ignore_sent_at() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let sent_at = OffsetDateTime::parse(
            "2023-01-01T12:00:05Z",
            &time::format_description::well_known::Rfc3339,
        )
        .unwrap();
        let context = create_test_context(now, Some(sent_at));

        let event = create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, Some(true));

        let result =
            process_single_event(&event, router::HistoricalConfig::new(false, 1), &context);

        assert!(result.is_ok());
        let processed = result.unwrap();

        let expected = DateTime::parse_from_rfc3339("2023-01-01T11:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(processed.metadata.computed_timestamp, Some(expected));
    }

    #[test]
    fn test_process_single_event_with_historical_migration_false() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let mut context = create_test_context(now, None);
        context.historical_migration = false;

        let event = create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None);

        let result =
            process_single_event(&event, router::HistoricalConfig::new(false, 1), &context);

        assert!(result.is_ok());
        let processed = result.unwrap();

        assert!(!processed.event.historical_migration);
        assert_eq!(processed.metadata.data_type, DataType::AnalyticsMain);
    }

    #[test]
    fn test_process_single_event_with_historical_migration_true() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let mut context = create_test_context(now, None);
        context.historical_migration = true;

        let event = create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None);

        let result =
            process_single_event(&event, router::HistoricalConfig::new(false, 1), &context);

        assert!(result.is_ok());
        let processed = result.unwrap();

        assert!(processed.event.historical_migration);
        assert_eq!(processed.metadata.data_type, DataType::AnalyticsHistorical);
    }

    // Mock sink for testing process_events with restrictions
    use crate::event_restrictions::{
        EventRestrictionService, Pipeline, Restriction, RestrictionFilters, RestrictionManager,
        RestrictionScope, RestrictionType,
    };
    use crate::sinks::test_sink::MockSink;
    use rstest::rstest;
    use std::time::Duration;

    #[tokio::test]
    async fn test_process_events_drop_event_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        // Create restriction service with DropEvent
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await;

        assert!(result.is_ok());
        // Event should be dropped
        assert_eq!(sink.get_events().len(), 0);
    }

    #[tokio::test]
    async fn test_process_events_force_overflow_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        // Create restriction service with ForceOverflow
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await;

        assert!(result.is_ok());
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.force_overflow);
    }

    #[tokio::test]
    async fn test_process_events_skip_person_processing_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        // Create restriction service with SkipPersonProcessing
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await;

        assert!(result.is_ok());
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.skip_person_processing);
    }

    #[tokio::test]
    async fn test_process_events_redirect_to_dlq_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        // Create restriction service with RedirectToDlq
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToDlq,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await;

        assert!(result.is_ok());
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.redirect_to_dlq);
    }

    #[tokio::test]
    async fn test_process_events_multiple_restrictions() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        // Create restriction service with multiple restrictions
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![
                Restriction {
                    restriction_type: RestrictionType::ForceOverflow,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
                Restriction {
                    restriction_type: RestrictionType::SkipPersonProcessing,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
            ],
        );
        service.update(manager).await;

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await;

        assert!(result.is_ok());
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.force_overflow);
        assert!(captured[0].metadata.skip_person_processing);
    }

    #[tokio::test]
    async fn test_process_events_no_restriction_service() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        // No restriction service
        let result = run_pipeline(sink.clone(), events, &context, PipelineOptions::default()).await;

        assert!(result.is_ok());
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(!captured[0].metadata.force_overflow);
        assert!(!captured[0].metadata.skip_person_processing);
        assert!(!captured[0].metadata.redirect_to_dlq);
        assert!(captured[0].metadata.redirect_to_topic.is_none());
    }

    #[tokio::test]
    async fn test_process_events_filtered_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        // Create restriction that only applies to different event name
        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        let mut filters = RestrictionFilters::default();
        filters.event_names.insert("$pageview".to_string()); // our event is "test_event"
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::Filtered(filters),
                args: None,
            }],
        );
        service.update(manager).await;

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await;

        assert!(result.is_ok());
        // Event should NOT be dropped because filter doesn't match
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
    }

    #[tokio::test]
    async fn test_process_events_redirect_to_topic_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToTopic,
                scope: RestrictionScope::AllEvents,
                args: Some(json!({"topic": "custom_events_topic"})),
            }],
        );
        service.update(manager).await;

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await;

        assert!(result.is_ok());
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(
            captured[0].metadata.redirect_to_topic,
            Some("custom_events_topic".to_string())
        );
    }

    /// The AI lane assignment holds across capture modes: `Events` and
    /// `Import` both divert every allowlisted AI event (only the AI lane has AI
    /// processing, so imports must divert too), winning over historical.
    /// Non-AI events stay on their normal route in every mode. The topic
    /// itself is resolved in the kafka sink from `DataType::AiEvents`, not
    /// here.
    struct AiLaneInput {
        capture_mode: crate::config::CaptureMode,
        // Import mode drops non-historical batches before classification, so
        // its case must arrive flagged historical.
        historical_migration: bool,
    }

    struct AiLaneExpected {
        ai_data_type: DataType,
        pageview_data_type: DataType,
    }

    #[rstest]
    #[case::events_mode(
        AiLaneInput {
            capture_mode: crate::config::CaptureMode::Events,
            historical_migration: false,
        },
        AiLaneExpected {
            ai_data_type: DataType::AiEvents,
            pageview_data_type: DataType::AnalyticsMain,
        }
    )]
    #[case::import_mode(
        AiLaneInput {
            capture_mode: crate::config::CaptureMode::Import,
            historical_migration: true,
        },
        AiLaneExpected {
            ai_data_type: DataType::AiEvents,
            pageview_data_type: DataType::AnalyticsHistorical,
        }
    )]
    #[tokio::test]
    async fn test_process_events_ai_lane_assignment(
        #[case] input: AiLaneInput,
        #[case] expected: AiLaneExpected,
    ) {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.capture_mode = input.capture_mode;
        context.historical_migration = input.historical_migration;
        let events = vec![
            create_test_event_with_name(
                "$ai_generation",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
            create_test_event_with_name(
                "$pageview",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
        ];

        let sink = Arc::new(MockSink::new());

        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 2);
        let ai_event = captured
            .iter()
            .find(|e| e.event.event == "$ai_generation")
            .unwrap();
        assert_eq!(ai_event.metadata.data_type, expected.ai_data_type);
        // Lane assignment must not leak into the restriction-driven redirect
        // mechanism; the sink resolves the AI topic from the data type alone.
        assert_eq!(ai_event.metadata.redirect_to_topic, None);
        let pageview = captured
            .iter()
            .find(|e| e.event.event == "$pageview")
            .unwrap();
        assert_eq!(pageview.metadata.data_type, expected.pageview_data_type);
        assert_eq!(pageview.metadata.redirect_to_topic, None);
    }

    /// End-to-end: `process_events` drops the over-budget `$ai_generation` and keeps the small one.
    #[tokio::test]
    async fn ai_events_over_byte_budget_are_dropped_end_to_end() {
        use crate::sinks::kafka::{test_topics, KafkaSinkBase};
        use crate::sinks::producer::MockKafkaProducer;

        // 800-byte budget: the enveloped small event (~672 B) fits, and the
        // large one takes the running total past it.
        let limiter = Some(Arc::new(GlobalRateLimiter::mock_budget(800)));

        let producer = MockKafkaProducer::new();
        let sink = Arc::new(KafkaSinkBase::with_producer(
            producer.clone(),
            test_topics(),
        ));

        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);

        let small_event = create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        );
        let mut oversized_event = create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        );
        oversized_event
            .properties
            .insert("$ai_input".to_string(), json!("x".repeat(500)));

        process_events(
            sink,
            Arc::new(TokenDropper::default()),
            None,
            router::HistoricalConfig::new(false, 1),
            None,
            None,
            None,
            None,
            vec![small_event, oversized_event],
            &context,
            limiter,
        )
        .await
        .expect("process_events must accept the batch even though one event is dropped");

        let records = producer.get_records();
        assert_eq!(
            records.len(),
            1,
            "only the under-budget AI event must reach the sink"
        );
        let topics = test_topics();
        let ai_topic = topics.topic_for(&crate::sinks::registry::Output::AiMain);
        assert_eq!(
            records[0].topic, ai_topic,
            "the surviving record must be on the AI lane"
        );
    }

    /// An AI event past the deployment's ceiling refuses the whole request, so
    /// no part of it reaches the sink. The legacy path already answers 413 for
    /// every other oversize condition, and the producer would refuse this event
    /// anyway once the request had been read in full.
    #[tokio::test]
    async fn oversize_ai_events_refuse_the_request_end_to_end() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.ai_max_event_bytes = 700;

        let sink = Arc::new(MockSink::new());
        let mut oversized = create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        );
        oversized
            .properties
            .insert("$ai_input".to_string(), json!("x".repeat(800)));
        // A client-supplied uuid: the case where the uuid in the message is a
        // handle the sender can match against its own outbox.
        let offender_uuid = Uuid::parse_str("018f2c6e-0000-7000-8000-00000000beef").unwrap();
        oversized.uuid = Some(offender_uuid);

        let err = run_pipeline(
            sink.clone(),
            vec![
                create_test_event_with_name(
                    "$ai_generation",
                    Some("2023-01-01T11:00:00Z".to_string()),
                    None,
                    None,
                ),
                oversized,
            ],
            &context,
            PipelineOptions::default(),
        )
        .await
        .expect_err("an oversize AI event must refuse the batch");

        assert!(matches!(err, CaptureError::AiEventTooBig(_)), "got {err:?}");
        // The offender's uuid, not the batch's first event: a batch can carry
        // several events of one name, so the name alone doesn't say which to fix.
        assert!(
            err.to_string().contains(&offender_uuid.to_string()),
            "the message must name the offending event's uuid, got {err}"
        );
        assert!(
            sink.get_events().is_empty(),
            "no event may reach the sink once the request is refused"
        );
    }

    /// The ceiling governs the AI lane only: an analytics event of the same
    /// size passes, so a deployment sized for its AI topic's broker does not
    /// start refusing ordinary analytics traffic.
    #[tokio::test]
    async fn the_ai_size_ceiling_leaves_analytics_events_alone() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.ai_max_event_bytes = 700;

        let sink = Arc::new(MockSink::new());
        let mut oversized = create_test_event_with_name(
            "$pageview",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        );
        oversized
            .properties
            .insert("big".to_string(), json!("x".repeat(800)));

        run_pipeline(
            sink.clone(),
            vec![oversized],
            &context,
            PipelineOptions::default(),
        )
        .await
        .expect("an oversize analytics event must not be refused");

        assert_eq!(sink.get_events().len(), 1);
    }

    /// A `DropEvent` restriction discards its event before the byte budget is
    /// charged, so the budget still has room for the events that survive it.
    /// Charging first would let a restricted event shed a legitimate one
    /// behind it.
    #[tokio::test]
    async fn restriction_dropped_ai_events_do_not_spend_the_byte_budget() {
        // 800-byte budget against two ~670 B enveloped events: whichever is
        // charged first is admitted, and a second charge exceeds the budget.
        let limiter = Some(Arc::new(GlobalRateLimiter::mock_budget(800)));

        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);

        let service = EventRestrictionService::new(
            vec![Pipeline::Analytics, Pipeline::Ai],
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        let mut filters = RestrictionFilters::default();
        filters.event_names.insert("$ai_generation".to_string());
        manager.insert_restrictions(
            Pipeline::Ai,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::Filtered(filters),
                args: None,
            }],
        );
        service.update(manager).await;

        let sink = Arc::new(MockSink::new());
        let events = vec![
            create_test_event_with_name(
                "$ai_generation",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
            create_test_event_with_name(
                "$ai_span",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
        ];

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ai_byte_rate_limiter: limiter,
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(
            captured.len(),
            1,
            "the restricted event must not spend budget the surviving event needs"
        );
        assert_eq!(captured[0].event.event, "$ai_span");
    }

    /// capture-ai loads only AI restrictions, so anything off the AI lane must
    /// not reach the pipeline there. Each case sends a two-event batch whose
    /// second event is the one under test.
    struct AiLaneGateCase {
        second_event: &'static str,
        rejected: bool,
    }

    #[rstest]
    #[case::analytics_event_is_rejected(AiLaneGateCase {
        second_event: "$pageview",
        rejected: true,
    })]
    // Lane membership is the AI_EVENT_NAMES allowlist, not an `$ai_` prefix.
    // A prefixed-but-unlisted name resolves to AnalyticsMain, so it must be
    // rejected too -- the Node AI pipeline would DLQ it downstream anyway.
    #[case::prefixed_but_unlisted_name_is_rejected(AiLaneGateCase {
        second_event: "$ai_call",
        rejected: true,
    })]
    #[case::exception_is_rejected(AiLaneGateCase {
        second_event: "$exception",
        rejected: true,
    })]
    #[case::second_allowlisted_event_passes(AiLaneGateCase {
        second_event: "$ai_span",
        rejected: false,
    })]
    #[tokio::test]
    async fn ai_mode_rejects_a_batch_carrying_anything_off_the_ai_lane(
        #[case] case: AiLaneGateCase,
    ) {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.capture_mode = crate::config::CaptureMode::Ai;

        let events = vec![
            create_test_event_with_name("$ai_generation", None, None, None),
            create_test_event_with_name(case.second_event, None, None, None),
        ];

        let sink = Arc::new(MockSink::new());
        let collector = Arc::new(CollectingEmitter::new());
        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                ingestion_warning_emitter: Some(collector.clone()),
                ..Default::default()
            },
        )
        .await;

        if !case.rejected {
            result.expect("an all-AI batch must be accepted");
            assert_eq!(sink.get_events().len(), 2);
            assert!(collector.emitted().is_empty());
            return;
        }

        let err = result.expect_err("the batch must be rejected");
        assert!(
            matches!(&err, CaptureError::NonAiEventOnAiLane(name) if name == case.second_event),
            "the error must name the offending event, got {err:?}"
        );
        // Rejecting the request means the whole batch is refused, including the
        // valid AI event ahead of the offender.
        assert!(sink.get_events().is_empty());

        // The 400 reaches the caller; the warning reaches the project owner.
        let emitted = collector.emitted();
        assert_eq!(emitted.len(), 1);
        assert_eq!(emitted[0].warning, WarningType::InvalidAiEvent);
    }

    /// The gate is scoped to capture-ai. On capture-analytics the same mixed
    /// batch is ordinary traffic: both events are accepted, each on its lane.
    #[tokio::test]
    async fn events_mode_accepts_a_batch_the_ai_lane_would_reject() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);

        let events = vec![
            create_test_event_with_name("$ai_generation", None, None, None),
            create_test_event_with_name("$pageview", None, None, None),
        ];

        let sink = Arc::new(MockSink::new());
        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .expect("capture-analytics must accept a mixed batch");

        let captured = sink.get_events();
        assert_eq!(captured.len(), 2);
        assert_eq!(
            captured
                .iter()
                .filter(|e| e.metadata.data_type == DataType::AiEvents)
                .count(),
            1
        );
    }

    /// Capture mode no longer changes which lane an AI event lands on: under `Ai`
    /// it diverts to `AiEvents` and the AI topic, exactly as under `Events`.
    #[tokio::test]
    async fn ai_mode_routes_ai_events_to_the_ai_lane_end_to_end() {
        use crate::sinks::kafka::{test_topics, KafkaSinkBase};
        use crate::sinks::producer::MockKafkaProducer;

        // 800-byte budget: the small event fits, the large one takes the
        // running total past it.
        let limiter = Some(Arc::new(GlobalRateLimiter::mock_budget(800)));

        let producer = MockKafkaProducer::new();
        let sink = Arc::new(KafkaSinkBase::with_producer(
            producer.clone(),
            test_topics(),
        ));

        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.capture_mode = crate::config::CaptureMode::Ai;

        let small_event = create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        );
        let mut oversized_event = create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        );
        oversized_event
            .properties
            .insert("$ai_input".to_string(), json!("x".repeat(500)));

        process_events(
            sink,
            Arc::new(TokenDropper::default()),
            None,
            router::HistoricalConfig::new(false, 1),
            None,
            None,
            None,
            None,
            vec![small_event, oversized_event],
            &context,
            limiter,
        )
        .await
        .expect("process_events must accept the batch even though one event is dropped");

        let records = producer.get_records();
        assert_eq!(
            records.len(),
            1,
            "only the under-budget event must reach the sink under Ai mode"
        );
        let topics = test_topics();
        let ai_topic = topics.topic_for(&crate::sinks::registry::Output::AiMain);
        assert_eq!(
            records[0].topic, ai_topic,
            "an allowlisted AI event diverts to the AI lane under Ai mode too"
        );
    }

    /// Under `Events` mode, only the diverted `AiEvents` lane is limited:
    /// AI traffic past the budget drops while same-sized `$pageview`s stay
    /// untouched however far over that budget the token already is.
    #[tokio::test]
    async fn events_mode_leaves_analytics_main_untouched_end_to_end() {
        let limiter = Some(Arc::new(GlobalRateLimiter::mock_budget(300)));

        let sink = Arc::new(MockSink::new());

        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);

        let oversized_ai_event = || {
            let mut event = create_test_event_with_name(
                "$ai_generation",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            );
            event
                .properties
                .insert("$ai_input".to_string(), json!("x".repeat(500)));
            event
        };
        let mut oversized_pageview = create_test_event_with_name(
            "$pageview",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        );
        oversized_pageview
            .properties
            .insert("$current_url".to_string(), json!("x".repeat(500)));

        process_events(
            sink.clone(),
            Arc::new(TokenDropper::default()),
            None,
            router::HistoricalConfig::new(false, 1),
            None,
            None,
            None,
            None,
            vec![oversized_ai_event(), oversized_pageview],
            &context,
            limiter,
        )
        .await
        .expect("process_events must accept the batch even though one event is dropped");

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1, "the over-budget AI event must drop");
        assert_eq!(
            captured[0].metadata.data_type,
            DataType::AnalyticsMain,
            "the same-sized $pageview must survive"
        );
    }

    /// A diverted AI event is governed by ai-scoped restrictions (the
    /// same slice the dedicated AI endpoints consult), not analytics ones:
    /// an ai-scoped DropEvent drops it, an analytics-scoped one must not
    /// cross pipelines into the AI lane.
    struct AiDropScopeCase {
        restriction_pipeline: Pipeline,
        expect_dropped: bool,
    }

    #[rstest]
    #[case::ai_scoped_drop_applies(AiDropScopeCase {
        restriction_pipeline: Pipeline::Ai,
        expect_dropped: true,
    })]
    #[case::analytics_scoped_drop_does_not_cross(AiDropScopeCase {
        restriction_pipeline: Pipeline::Analytics,
        expect_dropped: false,
    })]
    #[tokio::test]
    async fn test_process_events_drop_restriction_on_diverted_ai_events(
        #[case] case: AiDropScopeCase,
    ) {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        let service = EventRestrictionService::new(
            vec![Pipeline::Analytics, Pipeline::Ai],
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            case.restriction_pipeline,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        if case.expect_dropped {
            assert!(captured.is_empty());
        } else {
            assert_eq!(captured.len(), 1);
            assert_eq!(captured[0].metadata.data_type, DataType::AiEvents);
        }
    }

    /// An ai-scoped RedirectToTopic applies to a diverted AI event: the
    /// event keeps its AI lane, but the stamped redirect beats the data type
    /// in the sink so operators can reroute an AI token's traffic ad hoc,
    /// matching v1 where the restriction overwrites `Destination::AiEvents`
    /// with `Destination::Custom`.
    #[tokio::test]
    async fn test_process_events_restriction_redirect_applies_to_ai_events() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        let service = EventRestrictionService::new(
            vec![Pipeline::Analytics, Pipeline::Ai],
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Ai,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToTopic,
                scope: RestrictionScope::AllEvents,
                args: Some(json!({"topic": "custom_events_topic"})),
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.data_type, DataType::AiEvents);
        assert_eq!(
            captured[0].metadata.redirect_to_topic,
            Some("custom_events_topic".to_string())
        );
    }

    // ============ non-analytics data types bypass restrictions ============
    // The `EventRestrictionService` in analytics handlers is scoped to the
    // analytics pipeline. Events whose `data_type` belongs to a different
    // pipeline (exceptions → error tracking, heatmaps, client ingestion
    // warnings) must pass through the restriction stage untouched so that an
    // analytics-scoped DropEvent/RedirectToDlq/etc. does not cross pipelines.

    async fn process_single_with_drop_restriction(event_name: &str) -> Vec<ProcessedEvent> {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event_with_name(
            event_name,
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        sink.get_events()
    }

    #[rstest]
    #[case("$exception", DataType::ExceptionErrorTracking)]
    #[case("$$heatmap", DataType::HeatmapMain)]
    #[case("$$client_ingestion_warning", DataType::ClientIngestionWarning)]
    #[tokio::test]
    async fn test_non_analytics_events_bypass_drop_restriction(
        #[case] event_name: &str,
        #[case] expected_data_type: DataType,
    ) {
        let captured = process_single_with_drop_restriction(event_name).await;
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.data_type, expected_data_type);
    }

    #[tokio::test]
    async fn test_process_events_exception_bypasses_force_overflow_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event_with_name(
            "$exception",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![
                Restriction {
                    restriction_type: RestrictionType::ForceOverflow,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
                Restriction {
                    restriction_type: RestrictionType::SkipPersonProcessing,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
                Restriction {
                    restriction_type: RestrictionType::RedirectToDlq,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
            ],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(
            captured[0].metadata.data_type,
            DataType::ExceptionErrorTracking
        );
        assert!(!captured[0].metadata.force_overflow);
        assert!(!captured[0].metadata.skip_person_processing);
        assert!(!captured[0].metadata.redirect_to_dlq);
        assert!(captured[0].metadata.redirect_to_topic.is_none());
    }

    /// With an errortracking service configured, `$exception` events should be
    /// matched against errortracking-pipeline restrictions and dropped if so
    /// configured. Co-located analytics events must remain unaffected because
    /// they're matched against the (separate) analytics service.
    #[tokio::test]
    async fn test_process_events_errortracking_drop_only_affects_exceptions() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![
            create_test_event_with_name(
                "$exception",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
            create_test_event_with_name(
                "$pageview",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
        ];

        let sink = Arc::new(MockSink::new());

        // Single service serving both pipelines, with a DropEvent restriction
        // attached only to the errortracking pipeline.
        let service = EventRestrictionService::new(
            vec![Pipeline::Analytics, Pipeline::ErrorTracking],
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::ErrorTracking,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(
            captured.len(),
            1,
            "exception should be dropped, pageview kept"
        );
        assert_eq!(captured[0].metadata.data_type, DataType::AnalyticsMain);
        assert_eq!(captured[0].event.event, "$pageview");
    }

    /// Mirror image: an analytics-scoped DropEvent must drop analytics events
    /// while leaving `$exception` events untouched even though the same
    /// service is responsible for the errortracking pipeline (no entry there).
    #[tokio::test]
    async fn test_process_events_analytics_drop_does_not_cross_into_errortracking() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![
            create_test_event_with_name(
                "$exception",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
            create_test_event_with_name(
                "$pageview",
                Some("2023-01-01T11:00:00Z".to_string()),
                None,
                None,
            ),
        ];

        let sink = Arc::new(MockSink::new());

        let service = EventRestrictionService::new(
            vec![Pipeline::Analytics, Pipeline::ErrorTracking],
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(
            captured.len(),
            1,
            "pageview should be dropped, exception kept"
        );
        assert_eq!(
            captured[0].metadata.data_type,
            DataType::ExceptionErrorTracking
        );
        assert_eq!(captured[0].event.event, "$exception");
    }

    #[tokio::test]
    async fn test_process_events_analytics_historical_still_gets_restrictions() {
        // AnalyticsHistorical is part of the analytics pipeline, so restrictions
        // must still apply to it.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.historical_migration = true;
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        assert_eq!(sink.get_events().len(), 0);
    }

    // ============ overflow_reason stamping tests ============
    // These exercise the analytics pipeline's new overflow stamping stage
    // (the logic that used to live in the kafka sink's prepare_record).
    // Each case constructs a `process_events` call with a specific
    // `OverflowLimiter` configuration and asserts the stamped
    // `overflow_reason` on the sink-captured event.

    fn build_limiter(
        per_second: u32,
        burst: u32,
        keys_to_reroute: Option<String>,
        preserve_locality: bool,
    ) -> Arc<OverflowLimiter> {
        Arc::new(OverflowLimiter::new(
            NonZeroU32::new(per_second).unwrap(),
            NonZeroU32::new(burst).unwrap(),
            keys_to_reroute,
            preserve_locality,
        ))
    }

    #[tokio::test]
    async fn test_overflow_stamp_none_when_limiter_absent() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.overflow_reason, None);
    }

    #[tokio::test]
    async fn test_overflow_stamp_force_limited_when_token_in_reroute_list() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        // test_token is in the reroute list -> ForceLimited
        let limiter = build_limiter(10, 10, Some("test_token".to_string()), false);

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                overflow_limiter: Some(limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(
            captured[0].metadata.overflow_reason,
            Some(OverflowReason::ForceLimited)
        );
    }

    struct AiValveCase {
        ai_limiter_present: bool,
        expected_reason: Option<OverflowReason>,
    }

    /// End-to-end gate for the AI overflow valve: a diverted AI event
    /// is overflow-stamped only when the AI limiter is wired (setup builds
    /// it exactly when `CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC` is
    /// configured), and keeps its AI lane either way.
    #[rstest]
    #[case::limiter_present(AiValveCase {
        ai_limiter_present: true,
        expected_reason: Some(OverflowReason::ForceLimited),
    })]
    #[case::limiter_absent(AiValveCase {
        ai_limiter_present: false,
        expected_reason: None,
    })]
    #[tokio::test]
    async fn test_ai_events_overflow_stamp_gated_on_limiter_presence(#[case] case: AiValveCase) {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event_with_name(
            "$ai_generation",
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        let ai_limiter = case
            .ai_limiter_present
            .then(|| build_limiter(10, 10, Some("test_token".to_string()), false));

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                ai_events_overflow_limiter: ai_limiter,
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.data_type, DataType::AiEvents);
        assert_eq!(captured[0].metadata.overflow_reason, case.expected_reason);
    }

    #[tokio::test]
    async fn test_overflow_stamp_rate_limited_when_burst_exceeded() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
        ];

        let sink = Arc::new(MockSink::new());
        // burst of 1 -> first event passes, second event rate-limited
        let limiter = build_limiter(1, 1, None, true);

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                overflow_limiter: Some(limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 2);
        assert_eq!(captured[0].metadata.overflow_reason, None);
        assert_eq!(
            captured[1].metadata.overflow_reason,
            Some(OverflowReason::RateLimited {
                preserve_locality: true,
            })
        );
    }

    #[tokio::test]
    async fn test_overflow_stamp_preserve_locality_false_propagates() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
        ];

        let sink = Arc::new(MockSink::new());
        let limiter = build_limiter(1, 1, None, false);

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                overflow_limiter: Some(limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(
            captured[1].metadata.overflow_reason,
            Some(OverflowReason::RateLimited {
                preserve_locality: false,
            })
        );
    }

    #[tokio::test]
    async fn test_overflow_stamp_force_overflow_short_circuits_limiter() {
        // When event restrictions set force_overflow, the pipeline short-
        // circuits the limiter check and leaves overflow_reason = None. The
        // sink routes on force_overflow directly in this case.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        // Even with a limiter that would flag this token, force_overflow wins.
        let limiter = build_limiter(10, 10, Some("test_token".to_string()), false);

        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                overflow_limiter: Some(limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.force_overflow);
        assert_eq!(captured[0].metadata.overflow_reason, None);
    }

    #[tokio::test]
    async fn test_overflow_stamp_skipped_for_non_analytics_main() {
        // Historical, heatmap, exception, etc. events should never be stamped
        // with an overflow_reason even if the limiter would otherwise hit.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.historical_migration = true;
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        let limiter = build_limiter(10, 10, Some("test_token".to_string()), false);

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                overflow_limiter: Some(limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(
            captured[0].metadata.data_type,
            DataType::AnalyticsHistorical
        );
        assert_eq!(captured[0].metadata.overflow_reason, None);
    }

    // ============ global rate limiter x overflow limiter interplay ============

    #[tokio::test]
    async fn test_overflow_stamp_global_rate_limiter_and_overflow_interplay() {
        // Global RL stamps skip_person_processing + ForceLimited on both events;
        // the overflow limiter (burst=1) then overwrites event[1] with
        // RateLimited. Either way both reach overflow with the skip-person header.

        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);

        let events = vec![
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
        ];

        let sink = Arc::new(MockSink::new());

        // Global RL: limits (test_token, test_user) -> key `test_token:test_user`.
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));

        // Overflow limiter: burst=1, preserve_locality=true -> event[1]
        // stamped RateLimited{preserve_locality: true}.
        let overflow_limiter = build_limiter(1, 1, None, true);

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                global_rate_limiter: Some(global_limiter),
                overflow_limiter: Some(overflow_limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 2);

        // event[0]: global RL stamps skip_person_processing + ForceLimited; within
        // the overflow limiter's burst, so the ForceLimited stamp survives.
        assert!(
            captured[0].metadata.skip_person_processing,
            "event[0]: global RL should set skip_person_processing"
        );
        assert_eq!(
            captured[0].metadata.overflow_reason,
            Some(OverflowReason::ForceLimited),
            "event[0]: global RL reroutes the hot key to overflow via ForceLimited"
        );

        // event[1]: BOTH stamps fire. skip_person_processing from global RL,
        // overflow_reason=RateLimited{preserve_locality: true} from OverflowLimiter.
        assert!(
            captured[1].metadata.skip_person_processing,
            "event[1]: global RL should set skip_person_processing"
        );
        assert_eq!(
            captured[1].metadata.overflow_reason,
            Some(OverflowReason::RateLimited {
                preserve_locality: true,
            }),
            "event[1]: overflow limiter should stamp RateLimited{{preserve_locality: true}}"
        );
    }

    #[tokio::test]
    async fn global_rate_limit_reroutes_analytics_main_to_overflow() {
        // A globally rate-limited AnalyticsMain event is rerouted to overflow via
        // ForceLimited even with no OverflowLimiter configured.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        // historical_migration defaults to false -> AnalyticsMain.
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                global_rate_limiter: Some(global_limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.data_type, DataType::AnalyticsMain);
        assert!(captured[0].metadata.skip_person_processing);
        assert_eq!(
            captured[0].metadata.overflow_reason,
            Some(OverflowReason::ForceLimited),
            "globally limited AnalyticsMain should be rerouted to overflow"
        );
    }

    struct SdkWarningCase {
        attribution: Option<SdkAttribution>,
        expected_lib: &'static str,
        expected_lib_version: &'static str,
    }

    // The legacy path carries the bulk of rate-limited traffic, and it's the one
    // whose SDK attribution has to survive a snapshot taken back at batch
    // construction — by this stage the events are serialized.
    #[rstest::rstest]
    #[case::sdk_reported(SdkWarningCase {
        attribution: Some(SdkAttribution {
            lib: Some("web".to_string()),
            lib_version: Some("1.2.3".to_string()),
        }),
        expected_lib: "web",
        expected_lib_version: "1.2.3",
    })]
    #[case::sdk_absent(SdkWarningCase {
        attribution: None,
        expected_lib: "unknown",
        expected_lib_version: "unknown",
    })]
    #[tokio::test]
    async fn global_rate_limit_emits_a_warning_naming_the_hot_key(#[case] case: SdkWarningCase) {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        if let Some(attribution) = case.attribution {
            context.sdk_attribution = attribution;
        }
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));
        let collector = Arc::new(CollectingEmitter::new());

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                global_rate_limiter: Some(global_limiter),
                ingestion_warning_emitter: Some(collector.clone()),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let emitted = collector.emitted();
        assert_eq!(emitted.len(), 1);
        let w = &emitted[0];
        assert_eq!(w.token, "test_token");
        assert_eq!(w.warning, WarningType::HighVolumeDistinctId);
        assert_eq!(w.source, CAPTURE_LEGACY_RATE_LIMIT);
        assert_eq!(w.count, 1);
        assert_eq!(
            w.extra_details["distinctId"],
            serde_json::json!("test_user")
        );
        assert_eq!(w.extra_details["distinctIdCount"], serde_json::json!(1));
        assert_eq!(w.extra_details["lib"], serde_json::json!(case.expected_lib));
        assert_eq!(
            w.extra_details["libVersion"],
            serde_json::json!(case.expected_lib_version)
        );
        assert_eq!(w.extra_details["path"], serde_json::json!("/e/"));
    }

    #[tokio::test]
    async fn processing_abort_emits_warning_charging_the_full_batch() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let mut bad_event = create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None);
        bad_event.properties.remove("distinct_id");
        let events = vec![
            bad_event,
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
        ];

        let sink = Arc::new(MockSink::new());
        let collector = Arc::new(CollectingEmitter::new());

        let result = run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                ingestion_warning_emitter: Some(collector.clone()),
                ..Default::default()
            },
        )
        .await;

        assert!(matches!(result, Err(CaptureError::MissingDistinctId)));
        assert!(sink.get_events().is_empty(), "the whole batch is rejected");

        let emitted = collector.emitted();
        assert_eq!(emitted.len(), 1);
        let w = &emitted[0];
        assert_eq!(w.warning, WarningType::MissingDistinctId);
        assert_eq!(
            w.source,
            common_ingestion_warnings::CAPTURE_LEGACY_ANALYTICS
        );
        assert_eq!(w.token, "test_token");
        assert_eq!(w.count, 2, "an abort charges the full submitted batch");
    }

    #[tokio::test]
    async fn processing_abort_emits_nothing_for_non_warnable_errors() {
        // A sink failure aborts the request the same way, but it's ours to
        // fix, so the customer-facing warning must stay silent.
        struct RejectingSink;
        #[async_trait::async_trait]
        impl sinks::Event for RejectingSink {
            async fn send(&self, _event: ProcessedEvent) -> Result<(), CaptureError> {
                Err(CaptureError::RetryableSinkError)
            }
            async fn send_batch(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
                Err(CaptureError::RetryableSinkError)
            }
        }

        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let collector = Arc::new(CollectingEmitter::new());

        let result = run_pipeline(
            Arc::new(RejectingSink),
            events,
            &context,
            PipelineOptions {
                ingestion_warning_emitter: Some(collector.clone()),
                ..Default::default()
            },
        )
        .await;

        assert!(matches!(result, Err(CaptureError::RetryableSinkError)));
        assert!(collector.emitted().is_empty());
    }

    #[tokio::test]
    async fn global_rate_limit_is_skipped_when_person_processing_was_already_off() {
        // An ops restriction already took person processing away, so the limiter
        // is not consulted: it has nothing left to take, and the call would cost a
        // Redis round trip per event. The event keeps its lane and its partition
        // key, so the limiter's overflow reroute does not apply either. A hot key
        // under a restriction is left to the burst limiter downstream.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));
        let collector = Arc::new(CollectingEmitter::new());

        let service =
            EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                restriction_service: Some(service),
                global_rate_limiter: Some(global_limiter),
                ingestion_warning_emitter: Some(collector.clone()),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        assert!(collector.emitted().is_empty());
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.skip_person_processing);
        assert_eq!(
            captured[0].metadata.overflow_reason, None,
            "the limiter is skipped, so it does not reroute the key to overflow"
        );
    }

    #[tokio::test]
    async fn global_rate_limit_does_not_overflow_historical_events() {
        // Invariant: a globally rate-limited AnalyticsHistorical event gets person
        // processing disabled but is never rerouted to overflow.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.historical_migration = true; // classifies events as AnalyticsHistorical
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                global_rate_limiter: Some(global_limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(
            captured[0].metadata.data_type,
            DataType::AnalyticsHistorical
        );
        // Person processing disabled...
        assert!(captured[0].metadata.skip_person_processing);
        // ...but NOT rerouted to overflow.
        assert_eq!(captured[0].metadata.overflow_reason, None);
        assert!(!captured[0].metadata.force_overflow);
    }

    // ==================== Import-mode legacy path tests ======================

    #[tokio::test]
    async fn import_mode_drops_non_historical_batch() {
        // Import mode ingests only backfills: a batch without historical_migration
        // must be dropped (200, nothing published) so live traffic can't leak in.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.capture_mode = crate::config::CaptureMode::Import;
        // historical_migration defaults to false — this batch must be dropped.
        let events = vec![
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
        ];

        let sink = Arc::new(MockSink::new());

        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .unwrap();

        assert_eq!(
            sink.get_events().len(),
            0,
            "non-historical batch must be fully dropped in Import mode"
        );
    }

    #[tokio::test]
    async fn import_mode_processes_historical_batch() {
        // A properly flagged historical batch flows through Import mode to the sink.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.capture_mode = crate::config::CaptureMode::Import;
        context.historical_migration = true;
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert_eq!(
            captured[0].metadata.data_type,
            DataType::AnalyticsHistorical
        );
    }

    #[tokio::test]
    async fn import_mode_skips_global_rate_limiter() {
        // Import mode must never apply the global rate limiter. Same hot key that
        // sets skip_person_processing in Events mode (see
        // global_rate_limit_does_not_overflow_historical_events) must leave the
        // event untouched here. Uses a historical batch so it isn't dropped first.
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut context = create_test_context(now, None);
        context.capture_mode = crate::config::CaptureMode::Import;
        context.historical_migration = true;
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));

        run_pipeline(
            sink.clone(),
            events,
            &context,
            PipelineOptions {
                global_rate_limiter: Some(global_limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(
            !captured[0].metadata.skip_person_processing,
            "GRL must be skipped in Import mode — person processing must stay enabled"
        );
        assert_eq!(captured[0].metadata.overflow_reason, None);
    }

    // ============ end-to-end pipeline -> real KafkaSinkBase tests ============
    // These catch pipeline-to-sink contract drift that neither side's unit
    // tests alone cover: stamp metadata in pipeline, ensure the real sink
    // reads the metadata and produces the expected topic, key, and headers.

    use crate::sinks::kafka::{test_topics, KafkaSinkBase};
    use crate::sinks::producer::MockKafkaProducer;

    #[tokio::test]
    async fn e2e_force_limited_pipeline_to_sink_routes_to_overflow_with_null_key_and_header() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let producer = MockKafkaProducer::new();
        let sink = Arc::new(KafkaSinkBase::with_producer(
            producer.clone(),
            test_topics(),
        ));
        // test_token in reroute list -> ForceLimited stamped in pipeline.
        let limiter = build_limiter(10, 10, Some("test_token".to_string()), false);

        run_pipeline(
            sink,
            events,
            &context,
            PipelineOptions {
                overflow_limiter: Some(limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let records = producer.get_records();
        assert_eq!(records.len(), 1);
        assert_eq!(
            records[0].topic, "events_plugin_ingestion_overflow",
            "ForceLimited must route to overflow topic"
        );
        assert_eq!(
            records[0].key, None,
            "ForceLimited must drop partition key (broad-fanout semantics)"
        );
        assert_eq!(
            records[0].headers.force_disable_person_processing,
            Some(true),
            "ForceLimited must set force_disable_person_processing header"
        );
    }

    /// A person-on burst keeps its key on either locality setting: the
    /// overflow consumer updates persons keyed on distinct id, so spreading
    /// one distinct id across partitions would contend those updates.
    #[rstest]
    #[case::preserving_locality(true)]
    #[case::spreading(false)]
    #[tokio::test]
    async fn e2e_rate_limited_pipeline_to_sink_keeps_key_while_person_on(
        #[case] preserve_locality: bool,
    ) {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
            create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None),
        ];

        let producer = MockKafkaProducer::new();
        let sink = Arc::new(KafkaSinkBase::with_producer(
            producer.clone(),
            test_topics(),
        ));
        // burst=1 => event[1] stamped RateLimited { preserve_locality }.
        let limiter = build_limiter(1, 1, None, preserve_locality);

        run_pipeline(
            sink,
            events,
            &context,
            PipelineOptions {
                overflow_limiter: Some(limiter),
                ..Default::default()
            },
        )
        .await
        .unwrap();

        let records = producer.get_records();
        assert_eq!(records.len(), 2);
        assert_eq!(
            records[0].topic, "events_plugin_ingestion",
            "event[0]: within burst -> main topic"
        );
        assert_eq!(
            records[1].topic, "events_plugin_ingestion_overflow",
            "event[1]: over burst -> overflow topic"
        );
        assert!(
            records[1].key.is_some(),
            "a person-on burst must keep its partition key"
        );
        assert!(
            records[1].headers.force_disable_person_processing.is_none(),
            "RateLimited (non-Force) must NOT set force_disable_person_processing"
        );
    }

    // ============ heatmap redirect tests ============

    /// Two shapes of input event qualify for a heatmap redirect: an event
    /// carrying `$heatmap_data` directly, or an event carrying the
    /// scroll-depth pair (`$prev_pageview_pathname` + `$current_url`) which
    /// the heatmap pipeline turns into a synthetic `scrolldepth` data point.
    /// The pipeline must handle both identically end-to-end.
    #[derive(Clone, Copy, Debug)]
    enum HeatmapShape {
        HeatmapData,
        ScrollDepth,
    }

    fn build_heatmap_carrier_event(shape: HeatmapShape) -> RawEvent {
        let mut properties = HashMap::new();
        properties.insert("distinct_id".to_string(), json!("test_user"));
        properties.insert("$viewport_height".to_string(), json!(900));
        properties.insert("$viewport_width".to_string(), json!(1440));
        properties.insert("$session_id".to_string(), json!("session-abc"));
        properties.insert("$current_url".to_string(), json!("https://example.com"));
        // Cookieless identity inputs. Carrier events emitted by the JS SDK in
        // cookieless mode set these, and the ingestion pipeline drops events
        // with `cookieless_missing_user_agent` if `$raw_user_agent` is absent
        // on a `$cookieless_mode` event — so the redirect must carry them.
        properties.insert(
            "$raw_user_agent".to_string(),
            json!("Mozilla/5.0 (test agent)"),
        );
        properties.insert("$ip".to_string(), json!("203.0.113.7"));
        properties.insert("$host".to_string(), json!("example.com"));
        properties.insert("$timezone".to_string(), json!("Europe/London"));
        properties.insert("$cookieless_extra".to_string(), json!("extra-hash-input"));
        properties.insert(
            "other_prop".to_string(),
            json!("should_not_appear_in_redirect"),
        );

        match shape {
            HeatmapShape::HeatmapData => {
                properties.insert(
                    "$heatmap_data".to_string(),
                    json!({"https://example.com": [{"x": 100, "y": 200, "target_fixed": false, "type": "click"}]}),
                );
            }
            HeatmapShape::ScrollDepth => {
                properties.insert("$prev_pageview_pathname".to_string(), json!("/old"));
                properties.insert("$prev_pageview_max_scroll".to_string(), json!(0.42));
            }
        }

        let timestamp = "2023-01-01T11:00:00Z";
        RawEvent {
            uuid: Some(uuid_v7_from_datetime(
                DateTime::parse_from_rfc3339(timestamp).unwrap(),
            )),
            distinct_id: None,
            event: "$pageview".to_string(),
            properties,
            timestamp: Some(timestamp.to_string()),
            offset: None,
            set: None,
            set_once: None,
            token: Some("test_token".to_string()),
        }
    }

    struct HeatmapDataCase {
        property_keys: &'static [&'static str],
        expect_has_heatmap_data: bool,
    }

    #[rstest]
    #[case::heatmap_data_present(HeatmapDataCase {
        property_keys: &["$heatmap_data"],
        expect_has_heatmap_data: true,
    })]
    #[case::scroll_depth_pair(HeatmapDataCase {
        property_keys: &["$prev_pageview_pathname", "$current_url"],
        expect_has_heatmap_data: true,
    })]
    #[case::heatmap_data_with_scroll_depth(HeatmapDataCase {
        property_keys: &["$heatmap_data", "$prev_pageview_pathname", "$current_url"],
        expect_has_heatmap_data: true,
    })]
    #[case::only_prev_pageview_pathname(HeatmapDataCase {
        property_keys: &["$prev_pageview_pathname"],
        expect_has_heatmap_data: false,
    })]
    #[case::only_current_url(HeatmapDataCase {
        property_keys: &["$current_url"],
        expect_has_heatmap_data: false,
    })]
    #[case::no_heatmap_properties(HeatmapDataCase {
        property_keys: &[],
        expect_has_heatmap_data: false,
    })]
    fn test_has_heatmap_data(#[case] case: HeatmapDataCase) {
        let mut properties = HashMap::new();
        properties.insert("distinct_id".to_string(), json!("test_user"));
        for key in case.property_keys {
            properties.insert((*key).to_string(), json!("anything"));
        }

        let event = RawEvent {
            uuid: None,
            distinct_id: None,
            event: "$pageview".to_string(),
            properties,
            timestamp: None,
            offset: None,
            set: None,
            set_once: None,
            token: Some("test_token".to_string()),
        };

        assert_eq!(has_heatmap_data(&event), case.expect_has_heatmap_data);
    }

    #[test]
    fn test_create_heatmap_redirect_properties_and_metadata() {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let event = build_heatmap_carrier_event(HeatmapShape::HeatmapData);

        let redirect =
            create_heatmap_redirect(&event, router::HistoricalConfig::new(false, 1), &context)
                .unwrap()
                .expect("redirect should be created when distinct_id is resolvable");

        assert_eq!(redirect.metadata.data_type, DataType::HeatmapMain);
        assert_eq!(redirect.metadata.event_name, "$$heatmap");
        assert!(!redirect.metadata.skip_heatmap_processing);
        assert_eq!(redirect.event.event, "$$heatmap");
        assert_ne!(redirect.event.uuid, event.uuid.unwrap());

        let data: RawEvent = serde_json::from_str(&redirect.event.data).unwrap();
        assert!(data.properties.contains_key("$heatmap_data"));
        assert!(data.properties.contains_key("$viewport_height"));
        assert!(data.properties.contains_key("$viewport_width"));
        assert!(data.properties.contains_key("$session_id"));
        assert!(data.properties.contains_key("$current_url"));
        // Cookieless identity inputs must survive the redirect; without them
        // the ingestion pipeline drops cookieless-mode heatmap events.
        assert!(data.properties.contains_key("$raw_user_agent"));
        assert!(data.properties.contains_key("$ip"));
        assert!(data.properties.contains_key("$host"));
        assert!(data.properties.contains_key("$timezone"));
        assert!(data.properties.contains_key("$cookieless_extra"));
        assert_eq!(data.distinct_id, Some(json!("test_user")));
        assert!(
            !data.properties.contains_key("distinct_id"),
            "distinct_id lives on the top-level field, not in properties"
        );
        assert!(
            !data.properties.contains_key("other_prop"),
            "redirect should only contain heatmap and cookieless-identity properties"
        );
    }

    /// A `$cookieless_mode` event with heatmap data must produce a redirect
    /// that carries every property the cookieless identity hash reads in
    /// `nodejs/src/ingestion/cookieless/cookieless-manager.ts`. Without
    /// these, the ingestion pipeline emits `cookieless_missing_user_agent`
    /// against the redirect and silently drops every heatmap/scroll-depth
    /// data point from cookieless-mode customers.
    #[test]
    fn test_create_heatmap_redirect_preserves_cookieless_identity_inputs() {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let mut event = build_heatmap_carrier_event(HeatmapShape::HeatmapData);
        event
            .properties
            .insert("$cookieless_mode".to_string(), json!(true));

        let redirect =
            create_heatmap_redirect(&event, router::HistoricalConfig::new(false, 1), &context)
                .unwrap()
                .expect("redirect should be created");

        let data: RawEvent = serde_json::from_str(&redirect.event.data).unwrap();
        for key in [
            "$raw_user_agent",
            "$ip",
            "$host",
            "$timezone",
            "$cookieless_extra",
            "$cookieless_mode",
        ] {
            assert!(
                data.properties.contains_key(key),
                "cookieless redirect must carry {key}"
            );
            assert_eq!(
                data.properties.get(key),
                event.properties.get(key),
                "cookieless redirect must preserve {key} value verbatim"
            );
        }
    }

    #[test]
    fn test_create_heatmap_redirect_returns_none_when_distinct_id_missing() {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let mut event = build_heatmap_carrier_event(HeatmapShape::HeatmapData);
        event.distinct_id = None;
        event.properties.remove("distinct_id");

        let result =
            create_heatmap_redirect(&event, router::HistoricalConfig::new(false, 1), &context)
                .unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_create_heatmap_redirect_resolves_distinct_id_from_properties() {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let event = build_heatmap_carrier_event(HeatmapShape::HeatmapData);
        // Carrier event has distinct_id only in properties (top-level is None).
        assert!(event.distinct_id.is_none());

        let redirect =
            create_heatmap_redirect(&event, router::HistoricalConfig::new(false, 1), &context)
                .unwrap()
                .expect("redirect should fall back to properties for distinct_id");

        let data: RawEvent = serde_json::from_str(&redirect.event.data).unwrap();
        assert_eq!(data.distinct_id, Some(json!("test_user")));
    }

    #[rstest]
    #[case::heatmap_data(HeatmapShape::HeatmapData)]
    #[case::scroll_depth(HeatmapShape::ScrollDepth)]
    #[tokio::test]
    async fn test_process_events_creates_heatmap_redirect(#[case] shape: HeatmapShape) {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let events = vec![build_heatmap_carrier_event(shape)];

        let sink = Arc::new(MockSink::new());

        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 2, "should produce original + redirect");

        let original = &captured[0];
        assert_eq!(original.event.event, "$pageview");
        assert!(original.metadata.skip_heatmap_processing);
        let orig_data: RawEvent = serde_json::from_str(&original.event.data).unwrap();
        assert!(
            !orig_data.properties.contains_key("$heatmap_data"),
            "$heatmap_data must never be on the original (stripped if present, never added if not)"
        );
        assert!(
            orig_data.properties.contains_key("$current_url"),
            "non-$heatmap_data properties remain on original"
        );

        let redirect = &captured[1];
        assert_eq!(redirect.event.event, "$$heatmap");
        assert_eq!(redirect.metadata.data_type, DataType::HeatmapMain);
        assert!(!redirect.metadata.skip_heatmap_processing);
    }

    #[tokio::test]
    async fn test_process_events_no_redirect_for_heatmap_event() {
        let now = Utc::now();
        let context = create_test_context(now, None);

        let mut event = build_heatmap_carrier_event(HeatmapShape::HeatmapData);
        event.event = "$$heatmap".to_string();
        let events = vec![event];

        let sink = Arc::new(MockSink::new());

        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .unwrap();

        let captured = sink.get_events();
        assert_eq!(
            captured.len(),
            1,
            "$$heatmap events should not produce a redirect"
        );
        assert_eq!(captured[0].metadata.data_type, DataType::HeatmapMain);
        assert!(!captured[0].metadata.skip_heatmap_processing);
    }

    #[tokio::test]
    async fn test_process_events_no_redirect_without_heatmap_data() {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let events = vec![create_test_event(
            Some("2023-01-01T11:00:00Z".to_string()),
            None,
            None,
        )];

        let sink = Arc::new(MockSink::new());

        run_pipeline(sink.clone(), events, &context, PipelineOptions::default())
            .await
            .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
        assert!(!captured[0].metadata.skip_heatmap_processing);
    }

    /// End-to-end pipeline-to-kafka contract for the heatmap redirect: a
    /// non-`$$heatmap` event that qualifies as a heatmap carrier produces
    /// two kafka records — the stripped original on the events topic with
    /// the `skip_heatmap_processing` header, and a `$$heatmap` redirect on
    /// the heatmaps topic carrying the heatmap properties. Both qualifying
    /// shapes (explicit `$heatmap_data`, and the scroll-depth pair) must
    /// produce identical end-to-end behavior except for which heatmap-
    /// payload properties end up on the redirect.
    #[rstest]
    #[case::heatmap_data(HeatmapShape::HeatmapData)]
    #[case::scroll_depth(HeatmapShape::ScrollDepth)]
    #[tokio::test]
    async fn e2e_heatmap_redirect_strips_original_and_routes_redirect(#[case] shape: HeatmapShape) {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let event = build_heatmap_carrier_event(shape);
        let original_uuid = event.uuid.unwrap();
        let events = vec![event];

        let producer = MockKafkaProducer::new();
        let sink = Arc::new(KafkaSinkBase::with_producer(
            producer.clone(),
            test_topics(),
        ));

        run_pipeline(sink, events, &context, PipelineOptions::default())
            .await
            .unwrap();

        let records = producer.get_records();
        assert_eq!(
            records.len(),
            2,
            "should produce original + heatmap redirect"
        );

        let original = records
            .iter()
            .find(|r| r.topic == "events_plugin_ingestion")
            .expect("original event should land on the main events topic");
        let redirect = records
            .iter()
            .find(|r| r.topic == "heatmaps")
            .expect("redirect should land on the heatmaps topic");

        // ---- original on events topic ----
        assert_eq!(
            original.headers.skip_heatmap_processing,
            Some(true),
            "original must carry skip_heatmap_processing=true so the events pipeline skips extraction"
        );
        assert_eq!(
            original.headers.event.as_deref(),
            Some("$pageview"),
            "original keeps its event name"
        );
        assert_eq!(
            original.headers.uuid.as_deref(),
            Some(original_uuid.to_string().as_str()),
            "original keeps its uuid"
        );

        let original_captured: CapturedEvent =
            serde_json::from_slice(&original.payload).expect("payload should be a CapturedEvent");
        let original_raw: RawEvent = serde_json::from_str(&original_captured.data)
            .expect("data field should be a serialized RawEvent");
        assert!(
            !original_raw.properties.contains_key("$heatmap_data"),
            "$heatmap_data must never be on the original (stripped if present, never added otherwise)"
        );
        // Other heatmap-adjacent properties must remain — web analytics queries depend on them.
        assert!(original_raw.properties.contains_key("$current_url"));
        assert!(original_raw.properties.contains_key("$viewport_height"));
        assert!(original_raw.properties.contains_key("$viewport_width"));
        assert!(original_raw.properties.contains_key("$session_id"));
        // Unrelated user properties must also remain on the original.
        assert_eq!(
            original_raw.properties.get("other_prop"),
            Some(&json!("should_not_appear_in_redirect")),
        );

        // ---- redirect on heatmaps topic ----
        assert_eq!(
            redirect.headers.skip_heatmap_processing, None,
            "redirect must NOT set skip_heatmap_processing — the heatmaps pipeline is the consumer"
        );
        assert_eq!(
            redirect.headers.event.as_deref(),
            Some("$$heatmap"),
            "redirect must be renamed to $$heatmap"
        );
        assert_ne!(
            redirect.headers.uuid.as_deref(),
            Some(original_uuid.to_string().as_str()),
            "redirect must have a fresh uuid so it doesn't dedupe against the original"
        );

        let redirect_captured: CapturedEvent =
            serde_json::from_slice(&redirect.payload).expect("payload should be a CapturedEvent");
        assert_eq!(redirect_captured.event, "$$heatmap");
        let redirect_raw: RawEvent = serde_json::from_str(&redirect_captured.data)
            .expect("data field should be a serialized RawEvent");
        assert_eq!(redirect_raw.event, "$$heatmap");

        // Properties carried by every heatmap redirect, regardless of shape.
        assert_eq!(
            redirect_raw.properties.get("$viewport_height"),
            Some(&json!(900)),
        );
        assert_eq!(
            redirect_raw.properties.get("$viewport_width"),
            Some(&json!(1440)),
        );
        assert_eq!(
            redirect_raw.properties.get("$session_id"),
            Some(&json!("session-abc")),
        );
        assert_eq!(
            redirect_raw.properties.get("$current_url"),
            Some(&json!("https://example.com")),
        );
        // Cookieless identity inputs must survive the redirect end-to-end.
        // Without them the ingestion pipeline drops the redirect with
        // `cookieless_missing_user_agent` before the heatmap extractor runs.
        assert_eq!(
            redirect_raw.properties.get("$raw_user_agent"),
            Some(&json!("Mozilla/5.0 (test agent)")),
        );
        assert_eq!(
            redirect_raw.properties.get("$ip"),
            Some(&json!("203.0.113.7")),
        );
        assert_eq!(
            redirect_raw.properties.get("$host"),
            Some(&json!("example.com")),
        );
        assert_eq!(
            redirect_raw.properties.get("$timezone"),
            Some(&json!("Europe/London")),
        );
        assert_eq!(
            redirect_raw.properties.get("$cookieless_extra"),
            Some(&json!("extra-hash-input")),
        );
        // distinct_id is required for routing-key generation; it's pre-resolved
        // onto the top-level field rather than left in properties.
        assert_eq!(redirect_raw.distinct_id, Some(json!("test_user")));
        assert!(
            !redirect_raw.properties.contains_key("distinct_id"),
            "distinct_id is on the top-level field, not in properties"
        );
        // The redirect must NOT carry unrelated user properties — only what
        // the heatmap pipeline reads plus the cookieless identity inputs.
        assert!(
            !redirect_raw.properties.contains_key("other_prop"),
            "redirect must only carry heatmap and cookieless-identity properties"
        );

        // Shape-specific payload properties.
        match shape {
            HeatmapShape::HeatmapData => {
                assert_eq!(
                    redirect_raw.properties.get("$heatmap_data"),
                    Some(&json!({
                        "https://example.com": [{
                            "x": 100,
                            "y": 200,
                            "target_fixed": false,
                            "type": "click",
                        }]
                    })),
                );
                assert!(
                    !redirect_raw
                        .properties
                        .contains_key("$prev_pageview_pathname"),
                    "scroll-depth properties absent on heatmap-data shape"
                );
            }
            HeatmapShape::ScrollDepth => {
                assert!(
                    !redirect_raw.properties.contains_key("$heatmap_data"),
                    "scroll-depth shape doesn't carry $heatmap_data — the heatmap pipeline derives it from $prev_pageview_*"
                );
                assert_eq!(
                    redirect_raw.properties.get("$prev_pageview_pathname"),
                    Some(&json!("/old")),
                );
                assert_eq!(
                    redirect_raw.properties.get("$prev_pageview_max_scroll"),
                    Some(&json!(0.42)),
                );
            }
        }
    }

    fn event_with_distinct_id(distinct_id: &str) -> RawEvent {
        let mut event = create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None);
        event
            .properties
            .insert("distinct_id".to_string(), json!(distinct_id));
        event
    }

    async fn run_batch_collecting_warnings(
        events: Vec<RawEvent>,
        sink: Arc<dyn sinks::Event + Send + Sync>,
    ) -> (
        Result<(), CaptureError>,
        Vec<common_ingestion_warnings::test_support::EmittedWarning>,
    ) {
        run_batch_collecting_warnings_with_dropper(
            events,
            sink,
            Arc::new(limiters::token_dropper::TokenDropper::default()),
        )
        .await
    }

    async fn run_batch_collecting_warnings_with_dropper(
        events: Vec<RawEvent>,
        sink: Arc<dyn sinks::Event + Send + Sync>,
        dropper: Arc<limiters::token_dropper::TokenDropper>,
    ) -> (
        Result<(), CaptureError>,
        Vec<common_ingestion_warnings::test_support::EmittedWarning>,
    ) {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let collector = Arc::new(CollectingEmitter::new());

        let result = run_pipeline(
            sink,
            events,
            &context,
            PipelineOptions {
                dropper,
                ingestion_warning_emitter: Some(collector.clone()),
                ..Default::default()
            },
        )
        .await;

        (result, collector.emitted())
    }

    #[tokio::test]
    async fn truncated_distinct_id_ingests_the_event_and_emits_one_warning() {
        let long_id = "x".repeat(250);
        let events = vec![
            event_with_distinct_id(&long_id),
            event_with_distinct_id("normal_user"),
        ];

        let sink = Arc::new(MockSink::new());
        let (result, emitted) = run_batch_collecting_warnings(events, sink.clone()).await;
        result.unwrap();

        let sent = sink.get_events();
        assert_eq!(sent.len(), 2, "both events must still be ingested");
        assert_eq!(sent[0].event.distinct_id, long_id[..200]);

        assert_eq!(emitted.len(), 1);
        let w = &emitted[0];
        assert_eq!(w.warning, WarningType::DistinctIdTruncated);
        assert_eq!(
            w.source,
            common_ingestion_warnings::CAPTURE_LEGACY_ANALYTICS
        );
        assert_eq!(w.token, "test_token");
        assert_eq!(w.count, 1);
        assert_eq!(w.extra_details["distinctId"], json!(long_id[..200]));
        assert_eq!(w.extra_details["distinctIdLength"], json!(250));
        assert_eq!(
            w.extra_details["eventUuid"],
            json!(sent[0].event.uuid),
            "sample must name the truncated event, not the healthy one"
        );
    }

    #[tokio::test]
    async fn multiple_truncated_distinct_ids_group_into_one_anonymous_warning() {
        let events = vec![
            event_with_distinct_id(&"x".repeat(250)),
            event_with_distinct_id(&"y".repeat(300)),
        ];

        let (result, emitted) =
            run_batch_collecting_warnings(events, Arc::new(MockSink::new())).await;
        result.unwrap();

        assert_eq!(emitted.len(), 1);
        let w = &emitted[0];
        assert_eq!(w.warning, WarningType::DistinctIdTruncated);
        assert_eq!(w.count, 2);
        // With several truncated ids any single sample would be an arbitrary
        // pick, so the identifier details are omitted.
        assert!(!w.extra_details.contains_key("distinctId"));
        assert!(!w.extra_details.contains_key("distinctIdLength"));
        assert!(!w.extra_details.contains_key("eventUuid"));
    }

    #[tokio::test]
    async fn no_truncation_warning_for_ids_within_the_cap() {
        let events = vec![event_with_distinct_id(&"z".repeat(200))];

        let (result, emitted) =
            run_batch_collecting_warnings(events, Arc::new(MockSink::new())).await;
        result.unwrap();

        assert!(emitted.is_empty());
    }

    #[tokio::test]
    async fn truncation_warning_counts_only_events_that_survive_the_filters() {
        // The warning means "ingested with a modified distinct_id", so a
        // truncated event the token dropper (or a restriction) removes must
        // not be counted or named as the sample.
        let dropped_id = "x".repeat(250);
        let surviving_id = "y".repeat(300);
        // The dropper matches on the post-truncation id, since that is what
        // the processed event carries.
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::new(&format!(
            "test_token:{}",
            &dropped_id[..200]
        )));

        // Only truncated event is dropped: nothing was ingested-but-modified,
        // so no warning at all.
        let sink = Arc::new(MockSink::new());
        let (result, emitted) = run_batch_collecting_warnings_with_dropper(
            vec![
                event_with_distinct_id(&dropped_id),
                event_with_distinct_id("normal_user"),
            ],
            sink.clone(),
            dropper.clone(),
        )
        .await;
        result.unwrap();
        assert_eq!(sink.get_events().len(), 1);
        assert!(emitted.is_empty());

        // One truncated event dropped, another survives: count and sample
        // must reflect only the survivor.
        let sink = Arc::new(MockSink::new());
        let (result, emitted) = run_batch_collecting_warnings_with_dropper(
            vec![
                event_with_distinct_id(&dropped_id),
                event_with_distinct_id(&surviving_id),
            ],
            sink.clone(),
            dropper,
        )
        .await;
        result.unwrap();
        let sent = sink.get_events();
        assert_eq!(sent.len(), 1);

        assert_eq!(emitted.len(), 1);
        let w = &emitted[0];
        assert_eq!(w.count, 1);
        assert_eq!(w.extra_details["distinctId"], json!(surviving_id[..200]));
        assert_eq!(w.extra_details["distinctIdLength"], json!(300));
        assert_eq!(w.extra_details["eventUuid"], json!(sent[0].event.uuid));
    }

    #[tokio::test]
    async fn truncation_warning_is_not_emitted_when_the_sink_rejects_the_batch() {
        // The warning means "ingested with a modified distinct_id"; a batch
        // the sink refused was not ingested, so emitting would misreport.
        struct RejectingSink;
        #[async_trait::async_trait]
        impl sinks::Event for RejectingSink {
            async fn send(&self, _event: ProcessedEvent) -> Result<(), CaptureError> {
                Err(CaptureError::RetryableSinkError)
            }
            async fn send_batch(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
                Err(CaptureError::RetryableSinkError)
            }
        }

        let events = vec![event_with_distinct_id(&"x".repeat(250))];

        let (result, emitted) =
            run_batch_collecting_warnings(events, Arc::new(RejectingSink)).await;
        assert!(matches!(result, Err(CaptureError::RetryableSinkError)));

        assert!(emitted.is_empty());
    }
}
