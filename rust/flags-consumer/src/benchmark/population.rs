use crate::storage::{postgres::PostgresStorage, types::PersonUpdateData};
use rand::rngs::StdRng;
use rand::SeedableRng;
use sqlx::PgPool;
use uuid::Uuid;

use super::data_gen::{generate_properties, PersonRegistry};

/// Uses a separate seeded RNG (seed 43) for properties so the structural
/// distribution (persons, distinct_ids) is independent of property generation.
pub async fn populate(
    pool: &PgPool,
    storage: &PostgresStorage,
    registry: &PersonRegistry,
    batch_size: usize,
) -> anyhow::Result<()> {
    let total = registry.persons.len();
    tracing::info!(total, "populating person rows");

    let mut prop_rng = StdRng::seed_from_u64(43);

    for (batch_idx, chunk) in registry.persons.chunks(batch_size).enumerate() {
        let updates: Vec<PersonUpdateData> = chunk
            .iter()
            .map(|(team_id, uuid)| PersonUpdateData {
                team_id: *team_id,
                person_uuid: *uuid,
                properties: generate_properties(&mut prop_rng, 700),
                version: 1,
            })
            .collect();

        storage.batch_upsert_persons(&updates).await?;

        let done = ((batch_idx + 1) * batch_size).min(total);
        if done % (total / 10).max(1) < batch_size {
            tracing::info!(done, total, "persons inserted");
        }
    }

    assign_distinct_ids_bulk(pool, registry).await?;

    tracing::info!(total, "population complete");
    Ok(())
}

/// Bulk-assigns distinct_ids via UNNEST instead of the single-row transactional
/// upsert_distinct_id, which would be too slow for initial population.
async fn assign_distinct_ids_bulk(pool: &PgPool, registry: &PersonRegistry) -> anyhow::Result<()> {
    let total = registry.distinct_ids.len();
    tracing::info!(total, "assigning distinct_ids");

    let mut person_dids: std::collections::HashMap<(i32, Uuid), Vec<String>> =
        std::collections::HashMap::new();
    for (team_id, person_uuid, did) in &registry.distinct_ids {
        person_dids
            .entry((*team_id, *person_uuid))
            .or_default()
            .push(did.clone());
    }

    let entries: Vec<((i32, Uuid), Vec<String>)> = person_dids.into_iter().collect();
    let batch_size = 500;

    for (batch_idx, chunk) in entries.chunks(batch_size).enumerate() {
        let team_ids: Vec<i32> = chunk.iter().map(|((tid, _), _)| *tid).collect();
        let person_uuids: Vec<Uuid> = chunk.iter().map(|((_, uuid), _)| *uuid).collect();
        let primary_dids: Vec<String> = chunk.iter().map(|(_, dids)| dids[0].clone()).collect();

        sqlx::query(
            r#"
            UPDATE flags_person_lookup AS f
            SET distinct_ids = ARRAY[t.did]::text[],
                distinct_id_version = 1
            FROM UNNEST($1::int[], $2::uuid[], $3::text[]) AS t(team_id, person_uuid, did)
            WHERE f.team_id = t.team_id AND f.person_uuid = t.person_uuid
            "#,
        )
        .bind(&team_ids)
        .bind(&person_uuids)
        .bind(&primary_dids)
        .execute(pool)
        .await?;

        let mut extra_team_ids = Vec::new();
        let mut extra_uuids = Vec::new();
        let mut extra_dids = Vec::new();
        for ((tid, uuid), dids) in chunk {
            if dids.len() > 1 {
                for extra_did in &dids[1..] {
                    extra_team_ids.push(*tid);
                    extra_uuids.push(*uuid);
                    extra_dids.push(extra_did.clone());
                }
            }
        }

        if !extra_dids.is_empty() {
            sqlx::query(
                r#"
                UPDATE flags_person_lookup AS f
                SET distinct_ids = f.distinct_ids || t.did
                FROM UNNEST($1::int[], $2::uuid[], $3::text[]) AS t(team_id, person_uuid, did)
                WHERE f.team_id = t.team_id AND f.person_uuid = t.person_uuid
                "#,
            )
            .bind(&extra_team_ids)
            .bind(&extra_uuids)
            .bind(&extra_dids)
            .execute(pool)
            .await?;
        }

        let done = ((batch_idx + 1) * batch_size).min(entries.len());
        if done % (entries.len() / 10).max(1) < batch_size {
            tracing::info!(done, total = entries.len(), "distinct_ids assigned");
        }
    }

    Ok(())
}
