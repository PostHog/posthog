use std::sync::Arc;

use common_database::{get_pool, Client};
use once_cell::sync::Lazy;

use crate::config::Config;

pub static DEFAULT_TEST_CONFIG: Lazy<Config> = Lazy::new(Config::default);

pub async fn setup_pg_client(config: Option<&Config>) -> Arc<dyn Client + Send + Sync> {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);
    Arc::new(
        get_pool(&config.read_database_url, config.max_pg_connections)
            .await
            .expect("Failed to create Postgres client"),
    )
}
