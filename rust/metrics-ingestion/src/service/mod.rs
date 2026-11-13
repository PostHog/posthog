pub mod config;

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use ingestion_framework::KafkaMessage;
use lifecycle::{ComponentOptions, Manager};
use logs_ingestion::pipeline::UsageRecordBatch;
use logs_ingestion::rate_limiter::{system_clock, KeyRoot, RedisTokenBucket};
use logs_ingestion::service::config::RunMode;
use logs_ingestion::service::consumer_loop::{run_consumer_loop, BackgroundTask, BatchProcessor};
use logs_ingestion::service::kafka_outputs::KafkaOutputs;
use logs_ingestion::service::kafka_source::{
    consumer_client_config, FencingContext, KafkaBatchSource, LogsConsumer,
};
use logs_ingestion::service::node_env::NodeEnv;
use logs_ingestion::service::{
    create_kafka_producers, join_or_abort, named_health_router, postgres, redis_deps, shadow, usage,
};
use rdkafka::consumer::Consumer;
use sqlx::PgPool;

use crate::pipeline::unknown_tokens::UnknownTokenRecorder;
use crate::pipeline::{MetricsPipelineConsumer, MetricsPipelineConsumerDeps};
use config::ServiceConfig;

const SERVICE_NAME: &str = "metrics-ingestion";

#[async_trait]
impl BatchProcessor for MetricsPipelineConsumer {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        Ok(Some(self.handle_kafka_batch(messages).await?))
    }
}

pub fn shadow_deps(mut deps: MetricsPipelineConsumerDeps) -> MetricsPipelineConsumerDeps {
    deps.team_manager = Arc::new(shadow::ReadOnlyTeamManager(deps.team_manager));
    deps.usage_batch = Arc::new(shadow::DiscardUsageRecords);
    deps.key_root = KeyRoot::MetricsShadow;
    deps.source_offset_header = true;
    deps.unknown_tokens = None;
    deps
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
) -> anyhow::Result<MetricsPipelineConsumerDeps> {
    let reader = pool(&config.database_reader_url, config.pool_size)?;
    let writer = match (config.mode, &config.database_writer_url) {
        (RunMode::Primary, Some(url)) => Some(pool(url, config.pool_size)?),
        _ => None,
    };
    let clock = system_clock();
    let clock_for_tokens = clock.clone();
    let posthog_redis =
        redis_deps::ReconnectingRedis::new(redis_deps::connection_info(&config.posthog_redis)?)?;
    let metrics_redis =
        redis_deps::ReconnectingRedis::new(redis_deps::connection_info(&config.metrics_redis)?)?;
    let usage_batch: Arc<dyn UsageRecordBatch> = match config.mode {
        RunMode::Shadow => Arc::new(shadow::DiscardUsageRecords),
        RunMode::Primary => Arc::new(usage::GrpcUsageRecordBatch::new(
            &config.usage,
            "metrics",
            clock.clone(),
        )?),
    };
    let deps = MetricsPipelineConsumerDeps {
        team_manager: Arc::new(postgres::PgTeamManager::new(reader, writer)),
        quota_limiting: Arc::new(redis_deps::RedisQuotaLimiting::new(
            posthog_redis,
            clock.clone(),
        )),
        outputs,
        usage_batch,
        token_bucket_redis: Arc::new(RedisTokenBucket::new(metrics_redis.clone())),
        key_root: if config.node_env == NodeEnv::Test {
            KeyRoot::Test
        } else {
            KeyRoot::Production
        },
        clock,
        dev_env: config.node_env == NodeEnv::Development,
        source_offset_header: false,
        unknown_tokens: Some(Arc::new(UnknownTokenRecorder::new(
            metrics_redis,
            clock_for_tokens,
        ))),
    };
    Ok(match config.mode {
        RunMode::Primary => deps,
        RunMode::Shadow => shadow_deps(deps),
    })
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

/// A failed batch ends the process with an error, as the Node consumer crashes, so the restart replays from the last commit.
pub async fn run(config: ServiceConfig) -> anyhow::Result<()> {
    tracing::info!(
        mode = ?config.mode,
        group_id = %config.group_id,
        input_topic = %config.input_topic,
        routes = ?config.routes,
        "starting metrics-ingestion"
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

    let producers = create_kafka_producers(
        &config.routes,
        &config.producers,
        config.kafka_client_rack.as_deref(),
        config.mode,
    )?;
    let outputs = Arc::new(KafkaOutputs::new(&config.routes, &producers)?);
    let deps = build_deps(&config, outputs.clone())?;
    let consumer = MetricsPipelineConsumer::new(config.limiter.clone(), deps);
    let mut source = KafkaBatchSource::new(create_consumer(&config)?);
    let guard = manager.monitor_background();

    let loop_config = config.consumer_loop.clone();
    let drain_timeout = config.shutdown_timeout;
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
        if let Err(error) = &result {
            handle.signal_failure(format!("{error:#}"));
        }
        // Node drains side effects without a limit. The shutdown deadline bounds it here.
        if tokio::time::timeout(drain_timeout, consumer.stop())
            .await
            .is_err()
        {
            tracing::warn!("side effects still pending at the shutdown deadline");
        }
        outputs.flush(Duration::from_secs(10));
        if let Ok(stats) = &result {
            tracing::info!(
                batches = stats.batches,
                messages = stats.messages,
                "consumer stopped"
            );
        }
        result
    });

    let app = named_health_router(
        SERVICE_NAME,
        readiness,
        liveness,
        Arc::new(move || recorder.render()),
    );
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
