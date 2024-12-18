use anyhow::Error;
use health::HealthRegistry;
use sqlx::postgres::PgPoolOptions;

use crate::config::Config;

pub struct AppContext {
    pub config: Config,
    pub db: sqlx::PgPool,
    pub encryption_keys: Vec<String>, // fernet, base64-urlsafe encoded 32-byte long key
    pub health_registry: HealthRegistry,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, Error> {
        let health_registry = HealthRegistry::new("liveness");

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let db = options.connect(&config.database_url).await?;

        Ok(Self {
            config: config.clone(),
            db,
            encryption_keys: config
                .encryption_keys
                .split(",")
                .map(|s| s.to_string())
                .collect(),
            health_registry,
        })
    }

    pub async fn get_token_for_team_id(&self, team_id: i32) -> Result<String, Error> {
        Ok(
            sqlx::query_scalar!("SELECT api_token FROM posthog_team WHERE id = $1", team_id)
                .fetch_one(&self.db)
                .await?,
        )
    }
}
