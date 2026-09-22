//! Cross-path parity for overflow and global-rate-limit interaction.
//!
//! The v0 and v1 pipelines stamp their overflow and rate-limit decisions in
//! opposite orders (v0 runs the global rate limiter before the forced-key
//! check, v1 after) and reach the broker through separate sinks. Both must
//! still put the same event on the same lane, with the same partition-key
//! presence and the same person-processing header, because those three things
//! are the wire contract downstream ingestion reads.
//!
//! Each case runs the real pipeline on both paths and asserts both against an
//! explicit expectation, not merely against each other, so two paths that drift
//! together still fail.

use std::sync::Arc;

use chrono::{DateTime, Utc};
use limiters::overflow::ForcedOverflowKeys;
use limiters::token_dropper::TokenDropper;
use rstest::rstest;

use crate::global_rate_limiter::GlobalRateLimiter;
use crate::outputs::OutputRegistry;
use crate::router::HistoricalConfig;
use crate::sinks::kafka::{test_topics, KafkaSinkBase};
use crate::sinks::producer::MockKafkaProducer;
use crate::v0_request::ProcessingContext;
use crate::v1::analytics::process::process_batch;
use crate::v1::test_utils::{self, TestStateBuilder};
use common_types::RawEvent;

/// v0's canonical key is `token:distinct_id`; the two paths use different test
/// tokens and distinct ids, so each side gets a forced-key list of its own.
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
    /// The key is on the operator's forced-overflow list.
    force_limited: bool,
}

impl Limits {
    const NONE: Self = Self {
        globally_limited: false,
        force_limited: false,
    };
}

fn v0_overflow_forced_keys(limits: Limits) -> Option<Arc<ForcedOverflowKeys>> {
    limits
        .force_limited
        .then(|| Arc::new(ForcedOverflowKeys::new(Some(V0_TOKEN.to_string()))))
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

/// Drive the real v0 pipeline into a real `KafkaSinkBase` and read the single
/// produced record off the mock producer.
async fn run_v0(limits: Limits) -> Observed {
    let producer = MockKafkaProducer::new();
    let outputs = Arc::new(OutputRegistry::single(KafkaSinkBase::with_producer(
        producer.clone(),
        test_topics(),
    )));
    let global = limits.globally_limited.then(|| {
        Arc::new(GlobalRateLimiter::mock_limiting(&[&format!(
            "{V0_TOKEN}:{V0_DISTINCT_ID}"
        )]))
    });

    let now = DateTime::parse_from_rfc3339("2026-03-19T14:30:00Z")
        .unwrap()
        .with_timezone(&Utc);

    crate::events::analytics::process_events(
        outputs,
        Arc::new(TokenDropper::default()),
        None,
        HistoricalConfig::new(false, 1),
        global,
        v0_overflow_forced_keys(limits),
        None,
        None,
        vec![v0_raw_event()],
        &v0_context(now),
        None,
    )
    .await
    .expect("v0 pipeline must accept the batch");

    let records = producer.get_records();
    assert_eq!(records.len(), 1, "v0 must produce every event");
    let record = &records[0];
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

/// Drive the real v1 pipeline through its sink router and read the single
/// produced record off the mock producer.
async fn run_v1(limits: Limits) -> Observed {
    let mut builder = TestStateBuilder::new();
    if limits.force_limited {
        builder = builder.with_overflow_forced_key("phc_test_token");
    }
    if limits.globally_limited {
        builder = builder
            .with_global_rate_limiter(Arc::new(GlobalRateLimiter::mock_limiting(&[V1_HOT_KEY])));
    }
    let ts = builder.build();

    let mut ctx = test_utils::test_analytics_context();
    let events = vec![test_utils::valid_event()];
    process_batch(&ts.state, &mut ctx, test_utils::valid_batch(events))
        .await
        .expect("v1 pipeline must accept the batch");

    let cfg = test_utils::test_kafka_config();
    ts.mock_producer.with_records(|records| {
        assert_eq!(records.len(), 1, "v1 must produce every event");
        let record = &records[0];
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

/// The matrix. Every case sends and observes a single event.
#[rstest]
#[case::no_limits(
    Limits::NONE,
    Observed { lane: Lane::Main, has_key: true, person_processing_disabled: false }
)]
#[case::force_limited(
    Limits { force_limited: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: false, person_processing_disabled: true }
)]
#[case::globally_limited(
    Limits { globally_limited: true, ..Limits::NONE },
    Observed { lane: Lane::Overflow, has_key: false, person_processing_disabled: true }
)]
#[case::globally_limited_and_force_limited(
    Limits { globally_limited: true, force_limited: true },
    Observed { lane: Lane::Overflow, has_key: false, person_processing_disabled: true }
)]
#[tokio::test]
async fn v0_and_v1_agree(#[case] limits: Limits, #[case] expected: Observed) {
    let v0 = run_v0(limits).await;
    let v1 = run_v1(limits).await;

    assert_eq!(v0, expected, "v0 diverged from the contract");
    assert_eq!(v1, expected, "v1 diverged from the contract");
}
