//! Seed a realistic lagging-partition scenario into local Kafka.
//!
//! Partition 0 becomes the "problem partition": one dominant team (70% of
//! messages, a single hot distinct_id, large payloads) drowns out a mixed
//! background of other teams and events, and the consumer group's committed
//! offset is left near the start so the partition shows heavy lag. Partitions
//! 1 and 2 get light, balanced traffic and are committed at their high
//! watermark (healthy).
//!
//! Run against the dev stack:
//!
//! ```sh
//! DATABASE_URL=postgres://posthog:posthog@db:5432/posthog \
//!     cargo run -p ingestion-control-plane --example seed_lag
//! ```
//!
//! Env knobs: `KAFKA_HOSTS` (default `localhost:9092`), `TOPIC` (default
//! `ingestion-lag-demo`), `GROUP` (default `ingestion-lag-demo`), `HOT_MESSAGES`
//! (default 2000). With `DATABASE_URL` set, real team tokens are used so the
//! control plane's token -> team resolution shows real team ids.

use std::time::Duration;

use common_types::CapturedEventHeaders;
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::{Offset, TopicPartitionList};

const BACKGROUND_EVENTS: &[&str] = &["$identify", "$autocapture", "$screen", "survey sent"];

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn headers(token: &str, distinct_id: &str, event: &str, historical: bool) -> OwnedHeaders {
    CapturedEventHeaders {
        token: Some(token.to_string()),
        distinct_id: Some(distinct_id.to_string()),
        session_id: None,
        timestamp: Some(chrono::Utc::now().timestamp_millis().to_string()),
        event: Some(event.to_string()),
        uuid: Some(uuid::Uuid::new_v4().to_string()),
        now: Some(chrono::Utc::now().to_rfc3339()),
        force_disable_person_processing: None,
        historical_migration: historical.then_some(true),
        skip_heatmap_processing: None,
        dlq_reason: None,
        dlq_step: None,
        dlq_timestamp: None,
        content_encoding: None,
    }
    .into()
}

async fn fetch_tokens(database_url: &str) -> Vec<String> {
    let fallback: Vec<String> = ["phc_demo_a", "phc_demo_b", "phc_demo_c", "phc_demo_d"]
        .iter()
        .map(|t| t.to_string())
        .collect();
    if database_url.is_empty() {
        return fallback;
    }
    match sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(database_url)
        .await
    {
        Ok(pool) => {
            match sqlx::query_scalar::<_, String>(
                "SELECT api_token FROM posthog_team ORDER BY id LIMIT 4",
            )
            .fetch_all(&pool)
            .await
            {
                Ok(tokens) if !tokens.is_empty() => {
                    println!("using {} real team tokens from DATABASE_URL", tokens.len());
                    tokens
                }
                _ => fallback,
            }
        }
        Err(e) => {
            println!("DATABASE_URL unreachable ({e}); using demo tokens");
            fallback
        }
    }
}

#[tokio::main]
async fn main() {
    let kafka_hosts = env_or("KAFKA_HOSTS", "localhost:9092");
    let topic = env_or("TOPIC", "ingestion-lag-demo");
    let group = env_or("GROUP", "ingestion-lag-demo");
    let hot_messages: usize = env_or("HOT_MESSAGES", "2000")
        .parse()
        .expect("HOT_MESSAGES must be a number");
    let database_url = env_or("DATABASE_URL", "");

    let tokens = fetch_tokens(&database_url).await;
    let dominant = &tokens[0];
    let others = &tokens[1..];

    let mut base = ClientConfig::new();
    base.set("bootstrap.servers", &kafka_hosts);

    // Ensure the topic exists with 3 partitions.
    let admin: AdminClient<DefaultClientContext> = base.create().expect("create admin client");
    // Per-topic results may be "already exists"; only the request must succeed.
    admin
        .create_topics(
            &[NewTopic::new(&topic, 3, TopicReplication::Fixed(1))],
            &AdminOptions::new(),
        )
        .await
        .expect("create_topics request failed")
        .into_iter()
        .for_each(drop);

    let producer: FutureProducer = base.create().expect("create producer");
    let big_payload = "x".repeat(8 * 1024);

    let mut produced = 0usize;
    let mut send = |partition: i32,
                    token: &str,
                    distinct_id: &str,
                    event: &str,
                    payload: String,
                    historical: bool| {
        let key = format!("{token}:{distinct_id}");
        let record = FutureRecord::to(&topic)
            .partition(partition)
            .key(&key)
            .payload(&payload)
            .headers(headers(token, distinct_id, event, historical));
        // Fire-and-forget into the local producer queue; flushed below.
        producer.send_result(record).expect("producer queue full");
        produced += 1;
    };

    // Partition 0: dominant team drowning out mixed background traffic.
    let dominant_count = hot_messages * 7 / 10;
    for i in 0..hot_messages {
        if i % 10 < 7 {
            send(
                0,
                dominant,
                "hot-device-1",
                "$pageview",
                big_payload.clone(),
                i % 33 == 0,
            );
        } else {
            let token = &others[i % others.len()];
            let event = BACKGROUND_EVENTS[i % BACKGROUND_EVENTS.len()];
            let payload = "y".repeat(300 + (i * 37) % 1700);
            send(
                0,
                token,
                &format!("user-{}", i % 120),
                event,
                payload,
                false,
            );
        }
    }

    // Partitions 1-2: light, balanced traffic.
    for partition in [1, 2] {
        for i in 0..150usize {
            let token = &tokens[i % tokens.len()];
            let event = BACKGROUND_EVENTS[i % BACKGROUND_EVENTS.len()];
            let payload = "z".repeat(200 + (i * 53) % 1300);
            send(
                partition,
                token,
                &format!("user-{partition}-{}", i % 40),
                event,
                payload,
                false,
            );
        }
    }

    producer
        .flush(Duration::from_secs(30))
        .expect("flush producer");
    println!("produced {produced} messages to '{topic}' ({dominant_count} dominant on p0)");

    // Commit offsets for the group: p0 stuck near the start, p1/p2 caught up.
    let consumer: BaseConsumer = {
        let mut cfg = base.clone();
        cfg.set("group.id", &group)
            .set("enable.auto.commit", "false");
        cfg.create().expect("create offset consumer")
    };
    let (_, hwm1) = consumer
        .fetch_watermarks(&topic, 1, Duration::from_secs(10))
        .expect("watermarks p1");
    let (_, hwm2) = consumer
        .fetch_watermarks(&topic, 2, Duration::from_secs(10))
        .expect("watermarks p2");

    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(&topic, 0, Offset::Offset(50))
        .expect("tpl p0");
    tpl.add_partition_offset(&topic, 1, Offset::Offset(hwm1))
        .expect("tpl p1");
    tpl.add_partition_offset(&topic, 2, Offset::Offset(hwm2))
        .expect("tpl p2");
    consumer
        .commit(&tpl, rdkafka::consumer::CommitMode::Sync)
        .expect("commit offsets");

    println!(
        "committed offsets for group '{group}': p0=50 (lagging), p1={hwm1}, p2={hwm2} (caught up)"
    );
    println!("open the control plane UI and refresh the lag view");
}
