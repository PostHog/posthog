use std::time::Instant;

use axum::extract::{MatchedPath, Request};
use axum::http::{header, HeaderValue};
use axum::middleware::Next;
use axum::response::Response;
use axum::Router;
use chrono::Utc;

use super::constants::{CAPTURE_V1_PATH, CAPTURE_V1_PATH_TRAILING};
use crate::router::State;
use crate::v1::constants::{CAPTURE_V1_RESPONSE_TIME, POSTHOG_REQUEST_ID};

pub fn router() -> Router<State> {
    Router::new()
        .route(
            CAPTURE_V1_PATH,
            axum::routing::post(super::handler::handle_request),
        )
        .route(
            CAPTURE_V1_PATH_TRAILING,
            axum::routing::post(super::handler::handle_request),
        )
        .layer(axum::middleware::from_fn(v1_common_headers))
        .layer(axum::middleware::from_fn(v1_track_response_time))
}

pub(super) async fn v1_common_headers(req: Request, next: Next) -> Response {
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

pub(super) async fn v1_track_response_time(req: Request, next: Next) -> Response {
    let start = Instant::now();

    let path = req
        .extensions()
        .get::<MatchedPath>()
        .map(|m| m.as_str().to_owned())
        .unwrap_or_else(|| req.uri().path().to_owned());

    let response = next.run(req).await;

    let status = response.status().as_u16().to_string();
    let elapsed = start.elapsed().as_secs_f64();

    metrics::histogram!(
        CAPTURE_V1_RESPONSE_TIME,
        "status" => status,
        "path" => path,
    )
    .record(elapsed);

    response
}

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::{header, HeaderValue, Request, StatusCode};
    use axum::middleware;
    use axum::routing::get;
    use axum::Router;
    use chrono::DateTime;
    use tower::ServiceExt;
    use uuid::Uuid;

    use super::{v1_common_headers, v1_track_response_time};
    use crate::v1::constants::POSTHOG_REQUEST_ID;

    fn test_router() -> Router {
        Router::new()
            .route("/test", get(|| async { "ok" }))
            .layer(middleware::from_fn(v1_common_headers))
    }

    fn test_router_with_response_time() -> Router {
        Router::new()
            .route("/test", get(|| async { "ok" }))
            .route(
                "/error",
                get(|| async { StatusCode::INTERNAL_SERVER_ERROR }),
            )
            .layer(middleware::from_fn(v1_track_response_time))
    }

    #[tokio::test]
    async fn common_headers_sets_date() {
        let resp = test_router()
            .oneshot(Request::builder().uri("/test").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let date = resp
            .headers()
            .get(header::DATE)
            .expect("Date header missing");
        let parsed = DateTime::parse_from_rfc2822(date.to_str().unwrap());
        assert!(
            parsed.is_ok(),
            "Date header is not valid RFC 2822: {date:?}"
        );
    }

    #[tokio::test]
    async fn common_headers_passes_through_request_id() {
        let id = Uuid::new_v4().to_string();
        let resp = test_router()
            .oneshot(
                Request::builder()
                    .uri("/test")
                    .header(POSTHOG_REQUEST_ID, HeaderValue::from_str(&id).unwrap())
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let returned = resp
            .headers()
            .get(POSTHOG_REQUEST_ID)
            .expect("PostHog-Request-Id missing on response");
        assert_eq!(returned.to_str().unwrap(), id);
    }

    #[tokio::test]
    async fn common_headers_omits_request_id_when_absent() {
        let resp = test_router()
            .oneshot(Request::builder().uri("/test").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        assert!(
            resp.headers().get(POSTHOG_REQUEST_ID).is_none(),
            "PostHog-Request-Id should not be set when absent from request"
        );
    }

    // --- v1_track_response_time ---

    #[tokio::test]
    async fn response_time_middleware_passes_through_success() {
        let resp = test_router_with_response_time()
            .oneshot(Request::builder().uri("/test").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn response_time_middleware_passes_through_error_status() {
        let resp = test_router_with_response_time()
            .oneshot(
                Request::builder()
                    .uri("/error")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::INTERNAL_SERVER_ERROR);
    }
}
