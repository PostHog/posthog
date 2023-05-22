use std::collections::HashSet;

use bytes::Bytes;

use axum::{http::StatusCode, Json};
// TODO: stream this instead
use axum::extract::Query;

use crate::{
    api::CaptureResponse,
    event::{Event, EventQuery},
    token,
};

pub async fn event(
    meta: Query<EventQuery>,
    body: Bytes,
) -> Result<Json<CaptureResponse>, (StatusCode, String)> {
    let events = Event::from_bytes(&meta, body);

    let events = match events {
        Ok(events) => events,
        Err(_) => {
            return Err((
                StatusCode::BAD_REQUEST,
                String::from("Failed to decode event"),
            ))
        }
    };

    if events.is_empty() {
        return Err((StatusCode::BAD_REQUEST, String::from("No events in batch")));
    }

    let processed = process_events(&events);

    if let Err(msg) = processed {
        return Err((StatusCode::BAD_REQUEST, msg));
    }

    Ok(Json(CaptureResponse {}))
}

pub fn process_events(events: &[Event]) -> Result<(), String> {
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

    Ok(())
}

// A group of events! There is no limit here, though our HTTP stack will reject anything above
// 20mb.
pub async fn batch() -> &'static str {
    "No batching for you!"
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use serde_json::json;

    use super::process_events;
    use crate::event::Event;

    #[test]
    fn all_events_have_same_token() {
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

        assert_eq!(process_events(&events).is_ok(), true);
    }

    #[test]
    fn all_events_have_different_token() {
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

        assert_eq!(process_events(&events).is_err(), true);
    }
}
