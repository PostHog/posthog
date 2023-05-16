use crate::{
    api::{CaptureRequest, CaptureResponse},
    token,
};
use axum::{http::StatusCode, Json};

/// A single event
/// Does not yet support everything the old method does - we expect to be able to deserialize the
/// entire POST body, and not keep checking for form attributes.
///
/// TODO: Switch on this between two handlers. DO NOT branch in the code.
/// TODO: Add error responses in the same format as capture.py. Probs custom extractor.
pub async fn event(
    req: Json<CaptureRequest>,
) -> Result<Json<CaptureResponse>, (StatusCode, String)> {
    tracing::info!("new event of type {}", req.token);

    // I wanted to do some sort of middleware that pulled the token out of the headers, but... The
    // token isn't usually in the headers, but in the body :(
    // Could move token parsing into the middleware at some point
    if let Err(invalid) = token::validate_token(req.token.as_str()) {
        return Err((StatusCode::BAD_REQUEST, invalid.reason().to_string()));
    }

    Ok(Json(CaptureResponse {}))
}

// A group of events! There is no limit here, though our HTTP stack will reject anything above
// 20mb.
pub async fn batch() -> &'static str {
    "No batching for you!"
}
