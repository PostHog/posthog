//! Shadow mode end to end on librdkafka's mock cluster: Node's outputs reach the shadow topics, and no production topic receives anything.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use ingestion_framework::KafkaMessage;
use logs_ingestion::js::{json_parse, json_stringify, JsValue};
use logs_ingestion::pipeline::scenario::{kafka_message, PinnedClock};
use logs_ingestion::rate_limiter::{RedisTokenBucket, TokenBucketRedis};
use logs_ingestion::service::config::ConsumerLoopConfig;
use logs_ingestion::service::consumer_loop::{run_consumer_loop, BackgroundTask, BatchProcessor};
use logs_ingestion::service::create_kafka_producers;
use logs_ingestion::service::kafka_outputs::KafkaOutputs;
use logs_ingestion::service::kafka_source::{recv_batch, KafkaBatchSource};
use metrics_ingestion::pipeline::scenario::scenario_parts;
use metrics_ingestion::pipeline::MetricsPipelineConsumer;
use metrics_ingestion::service::config::ServiceConfig;
use metrics_ingestion::service::{create_consumer, shadow_deps};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::ClientConfig;
use tokio::sync::Notify;

const INPUT: &str = "metrics_ingestion_test";
const SHADOW_TOPICS: [(&str, &str); 3] = [
    ("metrics", "clickhouse_metrics_rust_shadow"),
    ("dlq", "metrics_ingestion_dlq_rust_shadow"),
    ("app_metrics", "clickhouse_app_metrics2_rust_shadow"),
];
const PRODUCTION: [&str; 3] = [
    "clickhouse_metrics",
    "metrics_ingestion_dlq",
    "clickhouse_app_metrics2",
];

fn env_for(bootstrap: &str) -> HashMap<String, String> {
    [
        ("PLUGIN_SERVER_MODE", "ingestion-metrics"),
        ("DATABASE_URL", "postgres://unused"),
        ("METRICS_INGESTION_CONSUMER_CONSUME_TOPIC", INPUT),
        ("KAFKA_CONSUMER_METADATA_BROKER_LIST", bootstrap),
        (
            "KAFKA_WARPSTREAM_METRICS_PRODUCER_METADATA_BROKER_LIST",
            bootstrap,
        ),
        (
            "KAFKA_WARPSTREAM_INGESTION_PRODUCER_METADATA_BROKER_LIST",
            bootstrap,
        ),
        ("KAFKA_WARPSTREAM_METRICS_PRODUCER_LINGER_MS", "0"),
        ("KAFKA_WARPSTREAM_INGESTION_PRODUCER_LINGER_MS", "0"),
    ]
    .iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect()
}

async fn produce(p: &FutureProducer, m: &KafkaMessage) {
    let mut headers = OwnedHeaders::new();
    for (k, v) in &m.headers {
        headers = headers.insert(Header {
            key: k,
            value: v.as_deref(),
        });
    }
    let mut record: FutureRecord<'_, [u8], [u8]> = FutureRecord::to(INPUT)
        .partition(m.partition)
        .headers(headers);
    if let Some(k) = &m.key {
        record = record.key(k.as_slice());
    }
    if let Some(v) = &m.value {
        record = record.payload(v.as_ref());
    }
    p.send(record, Duration::from_secs(5))
        .await
        .map_err(|(e, _)| e)
        .unwrap();
}

async fn read_all(bootstrap: &str, topics: &[&str], expected: usize) -> Vec<KafkaMessage> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", "shadow-reader")
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .create()
        .unwrap();
    consumer.subscribe(topics).unwrap();
    let deadline = Instant::now() + Duration::from_secs(40);
    let mut out = Vec::new();
    while Instant::now() < deadline && out.len() < expected {
        out.extend(
            recv_batch(&consumer, 1000, Duration::from_millis(300))
                .await
                .unwrap(),
        );
    }
    // A short grace read shows that nothing beyond the expected messages arrived.
    out.extend(
        recv_batch(&consumer, 1000, Duration::from_secs(1))
            .await
            .unwrap(),
    );
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

struct OneBatch<'a> {
    consumer: &'a MetricsPipelineConsumer,
    done: Arc<Notify>,
}

#[async_trait]
impl BatchProcessor for OneBatch<'_> {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        let task = self.consumer.handle_kafka_batch(messages).await?;
        self.done.notify_one();
        Ok(Some(task))
    }
}

fn get<'a>(v: &'a JsValue, key: &str) -> &'a JsValue {
    match v {
        JsValue::Object(o) => o.get(key).unwrap(),
        _ => panic!("not an object looking up {key}"),
    }
}

fn array(v: &JsValue) -> &[JsValue] {
    match v {
        JsValue::Array(a) => a,
        _ => panic!("not an array"),
    }
}

fn text(v: &JsValue) -> String {
    match v {
        JsValue::String(s) => s.to_utf8_lossy().into_owned(),
        other => json_stringify(other),
    }
}

/// `(output, sorted headers, value)`. Node's canonical form names a passthrough value by its input position, so this compares bytes.
type Comparable = (String, Vec<(String, String)>, Vec<u8>);

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shadow_mode_writes_node_outputs_to_shadow_topics_only() {
    let client = redis::Client::open("redis://127.0.0.1:6379").unwrap();
    let conn = match client.get_multiplexed_async_connection().await {
        Ok(c) => c,
        Err(e) => {
            assert!(std::env::var_os("CI").is_none(), "no Redis: {e}");
            eprintln!("skipping: no Redis: {e}");
            return;
        }
    };
    let redis: Arc<dyn TokenBucketRedis> = Arc::new(RedisTokenBucket::new(conn));
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../nodejs/src/ingestion/pipelines/metrics/parity/fixtures/passthrough.json");
    let fixture = json_parse(&std::fs::read_to_string(path).unwrap()).unwrap();
    let scenario = get(&fixture, "scenario");
    let inputs: Vec<KafkaMessage> = array(&array(get(scenario, "batches"))[0])
        .iter()
        .map(kafka_message)
        .collect();

    let cluster = MockCluster::new(1).unwrap();
    cluster.create_topic(INPUT, 4, 1).unwrap();
    for topic in SHADOW_TOPICS.iter().map(|(_, t)| *t).chain(PRODUCTION) {
        cluster.create_topic(topic, 1, 1).unwrap();
    }
    let bootstrap = cluster.bootstrap_servers();
    let config = ServiceConfig::from_env(&env_for(&bootstrap)).unwrap();
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", &bootstrap)
        .create()
        .unwrap();
    for m in &inputs {
        produce(&producer, m).await;
    }

    let clock = PinnedClock::new(match &array(get(scenario, "batch_now_ms"))[0] {
        JsValue::Number(n) => *n,
        _ => 0.0,
    });
    let mut parts = scenario_parts(scenario, redis, clock.clock());
    let producers =
        create_kafka_producers(&config.routes, &config.producers, None, config.mode).unwrap();
    parts.deps.outputs = Arc::new(KafkaOutputs::new(&config.routes, &producers).unwrap());
    let consumer = MetricsPipelineConsumer::new(parts.config, shadow_deps(parts.deps));
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
    assert_eq!((stats.batches, stats.messages), (1, inputs.len() as u64));
    drop(source);

    let expected: Vec<Comparable> = array(get(get(&fixture, "expected"), "outputs"))
        .iter()
        .filter(|o| matches!(get(o, "batch"), JsValue::Number(n) if *n == 0.0))
        .map(|o| {
            let value = get(o, "value");
            let bytes = match text(get(value, "kind")).as_str() {
                "passthrough" => {
                    let index = match get(value, "index") {
                        JsValue::Number(n) => *n as usize,
                        _ => unreachable!(),
                    };
                    inputs[index].value.as_ref().unwrap().to_vec()
                }
                "json" => text(get(value, "raw")).into_bytes(),
                kind => panic!("unexpected value kind {kind}"),
            };
            let headers = match get(o, "headers") {
                JsValue::Object(h) => h
                    .iter()
                    .map(|(k, v)| (k.to_utf8_lossy().into_owned(), text(v)))
                    .collect(),
                _ => Vec::new(),
            };
            (text(get(o, "output")), headers, bytes)
        })
        .collect();

    let shadow_topics: Vec<&str> = SHADOW_TOPICS.iter().map(|(_, t)| *t).collect();
    let read = read_all(&bootstrap, &shadow_topics, expected.len()).await;
    let mut actual: Vec<Comparable> = read
        .iter()
        .map(|m| {
            let output = SHADOW_TOPICS
                .iter()
                .find(|(_, t)| *t == m.topic)
                .map(|(o, _)| o.to_string())
                .unwrap();
            if output == "metrics" {
                let offset = m
                    .header("source_offset")
                    .expect("shadow output carries source_offset");
                let partition: i32 = m.header("source_partition").unwrap().parse().unwrap();
                assert!(inputs.iter().any(|i| i.partition == partition
                    && i.value.as_deref() == m.value.as_deref()
                    && !offset.is_empty()));
            }
            let mut headers: Vec<(String, String)> = m
                .headers
                .iter()
                .filter(|(k, _)| k != "source_offset")
                .map(|(k, v)| {
                    (
                        k.clone(),
                        String::from_utf8_lossy(v.as_deref().unwrap_or_default()).into_owned(),
                    )
                })
                .collect();
            headers.sort();
            (
                output,
                headers,
                m.value.as_deref().unwrap_or_default().to_vec(),
            )
        })
        .collect();
    let mut expected = expected;
    for (_, headers, _) in expected.iter_mut() {
        headers.sort();
    }
    expected.sort();
    actual.sort();
    assert_eq!(actual, expected);

    for topic in PRODUCTION {
        assert_eq!(
            high_watermark(&bootstrap, topic),
            0,
            "nothing reaches {topic}"
        );
    }
    assert!(parts.recorded.usage_rows.lock().unwrap().is_empty());
    assert!(parts.recorded.teams_ingested.lock().unwrap().is_empty());
}
