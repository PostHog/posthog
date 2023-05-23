use std::collections::HashSet;
use std::ops::Deref;
use std::sync::Arc;

use anyhow::Result;
use bytes::Bytes;

use axum::{http::StatusCode, Json};
// TODO: stream this instead
use axum::extract::{Query, State};
use axum::http::HeaderMap;
use base64::Engine;
use uuid::Uuid;

use crate::api::CaptureResponseCode;
use crate::event::ProcessedEvent;

use crate::{
    api::CaptureResponse,
    event::{Event, EventFormData, EventQuery},
    router, sink, token,
};

pub async fn event(
    state: State<router::State>,
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
            Event::from_bytes(&meta, payload.into())
        }
        _ => Event::from_bytes(&meta, body),
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

    let processed = process_events(state.sink.clone(), &events).await;

    if let Err(msg) = processed {
        return Err((StatusCode::BAD_REQUEST, msg));
    }

    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
    }))
}

pub fn process_single_event(_event: &Event) -> Result<ProcessedEvent> {
    // TODO: Put actual data in here and transform it properly
    Ok(ProcessedEvent {
        uuid: Uuid::new_v4(),
        distinct_id: Uuid::new_v4().simple().to_string(),
        ip: String::new(),
        site_url: String::new(),
        data: String::from("hallo I am some data 😊"),
        now: String::new(),
        sent_at: String::new(),
        token: String::from("tokentokentoken"),
    })
}

pub async fn process_events(
    sink: Arc<dyn sink::EventSink + Send + Sync>,
    events: &[Event],
) -> Result<(), String> {
    let mut distinct_tokens = HashSet::new();

    // 1. Tokens are all valid
    for event in events {
        let token = event.token.clone().unwrap_or_else(|| {
            event
                .properties
                .get("token")
                .map_or(String::new(), |t| String::from(t.as_str().unwrap()))
        });

        if let Err(invalid) = token::validate_token(token.as_str()) {
            return Err(invalid.reason().to_string());
        }

        distinct_tokens.insert(token);
    }

    if distinct_tokens.len() > 1 {
        return Err(String::from("Number of distinct tokens in batch > 1"));
    }

    let events: Vec<ProcessedEvent> = match events.iter().map(process_single_event).collect() {
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
        let sent = sink.send_batch(&events).await;

        if let Err(e) = sent {
            tracing::error!("Failed to send batch events to sink: {:?}", e);

            return Err(String::from("Failed to send batch events to sink"));
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use crate::sink;
    use std::collections::HashMap;
    use std::sync::Arc;

    use serde_json::json;

    use super::process_events;
    use crate::event::Event;
    use crate::router::State;

    #[tokio::test]
    async fn all_events_have_same_token() {
        let state = State {
            sink: Arc::new(sink::PrintSink {}),
        };

        let events = vec![
            Event {
                token: Some(String::from("hello")),
                event: String::new(),
                properties: HashMap::new(),
            },
            Event {
                token: None,
                event: String::new(),
                properties: HashMap::from([(String::from("token"), json!("hello"))]),
            },
        ];

        let processed = process_events(state.sink, &events).await;
        assert_eq!(processed.is_ok(), true);
    }

    #[tokio::test]
    async fn all_events_have_different_token() {
        let state = State {
            sink: Arc::new(sink::PrintSink {}),
        };

        let events = vec![
            Event {
                token: Some(String::from("hello")),
                event: String::new(),
                properties: HashMap::new(),
            },
            Event {
                token: None,
                event: String::new(),
                properties: HashMap::from([(String::from("token"), json!("goodbye"))]),
            },
        ];

        let processed = process_events(state.sink, &events).await;
        assert_eq!(processed.is_err(), true);
    }
}
