//! The service on librdkafka's mock cluster: the Kafka outputs, the commit-after-success rule
//! with a real consumer group, and shadow mode end to end against the parity corpus, followed
//! by the comparator against the Node outputs the corpus recorded.

mod common;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use common::{
    array, avro_from_canonical, canonical, get, js_sort_cmp, load_json, scenarios_dir, string,
};
use futures::FutureExt;
use ingestion_framework::{Headers, IngestionOutputs, KafkaMessage, OutputMessage};
use logs_ingestion::avro::{decode_container, encode_container, Schema};
use logs_ingestion::compare::kafka::{assign_all_partitions, run_compare, TopicPlan};
use logs_ingestion::compare::{Comparator, CompareSettings, Side, Stream};
use logs_ingestion::js::{json_parse, json_stringify, JsObject, JsString, JsValue};
use logs_ingestion::pipeline::scenario::{kafka_message, scenario_parts, PinnedClock};
use logs_ingestion::pipeline::LogsIngestionConsumer;
use logs_ingestion::rate_limiter::{RedisTokenBucket, TokenBucketRedis};
use logs_ingestion::service::config::{ConsumerLoopConfig, ServiceConfig};
use logs_ingestion::service::consumer_loop::{run_consumer_loop, BackgroundTask, BatchProcessor};
use logs_ingestion::service::kafka_outputs::KafkaOutputs;
use logs_ingestion::service::kafka_source::{recv_batch, KafkaBatchSource};
use logs_ingestion::service::{create_consumer, create_producers, shadow_deps};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer, FutureRecord};
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use tokio::sync::Notify;

const INPUT: &str = "logs_ingestion";
const SHADOW_LOGS: &str = "clickhouse_logs_rust_shadow";
const SHADOW_DLQ: &str = "logs_ingestion_dlq_rust_shadow";
const SHADOW_METRICS: &str = "app_metrics_rust_shadow";
const PRODUCTION: &[&str] = &[
    "clickhouse_logs",
    "logs_ingestion_dlq",
    "clickhouse_app_metrics2",
    "log_entries",
];
const GROUP: &str = "ingestion-logs-rust-shadow";

fn env_for(bootstrap: &str) -> HashMap<String, String> {
    [
        ("PLUGIN_SERVER_MODE", "ingestion-logs"),
        ("LOGS_RUST_MODE", "shadow"),
        ("DATABASE_URL", "postgres://unused"),
        ("DATABASE_READONLY_URL", "postgres://unused-replica"),
        ("LOGS_RUST_SHADOW_REDIS_HOST", "127.0.0.1"),
        ("LOGS_RUST_SHADOW_CONSUMER_GROUP_ID", GROUP),
        ("LOGS_RUST_SHADOW_LOGS_TOPIC", SHADOW_LOGS),
        ("LOGS_RUST_SHADOW_DLQ_TOPIC", SHADOW_DLQ),
        ("LOGS_RUST_SHADOW_APP_METRICS_TOPIC", SHADOW_METRICS),
        ("KAFKA_CONSUMER_METADATA_BROKER_LIST", bootstrap),
        ("KAFKA_CONSUMER_AUTO_OFFSET_RESET", "earliest"),
        ("KAFKA_CONSUMER_ENABLE_PARTITION_EOF", "false"),
        (
            "KAFKA_WARPSTREAM_LOGS_PRODUCER_METADATA_BROKER_LIST",
            bootstrap,
        ),
        (
            "KAFKA_WARPSTREAM_INGESTION_PRODUCER_METADATA_BROKER_LIST",
            bootstrap,
        ),
        ("KAFKA_WARPSTREAM_LOGS_PRODUCER_LINGER_MS", "0"),
        ("KAFKA_WARPSTREAM_INGESTION_PRODUCER_LINGER_MS", "0"),
    ]
    .iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect()
}

fn mock_cluster() -> MockCluster<'static, DefaultProducerContext> {
    let cluster = MockCluster::new(1).expect("mock cluster");
    cluster.create_topic(INPUT, 4, 1).unwrap();
    for t in [
        SHADOW_LOGS,
        SHADOW_DLQ,
        SHADOW_METRICS,
        "node_logs",
        "node_dlq",
    ]
    .iter()
    .chain(PRODUCTION)
    {
        cluster.create_topic(t, 1, 1).unwrap();
    }
    cluster
}

fn producer(bootstrap: &str) -> FutureProducer {
    ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("linger.ms", "0")
        .create()
        .unwrap()
}

async fn produce(
    p: &FutureProducer,
    topic: &str,
    partition: Option<i32>,
    m: &KafkaMessage,
) -> (i32, i64) {
    let mut headers = OwnedHeaders::new();
    for (k, v) in &m.headers {
        headers = headers.insert(Header {
            key: k,
            value: v.as_deref(),
        });
    }
    let mut record: FutureRecord<'_, [u8], [u8]> = FutureRecord::to(topic).headers(headers);
    if let Some(p) = partition {
        record = record.partition(p);
    }
    if let Some(k) = &m.key {
        record = record.key(k.as_slice());
    }
    if let Some(v) = &m.value {
        record = record.payload(v.as_ref());
    }
    if let Some(ts) = m.timestamp {
        record = record.timestamp(ts);
    }
    p.send(record, Duration::from_secs(5))
        .await
        .map_err(|(e, _)| e)
        .unwrap()
}

/// Every message of `topics`, until `expected` arrived and a short grace window passed.
async fn read_all(bootstrap: &str, topics: &[&str], expected: usize) -> Vec<KafkaMessage> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", format!("reader-{}", uuid::Uuid::now_v7()))
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .create()
        .unwrap();
    consumer.subscribe(topics).unwrap();
    let deadline = Instant::now() + Duration::from_secs(40);
    let mut out = Vec::new();
    let mut grace: Option<Instant> = None;
    while Instant::now() < deadline && grace.is_none_or(|g| Instant::now() < g) {
        out.extend(
            recv_batch(&consumer, 1000, Duration::from_millis(300))
                .await
                .unwrap(),
        );
        if out.len() >= expected && grace.is_none() {
            grace = Some(Instant::now() + Duration::from_secs(1));
        }
    }
    out
}

fn high_watermark(bootstrap: &str, topic: &str) -> i64 {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", "watermarks")
        .create()
        .unwrap();
    consumer
        .fetch_watermarks(topic, 0, Duration::from_secs(5))
        .unwrap()
        .1
}

fn committed(bootstrap: &str, partitions: i32) -> Vec<i64> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", GROUP)
        .create()
        .unwrap();
    let mut tpl = TopicPartitionList::new();
    for p in 0..partitions {
        tpl.add_partition(INPUT, p);
    }
    let c = consumer
        .committed_offsets(tpl, Duration::from_secs(5))
        .unwrap();
    (0..partitions)
        .map(|p| match c.find_partition(INPUT, p).unwrap().offset() {
            Offset::Offset(o) => o,
            _ => -1,
        })
        .collect()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn kafka_outputs_route_by_output_name_and_wait_for_delivery() {
    let cluster = mock_cluster();
    let bootstrap = cluster.bootstrap_servers();
    let config = ServiceConfig::from_env(&env_for(&bootstrap)).unwrap();
    let outputs = KafkaOutputs::new(&config.routes, &create_producers(&config).unwrap()).unwrap();
    let mut headers = Headers::new();
    headers.set("token", "phc_x");
    headers.set("team_id", "7");
    let message = OutputMessage {
        value: Some(b"payload".to_vec().into()),
        key: Some(b"k".to_vec()),
        headers,
    };
    outputs
        .queue_messages("logs", vec![message.clone(), message])
        .await
        .unwrap();
    outputs
        .produce("app_metrics", OutputMessage::default())
        .await
        .unwrap();
    assert!(outputs.queue_messages("log_entries", vec![]).await.is_err());

    let read = read_all(&bootstrap, &[SHADOW_LOGS, SHADOW_METRICS], 3).await;
    let logs: Vec<_> = read.iter().filter(|m| m.topic == SHADOW_LOGS).collect();
    assert_eq!(logs.len(), 2);
    assert_eq!(logs[0].value.as_deref(), Some(&b"payload"[..]));
    assert_eq!(logs[0].key.as_deref(), Some(&b"k"[..]));
    assert_eq!(
        logs[0].headers,
        vec![
            ("token".into(), Some(b"phc_x".to_vec())),
            ("team_id".into(), Some(b"7".to_vec()))
        ]
    );
    assert_eq!(read.iter().filter(|m| m.topic == SHADOW_METRICS).count(), 1);
    for t in PRODUCTION {
        assert_eq!(high_watermark(&bootstrap, t), 0);
    }

    let mut missing = env_for(&bootstrap);
    missing.insert(
        "LOGS_RUST_SHADOW_DLQ_TOPIC".into(),
        "missing_rust_shadow".into(),
    );
    let missing = ServiceConfig::from_env(&missing).unwrap();
    // The second call fails too only if the first one did not create the topic.
    for _ in 0..2 {
        let error = match create_producers(&missing) {
            Ok(_) => panic!("a missing shadow topic must fail startup"),
            Err(e) => e.to_string(),
        };
        assert!(error.contains("missing_rust_shadow"), "{error}");
    }
}

/// Fails the background task of the batch that holds `fail_offset` on partition 0.
struct FailingProcessor {
    fail_offset: i64,
    batches: Arc<Notify>,
}

#[async_trait]
impl BatchProcessor for FailingProcessor {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        let fail = messages.iter().any(|m| m.offset == self.fail_offset);
        self.batches.notify_one();
        Ok(Some(
            async move {
                if fail {
                    anyhow::bail!("produce failed")
                } else {
                    Ok(())
                }
            }
            .boxed(),
        ))
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn offsets_commit_only_after_the_background_task_succeeds() {
    let cluster = mock_cluster();
    let bootstrap = cluster.bootstrap_servers();
    let config = ServiceConfig::from_env(&env_for(&bootstrap)).unwrap();
    let p = producer(&bootstrap);
    for _ in 0..3 {
        produce(
            &p,
            INPUT,
            Some(0),
            &KafkaMessage {
                value: Some(b"x".to_vec().into()),
                ..Default::default()
            },
        )
        .await;
    }
    let mut source = KafkaBatchSource::new(create_consumer(&config).unwrap());
    let processor = FailingProcessor {
        fail_offset: 2,
        batches: Arc::new(Notify::new()),
    };
    let loop_config = ConsumerLoopConfig {
        batch_size: 2,
        batch_timeout: Duration::from_secs(20),
        max_background_tasks: 1,
        background_task_timeout: Duration::from_secs(5),
    };
    let result = run_consumer_loop(
        &mut source,
        &processor,
        &loop_config,
        futures::future::pending(),
        &|| {},
    )
    .await;
    assert_eq!(result.unwrap_err().to_string(), "produce failed");
    drop(source);
    assert_eq!(
        committed(&bootstrap, 1),
        vec![2],
        "the failed batch at offset 2 must replay"
    );
}

/// Runs the service consumer for exactly one Kafka batch.
struct OneBatch<'a> {
    consumer: &'a LogsIngestionConsumer,
    done: Arc<Notify>,
}

#[async_trait]
impl BatchProcessor for OneBatch<'_> {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        let task = self
            .consumer
            .process_kafka_batch(messages)
            .await?
            .background_task;
        self.done.notify_one();
        Ok(task)
    }
}

struct Input {
    message: KafkaMessage,
    scenario_offset: i64,
    actual_offset: i64,
}

fn sorted_texts(values: Vec<JsValue>) -> Vec<String> {
    let mut t: Vec<String> = values.iter().map(json_stringify).collect();
    t.sort_by(|a, b| js_sort_cmp(a, b));
    t
}

fn obj(entries: Vec<(&str, JsValue)>) -> JsValue {
    let mut o = JsObject::new();
    for (k, v) in entries {
        o.insert_str(k, v);
    }
    JsValue::Object(o)
}

/// The fixture's view of an output: `parity_corpus.rs` canonicalisation, with the DLQ
/// `source_offset` mapped back from the mock cluster's offsets to the scenario's.
fn canonical_output(output: &str, m: &KafkaMessage, inputs: &[Input]) -> JsValue {
    let mut headers: Vec<(String, String)> = m
        .headers
        .iter()
        .filter(|(k, _)| output != "logs" || k != "source_offset")
        .map(|(k, v)| {
            (
                k.clone(),
                String::from_utf8_lossy(v.as_deref().unwrap_or_default()).into_owned(),
            )
        })
        .collect();
    let partition = m.header("source_partition").unwrap_or_default();
    for (k, v) in headers.iter_mut() {
        if output == "logs_dlq" && k == "source_offset" {
            let actual: i64 = v.parse().unwrap();
            let input = inputs
                .iter()
                .find(|i| i.actual_offset == actual && i.message.partition.to_string() == partition)
                .unwrap();
            *v = input.scenario_offset.to_string();
        }
    }
    headers.sort_by(|a, b| js_sort_cmp(&a.0, &b.0));
    let mut h = JsObject::new();
    for (k, v) in headers {
        h.insert(JsString::from(k), JsValue::string(&v));
    }
    let bytes = m.value.as_deref().unwrap_or_default();
    let value = if let Some(i) = inputs
        .iter()
        .position(|i| i.message.value.as_deref() == Some(bytes))
    {
        obj(vec![
            ("kind", JsValue::string("passthrough")),
            ("batch", JsValue::Number(0.0)),
            ("index", JsValue::Number(i as f64)),
        ])
    } else if output == "app_metrics" {
        let raw = String::from_utf8_lossy(bytes).into_owned();
        let parsed = json_parse(&raw).unwrap();
        let JsValue::Object(o) = &parsed else {
            panic!()
        };
        let mut entries: Vec<_> = o.iter().map(|(k, v)| (k.to_string(), v.clone())).collect();
        entries.sort_by(|a, b| js_sort_cmp(&a.0, &b.0));
        let mut sorted = JsObject::new();
        for (k, v) in entries {
            sorted.insert(JsString::from(k), v);
        }
        obj(vec![
            ("kind", JsValue::string("json")),
            ("raw", JsValue::string(&raw)),
            ("json", JsValue::Object(sorted)),
        ])
    } else {
        let c = decode_container(bytes).unwrap();
        obj(vec![
            ("kind", JsValue::string("avro")),
            ("schema", json_parse(&c.schema_json).unwrap()),
            ("codec", JsValue::string(&c.codec)),
            (
                "records",
                JsValue::Array(c.records.iter().map(canonical).collect()),
            ),
        ])
    };
    obj(vec![
        ("batch", JsValue::Number(0.0)),
        ("output", JsValue::string(output)),
        (
            "key",
            m.key
                .as_ref()
                .map(|k| JsValue::string(&String::from_utf8_lossy(k)))
                .unwrap_or(JsValue::Null),
        ),
        ("headers", JsValue::Object(h)),
        ("value", value),
    ])
}

/// The Node output a fixture recorded, as a Kafka message on the seeded Node topic.
fn node_message(expected: &JsValue, inputs: &[Input]) -> KafkaMessage {
    let value = get(expected, "value");
    let bytes = match string(get(value, "kind")).as_str() {
        "passthrough" => inputs[match get(value, "index") {
            JsValue::Number(n) => *n as usize,
            _ => panic!(),
        }]
        .message
        .value
        .clone()
        .unwrap()
        .to_vec(),
        "avro" => {
            let schema = Schema::parse_json(&json_stringify(get(value, "schema"))).unwrap();
            let records: Vec<_> = array(get(value, "records"))
                .iter()
                .map(|r| avro_from_canonical(&schema, r))
                .collect();
            encode_container(&schema, &string(get(value, "codec")), &records).unwrap()
        }
        other => panic!("unexpected kind {other}"),
    };
    let JsValue::Object(headers) = get(expected, "headers") else {
        panic!()
    };
    let partition = headers
        .get("source_partition")
        .map(string)
        .unwrap_or_default();
    let headers = headers
        .iter()
        .map(|(k, v)| {
            let mut v = string(v);
            if k.as_str() == Some("source_offset") {
                let scenario: i64 = v.parse().unwrap();
                v = inputs
                    .iter()
                    .find(|i| {
                        i.scenario_offset == scenario
                            && i.message.partition.to_string() == partition
                    })
                    .unwrap()
                    .actual_offset
                    .to_string();
            }
            (k.to_string(), Some(v.into_bytes()))
        })
        .collect();
    KafkaMessage {
        value: Some(bytes.into()),
        headers,
        ..Default::default()
    }
}

async fn shadow_scenario(name: &str) {
    let client = redis::Client::open("redis://127.0.0.1:6379").unwrap();
    let mut conn = match client.get_multiplexed_async_connection().await {
        Ok(c) => c,
        Err(e) => {
            eprintln!("skipping: no Redis: {e}");
            return;
        }
    };
    let keys: Vec<String> = redis::cmd("KEYS")
        .arg("@posthog-logs-rust-shadow/*")
        .query_async(&mut conn)
        .await
        .unwrap();
    if !keys.is_empty() {
        let _: () = redis::cmd("DEL")
            .arg(&keys)
            .query_async(&mut conn)
            .await
            .unwrap();
    }
    let redis: Arc<dyn TokenBucketRedis> = Arc::new(RedisTokenBucket::new(conn));

    let fixture = load_json(&scenarios_dir().join(format!("{name}.json")));
    let scenario = get(&fixture, "scenario");
    let expected = get(&fixture, "expected");
    assert_eq!(array(get(scenario, "batches")).len(), 1);

    let cluster = mock_cluster();
    let bootstrap = cluster.bootstrap_servers();
    let config = ServiceConfig::from_env(&env_for(&bootstrap)).unwrap();
    let p = producer(&bootstrap);
    let mut inputs = Vec::new();
    for m in array(&array(get(scenario, "batches"))[0]) {
        let message = kafka_message(m);
        let (_, actual_offset) = produce(&p, INPUT, Some(message.partition), &message).await;
        inputs.push(Input {
            scenario_offset: message.offset,
            actual_offset,
            message,
        });
    }

    let clock = PinnedClock::new(match &array(get(scenario, "batch_now_ms"))[0] {
        JsValue::Number(n) => *n,
        _ => 0.0,
    });
    let mut parts = scenario_parts(scenario, redis, clock.clock(), false);
    let outputs =
        Arc::new(KafkaOutputs::new(&config.routes, &create_producers(&config).unwrap()).unwrap());
    parts.deps.outputs = outputs.clone();
    let consumer =
        LogsIngestionConsumer::new(parts.identity, parts.config, shadow_deps(parts.deps));
    let mut source = KafkaBatchSource::new(create_consumer(&config).unwrap());
    let done = Arc::new(Notify::new());
    let processor = OneBatch {
        consumer: &consumer,
        done: done.clone(),
    };
    let loop_config = ConsumerLoopConfig {
        batch_size: inputs.len(),
        batch_timeout: Duration::from_secs(30),
        max_background_tasks: 1,
        background_task_timeout: Duration::from_secs(30),
    };
    let stats = run_consumer_loop(
        &mut source,
        &processor,
        &loop_config,
        done.notified(),
        &|| {},
    )
    .await
    .unwrap();
    assert_eq!(
        (stats.batches, stats.messages),
        (1, inputs.len() as u64),
        "{name}: one Kafka batch"
    );
    drop(source);

    let mut per_partition = [0i64; 4];
    for i in &inputs {
        per_partition[i.message.partition as usize] =
            per_partition[i.message.partition as usize].max(i.actual_offset + 1);
    }
    let committed = committed(&bootstrap, 4);
    for p in 0..4 {
        if per_partition[p] > 0 {
            assert_eq!(
                committed[p], per_partition[p],
                "{name}: partition {p} committed"
            );
        }
    }

    let expected_outputs = array(get(expected, "outputs"));
    let read = read_all(
        &bootstrap,
        &[SHADOW_LOGS, SHADOW_DLQ, SHADOW_METRICS],
        expected_outputs.len(),
    )
    .await;
    for (output, topic) in [
        ("logs", SHADOW_LOGS),
        ("logs_dlq", SHADOW_DLQ),
        ("app_metrics", SHADOW_METRICS),
    ] {
        let actual: Vec<&KafkaMessage> = read.iter().filter(|m| m.topic == topic).collect();
        if output == "logs" {
            for m in &actual {
                let offset: i64 = m
                    .header("source_offset")
                    .expect("shadow logs carry source_offset")
                    .parse()
                    .unwrap();
                let partition = m.header("source_partition").unwrap();
                assert!(inputs
                    .iter()
                    .any(|i| i.actual_offset == offset
                        && i.message.partition.to_string() == partition));
            }
        }
        let want: Vec<JsValue> = expected_outputs
            .iter()
            .filter(|o| string(get(o, "output")) == output)
            .cloned()
            .collect();
        assert_eq!(
            sorted_texts(
                actual
                    .iter()
                    .map(|m| canonical_output(output, m, &inputs))
                    .collect()
            ),
            sorted_texts(want),
            "{name}: {output}"
        );
    }
    for t in PRODUCTION {
        assert_eq!(
            high_watermark(&bootstrap, t),
            0,
            "{name}: nothing reaches {t}"
        );
    }
    assert!(parts.recorded.usage_rows.lock().unwrap().is_empty());
    assert!(parts.recorded.teams_ingested.lock().unwrap().is_empty());
    assert!(parts.recorded.metric_emits.lock().unwrap().is_empty());

    let mut expected_records = 0u64;
    for o in expected_outputs {
        let topic = match string(get(o, "output")).as_str() {
            "logs" => "node_logs",
            "logs_dlq" => "node_dlq",
            _ => continue,
        };
        let m = node_message(o, &inputs);
        expected_records += if topic == "node_dlq" {
            1
        } else {
            decode_container(m.value.as_deref().unwrap())
                .map(|c| c.records.len() as u64)
                .unwrap_or(1)
        };
        produce(&p, topic, None, &m).await;
    }
    let plan = [
        TopicPlan {
            topic: "node_logs".into(),
            side: Side::Node,
            stream: Stream::Logs,
        },
        TopicPlan {
            topic: SHADOW_LOGS.into(),
            side: Side::Rust,
            stream: Stream::Logs,
        },
        TopicPlan {
            topic: "node_dlq".into(),
            side: Side::Node,
            stream: Stream::Dlq,
        },
        TopicPlan {
            topic: SHADOW_DLQ.into(),
            side: Side::Rust,
            stream: Stream::Dlq,
        },
    ];
    let compare_consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", &bootstrap)
        .set("group.id", "compare-test")
        .set("auto.offset.reset", "earliest")
        .create()
        .unwrap();
    assign_all_partitions(&compare_consumer, &plan, Duration::from_secs(10)).unwrap();
    let mut comparator = Comparator::new(
        CompareSettings {
            lag_tolerance: Duration::from_secs(60),
            warmup: Duration::ZERO,
            max_pending: 10_000,
            sample_limit: 20,
        },
        Instant::now(),
    );
    run_compare(
        &compare_consumer,
        &plan,
        &mut comparator,
        Some(Duration::from_secs(3)),
        futures::future::pending(),
    )
    .await
    .unwrap();
    let report = comparator.finish();
    assert_eq!(comparator.samples(), &[], "{name}: mismatch samples");
    assert_eq!(
        (
            report.matched,
            report.mismatched,
            report.node_only,
            report.rust_only
        ),
        (expected_records, 0, 0, 0),
        "{name}: comparator report"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shadow_mode_reproduces_the_corpus_on_shadow_topics_only() {
    for name in ["passthrough", "parse-failures", "codecs"] {
        shadow_scenario(name).await;
    }
}
