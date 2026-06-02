//! HTTP-level integration tests for the v1 analytics pipeline.
//!
//! These tests verify the full server path:
//!   POST /i/v1/analytics/events -> router -> handler -> process_batch
//!     -> v1 sink router -> real Kafka -> consumer -> CapturedEvent
//!
//! Requires Docker Kafka (same rig as the other integration tests).
//!
//! Scope is deliberately narrow: route gating (404 when no sink is configured)
//! and the HTTP->Kafka round trip for a single event and a small batch. Payload
//! shape, header parity, partition keys, and destination routing are already
//! covered at the sink layer by `v1_sink_integration.rs` — we don't re-test
//! them here.

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use anyhow::Result;
use common_types::CapturedEvent;
use uuid::Uuid;

use capture::v1::analytics::types::Event;
use capture::v1::test_utils::{batch_payload, valid_event};

const TOKEN: &str = "phc_http_integration_token";

/// A fresh `$pageview` event with a unique UUID and the given distinct_id.
fn pageview(distinct_id: &str) -> Event {
    let mut e = valid_event();
    e.uuid = Uuid::new_v4().to_string();
    e.distinct_id = distinct_id.to_string();
    e
}

fn named(distinct_id: &str, name: &str) -> Event {
    let mut e = pageview(distinct_id);
    e.event = name.to_string();
    e
}

async fn parse_body(res: reqwest::Response) -> serde_json::Value {
    let bytes = res.bytes().await.expect("failed to read response body");
    serde_json::from_slice(&bytes).expect("response body must be JSON")
}

// ---------------------------------------------------------------------------
// Route gating: the v1 endpoint is unregistered (404) without a v1 sink
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_route_unregistered_without_sink() {
    setup_tracing();
    // DEFAULT_CONFIG has capture_v1_sinks empty -> v1_sink_router is None ->
    // the route is never merged, so the path 404s rather than 503s.
    let server = ServerHandle::for_config(DEFAULT_CONFIG.clone()).await;

    let payload = batch_payload(&[pageview("user-404")]);
    let res = server.capture_v1(TOKEN, payload).await;

    assert_eq!(
        res.status(),
        reqwest::StatusCode::NOT_FOUND,
        "v1 route must not be registered when no v1 sink is configured"
    );
}

// ---------------------------------------------------------------------------
// Single event: HTTP -> real Kafka round trip
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_http_single_event_to_kafka() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_v1_topic(&topic).await;

    let ev = pageview("http-user-1");
    let uuid = ev.uuid.clone();
    let payload = batch_payload(std::slice::from_ref(&ev));

    let res = server.capture_v1(TOKEN, payload).await;
    assert_eq!(res.status(), reqwest::StatusCode::OK);

    let body = parse_body(res).await;
    assert_eq!(
        body["results"][uuid.as_str()]["result"],
        "ok",
        "event should be acked ok in the response body: {body}"
    );

    let captured: CapturedEvent = serde_json::from_value(topic.next_event()?)?;
    assert_eq!(captured.uuid.to_string(), uuid);
    assert_eq!(captured.distinct_id, "http-user-1");
    assert_eq!(captured.event, "$pageview");
    assert_eq!(captured.token, TOKEN);

    topic.assert_empty();
    Ok(())
}

// ---------------------------------------------------------------------------
// Small batch: HTTP -> real Kafka round trip
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_http_batch_to_kafka() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_v1_topic(&topic).await;

    let events = vec![
        pageview("http-batch-0"),
        named("http-batch-1", "$identify"),
        named("http-batch-2", "button_clicked"),
    ];
    let uuids: Vec<String> = events.iter().map(|e| e.uuid.clone()).collect();
    let payload = batch_payload(&events);

    let res = server.capture_v1(TOKEN, payload).await;
    assert_eq!(res.status(), reqwest::StatusCode::OK);

    let body = parse_body(res).await;
    for uuid in &uuids {
        assert_eq!(
            body["results"][uuid.as_str()]["result"],
            "ok",
            "every event should be acked ok: {body}"
        );
    }

    let mut distinct_ids = Vec::new();
    for _ in 0..events.len() {
        let captured: CapturedEvent = serde_json::from_value(topic.next_event()?)?;
        assert_eq!(captured.token, TOKEN);
        distinct_ids.push(captured.distinct_id.clone());
    }
    distinct_ids.sort();
    assert_eq!(
        distinct_ids,
        vec!["http-batch-0", "http-batch-1", "http-batch-2"]
    );

    topic.assert_empty();
    Ok(())
}
