use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_types::{CapturedEvent, CapturedEventHeaders, RawEvent};
use rdkafka::error::RDKafkaErrorCode;
use rstest::rstest;
use uuid::Uuid;

use crate::config::CaptureMode;
use crate::v1::context::Context;
use crate::v1::sinks::event::Event;
use crate::v1::sinks::sink::Sink;
use crate::v1::sinks::types::{BatchSummary, Outcome};
use crate::v1::sinks::{Config, Destination, SinkName};
use crate::v1::test_utils::{self, WrappedEventMut};

use super::mock::MockProducer;
use super::producer::ProduceError;
use super::sink::KafkaSink;

/// All-None CapturedEventHeaders for stubbing FakeEvent. `CapturedEventHeaders`
/// does not derive `Default` in common_types; keep the literal here so the
/// stub doesn't leak unrelated fields into sink_tests.
fn empty_captured_headers() -> CapturedEventHeaders {
    CapturedEventHeaders {
        token: None,
        distinct_id: None,
        session_id: None,
        timestamp: None,
        event: None,
        uuid: None,
        now: None,
        force_disable_person_processing: None,
        historical_migration: None,
        dlq_reason: None,
        dlq_step: None,
        dlq_timestamp: None,
    }
}

// ---------------------------------------------------------------------------
// FakeEvent
// ---------------------------------------------------------------------------

struct FakeEvent {
    parsed_uuid: Uuid,
    publish: bool,
    destination: Destination,
    partition_key: Option<String>,
    payload: Result<String, String>,
    event_headers: CapturedEventHeaders,
}

impl FakeEvent {
    fn ok(uuid: &str) -> Self {
        Self {
            parsed_uuid: Uuid::new_v4(),
            publish: true,
            destination: Destination::AnalyticsMain,
            partition_key: Some(format!("phc_test:{uuid}")),
            payload: Ok(r#"{"event":"test"}"#.to_string()),
            event_headers: empty_captured_headers(),
        }
    }

    fn with_destination(mut self, d: Destination) -> Self {
        self.destination = d;
        self
    }

    fn with_publish(mut self, p: bool) -> Self {
        self.publish = p;
        self
    }

    fn with_payload(mut self, p: Result<String, String>) -> Self {
        self.payload = p;
        self
    }

    fn with_partition_key(mut self, k: Option<&str>) -> Self {
        self.partition_key = k.map(String::from);
        self
    }
}

impl Event for FakeEvent {
    fn uuid(&self) -> Uuid {
        self.parsed_uuid
    }

    fn should_publish(&self) -> bool {
        self.publish
    }

    fn destination(&self) -> &Destination {
        &self.destination
    }

    fn headers(&self, _ctx: &Context) -> CapturedEventHeaders {
        self.event_headers.clone()
    }

    fn partition_key<'buf>(&self, _ctx: &Context, buf: &'buf mut String) -> Option<&'buf str> {
        match &self.partition_key {
            Some(k) => {
                buf.push_str(k);
                Some(buf.as_str())
            }
            None => None,
        }
    }

    fn serialize_into(&self, _ctx: &Context, buf: &mut String) -> anyhow::Result<()> {
        match &self.payload {
            Ok(p) => {
                buf.push_str(p);
                Ok(())
            }
            Err(e) => Err(anyhow::anyhow!(e.clone())),
        }
    }
}

// ---------------------------------------------------------------------------
// TestHarness
// ---------------------------------------------------------------------------

struct TestHarness {
    sink: KafkaSink<MockProducer>,
    producer: Arc<MockProducer>,
    handle: lifecycle::Handle,
    ctx: Context,
    _monitor: lifecycle::MonitorGuard,
}

impl TestHarness {
    fn new() -> Self {
        Self::builder().build()
    }

    fn builder() -> HarnessBuilder {
        HarnessBuilder {
            produce_timeout: Duration::from_secs(30),
            send_error: None,
            send_error_count: None,
            ack_error: None,
            ack_delay: None,
            not_ready: false,
            liveness: None,
            enqueue_retry_max: None,
            enqueue_poll_ms: None,
        }
    }
}

struct HarnessBuilder {
    produce_timeout: Duration,
    send_error: Option<fn() -> ProduceError>,
    send_error_count: Option<u32>,
    ack_error: Option<fn() -> ProduceError>,
    ack_delay: Option<Duration>,
    not_ready: bool,
    liveness: Option<(Duration, Duration)>,
    enqueue_retry_max: Option<u32>,
    enqueue_poll_ms: Option<u32>,
}

impl HarnessBuilder {
    fn produce_timeout(mut self, d: Duration) -> Self {
        self.produce_timeout = d;
        self
    }

    fn send_error(mut self, f: fn() -> ProduceError) -> Self {
        self.send_error = Some(f);
        self
    }

    fn send_error_count(mut self, n: u32) -> Self {
        self.send_error_count = Some(n);
        self
    }

    fn ack_error(mut self, f: fn() -> ProduceError) -> Self {
        self.ack_error = Some(f);
        self
    }

    fn ack_delay(mut self, d: Duration) -> Self {
        self.ack_delay = Some(d);
        self
    }

    fn not_ready(mut self) -> Self {
        self.not_ready = true;
        self
    }

    fn with_liveness(mut self, deadline: Duration, poll_interval: Duration) -> Self {
        self.liveness = Some((deadline, poll_interval));
        self
    }

    fn enqueue_retry_max(mut self, n: u32) -> Self {
        self.enqueue_retry_max = Some(n);
        self
    }

    fn enqueue_poll_ms(mut self, ms: u32) -> Self {
        self.enqueue_poll_ms = Some(ms);
        self
    }

    fn build(self) -> TestHarness {
        let mut builder = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false);

        if let Some((_, poll_interval)) = self.liveness {
            builder = builder.with_health_poll_interval(poll_interval);
        }

        let mut manager = builder.build();

        let mut opts = lifecycle::ComponentOptions::new();
        if let Some((deadline, _)) = self.liveness {
            opts = opts.with_liveness_deadline(deadline);
        }
        let handle = manager.register("kafka_sink_test", opts);
        handle.report_healthy();

        let monitor = manager.monitor_background();

        let mut mock = MockProducer::new(SinkName::Msk, handle.clone());
        if let Some(f) = self.send_error {
            mock = mock.with_send_error(f);
        }
        if let Some(n) = self.send_error_count {
            mock = mock.with_send_error_count(n);
        }
        if let Some(f) = self.ack_error {
            mock = mock.with_ack_error(f);
        }
        if let Some(d) = self.ack_delay {
            mock = mock.with_ack_delay(d);
        }
        if self.not_ready {
            mock = mock.with_not_ready();
        }

        let producer = Arc::new(mock);

        let mut kafka_config = crate::v1::test_utils::test_kafka_config();
        if let Some(n) = self.enqueue_retry_max {
            kafka_config.enqueue_retry_max = n;
        }
        if let Some(ms) = self.enqueue_poll_ms {
            kafka_config.enqueue_poll_ms = ms;
        }

        let config = Config {
            produce_timeout: self.produce_timeout,
            kafka: kafka_config,
        };

        let sink = KafkaSink::new(
            SinkName::Msk,
            Arc::clone(&producer),
            config,
            CaptureMode::Events,
            handle.clone(),
        );

        TestHarness {
            sink,
            producer,
            handle,
            ctx: {
                let mut ctx = crate::v1::test_utils::test_context();
                ctx.created_at = None;
                ctx
            },
            _monitor: monitor,
        }
    }
}

// ---------------------------------------------------------------------------
// 1. Happy path (single event)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn single_event_success() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), event.parsed_uuid);
    assert_eq!(results[0].outcome(), Outcome::Success);
    assert!(results[0].cause().is_none());
    assert!(results[0].elapsed().is_some());

    assert_eq!(h.producer.record_count(), 1);
    h.producer.with_records(|records| {
        assert_eq!(records[0].topic, "events_main");
        assert_eq!(records[0].payload, r#"{"event":"test"}"#);
        assert_eq!(records[0].key.as_deref(), Some("phc_test:evt-1"));
    });
}

// ---------------------------------------------------------------------------
// 2. Non-publishable events silently skipped
// ---------------------------------------------------------------------------

#[tokio::test]
async fn non_publishable_events_skipped() {
    let h = TestHarness::new();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2").with_publish(false);
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 2);
    assert_eq!(results[0].key(), e1.parsed_uuid);
    assert_eq!(results[1].key(), e3.parsed_uuid);
    assert_eq!(h.producer.record_count(), 2);
}

// ---------------------------------------------------------------------------
// 3. Destination::Drop skips without result
// ---------------------------------------------------------------------------

#[tokio::test]
async fn destination_drop_skips_without_result() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_destination(Destination::Drop);
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert!(results.is_empty());
    assert_eq!(h.producer.record_count(), 0);
}

// ---------------------------------------------------------------------------
// 4. Sink unavailable (producer not ready)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn sink_unavailable() {
    let h = TestHarness::builder().not_ready().build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 2);
    for r in &results {
        assert_eq!(r.outcome(), Outcome::RetriableError);
        assert_eq!(r.cause(), Some("sink_unavailable"));
    }
    assert_eq!(h.producer.record_count(), 0);
}

// ---------------------------------------------------------------------------
// 5. Send-time retriable error (queue full)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn send_error_retriable_queue_full() {
    let h = TestHarness::builder()
        .send_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::QueueFull,
        })
        .enqueue_retry_max(0)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), event.parsed_uuid);
    assert_eq!(results[0].outcome(), Outcome::RetriableError);
    assert_eq!(results[0].cause(), Some("queue_full"));
    assert_eq!(h.producer.record_count(), 0);
}

// ---------------------------------------------------------------------------
// 5b. QueueFull retry succeeds after drain
// ---------------------------------------------------------------------------

#[tokio::test]
async fn queue_full_retry_succeeds_after_drain() {
    let h = TestHarness::builder()
        .send_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::QueueFull,
        })
        .send_error_count(2)
        .enqueue_retry_max(3)
        .enqueue_poll_ms(1)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), event.parsed_uuid);
    assert_eq!(results[0].outcome(), Outcome::Success);
    assert_eq!(h.producer.record_count(), 1);
}

// ---------------------------------------------------------------------------
// 5c. QueueFull retry exhausted
// ---------------------------------------------------------------------------

#[tokio::test]
async fn queue_full_retry_exhausted() {
    let h = TestHarness::builder()
        .send_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::QueueFull,
        })
        .enqueue_retry_max(2)
        .enqueue_poll_ms(1)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), event.parsed_uuid);
    assert_eq!(results[0].outcome(), Outcome::RetriableError);
    assert_eq!(results[0].cause(), Some("queue_full"));
    assert_eq!(h.producer.record_count(), 0);
}

// ---------------------------------------------------------------------------
// 5d. QueueFull retry disabled (enqueue_retry_max = 0)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn queue_full_retry_zero_max_disables_retry() {
    let h = TestHarness::builder()
        .send_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::QueueFull,
        })
        .send_error_count(1)
        .enqueue_retry_max(0)
        .enqueue_poll_ms(1)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::RetriableError);
    assert_eq!(results[0].cause(), Some("queue_full"));
    assert_eq!(h.producer.record_count(), 0);
}

// ---------------------------------------------------------------------------
// 6. Send-time fatal error (event too big)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn send_error_fatal_event_too_big() {
    let h = TestHarness::builder()
        .send_error(|| ProduceError::EventTooBig {
            message: "too big".into(),
        })
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::FatalError);
    assert_eq!(results[0].cause(), Some("event_too_big"));
}

// ---------------------------------------------------------------------------
// 7. Ack-time retriable error (delivery cancelled)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn ack_error_retriable_delivery_cancelled() {
    let h = TestHarness::builder()
        .ack_error(|| ProduceError::DeliveryCancelled)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), event.parsed_uuid);
    assert_eq!(results[0].outcome(), Outcome::RetriableError);
    assert_eq!(results[0].cause(), Some("delivery_cancelled"));
    assert!(results[0].elapsed().is_some());
    // Enqueue succeeded before ack failed
    assert_eq!(h.producer.record_count(), 1);
}

// ---------------------------------------------------------------------------
// 8. Ack-time retriable kafka error (topic auth failed — infrastructure
//    misconfiguration, may succeed on a different pod)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn ack_error_retriable_topic_auth() {
    let h = TestHarness::builder()
        .ack_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::TopicAuthorizationFailed,
        })
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::RetriableError);
    assert_eq!(results[0].cause(), Some("topic_authorization_failed"));
    assert!(results[0].elapsed().is_some());
    assert_eq!(h.producer.record_count(), 1);
}

// ---------------------------------------------------------------------------
// 9. Produce timeout
// ---------------------------------------------------------------------------

#[tokio::test]
async fn produce_timeout_single() {
    let h = TestHarness::builder()
        .ack_delay(Duration::from_secs(60))
        .produce_timeout(Duration::from_millis(50))
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), event.parsed_uuid);
    assert_eq!(results[0].outcome(), Outcome::Timeout);
    assert_eq!(results[0].cause(), Some("timeout"));
}

#[tokio::test]
async fn produce_timeout_batch_all_pending_get_timeout() {
    let h = TestHarness::builder()
        .ack_delay(Duration::from_secs(60))
        .produce_timeout(Duration::from_millis(50))
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 3);
    for r in &results {
        assert_eq!(r.outcome(), Outcome::Timeout);
        assert_eq!(r.cause(), Some("timeout"));
    }
}

// ---------------------------------------------------------------------------
// 10. Serialization failure
// ---------------------------------------------------------------------------

#[tokio::test]
async fn serialization_failure() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_payload(Err("bad json".into()));
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), event.parsed_uuid);
    assert_eq!(results[0].outcome(), Outcome::FatalError);
    assert_eq!(results[0].cause(), Some("serialization_failed"));
    assert!(
        results[0].detail().unwrap().contains("bad json"),
        "expected detail to contain 'bad json', got: {:?}",
        results[0].detail()
    );
    assert_eq!(h.producer.record_count(), 0);
}

// ---------------------------------------------------------------------------
// 11. Mixed batch (some succeed, some fail)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn mixed_batch_success_and_serialize_error() {
    let h = TestHarness::new();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2").with_payload(Err("serialize error".into()));
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 3);

    // Serialization errors are returned inline before ack results, so evt-2
    // appears first in the results vec (pushed during Phase 1), while evt-1
    // and evt-3 are appended during Phase 2 (ack drain). Order among the
    // ack results may vary, so collect into maps.
    let by_key: HashMap<Uuid, _> = results.iter().map(|r| (r.key(), r)).collect();

    assert_eq!(by_key[&e1.parsed_uuid].outcome(), Outcome::Success);
    assert_eq!(by_key[&e2.parsed_uuid].outcome(), Outcome::FatalError);
    assert_eq!(
        by_key[&e2.parsed_uuid].cause(),
        Some("serialization_failed")
    );
    assert_eq!(by_key[&e3.parsed_uuid].outcome(), Outcome::Success);

    // Only the two successful events were enqueued
    assert_eq!(h.producer.record_count(), 2);
}

// ---------------------------------------------------------------------------
// 12. BatchSummary correctness
// ---------------------------------------------------------------------------

#[tokio::test]
async fn batch_summary_from_mixed_results() {
    let h = TestHarness::new();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2").with_payload(Err("ser error".into()));
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    let summary = BatchSummary::from_results(&results);

    assert_eq!(summary.total, 3);
    assert_eq!(summary.succeeded, 2);
    assert_eq!(summary.retriable, 0);
    assert_eq!(summary.fatal, 1);
    assert_eq!(summary.timed_out, 0);
    assert!(!summary.all_ok());
    assert_eq!(summary.errors.get("serialization_failed").copied(), Some(1));
}

// ---------------------------------------------------------------------------
// 13. Flush delegates to producer
// ---------------------------------------------------------------------------

#[tokio::test]
async fn flush_ok() {
    let h = TestHarness::new();
    assert!(h.sink.flush().await.is_ok());
}

// ---------------------------------------------------------------------------
// 14. Sink::name() returns configured name
// ---------------------------------------------------------------------------

#[test]
fn sink_name_returns_configured_name() {
    let h = TestHarness::new();
    assert_eq!(h.sink.name(), SinkName::Msk);
}

// ---------------------------------------------------------------------------
// Topic routing for non-default destinations
// ---------------------------------------------------------------------------

#[rstest]
#[case::historical(Destination::AnalyticsHistorical, "events_hist")]
#[case::overflow(Destination::Overflow, "events_overflow")]
#[case::dlq(Destination::Dlq, "events_dlq")]
#[case::custom(Destination::Custom("my_topic".into()), "my_topic")]
#[tokio::test]
async fn destination_routes_to_correct_topic(
    #[case] destination: Destination,
    #[case] expected_topic: &str,
) {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_destination(destination);
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(records[0].topic, expected_topic);
    });
}

// ---------------------------------------------------------------------------
// BatchSummary with timeout results
// ---------------------------------------------------------------------------

#[tokio::test]
async fn batch_summary_with_timeouts() {
    let h = TestHarness::builder()
        .ack_delay(Duration::from_secs(60))
        .produce_timeout(Duration::from_millis(50))
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    let summary = BatchSummary::from_results(&results);

    assert_eq!(summary.total, 2);
    assert_eq!(summary.succeeded, 0);
    assert_eq!(summary.retriable, 0);
    assert_eq!(summary.fatal, 0);
    assert_eq!(summary.timed_out, 2);
    assert!(!summary.all_ok());
    assert_eq!(summary.errors.get("timeout").copied(), Some(2));
}

// ===========================================================================
// Health heartbeat tests
//
// Production-proportional timing (100x faster, same ratios):
//   production: liveness_deadline=30s, health_poll=2s, produce_timeout=30s
//   test:       liveness_deadline=300ms, health_poll=20ms, produce_timeout=300ms
// ===========================================================================

const HEALTH_TEST_LIVENESS_DEADLINE: Duration = Duration::from_millis(300);
const HEALTH_TEST_POLL_INTERVAL: Duration = Duration::from_millis(20);
const HEALTH_TEST_PRODUCE_TIMEOUT: Duration = Duration::from_millis(300);
/// Sleep long enough for the liveness deadline to expire + poll to detect it.
const HEALTH_TEST_UNHEALTHY_SLEEP: Duration = Duration::from_millis(500);
/// Sleep just long enough for the poll to run, but well before deadline expiry.
const HEALTH_TEST_HEALTHY_SLEEP: Duration = Duration::from_millis(50);

// ---------------------------------------------------------------------------
// Health: no heartbeat when every event fails (parameterized by failure mode)
// ---------------------------------------------------------------------------

enum FailureMode {
    Timeout,
    SendError,
    AckError,
    SerializationError,
}

fn health_harness(mode: &FailureMode) -> TestHarness {
    let mut b = TestHarness::builder()
        .with_liveness(HEALTH_TEST_LIVENESS_DEADLINE, HEALTH_TEST_POLL_INTERVAL)
        .produce_timeout(HEALTH_TEST_PRODUCE_TIMEOUT);
    match mode {
        FailureMode::Timeout => {
            b = b.ack_delay(Duration::from_secs(10));
        }
        FailureMode::SendError => {
            b = b
                .send_error(|| ProduceError::Kafka {
                    code: RDKafkaErrorCode::QueueFull,
                })
                .enqueue_retry_max(0);
        }
        FailureMode::AckError => {
            b = b.ack_error(|| ProduceError::DeliveryCancelled);
        }
        FailureMode::SerializationError => {}
    }
    b.build()
}

fn health_events(mode: &FailureMode) -> Vec<FakeEvent> {
    let make = |id: &str| match mode {
        FailureMode::SerializationError => FakeEvent::ok(id).with_payload(Err("bad".into())),
        _ => FakeEvent::ok(id),
    };
    vec![make("evt-1"), make("evt-2"), make("evt-3")]
}

fn expected_outcome(mode: &FailureMode) -> Outcome {
    match mode {
        FailureMode::Timeout => Outcome::Timeout,
        FailureMode::SendError => Outcome::RetriableError,
        FailureMode::AckError => Outcome::RetriableError,
        FailureMode::SerializationError => Outcome::FatalError,
    }
}

#[rstest]
#[case::timeout(FailureMode::Timeout)]
#[case::send_error(FailureMode::SendError)]
#[case::ack_error(FailureMode::AckError)]
#[case::serialization_error(FailureMode::SerializationError)]
#[tokio::test]
async fn health_not_refreshed_on_full_failure(#[case] mode: FailureMode) {
    let h = health_harness(&mode);
    let owned_events = health_events(&mode);
    let refs: Vec<&FakeEvent> = owned_events.iter().collect();
    let events: Vec<&(dyn Event + Send + Sync)> = vec![refs[0], refs[1], refs[2]];
    let expected = expected_outcome(&mode);

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    for r in &results {
        assert_eq!(r.outcome(), expected);
    }

    tokio::time::sleep(HEALTH_TEST_UNHEALTHY_SLEEP).await;
    assert!(
        !h.handle.is_healthy(),
        "handle should be unhealthy after full {expected:?} batch"
    );
}

// ---------------------------------------------------------------------------
// Health: all events succeed -> heartbeat refreshed -> is_healthy stays true
// ---------------------------------------------------------------------------

#[tokio::test]
async fn health_refreshed_on_full_success() {
    let h = TestHarness::builder()
        .with_liveness(HEALTH_TEST_LIVENESS_DEADLINE, HEALTH_TEST_POLL_INTERVAL)
        .produce_timeout(HEALTH_TEST_PRODUCE_TIMEOUT)
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    for r in &results {
        assert_eq!(r.outcome(), Outcome::Success);
    }

    tokio::time::sleep(HEALTH_TEST_HEALTHY_SLEEP).await;
    assert!(
        h.handle.is_healthy(),
        "handle should stay healthy after successful batch"
    );
}

// ---------------------------------------------------------------------------
// Health: mixed batch (some succeed, some fail) -> heartbeat refreshed
// ---------------------------------------------------------------------------

#[tokio::test]
async fn health_refreshed_on_partial_success() {
    let h = TestHarness::builder()
        .with_liveness(HEALTH_TEST_LIVENESS_DEADLINE, HEALTH_TEST_POLL_INTERVAL)
        .produce_timeout(HEALTH_TEST_PRODUCE_TIMEOUT)
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2").with_payload(Err("bad".into()));
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    let summary = BatchSummary::from_results(&results);
    assert!(summary.succeeded > 0);
    assert!(summary.fatal > 0);

    tokio::time::sleep(HEALTH_TEST_HEALTHY_SLEEP).await;
    assert!(
        h.handle.is_healthy(),
        "handle should stay healthy when at least one event succeeded"
    );
}

// ---------------------------------------------------------------------------
// Partition key: None vs Some
// ---------------------------------------------------------------------------

#[tokio::test]
async fn none_partition_key_propagates_as_none() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_partition_key(None);
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(
            records[0].key, None,
            "None partition key must propagate as None"
        );
    });
}

#[tokio::test]
async fn some_partition_key_propagates_as_some() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_partition_key(Some("phc_test:user-1"));
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(records[0].key.as_deref(), Some("phc_test:user-1"));
    });
}

// ===========================================================================
// Realistic WrappedEvent round-trip tests
//
// These use production-shaped fixtures from test_utils and verify the
// MockProducer payload deserializes as CapturedEvent + RawEvent.
// ===========================================================================

#[tokio::test]
async fn realistic_single_pageview_round_trip() {
    let h = TestHarness::new();
    let wrapped = test_utils::realistic_pageview("user-42");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&wrapped];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), wrapped.uuid);
    assert_eq!(results[0].outcome(), Outcome::Success);

    h.producer.with_records(|records| {
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].topic, "events_main");

        let captured: CapturedEvent =
            serde_json::from_str(&records[0].payload).expect("must deserialize as CapturedEvent");
        assert_eq!(captured.uuid, wrapped.uuid);
        assert_eq!(captured.distinct_id, "user-42");
        assert_eq!(captured.event, "$pageview");

        let data: RawEvent =
            serde_json::from_str(&captured.data).expect("data must deserialize as RawEvent");
        assert_eq!(data.event, "$pageview");
        assert_eq!(data.properties["$browser"], "Chrome");
        assert_eq!(
            data.properties["$session_id"],
            "01jq9abc-def0-1234-5678-9abcdef01234"
        );
        assert_eq!(data.properties["$process_person_profile"], true);
    });
}

#[tokio::test]
async fn realistic_batch_round_trip() {
    let h = TestHarness::new();
    let batch = test_utils::realistic_batch();
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&batch[0], &batch[1], &batch[2]];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 3);
    for r in &results {
        assert_eq!(r.outcome(), Outcome::Success);
    }

    h.producer.with_records(|records| {
        assert_eq!(records.len(), 3);
        for record in records {
            let captured: CapturedEvent =
                serde_json::from_str(&record.payload).expect("must deserialize as CapturedEvent");
            let _data: RawEvent =
                serde_json::from_str(&captured.data).expect("data must deserialize as RawEvent");
        }

        let names: Vec<&str> = records
            .iter()
            .map(|r| {
                let c: CapturedEvent = serde_json::from_str(&r.payload).unwrap();
                match c.event.as_str() {
                    "$pageview" => "$pageview",
                    "$identify" => "$identify",
                    _ => "custom",
                }
            })
            .collect();
        assert_eq!(names, vec!["$pageview", "$identify", "custom"]);
    });
}

#[tokio::test]
async fn realistic_event_with_destination_mutation() {
    let h = TestHarness::new();
    let wrapped = test_utils::realistic_pageview("user-42")
        .with_destination(Destination::AnalyticsHistorical);
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&wrapped];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(records[0].topic, "events_hist");
    });
}

#[tokio::test]
async fn realistic_dropped_event_not_published() {
    use crate::v1::analytics::types::EventResult;

    let h = TestHarness::new();
    let wrapped = test_utils::realistic_pageview("user-42")
        .with_result(EventResult::Drop, Some("rate_limited"));
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&wrapped];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert!(results.is_empty());
    assert_eq!(h.producer.record_count(), 0);
}

// ===========================================================================
// Coverage gap fills (C5)
// ===========================================================================

// ---------------------------------------------------------------------------
// Mixed send error + ack error in one batch: first event fails at send,
// remaining events fail at ack. Verifies both error types are reported.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn mixed_send_error_and_ack_error_in_batch() {
    let h = TestHarness::builder()
        .send_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::QueueFull,
        })
        .send_error_count(1)
        .enqueue_retry_max(0)
        .ack_error(|| ProduceError::DeliveryCancelled)
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 3);
    let by_key: HashMap<Uuid, _> = results.iter().map(|r| (r.key(), r)).collect();

    // evt-1: send error (queue_full)
    assert_eq!(by_key[&e1.parsed_uuid].outcome(), Outcome::RetriableError);
    assert_eq!(by_key[&e1.parsed_uuid].cause(), Some("queue_full"));

    // evt-2 and evt-3: enqueued successfully, but ack error (delivery_cancelled)
    assert_eq!(by_key[&e2.parsed_uuid].outcome(), Outcome::RetriableError);
    assert_eq!(by_key[&e2.parsed_uuid].cause(), Some("delivery_cancelled"));
    assert_eq!(by_key[&e3.parsed_uuid].outcome(), Outcome::RetriableError);
    assert_eq!(by_key[&e3.parsed_uuid].cause(), Some("delivery_cancelled"));

    // Only evt-2 and evt-3 were enqueued (evt-1 failed at send)
    assert_eq!(h.producer.record_count(), 2);
}

// ---------------------------------------------------------------------------
// Partial timeout: first event fails at send (immediate), remaining time out.
// Verifies mixed Outcome::RetriableError and Outcome::Timeout in one batch.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn partial_timeout_with_send_error() {
    let h = TestHarness::builder()
        .send_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::QueueFull,
        })
        .send_error_count(1)
        .enqueue_retry_max(0)
        .ack_delay(Duration::from_secs(60))
        .produce_timeout(Duration::from_millis(50))
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 2);
    let by_key: HashMap<Uuid, _> = results.iter().map(|r| (r.key(), r)).collect();

    // evt-1: immediate send error
    assert_eq!(by_key[&e1.parsed_uuid].outcome(), Outcome::RetriableError);
    assert_eq!(by_key[&e1.parsed_uuid].cause(), Some("queue_full"));

    // evt-2: enqueued successfully, but ack times out
    assert_eq!(by_key[&e2.parsed_uuid].outcome(), Outcome::Timeout);
    assert_eq!(by_key[&e2.parsed_uuid].cause(), Some("timeout"));
}

// ---------------------------------------------------------------------------
// Partial timeout: serialization failure + timeout in one batch.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn partial_timeout_with_serialization_error() {
    let h = TestHarness::builder()
        .ack_delay(Duration::from_secs(60))
        .produce_timeout(Duration::from_millis(50))
        .build();
    let e1 = FakeEvent::ok("evt-1").with_payload(Err("bad".into()));
    let e2 = FakeEvent::ok("evt-2");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 2);
    let by_key: HashMap<Uuid, _> = results.iter().map(|r| (r.key(), r)).collect();

    // evt-1: serialization failure (immediate, fatal)
    assert_eq!(by_key[&e1.parsed_uuid].outcome(), Outcome::FatalError);
    assert_eq!(
        by_key[&e1.parsed_uuid].cause(),
        Some("serialization_failed")
    );

    // evt-2: enqueued, times out
    assert_eq!(by_key[&e2.parsed_uuid].outcome(), Outcome::Timeout);
    assert_eq!(by_key[&e2.parsed_uuid].cause(), Some("timeout"));
}
