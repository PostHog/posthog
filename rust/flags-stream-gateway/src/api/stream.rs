//! The SSE version-beacon endpoint (plan §2.6):
//! `GET /stream/v1?token=<project_api_key>&kind=definitions|remote_eval`.
//!
//! Parse → authorize → subscribe → stream. One event type (`version`) is emitted
//! on three occasions (init, change, heartbeat) through the single
//! [`crate::protocol::StreamEvent`] path, so the wire format lives in exactly one
//! place. The stream `select!`s over the watch receiver, a hand-driven heartbeat
//! (version-carrying, not axum `KeepAlive`), a jittered max-age deadline, and the
//! lifecycle shutdown token — the last is load-bearing: without it a drain hangs
//! on every open stream until max-age (plan §2.11).

use std::convert::Infallible;
use std::str::FromStr;
use std::time::Duration;

use axum::extract::{Query, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::sse::Sse;
use axum::response::{IntoResponse, Response};
use axum_client_ip::SecureClientIp;
use rand::Rng;
use serde::Deserialize;
use tokio::time::MissedTickBehavior;

use crate::auth::{DenyReason, ProjectToken, Subscription};
use crate::domain::{CacheKind, VersionState};
use crate::metrics;
use crate::protocol::{retry_event, StreamEvent};
use crate::router::AppState;

/// Reconnect base delay before per-connection jitter (plan §2.6).
const RETRY_BASE_MS: u64 = 3_000;
/// Upper bound of the additive reconnect jitter, so a mass disconnect never
/// produces a synchronized reconnect wave.
const RETRY_JITTER_MS: u64 = 5_000;

/// Raw query params. Both are required: a missing field makes axum's `Query`
/// reject with 400, which is exactly the contract (400 on missing/unknown).
#[derive(Deserialize)]
pub(crate) struct RawStreamQuery {
    token: String,
    kind: String,
}

/// `GET /stream/v1`. Non-200 outcomes (400/401/403/429/503) are plain HTTP
/// responses returned before any stream is established.
pub(crate) async fn stream_v1(
    State(state): State<AppState>,
    SecureClientIp(client_ip): SecureClientIp,
    Query(raw): Query<RawStreamQuery>,
    headers: HeaderMap,
) -> Response {
    let kind = match CacheKind::from_str(&raw.kind) {
        Ok(kind) => kind,
        Err(_) => {
            return (StatusCode::BAD_REQUEST, "unknown kind").into_response();
        }
    };
    let token = match ProjectToken::parse(&raw.token) {
        Ok(token) => token,
        Err(_) => {
            return (StatusCode::BAD_REQUEST, "missing token").into_response();
        }
    };

    let subscription = match state.authenticator.authorize(token, kind, client_ip).await {
        Ok(subscription) => subscription,
        Err(reason) => {
            metrics::connection_denied(kind, reason.metric_reason());
            return deny_response(reason);
        }
    };

    build_stream(state, kind, subscription, &headers)
}

/// Turn a [`DenyReason`] into its plain HTTP response, attaching `Retry-After`
/// for the rate-limit denials.
fn deny_response(reason: DenyReason) -> Response {
    let mut response = (reason.status(), reason.to_string()).into_response();
    if let Some(secs) = reason.retry_after_secs() {
        if let Ok(value) = HeaderValue::from_str(&secs.to_string()) {
            response.headers_mut().insert(header::RETRY_AFTER, value);
        }
    }
    response
}

/// Build the SSE response for an authorized subscription.
fn build_stream(
    state: AppState,
    kind: CacheKind,
    subscription: Subscription,
    headers: &HeaderMap,
) -> Response {
    let topic = subscription.topic;
    let stagger = subscription.stagger;
    // `Last-Event-ID` (SSE-standard reconnect header) lets us measure how often a
    // reconnect was already current — the "deploys are nearly free" metric.
    let last_event_id = headers
        .get("last-event-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);

    let rx = state.registry.subscribe(topic);
    let shutdown = state.shutdown_token.clone();
    let heartbeat_interval = state.config.heartbeat_interval;
    let max_age = jitter_max_age(state.config.max_connection_age);
    let retry_ms = jitter_retry();

    let sse_stream = async_stream::stream! {
        // The permit releases admission when this stream drops — the axum
        // disconnect signal (plan §2.5). Bound to a name (never bare `_`) so the
        // workspace `let_underscore_drop` deny does not fire and the RAII guard
        // is not dropped early.
        let _permit = subscription.into_permit();
        // Counting a connection here (on first poll) rather than at response-build
        // time keeps the active-connection gauge paired with the guard's Drop, so
        // a never-polled body can't leak the gauge.
        metrics::connection_opened(kind);
        let mut conn_guard = ConnectionGuard::new(kind);
        let mut rx = rx;

        // First frames: jittered retry:, then an immediate version event.
        yield Ok::<_, Infallible>(retry_event(retry_ms));
        let init_state = { *rx.borrow_and_update() };
        record_reconnect(kind, last_event_id.as_deref(), init_state);
        yield Ok(StreamEvent::new(kind, init_state, stagger).to_sse());
        metrics::event_sent(kind, metrics::OCCASION_INIT);

        let mut heartbeat = tokio::time::interval(heartbeat_interval);
        heartbeat.set_missed_tick_behavior(MissedTickBehavior::Skip);
        heartbeat.tick().await; // consume the immediate first tick

        let deadline = tokio::time::sleep(max_age);
        tokio::pin!(deadline);

        loop {
            tokio::select! {
                // Shutdown and max-age end the stream cleanly (clean EOF); the
                // client reconnects per its jittered retry:.
                _ = shutdown.cancelled() => {
                    conn_guard.set_reason(metrics::DISCONNECT_SHUTDOWN);
                    break;
                }
                _ = &mut deadline => {
                    conn_guard.set_reason(metrics::DISCONNECT_MAX_AGE);
                    break;
                }
                changed = rx.changed() => {
                    // Sender gone (topic dropped) — end the stream; the client
                    // reconnects and re-baselines.
                    if changed.is_err() {
                        break;
                    }
                    // Copy the Copy state out and drop the borrow guard BEFORE the
                    // yield (an await): never hold a watch borrow across await.
                    let state = { *rx.borrow_and_update() };
                    yield Ok(StreamEvent::new(kind, state, stagger).to_sse());
                    metrics::event_sent(kind, metrics::OCCASION_CHANGE);
                    // "A client was told to refetch": null beacons tell clients to
                    // HOLD (client contract rule 3), so they are not notifications.
                    if state.etag().is_some() {
                        metrics::notification_sent(kind);
                    }
                }
                _ = heartbeat.tick() => {
                    // `borrow` (not `borrow_and_update`) so a genuine change still
                    // fires the change arm; the heartbeat is defense-in-depth.
                    let state = { *rx.borrow() };
                    yield Ok(StreamEvent::new(kind, state, stagger).to_sse());
                    metrics::event_sent(kind, metrics::OCCASION_HEARTBEAT);
                }
            }
        }
        // On a clean break the guard drops here (recording the set reason). On a
        // client disconnect the generator is dropped mid-await and the guard's
        // Drop records the default `client_closed`.
    };

    let mut response = Sse::new(sse_stream).into_response();
    let response_headers = response.headers_mut();
    response_headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    // Defense-in-depth for nginx-family intermediaries a customer may run in
    // front; the edge controls that matter are verified in Phase 2 (plan §2.6).
    response_headers.insert("x-accel-buffering", HeaderValue::from_static("no"));
    response
}

/// Records the disconnect reason and the active-connection gauge on drop. The
/// reason defaults to `client_closed`; the stream sets it before a clean break.
struct ConnectionGuard {
    kind: CacheKind,
    reason: &'static str,
}

impl ConnectionGuard {
    fn new(kind: CacheKind) -> Self {
        Self {
            kind,
            reason: metrics::DISCONNECT_CLIENT_CLOSED,
        }
    }

    fn set_reason(&mut self, reason: &'static str) {
        self.reason = reason;
    }
}

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        metrics::connection_closed(self.kind, self.reason);
    }
}

/// Count a reconnect as current or stale, but only when both sides are non-null:
/// the client sent a `Last-Event-ID` AND our view is a `Known` version (plan §2.6).
fn record_reconnect(kind: CacheKind, last_event_id: Option<&str>, init_state: VersionState) {
    if let (Some(previous), Some(current)) = (last_event_id, init_state.etag()) {
        if previous.is_empty() {
            return;
        }
        if previous == current.to_string() {
            metrics::reconnect_current(kind);
        } else {
            metrics::reconnect_stale(kind);
        }
    }
}

/// Per-connection reconnect delay: base + uniform(0..=jitter) ms.
fn jitter_retry() -> u64 {
    RETRY_BASE_MS + rand::thread_rng().gen_range(0..=RETRY_JITTER_MS)
}

/// Max connection age jittered ±10% so recycled connections do not stampede.
fn jitter_max_age(base: Duration) -> Duration {
    let factor = rand::thread_rng().gen_range(0.9..=1.1);
    base.mul_f64(factor)
}
