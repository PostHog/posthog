use std::collections::HashMap;
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
    WrappedEvent {
        event: Event {
            event: event_name.to_string(),
            uuid: Uuid::new_v4().to_string(),
            distinct_id: distinct_id.to_string(),
            timestamp: "2026-03-19T14:29:58.123Z".to_string(),
            session_id: None,
            window_id: None,
            options: default_options(),
            properties: raw_obj("{}"),
        },
        adjusted_timestamp: Some(
            DateTime::parse_from_rfc3339("2026-03-19T14:29:58.123Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        result: EventResult::Ok,
        details: None,
        destination: Destination::default(),
        skip_person_processing: false,
    }
}

pub fn wrapped_event_at(timestamp: DateTime<Utc>) -> WrappedEvent {
    WrappedEvent {
        event: Event {
            event: "$pageview".to_string(),
            uuid: Uuid::new_v4().to_string(),
            distinct_id: "user-1".to_string(),
            timestamp: timestamp.to_rfc3339(),
            session_id: None,
            window_id: None,
            options: default_options(),
            properties: raw_obj("{}"),
        },
        adjusted_timestamp: Some(timestamp),
        result: EventResult::Ok,
        details: None,
        destination: Destination::default(),
        skip_person_processing: false,
    }
}

pub fn malformed_wrapped_event() -> WrappedEvent {
    WrappedEvent {
        event: Event {
            event: String::new(),
            uuid: Uuid::new_v4().to_string(),
            distinct_id: "user-1".to_string(),
            timestamp: "bad".to_string(),
            session_id: None,
            window_id: None,
            options: default_options(),
            properties: raw_obj("{}"),
        },
        adjusted_timestamp: None,
        result: EventResult::Drop,
        details: Some("missing_event_name"),
        destination: Destination::default(),
        skip_person_processing: false,
    }
}

pub fn events_map(events: Vec<WrappedEvent>) -> HashMap<Uuid, WrappedEvent> {
    events
        .into_iter()
        .map(|e| (Uuid::parse_str(&e.event.uuid).unwrap(), e))
        .collect()
}

pub fn find_by_did<'a>(
    events: &'a HashMap<Uuid, WrappedEvent>,
    distinct_id: &str,
) -> &'a WrappedEvent {
    events
        .values()
        .find(|e| e.event.distinct_id == distinct_id)
        .unwrap()
}
