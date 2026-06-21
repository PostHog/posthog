//! End-to-end benchmark: produce realistic events to a real Kafka topic, run the REAL propdefs
//! pipeline (legacy producer/consumer, or the staged reader/processors/writer) consuming ->
//! processing -> writing to a real Postgres, and measure end-to-end throughput. This exercises
//! the whole service, not a slice, so it's the baseline to optimize against.
//!
//! Requires a running Kafka and Postgres:
//!   KAFKA_HOSTS=localhost:9092 \
//!   DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog \
//!   SQLX_OFFLINE=true cargo bench -p property-defs-rs --bench end_to_end
//!
//! Set PROPDEFS_BENCH_WRITE_LATENCY_MS=173 to model a slow production DB (local writes are
//! ~1ms, which hides the win from write concurrency / the staged writer).

use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

use ahash::AHashSet;
use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::config::ClientConfig;
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use serde_json::{json, Map, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tokio::sync::mpsc;

use common_kafka::kafka_consumer::SingleTopicConsumer;
use lifecycle::{ComponentOptions, Manager};
use property_defs_rs::{
    api::v1::query::Manager as QueryManager,
    app_context::AppContext,
    config::Config,
    kafka_reader_loop,
    measuring_channel::measuring_channel,
    processor_loop,
    types::{Event, Update},
    update_cache::Cache,
    update_consumer_loop, update_producer_loop, writer_loop,
};

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}
fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

// Reads the global `prop_defs_events_received` counter so we can detect when the pipeline has
// consumed all N events (the true "ingested everything" signal — writes dedup to a bounded set,
// so DB row counts saturate and can't tell us when ingestion is done).
fn snapshotter() -> &'static Snapshotter {
    static S: OnceLock<Snapshotter> = OnceLock::new();
    S.get_or_init(|| {
        let recorder = DebuggingRecorder::new();
        let s = recorder.snapshotter();
        drop(recorder.install());
        s
    })
}

fn events_received() -> u64 {
    snapshotter()
        .snapshot()
        .into_vec()
        .into_iter()
        .find(|(key, _, _, _)| key.key().name() == "prop_defs_events_received")
        .and_then(|(_, _, _, v)| match v {
            DebugValue::Counter(c) => Some(c),
            _ => None,
        })
        .unwrap_or(0)
}

// ---- workload ----------------------------------------------------------

const COMMON_EVENTS: [&str; 4] = ["$pageview", "$autocapture", "$pageleave", "$identify"];
const COMMON_KEYS: [&str; 8] = [
    "$current_url", "$browser", "$os", "$device_type", "utm_source", "$referrer", "$session_id",
    "$lib_version",
];

fn gen_events(num_events: usize, num_teams: usize, seed: u64) -> Vec<(i32, String)> {
    let mut rng = StdRng::seed_from_u64(seed);
    let mut team_schemas: Vec<Vec<(String, Vec<String>)>> = Vec::with_capacity(num_teams);
    for t in 0..num_teams {
        let mut evs = Vec::new();
        for e in COMMON_EVENTS {
            let n = rng.gen_range(5..=COMMON_KEYS.len());
            let mut keys: Vec<String> = COMMON_KEYS.iter().take(n).map(|k| k.to_string()).collect();
            for c in 0..rng.gen_range(4..20) {
                keys.push(format!("prop_{c}"));
            }
            evs.push((e.to_string(), keys));
        }
        for c in 0..rng.gen_range(3..10) {
            let keys: Vec<String> = (0..rng.gen_range(5..25)).map(|i| format!("p{i}")).collect();
            evs.push((format!("custom_{t}_{c}"), keys));
        }
        team_schemas.push(evs);
    }

    let total_weight: f64 = (0..num_teams).map(|t| 1.0 / (t + 1) as f64).sum();
    let mut out = Vec::with_capacity(num_events);
    for _ in 0..num_events {
        let mut r = rng.gen_range(0.0..total_weight);
        let mut team = num_teams - 1;
        for t in 0..num_teams {
            r -= 1.0 / (t + 1) as f64;
            if r < 0.0 {
                team = t;
                break;
            }
        }
        let (event, keys) = &team_schemas[team][rng.gen_range(0..team_schemas[team].len())];
        let mut props = Map::new();
        for k in keys {
            props.insert(k.clone(), json!(format!("v{}", rng.gen_range(0..50))));
        }
        let team_id = (team as i32) + 1;
        let payload = json!({
            "team_id": team_id,
            "project_id": team_id as i64,
            "event": event,
            "properties": Value::Object(props).to_string(),
        });
        out.push((team_id, payload.to_string()));
    }
    out
}

// Distinct EventProperty keys the pipeline will write — used to detect completion.
fn expected_eventprops(events: &[(i32, String)]) -> usize {
    let mut set: AHashSet<Update> = AHashSet::new();
    for (_, raw) in events {
        let ev: Event = serde_json::from_str(raw).unwrap();
        for u in ev.into_updates(10_000) {
            if matches!(u, Update::EventProperty(_)) {
                set.insert(u);
            }
        }
    }
    set.len()
}

// ---- kafka -------------------------------------------------------------

async fn create_topic(hosts: &str, topic: &str, partitions: i32) {
    let admin: AdminClient<_> = ClientConfig::new()
        .set("bootstrap.servers", hosts)
        .create()
        .expect("admin client");
    let new = NewTopic::new(topic, partitions, TopicReplication::Fixed(1));
    let _created = admin.create_topics([&new], &AdminOptions::new()).await;
}

async fn produce(hosts: &str, topic: &str, events: &[(i32, String)]) {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", hosts)
        .set("linger.ms", "20")
        .set("queue.buffering.max.messages", "2000000")
        .create()
        .expect("producer");

    for chunk in events.chunks(10_000) {
        let mut futs = Vec::with_capacity(chunk.len());
        for (team_id, payload) in chunk {
            let key = team_id.to_string();
            let fut = producer
                .send_result(FutureRecord::to(topic).payload(payload.as_bytes()).key(&key))
                .expect("enqueue");
            futs.push(fut);
        }
        for f in futs {
            let _delivered = f.await;
        }
    }
    producer.flush(Timeout::After(Duration::from_secs(30))).expect("flush");
}

// ---- pipeline wiring ---------------------------------------------------

fn make_config(hosts: &str, topic: &str, group: &str, db_url: &str, staged: bool, writer_conc: usize, latency_ms: u64, workers: usize) -> Config {
    common_kafka::config::ConsumerConfig::set_defaults("propdefs-e2e", "placeholder", true);
    let mut config = Config::init_with_defaults().expect("config");
    config.kafka.kafka_hosts = hosts.to_string();
    config.consumer.kafka_consumer_topic = topic.to_string();
    config.consumer.kafka_consumer_group = group.to_string();
    config.database_url = db_url.to_string();
    config.max_pg_connections = 50;
    config.skip_reads = true; // no personhog
    config.skip_writes = false;
    config.staged_pipeline = staged;
    config.writer_max_concurrency = writer_conc;
    config.write_artificial_latency_ms = latency_ms;
    config.worker_loop_count = workers;
    config.max_issue_period = 2; // flush partial batches quickly so the run completes
    config.producer_drain_interval_secs = 1; // drain the legacy producer's tail promptly
    config
}

async fn truncate(pool: &PgPool) {
    sqlx::query("TRUNCATE posthog_eventproperty, posthog_propertydefinition, posthog_eventdefinition")
        .execute(pool)
        .await
        .unwrap();
}

async fn count_eventprops(pool: &PgPool) -> i64 {
    sqlx::query_scalar("SELECT count(*) FROM posthog_eventproperty")
        .fetch_one(pool)
        .await
        .unwrap()
}

// Spawns the pipeline, waits until `expected` event-properties are persisted, returns elapsed.
async fn run_scenario(
    label: &str,
    config: Config,
    consumer: SingleTopicConsumer,
    pool: &PgPool,
    expected: usize,
    num_events: usize,
) -> f64 {
    truncate(pool).await;

    let api_pool = PgPoolOptions::new().max_connections(2).connect(&config.database_url).await.unwrap();
    let qmgr = QueryManager::new(api_pool).await.unwrap();
    let context = Arc::new(AppContext::new(&config, qmgr).await.unwrap());
    let cache = Arc::new(Cache::new(2_000_000, 2_000_000, 2_000_000));

    let mut manager = Manager::builder("e2e").build();
    let h = manager.register("worker", ComponentOptions::new());
    let _guard = manager.monitor_background();

    let base = events_received();
    let start = Instant::now();
    if config.staged_pipeline {
        let n = config.worker_loop_count.max(1);
        let (update_tx, update_rx) =
            measuring_channel(config.update_batch_size * config.channel_slots_per_worker);
        let mut raw_txs = Vec::with_capacity(n);
        for _ in 0..n {
            let (raw_tx, raw_rx) = mpsc::channel::<Event>(config.channel_slots_per_worker);
            raw_txs.push(raw_tx);
            tokio::spawn(processor_loop(config.clone(), cache.clone(), raw_rx, update_tx.clone(), h.clone()));
        }
        tokio::spawn(kafka_reader_loop(config.clone(), consumer.clone(), raw_txs, h.clone()));
        drop(update_tx);
        tokio::spawn(writer_loop(config.clone(), cache.clone(), context.clone(), update_rx, h.clone()));
    } else {
        let (tx, rx) = measuring_channel(config.update_batch_size * config.channel_slots_per_worker);
        for _ in 0..config.worker_loop_count {
            tokio::spawn(update_producer_loop(config.clone(), consumer.clone(), cache.clone(), tx.clone(), h.clone()));
        }
        drop(tx);
        tokio::spawn(update_consumer_loop(config.clone(), cache.clone(), context.clone(), rx, h.clone()));
    }

    // End-to-end completion = all N events consumed AND all their distinct writes persisted.
    // The consume milestone is the read throughput; the gap to write-complete is the write
    // backlog, which is where slow writes + write concurrency show up.
    let target = base + num_events as u64;
    let deadline = Instant::now() + Duration::from_secs(180);
    let mut consume_secs: Option<f64> = None;
    loop {
        let consumed = events_received() >= target;
        if consumed && consume_secs.is_none() {
            consume_secs = Some(start.elapsed().as_secs_f64());
        }
        let written = count_eventprops(pool).await as usize;
        if consumed && written >= expected {
            break;
        }
        if Instant::now() > deadline {
            eprintln!(
                "  {label}: TIMEOUT (consumed={}, written={written}/{expected})",
                events_received() - base
            );
            break;
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    let complete_secs = start.elapsed().as_secs_f64();
    let consume_secs = consume_secs.unwrap_or(complete_secs);
    h.request_shutdown();
    tokio::time::sleep(Duration::from_millis(300)).await;

    eprintln!("  {label}: consume {consume_secs:.1}s, write-complete {complete_secs:.1}s");
    num_events as f64 / complete_secs
}

#[tokio::main]
async fn main() {
    let hosts = env_str("KAFKA_HOSTS", "localhost:9092");
    let db_url = env_str("DATABASE_URL", "postgres://posthog:posthog@localhost:5432/posthog");
    let num_events = env_usize("PROPDEFS_BENCH_EVENTS", 50_000);
    let num_teams = env_usize("PROPDEFS_BENCH_TEAMS", 50);
    let latency_ms = env_usize("PROPDEFS_BENCH_WRITE_LATENCY_MS", 0) as u64;
    let workers = env_usize("PROPDEFS_BENCH_WORKERS", 4);

    eprintln!("generating {num_events} events ({num_teams} teams)...");
    let events = gen_events(num_events, num_teams, 42);
    let expected = expected_eventprops(&events);

    let topic = format!("propdefs_e2e_{}", std::process::id());
    eprintln!("creating topic {topic} and producing {num_events} events to {hosts}...");
    create_topic(&hosts, &topic, 12).await;
    produce(&hosts, &topic, &events).await;

    let pool = PgPoolOptions::new().max_connections(4).connect(&db_url).await.expect("pg");
    let _ = events_received(); // install the metrics recorder before any pipeline runs

    println!("\n=== propdefs end-to-end ({num_events} events, write_latency={latency_ms}ms, {workers} workers) ===");
    println!("expected distinct event-properties: {expected}");
    println!("(events/sec = end-to-end: all N consumed AND all distinct writes persisted)");
    println!("{:<34} {:>16}", "scenario", "events/sec (e2e)");

    let scenarios: Vec<(String, bool, usize)> = vec![
        ("legacy (producers + 1 consumer)".to_string(), false, 1),
        ("staged, writer_concurrency=1".to_string(), true, 1),
        ("staged, writer_concurrency=4".to_string(), true, 4),
        ("staged, writer_concurrency=8".to_string(), true, 8),
    ];

    for (label, staged, writer_conc) in scenarios {
        let group = format!("g_{}_{}", std::process::id(), rand::random::<u32>());
        let config = make_config(&hosts, &topic, &group, &db_url, staged, writer_conc, latency_ms, workers);
        let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone()).expect("consumer");
        let eps = run_scenario(&label, config, consumer, &pool, expected, num_events).await;
        println!("{label:<34} {eps:>16.0}");
    }
}
