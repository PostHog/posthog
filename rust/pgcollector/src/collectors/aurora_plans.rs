//! `aurora_stat_plans` (APG 14.10+/15.5+, on by default): pg_stat_statements split by
//! plan id, with the plan text. Lets us see plan flips and per-plan cost.

use super::query_stats::aurora_has_peakmem;
use super::statements::{self, Source};
use crate::collector::*;
use anyhow::Result;
use async_trait::async_trait;
use std::time::Duration;

pub struct AuroraPlans;

const KEY: &[&str] = &["queryid", "planid", "datname", "rolname", "toplevel"];

#[async_trait]
impl Collector for AuroraPlans {
    fn name(&self) -> &str {
        "aurora_plans"
    }
    fn interval(&self) -> Duration {
        Duration::from_secs(300)
    }
    fn scope(&self) -> Scope {
        Scope::Cluster
    }
    fn kind(&self) -> Kind {
        Kind::Cumulative
    }
    fn min_pg_version(&self) -> u32 {
        140000
    }
    fn requires(&self) -> Requirements {
        Requirements {
            aurora: true,
            extension: Some("pg_stat_statements".into()),
        }
    }

    async fn collect(
        &self,
        cx: &CollectCtx<'_>,
        prev: Option<&State>,
    ) -> Result<(Snapshot, State)> {
        let extra = statements::load_extra(prev);
        let extra_cols = if aurora_has_peakmem(cx.caps.aurora_version.as_deref(), cx.pg_version) {
            statements::AURORA_COLUMNS
        } else {
            ""
        };
        let cols = statements::pgss_columns(cx.pg_version);
        let src = Source {
            name: "aurora_plans",
            aux_name: "query_plans",
            stats_sql: format!(
                "SELECT s.queryid, s.planid, {cols} {extra_cols}
                        s.plan_type, s.plan_captured_time, s.planid AS _id
                 FROM aurora_stat_plans(false) s JOIN pg_database d ON d.oid = s.dbid LEFT JOIN pg_roles r ON r.oid = s.userid
                 WHERE s.queryid IS NOT NULL AND s.planid IS NOT NULL"
            ),
            key: KEY,
            text_sql: format!(
                "SELECT DISTINCT ON (s.planid, d.datname) s.planid, s.queryid, d.datname,
                        left(s.explain_plan, {n}) AS explain_plan, s.plan_type, s.plan_captured_time
                 FROM aurora_stat_plans(true) s JOIN pg_database d ON d.oid = s.dbid
                 WHERE s.planid = ANY($1) ORDER BY s.planid, d.datname, s.calls DESC",
                n = statements::MAX_TEXT_BYTES * 4
            ),
            text_key: &["planid", "datname"],
        };
        statements::collect(&src, cx, prev, extra, false).await
    }
}
