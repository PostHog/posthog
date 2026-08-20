//! End-to-end check that a retried usage record collapses to one canonical row.

mod common;

use std::time::{Duration, Instant};

use chrono::Utc;
use common::{clickhouse, clickhouse_url, table, Service};
use usage_ingestion_proto::usage_ingestion::v1::{
    IngestUsageRecordsRequest, UsageMode, UsageRecord,
};
use uuid::Uuid;

/// Fixed so both rows land in one monthly partition, the scope ReplacingMergeTree collapses within.
const FIRST_EVENT_TIMESTAMP_MS: i64 = 1_718_409_600_000; // 2024-06-15T00:00:00Z
const RETRY_EVENT_TIMESTAMP_MS: i64 = FIRST_EVENT_TIMESTAMP_MS + 1_000;

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
#[ignore = "requires a local Kafka and ClickHouse with migration 0302; run with --ignored"]
async fn retried_record_deduplicates_to_the_latest_event_timestamp() {
    let clickhouse_url = clickhouse_url();
    let table = table();
    let service = Service::start(500).await;
    let mut client = service.client().await;

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
    // Milliseconds: the precision the service serializes inserted_at at.
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
        "SELECT count() FROM {table} WHERE record_id = '{record_id}' AND event_timestamp = toDateTime64('2024-06-15 00:00:01', 6, 'UTC')"
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
        &format!("SELECT toString(event_timestamp), toString(inserted_at) FROM {table} WHERE record_id = '{record_id}' FORMAT TSV"),
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
    // ReplacingMergeTree replaces the whole row, so the first inserted_at is lost.
    assert!(
        inserted_at >= between_ingests.as_str(),
        "inserted_at {inserted_at} came from the first ingest, before {between_ingests}"
    );

    service.stop().await;
}
