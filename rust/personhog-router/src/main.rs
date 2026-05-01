use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::{routing::get, Router};
use envconfig::Envconfig;
use k8s_awareness::K8sAwareness;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::PrometheusBuilder;
use personhog_common::grpc::{tracked_tcp_incoming, GrpcMetricsLayer};
use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::routing_table::{RoutingTable, RoutingTableConfig, StashHandler};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::StickyBalancedStrategy;
use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogServiceServer;
use personhog_router::backend::{
    LeaderBackend, LeaderBackendConfig, ReplicaBackend, ReplicaBackendConfig, StashTable,
};
use personhog_router::config::{Config, RouterMode};
use personhog_router::router::PersonHogRouter;
use personhog_router::service::PersonHogRouterService;
use personhog_router::stash_handler::RouterStashHandler;
use tokio_util::sync::CancellationToken;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

common_alloc::used!();

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("Failed to install rustls crypto provider");

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

    tracing::info!("Starting personhog-router service");
    tracing::info!("Router mode: {}", config.router_mode);
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!("Replica URL: {}", config.replica_url);
    tracing::info!("Replica channels: {}", config.replica_channels);
    tracing::info!("Backend timeout: {}ms", config.backend_timeout_ms);
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!(
        "Retry config: max_retries={}, initial_backoff={}ms, max_backoff={}ms",
        config.max_retries,
        config.initial_backoff_ms,
        config.max_backoff_ms
    );

    let mut manager = Manager::builder("personhog-router")
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();

    let grpc_handle = manager.register(
        "grpc-server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );

    // Only register coordination components in leader mode
    let (routing_table_handle, coordinator_handle) = if config.router_mode == RouterMode::Leader {
        let rt = manager.register(
            "routing-table",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
        );
        let coord = manager.register(
            "coordinator",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
        );
        (Some(rt), Some(coord))
    } else {
        (None, None)
    };

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let monitor_guard = manager.monitor_background();

    // Metrics/health HTTP server (observability handle — stays alive during standard drain)
    let metrics_port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();

        const BUCKETS: &[f64] = &[
            1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
        ];
        let recorder_handle = PrometheusBuilder::new()
            .add_global_label("service", "personhog-router")
            .set_buckets(BUCKETS)
            .unwrap()
            .install_recorder()
            .expect("Failed to install metrics recorder");

        let health_router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }))
            .route(
                "/metrics",
                get(move || std::future::ready(recorder_handle.render())),
            );

        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, health_router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    // Create backend connection(s) to personhog-replica
    let replica_backend = ReplicaBackend::new(ReplicaBackendConfig {
        url: config.replica_url.clone(),
        timeout: config.backend_timeout(),
        retry_config: config.retry_config(),
        keepalive_interval: config.backend_keepalive_interval(),
        keepalive_timeout: config.backend_keepalive_timeout(),
        max_send_message_size: config.grpc_max_send_message_size,
        max_recv_message_size: config.grpc_max_recv_message_size,
        num_channels: config.replica_channels,
    });

    // Build the router — in leader mode, also wire up etcd coordination
    // and the leader backend for person writes / strong reads.
    let router = if config.router_mode == RouterMode::Leader {
        tracing::info!("Leader mode: connecting to etcd");
        tracing::info!("etcd endpoints: {}", config.etcd_endpoints);
        tracing::info!("etcd prefix: {}", config.etcd_prefix);
        tracing::info!("Router name: {}", config.pod_name);

        let etcd_config = StoreConfig {
            endpoints: config.etcd_endpoint_list(),
            prefix: config.etcd_prefix.clone(),
        };
        let etcd_store = EtcdStore::connect(etcd_config)
            .await
            .expect("Failed to connect to etcd");
        let store = Arc::new(PersonhogStore::new(etcd_store));

        // Read total_partitions from etcd (set by kafka-assigner)
        let num_partitions = store
            .get_total_partitions()
            .await
            .expect("Failed to read total_partitions from etcd");
        tracing::info!(num_partitions, "loaded partition count from etcd");

        // Build the routing table and leader backend, sharing the same
        // partition-to-pod mapping so both see consistent state.
        let routing_table_config = RoutingTableConfig {
            router_name: config.pod_name.clone(),
            lease_ttl: config.lease_ttl,
            heartbeat_interval: config.heartbeat_interval(),
        };

        let coordination_routing_table =
            RoutingTable::new(Arc::clone(&store), routing_table_config);

        let shared_table = coordination_routing_table.table_handle();
        let leader_port = config.leader_port;
        let leader_backend = Arc::new(LeaderBackend::new(
            shared_table,
            Arc::new(move |pod_name: &str| Some(format!("http://{}:{}", pod_name, leader_port))),
            LeaderBackendConfig {
                num_partitions,
                timeout: config.backend_timeout(),
                retry_config: config.retry_config(),
                max_send_message_size: config.grpc_max_send_message_size,
                max_recv_message_size: config.grpc_max_recv_message_size,
            },
            StashTable::with_bounds(
                config.stash_max_messages_per_partition,
                config.stash_max_bytes_per_partition,
            ),
        ));

        let stash_handler: Arc<dyn StashHandler> = Arc::new(RouterStashHandler::new(
            Arc::clone(&leader_backend),
            config.stash_max_wait(),
            config.stash_drain_concurrency,
        ));

        // Start routing table (etcd registration + assignment/handoff watches)
        let routing_table_handle =
            routing_table_handle.expect("routing-table handle must be registered in leader mode");

        tokio::spawn(async move {
            let _guard = routing_table_handle.process_scope();
            if let Err(e) = coordination_routing_table
                .run(routing_table_handle.shutdown_token(), stash_handler)
                .await
            {
                routing_table_handle.signal_failure(format!("Routing table error: {e}"));
            }
        });

        // K8s awareness (optional)
        let k8s_cancel = CancellationToken::new();
        let k8s_awareness = if config.k8s_awareness_enabled {
            let namespace = config
                .resolve_k8s_namespace()
                .expect("k8s awareness enabled but namespace resolution failed");
            let client = kube::Client::try_default()
                .await
                .expect("failed to create K8s client");
            tracing::info!(%namespace, "K8s awareness enabled");
            Some(Arc::new(K8sAwareness::new(
                client,
                namespace,
                k8s_cancel.child_token(),
            )))
        } else {
            tracing::info!("K8s awareness disabled");
            None
        };

        // Start coordinator (leader election + partition assignment)
        let coordinator_handle =
            coordinator_handle.expect("coordinator handle must be registered in leader mode");
        let coordinator = Coordinator::new(
            store,
            CoordinatorConfig {
                name: config.pod_name.clone(),
                leader_lease_ttl: config.coordinator_lease_ttl,
                keepalive_interval: config.coordinator_keepalive_interval(),
                election_retry_interval: config.coordinator_election_retry_interval(),
                rebalance_debounce_interval: config.coordinator_rebalance_debounce_interval(),
            },
            Arc::new(StickyBalancedStrategy),
            k8s_awareness,
        );

        tokio::spawn(async move {
            let _guard = coordinator_handle.process_scope();
            if let Err(e) = coordinator.run(coordinator_handle.shutdown_token()).await {
                coordinator_handle.signal_failure(format!("Coordinator error: {e}"));
            }
            k8s_cancel.cancel();
        });

        PersonHogRouter::new(Arc::new(replica_backend)).with_leader(leader_backend)
    } else {
        tracing::info!("Replica mode: leader routing disabled");
        PersonHogRouter::new(Arc::new(replica_backend))
    };

    let service = PersonHogRouterService::new(Arc::new(router));

    // gRPC server
    let grpc_addr = config.grpc_address;
    let keepalive_interval = config.grpc_keepalive_interval();
    let keepalive_timeout = config.grpc_keepalive_timeout();
    let max_send = config.grpc_max_send_message_size;
    let max_recv = config.grpc_max_recv_message_size;
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
        if let Err(e) = Server::builder()
            .http2_keepalive_interval(keepalive_interval)
            .http2_keepalive_timeout(keepalive_timeout)
            .layer(GrpcMetricsLayer)
            .add_service(
                PersonHogServiceServer::new(service)
                    .max_encoding_message_size(max_send)
                    .max_decoding_message_size(max_recv),
            )
            .serve_with_incoming_shutdown(incoming, grpc_handle.shutdown_signal())
            .await
        {
            grpc_handle.signal_failure(format!("gRPC server error: {e}"));
        }
    });

    monitor_guard.wait().await?;
    Ok(())
}
