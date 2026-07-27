//! Dependency construction and serving (plan §2.2, §2.7, §2.11).
//!
//! [`register_components`] declares the lifecycle components (one `sweep:*` per
//! distinct tier, plus one advisory `hints:*` per tier when hints are enabled),
//! and [`run`] builds the Redis tiers and hands off to [`serve`]. [`serve`] takes
//! already-built Redis clients so tests can inject mocks through the exact same
//! path production uses.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use aws_config::BehaviorVersion;
use common_hypercache::{HyperCacheConfig, HyperCacheReader, S3Client};
use common_redis::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};
use common_s3::S3Impl;
use lifecycle::{ComponentOptions, Handle, LivenessHandler, Manager, ReadinessHandler};
use tokio::net::TcpListener;

use crate::auth::Authenticator;
use crate::config::RuntimeConfig;
use crate::domain::CacheKind;
use crate::registry::{ConnectionPermits, TopicRegistry};
use crate::router::{router, AppState};
use crate::trigger::hints::{self, HintConfig};
use crate::trigger::{sweep, Tier};

/// Backstop response timeout on the raw Redis clients. Reads additionally ride
/// HyperCache's own `redis_timeout` (500 ms), so this is a coarse ceiling.
const REDIS_RESPONSE_TIMEOUT: Duration = Duration::from_secs(2);
/// Connection-establishment timeout so startup can't hang on an unreachable tier.
const REDIS_CONNECTION_TIMEOUT: Duration = Duration::from_secs(5);
/// Liveness deadline for the advisory hints components. Generous because an idle
/// pub/sub subscriber legitimately waits; the task reports health on a timer.
const HINTS_LIVENESS_DEADLINE: Duration = Duration::from_secs(60);

/// A tier's role in the deployment: which kinds live on it and whether it uses
/// the dedicated flags client. Both [`register_components`] and [`serve`] derive
/// their per-tier work from the same [`plan_tiers`] output so counts never drift.
struct TierPlan {
    name: &'static str,
    kinds: Vec<CacheKind>,
    uses_flags_client: bool,
}

/// Distinct tiers in use. Two-tier when a dedicated flags URL is set (definitions
/// on shared, remote_eval on flags); otherwise one shared tier hosts both.
fn plan_tiers(config: &RuntimeConfig) -> Vec<TierPlan> {
    if config.flags_redis_url.is_some() {
        vec![
            TierPlan {
                name: "shared",
                kinds: vec![CacheKind::Definitions],
                uses_flags_client: false,
            },
            TierPlan {
                name: "flags",
                kinds: vec![CacheKind::RemoteEval],
                uses_flags_client: true,
            },
        ]
    } else {
        vec![TierPlan {
            name: "shared",
            kinds: vec![CacheKind::Definitions, CacheKind::RemoteEval],
            uses_flags_client: false,
        }]
    }
}

/// Every lifecycle handle the gateway registers, plus the probe handlers.
pub struct GatewayHandles {
    pub http: Handle,
    /// One per distinct tier, aligned with [`plan_tiers`].
    pub sweeps: Vec<Handle>,
    /// One per distinct tier when `hints_enabled`; empty otherwise.
    pub hints: Vec<Handle>,
    pub readiness: ReadinessHandler,
    pub liveness: LivenessHandler,
}

impl GatewayHandles {
    /// Surface an init-time error as a `Failure` on the http component (so the
    /// shutdown trigger reads `failure`, not a misleading `died`) and pre-complete
    /// the unstarted background handles. Call before each early return from
    /// [`run`]/[`serve`] (feature-flags server.rs precedent).
    fn fail_init(&self, reason: impl Into<String>) {
        self.http.signal_failure(reason);
        self.http.work_completed();
        for handle in &self.sweeps {
            handle.work_completed();
        }
        for handle in &self.hints {
            handle.work_completed();
        }
    }
}

/// Register the gateway's lifecycle components. Call once, before
/// `monitor_background()`.
pub fn register_components(manager: &mut Manager, config: &RuntimeConfig) -> GatewayHandles {
    let http = manager.register(
        "http-server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );

    let plans = plan_tiers(config);
    let mut sweeps = Vec::with_capacity(plans.len());
    let mut hints = Vec::new();
    for plan in &plans {
        sweeps.push(manager.register(
            &format!("sweep:{}", plan.name),
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(2)),
        ));
        if config.hints_enabled {
            // Advisory: hint loss is degraded latency, not unhealthy — a stall
            // updates the health gauge but never triggers app shutdown (plan §2.11).
            hints.push(
                manager.register(
                    &format!("hints:{}", plan.name),
                    ComponentOptions::new()
                        .is_advisory(true)
                        .with_liveness_deadline(HINTS_LIVENESS_DEADLINE),
                ),
            );
        }
    }

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    GatewayHandles {
        http,
        sweeps,
        hints,
        readiness,
        liveness,
    }
}

/// Production entry point: build the Redis tiers, then serve. On a client build
/// failure, route through `fail_init` (no panic) so shutdown is coordinated.
pub async fn run(config: RuntimeConfig, listener: TcpListener, handles: GatewayHandles) {
    let (shared, flags) = match build_redis_clients(&config).await {
        Ok(clients) => clients,
        Err(e) => {
            handles.fail_init(format!("redis init failed: {e}"));
            return;
        }
    };
    serve(config, shared, flags, listener, handles).await;
}

/// The trigger readers, one per kind plus the auth-path team reader.
struct ReaderSet {
    definitions: Arc<HyperCacheReader>,
    remote_eval: Arc<HyperCacheReader>,
    team: Arc<HyperCacheReader>,
}

impl ReaderSet {
    fn for_kind(&self, kind: CacheKind) -> Arc<HyperCacheReader> {
        match kind {
            CacheKind::Definitions => self.definitions.clone(),
            CacheKind::RemoteEval => self.remote_eval.clone(),
        }
    }
}

/// Build readers, registry, authenticator, spawn trigger tasks, and serve until
/// graceful shutdown. Public so integration tests can inject mock clients through
/// the same path (`shared == flags` for shared-only mode).
pub async fn serve(
    config: RuntimeConfig,
    shared: Arc<dyn Client + Send + Sync>,
    flags: Arc<dyn Client + Send + Sync>,
    listener: TcpListener,
    handles: GatewayHandles,
) {
    let readers = build_readers(&config, &shared, &flags).await;

    let GatewayHandles {
        http,
        sweeps,
        hints,
        readiness,
        liveness,
    } = handles;

    let config = Arc::new(config);
    let registry = Arc::new(TopicRegistry::new());
    let permits = ConnectionPermits::new(
        config.max_connections,
        config.definitions_max_connections_per_token,
    );
    let authenticator = Arc::new(Authenticator::new(
        readers.team.clone(),
        config.clone(),
        permits,
        http.shutdown_token(),
    ));

    spawn_triggers(&config, &registry, &readers, sweeps, hints);

    let app_state = AppState {
        config: config.clone(),
        registry,
        authenticator,
        shutdown_token: http.shutdown_token(),
    };
    let app = router(
        app_state,
        readiness,
        liveness,
        config.client_ip_source.clone(),
        config.enable_metrics,
    );

    tracing::info!(address = %config.address, "flags-stream-gateway listening");
    let serve_result = axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(http.shutdown_signal())
    .await;
    if let Err(e) = serve_result {
        tracing::error!(error = %e, "axum serve error");
    }
    http.work_completed();
}

/// Build the shared-tier and flags-tier primary clients. The flags tier reuses
/// the shared client when no dedicated URL is set (feature-flags fallback).
async fn build_redis_clients(
    config: &RuntimeConfig,
) -> Result<(Arc<dyn Client + Send + Sync>, Arc<dyn Client + Send + Sync>), CustomRedisError> {
    let shared = build_client(&config.redis_url).await?;
    let flags = match &config.flags_redis_url {
        Some(url) => build_client(url).await?,
        None => shared.clone(),
    };
    Ok((shared, flags))
}

/// A single-endpoint primary client — NOT a ReadWriteClient: every trigger read
/// is pinned to the primary (plan §2.7).
async fn build_client(url: &str) -> Result<Arc<dyn Client + Send + Sync>, CustomRedisError> {
    let client = RedisClient::with_config(
        url.to_string(),
        CompressionConfig::default(),
        RedisValueFormat::default(),
        Some(REDIS_RESPONSE_TIMEOUT),
        Some(REDIS_CONNECTION_TIMEOUT),
    )
    .await?;
    Ok(Arc::new(client))
}

/// Build the two trigger readers plus the token-based team reader, all sharing
/// ONE S3 client so startup performs a single aws-config load.
async fn build_readers(
    config: &RuntimeConfig,
    shared: &Arc<dyn Client + Send + Sync>,
    flags: &Arc<dyn Client + Send + Sync>,
) -> ReaderSet {
    // NOTE: `HyperCacheReader` requires an S3 client, but the gateway NEVER reads
    // S3 — every trigger and auth read is Redis-only (plan §2.7, §2.8). One
    // client is built purely to satisfy the constructors and shared by all three.
    let s3 = build_shared_s3_client(config).await;

    let definitions = HyperCacheReader::new_with_s3_client(
        shared.clone(),
        s3.clone(),
        reader_config(
            config,
            "feature_flags",
            CacheKind::Definitions.hypercache_value(),
            false,
        ),
    );
    let remote_eval = HyperCacheReader::new_with_s3_client(
        flags.clone(),
        s3.clone(),
        reader_config(
            config,
            "feature_flags",
            CacheKind::RemoteEval.hypercache_value(),
            false,
        ),
    );
    // Team metadata is token-keyed and lives on the flags tier (shared fallback),
    // exactly as feature-flags wires it; read Redis-only via the auth path.
    let team = HyperCacheReader::new_with_s3_client(
        flags.clone(),
        s3,
        reader_config(config, "team_metadata", "full_metadata.json", true),
    );

    ReaderSet {
        definitions: Arc::new(definitions),
        remote_eval: Arc::new(remote_eval),
        team: Arc::new(team),
    }
}

fn reader_config(
    config: &RuntimeConfig,
    namespace: &str,
    object_name: &str,
    token_based: bool,
) -> HyperCacheConfig {
    // django_cache_version defaults to "1" (matches Django + the flags service).
    let mut hc_config = HyperCacheConfig::new(
        namespace.to_string(),
        object_name.to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );
    hc_config.token_based = token_based;
    if let Some(endpoint) = &config.object_storage_endpoint {
        hc_config.s3_endpoint = Some(endpoint.clone());
    }
    hc_config
}

/// The single S3 client shared by every reader, mirroring the wiring
/// `HyperCacheReader::new` would do per reader (never used at runtime — see
/// [`build_readers`]).
async fn build_shared_s3_client(config: &RuntimeConfig) -> Arc<dyn S3Client + Send + Sync> {
    let mut loader = aws_config::defaults(BehaviorVersion::latest()).region(
        aws_config::Region::new(config.object_storage_region.clone()),
    );
    if let Some(endpoint) = &config.object_storage_endpoint {
        loader = loader.endpoint_url(endpoint);
    }
    let aws_config = loader.load().await;

    let mut builder = aws_sdk_s3::config::Builder::from(&aws_config);
    if config.object_storage_endpoint.is_some() {
        builder = builder.force_path_style(true);
    }
    Arc::new(S3Impl::new(aws_sdk_s3::Client::from_conf(builder.build())))
}

/// Spawn one sweep task per tier, and one advisory hints task per tier when
/// hints are enabled. Handles are aligned with [`plan_tiers`] order.
fn spawn_triggers(
    config: &Arc<RuntimeConfig>,
    registry: &Arc<TopicRegistry>,
    readers: &ReaderSet,
    sweeps: Vec<Handle>,
    hints: Vec<Handle>,
) {
    let plans = plan_tiers(config);
    let report_interval = HINTS_LIVENESS_DEADLINE / 2;
    let hint_cfg = HintConfig::default();
    let mut hints = hints.into_iter();

    for (plan, sweep_handle) in plans.into_iter().zip(sweeps.into_iter()) {
        let tier = build_tier(config, readers, &plan);
        tokio::spawn(sweep::run_sweep(
            sweep_handle,
            registry.clone(),
            tier.clone(),
            config.sweep_interval,
        ));
        if config.hints_enabled {
            if let Some(hints_handle) = hints.next() {
                tokio::spawn(hints::run_hints(
                    hints_handle,
                    registry.clone(),
                    tier,
                    hint_cfg,
                    report_interval,
                ));
            }
        }
    }
}

fn build_tier(config: &RuntimeConfig, readers: &ReaderSet, plan: &TierPlan) -> Tier {
    let pubsub_url = if plan.uses_flags_client {
        config
            .flags_redis_url
            .clone()
            .unwrap_or_else(|| config.redis_url.clone())
    } else {
        config.redis_url.clone()
    };
    let tier_readers: HashMap<CacheKind, Arc<HyperCacheReader>> = plan
        .kinds
        .iter()
        .map(|&kind| (kind, readers.for_kind(kind)))
        .collect();
    Tier {
        name: plan.name,
        kinds: plan.kinds.clone(),
        pubsub_url,
        readers: tier_readers,
    }
}
