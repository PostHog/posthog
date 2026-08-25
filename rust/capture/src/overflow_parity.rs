//! Cross-path parity for overflow and global-rate-limit interaction.
//!
//! The v0 and v1 pipelines stamp their overflow and rate-limit decisions in
//! opposite orders (v0 runs the global rate limiter before the burst limiter,
//! v1 after) and reach the broker through separate sinks. Both must still put
//! the same event on the same lane, with the same partition-key presence and
//! the same person-processing header, because those three things are the wire
//! contract downstream ingestion reads.
//!
//! Each case runs the real pipeline on both paths and asserts both against an
//! explicit expectation, not merely against each other, so two paths that drift
//! together still fail.

use std::sync::Arc;

use chrono::{DateTime, Utc};
use limiters::overflow::OverflowLimiter;
use limiters::token_dropper::TokenDropper;
use rstest::rstest;
use std::num::NonZeroU32;

use crate::global_rate_limiter::GlobalRateLimiter;
use crate::router::HistoricalConfig;
use crate::sinks::kafka::{test_topics, KafkaSinkBase};
use crate::sinks::producer::MockKafkaProducer;
use crate::v0_request::ProcessingContext;
use crate::v1::analytics::process::process_batch;
use crate::v1::test_utils::{self, TestStateBuilder};
use common_types::RawEvent;

/// v0's canonical key is `token:distinct_id`; the two paths use different test
/// tokens and distinct ids, so each side gets a limiter keyed for its own.
const V0_TOKEN: &str = "test_token";
const V0_DISTINCT_ID: &str = "test_user";
const V1_HOT_KEY: &str = "phc_test_token:user-42";

/// The lane an event landed on, independent of each path's test topic names.
#[derive(Debug, PartialEq, Eq)]
enum Lane {
    Main,
    Overflow,
    Other(String),
}

/// The three wire facts downstream ingestion actually reads.
#[derive(Debug, PartialEq, Eq)]
struct Observed {
    lane: Lane,
    has_key: bool,
    person_processing_disabled: bool,
}

#[derive(Clone, Copy)]
struct Limits {
    /// The token:distinct_id is over the global rate limit window.
    globally_limited: bool,
    /// A burst limiter is armed. `burst` of 1 limits every event after the first.
    burst_limiter: bool,
    /// The burst limiter keeps partition keys, as prod-US is configured.
    preserve_locality: bool,
    /// The burst limiter force-routes the key outright.
    force_limited: bool,
}

impl Limits {
    const NONE: Self = Self {
        globally_limited: false,
        burst_limiter: false,
        preserve_locality: false,
        force_limited: false,
    };
}

fn v0_overflow_limiter(limits: Limits) -> Option<Arc<OverflowLimiter>> {
    if !limits.burst_limiter && !limits.force_limited {
        return None;
    }
    let forced = limits.force_limited.then(|| V0_TOKEN.to_string());
    Some(Arc::new(OverflowLimiter::new(
        NonZeroU32::new(1).unwrap(),
        NonZeroU32::new(1).unwrap(),
        forced,
        limits.preserve_locality,
    )))
}

fn v0_raw_event() -> RawEvent {
    let mut properties = std::collections::HashMap::new();
    properties.insert("distinct_id".to_string(), serde_json::json!(V0_DISTINCT_ID));
    RawEvent {
        uuid: None,
        distinct_id: None,
        event: "test_event".to_string(),
        properties,
        timestamp: Some("2026-03-19T14:29:58.123Z".to_string()),
        offset: None,
        set: Some(std::collections::HashMap::new()),
        set_once: Some(std::collections::HashMap::new()),
        token: Some(V0_TOKEN.to_string()),
    }
}

fn v0_context(now: DateTime<Utc>) -> ProcessingContext {
    ProcessingContext {
        user_agent: None,
        sent_at: None,
        token: V0_TOKEN.to_string(),
        now,
        client_ip: "127.0.0.1".to_string(),
        request_id: "parity".to_string(),
        path: "/e/".to_string(),
        is_mirror_deploy: false,
        historical_migration: false,
        chatty_debug_enabled: false,
        capture_mode: crate::config::CaptureMode::Events,
        ai_max_event_bytes: 0,
        sdk_attribution: crate::ingestion_warnings::SdkAttribution::default(),
    }
}

/// Drive the real v0 pipeline into a real `KafkaSinkBase` and read the record
/// at `observe` off the mock producer.
async fn run_v0(limits: Limits, batch_size: usize, observe: usize) -> Observed {
    let producer = MockKafkaProducer::new();
    let sink = Arc::new(KafkaSinkBase::with_producer(
        producer.clone(),
        test_topics(),
    ));
    let global = limits.globally_limited.then(|| {
        Arc::new(GlobalRateLimiter::mock_limiting(&[&format!(
            "{V0_TOKEN}:{V0_DISTINCT_ID}"
        )]))
    });

    let now = DateTime::parse_from_rfc3339("2026-03-19T14:30:00Z")
        .unwrap()
        .with_timezone(&Utc);

    crate::events::analytics::process_events(
        sink,
        Arc::new(TokenDropper::default()),
        None,
        HistoricalConfig::new(false, 1),
        global,
        v0_overflow_limiter(limits),
        None,
        None,
        (0..batch_size).map(|_| v0_raw_event()).collect(),
        &v0_context(now),
        None,
    )
    .await
    .expect("v0 pipeline must accept the batch");

    let records = producer.get_records();
    assert_eq!(records.len(), batch_size, "v0 must produce every event");
    let record = &records[observe];
    let topics = test_topics();
    Observed {
        lane: if record.topic == topics.main {
            Lane::Main
        } else if record.topic == topics.overflow {
            Lane::Overflow
        } else {
            Lane::Other(record.topic.clone())
        },
        has_key: record.key.is_some(),
        person_processing_disabled: record
            .headers
            .force_disable_person_processing
            .unwrap_or(false),
    }
}

/// Drive the real v1 pipeline through its sink router and read the record at
/// `observe` off the mock producer.
async fn run_v1(limits: Limits, batch_size: usize, observe: usize) -> Observed {
    let mut builder = TestStateBuilder::new();
    if limits.burst_limiter || limits.force_limited {
        builder = builder.with_overflow_limiter(1, 1);
    }
    if limits.preserve_locality {
        builder = builder.with_overflow_preserve_locality();
    }
    if limits.force_limited {
        builder = builder.with_overflow_forced_key("phc_test_token");
    }
    if limits.globally_limited {
        builder = builder
            .with_global_rate_limiter(Arc::new(GlobalRateLimiter::mock_limiting(&[V1_HOT_KEY])));
    }
    let ts = builder.build();

    let mut ctx = test_utils::test_analytics_context();
    let events: Vec<_> = (0..batch_size).map(|_| test_utils::valid_event()).collect();
    process_batch(&ts.state, &mut ctx, test_utils::valid_batch(events))
        .await
        .expect("v1 pipeline must accept the batch");

    let cfg = test_utils::test_kafka_config();
    ts.mock_producer.with_records(|records| {
        assert_eq!(records.len(), batch_size, "v1 must produce every event");
        let record = &records[observe];
        Observed {
            lane: if record.topic == cfg.topic_main {
                Lane::Main
            } else if record.topic == cfg.topic_overflow {
                Lane::Overflow
            } else {
                Lane::Other(record.topic.clone())
            },
            has_key: record.key.is_some(),
            person_processing_disabled: record.header("force_disable_person_processing")
                == Some("true"),
        }
    })
}

/// The matrix. Cases with a burst limiter armed send two events and observe
/// the second (`burst` of 1 admits the first event and limits the rest);
/// every other case observes its only event.
#[rstest]
#[case::no_limits(
    Limits::NONE,
    Observed { lane: Lane::Main, has_key: true, person_processing_disabled: false }
)]
// A person-on burst keeps its key on either locality setting: the analytics
// overflow consumer updates persons keyed on distinct id, so spreading one
// distinct id across partitions would contend those updates. Person
// processing stays on — a burst says nothing about identity resolution.
#[case::burst_rate_limited(
    Limits { burst_limiter: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: true, person_processing_disabled: false }
)]
#[case::burst_rate_limited_preserving_locality(
    Limits { burst_limiter: true, preserve_locality: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: true, person_processing_disabled: false }
)]
#[case::force_limited(
    Limits { force_limited: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: false, person_processing_disabled: true }
)]
#[case::globally_limited(
    Limits { globally_limited: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: false, person_processing_disabled: true }
)]
#[case::globally_limited_and_burst_rate_limited(
    Limits { globally_limited: true, burst_limiter: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: false, person_processing_disabled: true }
)]
// The cell the two paths used to disagree on: the global rate limiter has taken
// person processing away, so the burst limiter's locality preference must not
// hand the hot key its partition back.
#[case::globally_limited_and_burst_preserving_locality(
    Limits { globally_limited: true, burst_limiter: true, preserve_locality: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: false, person_processing_disabled: true }
)]
#[tokio::test]
async fn v0_and_v1_agree(#[case] limits: Limits, #[case] expected: Observed) {
    let batch_size = if limits.burst_limiter { 2 } else { 1 };
    let observe = batch_size - 1;

    let v0 = run_v0(limits, batch_size, observe).await;
    let v1 = run_v1(limits, batch_size, observe).await;

    assert_eq!(v0, expected, "v0 diverged from the contract");
    assert_eq!(v1, expected, "v1 diverged from the contract");
}
