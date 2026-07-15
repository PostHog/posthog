use std::sync::Arc;
use std::time::Duration;

use common_database::PoolConfig;

use crate::cache::TtlCache;
use crate::config::Config;
use crate::jobs::JobRegistry;
use crate::k8s::PodDiscovery;
use crate::kafka::lag::{ConsumerTarget, LagOverview};
use crate::teams::TeamResolver;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub jobs: Arc<JobRegistry>,
    pub teams: Arc<TeamResolver>,
    pub pods: Arc<PodDiscovery>,
    pub http: reqwest::Client,
    /// Discovered group/topic targets; topology changes rarely.
    pub discovery: Arc<TtlCache<Vec<ConsumerTarget>>>,
    /// Overview scan results; short TTL + single-flight bounds broker load.
    pub overview: Arc<TtlCache<LagOverview>>,
}

impl AppState {
    pub fn new(config: Config) -> anyhow::Result<Self> {
        // Treat set-but-empty like unset so a templated empty env var can't
        // half-enable resolution with an unusable URL.
        let pool = match config.database_url.as_deref().filter(|url| !url.is_empty()) {
            None => {
                tracing::info!("DATABASE_URL not set; token -> team resolution disabled");
                None
            }
            Some(database_url) => {
                let pool_config = PoolConfig {
                    max_connections: config.pg_max_connections,
                    pool_name: Some("ingestion-control-plane".to_string()),
                    ..PoolConfig::default()
                };
                Some(common_database::get_pool_with_config(
                    database_url,
                    pool_config,
                )?)
            }
        };

        // No overall request timeout: the debug proxy pipes long-lived SSE
        // streams. Connect timeout still bounds unreachable pods.
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(2))
            .build()
            .expect("reqwest client construction cannot fail with static config");

        Ok(Self {
            jobs: Arc::new(JobRegistry::new(config.analysis_max_concurrent_jobs)),
            teams: Arc::new(TeamResolver::new(pool)),
            pods: Arc::new(PodDiscovery::from_config(&config)?),
            http,
            discovery: Arc::new(TtlCache::new(Duration::from_secs(
                config.discovery_cache_ttl_secs,
            ))),
            overview: Arc::new(TtlCache::new(Duration::from_secs(
                config.overview_cache_ttl_secs,
            ))),
            config: Arc::new(config),
        })
    }
}
