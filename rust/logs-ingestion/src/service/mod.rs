//! The runnable Kafka service around `LogsIngestionConsumer`: the port of
//! `servers/ingestion-logs-server.ts` and `servers/ingestion-traces-server.ts`, plus a shadow
//! mode that runs beside the Node consumer without affecting production.

pub mod config;
pub mod consumer_loop;
pub mod kafka_outputs;
pub mod kafka_source;
pub mod lazy_loader;
pub mod node_env;
pub mod postgres;
pub mod redis_deps;
pub mod shadow;
pub mod usage;

use std::collections::HashMap;
use std::future::ready;
use std::sync::Arc;
use std::time::Duration;

use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use lifecycle::{ComponentOptions, Manager};
use rdkafka::consumer::Consumer;
use rdkafka::metadata::Metadata;
use rdkafka::producer::{FutureProducer, Producer};
use sqlx::PgPool;

use crate::metric_rules::LogsMetricsEmitter;
use crate::pipeline::{
    DependencyRetry, LogsConsumerIdentity, LogsIngestionConsumer, LogsIngestionConsumerDeps,
};
use crate::rate_limiter::{system_clock, KeyRoot, RedisTokenBucket};

use config::{ConsumerKind, RunMode, ServiceConfig};
use consumer_loop::run_consumer_loop;
use kafka_outputs::{producer_client_config, KafkaOutputs};
use kafka_source::{consumer_client_config, FencingContext, KafkaBatchSource, LogsConsumer};
use node_env::NodeEnv;

const SERVICE_NAME: &str = "logs-ingestion";
/// How long a task may take to finish once the lifecycle monitor has returned.
const TASK_JOIN_GRACE: Duration = Duration::from_secs(2);

/// The shadow-mode rules, applied to any set of dependencies (README.md lists them).
pub fn shadow_deps(mut deps: LogsIngestionConsumerDeps) -> LogsIngestionConsumerDeps {
    deps.team_manager = Arc::new(shadow::ReadOnlyTeamManager(deps.team_manager));
    deps.usage_batch = Arc::new(shadow::DiscardUsageRecords);
    deps.metrics_emitter = deps
        .metrics_emitter
        .map(|_| Arc::new(shadow::SuppressedMetricsEmitter) as _);
    deps.logs_transformer = None;
    deps.key_root = KeyRoot::Shadow;
    deps.source_offset_header = true;
    deps
}

pub fn identity(kind: ConsumerKind) -> LogsConsumerIdentity {
    match kind {
        ConsumerKind::Logs => LogsConsumerIdentity::logs(),
        ConsumerKind::Traces => LogsConsumerIdentity::traces(),
    }
}

pub fn create_producers(config: &ServiceConfig) -> anyhow::Result<HashMap<String, FutureProducer>> {
    let mut out = HashMap::new();
    for (name, overrides) in &config.producers {
        let topics: Vec<&str> = config
            .routes
            .iter()
            .filter(|r| &r.producer == name)
            .map(|r| r.topic.as_str())
            .collect();
        if topics.is_empty() {
            continue;
        }
        let mut client = producer_client_config(overrides, config.kafka_client_rack.as_deref());
        if config.mode == RunMode::Shadow {
            // A mistyped shadow topic must fail here instead of creating a topic on the cluster.
            client.set("allow.auto.create.topics", "false");
        }
        let producer: FutureProducer = client.create()?;
        let metadata = producer
            .client()
            .fetch_metadata(None, Duration::from_secs(15))
            .map_err(|e| anyhow::anyhow!("producer {name} cannot reach Kafka: {e}"))?;
        if config.mode == RunMode::Shadow {
            for topic in topics {
                require_topic(&metadata, topic)?;
            }
        }
        out.insert(name.clone(), producer);
    }
    Ok(out)
}

/// Brokers below Metadata v4 ignore `allow.auto.create.topics`, so the shadow also checks that
/// each of its topics exists before it produces. `metadata` must come from the all-topics
/// request, because those brokers create a topic that a metadata request names.
fn require_topic(metadata: &Metadata, topic: &str) -> anyhow::Result<()> {
    let exists = metadata
        .topics()
        .iter()
        .any(|t| t.name() == topic && t.error().is_none() && !t.partitions().is_empty());
    anyhow::ensure!(exists, "shadow topic {topic} does not exist");
    Ok(())
}

pub fn create_consumer(config: &ServiceConfig) -> anyhow::Result<LogsConsumer> {
    let consumer: LogsConsumer = consumer_client_config(
        &config.group_id,
        &config.kafka_consumer,
        config.kafka_client_rack.as_deref(),
        config.node_env == NodeEnv::Test,
    )
    .create_with_context(FencingContext::default())?;
    consumer.subscribe(&[config.input_topic.as_str()])?;
    Ok(consumer)
}

fn pool(url: &str, size: u32) -> anyhow::Result<PgPool> {
    Ok(common_database::get_pool_with_config(
        url,
        common_database::PoolConfig {
            max_connections: size,
            pool_name: Some(SERVICE_NAME.to_string()),
            ..Default::default()
        },
    )?)
}

pub fn build_deps(
    config: &ServiceConfig,
    outputs: Arc<KafkaOutputs>,
) -> anyhow::Result<LogsIngestionConsumerDeps> {
    let reader = pool(&config.database_reader_url, config.pool_size)?;
    let writer = match (config.mode, &config.database_writer_url) {
        (RunMode::Primary, Some(url)) => Some(pool(url, config.pool_size)?),
        _ => None,
    };
    let clock = system_clock();
    let posthog_redis =
        redis_deps::ReconnectingRedis::new(redis_deps::connection_info(&config.posthog_redis)?)?;
    let logs_redis =
        redis_deps::ReconnectingRedis::new(redis_deps::connection_info(&config.logs_redis)?)?;
    let logs = config.kind == ConsumerKind::Logs;
    let metrics_enabled = !config.metrics_export_url.is_empty();
    let usage_batch: Arc<dyn crate::pipeline::UsageRecordBatch> = match config.mode {
        RunMode::Shadow => Arc::new(shadow::DiscardUsageRecords),
        RunMode::Primary => Arc::new(usage::GrpcUsageRecordBatch::new(
            &config.usage,
            if logs { "logs" } else { "apm-traces" },
            clock.clone(),
        )?),
    };
    let deps = LogsIngestionConsumerDeps {
        team_manager: Arc::new(postgres::PgTeamManager::new(reader.clone(), writer)),
        quota_limiting: Arc::new(redis_deps::RedisQuotaLimiting::new(
            posthog_redis,
            clock.clone(),
        )),
        outputs,
        usage_batch,
        sampling_rules: logs.then(|| Arc::new(postgres::PgSamplingRules::new(reader.clone())) as _),
        metric_rules: metrics_enabled
            .then(|| Arc::new(postgres::PgMetricRules::new(reader.clone())) as _),
        metrics_emitter: if metrics_enabled {
            Some(Arc::new(LogsMetricsEmitter::new(
                config.metrics_export_url.clone(),
                shadow::ReqwestOtlpTransport::new()?,
            )) as _)
        } else {
            None
        },
        logs_transformer: None,
        retention_rules: Some(Arc::new(postgres::PgRetentionRules::new(reader.clone()))),
        pattern_message_keys: logs
            .then(|| Arc::new(postgres::PgPatternMessageKeys::new(reader.clone())) as _),
        tracing_config: (!logs)
            .then(|| Arc::new(postgres::PgTracingConfig::new(reader.clone())) as _),
        dependency_retry: DependencyRetry::default(),
        internal_source_policies: None,
        token_bucket_redis: Arc::new(RedisTokenBucket::new(logs_redis)),
        key_root: if config.node_env == NodeEnv::Test {
            KeyRoot::Test
        } else {
            KeyRoot::Production
        },
        clock,
        source_offset_header: false,
    };
    Ok(match config.mode {
        RunMode::Primary => deps,
        RunMode::Shadow => shadow_deps(deps),
    })
}

pub fn health_router(
    readiness: lifecycle::ReadinessHandler,
    liveness: lifecycle::LivenessHandler,
    render_metrics: Arc<dyn Fn() -> String + Send + Sync>,
) -> Router {
    Router::new()
        .route("/", get(|| async { SERVICE_NAME }))
        .route(
            "/_health",
            get(move || {
                let liveness = liveness.clone();
                async move { liveness.check().into_response() }
            }),
        )
        .route(
            "/_ready",
            get(move || {
                let readiness = readiness.clone();
                async move { readiness.check().await }
            }),
        )
        .route("/metrics", get(move || ready(render_metrics())))
}

/// Starts everything and blocks until shutdown. A failed batch ends the process with an error,
/// as the Node consumer lets it crash, so the restart replays from the last commit.
pub async fn run(config: ServiceConfig) -> anyhow::Result<()> {
    tracing::info!(
        kind = ?config.kind,
        mode = ?config.mode,
        group_id = %config.group_id,
        input_topic = %config.input_topic,
        routes = ?config.routes,
        "starting logs-ingestion"
    );
    let recorder = serve_metrics::setup_metrics_recorder();
    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(config.shutdown_timeout)
        .build();
    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(config.shutdown_timeout)
            .with_liveness_deadline(Duration::from_secs(300))
            .with_stall_threshold(2),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let producers = create_producers(&config)?;
    let outputs = Arc::new(KafkaOutputs::new(&config.routes, &producers)?);
    let deps = build_deps(&config, outputs.clone())?;
    let consumer = LogsIngestionConsumer::new(identity(config.kind), config.consumer.clone(), deps);
    let mut source = KafkaBatchSource::new(create_consumer(&config)?);
    let guard = manager.monitor_background();

    let loop_config = config.consumer_loop.clone();
    let consumer_task = tokio::spawn(async move {
        let handle = consumer_handle;
        let _scope = handle.process_scope();
        let tick_handle = handle.clone();
        let result = run_consumer_loop(
            &mut source,
            &consumer,
            &loop_config,
            handle.shutdown_signal(),
            &move || tick_handle.report_healthy(),
        )
        .await;
        outputs.flush(Duration::from_secs(10));
        match &result {
            Ok(stats) => tracing::info!(
                batches = stats.batches,
                messages = stats.messages,
                "consumer stopped"
            ),
            Err(error) => handle.signal_failure(format!("{error:#}")),
        }
        result
    });

    let app = health_router(readiness, liveness, Arc::new(move || recorder.render()));
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", config.http_port)).await?;
    let server_task = tokio::spawn(async move {
        let result = axum::serve(listener, app)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await;
        match &result {
            Ok(()) => metrics_handle.work_completed(),
            Err(error) => metrics_handle.signal_failure(format!("http server failed: {error}")),
        }
        result
    });
    // The monitor returns by the global shutdown deadline, so nothing after it waits unbounded.
    let monitor = guard.wait().await;
    let consumer_result = join_or_abort("consumer", consumer_task).await;
    let server_result = join_or_abort("http server", server_task).await;
    consumer_result??;
    server_result??;
    monitor?;
    Ok(())
}

async fn join_or_abort<T>(name: &str, mut task: tokio::task::JoinHandle<T>) -> anyhow::Result<T> {
    match tokio::time::timeout(TASK_JOIN_GRACE, &mut task).await {
        Ok(joined) => Ok(joined?),
        Err(_) => {
            task.abort();
            Err(anyhow::anyhow!(
                "{name} did not stop by the shutdown deadline"
            ))
        }
    }
}
