//! Shared machinery for pg_stat_statements-shaped sources: `pg_stat_statements`,
//! `aurora_stat_statements`, `aurora_stat_plans`. Deltas the counters, tracks which
//! ids have had their text fetched, and emits the text as an aux snapshot.

use crate::collector::*;
use crate::collectors::declarative::{column_types, row_to_values};
use crate::logs::fingerprint::FINGERPRINT_VERSION;
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const MAX_TEXT_BYTES: usize = 10 * 1024;
const MAX_KNOWN: usize = 50_000;
/// Query texts fetched per tick. `pg_stat_statements(true)` materialises every
/// entry's text server-side, so keep the per-tick call count low and spread the
/// initial backfill over a few ticks.
const TEXT_BATCH: usize = 500;

#[derive(Default, Serialize, Deserialize)]
pub struct Extra {
    /// Ids (queryid, or planid for plans) whose text is already in the sink.
    pub known_ids: BTreeSet<i64>,
    pub dealloc: Option<i64>,
    pub warned_missing: bool,
    #[serde(default)]
    pub warned_stale: bool,
    /// `FINGERPRINT_VERSION` the known ids were fingerprinted with.
    #[serde(default)]
    pub fingerprint_version: u32,
}

pub struct Source<'a> {
    pub name: &'a str,
    pub aux_name: &'a str,
    /// Counter query; must emit a hidden `_id` column carrying the text id.
    pub stats_sql: String,
    pub key: &'a [&'a str],
    /// Text query taking `$1 bigint[]` of ids.
    pub text_sql: String,
    pub text_key: &'a [&'a str],
}

pub fn empty(
    name: &str,
    key: &[&str],
    cx: &CollectCtx<'_>,
    extra: &Extra,
    prev_rows: std::collections::BTreeMap<String, Row>,
) -> (Snapshot, State) {
    (
        Snapshot {
            collector: name.into(),
            kind: Kind::Cumulative,
            target: cx.target.clone(),
            collected_at: cx.now,
            interval_seconds: 0.0,
            key: key.iter().map(|s| s.to_string()).collect(),
            types: Default::default(),
            rows: vec![],
            events: vec![],
            aux: vec![],
        },
        State {
            collected_at: Some(cx.now),
            rows: prev_rows,
            extra: serde_json::to_value(extra).unwrap(),
        },
    )
}

pub async fn collect(
    src: &Source<'_>,
    cx: &CollectCtx<'_>,
    prev: Option<&State>,
    mut extra: Extra,
    watch_dealloc: bool,
) -> Result<(Snapshot, State)> {
    let pg_rows = cx
        .conn
        .query(&src.stats_sql, &[])
        .await
        .with_context(|| src.name.to_string())?;
    let rows: Vec<Row> = pg_rows.iter().map(row_to_values).collect::<Result<_>>()?;
    let mut types = pg_rows.first().map(column_types).unwrap_or_default();
    types.remove("_id");
    let key: Vec<String> = src.key.iter().map(|s| s.to_string()).collect();
    let interval_seconds = prev
        .and_then(|p| p.collected_at)
        .map(|t| (cx.now - t).num_milliseconds() as f64 / 1000.0)
        .unwrap_or(0.0);
    let (mut deltas, mut state, mut events) = compute_deltas(rows, &key, prev, cx.now);
    for d in &mut deltas {
        d.remove("_id");
    }

    if watch_dealloc && cx.pg_version >= 140000 {
        if let Some(r) = cx
            .conn
            .query_opt("SELECT dealloc FROM pg_stat_statements_info", &[])
            .await?
        {
            let dealloc: i64 = r.get(0);
            if let Some(prev_d) = extra.dealloc {
                if dealloc > prev_d {
                    events.push(Event {
                        kind: "pgss_dealloc".into(), subject: cx.target.instance.clone(),
                        before: Some(serde_json::json!({ "dealloc": prev_d })),
                        after: Some(serde_json::json!({ "dealloc": dealloc, "hint": "pg_stat_statements.max is too small for this workload; top-N is lossy" })),
                    });
                }
            }
            extra.dealloc = Some(dealloc);
        }
    }

    let mut unseen: Vec<i64> = state
        .rows
        .values()
        .filter_map(|r| {
            if let Some(Value::Int(q)) = r.get("_id") {
                Some(*q)
            } else {
                None
            }
        })
        .filter(|q| !extra.known_ids.contains(q))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let mut aux = Vec::new();
    if !unseen.is_empty() {
        unseen.truncate(TEXT_BATCH);
        let texts = cx
            .conn
            .query(&src.text_sql, &[&unseen])
            .await
            .with_context(|| format!("{} text", src.name))?;
        let mut text_rows: Vec<Row> = texts.iter().map(row_to_values).collect::<Result<_>>()?;
        let mut text_types = texts.first().map(column_types).unwrap_or_default();
        // Fingerprint the normalised text so log-derived rows (durations, plans, errors)
        // can be joined to cur_queries even without %Q in log_line_prefix.
        for r in &mut text_rows {
            if let Some(Value::Text(q)) = r.get("query") {
                let fp = crate::logs::fingerprint::fingerprint(q);
                r.insert("fingerprint".into(), Value::Int(fp));
            }
        }
        text_types.insert("fingerprint".into(), "bigint".into());
        extra.known_ids.extend(unseen);
        if extra.known_ids.len() > MAX_KNOWN {
            extra.known_ids = extra
                .known_ids
                .iter()
                .rev()
                .take(MAX_KNOWN / 2)
                .copied()
                .collect();
        }
        aux.push(Snapshot {
            collector: src.aux_name.into(),
            kind: Kind::Snapshot,
            target: cx.target.clone(),
            collected_at: cx.now,
            interval_seconds: 0.0,
            key: src.text_key.iter().map(|s| s.to_string()).collect(),
            types: text_types,
            rows: text_rows,
            events: vec![],
            aux: vec![],
        });
    }

    state.extra = serde_json::to_value(&extra)?;
    Ok((
        Snapshot {
            collector: src.name.into(),
            kind: Kind::Cumulative,
            target: cx.target.clone(),
            collected_at: cx.now,
            interval_seconds,
            key,
            types,
            rows: deltas,
            events,
            aux,
        },
        state,
    ))
}

pub fn load_extra(prev: Option<&State>) -> Extra {
    let mut extra: Extra = prev
        .map(|p| serde_json::from_value(p.extra.clone()).unwrap_or_default())
        .unwrap_or_default();
    // A normaliser change makes every stored fingerprint stale; forgetting the ids
    // makes the next ticks re-fetch their text and upsert fresh fingerprints.
    if extra.fingerprint_version != FINGERPRINT_VERSION {
        extra.known_ids.clear();
        extra.fingerprint_version = FINGERPRINT_VERSION;
    }
    extra
}

pub async fn pgss_installed(cx: &CollectCtx<'_>) -> bool {
    cx.caps.extensions.contains_key("pg_stat_statements")
}

pub fn bundled_pgss_version(pg_version: u32) -> (u32, u32) {
    match pg_version / 10000 {
        ..=13 => (1, 8),
        14 => (1, 9),
        15 | 16 => (1, 10),
        17 => (1, 11),
        _ => (1, 12),
    }
}

/// Oldest extension `pgss_columns` can select from: 1.8 split exec and plan time and added `wal_*`.
pub const MIN_PGSS_VERSION: (u32, u32) = (1, 8);

/// Warns once per state and returns the `pgss_stale` event when the installed extension is
/// behind the server's bundled one.
pub fn stale_report(cx: &CollectCtx<'_>, extra: &mut Extra) -> Option<Event> {
    let ext = pgss_version(cx);
    let bundled = bundled_pgss_version(cx.pg_version);
    let stale = ext < bundled;
    let first_report = stale && !extra.warned_stale;
    extra.warned_stale = stale;
    if !first_report {
        return None;
    }
    let installed = format!("{}.{}", ext.0, ext.1);
    let bundled = format!("{}.{}", bundled.0, bundled.1);
    tracing::warn!(server = cx.target.server_id, instance = cx.target.instance, installed, bundled,
        "pg_stat_statements is behind the server's bundled version; run ALTER EXTENSION pg_stat_statements UPDATE in the maintenance database");
    Some(Event {
        kind: "pgss_stale".into(),
        subject: cx.target.instance.clone(),
        before: Some(serde_json::json!({ "extversion": installed })),
        after: Some(
            serde_json::json!({ "extversion": bundled, "hint": "run ALTER EXTENSION pg_stat_statements UPDATE in the maintenance database; newer columns are skipped until then" }),
        ),
    })
}

/// Falls back to the server's bundled version when the probe could not read `extversion`.
pub fn pgss_version(cx: &CollectCtx<'_>) -> (u32, u32) {
    cx.caps
        .pgss_version()
        .unwrap_or_else(|| bundled_pgss_version(cx.pg_version))
}

/// The view's columns follow the installed extension version, not the server version.
/// A cluster upgraded in place keeps its old `pg_stat_statements` definition until
/// `ALTER EXTENSION pg_stat_statements UPDATE` runs, so a PG15 server can still expose
/// the 1.8 column set.
pub fn pgss_columns(ext: (u32, u32)) -> String {
    let toplevel = if ext >= (1, 9) {
        "s.toplevel"
    } else {
        "true AS toplevel"
    };
    let io_time = if ext >= (1, 11) {
        "s.shared_blk_read_time AS blk_read_time, s.shared_blk_write_time AS blk_write_time"
    } else {
        "s.blk_read_time, s.blk_write_time"
    };
    let temp_io = if ext >= (1, 10) {
        "s.temp_blk_read_time, s.temp_blk_write_time,"
    } else {
        ""
    };
    let jit = if ext >= (1, 10) {
        "s.jit_functions, s.jit_generation_time,"
    } else {
        ""
    };
    format!(
        "d.datname, COALESCE(r.rolname, s.userid::text) AS rolname, {toplevel},
         s.calls, s.total_exec_time, s.rows,
         s.calls * (s.stddev_exec_time * s.stddev_exec_time + s.mean_exec_time * s.mean_exec_time) AS sumsq_exec_time,
         s.plans, s.total_plan_time,
         s.shared_blks_hit, s.shared_blks_read, s.shared_blks_dirtied, s.shared_blks_written,
         s.local_blks_hit, s.local_blks_read, s.local_blks_dirtied, s.local_blks_written,
         s.temp_blks_read, s.temp_blks_written, {temp_io}
         {io_time},
         s.wal_records, s.wal_fpi, s.wal_bytes::bigint AS wal_bytes, {jit}"
    )
}

/// Extra columns from aurora_stat_statements / aurora_stat_plans (APG 14.9+/15.4+; peakmem 14.12+/15.7+/16.3+).
pub const AURORA_COLUMNS: &str = "
         s.storage_blks_read, s.storage_blk_read_time, s.orcache_blks_hit, s.orcache_blk_read_time,
         s.total_exec_peakmem, s.max_exec_peakmem, s.total_plan_peakmem, s.max_plan_peakmem,";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pgss_columns_follow_the_extension_version_not_the_server() {
        type Case = ((u32, u32), &'static [&'static str], &'static [&'static str]);
        let cases: &[Case] = &[
            (
                (1, 8),
                &["true AS toplevel", "s.blk_read_time"],
                &["s.toplevel", "s.jit_functions", "s.temp_blk_read_time"],
            ),
            (
                (1, 9),
                &["s.toplevel", "s.blk_read_time"],
                &["s.jit_functions", "s.temp_blk_read_time"],
            ),
            (
                (1, 10),
                &[
                    "s.toplevel",
                    "s.jit_functions",
                    "s.temp_blk_read_time",
                    "s.blk_read_time",
                ],
                &["s.shared_blk_read_time"],
            ),
            (
                (1, 11),
                &["s.toplevel", "s.jit_functions", "s.shared_blk_read_time"],
                &["s.blk_read_time,"],
            ),
        ];
        for (ext, present, absent) in cases {
            let cols = pgss_columns(*ext);
            for p in *present {
                assert!(cols.contains(p), "{ext:?} should select {p}");
            }
            for a in *absent {
                assert!(!cols.contains(a), "{ext:?} should not select {a}");
            }
        }
    }

    #[test]
    fn extversion_minor_compares_numerically() {
        let mut caps = Capabilities::default();
        caps.extensions
            .insert("pg_stat_statements".into(), "1.10".into());
        assert_eq!(caps.pgss_version(), Some((1, 10)));
        assert!(caps.pgss_version() > Some((1, 9)));
        caps.extensions
            .insert("pg_stat_statements".into(), "".into());
        assert_eq!(caps.pgss_version(), None);
    }
}
