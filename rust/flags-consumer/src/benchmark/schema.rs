use std::collections::BTreeMap;

use anyhow::Context;
use serde::Serialize;
use sqlx::PgPool;

const PERSON_TABLE: &str = "flags_person";
const DISTINCT_ID_MAP_TABLE: &str = "flags_distinct_id_map";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SchemaSource {
    Created,
    Existing,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PartitionStrategy {
    Hash,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TableMetadata {
    pub name: String,
    pub partition_strategy: PartitionStrategy,
    pub partition_count: usize,
    pub partition_fillfactors: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SchemaMetadata {
    pub source: SchemaSource,
    pub requested_schema_arguments_applied: bool,
    pub person: TableMetadata,
    pub distinct_id_map: TableMetadata,
}

pub async fn create_schema(
    pool: &PgPool,
    partition_count: usize,
    person_fillfactor: u8,
    map_fillfactor: u8,
) -> anyhow::Result<()> {
    anyhow::ensure!(
        partition_count > 0,
        "--partitions must be greater than zero"
    );
    anyhow::ensure!(
        (10..=100).contains(&person_fillfactor),
        "--person-fillfactor must be between 10 and 100"
    );
    anyhow::ensure!(
        (10..=100).contains(&map_fillfactor),
        "--map-fillfactor must be between 10 and 100"
    );

    tracing::info!("dropping existing schema (if any)");
    sqlx::query("DROP TABLE IF EXISTS flags_person_lookup CASCADE")
        .execute(pool)
        .await?;
    sqlx::query("DROP TABLE IF EXISTS flags_distinct_id_map CASCADE")
        .execute(pool)
        .await?;
    sqlx::query("DROP TABLE IF EXISTS flags_person CASCADE")
        .execute(pool)
        .await?;

    tracing::info!(
        partition_count,
        "creating hash-partitioned read-store tables"
    );
    sqlx::query(
        r#"
        CREATE TABLE flags_person (
            team_id        INTEGER NOT NULL,
            person_uuid    UUID NOT NULL,
            properties     JSONB NOT NULL DEFAULT '{}'::JSONB,
            person_version BIGINT NOT NULL DEFAULT 0,
            deleted_at     TIMESTAMPTZ,
            PRIMARY KEY (team_id, person_uuid)
        ) PARTITION BY HASH (team_id)
        "#,
    )
    .execute(pool)
    .await?;

    sqlx::query(
        r#"
        CREATE TABLE flags_distinct_id_map (
            team_id     INTEGER NOT NULL,
            distinct_id TEXT NOT NULL,
            person_uuid UUID NOT NULL,
            version     BIGINT NOT NULL DEFAULT 0,
            deleted_at  TIMESTAMPTZ,
            PRIMARY KEY (team_id, distinct_id)
        ) PARTITION BY HASH (team_id)
        "#,
    )
    .execute(pool)
    .await?;

    for i in 0..partition_count {
        let person_ddl = format!(
            "CREATE TABLE flags_person_p{i} \
             PARTITION OF flags_person \
             FOR VALUES WITH (MODULUS {partition_count}, REMAINDER {i}) \
             WITH (fillfactor = {person_fillfactor})"
        );
        sqlx::query(&person_ddl).execute(pool).await?;

        let map_ddl = format!(
            "CREATE TABLE flags_distinct_id_map_p{i} \
             PARTITION OF flags_distinct_id_map \
             FOR VALUES WITH (MODULUS {partition_count}, REMAINDER {i}) \
             WITH (fillfactor = {map_fillfactor})"
        );
        sqlx::query(&map_ddl).execute(pool).await?;
    }

    tracing::info!("schema created");
    Ok(())
}

pub async fn table_exists(pool: &PgPool) -> anyhow::Result<bool> {
    let row: (bool,) = sqlx::query_as(
        "SELECT to_regclass('flags_person') IS NOT NULL \
             AND to_regclass('flags_distinct_id_map') IS NOT NULL",
    )
    .fetch_one(pool)
    .await?;
    Ok(row.0)
}

pub async fn inspect_schema(pool: &PgPool, source: SchemaSource) -> anyhow::Result<SchemaMetadata> {
    let rows = sqlx::query_as::<_, (String, String, String, i32)>(
        r#"
        SELECT
            parent.relname,
            partitioned.partstrat::text,
            child.relname,
            COALESCE(
                (
                    SELECT split_part(option, '=', 2)::INTEGER
                    FROM unnest(COALESCE(child.reloptions, ARRAY[]::TEXT[])) AS option
                    WHERE option LIKE 'fillfactor=%'
                ),
                100
            ) AS fillfactor
        FROM pg_inherits
        JOIN pg_class AS parent ON parent.oid = pg_inherits.inhparent
        JOIN pg_partitioned_table AS partitioned ON partitioned.partrelid = parent.oid
        JOIN pg_class AS child ON child.oid = pg_inherits.inhrelid
        WHERE parent.oid IN (
            to_regclass('flags_person'),
            to_regclass('flags_distinct_id_map')
        )
        ORDER BY parent.relname, child.relname
        "#,
    )
    .fetch_all(pool)
    .await
    .context("inspect benchmark schema partitions")?;

    let mut tables = BTreeMap::<String, Vec<u8>>::new();
    for (parent, strategy, _child, fillfactor) in rows {
        anyhow::ensure!(
            strategy == "h",
            "{parent} must use hash partitioning, found strategy {strategy}"
        );
        let fillfactor = u8::try_from(fillfactor)
            .with_context(|| format!("invalid fillfactor {fillfactor} on {parent}"))?;
        tables.entry(parent).or_default().push(fillfactor);
    }

    let person = take_table_metadata(&mut tables, PERSON_TABLE)?;
    let distinct_id_map = take_table_metadata(&mut tables, DISTINCT_ID_MAP_TABLE)?;
    anyhow::ensure!(tables.is_empty(), "unexpected benchmark table metadata");
    Ok(SchemaMetadata {
        source,
        requested_schema_arguments_applied: source == SchemaSource::Created,
        person,
        distinct_id_map,
    })
}

fn take_table_metadata(
    tables: &mut BTreeMap<String, Vec<u8>>,
    name: &str,
) -> anyhow::Result<TableMetadata> {
    let partition_fillfactors = tables
        .remove(name)
        .with_context(|| format!("{name} is missing or has no partitions"))?;
    Ok(TableMetadata {
        name: name.to_owned(),
        partition_strategy: PartitionStrategy::Hash,
        partition_count: partition_fillfactors.len(),
        partition_fillfactors,
    })
}
