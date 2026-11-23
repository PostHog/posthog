//! Runs a bench workload through real Kafka, so the Rust consumer loop and the consumer-plus-gRPC-worker split can be compared on the same topic.
//!
//!   logs-ingestion-kafka-bench produce  <workload.json> <brokers> <topic> <partitions> <passes>
//!   logs-ingestion-kafka-bench monolith <workload.json> <brokers> <topic> <group> <expected> <result.json>
//!   logs-ingestion-kafka-bench worker   <workload.json> <http_port> <grpc_port> <expected> <result.json>
//!   logs-ingestion-kafka-bench lag      <brokers> <topic> <group>
//!
//! `monolith` and `worker` build the consumer from the workload with in-memory dependencies and discarded outputs, as `logs-ingestion-bench` does.

use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use async_trait::async_trait;
use axum::routing::get;
use axum::Router;
use ingestion_framework::KafkaMessage;
use logs_ingestion::js::{json_parse, JsValue};
use logs_ingestion::pipeline::scenario::{
    build_scenario_consumer, kafka_message, ScenarioConsumer,
};
use logs_ingestion::rate_limiter::{system_clock, RedisTokenBucket, TokenBucketRedis};
use logs_ingestion::service::config::ConsumerLoopConfig;
use logs_ingestion::service::consumer_loop::{run_consumer_loop, BackgroundTask, BatchProcessor};
use logs_ingestion::service::grpc_worker::LogsWorkerIngest;
use logs_ingestion::service::kafka_source::{
    consumer_client_config, FencingContext, KafkaBatchSource, LogsConsumer,
};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::error::RDKafkaErrorCode;
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use tokio::sync::Notify;

common_alloc::used!();

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as i64)
}

fn env_number(name: &str, default: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn workload_messages(scenario: &JsValue) -> Vec<KafkaMessage> {
    let JsValue::Object(scenario) = scenario else {
        return Vec::new();
    };
    match scenario.get("batches") {
        Some(JsValue::Array(batches)) => batches
            .iter()
            .flat_map(|batch| match batch {
                JsValue::Array(messages) => messages.iter().map(kafka_message).collect(),
                _ => Vec::new(),
            })
            .collect(),
        _ => Vec::new(),
    }
}

async fn scenario_consumer(path: &str) -> anyhow::Result<ScenarioConsumer> {
    let scenario = json_parse(&std::fs::read_to_string(path)?)?;
    let client = redis::Client::open("redis://127.0.0.1:6379/9")?;
    let mut conn = client.get_multiplexed_async_connection().await?;
    let _: () = redis::cmd("FLUSHDB").query_async(&mut conn).await?;
    let redis: Arc<dyn TokenBucketRedis> = Arc::new(RedisTokenBucket::new(conn));
    Ok(build_scenario_consumer(
        &scenario,
        redis,
        system_clock(),
        true,
    ))
}

/// Times the span from the first message handed to the pipeline to the last one it finished, so process start and group join stay out of the result.
struct Timed {
    inner: Arc<dyn BatchProcessor>,
    expected: u64,
    done: AtomicU64,
    batches: AtomicU64,
    first_ms: AtomicI64,
    result_path: String,
    finished: Notify,
}

impl Timed {
    fn new(inner: Arc<dyn BatchProcessor>, expected: u64, result_path: String) -> Arc<Self> {
        Arc::new(Self {
            inner,
            expected,
            done: AtomicU64::new(0),
            batches: AtomicU64::new(0),
            first_ms: AtomicI64::new(0),
            result_path,
            finished: Notify::new(),
        })
    }

    fn complete(&self, messages: u64) {
        let batches = self.batches.fetch_add(1, Ordering::SeqCst) + 1;
        let done = self.done.fetch_add(messages, Ordering::SeqCst) + messages;
        // A replayed sub-batch can pass the expected count, so only the crossing writes the result.
        if done >= self.expected && done - messages < self.expected {
            let result = format!(
                "{{\"first_ms\":{},\"last_ms\":{},\"messages\":{done},\"batches\":{batches}}}\n",
                self.first_ms.load(Ordering::SeqCst),
                now_ms(),
            );
            if let Err(error) = std::fs::write(&self.result_path, result) {
                tracing::error!(%error, "cannot write the bench result");
            }
            self.finished.notify_one();
        }
    }
}

struct TimedProcessor(Arc<Timed>);

#[async_trait]
impl BatchProcessor for TimedProcessor {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        let timed = Arc::clone(&self.0);
        let _ = timed
            .first_ms
            .compare_exchange(0, now_ms(), Ordering::SeqCst, Ordering::SeqCst);
        let count = messages.len() as u64;
        let background_task = timed.inner.process(messages).await?;
        Ok(Some(Box::pin(async move {
            if let Some(task) = background_task {
                task.await?;
            }
            timed.complete(count);
            Ok(())
        })))
    }
}

async fn produce(args: &[String]) -> anyhow::Result<()> {
    let [path, brokers, topic, partitions, passes] = args else {
        anyhow::bail!("usage: produce <workload.json> <brokers> <topic> <partitions> <passes>");
    };
    let partitions: i32 = partitions.parse()?;
    let passes: usize = passes.parse()?;
    let messages = workload_messages(&json_parse(&std::fs::read_to_string(path)?)?);
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", brokers)
        .set("linger.ms", "20")
        .set("message.max.bytes", "10485760")
        .set("queue.buffering.max.kbytes", "1048576")
        .create()?;
    let admin: AdminClient<_> = ClientConfig::new()
        .set("bootstrap.servers", brokers)
        .create()?;
    let created = admin
        .create_topics(
            &[NewTopic::new(topic, partitions, TopicReplication::Fixed(1))],
            &AdminOptions::new(),
        )
        .await?;
    for result in created {
        match result {
            Ok(_) | Err((_, RDKafkaErrorCode::TopicAlreadyExists)) => {}
            Err((name, code)) => anyhow::bail!("cannot create topic {name}: {code}"),
        }
    }
    let (mut total, mut bytes, mut records) = (0usize, 0usize, 0f64);
    let mut pending = Vec::new();
    for _ in 0..passes {
        for message in &messages {
            let mut headers = OwnedHeaders::new();
            for (key, value) in &message.headers {
                headers = headers.insert(Header {
                    key,
                    value: value.as_deref(),
                });
            }
            let value = message.value.as_deref().unwrap_or_default();
            let mut record = FutureRecord::<[u8], [u8]>::to(topic)
                .payload(value)
                .headers(headers)
                .partition(total as i32 % partitions);
            if let Some(key) = &message.key {
                record = record.key(key);
            }
            pending.push(
                producer
                    .send_result(record)
                    .map_err(|(error, _)| anyhow::anyhow!("produce failed: {error}"))?,
            );
            total += 1;
            bytes += value.len();
            records += message
                .header("record_count")
                .and_then(|v| v.parse::<f64>().ok())
                .unwrap_or(0.0);
            if pending.len() >= 2000 {
                for delivery in pending.drain(..) {
                    delivery
                        .await?
                        .map_err(|(error, _)| anyhow::anyhow!("delivery failed: {error}"))?;
                }
            }
        }
    }
    for delivery in pending {
        delivery
            .await?
            .map_err(|(error, _)| anyhow::anyhow!("delivery failed: {error}"))?;
    }
    producer.flush(Duration::from_secs(30))?;
    println!("{{\"messages\":{total},\"records\":{records},\"input_bytes\":{bytes}}}");
    Ok(())
}

async fn monolith(args: &[String]) -> anyhow::Result<()> {
    let [path, brokers, topic, group, expected, result_path] = args else {
        anyhow::bail!(
            "usage: monolith <workload.json> <brokers> <topic> <group> <expected> <result.json>"
        );
    };
    let harness = scenario_consumer(path).await?;
    let timed = Timed::new(
        Arc::new(harness.consumer),
        expected.parse()?,
        result_path.clone(),
    );
    let overrides = vec![("metadata.broker.list".to_string(), brokers.clone())];
    let consumer: LogsConsumer = consumer_client_config(group, &overrides, None, false)
        .create_with_context(FencingContext::default())?;
    consumer.subscribe(&[topic.as_str()])?;
    let mut source = KafkaBatchSource::new(consumer);
    let config = ConsumerLoopConfig {
        batch_size: env_number("CONSUMER_BATCH_SIZE", 500),
        batch_timeout: Duration::from_millis(500),
        max_background_tasks: env_number("CONSUMER_MAX_BACKGROUND_TASKS", 1),
        background_task_timeout: Duration::from_secs(60),
    };
    let finished = Arc::clone(&timed);
    let stats = run_consumer_loop(
        &mut source,
        &TimedProcessor(timed),
        &config,
        async move { finished.finished.notified().await },
        &|| {},
    )
    .await?;
    eprintln!(
        "monolith stopped after {} batches and {} messages",
        stats.batches, stats.messages
    );
    Ok(())
}

async fn worker(args: &[String]) -> anyhow::Result<()> {
    let [path, http_port, grpc_port, expected, result_path] = args else {
        anyhow::bail!(
            "usage: worker <workload.json> <http_port> <grpc_port> <expected> <result.json>"
        );
    };
    let harness = scenario_consumer(path).await?;
    let timed = Timed::new(
        Arc::new(harness.consumer),
        expected.parse()?,
        result_path.clone(),
    );
    let ingest = LogsWorkerIngest::new(
        Arc::new(TimedProcessor(timed)),
        env_number("INGESTION_WORKER_CONCURRENT_BATCHES", 1),
    );
    let app = Router::new().route("/_ready", get(|| async { "ok" }));
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", http_port.parse::<u16>()?)).await?;
    tokio::spawn(async move { axum::serve(listener, app).await });
    // The driver stops this process once the consumer has committed everything.
    tonic::transport::Server::builder()
        .add_service(ingest.into_server())
        .serve(([127, 0, 0, 1], grpc_port.parse::<u16>()?).into())
        .await?;
    Ok(())
}

fn lag(args: &[String]) -> anyhow::Result<()> {
    let [brokers, topic, group] = args else {
        anyhow::bail!("usage: lag <brokers> <topic> <group>");
    };
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", brokers)
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .create()?;
    let timeout = Duration::from_secs(10);
    let metadata = consumer.fetch_metadata(Some(topic), timeout)?;
    let mut assignment = TopicPartitionList::new();
    for topic_metadata in metadata.topics() {
        for partition in topic_metadata.partitions() {
            assignment.add_partition(topic, partition.id());
        }
    }
    let committed = consumer.committed_offsets(assignment, timeout)?;
    let mut total = 0i64;
    for element in committed.elements() {
        let (low, high) = consumer.fetch_watermarks(topic, element.partition(), timeout)?;
        let position = match element.offset() {
            Offset::Offset(offset) => offset,
            _ => low,
        };
        total += high - position;
    }
    println!("{total}");
    Ok(())
}

fn main() -> anyhow::Result<()> {
    // The arguments of this local benchmark only name a workload file, a local broker and counts.
    // nosemgrep: rust.lang.security.args.args
    let args: Vec<String> = std::env::args().collect();
    let command = args.get(1).map(String::as_str).unwrap_or_default();
    let rest = args.get(2..).unwrap_or_default();
    if command == "lag" {
        return lag(rest);
    }
    let _recorder = serve_metrics::setup_metrics_recorder();
    tracing_subscriber::fmt()
        .json()
        .with_writer(std::io::stderr)
        .with_env_filter(tracing_subscriber::EnvFilter::new("warn"))
        .init();
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        match command {
            "produce" => produce(rest).await,
            "monolith" => monolith(rest).await,
            "worker" => worker(rest).await,
            other => anyhow::bail!("unknown command {other:?}"),
        }
    })
}
