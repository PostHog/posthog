use anyhow::Context;
use serde::Serialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

use crate::storage::postgres::{
    CANONICAL_READ_SQL, DISTINCT_ID_DELETE_SQL, DISTINCT_ID_UPSERT_SQL, PERSON_DELETE_SQL,
    PERSON_UPSERT_SQL,
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PlanNodeEvidence {
    pub node_type: Box<str>,
    pub relation_name: Option<Box<str>>,
    pub index_name: Option<Box<str>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct NamedPlanEvidence {
    pub name: &'static str,
    pub nodes: Vec<PlanNodeEvidence>,
    pub conflict_arbiter_indexes: Vec<Box<str>>,
    pub plan: Value,
}

#[derive(Debug, Clone, Copy)]
enum PlanRequirement {
    CanonicalRead,
    Write { table: &'static str },
}

pub async fn verify_storage_plans(pool: &PgPool) -> anyhow::Result<Vec<NamedPlanEvidence>> {
    let person_uuid = Uuid::from_u128(1);
    let team_ids = vec![1i32];
    let person_uuids = vec![person_uuid];
    let properties = vec![json!({"plancheck": true})];
    let versions = vec![2i64];
    let distinct_ids = vec!["plancheck-distinct-id"];

    let canonical_read = sqlx::query_scalar::<_, Value>(&explain(CANONICAL_READ_SQL))
        .bind(1i32)
        .bind("plancheck-distinct-id")
        .fetch_one(pool)
        .await
        .context("EXPLAIN canonical read")?;
    let canonical_read = validate_plan(
        "canonical_read",
        canonical_read,
        PlanRequirement::CanonicalRead,
    )?;
    let person_upsert = sqlx::query_scalar::<_, Value>(&explain(PERSON_UPSERT_SQL))
        .bind(&team_ids)
        .bind(&person_uuids)
        .bind(&properties)
        .bind(&versions)
        .fetch_one(pool)
        .await
        .context("EXPLAIN person upsert")?;
    let person_delete = sqlx::query_scalar::<_, Value>(&explain(PERSON_DELETE_SQL))
        .bind(&team_ids)
        .bind(&person_uuids)
        .bind(&versions)
        .fetch_one(pool)
        .await
        .context("EXPLAIN person tombstone")?;
    let distinct_id_upsert = sqlx::query_scalar::<_, Value>(&explain(DISTINCT_ID_UPSERT_SQL))
        .bind(&team_ids)
        .bind(&distinct_ids)
        .bind(&person_uuids)
        .bind(&versions)
        .fetch_one(pool)
        .await
        .context("EXPLAIN distinct ID upsert")?;
    let distinct_id_delete = sqlx::query_scalar::<_, Value>(&explain(DISTINCT_ID_DELETE_SQL))
        .bind(&team_ids)
        .bind(&distinct_ids)
        .bind(&person_uuids)
        .bind(&versions)
        .fetch_one(pool)
        .await
        .context("EXPLAIN owner-guarded distinct ID tombstone")?;

    let mut evidence = vec![canonical_read];
    evidence.extend(
        [
            (
                "person_upsert",
                person_upsert,
                PlanRequirement::Write {
                    table: "flags_person",
                },
            ),
            (
                "person_tombstone",
                person_delete,
                PlanRequirement::Write {
                    table: "flags_person",
                },
            ),
            (
                "distinct_id_upsert",
                distinct_id_upsert,
                PlanRequirement::Write {
                    table: "flags_distinct_id_map",
                },
            ),
            (
                "distinct_id_tombstone",
                distinct_id_delete,
                PlanRequirement::Write {
                    table: "flags_distinct_id_map",
                },
            ),
        ]
        .into_iter()
        .map(|(name, plan, requirement)| validate_plan(name, plan, requirement))
        .collect::<anyhow::Result<Vec<_>>>()?,
    );
    Ok(evidence)
}

fn explain(sql: &str) -> String {
    format!("EXPLAIN (FORMAT JSON) {sql}")
}

fn validate_plan(
    name: &'static str,
    plan: Value,
    requirement: PlanRequirement,
) -> anyhow::Result<NamedPlanEvidence> {
    let mut nodes = Vec::new();
    let mut conflict_arbiter_indexes = Vec::new();
    collect_evidence(&plan, &mut nodes, &mut conflict_arbiter_indexes);

    let sequential_scans = nodes
        .iter()
        .filter(|node| node.node_type.as_ref() == "Seq Scan")
        .map(|node| node.relation_name.as_deref().unwrap_or("unknown"))
        .collect::<Vec<_>>();
    if !sequential_scans.is_empty() {
        anyhow::bail!(
            "plancheck {name} rejected sequential scans on: {}",
            sequential_scans.join(", ")
        );
    }

    match requirement {
        PlanRequirement::CanonicalRead => {
            for table in ["flags_distinct_id_map", "flags_person"] {
                if !nodes.iter().any(|node| is_index_access_for(node, table)) {
                    anyhow::bail!(
                        "plancheck {name} requires index access for {table}; nodes: {}",
                        format_nodes(&nodes)
                    );
                }
            }
        }
        PlanRequirement::Write { table } => {
            if conflict_arbiter_indexes.is_empty() {
                anyhow::bail!(
                    "plancheck {name} did not expose a conflict arbiter index for {table}"
                );
            }
            if !conflict_arbiter_indexes
                .iter()
                .all(|index| is_primary_key_for(index, table))
            {
                anyhow::bail!(
                    "plancheck {name} exposed unexpected conflict arbiter indexes for {table}: {}",
                    conflict_arbiter_indexes
                        .iter()
                        .map(AsRef::as_ref)
                        .collect::<Vec<&str>>()
                        .join(", ")
                );
            }
        }
    }

    Ok(NamedPlanEvidence {
        name,
        nodes,
        conflict_arbiter_indexes,
        plan,
    })
}

fn collect_evidence(
    value: &Value,
    nodes: &mut Vec<PlanNodeEvidence>,
    conflict_arbiter_indexes: &mut Vec<Box<str>>,
) {
    match value {
        Value::Object(object) => {
            if let Some(node_type) = object.get("Node Type").and_then(Value::as_str) {
                nodes.push(PlanNodeEvidence {
                    node_type: node_type.into(),
                    relation_name: object
                        .get("Relation Name")
                        .and_then(Value::as_str)
                        .map(Into::into),
                    index_name: object
                        .get("Index Name")
                        .and_then(Value::as_str)
                        .map(Into::into),
                });
            }
            if let Some(indexes) = object
                .get("Conflict Arbiter Indexes")
                .and_then(Value::as_array)
            {
                conflict_arbiter_indexes
                    .extend(indexes.iter().filter_map(Value::as_str).map(Into::into));
            }
            for child in object.values() {
                collect_evidence(child, nodes, conflict_arbiter_indexes);
            }
        }
        Value::Array(values) => {
            for child in values {
                collect_evidence(child, nodes, conflict_arbiter_indexes);
            }
        }
        _ => {}
    }
}

fn is_index_access_for(node: &PlanNodeEvidence, table: &str) -> bool {
    matches!(
        node.node_type.as_ref(),
        "Index Scan" | "Index Only Scan" | "Bitmap Index Scan"
    ) && (node
        .relation_name
        .as_deref()
        .is_some_and(|relation| relation.starts_with(table))
        || node
            .index_name
            .as_deref()
            .is_some_and(|index| index.starts_with(table)))
}

fn is_primary_key_for(index: &str, table: &str) -> bool {
    index == format!("{table}_pkey") || (index.starts_with(table) && index.ends_with("_pkey"))
}

fn format_nodes(nodes: &[PlanNodeEvidence]) -> String {
    nodes
        .iter()
        .map(|node| {
            format!(
                "{}({})",
                node.node_type,
                node.relation_name.as_deref().unwrap_or("no relation")
            )
        })
        .collect::<Vec<_>>()
        .join(", ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recursive_validation_rejects_scans_and_requires_both_read_indexes() {
        let scan = json!([{"Plan": {
            "Node Type": "Nested Loop",
            "Plans": [{"Node Type": "Seq Scan", "Relation Name": "flags_person_p0"}]
        }}]);
        let error = validate_plan("canonical_read", scan, PlanRequirement::CanonicalRead)
            .expect_err("sequential scan must fail");
        assert!(error.to_string().contains("flags_person_p0"));

        let indexed = json!([{"Plan": {
            "Node Type": "Nested Loop",
            "Plans": [
                {"Node Type": "Index Scan", "Relation Name": "flags_distinct_id_map_p0", "Index Name": "flags_distinct_id_map_p0_pkey"},
                {"Node Type": "Index Scan", "Relation Name": "flags_person_p0", "Index Name": "flags_person_p0_pkey"}
            ]
        }}]);
        let evidence = validate_plan("canonical_read", indexed, PlanRequirement::CanonicalRead)
            .expect("both probes use indexes");
        assert_eq!(evidence.nodes.len(), 3);
    }

    #[test]
    fn write_validation_requires_the_expected_primary_key_arbiter() {
        let no_arbiter = json!([{"Plan": {"Node Type": "ModifyTable"}}]);
        assert!(validate_plan(
            "person_upsert",
            no_arbiter,
            PlanRequirement::Write {
                table: "flags_person"
            }
        )
        .expect_err("missing arbiter must fail")
        .to_string()
        .contains("did not expose"));

        let wrong_arbiter = json!([{"Plan": {
            "Node Type": "ModifyTable",
            "Conflict Arbiter Indexes": ["unrelated_key"]
        }}]);
        assert!(validate_plan(
            "person_upsert",
            wrong_arbiter,
            PlanRequirement::Write {
                table: "flags_person"
            }
        )
        .expect_err("wrong arbiter must fail")
        .to_string()
        .contains("unexpected conflict arbiter"));

        let correct_arbiter = json!([{"Plan": {
            "Node Type": "ModifyTable",
            "Conflict Arbiter Indexes": ["flags_person_pkey"]
        }}]);
        validate_plan(
            "person_upsert",
            correct_arbiter,
            PlanRequirement::Write {
                table: "flags_person",
            },
        )
        .expect("primary key arbiter");
    }
}
