//! End-to-end check that a retried usage record collapses to one canonical row.
//! Needs a local Kafka and a ClickHouse with migration 0301 applied; the service
//! itself runs in-process.

use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::Utc;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
use common_liveness::SyncLivenessReporter;
use tokio::net::TcpListener;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::Server;
use usage_ingestion::resolver::{OrganizationResolver, ResolveError};
use usage_ingestion::service::UsageIngestionService;
use usage_ingestion_proto::usage_ingestion::v1::{
    usage_ingestion_client::UsageIngestionClient, usage_ingestion_server::UsageIngestionServer,
    IngestUsageRecordsRequest, UsageMode, UsageRecord,
};
use uuid::Uuid;

/// Fixed so both records always land in the same monthly partition, which is the
/// scope ReplacingMergeTree deduplicates within.
const FIRST_EVENT_TIMESTAMP_MS: i64 = 1_718_409_600_000; // 2024-06-15T00:00:00Z
const RETRY_EVENT_TIMESTAMP_MS: i64 = FIRST_EVENT_TIMESTAMP_MS + 1_000;
const TABLE: &str = "posthog.sharded_usage_records";

#[derive(Clone)]
struct TestLiveness;

impl SyncLivenessReporter for TestLiveness {
    fn report_healthy(&self) {}

    fn report_unhealthy(&self) {}
}

struct StaticResolver;

#[async_trait]
impl OrganizationResolver for StaticResolver {
    async fn resolve(&self, _team_id: i64) -> Result<Uuid, ResolveError> {
        Err(ResolveError::Missing)
    }
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

async fn clickhouse(client: &reqwest::Client, url: &str, query: &str) -> String {
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

fn record(record_id: &str, organization_id: Uuid, event_timestamp_ms: i64) -> UsageRecord {
    UsageRecord {
        record_id: record_id.to_string(),
        producer_id: "usage-ingestion-e2e".to_string(),
        team_id: 1,
        organization_id: Some(organization_id.to_string()),
        usage_key: "e2e_records".to_string(),
        mode: UsageMode::Delta as i32,
        unit: "record".to_string(),
        quantity: 1,
        version: 1,
        event_timestamp_ms,
        source_ref: None,
        user_id: None,
        variant: None,
        dimensions: Default::default(),
    }
}

#[tokio::test]
#[ignore = "requires a local Kafka and ClickHouse with migration 0301; run with --ignored"]
async fn retried_record_deduplicates_to_the_latest_event_timestamp() {
    let kafka_hosts = env_or("USAGE_INGESTION_E2E_KAFKA_HOSTS", "localhost:9092");
    let clickhouse_url = env_or(
        "USAGE_INGESTION_E2E_CLICKHOUSE_URL",
        "http://localhost:8123",
    );

    let producer = create_kafka_producer(
        &KafkaConfig {
            kafka_hosts,
            kafka_tls: false,
            kafka_client_id: "usage-ingestion-e2e".to_string(),
            ..Default::default()
        },
        TestLiveness,
    )
    .await
    .expect("failed to create the Kafka producer");
    let service = UsageIngestionService::new(producer, Arc::new(StaticResolver), 500);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (shutdown, shutdown_signal) = tokio::sync::oneshot::channel::<()>();
    let server = tokio::spawn(async move {
        Server::builder()
            .add_service(UsageIngestionServer::new(service))
            .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                let _ = shutdown_signal.await;
            })
            .await
            .expect("the gRPC server failed");
    });

    let mut client = UsageIngestionClient::connect(format!("http://{address}"))
        .await
        .expect("failed to connect to the in-process gRPC server");

    let record_id = Uuid::new_v4().to_string();
    let organization_id = Uuid::new_v4();
    client
        .ingest(IngestUsageRecordsRequest {
            records: vec![record(
                &record_id,
                organization_id,
                FIRST_EVENT_TIMESTAMP_MS,
            )],
        })
        .await
        .expect("the first ingest failed");
    tokio::time::sleep(Duration::from_millis(50)).await;
    // Truncated to milliseconds, the precision the service serializes inserted_at at.
    let between_ingests = Utc::now().format("%Y-%m-%d %H:%M:%S%.3f000").to_string();
    client
        .ingest(IngestUsageRecordsRequest {
            records: vec![record(
                &record_id,
                organization_id,
                RETRY_EVENT_TIMESTAMP_MS,
            )],
        })
        .await
        .expect("the retried ingest failed");

    let http = reqwest::Client::new();
    // Wait on the retry specifically: the first record may land a flush earlier.
    let arrival_query = format!(
        "SELECT count() FROM {TABLE} WHERE record_id = '{record_id}' AND event_timestamp = toDateTime64('2024-06-15 00:00:01', 6, 'UTC')"
    );
    let deadline = Instant::now() + Duration::from_secs(120);
    loop {
        if clickhouse(&http, &clickhouse_url, &arrival_query)
            .await
            .trim()
            == "1"
        {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "the retried record never reached ClickHouse"
        );
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    clickhouse(
        &http,
        &clickhouse_url,
        &format!("OPTIMIZE TABLE {TABLE} FINAL"),
    )
    .await;
    // No FINAL here: after OPTIMIZE the stored rows themselves must be collapsed.
    let canonical = clickhouse(
        &http,
        &clickhouse_url,
        &format!("SELECT toString(event_timestamp), toString(inserted_at) FROM {TABLE} WHERE record_id = '{record_id}' FORMAT TSV"),
    )
    .await;
    let canonical: Vec<&str> = canonical.lines().collect();

    assert_eq!(
        canonical.len(),
        1,
        "expected one canonical row: {canonical:?}"
    );
    let (event_timestamp, inserted_at) = canonical[0].split_once('\t').unwrap();
    assert_eq!(event_timestamp, "2024-06-15 00:00:01.000000");
    // ReplacingMergeTree keeps the whole winning row, so the first ingest's
    // inserted_at is lost. Reads that need first-seen time must derive it.
    assert!(
        inserted_at >= between_ingests.as_str(),
        "inserted_at {inserted_at} came from the first ingest, before {between_ingests}"
    );

    let _ = shutdown.send(());
    server.await.unwrap();
}
