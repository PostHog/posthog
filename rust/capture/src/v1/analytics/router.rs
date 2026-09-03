use axum::Router;

use super::constants::{
    CAPTURE_V1_AI_PATH, CAPTURE_V1_AI_PATH_TRAILING, CAPTURE_V1_PATH, CAPTURE_V1_PATH_TRAILING,
};
use crate::router::State;

/// Route declarations only. The shared v1 middleware stack (headers, metrics,
/// timeout, CORS, limits) is owned by `crate::v1::router`.
pub fn routes() -> Router<State> {
    Router::new()
        .route(
            CAPTURE_V1_PATH,
            axum::routing::post(super::handler::handle_request),
        )
        .route(
            CAPTURE_V1_PATH_TRAILING,
            axum::routing::post(super::handler::handle_request),
        )
}

/// The AI lane's v1 endpoint. Same handler, same request and response
/// contract, same middleware; only the path differs, so the ingress can send
/// v1 AI traffic to capture-ai, which produces straight to the AI topic and
/// applies its own `AI_MAX_EVENT_BYTES` ceiling.
///
/// The handler needs no AI-specific branch: every AI behavior in the v1
/// pipeline (gateway provenance, the llm_events quota exemption, `Pipeline::Ai`
/// restrictions, the per-event size ceiling, the byte-rate limiter, and the
/// `Destination::AiEvents` lane itself) keys off the event name, not the path.
/// What the path decides is which deployment answers, which `crate::router`
/// gates on the capture mode.
pub fn ai_routes() -> Router<State> {
    Router::new()
        .route(
            CAPTURE_V1_AI_PATH,
            axum::routing::post(super::handler::handle_request),
        )
        .route(
            CAPTURE_V1_AI_PATH_TRAILING,
            axum::routing::post(super::handler::handle_request),
        )
}
