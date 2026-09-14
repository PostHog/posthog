//! The rules, as pure functions over aggregates the SQL layer returns.

use crate::config::Thresholds;
use chrono::{DateTime, Utc};
use once_cell::sync::Lazy;
use regex::Regex;
use serde::Serialize;
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct WindowRow {
    pub datname: String,
    pub queryid: i64,
    pub calls: i64,
    pub total_ms: f64,
    pub rows: i64,
    pub shared_blks_read: i64,
    pub temp_blks_written: i64,
    pub rolnames: Vec<String>,
    pub query: Option<String>,
    pub fingerprint: Option<i64>,
    pub first_seen: Option<DateTime<Utc>>,
}

impl WindowRow {
    pub fn mean_ms(&self) -> f64 {
        if self.calls > 0 {
            self.total_ms / self.calls as f64
        } else {
            0.0
        }
    }
}

#[derive(Debug, Clone)]
pub struct Window {
    pub rows: Vec<WindowRow>,
    pub server_total_ms: f64,
    /// Distinct sample timestamps in the window: how much data the aggregates rest on.
    pub samples: i64,
    pub from: DateTime<Utc>,
    pub to: DateTime<Utc>,
}

impl Window {
    pub fn share_pct(&self, total_ms: f64) -> f64 {
        if self.server_total_ms > 0.0 {
            total_ms / self.server_total_ms * 100.0
        } else {
            0.0
        }
    }
}

/// One baseline hour for one query: the same hour-of-day on an earlier day.
#[derive(Debug, Clone, Copy)]
pub struct BaselinePoint {
    pub mean_ms: f64,
    pub share_pct: f64,
}

pub type Baselines = HashMap<(String, i64), Vec<BaselinePoint>>;

#[derive(Debug, Clone, Default)]
pub struct ServerContext {
    pub first_seen: Option<DateTime<Utc>>,
    pub stats_reset_recent: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Rule {
    NewHeavy,
    NewHeavyBurst,
    Regression,
}

impl Rule {
    pub fn as_str(self) -> &'static str {
        match self {
            Rule::NewHeavy => "new_heavy",
            Rule::NewHeavyBurst => "new_heavy_burst",
            Rule::Regression => "regression",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Candidate {
    pub rule: Rule,
    pub datname: String,
    pub queryid: i64,
    pub fingerprint: i64,
    pub query: String,
    pub rolnames: Vec<String>,
    pub stats: serde_json::Value,
    pub reasons: Vec<String>,
}

static UTILITY: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:/\*.*?\*/\s*)*(?:BEGIN|COMMIT|ROLLBACK|SET|SHOW|SAVEPOINT|RELEASE|DEALLOCATE|DISCARD|LISTEN|COPY|VACUUM|ANALYZE|CREATE|ALTER|DROP|REINDEX|CLUSTER|REFRESH|EXPLAIN|LOCK|FETCH|DECLARE|CLOSE)\b").unwrap()
});

pub fn is_utility(sql: &str) -> bool {
    UTILITY.is_match(sql)
}

/// Whether a row is worth fetching a 7-day baseline for.
pub fn needs_baseline(row: &WindowRow, w: &Window, th: &Thresholds, now: DateTime<Utc>) -> bool {
    let old_enough = row
        .first_seen
        .is_some_and(|f| now - f >= chrono::Duration::days(th.baseline_days_floor()));
    old_enough
        && ((row.mean_ms() >= th.regression_min_mean_ms && row.calls >= th.regression_min_calls)
            || w.share_pct(row.total_ms) >= th.regression_share_pct)
}

impl Thresholds {
    fn baseline_days_floor(&self) -> i64 {
        self.baseline_min_days as i64
    }
}

pub fn evaluate(
    w: &Window,
    baselines: &Baselines,
    ctx: &ServerContext,
    th: &Thresholds,
    mute: &[i64],
    now: DateTime<Utc>,
) -> Vec<Candidate> {
    let mut out = Vec::new();
    if w.samples < th.min_samples {
        return out;
    }
    let warming_up = ctx.stats_reset_recent
        || ctx
            .first_seen
            .is_some_and(|f| now - f < chrono::Duration::from_std(th.warmup).unwrap_or_default());
    for row in &w.rows {
        let (Some(query), Some(fp)) = (&row.query, row.fingerprint) else {
            continue;
        };
        if mute.contains(&fp) || is_utility(query) {
            continue;
        }
        let share = w.share_pct(row.total_ms);
        let mean = row.mean_ms();
        let is_new = row.first_seen.is_some_and(|f| {
            now - f < chrono::Duration::from_std(th.new_query_age).unwrap_or_default()
        });
        if is_new && !warming_up {
            let mut reasons = Vec::new();
            if share >= th.share_pct {
                reasons.push(format!(
                    "{share:.1}% of server exec time (floor {}%)",
                    th.share_pct
                ));
            }
            if row.total_ms >= th.total_ms {
                reasons.push(format!(
                    "{:.0} ms total in the window (floor {:.0})",
                    row.total_ms, th.total_ms
                ));
            }
            if mean >= th.mean_ms && row.calls >= th.mean_min_calls {
                reasons.push(format!(
                    "mean {mean:.0} ms over {} calls (floor {:.0} ms)",
                    row.calls, th.mean_ms
                ));
            }
            if row.shared_blks_read >= th.shared_blks_read {
                reasons.push(format!(
                    "{} shared blocks read (floor {})",
                    row.shared_blks_read, th.shared_blks_read
                ));
            }
            if row.temp_blks_written >= th.temp_blks_written {
                reasons.push(format!(
                    "{} temp blocks written (floor {})",
                    row.temp_blks_written, th.temp_blks_written
                ));
            }
            if !reasons.is_empty() {
                out.push(Candidate {
                    rule: Rule::NewHeavy,
                    datname: row.datname.clone(),
                    queryid: row.queryid,
                    fingerprint: fp,
                    query: query.clone(),
                    rolnames: row.rolnames.clone(),
                    stats: stats_json(row, w, share, mean, None),
                    reasons,
                });
                continue;
            }
        }
        if let Some(points) = baselines.get(&(row.datname.clone(), row.queryid)) {
            if let Some((reasons, base)) = regression(row, share, mean, points, th) {
                out.push(Candidate {
                    rule: Rule::Regression,
                    datname: row.datname.clone(),
                    queryid: row.queryid,
                    fingerprint: fp,
                    query: query.clone(),
                    rolnames: row.rolnames.clone(),
                    stats: stats_json(row, w, share, mean, Some(base)),
                    reasons,
                });
            }
        }
    }
    out
}

fn regression(
    row: &WindowRow,
    share: f64,
    mean: f64,
    points: &[BaselinePoint],
    th: &Thresholds,
) -> Option<(Vec<String>, serde_json::Value)> {
    if points.len() < th.baseline_min_days {
        return None;
    }
    let mut means: Vec<f64> = points.iter().map(|p| p.mean_ms).collect();
    let mut shares: Vec<f64> = points.iter().map(|p| p.share_pct).collect();
    let (mean_med, mean_p95) = (median(&mut means), p95(&mut means));
    let (share_med, share_p95) = (median(&mut shares), p95(&mut shares));
    let mut reasons = Vec::new();
    let mean_floor = (th.regression_multiple * mean_med).max(th.regression_p95_multiple * mean_p95);
    if mean >= th.regression_min_mean_ms
        && row.calls >= th.regression_min_calls
        && mean > mean_floor
    {
        reasons.push(format!(
            "mean {mean:.0} ms vs {mean_med:.0} ms median / {mean_p95:.0} ms p95 at this hour over {} days",
            points.len()
        ));
    }
    let share_floor =
        (th.regression_multiple * share_med).max(th.regression_p95_multiple * share_p95);
    if share >= th.regression_share_pct && share > share_floor {
        reasons.push(format!(
            "{share:.1}% of server time vs {share_med:.1}% median / {share_p95:.1}% p95 at this hour over {} days",
            points.len()
        ));
    }
    if reasons.is_empty() {
        return None;
    }
    Some((
        reasons,
        serde_json::json!({ "days": points.len(), "mean_ms_median": mean_med, "mean_ms_p95": mean_p95, "share_pct_median": share_med, "share_pct_p95": share_p95 }),
    ))
}

fn stats_json(
    row: &WindowRow,
    w: &Window,
    share: f64,
    mean: f64,
    baseline: Option<serde_json::Value>,
) -> serde_json::Value {
    serde_json::json!({
        "window_from": w.from, "window_to": w.to, "samples": w.samples,
        "calls": row.calls, "total_ms": row.total_ms, "mean_ms": mean, "share_pct": share,
        "rows": row.rows, "shared_blks_read": row.shared_blks_read, "temp_blks_written": row.temp_blks_written,
        "first_seen": row.first_seen, "rolnames": row.rolnames, "baseline": baseline,
    })
}

fn median(v: &mut [f64]) -> f64 {
    v.sort_by(|a, b| a.total_cmp(b));
    let n = v.len();
    if n == 0 {
        0.0
    } else if n % 2 == 1 {
        v[n / 2]
    } else {
        (v[n / 2 - 1] + v[n / 2]) / 2.0
    }
}

fn p95(v: &mut [f64]) -> f64 {
    v.sort_by(|a, b| a.total_cmp(b));
    if v.is_empty() {
        return 0.0;
    }
    let idx = ((v.len() as f64 * 0.95).ceil() as usize).clamp(1, v.len()) - 1;
    v[idx]
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Duration;

    fn now() -> DateTime<Utc> {
        "2026-09-03T12:00:00Z".parse().unwrap()
    }

    fn row(queryid: i64, calls: i64, total_ms: f64, age: Duration) -> WindowRow {
        WindowRow {
            datname: "posthog".into(),
            queryid,
            calls,
            total_ms,
            rows: 0,
            shared_blks_read: 0,
            temp_blks_written: 0,
            rolnames: vec!["posthog".into()],
            query: Some(format!("SELECT {queryid} FROM posthog_dashboard")),
            fingerprint: Some(queryid * 10),
            first_seen: Some(now() - age),
        }
    }

    fn window(rows: Vec<WindowRow>) -> Window {
        Window {
            rows,
            server_total_ms: 1_000_000.0,
            samples: 60,
            from: now() - Duration::hours(1),
            to: now(),
        }
    }

    fn th() -> Thresholds {
        Thresholds::default()
    }

    #[test]
    fn new_heavy_fires_on_any_floor_and_names_the_reason() {
        let w = window(vec![
            row(1, 1000, 30_000.0, Duration::hours(2)),
            row(2, 5, 4_000.0, Duration::hours(2)),
            row(3, 20, 12_000.0, Duration::hours(2)),
            row(4, 1000, 30_000.0, Duration::days(3)),
        ]);
        let c = evaluate(
            &w,
            &Baselines::new(),
            &ServerContext::default(),
            &th(),
            &[],
            now(),
        );
        let ids: Vec<i64> = c.iter().map(|c| c.queryid).collect();
        assert_eq!(ids, vec![1, 3]);
        assert!(c[0].reasons[0].contains("3.0% of server exec time"));
        assert!(c[1].reasons[0].contains("mean 600 ms over 20 calls"));
        assert_eq!(c[0].rule, Rule::NewHeavy);
    }

    #[test]
    fn new_heavy_is_suppressed_while_the_server_warms_up_or_with_little_data() {
        let mut w = window(vec![row(1, 1000, 30_000.0, Duration::hours(2))]);
        let ctx = ServerContext {
            first_seen: Some(now() - Duration::hours(3)),
            stats_reset_recent: false,
        };
        assert!(evaluate(&w, &Baselines::new(), &ctx, &th(), &[], now()).is_empty());
        let ctx = ServerContext {
            first_seen: Some(now() - Duration::days(30)),
            stats_reset_recent: true,
        };
        assert!(evaluate(&w, &Baselines::new(), &ctx, &th(), &[], now()).is_empty());
        w.samples = 5;
        assert!(evaluate(
            &w,
            &Baselines::new(),
            &ServerContext::default(),
            &th(),
            &[],
            now()
        )
        .is_empty());
    }

    #[test]
    fn muted_utility_and_textless_rows_are_skipped() {
        let mut r = row(1, 1000, 30_000.0, Duration::hours(2));
        r.query = Some("VACUUM ANALYZE posthog_person".into());
        let mut no_text = row(2, 1000, 30_000.0, Duration::hours(2));
        no_text.query = None;
        let w = window(vec![r, no_text, row(3, 1000, 30_000.0, Duration::hours(2))]);
        let c = evaluate(
            &w,
            &Baselines::new(),
            &ServerContext::default(),
            &th(),
            &[30],
            now(),
        );
        assert!(c.is_empty());
    }

    #[test]
    fn regression_needs_enough_days_and_beats_median_and_p95() {
        let old = row(7, 500, 100_000.0, Duration::days(20)); // mean 200 ms, share 10%
        let w = window(vec![old.clone()]);
        assert!(needs_baseline(&old, &w, &th(), now()));
        let point = |mean_ms, share_pct| BaselinePoint { mean_ms, share_pct };
        let mut b = Baselines::new();
        b.insert(("posthog".into(), 7), vec![point(50.0, 3.0); 4]);
        assert!(evaluate(&w, &b, &ServerContext::default(), &th(), &[], now()).is_empty());
        b.insert(("posthog".into(), 7), vec![point(50.0, 3.0); 7]);
        let c = evaluate(&w, &b, &ServerContext::default(), &th(), &[], now());
        assert_eq!(c.len(), 1);
        assert_eq!(c[0].rule, Rule::Regression);
        assert_eq!(c[0].reasons.len(), 2);
        // One noisy day lifts the p95 floor above the window mean.
        let mut noisy = vec![point(50.0, 3.0); 6];
        noisy.push(point(150.0, 8.0));
        b.insert(("posthog".into(), 7), noisy);
        let c = evaluate(&w, &b, &ServerContext::default(), &th(), &[], now());
        assert!(c.is_empty());
    }

    #[test]
    fn quantiles() {
        assert_eq!(median(&mut [3.0, 1.0, 2.0]), 2.0);
        assert_eq!(median(&mut [4.0, 1.0, 2.0, 3.0]), 2.5);
        assert_eq!(p95(&mut [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 100.0]), 100.0);
        assert_eq!(p95(&mut []), 0.0);
    }
}
