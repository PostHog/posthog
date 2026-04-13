use sqlx::PgPool;

/// Drop and recreate the flags_person_lookup table with GIN index.
///
/// DDL is copied from rust/flags_read_store_migrations/20260411000001_create_flags_person_lookup.sql.
/// The heartbeat table is omitted (not relevant to the benchmark).
pub async fn create_schema(pool: &PgPool) -> anyhow::Result<()> {
    tracing::info!("dropping existing schema (if any)");
    sqlx::query("DROP TABLE IF EXISTS flags_person_lookup CASCADE")
        .execute(pool)
        .await?;

    tracing::info!("creating btree_gin extension");
    sqlx::query("CREATE EXTENSION IF NOT EXISTS btree_gin")
        .execute(pool)
        .await?;

    tracing::info!("creating flags_person_lookup table (hash-partitioned, 64 partitions)");
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS flags_person_lookup (
            team_id              INTEGER NOT NULL,
            person_uuid          UUID NOT NULL,
            distinct_ids         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            properties           JSONB NOT NULL DEFAULT '{}'::jsonb,
            person_version       BIGINT NOT NULL DEFAULT 0,
            distinct_id_version  BIGINT NOT NULL DEFAULT 0,
            PRIMARY KEY (team_id, person_uuid)
        ) PARTITION BY HASH (team_id)
        "#,
    )
    .execute(pool)
    .await?;

    // Create 64 hash partitions matching posthog_person's partition count.
    for i in 0..64 {
        let ddl = format!(
            "CREATE TABLE IF NOT EXISTS flags_person_lookup_p{i} \
             PARTITION OF flags_person_lookup \
             FOR VALUES WITH (MODULUS 64, REMAINDER {i})"
        );
        sqlx::query(&ddl).execute(pool).await?;
    }

    tracing::info!("creating GIN index on (team_id, distinct_ids)");
    sqlx::query(
        "CREATE INDEX IF NOT EXISTS idx_flags_person_gin \
         ON flags_person_lookup USING GIN (team_id, distinct_ids)",
    )
    .execute(pool)
    .await?;

    tracing::info!("schema created");
    Ok(())
}

/// Check whether the flags_person_lookup table exists.
pub async fn table_exists(pool: &PgPool) -> anyhow::Result<bool> {
    let row: (bool,) = sqlx::query_as(
        "SELECT EXISTS (
            SELECT 1 FROM pg_class WHERE relname = 'flags_person_lookup' AND relkind = 'p'
        )",
    )
    .fetch_one(pool)
    .await?;
    Ok(row.0)
}
