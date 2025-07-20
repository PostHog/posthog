use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::Json,
    body::Bytes,
};
use serde_json::json;
use tracing::{error, info, warn};

use crate::config::Config;
use crate::sentry::SentryEvent;
use crate::converter::convert_sentry_to_posthog;
use crate::client::send_to_posthog;

pub async fn handle_sentry_event(
    Path(api_key): Path<String>,
    State(config): State<Config>,
    body: Bytes,
) -> Result<Json<serde_json::Value>, StatusCode> {
    // Parse Sentry event
    let sentry_event: SentryEvent = match serde_json::from_slice(&body) {
        Ok(event) => event,
        Err(e) => {
            error!("Failed to parse Sentry event: {}", e);
            return Err(StatusCode::BAD_REQUEST);
        }
    };

    info!(
        "Received Sentry event {} for API key {}",
        sentry_event.event_id,
        api_key
    );

    // Convert to PostHog format
    let posthog_event = convert_sentry_to_posthog(sentry_event, api_key, None);

    // Send to PostHog
    match send_to_posthog(&config, posthog_event).await {
        Ok(_) => {
            info!("Successfully forwarded event to PostHog");
            Ok(Json(json!({"id": uuid::Uuid::new_v4().to_string()})))
        }
        Err(e) => {
            error!("Failed to send event to PostHog: {}", e);
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
    }
}

pub async fn handle_sentry_envelope(
    Path(api_key): Path<String>,
    State(config): State<Config>,
    body: Bytes,
) -> Result<Json<serde_json::Value>, StatusCode> {
    // Parse envelope format (simplified - real implementation would need proper envelope parsing)
    let body_str = match std::str::from_utf8(&body) {
        Ok(s) => s,
        Err(e) => {
            error!("Failed to parse envelope as UTF-8: {}", e);
            return Err(StatusCode::BAD_REQUEST);
        }
    };

    // Sentry envelopes have headers on first line, then items
    let mut lines = body_str.lines();

    // Skip envelope header
    if lines.next().is_none() {
        error!("Empty envelope");
        return Err(StatusCode::BAD_REQUEST);
    }

    let mut event_id = uuid::Uuid::new_v4().to_string();

    // Process items
    while let Some(item_header) = lines.next() {
        if item_header.is_empty() {
            continue;
        }

        // Parse item header
        let item_header_json: serde_json::Value = match serde_json::from_str(item_header) {
            Ok(v) => v,
            Err(_) => continue,
        };

        let item_type = item_header_json.get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        if let Some(item_body) = lines.next() {
            match item_type {
                "event" | "error" => {
                    // Parse as Sentry event
                    if let Ok(sentry_event) = serde_json::from_str::<SentryEvent>(item_body) {
                        event_id = sentry_event.event_id.clone();
                        let posthog_event = convert_sentry_to_posthog(sentry_event, api_key.clone(), None);

                        if let Err(e) = send_to_posthog(&config, posthog_event).await {
                            error!("Failed to send event to PostHog: {}", e);
                            return Err(StatusCode::INTERNAL_SERVER_ERROR);
                        }
                    }
                }
                "session" | "attachment" | "user_report" => {
                    // These types are not relevant for exception tracking
                    warn!("Ignoring envelope item type: {}", item_type);
                }
                _ => {
                    warn!("Unknown envelope item type: {}", item_type);
                }
            }
        }
    }

    Ok(Json(json!({"id": event_id})))
}
