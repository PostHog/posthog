use crate::api::errors::FlagError;
use crate::config::Config;
use common_database::get_pool;
use sqlx::PgPool;
use std::sync::Arc;

/// Direct database pool access for different operation types
#[derive(Clone)]
pub struct DatabasePools {
    pub non_persons_reader: Arc<PgPool>,
    pub non_persons_writer: Arc<PgPool>,
    pub persons_reader: Arc<PgPool>,
    pub persons_writer: Arc<PgPool>,
}

impl DatabasePools {
    /// Create database pools based on configuration
    pub async fn from_config(config: &Config) -> Result<Self, FlagError> {
        // Create flag matching pools (default behavior)
        let non_persons_reader = Arc::new(
            get_pool(&config.read_database_url, config.max_pg_connections)
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(format!(
                        "Failed to create flag matching reader pool: {}",
                        e
                    ))
                })?,
        );

        let non_persons_writer = Arc::new(
            get_pool(&config.write_database_url, config.max_pg_connections)
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(format!(
                        "Failed to create flag matching writer pool: {}",
                        e
                    ))
                })?,
        );

        // Create persons pools (may be same as flag matching if routing not enabled)
        let persons_reader = if config.is_persons_db_routing_enabled() {
            Arc::new(
                get_pool(
                    config.get_persons_read_database_url(),
                    config.max_pg_connections,
                )
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(format!("Failed to create persons reader pool: {}", e))
                })?,
            )
        } else {
            non_persons_reader.clone()
        };

        let persons_writer = if config.is_persons_db_routing_enabled() {
            Arc::new(
                get_pool(
                    config.get_persons_write_database_url(),
                    config.max_pg_connections,
                )
                .await
                .map_err(|e| {
                    FlagError::DatabaseError(format!("Failed to create persons writer pool: {}", e))
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
        let config = Config::default();

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
            read_database_url: "postgres://test:test@localhost:5432/test".to_string(),
            write_database_url: "postgres://test:test@localhost:5432/test".to_string(),
            persons_read_database_url: "postgres://test:test@localhost:5432/persons_read"
                .to_string(),
            persons_write_database_url: "postgres://test:test@localhost:5432/persons_write"
                .to_string(),
            max_pg_connections: 1,
            ..Default::default()
        };

        assert!(config.is_persons_db_routing_enabled());
        assert_eq!(
            config.get_persons_read_database_url(),
            "postgres://test:test@localhost:5432/persons_read"
        );
        assert_eq!(
            config.get_persons_write_database_url(),
            "postgres://test:test@localhost:5432/persons_write"
        );
    }

    #[tokio::test]
    async fn test_fallback_to_writer() {
        let config = Config {
            read_database_url: "postgres://test:test@localhost:5432/test".to_string(),
            write_database_url: "postgres://test:test@localhost:5432/test".to_string(),
            persons_read_database_url: "".to_string(),
            persons_write_database_url: "postgres://test:test@localhost:5432/persons_write"
                .to_string(),
            max_pg_connections: 1,
            ..Default::default()
        };

        assert!(config.is_persons_db_routing_enabled());
        // Should fall back to writer URL when reader is not set
        assert_eq!(
            config.get_persons_read_database_url(),
            "postgres://test:test@localhost:5432/persons_write"
        );
        assert_eq!(
            config.get_persons_write_database_url(),
            "postgres://test:test@localhost:5432/persons_write"
        );
    }
}
