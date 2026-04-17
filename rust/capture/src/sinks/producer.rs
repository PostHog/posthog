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
pub struct DeliveryAckFuture {
    inner: DeliveryFuture,
    started: Instant,
    topic: String,
}

impl Future for DeliveryAckFuture {
    type Output = Result<(), CaptureError>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.inner).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(result) => {
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

/// Mock Kafka producer for testing - captures all sent records
#[derive(Clone, Default)]
pub struct MockKafkaProducer {
    records: std::sync::Arc<std::sync::Mutex<Vec<ProduceRecord>>>,
}

impl MockKafkaProducer {
    pub fn new() -> Self {
        Self {
            records: std::sync::Arc::new(std::sync::Mutex::new(Vec::new())),
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
        self.records.lock().unwrap().push(record);
        Ok(std::future::ready(Ok(())))
    }

    fn flush(&self) -> Result<(), KafkaError> {
        Ok(())
    }
}
