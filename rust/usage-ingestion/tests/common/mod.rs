//! Shared harness for the opt-in end-to-end tests.

// Each test binary compiles this module separately, so helpers only one uses look dead.
#![allow(dead_code)]

use std::net::SocketAddr;
use std::sync::Arc;

use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
use common_liveness::SyncLivenessReporter;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::{Channel, Server};
use usage_ingestion::resolver::{OrganizationResolver, ResolveError};
use usage_ingestion::service::UsageIngestionService;
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_client::UsageIngestionClient;
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_server::UsageIngestionServer;
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
struct TestLiveness;

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
    pub async fn start(max_batch_size: usize, organization_id: Uuid) -> Self {
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
        let service = UsageIngestionService::new(
            producer,
            Arc::new(FixedResolver(organization_id)),
            max_batch_size,
            topic(),
        );

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (shutdown, shutdown_signal) = oneshot::channel::<()>();
        let handle = tokio::spawn(async move {
            Server::builder()
                .add_service(UsageIngestionServer::new(service))
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
