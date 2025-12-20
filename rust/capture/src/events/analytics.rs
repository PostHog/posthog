//! Analytics event processing
//!
//! This module handles processing of regular analytics events (pageviews, custom events,
//! exceptions, etc.) as opposed to recordings (session replay).

use std::sync::Arc;

use chrono::DateTime;
use common_types::{CapturedEvent, RawEvent};
use limiters::token_dropper::TokenDropper;
use metrics::counter;
use serde_json;
use tracing::{error, instrument, Span};

use crate::{
    api::CaptureError,
    debug_or_info,
    event_restrictions::{EventContext as RestrictionEventContext, EventRestrictionService, RestrictionType},
    prometheus::report_dropped_events,
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
        ("$exception", _) => DataType::ExceptionMain,
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
        error!("failed to encode data field: {}", e);
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
    let computed_timestamp = common_types::timestamp::parse_event_timestamp(
        event.timestamp.as_deref(),
        event.offset,
        sent_at_utc,
        ignore_sent_at,
        context.now,
    );

    let event_name = event.event.clone();

    let mut metadata = ProcessedEventMetadata {
        data_type,
        session_id: None,
        computed_timestamp: Some(computed_timestamp),
        event_name: event_name.clone(),
        force_overflow: false,
        skip_person_processing: false,
        redirect_to_dlq: false,
    };

    if historical_cfg.should_reroute(metadata.data_type, computed_timestamp) {
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
        timestamp: computed_timestamp,
        is_cookieless_mode: event
            .extract_is_cookieless_mode()
            .ok_or(CaptureError::InvalidCookielessMode)?,
        historical_migration: metadata.data_type == DataType::AnalyticsHistorical,
    };

    Ok(ProcessedEvent { metadata, event })
}

/// Process a batch of analytics events
#[instrument(skip_all, fields(events = events.len(), request_id))]
pub async fn process_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    dropper: Arc<TokenDropper>,
    restriction_service: Option<EventRestrictionService>,
    historical_cfg: router::HistoricalConfig,
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

    // Apply event restrictions if service is configured
    if let Some(ref service) = restriction_service {
        let mut filtered_events = Vec::with_capacity(events.len());

        for e in events {
            let event_ctx = RestrictionEventContext {
                distinct_id: Some(e.event.distinct_id.clone()),
                session_id: e.event.session_id.clone(),
                event_name: Some(e.event.event.clone()),
                event_uuid: Some(e.event.uuid.to_string()),
            };

            let restrictions = service.get_restrictions(&e.event.token, &event_ctx).await;

            if restrictions.contains(&RestrictionType::DropEvent) {
                counter!(
                    "capture_event_restrictions_applied",
                    "restriction_type" => "drop_event",
                    "pipeline" => "analytics"
                )
                .increment(1);
                report_dropped_events("event_restriction_drop", 1);
                continue;
            }

            let mut event = e;

            if restrictions.contains(&RestrictionType::ForceOverflow) {
                counter!(
                    "capture_event_restrictions_applied",
                    "restriction_type" => "force_overflow",
                    "pipeline" => "analytics"
                )
                .increment(1);
                event.metadata.force_overflow = true;
            }

            if restrictions.contains(&RestrictionType::SkipPersonProcessing) {
                counter!(
                    "capture_event_restrictions_applied",
                    "restriction_type" => "skip_person_processing",
                    "pipeline" => "analytics"
                )
                .increment(1);
                event.metadata.skip_person_processing = true;
            }

            if restrictions.contains(&RestrictionType::RedirectToDlq) {
                counter!(
                    "capture_event_restrictions_applied",
                    "restriction_type" => "redirect_to_dlq",
                    "pipeline" => "analytics"
                )
                .increment(1);
                event.metadata.redirect_to_dlq = true;
            }

            filtered_events.push(event);
        }

        events = filtered_events;
        debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "filtered by event_restrictions");
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

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::v0_request::ProcessingContext;
    use chrono::{DateTime, TimeZone, Utc};
    use common_types::RawEvent;
    use serde_json::json;
    use std::collections::HashMap;
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
        let mut properties = HashMap::new();
        if let Some(ignore) = ignore_sent_at {
            properties.insert("$ignore_sent_at".to_string(), json!(ignore));
        }
        properties.insert("distinct_id".to_string(), json!("test_user"));

        RawEvent {
            uuid: Some(uuid_v7()),
            distinct_id: None,
            event: "test_event".to_string(),
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
    use async_trait::async_trait;
    use crate::sinks;
    use crate::event_restrictions::{
        EventRestrictionService, IngestionPipeline, Restriction, RestrictionFilters,
        RestrictionManager, RestrictionScope, RestrictionType,
    };
    use std::sync::Mutex;
    use std::time::Duration;

    struct MockSink {
        events: Arc<Mutex<Vec<ProcessedEvent>>>,
    }

    impl MockSink {
        fn new() -> Self {
            Self {
                events: Arc::new(Mutex::new(Vec::new())),
            }
        }

        fn get_events(&self) -> Vec<ProcessedEvent> {
            self.events.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl sinks::Event for MockSink {
        async fn send(&self, event: ProcessedEvent) -> Result<(), crate::api::CaptureError> {
            self.events.lock().unwrap().push(event);
            Ok(())
        }

        async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), crate::api::CaptureError> {
            self.events.lock().unwrap().extend(events);
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_process_events_drop_event_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None)];

        let sink = Arc::new(MockSink::new());
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // Create restriction service with DropEvent
        let service = EventRestrictionService::new(
            IngestionPipeline::Analytics,
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
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
        let events = vec![create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None)];

        let sink = Arc::new(MockSink::new());
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // Create restriction service with ForceOverflow
        let service = EventRestrictionService::new(
            IngestionPipeline::Analytics,
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
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
        let events = vec![create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None)];

        let sink = Arc::new(MockSink::new());
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // Create restriction service with SkipPersonProcessing
        let service = EventRestrictionService::new(
            IngestionPipeline::Analytics,
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
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
        let events = vec![create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None)];

        let sink = Arc::new(MockSink::new());
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // Create restriction service with RedirectToDlq
        let service = EventRestrictionService::new(
            IngestionPipeline::Analytics,
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToDlq,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
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
        let events = vec![create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None)];

        let sink = Arc::new(MockSink::new());
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // Create restriction service with multiple restrictions
        let service = EventRestrictionService::new(
            IngestionPipeline::Analytics,
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![
                Restriction {
                    restriction_type: RestrictionType::ForceOverflow,
                    scope: RestrictionScope::AllEvents,
                },
                Restriction {
                    restriction_type: RestrictionType::SkipPersonProcessing,
                    scope: RestrictionScope::AllEvents,
                },
            ],
        );
        service.update(manager).await;

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
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
        let events = vec![create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None)];

        let sink = Arc::new(MockSink::new());
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // No restriction service
        let result = process_events(
            sink.clone(),
            dropper,
            None,
            historical_cfg,
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
    }

    #[tokio::test]
    async fn test_process_events_filtered_restriction() {
        let now = DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let context = create_test_context(now, None);
        let events = vec![create_test_event(Some("2023-01-01T11:00:00Z".to_string()), None, None)];

        let sink = Arc::new(MockSink::new());
        let dropper = Arc::new(limiters::token_dropper::TokenDropper::default());
        let historical_cfg = router::HistoricalConfig::new(false, 1);

        // Create restriction that only applies to different event name
        let service = EventRestrictionService::new(
            IngestionPipeline::Analytics,
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        let mut filters = RestrictionFilters::default();
        filters.event_names.insert("$pageview".to_string()); // our event is "test_event"
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::Filtered(filters),
            }],
        );
        service.update(manager).await;

        let result = process_events(
            sink.clone(),
            dropper,
            Some(service),
            historical_cfg,
            &events,
            &context,
        )
        .await;

        assert!(result.is_ok());
        // Event should NOT be dropped because filter doesn't match
        let captured = sink.get_events();
        assert_eq!(captured.len(), 1);
    }
}
