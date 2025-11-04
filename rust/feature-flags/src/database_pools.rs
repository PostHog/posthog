use crate::api::errors::FlagError;
use crate::config::Config;
use common_database::{get_pool_with_config, PoolConfig};
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
    /// Default value for max_connections when config value is invalid (matches PoolConfig::default)
    const DEFAULT_MAX_CONNECTIONS: u32 = 10;

    /// Helper to build a pool configuration with specific min_connections and statement_timeout
    fn build_pool_config(
        base: &PoolConfig,
        min_connections: u32,
        statement_timeout_ms: u64,
    ) -> PoolConfig {
        PoolConfig {
            min_connections,
            statement_timeout_ms: if statement_timeout_ms > 0 {
                Some(statement_timeout_ms)
            } else {
                None
            },
            ..base.clone()
        }
    }

    pub async fn from_config(config: &Config) -> Result<Self, FlagError> {
        // Validate acquire_timeout_secs - must be at least 1 second
        if config.acquire_timeout_secs == 0 {
            return Err(FlagError::Internal(
                "ACQUIRE_TIMEOUT_SECS must be at least 1 second".to_string(),
            ));
        }

        // Validate and fix max_connections if it's 0
        let max_pg_connections = if config.max_pg_connections == 0 {
            tracing::warn!(
                configured = config.max_pg_connections,
                default = Self::DEFAULT_MAX_CONNECTIONS,
                "MAX_PG_CONNECTIONS is 0, using default"
            );
            Self::DEFAULT_MAX_CONNECTIONS
        } else {
            config.max_pg_connections
        };

        // Clamp min_connections to max_connections for each pool
        // This prevents misconfiguration while allowing the service to start
        let min_non_persons_reader_connections = config
            .min_non_persons_reader_connections
            .min(max_pg_connections);
        let min_non_persons_writer_connections = config
            .min_non_persons_writer_connections
            .min(max_pg_connections);
        let min_persons_reader_connections = config
            .min_persons_reader_connections
            .min(max_pg_connections);
        let min_persons_writer_connections = config
            .min_persons_writer_connections
            .min(max_pg_connections);

        // Log warnings if we had to clamp any values
        if config.min_non_persons_reader_connections > max_pg_connections {
            tracing::warn!(
                configured = config.min_non_persons_reader_connections,
                clamped_to = min_non_persons_reader_connections,
                max_connections = max_pg_connections,
                "MIN_NON_PERSONS_READER_CONNECTIONS exceeds MAX_PG_CONNECTIONS, clamping to max"
            );
        }
        if config.min_non_persons_writer_connections > max_pg_connections {
            tracing::warn!(
                configured = config.min_non_persons_writer_connections,
                clamped_to = min_non_persons_writer_connections,
                max_connections = max_pg_connections,
                "MIN_NON_PERSONS_WRITER_CONNECTIONS exceeds MAX_PG_CONNECTIONS, clamping to max"
            );
        }
        if config.min_persons_reader_connections > max_pg_connections {
            tracing::warn!(
                configured = config.min_persons_reader_connections,
                clamped_to = min_persons_reader_connections,
                max_connections = max_pg_connections,
                "MIN_PERSONS_READER_CONNECTIONS exceeds MAX_PG_CONNECTIONS, clamping to max"
            );
        }
        if config.min_persons_writer_connections > max_pg_connections {
            tracing::warn!(
                configured = config.min_persons_writer_connections,
                clamped_to = min_persons_writer_connections,
                max_connections = max_pg_connections,
                "MIN_PERSONS_WRITER_CONNECTIONS exceeds MAX_PG_CONNECTIONS, clamping to max"
            );
        }

        // Create base pool config (used for both readers and writers)
        let base_pool_config = PoolConfig {
            min_connections: 0, // Will be overridden per pool
            max_connections: max_pg_connections,
            acquire_timeout: Duration::from_secs(config.acquire_timeout_secs),
            idle_timeout: if config.idle_timeout_secs > 0 {
                Some(Duration::from_secs(config.idle_timeout_secs))
            } else {
                None
            },
            test_before_acquire: *config.test_before_acquire,
            statement_timeout_ms: None, // Set per pool type below
        };

        // Non-persons reader pool config (may allow longer queries for analytics)
        let non_persons_reader_pool_config = Self::build_pool_config(
            &base_pool_config,
            min_non_persons_reader_connections,
            config.non_persons_reader_statement_timeout_ms,
        );
        info!(
            pool = "non_persons_reader",
            statement_timeout_ms = ?config.non_persons_reader_statement_timeout_ms,
            "Creating non-persons reader pool"
        );

        // Persons reader pool config (may allow longer queries for analytics)
        let persons_reader_pool_config = Self::build_pool_config(
            &base_pool_config,
            min_persons_reader_connections,
            config.persons_reader_statement_timeout_ms,
        );
        info!(
            pool = "persons_reader",
            statement_timeout_ms = ?config.persons_reader_statement_timeout_ms,
            "Creating persons reader pool config"
        );

        // Non-persons writer pool config (should be fast transactional operations)
        let non_persons_writer_pool_config = Self::build_pool_config(
            &base_pool_config,
            min_non_persons_writer_connections,
            config.writer_statement_timeout_ms,
        );

        // Persons writer pool config (should be fast transactional operations)
        let persons_writer_pool_config = Self::build_pool_config(
            &base_pool_config,
            min_persons_writer_connections,
            config.writer_statement_timeout_ms,
        );
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
            get_pool_with_config(&config.write_database_url, non_persons_writer_pool_config)
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
                get_pool_with_config(
                    &config.get_persons_write_database_url(),
                    persons_writer_pool_config,
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

        // Log pool configuration at startup (using validated/clamped values)
        info!(
            max_connections = max_pg_connections,
            min_non_persons_reader_connections = min_non_persons_reader_connections,
            min_non_persons_writer_connections = min_non_persons_writer_connections,
            min_persons_reader_connections = min_persons_reader_connections,
            min_persons_writer_connections = min_persons_writer_connections,
            acquire_timeout_secs = config.acquire_timeout_secs,
            idle_timeout_secs = config.idle_timeout_secs,
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

    #[tokio::test]
    async fn test_min_connections_clamped_to_max() {
        // Create a config with min_connections > max_connections for all pools
        let config = Config {
            max_pg_connections: 5,
            min_non_persons_reader_connections: 10,
            min_non_persons_writer_connections: 15,
            min_persons_reader_connections: 20,
            min_persons_writer_connections: 25,
            ..Config::default_test_config()
        };

        // Create pools - this should clamp all min_connections to max_connections
        let pools = super::DatabasePools::from_config(&config).await.unwrap();

        // Verify that the pools were created successfully (no panic/error)
        // Pool size() returns the current number of connections, which starts at min_connections
        // Since we clamped to max_pg_connections (5), all pools should have 5 connections
        assert_eq!(pools.non_persons_reader.size(), 5);
        assert_eq!(pools.non_persons_writer.size(), 5);
        assert_eq!(pools.persons_reader.size(), 5);
        assert_eq!(pools.persons_writer.size(), 5);
    }

    #[tokio::test]
    async fn test_min_connections_within_max() {
        // Create a config with min_connections < max_connections
        let config = Config {
            max_pg_connections: 10,
            min_non_persons_reader_connections: 2,
            min_non_persons_writer_connections: 3,
            min_persons_reader_connections: 4,
            min_persons_writer_connections: 5,
            ..Config::default_test_config()
        };

        // Create pools - should work without warnings
        let pools = super::DatabasePools::from_config(&config).await.unwrap();

        // Pool size() returns the current number of connections, which starts at min_connections
        assert_eq!(pools.non_persons_reader.size(), 2);
        assert_eq!(pools.non_persons_writer.size(), 3);
        assert_eq!(pools.persons_reader.size(), 4);
        assert_eq!(pools.persons_writer.size(), 5);
    }

    #[tokio::test]
    async fn test_zero_max_connections_uses_default() {
        // Create a config with max_pg_connections = 0
        let config = Config {
            max_pg_connections: 0,
            min_non_persons_reader_connections: 5,
            min_non_persons_writer_connections: 5,
            min_persons_reader_connections: 5,
            min_persons_writer_connections: 5,
            ..Config::default_test_config()
        };

        // Create pools - should use default max_connections (10) and clamp min to that
        let pools = super::DatabasePools::from_config(&config).await.unwrap();

        // All pools should have 5 connections (min clamped to default max of 10)
        assert_eq!(pools.non_persons_reader.size(), 5);
        assert_eq!(pools.non_persons_writer.size(), 5);
        assert_eq!(pools.persons_reader.size(), 5);
        assert_eq!(pools.persons_writer.size(), 5);
    }

    #[tokio::test]
    async fn test_zero_max_with_higher_min_clamps_to_default() {
        // Create a config with max_pg_connections = 0 and min > default max (10)
        let config = Config {
            max_pg_connections: 0,
            min_non_persons_reader_connections: 15,
            min_non_persons_writer_connections: 20,
            min_persons_reader_connections: 25,
            min_persons_writer_connections: 30,
            ..Config::default_test_config()
        };

        // Create pools - should use default max_connections (10) and clamp all min to 10
        let pools = super::DatabasePools::from_config(&config).await.unwrap();

        // All pools should have 10 connections (default max)
        assert_eq!(pools.non_persons_reader.size(), 10);
        assert_eq!(pools.non_persons_writer.size(), 10);
        assert_eq!(pools.persons_reader.size(), 10);
        assert_eq!(pools.persons_writer.size(), 10);
    }
}
