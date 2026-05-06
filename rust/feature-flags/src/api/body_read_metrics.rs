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
            // Pair the warn-log with a counter so dashboards can alert on a
            // sudden spike of broken uploads — the warn alone disappears
            // into the log stream and never surfaces a rate signal.
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

    /// Sentinel separating the wait marker from the buffered body bytes
    /// in [`echo_body_read`]'s response. Picked to avoid colliding with
    /// the ASCII byte values produced by `Duration::as_micros()` (digits)
    /// and the empty-body assertion (`"missing"`).
    const ECHO_DELIM: u8 = b'|';

    /// Echoes the captured body-read duration plus the **raw bytes** of
    /// the buffered body. The format is `<wait_micros|"missing">|<bytes>`,
    /// so callers can split on the first `|` and compare body content
    /// byte-for-byte. Comparing length only would let a shim regression
    /// that mangles bytes pass silently.
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

    /// Splits a response from [`echo_body_read`] into its `(wait, body)`
    /// halves. Returns `wait` as `&str` (always ASCII micros or
    /// `"missing"`) and `body` as raw bytes for content comparison.
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
        // Use bytes that would surface byte-level corruption: high-bit
        // values, embedded NUL, and non-UTF-8 are intentional. A
        // length-only assertion would miss any of these regressions.
        let body: Vec<u8> = vec![
            0x00, 0xFF, 0xC3, 0x28, // invalid UTF-8 sequence
            b'h', b'e', b'l', b'l', b'o', 0x80, 0x81, 0x82,
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
        assert_ne!(
            wait, "missing",
            "shim must stamp BodyReadDuration onto request extensions"
        );
        // Byte-for-byte comparison: catches any in-shim mangling
        // (encoding, truncation, slice boundary errors).
        assert_eq!(
            echoed_body, body,
            "shim must hand the handler the original bytes verbatim"
        );
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
        assert_ne!(
            wait, "missing",
            "shim should set BodyReadDuration even for empty bodies"
        );
        assert!(
            echoed_body.is_empty(),
            "empty input must echo back as empty (not truncated nor padded)"
        );
    }

    #[tokio::test]
    async fn shim_extension_absent_when_layer_omitted() {
        // Rollout-safety: if a future refactor removes the shim, the
        // handler's `Option<Extension<BodyReadDuration>>` must observe
        // the absence rather than panic.
        let app = Router::new().route("/", post(echo_body_read));
        let resp = app.oneshot(make_request("payload")).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let payload = read_response_bytes(resp).await;
        let (wait, echoed_body) = split_echo(&payload);
        assert_eq!(wait, "missing");
        // Sanity: the body still flows through axum's `Bytes` extractor
        // in the no-shim path. Asserts the test harness, not the shim.
        assert_eq!(echoed_body, b"payload");
    }

    #[tokio::test]
    async fn shim_returns_400_and_increments_failed_counter_on_buffering_error() {
        // Drive the `to_bytes` Err branch by handing the shim a body
        // whose stream yields an error frame. This exercises the
        // production failure path: any IO-level disruption during
        // buffering (peer disconnect, malformed framing, upstream
        // hangup) bottoms out as a `to_bytes` `Err`. We're testing
        // application code (the shim's response shape *and* its metric
        // emission) — not just that `axum::body::to_bytes` returns Err
        // when fed an erroring stream.
        use futures::stream;

        // `#[tokio::test]` defaults to a current-thread runtime, so the
        // thread-local guard here covers the entire `.await` chain
        // below. `set_default_local_recorder` is the async-safe variant
        // of `with_local_recorder` for exactly this reason.
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

        assert_eq!(
            resp.status(),
            StatusCode::BAD_REQUEST,
            "buffering failure must surface as 400 to the caller"
        );

        // The handler must not have run — confirms 400 is from the
        // shim, not from a downstream that observed an empty `Bytes`.
        let body_bytes = read_response_bytes(resp).await;
        assert_eq!(
            body_bytes, b"Failed to buffer the request body",
            "shim's 400 must carry its own message, not the handler's echo"
        );

        // Counter must increment exactly once per buffering failure.
        // Looking up by metric name pins the constant string is wired,
        // and asserting the count rejects double-emission.
        let snapshot = snapshotter.snapshot().into_vec();
        let failed = snapshot.iter().find_map(|(ckey, _, _, value)| {
            (ckey.key().name() == FLAG_BODY_READ_FAILED_COUNTER).then_some(value)
        });
        match failed {
            Some(DebugValue::Counter(n)) => assert_eq!(
                *n, 1,
                "failed counter must increment exactly once per buffering error"
            ),
            other => panic!(
                "expected `{FLAG_BODY_READ_FAILED_COUNTER}` Counter sample, got {other:?}"
            ),
        }
    }
}
