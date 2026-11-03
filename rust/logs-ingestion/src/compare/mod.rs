//! Each side's unmatched items wait up to the lag tolerance, so the two consumers can run at different offsets.

pub mod kafka;

use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use ingestion_framework::KafkaMessage;
use sha2::{Digest, Sha256};

use crate::avro::{decode_container, AvroValue};
use crate::js::{json_stringify, JsObject, JsString, JsValue};

/// `source_offset` is stamped by the shadow only.
pub const IGNORED_LOGS_HEADERS: &[&str] = &["source_offset"];
/// `failed_at` is a wall clock, and the contract lets error text differ.
pub const IGNORED_DLQ_HEADERS: &[&str] = &["failed_at", "error_message"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Side {
    Node,
    Rust,
}

impl Side {
    fn index(self) -> usize {
        match self {
            Side::Node => 0,
            Side::Rust => 1,
        }
    }
    fn other(self) -> Side {
        match self {
            Side::Node => Side::Rust,
            Side::Rust => Side::Node,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Stream {
    Logs,
    Dlq,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Key {
    pub stream: Stream,
    pub source: String,
    pub id: String,
}

#[derive(Debug, Clone)]
struct Item {
    seq: u64,
    fields: BTreeMap<String, String>,
}

/// `node` and `rust` hold `redact` of each value, because field values are customer content.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Mismatch {
    pub key: Key,
    pub field: String,
    pub node: Option<String>,
    pub rust: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Report {
    pub matched: u64,
    pub mismatched: u64,
    pub node_only: u64,
    pub rust_only: u64,
    pub warmup_unmatched: u64,
    pub field_mismatches: BTreeMap<String, u64>,
}

#[derive(Debug, Clone)]
pub struct CompareSettings {
    pub lag_tolerance: Duration,
    pub warmup: Duration,
    pub max_pending: usize,
    pub sample_limit: usize,
}

/// As the Node harness's `canonicalizeAvroValue`: keys sorted, numbers as doubles, bytes as `{ $bytes: hex }`.
pub fn canonical(value: &AvroValue) -> JsValue {
    let object = |mut entries: Vec<(String, JsValue)>| {
        entries.sort_by(|(a, _), (b, _)| a.encode_utf16().cmp(b.encode_utf16()));
        let mut o = JsObject::new();
        for (k, v) in entries {
            o.insert(JsString::from(k), v);
        }
        JsValue::Object(o)
    };
    match value {
        AvroValue::Null => JsValue::Null,
        AvroValue::Boolean(b) => JsValue::Bool(*b),
        AvroValue::Int(n) | AvroValue::Long(n) => JsValue::Number(*n as f64),
        AvroValue::Float(f) | AvroValue::Double(f) => JsValue::Number(*f),
        AvroValue::Bytes(b) | AvroValue::Fixed(b) => object(vec![(
            "$bytes".to_string(),
            JsValue::string(&hex::encode(b)),
        )]),
        AvroValue::String(s) | AvroValue::Enum(s) => JsValue::string(s),
        AvroValue::Array(items) => JsValue::Array(items.iter().map(canonical).collect()),
        AvroValue::Map(m) => object(
            m.iter()
                .map(|(k, v)| (k.to_string(), canonical(v)))
                .collect(),
        ),
        AvroValue::Record(fields) => object(
            fields
                .iter()
                .map(|(k, v)| (k.to_string(), canonical(v)))
                .collect(),
        ),
    }
}

fn sha(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// The length and a short hash of a value: enough to tell two values apart, not to read them.
pub fn redact(value: &str) -> String {
    format!(
        "len={} sha256={}",
        value.len(),
        &sha(value.as_bytes())[..12]
    )
}

fn header_fields(message: &KafkaMessage, ignored: &[&str]) -> BTreeMap<String, String> {
    message
        .headers
        .iter()
        .filter(|(k, _)| !ignored.contains(&k.as_str()))
        .map(|(k, v)| {
            (
                format!("header:{k}"),
                String::from_utf8_lossy(v.as_deref().unwrap_or_default()).into_owned(),
            )
        })
        .collect()
}

fn header(message: &KafkaMessage, name: &str) -> String {
    message.header(name).unwrap_or_default()
}

pub fn items(stream: Stream, message: &KafkaMessage) -> Vec<(Key, BTreeMap<String, String>)> {
    let source = format!(
        "{}:{}",
        header(message, "source_topic"),
        header(message, "source_partition")
    );
    let value = message.value.as_deref().unwrap_or_default();
    match stream {
        Stream::Dlq => {
            let mut fields = header_fields(message, IGNORED_DLQ_HEADERS);
            fields.insert("value".to_string(), sha(value));
            let id = header(message, "source_offset");
            vec![(Key { stream, source, id }, fields)]
        }
        Stream::Logs => {
            let headers = header_fields(message, IGNORED_LOGS_HEADERS);
            let Ok(container) = decode_container(value) else {
                let mut fields = headers;
                fields.insert("value".to_string(), sha(value));
                return vec![(
                    Key {
                        stream,
                        source,
                        id: format!("raw:{}", sha(value)),
                    },
                    fields,
                )];
            };
            container
                .records
                .iter()
                .map(|record| {
                    let canonical_record = canonical(record);
                    let mut fields = headers.clone();
                    if let JsValue::Object(o) = &canonical_record {
                        for (k, v) in o.iter() {
                            fields.insert(k.to_utf8_lossy().into_owned(), json_stringify(v));
                        }
                    }
                    let id = match record {
                        AvroValue::Record(fs) => fs
                            .iter()
                            .find(|(k, _)| &**k == "uuid")
                            .and_then(|(_, v)| v.as_str().map(str::to_string)),
                        _ => None,
                    }
                    .unwrap_or_else(|| {
                        format!("sha:{}", sha(json_stringify(&canonical_record).as_bytes()))
                    });
                    (
                        Key {
                            stream,
                            source: source.clone(),
                            id,
                        },
                        fields,
                    )
                })
                .collect()
        }
    }
}

pub struct Comparator {
    settings: CompareSettings,
    started: Instant,
    seq: u64,
    pending: [HashMap<Key, VecDeque<Item>>; 2],
    /// Waiting items by arrival sequence. A matched item leaves at once, so the length is exact.
    order: BTreeMap<u64, (Instant, Side, Key)>,
    report: Report,
    samples: Vec<Mismatch>,
}

fn record_result(result: &'static str, n: u64) {
    if n > 0 {
        metrics::counter!("logs_shadow_compare_records_total", "result" => result).increment(n);
    }
}

impl Comparator {
    pub fn new(settings: CompareSettings, now: Instant) -> Self {
        Self {
            settings,
            started: now,
            seq: 0,
            pending: [HashMap::new(), HashMap::new()],
            order: BTreeMap::new(),
            report: Report::default(),
            samples: Vec::new(),
        }
    }

    pub fn report(&self) -> &Report {
        &self.report
    }

    pub fn samples(&self) -> &[Mismatch] {
        &self.samples
    }

    pub fn pending(&self) -> usize {
        self.order.len()
    }

    pub fn ingest(&mut self, side: Side, stream: Stream, message: &KafkaMessage, now: Instant) {
        for (key, fields) in items(stream, message) {
            self.ingest_item(side, key, fields, now);
        }
        self.sweep(now);
    }

    fn ingest_item(
        &mut self,
        side: Side,
        key: Key,
        fields: BTreeMap<String, String>,
        now: Instant,
    ) {
        let other = &mut self.pending[side.other().index()];
        if let Some(queue) = other.get_mut(&key) {
            let counterpart = queue.pop_front().expect("queues are never left empty");
            if queue.is_empty() {
                other.remove(&key);
            }
            self.order.remove(&counterpart.seq);
            let (node, rust) = match side {
                Side::Node => (fields, counterpart.fields),
                Side::Rust => (counterpart.fields, fields),
            };
            self.compare(key, &node, &rust);
            return;
        }
        self.seq += 1;
        self.pending[side.index()]
            .entry(key.clone())
            .or_default()
            .push_back(Item {
                seq: self.seq,
                fields,
            });
        self.order.insert(self.seq, (now, side, key));
    }

    fn compare(
        &mut self,
        key: Key,
        node: &BTreeMap<String, String>,
        rust: &BTreeMap<String, String>,
    ) {
        let names: BTreeSet<&String> = node.keys().chain(rust.keys()).collect();
        let mut differs = false;
        for name in names {
            let (n, r) = (node.get(name), rust.get(name));
            if n == r {
                continue;
            }
            differs = true;
            *self
                .report
                .field_mismatches
                .entry(name.clone())
                .or_default() += 1;
            let field: Arc<str> = Arc::from(name.as_str());
            metrics::counter!("logs_shadow_compare_field_mismatches_total", "field" => field)
                .increment(1);
            if self.samples.len() < self.settings.sample_limit {
                let sample = Mismatch {
                    key: key.clone(),
                    field: name.clone(),
                    node: n.map(|v| redact(v)),
                    rust: r.map(|v| redact(v)),
                };
                tracing::warn!(stream = ?sample.key.stream, source = %sample.key.source, id = %sample.key.id, field = %sample.field, node = ?sample.node, rust = ?sample.rust, "shadow mismatch");
                self.samples.push(sample);
            }
        }
        if differs {
            self.report.mismatched += 1;
            record_result("mismatched", 1);
        } else {
            self.report.matched += 1;
            record_result("matched", 1);
        }
    }

    fn expire_front(&mut self) {
        let Some((seq, (arrived, side, key))) = self.order.pop_first() else {
            return;
        };
        let queue = self.pending[side.index()].get_mut(&key);
        let Some(queue) = queue else { return };
        if queue.front().is_none_or(|i| i.seq != seq) {
            return;
        }
        queue.pop_front();
        if queue.is_empty() {
            self.pending[side.index()].remove(&key);
        }
        if arrived.duration_since(self.started) < self.settings.warmup {
            self.report.warmup_unmatched += 1;
            record_result("warmup_unmatched", 1);
        } else if side == Side::Node {
            self.report.node_only += 1;
            record_result("node_only", 1);
        } else {
            self.report.rust_only += 1;
            record_result("rust_only", 1);
        }
    }

    pub fn sweep(&mut self, now: Instant) {
        while let Some((_, (arrived, _, _))) = self.order.first_key_value() {
            let expired = now.saturating_duration_since(*arrived) > self.settings.lag_tolerance;
            if !expired && self.order.len() <= self.settings.max_pending {
                break;
            }
            self.expire_front();
        }
        metrics::gauge!("logs_shadow_compare_pending").set(self.order.len() as f64);
    }

    pub fn finish(&mut self) -> Report {
        while !self.order.is_empty() {
            self.expire_front();
        }
        self.report.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::avro::{encode_container, Schema};

    fn schema() -> Schema {
        Schema::parse_json(
            r#"{"type":"record","name":"LogRecord","fields":[{"name":"uuid","type":["null","string"]},{"name":"body","type":["null","string"]},{"name":"n","type":["null","double"]},{"name":"attributes","type":["null",{"type":"map","values":"string"}]}]}"#,
        )
        .unwrap()
    }

    fn record(uuid: &str, body: &str, n: f64, attrs: &[(&str, &str)]) -> AvroValue {
        AvroValue::Record(vec![
            (Arc::from("uuid"), AvroValue::String(uuid.into())),
            (Arc::from("body"), AvroValue::String(body.into())),
            (Arc::from("n"), AvroValue::Double(n)),
            (
                Arc::from("attributes"),
                AvroValue::Map(crate::avro::AvroMap::from_strings(attrs.iter().copied())),
            ),
        ])
    }

    fn logs_message(records: &[AvroValue], headers: &[(&str, &str)]) -> KafkaMessage {
        let mut all = vec![
            ("source_topic", "logs_ingestion"),
            ("source_partition", "3"),
            ("team_id", "1"),
        ];
        all.extend_from_slice(headers);
        KafkaMessage {
            value: Some(
                encode_container(&schema(), "zstandard", records)
                    .unwrap()
                    .into(),
            ),
            headers: all
                .iter()
                .map(|(k, v)| (k.to_string(), Some(v.as_bytes().to_vec())))
                .collect(),
            ..Default::default()
        }
    }

    fn settings() -> CompareSettings {
        CompareSettings {
            lag_tolerance: Duration::from_secs(10),
            warmup: Duration::ZERO,
            max_pending: 100,
            sample_limit: 10,
        }
    }

    #[test]
    fn records_match_by_uuid_across_messages_ignoring_order_and_shadow_headers() {
        let t0 = Instant::now();
        let mut c = Comparator::new(settings(), t0);
        let a = record("a", "x", 1.0, &[("k1", "v"), ("k2", "w")]);
        let b = record("b", "y", 2.0, &[]);
        c.ingest(
            Side::Node,
            Stream::Logs,
            &logs_message(&[a.clone(), b.clone()], &[]),
            t0,
        );
        let a_reordered = record("a", "x", 1.0, &[("k2", "w"), ("k1", "v")]);
        c.ingest(
            Side::Rust,
            Stream::Logs,
            &logs_message(&[b], &[("source_offset", "9")]),
            t0,
        );
        c.ingest(
            Side::Rust,
            Stream::Logs,
            &logs_message(&[a_reordered], &[("source_offset", "9")]),
            t0,
        );
        let report = c.finish();
        assert_eq!(report.matched, 2);
        assert_eq!(report.mismatched + report.node_only + report.rust_only, 0);
    }

    #[test]
    fn field_and_header_differences_are_reported_without_their_values() {
        let t0 = Instant::now();
        let mut c = Comparator::new(settings(), t0);
        c.ingest(
            Side::Node,
            Stream::Logs,
            &logs_message(
                &[record("a", "secret-node-body", 1.0, &[])],
                &[("retention-days", "14")],
            ),
            t0,
        );
        c.ingest(
            Side::Rust,
            Stream::Logs,
            &logs_message(
                &[record("a", "secret-rust-body", 1.5, &[])],
                &[("retention-days", "30")],
            ),
            t0,
        );
        let report = c.finish();
        assert_eq!(report.mismatched, 1);
        assert_eq!(
            report.field_mismatches,
            BTreeMap::from([
                ("body".to_string(), 1),
                ("header:retention-days".to_string(), 1),
                ("n".to_string(), 1)
            ])
        );
        let body = &c.samples()[0];
        assert_eq!(body.field, "body");
        assert_ne!(body.node, body.rust);
        assert!(!format!("{:?}", c.samples()).contains("secret"));
    }

    #[test]
    fn matched_items_do_not_count_against_max_pending() {
        let t0 = Instant::now();
        let mut c = Comparator::new(
            CompareSettings {
                max_pending: 2,
                ..settings()
            },
            t0,
        );
        for (side, uuid) in [
            (Side::Node, "x"),
            (Side::Node, "a"),
            (Side::Rust, "a"),
            (Side::Node, "b"),
            (Side::Rust, "x"),
        ] {
            c.ingest(
                side,
                Stream::Logs,
                &logs_message(&[record(uuid, "v", 1.0, &[])], &[]),
                t0,
            );
        }
        assert_eq!(c.pending(), 1);
        let r = c.finish();
        assert_eq!((r.matched, r.node_only, r.rust_only), (2, 1, 0));
    }

    #[test]
    fn unmatched_items_expire_after_the_lag_tolerance_and_warmup_is_separate() {
        let t0 = Instant::now();
        let mut c = Comparator::new(
            CompareSettings {
                warmup: Duration::from_secs(1),
                ..settings()
            },
            t0,
        );
        c.ingest(
            Side::Node,
            Stream::Logs,
            &logs_message(&[record("early", "x", 1.0, &[])], &[]),
            t0,
        );
        let t1 = t0 + Duration::from_secs(5);
        c.ingest(
            Side::Node,
            Stream::Logs,
            &logs_message(&[record("a", "x", 1.0, &[])], &[]),
            t1,
        );
        c.ingest(
            Side::Rust,
            Stream::Logs,
            &logs_message(&[record("b", "x", 1.0, &[])], &[]),
            t1,
        );
        c.sweep(t1 + Duration::from_secs(9));
        assert_eq!(c.report().warmup_unmatched, 1);
        assert_eq!(c.pending(), 2);
        c.ingest(
            Side::Rust,
            Stream::Logs,
            &logs_message(&[record("a", "x", 1.0, &[])], &[]),
            t1 + Duration::from_secs(9),
        );
        c.sweep(t1 + Duration::from_secs(11));
        let r = c.report().clone();
        assert_eq!((r.matched, r.node_only, r.rust_only), (1, 0, 1));
    }

    #[test]
    fn dlq_messages_match_by_source_offset_and_ignore_the_failure_time() {
        let t0 = Instant::now();
        let mut c = Comparator::new(settings(), t0);
        let dlq = |failed_at: &str, name: &str| KafkaMessage {
            value: Some(b"garbage".to_vec().into()),
            headers: [
                ("source_topic", "logs_ingestion"),
                ("source_partition", "0"),
                ("source_offset", "7"),
                ("failed_at", failed_at),
                ("error_name", name),
                ("error_message", "x"),
            ]
            .iter()
            .map(|(k, v)| (k.to_string(), Some(v.as_bytes().to_vec())))
            .collect(),
            ..Default::default()
        };
        c.ingest(
            Side::Node,
            Stream::Dlq,
            &dlq("2025-01-01T00:00:00.000Z", "Error"),
            t0,
        );
        c.ingest(
            Side::Rust,
            Stream::Dlq,
            &dlq("2025-01-01T00:00:09.000Z", "Error"),
            t0,
        );
        c.ingest(Side::Node, Stream::Dlq, &dlq("t", "Error"), t0);
        c.ingest(Side::Rust, Stream::Dlq, &dlq("t", "TypeError"), t0);
        let r = c.finish();
        assert_eq!((r.matched, r.mismatched), (1, 1));
        assert_eq!(r.field_mismatches.get("header:error_name"), Some(&1));
    }
}
