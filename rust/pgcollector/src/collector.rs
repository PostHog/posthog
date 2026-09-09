//! Core types shared by every collector and sink.

use anyhow::Result;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Scope {
    /// Run once per server (pg_stat_statements, pg_stat_bgwriter, replication ...)
    Cluster,
    /// Run once per database (pg_stat_user_tables, sizes, schema ...)
    Database,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    /// Rows written as-is per tick.
    Gauge,
    /// Numeric non-key columns diffed against previous tick per key.
    Cumulative,
    /// Full picture of an entity set; upserted into cur_* and diffed into events.
    Snapshot,
}

/// A single cell. Deliberately small: everything Postgres stats views emit fits here.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Text(String),
    Timestamp(DateTime<Utc>),
    Json(serde_json::Value),
}

impl Value {
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Int(i) => Some(*i as f64),
            Value::Float(f) => Some(*f),
            _ => None,
        }
    }
    pub fn is_numeric(&self) -> bool {
        matches!(self, Value::Int(_) | Value::Float(_))
    }
    /// Postgres column type used when the sink auto-creates a column for this value.
    pub fn pg_type(&self) -> &'static str {
        match self {
            Value::Null => "text",
            Value::Bool(_) => "boolean",
            Value::Int(_) => "bigint",
            Value::Float(_) => "double precision",
            Value::Text(_) => "text",
            Value::Timestamp(_) => "timestamptz",
            Value::Json(_) => "jsonb",
        }
    }
}

/// One row: ordered column name → value.
pub type Row = BTreeMap<String, Value>;

/// Identity of where a snapshot came from.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct Target {
    pub server_id: String,
    /// Which instance of the server: "writer", or a name from `[servers.instances]`.
    pub instance: String,
    /// None for cluster-scoped collectors.
    pub datname: Option<String>,
}

/// The unit of output. One per collector per target per tick.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub collector: String,
    pub kind: Kind,
    pub target: Target,
    pub collected_at: DateTime<Utc>,
    /// Seconds since the previous successful tick (what deltas are over). 0 on first tick.
    pub interval_seconds: f64,
    pub key: Vec<String>,
    /// Postgres column types (DDL names) as reported by the result set, so the sink
    /// creates columns with the right type even when the first tick's value is NULL.
    #[serde(default)]
    pub types: BTreeMap<String, String>,
    pub rows: Vec<Row>,
    /// Out-of-band events discovered during collection (stats reset, dealloc, ...).
    pub events: Vec<Event>,
    /// Secondary snapshots produced by the same tick (e.g. newly seen query texts).
    /// Written by the sink after the primary rows.
    #[serde(default)]
    pub aux: Vec<Snapshot>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub kind: String,
    pub subject: String,
    pub before: Option<serde_json::Value>,
    pub after: Option<serde_json::Value>,
}

/// Opaque per-(collector,target) state carried between ticks. Serialisable so it
/// can be persisted on shutdown.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct State {
    pub collected_at: Option<DateTime<Utc>>,
    /// Previous raw rows keyed by the collector's key columns (joined with \x1f).
    pub rows: BTreeMap<String, Row>,
    /// Anything collector-specific.
    pub extra: serde_json::Value,
}

/// What a target server/database offers, probed once per connection.
#[derive(Debug, Clone, Default)]
pub struct Capabilities {
    pub aurora: bool,
    pub aurora_version: Option<String>,
    /// Extensions installed in the connected database.
    pub extensions: std::collections::HashSet<String>,
}

/// What a collector needs from a target before it can run.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Requirements {
    #[serde(default)]
    pub aurora: bool,
    #[serde(default)]
    pub extension: Option<String>,
}

impl Requirements {
    /// None if satisfied, else a human reason.
    pub fn unmet(&self, caps: &Capabilities) -> Option<String> {
        if self.aurora && !caps.aurora {
            return Some("requires Aurora".into());
        }
        if let Some(e) = &self.extension {
            if !caps.extensions.contains(e) {
                return Some(format!("requires extension {e} (CREATE EXTENSION {e})"));
            }
        }
        None
    }
}

pub struct CollectCtx<'a> {
    pub target: Target,
    pub server: &'a crate::config::ServerConfig,
    pub conn: &'a tokio_postgres::Client,
    pub pg_version: u32,
    pub caps: &'a Capabilities,
    pub now: DateTime<Utc>,
}

#[async_trait]
pub trait Collector: Send + Sync {
    fn name(&self) -> &str;
    /// One line for `--check` output and docs.
    fn description(&self) -> &str {
        ""
    }
    /// Collectors that cost more than a catalog read on large clusters ship
    /// disabled and are switched on per server via `overrides.<name>.enabled`.
    fn default_enabled(&self) -> bool {
        true
    }
    fn interval(&self) -> Duration;
    fn scope(&self) -> Scope;
    fn kind(&self) -> Kind;
    /// PG_VERSION_NUM style, e.g. 160000.
    fn min_pg_version(&self) -> u32 {
        120000
    }
    /// Prefer the reader endpoint when one is configured.
    fn prefers_reader(&self) -> bool {
        false
    }
    /// Server-side prerequisites; the scheduler skips (and periodically re-checks)
    /// targets that don't satisfy them.
    fn requires(&self) -> Requirements {
        Requirements::default()
    }
    /// Run against every configured instance (writer + each `[servers.instances]`), not
    /// just the writer. Defaults to true for cluster scope: pg_stat_statements,
    /// pg_stat_activity, bgwriter etc. are per-instance on Aurora replicas.
    fn per_instance(&self) -> bool {
        self.scope() == Scope::Cluster
    }
    async fn collect(&self, cx: &CollectCtx<'_>, prev: Option<&State>)
        -> Result<(Snapshot, State)>;
}

pub fn key_of(row: &Row, key: &[String]) -> String {
    key.iter()
        .map(|k| match row.get(k) {
            Some(Value::Text(s)) => s.clone(),
            Some(v) => serde_json::to_string(v).unwrap_or_default(),
            None => String::new(),
        })
        .collect::<Vec<_>>()
        .join("\u{1f}")
}

/// Shared diff logic for `Kind::Snapshot` collectors: compares the current entity set
/// with the previous tick's and emits `<name>_added` / `<name>_removed` /
/// `<name>_changed` events with the full before/after rows. No events on the first
/// tick (no baseline) — a restart must not look like a schema change.
pub fn diff_snapshot(
    name: &str,
    current: &[Row],
    key: &[String],
    prev: Option<&State>,
    now: DateTime<Utc>,
) -> (State, Vec<Event>) {
    let mut next = State {
        collected_at: Some(now),
        rows: BTreeMap::new(),
        extra: serde_json::Value::Null,
    };
    let mut events = Vec::new();
    for row in current {
        next.rows.insert(key_of(row, key), row.clone());
    }
    if let Some(p) = prev.filter(|p| !p.rows.is_empty() || p.collected_at.is_some()) {
        for (k, row) in &next.rows {
            match p.rows.get(k) {
                None => events.push(Event {
                    kind: format!("{name}_added"),
                    subject: k.replace('\u{1f}', "."),
                    before: None,
                    after: Some(serde_json::to_value(row).unwrap()),
                }),
                Some(old) if old != row => events.push(Event {
                    kind: format!("{name}_changed"),
                    subject: k.replace('\u{1f}', "."),
                    before: Some(serde_json::to_value(changed_cols(old, row, false)).unwrap()),
                    after: Some(serde_json::to_value(changed_cols(old, row, true)).unwrap()),
                }),
                _ => {}
            }
        }
        for (k, old) in &p.rows {
            if !next.rows.contains_key(k) {
                events.push(Event {
                    kind: format!("{name}_removed"),
                    subject: k.replace('\u{1f}', "."),
                    before: Some(serde_json::to_value(old).unwrap()),
                    after: None,
                });
            }
        }
    }
    (next, events)
}

/// Only the columns that differ (plus nothing else) — keeps events readable.
fn changed_cols(old: &Row, new: &Row, take_new: bool) -> Row {
    let src = if take_new { new } else { old };
    old.iter()
        .chain(new.iter())
        .map(|(c, _)| c)
        .filter(|c| old.get(*c) != new.get(*c))
        .filter_map(|c| src.get(c).map(|v| (c.clone(), v.clone())))
        .collect()
}

/// Shared delta logic for `Kind::Cumulative` collectors.
///
/// Rules (see DESIGN.md §4):
/// * row absent in `prev` → baseline, not emitted
/// * `stats_reset` changed → row dropped, re-baselined
/// * any numeric delta < 0 → row dropped, re-baselined
/// * non-numeric columns pass through from the current row
/// * rows whose every counter delta is zero are not emitted (idle entries)
pub fn compute_deltas(
    current: Vec<Row>,
    key: &[String],
    prev: Option<&State>,
    now: DateTime<Utc>,
) -> (Vec<Row>, State, Vec<Event>) {
    compute_deltas_with(current, key, &[], prev, now)
}

/// Like `compute_deltas`, but `passthrough` numeric columns are copied as-is
/// (gauges riding along with counters, e.g. `rss` next to `utime`).
pub fn compute_deltas_with(
    current: Vec<Row>,
    key: &[String],
    passthrough: &[String],
    prev: Option<&State>,
    now: DateTime<Utc>,
) -> (Vec<Row>, State, Vec<Event>) {
    let mut next = State {
        collected_at: Some(now),
        rows: BTreeMap::new(),
        extra: serde_json::Value::Null,
    };
    let mut out = Vec::with_capacity(current.len());
    let mut events = Vec::new();
    for row in current {
        let k = key_of(&row, key);
        if let Some(prev_row) = prev.and_then(|p| p.rows.get(&k)) {
            let reset = matches!((row.get("stats_reset"), prev_row.get("stats_reset")), (Some(a), Some(b)) if a != b);
            if reset {
                events.push(Event {
                    kind: "stats_reset".into(),
                    subject: k.clone(),
                    before: None,
                    after: None,
                });
            } else if let Some(delta) = delta_row(&row, prev_row, key, passthrough) {
                let changed = delta.iter().any(|(c, v)| {
                    !key.iter().any(|k| k == c)
                        && !passthrough.contains(c)
                        && v.as_f64().map(|f| f != 0.0).unwrap_or(false)
                });
                if changed {
                    out.push(delta);
                }
            }
        }
        next.rows.insert(k, row);
    }
    (out, next, events)
}

fn delta_row(cur: &Row, prev: &Row, key: &[String], passthrough: &[String]) -> Option<Row> {
    let mut d = Row::new();
    for (col, v) in cur {
        if key.iter().any(|k| k == col) || passthrough.contains(col) || !v.is_numeric() {
            d.insert(col.clone(), v.clone());
            continue;
        }
        let p = prev.get(col).and_then(Value::as_f64).unwrap_or(0.0);
        let c = v.as_f64().unwrap();
        if c < p {
            return None; // counter went backwards → reset we couldn't see
        }
        d.insert(
            col.clone(),
            match v {
                Value::Int(i) => Value::Int(
                    i - prev
                        .get(col)
                        .and_then(|x| {
                            if let Value::Int(pi) = x {
                                Some(*pi)
                            } else {
                                None
                            }
                        })
                        .unwrap_or(0),
                ),
                _ => Value::Float(c - p),
            },
        );
    }
    Some(d)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(pairs: &[(&str, Value)]) -> Row {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.clone()))
            .collect()
    }

    #[test]
    fn first_tick_is_baseline_only() {
        let rows = vec![row(&[
            ("relname", Value::Text("t".into())),
            ("seq_scan", Value::Int(10)),
        ])];
        let (out, st, _) = compute_deltas(rows, &["relname".into()], None, Utc::now());
        assert!(out.is_empty());
        assert_eq!(st.rows.len(), 1);
    }

    #[test]
    fn snapshot_diff_emits_add_change_remove_but_not_on_first_tick() {
        let key = vec!["name".to_string()];
        let t0 = vec![
            row(&[
                ("name", Value::Text("a".into())),
                ("setting", Value::Text("1".into())),
            ]),
            row(&[
                ("name", Value::Text("b".into())),
                ("setting", Value::Text("1".into())),
            ]),
        ];
        let (st, ev) = diff_snapshot("settings", &t0, &key, None, Utc::now());
        assert!(ev.is_empty());
        let t1 = vec![
            row(&[
                ("name", Value::Text("a".into())),
                ("setting", Value::Text("2".into())),
            ]),
            row(&[
                ("name", Value::Text("c".into())),
                ("setting", Value::Text("1".into())),
            ]),
        ];
        let (_, ev) = diff_snapshot("settings", &t1, &key, Some(&st), Utc::now());
        let kinds: Vec<_> = ev.iter().map(|e| e.kind.as_str()).collect();
        assert!(
            kinds.contains(&"settings_changed")
                && kinds.contains(&"settings_added")
                && kinds.contains(&"settings_removed")
        );
        let ch = ev.iter().find(|e| e.kind == "settings_changed").unwrap();
        assert_eq!(ch.after.as_ref().unwrap()["setting"], "2");
        assert!(ch.after.as_ref().unwrap().get("name").is_none());
    }

    #[test]
    fn unchanged_rows_are_not_emitted() {
        let key = vec!["relname".to_string()];
        let t = vec![row(&[
            ("relname", Value::Text("a".into())),
            ("seq_scan", Value::Int(10)),
        ])];
        let (_, st, _) = compute_deltas(t.clone(), &key, None, Utc::now());
        let (out, _, _) = compute_deltas(t, &key, Some(&st), Utc::now());
        assert!(out.is_empty());
    }

    #[test]
    fn second_tick_emits_delta_and_drops_negative() {
        let key = vec!["relname".to_string()];
        let t0 = vec![
            row(&[
                ("relname", Value::Text("a".into())),
                ("seq_scan", Value::Int(10)),
            ]),
            row(&[
                ("relname", Value::Text("b".into())),
                ("seq_scan", Value::Int(10)),
            ]),
        ];
        let (_, st, _) = compute_deltas(t0, &key, None, Utc::now());
        let t1 = vec![
            row(&[
                ("relname", Value::Text("a".into())),
                ("seq_scan", Value::Int(15)),
            ]),
            row(&[
                ("relname", Value::Text("b".into())),
                ("seq_scan", Value::Int(3)),
            ]), // reset
        ];
        let (out, _, _) = compute_deltas(t1, &key, Some(&st), Utc::now());
        assert_eq!(out.len(), 1);
        assert_eq!(out[0]["seq_scan"], Value::Int(5));
    }
}
