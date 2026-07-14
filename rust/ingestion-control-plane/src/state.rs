use std::sync::Arc;
use std::time::Duration;

use common_database::PoolConfig;

use crate::config::Config;
use crate::jobs::JobRegistry;
use crate::k8s::PodDiscovery;
use crate::teams::TeamResolver;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub jobs: Arc<JobRegistry>,
    pub teams: Arc<TeamResolver>,
    pub pods: Arc<PodDiscovery>,
    pub http: reqwest::Client,
}

impl AppState {
    pub fn new(config: Config) -> anyhow::Result<Self> {
        let pool = if config.database_url.is_empty() {
            tracing::info!("DATABASE_URL not set; token -> team resolution disabled");
            None
        } else {
            let pool_config = PoolConfig {
                max_connections: config.pg_max_connections,
                pool_name: Some("ingestion-control-plane".to_string()),
                ..PoolConfig::default()
            };
            Some(common_database::get_pool_with_config(
                &config.database_url,
                pool_config,
            )?)
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
            config: Arc::new(config),
        })
    }
}
