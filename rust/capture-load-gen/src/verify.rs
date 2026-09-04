//! Shadow-parity verification: compares the Postgres person graph the
//! authoritative backend writes against the personhog writer's temp
//! tables, for every distinct id the generator's prefix names.
//!
//! Rows are matched by distinct id and compared on uuid, properties,
//! is_identified, and created_at. Version, last_seen_at, and the
//! Postgres-only bookkeeping columns are excluded: they legitimately
//! differ between backends for identical state. The shadow leg trails
//! the authoritative one by the writer's changelog lag, so the run
//! polls until the graphs agree, and only a mismatch that outlasts the
//! deadline reports.

use std::collections::{BTreeMap, BTreeSet};
use std::time::Duration;

use anyhow::{bail, Context, Result};
use metrics::gauge;
use serde_json::Value;
use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};

const SWEEP_INTERVAL: Duration = Duration::from_secs(5);

pub struct VerifyConfig {
    pub database_url: String,
    pub prefix: String,
    pub tmp_person_table: String,
    pub tmp_pdi_table: String,
    pub deadline: Duration,
}

/// The compared slice of a person row, shared by both graphs.
#[derive(Debug, Clone, PartialEq)]
pub struct DurableRow {
    pub uuid: String,
    pub properties: Value,
    pub is_identified: bool,
    pub created_at_ms: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum MismatchKind {
    MissingShadow,
    ExtraShadow,
    Uuid,
    Properties,
    IsIdentified,
    CreatedAt,
}

impl MismatchKind {
    pub fn as_str(self) -> &'static str {
        match self {
            MismatchKind::MissingShadow => "missing_shadow",
            MismatchKind::ExtraShadow => "extra_shadow",
            MismatchKind::Uuid => "uuid",
            MismatchKind::Properties => "properties",
            MismatchKind::IsIdentified => "is_identified",
            MismatchKind::CreatedAt => "created_at",
        }
    }

    const ALL: [MismatchKind; 6] = [
        MismatchKind::MissingShadow,
        MismatchKind::ExtraShadow,
        MismatchKind::Uuid,
        MismatchKind::Properties,
        MismatchKind::IsIdentified,
        MismatchKind::CreatedAt,
    ];
}

/// Field-level differences between the two graphs' rows for one distinct
/// id. serde_json object equality is key-order-insensitive, so jsonb
/// reordering cannot read as a properties difference.
pub fn compare_rows(main: Option<&DurableRow>, tmp: Option<&DurableRow>) -> Vec<MismatchKind> {
    match (main, tmp) {
        (None, None) => Vec::new(),
        (Some(_), None) => vec![MismatchKind::MissingShadow],
        (None, Some(_)) => vec![MismatchKind::ExtraShadow],
        (Some(main), Some(tmp)) => {
            let mut kinds = Vec::new();
            if main.uuid != tmp.uuid {
                kinds.push(MismatchKind::Uuid);
            }
            if main.properties != tmp.properties {
                kinds.push(MismatchKind::Properties);
            }
            if main.is_identified != tmp.is_identified {
                kinds.push(MismatchKind::IsIdentified);
            }
            if main.created_at_ms != tmp.created_at_ms {
                kinds.push(MismatchKind::CreatedAt);
            }
            kinds
        }
    }
}

/// The property keys whose values differ, for a report that never prints
/// the values themselves.
fn differing_property_keys(main: &Value, tmp: &Value) -> Vec<String> {
    let empty = serde_json::Map::new();
    let left = main.as_object().unwrap_or(&empty);
    let right = tmp.as_object().unwrap_or(&empty);
    let mut keys: BTreeSet<&String> = left.keys().collect();
    keys.extend(right.keys());
    keys.into_iter()
        .filter(|key| left.get(*key) != right.get(*key))
        .cloned()
        .collect()
}

pub struct Verifier {
    pool: PgPool,
    team_id: i32,
    prefix_pattern: String,
    tmp_person_table: String,
    tmp_pdi_table: String,
}

impl Verifier {
    pub async fn connect(cfg: &VerifyConfig) -> Result<Self> {
        let pool = PgPoolOptions::new()
            .max_connections(4)
            .connect(&cfg.database_url)
            .await
            .context("connecting to the persons database")?;
        // LIKE special characters in the prefix would silently widen the
        // cohort.
        let prefix_pattern = format!(
            "{}%",
            cfg.prefix.replace('\\', "\\\\").replace(['%', '_'], "\\")
        );
        let team_id = resolve_team(&pool, &prefix_pattern).await?;
        Ok(Self {
            pool,
            team_id,
            prefix_pattern,
            tmp_person_table: cfg.tmp_person_table.clone(),
            tmp_pdi_table: cfg.tmp_pdi_table.clone(),
        })
    }

    /// Every prefix-matched distinct id from both graphs, so an id only
    /// one side knows is enumerated rather than invisible.
    async fn cohort(&self) -> Result<BTreeSet<String>> {
        let mut ids: BTreeSet<String> = BTreeSet::new();
        let main_rows = sqlx::query(
            "SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id LIKE $2",
        )
        .bind(self.team_id)
        .bind(&self.prefix_pattern)
        .fetch_all(&self.pool)
        .await
        .context("enumerating the authoritative cohort")?;
        for row in main_rows {
            ids.insert(row.get::<String, _>(0));
        }
        let tmp_sql = format!(
            "SELECT distinct_id FROM {} WHERE team_id = $1 AND distinct_id LIKE $2 AND is_deleted = false",
            self.tmp_pdi_table
        );
        let tmp_rows = sqlx::query(&tmp_sql)
            .bind(self.team_id)
            .bind(&self.prefix_pattern)
            .fetch_all(&self.pool)
            .await
            .context("enumerating the shadow cohort")?;
        for row in tmp_rows {
            ids.insert(row.get::<String, _>(0));
        }
        Ok(ids)
    }

    async fn main_row(&self, distinct_id: &str) -> Result<Option<DurableRow>> {
        let row = sqlx::query(
            "SELECT p.uuid::text, p.properties, p.is_identified,
                    (extract(epoch from p.created_at) * 1000)::bigint AS created_at_ms
               FROM posthog_persondistinctid d
               JOIN posthog_person p ON p.id = d.person_id
              WHERE d.team_id = $1 AND d.distinct_id = $2",
        )
        .bind(self.team_id)
        .bind(distinct_id)
        .fetch_optional(&self.pool)
        .await?;
        Ok(row.map(|row| DurableRow {
            uuid: row.get(0),
            properties: row.get(1),
            is_identified: row.get(2),
            created_at_ms: row.get(3),
        }))
    }

    async fn tmp_row(&self, distinct_id: &str) -> Result<Option<DurableRow>> {
        let sql = format!(
            "SELECT p.uuid::text, p.properties, p.is_identified,
                    (extract(epoch from p.created_at) * 1000)::bigint AS created_at_ms
               FROM {} d
               JOIN {} p ON p.id = d.person_id AND p.team_id = d.team_id
              WHERE d.team_id = $1 AND d.distinct_id = $2
                AND d.is_deleted = false AND p.is_deleted = false",
            self.tmp_pdi_table, self.tmp_person_table
        );
        let row = sqlx::query(&sql)
            .bind(self.team_id)
            .bind(distinct_id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(row.map(|row| DurableRow {
            uuid: row.get(0),
            properties: row.get(1),
            is_identified: row.get(2),
            created_at_ms: row.get(3),
        }))
    }

    /// One full comparison pass; the map's emptiness is the verdict.
    async fn sweep(&self) -> Result<(usize, BTreeMap<String, Vec<MismatchKind>>)> {
        let cohort = self.cohort().await?;
        let mut mismatches = BTreeMap::new();
        for distinct_id in &cohort {
            let main = self.main_row(distinct_id).await?;
            let tmp = self.tmp_row(distinct_id).await?;
            let kinds = compare_rows(main.as_ref(), tmp.as_ref());
            if !kinds.is_empty() {
                if let (Some(main), Some(tmp)) = (main.as_ref(), tmp.as_ref()) {
                    if kinds.contains(&MismatchKind::Properties) {
                        tracing::warn!(
                            distinct_id,
                            differing_keys = ?differing_property_keys(&main.properties, &tmp.properties),
                            "shadow properties differ"
                        );
                    }
                }
                mismatches.insert(distinct_id.clone(), kinds);
            }
        }
        Ok((cohort.len(), mismatches))
    }

    fn export_gauges(&self, cohort: usize, mismatches: &BTreeMap<String, Vec<MismatchKind>>) {
        let mut by_kind: BTreeMap<MismatchKind, u64> = BTreeMap::new();
        for kinds in mismatches.values() {
            for kind in kinds {
                *by_kind.entry(*kind).or_default() += 1;
            }
        }
        for kind in MismatchKind::ALL {
            gauge!("capture_loadgen_parity_mismatches", "kind" => kind.as_str())
                .set(by_kind.get(&kind).copied().unwrap_or(0) as f64);
        }
        gauge!("capture_loadgen_parity_cohort_size").set(cohort as f64);
        gauge!("capture_loadgen_parity_last_sweep_timestamp_seconds")
            .set(common_metrics::get_current_timestamp_seconds());
    }

    /// Polls until the graphs agree or the deadline passes; a lagging
    /// writer and a real divergence read identically row-side, so the
    /// deadline is the only arbiter and the report says so.
    pub async fn run(&self, cfg: &VerifyConfig) -> Result<bool> {
        let deadline = tokio::time::Instant::now() + cfg.deadline;
        loop {
            let (cohort, mismatches) = self.sweep().await?;
            self.export_gauges(cohort, &mismatches);
            if mismatches.is_empty() {
                tracing::info!(cohort, "shadow graphs agree");
                return Ok(true);
            }
            if tokio::time::Instant::now() >= deadline {
                for (distinct_id, kinds) in &mismatches {
                    let kinds: Vec<&str> = kinds.iter().map(|kind| kind.as_str()).collect();
                    tracing::warn!(distinct_id, ?kinds, "still mismatched at the deadline");
                }
                tracing::warn!(
                    cohort,
                    mismatched_ids = mismatches.len(),
                    deadline_secs = cfg.deadline.as_secs(),
                    "shadow parity verification failed"
                );
                return Ok(false);
            }
            tokio::time::sleep(SWEEP_INTERVAL).await;
        }
    }
}

/// The cohort's team, from the rows themselves; refusing an ambiguous
/// answer beats comparing two teams' graphs as one.
async fn resolve_team(pool: &PgPool, prefix_pattern: &str) -> Result<i32> {
    let teams: Vec<i32> = sqlx::query_scalar(
        "SELECT DISTINCT team_id FROM posthog_persondistinctid WHERE distinct_id LIKE $1",
    )
    .bind(prefix_pattern)
    .fetch_all(pool)
    .await
    .context("resolving the cohort's team")?;
    match teams.as_slice() {
        [team_id] => Ok(*team_id),
        [] => bail!("no rows match the prefix; nothing to verify"),
        many => bail!("the prefix spans {} teams: {many:?}", many.len()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn row(uuid: &str, properties: Value, is_identified: bool, created_at_ms: i64) -> DurableRow {
        DurableRow {
            uuid: uuid.to_string(),
            properties,
            is_identified,
            created_at_ms,
        }
    }

    #[test]
    fn equal_rows_and_double_absence_match() {
        let a = row("u1", json!({"a": 1}), true, 5);
        assert_eq!(compare_rows(Some(&a), Some(&a.clone())), vec![]);
        assert_eq!(compare_rows(None, None), vec![]);
    }

    #[test]
    fn one_sided_presence_names_the_missing_side() {
        let a = row("u1", json!({}), false, 5);
        assert_eq!(
            compare_rows(Some(&a), None),
            vec![MismatchKind::MissingShadow]
        );
        assert_eq!(
            compare_rows(None, Some(&a)),
            vec![MismatchKind::ExtraShadow]
        );
    }

    #[test]
    fn every_differing_field_is_named() {
        let main = row("u1", json!({"a": 1}), true, 5);
        let tmp = row("u2", json!({"a": 2}), false, 6);
        assert_eq!(
            compare_rows(Some(&main), Some(&tmp)),
            vec![
                MismatchKind::Uuid,
                MismatchKind::Properties,
                MismatchKind::IsIdentified,
                MismatchKind::CreatedAt,
            ]
        );
    }

    #[test]
    fn property_key_order_is_not_a_difference() {
        let main = row("u1", json!({"a": 1, "b": {"c": 2, "d": 3}}), true, 5);
        let tmp = row("u1", json!({"b": {"d": 3, "c": 2}, "a": 1}), true, 5);
        assert_eq!(compare_rows(Some(&main), Some(&tmp)), vec![]);
    }
}
