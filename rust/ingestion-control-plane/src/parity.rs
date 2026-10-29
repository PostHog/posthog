use std::time::Duration;

use axum::extract::State;
use axum::Json;
use chrono::{DateTime, Utc};
use reqwest::StatusCode;
use serde::Serialize;

use crate::api::ApiError;
use crate::state::AppState;

/// The shared client has no timeout because the pod proxy streams SSE.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Serialize)]
pub struct ParityMismatches {
    pub fetched_at: DateTime<Utc>,
    pub samples: Vec<serde_json::Value>,
}

fn mismatches_url(base: &str) -> String {
    format!("{}/debug/mismatches", base.trim_end_matches('/'))
}

pub async fn mismatches(State(state): State<AppState>) -> Result<Json<ParityMismatches>, ApiError> {
    let base = state
        .config
        .parity_monitor_url
        .as_deref()
        .filter(|url| !url.is_empty())
        .ok_or_else(|| {
            ApiError::unavailable("the parity view is disabled (PARITY_MONITOR_URL not set)")
        })?;

    let mut request = state
        .http
        .get(mismatches_url(base))
        .timeout(REQUEST_TIMEOUT);
    if let Some(secret) = state
        .config
        .debug_api_secret
        .as_deref()
        .filter(|s| !s.is_empty())
    {
        request = request.header("X-Debug-Api-Secret", secret);
    }
    let response = request
        .send()
        .await
        .map_err(|e| ApiError::upstream(format!("parity monitor request failed: {e}")))?;

    match response.status() {
        StatusCode::NOT_FOUND => {
            return Err(ApiError::unavailable(
                "the parity monitor answered 404: its debug API is off (DEBUG_API_SECRET not set on the monitor) or PARITY_MONITOR_URL points elsewhere",
            ))
        }
        StatusCode::UNAUTHORIZED => {
            return Err(ApiError::upstream(
                "the parity monitor rejected the secret: DEBUG_API_SECRET differs between the control plane and the monitor",
            ))
        }
        status if !status.is_success() => {
            return Err(ApiError::upstream(format!(
                "parity monitor answered {status}"
            )))
        }
        _ => {}
    }
    let samples = response
        .json()
        .await
        .map_err(|e| ApiError::upstream(format!("parity monitor sent an unreadable body: {e}")))?;
    Ok(Json(ParityMismatches {
        fetched_at: Utc::now(),
        samples,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mismatches_url_tolerates_a_trailing_slash() {
        for base in ["http://monitor:3301", "http://monitor:3301/"] {
            assert_eq!(mismatches_url(base), "http://monitor:3301/debug/mismatches");
        }
    }
}
