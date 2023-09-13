use std::collections::HashSet;
use std::ops::Deref;
use std::sync::Arc;

use anyhow::{anyhow, Result};
use bytes::Bytes;

use axum::{http::StatusCode, Json};
// TODO: stream this instead
use axum::extract::{Query, State};
use axum::http::HeaderMap;
use axum_client_ip::InsecureClientIp;
use base64::Engine;
use time::OffsetDateTime;

use crate::event::ProcessingContext;
use crate::token::validate_token;
use crate::{
    api::{CaptureResponse, CaptureResponseCode},
    event::{EventFormData, EventQuery, ProcessedEvent, RawEvent},
    router, sink,
    utils::uuid_v7,
};

pub async fn event(
    state: State<router::State>,
    InsecureClientIp(ip): InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<CaptureResponse>, (StatusCode, String)> {
    tracing::debug!(len = body.len(), "new event request");

    let events = match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/x-www-form-urlencoded" => {
            let input: EventFormData = serde_urlencoded::from_bytes(body.deref()).unwrap();
            let payload = base64::engine::general_purpose::STANDARD
                .decode(input.data)
                .unwrap();
            RawEvent::from_bytes(&meta, payload.into())
        }
        _ => RawEvent::from_bytes(&meta, body),
    };

    let events = match events {
        Ok(events) => events,
        Err(e) => {
            tracing::error!("failed to decode event: {:?}", e);
            return Err((
                StatusCode::BAD_REQUEST,
                String::from("Failed to decode event"),
            ));
        }
    };

    println!("Got events {:?}", &events);

    if events.is_empty() {
        return Err((StatusCode::BAD_REQUEST, String::from("No events in batch")));
    }
    let token = match extract_and_verify_token(&events) {
        Ok(token) => token,
        Err(msg) => return Err((StatusCode::UNAUTHORIZED, msg)),
    };

    let sent_at = meta.sent_at.and_then(|value| {
        let value_nanos: i128 = i128::from(value) * 1_000_000; // Assuming the value is in milliseconds, latest posthog-js releases
        if let Ok(sent_at) = OffsetDateTime::from_unix_timestamp_nanos(value_nanos) {
            if sent_at.year() > 2020 {
                // Could be lower if the input is in seconds
                return Some(sent_at);
            }
        }
        None
    });
    let context = ProcessingContext {
        lib_version: meta.lib_version.clone(),
        sent_at,
        token,
        now: state.timesource.current_time(),
        client_ip: ip.to_string(),
    };

    let processed = process_events(state.sink.clone(), &events, &context).await;

    if let Err(msg) = processed {
        return Err((StatusCode::BAD_REQUEST, msg));
    }

    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
    }))
}

pub fn process_single_event(
    event: &RawEvent,
    context: &ProcessingContext,
) -> Result<ProcessedEvent> {
    let distinct_id = match &event.distinct_id {
        Some(id) => id,
        None => match event.properties.get("distinct_id").map(|v| v.as_str()) {
            Some(Some(id)) => id,
            _ => return Err(anyhow!("missing distinct_id")),
        },
    };

    Ok(ProcessedEvent {
        uuid: event.uuid.unwrap_or_else(uuid_v7),
        distinct_id: distinct_id.to_string(),
        ip: context.client_ip.clone(),
        site_url: String::new(),
        data: String::from("hallo I am some data 😊"),
        now: context.now.clone(),
        sent_at: context.sent_at,
        token: context.token.clone(),
    })
}

pub fn extract_and_verify_token(events: &[RawEvent]) -> Result<String, String> {
    let distinct_tokens: HashSet<Option<String>> = HashSet::from_iter(
        events
            .iter()
            .map(RawEvent::extract_token)
            .filter(Option::is_some),
    );

    return match distinct_tokens.len() {
        0 => Err(String::from("no token found in request")),
        1 => match distinct_tokens.iter().last() {
            Some(Some(token)) => {
                validate_token(token).map_err(|err| String::from(err.reason()))?;
                Ok(token.clone())
            }
            _ => Err(String::from("no token found in request")),
        },
        _ => Err(String::from("number of distinct tokens in batch > 1")),
    };
}

pub async fn process_events(
    sink: Arc<dyn sink::EventSink + Send + Sync>,
    events: &[RawEvent],
    context: &ProcessingContext,
) -> Result<(), String> {
    let events: Vec<ProcessedEvent> = match events
        .iter()
        .map(|e| process_single_event(e, context))
        .collect()
    {
        Err(_) => return Err(String::from("Failed to process all events")),
        Ok(events) => events,
    };

    if events.len() == 1 {
        let sent = sink.send(events[0].clone()).await;

        if let Err(e) = sent {
            tracing::error!("Failed to send event to sink: {:?}", e);

            return Err(String::from("Failed to send event to sink"));
        }
    } else {
        let sent = sink.send_batch(events).await;

        if let Err(e) = sent {
            tracing::error!("Failed to send batch events to sink: {:?}", e);

            return Err(String::from("Failed to send batch events to sink"));
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use crate::capture::extract_and_verify_token;
    use crate::event::RawEvent;
    use serde_json::json;
    use std::collections::HashMap;

    #[tokio::test]
    async fn all_events_have_same_token() {
        let events = vec![
            RawEvent {
                token: Some(String::from("hello")),
                distinct_id: Some("testing".to_string()),
                uuid: None,
                event: String::new(),
                properties: HashMap::new(),
            },
            RawEvent {
                token: None,
                distinct_id: Some("testing".to_string()),
                uuid: None,
                event: String::new(),
                properties: HashMap::from([(String::from("token"), json!("hello"))]),
            },
        ];

        let processed = extract_and_verify_token(&events);
        assert_eq!(processed.is_ok(), true, "{:?}", processed);
    }

    #[tokio::test]
    async fn all_events_have_different_token() {
        let events = vec![
            RawEvent {
                token: Some(String::from("hello")),
                distinct_id: Some("testing".to_string()),
                uuid: None,
                event: String::new(),
                properties: HashMap::new(),
            },
            RawEvent {
                token: None,
                distinct_id: Some("testing".to_string()),
                uuid: None,
                event: String::new(),
                properties: HashMap::from([(String::from("token"), json!("goodbye"))]),
            },
        ];

        let processed = extract_and_verify_token(&events);
        assert_eq!(processed.is_err(), true);
    }
}
