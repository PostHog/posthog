//! Replays `nodejs/src/ingestion/pipelines/metrics/parity/fixtures`, which Node recorded, through the Rust consumer.

use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;
use std::sync::Arc;

use ingestion_framework::KafkaMessage;
use logs_ingestion::js::{json_parse, json_stringify, JsObject, JsString, JsValue};
use logs_ingestion::pipeline::scenario::{kafka_message, PinnedClock};
use logs_ingestion::rate_limiter::{RedisTokenBucket, TokenBucketRedis};
use metrics_ingestion::pipeline::retry::error_name;
use metrics_ingestion::pipeline::scenario::build_scenario_consumer;
use sha2::{Digest, Sha256};

// Database 10 keeps the FLUSHDB away from the dev stack (database 0) and the logs corpus (database 9).
const REDIS_URL: &str = "redis://127.0.0.1:6379/10";

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../nodejs/src/ingestion/pipelines/metrics/parity/fixtures")
}

fn get<'a>(value: &'a JsValue, key: &str) -> &'a JsValue {
    match value {
        JsValue::Object(o) => o.get(key).unwrap_or_else(|| panic!("missing key {key}")),
        _ => panic!("not an object looking up {key}"),
    }
}

fn array(value: &JsValue) -> &[JsValue] {
    match value {
        JsValue::Array(items) => items,
        other => panic!("not an array: {other:?}"),
    }
}

fn obj(entries: Vec<(&str, JsValue)>) -> JsValue {
    let mut o = JsObject::new();
    for (k, v) in entries {
        o.insert_str(k, v);
    }
    JsValue::Object(o)
}

fn num(n: f64) -> JsValue {
    JsValue::Number(n)
}

/// The default JavaScript sort: by UTF-16 code units.
fn js_sort_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}

fn sort_keys(value: &JsValue) -> JsValue {
    match value {
        JsValue::Array(items) => JsValue::Array(items.iter().map(sort_keys).collect()),
        JsValue::Object(o) => {
            let mut entries: Vec<(String, JsValue)> = o
                .iter()
                .map(|(k, v)| (k.to_utf8_lossy().into_owned(), sort_keys(v)))
                .collect();
            entries.sort_by(|(a, _), (b, _)| js_sort_cmp(a, b));
            let mut out = JsObject::new();
            for (k, v) in entries {
                out.insert(JsString::from(k), v);
            }
            JsValue::Object(out)
        }
        other => other.clone(),
    }
}

fn is_iso_timestamp(value: &str) -> bool {
    let b = value.as_bytes();
    let digits = |range: std::ops::Range<usize>| range.into_iter().all(|i| b[i].is_ascii_digit());
    b.len() == 24
        && digits(0..4)
        && b[4] == b'-'
        && digits(5..7)
        && b[7] == b'-'
        && digits(8..10)
        && b[10] == b'T'
        && digits(11..13)
        && b[13] == b':'
        && digits(14..16)
        && b[16] == b':'
        && digits(17..19)
        && b[19] == b'.'
        && digits(20..23)
        && b[23] == b'Z'
}

fn canonical_value(
    output: &str,
    value: Option<&[u8]>,
    inputs: &[(Vec<u8>, usize, usize)],
) -> JsValue {
    let Some(value) = value else {
        return obj(vec![("kind", JsValue::string("null"))]);
    };
    if let Some((_, batch, index)) = inputs.iter().find(|(bytes, _, _)| bytes == value) {
        return obj(vec![
            ("kind", JsValue::string("passthrough")),
            ("batch", num(*batch as f64)),
            ("index", num(*index as f64)),
        ]);
    }
    if output == "app_metrics" {
        let raw = String::from_utf8_lossy(value).into_owned();
        let json = sort_keys(&json_parse(&raw).unwrap());
        return obj(vec![
            ("kind", JsValue::string("json")),
            ("raw", JsValue::string(&raw)),
            ("json", json),
        ]);
    }
    let sha: String = Sha256::digest(value)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    obj(vec![
        ("kind", JsValue::string("bytes")),
        ("sha256", JsValue::string(&sha)),
        ("length", num(value.len() as f64)),
    ])
}

fn sorted_texts(values: impl IntoIterator<Item = JsValue>) -> Vec<String> {
    let mut texts: Vec<String> = values.into_iter().map(|v| json_stringify(&v)).collect();
    texts.sort_by(|a, b| js_sort_cmp(a, b));
    texts
}

fn diff(scenario: &str, what: &str, expected: &[String], actual: &[String]) -> Option<String> {
    if expected == actual {
        return None;
    }
    let mut missing: Vec<&String> = Vec::new();
    let mut extra: Vec<&String> = actual.iter().collect();
    for e in expected {
        match extra.iter().position(|a| *a == e) {
            Some(i) => {
                extra.remove(i);
            }
            None => missing.push(e),
        }
    }
    let mut out = format!(
        "\n== {scenario}: {what}: {} only in Node, {} only in Rust\n",
        missing.len(),
        extra.len()
    );
    for m in missing.iter().take(5) {
        out += &format!("  node: {m}\n");
    }
    for e in extra.iter().take(5) {
        out += &format!("  rust: {e}\n");
    }
    if missing.is_empty() && extra.is_empty() {
        out += "  same items, different order\n";
    }
    Some(out)
}

async fn run_scenario(
    path: &Path,
    redis: Arc<dyn TokenBucketRedis>,
    conn: &mut redis::aio::MultiplexedConnection,
) -> Option<String> {
    let text = std::fs::read_to_string(path).unwrap();
    let fixture = json_parse(&text).unwrap();
    let scenario = get(&fixture, "scenario");
    let expected = get(&fixture, "expected");
    let name = json_stringify(get(scenario, "name"));
    let _: () = redis::cmd("FLUSHDB").query_async(conn).await.unwrap();

    let clock = PinnedClock::new(0.0);
    let harness = build_scenario_consumer(scenario, redis, clock.clock());
    let batches: Vec<Vec<KafkaMessage>> = array(get(scenario, "batches"))
        .iter()
        .map(|b| array(b).iter().map(kafka_message).collect())
        .collect();
    let mut inputs: Vec<(Vec<u8>, usize, usize)> = Vec::new();
    for (b, batch) in batches.iter().enumerate() {
        for (i, m) in batch.iter().enumerate() {
            if let Some(v) = &m.value {
                inputs.push((v.to_vec(), b, i));
            }
        }
    }
    let clocks = array(get(scenario, "batch_now_ms"));
    let mut batch_results = Vec::new();
    for (b, batch) in batches.into_iter().enumerate() {
        harness
            .outputs
            .current_batch
            .store(b as u64, Ordering::SeqCst);
        if let JsValue::Number(ms) = &clocks[b] {
            clock.set(*ms);
        }
        let result = match harness.consumer.handle_kafka_batch(batch).await {
            Ok(task) => task.await,
            Err(e) => Err(e),
        };
        batch_results.push(obj(vec![(
            "error",
            match result {
                Ok(()) => JsValue::Null,
                Err(e) => JsValue::string(&error_name(&e)),
            },
        )]));
    }

    let mut problems = String::new();
    let mut check = |what: &str, expected: Vec<String>, actual: Vec<String>| {
        if let Some(d) = diff(&name, what, &expected, &actual) {
            problems += &d;
        }
    };
    check(
        "batches",
        array(get(expected, "batches"))
            .iter()
            .map(json_stringify)
            .collect(),
        batch_results.iter().map(json_stringify).collect(),
    );

    let captured = harness.outputs.captured.lock().unwrap().clone();
    let actual_outputs: Vec<JsValue> = captured
        .iter()
        .map(|c| {
            let mut headers: Vec<(String, String)> = c.message.headers.iter().cloned().collect();
            headers.sort_by(|a, b| js_sort_cmp(&a.0, &b.0));
            let mut h = JsObject::new();
            for (k, v) in headers {
                let v = if k == "dlq_timestamp" && is_iso_timestamp(&v) {
                    "<iso>".to_string()
                } else {
                    v
                };
                h.insert(JsString::from(k), JsValue::string(&v));
            }
            obj(vec![
                ("batch", num(c.batch as f64)),
                ("output", JsValue::string(&c.output)),
                (
                    "key",
                    match &c.message.key {
                        Some(k) => JsValue::string(&String::from_utf8_lossy(k)),
                        None => JsValue::Null,
                    },
                ),
                ("headers", JsValue::Object(h)),
                (
                    "value",
                    canonical_value(&c.output, c.message.value.as_deref(), &inputs),
                ),
            ])
        })
        .collect();
    // The output order is not a contract, so outputs compare as a multiset per output kind.
    let expected_outputs = array(get(expected, "outputs")).to_vec();
    for kind in ["metrics", "dlq", "app_metrics"] {
        let pick = |v: &JsValue| matches!(get(v, "output"), JsValue::String(s) if *s == kind);
        check(
            &format!("outputs[{kind}]"),
            sorted_texts(expected_outputs.iter().filter(|v| pick(v)).cloned()),
            sorted_texts(actual_outputs.iter().filter(|v| pick(v)).cloned()),
        );
    }
    check(
        "outputs[all]",
        sorted_texts(expected_outputs.iter().cloned()),
        sorted_texts(actual_outputs),
    );

    let recorded = &harness.recorded;
    let usage = recorded.usage_rows.lock().unwrap().clone();
    check(
        "usage_records",
        sorted_texts(array(get(expected, "usage_records")).iter().cloned()),
        sorted_texts(usage.iter().map(|r| {
            obj(vec![
                ("batch", num(r.batch as f64)),
                ("team_id", num(r.team_id as f64)),
                ("usage_key", JsValue::string(&r.usage_key)),
                ("record_id", JsValue::string(&r.record_id)),
                ("quantity", num(r.quantity)),
                ("unit", JsValue::string(&r.unit)),
                (
                    "timestamp_ms",
                    r.timestamp_ms.map_or(JsValue::Null, |t| num(t as f64)),
                ),
            ])
        })),
    );
    check(
        "teams_ingested",
        array(get(expected, "teams_ingested"))
            .iter()
            .map(json_stringify)
            .collect(),
        recorded
            .teams_ingested
            .lock()
            .unwrap()
            .iter()
            .map(|ids| {
                json_stringify(&JsValue::Array(
                    ids.iter().map(|t| num(*t as f64)).collect(),
                ))
            })
            .collect(),
    );
    check(
        "quota_checks",
        array(get(expected, "quota_checks"))
            .iter()
            .map(json_stringify)
            .collect(),
        sorted_texts(
            recorded
                .quota_checks
                .lock()
                .unwrap()
                .iter()
                .map(|(t, r)| JsValue::Array(vec![JsValue::string(t), JsValue::string(r)])),
        ),
    );
    // Node's harness records no unknown tokens, so this expectation comes from the scenarios. Only `drops` has a
    // token that belongs to no team. A token whose lookup failed must not be recorded.
    check(
        "unknown_tokens",
        if name == "\"drops\"" {
            vec!["token-unknown".to_string()]
        } else {
            Vec::new()
        },
        recorded.unknown_tokens.lock().unwrap().clone(),
    );
    (!problems.is_empty()).then_some(problems)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rust_consumer_reproduces_the_node_metrics_parity_corpus() {
    let client = redis::Client::open(REDIS_URL).unwrap();
    let mut conn = match client.get_multiplexed_async_connection().await {
        Ok(c) => c,
        Err(e) => {
            assert!(
                std::env::var_os("CI").is_none(),
                "no Redis at {REDIS_URL}: {e}"
            );
            eprintln!("skipping: no Redis at {REDIS_URL}: {e}");
            return;
        }
    };
    let redis: Arc<dyn TokenBucketRedis> = Arc::new(RedisTokenBucket::new(conn.clone()));
    let mut paths: Vec<PathBuf> = std::fs::read_dir(fixtures_dir())
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .collect();
    paths.sort();
    assert!(!paths.is_empty());
    let mut failures = String::new();
    for path in &paths {
        if let Some(problems) = run_scenario(path, redis.clone(), &mut conn).await {
            failures += &problems;
        }
    }
    assert!(failures.is_empty(), "{failures}");
}
