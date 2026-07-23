//! Postgres-side verification shared by the gate and the continuous
//! traffic mode.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::report::ConsistencyViolation;
use crate::state::{verify_properties, ExpectedPerson};

/// How long to wait for the writer to drain acked writes into Postgres
/// before declaring them lost.
pub const QUIESCE_DEADLINE: Duration = Duration::from_secs(60);

/// Poll Postgres until every journaled person row contains all acked
/// property writes at the acked version, or the quiesce deadline passes.
/// Returns the outstanding violations (empty = converged).
pub async fn verify_postgres(
    pool: &PgPool,
    table: &str,
    team_id: i64,
    journal: &HashMap<i64, ExpectedPerson>,
) -> Result<Vec<ConsistencyViolation>> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let person_ids: Vec<i64> = journal.keys().copied().collect();
    if person_ids.is_empty() {
        return Ok(Vec::new());
    }

    let query = format!(
        "SELECT id, properties::text AS properties, version \
         FROM {table} WHERE team_id = $1 AND id = ANY($2)"
    );
    let deadline = Instant::now() + QUIESCE_DEADLINE;
    loop {
        let rows = sqlx::query(&query)
            .bind(team)
            .bind(&person_ids)
            .fetch_all(pool)
            .await
            .context("reading persons from Postgres")?;

        let mut by_id: HashMap<i64, (serde_json::Value, i64)> = HashMap::new();
        for row in rows {
            let id: i64 = row.get("id");
            let properties: Option<String> = row.get("properties");
            let version: Option<i64> = row.get("version");
            let props = properties
                .as_deref()
                .map(serde_json::from_str)
                .transpose()
                .context("parsing properties JSON")?
                .unwrap_or_else(|| serde_json::json!({}));
            by_id.insert(id, (props, version.unwrap_or(0)));
        }

        let mut violations = Vec::new();
        for (person_id, expected) in journal {
            match by_id.get(person_id) {
                Some((props, version)) => {
                    violations.extend(verify_properties(
                        *person_id,
                        &expected.written_properties,
                        props,
                    ));
                    // The highest acked version is a floor, not an exact
                    // target: a write that produced its record but lost the
                    // response (a drain, a client timeout) is unacked yet
                    // still applied, legitimately leaving the row above the
                    // floor. Below it, an acked write never reached
                    // Postgres.
                    if *version < expected.last_version {
                        violations.push(ConsistencyViolation {
                            person_id: *person_id,
                            key: "__version".to_string(),
                            expected: serde_json::json!(format!(">= {}", expected.last_version)),
                            actual: serde_json::json!(version),
                        });
                    }
                }
                None => {
                    violations.push(ConsistencyViolation {
                        person_id: *person_id,
                        key: "__row".to_string(),
                        expected: serde_json::json!("present"),
                        actual: serde_json::Value::Null,
                    });
                }
            }
        }

        if violations.is_empty() {
            return Ok(violations);
        }
        if Instant::now() > deadline {
            tracing::error!(
                outstanding = violations.len(),
                "Postgres did not converge within {QUIESCE_DEADLINE:?}"
            );
            return Ok(violations);
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}
