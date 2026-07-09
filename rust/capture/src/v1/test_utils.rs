#![allow(dead_code)]

use std::net::{IpAddr, Ipv4Addr};

use axum::http::Method;
use chrono::{DateTime, Utc};
use serde_json::value::RawValue;
use uuid::Uuid;

use crate::v1::analytics::constants::CAPTURE_V1_PATH;
use crate::v1::analytics::context::Context as AnalyticsContext;
use crate::v1::analytics::query::Query;
use crate::v1::analytics::types::{Event, EventResult, Options, RawOptions, WrappedEvent};
use crate::v1::context::RequestContext;
use crate::v1::sinks::event::Event as SinkEvent;
use crate::v1::sinks::types::PreparedEvent;
use crate::v1::sinks::Destination;

/// Serialize publishable events into `PreparedEvent`s for driving sinks in tests.
/// Accepts `&[&dyn Event]` (integration) or `&[&ConcreteType]` (unit) via `?Sized`.
pub fn prepared<E: SinkEvent + ?Sized>(events: &[&E], ctx: &RequestContext) -> Vec<PreparedEvent> {
    events
        .iter()
        .filter(|e| e.should_publish())
        .map(|e| PreparedEvent {
            uuid: e.uuid(),
            destination: e.destination().clone(),
            payload: e.serialize(ctx).expect("test payload must serialize"),
            headers: e.headers(ctx),
            partition_key: e.partition_key(ctx),
        })
        .collect()
}

pub fn raw_obj(s: &str) -> Box<RawValue> {
    RawValue::from_string(s.to_owned()).unwrap()
}

pub fn test_context() -> RequestContext {
    RequestContext {
        api_token: "phc_test_token".to_string(),
        user_agent: "test-agent/1.0".to_string(),
        content_type: "application/json".to_string(),
        content_encoding: None,
        sdk_info: "posthog-rs/1.0.0".to_string(),
        attempt: 1,
        request_id: Uuid::new_v4(),
        client_timestamp: Utc::now(),
        client_ip: IpAddr::V4(Ipv4Addr::LOCALHOST),
        raw_query: None,
        method: Method::POST,
        path: CAPTURE_V1_PATH,
        server_received_at: Utc::now(),
        created_at: Some("2026-03-19T14:30:00.000Z".to_string()),
        capture_internal: false,
        historical_migration: false,
        gateway_signature: None,
    }
}

/// Analytics-mode context wrapping [`test_context`] for tests that drive
/// `process_batch` (which takes `&mut analytics::Context`).
pub fn test_analytics_context() -> AnalyticsContext {
    AnalyticsContext {
        req: test_context(),
        query: Query::default(),
    }
}

pub fn valid_event() -> Event {
    Event {
        event: "$pageview".to_string(),
        uuid: Uuid::new_v4().to_string(),
        distinct_id: "user-42".to_string(),
        timestamp: "2026-03-19T14:29:58.123Z".to_string(),
        session_id: None,
        window_id: None,
        options: RawOptions::default(),
        properties: raw_obj("{}"),
    }
}

pub fn wrapped_event(event_name: &str, distinct_id: &str) -> WrappedEvent {
    let uuid = Uuid::new_v4();
    WrappedEvent {
        event: Event {
            event: event_name.to_string(),
            uuid: uuid.to_string(),
            distinct_id: distinct_id.to_string(),
            timestamp: "2026-03-19T14:29:58.123Z".to_string(),
            session_id: None,
            window_id: None,
            options: RawOptions::default(),
            properties: raw_obj("{}"),
        },
        uuid,
        options: Options::default(),
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:29:58.123Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::default(),
        force_disable_person_processing: false,
        is_gateway_verified: false,
    }
}

pub fn wrapped_event_at(timestamp: DateTime<Utc>) -> WrappedEvent {
    let uuid = Uuid::new_v4();
    WrappedEvent {
        event: Event {
            event: "$pageview".to_string(),
            uuid: uuid.to_string(),
            distinct_id: "user-1".to_string(),
            timestamp: timestamp.to_rfc3339(),
            session_id: None,
            window_id: None,
            options: RawOptions::default(),
            properties: raw_obj("{}"),
        },
        uuid,
        options: Options::default(),
        adjusted_timestamp: Some(timestamp),
        result: EventResult::Ok,
        details: None,
        destination: Destination::default(),
        force_disable_person_processing: false,
        is_gateway_verified: false,
    }
}

pub fn malformed_wrapped_event() -> WrappedEvent {
    let uuid = Uuid::new_v4();
    WrappedEvent {
        event: Event {
            event: String::new(),
            uuid: uuid.to_string(),
            distinct_id: "user-1".to_string(),
            timestamp: "bad".to_string(),
            session_id: None,
            window_id: None,
            options: RawOptions::default(),
            properties: raw_obj("{}"),
        },
        uuid,
        options: Options::default(),
        adjusted_timestamp: None,
        result: EventResult::Drop,
        details: Some("missing_event_name"),
        destination: Destination::default(),
        force_disable_person_processing: false,
        is_gateway_verified: false,
    }
}

pub fn find_by_did<'a>(events: &'a [WrappedEvent], distinct_id: &str) -> &'a WrappedEvent {
    events
        .iter()
        .find(|e| e.event.distinct_id == distinct_id)
        .unwrap()
}

pub fn test_kafka_config() -> crate::v1::sinks::kafka::config::Config {
    let env: std::collections::HashMap<String, String> = [
        ("HOSTS", "localhost:9092"),
        ("TOPIC_MAIN", "events_main"),
        ("TOPIC_HISTORICAL", "events_hist"),
        ("TOPIC_OVERFLOW", "events_overflow"),
        ("TOPIC_DLQ", "events_dlq"),
        ("TOPIC_EXCEPTION", "error_tracking_events"),
        ("TOPIC_HEATMAP", "heatmaps_ingestion"),
        ("TOPIC_CLIENT_INGESTION_WARNING", "events_plugin_ingestion"),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect();
    envconfig::Envconfig::init_from_hashmap(&env).unwrap()
}

// ---------------------------------------------------------------------------
// Realistic fixture builders
// ---------------------------------------------------------------------------

/// A realistic $pageview event with typical posthog-js properties.
pub fn realistic_pageview(distinct_id: &str) -> WrappedEvent {
    let uuid = Uuid::new_v4();
    WrappedEvent {
        event: Event {
            event: "$pageview".to_string(),
            uuid: uuid.to_string(),
            distinct_id: distinct_id.to_string(),
            timestamp: "2026-03-19T14:29:58.123Z".to_string(),
            session_id: Some("01jq9abc-def0-1234-5678-9abcdef01234".to_string()),
            window_id: Some("01jq9xyz-0000-4321-8765-fedcba987654".to_string()),
            options: RawOptions(serde_json::json!({
                "cookieless_mode": false,
                "process_person_profile": true
            })),
            properties: raw_obj(
                r#"{"$current_url":"https://app.example.com/dashboard","$referrer":"https://google.com","$browser":"Chrome","$browser_version":"120.0","$os":"Mac OS X","$lib":"posthog-js","$lib_version":"1.150.0","custom_prop":42}"#,
            ),
        },
        uuid,
        options: Options {
            cookieless_mode: Some(false),
            disable_skew_correction: None,
            product_tour_id: None,
            process_person_profile: Some(true),
        },
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:29:53.123Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::AnalyticsMain,
        force_disable_person_processing: false,
        is_gateway_verified: false,
    }
}

/// A realistic $identify event.
pub fn realistic_identify(distinct_id: &str) -> WrappedEvent {
    let uuid = Uuid::new_v4();
    WrappedEvent {
        event: Event {
            event: "$identify".to_string(),
            uuid: uuid.to_string(),
            distinct_id: distinct_id.to_string(),
            timestamp: "2026-03-19T14:30:01.000Z".to_string(),
            session_id: Some("01jq9abc-def0-1234-5678-9abcdef01234".to_string()),
            window_id: None,
            options: RawOptions(serde_json::json!({
                "process_person_profile": true
            })),
            properties: raw_obj(
                r#"{"$set":{"email":"user@example.com","name":"Test User"},"$set_once":{"created_at":"2026-01-01"},"$browser":"Safari","$os":"iOS"}"#,
            ),
        },
        uuid,
        options: Options {
            cookieless_mode: None,
            disable_skew_correction: None,
            product_tour_id: None,
            process_person_profile: Some(true),
        },
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:29:56.000Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::AnalyticsMain,
        force_disable_person_processing: false,
        is_gateway_verified: false,
    }
}

/// A realistic custom event.
pub fn realistic_custom(distinct_id: &str, event_name: &str) -> WrappedEvent {
    let uuid = Uuid::new_v4();
    WrappedEvent {
        event: Event {
            event: event_name.to_string(),
            uuid: uuid.to_string(),
            distinct_id: distinct_id.to_string(),
            timestamp: "2026-03-19T14:30:05.500Z".to_string(),
            session_id: Some("01jq9abc-def0-1234-5678-9abcdef01234".to_string()),
            window_id: Some("01jq9xyz-0000-4321-8765-fedcba987654".to_string()),
            options: RawOptions(serde_json::json!({
                "process_person_profile": true
            })),
            properties: raw_obj(
                r#"{"button_id":"cta-signup","$current_url":"https://app.example.com/pricing"}"#,
            ),
        },
        uuid,
        options: Options {
            cookieless_mode: None,
            disable_skew_correction: None,
            product_tour_id: None,
            process_person_profile: Some(true),
        },
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:30:00.500Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::AnalyticsMain,
        force_disable_person_processing: false,
        is_gateway_verified: false,
    }
}

/// A realistic 3-event batch for round-trip tests.
pub fn realistic_batch() -> Vec<WrappedEvent> {
    vec![
        realistic_pageview("user-42"),
        realistic_identify("user-42"),
        realistic_custom("user-42", "button_clicked"),
    ]
}

/// 6-event batch with `user-pos-{0..5}` distinct_ids and per-slot state:
/// 0=Ok/Main, 1=Drop, 2=Ok/Main, 3=Warning, 4=Ok/Overflow, 5=Ok/Historical.
pub fn realistic_ordered_mixed_batch() -> Vec<WrappedEvent> {
    let pageview_ok = realistic_pageview("user-pos-0");

    let mut malformed = realistic_pageview("user-pos-1");
    malformed.event.event = String::new();
    malformed.event.timestamp = "bad".to_string();
    malformed.adjusted_timestamp = None;
    malformed.result = EventResult::Drop;
    malformed.details = Some("missing_event_name");

    let identify_ok = realistic_identify("user-pos-2");

    let mut exception_warning = realistic_custom("user-pos-3", "$exception");
    exception_warning.result = EventResult::Warning;
    exception_warning.destination = Destination::Drop;
    exception_warning.details = Some("exceptions_over_quota");

    let click_overflow =
        realistic_custom("user-pos-4", "button_clicked").with_destination(Destination::Overflow);

    let pageview_historical =
        realistic_pageview("user-pos-5").with_destination(Destination::AnalyticsHistorical);

    vec![
        pageview_ok,
        malformed,
        identify_ok,
        exception_warning,
        click_overflow,
        pageview_historical,
    ]
}

/// Two distinct `Event`s sharing one UUID — for the dup-uuid bail.
pub fn realistic_dup_uuid_pair() -> (Event, Event) {
    let shared_uuid = Uuid::new_v4().to_string();
    let first = Event {
        event: "$pageview".to_string(),
        uuid: shared_uuid.clone(),
        distinct_id: "user-dup-A".to_string(),
        timestamp: "2026-03-19T14:29:58.123Z".to_string(),
        session_id: Some("01jq9abc-def0-1234-5678-9abcdef01234".to_string()),
        window_id: Some("01jq9xyz-0000-4321-8765-fedcba987654".to_string()),
        options: RawOptions(serde_json::json!({
            "cookieless_mode": false,
            "process_person_profile": true
        })),
        properties: raw_obj(r#"{"$current_url":"https://app.example.com/dashboard"}"#),
    };
    let second = Event {
        event: "$identify".to_string(),
        uuid: shared_uuid,
        distinct_id: "user-dup-B".to_string(),
        timestamp: "2026-03-19T14:30:01.000Z".to_string(),
        session_id: Some("01jq9abc-def0-1234-5678-9abcdef01234".to_string()),
        window_id: None,
        options: RawOptions::default(),
        properties: raw_obj(r#"{"$set":{"email":"user@example.com"}}"#),
    };
    (first, second)
}

/// One Ok event per `Destination` variant + one pre-marked Drop, with
/// ordinal `user-dest-{0..5}` distinct_ids.
pub fn realistic_spread_destinations() -> Vec<WrappedEvent> {
    let main = realistic_pageview("user-dest-0").with_destination(Destination::AnalyticsMain);
    let historical =
        realistic_pageview("user-dest-1").with_destination(Destination::AnalyticsHistorical);
    let overflow = realistic_pageview("user-dest-2").with_destination(Destination::Overflow);
    let dlq = realistic_pageview("user-dest-3").with_destination(Destination::Dlq);
    let custom = realistic_pageview("user-dest-4")
        .with_destination(Destination::Custom("custom_topic".to_string()));
    let dropped = realistic_pageview("user-dest-5")
        .with_result(EventResult::Drop, Some("missing_event_name"))
        .with_destination(Destination::Drop);
    vec![main, historical, overflow, dlq, custom, dropped]
}

/// Builder for mutating a WrappedEvent after creation.
pub trait WrappedEventMut {
    fn with_destination(self, d: Destination) -> Self;
    fn with_force_disable_person_processing(self, v: bool) -> Self;
    fn with_result(self, r: EventResult, details: Option<&'static str>) -> Self;
    fn with_properties(self, raw: &str) -> Self;
}

impl WrappedEventMut for WrappedEvent {
    fn with_destination(mut self, d: Destination) -> Self {
        self.destination = d;
        self
    }

    fn with_force_disable_person_processing(mut self, v: bool) -> Self {
        self.force_disable_person_processing = v;
        self
    }

    fn with_result(mut self, r: EventResult, details: Option<&'static str>) -> Self {
        self.result = r;
        self.details = details;
        self
    }

    fn with_properties(mut self, raw: &str) -> Self {
        self.event.properties = raw_obj(raw);
        self
    }
}

/// Assert that a serialized WrappedEvent round-trips through CapturedEvent
/// and its inner data field round-trips through RawEvent.
pub fn assert_round_trip(
    wrapped: &WrappedEvent,
    ctx: &RequestContext,
) -> (common_types::CapturedEvent, common_types::RawEvent) {
    use crate::v1::sinks::event::Event as SinkEvent;

    let buf = wrapped.serialize(ctx).expect("serialize failed");
    let captured: common_types::CapturedEvent =
        serde_json::from_slice(&buf).expect("v1 output must deserialize as CapturedEvent");
    let data: common_types::RawEvent =
        serde_json::from_str(&captured.data).expect("data field must deserialize as RawEvent");

    assert_eq!(captured.uuid, wrapped.uuid);
    assert_eq!(captured.distinct_id, wrapped.event.distinct_id);
    assert_eq!(captured.event, wrapped.event.event);

    (captured, data)
}

// ---------------------------------------------------------------------------
// Payload generators for batch-level tests
// ---------------------------------------------------------------------------

/// Serialize a list of Events into a valid V1 batch JSON payload.
pub fn batch_payload(events: &[Event]) -> Vec<u8> {
    let batch_json = serde_json::json!({
        "created_at": "2026-03-19T14:30:00.000Z",
        "batch": events.iter().map(|e| {
            let mut obj = serde_json::json!({
                "event": e.event,
                "uuid": e.uuid,
                "distinct_id": e.distinct_id,
                "timestamp": e.timestamp,
                "options": e.options,
            });
            obj.as_object_mut().unwrap().insert(
                "properties".to_string(),
                serde_json::from_str(e.properties.get()).unwrap(),
            );
            if let Some(ref sid) = e.session_id {
                obj.as_object_mut().unwrap().insert(
                    "session_id".to_string(),
                    serde_json::Value::String(sid.clone()),
                );
            }
            if let Some(ref wid) = e.window_id {
                obj.as_object_mut().unwrap().insert(
                    "window_id".to_string(),
                    serde_json::Value::String(wid.clone()),
                );
            }
            obj
        }).collect::<Vec<_>>(),
    });
    serde_json::to_vec(&batch_json).unwrap()
}

/// Compress raw bytes using the given encoding.
/// Supported: "gzip", "deflate", "br", "zstd"
#[cfg(test)]
pub fn compressed_payload(data: &[u8], encoding: &str) -> Vec<u8> {
    match encoding {
        "gzip" => {
            use flate2::write::GzEncoder;
            use flate2::Compression;
            use std::io::Write;
            let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
            encoder.write_all(data).unwrap();
            encoder.finish().unwrap()
        }
        "deflate" => {
            use flate2::write::DeflateEncoder;
            use flate2::Compression;
            use std::io::Write;
            let mut encoder = DeflateEncoder::new(Vec::new(), Compression::fast());
            encoder.write_all(data).unwrap();
            encoder.finish().unwrap()
        }
        "br" => {
            let mut output = Vec::new();
            let params = brotli::enc::BrotliEncoderParams::default();
            brotli::BrotliCompress(&mut std::io::Cursor::new(data), &mut output, &params).unwrap();
            output
        }
        "zstd" => zstd::encode_all(std::io::Cursor::new(data), 1).unwrap(),
        other => panic!("unsupported encoding for test: {other}"),
    }
}

/// Event with all options populated.
pub fn event_with_all_options() -> Event {
    Event {
        event: "$pageview".to_string(),
        uuid: Uuid::new_v4().to_string(),
        distinct_id: "user-all-opts".to_string(),
        timestamp: "2026-03-19T14:29:58.123Z".to_string(),
        session_id: Some("sess-all".to_string()),
        window_id: Some("win-all".to_string()),
        options: RawOptions(serde_json::json!({
            "cookieless_mode": true,
            "disable_skew_correction": true,
            "product_tour_id": "tour-v2",
            "process_person_profile": false
        })),
        properties: raw_obj(r#"{"existing":"prop"}"#),
    }
}

/// Event with empty `options: {}`.
pub fn event_with_empty_options() -> Event {
    Event {
        event: "$pageview".to_string(),
        uuid: Uuid::new_v4().to_string(),
        distinct_id: "user-empty-opts".to_string(),
        timestamp: "2026-03-19T14:29:58.123Z".to_string(),
        session_id: None,
        window_id: None,
        options: RawOptions::default(),
        properties: raw_obj("{}"),
    }
}

// ---------------------------------------------------------------------------
// Mock SinkResult for unit testing merge logic
// ---------------------------------------------------------------------------

use std::borrow::Cow;
use std::time::Duration;

use crate::v1::sinks::types::{Outcome, SinkResult as SinkResultTrait};

/// Concrete SinkResult for testing — all fields are user-specified.
pub struct MockSinkResult {
    pub uuid: Uuid,
    pub outcome: Outcome,
    pub cause: Option<&'static str>,
    pub detail: Option<String>,
    pub elapsed: Option<Duration>,
}

impl MockSinkResult {
    pub fn success(uuid: Uuid) -> Box<dyn SinkResultTrait> {
        Box::new(Self {
            uuid,
            outcome: Outcome::Success,
            cause: None,
            detail: None,
            elapsed: Some(Duration::from_millis(5)),
        })
    }

    pub fn retriable(uuid: Uuid, cause: &'static str) -> Box<dyn SinkResultTrait> {
        Box::new(Self {
            uuid,
            outcome: Outcome::RetriableError,
            cause: Some(cause),
            detail: Some(format!("{cause}: queue full")),
            elapsed: Some(Duration::from_millis(100)),
        })
    }

    pub fn timeout(uuid: Uuid) -> Box<dyn SinkResultTrait> {
        Box::new(Self {
            uuid,
            outcome: Outcome::Timeout,
            cause: Some("timeout"),
            detail: Some("message delivery timed out".to_string()),
            elapsed: Some(Duration::from_secs(30)),
        })
    }

    pub fn fatal(uuid: Uuid, cause: &'static str) -> Box<dyn SinkResultTrait> {
        Box::new(Self {
            uuid,
            outcome: Outcome::FatalError,
            cause: Some(cause),
            detail: Some(format!("{cause}: permanent failure")),
            elapsed: None,
        })
    }

    pub fn fatal_no_cause(uuid: Uuid) -> Box<dyn SinkResultTrait> {
        Box::new(Self {
            uuid,
            outcome: Outcome::FatalError,
            cause: None,
            detail: None,
            elapsed: None,
        })
    }
}

impl SinkResultTrait for MockSinkResult {
    fn key(&self) -> Uuid {
        self.uuid
    }

    fn outcome(&self) -> Outcome {
        self.outcome
    }

    fn cause(&self) -> Option<&'static str> {
        self.cause
    }

    fn detail(&self) -> Option<Cow<'_, str>> {
        self.detail.as_ref().map(|s| Cow::Borrowed(s.as_str()))
    }

    fn elapsed(&self) -> Option<Duration> {
        self.elapsed
    }
}

// ---------------------------------------------------------------------------
// TestStateBuilder — builds a router::State for V1 pipeline integration tests
// ---------------------------------------------------------------------------

use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::Arc;

use common_redis::MockRedisClient;
use limiters::overflow::OverflowLimiter;
use limiters::redis::{QuotaResource, QUOTA_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;

use crate::config::CaptureMode;
use crate::event_restrictions::EventRestrictionService;
use crate::global_rate_limiter::GlobalRateLimiter;
use crate::quota_limiters::CaptureQuotaLimiter;
use crate::router::{self, HistoricalConfig};
use crate::sinks;
use crate::time::TimeSource;
use crate::v1::sinks::kafka::mock::MockProducer;
use crate::v1::sinks::kafka::sink::KafkaSink;
use crate::v1::sinks::sink::Sink;
use crate::v1::sinks::{self as v1_sinks, SinkName};

/// Result of building a test state — gives access to both the `router::State`
/// and the underlying `MockProducer` so tests can inspect sent records.
pub struct TestState {
    pub state: router::State,
    pub mock_producer: Arc<MockProducer>,
}

/// Builder for `router::State` with configurable mock services.
pub struct TestStateBuilder {
    quota_limited: bool,
    overflow_limiter: Option<(NonZeroU32, NonZeroU32)>,
    historical_threshold_days: Option<i64>,
    restriction_service: Option<EventRestrictionService>,
    global_rate_limiter: Option<Arc<GlobalRateLimiter>>,
    mock_producer: Option<Arc<MockProducer>>,
    ai_gateway_signing_secret: Option<String>,
}

impl Default for TestStateBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl TestStateBuilder {
    pub fn new() -> Self {
        Self {
            quota_limited: false,
            overflow_limiter: None,
            historical_threshold_days: None,
            restriction_service: None,
            global_rate_limiter: None,
            mock_producer: None,
            ai_gateway_signing_secret: None,
        }
    }

    /// Configure quota limiter to reject all events for any token.
    pub fn with_quota_limited(mut self) -> Self {
        self.quota_limited = true;
        self
    }

    /// Set the AI-gateway HMAC signing secret used by provenance verification.
    pub fn with_ai_gateway_signing_secret(mut self, secret: impl Into<String>) -> Self {
        self.ai_gateway_signing_secret = Some(secret.into());
        self
    }

    /// Add an in-process overflow limiter with the given rate and burst.
    pub fn with_overflow_limiter(mut self, per_second: u32, burst: u32) -> Self {
        self.overflow_limiter = Some((
            NonZeroU32::new(per_second).expect("per_second must be > 0"),
            NonZeroU32::new(burst).expect("burst must be > 0"),
        ));
        self
    }

    /// Enable historical rerouting with the given threshold in days.
    pub fn with_historical_rerouting(mut self, threshold_days: i64) -> Self {
        self.historical_threshold_days = Some(threshold_days);
        self
    }

    /// Add a restriction service.
    pub fn with_restriction_service(mut self, service: EventRestrictionService) -> Self {
        self.restriction_service = Some(service);
        self
    }

    /// Add a global rate limiter.
    pub fn with_global_rate_limiter(mut self, limiter: Arc<GlobalRateLimiter>) -> Self {
        self.global_rate_limiter = Some(limiter);
        self
    }

    /// Supply a pre-configured MockProducer (e.g. for error injection).
    pub fn with_mock_producer(mut self, producer: Arc<MockProducer>) -> Self {
        self.mock_producer = Some(producer);
        self
    }

    pub fn build(self) -> TestState {
        let mut manager = lifecycle::Manager::builder("test_state")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .build();
        let handle = manager.register("test_state", lifecycle::ComponentOptions::new());
        handle.report_healthy();
        let _monitor = manager.monitor_background();

        let redis: Arc<dyn common_redis::Client + Send + Sync> = if self.quota_limited {
            let mut mock = MockRedisClient::new();
            for resource in &[
                QuotaResource::Events,
                QuotaResource::Recordings,
                QuotaResource::Exceptions,
                QuotaResource::Surveys,
                QuotaResource::LLMEvents,
            ] {
                let key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, resource.as_str());
                // Return a wildcard token so every token is limited
                mock = mock.zrangebyscore_ret(&key, vec!["*".to_string()]);
            }
            Arc::new(mock)
        } else {
            Arc::new(MockRedisClient::new())
        };

        // CaptureQuotaLimiter needs a Config — build a minimal one via envconfig
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "events"),
            ("KAFKA_HOSTS", "localhost:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let cfg: crate::config::Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("failed to build test Config");

        let quota_limiter = CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60));

        let historical_cfg = match self.historical_threshold_days {
            Some(days) => HistoricalConfig::new(true, days),
            None => HistoricalConfig::new(false, 1),
        };

        let overflow_limiter = self
            .overflow_limiter
            .map(|(per_sec, burst)| Arc::new(OverflowLimiter::new(per_sec, burst, None, false)));

        // Build the v1 sink router with a MockProducer-backed KafkaSink
        let mock_producer = self
            .mock_producer
            .unwrap_or_else(|| Arc::new(MockProducer::new(SinkName::Msk, handle.clone())));

        let kafka_config = test_kafka_config();
        let sink_config = v1_sinks::Config {
            produce_timeout: Duration::from_secs(30),
            kafka: kafka_config,
        };

        let kafka_sink = KafkaSink::new(
            SinkName::Msk,
            Arc::clone(&mock_producer),
            sink_config,
            CaptureMode::Events,
            handle.clone(),
        );

        let boxed_sink: Box<dyn Sink> = Box::new(kafka_sink);
        let sinks_map: HashMap<SinkName, Box<dyn Sink>> =
            [(SinkName::Msk, boxed_sink)].into_iter().collect();
        let v1_router = v1_sinks::Router::new(SinkName::Msk, sinks_map);

        // Legacy sink — no-op since V1 tests go through v1_sink_router
        let legacy_sink: Arc<dyn sinks::Event + Send + Sync> =
            Arc::new(crate::sinks::noop::NoOpSink::new());

        let timesource: Arc<dyn TimeSource + Send + Sync> = Arc::new(crate::time::SystemTime {});

        let state = router::State {
            sink: legacy_sink,
            timesource,
            redis,
            global_rate_limiter_token_distinctid: self.global_rate_limiter,
            quota_limiter: Arc::new(quota_limiter),
            token_dropper: Arc::new(TokenDropper::default()),
            event_restriction_service: self.restriction_service,
            event_payload_size_limit: 20 * 1024 * 1024,
            historical_cfg,
            is_mirror_deploy: false,
            verbose_sample_percent: 0.0,
            ai_max_sum_of_parts_bytes: 100 * 1024 * 1024,
            ai_blob_storage: None,
            body_chunk_read_timeout: None,
            body_read_chunk_size_kb: 64,
            capture_v1_max_compressed_body_bytes: 2 * 1024 * 1024,
            capture_v1_max_decompressed_body_bytes: 20 * 1024 * 1024,
            overflow_limiter,
            replay_overflow_limiter: None,
            v1_sink_router: Some(Arc::new(v1_router)),
            capture_v1_scatter_gather_min_batch: 8,
            ai_gateway_signing_secret: self.ai_gateway_signing_secret,
        };

        TestState {
            state,
            mock_producer,
        }
    }
}
