//! End-to-end integration tests for `GET /stream/v1` (plan §2.12): the real
//! serve path with a mock behind both Redis tiers. Sweep runs at 50 ms, so
//! change delivery is asserted with short bounded timeouts; heartbeats default
//! to 5 s so silence windows are never raced.

mod common;

use std::time::Duration;

use common::{
    etag_key, mock_with_valid_team, pickled, team_metadata_key, SseFrames, TestServer, ETAG_A,
    ETAG_B, TEAM_ID, VALID_TOKEN,
};
use common_redis::{CustomRedisError, MockRedisClient};

/// flags_with_cohorts.json — what `kind=definitions` watches.
const DEFS_VALUE: &str = "flags_with_cohorts.json";

/// A generous per-read bound; individual assertions stay well under it.
const READ_TIMEOUT: Duration = Duration::from_secs(3);

fn mock_with_team_and_defs_etag(etag: &str) -> MockRedisClient {
    mock_with_valid_team()
        .mget_with_format_ret(&etag_key(TEAM_ID, DEFS_VALUE), Some(etag.to_string()))
}

// Scenario 1: connect with a valid token → 200 text/event-stream; first frames
// are `retry:` then an init `version` event (null before the first sweep, or the
// mocked etag if a sweep tick won the race), and the etag arrives promptly.
#[tokio::test]
async fn connect_streams_retry_then_version_events() {
    let server = TestServer::start(mock_with_team_and_defs_etag(ETAG_A), |_| {}).await;
    let response = server.connect("definitions", VALID_TOKEN).await;

    assert_eq!(response.status(), 200);
    let content_type = response
        .headers()
        .get("content-type")
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .to_string();
    assert!(
        content_type.starts_with("text/event-stream"),
        "unexpected content-type: {content_type}"
    );
    assert_eq!(
        response
            .headers()
            .get("cache-control")
            .and_then(|value| value.to_str().ok()),
        Some("no-cache")
    );

    let mut frames = SseFrames::new(response);
    let first = frames.next_frame(READ_TIMEOUT).await.expect("first frame");
    assert!(
        first.contains("retry:"),
        "expected retry frame, got {first:?}"
    );

    let init = frames.next_frame(READ_TIMEOUT).await.expect("init frame");
    assert!(
        init.contains("version"),
        "expected version event, got {init:?}"
    );
    assert!(
        init.contains(r#""version":null"#) || init.contains(ETAG_A),
        "init must carry null or the mocked etag, got {init:?}"
    );
    assert!(init.contains(r#""kind":"definitions""#), "got {init:?}");

    // Whatever the init carried, the sweep-driven etag arrives promptly.
    let known = frames
        .frame_matching(READ_TIMEOUT, |frame| frame.contains(ETAG_A))
        .await;
    assert!(known.contains(r#""stagger_window_s":60"#), "got {known:?}");
}

// Scenario 2: an etag flip in the mock produces a change event within a sweep
// tick (asserted with a bound far under the 5 s heartbeat, so a heartbeat can't
// mask a broken sweep).
#[tokio::test]
async fn etag_flip_delivers_change_event() {
    let server = TestServer::start(mock_with_team_and_defs_etag(ETAG_A), |_| {}).await;
    let response = server.connect("definitions", VALID_TOKEN).await;
    let mut frames = SseFrames::new(response);
    frames
        .frame_matching(READ_TIMEOUT, |frame| frame.contains(ETAG_A))
        .await;

    server.redis.swap(mock_with_team_and_defs_etag(ETAG_B));

    let changed = frames
        .frame_matching(Duration::from_secs(1), |frame| frame.contains(ETAG_B))
        .await;
    assert!(
        changed.contains(r#""kind":"definitions""#),
        "got {changed:?}"
    );
}

// Scenario 3: re-setting the identical etag produces NO event (content-hash
// equality suppresses spurious rebuilds). Silence asserted across ~8 sweep
// ticks, well under the 5 s heartbeat.
#[tokio::test]
async fn identical_etag_reset_is_silent() {
    let server = TestServer::start(mock_with_team_and_defs_etag(ETAG_A), |_| {}).await;
    let response = server.connect("definitions", VALID_TOKEN).await;
    let mut frames = SseFrames::new(response);
    frames
        .frame_matching(READ_TIMEOUT, |frame| frame.contains(ETAG_A))
        .await;

    // Identical content "re-written": same etag through a fresh mock instance.
    server.redis.swap(mock_with_team_and_defs_etag(ETAG_A));

    frames.expect_silence(Duration::from_millis(400)).await;
}

// Scenario 4: etag deletion produces a null-version event with NO id: line
// (clients hold on null — the refetch-storm guard).
#[tokio::test]
async fn etag_deletion_emits_null_beacon_without_id() {
    let server = TestServer::start(mock_with_team_and_defs_etag(ETAG_A), |_| {}).await;
    let response = server.connect("definitions", VALID_TOKEN).await;
    let mut frames = SseFrames::new(response);

    let known = frames
        .frame_matching(READ_TIMEOUT, |frame| frame.contains(ETAG_A))
        .await;
    assert!(
        known.contains("id:"),
        "known version carries id:, got {known:?}"
    );

    // Remove the etag key: the sweep observes Absent.
    server.redis.swap(mock_with_valid_team());

    let null_beacon = frames
        .frame_matching(Duration::from_secs(1), |frame| {
            frame.contains(r#""version":null"#)
        })
        .await;
    assert!(
        !null_beacon.contains("id:"),
        "null beacon must omit the id line entirely, got {null_beacon:?}"
    );
}

// Scenario 5: the heartbeat carries the current version.
#[tokio::test]
async fn heartbeat_carries_current_version() {
    let server = TestServer::start(mock_with_team_and_defs_etag(ETAG_A), |raw| {
        raw.heartbeat_interval_secs = 1;
    })
    .await;
    let response = server.connect("definitions", VALID_TOKEN).await;
    let mut frames = SseFrames::new(response);
    frames
        .frame_matching(READ_TIMEOUT, |frame| frame.contains(ETAG_A))
        .await;

    // Nothing changes in the mock, so the next version frame is heartbeat-driven
    // — and it must still carry the current etag.
    let heartbeat = frames
        .next_frame(Duration::from_secs(3))
        .await
        .expect("heartbeat frame");
    assert!(
        heartbeat.contains(ETAG_A) && heartbeat.contains("version"),
        "heartbeat must carry the current version, got {heartbeat:?}"
    );
}

// Scenario 6: exhausting the definitions per-token cap yields 429 + Retry-After.
#[tokio::test]
async fn definitions_token_cap_yields_429_with_retry_after() {
    let server = TestServer::start(mock_with_team_and_defs_etag(ETAG_A), |raw| {
        raw.definitions_max_connections_per_token = 1;
    })
    .await;

    let held = server.connect("definitions", VALID_TOKEN).await;
    assert_eq!(held.status(), 200);
    // Keep the first stream alive (response held) while the second connects.
    let denied = server.connect("definitions", VALID_TOKEN).await;
    assert_eq!(denied.status(), 429);
    assert_eq!(
        denied
            .headers()
            .get("retry-after")
            .and_then(|value| value.to_str().ok()),
        Some("60")
    );
    drop(held);
}

// Scenario 7a: the `__missing__` sentinel for a token is an authenticated
// "unknown token" → 401.
#[tokio::test]
async fn sentinel_token_yields_401() {
    let mock = MockRedisClient::new()
        .get_raw_bytes_ret(&team_metadata_key("phc_ghost"), Ok(pickled("__missing__")));
    let server = TestServer::start(mock, |_| {}).await;

    let response = server.connect("definitions", "phc_ghost").await;
    assert_eq!(response.status(), 401);
}

// Scenario 7b: a Redis infra error on the team cache fails closed → 503 (the
// gateway must not fall through to S3/Postgres, plan §2.8).
#[tokio::test]
async fn team_cache_infra_error_yields_503() {
    let mock = MockRedisClient::new().get_raw_bytes_ret(
        &team_metadata_key(VALID_TOKEN),
        Err(CustomRedisError::Timeout),
    );
    let server = TestServer::start(mock, |_| {}).await;

    let response = server.connect("definitions", VALID_TOKEN).await;
    assert_eq!(response.status(), 503);
}

// Scenario 7c/7d: remote_eval is allowlist-gated — 403 off-list, 200 on-list.
#[tokio::test]
async fn remote_eval_requires_allowlist() {
    let off_list = TestServer::start(mock_with_valid_team(), |_| {}).await;
    let response = off_list.connect("remote_eval", VALID_TOKEN).await;
    assert_eq!(response.status(), 403);

    let on_list = TestServer::start(mock_with_valid_team(), |raw| {
        raw.mode2_team_allowlist = TEAM_ID.to_string();
    })
    .await;
    let response = on_list.connect("remote_eval", VALID_TOKEN).await;
    assert_eq!(response.status(), 200);
    let mut frames = SseFrames::new(response);
    let first = frames.next_frame(READ_TIMEOUT).await.expect("first frame");
    assert!(first.contains("retry:"), "got {first:?}");
}

// Boundary parsing: unknown kind and empty token are 400s before any auth work.
#[tokio::test]
async fn bad_requests_yield_400() {
    let server = TestServer::start(mock_with_valid_team(), |_| {}).await;

    let bad_kind = server.connect("bogus", VALID_TOKEN).await;
    assert_eq!(bad_kind.status(), 400);

    let empty_token = server.connect("definitions", "").await;
    assert_eq!(empty_token.status(), 400);
}

// Scenario 8: drain — cancelling the pod shutdown token closes the open stream
// promptly with a clean EOF (well under max-age), and the pod stops accepting.
#[tokio::test]
async fn drain_closes_open_streams_promptly() {
    let server = TestServer::start(mock_with_team_and_defs_etag(ETAG_A), |_| {}).await;
    let response = server.connect("definitions", VALID_TOKEN).await;
    let mut frames = SseFrames::new(response);
    frames
        .frame_matching(READ_TIMEOUT, |frame| frame.contains(ETAG_A))
        .await;

    server.drain();

    // The stream must end (EOF), not hang until max-age (30 min default).
    let end = frames.next_frame(Duration::from_secs(2)).await;
    assert!(end.is_none(), "expected clean EOF on drain, got {end:?}");

    // The pod no longer accepts work: 503 while readiness is still up, or a
    // connection error once the drained server has fully exited (the in-process
    // drain completes in milliseconds, so either state is legitimate here).
    match reqwest::Client::new()
        .get(format!("http://{}/_readiness", server.addr))
        .send()
        .await
    {
        Ok(readiness) => assert_eq!(readiness.status(), 503),
        Err(e) => assert!(e.is_connect(), "unexpected readiness error: {e}"),
    }
}
