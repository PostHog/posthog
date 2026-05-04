use sqlx::PgPool;

pub const PARTITION_COUNT: usize = 64;

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
            deleted_at           TIMESTAMPTZ,
            PRIMARY KEY (team_id, person_uuid)
        ) PARTITION BY HASH (team_id)
        "#,
    )
    .execute(pool)
    .await?;

    for i in 0..PARTITION_COUNT {
        let ddl = format!(
            "CREATE TABLE IF NOT EXISTS flags_person_lookup_p{i} \
             PARTITION OF flags_person_lookup \
             FOR VALUES WITH (MODULUS {PARTITION_COUNT}, REMAINDER {i})"
        );
        sqlx::query(&ddl).execute(pool).await?;
    }

    tracing::info!("creating GIN index on (team_id, distinct_ids) WHERE deleted_at IS NULL");
    sqlx::query(
        "CREATE INDEX IF NOT EXISTS idx_flags_person_gin \
         ON flags_person_lookup USING GIN (team_id, distinct_ids) \
         WHERE deleted_at IS NULL",
    )
    .execute(pool)
    .await?;

    tracing::info!("schema created");
    Ok(())
}

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
