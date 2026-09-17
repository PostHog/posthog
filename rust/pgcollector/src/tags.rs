//! Query tags: key/value pairs in a SQL comment that name the code path that ran a
//! statement. Three comment shapes are accepted because all three are in production:
//! SQLCommenter `key='value'`, colon pairs `key:value`, and the ingestion service's
//! `nodejs:<DB_USE>[:Tx]<operation[:caller]>` prefix. See docs/query-tags.md.

use crate::collector::{Row, Value};
use once_cell::sync::Lazy;
use regex::Regex;
use serde::Deserialize;
use std::collections::BTreeMap;

pub type Tags = BTreeMap<String, String>;

const MAX_PAIRS: usize = 32;
const MAX_KEY: usize = 64;
const MAX_VALUE: usize = 256;

/// Keys that identify one request rather than one code path; grouping on them is
/// meaningless, so they are dropped and only a trace id survives as `trace_id`.
const CONTEXT_KEYS: &[&str] = &[
    "traceparent",
    "tracestate",
    "trace_id",
    "span_id",
    "request_id",
    "x-request-id",
    "session_id",
    "task_id",
    "job_id",
    "run_id",
    "workflow_id",
    "activity_id",
    "txid",
];

/// `nodejs:<DB_USE>[:Tx]<operation[:caller]>` as emitted by the ingestion service.
static NODEJS: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^(?P<db_use>[A-Za-z_]+)(?P<tx>:Tx)?<(?P<op>[^:<>]+)(?::(?P<caller>[^<>]*))?>$")
        .unwrap()
});

#[derive(Debug, Default, Clone, PartialEq)]
pub struct Extracted {
    pub tags: Tags,
    pub trace_id: Option<String>,
    /// The statement with its tag comments removed. Other comments are kept.
    pub sql: String,
}

/// Later comments override earlier keys, so a trailing SQLCommenter block wins over a
/// leading prefix for a shared key. Comment markers inside string literals, dollar
/// quotes and `--` comments are text, not comments.
pub fn extract(sql: &str) -> Extracted {
    let mut out = Extracted::default();
    let b = sql.as_bytes();
    let mut i = 0;
    let mut removed = false;
    while i < b.len() {
        match b[i] {
            b'\'' => {
                // E'..' escapes with a backslash; plain literals double the quote.
                let escapes = i > 0 && matches!(b[i - 1], b'E' | b'e');
                let mut j = i + 1;
                while j < b.len() {
                    if escapes && b[j] == b'\\' {
                        j += 2;
                        continue;
                    }
                    if b[j] == b'\'' {
                        if j + 1 < b.len() && b[j + 1] == b'\'' {
                            j += 2;
                            continue;
                        }
                        break;
                    }
                    j += 1;
                }
                let j = (j + 1).min(b.len());
                out.sql.push_str(&sql[i..j]);
                i = j;
            }
            b'$' => {
                // $$ .. $$ or $tag$ .. $tag$; any other `$` is a parameter marker.
                let close = sql[i + 1..].find('$').map(|n| i + 1 + n).filter(|&c| {
                    sql[i + 1..c]
                        .bytes()
                        .all(|x| x.is_ascii_alphanumeric() || x == b'_')
                });
                match close {
                    Some(c) => {
                        let tag = &sql[i..=c];
                        let end = sql[c + 1..]
                            .find(tag)
                            .map(|n| c + 1 + n + tag.len())
                            .unwrap_or(b.len());
                        out.sql.push_str(&sql[i..end]);
                        i = end;
                    }
                    None => {
                        out.sql.push('$');
                        i += 1;
                    }
                }
            }
            b'-' if b.get(i + 1) == Some(&b'-') => {
                let end = sql[i..].find('\n').map(|n| i + n).unwrap_or(b.len());
                out.sql.push_str(&sql[i..end]);
                i = end;
            }
            b'/' if b.get(i + 1) == Some(&b'*') => {
                let Some(n) = sql[i + 2..].find("*/") else {
                    out.sql.push_str(&sql[i..]);
                    break;
                };
                let body = &sql[i + 2..i + 2 + n];
                let end = i + 2 + n + 2;
                match parse_comment(body) {
                    Some(pairs) => {
                        for (k, v) in pairs {
                            absorb(&mut out, k, v);
                        }
                        removed = true;
                        // Only the blanks around a removed leading comment go with it, so
                        // the rest of the statement keeps its whitespace as written.
                        let ends_blank = out.sql.chars().last().is_none_or(char::is_whitespace);
                        i = end;
                        if ends_blank {
                            while i < b.len() && matches!(b[i], b' ' | b'\t') {
                                i += 1;
                            }
                        }
                    }
                    None => {
                        out.sql.push_str(&sql[i..end]);
                        i = end;
                    }
                }
            }
            _ => {
                let c = sql[i..].chars().next().unwrap();
                out.sql.push(c);
                i += c.len_utf8();
            }
        }
    }
    if removed {
        out.sql = out.sql.trim().to_string();
    }
    out
}

fn absorb(out: &mut Extracted, key: String, value: String) {
    if key == "traceparent" {
        // 00-<trace id>-<span id>-<flags>
        if let Some(id) = value.split('-').nth(1).filter(|id| id.len() == 32) {
            out.trace_id = Some(id.to_string());
        }
        return;
    }
    if key == "trace_id" {
        out.trace_id = Some(value);
        return;
    }
    if CONTEXT_KEYS.contains(&key.as_str()) {
        return;
    }
    if key == "nodejs" {
        expand_nodejs(&mut out.tags, &value);
        return;
    }
    out.tags.insert(key, value);
}

fn expand_nodejs(tags: &mut Tags, value: &str) {
    tags.insert("service".into(), "nodejs".into());
    let Some(c) = NODEJS.captures(value) else {
        tags.insert("operation".into(), value.to_string());
        return;
    };
    tags.insert("db_use".into(), c["db_use"].to_string());
    tags.insert("operation".into(), c["op"].to_string());
    if let Some(caller) = c.name("caller").filter(|m| !m.as_str().is_empty()) {
        tags.insert("caller".into(), caller.as_str().to_string());
    }
    if c.name("tx").is_some() {
        tags.insert("tx".into(), "true".into());
    }
}

/// `None` when any token is not a pair, so the caller leaves a prose comment in place.
pub fn parse_comment(body: &str) -> Option<Vec<(String, String)>> {
    let b: Vec<char> = body.chars().collect();
    let mut i = 0;
    let mut pairs = Vec::new();
    let is_sep = |c: char| c.is_whitespace() || c == ',';
    let is_key = |c: char| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-');
    loop {
        while i < b.len() && is_sep(b[i]) {
            i += 1;
        }
        if i == b.len() {
            break;
        }
        let ks = i;
        while i < b.len() && is_key(b[i]) {
            i += 1;
        }
        if i == ks {
            return None;
        }
        let key: String = b[ks..i].iter().collect::<String>().to_ascii_lowercase();
        while i < b.len() && b[i] == ' ' {
            i += 1;
        }
        if i == b.len() || !matches!(b[i], '=' | ':') {
            return None;
        }
        i += 1;
        while i < b.len() && b[i] == ' ' {
            i += 1;
        }
        let value = if i < b.len() && b[i] == '\'' {
            i += 1;
            let mut v = String::new();
            loop {
                if i == b.len() {
                    return None;
                }
                match b[i] {
                    '\\' if i + 1 < b.len() => {
                        v.push(b[i + 1]);
                        i += 2;
                    }
                    '\'' if i + 1 < b.len() && b[i + 1] == '\'' => {
                        v.push('\'');
                        i += 2;
                    }
                    '\'' => {
                        i += 1;
                        break;
                    }
                    c => {
                        v.push(c);
                        i += 1;
                    }
                }
            }
            v
        } else {
            let vs = i;
            while i < b.len() && !is_sep(b[i]) {
                i += 1;
            }
            b[vs..i].iter().collect()
        };
        if key.len() <= MAX_KEY && pairs.len() < MAX_PAIRS {
            let decoded = percent_decode(&value);
            pairs.push((key, decoded.chars().take(MAX_VALUE).collect()));
        }
    }
    if pairs.is_empty() {
        None
    } else {
        Some(pairs)
    }
}

fn percent_decode(s: &str) -> String {
    if !s.contains('%') {
        return s.to_string();
    }
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Some(v) = std::str::from_utf8(&bytes[i + 1..i + 3])
                .ok()
                .and_then(|h| u8::from_str_radix(h, 16).ok())
            {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

pub fn to_value(tags: &Tags) -> Value {
    if tags.is_empty() {
        Value::Null
    } else {
        Value::Json(serde_json::to_value(tags).unwrap_or(serde_json::Value::Null))
    }
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Spec {
    pub from: String,
    /// Also emit a `trace_id` column (per-sample rows only; meaningless once merged).
    #[serde(default)]
    pub trace_id: bool,
    /// Rows that share every column outside these lists after tagging are merged:
    /// a SQL GROUP BY on the raw comment splits one code path per request id, and
    /// the split is undone here once the request ids are gone.
    pub merge: Option<Merge>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Merge {
    #[serde(default)]
    pub sum: Vec<String>,
    #[serde(default)]
    pub max: Vec<String>,
}

pub fn apply(rows: Vec<Row>, types: &mut BTreeMap<String, String>, spec: &Spec) -> Vec<Row> {
    types.remove(&spec.from);
    types.insert("tags".into(), "jsonb".into());
    if spec.trace_id {
        types.insert("trace_id".into(), "text".into());
    }
    let mut tagged = Vec::with_capacity(rows.len());
    for mut row in rows {
        let ex = match row.remove(&spec.from) {
            Some(Value::Text(s)) => extract(&s),
            _ => Extracted::default(),
        };
        row.insert("tags".into(), to_value(&ex.tags));
        if spec.trace_id {
            row.insert(
                "trace_id".into(),
                ex.trace_id.map(Value::Text).unwrap_or(Value::Null),
            );
        }
        tagged.push(row);
    }
    match &spec.merge {
        Some(m) => merge_rows(tagged, m),
        None => tagged,
    }
}

fn merge_rows(rows: Vec<Row>, m: &Merge) -> Vec<Row> {
    let mut index: BTreeMap<String, usize> = BTreeMap::new();
    let mut out: Vec<Row> = Vec::with_capacity(rows.len());
    for row in rows {
        let group: Vec<String> = row
            .keys()
            .filter(|k| !m.sum.contains(k) && !m.max.contains(k))
            .cloned()
            .collect();
        let k = crate::collector::key_of(&row, &group);
        match index.get(&k) {
            None => {
                index.insert(k, out.len());
                out.push(row);
            }
            Some(&i) => {
                let acc = &mut out[i];
                for c in &m.sum {
                    let v = match (acc.get(c), row.get(c)) {
                        (Some(Value::Int(a)), Some(Value::Int(b))) => Value::Int(a + b),
                        (Some(a), Some(b)) => match (a.as_f64(), b.as_f64()) {
                            (Some(x), Some(y)) => Value::Float(x + y),
                            (None, Some(_)) => b.clone(),
                            _ => a.clone(),
                        },
                        (None, Some(b)) => b.clone(),
                        (a, None) => a.cloned().unwrap_or(Value::Null),
                    };
                    acc.insert(c.clone(), v);
                }
                for c in &m.max {
                    let v = match (
                        acc.get(c).and_then(Value::as_f64),
                        row.get(c).and_then(Value::as_f64),
                    ) {
                        (Some(x), Some(y)) if y > x => row[c].clone(),
                        (None, Some(_)) => row[c].clone(),
                        _ => acc.get(c).cloned().unwrap_or(Value::Null),
                    };
                    acc.insert(c.clone(), v);
                }
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tags(pairs: &[(&str, &str)]) -> Tags {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn ingestion_prefix_is_expanded_into_structured_keys() {
        let e = extract(
            "/* nodejs:PERSONS_WRITE:Tx<fetchPerson:ingestion/person-update-conflict> */ SELECT 1",
        );
        assert_eq!(
            e.tags,
            tags(&[
                ("service", "nodejs"),
                ("db_use", "PERSONS_WRITE"),
                ("operation", "fetchPerson"),
                ("caller", "ingestion/person-update-conflict"),
                ("tx", "true"),
            ])
        );
        assert_eq!(e.sql, "SELECT 1");
        let e = extract("/* nodejs:PERSONS_WRITE<updatePersonsBatch> */\n  UPDATE t SET a = $1");
        assert_eq!(e.tags["operation"], "updatePersonsBatch");
        assert!(!e.tags.contains_key("tx"));
        assert_eq!(e.sql, "UPDATE t SET a = $1");
    }

    #[test]
    fn sqlcommenter_and_colon_styles_merge_across_comments() {
        let e = extract(
            "/* nodejs:X<op> */ UPDATE t SET a = $1 /* operation='updatePerson',purpose='update%20now' */",
        );
        assert_eq!(e.tags["operation"], "updatePerson");
        assert_eq!(e.tags["purpose"], "update now");
        assert_eq!(e.sql, "UPDATE t SET a = $1");
        let e = extract("/* team_id:42 query_type:recording_api_list_blocks */ SELECT 1");
        assert_eq!(
            e.tags,
            tags(&[
                ("team_id", "42"),
                ("query_type", "recording_api_list_blocks")
            ])
        );
    }

    #[test]
    fn context_keys_are_dropped_and_trace_id_kept_apart() {
        let e = extract(
            "SELECT 1 /*route='/api/x',traceparent='00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01',request_id='abc'*/",
        );
        assert_eq!(e.tags, tags(&[("route", "/api/x")]));
        assert_eq!(
            e.trace_id.as_deref(),
            Some("0af7651916cd43dd8448eb211c80319c")
        );
        assert_eq!(e.sql, "SELECT 1");
    }

    #[test]
    fn prose_comments_and_hints_are_not_tags() {
        for sql in [
            "SELECT 1 /* token not in posthog_team, try PSAK below */",
            "/* truncated-query */ SELECT 1",
            "/*+ IndexScan(t) */ SELECT 1",
            "/* code */ SELECT 1",
            "SELECT 1 /* */",
            "SELECT a,\n       b\n  FROM t  WHERE x = 'a  b'",
        ] {
            let e = extract(sql);
            assert!(e.tags.is_empty(), "{sql}");
            assert_eq!(e.sql, sql, "untagged text must come back byte for byte");
        }
        assert_eq!(
            extract("/* route='/x' */ SELECT a,\n       b\n  FROM t  WHERE x = 'a  b'").sql,
            "SELECT a,\n       b\n  FROM t  WHERE x = 'a  b'"
        );
        for sql in [
            "SELECT '/* a:b */'",
            "SELECT E'\\'/* a:b */'",
            "SELECT $$/* a:b */$$, $fn$ /* c:d */ $fn$",
            "SELECT 1 -- /* a:b */",
            "SELECT 'it''s' || '/* a:b */'",
        ] {
            let e = extract(sql);
            assert!(e.tags.is_empty(), "{sql}");
            assert_eq!(e.sql, sql);
        }
        assert_eq!(extract("SELECT 'x' /* a:b */ FROM t").tags.len(), 1);
    }

    #[test]
    fn quoted_values_unescape_and_unterminated_comment_is_left_alone() {
        let p = parse_comment(" a='it\\'s', b='x''y' ").unwrap();
        assert_eq!(
            p,
            vec![("a".into(), "it's".into()), ("b".into(), "x'y".into())]
        );
        assert!(parse_comment("a='open").is_none());
        let e = extract("/* nodejs:X<op> */ SELECT /* trunc");
        assert_eq!(e.tags["operation"], "op");
        assert_eq!(e.sql, "SELECT /* trunc");
    }

    #[test]
    fn apply_merges_rows_that_only_differed_by_request_context() {
        let row = |raw: &str, backends: i64, age: f64| -> Row {
            let mut r = Row::new();
            r.insert("state".into(), Value::Text("active".into()));
            r.insert("query_tags_raw".into(), Value::Text(raw.into()));
            r.insert("backends".into(), Value::Int(backends));
            r.insert("max_query_age_s".into(), Value::Float(age));
            r
        };
        let rows = vec![
            row("/* route='/a', request_id='1' */", 1, 0.5),
            row("/* route='/a', request_id='2' */", 2, 3.0),
            row("/* route='/b' */", 1, 1.0),
        ];
        let spec = Spec {
            from: "query_tags_raw".into(),
            trace_id: false,
            merge: Some(Merge {
                sum: vec!["backends".into()],
                max: vec!["max_query_age_s".into()],
            }),
        };
        let mut types = BTreeMap::from([("query_tags_raw".to_string(), "text".to_string())]);
        let out = apply(rows, &mut types, &spec);
        assert_eq!(out.len(), 2);
        assert_eq!(out[0]["backends"], Value::Int(3));
        assert_eq!(out[0]["max_query_age_s"], Value::Float(3.0));
        assert!(!out[0].contains_key("query_tags_raw"));
        assert_eq!(types.get("tags").map(String::as_str), Some("jsonb"));
        assert!(!types.contains_key("query_tags_raw"));
    }
}
