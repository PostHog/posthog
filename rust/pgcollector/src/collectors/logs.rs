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
    fingerprint::{fingerprint, redact_literals},
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
        let mut out = Outputs::default();
        for (stream, lines) in batch.lines {
            let asm = extra.assemblers.entry(stream.clone()).or_default();
            for line in lines {
                if let Some(e) = asm.push(&re, &line) {
                    out.record(&stream, &e, cx);
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
                        out.record(stream, &e, cx);
                    }
                }
            }
        }
        extra.assemblers.retain(|_, a| a.pending.is_some());

        let mk = |name: &str, key: Vec<&str>, rows: Vec<Row>, types: BTreeMap<String, String>| {
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
            }
        };
        let mut aux = Vec::new();
        if !out.durations.is_empty() {
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
                    ("query", "text"),
                ]),
            ));
        }
        if !out.plans.is_empty() {
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
            ));
        }
        if !out.autovacuum.is_empty() {
            aux.push(mk(
                "autovacuum_runs",
                vec![],
                out.autovacuum,
                types_of(&[("log_time", "timestamptz"), ("aggressive", "boolean")]),
            ));
        }
        if !out.checkpoints.is_empty() {
            aux.push(mk(
                "checkpoints",
                vec![],
                out.checkpoints,
                types_of(&[("log_time", "timestamptz")]),
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
        let mut snap = mk("logs", vec![], counts, types_of(&[("count", "bigint")]));
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
            },
            State {
                collected_at: Some(cx.now),
                rows: Default::default(),
                extra: serde_json::to_value(extra).unwrap(),
            },
        )
    }
}

fn types_of(t: &[(&str, &str)]) -> BTreeMap<String, String> {
    t.iter()
        .map(|(a, b)| (a.to_string(), b.to_string()))
        .collect()
}

#[derive(Default)]
struct Outputs {
    durations: Vec<Row>,
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

    fn record(&mut self, stream: &str, e: &Entry, _cx: &CollectCtx<'_>) {
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
                let mut r = Self::base(stream, e);
                r.insert("duration_ms".into(), Value::Float(duration_ms));
                r.insert("kind".into(), Value::Text(kind));
                r.insert(
                    "fingerprint".into(),
                    query
                        .as_deref()
                        .map(|q| Value::Int(fingerprint(q)))
                        .unwrap_or(Value::Null),
                );
                r.insert("query".into(), opt(&query));
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
