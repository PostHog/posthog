use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use anyhow::Error;
use health::HealthRegistry;
use sqlx::postgres::PgPoolOptions;

use crate::config::Config;

pub struct AppContext {
    pub config: Config,
    pub db: sqlx::PgPool,
    pub encryption_keys: Vec<String>, // fernet, base64-urlsafe encoded 32-byte long key
    pub health_registry: HealthRegistry,
    pub running: AtomicBool, // Set to false on SIGTERM, etc.
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, Error> {
        let health_registry = HealthRegistry::new("liveness");

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let db = options.connect(&config.database_url).await?;

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
