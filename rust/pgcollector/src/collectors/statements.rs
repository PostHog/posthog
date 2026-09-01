//! Shared machinery for pg_stat_statements-shaped sources: `pg_stat_statements`,
//! `aurora_stat_statements`, `aurora_stat_plans`. Deltas the counters, tracks which
//! ids have had their text fetched, and emits the text as an aux snapshot.

use crate::collector::*;
use crate::collectors::declarative::{column_types, row_to_values};
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
    prev.map(|p| serde_json::from_value(p.extra.clone()).unwrap_or_default())
        .unwrap_or_default()
}

pub async fn pgss_installed(cx: &CollectCtx<'_>) -> bool {
    cx.caps.extensions.contains("pg_stat_statements")
}

/// Column list shared by pg_stat_statements and its Aurora superset, version-gated.
pub fn pgss_columns(v: u32) -> String {
    let toplevel = if v >= 140000 {
        "s.toplevel"
    } else {
        "true AS toplevel"
    };
    let io_time = if v >= 170000 {
        "s.shared_blk_read_time AS blk_read_time, s.shared_blk_write_time AS blk_write_time"
    } else {
        "s.blk_read_time, s.blk_write_time"
    };
    let temp_io = if v >= 150000 {
        "s.temp_blk_read_time, s.temp_blk_write_time,"
    } else {
        ""
    };
    let jit = if v >= 150000 {
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
