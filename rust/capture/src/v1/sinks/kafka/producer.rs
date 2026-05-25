use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Duration;

use metrics::counter;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};
use rdkafka::ClientConfig;
use tracing::{error, info};

use super::types::error_code_tag;
use crate::v1::sinks::kafka::config::Config as KafkaConfig;
use crate::v1::sinks::kafka::context::KafkaContext;
use crate::v1::sinks::SinkName;

// ---------------------------------------------------------------------------
// ProduceError
// ---------------------------------------------------------------------------

#[derive(Debug, thiserror::Error)]
pub enum ProduceError {
    #[error("event too big: {message}")]
    EventTooBig { message: String },

    #[error("kafka error: {code}")]
    Kafka { code: RDKafkaErrorCode },

    #[error("delivery cancelled (timeout in librdkafka)")]
    DeliveryCancelled,
}

impl ProduceError {
    pub fn is_retriable(&self) -> bool {
        match self {
            Self::EventTooBig { .. } => false,
            Self::Kafka { code } => !is_fatal_kafka_error(*code),
            Self::DeliveryCancelled => true,
        }
    }

    pub fn error_code(&self) -> Option<RDKafkaErrorCode> {
        match self {
            Self::Kafka { code } => Some(*code),
            _ => None,
        }
    }

    pub fn is_queue_full(&self) -> bool {
        matches!(
            self,
            Self::Kafka {
                code: RDKafkaErrorCode::QueueFull,
            }
        )
    }

    /// Stable, low-cardinality tag for metrics and log aggregation.
    pub fn as_tag(&self) -> &'static str {
        match self {
            Self::EventTooBig { .. } => "event_too_big",
            Self::DeliveryCancelled => "delivery_cancelled",
            Self::Kafka { code } => error_code_tag(*code),
        }
    }
}

// ---------------------------------------------------------------------------
// ProduceRecord
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub struct ProduceRecord<'a> {
    pub topic: &'a str,
    pub key: Option<&'a str>,
    pub payload: &'a str,
    pub headers: OwnedHeaders,
}

// ---------------------------------------------------------------------------
// SendHandle
// ---------------------------------------------------------------------------

pub struct SendHandle {
    inner: DeliveryFuture,
}

impl Future for SendHandle {
    type Output = Result<(), ProduceError>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.inner).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(Err(_)) => Poll::Ready(Err(ProduceError::DeliveryCancelled)),
            Poll::Ready(Ok(Err((e, _)))) => Poll::Ready(Err(produce_error_from_kafka(e))),
            Poll::Ready(Ok(Ok(_))) => Poll::Ready(Ok(())),
        }
    }
}

// ---------------------------------------------------------------------------
// KafkaProducer
// ---------------------------------------------------------------------------

pub struct KafkaProducer {
    inner: FutureProducer<KafkaContext>,
    handle: lifecycle::Handle,
    sink: SinkName,
}

impl KafkaProducer {
    pub fn new(
        sink: SinkName,
        config: &KafkaConfig,
        handle: lifecycle::Handle,
        capture_mode: &'static str,
    ) -> anyhow::Result<Self> {
        let ctx = KafkaContext::new(handle.clone(), sink, capture_mode);

        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.hosts)
            .set(
                "statistics.interval.ms",
                config.statistics_interval_ms.to_string(),
            )
            .set("linger.ms", config.linger_ms.to_string())
            .set("message.timeout.ms", config.message_timeout_ms.to_string())
            .set("message.max.bytes", config.message_max_bytes.to_string())
            .set("compression.codec", &config.compression_codec)
            .set(
                "queue.buffering.max.kbytes",
                (config.queue_mib * 1024).to_string(),
            )
            .set("acks", &config.acks)
            .set("batch.num.messages", config.batch_num_messages.to_string())
            .set("batch.size", config.batch_size.to_string())
            .set("enable.idempotence", config.enable_idempotence.to_string())
            .set(
                "topic.metadata.refresh.interval.ms",
                config.metadata_refresh_interval_ms.to_string(),
            )
            .set(
                "metadata.max.age.ms",
                config.metadata_max_age_ms.to_string(),
            )
            .set("socket.timeout.ms", config.socket_timeout_ms.to_string())
            .set("partitioner", &config.partitioner)
            .set("message.send.max.retries", config.max_retries.to_string())
            .set(
                "max.in.flight.requests.per.connection",
                config.max_in_flight_requests.to_string(),
            )
            .set(
                "sticky.partitioning.linger.ms",
                config.sticky_partitioning_linger_ms.to_string(),
            )
            .set(
                "log.connection.close",
                config.log_connection_close.to_string(),
            )
            .set(
                "queue.buffering.max.messages",
                config.queue_buffering_max_messages.to_string(),
            )
            .set(
                "retry.backoff.max.ms",
                config.retry_backoff_max_ms.to_string(),
            )
            .set(
                "socket.send.buffer.bytes",
                config.socket_send_buffer_bytes.to_string(),
            )
            .set(
                "socket.receive.buffer.bytes",
                config.socket_receive_buffer_bytes.to_string(),
            );

        if !config.broker_address_family.is_empty() {
            client_config.set("broker.address.family", &config.broker_address_family);
        }
        if !config.client_id.is_empty() {
            client_config.set("client.id", &config.client_id);
        }
        if config.tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }

        let producer: FutureProducer<KafkaContext> = client_config.create_with_context(ctx)?;

        match producer
            .client()
            .fetch_metadata(None, Duration::from_secs(10))
        {
            Ok(_) => {
                handle.report_healthy();
                info!("v1 kafka producer [{}] connected", sink.as_str());
            }
            Err(e) => {
                error!(
                    "v1 kafka producer [{}]: initial metadata fetch failed: {e}",
                    sink.as_str()
                );
                counter!(
                    "capture_v1_kafka_client_errors_total",
                    "cluster" => sink.as_str(),
                    "mode" => capture_mode,
                    "error" => "metadata_fetch_failed",
                )
                .increment(1);
            }
        }

        Ok(Self {
            inner: producer,
            handle,
            sink,
        })
    }
}

impl super::KafkaProducerTrait for KafkaProducer {
    type Ack = SendHandle;

    fn send<'a>(
        &self,
        record: ProduceRecord<'a>,
    ) -> Result<SendHandle, (ProduceError, ProduceRecord<'a>)> {
        match self.inner.send_result(FutureRecord {
            topic: record.topic,
            payload: Some(record.payload),
            partition: None,
            key: record.key,
            timestamp: None,
            headers: Some(record.headers),
        }) {
            Ok(future) => Ok(SendHandle { inner: future }),
            Err((e, returned)) => {
                let returned_record = ProduceRecord {
                    topic: returned.topic,
                    key: returned.key,
                    payload: returned.payload.unwrap_or(""),
                    headers: returned.headers.unwrap_or_else(OwnedHeaders::new),
                };
                Err((produce_error_from_kafka(e), returned_record))
            }
        }
    }

    fn flush(&self, timeout: Duration) -> Result<(), KafkaError> {
        self.inner.flush(rdkafka::util::Timeout::After(timeout))
    }

    fn is_ready(&self) -> bool {
        self.handle.is_healthy()
    }

    fn sink_name(&self) -> SinkName {
        self.sink
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn is_fatal_kafka_error(code: RDKafkaErrorCode) -> bool {
    matches!(
        code,
        RDKafkaErrorCode::MessageSizeTooLarge
            | RDKafkaErrorCode::InvalidMessageSize
            | RDKafkaErrorCode::InvalidMessage
    )
}

pub(crate) fn produce_error_from_kafka(e: KafkaError) -> ProduceError {
    let code = e.rdkafka_error_code().unwrap_or(RDKafkaErrorCode::Unknown);
    if code == RDKafkaErrorCode::MessageSizeTooLarge {
        ProduceError::EventTooBig {
            message: e.to_string(),
        }
    } else {
        ProduceError::Kafka { code }
    }
}
