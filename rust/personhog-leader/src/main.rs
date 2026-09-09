use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::{routing::get, Router};
use common_kafka::kafka_producer::create_kafka_producer;
use common_metrics::{setup_metrics_routes_with_overrides, Matcher};
use dashmap::DashMap;
use envconfig::Envconfig;
use k8s_awareness::{K8sAwareness, PodInfo};
use kube::Client;
use lifecycle::{ComponentOptions, Manager};
use personhog_common::async_gzip::{AsyncGzipConfig, AsyncGzipLayer};
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use personhog_common::metrics::{WARM_LATENCY_BUCKETS_MS, WRITE_PATH_LATENCY_BUCKETS_MS};
use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::pod::{PodConfig, PodHandle};
use personhog_coordination::store::PersonhogStore;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use tokio::sync::Notify;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use tonic::codec::CompressionEncoding;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use metrics::{counter, gauge};
use personhog_leader::cache::{DirtyIndex, PartitionedCache};
use personhog_leader::config::Config;
use personhog_leader::coordination::LeaderHandoffHandler;
use personhog_leader::fencing::{
    preregister_fencing_metrics, FencedChangelogProducers, FencedProducerConfig,
};
use personhog_leader::inflight::InflightTracker;
use personhog_leader::pg::{validate_table_name, PgFallback};
use personhog_leader::recovery::{ChangelogRecovery, RecoveryConfig};
use personhog_leader::service::{sweep_idle_locks, PersonHogLeaderService, PropertySizeLimits};
use personhog_leader::warming::{
    fetch_writer_committed_offsets, WarmClientPools, WarmingConfig, WarmingRetryPolicy,
};
use personhog_leader::warnings::WarningsProducer;

common_alloc::used!();

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Install a process-wide rustls CryptoProvider before any TLS use. kube's
    // HTTPS client (controller discovery) uses rustls 0.23, which can't
    // auto-pick a provider with both aws-lc-rs and ring compiled in — it
    // panics. Matches personhog-router / cymbal / ingestion-consumer.
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install rustls ring CryptoProvider");

    let config = Config::init_from_env().expect("Invalid configuration");
    config
        .validate_lease_timescales()
        .expect("Invalid lease configuration");
    config
        .validate_fencing_timescales()
        .expect("Invalid fencing configuration");
    config
        .validate_shutdown_budgets()
        .expect("Invalid shutdown configuration");
    validate_table_name(&config.fallback_table).expect("Invalid FALLBACK_TABLE");

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

    tracing::info!("Starting personhog-leader service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!(
        "Cache capacity: {} bytes per partition",
        config.cache_memory_capacity_bytes
    );
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!("etcd endpoints: {}", config.etcd_endpoints);
    tracing::info!("etcd prefix: {}", config.etcd_prefix);
    tracing::info!("Pod name: {}", config.pod_name);
    tracing::info!("Kafka changelog topic: {}", config.kafka_person_state_topic);

    // Shutdown order matters: the coordination drain (phase 0) hands this
    // pod's partitions off, which requires the gRPC server to keep serving
    // reads and completing in-flight writes and the producer to keep
    // delivering their changelog records. Server and producer therefore
    // stop in phase 1, only after the drain finishes — signalling them
    // together with coordination black-holed every partition for the whole
    // drain (dead server, still the registered owner). The coordination
    // window must fit the pod's whole teardown — drain, fence, keepalive
    // join, revoke — and the global timeout both phases;
    // `validate_lease_timescales` refuses a configuration that breaks
    // the first relation at startup.
    let mut manager = Manager::builder("personhog-leader")
        .with_global_shutdown_timeout(config.global_shutdown_timeout())
        .build();

    let grpc_handle = manager.register(
        "grpc-server",
        ComponentOptions::new()
            .with_graceful_shutdown(config.phase1_graceful_shutdown())
            .with_shutdown_phase(1),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let coordination_handle = manager.register(
        "coordination",
        ComponentOptions::new().with_graceful_shutdown(config.coordination_graceful_shutdown()),
    );
    let kafka_handle = manager.register(
        "kafka-producer",
        // The graceful window is the ceiling; the bounded flush task
        // spawned after the producer is built normally completes well
        // inside it.
        ComponentOptions::new()
            .with_graceful_shutdown(config.phase1_graceful_shutdown())
            .with_shutdown_phase(1),
    );

    let authority_metrics_handle = manager.register(
        "authority-metrics",
        ComponentOptions::new().is_observability(true),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let monitor_guard = manager.monitor_background();

    // Metrics/health HTTP server. The router is built here rather than
    // inside the task because `setup_metrics_routes_with_overrides` is
    // what installs the process-wide recorder: anything preregistered
    // before it lands in a no-op recorder and never becomes a series.
    let metrics_port = config.metrics_port;
    let health_router = Router::new()
        .route(
            "/_readiness",
            get(move || {
                let r = readiness.clone();
                async move { r.check().await }
            }),
        )
        .route("/_liveness", get(move || async move { liveness.check() }));
    // Changelog payload sizes: dense through the small-person range,
    // with the top boundaries straddling the broker's message.max.bytes
    // (typically 1 MiB) so p99 creeping toward the produce limit is
    // visible before messages start getting rejected.
    const CHANGELOG_PRODUCE_SIZE_BUCKETS_BYTES: &[f64] = &[
        256.0, 1024.0, 4096.0, 16384.0, 65536.0, 262144.0, 524288.0, 1048576.0, 2097152.0,
    ];
    // The write path and warms are tuned in single-digit milliseconds;
    // the default ladder's 10 → 50 ms step blurs exactly the spans the
    // fencing and warm work steers by, and pins interpolated quantiles
    // to bucket edges. Overridden per metric so seconds-scale histograms
    // keep the cheap default ladder.
    let metrics_router = setup_metrics_routes_with_overrides(
        health_router,
        &[
            (
                Matcher::Full("personhog_leader_kafka_produce_duration_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_fence_send_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_fence_ack_wait_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_fence_window_wait_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_fence_commit_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_fence_init_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_person_lock_wait_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("grpc_server_request_duration_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_warm_duration_ms".into()),
                WARM_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_coordination_partition_warm_ms".into()),
                WARM_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_warm_span_ms".into()),
                WARM_LATENCY_BUCKETS_MS,
            ),
            (
                Matcher::Full("personhog_leader_kafka_produce_bytes".into()),
                CHANGELOG_PRODUCE_SIZE_BUCKETS_BYTES,
            ),
        ],
    );
    preregister_metrics();
    // The refusals the gate can emit: rare by design, and a burst is
    // exactly what a deploy-window scrape would otherwise miss.
    for reason in ["surrendered", "stale"] {
        counter!(
            "personhog_leader_authority_lapsed_rejections_total",
            "reason" => reason
        )
        .increment(0);
        for phase in ["warm", "resume"] {
            counter!(
                "personhog_leader_authority_lapsed_acquires_total",
                "phase" => phase,
                "reason" => reason
            )
            .increment(0);
        }
    }
    for phase in ["warm", "resume"] {
        counter!(
            "personhog_leader_authority_lapsed_mid_acquire_total",
            "phase" => phase
        )
        .increment(0);
    }
    counter!("personhog_leader_unresolved_versions_total").increment(0);
    counter!("personhog_leader_unresolved_versions_spilled_total").increment(0);
    gauge!("personhog_leader_unresolved_versions").set(0.0);

    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();

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

    // Initialize partitioned cache and Kafka producer
    let cache = Arc::new(PartitionedCache::new(config.cache_memory_capacity_bytes));

    let kafka_producer = match create_kafka_producer(&config.kafka, kafka_handle.clone()).await {
        Ok(producer) => producer,
        Err(e) => {
            tracing::error!(error = %e, "failed to create Kafka producer");
            return Err(e.into());
        }
    };
    // Runs at phase 1, after the coordination drain, so the drain's last
    // records are in the queue it flushes.
    personhog_leader::kafka::spawn_bounded_flush_on_shutdown(
        kafka_producer.clone(),
        kafka_handle,
        Duration::from_secs(10),
    );

    // PG fallback pool for cache misses (optional, disabled if URL is empty)
    let fallback = if config.fallback_database_url.is_empty() {
        tracing::info!("PG fallback disabled (no FALLBACK_DATABASE_URL)");
        None
    } else {
        tracing::info!("PG fallback enabled");
        let pool_config = common_database::PoolConfig {
            max_connections: config.fallback_pg_max_connections,
            min_connections: config.fallback_pg_min_connections,
            pool_name: Some("personhog-leader-fallback".to_string()),
            statement_timeout_ms: Some(5_000),
            ..Default::default()
        };
        Some(PgFallback {
            pool: common_database::get_pool_with_config(
                &config.fallback_database_url,
                pool_config,
            )?,
            table: config.fallback_table.clone(),
        })
    };

    // Connect to etcd for coordination and the partition count
    let etcd_config = StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    };
    let etcd_store = EtcdStore::connect(etcd_config)
        .await
        .expect("Failed to connect to etcd");
    let store = Arc::new(PersonhogStore::new(etcd_store));

    // Read total_partitions from etcd (set by kafka-assigner) — the same
    // source the router hashes against, so partition validation can never
    // drift between the two.
    let num_partitions = store
        .get_total_partitions()
        .await
        .expect("Failed to read total_partitions from etcd");
    tracing::info!(num_partitions, "loaded partition count from etcd");

    let locks = Arc::new(DashMap::new());
    let fences: personhog_leader::fence::FenceMap = Arc::new(DashMap::new());
    let inflight = Arc::new(InflightTracker::new());
    let dirty_index = Arc::new(DirtyIndex::new(config.dirty_index_max_entries));
    // One per pod, shared by the service that raises floors and the
    // handler that drops them with the partition. The same bound the
    // dirty index uses: both hold one entry per person written but not
    // yet settled, and both are attackable the same way.
    let emitted_versions = Arc::new(personhog_leader::emitted::EmittedVersions::new(
        config.emitted_versions_max_entries,
    ));
    let recovery = Arc::new(
        ChangelogRecovery::new(RecoveryConfig {
            kafka: config.kafka.clone(),
            topic: config.kafka_person_state_topic.clone(),
            pod_name: config.pod_name.clone(),
            recv_timeout: Duration::from_secs(config.recovery_recv_timeout_secs),
            pool_size: config.recovery_pool_size,
        })
        .expect("Failed to build changelog recovery consumer pool"),
    );
    let warnings = WarningsProducer::new(
        kafka_producer.clone(),
        config.ingestion_warnings_topic.clone(),
    );
    let fence_scan_pool = fallback.as_ref().map(|f| f.pool.clone());
    let mut fence_repair_nudge: Option<Arc<Notify>> = None;
    let fenced = if config.kafka_transactional_fencing {
        // Every one of these is derived from LEASE_TTL rather than set
        // directly, so an operator debugging a fenced-write timeout has
        // no way to recover them without re-running the derivation by
        // hand.
        tracing::info!(
            window_ms = config.fencing_window_ms,
            message_timeout_ms = config.fencing_message_timeout().as_millis(),
            txn_timeout_ms = config.fencing_txn_timeout().as_millis(),
            broker_txn_timeout_ms = config.fencing_broker_txn_timeout().as_millis(),
            lease_runway_ms = config.lease_fence_runway().as_millis(),
            "broker-enforced epoch fencing enabled for the changelog"
        );
        preregister_fencing_metrics(num_partitions);
        // A condemned producer's repair otherwise waits for the next
        // reconcile tick; this nudge lets the condemnation itself
        // trigger the repair pass that heals it.
        let repair_nudge = Arc::new(Notify::new());
        fence_repair_nudge = Some(Arc::clone(&repair_nudge));
        // The fenced producer runs on a tighter message timeout than the
        // shared one: its writes must resolve inside the lease runway.
        let fencing_kafka = common_kafka::config::KafkaConfig {
            kafka_message_timeout_ms: config.fencing_message_timeout().as_millis() as u32,
            // One producer per owned partition, so the shared producer's
            // queue limits are an aggregate to divide rather than a
            // per-producer figure to copy.
            kafka_producer_queue_mib: config.fencing_queue_mib(num_partitions),
            kafka_producer_queue_messages: config.fencing_queue_messages(num_partitions),
            ..config.kafka.clone()
        };
        Some(Arc::new(
            FencedChangelogProducers::new(FencedProducerConfig {
                kafka: fencing_kafka,
                topic: config.kafka_person_state_topic.clone(),
                init_timeout: config.fencing_init_timeout(),
                commit_timeout: config.fencing_txn_timeout(),
                broker_txn_timeout: config.fencing_broker_txn_timeout(),
                window: Duration::from_millis(config.fencing_window_ms),
                window_max_writes: config.fencing_window_max_writes,
                settle_budget: config.fencing_settle_budget(),
            })
            .with_repair_nudge(repair_nudge),
        ))
    } else {
        None
    };

    // One clock for the process: the coordination session claims and
    // surrenders it, the data plane reads it per request.
    let authority = Arc::new(AuthorityClock::unclaimed());
    // Publish the live headroom whether or not the gate is armed: the
    // question before enabling it is how close this fleet routinely runs
    // to the margin, and that has to be answerable from a deployment
    // that is not yet enforcing anything.
    //
    // This says nothing about a process-wide stall — a task that cannot
    // run cannot report that it cannot run, which is the same limitation
    // the clock exists to route around, and why enforcement reads the
    // stamp inline on the request path instead of trusting a publisher.
    // What it does show is a keepalive falling behind while the rest of
    // the process is healthy, and the steady-state distance from the
    // margin.
    {
        let authority = Arc::clone(&authority);
        let handle = authority_metrics_handle;
        tokio::spawn(async move {
            let _guard = handle.process_scope();
            let mut shutdown = std::pin::pin!(handle.shutdown_signal());
            let mut tick = tokio::time::interval(Duration::from_secs(5));
            loop {
                tokio::select! {
                    _ = &mut shutdown => break,
                    _ = tick.tick() => {}
                }
                // Before the first grant there is no claim to measure
                // against: age would read as process uptime and margin as
                // zero, which any threshold would treat as a permanent
                // emergency.
                if !authority.is_claimed() {
                    continue;
                }
                gauge!("personhog_leader_authority_valid").set(if authority.is_valid() {
                    1.0
                } else {
                    0.0
                });
                gauge!("personhog_leader_authority_age_ms")
                    .set(authority.since_confirmed().as_secs_f64() * 1000.0);
                gauge!("personhog_leader_authority_margin_ms")
                    .set(authority.margin().as_secs_f64() * 1000.0);
            }
        });
    }

    let gated_authority = if config.lease_gated_authority {
        tracing::info!(
            "lease-gated authority enabled: reads and fence acquisition require a \
                        confirmed lease renewal within the keepalive margin"
        );
        Some(Arc::clone(&authority))
    } else {
        None
    };

    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer.clone(),
        config.kafka_person_state_topic.clone(),
        fallback,
        Arc::clone(&locks),
        Arc::clone(&inflight),
        num_partitions,
        Arc::clone(&dirty_index),
        Arc::clone(&recovery),
        PropertySizeLimits::new(
            config.properties_size_threshold,
            config.properties_trim_target,
        ),
        warnings.clone(),
        Arc::clone(&fences),
        fenced.clone(),
        gated_authority.clone(),
        Arc::clone(&emitted_versions),
    )
    .with_fence_capacity(config.fence_map_max_entries);

    let warm_pools = Arc::new(WarmClientPools::new(
        &config.kafka,
        &config.pod_name,
        &config.writer_consumer_group,
    ));
    let handler = LeaderHandoffHandler::new(
        Arc::clone(&cache),
        Arc::clone(&inflight),
        Arc::clone(&dirty_index),
        WarmingConfig {
            kafka: config.kafka.clone(),
            topic: config.kafka_person_state_topic.clone(),
            pod_name: config.pod_name.clone(),
            writer_consumer_group: config.writer_consumer_group.clone(),
            lookback_offsets: config.warm_lookback_offsets,
            committed_offsets_timeout: Duration::from_secs(
                config.warm_committed_offsets_timeout_secs,
            ),
            fetch_watermarks_timeout: Duration::from_secs(
                config.warm_fetch_watermarks_timeout_secs,
            ),
            recv_timeout: Duration::from_secs(config.warm_recv_timeout_secs),
            retry: WarmingRetryPolicy {
                max_attempts: config.warm_retry_max_attempts,
                initial_backoff: Duration::from_millis(config.warm_retry_initial_backoff_ms),
                max_backoff: Duration::from_millis(config.warm_retry_max_backoff_ms),
            },
        },
        Arc::clone(&fences),
        fence_scan_pool,
        num_partitions,
        Arc::clone(&warm_pools),
        fenced.clone(),
        gated_authority.clone(),
        Arc::clone(&emitted_versions),
    );
    let advertise_address =
        personhog_leader::config::derive_advertise_address(&config.grpc_address, &config.pod_ip)
            .expect("Invalid advertise address configuration");
    tracing::info!(%advertise_address, "advertising gRPC address for routing");

    // Discover this pod's owning controller and generation so the
    // coordinator can steer placement away from old-generation pods
    // during rollouts. Fail-open, and bounded: this runs before the pod
    // handle and gRPC server exist, so an unresponsive API server must
    // cost a few seconds of startup at worst — never availability.
    let (controller, generation, k8s_awareness) = if config.k8s_awareness_enabled {
        let discovery = discover_own_controller(&config, coordination_handle.shutdown_token());
        match timeout(K8S_DISCOVERY_TIMEOUT, discovery).await {
            Ok(Ok((awareness, info))) => {
                tracing::info!(
                    controller = %info.controller,
                    generation = %info.generation,
                    "K8s awareness enabled; controller discovered"
                );
                (Some(info.controller), info.generation, Some(awareness))
            }
            Ok(Err(e)) => {
                tracing::warn!(
                    error = %e,
                    "K8s awareness enabled but controller discovery failed; \
                     registering without rollout awareness"
                );
                (None, String::new(), None)
            }
            Err(_) => {
                tracing::warn!(
                    timeout = ?K8S_DISCOVERY_TIMEOUT,
                    "K8s awareness enabled but controller discovery timed out; \
                     registering without rollout awareness"
                );
                (None, String::new(), None)
            }
        }
    } else {
        (None, String::new(), None)
    };

    // Timescale and concurrency knobs come from `base_pod_config`, the
    // same values `validate_lease_timescales` summed at startup; only
    // the identity fields, which no validation reads, are filled here.
    let pod_config = PodConfig {
        pod_name: config.pod_name.clone(),
        generation,
        controller,
        advertise_address: Some(advertise_address),
        ..config.base_pod_config()
    };

    // Open connections up front: warms cluster in deploy bursts, and a
    // cold pool would make every burst's first operations pay the client
    // setup the pool exists to amortize. Sized from the pod's actual
    // configured warm concurrency — the bound the semaphore enforces —
    // so the pool and the concurrency limit cannot drift apart.
    // Committed-offset queries run one per concurrent warm, so the
    // offsets pool needs the same depth; it also serves the dirty-index
    // prune tick.
    //
    // Awaited before the pod registers for partitions: a deploy burst
    // hands this pod partitions immediately, and a warm that finds the
    // pool empty builds its clients cold inside the handoff — seconds of
    // connection setup on the path the pool exists to keep off. The
    // deadline keeps a broker outage from wedging boot; past it,
    // registration proceeds and the remaining slots are built cold, so
    // this stays best-effort.
    {
        let warm_slots = pod_config.warm_concurrency;
        let warm_up = async {
            tokio::join!(
                warm_pools.offsets.warm_up(warm_slots),
                warm_pools.warming.warm_up(warm_slots),
            );
        };
        if timeout(POOL_WARM_UP_DEADLINE, warm_up).await.is_err() {
            tracing::warn!(
                deadline_secs = POOL_WARM_UP_DEADLINE.as_secs(),
                "consumer pool warm-up hit its deadline; continuing with a partially cold pool"
            );
        }
    }

    let mut pod = PodHandle::new(
        store,
        pod_config,
        Arc::new(handler),
        k8s_awareness,
        Arc::clone(&authority),
    );
    if let Some(nudge) = fence_repair_nudge.take() {
        pod = pod.with_repair_nudge(nudge);
    }

    tokio::spawn(async move {
        let _guard = coordination_handle.process_scope();
        if let Err(e) = pod.run(coordination_handle.shutdown_token()).await {
            coordination_handle.signal_failure(format!("Coordination error: {e}"));
        }
    });

    // Periodic sweep of idle per-key locks, refilled warning-throttle
    // keys, and parked fence connections nothing consumed (a cancelled
    // inbound handoff leaves no convergence behind to discard them).
    let sweep_locks = Arc::clone(&locks);
    let sweep_warnings = warnings.clone();
    let sweep_fenced = fenced.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(60));
        loop {
            interval.tick().await;
            sweep_idle_locks(&sweep_locks);
            sweep_warnings.sweep_throttle();
            if let Some(fenced) = &sweep_fenced {
                fenced.sweep_prepared();
            }
        }
    });

    tokio::spawn(run_dirty_index_prune_loop(
        Arc::clone(&dirty_index),
        Arc::clone(&cache),
        Arc::clone(&warm_pools),
        config.kafka_person_state_topic.clone(),
        Duration::from_secs(config.warm_committed_offsets_timeout_secs),
        Duration::from_secs(config.dirty_index_prune_interval_secs.max(1)),
    ));

    // gRPC server. Mirrors the replica's middleware stack so the router's
    // per-backend metrics (processing time, transport/network overhead) and
    // response compression behave identically on both backends. No tonic
    // codec compression: requests always arrive uncompressed (the router
    // rejects compressed leader requests before forwarding — it scans the
    // request bytes for the routing key), and response compression is
    // exclusively the gzip layer.
    let grpc_addr = config.grpc_address;
    let keepalive_interval = config.grpc_keepalive_interval();
    let keepalive_timeout = config.grpc_keepalive_timeout();
    let max_connection_age = config.grpc_max_connection_age();
    let max_send = config.grpc_max_send_message_size;
    let max_recv = config.grpc_max_recv_message_size;
    let max_concurrent_requests = config.max_concurrent_requests;
    let max_response_size = if config.gzip_max_response_size > 0 {
        Some(config.gzip_max_response_size)
    } else {
        None
    };
    let gzip_config = AsyncGzipConfig::new(
        config.gzip_response_compression,
        config.gzip_compression_level,
        config.gzip_min_payload_size,
    )
    .with_max_response_size(max_response_size, config.gzip_max_response_size_enforce);

    if gzip_config.enabled {
        tracing::info!(
            level = gzip_config.compression_level,
            min_payload_size = gzip_config.min_payload_size,
            "Async gzip response compression enabled"
        );
    }
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
        if let Err(e) = server
            .layer(AsyncGzipLayer::new(gzip_config))
            .layer(GrpcMetricsLayer::default().with_processing_time_header())
            .layer(GrpcLoadShedLayer::new(max_concurrent_requests))
            .add_service(
                // accept_compressed only decodes gzip request frames from
                // opted-in clients; responses stay with the AsyncGzipLayer
                // (never send_compressed — see the tonic entry in Cargo.toml).
                PersonHogLeaderServer::new(service)
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

    monitor_guard.wait().await?;
    Ok(())
}

/// Periodically drop dirty-index marks the writer has applied to PG, and
/// export the dirty-count and writer-lag gauges as a side effect. One
/// batched OffsetFetch covers every partition with marks, on a pooled
/// client — each tick reuses the connection instead of rebuilding one.
async fn run_dirty_index_prune_loop(
    dirty_index: Arc<DirtyIndex>,
    cache: Arc<PartitionedCache>,
    pools: Arc<WarmClientPools>,
    topic: String,
    offsets_timeout: Duration,
    prune_interval: Duration,
) {
    let mut interval = tokio::time::interval(prune_interval);
    loop {
        interval.tick().await;
        // One batched OffsetFetch, then queue pops proportional to the
        // marks actually reclaimed — a tick never scans the index, which
        // is what makes the 1s interval affordable even when a lagging
        // writer has made the index large.
        let partitions = dirty_index.partitions_with_marks();
        gauge!("personhog_leader_dirty_index_size").set(dirty_index.len() as f64);
        gauge!("personhog_leader_dirty_index_max_entries").set(dirty_index.max_entries() as f64);
        gauge!("personhog_leader_cache_weight_bytes").set(cache.usage_bytes() as f64);
        if partitions.is_empty() {
            continue;
        }
        let committed_offsets = match fetch_writer_committed_offsets(
            &pools.offsets,
            &topic,
            &partitions,
            offsets_timeout,
        )
        .await
        {
            Ok(offsets) => offsets,
            Err(e) => {
                tracing::warn!(error = %e, "dirty-index prune offset fetch failed");
                continue;
            }
        };

        let pruned = dirty_index.prune_applied(&committed_offsets);
        if pruned > 0 {
            counter!("personhog_leader_dirty_index_pruned_total").increment(pruned as u64);
        }
        // A partition absent from the committed offsets has no writer
        // commit yet: nothing is applied, every mark stays, and its lag
        // is the entire marked backlog. A partition the prune fully
        // reclaimed has no live marks left — the writer caught up, so its
        // lag reads zero.
        for partition in &partitions {
            let lag = match dirty_index.max_offset(*partition) {
                Some(max_offset) => {
                    let committed = committed_offsets.get(partition).copied().unwrap_or(0);
                    (max_offset + 1 - committed).max(0)
                }
                None => 0,
            };
            gauge!(
                "personhog_leader_writer_uncommitted_offsets",
                "partition" => partition.to_string()
            )
            .set(lag as f64);
        }
    }
}

/// How long startup may spend on controller discovery before falling
/// open. Generous against a healthy API server (three small reads);
/// tight against an unresponsive one, which must not delay serving.
const K8S_DISCOVERY_TIMEOUT: Duration = Duration::from_secs(5);

/// Upper bound on the pre-registration consumer-pool warm-up. Generous
/// against MSK connection setup (~1–2s per client, run concurrently),
/// tight enough that a broker outage delays boot rather than blocking it.
const POOL_WARM_UP_DEADLINE: Duration = Duration::from_secs(10);

/// Build a K8s awareness client and discover this pod's owning controller
/// and generation. The awareness handle is returned alongside so the pod
/// can also classify its own departure at drain time.
async fn discover_own_controller(
    config: &Config,
    cancel: CancellationToken,
) -> Result<(Arc<K8sAwareness>, PodInfo), String> {
    let namespace = config.resolve_k8s_namespace()?;
    let client = Client::try_default()
        .await
        .map_err(|e| format!("failed to create K8s client: {e}"))?;
    let awareness = Arc::new(K8sAwareness::new(client, namespace, cancel));
    let info = awareness
        .discover_controller(&config.pod_name)
        .await
        .map_err(|e| format!("controller discovery failed: {e}"))?;
    Ok((awareness, info))
}

/// Touch the leader's deploy-burst counters so their series exist with
/// zero samples before any burst. metrics registration is lazy: a counter
/// that first fires between two scrapes materializes with the burst
/// already inside it, and no rate function can recover a delta that
/// precedes a series' first sample.
fn preregister_metrics() {
    for fenced in ["true", "false"] {
        counter!("personhog_leader_indeterminate_outcomes_total", "fenced" => fenced).increment(0);
    }
    counter!("personhog_leader_unresolved_versions_total").increment(0);
    gauge!("personhog_leader_unresolved_versions").set(0.0);
    counter!("personhog_leader_warmed_messages_total").increment(0);
    counter!("personhog_leader_warm_retries_exhausted_total", "stage" => "committed_offset")
        .increment(0);
    counter!("personhog_leader_warm_retries_exhausted_total", "stage" => "fetch_watermarks")
        .increment(0);
    for stage in ["committed_offset", "fetch_watermarks"] {
        counter!("personhog_leader_warm_retries_total", "stage" => stage).increment(0);
    }
    // A broker blip is short enough to fall entirely between two
    // scrapes, and these fire only during one. The codes seen in dev are
    // preregistered so that burst is not swallowed; anything else stays
    // lazy, as elsewhere for dynamic labels.
    for code in ["BrokerTransportFailure", "AllBrokersDown"] {
        counter!("personhog_leader_warm_transient_errors_total", "code" => code).increment(0);
    }
}
