use crate::api::errors::FlagError;
use crate::config::Config;
use common_database::{get_pool_with_config, PoolConfig};
use rand::Rng;
use sqlx::PgPool;
use std::sync::Arc;
use std::time::Duration;
use tracing::info;

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

        // Create base pool config (used for both readers and writers)
        let base_pool_config = PoolConfig {
            max_connections: config.max_pg_connections,
            acquire_timeout: Duration::from_secs(config.acquire_timeout_secs),
            idle_timeout: if config.idle_timeout_secs > 0 {
                Some(Duration::from_secs(config.idle_timeout_secs))
            } else {
                None
            },
            max_lifetime: if config.max_lifetime_secs > 0 {
                let jitter = if config.max_lifetime_jitter_secs > 0 {
                    rand::thread_rng().gen_range(0..config.max_lifetime_jitter_secs)
                } else {
                    0
                };
                Some(Duration::from_secs(config.max_lifetime_secs + jitter))
            } else {
                None
            },
            test_before_acquire: *config.test_before_acquire,
            statement_timeout_ms: None, // Set per pool type below
        };

        // Non-persons reader pool config (may allow longer queries for analytics)
        let non_persons_reader_pool_config = PoolConfig {
            statement_timeout_ms: if config.non_persons_reader_statement_timeout_ms > 0 {
                Some(config.non_persons_reader_statement_timeout_ms)
            } else {
                None
            },
            ..base_pool_config.clone()
        };
        info!(
            pool = "non_persons_reader",
            statement_timeout_ms = ?config.non_persons_reader_statement_timeout_ms,
            "Creating non-persons reader pool"
        );

        // Persons reader pool config (may allow longer queries for analytics)
        let persons_reader_pool_config = PoolConfig {
            statement_timeout_ms: if config.persons_reader_statement_timeout_ms > 0 {
                Some(config.persons_reader_statement_timeout_ms)
            } else {
                None
            },
            ..base_pool_config.clone()
        };
        info!(
            pool = "persons_reader",
            statement_timeout_ms = ?config.persons_reader_statement_timeout_ms,
            "Creating persons reader pool config"
        );

        // Writer pool config (should be fast transactional operations)
        let writer_pool_config = PoolConfig {
            statement_timeout_ms: if config.writer_statement_timeout_ms > 0 {
                Some(config.writer_statement_timeout_ms)
            } else {
                None
            },
            ..base_pool_config
        };
        info!(
            pool = "writer",
            statement_timeout_ms = ?config.writer_statement_timeout_ms,
            "Creating writer pool"
        );

        let non_persons_reader = Arc::new(
            get_pool_with_config(&config.read_database_url, non_persons_reader_pool_config)
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(
                        e,
                        Some("Failed to create non-persons reader pool".to_string()),
                    )
                })?,
        );

        let non_persons_writer = Arc::new(
            get_pool_with_config(&config.write_database_url, writer_pool_config.clone())
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
                get_pool_with_config(
                    &config.get_persons_read_database_url(),
                    persons_reader_pool_config,
                )
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
                get_pool_with_config(&config.get_persons_write_database_url(), writer_pool_config)
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

        // Log pool configuration at startup
        info!(
            max_connections = config.max_pg_connections,
            acquire_timeout_secs = config.acquire_timeout_secs,
            idle_timeout_secs = config.idle_timeout_secs,
            max_lifetime_secs = config.max_lifetime_secs,
            test_before_acquire = config.test_before_acquire.0,
            non_persons_reader_statement_timeout_ms =
                config.non_persons_reader_statement_timeout_ms,
            persons_reader_statement_timeout_ms = config.persons_reader_statement_timeout_ms,
            writer_statement_timeout_ms = config.writer_statement_timeout_ms,
            persons_routing_enabled = config.is_persons_db_routing_enabled(),
            "Database pool configuration"
        );

        // Log whether pools are actually separate or aliased
        let pools_are_separate = config.is_persons_db_routing_enabled();
        if pools_are_separate {
            info!("Using separate persons database pools");
        } else {
            info!("Persons pools are aliased to non-persons pools (persons DB routing disabled)");
        }

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
        let config = Config {
            persons_read_database_url: "".to_string(),
            persons_write_database_url: "".to_string(),
            ..Config::default_test_config()
        };

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
        let config = Config::default_test_config();

        assert!(config.is_persons_db_routing_enabled());
        assert_eq!(
            config.get_persons_read_database_url(),
            "postgres://posthog:posthog@localhost:5432/posthog_persons"
        );
        assert_eq!(
            config.get_persons_write_database_url(),
            "postgres://posthog:posthog@localhost:5432/posthog_persons"
        );
    }
}
