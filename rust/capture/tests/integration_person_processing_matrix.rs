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
//!
//! Every case runs against both analytics endpoints, `/capture` (v0) and
//! `/i/v1/analytics/events` (v1), and asserts each against the same explicit
//! expectation rather than against the other, so two paths that drift together
//! still fail. The two express the personless choice differently: v0 reads the
//! `$process_person_profile` property, v1 reads `options.process_person_profile`.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use axum::http::StatusCode;
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
use capture::v1::router::{router as v1_router, RouterConfig as V1RouterConfig};
use capture::v1::test_utils::TestStateBuilder;
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

/// The lane an event landed on, independent of each path's topic names.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
enum Lane {
    Main,
    Overflow,
    Other(&'static str),
}

#[derive(Debug, PartialEq, Eq)]
struct Observed {
    lane: Lane,
    has_key: bool,
    force_disable_person_processing: Option<bool>,
    limiter_consultations: u64,
}

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
struct Expected {
    lane: Lane,
    has_key: bool,
    force_disable_person_processing: Option<bool>,
    /// Consultations across the whole two-event batch, not just the observed
    /// event, because the cost this counts is paid per event.
    limiter_consultations: u64,
}

impl From<Expected> for Observed {
    fn from(e: Expected) -> Self {
        Self {
            lane: e.lane,
            has_key: e.has_key,
            force_disable_person_processing: e.force_disable_person_processing,
            limiter_consultations: e.limiter_consultations,
        }
    }
}

/// Count limiter evaluations on the recorder the caller installed. Each
/// evaluation increments this counter exactly once, so it measures the Redis
/// work the skip exists to avoid.
fn consultations(snapshotter: &metrics_util::debugging::Snapshotter) -> u64 {
    snapshotter
        .snapshot()
        .into_vec()
        .iter()
        .filter(|(key, _, _, _)| key.key().name() == "global_rate_limiter_eval_counts_total")
        .filter_map(|(_, _, _, value)| match value {
            DebugValue::Counter(v) => Some(*v),
            _ => None,
        })
        .sum()
}

fn build_limiter(inputs: Inputs, redis: Arc<MockRedisClient>) -> GlobalRateLimiter {
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
    GlobalRateLimiter::new_token_distinct_id(&cfg, vec![redis])
        .expect("failed to build the global rate limiter")
}

async fn build_restrictions(inputs: Inputs) -> EventRestrictionService {
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
    service
}

/// Drive the v0 endpoint (`/capture`) into a real `KafkaSinkBase` and read the
/// second record off the mock producer.
///
/// The batch carries two events for one key on purpose: the limiter evaluates
/// the local cache, so the first is always a miss that passes, and only the
/// second can exceed a zero threshold. That keeps the limiting case free of
/// Redis and of the clock.
async fn run_v0(inputs: Inputs) -> Observed {
    // The handler runs on this thread: `#[tokio::test]` is a current-thread
    // runtime, so a thread-local recorder sees the limiter's counters.
    let recorder = DebuggingRecorder::new();
    let snapshotter = recorder.snapshotter();
    let _guard = metrics::set_default_local_recorder(&recorder);

    let (readiness, liveness, _monitor) = test_lifecycle_handlers();
    let redis = Arc::new(MockRedisClient::new());
    let cfg = DEFAULT_CONFIG.clone();
    let limiter = build_limiter(inputs, redis.clone());
    let service = build_restrictions(inputs).await;

    let producer = MockKafkaProducer::new();
    let sink = KafkaSinkBase::with_producer(producer.clone(), OutputRegistry::from(&cfg.kafka));
    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    let router = router(
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
    );

    // v0 reads the customer's choice from the event property.
    let mut properties = json!({});
    if inputs.personless {
        properties["$process_person_profile"] = json!(false);
    }
    let event = json!({
        "event": "$pageview",
        "distinct_id": DISTINCT_ID,
        "properties": properties,
    });
    let payload = json!({ "api_key": TOKEN, "batch": [event.clone(), event] });

    let response = TestClient::new(router)
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;
    assert_eq!(response.status(), StatusCode::OK, "v0 rejected the batch");

    let records = producer.get_records();
    assert_eq!(records.len(), 2, "v0 must produce both events");
    let observed = &records[1];

    Observed {
        lane: v0_lane(&observed.topic),
        has_key: observed.key.is_some(),
        force_disable_person_processing: observed.headers.force_disable_person_processing,
        limiter_consultations: consultations(&snapshotter),
    }
}

/// Drive the v1 endpoint (`/i/v1/analytics/events`) through its own router and
/// sink, reading the second record off the v1 mock producer.
async fn run_v1(inputs: Inputs) -> Observed {
    let recorder = DebuggingRecorder::new();
    let snapshotter = recorder.snapshotter();
    let _guard = metrics::set_default_local_recorder(&recorder);

    let redis = Arc::new(MockRedisClient::new());
    let limiter = build_limiter(inputs, redis);
    let service = build_restrictions(inputs).await;

    let ts = TestStateBuilder::new()
        .with_restriction_service(service)
        .with_global_rate_limiter(Arc::new(limiter))
        .build();

    let router = v1_router(V1RouterConfig {
        concurrency_limit: None,
        max_compressed_body_bytes: 10 * 1024 * 1024,
    })
    .with_state(ts.state.clone());

    // v1 reads the customer's choice from the event options, not the property.
    let options = if inputs.personless {
        json!({ "process_person_profile": false })
    } else {
        json!({})
    };
    let event = json!({
        "event": "$pageview",
        "uuid": "0198f0a0-0000-7000-8000-000000000001",
        "distinct_id": DISTINCT_ID,
        "timestamp": "2026-03-19T14:29:58.123Z",
        "options": options,
        "properties": {},
    });
    let mut second = event.clone();
    second["uuid"] = json!("0198f0a0-0000-7000-8000-000000000002");
    let payload = json!({
        "created_at": "2026-03-19T14:30:00.000Z",
        "batch": [event, second],
    });

    let response = TestClient::new(router)
        .post("/i/v1/analytics/events")
        .header("authorization", format!("Bearer {TOKEN}"))
        .header("content-type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .header("PostHog-Sdk-Info", "posthog-rs/1.0.0")
        .header("PostHog-Attempt", "1")
        .header("PostHog-Request-Id", "00000000-0000-0000-0000-000000000001")
        .header("PostHog-Request-Timestamp", "2026-03-19T14:30:00.000Z")
        .header("user-agent", "test-client/1.0")
        .body(payload.to_string())
        .send()
        .await;
    let status = response.status();
    let body = response.text().await;
    assert_eq!(status, StatusCode::OK, "v1 rejected the batch: {body}");

    ts.mock_producer.with_records(|records| {
        assert_eq!(records.len(), 2, "v1 must produce both events");
        let observed = &records[1];
        Observed {
            lane: v1_lane(&observed.topic),
            has_key: observed.key.is_some(),
            // The wire header is bytes, so read it back the way a consumer would.
            force_disable_person_processing: observed
                .header("force_disable_person_processing")
                .map(|v| v == "true"),
            limiter_consultations: consultations(&snapshotter),
        }
    })
}

// Each path names its lanes differently; the matrix compares lanes, not strings.
fn v0_lane(topic: &str) -> Lane {
    match topic {
        "events_plugin_ingestion" => Lane::Main,
        "events_plugin_ingestion_overflow" => Lane::Overflow,
        other => Lane::Other(Box::leak(other.to_string().into_boxed_str())),
    }
}

fn v1_lane(topic: &str) -> Lane {
    match topic {
        "events_main" => Lane::Main,
        "events_overflow" => Lane::Overflow,
        other => Lane::Other(Box::leak(other.to_string().into_boxed_str())),
    }
}

// Each pair of cases differs only in `personless` and shares one expectation.
#[rstest]
// Nothing applies: the limiter runs on both events and changes nothing.
#[case::plain(
    Inputs::default(),
    Expected { lane: Lane::Main, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
#[case::plain_personless(
    Inputs { personless: true, ..Inputs::default() },
    Expected { lane: Lane::Main, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
// The limiter alone: it takes person processing away and spreads the key.
#[case::rate_limited(
    Inputs { over_rate_limit: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
#[case::rate_limited_personless(
    Inputs { over_rate_limit: true, personless: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
// The skip-person restriction alone: person processing off and the key dropped,
// on the main lane, and the limiter is never consulted.
#[case::skip_person(
    Inputs { skip_person_restriction: true, ..Inputs::default() },
    Expected { lane: Lane::Main, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::skip_person_personless(
    Inputs { skip_person_restriction: true, personless: true, ..Inputs::default() },
    Expected { lane: Lane::Main, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
// The restriction shadows the limiter entirely: the key is over its window, but
// the limiter is skipped, so nothing reroutes it.
#[case::skip_person_and_rate_limited(
    Inputs { skip_person_restriction: true, over_rate_limit: true, ..Inputs::default() },
    Expected { lane: Lane::Main, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::skip_person_and_rate_limited_personless(
    Inputs { skip_person_restriction: true, over_rate_limit: true, personless: true, ..Inputs::default() },
    Expected { lane: Lane::Main, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
// The overflow restriction alone moves the lane but leaves person processing on,
// so the key survives.
#[case::force_overflow(
    Inputs { overflow_restriction: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
#[case::force_overflow_personless(
    Inputs { overflow_restriction: true, personless: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: true, force_disable_person_processing: None, limiter_consultations: 2 }
)]
// Overflow restriction plus the limiter: already on the overflow lane, and the
// limiter's verdict drops the key.
#[case::force_overflow_and_rate_limited(
    Inputs { overflow_restriction: true, over_rate_limit: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
#[case::force_overflow_and_rate_limited_personless(
    Inputs { overflow_restriction: true, over_rate_limit: true, personless: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 2 }
)]
// Both restrictions: the overflow lane from one, the dropped key from the other.
#[case::both_restrictions(
    Inputs { skip_person_restriction: true, overflow_restriction: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::both_restrictions_personless(
    Inputs { skip_person_restriction: true, overflow_restriction: true, personless: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
// All three: the limiter is still skipped, and the restrictions alone produce
// the same wire outcome the limiter would have.
#[case::everything(
    Inputs { skip_person_restriction: true, overflow_restriction: true, over_rate_limit: true, ..Inputs::default() },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[case::everything_personless(
    Inputs { skip_person_restriction: true, overflow_restriction: true, over_rate_limit: true, personless: true },
    Expected { lane: Lane::Overflow, has_key: false, force_disable_person_processing: Some(true), limiter_consultations: 0 }
)]
#[tokio::test]
async fn person_processing_and_routing_matrix(#[case] inputs: Inputs, #[case] expected: Expected) {
    assert_eq!(
        run_v0(inputs).await,
        Observed::from(expected),
        "v0 endpoint, inputs: {inputs:?}"
    );
    assert_eq!(
        run_v1(inputs).await,
        Observed::from(expected),
        "v1 endpoint, inputs: {inputs:?}"
    );
}
