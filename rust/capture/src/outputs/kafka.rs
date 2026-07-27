//! Kafka outputs: one cluster's produce surface.
//!
//! A [`KafkaOutputs`] handles every destination its [`TopicTable`] maps: it
//! preps events (lane resolution, serialization, headers), realizes each
//! abstract [`Address`](crate::pipeline::Address) as a concrete topic in its
//! cluster's namespace, and hands realized records to the transport sink.
//! The sink below it is a pure producer wrapper; the map from destination to
//! topic name lives here, which is what makes sibling implementations
//! possible — a kafka+S3 fallback composes this with an S3 leaf, and a
//! future managed-kafka outputs swaps the static table for dynamic
//! broker/topic/partition assignment without touching the transport.

use std::sync::Arc;

use async_trait::async_trait;

use crate::api::CaptureError;
use crate::config::KafkaConfig;
use crate::outputs::topics::TopicTable;
use crate::outputs::{prepare_batch, AddressedPayload, Outputs, PrepSpec};
use crate::sinks::kafka::{KafkaContext, KafkaSink, KafkaSinkBase, RealizedRecord};
use crate::sinks::producer::{KafkaProducer, ProduceRecord, RdKafkaProducer};
use crate::sinks::sink::fold_results;
use crate::v0_request::ProcessedEvent;

/// One Kafka cluster's outputs: prep spec + topic table + transport sink.
/// Generic over the producer so tests drive the exact production path
/// against a mock.
pub struct KafkaOutputsBase<P: KafkaProducer> {
    prep: PrepSpec,
    topics: Arc<TopicTable>,
    sink: KafkaSinkBase<P>,
}

/// The production Kafka outputs over rdkafka's FutureProducer.
pub type KafkaOutputs = KafkaOutputsBase<RdKafkaProducer<KafkaContext>>;

impl KafkaOutputs {
    /// Connect a producer and build the outputs for one cluster.
    pub async fn new(
        config: KafkaConfig,
        topics: TopicTable,
        liveness: Option<lifecycle::Handle>,
    ) -> anyhow::Result<KafkaOutputs> {
        let prep = PrepSpec::from(&config);
        let sink = KafkaSink::new(config, liveness).await?;
        Ok(Self::from_parts(prep, topics, sink))
    }

    /// Outputs over an already-connected sink — how multiple per-pipeline
    /// outputs share one cluster connection while naming topics
    /// independently.
    pub fn from_parts(prep: PrepSpec, topics: TopicTable, sink: KafkaSink) -> Self {
        Self {
            prep,
            topics: Arc::new(topics),
            sink,
        }
    }

    /// Probe this cluster for the listed topics (boot verification).
    pub fn verify_topics(&self, topics: &[&str]) -> anyhow::Result<()> {
        self.sink.verify_topics(topics)
    }
}

impl<P: KafkaProducer> KafkaOutputsBase<P> {
    /// Realize an address in this cluster's namespace. `Custom` redirects
    /// carry a literal topic and bypass the table.
    fn realize(&self, payload: AddressedPayload) -> RealizedRecord {
        let topic = self.topics.topic_for(&payload.address).to_string();
        RealizedRecord {
            uuid: payload.uuid,
            record: ProduceRecord {
                topic,
                key: payload.key,
                payload: payload.payload,
                headers: payload.headers,
            },
        }
    }
}

#[async_trait]
impl<P: KafkaProducer + 'static> Outputs for KafkaOutputsBase<P> {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let prepared = prepare_batch(&self.prep, events).await?;
        let realized = prepared.into_iter().map(|p| self.realize(p)).collect();
        fold_results(self.sink.publish(realized).await)
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        self.sink.flush()
    }
}

/// Test-only construction and produce helpers: the goldens drive the exact
/// production path (prep → realize → publish → fold) against a mock
/// producer, keeping their bodies identical to the pre-outputs era. The
/// default spec uses the test topics with no envelope compression; lz4
/// goldens pass their own.
#[cfg(test)]
impl<P: KafkaProducer + 'static> KafkaOutputsBase<P> {
    pub(crate) fn with_producer(producer: P, topics: TopicTable) -> Self {
        Self {
            prep: Self::test_prep_spec(),
            topics: Arc::new(topics),
            sink: KafkaSinkBase::with_producer(producer),
        }
    }

    pub(crate) fn test_prep_spec() -> PrepSpec {
        PrepSpec::new(crate::config::EnvelopeCompression::None)
    }

    pub(crate) async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.send_batch(vec![event]).await
    }

    pub(crate) async fn send_with(
        &self,
        spec: &PrepSpec,
        event: ProcessedEvent,
    ) -> Result<(), CaptureError> {
        self.send_batch_with(spec, vec![event]).await
    }

    pub(crate) async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.send_batch_with(&Self::test_prep_spec(), events).await
    }

    pub(crate) async fn send_batch_with(
        &self,
        spec: &PrepSpec,
        events: Vec<ProcessedEvent>,
    ) -> Result<(), CaptureError> {
        let prepared = prepare_batch(spec, events).await?;
        let realized = prepared.into_iter().map(|p| self.realize(p)).collect();
        fold_results(self.sink.publish(realized).await)
    }
}

#[cfg(test)]
mod tests {
    use crate::api::CaptureError;
    use crate::config::{self, EnvelopeCompression};
    use crate::outputs::kafka::KafkaOutputs;
    use crate::outputs::topics::TopicTable;
    use crate::outputs::PrepSpec;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, OverflowReason, ProcessedEvent, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use rand::distributions::Alphanumeric;
    use rand::Rng;
    use rdkafka::mocking::MockCluster;
    use rdkafka::producer::DefaultProducerContext;
    use rdkafka::types::{RDKafkaApiKey, RDKafkaRespErr};
    use tokio_util::sync::CancellationToken;

    async fn start_on_mocked_sink(
        message_max_bytes: Option<u32>,
    ) -> (MockCluster<'static, DefaultProducerContext>, KafkaOutputs) {
        let shutdown_token = CancellationToken::new();
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_shutdown_token(shutdown_token)
            .build();
        let handle = manager.register(
            "sink",
            lifecycle::ComponentOptions::new()
                .with_liveness_deadline(std::time::Duration::from_secs(30)),
        );
        let _monitor = manager.monitor_background();
        let cluster = MockCluster::new(1).expect("failed to create mock brokers");
        let config = config::KafkaConfig {
            kafka_producer_linger_ms: 0,
            kafka_producer_queue_mib: 50,
            kafka_message_timeout_ms: 500,
            kafka_topic_metadata_refresh_interval_ms: 20000,
            kafka_producer_message_max_bytes: message_max_bytes.unwrap_or(1000000),
            kafka_compression_codec: "none".to_string(),
            kafka_hosts: cluster.bootstrap_servers(),
            kafka_topic: "events_plugin_ingestion".to_string(),
            kafka_overflow_topic: "events_plugin_ingestion_overflow".to_string(),
            kafka_historical_topic: "events_plugin_ingestion_historical".to_string(),
            kafka_client_ingestion_warning_topic: "events_plugin_ingestion".to_string(),
            kafka_error_tracking_topic: "error_tracking_events".to_string(),
            kafka_heatmaps_topic: "events_plugin_ingestion".to_string(),
            kafka_replay_overflow_topic: "session_recording_snapshot_item_overflow".to_string(),
            kafka_dlq_topic: "events_plugin_ingestion_dlq".to_string(),
            kafka_traces_topic: "traces_ingestion".to_string(),
            kafka_metrics_topic: "metrics_ingestion".to_string(),
            kafka_tls: false,
            kafka_client_id: "".to_string(),
            kafka_metadata_max_age_ms: 60000,
            kafka_producer_max_retries: 2,
            kafka_producer_acks: "all".to_string(),
            kafka_socket_timeout_ms: 60000,
            kafka_producer_batch_num_messages: 10000,
            kafka_producer_batch_size: 1000000,
            kafka_producer_max_in_flight_requests: 1000000,
            kafka_producer_sticky_partitioning_linger_ms: 10,
            kafka_producer_enable_idempotence: false,
            kafka_producer_partitioner: "murmur2_random".to_string(),
            kafka_broker_address_family: String::new(),
            kafka_log_connection_close: true,
            kafka_producer_queue_buffering_max_messages: 100000,
            kafka_retry_backoff_max_ms: 1000,
            kafka_socket_send_buffer_bytes: 0,
            kafka_socket_receive_buffer_bytes: 0,
            kafka_traces_hosts: None,
            kafka_traces_tls: None,
            kafka_traces_client_id: None,
            kafka_traces_compression_codec: None,
            kafka_traces_producer_acks: None,
            kafka_traces_producer_linger_ms: None,
            kafka_traces_producer_queue_mib: None,
            kafka_traces_message_timeout_ms: None,
            kafka_traces_producer_message_max_bytes: None,
            kafka_traces_producer_max_retries: None,
            kafka_traces_topic_metadata_refresh_interval_ms: None,
            kafka_traces_metadata_max_age_ms: None,
            kafka_metrics_hosts: None,
            kafka_metrics_tls: None,
            kafka_metrics_client_id: None,
            kafka_metrics_compression_codec: None,
            kafka_metrics_producer_acks: None,
            kafka_metrics_producer_linger_ms: None,
            kafka_metrics_producer_queue_mib: None,
            kafka_metrics_message_timeout_ms: None,
            kafka_metrics_producer_message_max_bytes: None,
            kafka_metrics_producer_max_retries: None,
            kafka_metrics_topic_metadata_refresh_interval_ms: None,
            kafka_metrics_metadata_max_age_ms: None,
            kafka_replay_envelope_compression: EnvelopeCompression::None,
        };
        let sink = KafkaOutputs::new(config.clone(), TopicTable::from(&config), Some(handle))
            .await
            .expect("failed to create sink");
        (cluster, sink)
    }

    #[tokio::test]
    async fn kafka_sink_error_handling() {
        // Uses a mocked Kafka broker that allows injecting write errors, to check error handling.
        // We test different cases in a single test to amortize the startup cost of the producer.

        let (cluster, sink) = start_on_mocked_sink(Some(3000000)).await;
        let distinct_id = "test_distinct_id_123".to_string();
        let timestamp = chrono::Utc::now();
        let event: CapturedEvent = CapturedEvent {
            uuid: uuid_v7_from_datetime(timestamp),
            distinct_id: distinct_id.clone(),
            session_id: None,
            ip: "".to_string(),
            data: "".to_string(),
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            event: "test_event".to_string(),
            timestamp,
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let metadata = ProcessedEventMetadata {
            data_type: DataType::AnalyticsMain,
            session_id: None,
            computed_timestamp: None,
            event_name: "test_event".to_string(),
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            skip_heatmap_processing: false,
            overflow_reason: None,
        };

        let event = ProcessedEvent {
            event,
            metadata: metadata.clone(),
        };

        // Wait for producer to be healthy, to keep kafka_message_timeout_ms short and tests faster
        for _ in 0..20 {
            if sink.send(event.clone()).await.is_ok() {
                break;
            }
        }

        // Send events to confirm happy path
        sink.send(event.clone())
            .await
            .expect("failed to send one initial event");
        sink.send_batch(vec![event.clone(), event.clone()])
            .await
            .expect("failed to send initial event batch");

        // Producer should accept a 2MB message as we set message.max.bytes to 3MB
        let big_data = rand::thread_rng()
            .sample_iter(Alphanumeric)
            .take(2_000_000)
            .map(char::from)
            .collect();
        let timestamp = chrono::Utc::now();
        let captured = CapturedEvent {
            uuid: uuid_v7_from_datetime(timestamp),
            distinct_id: "id1".to_string(),
            session_id: None,
            ip: "".to_string(),
            data: big_data,
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            event: "test_event".to_string(),
            timestamp,
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let big_event = ProcessedEvent {
            event: captured,
            metadata: metadata.clone(),
        };

        sink.send(big_event)
            .await
            .expect("failed to send event larger than default max size");

        // Producer should reject a 4MB message
        let big_data = rand::thread_rng()
            .sample_iter(Alphanumeric)
            .take(4_000_000)
            .map(char::from)
            .collect();

        let timestamp = chrono::Utc::now();
        let big_event = ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: "id1".to_string(),
                session_id: None,
                ip: "".to_string(),
                data: big_data,
                now: "".to_string(),
                sent_at: None,
                token: "token1".to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            },
            metadata: metadata.clone(),
        };

        match sink.send(big_event).await {
            Err(CaptureError::EventTooBig(_)) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };

        // Simulate unretriable errors
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_MSG_SIZE_TOO_LARGE; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send(event.clone()).await {
            Err(CaptureError::EventTooBig(_)) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_INVALID_PARTITIONS; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };

        // Simulate transient errors, messages should go through OK
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 2];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        sink.send(event.clone())
            .await
            .expect("failed to send one event after recovery");
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 2];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        sink.send_batch(vec![event.clone(), event.clone()])
            .await
            .expect("failed to send event batch after recovery");

        // Timeout on a sustained transient error
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 50];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send(event.clone()).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };
    }

    #[tokio::test]
    async fn test_historical_migration_headers() {
        use common_types::CapturedEventHeaders;
        use rdkafka::message::OwnedHeaders;

        // Test that historical_migration=true is set in headers for AnalyticsHistorical
        let headers_historical = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2023-01-01T12:00:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some("2023-01-01T12:00:00Z".to_string()),
            force_disable_person_processing: None,
            historical_migration: Some(true),
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        };

        let owned_headers: OwnedHeaders = headers_historical.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);
        assert_eq!(parsed_headers.historical_migration, Some(true));
        assert_eq!(parsed_headers.now, Some("2023-01-01T12:00:00Z".to_string()));

        let headers_main = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2023-01-01T12:00:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some("2023-01-01T12:00:00Z".to_string()),
            force_disable_person_processing: None,
            historical_migration: Some(false),
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        };

        let owned_headers: OwnedHeaders = headers_main.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);
        assert_eq!(parsed_headers.historical_migration, Some(false));
        assert_eq!(parsed_headers.now, Some("2023-01-01T12:00:00Z".to_string()));
    }

    #[tokio::test]
    async fn test_now_header_is_set() {
        use common_types::CapturedEventHeaders;
        use rdkafka::message::OwnedHeaders;

        // Test that the 'now' header is correctly set and parsed
        let test_now = "2024-01-15T10:30:45Z".to_string();
        let headers = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2024-01-15T10:30:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some(test_now.clone()),
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        };

        // Convert to owned headers and back
        let owned_headers: OwnedHeaders = headers.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);

        // Verify the 'now' field is preserved
        assert_eq!(parsed_headers.now, Some(test_now));
        assert_eq!(parsed_headers.token, Some("test_token".to_string()));
        assert_eq!(parsed_headers.distinct_id, Some("test_id".to_string()));
    }

    #[tokio::test]
    async fn test_dlq_headers_are_set() {
        use common_types::CapturedEventHeaders;
        use rdkafka::message::OwnedHeaders;

        // Test that the 'now' header is correctly set and parsed
        let test_now = "2024-01-15T10:30:45Z".to_string();
        let dlq_timestamp = "2025-01-15T10:30:45Z".to_string();
        let headers = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2024-01-15T10:30:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some(test_now.clone()),
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: Some("test reason".to_string()),
            dlq_step: Some("test step".to_string()),
            dlq_timestamp: Some(dlq_timestamp.clone()),
            content_encoding: None,
        };

        // Convert to owned headers and back
        let owned_headers: OwnedHeaders = headers.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);

        // Verify the 'now' field is preserved
        assert_eq!(parsed_headers.dlq_reason, Some("test reason".to_string()));
        assert_eq!(parsed_headers.dlq_step, Some("test step".to_string()));
        assert_eq!(parsed_headers.dlq_timestamp, Some(dlq_timestamp));
    }

    #[cfg(test)]
    mod topic_routing {
        use super::*;
        use crate::outputs::kafka::KafkaOutputsBase;
        use crate::outputs::topics::test_topics;
        use crate::outputs::SCATTER_GATHER_MIN_BATCH;
        use crate::sinks::producer::MockKafkaProducer;

        const MAIN_TOPIC: &str = "events_plugin_ingestion";
        const OVERFLOW_TOPIC: &str = "events_plugin_ingestion_overflow";
        const DLQ_TOPIC: &str = "events_plugin_ingestion_dlq";
        const HISTORICAL_TOPIC: &str = "events_plugin_ingestion_historical";
        const HEATMAPS_TOPIC: &str = "heatmaps";
        const CLIENT_INGESTION_WARNING_TOPIC: &str = "client_ingestion_warning";
        const REPLAY_OVERFLOW_TOPIC: &str = "session_replay_overflow";
        const ERROR_TRACKING_TOPIC: &str = "error_tracking_events";

        /// Which reroute counter (if any) an event must increment. DLQ and
        /// custom-topic redirects are mutually exclusive at the sink because DLQ
        /// takes strict priority, so a single event fires at most one counter.
        #[derive(Clone, Copy, PartialEq, Debug)]
        enum Rerouted {
            None,
            Dlq,
            CustomTopic,
        }

        struct EventInput {
            data_type: DataType,
            force_overflow: bool,
            skip_person_processing: bool,
            skip_heatmap_processing: bool,
            redirect_to_dlq: bool,
            redirect_to_topic: Option<String>,
            overflow_reason: Option<OverflowReason>,
            compression: EnvelopeCompression,
        }

        impl Default for EventInput {
            fn default() -> Self {
                Self {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    skip_heatmap_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    compression: EnvelopeCompression::None,
                }
            }
        }

        fn create_test_event(input: &EventInput) -> ProcessedEvent {
            let timestamp = chrono::Utc::now();
            let event = CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: "test_user".to_string(),
                session_id: Some("session123".to_string()),
                ip: "127.0.0.1".to_string(),
                data: "{}".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            };

            let metadata = ProcessedEventMetadata {
                data_type: input.data_type,
                session_id: Some("session123".to_string()),
                computed_timestamp: None,
                event_name: "test_event".to_string(),
                force_overflow: input.force_overflow,
                skip_person_processing: input.skip_person_processing,
                redirect_to_dlq: input.redirect_to_dlq,
                redirect_to_topic: input.redirect_to_topic.clone(),
                skip_heatmap_processing: input.skip_heatmap_processing,
                overflow_reason: input.overflow_reason.clone(),
            };

            ProcessedEvent { event, metadata }
        }

        /// The full routing fingerprint of one event: topic + partition key +
        /// every header the sink can stamp + which reroute counter (if any)
        /// fires. This is the golden oracle every later refactor step diffs
        /// against, so each field is stated explicitly rather than re-derived
        /// from the input. Fields default to the "normal main-topic" outcome so
        /// each case only spells out what makes it different.
        struct ExpectedRouting<'a> {
            topic: &'a str,
            has_key: bool,
            force_disable_person_processing: Option<bool>,
            skip_heatmap_processing: Option<bool>,
            content_encoding: Option<&'a str>,
            dlq_headers: bool,
            rerouted: Rerouted,
        }

        impl Default for ExpectedRouting<'_> {
            fn default() -> Self {
                Self {
                    topic: "",
                    has_key: true,
                    force_disable_person_processing: None,
                    skip_heatmap_processing: None,
                    content_encoding: None,
                    dlq_headers: false,
                    rerouted: Rerouted::None,
                }
            }
        }

        async fn assert_routing(input: EventInput, expected: ExpectedRouting<'_>) {
            // Capture reroute counters on a thread-local recorder. `assert_routing`
            // runs on the default current-thread test runtime and `send` prepares
            // the record inline before the first await, so the guard stays visible
            // when `prepare_record` increments the counter.
            let recorder = metrics_util::debugging::DebuggingRecorder::new();
            let snapshotter = recorder.snapshotter();
            let _guard = metrics::set_default_local_recorder(&recorder);

            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());
            let spec = PrepSpec::new(input.compression);

            let event = create_test_event(&input);
            sink.send_with(&spec, event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1, "Expected exactly one record");
            let record = &records[0];
            let headers = &record.headers;

            let ctx = format!(
                "{:?} (force_overflow={}, skip_person={}, skip_heatmap={}, dlq={}, redirect_to_topic={:?}, overflow_reason={:?})",
                input.data_type,
                input.force_overflow,
                input.skip_person_processing,
                input.skip_heatmap_processing,
                input.redirect_to_dlq,
                input.redirect_to_topic,
                input.overflow_reason,
            );

            assert_eq!(record.topic, expected.topic, "wrong topic for {ctx}");
            assert_eq!(
                record.key.is_some(),
                expected.has_key,
                "wrong key presence for {ctx}"
            );
            assert_eq!(
                headers.force_disable_person_processing, expected.force_disable_person_processing,
                "wrong force_disable_person_processing header for {ctx}"
            );
            assert_eq!(
                headers.skip_heatmap_processing, expected.skip_heatmap_processing,
                "wrong skip_heatmap_processing header for {ctx}"
            );
            assert_eq!(
                headers.content_encoding.as_deref(),
                expected.content_encoding,
                "wrong content_encoding header for {ctx}"
            );

            // DLQ headers travel as a set: a reason, a step, and a valid RFC-3339
            // timestamp when the event is routed to the DLQ; all three absent on
            // every other route.
            if expected.dlq_headers {
                assert_eq!(
                    headers.dlq_reason.as_deref(),
                    Some("event_restriction"),
                    "wrong dlq_reason for {ctx}"
                );
                assert_eq!(
                    headers.dlq_step.as_deref(),
                    Some("capture"),
                    "wrong dlq_step for {ctx}"
                );
                let ts = headers
                    .dlq_timestamp
                    .as_deref()
                    .unwrap_or_else(|| panic!("dlq_timestamp missing for {ctx}"));
                chrono::DateTime::parse_from_rfc3339(ts).unwrap_or_else(|e| {
                    panic!("dlq_timestamp '{ts}' is not valid RFC 3339 for {ctx}: {e}")
                });
            } else {
                assert_eq!(
                    headers.dlq_reason, None,
                    "dlq_reason must be absent for {ctx}"
                );
                assert_eq!(headers.dlq_step, None, "dlq_step must be absent for {ctx}");
                assert_eq!(
                    headers.dlq_timestamp, None,
                    "dlq_timestamp must be absent for {ctx}"
                );
            }

            // Exactly one reroute counter fires per redirected event; neither
            // fires on the normal per-datatype or overflow paths.
            let snapshot = snapshotter.snapshot().into_vec();
            let count = |name: &str| -> Option<u64> {
                snapshot.iter().find_map(|(key, _, _, value)| {
                    if key.key().name() != name {
                        return None;
                    }
                    match value {
                        metrics_util::debugging::DebugValue::Counter(v) => Some(*v),
                        _ => None,
                    }
                })
            };
            let dlq_count = count("capture_events_rerouted_dlq");
            let custom_count = count("capture_events_rerouted_custom_topic");
            match expected.rerouted {
                Rerouted::None => {
                    assert_eq!(
                        dlq_count, None,
                        "capture_events_rerouted_dlq must not fire for {ctx}"
                    );
                    assert_eq!(
                        custom_count, None,
                        "capture_events_rerouted_custom_topic must not fire for {ctx}"
                    );
                }
                Rerouted::Dlq => {
                    assert_eq!(
                        dlq_count,
                        Some(1),
                        "capture_events_rerouted_dlq must fire once for {ctx}"
                    );
                    assert_eq!(
                        custom_count, None,
                        "capture_events_rerouted_custom_topic must not fire for {ctx}"
                    );
                }
                Rerouted::CustomTopic => {
                    assert_eq!(
                        custom_count,
                        Some(1),
                        "capture_events_rerouted_custom_topic must fire once for {ctx}"
                    );
                    assert_eq!(
                        dlq_count, None,
                        "capture_events_rerouted_dlq must not fire for {ctx}"
                    );
                }
            }
        }

        // ==================== AnalyticsMain ====================

        #[tokio::test]
        async fn analytics_main_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_force_overflow_with_skip_person() {
            // Key should be dropped when both force_overflow and skip_person_processing are set
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_skip_person_only() {
            // Key should be dropped when skip_person_processing is set, even without overflow
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_dlq_priority_over_overflow() {
            // DLQ takes priority over force_overflow
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_dlq_with_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    skip_person_processing: true,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    force_disable_person_processing: Some(true),
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_all_flags() {
            // DLQ takes priority, skip_person still sets header
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    skip_person_processing: true,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    force_disable_person_processing: Some(true),
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== AnalyticsHistorical ====================
        // Historical events IGNORE force_overflow - they never overflow

        #[tokio::test]
        async fn analytics_historical_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_ignores_force_overflow() {
            // Historical events should ignore force_overflow
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    force_overflow: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_all_flags() {
            // DLQ takes priority, historical ignores overflow, skip_person sets header
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    force_overflow: true,
                    skip_person_processing: true,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    force_disable_person_processing: Some(true),
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== SnapshotMain ====================

        #[tokio::test]
        async fn snapshot_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_force_overflow_with_skip_person() {
            // Unlike AnalyticsMain, SnapshotMain does NOT drop key with skip_person_processing
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: true,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_skip_person_only() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_dlq_priority_over_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: true,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_lz4_sets_content_encoding_header() {
            // With envelope compression on, a snapshot event carries the
            // `content-encoding: lz4` header alongside its normal main-topic
            // routing. The compressed-payload bytes are covered by the lz4
            // payload goldens below; here the oracle pins just the header.
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    compression: EnvelopeCompression::Lz4,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    content_encoding: Some("lz4"),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_lz4_leaves_content_encoding_unset() {
            // Envelope compression only applies to snapshots: a non-snapshot
            // event under the same sink config carries no content-encoding.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    compression: EnvelopeCompression::Lz4,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== HeatmapMain ====================
        // Heatmaps IGNORE force_overflow

        #[tokio::test]
        async fn heatmap_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_ignores_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    force_overflow: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_skip_heatmap_processing_sets_header() {
            // The skip_heatmap_processing metadata flag stamps its own header,
            // independent of the routing topic and the person-processing flag.
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    skip_heatmap_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    skip_heatmap_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_skip_heatmap_processing_sets_header() {
            // skip_heatmap_processing is not gated on data type: it rides through
            // for AnalyticsMain too, orthogonally to skip_person_processing.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    skip_heatmap_processing: true,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    skip_heatmap_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== ExceptionErrorTracking ====================
        // Exceptions IGNORE force_overflow

        #[tokio::test]
        async fn exception_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_ignores_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    force_overflow: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== ClientIngestionWarning ====================
        // ClientIngestionWarning IGNORES force_overflow

        #[tokio::test]
        async fn client_ingestion_warning_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn client_ingestion_warning_ignores_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    force_overflow: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn client_ingestion_warning_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn client_ingestion_warning_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    redirect_to_dlq: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== RedirectToTopic ====================
        // redirect_to_topic overrides normal routing but DLQ takes priority

        #[tokio::test]
        async fn analytics_main_redirect_to_topic() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_dlq_priority_over_redirect_to_topic() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    redirect_to_dlq: true,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_redirect_to_topic_priority_over_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_redirect_to_topic_with_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    skip_person_processing: true,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    force_disable_person_processing: Some(true),
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_redirect_to_topic() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== overflow_reason routing tests ====================
        // The pipeline stamps ProcessedEventMetadata::overflow_reason upstream;
        // the sink is a pure mechanism layer that switches on it. These cover
        // each variant: ForceLimited, RateLimited { preserve_locality }, and
        // ReplayLimited. `force_overflow` coexistence is covered by the
        // analytics_main_force_overflow / snapshot_main_force_overflow cases
        // above (force_overflow short-circuits the overflow_reason branch).

        #[tokio::test]
        async fn overflow_reason_force_limited_routes_to_overflow_with_null_key_and_flag() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    overflow_reason: Some(OverflowReason::ForceLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_rate_limited_preserves_key_when_preserve_locality() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: true,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_rate_limited_drops_key_when_not_preserve_locality() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_ignored_for_analytics_historical() {
            // historical events never go through overflow routing even if the
            // upstream pipeline accidentally stamps one — be defensive.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_replay_limited_routes_snapshot_to_replay_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    overflow_reason: Some(OverflowReason::ReplayLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_force_overflow_short_circuits_overflow_reason() {
            // Precedence check: force_overflow set by event restrictions wins
            // over any overflow_reason stamped by the governor. This ensures
            // the event_restriction counter label stays distinct from
            // force_limited / rate_limited labels.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_redirect_to_dlq_wins_over_overflow_reason() {
            // DLQ routing is the highest-priority routing decision: it wins
            // over both force_overflow and overflow_reason.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    redirect_to_dlq: true,
                    overflow_reason: Some(OverflowReason::ForceLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_redirect_to_topic_wins_over_overflow_reason() {
            // Custom topic redirect (set by event restrictions) also wins over
            // overflow_reason since overflow decisions cannot compose with a
            // hard-coded topic override.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: Some(OverflowReason::ForceLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== send_batch ordering + error tests ====================
        // These exercise the B2 three-phase send_batch: parallel prepare_record,
        // serial enqueue_record, concurrent ack drain. The ordering test runs on
        // a multi-thread runtime so phase 1 actually parallelizes across workers
        // and we can detect if phase 2 is accidentally reordering records.

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_preserves_order_same_key() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            // 20 events, all sharing the same distinct_id (so they hash to the
            // same partition via murmur2), each with a unique UUID so we can
            // track input->output order through the pipeline.
            let events: Vec<ProcessedEvent> = (0..20)
                .map(|_| {
                    create_test_event(&EventInput {
                        data_type: DataType::AnalyticsMain,
                        ..Default::default()
                    })
                })
                .collect();

            let input_uuids: Vec<String> =
                events.iter().map(|e| e.event.uuid.to_string()).collect();

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), 20, "expected 20 records");

            // Parse the UUID out of each record's serialized payload and compare
            // against the input order. If phase 2 ever reorders enqueue calls,
            // librdkafka's partition-order guarantee would be broken for same-key
            // events and this assertion trips.
            let output_uuids: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v.get("uuid")
                        .and_then(|u| u.as_str())
                        .expect("uuid field present")
                        .to_string()
                })
                .collect();

            assert_eq!(
                output_uuids, input_uuids,
                "send_batch must preserve input order for same-key events"
            );

            // Sanity: all records share the same partition key.
            let first_key = records[0].key.as_deref().expect("partition key set");
            for r in &records {
                assert_eq!(
                    r.key.as_deref(),
                    Some(first_key),
                    "all events should share partition key"
                );
            }
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_prep_error_aborts_batch() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            // Build a batch where event #3 is a SnapshotMain with session_id=None,
            // which causes prepare_record to return MissingSessionId. The other
            // events are valid AnalyticsMain. Since phase 2 only runs after all
            // prep tasks complete, a prep error must short-circuit before any
            // producer.send() call — so the mock producer should see zero records.
            let mut events: Vec<ProcessedEvent> = (0..5)
                .map(|_| {
                    create_test_event(&EventInput {
                        data_type: DataType::AnalyticsMain,
                        ..Default::default()
                    })
                })
                .collect();

            // Overwrite element [2] with a SnapshotMain event whose session_id
            // metadata is None — prepare_record returns MissingSessionId at the
            // session_id lookup in the SnapshotMain branch.
            let mut bad = create_test_event(&EventInput {
                data_type: DataType::SnapshotMain,
                ..Default::default()
            });
            bad.metadata.session_id = None;
            events[2] = bad;

            let res = sink.send_batch(events).await;
            match res {
                Err(CaptureError::MissingSessionId) => {}
                Err(other) => panic!("expected MissingSessionId, got {other:?}"),
                Ok(()) => panic!("expected send_batch to fail on prep error"),
            }

            let records = producer.get_records();
            assert!(
                records.is_empty(),
                "no records should reach the producer when prep phase fails; got {} records",
                records.len()
            );
        }

        // ==================== send_batch fast-path + mid-batch failure tests ====================

        /// Builds N AnalyticsMain events with sequential distinct_ids so each
        /// record is individually identifiable in the mock producer's output.
        fn build_batch(n: usize) -> Vec<ProcessedEvent> {
            (0..n)
                .map(|i| {
                    let mut e = create_test_event(&EventInput::default());
                    e.event.distinct_id = format!("user_{i}");
                    e
                })
                .collect()
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_mid_enqueue_failure_preserves_earlier_records() {
            // Fail at phase-2 send #3 (0-indexed): events [0, 1, 2] should land
            // in the mock, send_batch must return Err, and no event at index
            // >= 3 should ever hit the producer. Batch size is well above the
            // scatter-gather threshold so phase 2 runs post-parallel-prep.
            const BATCH: usize = 10;
            const FAIL_IDX: usize = 3;
            let producer = MockKafkaProducer::new_failing_at(FAIL_IDX);
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            let events = build_batch(BATCH);
            let input_distinct_ids: Vec<String> =
                events.iter().map(|e| e.event.distinct_id.clone()).collect();

            let res = sink.send_batch(events).await;
            match res {
                Err(CaptureError::RetryableSinkError) => {}
                Err(other) => panic!("expected RetryableSinkError, got {other:?}"),
                Ok(()) => panic!("expected send_batch to fail on enqueue #{FAIL_IDX}"),
            }

            let records = producer.get_records();
            assert_eq!(
                records.len(),
                FAIL_IDX,
                "expected exactly {FAIL_IDX} records to reach producer before failure"
            );

            // Output distinct_ids should match input[..FAIL_IDX] in order:
            // phase-2 is serial in input order, so the earlier records must
            // be the first FAIL_IDX events of the input batch.
            let output_distinct_ids: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v.get("distinct_id")
                        .and_then(|u| u.as_str())
                        .expect("distinct_id field present")
                        .to_string()
                })
                .collect();
            assert_eq!(
                output_distinct_ids,
                input_distinct_ids[..FAIL_IDX],
                "earlier records must preserve input order on mid-batch failure"
            );
        }

        #[tokio::test]
        async fn send_batch_single_event_via_batch_path() {
            // batch_size=1 exercises the serial fast path (1 < SCATTER_GATHER_MIN_BATCH)
            // and verifies the loop handles a single-element batch correctly.
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            let events = build_batch(1);
            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), 1, "expected exactly one record");
            assert_eq!(records[0].topic, MAIN_TOPIC);
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_just_below_threshold_uses_serial_path() {
            // batch_size = SCATTER_GATHER_MIN_BATCH - 1 takes the serial fast
            // path. We can't observe "which path ran" directly, so we assert
            // behavioral equivalence: N records, correct topic, input order.
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            let size = SCATTER_GATHER_MIN_BATCH - 1;
            let events = build_batch(size);
            let input_distinct_ids: Vec<String> =
                events.iter().map(|e| e.event.distinct_id.clone()).collect();

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), size);
            let output: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v["distinct_id"].as_str().unwrap().to_string()
                })
                .collect();
            assert_eq!(
                output, input_distinct_ids,
                "serial path must preserve order"
            );
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_at_threshold_uses_scatter_gather_path() {
            // batch_size = SCATTER_GATHER_MIN_BATCH takes the scatter-gather
            // path. Behavioral equivalence with the serial path must hold:
            // same N records, same order, same topics.
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            let size = SCATTER_GATHER_MIN_BATCH;
            let events = build_batch(size);
            let input_distinct_ids: Vec<String> =
                events.iter().map(|e| e.event.distinct_id.clone()).collect();

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), size);
            let output: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v["distinct_id"].as_str().unwrap().to_string()
                })
                .collect();
            assert_eq!(
                output, input_distinct_ids,
                "scatter-gather path must preserve input order after sort_unstable_by_key"
            );
        }

        /// Per-event-type topic routing is covered by `assert_routing` for
        /// the single-event path. This test verifies routing survives the
        /// batch path for a mixed batch of data types plus one force_overflow
        /// AnalyticsMain — exercised on both the serial fast path (5 events)
        /// and the scatter-gather path (10 events).
        async fn mixed_datatypes_routing_for_batch(pad_to: usize) {
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            // Core 5-event diverse batch.
            let mut events: Vec<ProcessedEvent> = vec![
                create_test_event(&EventInput {
                    data_type: DataType::AnalyticsMain,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::HeatmapMain,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    ..EventInput::default()
                }),
            ];

            // Pad with AnalyticsMain events if caller wants to push the batch
            // over SCATTER_GATHER_MIN_BATCH. Padding goes at the end so the
            // first 5 per-event assertions line up regardless of batch size.
            while events.len() < pad_to {
                events.push(create_test_event(&EventInput::default()));
            }

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), pad_to.max(5));

            // Per-index topic assertions (order-preserving: phase-2 is serial
            // in input order on both paths).
            assert_eq!(records[0].topic, MAIN_TOPIC, "event[0]: AnalyticsMain");
            assert_eq!(records[1].topic, HEATMAPS_TOPIC, "event[1]: HeatmapMain");
            assert_eq!(
                records[2].topic, ERROR_TRACKING_TOPIC,
                "event[2]: ExceptionErrorTracking"
            );
            assert_eq!(
                records[3].topic, CLIENT_INGESTION_WARNING_TOPIC,
                "event[3]: ClientIngestionWarning"
            );
            assert_eq!(
                records[4].topic, OVERFLOW_TOPIC,
                "event[4]: AnalyticsMain + force_overflow"
            );
        }

        #[tokio::test]
        async fn send_batch_mixed_datatypes_serial_path() {
            // 5 events < SCATTER_GATHER_MIN_BATCH => serial fast path.
            mixed_datatypes_routing_for_batch(5).await;
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_mixed_datatypes_scatter_gather_path() {
            // 10 events >= SCATTER_GATHER_MIN_BATCH => scatter-gather path.
            mixed_datatypes_routing_for_batch(10).await;
        }

        // ==================== Envelope compression ====================

        #[tokio::test]
        async fn snapshot_payload_uncompressed_by_default() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());

            let event = create_test_event(&EventInput {
                data_type: DataType::SnapshotMain,
                ..Default::default()
            });
            sink.send(event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            // Payload must be valid UTF-8 JSON when compression is off.
            let v: serde_json::Value = serde_json::from_slice(&records[0].payload)
                .expect("uncompressed payload is valid json");
            assert!(v.get("distinct_id").is_some());
        }

        #[tokio::test]
        async fn snapshot_payload_lz4_compressed_when_enabled() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());
            let spec = PrepSpec::new(EnvelopeCompression::Lz4);

            let event = create_test_event(&EventInput {
                data_type: DataType::SnapshotMain,
                ..Default::default()
            });
            sink.send_with(&spec, event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            // `content-encoding: lz4` header must be present.
            assert_eq!(
                records[0].headers.content_encoding.as_deref(),
                Some("lz4"),
                "expected content-encoding: lz4 header"
            );
            // Payload = 4-byte LE uncompressed size + LZ4 block data. Decompress and verify.
            let payload = &records[0].payload;
            let uncompressed_len = u32::from_le_bytes(payload[..4].try_into().unwrap()) as usize;
            let decompressed = lz4::block::decompress(&payload[4..], Some(uncompressed_len as i32))
                .expect("failed to decompress");
            let v: serde_json::Value =
                serde_json::from_slice(&decompressed).expect("decompressed payload is valid json");
            assert!(v.get("distinct_id").is_some());
        }

        #[tokio::test]
        async fn non_snapshot_payload_not_compressed_when_lz4_enabled() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaOutputsBase::with_producer(producer.clone(), test_topics());
            let spec = PrepSpec::new(EnvelopeCompression::Lz4);

            let event = create_test_event(&EventInput {
                data_type: DataType::AnalyticsMain,
                ..Default::default()
            });
            sink.send_with(&spec, event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            // Non-snapshot payloads must stay uncompressed regardless of the flag.
            let v: serde_json::Value =
                serde_json::from_slice(&records[0].payload).expect("payload must be plain json");
            assert!(v.get("distinct_id").is_some());
        }
    }
}
