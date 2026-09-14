//! Findings: the persisted, debounced form of a candidate, and the gauges that alert on it.

use super::rules::Candidate;
use crate::config::Thresholds;
use crate::http::METRICS;
use crate::ownership::{Attribution, Ownership};
use anyhow::Result;
use chrono::{DateTime, Utc};
use deadpool_postgres::Client;
use serde::Serialize;
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize)]
pub struct Finding {
    pub server_id: String,
    pub datname: String,
    pub fingerprint: i64,
    pub queryid: i64,
    pub rule: &'static str,
    pub severity: &'static str,
    pub team: String,
    pub rotation: String,
    pub slack_channel: Option<String>,
    pub method: &'static str,
    pub attribution: serde_json::Value,
    pub stats: serde_json::Value,
}

pub fn build(server: &str, cand: &Candidate, attr: &Attribution, own: &Ownership) -> Finding {
    let mut attribution = serde_json::to_value(attr).unwrap_or_default();
    attribution["reasons"] = serde_json::json!(cand.reasons);
    attribution["rolnames"] = serde_json::json!(cand.rolnames);
    Finding {
        server_id: server.to_string(),
        datname: cand.datname.clone(),
        fingerprint: cand.fingerprint,
        queryid: cand.queryid,
        rule: cand.rule.as_str(),
        severity: "warning",
        team: attr.team.clone(),
        rotation: own.rotation(&attr.team),
        slack_channel: own.slack_channel(&attr.team),
        method: attr.method,
        attribution,
        stats: cand.stats.clone(),
    }
}

/// Write this run's candidates for one server and age out the rest. Returns the
/// findings that reached `open` on this run.
pub async fn apply(
    c: &Client,
    server: &str,
    findings: &[Finding],
    th: &Thresholds,
    now: DateTime<Utc>,
) -> Result<Vec<Finding>> {
    let before: HashMap<i64, String> = c
        .query(
            "SELECT id, status FROM query_findings WHERE server_id = $1 AND status <> 'resolved'",
            &[&server],
        )
        .await?
        .into_iter()
        .map(|r| (r.get::<_, i64>(0), r.get::<_, String>(1)))
        .collect();
    let mut matched_ids: Vec<i64> = Vec::new();
    let mut opened = Vec::new();
    for f in findings {
        let row = c
            .query_one(
                "INSERT INTO query_findings (server_id, datname, fingerprint, queryid, rule, severity, status, team, rotation, slack_channel, method,
                                             attribution, stats, seen_count, miss_count, first_detected, last_detected)
                 VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN 1 >= $14 THEN 'open' ELSE 'pending' END, $7, $8, $9, $10, $11, $12, 1, 0, $13, $13)
                 ON CONFLICT (server_id, datname, fingerprint, rule) DO UPDATE SET
                   seen_count = CASE WHEN query_findings.status = 'resolved' THEN 1 ELSE query_findings.seen_count + 1 END,
                   miss_count = 0,
                   status = CASE WHEN query_findings.status = 'open' THEN 'open'
                                 WHEN (CASE WHEN query_findings.status = 'resolved' THEN 1 ELSE query_findings.seen_count + 1 END) >= $14 THEN 'open'
                                 ELSE 'pending' END,
                   first_detected = CASE WHEN query_findings.status = 'resolved' THEN EXCLUDED.first_detected ELSE query_findings.first_detected END,
                   last_detected = EXCLUDED.last_detected, resolved_at = NULL,
                   queryid = EXCLUDED.queryid, severity = EXCLUDED.severity, team = EXCLUDED.team, rotation = EXCLUDED.rotation,
                   slack_channel = EXCLUDED.slack_channel, method = EXCLUDED.method, attribution = EXCLUDED.attribution, stats = EXCLUDED.stats
                 RETURNING id, status",
                &[
                    &f.server_id, &f.datname, &f.fingerprint, &f.queryid, &f.rule, &f.severity, &f.team, &f.rotation,
                    &f.slack_channel, &f.method, &f.attribution, &f.stats, &now, &th.open_after_runs,
                ],
            )
            .await?;
        let (id, status): (i64, String) = (row.get(0), row.get(1));
        matched_ids.push(id);
        if status == "open" && before.get(&id).map(String::as_str) != Some("open") {
            opened.push(f.clone());
        }
    }
    c.execute(
        "UPDATE query_findings
         SET miss_count = miss_count + 1,
             status = CASE WHEN miss_count + 1 >= $3 THEN 'resolved' ELSE status END,
             resolved_at = CASE WHEN miss_count + 1 >= $3 THEN $4 ELSE resolved_at END
         WHERE server_id = $1 AND status <> 'resolved' AND NOT (id = ANY($2))",
        &[&server, &matched_ids, &th.resolve_after_runs, &now],
    )
    .await?;
    for f in &opened {
        METRICS
            .checks_findings
            .with_label_values(&[f.rule, &f.team])
            .inc();
    }
    Ok(opened)
}

/// Rebuild the `pgcollector_query_finding` gauge from every open finding.
pub async fn export_gauges(c: &Client) -> Result<usize> {
    let rows = c
        .query(
            "SELECT server_id, datname, rule, severity, team, rotation, coalesce(slack_channel, ''), method, queryid, fingerprint
             FROM query_findings WHERE status = 'open'",
            &[],
        )
        .await?;
    METRICS.query_finding.reset();
    for r in &rows {
        let queryid: i64 = r.get(8);
        let fingerprint: i64 = r.get(9);
        METRICS
            .query_finding
            .with_label_values(&[
                r.get::<_, &str>(0),
                r.get::<_, &str>(1),
                r.get::<_, &str>(2),
                r.get::<_, &str>(3),
                r.get::<_, &str>(4),
                r.get::<_, &str>(5),
                r.get::<_, &str>(6),
                r.get::<_, &str>(7),
                &queryid.to_string(),
                &fingerprint.to_string(),
            ])
            .set(1);
    }
    Ok(rows.len())
}
