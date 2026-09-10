//! `pg_stat_statements` deltas (Tier B). On Aurora, reads `aurora_stat_statements`
//! instead, which adds Aurora-storage I/O and per-query peak memory columns.
//!
//! What this cannot give you: per-call latency quantiles. pg_stat_statements has no
//! histogram; real p95/p99 come from sampled statement logs (phase 4,
//! `ts_query_durations`) keyed by the same `queryid`.

use super::statements::{self, Source};
use crate::collector::*;
use anyhow::Result;
use async_trait::async_trait;
use std::time::Duration;

pub struct QueryStats;

const KEY: &[&str] = &["queryid", "datname", "rolname", "toplevel"];

#[async_trait]
impl Collector for QueryStats {
    fn name(&self) -> &str {
        "query_stats"
    }
    fn interval(&self) -> Duration {
        Duration::from_secs(60)
    }
    fn scope(&self) -> Scope {
        Scope::Cluster
    }
    fn kind(&self) -> Kind {
        Kind::Cumulative
    }
    fn min_pg_version(&self) -> u32 {
        130000
    }

    async fn collect(
        &self,
        cx: &CollectCtx<'_>,
        prev: Option<&State>,
    ) -> Result<(Snapshot, State)> {
        let mut extra = statements::load_extra(prev);
        if !statements::pgss_installed(cx).await {
            if !extra.warned_missing {
                tracing::warn!(server = cx.target.server_id, instance = cx.target.instance,
                    "pg_stat_statements is not installed in the maintenance database; run CREATE EXTENSION pg_stat_statements there");
                extra.warned_missing = true;
            }
            return Ok(statements::empty(
                self.name(),
                KEY,
                cx,
                &extra,
                Default::default(),
            ));
        }
        extra.warned_missing = false;

        // aurora_stat_statements exists from APG 14.9 / 15.4; peakmem columns from 14.12 / 15.7 / 16.3.
        // We only use the Aurora function when the peakmem columns exist, to keep one SQL shape.
        let aurora =
            cx.caps.aurora && aurora_has_peakmem(cx.caps.aurora_version.as_deref(), cx.pg_version);
        let (func, extra_cols) = if aurora {
            ("aurora_stat_statements(false)", statements::AURORA_COLUMNS)
        } else {
            ("pg_stat_statements(false)", "")
        };
        let cols = statements::pgss_columns(cx.pg_version);
        let src = Source {
            name: "query_stats",
            aux_name: "queries",
            stats_sql: format!(
                "SELECT s.queryid, {cols} {extra_cols} s.queryid AS _id
                 FROM {func} s JOIN pg_database d ON d.oid = s.dbid LEFT JOIN pg_roles r ON r.oid = s.userid
                 WHERE s.queryid IS NOT NULL"
            ),
            key: KEY,
            text_sql: format!(
                "SELECT DISTINCT ON (s.queryid, d.datname) s.queryid, d.datname,
                        left(s.query, {n}) AS query, length(s.query) > {n} AS truncated
                 FROM pg_stat_statements(true) s JOIN pg_database d ON d.oid = s.dbid
                 WHERE s.queryid = ANY($1) ORDER BY s.queryid, d.datname, s.calls DESC",
                n = statements::MAX_TEXT_BYTES
            ),
            text_key: &["queryid", "datname"],
        };
        statements::collect(&src, cx, prev, extra, true).await
    }
}

/// aurora_version() looks like "16.3.0" / "15.7.1"; peakmem columns landed in 14.12 / 15.7 / 16.3.
pub fn aurora_has_peakmem(aurora_version: Option<&str>, pg_version: u32) -> bool {
    let Some(v) = aurora_version else {
        return false;
    };
    let mut it = v.split('.').filter_map(|p| p.parse::<u32>().ok());
    let (major, minor) = (it.next().unwrap_or(0), it.next().unwrap_or(0));
    match major {
        14 => minor >= 12,
        15 => minor >= 7,
        16 => minor >= 3,
        m if m >= 17 => true,
        _ => pg_version >= 170000,
    }
}
