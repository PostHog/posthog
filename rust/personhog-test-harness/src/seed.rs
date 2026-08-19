use anyhow::{bail, Context, Result};
use metrics::{counter, histogram};
use personhog_proto::personhog::identity::v1::GetOrCreatePersonEntry;
use sqlx::postgres::PgPool;

use crate::client::IdentityClient;

/// Seed `count` persons for `team_id` directly in `table` and return their
/// ids, assigned by the table's own id default so they spread across
/// leader partitions exactly like organic ids.
///
/// Every harness mode operates on one configured table (the writer's
/// validation target by default) for seeding, verification, and cleanup
/// alike — `posthog_person` is deliberately not reachable from here.
///
/// There is no team to seed: the persons database has no team table and no
/// foreign key on `team_id` — a team exists here only as an integer value
/// on rows, so the first insert brings the harness team into existence and
/// a team-wide delete removes every trace of it.
///
/// This SQL path is the default; the gate's --create-via-identity flag
/// swaps in the personhog-identity GetOrCreatePersonsByDistinctIds RPC
/// instead.
pub async fn seed_persons(
    pool: &PgPool,
    table: &str,
    team_id: i64,
    count: u32,
) -> Result<Vec<i64>> {
    validate_table_name(table)?;
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;

    let ids: Vec<i64> = sqlx::query_scalar(&format!(
        r#"
        INSERT INTO {table} (
            team_id, uuid, properties, properties_last_updated_at,
            properties_last_operation, created_at, version, is_identified
        )
        SELECT $1, gen_random_uuid(), '{{}}'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, now(), 0, false
        FROM generate_series(1, $2)
        RETURNING id
        "#
    ))
    .bind(team)
    .bind(count as i32)
    .fetch_all(pool)
    .await
    .with_context(|| format!("seeding persons into {table}"))?;

    Ok(ids)
}

/// The mapping table paired with a person table — the one identity
/// writes and whose FK blocks the person delete. Cleanup stays inside
/// the person table's own namespace: targeting the validation set must
/// never delete from the real tables.
fn distinct_id_tables_for(person_table: &str) -> &'static [&'static str] {
    if person_table == "personhog_person_tmp" {
        &["personhog_persondistinctid_tmp"]
    } else {
        &["posthog_persondistinctid"]
    }
}

/// Create (or revive) one person per distinct id through the identity
/// service and return their row ids in entry order. This is the bed's
/// seeding path: creation runs the same get-or-create the ingestion
/// store uses, so `created_at`, uuids, and mapping rows are all
/// server-authoritative — the harness can no longer invent a timestamp
/// the stack must survive. Recycled distinct ids resolve to tombstoned
/// rows and exercise the revival branch, counted separately from fresh
/// creates.
pub async fn seed_persons_via_identity(
    identity: &IdentityClient,
    team_id: i64,
    distinct_ids: &[String],
) -> Result<Vec<i64>> {
    let mut ids = Vec::with_capacity(distinct_ids.len());
    // The identity service caps batches at 250 entries.
    for chunk in distinct_ids.chunks(200) {
        let started = std::time::Instant::now();
        let entries = chunk
            .iter()
            .map(|distinct_id| GetOrCreatePersonEntry {
                team_id,
                distinct_id: distinct_id.clone(),
                extra_distinct_ids: vec![],
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(
                    &serde_json::json!({ "harness_seed": distinct_id }),
                )
                .expect("seed properties serialize"),
                ..Default::default()
            })
            .collect();
        let results = identity.get_or_create_persons(entries).await?;
        histogram!("personhog_traffic_pool_seed_duration_ms")
            .record(started.elapsed().as_secs_f64() * 1000.0);
        for result in results {
            if let Some(error) = &result.error {
                bail!("get-or-create rejected a seed entry: {error:?}");
            }
            let person = result
                .person
                .context("get-or-create returned no person for a seed entry")?;
            let outcome = if result.created {
                "created"
            } else {
                "resolved"
            };
            counter!("personhog_traffic_pool_seed_total", "outcome" => outcome).increment(1);
            ids.push(person.id);
        }
    }
    Ok(ids)
}

/// Delete all of `team_id`'s rows from `table`, plus the distinct id
/// mappings the identity-service create path writes. The harness owns
/// its team ids outright, so team-wide deletes are the whole cleanup.
/// Distinct id rows go first: their FK references the person rows.
pub async fn cleanup_team(pool: &PgPool, table: &str, team_id: i64) -> Result<u64> {
    validate_table_name(table)?;
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;

    for pdi_table in distinct_id_tables_for(table) {
        sqlx::query(&format!("DELETE FROM {pdi_table} WHERE team_id = $1"))
            .bind(team)
            .execute(pool)
            .await
            .with_context(|| format!("deleting distinct ids from {pdi_table}"))?;
    }

    let deleted = sqlx::query(&format!("DELETE FROM {table} WHERE team_id = $1"))
        .bind(team)
        .execute(pool)
        .await
        .with_context(|| format!("cleaning up {table}"))?
        .rows_affected();
    Ok(deleted)
}

/// The table name comes from the operator's CLI/env, but sanity-check it
/// anyway since it is interpolated into SQL (identifiers cannot be bound).
pub fn validate_table_name(table: &str) -> Result<()> {
    personhog_common::persons::validate_table_name(table).map_err(|e| anyhow::anyhow!(e))
}

#[cfg(test)]
mod tests {
    use super::validate_table_name;

    #[test]
    fn validate_table_name_gates_what_reaches_sql_interpolation() {
        for ok in ["posthog_person", "personhog_person_tmp", "t1"] {
            assert!(validate_table_name(ok).is_ok(), "{ok} should be valid");
        }
        for bad in [
            "",
            "posthog_person; DROP TABLE posthog_person",
            "table-name",
            "table name",
            "table\"quoted",
        ] {
            assert!(
                validate_table_name(bad).is_err(),
                "{bad:?} should be rejected"
            );
        }
    }
}
