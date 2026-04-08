use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use rdkafka::error::RDKafkaErrorCode;

use crate::config::CaptureMode;
use crate::v1::context::Context;
use crate::v1::sinks::event::Event;
use crate::v1::sinks::sink::Sink;
use crate::v1::sinks::types::{BatchSummary, Outcome};
use crate::v1::sinks::{Config, Destination, SinkName};

use super::mock::MockProducer;
use super::producer::ProduceError;
use super::sink::KafkaSink;

// ---------------------------------------------------------------------------
// FakeEvent
// ---------------------------------------------------------------------------

struct FakeEvent {
    uuid: String,
    publish: bool,
    destination: Destination,
    partition_key: String,
    payload: Result<String, String>,
    event_headers: Vec<(String, String)>,
}

impl FakeEvent {
    fn ok(uuid: &str) -> Self {
        Self {
            uuid: uuid.to_string(),
            publish: true,
            destination: Destination::AnalyticsMain,
            partition_key: format!("phc_test:{uuid}"),
            payload: Ok(r#"{"event":"test"}"#.to_string()),
            event_headers: vec![],
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
}

impl Event for FakeEvent {
    fn uuid_key(&self) -> &str {
        &self.uuid
    }

    fn should_publish(&self) -> bool {
        self.publish
    }

    fn destination(&self) -> &Destination {
        &self.destination
    }

    fn headers(&self) -> Vec<(String, String)> {
        self.event_headers.clone()
    }

    fn write_partition_key(&self, _ctx: &Context, buf: &mut String) {
        buf.push_str(&self.partition_key);
    }

    fn serialize_into(&self, _ctx: &Context, buf: &mut String) -> Result<(), String> {
        match &self.payload {
            Ok(p) => {
                buf.push_str(p);
                Ok(())
            }
            Err(e) => Err(e.clone()),
        }
    }
}

// ---------------------------------------------------------------------------
// TestHarness
// ---------------------------------------------------------------------------

fn test_kafka_config() -> super::config::Config {
    let env: HashMap<String, String> = [
        ("HOSTS", "localhost:9092"),
        ("TOPIC_MAIN", "events_main"),
        ("TOPIC_HISTORICAL", "events_hist"),
        ("TOPIC_OVERFLOW", "events_overflow"),
        ("TOPIC_DLQ", "events_dlq"),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect();
    envconfig::Envconfig::init_from_hashmap(&env).unwrap()
}

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

        let mut kafka_config = test_kafka_config();
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
    assert_eq!(results[0].key(), "evt-1");
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
    assert_eq!(results[0].key(), "evt-1");
    assert_eq!(results[1].key(), "evt-3");
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
            retriable: true,
        })
        .enqueue_retry_max(0)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), "evt-1");
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
            retriable: true,
        })
        .send_error_count(2)
        .enqueue_retry_max(3)
        .enqueue_poll_ms(1)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), "evt-1");
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
            retriable: true,
        })
        .enqueue_retry_max(2)
        .enqueue_poll_ms(1)
        .build();
    let event = FakeEvent::ok("evt-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), "evt-1");
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
            retriable: true,
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
    assert_eq!(results[0].key(), "evt-1");
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
            retriable: true,
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
    assert_eq!(results[0].key(), "evt-1");
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
    assert_eq!(results[0].key(), "evt-1");
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
    let by_key: HashMap<&str, _> = results.iter().map(|r| (r.key(), r)).collect();

    assert_eq!(by_key["evt-1"].outcome(), Outcome::Success);
    assert_eq!(by_key["evt-2"].outcome(), Outcome::FatalError);
    assert_eq!(by_key["evt-2"].cause(), Some("serialization_failed"));
    assert_eq!(by_key["evt-3"].outcome(), Outcome::Success);

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

#[tokio::test]
async fn destination_historical_routes_to_correct_topic() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_destination(Destination::AnalyticsHistorical);
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(records[0].topic, "events_hist");
    });
}

#[tokio::test]
async fn destination_overflow_routes_to_correct_topic() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_destination(Destination::Overflow);
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(records[0].topic, "events_overflow");
    });
}

#[tokio::test]
async fn destination_dlq_routes_to_correct_topic() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_destination(Destination::Dlq);
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(records[0].topic, "events_dlq");
    });
}

// ---------------------------------------------------------------------------
// Destination::Custom topic routing
// ---------------------------------------------------------------------------

#[tokio::test]
async fn destination_custom_routes_to_custom_topic() {
    let h = TestHarness::new();
    let event = FakeEvent::ok("evt-1").with_destination(Destination::Custom("my_topic".into()));
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

    let results = h.sink.publish_batch(&h.ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].outcome(), Outcome::Success);
    h.producer.with_records(|records| {
        assert_eq!(records[0].topic, "my_topic");
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
// Health: all events timeout -> no heartbeat -> is_healthy becomes false
// ---------------------------------------------------------------------------

#[tokio::test]
async fn health_not_refreshed_on_full_timeout() {
    let h = TestHarness::builder()
        .with_liveness(HEALTH_TEST_LIVENESS_DEADLINE, HEALTH_TEST_POLL_INTERVAL)
        .ack_delay(Duration::from_secs(10))
        .produce_timeout(HEALTH_TEST_PRODUCE_TIMEOUT)
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    for r in &results {
        assert_eq!(r.outcome(), Outcome::Timeout);
    }

    tokio::time::sleep(HEALTH_TEST_UNHEALTHY_SLEEP).await;
    assert!(
        !h.handle.is_healthy(),
        "handle should be unhealthy after full timeout batch"
    );
}

// ---------------------------------------------------------------------------
// Health: all events fail at send (queue full) -> no heartbeat
// ---------------------------------------------------------------------------

#[tokio::test]
async fn health_not_refreshed_on_full_send_error() {
    let h = TestHarness::builder()
        .with_liveness(HEALTH_TEST_LIVENESS_DEADLINE, HEALTH_TEST_POLL_INTERVAL)
        .produce_timeout(HEALTH_TEST_PRODUCE_TIMEOUT)
        .send_error(|| ProduceError::Kafka {
            code: RDKafkaErrorCode::QueueFull,
            retriable: true,
        })
        .enqueue_retry_max(0)
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    for r in &results {
        assert_eq!(r.outcome(), Outcome::RetriableError);
    }

    tokio::time::sleep(HEALTH_TEST_UNHEALTHY_SLEEP).await;
    assert!(
        !h.handle.is_healthy(),
        "handle should be unhealthy after full send error batch"
    );
}

// ---------------------------------------------------------------------------
// Health: all events fail at ack (delivery cancelled) -> no heartbeat
// ---------------------------------------------------------------------------

#[tokio::test]
async fn health_not_refreshed_on_full_ack_error() {
    let h = TestHarness::builder()
        .with_liveness(HEALTH_TEST_LIVENESS_DEADLINE, HEALTH_TEST_POLL_INTERVAL)
        .produce_timeout(HEALTH_TEST_PRODUCE_TIMEOUT)
        .ack_error(|| ProduceError::DeliveryCancelled)
        .build();
    let e1 = FakeEvent::ok("evt-1");
    let e2 = FakeEvent::ok("evt-2");
    let e3 = FakeEvent::ok("evt-3");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    for r in &results {
        assert_eq!(r.outcome(), Outcome::RetriableError);
    }

    tokio::time::sleep(HEALTH_TEST_UNHEALTHY_SLEEP).await;
    assert!(
        !h.handle.is_healthy(),
        "handle should be unhealthy after full ack error batch"
    );
}

// ---------------------------------------------------------------------------
// Health: all events fail serialization -> no heartbeat
// ---------------------------------------------------------------------------

#[tokio::test]
async fn health_not_refreshed_on_full_serialization_error() {
    let h = TestHarness::builder()
        .with_liveness(HEALTH_TEST_LIVENESS_DEADLINE, HEALTH_TEST_POLL_INTERVAL)
        .produce_timeout(HEALTH_TEST_PRODUCE_TIMEOUT)
        .build();
    let e1 = FakeEvent::ok("evt-1").with_payload(Err("bad".into()));
    let e2 = FakeEvent::ok("evt-2").with_payload(Err("bad".into()));
    let e3 = FakeEvent::ok("evt-3").with_payload(Err("bad".into()));
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&e1, &e2, &e3];

    let results = h.sink.publish_batch(&h.ctx, &events).await;
    for r in &results {
        assert_eq!(r.outcome(), Outcome::FatalError);
    }

    tokio::time::sleep(HEALTH_TEST_UNHEALTHY_SLEEP).await;
    assert!(
        !h.handle.is_healthy(),
        "handle should be unhealthy after full serialization error batch"
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
