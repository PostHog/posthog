#![allow(dead_code)]

use std::net::{IpAddr, Ipv4Addr};

use axum::http::Method;
use chrono::{DateTime, Utc};
use serde_json::value::RawValue;
use uuid::Uuid;

use crate::v1::analytics::query::Query;
use crate::v1::analytics::types::{Event, EventResult, Options, WrappedEvent};
use crate::v1::context::Context;
use crate::v1::sinks::Destination;

pub fn raw_obj(s: &str) -> Box<RawValue> {
    RawValue::from_string(s.to_owned()).unwrap()
}

pub fn default_options() -> Options {
    Options {
        cookieless_mode: None,
        disable_skew_adjustment: None,
        product_tour_id: None,
        process_person_profile: None,
    }
}

pub fn test_context() -> Context {
    Context {
        api_token: "phc_test_token".to_string(),
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
        path: "/i/v1/general/events".to_string(),
        server_received_at: Utc::now(),
        created_at: Some("2026-03-19T14:30:00.000Z".to_string()),
        capture_internal: false,
        historical_migration: false,
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
        options: default_options(),
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
            options: default_options(),
            properties: raw_obj("{}"),
        },
        uuid,
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:29:58.123Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::default(),
        force_disable_person_processing: false,
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
            options: default_options(),
            properties: raw_obj("{}"),
        },
        uuid,
        adjusted_timestamp: Some(timestamp),
        result: EventResult::Ok,
        details: None,
        destination: Destination::default(),
        force_disable_person_processing: false,
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
            options: default_options(),
            properties: raw_obj("{}"),
        },
        uuid,
        adjusted_timestamp: None,
        result: EventResult::Drop,
        details: Some("missing_event_name"),
        destination: Destination::default(),
        force_disable_person_processing: false,
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
            options: Options {
                cookieless_mode: Some(false),
                disable_skew_adjustment: None,
                product_tour_id: None,
                process_person_profile: Some(true),
            },
            properties: raw_obj(
                r#"{"$current_url":"https://app.example.com/dashboard","$referrer":"https://google.com","$browser":"Chrome","$browser_version":"120.0","$os":"Mac OS X","$lib":"posthog-js","$lib_version":"1.150.0","custom_prop":42}"#,
            ),
        },
        uuid,
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:29:53.123Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::AnalyticsMain,
        force_disable_person_processing: false,
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
            options: Options {
                cookieless_mode: None,
                disable_skew_adjustment: None,
                product_tour_id: None,
                process_person_profile: Some(true),
            },
            properties: raw_obj(
                r#"{"$set":{"email":"user@example.com","name":"Test User"},"$set_once":{"created_at":"2026-01-01"},"$browser":"Safari","$os":"iOS"}"#,
            ),
        },
        uuid,
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:29:56.000Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::AnalyticsMain,
        force_disable_person_processing: false,
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
            options: Options {
                cookieless_mode: None,
                disable_skew_adjustment: None,
                product_tour_id: None,
                process_person_profile: Some(true),
            },
            properties: raw_obj(
                r#"{"button_id":"cta-signup","$current_url":"https://app.example.com/pricing"}"#,
            ),
        },
        uuid,
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:30:00.500Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::AnalyticsMain,
        force_disable_person_processing: false,
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
/// 0=Ok/Main, 1=Drop, 2=Ok/Main, 3=Limited, 4=Ok/Overflow, 5=Ok/Historical.
pub fn realistic_ordered_mixed_batch() -> Vec<WrappedEvent> {
    let pageview_ok = realistic_pageview("user-pos-0");

    let mut malformed = realistic_pageview("user-pos-1");
    malformed.event.event = String::new();
    malformed.event.timestamp = "bad".to_string();
    malformed.adjusted_timestamp = None;
    malformed.result = EventResult::Drop;
    malformed.details = Some("missing_event_name");

    let identify_ok = realistic_identify("user-pos-2");

    let mut exception_limited = realistic_custom("user-pos-3", "$exception");
    exception_limited.result = EventResult::Limited;
    exception_limited.destination = Destination::Drop;
    exception_limited.details = Some("exceptions_over_quota");

    let click_overflow =
        realistic_custom("user-pos-4", "button_clicked").with_destination(Destination::Overflow);

    let pageview_historical =
        realistic_pageview("user-pos-5").with_destination(Destination::AnalyticsHistorical);

    vec![
        pageview_ok,
        malformed,
        identify_ok,
        exception_limited,
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
        options: Options {
            cookieless_mode: Some(false),
            disable_skew_adjustment: None,
            product_tour_id: None,
            process_person_profile: Some(true),
        },
        properties: raw_obj(r#"{"$current_url":"https://app.example.com/dashboard"}"#),
    };
    let second = Event {
        event: "$identify".to_string(),
        uuid: shared_uuid,
        distinct_id: "user-dup-B".to_string(),
        timestamp: "2026-03-19T14:30:01.000Z".to_string(),
        session_id: Some("01jq9abc-def0-1234-5678-9abcdef01234".to_string()),
        window_id: None,
        options: default_options(),
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
        .with_result(EventResult::Drop, Some("invalid_distinct_id"))
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
    ctx: &Context,
) -> (common_types::CapturedEvent, common_types::RawEvent) {
    use crate::v1::sinks::event::Event as SinkEvent;

    let mut buf = String::new();
    wrapped
        .serialize_into(ctx, &mut buf)
        .expect("serialize_into failed");
    let captured: common_types::CapturedEvent =
        serde_json::from_str(&buf).expect("v1 output must deserialize as CapturedEvent");
    let data: common_types::RawEvent =
        serde_json::from_str(&captured.data).expect("data field must deserialize as RawEvent");

    assert_eq!(captured.uuid, wrapped.uuid);
    assert_eq!(captured.distinct_id, wrapped.event.distinct_id);
    assert_eq!(captured.event, wrapped.event.event);

    (captured, data)
}
