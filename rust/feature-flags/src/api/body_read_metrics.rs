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
use common_metrics::inc;

use crate::metrics::consts::FLAG_BODY_READ_FAILED_COUNTER;

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
            inc(FLAG_BODY_READ_FAILED_COUNTER, &[], 1);
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
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    use tower::ServiceExt;

    /// Encodes responses as `<wait_micros|"missing">|<body_bytes>` so
    /// tests can split on the first `|` and compare body bytes verbatim.
    const ECHO_DELIM: u8 = b'|';

    async fn echo_body_read(
        wait: Option<Extension<BodyReadDuration>>,
        body: Bytes,
    ) -> (StatusCode, Vec<u8>) {
        let wait_repr = wait
            .map(|Extension(w)| w.0.as_micros().to_string())
            .unwrap_or_else(|| "missing".to_string());
        let mut out = wait_repr.into_bytes();
        out.push(ECHO_DELIM);
        out.extend_from_slice(&body);
        (StatusCode::OK, out)
    }

    fn make_request(body: &str) -> HttpRequest<Body> {
        HttpRequest::builder()
            .method("POST")
            .uri("/")
            .body(Body::from(body.to_owned()))
            .unwrap()
    }

    async fn read_response_bytes(resp: Response) -> Vec<u8> {
        axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .unwrap()
            .to_vec()
    }

    fn split_echo(payload: &[u8]) -> (&str, &[u8]) {
        let i = payload
            .iter()
            .position(|b| *b == ECHO_DELIM)
            .expect("echo response must contain the delimiter");
        let wait =
            std::str::from_utf8(&payload[..i]).expect("wait segment must be ASCII micros/marker");
        (wait, &payload[i + 1..])
    }

    #[tokio::test]
    async fn shim_records_duration_and_preserves_body_bytes() {
        // Mix of NUL, invalid UTF-8, and high-bit bytes — picked so any
        // accidental string conversion or truncation surfaces.
        let body: Vec<u8> = vec![
            0x00, 0xFF, 0xC3, 0x28, b'h', b'e', b'l', b'l', b'o', 0x80, 0x81, 0x82,
        ];
        let app = Router::new()
            .route("/", post(echo_body_read))
            .layer(axum::middleware::from_fn(record_body_read));

        let req = HttpRequest::builder()
            .method("POST")
            .uri("/")
            .body(Body::from(body.clone()))
            .unwrap();
        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let payload = read_response_bytes(resp).await;
        let (wait, echoed_body) = split_echo(&payload);
        assert_ne!(wait, "missing");
        assert_eq!(echoed_body, body);
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
        let payload = read_response_bytes(resp).await;
        let (wait, echoed_body) = split_echo(&payload);
        assert_ne!(wait, "missing");
        assert!(echoed_body.is_empty());
    }

    #[tokio::test]
    async fn shim_extension_absent_when_layer_omitted() {
        let app = Router::new().route("/", post(echo_body_read));
        let resp = app.oneshot(make_request("payload")).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let payload = read_response_bytes(resp).await;
        let (wait, echoed_body) = split_echo(&payload);
        assert_eq!(wait, "missing");
        assert_eq!(echoed_body, b"payload");
    }

    #[tokio::test]
    async fn shim_returns_400_and_increments_failed_counter_on_buffering_error() {
        use futures::stream;

        // `set_default_local_recorder` returns a thread-local guard;
        // safe across `.await` because `#[tokio::test]` defaults to a
        // current-thread runtime.
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        let app = Router::new()
            .route("/", post(echo_body_read))
            .layer(axum::middleware::from_fn(record_body_read));

        let err_stream = stream::once(async {
            Err::<Bytes, std::io::Error>(std::io::Error::other("simulated upload failure"))
        });
        let req = HttpRequest::builder()
            .method("POST")
            .uri("/")
            .body(Body::from_stream(err_stream))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        // Pin the shim's own 400 message so we know the response did
        // not come from a downstream that observed an empty `Bytes`.
        let body_bytes = read_response_bytes(resp).await;
        assert_eq!(body_bytes, b"Failed to buffer the request body");

        let snapshot = snapshotter.snapshot().into_vec();
        let failed = snapshot.iter().find_map(|(ckey, _, _, value)| {
            (ckey.key().name() == FLAG_BODY_READ_FAILED_COUNTER).then_some(value)
        });
        match failed {
            Some(DebugValue::Counter(n)) => assert_eq!(*n, 1),
            other => {
                panic!("expected `{FLAG_BODY_READ_FAILED_COUNTER}` Counter sample, got {other:?}")
            }
        }
    }
}
