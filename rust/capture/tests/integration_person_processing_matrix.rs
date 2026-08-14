//! Interaction matrix for the four mechanisms that decide an analytics event's
//! person processing and routing: the customer's `$process_person_profile`
//! property, a `SkipPersonProcessing` restriction, a `ForceOverflow`
//! restriction, and the global rate limiter.
//!
//! Each mechanism has unit coverage on its own. What no other suite covers is
//! how they compose, and composition is where they are easy to get wrong: three
//! of the four can disable person processing, and two of them decide the
//! partition key through the same `person_ordering` rule.
//!
//! The assertions are the four facts downstream ingestion actually reads off the
//! wire, plus whether capture paid for the limiter at all:
//!
//! - the topic the record landed on
//! - whether it carries a partition key
//! - the `force_disable_person_processing` header
//! - how many times the limiter was consulted
//!
//! The `personless` column is the reason this file exists. `$process_person_profile`
//! and a skip-person restriction mean the same thing to the consumer, so it would
//! be easy to derive one from the other in capture. Doing so would silently stop
//! the limiter from running on personless traffic, which is a large share of
//! volume and exactly the traffic the limiter still has a job on. Every case is
//! run twice, once with the property and once without, and both rows carry the
//! same expectation: the property must change nothing here.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::config::CaptureMode;
use capture::event_restrictions::{
    EventRestrictionService, Pipeline, Restriction, RestrictionManager, RestrictionScope,
    RestrictionType,
};
use capture::global_rate_limiter::GlobalRateLimiter;
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::kafka::KafkaSinkBase;
use capture::sinks::producer::MockKafkaProducer;
use capture::sinks::registry::OutputRegistry;
use capture::time::TimeSource;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use integration_utils::{test_lifecycle_handlers, DEFAULT_CONFIG, DEFAULT_TEST_TIME};
use limiters::token_dropper::TokenDropper;
use metrics_util::debugging::{DebugValue, DebuggingRecorder};
use rstest::rstest;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

const TOKEN: &str = "phc_matrix_token";
const DISTINCT_ID: &str = "matrix-user";

/// The limiter evaluates the local cache, so the first event for a key is always
/// a miss and passes. A threshold of 0 makes the second event for that key
/// exceed the window deterministically, with no Redis round trip and no clock.
const THRESHOLD_ALWAYS_LIMITS: u64 = 0;
const THRESHOLD_NEVER_LIMITS: u64 = 1_000_000;

struct FixedTime {
    time: DateTime<Utc>,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> DateTime<Utc> {
        self.time
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct Inputs {
    /// The event carries `$process_person_profile: false`.
    personless: bool,
    /// A `SkipPersonProcessing` restriction covers the token.
    skip_person_restriction: bool,
    /// A `ForceOverflow` restriction covers the token.
    overflow_restriction: bool,
    /// The limiter's threshold is low enough to limit the observed event.
    over_rate_limit: bool,
}

#[derive(Debug, PartialEq, Eq)]
struct Observed {
    topic: String,
    has_key: bool,
    force_disable_person_processing: Option<bool>,
    limiter_consultations: u64,
}

#[derive(Debug, PartialEq, Eq)]
struct Expected {
    topic: &'static str,
    has_key: bool,
    force_disable_person_processing: Option<bool>,
    /// Consultations across the whole two-event batch, not just the observed
    /// event, because the cost this counts is paid per event.
    limiter_consultations: u64,
}

async fn build_router(inputs: Inputs, producer: MockKafkaProducer) -> Router {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();

    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = CaptureMode::Events;
    cfg.global_rate_limit_enabled = true;
    cfg.global_rate_limit_token_distinctid_threshold = if inputs.over_rate_limit {
        THRESHOLD_ALWAYS_LIMITS
    } else {
        THRESHOLD_NEVER_LIMITS
    };
    // Park the background sync well beyond the request so the limiter's verdict
    // comes from the local cache alone and no Redis tick can race the batch.
    cfg.global_rate_limit_tick_interval_ms = 600_000;

    let redis = Arc::new(MockRedisClient::new());
    let limiter = GlobalRateLimiter::new_token_distinct_id(&cfg, vec![redis.clone()])
        .expect("failed to build the global rate limiter");

    let mut restrictions = Vec::new();
    if inputs.skip_person_restriction {
        restrictions.push(Restriction {
            restriction_type: RestrictionType::SkipPersonProcessing,
            scope: RestrictionScope::AllEvents,
            args: None,
        });
    }
    if inputs.overflow_restriction {
        restrictions.push(Restriction {
            restriction_type: RestrictionType::ForceOverflow,
            scope: RestrictionScope::AllEvents,
            args: None,
        });
    }
    let service = EventRestrictionService::new(
        Pipeline::for_capture_mode(CaptureMode::Events),
        Duration::from_secs(300),
    );
    let mut manager = RestrictionManager::new();
    manager.insert_restrictions(Pipeline::Analytics, TOKEN, restrictions);
    service.update(manager).await;

    let sink = KafkaSinkBase::with_producer(producer, OutputRegistry::from(&cfg.kafka));
    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    router(
        FixedTime {
            time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
                .expect("invalid fixed time")
                .with_timezone(&Utc),
        },
        readiness,
        liveness,
        Arc::new(sink),
        redis,
        Some(Arc::new(limiter)),
        quota_limiter,
        TokenDropper::default(),
        Some(service),
        None,
        CaptureMode::Events,
        None,
        25 * 1024 * 1024,
        false,
        1_i64,
        false,
        0.0_f32,
        26_214_400,
        None,
        256,
        10 * 1024 * 1024,
        50 * 1024 * 1024,
        None,
        None,
        None,
        None,
        8,
        None,
        false,
        None,
    )
}

/// Post a two-event batch for one key and report the wire facts of the second
/// record. The first event seeds the limiter's local cache, which is what lets
/// the second one exceed a zero threshold without any Redis interaction.
async fn run_case(inputs: Inputs) -> Observed {
    // The handler runs on this thread: `#[tokio::test]` is a current-thread
    // runtime, so a thread-local recorder sees the limiter's counters.
    let recorder = DebuggingRecorder::new();
    let snapshotter = recorder.snapshotter();
    let _guard = metrics::set_default_local_recorder(&recorder);

    let producer = MockKafkaProducer::new();
    let router = build_router(inputs, producer.clone()).await;

    let mut properties = json!({});
    if inputs.personless {
        properties["$process_person_profile"] = json!(false);
    }
    let event = json!({
        "event": "$pageview",
        "distinct_id": DISTINCT_ID,
        "properties": properties,
    });
    let payload = json!({
        "api_key": TOKEN,
        "batch": [event.clone(), event],
    });

    let response = TestClient::new(router)
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;
    assert_eq!(response.status(), StatusCode::OK, "capture rejected the batch");

    let records = producer.get_records();
    assert_eq!(records.len(), 2, "both events must reach the producer");
    let observed = &records[1];

    let consultations = snapshotter
        .snapshot()
        .into_vec()
        .iter()
        .filter(|(key, _, _, _)| key.key().name() == "global_rate_limiter_eval_counts_total")
        .filter_map(|(_, _, _, value)| match value {
            DebugValue::Counter(v) => Some(*v),
            _ => None,
        })
        .sum();

    Observed {
        topic: observed.topic.clone(),
        has_key: observed.key.is_some(),
        force_disable_person_processing: observed.headers.force_disable_person_processing,
        limiter_consultations: consultations,
    }
}

// Topic names come from `DEFAULT_CONFIG.kafka`, which the registry is built from.
const MAIN: &str = "events_plugin_ingestion";
const OVERFLOW: &str = "events_plugin_ingestion_overflow";

// Each pair of cases differs only in `personless` and shares one expectation.
#[rstest]
// Nothing applies: the limiter runs on both events and changes nothing.
#[case::plain(
    Inputs::default(),
    Expected { topic: MAIN, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
#[case::plain_personless(
    Inputs { personless: true, ..Inputs::default() },
    Expected { topic: MAIN, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
// The limiter alone: it takes person processing away and spreads the key.
#[case::rate_limited(
    Inputs { over_rate_limit: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
#[case::rate_limited_personless(
    Inputs { over_rate_limit: true, personless: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
// The skip-person restriction alone: person processing off and the key dropped,
// on the main lane, and the limiter is never consulted.
#[case::skip_person(
    Inputs { skip_person_restriction: true, ..Inputs::default() },
    Expected { topic: MAIN, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::skip_person_personless(
    Inputs { skip_person_restriction: true, personless: true, ..Inputs::default() },
    Expected { topic: MAIN, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
// The restriction shadows the limiter entirely: the key is over its window, but
// the limiter is skipped, so nothing reroutes it.
#[case::skip_person_and_rate_limited(
    Inputs { skip_person_restriction: true, over_rate_limit: true, ..Inputs::default() },
    Expected { topic: MAIN, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::skip_person_and_rate_limited_personless(
    Inputs { skip_person_restriction: true, over_rate_limit: true, personless: true, ..Inputs::default() },
    Expected { topic: MAIN, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
// The overflow restriction alone moves the lane but leaves person processing on,
// so the key survives.
#[case::force_overflow(
    Inputs { overflow_restriction: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
#[case::force_overflow_personless(
    Inputs { overflow_restriction: true, personless: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
// Overflow restriction plus the limiter: already on the overflow lane, and the
// limiter's verdict drops the key.
#[case::force_overflow_and_rate_limited(
    Inputs { overflow_restriction: true, over_rate_limit: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
#[case::force_overflow_and_rate_limited_personless(
    Inputs { overflow_restriction: true, over_rate_limit: true, personless: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
// Both restrictions: the overflow lane from one, the dropped key from the other.
#[case::both_restrictions(
    Inputs { skip_person_restriction: true, overflow_restriction: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::both_restrictions_personless(
    Inputs { skip_person_restriction: true, overflow_restriction: true, personless: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
// All three: the limiter is still skipped, and the restrictions alone produce
// the same wire outcome the limiter would have.
#[case::everything(
    Inputs { skip_person_restriction: true, overflow_restriction: true, over_rate_limit: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::everything_personless(
    Inputs { skip_person_restriction: true, overflow_restriction: true, over_rate_limit: true, personless: true, ..Inputs::default() },
    Expected { topic: OVERFLOW, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[tokio::test]
async fn person_processing_and_routing_matrix(#[case] inputs: Inputs, #[case] expected: Expected) {
    let observed = run_case(inputs).await;

    assert_eq!(
        observed,
        Observed {
            topic: expected.topic.to_string(),
            has_key: expected.has_key,
            force_disable_person_processing: expected.force_disable_person_processing,
            limiter_consultations: expected.limiter_consultations,
        },
        "inputs: {inputs:?}"
    );
}
