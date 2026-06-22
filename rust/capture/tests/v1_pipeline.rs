mod common;

use std::sync::Arc;

use rdkafka::error::RDKafkaErrorCode;
use rstest::rstest;
use uuid::Uuid;

use capture::v1::analytics::process::process_batch;
use capture::v1::analytics::response::BatchResponse;
use capture::v1::analytics::types::{Batch, EventResult};
use capture::v1::sinks::kafka::mock::MockProducer;
use capture::v1::sinks::kafka::producer::ProduceError;
use capture::v1::sinks::SinkName;
use capture::v1::test_utils::{self, batch_payload, valid_event, TestStateBuilder};
use capture::v1::Error;

fn event_with_name(name: &str) -> capture::v1::analytics::types::Event {
    let mut e = valid_event();
    e.event = name.to_string();
    e.uuid = Uuid::new_v4().to_string();
    e
}

async fn run_batch(payload: &[u8], builder: TestStateBuilder) -> Result<BatchResponse, Error> {
    run_batch_with_state(payload, builder).await.0
}

async fn run_batch_with_state(
    payload: &[u8],
    builder: TestStateBuilder,
) -> (Result<BatchResponse, Error>, test_utils::TestState) {
    let batch: Batch = serde_json::from_slice(payload).expect("payload must parse as Batch");
    let ts = builder.build();
    let mut ctx = test_utils::test_analytics_context();
    let result = process_batch(&ts.state, &mut ctx, batch).await;
    (result, ts)
}

// -------------------------------------------------------------------------
// Table 1: Event Type → Destination Routing
// -------------------------------------------------------------------------

#[rstest]
#[case::pageview("$pageview", "events_main")]
#[case::exception("$exception", "error_tracking_events")]
#[case::heatmap("$$heatmap", "heatmaps_ingestion")]
#[case::client_warning("$$client_ingestion_warning", "events_plugin_ingestion")]
#[case::custom("signup_complete", "events_main")]
#[tokio::test]
async fn event_type_routes_to_destination(#[case] event_name: &str, #[case] expected_topic: &str) {
    let events = vec![event_with_name(event_name)];
    let payload = batch_payload(&events);

    let (result, ts) = run_batch_with_state(&payload, TestStateBuilder::new()).await;

    let resp = result.expect("batch should succeed");
    assert_eq!(resp.entries().len(), 1);
    assert_eq!(resp.entries()[0].1.result, EventResult::Ok);

    ts.mock_producer.with_records(|records| {
        assert_eq!(records.len(), 1, "expected exactly 1 Kafka record");
        assert_eq!(records[0].topic, expected_topic);
    });
}

// -------------------------------------------------------------------------
// Table 2: Processing Outcomes (Mixed Batches)
// -------------------------------------------------------------------------

#[tokio::test]
async fn mixed_batch_all_ok() {
    let events = vec![
        event_with_name("$pageview"),
        event_with_name("$identify"),
        event_with_name("custom_event"),
    ];
    let payload = batch_payload(&events);

    let resp = run_batch(&payload, TestStateBuilder::new())
        .await
        .expect("batch should succeed");

    assert_eq!(resp.entries().len(), 3);
    assert!(!resp.has_retry);
    for (_, status) in resp.entries() {
        assert_eq!(status.result, EventResult::Ok);
    }
}

#[tokio::test]
async fn sink_ack_error_causes_retry() {
    let mut manager = lifecycle::Manager::builder("test_ack_err")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .build();
    let handle = manager.register("test_ack_err", lifecycle::ComponentOptions::new());
    handle.report_healthy();
    let _monitor = manager.monitor_background();

    let producer =
        Arc::new(
            MockProducer::new(SinkName::Msk, handle).with_ack_error(|| ProduceError::Kafka {
                code: RDKafkaErrorCode::BrokerNotAvailable,
            }),
        );

    let events = vec![event_with_name("$pageview"), event_with_name("$identify")];
    let payload = batch_payload(&events);

    let resp = run_batch(
        &payload,
        TestStateBuilder::new().with_mock_producer(producer),
    )
    .await
    .expect("batch should succeed");

    assert_eq!(resp.entries().len(), 2);
    assert!(resp.has_retry);
    for (_, status) in resp.entries() {
        assert_eq!(status.result, EventResult::Retry);
    }
}

#[tokio::test]
async fn all_events_quota_dropped() {
    let events = vec![
        event_with_name("$pageview"),
        event_with_name("custom_event"),
    ];
    let payload = batch_payload(&events);

    let ts = TestStateBuilder::new().with_quota_limited().build();

    // with_quota_limited() loads a wildcard "*" token into the limiter's
    // DashMap — use "*" as the api_token so `is_limited("*")` matches.
    // Poll until the background task populates the cache (avoids flaky fixed sleep).
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(2);
    loop {
        let batch: Batch = serde_json::from_slice(&payload).expect("payload must parse as Batch");
        let mut ctx = test_utils::test_analytics_context();
        ctx.api_token = "*".to_string();
        let result = process_batch(&ts.state, &mut ctx, batch).await;
        if result.is_err() {
            let err = result.unwrap_err();
            assert!(
                matches!(err, Error::BillingLimitExceeded),
                "expected BillingLimitExceeded, got: {err:?}"
            );
            return;
        }
        assert!(
            tokio::time::Instant::now() < deadline,
            "quota limiter cache was not populated within 2s"
        );
        tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    }
}

#[tokio::test]
async fn historical_rerouting() {
    let old_ts = chrono::Utc::now() - chrono::Duration::days(60);
    let mut event = valid_event();
    event.timestamp = old_ts.to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    event.uuid = Uuid::new_v4().to_string();

    let events = vec![event];
    let payload = batch_payload(&events);

    let (result, ts) = run_batch_with_state(
        &payload,
        TestStateBuilder::new().with_historical_rerouting(30),
    )
    .await;

    let resp = result.expect("batch should succeed");
    assert_eq!(resp.entries().len(), 1);
    assert_eq!(resp.entries()[0].1.result, EventResult::Ok);

    ts.mock_producer.with_records(|records| {
        assert_eq!(records.len(), 1);
        assert_eq!(
            records[0].topic, "events_hist",
            "old event should route to historical topic"
        );
    });
}

// -------------------------------------------------------------------------
// Table 3: Compression Round-Trip
// -------------------------------------------------------------------------

#[rstest]
#[case::identity(None)]
#[case::gzip(Some("gzip"))]
#[case::zstd(Some("zstd"))]
#[case::deflate(Some("deflate"))]
#[case::brotli(Some("br"))]
#[tokio::test]
async fn compression_round_trip(#[case] encoding: Option<&str>) {
    let events = vec![
        event_with_name("$pageview"),
        event_with_name("$exception"),
        event_with_name("custom"),
    ];
    let raw = batch_payload(&events);

    let payload = match encoding {
        Some(enc) => common::compress(&raw, enc),
        None => raw,
    };

    let batch: Batch = match encoding {
        Some(enc) => {
            let decompressed = capture::v1::util::decompress_payload(
                Some(enc),
                bytes::Bytes::from(payload),
                20 * 1024 * 1024,
                64,
            )
            .await
            .expect("decompression should succeed");
            serde_json::from_slice(&decompressed).expect("decompressed payload must parse")
        }
        None => serde_json::from_slice(&payload).expect("raw payload must parse"),
    };

    let ts = TestStateBuilder::new().build();
    let mut ctx = test_utils::test_analytics_context();
    if encoding.is_some() {
        ctx.content_encoding = encoding.map(String::from);
    }

    let resp = process_batch(&ts.state, &mut ctx, batch)
        .await
        .expect("batch should succeed");

    assert_eq!(resp.entries().len(), 3);
    assert!(!resp.has_retry);
    for (_, status) in resp.entries() {
        assert_eq!(status.result, EventResult::Ok);
    }
}

// -------------------------------------------------------------------------
// Table 4: Validation Errors
// -------------------------------------------------------------------------

#[tokio::test]
async fn empty_batch_error() {
    let payload = serde_json::to_vec(&serde_json::json!({
        "created_at": "2026-03-19T14:30:00.000Z",
        "batch": []
    }))
    .unwrap();

    let err = run_batch(&payload, TestStateBuilder::new())
        .await
        .expect_err("empty batch should fail");

    assert!(
        matches!(err, Error::EmptyBatch),
        "expected EmptyBatch, got: {err:?}"
    );
}

#[tokio::test]
async fn duplicate_uuid_error() {
    let shared_uuid = Uuid::new_v4().to_string();
    let mut e1 = valid_event();
    e1.uuid = shared_uuid.clone();
    let mut e2 = valid_event();
    e2.event = "$identify".to_string();
    e2.uuid = shared_uuid;

    let payload = batch_payload(&[e1, e2]);

    let err = run_batch(&payload, TestStateBuilder::new())
        .await
        .expect_err("duplicate uuid should fail");

    assert!(
        matches!(err, Error::DuplicateEventUuid(_)),
        "expected DuplicateEventUuid, got: {err:?}"
    );
}

#[tokio::test]
async fn missing_event_name_drops_event() {
    let mut bad = valid_event();
    bad.event = String::new();
    let good = event_with_name("$pageview");

    let payload = batch_payload(&[bad, good]);

    let resp = run_batch(&payload, TestStateBuilder::new())
        .await
        .expect("batch with mix of valid and invalid events should succeed");

    assert_eq!(resp.entries().len(), 2);
    assert_eq!(resp.entries()[0].1.result, EventResult::Drop);
    assert_eq!(resp.entries()[0].1.details, Some("missing_event_name"));
    assert_eq!(resp.entries()[1].1.result, EventResult::Ok);
}
