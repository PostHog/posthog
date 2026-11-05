mod common;

use std::sync::Arc;

use common::{array, canonical, get, js_sort_cmp, load_json, scenarios_dir, string};
use ingestion_framework::KafkaMessage;
use logs_ingestion::avro::decode_container;
use logs_ingestion::js::{json_parse, json_stringify, JsObject, JsString, JsValue};
use logs_ingestion::pipeline::errors::error_name;
use logs_ingestion::pipeline::scenario::{
    build_scenario_consumer, kafka_message, PinnedClock, UsageRow,
};
use logs_ingestion::rate_limiter::{RedisTokenBucket, TokenBucketRedis};
use sha2::{Digest, Sha256};

const REDIS_URL: &str = "redis://127.0.0.1:6379";

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

/// Keys sorted, then assigned to an object, as `canonicalizeAvroValue` does.
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

/// Kept equal to `UNORDERED_METRIC_ARRAYS` in `parity-harness.ts`. A histogram's bucket arrays are positional.
const UNORDERED_METRIC_ARRAYS: [&str; 7] = [
    "resourceMetrics",
    "scopeMetrics",
    "metrics",
    "dataPoints",
    "attributes",
    "exemplars",
    "filteredAttributes",
];

fn sort_arrays(value: &JsValue) -> JsValue {
    sort_arrays_under(value, None)
}

fn sort_arrays_under(value: &JsValue, key: Option<&str>) -> JsValue {
    match value {
        JsValue::Array(items) => {
            let mut items: Vec<JsValue> = items
                .iter()
                .map(|item| sort_arrays_under(item, None))
                .collect();
            if key.is_some_and(|key| UNORDERED_METRIC_ARRAYS.contains(&key)) {
                items.sort_by(|a, b| js_sort_cmp(&json_stringify(a), &json_stringify(b)));
            }
            JsValue::Array(items)
        }
        JsValue::Object(o) => {
            let mut out = JsObject::new();
            for (k, v) in o.iter() {
                out.insert(k.clone(), sort_arrays_under(v, k.as_str()));
            }
            JsValue::Object(out)
        }
        other => other.clone(),
    }
}

fn schema_and_codec(buffer: &[u8]) -> Option<(JsValue, String)> {
    let container = decode_container(buffer).ok()?;
    Some((json_parse(&container.schema_json).ok()?, container.codec))
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
    if output == "logs" && value.starts_with(b"Obj\x01") {
        if let Ok(container) = decode_container(value) {
            let (schema, codec) = schema_and_codec(value).unwrap();
            return obj(vec![
                ("kind", JsValue::string("avro")),
                ("schema", schema),
                ("codec", JsValue::string(&codec)),
                (
                    "records",
                    JsValue::Array(container.records.iter().map(canonical).collect()),
                ),
            ]);
        }
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
    let clip = |s: &str| s.chars().take(1500).collect::<String>();
    let mut out = format!(
        "\n== {scenario}: {what}: {} only in Node, {} only in Rust\n",
        missing.len(),
        extra.len()
    );
    for m in missing.iter().take(5) {
        out += &format!("  node: {}\n", clip(m));
    }
    for e in extra.iter().take(5) {
        out += &format!("  rust: {}\n", clip(e));
    }
    if missing.is_empty() && extra.is_empty() {
        out += "  same items, different order\n";
    }
    Some(out)
}

fn usage_texts(rows: Vec<UsageRow>) -> Vec<String> {
    let as_js = |r: &UsageRow, record_id: JsValue| {
        obj(vec![
            ("batch", num(r.batch as f64)),
            ("team_id", num(r.team_id as f64)),
            ("metric", JsValue::string(&r.metric)),
            ("quantity", num(r.quantity)),
            ("unit", JsValue::string(&r.unit)),
            ("record_id", record_id),
        ])
    };
    let mut rows = rows;
    rows.sort_by(|a, b| {
        js_sort_cmp(
            &json_stringify(&as_js(a, JsValue::string(""))),
            &json_stringify(&as_js(b, JsValue::string(""))),
        )
    });
    let mut groups: Vec<String> = Vec::new();
    rows.iter()
        .map(|r| {
            let group = match groups.iter().position(|g| *g == r.record_id) {
                Some(i) => i,
                None => {
                    groups.push(r.record_id.clone());
                    groups.len() - 1
                }
            };
            let mut v = as_js(r, JsValue::Null);
            if let JsValue::Object(o) = &mut v {
                o.remove("record_id");
                o.insert_str("record_group", num(group as f64));
            }
            json_stringify(&v)
        })
        .collect()
}

async fn run_scenario(
    path: &std::path::Path,
    redis: Arc<dyn TokenBucketRedis>,
    conn: &mut redis::aio::MultiplexedConnection,
) -> Option<String> {
    let fixture = load_json(&path.to_path_buf());
    let scenario = get(&fixture, "scenario");
    let expected = get(&fixture, "expected");
    let name = string(get(scenario, "name"));
    let _: () = redis::cmd("FLUSHDB").query_async(conn).await.unwrap();

    let clock = PinnedClock::new(0.0);
    let harness = build_scenario_consumer(scenario, redis, clock.clock(), false);
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
            .store(b as u64, std::sync::atomic::Ordering::SeqCst);
        if let JsValue::Number(ms) = &clocks[b] {
            clock.set(*ms);
        }
        let result = match harness.consumer.process_kafka_batch(batch).await {
            Ok(processed) => match processed.background_task {
                Some(task) => task.await,
                None => Ok(()),
            },
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
    let actual_outputs = captured.iter().map(|c| {
        let mut headers: Vec<(String, String)> = c.message.headers.iter().cloned().collect();
        headers.sort_by(|a, b| js_sort_cmp(&a.0, &b.0));
        let mut h = JsObject::new();
        for (k, v) in headers {
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
    });
    // The output order is not a contract, so compare per output kind as multisets.
    let expected_outputs = array(get(expected, "outputs")).to_vec();
    for kind in ["logs", "logs_dlq", "app_metrics"] {
        let pick = |v: &JsValue| matches!(get(v, "output"), JsValue::String(s) if *s == kind);
        check(
            &format!("outputs[{kind}]"),
            sorted_texts(expected_outputs.iter().filter(|v| pick(v)).cloned()),
            sorted_texts(actual_outputs.clone().filter(|v| pick(v))),
        );
    }

    let recorded = &harness.recorded;
    check(
        "metric_emits",
        sorted_texts(array(get(expected, "metric_emits")).iter().cloned()),
        sorted_texts(
            recorded
                .metric_emits
                .lock()
                .unwrap()
                .iter()
                .map(|(token, team, payload)| {
                    obj(vec![
                        ("token", JsValue::string(token)),
                        ("team_id", num(*team as f64)),
                        ("payload", sort_arrays(&sort_keys(payload))),
                    ])
                }),
        ),
    );
    check(
        "usage_records",
        array(get(expected, "usage_records"))
            .iter()
            .map(json_stringify)
            .collect(),
        usage_texts(recorded.usage_rows.lock().unwrap().clone()),
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
    let mut quota: Vec<String> = recorded
        .quota_checks
        .lock()
        .unwrap()
        .iter()
        .map(|(t, r)| {
            json_stringify(&JsValue::Array(vec![
                JsValue::string(t),
                JsValue::string(r),
            ]))
        })
        .collect();
    quota.sort_by(|a, b| js_sort_cmp(a, b));
    check(
        "quota_checks",
        array(get(expected, "quota_checks"))
            .iter()
            .map(json_stringify)
            .collect(),
        quota,
    );
    (!problems.is_empty()).then_some(problems)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rust_consumer_reproduces_the_node_parity_corpus() {
    let client = redis::Client::open(REDIS_URL).unwrap();
    let mut conn = match client.get_multiplexed_async_connection().await {
        Ok(c) => c,
        Err(e) => {
            eprintln!("skipping: no Redis at {REDIS_URL}: {e}");
            return;
        }
    };
    let redis: Arc<dyn TokenBucketRedis> = Arc::new(RedisTokenBucket::new(conn.clone()));
    let only = std::env::var("PARITY_SCENARIO").ok();
    let mut paths: Vec<_> = std::fs::read_dir(scenarios_dir())
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .filter(|p| {
            only.as_ref()
                .is_none_or(|o| p.file_stem().unwrap().to_string_lossy() == *o)
        })
        .collect();
    paths.sort();
    assert!(!paths.is_empty());
    let mut failures = String::new();
    let mut passed = Vec::new();
    for path in &paths {
        match run_scenario(path, redis.clone(), &mut conn).await {
            Some(problems) => failures += &problems,
            None => passed.push(path.file_stem().unwrap().to_string_lossy().into_owned()),
        }
    }
    eprintln!(
        "parity passed: {}/{} {:?}",
        passed.len(),
        paths.len(),
        passed
    );
    assert!(failures.is_empty(), "{failures}");
}
