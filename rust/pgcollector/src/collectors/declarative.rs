//! Tier A: a collector defined entirely by a YAML file (see collectors/*.yaml).

use crate::collector::*;
use anyhow::{Context, Result};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde::Deserialize;
use std::path::Path;
use std::time::Duration;
use tokio_postgres::types::Type;

#[derive(Debug, Deserialize)]
pub struct Spec {
    pub name: String,
    #[serde(with = "humantime_serde")]
    pub interval: Duration,
    pub scope: Scope,
    pub kind: Kind,
    #[serde(default = "default_min_version")]
    pub min_pg_version: u32,
    #[serde(default)]
    pub key: Vec<String>,
    #[serde(default)]
    pub prefers_reader: bool,
    /// Override the default (cluster scope → every instance, database scope → writer only).
    pub per_instance: Option<bool>,
    /// Server-side prerequisites (`aurora: true`, `extension: pg_proctab`).
    #[serde(default)]
    pub requires: Requirements,
    /// Ship disabled (opt in via overrides). For collectors whose cost scales
    /// with backends/relations rather than being a single catalog read.
    #[serde(default = "default_true")]
    pub enabled: bool,
    /// For `cumulative`: numeric columns that are gauges and must not be diffed.
    #[serde(default)]
    pub passthrough: Vec<String>,
    /// Query used by default.
    pub query: String,
    /// Optional version-specific queries: first entry whose `min_pg_version <= server` wins.
    #[serde(default)]
    pub variants: Vec<Variant>,
    #[serde(default)]
    pub description: String,
}
fn default_true() -> bool {
    true
}
fn default_min_version() -> u32 {
    120000
}

#[derive(Debug, Deserialize)]
pub struct Variant {
    #[serde(default)]
    pub min_pg_version: u32,
    /// Only use this variant on Aurora.
    #[serde(default)]
    pub aurora: bool,
    pub query: String,
}

pub struct SqlCollector {
    spec: Spec,
}

impl SqlCollector {
    pub fn from_file(path: &Path) -> Result<Self> {
        let raw = std::fs::read_to_string(path)?;
        Self::from_str(&raw, &path.display().to_string())
    }

    pub fn from_str(raw: &str, origin: &str) -> Result<Self> {
        let mut spec: Spec =
            serde_yaml::from_str(raw).with_context(|| format!("parsing {origin}"))?;
        // Most specific first: Aurora variants before generic, then highest version.
        spec.variants.sort_by(|a, b| {
            b.aurora
                .cmp(&a.aurora)
                .then(b.min_pg_version.cmp(&a.min_pg_version))
        });
        if spec.kind != Kind::Gauge {
            anyhow::ensure!(
                !spec.key.is_empty(),
                "{}: kind {:?} requires `key`",
                spec.name,
                spec.kind
            );
        }
        Ok(Self { spec })
    }

    fn query_for(&self, pg_version: u32, aurora: bool) -> &str {
        self.spec
            .variants
            .iter()
            .find(|v| v.min_pg_version <= pg_version && (!v.aurora || aurora))
            .map(|v| v.query.as_str())
            .unwrap_or(&self.spec.query)
    }
}

#[async_trait]
impl Collector for SqlCollector {
    fn name(&self) -> &str {
        &self.spec.name
    }
    fn description(&self) -> &str {
        self.spec.description.lines().next().unwrap_or("")
    }
    fn interval(&self) -> Duration {
        self.spec.interval
    }
    fn scope(&self) -> Scope {
        self.spec.scope
    }
    fn kind(&self) -> Kind {
        self.spec.kind
    }
    fn min_pg_version(&self) -> u32 {
        self.spec.min_pg_version
    }
    fn prefers_reader(&self) -> bool {
        self.spec.prefers_reader
    }
    fn per_instance(&self) -> bool {
        self.spec
            .per_instance
            .unwrap_or(self.spec.scope == Scope::Cluster)
    }
    fn requires(&self) -> Requirements {
        self.spec.requires.clone()
    }
    fn default_enabled(&self) -> bool {
        self.spec.enabled
    }

    async fn collect(
        &self,
        cx: &CollectCtx<'_>,
        prev: Option<&State>,
    ) -> Result<(Snapshot, State)> {
        let sql = self.query_for(cx.pg_version, cx.caps.aurora);
        let pg_rows = cx
            .conn
            .query(sql, &[])
            .await
            .with_context(|| format!("{}: query failed", self.spec.name))?;
        let rows: Vec<Row> = pg_rows.iter().map(row_to_values).collect::<Result<_>>()?;
        let types = pg_rows.first().map(column_types).unwrap_or_default();

        let interval_seconds = prev
            .and_then(|p| p.collected_at)
            .map(|t| (cx.now - t).num_milliseconds() as f64 / 1000.0)
            .unwrap_or(0.0);

        let (rows, state, events) = match self.spec.kind {
            Kind::Cumulative => {
                compute_deltas_with(rows, &self.spec.key, &self.spec.passthrough, prev, cx.now)
            }
            Kind::Snapshot => {
                let (state, events) =
                    diff_snapshot(&self.spec.name, &rows, &self.spec.key, prev, cx.now);
                (rows, state, events)
            }
            Kind::Gauge => (
                rows,
                State {
                    collected_at: Some(cx.now),
                    ..Default::default()
                },
                vec![],
            ),
        };

        Ok((
            Snapshot {
                collector: self.spec.name.clone(),
                kind: self.spec.kind,
                target: cx.target.clone(),
                collected_at: cx.now,
                interval_seconds,
                key: self.spec.key.clone(),
                types,
                rows,
                events,
                aux: vec![],
            },
            state,
        ))
    }
}

/// DDL type names for the sink, from the result set's column types.
pub fn column_types(r: &tokio_postgres::Row) -> std::collections::BTreeMap<String, String> {
    r.columns()
        .iter()
        .map(|c| {
            let t = match *c.type_() {
                Type::BOOL => "boolean",
                Type::INT2 | Type::INT4 | Type::INT8 | Type::OID => "bigint",
                Type::FLOAT4 | Type::FLOAT8 | Type::NUMERIC => "double precision",
                Type::TIMESTAMPTZ => "timestamptz",
                Type::JSON | Type::JSONB => "jsonb",
                _ => "text",
            };
            (c.name().to_string(), t.to_string())
        })
        .collect()
}

/// Convert a tokio_postgres row into our Value model. Covers the types the stats
/// views actually emit; anything else falls back to text via a cast-free `to_string`.
pub fn row_to_values(r: &tokio_postgres::Row) -> Result<Row> {
    let mut out = Row::new();
    for (i, col) in r.columns().iter().enumerate() {
        let v = match *col.type_() {
            Type::BOOL => r.try_get::<_, Option<bool>>(i)?.map(Value::Bool),
            Type::INT2 => r
                .try_get::<_, Option<i16>>(i)?
                .map(|x| Value::Int(x as i64)),
            Type::INT4 => r
                .try_get::<_, Option<i32>>(i)?
                .map(|x| Value::Int(x as i64)),
            Type::INT8 | Type::OID => match *col.type_() {
                Type::OID => r
                    .try_get::<_, Option<u32>>(i)?
                    .map(|x| Value::Int(x as i64)),
                _ => r.try_get::<_, Option<i64>>(i)?.map(Value::Int),
            },
            Type::FLOAT4 => r
                .try_get::<_, Option<f32>>(i)?
                .map(|x| Value::Float(x as f64)),
            Type::FLOAT8 => r.try_get::<_, Option<f64>>(i)?.map(Value::Float),
            Type::NUMERIC => r
                .try_get::<_, Option<rust_decimal::Decimal>>(i)?
                .map(|d| Value::Float(d.try_into().unwrap_or(f64::NAN))),
            Type::TIMESTAMPTZ => r
                .try_get::<_, Option<DateTime<Utc>>>(i)?
                .map(Value::Timestamp),
            Type::JSON | Type::JSONB => r
                .try_get::<_, Option<serde_json::Value>>(i)?
                .map(Value::Json),
            Type::TEXT | Type::VARCHAR | Type::NAME | Type::BPCHAR | Type::CHAR => {
                r.try_get::<_, Option<String>>(i)?.map(Value::Text)
            }
            ref t => anyhow::bail!(
                "column {} has unsupported type {t}; cast it to text/bigint/float8 in the query",
                col.name()
            ),
        };
        out.insert(col.name().to_string(), v.unwrap_or(Value::Null));
    }
    Ok(out)
}
