//! Load check: thousands of concurrent requests over varied data, a tenth of them retries.
//!
//! The printed percentiles matter as much as the assertions. Raise the request count with
//! `--nocapture` to find where a machine stops scaling. See the crate README.

mod common;

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use common::{clickhouse, clickhouse_url, env_usize, table, Service};
use redis::cluster::ClusterClient;
use redis::AsyncCommands;
use tokio::sync::Semaphore;
use usage_ingestion::counters::{
    counter_key, flush, Bucket, CounterAccumulator, CounterScope, CounterStore, RedisCounterStore,
};
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageRecord, IngestBillingUsageRequest};
use uuid::Uuid;

/// Midnight UTC, so the whole run shares one `toDate(timestamp)` and one monthly partition.
fn base_timestamp_ms() -> i64 {
    Utc::now()
        .date_naive()
        .and_hms_opt(0, 0, 0)
        .unwrap()
        .and_utc()
        .timestamp_millis()
}
/// An hour after the original: a different `timestamp` but the same day, which is the window
/// the sorting key deduplicates within. Producers stamp flush time, so a retry does move it.
const RETRY_OFFSET_MS: i64 = 3_600_000;

const BASELINE_REQUESTS: usize = 32;
/// Sequential latency is dominated by the producer's 20ms linger, so there is a lot of
/// headroom for concurrency to reclaim. Real runs clear 100x; serialization lands under 2x.
const MIN_THROUGHPUT_SPEEDUP: f64 = 5.0;
const TEAMS: usize = 8;
const BUCKETS_PER_SCOPE: usize = 3;
const MIN_BYTES_PER_COUNTER_KEY: usize = 64;
// This is the Redis budget for one hourly or daily hash with the four usage fields below.
// Raise it deliberately when adding counter series, rather than letting per-request data grow it.
const MAX_BYTES_PER_COUNTER_KEY: usize = 1024;
/// Only a tenth of the requests are retries, and they alone fill the retry hour bucket. It
/// needs every team and usage key for the counter assertions to hold.
const MIN_REQUESTS: usize = TEAMS * USAGE_KEYS.len() * 10;

const USAGE_KEYS: [(&str, &str); 4] = [
    ("events_captured", "event"),
    ("flag_requests", "request"),
    ("recordings_ingested", "recording"),
    ("queries_executed", "query"),
];

/// A retry reuses the sorting key `(team_id, toDate(timestamp), producer_id, usage_key,
/// record_id)` while moving `timestamp` within the day. Narrowing the key's date to the exact
/// timestamp makes this test fail with double the rows.
fn record(
    run: &str,
    index: usize,
    retry: bool,
    first_team_id: i64,
    base_timestamp_ms: i64,
) -> BillingUsageRecord {
    let (usage_key, unit) = USAGE_KEYS[(index / TEAMS) % USAGE_KEYS.len()];
    let event_offset_ms = (index % 60_000) as i64;
    BillingUsageRecord {
        record_id: format!("{run}:{index}"),
        producer_id: "usage-ingestion-load".to_string(),
        team_id: first_team_id + (index % TEAMS) as i64,
        usage_key: usage_key.to_string(),
        unit: unit.to_string(),
        quantity: 1 + (index % 100) as i64,
        timestamp_ms: base_timestamp_ms + event_offset_ms + if retry { RETRY_OFFSET_MS } else { 0 },
    }
}

fn redis_url() -> String {
    std::env::var("USAGE_INGESTION_REDIS_URL")
        .unwrap_or_else(|_| "redis://127.0.0.1:6390".to_string())
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
    assert!(
        requests >= MIN_REQUESTS,
        "USAGE_INGESTION_E2E_LOAD_REQUESTS must be at least {MIN_REQUESTS}"
    );
    assert!(concurrency >= 1 && channels >= 1);

    let retries = requests / 10;
    let unique = requests - retries;
    let run = Uuid::new_v4().to_string();
    let base_timestamp_ms = base_timestamp_ms();
    let first_team_id = 1 + (Uuid::new_v4().as_u128() % (i32::MAX as u128 - TEAMS as u128)) as i64;
    let organization_id = Uuid::new_v4();
    let accumulator = Arc::new(CounterAccumulator::default());
    let store: Arc<dyn CounterStore> = Arc::new(
        RedisCounterStore::connect(&redis_url())
            .await
            .expect("failed to connect to Valkey Cluster"),
    );

    let clickhouse_url = clickhouse_url();
    let table = table();
    let service = Service::start(500, organization_id, Some(Arc::clone(&accumulator))).await;

    // Measured here, not hardcoded, so the throughput assertion is not a hardware guess.
    let mut baseline_client = service.client().await;
    let mut baseline_latencies = Vec::with_capacity(BASELINE_REQUESTS);
    let baseline_started = Instant::now();
    for index in unique..unique + BASELINE_REQUESTS {
        let started = Instant::now();
        baseline_client
            .ingest_billing_usage(IngestBillingUsageRequest {
                records: vec![record(&run, index, false, first_team_id, base_timestamp_ms)],
            })
            .await
            .expect("a baseline ingest failed");
        baseline_latencies.push(started.elapsed());
    }
    let baseline_throughput = BASELINE_REQUESTS as f64 / baseline_started.elapsed().as_secs_f64();
    baseline_latencies.sort();

    let mut plan: Vec<BillingUsageRecord> = (0..unique)
        .map(|index| record(&run, index, false, first_team_id, base_timestamp_ms))
        .chain(
            (0..retries).map(|index| record(&run, index, true, first_team_id, base_timestamp_ms)),
        )
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

    let outcome = flush(Arc::clone(&store), accumulator.drain()).await;
    assert_eq!(
        (outcome.dropped, outcome.capped),
        (0, 0),
        "Valkey dropped counter deltas under request load"
    );
    assert_eq!(
        outcome.commands,
        (TEAMS + 1) * USAGE_KEYS.len() * BUCKETS_PER_SCOPE * 2,
        "the service should aggregate request counters by scope and series"
    );

    let client = ClusterClient::new([redis_url()]).expect("invalid Valkey Cluster URL");
    let mut redis = client
        .get_async_connection()
        .await
        .expect("failed to connect to Valkey Cluster");
    let timestamp = DateTime::<Utc>::from_timestamp_millis(base_timestamp_ms).unwrap();
    let retry_timestamp =
        DateTime::<Utc>::from_timestamp_millis(base_timestamp_ms + RETRY_OFFSET_MS).unwrap();
    let buckets = [
        Bucket::Hour(timestamp.timestamp().div_euclid(60 * 60)),
        Bucket::Hour(retry_timestamp.timestamp().div_euclid(60 * 60)),
        Bucket::Day(timestamp.timestamp().div_euclid(24 * 60 * 60)),
    ];
    let scopes = (0..TEAMS)
        .map(|offset| CounterScope::Team(first_team_id + offset as i64))
        .chain(std::iter::once(CounterScope::Organization(organization_id)));
    let mut counter_bytes = 0;
    for scope in scopes {
        for bucket in buckets {
            let key = counter_key(&scope, bucket);
            let fields: usize = redis
                .hlen(&key)
                .await
                .expect("failed to count counter fields");
            assert_eq!(
                fields,
                USAGE_KEYS.len(),
                "counter key {key} grew per request"
            );
            let bytes: usize = redis::cmd("MEMORY")
                .arg("USAGE")
                .arg(&key)
                .query_async(&mut redis)
                .await
                .expect("failed to measure counter key memory");
            counter_bytes += bytes;
        }
    }
    let counter_keys = (TEAMS + 1) * BUCKETS_PER_SCOPE;
    assert!(
        (counter_keys * MIN_BYTES_PER_COUNTER_KEY..=counter_keys * MAX_BYTES_PER_COUNTER_KEY)
            .contains(&counter_bytes),
        "counter keyspace used {counter_bytes} bytes across {counter_keys} keys; expected {}..={} bytes",
        counter_keys * MIN_BYTES_PER_COUNTER_KEY,
        counter_keys * MAX_BYTES_PER_COUNTER_KEY,
    );
    println!("Valkey counter keyspace: {counter_bytes} bytes across {counter_keys} keys");

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
