use axum::extract::Request;
use axum::http::{header, HeaderValue};
use axum::middleware::Next;
use axum::response::Response;
use axum::Router;
use chrono::Utc;

use super::header::POSTHOG_REQUEST_ID;
use crate::router::State;

pub fn router() -> Router<State> {
    Router::new()
        .route(
            "/i/v1/e",
            axum::routing::post(super::handler::handle_request),
        )
        .route(
            "/i/v1/e/",
            axum::routing::post(super::handler::handle_request),
        )
        .layer(axum::middleware::from_fn(v1_common_headers))
}

async fn v1_common_headers(req: Request, next: Next) -> Response {
    let received_at = Utc::now();
    let request_id = req.headers().get(POSTHOG_REQUEST_ID).cloned();

    let mut response = next.run(req).await;

    let headers = response.headers_mut();
    if let Ok(date_val) = HeaderValue::from_str(&received_at.to_rfc2822()) {
        headers.insert(header::DATE, date_val);
    }
    if let Some(id) = request_id {
        headers.insert(POSTHOG_REQUEST_ID, id);
    }

    response
}
