//! The unknown-token recorder against a real Redis, and its wiring into the consumer. Skips when Redis is down.

mod common;

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use common::{array, get, load_json, scenarios_dir};
use ingestion_framework::KafkaMessage;
use logs_ingestion::js::JsValue;
use logs_ingestion::pipeline::scenario::{kafka_message, scenario_parts, PinnedClock};
use logs_ingestion::pipeline::LogsIngestionConsumer;
use logs_ingestion::rate_limiter::RedisTokenBucket;
use logs_ingestion::service::shadow_deps;
use logs_ingestion::unknown_tokens::{
    UnknownTokenRecorder, UnknownTokens, UNKNOWN_TOKENS_MAX_ENTRIES, UNKNOWN_TOKEN_CONFIRM_MS,
    UNKNOWN_TOKEN_RETENTION_MS,
};
use redis::aio::MultiplexedConnection;

// Its own database, so the FLUSHDB of the parity corpus (database 9) and the dev stack (database 0) are untouched.
const REDIS_URL: &str = "redis://127.0.0.1:6379/11";
const KEY: &str = "@posthog-test/capture_logs:unknown_tokens";

async fn connect() -> Option<MultiplexedConnection> {
    let client = redis::Client::open(REDIS_URL).unwrap();
    match client.get_multiplexed_async_connection().await {
        Ok(conn) => Some(conn),
        Err(e) => {
            eprintln!("skipping: no Redis at {REDIS_URL}: {e}");
            None
        }
    }
}

#[derive(Default)]
struct RecordedTokens(Mutex<Vec<String>>);

impl UnknownTokens for RecordedTokens {
    fn record(&self, token: &str) {
        self.0.lock().unwrap().push(token.to_string());
    }
}

/// `parse-failures` sends a token with no team, a failed and an unavailable lookup, and empty and missing tokens.
/// Only the token with no team is recorded, as in Node's parse step.
#[tokio::test]
async fn records_only_tokens_whose_lookup_found_no_team() {
    let Some(mut conn) = connect().await else {
        return;
    };
    let _: () = redis::cmd("FLUSHDB").query_async(&mut conn).await.unwrap();
    let fixture = load_json(&scenarios_dir().join("parse-failures.json"));
    let scenario = get(&fixture, "scenario");
    let clock = PinnedClock::new(match &array(get(scenario, "batch_now_ms"))[0] {
        JsValue::Number(n) => *n,
        _ => 0.0,
    });
    let mut parts = scenario_parts(
        scenario,
        Arc::new(RedisTokenBucket::new(conn)),
        clock.clock(),
        false,
    );
    let recorded = Arc::new(RecordedTokens::default());
    parts.deps.unknown_tokens = Some(recorded.clone());
    let consumer = LogsIngestionConsumer::new(parts.identity, parts.config, parts.deps);
    for batch in array(get(scenario, "batches")) {
        let messages: Vec<KafkaMessage> = array(batch).iter().map(kafka_message).collect();
        if let Some(task) = consumer
            .process_kafka_batch(messages)
            .await
            .unwrap()
            .background_task
        {
            task.await.unwrap();
        }
    }
    assert_eq!(*recorded.0.lock().unwrap(), vec!["phc_unknown_token"]);
}

#[tokio::test]
async fn shadow_mode_records_nothing() {
    let Some(conn) = connect().await else {
        return;
    };
    let fixture = load_json(&scenarios_dir().join("parse-failures.json"));
    let mut parts = scenario_parts(
        get(&fixture, "scenario"),
        Arc::new(RedisTokenBucket::new(conn)),
        PinnedClock::new(0.0).clock(),
        false,
    );
    parts.deps.unknown_tokens = Some(Arc::new(RecordedTokens::default()));
    assert!(shadow_deps(parts.deps).unknown_tokens.is_none());
}

/// The recorder's pipeline against Redis itself: the score, the key TTL, and both trims.
#[tokio::test]
async fn a_write_scores_the_token_and_keeps_the_set_within_its_age_and_size_caps() {
    let Some(mut conn) = connect().await else {
        return;
    };
    let _: () = redis::cmd("DEL")
        .arg(KEY)
        .query_async(&mut conn)
        .await
        .unwrap();
    let start = 1_700_000_000_000u64;
    let now = Arc::new(AtomicU64::new(start));
    let clock_now = now.clone();
    let recorder = UnknownTokenRecorder::with_key(
        conn.clone(),
        Arc::new(move || clock_now.load(Ordering::SeqCst) as f64),
        KEY,
    );
    let write_at = start + UNKNOWN_TOKEN_CONFIRM_MS as u64;

    // One entry past retention, then a full set of fresh ones, so the write must trim by age and by rank.
    let mut fill = redis::pipe();
    fill.zadd(
        KEY,
        "token-expired",
        write_at - UNKNOWN_TOKEN_RETENTION_MS as u64 - 1,
    );
    for chunk in (0..UNKNOWN_TOKENS_MAX_ENTRIES)
        .collect::<Vec<_>>()
        .chunks(10_000)
    {
        let members: Vec<(u64, String)> = chunk
            .iter()
            .map(|i| {
                (
                    write_at - 1_000 + (*i as u64 % 1_000),
                    format!("token-fresh-{i}"),
                )
            })
            .collect();
        fill.zadd_multiple(KEY, &members);
    }
    let _: () = fill.query_async(&mut conn).await.unwrap();

    recorder.record("token-unknown");
    now.store(write_at, Ordering::SeqCst);
    recorder.record("token-unknown");
    for _ in 0..200 {
        if recorder.in_flight_writes() == 0 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert_eq!(recorder.in_flight_writes(), 0);

    let score: Option<f64> = redis::cmd("ZSCORE")
        .arg(KEY)
        .arg("token-unknown")
        .query_async(&mut conn)
        .await
        .unwrap();
    assert_eq!(score, Some(write_at as f64));
    let expired: Option<f64> = redis::cmd("ZSCORE")
        .arg(KEY)
        .arg("token-expired")
        .query_async(&mut conn)
        .await
        .unwrap();
    assert_eq!(expired, None);
    let size: usize = redis::cmd("ZCARD")
        .arg(KEY)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert_eq!(size, UNKNOWN_TOKENS_MAX_ENTRIES);
    let ttl: i64 = redis::cmd("TTL")
        .arg(KEY)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!((7_190..=7_200).contains(&ttl), "ttl {ttl}");

    let _: () = redis::cmd("DEL")
        .arg(KEY)
        .query_async(&mut conn)
        .await
        .unwrap();
}
