use crate::storage::{
    postgres::PostgresStorage,
    types::{DistinctIdAssignmentData, PersonUpdateData},
};
use rand::rngs::StdRng;
use rand::SeedableRng;
use serde::Serialize;
use sqlx::PgPool;

use super::world::{generate_properties as generate_world_properties, PopulationView};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct PopulationSummary {
    pub persons: u64,
    pub distinct_ids: u64,
}

pub async fn populate_world(
    pool: &PgPool,
    storage: &PostgresStorage,
    population: PopulationView<'_>,
    batch_size: usize,
) -> anyhow::Result<PopulationSummary> {
    anyhow::ensure!(batch_size > 0, "population batch size must be positive");

    let mut property_rng = StdRng::seed_from_u64(population.property_seed());
    let mut updates = Vec::with_capacity(batch_size);
    let mut person_count = 0u64;
    for person in population.persons() {
        updates.push(PersonUpdateData {
            team_id: person.team_id,
            person_uuid: person.person_uuid,
            properties: generate_world_properties(&mut property_rng, population.property_bytes()),
            version: person.version,
        });
        person_count = person_count.saturating_add(1);
        if updates.len() == batch_size {
            storage.batch_upsert_persons(&updates).await?;
            updates.clear();
        }
    }
    if !updates.is_empty() {
        storage.batch_upsert_persons(&updates).await?;
    }

    let mut assignments = Vec::with_capacity(batch_size);
    let mut distinct_id_count = 0u64;
    for distinct_id in population.distinct_ids() {
        assignments.push(DistinctIdAssignmentData {
            team_id: distinct_id.team_id,
            person_uuid: distinct_id.person_uuid,
            distinct_id: distinct_id.distinct_id,
            version: distinct_id.version,
        });
        distinct_id_count = distinct_id_count.saturating_add(1);
        if assignments.len() == batch_size {
            storage.batch_upsert_distinct_ids(&assignments).await?;
            assignments.clear();
        }
    }
    if !assignments.is_empty() {
        storage.batch_upsert_distinct_ids(&assignments).await?;
    }

    vacuum_analyze_checkpoint(pool).await?;
    Ok(PopulationSummary {
        persons: person_count,
        distinct_ids: distinct_id_count,
    })
}

pub async fn vacuum_analyze_checkpoint(pool: &PgPool) -> anyhow::Result<()> {
    tracing::info!("vacuuming populated tables");
    sqlx::query("VACUUM (ANALYZE) flags_person")
        .execute(pool)
        .await?;
    sqlx::query("VACUUM (ANALYZE) flags_distinct_id_map")
        .execute(pool)
        .await?;
    sqlx::query("CHECKPOINT").execute(pool).await?;
    Ok(())
}
