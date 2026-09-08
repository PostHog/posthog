//! Shared harness for the opt-in end-to-end tests.

// Each test binary compiles this module separately, so helpers only one uses look dead.
#![allow(dead_code)]

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
use common_kafka_consumer::config::ConsumerConfigBuilder;
use common_liveness::SyncLivenessReporter;
use prost::Message;
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::ClientConfig;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::{Channel, Server};
use usage_ingestion::counters::CounterAccumulator;
use usage_ingestion::grpc::GrpcUsageIngestion;
use usage_ingestion::kafka::{KafkaBatchConfig, KafkaUsageIngestion};
use usage_ingestion::resolver::{OrganizationResolver, ResolveError};
use usage_ingestion::service::UsageIngestionService;
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_client::UsageIngestionClient;
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_server::UsageIngestionServer;
use usage_ingestion_proto::usage_ingestion::v1::IngestBillingUsageRequest;
use uuid::Uuid;

/// A Django test environment suffixes both the database and the topic, so CI overrides both.
pub fn table() -> String {
    format!(
        "{}.sharded_billing_usage_records",
        env_or("USAGE_INGESTION_E2E_CLICKHOUSE_DATABASE", "posthog")
    )
}

pub fn topic() -> String {
    env_or(
        "USAGE_INGESTION_E2E_TOPIC",
        "clickhouse_billing_usage_records",
    )
}

#[derive(Clone)]
pub struct TestLiveness;

impl SyncLivenessReporter for TestLiveness {
    fn report_healthy(&self) {}

    fn report_unhealthy(&self) {}
}

/// The service resolves every organization itself, so these tests stand in for the
/// HyperCache/PostgreSQL lookup rather than seeding a team row.
struct FixedResolver(Uuid);

#[async_trait]
impl OrganizationResolver for FixedResolver {
    async fn resolve(&self, _team_id: i64) -> Result<Uuid, ResolveError> {
        Ok(self.0)
    }
}

pub fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

pub fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .map(|value| {
            value
                .parse()
                .unwrap_or_else(|_| panic!("{key} must be a positive integer, got {value:?}"))
        })
        .unwrap_or(default)
}

pub fn kafka_hosts() -> String {
    env_or("USAGE_INGESTION_E2E_KAFKA_HOSTS", "localhost:9092")
}

pub async fn create_topic(name: &str, partitions: i32) {
    let admin: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", kafka_hosts())
        .create()
        .expect("failed to create the Kafka admin client");
    let topic = NewTopic::new(name, partitions, TopicReplication::Fixed(1));
    let options = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));
    for result in admin.create_topics(&[topic], &options).await.unwrap() {
        match result {
            Ok(_) | Err((_, RDKafkaErrorCode::TopicAlreadyExists)) => {}
            Err((name, error)) => panic!("failed to create topic {name}: {error:?}"),
        }
    }
}

pub fn clickhouse_url() -> String {
    env_or(
        "USAGE_INGESTION_E2E_CLICKHOUSE_URL",
        "http://localhost:8123",
    )
}

pub async fn clickhouse(client: &reqwest::Client, url: &str, query: &str) -> String {
    let response = client
        .post(url)
        .body(query.to_string())
        .send()
        .await
        .expect("ClickHouse request failed");
    let status = response.status();
    let body = response.text().await.expect("ClickHouse body was not text");
    assert!(status.is_success(), "{query}\n-> {status}: {body}");
    body
}

pub struct Service {
    pub address: SocketAddr,
    shutdown: oneshot::Sender<()>,
    handle: JoinHandle<()>,
}

impl Service {
    pub async fn start(
        max_batch_size: usize,
        organization_id: Uuid,
        counters: Option<Arc<CounterAccumulator>>,
    ) -> Self {
        let service = service(max_batch_size, organization_id, counters).await;

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (shutdown, shutdown_signal) = oneshot::channel::<()>();
        let handle = tokio::spawn(async move {
            Server::builder()
                .add_service(UsageIngestionServer::new(GrpcUsageIngestion::new(service)))
                .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                    let _ = shutdown_signal.await;
                })
                .await
                .expect("the gRPC server failed");
        });

        Self {
            address,
            shutdown,
            handle,
        }
    }

    pub async fn client(&self) -> UsageIngestionClient<Channel> {
        UsageIngestionClient::connect(format!("http://{}", self.address))
            .await
            .expect("failed to connect to the in-process gRPC server")
    }

    pub async fn stop(self) {
        let _ = self.shutdown.send(());
        self.handle.await.unwrap();
    }
}

pub struct KafkaService {
    input_topic: String,
    producer: FutureProducer,
    handle: JoinHandle<()>,
}

impl KafkaService {
    pub async fn start(max_batch_size: usize, organization_id: Uuid) -> Self {
        let service = service(max_batch_size, organization_id, None).await;
        let input_topic = format!("usage_ingestion_e2e_{}", Uuid::new_v4());
        let dead_letter_topic = format!("{input_topic}_dlq");
        create_topic(&input_topic, 1).await;
        create_topic(&dead_letter_topic, 1).await;
        let group = format!("usage-ingestion-e2e-{}", Uuid::new_v4());
        let consumer_config = ConsumerConfigBuilder::for_batch_consumer(&kafka_hosts(), &group)
            .with_offset_reset("earliest")
            .build();
        let transport = KafkaUsageIngestion::new(
            &consumer_config,
            &input_topic,
            dead_letter_topic,
            service,
            KafkaBatchConfig {
                max_messages: 100,
                max_wait: Duration::from_millis(10),
                concurrency: 16,
            },
            TestLiveness,
        )
        .expect("failed to create the Kafka transport");
        let handle = tokio::spawn(async move {
            transport.run().await.expect("Kafka transport failed");
        });
        let producer = ClientConfig::new()
            .set("bootstrap.servers", kafka_hosts())
            .set("message.timeout.ms", "10000")
            .create()
            .expect("failed to create the input Kafka producer");

        Self {
            input_topic,
            producer,
            handle,
        }
    }

    pub async fn publish(&self, request: IngestBillingUsageRequest) {
        let payload = request.encode_to_vec();
        self.producer
            .send_result(
                FutureRecord::to(&self.input_topic)
                    .key("usage-ingestion-e2e")
                    .payload(&payload),
            )
            .expect("failed to enqueue the input message")
            .await
            .expect("input delivery was canceled")
            .expect("input delivery failed");
    }

    pub fn stop(self) {
        self.handle.abort();
    }
}

async fn service(
    max_batch_size: usize,
    organization_id: Uuid,
    counters: Option<Arc<CounterAccumulator>>,
) -> Arc<UsageIngestionService> {
    service_with_resolver(
        max_batch_size,
        Arc::new(FixedResolver(organization_id)),
        counters,
    )
    .await
}

pub async fn service_with_resolver(
    max_batch_size: usize,
    resolver: Arc<dyn OrganizationResolver>,
    counters: Option<Arc<CounterAccumulator>>,
) -> Arc<UsageIngestionService> {
    let producer = create_kafka_producer(
        &KafkaConfig {
            kafka_hosts: kafka_hosts(),
            kafka_tls: false,
            kafka_client_id: "usage-ingestion-e2e".to_string(),
            ..Default::default()
        },
        TestLiveness,
    )
    .await
    .expect("failed to create the Kafka producer");
    Arc::new(UsageIngestionService::new(
        producer,
        resolver,
        max_batch_size,
        topic(),
        counters,
    ))
}
