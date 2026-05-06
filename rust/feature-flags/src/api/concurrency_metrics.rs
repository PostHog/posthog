//! Tower-layer instrumentation for `ConcurrencyLimitLayer` permit-wait.
//!
//! `tower::limit::ConcurrencyLimitLayer` exposes no timing hook for permit
//! acquisition, so we sandwich it between two `axum::middleware::from_fn`
//! shims that communicate via request extensions:
//!
//! 1. [`record_concurrency_enter`] runs *before* the request reaches
//!    `ConcurrencyLimitLayer` and stamps the entry instant on the request.
//! 2. [`record_concurrency_wait`] runs *after* the layer has handed off a
//!    permit and computes `Instant::elapsed`, which the handler then reads
//!    out of the extensions to populate the canonical log.
//!
//! Layer wiring lives in `router::router` — see the comment block there.
//! Both shims are no-ops when their counterpart is missing, so they can be
//! rolled out / reverted independently without breaking requests.
//!
//! # Load-bearing axum invariant
//!
//! The metric only captures *true* permit-wait because each `Router::layer()`
//! call in axum wraps the inner chain in a `Route` whose `poll_ready` returns
//! `Poll::Ready(Ok(()))` unconditionally (see
//! `axum::routing::route::Route::poll_ready`). That breaks the synchronous
//! `poll_ready` cascade at every layer boundary, so
//! `tower::limit::ConcurrencyLimit::poll_ready` (which is what blocks on the
//! semaphore) does not run during the outer chain's readiness check — it
//! runs inside `Route::call` *after* `record_concurrency_enter::call` has
//! already stamped `Instant::now()`. If a future axum version changes
//! `Route::poll_ready` to delegate to its inner service, this metric will
//! silently report ~0 ms regardless of real wait. Re-verify against
//! `axum::routing::route::Route::poll_ready` on every axum bump; a
//! regression there will not surface in unit tests (the shim contract is
//! decoupled from the cascade behavior) but will show up as the
//! `flags_concurrency_limit_wait_ms` histogram collapsing to ~0 in
//! production dashboards.

use std::time::{Duration, Instant};

use axum::{extract::Request, middleware::Next, response::Response};

/// Wall-clock instant captured immediately before the request enters
/// `ConcurrencyLimitLayer`. Read by [`record_concurrency_wait`] to compute
/// permit-acquisition latency. `Copy` so the shim doesn't need to clone.
#[derive(Clone, Copy, Debug)]
pub struct ConcurrencyEnterTime(pub Instant);

/// Time spent waiting on a permit from `ConcurrencyLimitLayer`. Inserted
/// into the request extensions by [`record_concurrency_wait`] and read by
/// the `flags` handler to populate `FlagsCanonicalLogLine::concurrency_limit_wait_ms`.
#[derive(Clone, Copy, Debug)]
pub struct ConcurrencyLimitWait(pub Duration);

/// Stamps `ConcurrencyEnterTime` on the request before it reaches
/// `ConcurrencyLimitLayer`. Wired between `TimeoutLayer` and the
/// concurrency limiter so the captured instant happens *after* timeout
/// deadline propagation but *before* permit acquisition.
pub async fn record_concurrency_enter(mut req: Request, next: Next) -> Response {
    req.extensions_mut()
        .insert(ConcurrencyEnterTime(Instant::now()));
    next.run(req).await
}

/// Runs *after* `ConcurrencyLimitLayer` has handed off a permit. Computes
/// the elapsed permit-wait and stores it on the request extensions so the
/// handler can pull it into the canonical log.
///
/// No-ops if `ConcurrencyEnterTime` is missing — keeps the two shims
/// independently rollout-able and tolerant of layer-ordering mistakes
/// during refactors.
pub async fn record_concurrency_wait(mut req: Request, next: Next) -> Response {
    if let Some(enter) = req.extensions().get::<ConcurrencyEnterTime>().copied() {
        req.extensions_mut()
            .insert(ConcurrencyLimitWait(enter.0.elapsed()));
    }
    next.run(req).await
}

#[cfg(test)]
mod tests {
    //! These tests exercise the middleware's contract directly — capture
    //! `Instant` at `enter`, write `Duration` since at `wait` — without
    //! depending on `ConcurrencyLimitLayer`'s real-runtime permit
    //! semantics. That keeps tests deterministic. The router-level
    //! interaction (this pair sandwiches `ConcurrencyLimitLayer`) is
    //! enforced by layer ordering in `router::router`; we test the layer
    //! contract here, not the layer placement.
    use super::*;
    use axum::{body::Body, extract::Extension, http::StatusCode, routing::get, Router};
    use rstest::rstest;
    use tower::ServiceExt;

    /// Handler that echoes the captured wait as plain text. `"missing"`
    /// distinguishes the "extension never set" case from a real `0 ms`.
    async fn echo_wait_ms(wait: Option<Extension<ConcurrencyLimitWait>>) -> String {
        wait.map(|Extension(w)| w.0.as_millis().to_string())
            .unwrap_or_else(|| "missing".to_string())
    }

    async fn read_body(resp: Response) -> String {
        let bytes = axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .unwrap();
        String::from_utf8(bytes.to_vec()).unwrap()
    }

    fn make_request() -> axum::http::Request<Body> {
        axum::http::Request::builder()
            .uri("/")
            .body(Body::empty())
            .unwrap()
    }

    #[tokio::test]
    async fn enter_then_wait_records_elapsed_duration() {
        // Insert a known sleep between `record_concurrency_enter` and
        // `record_concurrency_wait`. The wait middleware must record at
        // least that much elapsed — proving the extension flows and that
        // any latency introduced between the shims is captured. In
        // production the latency source is `ConcurrencyLimitLayer`;
        // here it's a sleep, so the test is deterministic.
        const DELAY_MS: u64 = 50;

        let app = Router::new()
            .route("/", get(echo_wait_ms))
            .layer(axum::middleware::from_fn(record_concurrency_wait))
            .layer(axum::middleware::from_fn(
                |req: axum::extract::Request, next: axum::middleware::Next| async move {
                    tokio::time::sleep(Duration::from_millis(DELAY_MS)).await;
                    next.run(req).await
                },
            ))
            .layer(axum::middleware::from_fn(record_concurrency_enter));

        let resp = app.oneshot(make_request()).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);

        let body = read_body(resp).await;
        let wait_ms: u128 = body
            .parse()
            .unwrap_or_else(|_| panic!("expected numeric wait, got {body:?}"));

        // Allow scheduler jitter on the lower bound while still catching
        // the "stuck at 0 / missing" regressions. Upper bound guards
        // against runaway clock skew or accidental double-stamping.
        let lower = (DELAY_MS - 10) as u128;
        let upper = (DELAY_MS + 500) as u128;
        assert!(
            (lower..=upper).contains(&wait_ms),
            "expected wait in [{lower}, {upper}] ms, got {wait_ms} ms"
        );
    }

    /// Builds a router that only installs the named shim. The other shim
    /// is intentionally absent so the test can verify each is independently
    /// rollout-safe — neither panics, and the wait extension is only ever
    /// written by `record_concurrency_wait`.
    fn router_with_single_shim(shim: SingleShim) -> Router {
        let r = Router::new().route("/", get(echo_wait_ms));
        match shim {
            SingleShim::WaitOnly => r.layer(axum::middleware::from_fn(record_concurrency_wait)),
            SingleShim::EnterOnly => r.layer(axum::middleware::from_fn(record_concurrency_enter)),
        }
    }

    #[derive(Copy, Clone)]
    enum SingleShim {
        /// Drops `record_concurrency_enter`. Verifies `record_concurrency_wait`
        /// no-ops rather than panicking when the entry instant is missing.
        WaitOnly,
        /// Drops `record_concurrency_wait`. Verifies that no other code path
        /// accidentally writes the wait extension — catches a future
        /// regression where someone merges the two shims into one and
        /// breaks the layer-ordering semantics.
        EnterOnly,
    }

    #[rstest]
    #[case::wait_shim_alone(SingleShim::WaitOnly)]
    #[case::enter_shim_alone(SingleShim::EnterOnly)]
    #[tokio::test]
    async fn single_shim_leaves_wait_extension_absent(#[case] shim: SingleShim) {
        let app = router_with_single_shim(shim);
        let resp = app.oneshot(make_request()).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let body = read_body(resp).await;
        assert_eq!(body, "missing");
    }
}
