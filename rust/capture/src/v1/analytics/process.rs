use std::collections::HashMap;

use chrono::{DateTime, Utc};
use uuid::Uuid;

use super::response::Response;
use super::types::{CaptureV1Batch, CaptureV1Event, WrappedEvent};
use crate::event_restrictions::{EventContext, EventRestrictionService};
use crate::global_rate_limiter::{GlobalRateLimitKey, GlobalRateLimiter};
use crate::router;
use crate::v1::context::Context;
use crate::v1::sinks::Destination;
use crate::v1::Error;

const CAPTURE_PARSED_EVENTS: &str = "capture_v1_parsed_events";
const CAPTURE_V1_MAX_EVENT_NAME_LENGTH: usize = 200;
const CAPTURE_V1_DISTINCT_ID_MAX_SIZE: usize = 200;
const FUTURE_EVENT_HOURS_CUTOFF_MS: i64 = 23 * 3600 * 1000;

pub async fn process_batch(
    state: &router::State,
    context: &mut Context,
    batch: CaptureV1Batch,
) -> Result<Response, Error> {
    tracing::info!(ctx = ?context, "process_batch called");

    validate_batch(&batch)?;
    context.set_batch_metadata(&batch.metadata);

    let mut events: Vec<WrappedEvent> = validate_events(context, batch);

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

    if let Some(ref limiter) = state.global_rate_limiter_token_distinctid {
        apply_token_distinct_id_limits(limiter, &context.api_token, &mut events).await;
    }

    unimplemented!()
}

fn validate_batch(batch: &CaptureV1Batch) -> Result<(), Error> {
    DateTime::parse_from_rfc3339(&batch.metadata.created_at).map_err(|_| {
        Error::InvalidBatch(format!(
            "created_at is not valid RFC 3339: {}",
            batch.metadata.created_at
        ))
    })?;

    for event in &batch.batch {
        Uuid::parse_str(&event.uuid).map_err(|_| Error::MissingEventUuid)?;
    }

    Ok(())
}

fn validate_events(context: &Context, batch: CaptureV1Batch) -> Vec<WrappedEvent> {
    let mut malformed: HashMap<&'static str, u64> = HashMap::new();

    let events: Vec<WrappedEvent> = batch
        .batch
        .into_iter()
        .enumerate()
        .map(|(ordinal, event)| match validate_event(&event) {
            Ok(raw_ts) => {
                metrics::counter!(CAPTURE_PARSED_EVENTS, "result" => "valid").increment(1);
                let adjusted = normalize_timestamp(context, &event, raw_ts);
                WrappedEvent {
                    event,
                    adjusted_timestamp: Some(adjusted),
                    ordinal,
                    status_code: 200,
                    destination: Destination::default(),
                    skip_person_processing: false,
                }
            }
            Err(err) => {
                *malformed.entry(err.tag()).or_insert(0) += 1;
                WrappedEvent {
                    event,
                    adjusted_timestamp: None,
                    ordinal,
                    status_code: 400,
                    destination: Destination::default(),
                    skip_person_processing: false,
                }
            }
        })
        .collect();

    if !malformed.is_empty() {
        observe_malformed_events(context, &malformed);
    }

    events
}

fn observe_malformed_events(context: &Context, malformed: &HashMap<&'static str, u64>) {
    for (error_tag, count) in malformed {
        metrics::counter!(CAPTURE_PARSED_EVENTS, "result" => "malformed", "error" => *error_tag)
            .increment(*count);
    }

    let summary: String = malformed
        .iter()
        .map(|(tag, count)| format!("{tag}={count}"))
        .collect::<Vec<_>>()
        .join(", ");

    tracing::warn!(
        token = %context.api_token,
        request_id = %context.request_id,
        sdk_info = %context.sdk_info,
        attempt = context.attempt,
        client_timestamp = %context.client_timestamp,
        server_received_at = %context.server_received_at,
        user_agent = %context.user_agent,
        content_type = %context.content_type,
        content_encoding = ?context.content_encoding,
        client_ip = %context.client_ip,
        method = %context.method,
        path = %context.path,
        "malformed events: {summary}"
    );
}

fn validate_event(event: &CaptureV1Event) -> Result<DateTime<Utc>, Error> {
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
    Ok(ts)
}

fn normalize_timestamp(
    context: &Context,
    event: &CaptureV1Event,
    raw_event_ts: DateTime<Utc>,
) -> DateTime<Utc> {
    let ignore_sent_at = event
        .properties
        .get("$ignore_sent_at")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    if ignore_sent_at {
        return raw_event_ts;
    }

    let adjusted = raw_event_ts - context.clock_skew();
    let now = context.server_received_at;
    if adjusted.signed_duration_since(now).num_milliseconds() > FUTURE_EVENT_HOURS_CUTOFF_MS {
        return now;
    }
    adjusted
}

const CAPTURE_V1_EVENTS_REROUTED_HISTORICAL: &str = "capture_v1_events_rerouted_historical";

fn apply_historical_rerouting(
    cfg: &router::HistoricalConfig,
    context: &Context,
    events: &mut [WrappedEvent],
) {
    for event in events.iter_mut() {
        if event.status_code != 200 || event.destination != Destination::AnalyticsMain {
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

const CAPTURE_V1_EVENTS_DROPPED: &str = "capture_v1_events_dropped";

async fn apply_restrictions(
    service: &EventRestrictionService,
    token: &str,
    now_ts: i64,
    events: &mut [WrappedEvent],
) {
    for event in events.iter_mut() {
        if event.status_code != 200 {
            continue;
        }

        let event_ctx = EventContext {
            distinct_id: Some(&event.event.distinct_id),
            session_id: None,
            event_name: Some(&event.event.event),
            event_uuid: Some(&event.event.uuid),
            now_ts,
        };

        let applied = service.get_restrictions(token, &event_ctx).await;

        if applied.should_drop() {
            event.status_code = 400;
            event.destination = Destination::Drop;
            metrics::counter!(CAPTURE_V1_EVENTS_DROPPED, "reason" => "event_restriction")
                .increment(1);
            continue;
        }

        // Priority: overflow < custom topic < DLQ (DLQ wins, applied last)
        if applied.force_overflow() {
            event.destination = Destination::Overflow;
        }
        if let Some(topic) = applied.redirect_to_topic() {
            event.destination = Destination::Custom(topic.to_string());
        }
        if applied.redirect_to_dlq() {
            event.destination = Destination::Dlq;
        }

        if applied.skip_person_processing() {
            event.skip_person_processing = true;
        }
    }
}

const CAPTURE_V1_EVENTS_RATE_LIMITED: &str = "capture_v1_events_rate_limited";

async fn apply_token_distinct_id_limits(
    limiter: &GlobalRateLimiter,
    token: &str,
    events: &mut [WrappedEvent],
) {
    for event in events.iter_mut() {
        if event.status_code != 200 {
            continue;
        }
        let cache_key =
            GlobalRateLimitKey::TokenDistinctId(token, &event.event.distinct_id).to_cache_key();
        if limiter.is_limited(&cache_key, 1).await.is_some() {
            event.status_code = 429;
            event.destination = Destination::Drop;
            metrics::counter!(CAPTURE_V1_EVENTS_RATE_LIMITED, "reason" => "token_distinct_id")
                .increment(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::Duration as StdDuration;

    use chrono::{DateTime, Duration, Utc};
    use uuid::Uuid;

    use super::*;
    use crate::config::CaptureMode;
    use crate::event_restrictions::{
        Restriction, RestrictionManager, RestrictionScope, RestrictionType,
    };
    use crate::v1::analytics::types::{BatchMetadata, CaptureV1Batch, CaptureV1Event};
    use crate::v1::sinks::Destination;
    use crate::v1::Error;

    fn valid_event() -> CaptureV1Event {
        CaptureV1Event {
            event: "$pageview".to_string(),
            uuid: Uuid::new_v4().to_string(),
            distinct_id: "user-42".to_string(),
            timestamp: "2026-03-19T14:29:58.123Z".to_string(),
            properties: HashMap::new(),
        }
    }

    fn valid_batch(events: Vec<CaptureV1Event>) -> CaptureV1Batch {
        CaptureV1Batch {
            metadata: BatchMetadata {
                created_at: "2026-03-19T14:30:00.000Z".to_string(),
                historical_migration: false,
                capture_internal: false,
            },
            batch: events,
        }
    }

    // --- validate_batch ---

    #[test]
    fn batch_valid() {
        let batch = valid_batch(vec![valid_event()]);
        assert!(validate_batch(&batch).is_ok());
    }

    #[test]
    fn batch_bad_created_at() {
        let batch = CaptureV1Batch {
            metadata: BatchMetadata {
                created_at: "not-a-timestamp".to_string(),
                historical_migration: false,
                capture_internal: false,
            },
            batch: vec![valid_event()],
        };
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::InvalidBatch(_)));
    }

    #[test]
    fn batch_bad_uuid() {
        let mut event = valid_event();
        event.uuid = "not-a-uuid".to_string();
        let batch = valid_batch(vec![event]);
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::MissingEventUuid));
    }

    #[test]
    fn batch_empty_uuid() {
        let mut event = valid_event();
        event.uuid = String::new();
        let batch = valid_batch(vec![event]);
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::MissingEventUuid));
    }

    #[test]
    fn batch_multiple_events_second_bad_uuid() {
        let good = valid_event();
        let mut bad = valid_event();
        bad.uuid = "garbage".to_string();
        let batch = valid_batch(vec![good, bad]);
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::MissingEventUuid));
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

    // --- normalize_timestamp ---

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    fn ctx_with_skew(server_received_at: DateTime<Utc>, skew: Duration) -> Context {
        Context {
            api_token: "phc_test".to_string(),
            authorization: None,
            user_agent: "test/1.0".to_string(),
            content_type: "application/json".to_string(),
            content_encoding: None,
            sdk_info: "test/1.0".to_string(),
            attempt: 1,
            request_id: Uuid::new_v4(),
            client_timestamp: server_received_at + skew,
            client_ip: std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST),
            query: crate::v1::analytics::query::Query::default(),
            method: axum::http::Method::POST,
            path: "/i/v1/general/analytics/events".to_string(),
            server_received_at,
            created_at: None,
            capture_internal: false,
            historical_migration: false,
        }
    }

    fn event_with_ignore_sent_at(ignore: bool) -> CaptureV1Event {
        let mut props = HashMap::new();
        props.insert(
            "$ignore_sent_at".to_string(),
            serde_json::Value::Bool(ignore),
        );
        CaptureV1Event {
            event: "$pageview".to_string(),
            uuid: Uuid::new_v4().to_string(),
            distinct_id: "user-1".to_string(),
            timestamp: "2026-03-19T11:00:00Z".to_string(),
            properties: props,
        }
    }

    #[test]
    fn normalize_no_skew() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::zero());
        let event = valid_event();
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_positive_skew_client_ahead() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event = valid_event();
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, dt("2026-03-19T10:59:50Z"));
    }

    #[test]
    fn normalize_negative_skew_client_behind() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(-10));
        let event = valid_event();
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, dt("2026-03-19T11:00:10Z"));
    }

    #[test]
    fn normalize_clamps_far_future() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::zero());
        let event = valid_event();
        let event_ts = dt("2026-03-21T12:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, now);
    }

    #[test]
    fn normalize_allows_near_future() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::zero());
        let event = valid_event();
        let event_ts = dt("2026-03-20T10:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_ignore_sent_at_skips_adjustment() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event = event_with_ignore_sent_at(true);
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_ignore_sent_at_false_still_adjusts() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event = event_with_ignore_sent_at(false);
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, dt("2026-03-19T10:59:50Z"));
    }

    // --- apply_restrictions ---

    fn wrapped_event(ordinal: usize, event_name: &str, distinct_id: &str) -> WrappedEvent {
        WrappedEvent {
            event: CaptureV1Event {
                event: event_name.to_string(),
                uuid: Uuid::new_v4().to_string(),
                distinct_id: distinct_id.to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                properties: HashMap::new(),
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:58.123Z")),
            ordinal,
            status_code: 200,
            destination: Destination::default(),
            skip_person_processing: false,
        }
    }

    fn malformed_wrapped_event(ordinal: usize) -> WrappedEvent {
        WrappedEvent {
            event: CaptureV1Event {
                event: String::new(),
                uuid: Uuid::new_v4().to_string(),
                distinct_id: "user-1".to_string(),
                timestamp: "bad".to_string(),
                properties: HashMap::new(),
            },
            adjusted_timestamp: None,
            ordinal,
            status_code: 400,
            destination: Destination::default(),
            skip_person_processing: false,
        }
    }

    async fn restriction_service(
        token: &str,
        restrictions: Vec<Restriction>,
    ) -> EventRestrictionService {
        let service =
            EventRestrictionService::new(CaptureMode::Events, StdDuration::from_secs(300));
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(token.to_string(), restrictions);
        service.update(manager).await;
        service
    }

    #[tokio::test]
    async fn restrictions_no_restrictions_passthrough() {
        let service =
            EventRestrictionService::new(CaptureMode::Events, StdDuration::from_secs(300));
        service.update(RestrictionManager::new()).await;

        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        assert!(!events[0].skip_person_processing);
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
            wrapped_event(0, "$pageview", "user-1"),
            wrapped_event(1, "$identify", "user-2"),
        ];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 400);
        assert_eq!(events[0].destination, Destination::Drop);
        assert_eq!(events[1].status_code, 400);
        assert_eq!(events[1].destination, Destination::Drop);
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

        let mut events = vec![
            malformed_wrapped_event(0),
            wrapped_event(1, "$pageview", "user-1"),
        ];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        // malformed event stays 400 with original destination, not re-evaluated
        assert_eq!(events[0].status_code, 400);
        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        // valid event gets dropped by restriction
        assert_eq!(events[1].status_code, 400);
        assert_eq!(events[1].destination, Destination::Drop);
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

        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::Overflow);
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

        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::Dlq);
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

        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(
            events[0].destination,
            Destination::Custom("custom_analytics".to_string())
        );
    }

    #[tokio::test]
    async fn restrictions_skip_person_processing() {
        let service = restriction_service(
            "phc_token",
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        )
        .await;

        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        assert!(events[0].skip_person_processing);
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

        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::Dlq);
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

        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::AnalyticsMain);
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

    #[tokio::test]
    async fn td_limits_under_limit_all_pass() {
        let limiter = mock_limiter(vec![]);
        let mut events = vec![
            wrapped_event(0, "$pageview", "user-1"),
            wrapped_event(1, "$identify", "user-2"),
        ];

        apply_token_distinct_id_limits(&limiter, "phc_tok", &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        assert_eq!(events[1].status_code, 200);
        assert_eq!(events[1].destination, Destination::AnalyticsMain);
    }

    #[tokio::test]
    async fn td_limits_one_distinct_id_over_limit() {
        let limiter = mock_limiter(vec!["phc_tok:user-2"]);
        let mut events = vec![
            wrapped_event(0, "$pageview", "user-1"),
            wrapped_event(1, "$identify", "user-2"),
        ];

        apply_token_distinct_id_limits(&limiter, "phc_tok", &mut events).await;

        assert_eq!(events[0].status_code, 200);
        assert_eq!(events[0].destination, Destination::AnalyticsMain);
        assert_eq!(events[1].status_code, 429);
        assert_eq!(events[1].destination, Destination::Drop);
    }

    #[tokio::test]
    async fn td_limits_skips_already_invalid_events() {
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let mut events = vec![malformed_wrapped_event(0)];

        apply_token_distinct_id_limits(&limiter, "phc_tok", &mut events).await;

        assert_eq!(events[0].status_code, 400);
        assert_eq!(events[0].destination, Destination::default());
    }

    #[tokio::test]
    async fn td_limits_multiple_events_same_distinct_id_all_limited() {
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let mut events = vec![
            wrapped_event(0, "$pageview", "user-1"),
            wrapped_event(1, "$identify", "user-1"),
            wrapped_event(2, "$click", "user-1"),
        ];

        apply_token_distinct_id_limits(&limiter, "phc_tok", &mut events).await;

        for (i, event) in events.iter().enumerate() {
            assert_eq!(event.status_code, 429, "event {i} should be 429");
            assert_eq!(
                event.destination,
                Destination::Drop,
                "event {i} should be Drop"
            );
        }
    }

    #[tokio::test]
    async fn td_limits_mixed_valid_and_pre_dropped_events() {
        let limiter = mock_limiter(vec!["phc_tok:user-2"]);
        let mut events = vec![
            wrapped_event(0, "$pageview", "user-1"),
            wrapped_event(1, "$identify", "user-2"),
        ];
        // Simulate event 0 already dropped by restrictions
        events[0].status_code = 400;
        events[0].destination = Destination::Drop;

        apply_token_distinct_id_limits(&limiter, "phc_tok", &mut events).await;

        // Event 0 untouched (was already 400)
        assert_eq!(events[0].status_code, 400);
        assert_eq!(events[0].destination, Destination::Drop);
        // Event 1 rate-limited
        assert_eq!(events[1].status_code, 429);
        assert_eq!(events[1].destination, Destination::Drop);
    }

    // --- apply_historical_rerouting ---

    use std::net::{IpAddr, Ipv4Addr};

    use axum::http::Method;

    use crate::v1::analytics::query::Query;

    fn test_context(historical_migration: bool) -> Context {
        Context {
            api_token: "phc_test_token".to_string(),
            authorization: None,
            user_agent: "test-agent/1.0".to_string(),
            content_type: "application/json".to_string(),
            content_encoding: None,
            sdk_info: "posthog-rust/1.0.0".to_string(),
            attempt: 1,
            request_id: Uuid::new_v4(),
            client_timestamp: Utc::now(),
            client_ip: IpAddr::V4(Ipv4Addr::LOCALHOST),
            query: Query::default(),
            method: Method::POST,
            path: "/i/v1/general/analytics/events".to_string(),
            server_received_at: Utc::now(),
            created_at: Some("2026-03-19T14:30:00.000Z".to_string()),
            capture_internal: false,
            historical_migration,
        }
    }

    fn wrapped_event_at(ordinal: usize, timestamp: DateTime<Utc>) -> WrappedEvent {
        WrappedEvent {
            event: CaptureV1Event {
                event: "$pageview".to_string(),
                uuid: Uuid::new_v4().to_string(),
                distinct_id: "user-1".to_string(),
                timestamp: timestamp.to_rfc3339(),
                properties: HashMap::new(),
            },
            adjusted_timestamp: Some(timestamp),
            ordinal,
            status_code: 200,
            destination: Destination::default(),
            skip_person_processing: false,
        }
    }

    #[test]
    fn historical_batch_flag_reroutes_all_events() {
        let cfg = router::HistoricalConfig::new(false, 1);
        let ctx = test_context(true);
        let mut events = vec![
            wrapped_event(0, "$pageview", "user-1"),
            wrapped_event(1, "$identify", "user-2"),
        ];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsHistorical);
        assert_eq!(events[1].destination, Destination::AnalyticsHistorical);
    }

    #[test]
    fn historical_timestamp_reroutes_old_event() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_context(false);
        let old_ts = Utc::now() - Duration::days(60);
        let mut events = vec![wrapped_event_at(0, old_ts)];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsHistorical);
    }

    #[test]
    fn historical_timestamp_keeps_recent_event() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_context(false);
        let recent_ts = Utc::now() - Duration::hours(1);
        let mut events = vec![wrapped_event_at(0, recent_ts)];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_rerouting_disabled_no_change() {
        let cfg = router::HistoricalConfig::new(false, 30);
        let ctx = test_context(false);
        let old_ts = Utc::now() - Duration::days(60);
        let mut events = vec![wrapped_event_at(0, old_ts)];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_skips_non_analytics_main() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_context(true);
        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        events[0].destination = Destination::Overflow;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::Overflow);
    }

    #[test]
    fn historical_skips_dropped_events() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_context(true);
        let mut events = vec![wrapped_event(0, "$pageview", "user-1")];
        events[0].status_code = 400;
        events[0].destination = Destination::Drop;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::Drop);
    }

    #[test]
    fn historical_skips_malformed_events() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_context(true);
        let mut events = vec![malformed_wrapped_event(0)];

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_mixed_batch_flag_and_already_redirected() {
        let cfg = router::HistoricalConfig::new(false, 1);
        let ctx = test_context(true);
        let mut events = vec![
            wrapped_event(0, "$pageview", "user-1"),
            wrapped_event(1, "$identify", "user-2"),
        ];
        events[1].destination = Destination::Dlq;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events[0].destination, Destination::AnalyticsHistorical);
        // DLQ event untouched
        assert_eq!(events[1].destination, Destination::Dlq);
    }
}
