use common_types::CapturedEventHeaders;
use metrics::{counter, histogram};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};
use tracing::error;

use crate::api::CaptureError;
use crate::prometheus::report_dropped_events;

/// A record to be produced to Kafka
#[derive(Debug, Clone)]
pub struct ProduceRecord {
    pub topic: String,
    pub key: Option<String>,
    pub payload: String,
    pub headers: CapturedEventHeaders,
}

/// Abstraction over Kafka producer for testability
pub trait KafkaProducer: Send + Sync {
    /// The future type returned by send() that resolves to the delivery acknowledgment
    type AckFuture: Future<Output = Result<(), CaptureError>> + Send;

    /// Send a record to Kafka. Returns either an immediate error or a future to await for ack.
    fn send(&self, record: ProduceRecord) -> Result<Self::AckFuture, CaptureError>;

    /// Flush pending messages
    fn flush(&self) -> Result<(), KafkaError>;
}

/// Future that wraps rdkafka's DeliveryFuture and converts the result to CaptureError.
/// Also records the full app-side ack duration (from `send_result()` returning to
/// broker ack / error / cancellation) as a histogram so we can see the true long
/// tail that the per-broker rdkafka rtt gauge smears away.
///
/// `recorded` flips to true once `poll` observes `Poll::Ready` so the Drop impl
/// can emit a `capture_kafka_produce_ack_duration_ms{outcome="dropped"}` sample
/// when the future is cancelled mid-flight (e.g. `JoinSet::abort_all()` fires
/// after a peer ack fails). Without this, the slowest in-flight acks get
/// censored out of the histogram precisely when the tail matters most.
pub struct DeliveryAckFuture {
    inner: DeliveryFuture,
    started: Instant,
    topic: String,
    recorded: bool,
}

impl Future for DeliveryAckFuture {
    type Output = Result<(), CaptureError>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.inner).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(result) => {
                // Mark before recording so a panic inside the match still disables Drop.
                self.recorded = true;
                let elapsed_ms = self.started.elapsed().as_secs_f64() * 1000.0;
                let (outcome, mapped) = match result {
                    Err(_) => {
                        // Cancelled due to timeout while retrying
                        metrics::counter!("capture_kafka_produce_errors_total").increment(1);
                        error!("failed to produce to Kafka before write timeout");
                        ("cancelled", Err(CaptureError::RetryableSinkError))
                    }
                    Ok(Err((
                        KafkaError::MessageProduction(RDKafkaErrorCode::MessageSizeTooLarge),
                        _,
                    ))) => {
                        report_dropped_events("kafka_message_size", 1);
                        (
                            "too_large",
                            Err(CaptureError::EventTooBig(
                                "Event rejected by kafka broker during ack".to_string(),
                            )),
                        )
                    }
                    Ok(Err((err, _))) => {
                        metrics::counter!("capture_kafka_produce_errors_total").increment(1);
                        error!("failed to produce to Kafka: {err:#}");
                        ("broker_err", Err(CaptureError::RetryableSinkError))
                    }
                    Ok(Ok(_)) => {
                        metrics::counter!("capture_events_ingested_total").increment(1);
                        ("ok", Ok(()))
                    }
                };
                histogram!(
                    "capture_kafka_produce_ack_duration_ms",
                    "outcome" => outcome,
                    "topic" => self.topic.clone()
                )
                .record(elapsed_ms);
                Poll::Ready(mapped)
            }
        }
    }
}

impl Drop for DeliveryAckFuture {
    fn drop(&mut self) {
        // Only fires when the future is dropped before poll saw Ready
        // (e.g. JoinSet::abort_all on batch fail-fast). Records the elapsed
        // wait so tail-latency dashboards don't lose the slowest samples.
        if !self.recorded {
            let elapsed_ms = self.started.elapsed().as_secs_f64() * 1000.0;
            histogram!(
                "capture_kafka_produce_ack_duration_ms",
                "outcome" => "dropped",
                "topic" => self.topic.clone()
            )
            .record(elapsed_ms);
        }
    }
}

/// Real Kafka producer implementation using rdkafka
pub struct RdKafkaProducer<C: rdkafka::ClientContext + Send + Sync + 'static> {
    producer: FutureProducer<C>,
}

impl<C: rdkafka::ClientContext + Send + Sync + 'static> RdKafkaProducer<C> {
    pub fn new(producer: FutureProducer<C>) -> Self {
        Self { producer }
    }
}

impl<C: rdkafka::ClientContext + Send + Sync + 'static> KafkaProducer for RdKafkaProducer<C> {
    type AckFuture = DeliveryAckFuture;

    fn send(&self, record: ProduceRecord) -> Result<Self::AckFuture, CaptureError> {
        let headers: rdkafka::message::OwnedHeaders = record.headers.into();
        let topic = record.topic.clone();

        match self.producer.send_result(FutureRecord {
            topic: &record.topic,
            payload: Some(&record.payload),
            partition: None,
            key: record.key.as_deref(),
            timestamp: None,
            headers: Some(headers),
        }) {
            Ok(delivery_future) => Ok(DeliveryAckFuture {
                inner: delivery_future,
                started: Instant::now(),
                topic,
                recorded: false,
            }),
            Err((e, _)) => match e.rdkafka_error_code() {
                Some(RDKafkaErrorCode::MessageSizeTooLarge) => {
                    report_dropped_events("kafka_message_size", 1);
                    Err(CaptureError::EventTooBig(
                        "Event rejected by kafka during send".to_string(),
                    ))
                }
                _ => {
                    // Use error counter, not dropped counter - this is retryable
                    counter!("capture_kafka_produce_errors_total").increment(1);
                    error!("failed to produce event: {e:#}");
                    Err(CaptureError::RetryableSinkError)
                }
            },
        }
    }

    fn flush(&self) -> Result<(), KafkaError> {
        self.producer.flush(Duration::new(30, 0))
    }
}

/// Mock Kafka producer for testing - captures all sent records.
///
/// Optionally fails on a specific send index (0-based) by returning
/// `CaptureError::RetryableSinkError`. Records before the failing index are
/// still captured; the failing record is not. Used by send-batch tests that
/// need to simulate a mid-batch enqueue failure.
#[derive(Clone, Default)]
pub struct MockKafkaProducer {
    records: std::sync::Arc<std::sync::Mutex<Vec<ProduceRecord>>>,
    fail_at_index: Option<usize>,
    call_count: std::sync::Arc<std::sync::atomic::AtomicUsize>,
}

impl MockKafkaProducer {
    pub fn new() -> Self {
        Self::default()
    }

    /// Build a producer that returns `RetryableSinkError` on the `idx`-th
    /// `send()` call (0-based). All other calls succeed and capture the record.
    pub fn new_failing_at(idx: usize) -> Self {
        Self {
            fail_at_index: Some(idx),
            ..Self::default()
        }
    }

    /// Get all records that were sent
    pub fn get_records(&self) -> Vec<ProduceRecord> {
        self.records.lock().unwrap().clone()
    }

    /// Clear all captured records
    pub fn clear(&self) {
        self.records.lock().unwrap().clear();
    }
}

impl KafkaProducer for MockKafkaProducer {
    type AckFuture = std::future::Ready<Result<(), CaptureError>>;

    fn send(&self, record: ProduceRecord) -> Result<Self::AckFuture, CaptureError> {
        let idx = self
            .call_count
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        if self.fail_at_index == Some(idx) {
            return Err(CaptureError::RetryableSinkError);
        }
        self.records.lock().unwrap().push(record);
        Ok(std::future::ready(Ok(())))
    }

    fn flush(&self) -> Result<(), KafkaError> {
        Ok(())
    }
}
