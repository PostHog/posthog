//! Analytics event processing
//!
//! This module handles processing of regular analytics events (pageviews, custom events,
//! exceptions, etc.) as opposed to recordings (session replay).

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono::DateTime;
use common_types::{CapturedEvent, RawEvent};
use limiters::token_dropper::TokenDropper;
use metrics::counter;
use serde_json;
use tracing::{error, instrument, warn, Span};

use limiters::overflow::OverflowLimiter;

use crate::{
    api::CaptureError,
    debug_or_info,
    event_restrictions::{EventContext as RestrictionEventContext, EventRestrictionService},
    events::overflow_stamping::stamp_overflow_reason,
    global_rate_limiter::{GlobalRateLimitKey, GlobalRateLimiter},
    prometheus::{report_clock_skew, report_dropped_events},
    router, sinks,
    utils::uuid_v7_from_datetime,
    v0_request::{
        DataType, OverflowReason, ProcessedEvent, ProcessedEventMetadata, ProcessingContext,
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

/// Process a single analytics event from RawEvent to ProcessedEvent
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
        distinct_id: event
            .extract_distinct_id()
            .ok_or(CaptureError::MissingDistinctId)?,
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
/// All routing policy lives here: token dropping, event restrictions, global
/// rate limiting (per `token:distinct_id`), historical rerouting, and
/// per-key overflow rerouting via [`OverflowLimiter`]. Overflow stamping
/// goes through the shared [`stamp_overflow_reason`] helper, which the AI
/// (`ai_endpoint::ai_handler`) and OTEL (`otel::otel_handler`) paths also
/// call so every `DataType::AnalyticsMain` event gets identical limiter
/// semantics regardless of entry point. The kafka sink is a pure mechanism
/// layer — it reads `ProcessedEventMetadata::overflow_reason`,
/// `force_overflow`, `redirect_to_dlq`, and `redirect_to_topic` to decide
/// which topic and key to produce to.
#[instrument(skip_all, fields(events = events.len(), request_id))]
#[allow(clippy::too_many_arguments)]
pub async fn process_events(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    dropper: Arc<TokenDropper>,
    restriction_service: Option<EventRestrictionService>,
    historical_cfg: router::HistoricalConfig,
    global_rate_limiter: Option<Arc<GlobalRateLimiter>>,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    events: Vec<RawEvent>,
    context: &ProcessingContext,
) -> Result<(), CaptureError> {
    let chatty_debug_enabled = context.chatty_debug_enabled;

    Span::current().record("request_id", &context.request_id);
    Span::current().record("is_mirror_deploy", context.is_mirror_deploy);

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
        if raw.event == "$$heatmap" || !has_heatmap_data(&raw) {
            events.push(process_single_event(&raw, historical_cfg, context)?);
            continue;
        }
        let redirect = match create_heatmap_redirect(&raw, historical_cfg, context) {
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
        events.push(redirect);
    }

    debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "created ProcessedEvents batch");

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
    // through unrestricted.
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

    // Per-(token, distinct_id) global rate limiting: skip person processing for
    // hot distinct_ids and reroute AnalyticsMain events to overflow.
    if let Some(ref limiter) = global_rate_limiter {
        let mut limited_distinct_ids: HashSet<&str> = HashSet::new();
        let mut limited_event_count: u64 = 0;
        for event in events.iter_mut() {
            let cache_key =
                GlobalRateLimitKey::TokenDistinctId(&context.token, &event.event.distinct_id)
                    .to_cache_key();
            if limiter.is_limited(&cache_key, 1).await.is_some() {
                event.metadata.skip_person_processing = true;
                // Reroute the hot key to overflow. AnalyticsMain only: historical
                // never overflows and only AnalyticsMain acts on overflow_reason.
                if event.metadata.data_type == DataType::AnalyticsMain {
                    event.metadata.overflow_reason = Some(OverflowReason::ForceLimited);
                }
                limited_distinct_ids.insert(&event.event.distinct_id);
                limited_event_count += 1;
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
    }

    // Overflow routing stage. This used to live in the kafka sink's
    // prepare_record; moving it here keeps the sink free of policy and
    // co-locates overflow with every other pipeline-level routing decision.
    // The stamping helper is shared with the AI (`ai_endpoint::ai_handler`)
    // and OTEL (`otel::otel_handler`) paths so every handler that emits
    // `DataType::AnalyticsMain` events gets identical limiter semantics and
    // metric labels — see `events::overflow_stamping`.
    stamp_overflow_reason(&mut events, overflow_limiter.as_ref());

    if events.is_empty() {
        return Ok(());
    }

    if events.len() == 1 {
        sink.send(events[0].clone()).await?;
    } else {
        sink.send_batch(events).await?;
    }

    debug_or_info!(chatty_debug_enabled, context=?context, "sent analytics events");

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{OverflowReason, ProcessingContext};
    use chrono::{DateTime, TimeZone, Utc};
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

        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let processed = process_single_event(&event, historical_cfg, &context).unwrap();

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

        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let processed = process_single_event(&event, historical_cfg, &context).unwrap();

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
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let result = process_single_event(&event, historical_cfg, &context);

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

        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let result = process_single_event(&event, historical_cfg, &context);

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

        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let result = process_single_event(&event, historical_cfg, &context);

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

        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let result = process_single_event(&event, historical_cfg, &context);

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

        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let result = process_single_event(&event, historical_cfg, &context);

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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // No restriction service
        let result = process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            None,
            events,
            &context,
        )
        .await;

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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

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

        process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            None,
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            None, // no overflow limiter
            events,
            &context,
        )
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        // test_token is in the reroute list -> ForceLimited
        let limiter = build_limiter(10, 10, Some("test_token".to_string()), false);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        // burst of 1 -> first event passes, second event rate-limited
        let limiter = build_limiter(1, 1, None, true);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let limiter = build_limiter(1, 1, None, false);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
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

        process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let limiter = build_limiter(10, 10, Some("test_token".to_string()), false);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // Global RL: limits (test_token, test_user) -> key `test_token:test_user`.
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));

        // Overflow limiter: burst=1, preserve_locality=true -> event[1]
        // stamped RateLimited{preserve_locality: true}.
        let overflow_limiter = build_limiter(1, 1, None, true);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            Some(global_limiter),
            Some(overflow_limiter),
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            Some(global_limiter),
            None, // no overflow limiter -- isolate global RL behavior
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        let global_limiter = Arc::new(GlobalRateLimiter::mock_limiting(&["test_token:test_user"]));

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            Some(global_limiter),
            None, // no overflow limiter -- isolate global RL behavior
            events,
            &context,
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        // test_token in reroute list -> ForceLimited stamped in pipeline.
        let limiter = build_limiter(10, 10, Some("test_token".to_string()), false);

        process_events(
            sink,
            dropper,
            None,
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
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

    #[tokio::test]
    async fn e2e_rate_limited_preserve_locality_pipeline_to_sink_keeps_key() {
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        // burst=1, preserve_locality=true => event[1] stamped RateLimited{preserve_locality: true}.
        let limiter = build_limiter(1, 1, None, true);

        process_events(
            sink,
            dropper,
            None,
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
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
            "RateLimited{{preserve_locality:true}} must preserve partition key"
        );
        assert!(
            records[1].headers.force_disable_person_processing.is_none(),
            "RateLimited (non-Force) must NOT set force_disable_person_processing"
        );
    }

    #[tokio::test]
    async fn e2e_rate_limited_no_preserve_locality_pipeline_to_sink_drops_key() {
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);
        // burst=1, preserve_locality=false => event[1] stamped RateLimited{preserve_locality: false}.
        let limiter = build_limiter(1, 1, None, false);

        process_events(
            sink,
            dropper,
            None,
            historical_cfg,
            None,
            Some(limiter),
            events,
            &context,
        )
        .await
        .unwrap();

        let records = producer.get_records();
        assert_eq!(records.len(), 2);
        assert_eq!(records[1].topic, "events_plugin_ingestion_overflow");
        assert_eq!(
            records[1].key, None,
            "RateLimited{{preserve_locality:false}} must drop partition key"
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

    #[rstest]
    #[case::heatmap_data_present(&["$heatmap_data"], true)]
    #[case::scroll_depth_pair(&["$prev_pageview_pathname", "$current_url"], true)]
    #[case::heatmap_data_with_scroll_depth(
        &["$heatmap_data", "$prev_pageview_pathname", "$current_url"],
        true,
    )]
    #[case::only_prev_pageview_pathname(&["$prev_pageview_pathname"], false)]
    #[case::only_current_url(&["$current_url"], false)]
    #[case::no_heatmap_properties(&[], false)]
    fn test_has_heatmap_data(#[case] property_keys: &[&str], #[case] expected: bool) {
        let mut properties = HashMap::new();
        properties.insert("distinct_id".to_string(), json!("test_user"));
        for key in property_keys {
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

        assert_eq!(has_heatmap_data(&event), expected);
    }

    #[test]
    fn test_create_heatmap_redirect_properties_and_metadata() {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let event = build_heatmap_carrier_event(HeatmapShape::HeatmapData);
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        let redirect = create_heatmap_redirect(&event, historical_cfg, &context)
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
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        let redirect = create_heatmap_redirect(&event, historical_cfg, &context)
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
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        let result = create_heatmap_redirect(&event, historical_cfg, &context).unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_create_heatmap_redirect_resolves_distinct_id_from_properties() {
        let now = Utc::now();
        let context = create_test_context(now, None);
        let event = build_heatmap_carrier_event(HeatmapShape::HeatmapData);
        // Carrier event has distinct_id only in properties (top-level is None).
        assert!(event.distinct_id.is_none());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        let redirect = create_heatmap_redirect(&event, historical_cfg, &context)
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            None,
            events,
            &context,
        )
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            None,
            events,
            &context,
        )
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
            None,
            None,
            events,
            &context,
        )
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
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        process_events(
            sink,
            dropper,
            None,
            historical_cfg,
            None,
            None,
            events,
            &context,
        )
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
}
