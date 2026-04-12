use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::PrometheusBuilder;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_common::{spawn_pool_monitor, MonitoredPool};

use flags_consumer::config::Config;
use flags_consumer::storage::postgres::PostgresStorage;

common_alloc::used!();

const POOL_NAME: &str = "flags_read_store";
const SERVICE_NAME: &str = "flags-consumer";

async fn create_storage(config: &Config) -> Arc<PostgresStorage> {
    let pool_config = PoolConfig {
        min_connections: config.min_pg_connections,
        max_connections: config.max_pg_connections,
        acquire_timeout: config.acquire_timeout(),
        idle_timeout: config.idle_timeout(),
        test_before_acquire: true,
        statement_timeout_ms: config.statement_timeout(),
        pool_name: Some(POOL_NAME.to_string()),
    };

    let pool = get_pool_with_config(&config.flags_read_store_database_url, pool_config)
        .expect("Failed to create flags_read_store database pool");
    tracing::info!("Created flags_read_store database pool");

    Arc::new(PostgresStorage::new(pool))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("Invalid configuration");

    // Initialize tracing
    let log_layer = fmt::layer()
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true);

    tracing_subscriber::registry()
        .with(log_layer)
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();

    tracing::info!("Starting {SERVICE_NAME} service");
    tracing::info!("Metrics port: {}", config.metrics_port);

    // Build lifecycle manager and register components
    let mut manager = Manager::builder(SERVICE_NAME).build();

    let metrics_handle = manager.register(
        "metrics_server",
        ComponentOptions::new().is_observability(true),
    );
    let main_handle = manager.register(
        "main",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let monitor = manager.monitor_background();

    // Metrics/health HTTP server (observability handle — stays alive during standard drain)
    let metrics_port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();

        let health_router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }));
        const BUCKETS: &[f64] = &[
            1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
        ];
        let recorder_handle = PrometheusBuilder::new()
            .add_global_label("service", SERVICE_NAME)
            .set_buckets(BUCKETS)
            .unwrap()
            .install_recorder()
            .expect("Failed to install metrics recorder");

        let router = health_router.route(
            "/metrics",
            get(move || std::future::ready(recorder_handle.render())),
        );

        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    // Create storage and verify connectivity before we report ready.
    let storage = create_storage(&config).await;
    storage
        .ping()
        .await
        .expect("Startup SELECT 1 against flags_read_store failed");
    tracing::info!("Startup SELECT 1 check succeeded");

    // Spawn background pool health monitor (reports personhog_db_pool_{size,idle,max} gauges)
    let pools = vec![MonitoredPool {
        pool: storage.pool.clone(),
        label: POOL_NAME.to_string(),
        max_connections: config.max_pg_connections,
    }];
    spawn_pool_monitor(
        pools,
        Duration::from_secs(config.pool_monitor_interval_secs),
    );

    // Main component loop. Step 1 is a placeholder — the future CDC consumer
    // body will live here.
    tokio::spawn(async move {
        let _guard = main_handle.process_scope();
        let shutdown = main_handle.shutdown_signal();
        tokio::pin!(shutdown);
        let mut tick = tokio::time::interval(Duration::from_secs(30));
        loop {
            tokio::select! {
                _ = &mut shutdown => {
                    tracing::info!("main loop shutting down");
                    break;
                }
                _ = tick.tick() => {
                    tracing::debug!("flags-consumer main loop idle (Step 1 skeleton)");
                }
            }
        }
    });

    monitor.wait().await?;

    Ok(())
}
