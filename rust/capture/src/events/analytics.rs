//! Analytics event processing
//!
//! This module handles processing of regular analytics events (pageviews, custom events,
//! exceptions, etc.) as opposed to recordings (session replay).

use std::collections::HashSet;
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
    utils::uuid_v7,
    v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata, ProcessingContext},
};

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

    let data_type = match (event.event.as_str(), context.historical_migration) {
        ("$$client_ingestion_warning", _) => DataType::ClientIngestionWarning,
        ("$exception", _) => DataType::ExceptionErrorTracking,
        ("$$heatmap", _) => DataType::HeatmapMain,
        (_, true) => DataType::AnalyticsHistorical,
        (_, false) => DataType::AnalyticsMain,
    };

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
        uuid: event.uuid.unwrap_or_else(uuid_v7),
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
pub async fn process_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    dropper: Arc<TokenDropper>,
    restriction_service: Option<EventRestrictionService>,
    historical_cfg: router::HistoricalConfig,
    global_rate_limiter: Option<Arc<GlobalRateLimiter>>,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    events: &'a [RawEvent],
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    let chatty_debug_enabled = context.chatty_debug_enabled;

    Span::current().record("request_id", &context.request_id);
    Span::current().record("is_mirror_deploy", context.is_mirror_deploy);

    let mut events: Vec<ProcessedEvent> = events
        .iter()
        .map(|e| process_single_event(e, historical_cfg.clone(), context))
        .collect::<Result<Vec<ProcessedEvent>, CaptureError>>()?;

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

    // Apply event restrictions if service is configured.
    //
    // The service is scoped to the analytics pipeline (loaded for
    // `CaptureMode::Events` → pipeline name `"analytics"`), so restrictions
    // only apply to events routed to the analytics pipeline. Non-analytics
    // data types (exceptions, heatmaps, client ingestion warnings) flow to
    // separate topics and separate consumers that own their own restriction
    // scope — applying analytics restrictions here would cross pipelines
    // (e.g. a DropEvent restriction would silently drop exception events
    // before they reach the error tracking topic).
    if let Some(ref service) = restriction_service {
        let mut filtered_events = Vec::with_capacity(events.len());
        let now_ts = context.now.timestamp();

        for e in events {
            if !e.metadata.data_type.is_analytics_pipeline() {
                filtered_events.push(e);
                continue;
            }

            let uuid_str = e.event.uuid.to_string();
            let event_ctx = RestrictionEventContext {
                distinct_id: Some(&e.event.distinct_id),
                session_id: e.event.session_id.as_deref(),
                event_name: Some(&e.event.event),
                event_uuid: Some(&uuid_str),
                now_ts,
            };

            let applied = service.get_restrictions(&e.event.token, &event_ctx).await;

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

    // Apply per-(token, distinct_id) global rate limiting -- skip person processing for high-volume distinct_ids
    if let Some(ref limiter) = global_rate_limiter {
        let mut limited_distinct_ids: HashSet<&str> = HashSet::new();
        let mut limited_event_count: u64 = 0;
        for event in events.iter_mut() {
            let cache_key =
                GlobalRateLimitKey::TokenDistinctId(&context.token, &event.event.distinct_id)
                    .to_cache_key();
            if limiter.is_limited(&cache_key, 1).await.is_some() {
                event.metadata.skip_person_processing = true;
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
            lib_version: None,
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
            uuid: Some(uuid_v7()),
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
    use crate::config::CaptureMode;
    use crate::event_restrictions::{
        EventRestrictionService, Restriction, RestrictionFilters, RestrictionManager,
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
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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
            &events,
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
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        let mut filters = RestrictionFilters::default();
        filters.event_names.insert("$pageview".to_string()); // our event is "test_event"
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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

        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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

        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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

        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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

        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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
            &events,
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
            &events,
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
            &events,
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
            &events,
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

        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
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
            &events,
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
            &events,
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
        // Both limiters fire on the same event: global RL sets
        // skip_person_processing=true on (token, distinct_id) overage, and the
        // OverflowLimiter stamps RateLimited{preserve_locality: true} on the
        // second event because burst=1. The pipeline must OR the two effects
        // into the same metadata record; the sink then routes to the overflow
        // topic, keeps the partition key, and writes the skip-person header.
        // Pre-refactor these were split across pipeline + sink; this test
        // pins the end-to-end metadata contract.

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
            &events,
            &context,
        )
        .await
        .unwrap();

        let captured = sink.get_events();
        assert_eq!(captured.len(), 2);

        // event[0]: global RL fires (distinct_id limited) -> skip_person_processing.
        // Overflow limiter's first token is within burst so no overflow_reason.
        assert!(
            captured[0].metadata.skip_person_processing,
            "event[0]: global RL should set skip_person_processing"
        );
        assert_eq!(
            captured[0].metadata.overflow_reason, None,
            "event[0]: burst=1 means first event is NOT overflow"
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
            &events,
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
            &events,
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
            &events,
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
}
