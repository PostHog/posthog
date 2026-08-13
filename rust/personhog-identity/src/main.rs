use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder};
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use personhog_common::{spawn_pool_monitor, MonitoredPool};
use personhog_proto::personhog::identity::v1::person_hog_identity_server::PersonHogIdentityServer;
use personhog_proto::personhog::lifecycle::v1::person_hog_lifecycle_server::PersonHogLifecycleServer;
use tonic::codec::CompressionEncoding;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_common::client::RouterClient;
use personhog_identity::config::Config;
use personhog_identity::leader::LifecycleLeader;
use personhog_identity::lifecycle::delete::DeleteDriver;
use personhog_identity::lifecycle::engine::Engine;
use personhog_identity::lifecycle::merge::{MergeDriver, MergeOpExecutor};
use personhog_identity::lifecycle::PersonHogLifecycleService;
use personhog_identity::service::merge::MergeEntrance;
use personhog_identity::service::PersonHogIdentityService;
use personhog_identity::storage::postgres::PostgresIdentityStorage;

common_alloc::used!();

fn create_storage(config: &Config) -> Arc<PostgresIdentityStorage> {
    let primary_pool_config = PoolConfig {
        min_connections: config.min_pg_connections,
        max_connections: config.max_pg_connections,
        acquire_timeout: config.acquire_timeout(),
        idle_timeout: config.idle_timeout(),
        test_before_acquire: false,
        statement_timeout_ms: config.statement_timeout(),
        pool_name: Some("primary".to_string()),
    };

    let primary_pool = get_pool_with_config(&config.primary_database_url, primary_pool_config)
        .expect("Failed to create primary database pool");
    tracing::info!("Created primary database pool");

    Arc::new(PostgresIdentityStorage::new(primary_pool, config.tables()))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("Invalid configuration");

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

    config
        .tables()
        .validate()
        .expect("Invalid identity table set");

    tracing::info!("Starting personhog-identity service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!("Router URL: {}", config.router_url);
    tracing::info!("Tables: {:?}", config.tables());

    // Build lifecycle manager and register components
    let mut manager = Manager::builder("personhog-identity").build();

    let grpc_handle = manager.register(
        "grpc_server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    let metrics_handle = manager.register(
        "metrics_server",
        ComponentOptions::new().is_observability(true),
    );
    // Registered here because components must exist before monitoring
    // starts; the sweeper task itself is spawned later, once the engine
    // exists. Supervision matters: with one sweeper per fleet, a silently
    // dead loop means abandoned ops are never resumed.
    let sweeper_handle = config
        .lifecycle_sweeper_enabled
        .then(|| manager.register("lifecycle_sweeper", ComponentOptions::new()));

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
        // Lifecycle ops span "settled in one drive" (tens of ms) to
        // "abandoned, parked, or leader-blocked and resumed by the sweeper"
        // (minutes to an hour); the default latency ladder tops out at 10s
        // and would collapse every resumed op into +Inf.
        const OP_DURATION_BUCKETS: &[f64] = &[
            10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 30000.0, 60000.0,
            300000.0, 1800000.0, 3600000.0,
        ];
        // Source counts, not latency; the request cap is 250.
        const MERGE_SOURCES_BUCKETS: &[f64] = &[1.0, 2.0, 3.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0];
        let recorder_handle = PrometheusBuilder::new()
            .add_global_label("service", "personhog-identity")
            .set_buckets(BUCKETS)
            .unwrap()
            .set_buckets_for_metric(
                Matcher::Full("personhog_lifecycle_op_duration_ms".into()),
                OP_DURATION_BUCKETS,
            )
            .unwrap()
            .set_buckets_for_metric(
                Matcher::Full("personhog_identity_merge_sources_per_call".into()),
                MERGE_SOURCES_BUCKETS,
            )
            .unwrap()
            .install_recorder()
            .expect("Failed to install metrics recorder");
        let metrics_router = health_router.route(
            "/metrics",
            get(move || std::future::ready(recorder_handle.render())),
        );

        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, metrics_router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    let storage = create_storage(&config);

    // Pre-warm the DB connection pool before accepting traffic.
    // connect_lazy() starts with zero connections; without this, the first
    // burst of requests after K8s routes traffic all pay the cold-start cost.
    // Warming here is safe because the gRPC server hasn't bound its port yet.
    if config.min_pg_connections > 0 {
        let warmup_count = config.min_pg_connections as usize;
        let server_warmup_count = (config.warmup_server_connections as usize).min(warmup_count);
        tracing::info!(
            count = warmup_count,
            server_warmup = server_warmup_count,
            "Warming database connection pool before accepting traffic"
        );
        let pool_start = std::time::Instant::now();
        let mut conns = Vec::with_capacity(warmup_count);
        for _ in 0..warmup_count {
            match storage.primary_pool.acquire().await {
                Ok(conn) => conns.push(conn),
                Err(e) => {
                    tracing::warn!(error = %e, "Failed to warm connection");
                    break;
                }
            }
        }
        // Run a query on a subset of held connections to warm PgBouncer → PG.
        // acquire() only establishes app → PgBouncer; in transaction pooling
        // mode PgBouncer doesn't open a server connection until a query runs.
        let mut server_warmed = 0u32;
        for conn in conns.iter_mut().take(server_warmup_count) {
            match sqlx::query("SELECT 1").execute(&mut **conn).await {
                Ok(_) => server_warmed += 1,
                Err(e) => {
                    tracing::warn!(error = %e, "Failed to warm server-side connection");
                }
            }
        }
        tracing::info!(
            client_conns = conns.len(),
            server_conns = server_warmed,
            elapsed_ms = pool_start.elapsed().as_millis() as u64,
            "Pool warmup complete"
        );
    }

    spawn_pool_monitor(
        vec![MonitoredPool {
            pool: storage.primary_pool.clone(),
            label: "primary".to_string(),
            max_connections: config.max_pg_connections,
        }],
        Duration::from_secs(config.pool_monitor_interval_secs),
    );

    let property_writer = Arc::new(
        RouterClient::new(&config.router_url, config.leader_request_timeout())
            .expect("Invalid router URL"),
    );
    // Both sagas' leader surface, reached through the router like the
    // property writes.
    let lifecycle_leader: Arc<dyn LifecycleLeader> = property_writer.clone();
    let engine = Arc::new(Engine::new(
        storage.primary_pool.clone(),
        config.lifecycle_engine_config(),
    ));
    if let Some(sweeper_handle) = sweeper_handle {
        let sweeper_merge_driver = MergeDriver::new(property_writer.clone(), config.tables());
        let sweeper_delete_driver = DeleteDriver::new(lifecycle_leader.clone(), config.tables());
        let sweeper_engine = engine.clone();
        let sweep_interval = config.lifecycle_sweep_interval();
        let retention = config.lifecycle_op_retention();
        tracing::info!(
            interval_secs = sweep_interval.as_secs(),
            retention_hours = retention.as_secs() / 3600,
            "Lifecycle sweeper enabled"
        );
        tokio::spawn(async move {
            // The scope guard tells the manager if this task dies (e.g. a
            // panic in a sweep pass), so the pod restarts instead of running
            // on with no resumer.
            let _guard = sweeper_handle.process_scope();
            let mut ticker = tokio::time::interval(sweep_interval);
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            loop {
                tokio::select! {
                    _ = sweeper_handle.shutdown_recv() => break,
                    _ = ticker.tick() => {}
                }
                match sweeper_engine
                    .sweep(&[&sweeper_delete_driver, &sweeper_merge_driver])
                    .await
                {
                    Ok(resumed) if resumed > 0 => {
                        tracing::info!(resumed, "Lifecycle sweeper resumed abandoned ops")
                    }
                    Ok(_) => {}
                    Err(e) => tracing::warn!(error = %e, "Lifecycle sweep pass failed"),
                }
                if let Err(e) = sweeper_engine.gc(retention).await {
                    tracing::warn!(error = %e, "Lifecycle GC pass failed");
                }
            }
        });
    }

    // Separate proto service co-served on the same server so lifecycle
    // callers are insulated from any future split.
    let merge_entrance = MergeEntrance::new(
        storage.clone(),
        property_writer.clone(),
        MergeOpExecutor::new(
            engine.clone(),
            MergeDriver::new(property_writer.clone(), config.tables()),
        ),
    );
    let lifecycle_service =
        PersonHogLifecycleService::new(engine, lifecycle_leader, config.tables());
    let service = PersonHogIdentityService::new(
        storage,
        property_writer,
        config.request_limits(),
        merge_entrance,
    );

    let grpc_addr = config.grpc_address;
    let keepalive_interval = config.grpc_keepalive_interval();
    let keepalive_timeout = config.grpc_keepalive_timeout();
    let max_connection_age = config.grpc_max_connection_age();
    let max_send = config.grpc_max_send_message_size;
    let max_recv = config.grpc_max_recv_message_size;
    let max_concurrent_requests = config.max_concurrent_requests;
    if max_concurrent_requests > 0 {
        tracing::info!(
            limit = max_concurrent_requests,
            "gRPC load shedding enabled"
        );
    }
    tracing::info!("Starting gRPC server on {}", grpc_addr);

    tokio::spawn(async move {
        let _guard = grpc_handle.process_scope();
        let listener = match tokio::net::TcpListener::bind(grpc_addr).await {
            Ok(l) => l,
            Err(e) => {
                grpc_handle.signal_failure(format!("Failed to bind gRPC port: {e}"));
                return;
            }
        };
        let incoming = tracked_tcp_incoming(listener);
        let mut server = Server::builder()
            .http2_keepalive_interval(keepalive_interval)
            .http2_keepalive_timeout(keepalive_timeout);
        if let Some(age) = max_connection_age {
            server = server.max_connection_age(age);
        }
        // accept_compressed only decodes gzip request frames from opted-in
        // clients (never send_compressed — see the tonic entry in Cargo.toml).
        // Note max_decoding_message_size bounds the wire (compressed) size, so
        // a compressed request can decode larger than the limit; tonic 0.12
        // does not cap the decompressed size (0.14 does — bounding this means
        // upgrading the workspace tonic). Until then this trusts internal
        // callers not to send pathological frames, same as the replica.
        if let Err(e) = server
            .layer(GrpcMetricsLayer::default().with_processing_time_header())
            .layer(GrpcLoadShedLayer::new(max_concurrent_requests))
            .add_service(
                PersonHogIdentityServer::new(service)
                    .accept_compressed(CompressionEncoding::Gzip)
                    .max_encoding_message_size(max_send)
                    .max_decoding_message_size(max_recv),
            )
            .add_service(
                PersonHogLifecycleServer::new(lifecycle_service)
                    .accept_compressed(CompressionEncoding::Gzip)
                    .max_encoding_message_size(max_send)
                    .max_decoding_message_size(max_recv),
            )
            .serve_with_incoming_shutdown(incoming, grpc_handle.shutdown_signal())
            .await
        {
            grpc_handle.signal_failure(format!("gRPC server error: {e}"));
        }
    });

    monitor.wait().await?;

    Ok(())
}
