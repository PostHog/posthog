//! The slow-query checks job. Every `checks.interval` it rolls raw stats into hourly
//! buckets, evaluates the rules over the last window per server, attributes each
//! candidate to a team, and persists the result as a debounced finding. Open findings
//! become `pgcollector_query_finding` gauges when `alerting` is on; the vmalert rule
//! in the charts repo turns those into per-rotation alerts.

pub mod findings;
pub mod rules;
pub mod sql;

use crate::config::{ChecksConfig, SinkConfig};
use crate::http::METRICS;
use crate::ownership::{extract, Ownership, UNOWNED};
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use findings::Finding;
use rules::{Candidate, Rule};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Instant;

pub fn pool(sink: &SinkConfig) -> Result<Pool> {
    let mut pg_cfg: tokio_postgres::Config =
        sink.database_url.parse().context("parsing sink url")?;
    pg_cfg.ssl_mode(crate::pg::tls_policy(&sink.database_url));
    pg_cfg.application_name("pgcollector-checks");
    let mgr = Manager::from_config(
        pg_cfg,
        crate::pg::tls_connector(),
        ManagerConfig {
            recycling_method: RecyclingMethod::Fast,
        },
    );
    Ok(Pool::builder(mgr).max_size(2).build()?)
}

pub async fn run(cfg: Arc<crate::config::Config>) {
    let own = match Ownership::load(&cfg.ownership) {
        Ok(o) => o,
        Err(e) => {
            tracing::error!(error = %format!("{e:#}"), "checks: cannot load ownership; job disabled");
            return;
        }
    };
    let pool = match pool(&cfg.sink) {
        Ok(p) => p,
        Err(e) => {
            tracing::error!(error = %format!("{e:#}"), "checks: cannot build pool; job disabled");
            return;
        }
    };
    tracing::info!(
        tables = own.table_count(),
        alerting = cfg.checks.alerting,
        "checks job started"
    );
    let mut t = tokio::time::interval(cfg.checks.interval);
    loop {
        t.tick().await;
        let started = Instant::now();
        match run_once(&pool, &cfg.checks, &own, Utc::now(), true).await {
            Ok(Some(report)) => tracing::info!(
                candidates = report.candidates.len(),
                opened = report.opened.len(),
                exported = report.exported,
                rollup_hours = report.rollup_hours,
                "checks run"
            ),
            Ok(None) => tracing::debug!("checks: another runner holds the lock"),
            Err(e) => tracing::warn!(error = %format!("{e:#}"), "checks run failed"),
        }
        METRICS
            .checks_run_seconds
            .observe(started.elapsed().as_secs_f64());
    }
}

pub struct Report {
    pub candidates: Vec<(String, Candidate, Finding)>,
    pub opened: Vec<Finding>,
    pub exported: usize,
    pub rollup_hours: i64,
}

/// One evaluation. `persist = false` (the `--checks-once` CLI path) still fills the
/// roll-up, which is idempotent, but neither writes findings nor touches gauges.
pub async fn run_once(
    pool: &Pool,
    cfg: &ChecksConfig,
    own: &Ownership,
    now: DateTime<Utc>,
    persist: bool,
) -> Result<Option<Report>> {
    let c = pool.get().await?;
    if !sql::try_lock(&c).await? {
        return Ok(None);
    }
    let result = evaluate_all(&c, cfg, own, now, persist).await;
    if let Err(e) = sql::unlock(&c).await {
        tracing::warn!(error = %e, "checks: advisory unlock failed; the session will release it");
    }
    result.map(Some)
}

async fn evaluate_all(
    c: &deadpool_postgres::Client,
    cfg: &ChecksConfig,
    own: &Ownership,
    now: DateTime<Utc>,
    persist: bool,
) -> Result<Report> {
    let rollup_hours = sql::fill_rollup(c, now, cfg.baseline_days, &cfg.ignore_roles).await?;
    let mut all = Vec::new();
    let mut opened = Vec::new();
    let window_len = chrono::Duration::from_std(cfg.window)?;
    for server in sql::servers(c).await? {
        let ctx = sql::server_context(c, &server).await?;
        let w = sql::window(c, &server, now - window_len, now, &cfg.ignore_roles).await?;
        let wanted: Vec<i64> = w
            .rows
            .iter()
            .filter(|r| rules::needs_baseline(r, &w, &cfg.thresholds, now))
            .map(|r| r.queryid)
            .collect();
        let baselines = sql::baselines(c, &server, &wanted, now, cfg.baseline_days).await?;
        let cands = rules::evaluate(&w, &baselines, &ctx, &cfg.thresholds, &cfg.mute, now);
        let attributed: Vec<(Candidate, Finding)> = cands
            .into_iter()
            .filter_map(|cand| {
                let ex = extract(&cand.query);
                if ex.catalog_only() {
                    return None;
                }
                let attr = own.attribute(&server, &cand.datname, &ex);
                let f = findings::build(&server, &cand, &attr, own);
                Some((cand, f))
            })
            .collect();
        let collapsed = collapse_bursts(attributed, cfg.thresholds.burst_shapes);
        let fs: Vec<Finding> = collapsed.iter().map(|(_, f)| f.clone()).collect();
        if persist {
            opened.extend(findings::apply(c, &server, &fs, &cfg.thresholds, now).await?);
        }
        all.extend(
            collapsed
                .into_iter()
                .map(|(cand, f)| (server.clone(), cand, f)),
        );
    }
    let exported = if persist && cfg.alerting {
        findings::export_gauges(c).await?
    } else {
        0
    };
    for f in &opened {
        tracing::info!(
            server = f.server_id,
            datname = f.datname,
            rule = f.rule,
            team = f.team,
            rotation = f.rotation,
            method = f.method,
            queryid = f.queryid,
            fingerprint = f.fingerprint,
            "finding opened"
        );
    }
    Ok(Report {
        candidates: all,
        opened,
        exported,
        rollup_hours,
    })
}

/// A deploy that touches one model can produce dozens of new query shapes on one table
/// at once. Above `burst_shapes` new_heavy candidates on the same (team, table), keep
/// one grouped finding instead of one per shape.
pub fn collapse_bursts(
    items: Vec<(Candidate, Finding)>,
    burst_shapes: usize,
) -> Vec<(Candidate, Finding)> {
    let mut groups: BTreeMap<(String, String, String), Vec<usize>> = BTreeMap::new();
    for (i, (cand, f)) in items.iter().enumerate() {
        if cand.rule != Rule::NewHeavy || f.team == UNOWNED {
            continue;
        }
        let table = f.attribution["primary_table"]
            .as_str()
            .unwrap_or_default()
            .to_string();
        if table.is_empty() {
            continue;
        }
        groups
            .entry((f.datname.clone(), f.team.clone(), table))
            .or_default()
            .push(i);
    }
    let mut drop = vec![false; items.len()];
    let mut merged = Vec::new();
    for ((datname, team, table), idx) in groups {
        if idx.len() <= burst_shapes {
            continue;
        }
        let total_ms: f64 = idx.iter().map(|&i| items[i].cand_total_ms()).sum();
        let share: f64 = idx.iter().map(|&i| items[i].cand_share()).sum();
        let top = idx
            .iter()
            .copied()
            .max_by(|&a, &b| {
                items[a]
                    .cand_total_ms()
                    .total_cmp(&items[b].cand_total_ms())
            })
            .unwrap();
        for &i in &idx {
            drop[i] = true;
        }
        let (cand, f) = &items[top];
        let mut c = cand.clone();
        c.rule = Rule::NewHeavyBurst;
        c.fingerprint = crate::logs::fingerprint::fingerprint(&format!("burst:{datname}:{table}"));
        c.query = format!(
            "{} new query shapes on {table}; heaviest: {}",
            idx.len(),
            cand.query
        );
        c.reasons = vec![format!(
            "{} new query shapes on {table} in one window, {total_ms:.0} ms total ({share:.1}% of server time); likely one deploy",
            idx.len()
        )];
        c.stats = serde_json::json!({ "shapes": idx.len(), "total_ms": total_ms, "share_pct": share, "heaviest": cand.stats });
        let mut nf = f.clone();
        nf.rule = c.rule.as_str();
        nf.fingerprint = c.fingerprint;
        nf.stats = c.stats.clone();
        nf.attribution["reasons"] = serde_json::json!(c.reasons);
        nf.team = team;
        merged.push((c, nf));
    }
    let mut out: Vec<(Candidate, Finding)> = items
        .into_iter()
        .enumerate()
        .filter(|(i, _)| !drop[*i])
        .map(|(_, x)| x)
        .collect();
    out.extend(merged);
    out
}

trait CandStats {
    fn cand_total_ms(&self) -> f64;
    fn cand_share(&self) -> f64;
}
impl CandStats for (Candidate, Finding) {
    fn cand_total_ms(&self) -> f64 {
        self.0.stats["total_ms"].as_f64().unwrap_or(0.0)
    }
    fn cand_share(&self) -> f64 {
        self.0.stats["share_pct"].as_f64().unwrap_or(0.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(queryid: i64, table: &str, total_ms: f64) -> (Candidate, Finding) {
        let cand = Candidate {
            rule: Rule::NewHeavy,
            datname: "posthog".into(),
            queryid,
            fingerprint: queryid,
            query: format!("SELECT {queryid} FROM {table}"),
            rolnames: vec![],
            stats: serde_json::json!({ "total_ms": total_ms, "share_pct": 1.0 }),
            reasons: vec!["x".into()],
        };
        let f = Finding {
            server_id: "cloud".into(),
            datname: "posthog".into(),
            fingerprint: queryid,
            queryid,
            rule: "new_heavy",
            severity: "warning",
            team: "team-a".into(),
            rotation: "a".into(),
            slack_channel: None,
            method: "table",
            attribution: serde_json::json!({ "primary_table": table }),
            stats: cand.stats.clone(),
        };
        (cand, f)
    }

    #[test]
    fn many_new_shapes_on_one_table_become_one_burst_finding() {
        let mut items: Vec<_> = (1..=4).map(|i| item(i, "posthog_a", i as f64)).collect();
        items.push(item(9, "posthog_b", 1.0));
        let out = collapse_bursts(items.clone(), 3);
        assert_eq!(out.len(), 2);
        let burst = out
            .iter()
            .find(|(c, _)| c.rule == Rule::NewHeavyBurst)
            .unwrap();
        assert_eq!(burst.0.queryid, 4);
        assert_eq!(burst.1.rule, "new_heavy_burst");
        assert_eq!(burst.0.stats["shapes"], 4);
        assert_eq!(burst.0.stats["total_ms"], 10.0);
        assert!(out
            .iter()
            .any(|(c, _)| c.queryid == 9 && c.rule == Rule::NewHeavy));
        assert_eq!(collapse_bursts(items, 4).len(), 5);
    }
}
