//! Load check: thousands of concurrent requests over varied data, a tenth of them retries.
//!
//! The printed percentiles matter as much as the assertions. Raise the request count with
//! `--nocapture` to find where a machine stops scaling. See the crate README.

mod common;

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common::{clickhouse, clickhouse_url, env_usize, table, Service};
use tokio::sync::Semaphore;
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageRecord, IngestBillingUsageRequest};
use uuid::Uuid;

/// Midnight UTC, so the whole run shares one `toDate(timestamp)` and one monthly partition.
const BASE_TIMESTAMP_MS: i64 = 1_718_409_600_000; // 2024-06-15T00:00:00Z
/// An hour after the original: a different `timestamp` but the same day, which is the window
/// the sorting key deduplicates within. Producers stamp flush time, so a retry does move it.
const RETRY_OFFSET_MS: i64 = 3_600_000;

const BASELINE_REQUESTS: usize = 32;
/// Sequential latency is dominated by the producer's 20ms linger, so there is a lot of
/// headroom for concurrency to reclaim. Real runs clear 100x; serialization lands under 2x.
const MIN_THROUGHPUT_SPEEDUP: f64 = 5.0;

const USAGE_KEYS: [(&str, &str); 4] = [
    ("events_captured", "event"),
    ("flag_requests", "request"),
    ("recordings_ingested", "recording"),
    ("queries_executed", "query"),
];

/// A retry reuses the sorting key `(team_id, toDate(timestamp), producer_id, usage_key,
/// record_id)` while moving `timestamp` within the day. Narrowing the key's date to the exact
/// timestamp makes this test fail with double the rows.
fn record(run: &str, index: usize, retry: bool) -> BillingUsageRecord {
    let (usage_key, unit) = USAGE_KEYS[index % USAGE_KEYS.len()];
    let event_offset_ms = (index % 60_000) as i64;
    BillingUsageRecord {
        record_id: format!("{run}:{index}"),
        producer_id: "usage-ingestion-load".to_string(),
        team_id: 1 + (index % 8) as i64,
        usage_key: usage_key.to_string(),
        unit: unit.to_string(),
        quantity: 1 + (index % 100) as i64,
        timestamp_ms: BASE_TIMESTAMP_MS + event_offset_ms + if retry { RETRY_OFFSET_MS } else { 0 },
    }
}

fn percentile(sorted: &[Duration], fraction: f64) -> Duration {
    let index = ((sorted.len() as f64 * fraction) as usize).min(sorted.len() - 1);
    sorted[index]
}

#[tokio::test(flavor = "multi_thread")]
#[ignore = "load test: needs a local Kafka and ClickHouse with migration 0303; run with --ignored --nocapture"]
async fn sustains_thousands_of_concurrent_requests() {
    let requests = env_usize("USAGE_INGESTION_E2E_LOAD_REQUESTS", 5_000);
    let concurrency = env_usize("USAGE_INGESTION_E2E_LOAD_CONCURRENCY", 128);
    let channels = env_usize("USAGE_INGESTION_E2E_LOAD_CHANNELS", 8);
    assert!(requests >= 100 && concurrency >= 1 && channels >= 1);

    let retries = requests / 10;
    let unique = requests - retries;
    let run = Uuid::new_v4().to_string();

    let clickhouse_url = clickhouse_url();
    let table = table();
    let service = Service::start(500, Uuid::new_v4()).await;

    // Measured here, not hardcoded, so the throughput assertion is not a hardware guess.
    let mut baseline_client = service.client().await;
    let mut baseline_latencies = Vec::with_capacity(BASELINE_REQUESTS);
    let baseline_started = Instant::now();
    for index in unique..unique + BASELINE_REQUESTS {
        let started = Instant::now();
        baseline_client
            .ingest_billing_usage(IngestBillingUsageRequest {
                records: vec![record(&run, index, false)],
            })
            .await
            .expect("a baseline ingest failed");
        baseline_latencies.push(started.elapsed());
    }
    let baseline_throughput = BASELINE_REQUESTS as f64 / baseline_started.elapsed().as_secs_f64();
    baseline_latencies.sort();

    let mut plan: Vec<BillingUsageRecord> = (0..unique)
        .map(|index| record(&run, index, false))
        .chain((0..retries).map(|index| record(&run, index, true)))
        .collect();
    // Arrival order must not match event order: a retry landing before its original still has
    // to collapse to one row.
    plan.sort_by_key(|record| {
        let mut hasher = DefaultHasher::new();
        (&record.record_id, record.timestamp_ms).hash(&mut hasher);
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
                    .ingest_billing_usage(IngestBillingUsageRequest {
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
        format!("SELECT uniqExact(record_id) FROM {table} WHERE startsWith(record_id, '{run}:')");
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
        &format!("OPTIMIZE TABLE {table} FINAL"),
    )
    .await;
    // No FINAL in the read: after the merge the stored rows themselves must be collapsed. This
    // merge covers every row the run inserted rather than the handful the e2e test writes, so
    // poll instead of assuming OPTIMIZE returned with all parts already merged.
    //
    // Which of the two survives is not asserted: `ver` is inserted_at, so the copy that
    // arrived second wins, and arrival order here is deliberately shuffled.
    let collapse_query =
        format!("SELECT count() FROM {table} WHERE startsWith(record_id, '{run}:') FORMAT TSV");
    let collapse_deadline = Instant::now() + Duration::from_secs(60);
    loop {
        let stored = clickhouse(&http, &clickhouse_url, &collapse_query)
            .await
            .trim()
            .to_string();
        if stored == expected_rows.to_string() {
            break;
        }
        assert!(
            Instant::now() < collapse_deadline,
            "{retries} retries did not collapse: {stored} rows, expected {expected_rows}"
        );
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    service.stop().await;
}
