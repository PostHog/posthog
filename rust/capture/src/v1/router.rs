//! Top-level v1 router. Owns the complete middleware stack for every v1
//! endpoint so no legacy/v0 layer (CORS, body limits, etc.) applies to v1
//! requests. `crate::router` merges this after all legacy layers are in place;
//! future v1 endpoints mount their routes here to inherit the same contract.
//!
//! Stack, outermost first:
//!   CORS -> response-time metric -> common headers
//!   -> concurrency limit -> body-size backstop -> routes

use axum::extract::DefaultBodyLimit;
use axum::http::Method;
use axum::Router;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::cors::{AllowHeaders, AllowOrigin, CorsLayer};

use crate::router::State;
use crate::v1::middleware::{v1_common_headers, v1_track_response_time};

pub struct RouterConfig {
    /// Per-route in-flight cap, same `CONCURRENCY_LIMIT` value the legacy
    /// router applies to its own routes (axum's `Router::layer` wraps each
    /// route individually, so every route gets its own permit pool).
    pub concurrency_limit: Option<usize>,
    /// Backstop only: `v1::util` enforces the real compressed-size limit and
    /// returns the 413 envelope before this extractor-level limit can trip.
    pub max_compressed_body_bytes: usize,
}

pub fn router(cfg: RouterConfig) -> Router<State> {
    // v1 endpoints are POST-only; preflight is answered by the CORS layer.
    let cors = CorsLayer::new()
        .allow_methods([Method::POST, Method::OPTIONS])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    let mut router = crate::v1::analytics::router::routes()
        .layer(DefaultBodyLimit::max(cfg.max_compressed_body_bytes));

    if let Some(limit) = cfg.concurrency_limit {
        router = router.layer(ConcurrencyLimitLayer::new(limit));
    }

    router
        .layer(axum::middleware::from_fn(v1_common_headers))
        .layer(axum::middleware::from_fn(v1_track_response_time))
        .layer(cors)
}

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::{header, Method, Request, StatusCode};
    use axum::Router;
    use tower::ServiceExt;
    use uuid::Uuid;

    use super::{router, RouterConfig};
    use crate::v1::analytics::constants::CAPTURE_V1_PATH;
    use crate::v1::constants::{
        POSTHOG_ATTEMPT, POSTHOG_REQUEST_ID, POSTHOG_REQUEST_TIMESTAMP, POSTHOG_SDK_INFO,
    };
    use crate::v1::test_utils::{batch_payload, valid_event, TestStateBuilder};

    fn app(cfg: RouterConfig) -> Router {
        let ts = TestStateBuilder::new().build();
        router(cfg).with_state(ts.state)
    }

    fn default_cfg() -> RouterConfig {
        RouterConfig {
            concurrency_limit: Some(8),
            max_compressed_body_bytes: 1024 * 1024,
        }
    }

    fn valid_request() -> axum::http::request::Builder {
        Request::builder()
            .method("POST")
            .uri(CAPTURE_V1_PATH)
            .header("Authorization", "Bearer phc_test_token")
            .header("Content-Type", "application/json")
            .header("X-Forwarded-For", "127.0.0.1")
            .header(POSTHOG_SDK_INFO, "posthog-rs/1.0.0")
            .header(POSTHOG_ATTEMPT, "1")
            .header(POSTHOG_REQUEST_ID, Uuid::new_v4().to_string())
            .header(POSTHOG_REQUEST_TIMESTAMP, "2026-03-19T14:30:00Z")
            .header("User-Agent", "test-agent/1.0")
    }

    #[tokio::test]
    async fn post_reaches_handler_through_full_stack() {
        let payload = batch_payload(&[valid_event()]);
        let resp = app(default_cfg())
            .oneshot(valid_request().body(Body::from(payload)).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        assert!(resp.headers().get(header::DATE).is_some());
    }

    #[tokio::test]
    async fn preflight_answered_by_v1_cors() {
        let resp = app(default_cfg())
            .oneshot(
                Request::builder()
                    .method(Method::OPTIONS)
                    .uri(CAPTURE_V1_PATH)
                    .header(header::ORIGIN, "https://example.com")
                    .header("Access-Control-Request-Method", "POST")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            resp.headers()
                .get(header::ACCESS_CONTROL_ALLOW_ORIGIN)
                .and_then(|v| v.to_str().ok()),
            Some("https://example.com")
        );
        let methods = resp
            .headers()
            .get(header::ACCESS_CONTROL_ALLOW_METHODS)
            .and_then(|v| v.to_str().ok())
            .unwrap_or_default();
        assert!(methods.contains("POST"));
        assert!(!methods.contains("GET"), "v1 endpoints are POST-only");
    }

    #[tokio::test]
    async fn get_method_not_allowed() {
        let resp = app(default_cfg())
            .oneshot(
                Request::builder()
                    .method(Method::GET)
                    .uri(CAPTURE_V1_PATH)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::METHOD_NOT_ALLOWED);
    }

    // A 503 the browser can't read is invisible to the SDK's retry logic: the
    // fetch rejects as a network error and the batch is eventually dropped. Any
    // 5xx leaving the v1 stack must therefore carry the same CORS headers and a
    // Retry-After that 2xx/4xx responses get, so posthog-js can read the status
    // and back off instead of hard-failing. CorsLayer sits outermost, so this
    // holds as long as no inner layer short-circuits the response — this test
    // pins that invariant against router refactors.
    #[tokio::test]
    async fn cors_and_retry_after_present_on_503() {
        // Drop the sink-router so process_batch returns ServiceUnavailable (503),
        // the only 5xx the v1 analytics path emits on its own.
        let mut ts = TestStateBuilder::new().build();
        ts.state.v1_sink_router = None;
        let app = router(default_cfg()).with_state(ts.state);

        let resp = app
            .oneshot(
                valid_request()
                    .header(header::ORIGIN, "https://example.com")
                    .body(Body::from(batch_payload(&[valid_event()])))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(
            resp.headers()
                .get(header::ACCESS_CONTROL_ALLOW_ORIGIN)
                .and_then(|v| v.to_str().ok()),
            Some("https://example.com"),
            "503 must carry CORS headers so browser SDKs can read it and retry"
        );
        assert!(
            resp.headers().contains_key(header::RETRY_AFTER),
            "503 must carry Retry-After so browser SDKs back off instead of dropping"
        );
    }

    #[tokio::test]
    async fn cors_headers_on_error_responses() {
        let resp = app(default_cfg())
            .oneshot(
                valid_request()
                    .header(header::ORIGIN, "https://example.com")
                    .body(Body::from("not json"))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert!(resp.status().is_client_error());
        assert_eq!(
            resp.headers()
                .get(header::ACCESS_CONTROL_ALLOW_ORIGIN)
                .and_then(|v| v.to_str().ok()),
            Some("https://example.com")
        );
    }
}
