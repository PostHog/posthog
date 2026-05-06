//! Tower-layer instrumentation for inbound POST body buffering.
//!
//! axum's `Bytes` extractor reads and buffers the entire request body
//! before the handler observes it, but that buffering happens *inside*
//! the handler's invocation — so on a slow client upload, the latency
//! is charged to the handler with no per-step visibility. This shim
//! buffers the body explicitly inside a middleware layer placed
//! immediately after [`crate::api::concurrency_metrics::record_concurrency_wait`]
//! and before the handler. Side effects:
//!
//! 1. The elapsed wall-clock duration of `axum::body::to_bytes` is
//!    stamped onto the request extensions as [`BodyReadDuration`].
//! 2. The original body is replaced with `Body::from(bytes)`, so the
//!    handler's `body: Bytes` extractor reads from in-memory and the
//!    overall behavior is unchanged.
//!
//! Layer wiring lives in `router::router` — see the comment block there.
//! The shim no-ops gracefully on the `Bytes` extractor's downstream
//! contract: if buffering fails, the framework's existing 400 response
//! shape is preserved.
//!
//! # Why no team_id label
//!
//! Body buffering happens before authentication resolves a team. The
//! histogram is pod-level by design, mirroring
//! `flags_concurrency_limit_wait_ms`.

use std::time::{Duration, Instant};

use axum::{
    body::Body,
    extract::Request,
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
};

/// Wall-clock duration spent buffering the inbound request body. Inserted
/// into request extensions by [`record_body_read`] and read by the
/// `flags` handler to populate `FlagsCanonicalLogLine::body_read_ms`.
#[derive(Clone, Copy, Debug)]
pub struct BodyReadDuration(pub Duration);

/// Buffers the request body to memory while timing the operation, then
/// forwards a request with an in-memory body so the handler's `Bytes`
/// extractor short-circuits.
///
/// Errors during buffering map to a 400 response — the same shape the
/// `Bytes` extractor's `BytesRejection` produces by default. The shim
/// must not absorb the request silently; an unbuffered body would never
/// reach the handler regardless.
pub async fn record_body_read(req: Request, next: Next) -> Response {
    let (parts, body) = req.into_parts();
    let start = Instant::now();
    // No explicit upper bound: the existing handler accepts `body: Bytes`
    // without a `RequestBodyLimitLayer`, so this shim must match that
    // contract. Upstream (Envoy / Contour) enforces the real ceiling.
    let bytes = match axum::body::to_bytes(body, usize::MAX).await {
        Ok(bytes) => bytes,
        Err(err) => {
            tracing::warn!(error = %err, "failed to buffer request body");
            return (StatusCode::BAD_REQUEST, "Failed to buffer the request body").into_response();
        }
    };
    let elapsed = start.elapsed();

    let mut req = Request::from_parts(parts, Body::from(bytes));
    req.extensions_mut().insert(BodyReadDuration(elapsed));
    next.run(req).await
}

#[cfg(test)]
mod tests {
    //! These tests exercise the shim's contract directly — buffer the
    //! body, time the operation, hand off a request with an in-memory
    //! body — without depending on the rest of the layer chain. The
    //! placement after `record_concurrency_wait` is enforced by the
    //! router wiring; we test the shim itself here.

    use super::*;
    use axum::{
        body::Body,
        extract::Extension,
        http::{Request as HttpRequest, StatusCode},
        routing::post,
        Router,
    };
    use bytes::Bytes;
    use tower::ServiceExt;

    /// Echoes the captured body-read duration as plain text, plus the
    /// length of the buffered body. `"missing"` distinguishes the
    /// "extension never set" case from a real `0 ms`.
    async fn echo_body_read(
        wait: Option<Extension<BodyReadDuration>>,
        body: Bytes,
    ) -> (StatusCode, String) {
        let wait_repr = wait
            .map(|Extension(w)| w.0.as_micros().to_string())
            .unwrap_or_else(|| "missing".to_string());
        (StatusCode::OK, format!("{wait_repr}|{}", body.len()))
    }

    fn make_request(body: &str) -> HttpRequest<Body> {
        HttpRequest::builder()
            .method("POST")
            .uri("/")
            .body(Body::from(body.to_owned()))
            .unwrap()
    }

    async fn read_body(resp: Response) -> String {
        let bytes = axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .unwrap();
        String::from_utf8(bytes.to_vec()).unwrap()
    }

    #[tokio::test]
    async fn shim_records_duration_and_preserves_body() {
        let app = Router::new()
            .route("/", post(echo_body_read))
            .layer(axum::middleware::from_fn(record_body_read));

        let body = "hello world";
        let resp = app.oneshot(make_request(body)).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let payload = read_body(resp).await;
        let (_wait, len) = payload.split_once('|').unwrap();
        // Body must reach the handler intact via the in-memory path.
        assert_eq!(len, body.len().to_string());
    }

    #[tokio::test]
    async fn shim_handles_empty_body() {
        // GET / OPTIONS / HEAD requests routed through the same layer
        // chain see an empty body. The shim must record a duration
        // (even ~0) and forward without error.
        let app = Router::new()
            .route("/", post(echo_body_read))
            .layer(axum::middleware::from_fn(record_body_read));

        let req = HttpRequest::builder()
            .method("POST")
            .uri("/")
            .body(Body::empty())
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let payload = read_body(resp).await;
        let (wait, len) = payload.split_once('|').unwrap();
        assert_ne!(
            wait, "missing",
            "shim should set BodyReadDuration even for empty bodies"
        );
        assert_eq!(len, "0");
    }

    #[tokio::test]
    async fn shim_extension_absent_when_layer_omitted() {
        // Rollout-safety: if a future refactor removes the shim, the
        // handler's `Option<Extension<BodyReadDuration>>` must observe
        // the absence rather than panic.
        let app = Router::new().route("/", post(echo_body_read));
        let resp = app.oneshot(make_request("payload")).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let payload = read_body(resp).await;
        let (wait, _len) = payload.split_once('|').unwrap();
        assert_eq!(wait, "missing");
    }
}
