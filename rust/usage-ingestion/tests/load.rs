//! Load check for the gRPC service: thousands of concurrent single-record
//! requests across varied teams, organizations, usage keys and modes, a tenth of
//! them retries of an earlier record.
//!
//! It asserts three things. Every request succeeds, so nothing is lost to a full
//! producer queue or an exhausted connection. Concurrent throughput far exceeds
//! the sequential baseline measured on the same machine, so no lock or single
//! worker is serializing the request path. And ClickHouse ends up with exactly
//! one row per distinct record, each retry having won on event timestamp.
//!
//! The reported percentiles are the point of the test as much as the assertions
//! are: run it with `--nocapture` and raise the request count to find where this
//! machine's throughput stops scaling.

mod common;

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common::{clickhouse, clickhouse_url, env_usize, Service, TABLE};
use tokio::sync::Semaphore;
use usage_ingestion_proto::usage_ingestion::v1::{
    IngestUsageRecordsRequest, UsageMode, UsageRecord,
};
use uuid::Uuid;

/// Same fixed month as the deduplication test, so every row lands in one
/// partition. Originals spread over the first minute; retries sit an hour later,
/// which makes "the retry won" a single countable predicate.
const BASE_EVENT_TIMESTAMP_MS: i64 = 1_718_409_600_000; // 2024-06-15T00:00:00Z
const RETRY_OFFSET_MS: i64 = 3_600_000;
const RETRY_BOUNDARY: &str = "2024-06-15 01:00:00";

const BASELINE_REQUESTS: usize = 32;
/// Sequential latency is dominated by the producer's 20ms linger, so concurrency
/// has a lot of headroom to reclaim. Anything serializing the request path lands
/// far below this.
const MIN_THROUGHPUT_SPEEDUP: f64 = 5.0;

const USAGE_KEYS: [(&str, &str); 4] = [
    ("events_captured", "event"),
    ("flag_requests", "request"),
    ("recordings_ingested", "recording"),
    ("queries_executed", "query"),
];

/// Builds one request's record. `index` identifies the record; `retry` re-sends
/// the same identity with a later event timestamp, so it must leave every field
/// in the table's sorting key — team_id, producer_id, record_id, version —
/// untouched.
fn record(run: &str, organizations: &[Uuid], index: usize, retry: bool) -> UsageRecord {
    let (usage_key, unit) = USAGE_KEYS[index % USAGE_KEYS.len()];
    let event_offset_ms = (index % 60_000) as i64;
    UsageRecord {
        record_id: format!("{run}:{index}"),
        producer_id: "usage-ingestion-load".to_string(),
        team_id: 1 + (index % 8) as i64,
        organization_id: Some(organizations[index % organizations.len()].to_string()),
        usage_key: usage_key.to_string(),
        mode: if index.is_multiple_of(7) {
            UsageMode::Snapshot as i32
        } else {
            UsageMode::Delta as i32
        },
        unit: unit.to_string(),
        quantity: 1 + (index % 100) as i64,
        version: 1 + (index % 3) as u64,
        event_timestamp_ms: BASE_EVENT_TIMESTAMP_MS
            + event_offset_ms
            + if retry { RETRY_OFFSET_MS } else { 0 },
        source_ref: None,
        user_id: None,
        variant: Some(format!("variant-{}", index % 5)),
        dimensions: [("region".to_string(), format!("region-{}", index % 3))]
            .into_iter()
            .collect(),
    }
}

fn percentile(sorted: &[Duration], fraction: f64) -> Duration {
    let index = ((sorted.len() as f64 * fraction) as usize).min(sorted.len() - 1);
    sorted[index]
}

#[tokio::test(flavor = "multi_thread")]
#[ignore = "load test: needs a local Kafka and ClickHouse with migration 0301; run with --ignored --nocapture"]
async fn sustains_thousands_of_concurrent_requests() {
    let requests = env_usize("USAGE_INGESTION_E2E_LOAD_REQUESTS", 5_000);
    let concurrency = env_usize("USAGE_INGESTION_E2E_LOAD_CONCURRENCY", 128);
    let channels = env_usize("USAGE_INGESTION_E2E_LOAD_CHANNELS", 8);
    assert!(requests >= 100 && concurrency >= 1 && channels >= 1);

    let retries = requests / 10;
    let unique = requests - retries;
    let run = Uuid::new_v4().to_string();
    let organizations: Vec<Uuid> = (0..4).map(|_| Uuid::new_v4()).collect();

    let clickhouse_url = clickhouse_url();
    let service = Service::start(500).await;

    // Sequential baseline on this machine, so the throughput assertion below is
    // not a hardware guess. Its records use the run prefix too, keeping the
    // ClickHouse assertions to a single filter.
    let mut baseline_client = service.client().await;
    let mut baseline_latencies = Vec::with_capacity(BASELINE_REQUESTS);
    let baseline_started = Instant::now();
    for index in unique..unique + BASELINE_REQUESTS {
        let started = Instant::now();
        baseline_client
            .ingest(IngestUsageRecordsRequest {
                records: vec![record(&run, &organizations, index, false)],
            })
            .await
            .expect("a baseline ingest failed");
        baseline_latencies.push(started.elapsed());
    }
    let baseline_throughput = BASELINE_REQUESTS as f64 / baseline_started.elapsed().as_secs_f64();
    baseline_latencies.sort();

    let mut plan: Vec<UsageRecord> = (0..unique)
        .map(|index| record(&run, &organizations, index, false))
        .chain((0..retries).map(|index| record(&run, &organizations, index, true)))
        .collect();
    // Mix retries among originals so arrival order does not match event order:
    // a retry that lands before its original must still win deduplication.
    plan.sort_by_key(|record| {
        let mut hasher = DefaultHasher::new();
        (&record.record_id, record.event_timestamp_ms).hash(&mut hasher);
        hasher.finish()
    });

    let mut clients = Vec::with_capacity(channels);
    for _ in 0..channels {
        clients.push(service.client().await);
    }
    let permits = Arc::new(Semaphore::new(concurrency));
    let load_started = Instant::now();
    let tasks: Vec<_> = plan
        .into_iter()
        .enumerate()
        .map(|(slot, record)| {
            let mut client = clients[slot % channels].clone();
            let permits = permits.clone();
            tokio::spawn(async move {
                let _permit = permits.acquire().await.unwrap();
                let started = Instant::now();
                let result = client
                    .ingest(IngestUsageRecordsRequest {
                        records: vec![record],
                    })
                    .await;
                (started.elapsed(), result.err())
            })
        })
        .collect();

    let mut latencies = Vec::with_capacity(requests);
    let mut failures = Vec::new();
    for task in tasks {
        let (latency, error) = task.await.expect("an ingest task panicked");
        latencies.push(latency);
        if let Some(error) = error {
            failures.push(error);
        }
    }
    let elapsed = load_started.elapsed();
    let throughput = requests as f64 / elapsed.as_secs_f64();
    latencies.sort();

    println!(
        "sequential baseline: {} requests, p50 {:?}, {:.0} req/s",
        BASELINE_REQUESTS,
        percentile(&baseline_latencies, 0.50),
        baseline_throughput,
    );
    println!(
        "concurrent load: {requests} requests ({retries} retries) at concurrency {concurrency} over {channels} channels in {elapsed:?}, {throughput:.0} req/s ({:.1}x baseline)",
        throughput / baseline_throughput,
    );
    println!(
        "latency: p50 {:?}, p95 {:?}, p99 {:?}, max {:?}",
        percentile(&latencies, 0.50),
        percentile(&latencies, 0.95),
        percentile(&latencies, 0.99),
        latencies.last().unwrap(),
    );

    assert!(
        failures.is_empty(),
        "{} of {requests} requests failed, first: {:?}",
        failures.len(),
        failures[0]
    );
    assert!(
        throughput >= baseline_throughput * MIN_THROUGHPUT_SPEEDUP,
        "concurrency bought only {:.1}x the sequential throughput; the request path is serializing",
        throughput / baseline_throughput,
    );

    let http = reqwest::Client::new();
    let expected_rows = unique + BASELINE_REQUESTS;
    let arrival_query =
        format!("SELECT uniqExact(record_id) FROM {TABLE} WHERE startsWith(record_id, '{run}:')");
    let deadline = Instant::now() + Duration::from_secs(300);
    loop {
        let arrived = clickhouse(&http, &clickhouse_url, &arrival_query)
            .await
            .trim()
            .to_string();
        if arrived == expected_rows.to_string() {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "only {arrived} of {expected_rows} distinct records reached ClickHouse"
        );
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    clickhouse(
        &http,
        &clickhouse_url,
        &format!("OPTIMIZE TABLE {TABLE} FINAL"),
    )
    .await;
    // No FINAL: after OPTIMIZE the stored rows themselves must be collapsed.
    let summary = clickhouse(
        &http,
        &clickhouse_url,
        &format!(
            "SELECT count(), countIf(event_timestamp >= toDateTime64('{RETRY_BOUNDARY}', 6, 'UTC')) FROM {TABLE} WHERE startsWith(record_id, '{run}:') FORMAT TSV"
        ),
    )
    .await;

    assert_eq!(
        summary.trim(),
        format!("{expected_rows}\t{retries}"),
        "expected {expected_rows} canonical rows with {retries} won by a retry"
    );

    service.stop().await;
}
