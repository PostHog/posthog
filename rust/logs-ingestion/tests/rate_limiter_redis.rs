use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use logs_ingestion::avro::{AvroMap, AvroValue};
use logs_ingestion::content_weights::run_pipeline_stages;
use logs_ingestion::js::{json_parse, JsValue};
use logs_ingestion::rate_limiter::{
    token_bucket_v2, token_bucket_v3, Clock, KeyRoot, KeyedRateLimitRequest, KeyedRateLimiter,
    KeyedRateLimiterConfig, LogsRateLimiter, LogsRateLimiterConfig, RateLimitedMessage,
    RedisTokenBucket, ScriptVersion, TokenBucketRedis,
};
use logs_ingestion::record::LogRecord;
use logs_ingestion::sampling::{compile_rule_set, LogsSamplingService, SamplingRuleRow};

const REDIS_URL: &str = "redis://127.0.0.1:6379";

fn get<'a>(v: &'a JsValue, key: &str) -> &'a JsValue {
    match v {
        JsValue::Object(o) => o.get(key).unwrap_or_else(|| panic!("missing {key}")),
        _ => panic!("not an object looking up {key}"),
    }
}

fn opt<'a>(v: &'a JsValue, key: &str) -> Option<&'a JsValue> {
    match v {
        JsValue::Object(o) => o.get(key),
        _ => None,
    }
}

fn arr(v: &JsValue) -> &[JsValue] {
    match v {
        JsValue::Array(a) => a,
        other => panic!("not an array: {other:?}"),
    }
}

fn s(v: &JsValue) -> String {
    match v {
        JsValue::String(x) => x.to_string(),
        other => panic!("not a string: {other:?}"),
    }
}

fn n(v: &JsValue) -> f64 {
    match v {
        JsValue::Number(x) => *x,
        other => panic!("not a number: {other:?}"),
    }
}

fn opt_n(v: &JsValue, key: &str) -> Option<f64> {
    opt(v, key).map(n)
}

fn record_from_json(v: &JsValue) -> LogRecord {
    let JsValue::Object(o) = v else {
        panic!("record is not an object")
    };
    let fields = o
        .iter()
        .map(|(k, v)| (Arc::from(k.to_string().as_str()), avro_from_json(v)))
        .collect();
    LogRecord::from_value(AvroValue::Record(fields))
}

fn avro_from_json(v: &JsValue) -> AvroValue {
    match v {
        JsValue::Null => AvroValue::Null,
        JsValue::Bool(b) => AvroValue::Boolean(*b),
        JsValue::Number(x) if x.fract() == 0.0 => AvroValue::Long(*x as i64),
        JsValue::Number(x) => AvroValue::Double(*x),
        JsValue::String(x) => AvroValue::String(x.to_utf8_lossy().into_owned()),
        JsValue::Object(o) => {
            if let Some(JsValue::String(hex)) = o.get("$bytes") {
                return AvroValue::Bytes(hex::decode(hex.to_string()).unwrap());
            }
            let mut map = AvroMap::new();
            for (k, v) in o.iter() {
                map.assign(k.to_string(), avro_from_json(v));
            }
            AvroValue::Map(map)
        }
        JsValue::Array(items) => AvroValue::Array(items.iter().map(avro_from_json).collect()),
    }
}

struct Msg {
    team: i64,
    bytes: f64,
    created_at: Option<Vec<u8>>,
}

impl RateLimitedMessage for Msg {
    fn team_id(&self) -> i64 {
        self.team
    }
    fn bytes_uncompressed(&self) -> f64 {
        self.bytes
    }
    fn created_at_header(&self) -> Option<&[u8]> {
        self.created_at.as_deref()
    }
}

async fn keys_matching(
    conn: &mut redis::aio::MultiplexedConnection,
    patterns: &[String],
) -> Vec<String> {
    let mut keys = Vec::new();
    for pattern in patterns {
        let found: Vec<String> = redis::cmd("KEYS")
            .arg(pattern)
            .query_async(conn)
            .await
            .unwrap();
        keys.extend(found);
    }
    keys
}

#[tokio::test]
async fn rate_limiters_match_node_against_redis() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/rate-limiter-reference.json");
    let fixture = json_parse(&std::fs::read_to_string(path).unwrap()).unwrap();

    let client = redis::Client::open(REDIS_URL).unwrap();
    let mut conn = match client.get_multiplexed_async_connection().await {
        Ok(c) => c,
        Err(e) => {
            eprintln!("skipping: no Redis at {REDIS_URL}: {e}");
            return;
        }
    };

    assert_eq!(s(get(get(&fixture, "shas"), "v2")), token_bucket_v2().sha);
    assert_eq!(s(get(get(&fixture, "shas"), "v3")), token_bucket_v3().sha);

    let patterns: Vec<String> = arr(get(&fixture, "keyPatterns")).iter().map(s).collect();
    let stale = keys_matching(&mut conn, &patterns).await;
    if !stale.is_empty() {
        let _: () = redis::cmd("DEL")
            .arg(&stale)
            .query_async(&mut conn)
            .await
            .unwrap();
    }

    let now_bits = Arc::new(AtomicU64::new(0));
    let clock: Clock = {
        let now_bits = now_bits.clone();
        Arc::new(move || f64::from_bits(now_bits.load(Ordering::SeqCst)))
    };
    let set_now = |ms: f64| now_bits.store(ms.to_bits(), Ordering::SeqCst);
    let redis: Arc<dyn TokenBucketRedis> = Arc::new(RedisTokenBucket::new(conn.clone()));

    let mut keyed: HashMap<String, KeyedRateLimiter> = HashMap::new();
    if let JsValue::Object(limiters) = get(&fixture, "keyedLimiters") {
        for (name, cfg) in limiters.iter() {
            let mut config = KeyedRateLimiterConfig::new(&s(get(cfg, "name")), KeyRoot::Test);
            config.ttl_seconds = opt_n(cfg, "ttlSeconds");
            config.script_version = if s(get(cfg, "scriptVersion")) == "v3" {
                ScriptVersion::V3
            } else {
                ScriptVersion::V2
            };
            keyed.insert(
                name.to_string(),
                KeyedRateLimiter::with_clock(config, redis.clone(), clock.clone()),
            );
        }
    }

    let mut logs: HashMap<String, LogsRateLimiter> = HashMap::new();
    if let JsValue::Object(limiters) = get(&fixture, "logsLimiters") {
        for (name, entry) in limiters.iter() {
            let c = get(entry, "config");
            let config = LogsRateLimiterConfig {
                team_bucket_size_kb: s(get(c, "LOGS_LIMITER_TEAM_BUCKET_SIZE_KB")),
                team_refill_rate_kb_per_second: s(get(
                    c,
                    "LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND",
                )),
                disabled_for_teams: s(get(c, "LOGS_LIMITER_DISABLED_FOR_TEAMS")),
                enabled_teams: s(get(c, "LOGS_LIMITER_ENABLED_TEAMS")),
                bucket_size_kb: n(get(c, "LOGS_LIMITER_BUCKET_SIZE_KB")),
                refill_rate_kb_per_second: n(get(c, "LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND")),
                ttl_seconds: n(get(c, "LOGS_LIMITER_TTL_SECONDS")),
            };
            logs.insert(
                name.to_string(),
                LogsRateLimiter::new(
                    config,
                    redis.clone(),
                    &s(get(entry, "name")),
                    KeyRoot::Test,
                    clock.clone(),
                ),
            );
        }
    }

    let rows: Vec<SamplingRuleRow> = arr(get(&fixture, "samplingRules"))
        .iter()
        .map(|r| SamplingRuleRow {
            id: s(get(r, "id")),
            rule_type: s(get(r, "rule_type")),
            scope_service: match get(r, "scope_service") {
                JsValue::Null => None,
                v => Some(s(v)),
            },
            scope_path_pattern: match get(r, "scope_path_pattern") {
                JsValue::Null => None,
                v => Some(s(v)),
            },
            scope_attribute_filters: get(r, "scope_attribute_filters").clone(),
            config: get(r, "config").clone(),
            version: None,
        })
        .collect();
    let rule_set = Arc::new(compile_rule_set(&rows).unwrap());
    let sampling = Arc::new(LogsSamplingService::new(
        redis.clone(),
        600.0,
        KeyRoot::Test,
        clock.clone(),
    ));

    for (i, step) in arr(get(&fixture, "steps")).iter().enumerate() {
        set_now(n(get(step, "nowMs")));
        let expected = get(step, "output");
        match s(get(step, "kind")).as_str() {
            "keyed" => {
                let limiter = &keyed[&s(get(step, "limiter"))];
                let requests: Vec<KeyedRateLimitRequest> = arr(get(step, "requests"))
                    .iter()
                    .map(|r| KeyedRateLimitRequest {
                        id: s(get(r, "id")),
                        cost: n(get(r, "cost")),
                        bucket_size: opt_n(r, "bucketSize"),
                        refill_rate: opt_n(r, "refillRate"),
                        ttl_seconds: opt_n(r, "ttlSeconds"),
                        now: opt_n(r, "now"),
                    })
                    .collect();
                let out = if s(get(step, "method")) == "many" {
                    limiter.rate_limit_many(&requests).await.unwrap()
                } else {
                    limiter.rate_limit_grouped(&requests).await.unwrap()
                };
                let expected: Vec<(String, f64, f64, bool)> = arr(expected)
                    .iter()
                    .map(|pair| {
                        let [id, r] = arr(pair) else { panic!("pair") };
                        let JsValue::Bool(limited) = get(r, "isRateLimited") else {
                            panic!("bool")
                        };
                        (
                            s(id),
                            n(get(r, "tokensBefore")),
                            n(get(r, "tokens")),
                            *limited,
                        )
                    })
                    .collect();
                let actual: Vec<(String, f64, f64, bool)> = out
                    .into_iter()
                    .map(|(id, r)| (id, r.tokens_before, r.tokens, r.is_rate_limited))
                    .collect();
                assert_eq!(actual, expected, "step {i}");
            }
            "logs" => {
                let limiter = &logs[&s(get(step, "limiter"))];
                let messages: Vec<(usize, Msg)> = arr(get(step, "messages"))
                    .iter()
                    .enumerate()
                    .map(|(index, m)| {
                        let created_at = match get(m, "createdAt") {
                            JsValue::Null => None,
                            v => Some(s(v).into_bytes()),
                        };
                        let msg = Msg {
                            team: n(get(m, "teamId")) as i64,
                            bytes: n(get(m, "bytesUncompressed")),
                            created_at,
                        };
                        (index, msg)
                    })
                    .collect();
                struct Indexed(usize, Msg);
                impl RateLimitedMessage for Indexed {
                    fn team_id(&self) -> i64 {
                        self.1.team_id()
                    }
                    fn bytes_uncompressed(&self) -> f64 {
                        self.1.bytes_uncompressed()
                    }
                    fn created_at_header(&self) -> Option<&[u8]> {
                        self.1.created_at_header()
                    }
                }
                let result = limiter
                    .filter_messages(messages.into_iter().map(|(i, m)| Indexed(i, m)).collect())
                    .await
                    .unwrap();
                let indices =
                    |v: &JsValue| arr(v).iter().map(|x| n(x) as usize).collect::<Vec<_>>();
                assert_eq!(
                    result.allowed.iter().map(|m| m.0).collect::<Vec<_>>(),
                    indices(get(expected, "allowed")),
                    "step {i} allowed"
                );
                assert_eq!(
                    result.dropped.iter().map(|m| m.0).collect::<Vec<_>>(),
                    indices(get(expected, "dropped")),
                    "step {i} dropped"
                );
            }
            "sampling" => {
                let records: Vec<LogRecord> = arr(get(step, "records"))
                    .iter()
                    .map(record_from_json)
                    .collect();
                let team = n(get(step, "teamId")) as i64;
                let stage = sampling.make_sampling_stage(
                    rule_set.clone(),
                    Some(team),
                    n(get(step, "headerBytes")),
                );
                let (kept, stats) = run_pipeline_stages(records, &[stage]).await.unwrap();
                let kept: Vec<String> =
                    kept.iter().map(|r| r.uuid().unwrap().to_string()).collect();
                let expected_kept: Vec<String> = arr(get(expected, "kept")).iter().map(s).collect();
                assert_eq!(kept, expected_kept, "step {i} kept");
                let pairs = |v: &JsValue| {
                    arr(v)
                        .iter()
                        .map(|p| {
                            let [k, v] = arr(p) else { panic!("pair") };
                            (s(k), n(v))
                        })
                        .collect::<Vec<_>>()
                };
                assert_eq!(
                    stats.stage.records_dropped,
                    n(get(expected, "recordsDropped"))
                );
                assert_eq!(
                    stats.stage.records_dropped_by_rule_id.0,
                    pairs(get(expected, "recordsDroppedByRuleId"))
                );
                assert_eq!(stats.stage.bytes_dropped, n(get(expected, "bytesDropped")));
                assert_eq!(
                    stats.stage.bytes_dropped_by_rule_id.0,
                    pairs(get(expected, "bytesDroppedByRuleId"))
                );
                assert_eq!(
                    stats.stage.content_bytes_dropped,
                    n(get(expected, "contentBytesDropped"))
                );
                assert_eq!(
                    stats.content_bytes_total,
                    n(get(expected, "contentBytesTotal"))
                );
                let dropped_by = match get(expected, "droppedBy") {
                    JsValue::Null => None,
                    v => Some(s(v)),
                };
                assert_eq!(stats.dropped_by, dropped_by, "step {i} droppedBy");
            }
            other => panic!("unknown step kind {other}"),
        }
    }

    let mut keys = keys_matching(&mut conn, &patterns).await;
    keys.sort();
    let JsValue::Object(expected_state) = get(&fixture, "finalState") else {
        panic!("finalState")
    };
    let expected_keys: Vec<String> = expected_state.keys().map(|k| k.to_string()).collect();
    assert_eq!(keys, expected_keys);
    for key in keys {
        let actual: HashMap<String, String> = redis::cmd("HGETALL")
            .arg(&key)
            .query_async(&mut conn)
            .await
            .unwrap();
        let expected: HashMap<String, String> = match expected_state.get(&key) {
            Some(JsValue::Object(o)) => o.iter().map(|(k, v)| (k.to_string(), s(v))).collect(),
            _ => panic!("state for {key}"),
        };
        assert_eq!(actual, expected, "bucket state of {key}");
    }
}
