use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::{routing::get, Router};
use envconfig::Envconfig;
use k8s_awareness::K8sAwareness;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};
use personhog_common::grpc::{tracked_tcp_incoming, GrpcMetricsLayer};
use personhog_common::metrics::WRITE_PATH_LATENCY_BUCKETS_MS;
use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::routing_table::{RoutingTable, RoutingTableConfig, StashHandler};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::StickyBalancedStrategy;
use personhog_router::backend::discovery::{EndpointConfig, EndpointDiscovery};
use personhog_router::backend::{
    LeaderBackend, LeaderBackendConfig, ReplicaBackend, ReplicaDnsConfig, StashTable,
};
use personhog_router::config::{Config, ReplicaDiscoveryMode, RouterMode};
use personhog_router::proxy::RawProxyService;
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
    if let Err(e) = config.validate_lease_timescales() {
        panic!("invalid lease configuration: {e}");
    }
    if let Err(e) = config.validate_shutdown_budgets() {
        panic!("invalid shutdown configuration: {e}");
    }
    // Install the process-wide recorder before anything records: metrics
    // emitted ahead of it land in a no-op recorder and are dropped, and
    // preregistered series never materialize.
    let recorder_handle = install_metrics_recorder();
    preregister_metrics();

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
    tracing::info!("Replica discovery mode: {}", config.replica_discovery_mode);
    tracing::info!("Replica URL: {}", config.replica_url);
    tracing::info!("Backend timeout: {}ms", config.backend_timeout_ms);
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!(
        "Retry config: max_retries={}, initial_backoff={}ms, max_backoff={}ms",
        config.max_retries,
        config.initial_backoff_ms,
        config.max_backoff_ms
    );

    let mut manager = Manager::builder("personhog-router")
        // Below the pod's 40s termination grace so shutdown always
        // concludes process-side — reaching the routing table's lease
        // revoke — rather than racing the kubelet's SIGKILL.
        .with_global_shutdown_timeout(config.global_shutdown_timeout())
        .build();

    // Shutdown order is the inverse of the leader's: the gRPC server
    // drains first (phase 0) while the routing table, coordinator, and
    // discovery stay alive to serve its in-flight requests and keep
    // acking freezes; they stop in phase 1, at which point the
    // coordinator exits cleanly and revokes the election lease so another
    // router takes over coordination immediately.
    let grpc_handle = manager.register(
        "grpc-server",
        ComponentOptions::new().with_graceful_shutdown(config.grpc_graceful_shutdown()),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );

    // Only register coordination components in leader mode
    let (routing_table_handle, coordinator_handle) = if config.router_mode == RouterMode::Leader {
        let rt = manager.register(
            "routing-table",
            ComponentOptions::new()
                .with_graceful_shutdown(config.phase1_graceful_shutdown())
                .with_shutdown_phase(1),
        );
        let coord = config.coordinator_enabled.then(|| {
            // The whole teardown — the keepalive join and then the lease
            // revoke — is checked against this budget by
            // `validate_lease_timescales`, which runs before any of this.
            manager.register(
                "coordinator",
                ComponentOptions::new()
                    .with_graceful_shutdown(config.coordinator_graceful_shutdown())
                    .with_shutdown_phase(1),
            )
        });
        (Some(rt), coord)
    } else {
        (None, None)
    };

    // Register discovery handle before monitor_background() consumes the manager
    let discovery_handle = if config.replica_discovery_mode == ReplicaDiscoveryMode::K8s {
        Some(
            manager.register(
                "replica-discovery",
                ComponentOptions::new()
                    .with_graceful_shutdown(config.phase1_graceful_shutdown())
                    .with_shutdown_phase(1),
            ),
        )
    } else {
        None
    };

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let monitor_guard = manager.monitor_background();

    // Create backend connection(s) to personhog-replica
    let (replica_backend, discovery_readiness) = match config.replica_discovery_mode {
        ReplicaDiscoveryMode::Dns => (
            Arc::new(ReplicaBackend::new_dns(ReplicaDnsConfig {
                url: config.replica_url.clone(),
                timeout: config.backend_timeout(),
                retry_config: config.retry_config(),
                keepalive_interval: config.backend_keepalive_interval(),
                keepalive_timeout: config.backend_keepalive_timeout(),
                num_channels: config.replica_channels,
            })),
            None,
        ),
        ReplicaDiscoveryMode::K8s => {
            let kube_client = kube::Client::try_default()
                .await
                .expect("failed to create K8s client for replica discovery");
            let namespace = config
                .resolve_replica_namespace()
                .expect("failed to resolve replica service namespace");

            let discovery_handle =
                discovery_handle.expect("discovery handle must be registered in k8s mode");

            let (channel, disc_readiness, discovery) = EndpointDiscovery::new(
                kube_client,
                namespace,
                config.replica_service_name.clone(),
                config.replica_port,
                EndpointConfig {
                    timeout: config.backend_timeout(),
                    connect_timeout: config.backend_connect_timeout(),
                    keepalive_interval: config.backend_keepalive_interval(),
                    keepalive_timeout: config.backend_keepalive_timeout(),
                },
                discovery_handle.shutdown_token(),
            );

            tokio::spawn(async move {
                let _guard = discovery_handle.process_scope();
                discovery.run().await;
            });

            (
                Arc::new(ReplicaBackend::new_k8s(channel, config.retry_config())),
                Some(disc_readiness),
            )
        }
    };

    // Metrics/health HTTP server (spawned after backend creation so it can
    // include discovery readiness in the health check)
    let metrics_port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();

        let health_router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    let dr = discovery_readiness.clone();
                    async move {
                        if let Some(ref dr) = dr {
                            if !dr.is_ready() {
                                return axum::http::StatusCode::SERVICE_UNAVAILABLE;
                            }
                        }
                        r.check().await
                    }
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

    // In leader mode, wire up etcd coordination and the leader backend
    // for person writes / strong reads.
    let leader_backend: Option<Arc<LeaderBackend>> = if config.router_mode == RouterMode::Leader {
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
            participant_stall_threshold: config.participant_stall_threshold(),
            reconcile_failure_budget: config.router_reconcile_failure_budget,
            run_retry_budget: config.router_run_retry_budget,
            run_retry_backoff: Duration::from_millis(config.router_run_retry_backoff_ms),
            reconcile_interval: config.router_reconcile_interval(),
            max_txn_ops: config.etcd_max_txn_ops,
        };

        let coordination_routing_table =
            RoutingTable::new(Arc::clone(&store), routing_table_config);

        let shared_table = coordination_routing_table.table_handle();
        // Addresses come from the same etcd records that carry ownership
        // (each pod registers its advertised host:port, and the
        // coordinator copies it into handoffs and assignments), so a
        // routable owner is always dialable — there is no separate
        // discovery or DNS step to lag behind the routing table.
        let leader_addresses = coordination_routing_table.addresses_handle();
        let leader_backend = Arc::new(LeaderBackend::new(
            shared_table,
            Arc::new(move |pod_name: &str| {
                leader_addresses
                    .read()
                    .expect("addresses lock poisoned")
                    .get(pod_name)
                    .map(|address| format!("http://{address}"))
            }),
            LeaderBackendConfig {
                num_partitions,
                timeout: config.backend_timeout(),
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

        // Start coordinator (leader election + partition assignment),
        // unless this router opted out of candidacy. K8s awareness only
        // feeds the coordinator's placement decisions, so it starts (and
        // stops) with it.
        if let Some(coordinator_handle) = coordinator_handle {
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

            let coordinator = Coordinator::new(
                store,
                CoordinatorConfig {
                    name: config.pod_name.clone(),
                    leader_lease_ttl: config.coordinator_lease_ttl,
                    keepalive_interval: config.coordinator_keepalive_interval(),
                    standby_poll_interval: config.coordinator_standby_poll_interval(),
                    run_retry_backoff: config.coordinator_run_retry_backoff(),
                    backoff_decay_window: config.coordinator_backoff_decay_window(),
                    rebalance_debounce_interval: config.coordinator_rebalance_debounce_interval(),
                    reconcile_interval: config.coordinator_reconcile_interval(),
                    handoff_deadline: config.coordinator_handoff_deadline(),
                    warming_deadline: config.coordinator_warming_deadline(),
                },
                Arc::new(StickyBalancedStrategy),
                k8s_awareness,
            );

            tokio::spawn(async move {
                let _guard = coordinator_handle.process_scope();
                // No failure path back into the lifecycle manager on
                // purpose: a peer takes over for free, a restart cannot
                // mend an unwell etcd, and this process also serves
                // person writes and strong reads. It retries and
                // reports.
                coordinator.run(coordinator_handle.shutdown_token()).await;
                k8s_cancel.cancel();
            });
        } else {
            tracing::info!("coordinator election disabled; this router never campaigns");
        }

        Some(leader_backend)
    } else {
        tracing::info!("Replica mode: leader routing disabled");
        None
    };

    // gRPC server
    let grpc_addr = config.grpc_address;
    let keepalive_interval = config.grpc_keepalive_interval();
    let keepalive_timeout = config.grpc_keepalive_timeout();
    let max_recv = config.grpc_max_recv_message_size;
    let retry_config = config.retry_config();
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

        let proxy = RawProxyService::new(
            replica_backend,
            leader_backend,
            retry_config,
            max_recv,
            config.response_size_warn_bytes,
        );
        let result = Server::builder()
            .http2_keepalive_interval(keepalive_interval)
            .http2_keepalive_timeout(keepalive_timeout)
            .layer(GrpcMetricsLayer::default())
            .add_service(proxy)
            .serve_with_incoming_shutdown(incoming, grpc_handle.shutdown_signal())
            .await;

        if let Err(e) = result {
            grpc_handle.signal_failure(format!("gRPC server error: {e}"));
        }
    });

    monitor_guard.wait().await?;
    Ok(())
}

/// Must stay equal to `common_metrics::ETCD_PAYLOAD_SIZE_BUCKETS_BYTES`,
/// which every binary on the shared recorder gets. This binary builds its
/// own recorder and does not depend on that crate, but the store layer
/// emits the metric from both, and one name carrying two ladders across
/// jobs cannot be aggregated. `etcd_payload_ladder_matches_the_shared_one`
/// enforces the equality rather than leaving it to this comment.
const ETCD_PAYLOAD_SIZE_BUCKETS_BYTES: &[f64] = &[
    1024.0, 8192.0, 65536.0, 262144.0, 524288.0, 1048576.0, 1572864.0, 2097152.0, 4194304.0,
];

/// Build and install the process-wide Prometheus recorder. Runs in
/// `main` before anything records — including `preregister_metrics` —
/// because everything emitted ahead of the install lands in the default
/// no-op recorder and is silently dropped.
fn install_metrics_recorder() -> PrometheusHandle {
    const BUCKETS: &[f64] = &[
        1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
    ];
    const RESPONSE_SIZE_BUCKETS: &[f64] = &[
        256.0, 1024.0, 4096.0, 16384.0, 65536.0, 262144.0, 1048576.0, 4194304.0, 8388608.0,
        16777216.0, 33554432.0, 67108864.0,
    ];
    // Handoff phase timings are a stall detector: healthy phases
    // complete in seconds, and the interesting tail is minutes.
    // Sub-second buckets at the bottom because the source is
    // millisecond-precise; the top still reaches far past the
    // handoff deadline so a stall is never collapsed into +Inf.
    // Dense through the seconds range: healthy phases finish in
    // hundreds of milliseconds to a few seconds, and during deploy
    // churn the interesting question is where in 1–10s a phase landed —
    // the old 2s → 5s gap rendered any tail there as an interpolated
    // "4.7s" regardless of the real value. The top still reaches far
    // past the handoff deadline so a stall is never collapsed into
    // +Inf.
    const HANDOFF_PHASE_BUCKETS: &[f64] = &[
        50.0, 250.0, 500.0, 1000.0, 1500.0, 2000.0, 3000.0, 5000.0, 7500.0, 10000.0, 15000.0,
        30000.0, 60000.0, 120000.0, 300000.0, 600000.0,
    ];
    // Stash waits span "drained at activation" (hundreds of ms) to
    // "parked across chained handoffs" (seconds); the ceiling is
    // max_stash_wait, so resolution past ~30s buys nothing.
    const STASH_WAIT_BUCKETS: &[f64] = &[
        100.0, 250.0, 500.0, 1000.0, 2000.0, 3000.0, 5000.0, 7500.0, 10000.0, 15000.0, 30000.0,
    ];
    PrometheusBuilder::new()
        .add_global_label("service", "personhog-router")
        .set_buckets(BUCKETS)
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Prefix("personhog_router_response_size".into()),
            RESPONSE_SIZE_BUCKETS,
        )
        .expect("valid buckets")
        .set_buckets_for_metric(
            Matcher::Full("personhog_coordination_plan_bytes".into()),
            ETCD_PAYLOAD_SIZE_BUCKETS_BYTES,
        )
        .expect("valid buckets")
        .set_buckets_for_metric(
            Matcher::Full("assignment_coordination_etcd_payload_bytes".into()),
            ETCD_PAYLOAD_SIZE_BUCKETS_BYTES,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_coordination_handoff_phase_reached_ms".into()),
            HANDOFF_PHASE_BUCKETS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_coordination_handoff_phase_duration_ms".into()),
            HANDOFF_PHASE_BUCKETS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_router_stash_wait_duration_ms".into()),
            STASH_WAIT_BUCKETS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_router_stash_drain_duration_ms".into()),
            STASH_WAIT_BUCKETS,
        )
        .unwrap()
        // Per-request forwarding spans live in single-digit milliseconds;
        // the default ladder's 10 → 50 ms step blurs them and pins
        // interpolated quantiles to bucket edges.
        .set_buckets_for_metric(
            Matcher::Prefix("personhog_router_channel_".into()),
            WRITE_PATH_LATENCY_BUCKETS_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_router_backend_duration_ms".into()),
            WRITE_PATH_LATENCY_BUCKETS_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_router_network_overhead_ms".into()),
            WRITE_PATH_LATENCY_BUCKETS_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_router_transport_overhead_ms".into()),
            WRITE_PATH_LATENCY_BUCKETS_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("personhog_router_body_collect_ms".into()),
            WRITE_PATH_LATENCY_BUCKETS_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("grpc_server_request_duration_ms".into()),
            WRITE_PATH_LATENCY_BUCKETS_MS,
        )
        .unwrap()
        .install_recorder()
        .expect("Failed to install metrics recorder")
}

/// Touch the deploy-burst counters so their series exist with zero
/// samples before any burst. metrics registration is lazy: a counter
/// that first fires between two scrapes materializes with the burst
/// already inside it, and no rate function can recover a delta that
/// precedes a series' first sample. Only enumerable label sets are
/// touched; series with dynamic labels (client names) stay lazy.
fn preregister_metrics() {
    use metrics::counter;
    counter!("personhog_router_stash_enqueued_total").increment(0);
    counter!("personhog_router_stash_replayed_total").increment(0);
    counter!("personhog_router_forward_retries_exhausted_total").increment(0);
    for outcome in ["success", "error", "expired"] {
        counter!("personhog_router_stash_drained_total", "outcome" => outcome).increment(0);
    }
    for cause in ["max_messages", "max_bytes"] {
        counter!("personhog_router_stash_rejected_total", "cause" => cause).increment(0);
    }
    counter!("personhog_router_stash_dropped_total", "reason" => "receiver_gone").increment(0);
    for reason in ["unrouted", "fenced", "transport"] {
        counter!("personhog_router_forward_retries_total", "path" => "direct", "reason" => reason)
            .increment(0);
    }
    for reason in ["unrouted", "fenced", "transport", "cancelled"] {
        counter!("personhog_router_forward_retries_total", "path" => "stash", "reason" => reason)
            .increment(0);
    }
    personhog_coordination::preregister_router_coordination_metrics();
}

#[cfg(test)]
mod tests {
    /// The two ladders are separate literals that must agree; this
    /// test is what enforces it.
    #[test]
    fn etcd_payload_ladder_matches_the_shared_one() {
        assert_eq!(
            super::ETCD_PAYLOAD_SIZE_BUCKETS_BYTES,
            common_metrics::ETCD_PAYLOAD_SIZE_BUCKETS_BYTES,
            "one metric name carrying two bucket ladders cannot be aggregated across jobs"
        );
    }
}
