mod cohort;
mod distinct_id;
mod feature_flag;
mod group;
mod person;

use sqlx::postgres::PgPool;

use super::error::StorageError;

pub(crate) const DB_QUERY_DURATION: &str = "personhog_replica_db_query_duration_ms";

/// Postgres implementation of storage traits
pub struct PostgresStorage {
    pub(crate) pool: PgPool,
}

impl PostgresStorage {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

impl From<sqlx::Error> for StorageError {
    fn from(err: sqlx::Error) -> Self {
        match &err {
            sqlx::Error::PoolTimedOut | sqlx::Error::PoolClosed => StorageError::PoolExhausted,

            sqlx::Error::Io(_) | sqlx::Error::Tls(_) => StorageError::Connection(err.to_string()),

            _ => StorageError::Query(err.to_string()),
        }
    }
}
