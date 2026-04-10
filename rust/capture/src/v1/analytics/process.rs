use std::collections::{HashMap, HashSet};

use chrono::{DateTime, Utc};
use uuid::Uuid;

use super::constants::{
    CAPTURE_V1_DISTINCT_ID_MAX_SIZE, CAPTURE_V1_EVENTS_DROPPED,
    CAPTURE_V1_EVENTS_REROUTED_HISTORICAL, CAPTURE_V1_MAX_EVENT_NAME_LENGTH,
    CAPTURE_V1_PARSED_EVENTS, CAPTURE_V1_RATE_LIMITER, DETAIL_RATE_LIMITED_TOKEN_DISTINCT_ID,
    FUTURE_EVENT_HOURS_CUTOFF_MS, ILLEGAL_DISTINCT_IDS,
};
use super::response::Response;
use super::types::{Batch, Event, EventResult, WrappedEvent};
use crate::event_restrictions::{EventContext, EventRestrictionService};
use crate::global_rate_limiter::{GlobalRateLimitKey, GlobalRateLimiter};
use tracing::Level;

use crate::router;
use crate::v1::context::Context;
use crate::v1::sinks::Destination;
use crate::v1::Error;

pub async fn process_batch(
    state: &router::State,
    context: &mut Context,
    batch: Batch,
) -> Result<Response, Error> {
    crate::ctx_log!(Level::INFO, context, "process_batch called");

    validate_batch(&batch)?;
    context.set_batch_metadata(&batch);

    let mut events = validate_events(context, batch)?;

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

    if let Some(ref limiter) = state.global_rate_limiter_token_distinctid {
        apply_token_distinct_id_limits(limiter, context, &mut events).await;
    }

    // TODO: publish to v1::Sink, collect results, format + return response
    Err(Error::ServiceUnavailable("not yet implemented".into()))
}

fn validate_batch(batch: &Batch) -> Result<(), Error> {
    if batch.batch.is_empty() {
        return Err(Error::EmptyBatch);
    }

    DateTime::parse_from_rfc3339(&batch.created_at).map_err(|_| {
        Error::InvalidBatch(format!(
            "created_at is not valid RFC 3339: {}",
            batch.created_at
        ))
    })?;

    Ok(())
}

fn validate_events(context: &Context, batch: Batch) -> Result<HashMap<Uuid, WrappedEvent>, Error> {
    let mut events: HashMap<Uuid, WrappedEvent> = HashMap::with_capacity(batch.batch.len());

    for event in batch.batch.into_iter() {
        let uuid = Uuid::parse_str(&event.uuid).map_err(|_| Error::MissingEventUuid)?;
        if events.contains_key(&uuid) {
            return Err(Error::DuplicateEventUuid(event.uuid));
        }

        match validate_event(&event) {
            Ok(raw_ts) => {
                metrics::counter!(CAPTURE_V1_PARSED_EVENTS, "result" => "valid").increment(1);
                let adjusted = normalize_timestamp(context, &event, raw_ts);
                events.insert(
                    uuid,
                    WrappedEvent {
                        event,
                        adjusted_timestamp: Some(adjusted),
                        result: EventResult::Ok,
                        details: None,
                        destination: Destination::default(),
                        skip_person_processing: false,
                    },
                );
            }
            Err(err) => {
                events.insert(
                    uuid,
                    WrappedEvent {
                        event,
                        adjusted_timestamp: None,
                        result: EventResult::Drop,
                        details: Some(err.tag()),
                        destination: Destination::default(),
                        skip_person_processing: false,
                    },
                );
            }
        }
    }

    if events.values().any(|e| e.result != EventResult::Ok) {
        observe_malformed_events(context, &events);
    }

    Ok(events)
}

fn observe_malformed_events(context: &Context, events: &HashMap<Uuid, WrappedEvent>) {
    let mut malformed: HashMap<&'static str, u64> = HashMap::new();
    let mut illegal_distinct_ids: HashSet<&str> = HashSet::new();

    for event in events.values() {
        if let Some(tag) = event.details {
            *malformed.entry(tag).or_insert(0) += 1;
            if tag == "invalid_distinct_id" {
                illegal_distinct_ids.insert(&event.event.distinct_id);
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

    let illegal_ids_csv: String = illegal_distinct_ids
        .into_iter()
        .collect::<Vec<_>>()
        .join(", ");

    crate::ctx_log!(Level::WARN, context,
        illegal_distinct_ids = %illegal_ids_csv,
        "malformed events: {summary}"
    );
}

fn is_distinct_id_illegal(distinct_id: &str) -> bool {
    let trimmed = distinct_id.trim();
    ILLEGAL_DISTINCT_IDS
        .iter()
        .any(|id| trimmed.eq_ignore_ascii_case(id))
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
    if is_distinct_id_illegal(&event.distinct_id) {
        return Err(Error::InvalidDistinctId(event.distinct_id.clone()));
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
    context: &Context,
    event: &Event,
    raw_event_ts: DateTime<Utc>,
) -> DateTime<Utc> {
    if event.options.disable_skew_adjustment.unwrap_or(false) {
        return raw_event_ts;
    }

    let adjusted = raw_event_ts - context.clock_skew();
    let now = context.server_received_at;
    if adjusted.signed_duration_since(now).num_milliseconds() > FUTURE_EVENT_HOURS_CUTOFF_MS {
        return now;
    }
    adjusted
}

fn apply_historical_rerouting(
    cfg: &router::HistoricalConfig,
    context: &Context,
    events: &mut HashMap<Uuid, WrappedEvent>,
) {
    for event in events.values_mut() {
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

async fn apply_restrictions(
    service: &EventRestrictionService,
    token: &str,
    now_ts: i64,
    events: &mut HashMap<Uuid, WrappedEvent>,
) {
    for event in events.values_mut() {
        if event.result != EventResult::Ok {
            continue;
        }

        let event_ctx = EventContext {
            distinct_id: Some(&event.event.distinct_id),
            session_id: event.event.session_id.as_deref(),
            event_name: Some(&event.event.event),
            event_uuid: Some(&event.event.uuid),
            now_ts,
        };

        let applied = service.get_restrictions(token, &event_ctx).await;

        if applied.should_drop() {
            event.result = EventResult::Drop;
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

async fn apply_token_distinct_id_limits(
    limiter: &GlobalRateLimiter,
    context: &Context,
    events: &mut HashMap<Uuid, WrappedEvent>,
) {
    let mut limited_distinct_ids: HashSet<&str> = HashSet::new();
    let mut allowed_count: u64 = 0;

    for event in events.values_mut() {
        if event.result != EventResult::Ok {
            continue;
        }
        let cache_key =
            GlobalRateLimitKey::TokenDistinctId(&context.api_token, &event.event.distinct_id)
                .to_cache_key();
        if limiter.is_limited(&cache_key, 1).await.is_some() {
            event.result = EventResult::Limited;
            event.destination = Destination::Drop;
            event.details = Some(DETAIL_RATE_LIMITED_TOKEN_DISTINCT_ID);
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
            "events rate limited by distinct_id"
        );
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration as StdDuration;

    use chrono::{DateTime, Duration, Utc};
    use uuid::Uuid;

    use super::*;
    use crate::config::CaptureMode;
    use crate::event_restrictions::{
        Restriction, RestrictionManager, RestrictionScope, RestrictionType,
    };
    use crate::v1::analytics::types::{Batch, Event, Options};
    use crate::v1::sinks::Destination;
    use crate::v1::test_utils::{
        self, events_map, find_by_did, malformed_wrapped_event, raw_obj, valid_event,
        wrapped_event, wrapped_event_at,
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
    fn event_illegal_distinct_ids_rejected() {
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
            let mut event = valid_event();
            event.distinct_id = id.to_string();
            assert!(
                matches!(validate_event(&event), Err(Error::InvalidDistinctId(_))),
                "expected InvalidDistinctId for distinct_id={id:?}"
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
        let p = events.get(&perf_uuid).unwrap();
        assert_eq!(p.result, EventResult::Drop);
        assert_eq!(p.details, Some("dropped_performance_event"));
        let n = events.get(&normal_uuid).unwrap();
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
        for ev in events.values() {
            assert_eq!(ev.result, EventResult::Drop);
            assert_eq!(ev.details, Some("dropped_performance_event"));
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
    fn validate_events_missing_uuid_bails_batch() {
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
        assert!(matches!(err, Error::MissingEventUuid));
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
        let event = events.get(&uuid).unwrap();
        assert_eq!(event.result, EventResult::Drop);
        assert_eq!(event.details, Some("malformed_event_properties"));
    }

    // --- normalize_timestamp ---

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    fn ctx_with_skew(server_received_at: DateTime<Utc>, skew: Duration) -> Context {
        Context {
            api_token: "phc_test".to_string(),
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
            path: "/i/v1/general/events".to_string(),
            server_received_at,
            created_at: None,
            capture_internal: false,
            historical_migration: false,
        }
    }

    fn event_with_disable_skew_adjustment(disable: bool) -> Event {
        Event {
            event: "$pageview".to_string(),
            uuid: Uuid::new_v4().to_string(),
            distinct_id: "user-1".to_string(),
            timestamp: "2026-03-19T11:00:00Z".to_string(),
            session_id: None,
            window_id: None,
            options: Options {
                cookieless_mode: None,
                disable_skew_adjustment: Some(disable),
                product_tour_id: None,
                process_person_profile: None,
            },
            properties: raw_obj("{}"),
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
    fn normalize_disable_skew_adjustment_skips_adjustment() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event = event_with_disable_skew_adjustment(true);
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_disable_skew_adjustment_false_still_adjusts() {
        let now = dt("2026-03-19T12:00:00Z");
        let ctx = ctx_with_skew(now, Duration::seconds(10));
        let event = event_with_disable_skew_adjustment(false);
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(&ctx, &event, event_ts);
        assert_eq!(result, dt("2026-03-19T10:59:50Z"));
    }

    // --- apply_restrictions ---

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

        let mut events = events_map(vec![wrapped_event("$pageview", "user-1")]);
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::AnalyticsMain);
        assert!(!ev.skip_person_processing);
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

        let mut events = events_map(vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ]);
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        for ev in events.values() {
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
        let mut events = events_map(vec![malformed, wrapped_event("$pageview", "user-valid")]);
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

        let mut events = events_map(vec![wrapped_event("$pageview", "user-1")]);
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

        let mut events = events_map(vec![wrapped_event("$pageview", "user-1")]);
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

        let mut events = events_map(vec![wrapped_event("$pageview", "user-1")]);
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

        let mut events = events_map(vec![wrapped_event("$pageview", "user-1")]);
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::AnalyticsMain);
        assert!(ev.skip_person_processing);
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

        let mut events = events_map(vec![wrapped_event("$pageview", "user-1")]);
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

        let mut events = events_map(vec![wrapped_event("$pageview", "user-1")]);
        let now_ts = Utc::now().timestamp();

        apply_restrictions(&service, "phc_token", now_ts, &mut events).await;

        let ev = find_by_did(&events, "user-1");
        assert_eq!(ev.result, EventResult::Ok);
        assert_eq!(ev.destination, Destination::AnalyticsMain);
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

    fn td_context() -> Context {
        let mut ctx = test_utils::test_context();
        ctx.api_token = "phc_tok".to_string();
        ctx
    }

    #[tokio::test]
    async fn td_limits_under_limit_all_pass() {
        let limiter = mock_limiter(vec![]);
        let ctx = td_context();
        let mut events = events_map(vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ]);

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        for ev in events.values() {
            assert_eq!(ev.result, EventResult::Ok);
            assert_eq!(ev.destination, Destination::AnalyticsMain);
            assert!(ev.details.is_none());
        }
    }

    #[tokio::test]
    async fn td_limits_one_distinct_id_over_limit() {
        let limiter = mock_limiter(vec!["phc_tok:user-2"]);
        let ctx = td_context();
        let mut events = events_map(vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ]);

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        let ok_ev = find_by_did(&events, "user-1");
        assert_eq!(ok_ev.result, EventResult::Ok);
        assert_eq!(ok_ev.destination, Destination::AnalyticsMain);
        assert!(ok_ev.details.is_none());
        let limited_ev = find_by_did(&events, "user-2");
        assert_eq!(limited_ev.result, EventResult::Limited);
        assert_eq!(limited_ev.destination, Destination::Drop);
        assert_eq!(
            limited_ev.details,
            Some(DETAIL_RATE_LIMITED_TOKEN_DISTINCT_ID)
        );
    }

    #[tokio::test]
    async fn td_limits_skips_already_invalid_events() {
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let ctx = td_context();
        let mut events = events_map(vec![malformed_wrapped_event()]);

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        let ev = events.values().next().unwrap();
        assert_eq!(ev.result, EventResult::Drop);
        assert_eq!(ev.destination, Destination::default());
        assert!(ev.details.is_some());
    }

    #[tokio::test]
    async fn td_limits_multiple_events_same_distinct_id_all_limited() {
        let limiter = mock_limiter(vec!["phc_tok:user-1"]);
        let ctx = td_context();
        let mut events = events_map(vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-1"),
            wrapped_event("$click", "user-1"),
        ]);

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        for ev in events.values() {
            assert_eq!(ev.result, EventResult::Limited, "should be Limited");
            assert_eq!(ev.destination, Destination::Drop, "should be Drop");
            assert_eq!(
                ev.details,
                Some(DETAIL_RATE_LIMITED_TOKEN_DISTINCT_ID),
                "should have details"
            );
        }
    }

    #[tokio::test]
    async fn td_limits_mixed_valid_and_pre_dropped_events() {
        let limiter = mock_limiter(vec!["phc_tok:user-2"]);
        let ctx = td_context();
        let pre_drop = wrapped_event("$pageview", "user-1");
        let pre_drop_uuid = Uuid::parse_str(&pre_drop.event.uuid).unwrap();
        let mut events = events_map(vec![pre_drop, wrapped_event("$identify", "user-2")]);
        // Simulate event already dropped by restrictions
        events.get_mut(&pre_drop_uuid).unwrap().result = EventResult::Drop;
        events.get_mut(&pre_drop_uuid).unwrap().destination = Destination::Drop;

        apply_token_distinct_id_limits(&limiter, &ctx, &mut events).await;

        // Pre-dropped event untouched
        let dropped = find_by_did(&events, "user-1");
        assert_eq!(dropped.result, EventResult::Drop);
        assert_eq!(dropped.destination, Destination::Drop);
        // Other event rate-limited
        let limited = find_by_did(&events, "user-2");
        assert_eq!(limited.result, EventResult::Limited);
        assert_eq!(limited.destination, Destination::Drop);
        assert_eq!(limited.details, Some(DETAIL_RATE_LIMITED_TOKEN_DISTINCT_ID));
    }

    // --- apply_historical_rerouting ---

    #[test]
    fn historical_batch_flag_reroutes_all_events() {
        let cfg = router::HistoricalConfig::new(false, 1);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let mut events = events_map(vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
        ]);

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        for ev in events.values() {
            assert_eq!(ev.destination, Destination::AnalyticsHistorical);
        }
    }

    #[test]
    fn historical_timestamp_reroutes_old_event() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_utils::test_context();
        let old_ts = Utc::now() - Duration::days(60);
        let mut events = events_map(vec![wrapped_event_at(old_ts)]);

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = events.values().next().unwrap();
        assert_eq!(ev.destination, Destination::AnalyticsHistorical);
    }

    #[test]
    fn historical_timestamp_keeps_recent_event() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let ctx = test_utils::test_context();
        let recent_ts = Utc::now() - Duration::hours(1);
        let mut events = events_map(vec![wrapped_event_at(recent_ts)]);

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = events.values().next().unwrap();
        assert_eq!(ev.destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_rerouting_disabled_no_change() {
        let cfg = router::HistoricalConfig::new(false, 30);
        let ctx = test_utils::test_context();
        let old_ts = Utc::now() - Duration::days(60);
        let mut events = events_map(vec![wrapped_event_at(old_ts)]);

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = events.values().next().unwrap();
        assert_eq!(ev.destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_skips_non_analytics_main() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let ev = wrapped_event("$pageview", "user-1");
        let uuid = Uuid::parse_str(&ev.event.uuid).unwrap();
        let mut events = events_map(vec![ev]);
        events.get_mut(&uuid).unwrap().destination = Destination::Overflow;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(
            events.get(&uuid).unwrap().destination,
            Destination::Overflow
        );
    }

    #[test]
    fn historical_skips_dropped_events() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let ev = wrapped_event("$pageview", "user-1");
        let uuid = Uuid::parse_str(&ev.event.uuid).unwrap();
        let mut events = events_map(vec![ev]);
        let e = events.get_mut(&uuid).unwrap();
        e.result = EventResult::Drop;
        e.destination = Destination::Drop;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        assert_eq!(events.get(&uuid).unwrap().destination, Destination::Drop);
    }

    #[test]
    fn historical_skips_malformed_events() {
        let cfg = router::HistoricalConfig::new(true, 30);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let mut events = events_map(vec![malformed_wrapped_event()]);

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let ev = events.values().next().unwrap();
        assert_eq!(ev.destination, Destination::AnalyticsMain);
    }

    #[test]
    fn historical_mixed_batch_flag_and_already_redirected() {
        let cfg = router::HistoricalConfig::new(false, 1);
        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let dlq_ev = wrapped_event("$identify", "user-2");
        let dlq_uuid = Uuid::parse_str(&dlq_ev.event.uuid).unwrap();
        let mut events = events_map(vec![wrapped_event("$pageview", "user-1"), dlq_ev]);
        events.get_mut(&dlq_uuid).unwrap().destination = Destination::Dlq;

        apply_historical_rerouting(&cfg, &ctx, &mut events);

        let main_ev = find_by_did(&events, "user-1");
        assert_eq!(main_ev.destination, Destination::AnalyticsHistorical);
        // DLQ event untouched
        assert_eq!(events.get(&dlq_uuid).unwrap().destination, Destination::Dlq);
    }
}
