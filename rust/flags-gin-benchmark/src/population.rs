use flags_consumer::storage::{postgres::PostgresStorage, types::PersonUpdateData};
use rand::rngs::StdRng;
use rand::SeedableRng;
use sqlx::PgPool;
use uuid::Uuid;

use crate::data_gen::{generate_properties, PersonRegistry};

/// Populate the flags_person_lookup table from a PersonRegistry.
///
/// Properties are generated on-the-fly per batch using a separate seeded RNG
/// (seed 43), decoupled from the structural RNG (seed 42) so that removing
/// properties from the registry doesn't change distinct_id distribution.
/// Each batch's properties are dropped after the DB insert.
pub async fn populate(
    pool: &PgPool,
    storage: &PostgresStorage,
    registry: &PersonRegistry,
    batch_size: usize,
) -> anyhow::Result<()> {
    let total = registry.persons.len();
    tracing::info!(total, "populating person rows");

    let mut prop_rng = StdRng::seed_from_u64(43);

    // Step 1: Insert person rows via batch_upsert_persons.
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

    // Step 2: Assign distinct_ids via batch UPDATE (custom, not production upsert_distinct_id).
    assign_distinct_ids_bulk(pool, registry).await?;

    tracing::info!(total, "population complete");
    Ok(())
}

/// Batch-assign distinct_ids using a custom UPDATE that bypasses the single-row
/// transactional upsert_distinct_id (which is designed for incremental CDC, not bulk load).
async fn assign_distinct_ids_bulk(pool: &PgPool, registry: &PersonRegistry) -> anyhow::Result<()> {
    let total = registry.distinct_ids.len();
    tracing::info!(total, "assigning distinct_ids");

    // Group distinct_ids by person_uuid to build per-person arrays.
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
        let did_arrays: Vec<Vec<String>> = chunk.iter().map(|(_, dids)| dids.clone()).collect();

        // Primary distinct_ids (first element of each person's array).
        let primary_dids: Vec<String> = did_arrays.iter().map(|dids| dids[0].clone()).collect();

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

        // Second distinct_ids for persons that have two (the 14% case).
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
