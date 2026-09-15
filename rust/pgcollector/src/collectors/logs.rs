//! Log collector (Tier B): pulls new log lines from the configured source, parses
//! and classifies them, and writes typed records:
//!
//! * `ts_query_durations` — every logged statement duration (this is where real
//!   per-call latency quantiles come from: `log_min_duration_sample` +
//!   `log_statement_sample_rate` on RDS)
//! * `ts_log_plans`       — auto_explain plans (JSON)
//! * `ts_autovacuum_runs` — parsed autovacuum / autoanalyze reports
//! * `ts_checkpoints`     — parsed checkpoint reports
//! * `ts_temp_files`      — temp file spills
//! * `ts_log_errors`      — ERROR/FATAL/PANIC with statement + sqlstate
//! * `ts_log_counts`      — counts by level/class per tick (primary snapshot)
//! * events               — deadlocks, lock waits, cancellations

use crate::collector::*;
use crate::config::{LogSource, LogsConfig};
use crate::logs::{
    self,
    fingerprint::{fingerprint, redact_literals, representative_text},
    histogram::Histogram,
    parse::*,
};
use anyhow::Result;
use async_trait::async_trait;
use once_cell::sync::OnceCell;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::time::Duration;

pub struct Logs {
    cw: OnceCell<aws_sdk_cloudwatchlogs::Client>,
}
impl Logs {
    pub fn new() -> Self {
        Self {
            cw: OnceCell::new(),
        }
    }
}

#[derive(Default, Serialize, Deserialize)]
struct Extra {
    file: logs::FileCursor,
    cloudwatch: logs::CloudWatchCursor,
    assemblers: BTreeMap<String, Assembler>,
}

const MAX_TEXT: usize = 2000;
const MAX_BYTES_PER_TICK: usize = 32 * 1024 * 1024;
const MAX_EVENTS_PER_TICK: usize = 20_000;

#[async_trait]
impl Collector for Logs {
    fn name(&self) -> &str {
        "logs"
    }
    fn interval(&self) -> Duration {
        Duration::from_secs(30)
    }
    fn scope(&self) -> Scope {
        Scope::Cluster
    }
    fn kind(&self) -> Kind {
        Kind::Gauge
    }
    fn per_instance(&self) -> bool {
        false
    }

    async fn collect(
        &self,
        cx: &CollectCtx<'_>,
        prev: Option<&State>,
    ) -> Result<(Snapshot, State)> {
        let mut extra: Extra = prev
            .map(|p| serde_json::from_value(p.extra.clone()).unwrap_or_default())
            .unwrap_or_default();
        let cfg: &LogsConfig = match &cx.server.logs {
            Some(c) => c,
            None => return Ok(self.empty(cx, &extra)),
        };
        let re = prefix_regex(&cfg.log_line_prefix);

        let batch = match &cfg.source {
            LogSource::File => logs::poll_files(&cfg.paths, &mut extra.file, MAX_BYTES_PER_TICK)?,
            LogSource::Cloudwatch => {
                let group = cfg.log_group.clone().ok_or_else(|| {
                    anyhow::anyhow!("logs.log_group is required for source = cloudwatch")
                })?;
                let client = match self.cw.get() {
                    Some(c) => c,
                    None => {
                        let mut loader =
                            aws_config::defaults(aws_config::BehaviorVersion::latest());
                        if let Some(r) = &cfg.region {
                            loader = loader.region(aws_config::Region::new(r.clone()));
                        }
                        let c = aws_sdk_cloudwatchlogs::Client::new(&loader.load().await);
                        self.cw.set(c).ok();
                        self.cw.get().unwrap()
                    }
                };
                logs::poll_cloudwatch(
                    client,
                    &group,
                    &mut extra.cloudwatch,
                    10,
                    MAX_EVENTS_PER_TICK,
                )
                .await?
            }
        };

        if batch.backlog > 0 {
            tracing::warn!(
                server = cx.target.server_id,
                backlog = batch.backlog,
                "log ingestion is behind (per-tick budget hit); will catch up over following ticks"
            );
        }
        let sampling = log_sampling(cx.conn).await;
        let mut out = Outputs {
            sample_rows_over_ms: cfg.sample_rows_over_ms,
            sample_rate: sampling.rate,
            hard_threshold_ms: sampling.hard_threshold_ms,
            ..Default::default()
        };
        for (stream, lines) in batch.lines {
            let asm = extra.assemblers.entry(stream.clone()).or_default();
            for line in lines {
                if let Some(e) = asm.push(&re, &line) {
                    out.record(&stream, &e);
                }
            }
        }
        // Entries waiting on a possible continuation are flushed if older than a tick.
        for (stream, asm) in extra.assemblers.iter_mut() {
            if let Some(p) = &asm.pending {
                if p.ts
                    .map(|t| (cx.now - t).num_seconds() > 30)
                    .unwrap_or(true)
                {
                    if let Some(e) = asm.flush() {
                        out.record(stream, &e);
                    }
                }
            }
        }
        extra.assemblers.retain(|_, a| a.pending.is_some());

        let mk = |name: &str,
                  key: Vec<&str>,
                  rows: Vec<Row>,
                  types: BTreeMap<String, String>,
                  indexes: Vec<Vec<String>>| {
            Snapshot {
                collector: name.into(),
                kind: Kind::Gauge,
                target: cx.target.clone(),
                collected_at: cx.now,
                interval_seconds: 0.0,
                key: key.into_iter().map(str::to_string).collect(),
                types,
                rows,
                events: vec![],
                aux: vec![],
                indexes,
            }
        };
        // pgapi looks statements up by fingerprint (RDS cannot log %Q, so query_id is
        // usually NULL) or by query id.
        let by_statement = || {
            vec![
                vec!["fingerprint".to_string()],
                vec!["query_id".to_string()],
            ]
        };
        let mut aux = Vec::new();
        // Always emitted, even empty, so an existing table gets its indexes without
        // waiting for a new statement.
        {
            aux.push(mk(
                "query_durations",
                vec![],
                out.durations,
                types_of(&[
                    ("log_time", "timestamptz"),
                    ("pid", "bigint"),
                    ("query_id", "bigint"),
                    ("fingerprint", "bigint"),
                    ("duration_ms", "double precision"),
                ]),
                by_statement(),
            ));
        }
        if !out.texts.is_empty() {
            let rows = out
                .texts
                .into_iter()
                .map(|((db, fp), q)| {
                    let mut r = Row::new();
                    r.insert("datname".into(), db.map(Value::Text).unwrap_or(Value::Null));
                    r.insert("fingerprint".into(), Value::Int(fp));
                    r.insert("query".into(), Value::Text(q));
                    r
                })
                .collect();
            let mut snap = mk(
                "query_texts",
                vec!["fingerprint"],
                rows,
                types_of(&[("fingerprint", "bigint"), ("query", "text")]),
                vec![],
            );
            snap.kind = Kind::Snapshot;
            aux.push(snap);
        }
        {
            let rows = out
                .latency
                .into_iter()
                .map(|((db, fp, qid, minute), h)| {
                    let mut r = Row::new();
                    r.insert("datname".into(), db.map(Value::Text).unwrap_or(Value::Null));
                    r.insert(
                        "fingerprint".into(),
                        fp.map(Value::Int).unwrap_or(Value::Null),
                    );
                    r.insert(
                        "query_id".into(),
                        qid.map(Value::Int).unwrap_or(Value::Null),
                    );
                    r.insert("minute".into(), Value::Timestamp(minute));
                    r.insert("count".into(), Value::Int(h.n));
                    r.insert("sum_ms".into(), Value::Float(h.sum_ms));
                    r.insert("max_ms".into(), Value::Float(h.max_ms));
                    r.insert("sampled_counts".into(), Value::IntArray(h.sampled));
                    r.insert("logged_counts".into(), Value::IntArray(h.logged));
                    r.insert("sample_rate".into(), Value::Float(out.sample_rate));
                    r.insert(
                        "hard_threshold_ms".into(),
                        Value::Float(out.hard_threshold_ms),
                    );
                    r
                })
                .collect();
            aux.push(mk(
                "query_latency",
                vec![],
                rows,
                types_of(&[
                    ("fingerprint", "bigint"),
                    ("query_id", "bigint"),
                    ("minute", "timestamptz"),
                    ("count", "bigint"),
                    ("sum_ms", "double precision"),
                    ("max_ms", "double precision"),
                    ("sampled_counts", "integer[]"),
                    ("logged_counts", "integer[]"),
                    ("sample_rate", "double precision"),
                    ("hard_threshold_ms", "double precision"),
                ]),
                by_statement(),
            ));
        }
        {
            aux.push(mk(
                "log_plans",
                vec![],
                out.plans,
                types_of(&[
                    ("log_time", "timestamptz"),
                    ("pid", "bigint"),
                    ("query_id", "bigint"),
                    ("fingerprint", "bigint"),
                    ("duration_ms", "double precision"),
                    ("plan", "jsonb"),
                    ("query", "text"),
                ]),
                by_statement(),
            ));
        }
        if !out.autovacuum.is_empty() {
            aux.push(mk(
                "autovacuum_runs",
                vec![],
                out.autovacuum,
                types_of(&[("log_time", "timestamptz"), ("aggressive", "boolean")]),
                vec![],
            ));
        }
        if !out.checkpoints.is_empty() {
            aux.push(mk(
                "checkpoints",
                vec![],
                out.checkpoints,
                types_of(&[("log_time", "timestamptz")]),
                vec![],
            ));
        }
        if !out.temp_files.is_empty() {
            aux.push(mk(
                "temp_files",
                vec![],
                out.temp_files,
                types_of(&[
                    ("log_time", "timestamptz"),
                    ("pid", "bigint"),
                    ("query_id", "bigint"),
                    ("size_bytes", "bigint"),
                    ("statement", "text"),
                ]),
                vec![],
            ));
        }
        if !out.errors.is_empty() {
            aux.push(mk(
                "log_errors",
                vec![],
                out.errors,
                types_of(&[
                    ("log_time", "timestamptz"),
                    ("pid", "bigint"),
                    ("query_id", "bigint"),
                    ("sqlstate", "text"),
                    ("statement", "text"),
                    ("detail", "text"),
                ]),
                vec![],
            ));
        }

        let counts: Vec<Row> = out
            .counts
            .into_iter()
            .map(|((stream, level, class), n)| {
                let mut r = Row::new();
                r.insert("log_stream".into(), Value::Text(stream));
                r.insert("level".into(), Value::Text(level));
                r.insert("class".into(), Value::Text(class));
                r.insert("count".into(), Value::Int(n));
                r
            })
            .collect();
        let mut snap = mk(
            "logs",
            vec![],
            counts,
            types_of(&[("count", "bigint")]),
            vec![],
        );
        snap.events = out.events;
        snap.aux = aux;
        Ok((
            snap,
            State {
                collected_at: Some(cx.now),
                rows: Default::default(),
                extra: serde_json::to_value(&extra)?,
            },
        ))
    }
}

impl Logs {
    fn empty(&self, cx: &CollectCtx<'_>, extra: &Extra) -> (Snapshot, State) {
        (
            Snapshot {
                collector: "logs".into(),
                kind: Kind::Gauge,
                target: cx.target.clone(),
                collected_at: cx.now,
                interval_seconds: 0.0,
                key: vec![],
                types: Default::default(),
                rows: vec![],
                events: vec![],
                aux: vec![],
                indexes: vec![],
            },
            State {
                collected_at: Some(cx.now),
                rows: Default::default(),
                extra: serde_json::to_value(extra).unwrap(),
            },
        )
    }
}

struct LogSampling {
    rate: f64,
    /// `log_min_duration_statement` in ms; negative means off.
    hard_threshold_ms: f64,
}

/// A statement at or above `log_min_duration_statement` is always logged; below it,
/// `log_statement_sample_rate` decides. Read per tick, because the log line itself
/// does not say which case it was and the settings can change under us.
async fn log_sampling(conn: &tokio_postgres::Client) -> LogSampling {
    let mut s = LogSampling {
        rate: 1.0,
        hard_threshold_ms: -1.0,
    };
    match conn
        .query(
            // reset_val, not setting: this session quiets its own statements by
            // setting log_min_duration_statement = -1, and that must not count as
            // the server's value.
            "SELECT name, reset_val FROM pg_settings WHERE name IN ('log_statement_sample_rate', 'log_min_duration_statement')",
            &[],
        )
        .await
    {
        Ok(rows) => {
            for r in rows {
                let (name, setting): (String, String) = (r.get(0), r.get(1));
                if let Ok(v) = setting.parse::<f64>() {
                    match name.as_str() {
                        "log_statement_sample_rate" => s.rate = v,
                        "log_min_duration_statement" => s.hard_threshold_ms = v,
                        _ => {}
                    }
                }
            }
        }
        Err(e) => tracing::warn!(error = %e, "reading log sampling settings; weighting samples 1:1"),
    }
    s
}

fn types_of(t: &[(&str, &str)]) -> BTreeMap<String, String> {
    t.iter()
        .map(|(a, b)| (a.to_string(), b.to_string()))
        .collect()
}

type LatencyKey = (
    Option<String>,
    Option<i64>,
    Option<i64>,
    chrono::DateTime<chrono::Utc>,
);

#[derive(Default)]
struct Outputs {
    /// Durations below this only count in the histogram; see `LogsConfig`.
    sample_rows_over_ms: f64,
    /// The server's `log_statement_sample_rate` and `log_min_duration_statement`
    /// while these lines were logged; stored with every histogram row so the
    /// weighting survives a settings change.
    sample_rate: f64,
    hard_threshold_ms: f64,
    durations: Vec<Row>,
    /// (datname, fingerprint, query id, minute) → latency histogram.
    latency: BTreeMap<LatencyKey, Histogram>,
    /// (datname, fingerprint) → statement text, stored once per fingerprint in
    /// `cur_query_texts` rather than on every duration row.
    texts: BTreeMap<(Option<String>, i64), String>,
    plans: Vec<Row>,
    autovacuum: Vec<Row>,
    checkpoints: Vec<Row>,
    temp_files: Vec<Row>,
    errors: Vec<Row>,
    counts: BTreeMap<(String, String, String), i64>,
    events: Vec<Event>,
}

/// Statement text as stored: literals redacted, then truncated.
fn text(s: &str) -> Value {
    Value::Text(redact_literals(s).chars().take(MAX_TEXT).collect())
}
fn opt(s: &Option<String>) -> Value {
    s.as_deref().map(text).unwrap_or(Value::Null)
}
fn json_to_value(v: &serde_json::Value) -> Value {
    match v {
        serde_json::Value::Null => Value::Null,
        serde_json::Value::Bool(b) => Value::Bool(*b),
        serde_json::Value::Number(n) => n
            .as_i64()
            .map(Value::Int)
            .or_else(|| n.as_f64().map(Value::Float))
            .unwrap_or(Value::Null),
        serde_json::Value::String(s) => Value::Text(s.clone()),
        other => Value::Json(other.clone()),
    }
}

impl Outputs {
    fn base(stream: &str, e: &Entry) -> Row {
        let mut r = Row::new();
        r.insert(
            "log_time".into(),
            e.ts.map(Value::Timestamp).unwrap_or(Value::Null),
        );
        r.insert("log_stream".into(), Value::Text(stream.to_string()));
        r.insert("pid".into(), e.pid.map(Value::Int).unwrap_or(Value::Null));
        r.insert("datname".into(), opt(&e.db));
        r.insert("usename".into(), opt(&e.user));
        r.insert("application_name".into(), opt(&e.app));
        r.insert(
            "query_id".into(),
            e.query_id.map(Value::Int).unwrap_or(Value::Null),
        );
        r
    }

    fn record(&mut self, stream: &str, e: &Entry) {
        let rec = classify(e);
        let class = match &rec {
            Record::Duration { .. } => "duration",
            Record::Plan { .. } => "plan",
            Record::Autovacuum(_) => "autovacuum",
            Record::Checkpoint(_) => "checkpoint",
            Record::LockWait { .. } => "lock_wait",
            Record::Deadlock => "deadlock",
            Record::TempFile { .. } => "temp_file",
            Record::Cancel { .. } => "cancel",
            Record::Connection { .. } => "connection",
            Record::Error => "error",
            Record::Other => "other",
        };
        *self
            .counts
            .entry((stream.to_string(), e.level.clone(), class.to_string()))
            .or_default() += 1;
        let subject = |e: &Entry| {
            format!(
                "{}@{} pid {}",
                e.user.as_deref().unwrap_or(""),
                e.db.as_deref().unwrap_or(""),
                e.pid.unwrap_or(0)
            )
        };
        match rec {
            Record::Duration {
                duration_ms,
                kind,
                query,
            } => {
                // Bare "duration: X ms" (no text) only carries information with a query id.
                if query.is_none() && e.query_id.is_none() {
                    return;
                }
                // Extended-protocol clients log parse and bind separately; only execute
                // is comparable to execution time, and pgapi never reads the other two.
                if kind == "parse" || kind == "bind" {
                    return;
                }
                let fp = query.as_deref().map(fingerprint);
                if let (Some(fp), Some(q)) = (fp, &query) {
                    self.texts
                        .entry((e.db.clone(), fp))
                        .or_insert_with(|| representative_text(q).chars().take(MAX_TEXT).collect());
                }
                if let Some(ts) = e.ts {
                    let minute = ts
                        - chrono::Duration::seconds(ts.timestamp().rem_euclid(60))
                        - chrono::Duration::nanoseconds(ts.timestamp_subsec_nanos() as i64);
                    let always_logged =
                        self.hard_threshold_ms >= 0.0 && duration_ms >= self.hard_threshold_ms;
                    self.latency
                        .entry((e.db.clone(), fp, e.query_id, minute))
                        .or_default()
                        .add(duration_ms, always_logged);
                }
                if duration_ms < self.sample_rows_over_ms {
                    return;
                }
                let mut r = Self::base(stream, e);
                r.insert("duration_ms".into(), Value::Float(duration_ms));
                r.insert("kind".into(), Value::Text(kind));
                r.insert(
                    "fingerprint".into(),
                    fp.map(Value::Int).unwrap_or(Value::Null),
                );
                self.durations.push(r);
            }
            Record::Plan {
                duration_ms,
                query,
                plan,
            } => {
                let mut r = Self::base(stream, e);
                r.insert("duration_ms".into(), Value::Float(duration_ms));
                r.insert(
                    "fingerprint".into(),
                    query
                        .as_deref()
                        .map(|q| Value::Int(fingerprint(q)))
                        .unwrap_or(Value::Null),
                );
                r.insert("query".into(), opt(&query));
                let mut plan = plan;
                if let Some(o) = plan.as_object_mut() {
                    // auto_explain.log_parameter_max_length puts bound values here.
                    o.remove("Query Parameters");
                    if let Some(serde_json::Value::String(q)) = o.get_mut("Query Text") {
                        *q = redact_literals(q);
                    }
                }
                r.insert("plan".into(), Value::Json(plan));
                self.plans.push(r);
            }
            Record::Autovacuum(fields) => {
                let mut r = Self::base(stream, e);
                for (k, v) in fields {
                    r.insert(k, json_to_value(&v));
                }
                self.autovacuum.push(r);
            }
            Record::Checkpoint(fields) => {
                let mut r = Self::base(stream, e);
                for (k, v) in fields {
                    r.insert(k, json_to_value(&v));
                }
                self.checkpoints.push(r);
            }
            Record::TempFile { size_bytes, path } => {
                let mut r = Self::base(stream, e);
                r.insert("size_bytes".into(), Value::Int(size_bytes));
                r.insert("path".into(), Value::Text(path));
                r.insert("statement".into(), opt(&e.statement));
                r.insert(
                    "fingerprint".into(),
                    e.statement
                        .as_deref()
                        .map(|q| Value::Int(fingerprint(q)))
                        .unwrap_or(Value::Null),
                );
                self.temp_files.push(r);
            }
            Record::LockWait {
                waiting_pid,
                lock_type,
                target,
                wait_ms,
                acquired,
            } => {
                if !acquired {
                    self.events.push(Event { kind: "log_lock_wait".into(), subject: subject(e), before: None,
                        after: Some(serde_json::json!({ "at": e.ts, "pid": waiting_pid, "lock_type": lock_type, "target": target, "wait_ms": wait_ms,
                            "detail": e.detail, "statement": e.statement.as_deref().map(|s| redact_literals(s).chars().take(MAX_TEXT).collect::<String>()), "log_stream": stream })) });
                }
            }
            Record::Deadlock => {
                self.events.push(Event { kind: "log_deadlock".into(), subject: subject(e), before: None,
                    after: Some(serde_json::json!({ "at": e.ts, "detail": e.detail.as_deref().map(redact_literals), "hint": e.hint, "statement": e.statement.as_deref().map(redact_literals), "log_stream": stream })) });
                self.push_error(stream, e, "deadlock");
            }
            Record::Cancel { reason } => {
                self.events.push(Event { kind: "log_cancel".into(), subject: subject(e), before: None,
                    after: Some(serde_json::json!({ "at": e.ts, "reason": reason, "statement": e.statement.as_deref().map(|s| redact_literals(s).chars().take(MAX_TEXT).collect::<String>()), "log_stream": stream })) });
                self.push_error(stream, e, "cancel");
            }
            Record::Error => self.push_error(stream, e, "error"),
            Record::Connection { .. } | Record::Other => {}
        }
    }

    fn push_error(&mut self, stream: &str, e: &Entry, class: &str) {
        let mut r = Self::base(stream, e);
        r.insert("level".into(), Value::Text(e.level.clone()));
        r.insert("class".into(), Value::Text(class.into()));
        r.insert("sqlstate".into(), opt(&e.sqlstate));
        r.insert("message".into(), text(&e.message));
        r.insert("detail".into(), opt(&e.detail));
        r.insert("statement".into(), opt(&e.statement));
        r.insert(
            "fingerprint".into(),
            e.statement
                .as_deref()
                .map(|q| Value::Int(fingerprint(q)))
                .unwrap_or(Value::Null),
        );
        self.errors.push(r);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_and_bind_durations_are_counted_but_not_stored() {
        let re = prefix_regex("%t:%r:%u@%d:[%p]:");
        let mut asm = Assembler::default();
        let mut out = Outputs {
            sample_rows_over_ms: 100.0,
            sample_rate: 0.1,
            hard_threshold_ms: 200.0,
            ..Default::default()
        };
        let lines = [
            "2026-08-27 18:22:49 UTC:10.1.2.3(5000):app@app:[140]:LOG:  duration: 0.010 ms  parse <unnamed>: select id from t where id = $1",
            "2026-08-27 18:22:49 UTC:10.1.2.3(5000):app@app:[140]:LOG:  duration: 0.020 ms  bind <unnamed>: select id from t where id = $1",
            "2026-08-27 18:22:49 UTC:10.1.2.3(5000):app@app:[140]:LOG:  duration: 1.500 ms  execute <unnamed>: select id from t where id = $1",
            "2026-08-27 18:22:59 UTC:10.1.2.3(5000):app@app:[140]:LOG:  duration: 3.000 ms  execute <unnamed>: select id from t where id = $1",
            "2026-08-27 18:22:50 UTC:10.1.2.3(5000):app@app:[141]:LOG:  duration: 250.0 ms  statement: select count(*) from t /* not stored */",
        ];
        for l in lines {
            if let Some(e) = asm.push(&re, l) {
                out.record("writer", &e);
            }
        }
        if let Some(e) = asm.flush() {
            out.record("writer", &e);
        }
        assert!(out.durations.iter().all(|r| !r.contains_key("query")));
        assert!(out.texts.values().any(|q| q == "select count(*) from t"));
        assert_eq!(
            out.texts
                .keys()
                .map(|(db, _)| db.as_deref())
                .collect::<Vec<_>>(),
            [Some("app"), Some("app")]
        );
        let kinds: Vec<&Value> = out.durations.iter().map(|r| &r["kind"]).collect();
        assert_eq!(kinds, [&Value::Text("statement".into())]);
        // The 250 ms statement is over the always-log threshold, the executes were sampled.
        let mut hists: Vec<(i64, f64, i32, i32)> = out
            .latency
            .values()
            .map(|h| (h.n, h.max_ms, h.sampled.iter().sum(), h.logged.iter().sum()))
            .collect();
        hists.sort_by(|a, b| a.partial_cmp(b).unwrap());
        assert_eq!(hists, [(1, 250.0, 0, 1), (2, 3.0, 2, 0)]);
        assert!(out
            .latency
            .keys()
            .all(|(_, _, _, minute)| minute.to_rfc3339() == "2026-08-27T18:22:00+00:00"));
        assert_eq!(
            out.counts[&(
                "writer".to_string(),
                "LOG".to_string(),
                "duration".to_string()
            )],
            5
        );
    }
}
