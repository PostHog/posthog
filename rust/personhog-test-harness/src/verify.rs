//! Postgres-side verification shared by the gate and the continuous
//! traffic mode.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use serde_json::{json, Value};
use sqlx::postgres::PgPool;
use sqlx::Row;
use tokio::time::sleep;

use crate::report::ConsistencyViolation;
use crate::state::{verify_properties, ExpectedPerson, MergedSource};

/// How long to wait for the writer to drain acked writes into Postgres
/// before declaring them lost.
pub const QUIESCE_DEADLINE: Duration = Duration::from_secs(60);

/// Poll Postgres until every journaled person row contains all acked
/// property writes at the acked version, or the quiesce deadline passes.
/// Returns the outstanding violations (empty = converged).
///
/// A merged source must be a tombstone: the row is deleted, and its
/// version is above every version the leader acked for it. The fence is
/// checked against the sealed version on the source's
/// `lifecycle_op_person` row. An ack above the seal means a write got
/// through the fence. The death version alone cannot show that, because
/// the leader derives it from its current version too.
pub async fn verify_postgres(
    pool: &PgPool,
    table: &str,
    team_id: i64,
    journal: &HashMap<i64, ExpectedPerson>,
    merged: &HashMap<i64, MergedSource>,
) -> Result<Vec<ConsistencyViolation>> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let person_ids: Vec<i64> = journal.keys().copied().collect();
    let merged_ids: Vec<i64> = merged.keys().copied().collect();
    if person_ids.is_empty() && merged_ids.is_empty() {
        return Ok(Vec::new());
    }

    let query = format!(
        "SELECT id, properties::text AS properties, version \
         FROM {table} WHERE team_id = $1 AND id = ANY($2)"
    );
    let tombstone_query =
        format!("SELECT id, is_deleted, version FROM {table} WHERE team_id = $1 AND id = ANY($2)");
    // A mapping left on a tombstone resolves events to a person that no
    // longer exists.
    let leftover_dids_query = crate::seed::distinct_id_tables_for(table)
        .iter()
        .map(|pdi_table| {
            format!(
                "SELECT person_id, count(*) AS n FROM {pdi_table} \
                 WHERE team_id = $1 AND person_id = ANY($2) GROUP BY person_id"
            )
        })
        .collect::<Vec<_>>();
    // The saga records each source's seal on its op row and sets the
    // row's status to deleted after the flip.
    let sealed_query = "SELECT person_id, (sealed->>'version')::bigint AS sealed_version \
                        FROM lifecycle_op_person \
                        WHERE team_id = $1 AND role = 'source' AND status = 'deleted' \
                          AND person_id = ANY($2)";
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
                .unwrap_or_else(|| json!({}));
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
                            expected: json!(format!(">= {}", expected.last_version)),
                            actual: json!(version),
                        });
                    }
                }
                None => {
                    violations.push(ConsistencyViolation {
                        person_id: *person_id,
                        key: "__row".to_string(),
                        expected: json!("present"),
                        actual: Value::Null,
                    });
                }
            }
        }

        if !merged_ids.is_empty() {
            let rows = sqlx::query(&tombstone_query)
                .bind(team)
                .bind(&merged_ids)
                .fetch_all(pool)
                .await
                .context("reading merged sources from Postgres")?;
            let mut tombstones: HashMap<i64, (bool, i64)> = HashMap::new();
            for row in rows {
                let id: i64 = row.get("id");
                let is_deleted: bool = row.get("is_deleted");
                let version: Option<i64> = row.get("version");
                tombstones.insert(id, (is_deleted, version.unwrap_or(0)));
            }
            let mut seals: HashMap<i64, i64> = HashMap::new();
            for row in sqlx::query(sealed_query)
                .bind(team)
                .bind(&merged_ids)
                .fetch_all(pool)
                .await
                .context("reading merge seals from lifecycle_op_person")?
            {
                let person_id: i64 = row.get("person_id");
                let sealed_version: Option<i64> = row.get("sealed_version");
                if let Some(sealed_version) = sealed_version {
                    seals.insert(person_id, sealed_version);
                }
            }
            for (person_id, source) in merged {
                violations.extend(verify_tombstone(
                    *person_id,
                    source,
                    tombstones.get(person_id).copied(),
                    seals.get(person_id).copied(),
                ));
            }
            for query in &leftover_dids_query {
                for row in sqlx::query(query)
                    .bind(team)
                    .bind(&merged_ids)
                    .fetch_all(pool)
                    .await
                    .context("counting distinct ids left on merged sources")?
                {
                    let person_id: i64 = row.get("person_id");
                    let n: i64 = row.get("n");
                    violations.push(ConsistencyViolation {
                        person_id,
                        key: "__merged_source_dids_left".to_string(),
                        expected: json!("every mapping repointed to the survivor"),
                        actual: json!(n),
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
        sleep(Duration::from_millis(500)).await;
    }
}

/// The decision table for a merged source's row. `row` is
/// `(is_deleted, version)`, or None when the row is gone. `sealed` is
/// the version the saga recorded at the fence, or None when the op row
/// is missing.
pub fn verify_tombstone(
    person_id: i64,
    source: &MergedSource,
    row: Option<(bool, i64)>,
    sealed: Option<i64>,
) -> Vec<ConsistencyViolation> {
    let Some((is_deleted, version)) = row else {
        return vec![ConsistencyViolation {
            person_id,
            key: "__merged_source_row".to_string(),
            expected: json!(format!(
                "tombstone present (merged into {})",
                source.survivor
            )),
            actual: Value::Null,
        }];
    };
    let mut violations = Vec::new();
    if !is_deleted {
        violations.push(ConsistencyViolation {
            person_id,
            key: "__merged_source_tombstone".to_string(),
            expected: json!("is_deleted"),
            actual: json!(false),
        });
    }
    if version <= source.max_acked_version {
        violations.push(ConsistencyViolation {
            person_id,
            key: "__merged_source_death_version".to_string(),
            expected: json!(format!("> {} (highest acked)", source.max_acked_version)),
            actual: json!(version),
        });
    }
    match sealed {
        Some(sealed) if sealed < source.max_acked_version => {
            violations.push(ConsistencyViolation {
                person_id,
                key: "__merged_source_ack_above_seal".to_string(),
                expected: json!(format!("no acked version above seal {sealed}")),
                actual: json!(source.max_acked_version),
            });
        }
        Some(_) => {}
        None => violations.push(ConsistencyViolation {
            person_id,
            key: "__merged_source_seal_record".to_string(),
            expected: json!("a deleted source row on the merge op"),
            actual: Value::Null,
        }),
    }
    violations
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keys(violations: Vec<ConsistencyViolation>) -> Vec<String> {
        violations.into_iter().map(|v| v.key).collect()
    }

    #[test]
    fn tombstone_decision_table() {
        let source = MergedSource::for_test(2, 7);
        assert!(verify_tombstone(1, &source, Some((true, 8)), Some(7)).is_empty());
        assert!(verify_tombstone(1, &source, Some((true, 20)), Some(9)).is_empty());
        assert_eq!(
            keys(verify_tombstone(1, &source, None, Some(7))),
            vec!["__merged_source_row"]
        );
        assert_eq!(
            keys(verify_tombstone(1, &source, Some((false, 8)), Some(7))),
            vec!["__merged_source_tombstone"]
        );
        // Death at the highest acked version: that ack sat above the seal.
        assert_eq!(
            keys(verify_tombstone(1, &source, Some((true, 7)), Some(7))),
            vec!["__merged_source_death_version"]
        );
        assert_eq!(
            keys(verify_tombstone(1, &source, Some((false, 3)), Some(7))),
            vec!["__merged_source_tombstone", "__merged_source_death_version"]
        );
        // The fence failed open: the ack sits above the recorded seal,
        // but the death version cleared it.
        assert_eq!(
            keys(verify_tombstone(1, &source, Some((true, 20)), Some(6))),
            vec!["__merged_source_ack_above_seal"]
        );
        assert_eq!(
            keys(verify_tombstone(1, &source, Some((true, 8)), None)),
            vec!["__merged_source_seal_record"]
        );
    }
}
