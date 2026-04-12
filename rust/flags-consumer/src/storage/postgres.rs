use sqlx::postgres::PgPool;

/// Storage handle for the dedicated `flags_read_store` PostgreSQL database.
///
/// Step 1: holds a single `PgPool` and exposes a startup connectivity check.
/// Later steps will add version-guarded upsert methods for person rows,
/// distinct_id updates, and heartbeat writes.
pub struct PostgresStorage {
    pub pool: PgPool,
}

impl PostgresStorage {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Connectivity check used at startup to fail fast if the dedicated store
    /// is unreachable or misconfigured.
    pub async fn ping(&self) -> Result<(), sqlx::Error> {
        sqlx::query_scalar::<_, i32>("SELECT 1")
            .fetch_one(&self.pool)
            .await
            .map(|_| ())
    }
}
