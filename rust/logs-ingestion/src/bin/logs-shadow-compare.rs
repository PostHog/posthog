//! Compares the Node consumer's `logs` (and optionally DLQ) output with the Rust shadow's.
//! See `README.md`. It never produces: it has no Kafka producer.

use std::sync::Arc;
use std::time::{Duration, Instant};

use envconfig::Envconfig;
use logs_ingestion::compare::kafka::{compare_group_id, run_compare, subscribe, TopicPlan};
use logs_ingestion::compare::{Comparator, CompareSettings, Side, Stream};
use logs_ingestion::service::config::NODE_DEFAULT_CONFIG_CONSUMER_KEYS;
use logs_ingestion::service::kafka_source::consumer_client_config;
use logs_ingestion::service::node_env::{process_env, rdkafka_from_env};
use rdkafka::consumer::StreamConsumer;
use tracing_subscriber::EnvFilter;

common_alloc::used!();

#[derive(Envconfig)]
struct CompareEnv {
    #[envconfig(from = "LOGS_SHADOW_COMPARE_GROUP_ID")]
    group_id: String,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_NODE_TOPIC")]
    node_topic: String,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_RUST_TOPIC")]
    rust_topic: String,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_NODE_DLQ_TOPIC")]
    node_dlq_topic: Option<String>,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_RUST_DLQ_TOPIC")]
    rust_dlq_topic: Option<String>,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_LAG_TOLERANCE_MS", default = "120000")]
    lag_tolerance_ms: u64,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_WARMUP_MS", default = "300000")]
    warmup_ms: u64,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_MAX_PENDING", default = "1000000")]
    max_pending: usize,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_MISMATCH_SAMPLE", default = "200")]
    sample_limit: usize,
    #[envconfig(from = "LOGS_SHADOW_COMPARE_HTTP_PORT", default = "6739")]
    http_port: u16,
}

fn plan(env: &CompareEnv) -> anyhow::Result<Vec<TopicPlan>> {
    let mut plan = vec![
        TopicPlan {
            topic: env.node_topic.clone(),
            side: Side::Node,
            stream: Stream::Logs,
        },
        TopicPlan {
            topic: env.rust_topic.clone(),
            side: Side::Rust,
            stream: Stream::Logs,
        },
    ];
    match (&env.node_dlq_topic, &env.rust_dlq_topic) {
        (Some(n), Some(r)) => {
            plan.push(TopicPlan { topic: n.clone(), side: Side::Node, stream: Stream::Dlq });
            plan.push(TopicPlan { topic: r.clone(), side: Side::Rust, stream: Stream::Dlq });
        }
        (None, None) => {}
        _ => anyhow::bail!("set both LOGS_SHADOW_COMPARE_NODE_DLQ_TOPIC and LOGS_SHADOW_COMPARE_RUST_DLQ_TOPIC, or neither"),
    }
    let mut topics: Vec<&str> = plan.iter().map(|p| p.topic.as_str()).collect();
    topics.sort();
    topics.dedup();
    anyhow::ensure!(
        topics.len() == plan.len(),
        "compared topics must be distinct"
    );
    Ok(plan)
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();
    let env = CompareEnv::init_from_env()?;
    let group_id = compare_group_id(&env.group_id)?;
    let plan = plan(&env)?;
    let mut client = consumer_client_config(
        &group_id,
        &rdkafka_from_env(
            &process_env(),
            "KAFKA_CONSUMER_",
            NODE_DEFAULT_CONFIG_CONSUMER_KEYS,
        ),
        None,
        false,
    );
    // Auto commit only records the comparator's own progress, under its reserved group.
    client
        .set("enable.auto.offset.store", "true")
        .set("allow.auto.create.topics", "false");
    let consumer: StreamConsumer = client.create()?;
    subscribe(&consumer, &plan)?;

    let recorder = serve_metrics::setup_metrics_recorder();
    let app = axum::Router::new()
        .route("/_health", axum::routing::get(|| async { "ok" }))
        .route(
            "/metrics",
            axum::routing::get(move || std::future::ready(recorder.render())),
        );
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", env.http_port)).await?;
    tokio::spawn(async move { axum::serve(listener, app).await });

    let mut comparator = Comparator::new(
        CompareSettings {
            lag_tolerance: Duration::from_millis(env.lag_tolerance_ms),
            warmup: Duration::from_millis(env.warmup_ms),
            max_pending: env.max_pending,
            sample_limit: env.sample_limit,
        },
        Instant::now(),
    );
    let stop = Arc::new(tokio::sync::Notify::new());
    let notify = stop.clone();
    tokio::spawn(async move {
        let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {},
            _ = term.recv() => {},
        }
        notify.notify_one();
    });
    run_compare(&consumer, &plan, &mut comparator, None, stop.notified()).await?;
    let report = comparator.report().clone();
    tracing::info!(
        matched = report.matched,
        mismatched = report.mismatched,
        node_only = report.node_only,
        rust_only = report.rust_only,
        warmup_unmatched = report.warmup_unmatched,
        pending = comparator.pending(),
        field_mismatches = ?report.field_mismatches,
        "shadow comparison stopped"
    );
    Ok(())
}
