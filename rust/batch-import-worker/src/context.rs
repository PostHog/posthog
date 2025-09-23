use std::sync::Arc;
use std::{sync::atomic::AtomicBool, time::Duration};

use anyhow::Error;
use health::{HealthHandle, HealthRegistry};
use sqlx::postgres::PgPoolOptions;
use tracing::info;

use crate::cache::{GroupCache, IdentifyCache, MemoryGroupCache, MemoryIdentifyCache};
use crate::config::Config;

pub struct AppContext {
    pub config: Config,
    pub db: sqlx::PgPool,
    pub encryption_keys: Vec<String>, // fernet, base64-urlsafe encoded 32-byte long key
    pub health_registry: HealthRegistry,
    pub running: AtomicBool, // Set to false on SIGTERM, etc.
    pub worker_liveness: Arc<HealthHandle>,
    pub identify_cache: Arc<dyn IdentifyCache>,
    pub group_cache: Arc<dyn GroupCache>,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, Error> {
        let health_registry = HealthRegistry::new("liveness");

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let db = options.connect(&config.database_url).await?;

        let liveness = health_registry
            .register("main-loop".to_string(), Duration::from_secs(30))
            .await;

        let liveness = Arc::new(liveness);

        // Initialize the identify cache - memory-only implementation
        info!(
            "Using in-memory cache for identify events (capacity: {}, TTL: {}s)",
            config.identify_memory_cache_capacity, config.identify_memory_cache_ttl_seconds
        );
        let identify_cache: Arc<dyn IdentifyCache> = Arc::new(MemoryIdentifyCache::new(
            config.identify_memory_cache_capacity,
            Duration::from_secs(config.identify_memory_cache_ttl_seconds),
        ));

        // Initialize the group cache - memory-only implementation
        info!(
            "Using in-memory cache for group events (capacity: {}, TTL: {}s)",
            config.group_memory_cache_capacity, config.group_memory_cache_ttl_seconds
        );
        let group_cache: Arc<dyn GroupCache> = Arc::new(MemoryGroupCache::new(
            config.group_memory_cache_capacity,
            Duration::from_secs(config.group_memory_cache_ttl_seconds),
        ));

        let ctx = Self {
            config: config.clone(),
            db,
            encryption_keys: config
                .encryption_keys
                .split(",")
                .map(|s| s.to_string())
                .collect(),
            health_registry,
            running: AtomicBool::new(true),
            worker_liveness: liveness,
            identify_cache,
            group_cache,
        };

        Ok(ctx)
    }

    pub async fn get_token_for_team_id(&self, team_id: i32) -> Result<String, Error> {
        Ok(
            sqlx::query_scalar!("SELECT api_token FROM posthog_team WHERE id = $1", team_id)
                .fetch_one(&self.db)
                .await?,
        )
    }

    pub fn is_running(&self) -> bool {
        self.running.load(std::sync::atomic::Ordering::SeqCst)
    }

    pub fn stop(&self) {
        self.running
            .store(false, std::sync::atomic::Ordering::SeqCst);
    }

    // Listen for all signals that indicate we should shut down, and if we receive one, stop the app.
    // Handled signals are SIGTERM and SIGINT
    #[cfg(unix)]
    pub fn spawn_shutdown_listener(self: Arc<Self>) {
        use tokio::signal::unix::SignalKind;
        use tracing::info;

        tokio::spawn(async move {
            let mut term = tokio::signal::unix::signal(SignalKind::terminate())
                .expect("failed to register SIGTERM handler");
            let mut int = tokio::signal::unix::signal(SignalKind::interrupt())
                .expect("failed to register SIGINT handler");

            let recvd = tokio::select! {
                _ = term.recv() => "SIGTERM",
                _ = int.recv() => "SIGINT",
            };

            info!(signal = recvd, "Received signal, shutting down");
            self.stop();
        });
    }

    #[cfg(windows)]
    pub fn spawn_shutdown_listener(self: Arc<Self>) {
        unimplemented!() // We simply do not support running this code in a windows environment
    }
}
