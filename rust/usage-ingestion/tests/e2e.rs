//! End-to-end check that a retried usage record collapses to one canonical row.

mod common;

use std::time::{Duration, Instant};

use common::{clickhouse, clickhouse_url, table, Service};
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageRecord, IngestBillingUsageRequest};
use uuid::Uuid;

/// Fixed so both rows land in one monthly partition, the scope ReplacingMergeTree collapses within.
const FIRST_EVENT_TIMESTAMP_MS: i64 = 1_718_409_600_000; // 2024-06-15T00:00:00Z

fn record(record_id: &str, timestamp_ms: i64) -> BillingUsageRecord {
    BillingUsageRecord {
        record_id: record_id.to_string(),
        producer_id: "usage-ingestion-e2e".to_string(),
        team_id: 1,
        usage_key: "e2e_records".to_string(),
        unit: "record".to_string(),
        quantity: 1,
        timestamp_ms,
    }
}

#[tokio::test]
#[ignore = "requires a local Kafka and ClickHouse with migration 0303; run with --ignored"]
async fn retried_record_with_original_timestamp_deduplicates() {
    let clickhouse_url = clickhouse_url();
    let table = table();
    let organization_id = Uuid::new_v4();
    let service = Service::start(500, organization_id).await;
    let mut client = service.client().await;

    let record_id = Uuid::new_v4().to_string();
    client
        .ingest_billing_usage(IngestBillingUsageRequest {
            records: vec![record(&record_id, FIRST_EVENT_TIMESTAMP_MS)],
        })
        .await
        .expect("the first ingest failed");
    tokio::time::sleep(Duration::from_millis(50)).await;
    client
        .ingest_billing_usage(IngestBillingUsageRequest {
            records: vec![record(&record_id, FIRST_EVENT_TIMESTAMP_MS)],
        })
        .await
        .expect("the retried ingest failed");

    let http = reqwest::Client::new();
    // Wait for the original record: each retry preserves the event timestamp.
    let arrival_query = format!(
        "SELECT count() FROM {table} WHERE record_id = '{record_id}' AND timestamp = toDateTime64('2024-06-15 00:00:00', 6, 'UTC')"
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
        &format!("OPTIMIZE TABLE {table} FINAL"),
    )
    .await;
    // No FINAL: after OPTIMIZE the stored rows themselves must be collapsed.
    let canonical = clickhouse(
        &http,
        &clickhouse_url,
        &format!(
            "SELECT toString(timestamp) FROM {table} WHERE record_id = '{record_id}' FORMAT TSV"
        ),
    )
    .await;
    let canonical: Vec<&str> = canonical.lines().collect();

    assert_eq!(
        canonical.len(),
        1,
        "expected one canonical row: {canonical:?}"
    );
    assert_eq!(canonical[0], "2024-06-15 00:00:00.000000");

    service.stop().await;
}
