use crate::api::errors::FlagError;
use crate::config::Config;
use common_database::{get_pool_with_config, PoolConfig};
use sqlx::PgPool;
use std::sync::Arc;
use std::time::Duration;

/// Direct database pool access for different operation types
#[derive(Clone)]
pub struct DatabasePools {
    pub non_persons_reader: Arc<PgPool>,
    pub non_persons_writer: Arc<PgPool>,
    pub persons_reader: Arc<PgPool>,
    pub persons_writer: Arc<PgPool>,
}

impl DatabasePools {
    pub async fn from_config(config: &Config) -> Result<Self, FlagError> {
        // Validate acquire_timeout_secs - must be at least 1 second
        if config.acquire_timeout_secs == 0 {
            return Err(FlagError::Internal(
                "ACQUIRE_TIMEOUT_SECS must be at least 1 second".to_string(),
            ));
        }

        let pool_config = PoolConfig {
            max_connections: config.max_pg_connections,
            acquire_timeout: Duration::from_secs(config.acquire_timeout_secs),
            idle_timeout: if config.idle_timeout_secs > 0 {
                Some(Duration::from_secs(config.idle_timeout_secs))
            } else {
                None
            },
            max_lifetime: if config.max_lifetime_secs > 0 {
                Some(Duration::from_secs(config.max_lifetime_secs))
            } else {
                None
            },
            test_before_acquire: *config.test_before_acquire,
        };

        let non_persons_reader = Arc::new(
            get_pool_with_config(&config.read_database_url, pool_config.clone())
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(
                        e,
                        Some("Failed to create non-persons reader pool".to_string()),
                    )
                })?,
        );

        let non_persons_writer = Arc::new(
            get_pool_with_config(&config.write_database_url, pool_config.clone())
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(
                        e,
                        Some("Failed to create non-persons writer pool".to_string()),
                    )
                })?,
        );

        // Create persons pools if configured, otherwise reuse the non-persons pools
        let persons_reader = if config.is_persons_db_routing_enabled() {
            Arc::new(
                get_pool_with_config(&config.get_persons_read_database_url(), pool_config.clone())
                    .await
                    .map_err(|e| {
                        FlagError::DatabaseError(
                            e,
                            Some("Failed to create persons reader pool".to_string()),
                        )
                    })?,
            )
        } else {
            non_persons_reader.clone()
        };

        let persons_writer = if config.is_persons_db_routing_enabled() {
            Arc::new(
                get_pool_with_config(
                    &config.get_persons_write_database_url(),
                    pool_config.clone(),
                )
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(
                        e,
                        Some("Failed to create persons writer pool".to_string()),
                    )
                })?,
            )
        } else {
            non_persons_writer.clone()
        };

        Ok(DatabasePools {
            non_persons_reader,
            non_persons_writer,
            persons_reader,
            persons_writer,
        })
    }
}

#[cfg(test)]
mod tests {
    use crate::config::Config;

    #[tokio::test]
    async fn test_database_routing_disabled() {
        let config = Config::default_test_config();

        assert!(!config.is_persons_db_routing_enabled());
        assert_eq!(
            config.get_persons_read_database_url(),
            config.read_database_url
        );
        assert_eq!(
            config.get_persons_write_database_url(),
            config.write_database_url
        );
    }

    #[tokio::test]
    async fn test_database_routing_enabled() {
        let config = Config {
            persons_read_database_url: "postgres://user:pass@persons-reader:5432/db".to_string(),
            persons_write_database_url: "postgres://user:pass@persons-writer:5432/db".to_string(),
            ..Config::default_test_config()
        };

        assert!(config.is_persons_db_routing_enabled());
        assert_eq!(
            config.get_persons_read_database_url(),
            "postgres://user:pass@persons-reader:5432/db"
        );
        assert_eq!(
            config.get_persons_write_database_url(),
            "postgres://user:pass@persons-writer:5432/db"
        );
    }
}
