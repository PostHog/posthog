//! Port of `nodejs/src/logs/pipeline/log-processing-pipeline.ts`: content weights, the stage model
//! and `runPipelineStages` with its drop accounting.
//!
//! Node keys the content weights by record object identity. A stage that puts a new record object
//! in the batch gets weight 0 for it. `StagedRecord` carries that identity: a record from the
//! decode keeps its origin index, and `StagedRecord::fresh` makes one without an origin.

use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;

use crate::avro::AvroMap;
use crate::js::{quote_js_string, JsString};
use crate::property_filter::coerce::js_compare;
use crate::record::LogRecord;

fn string_bytes(value: Option<&str>) -> f64 {
    value.map_or(0.0, |s| s.len() as f64)
}

fn map_bytes(map: Option<&AvroMap>) -> f64 {
    let mut total = 0.0;
    if let Some(map) = map {
        for (k, v) in map.iter_strings() {
            total += k.len() as f64 + v.len() as f64;
        }
    }
    total
}

/// `JSON.stringify(Object.entries(map).sort(byKey))`.
fn resource_key(map: Option<&AvroMap>) -> String {
    let mut entries: Vec<(JsString, JsString)> = map
        .map(|m| {
            m.iter_strings()
                .map(|(k, v)| (JsString::from(k), JsString::from(v)))
                .collect()
        })
        .unwrap_or_default();
    entries.sort_by(|(a, _), (b, _)| js_compare(a, b));
    let mut out = String::from("[");
    for (i, (k, v)) in entries.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push('[');
        quote_js_string(k, &mut out);
        out.push(',');
        quote_js_string(v, &mut out);
        out.push(']');
    }
    out.push(']');
    out
}

/// `measureContentWeights`: one weight per record, in input order. Resource and scope bytes are
/// split across the rows that share them, so the weights are fractional.
pub fn measure_content_weights(records: &[LogRecord]) -> Vec<f64> {
    let mut rows_by_resource: HashMap<String, f64> = HashMap::new();
    let mut rows_by_scope: HashMap<String, f64> = HashMap::new();
    let keys: Vec<(String, String)> = records
        .iter()
        .map(|record| {
            let resource = resource_key(record.resource_attributes());
            let mut scope = String::from("[");
            quote_js_string(&JsString::from(resource.as_str()), &mut scope);
            scope.push(',');
            quote_js_string(
                &JsString::from(record.instrumentation_scope().unwrap_or("")),
                &mut scope,
            );
            scope.push(']');
            *rows_by_resource.entry(resource.clone()).or_insert(0.0) += 1.0;
            *rows_by_scope.entry(scope.clone()).or_insert(0.0) += 1.0;
            (resource, scope)
        })
        .collect();
    records
        .iter()
        .zip(keys)
        .map(|(record, (resource, scope))| {
            // Summed left to right, as the TypeScript expression is.
            string_bytes(record.body())
                + string_bytes(record.event_name())
                + string_bytes(record.severity_text())
                + map_bytes(record.attributes())
                + map_bytes(record.resource_attributes()) / rows_by_resource[&resource]
                + string_bytes(record.instrumentation_scope()) / rows_by_scope[&scope]
        })
        .collect()
}

/// A record in the stage pipeline, with the identity that its content weight is keyed by.
#[derive(Debug, Clone, PartialEq)]
pub struct StagedRecord {
    pub record: LogRecord,
    origin: Option<usize>,
}

impl StagedRecord {
    /// A record that a stage made: it has no content weight, as a new object has none in Node.
    pub fn fresh(record: LogRecord) -> Self {
        StagedRecord {
            record,
            origin: None,
        }
    }
}

/// Counts in insertion order, as a JavaScript `Map` keeps them.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct OrderedCounts(pub Vec<(String, f64)>);

impl OrderedCounts {
    pub fn add(&mut self, key: &str, n: f64) {
        match self.0.iter_mut().find(|(k, _)| k == key) {
            Some(entry) => entry.1 += n,
            None => self.0.push((key.to_string(), n)),
        }
    }

    pub fn get(&self, key: &str) -> Option<f64> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| *v)
    }

    fn merge(&mut self, other: &OrderedCounts) {
        for (k, n) in &other.0 {
            self.add(k, *n);
        }
    }
}

/// What one `filter` stage dropped.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct StageDropStats {
    pub records_dropped: f64,
    pub records_dropped_by_rule_id: OrderedCounts,
    pub bytes_dropped: f64,
    pub bytes_dropped_by_rule_id: OrderedCounts,
    pub content_bytes_dropped: f64,
}

/// The stages' reports summed, plus what the pipeline measures itself.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct DropStats {
    pub stage: StageDropStats,
    /// The billing pro-rate denominator, over the whole decoded batch.
    pub content_bytes_total: f64,
    pub records_dropped_by_stage: OrderedCounts,
    /// The last stage that removed records.
    pub dropped_by: Option<String>,
}

/// Content weights fixed before any stage runs.
#[derive(Debug, Clone, Default)]
pub struct BatchContext {
    pub content_bytes_total: f64,
    weights: Arc<Vec<f64>>,
}

impl BatchContext {
    pub fn new(weights: Vec<f64>) -> Self {
        BatchContext {
            content_bytes_total: weights.iter().fold(0.0, |total, w| total + w),
            weights: Arc::new(weights),
        }
    }

    /// `contentBytesOf(record)`: 0 for a record that was not in the decoded batch.
    pub fn content_bytes_of(&self, record: &StagedRecord) -> f64 {
        record
            .origin
            .and_then(|i| self.weights.get(i).copied())
            .unwrap_or(0.0)
    }
}

/// The surviving records of a `filter` stage and what it dropped.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct FilterResult {
    pub kept: Vec<StagedRecord>,
    pub stats: StageDropStats,
}

/// A stage that edits records in place.
#[async_trait]
pub trait MutateStage: Send + Sync {
    fn name(&self) -> &str;
    async fn run(&self, records: &mut Vec<StagedRecord>) -> anyhow::Result<()>;
}

/// A stage that removes records and reports what it dropped.
#[async_trait]
pub trait FilterStage: Send + Sync {
    fn name(&self) -> &str;
    async fn run(
        &self,
        records: Vec<StagedRecord>,
        batch: &BatchContext,
    ) -> anyhow::Result<FilterResult>;
}

pub enum PipelineStage {
    Mutate(Box<dyn MutateStage>),
    Filter(Box<dyn FilterStage>),
}

/// `runPipelineStages`: runs the stages in order and stops once every record is dropped.
pub async fn run_pipeline_stages(
    records: Vec<LogRecord>,
    stages: &[PipelineStage],
) -> anyhow::Result<(Vec<LogRecord>, DropStats)> {
    let mut stats = DropStats::default();
    let has_filter = stages.iter().any(|s| matches!(s, PipelineStage::Filter(_)));
    let batch = BatchContext::new(if has_filter {
        measure_content_weights(&records)
    } else {
        Vec::new()
    });
    stats.content_bytes_total = batch.content_bytes_total;
    let mut working: Vec<StagedRecord> = records
        .into_iter()
        .enumerate()
        .map(|(i, record)| StagedRecord {
            record,
            origin: Some(i),
        })
        .collect();
    for stage in stages {
        let stage = match stage {
            PipelineStage::Mutate(m) => {
                m.run(&mut working).await?;
                continue;
            }
            PipelineStage::Filter(f) => f,
        };
        let before = working.len();
        let FilterResult {
            kept,
            stats: dropped,
        } = stage.run(working, &batch).await?;
        stats.stage.records_dropped += dropped.records_dropped;
        stats.stage.bytes_dropped += dropped.bytes_dropped;
        stats.stage.content_bytes_dropped += dropped.content_bytes_dropped;
        stats
            .stage
            .records_dropped_by_rule_id
            .merge(&dropped.records_dropped_by_rule_id);
        stats
            .stage
            .bytes_dropped_by_rule_id
            .merge(&dropped.bytes_dropped_by_rule_id);
        if kept.len() < before {
            let removed = (before - kept.len()) as f64;
            stats.records_dropped_by_stage.add(stage.name(), removed);
            stats.dropped_by = Some(stage.name().to_string());
        }
        working = kept;
        if working.is_empty() {
            break;
        }
    }
    Ok((working.into_iter().map(|r| r.record).collect(), stats))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::avro::AvroValue;

    fn record(body: &str) -> LogRecord {
        LogRecord::from_value(AvroValue::Record(vec![(
            Arc::from("body"),
            AvroValue::String(body.into()),
        )]))
    }

    struct DropFirst(&'static str);

    #[async_trait]
    impl FilterStage for DropFirst {
        fn name(&self) -> &str {
            self.0
        }
        async fn run(
            &self,
            mut records: Vec<StagedRecord>,
            batch: &BatchContext,
        ) -> anyhow::Result<FilterResult> {
            let mut stats = StageDropStats::default();
            if !records.is_empty() {
                let gone = records.remove(0);
                stats.records_dropped = 1.0;
                stats.content_bytes_dropped = batch.content_bytes_of(&gone);
                stats.records_dropped_by_rule_id.add("r", 1.0);
            }
            Ok(FilterResult {
                kept: records,
                stats,
            })
        }
    }

    struct Replace;

    #[async_trait]
    impl FilterStage for Replace {
        fn name(&self) -> &str {
            "replace"
        }
        async fn run(
            &self,
            records: Vec<StagedRecord>,
            _: &BatchContext,
        ) -> anyhow::Result<FilterResult> {
            let kept = records
                .into_iter()
                .map(|r| StagedRecord::fresh(r.record))
                .collect();
            Ok(FilterResult {
                kept,
                stats: StageDropStats::default(),
            })
        }
    }

    #[tokio::test]
    async fn accounting_follows_identity_and_stops_when_empty() {
        let stages = vec![
            PipelineStage::Filter(Box::new(DropFirst("a"))),
            PipelineStage::Filter(Box::new(Replace)),
            PipelineStage::Filter(Box::new(DropFirst("b"))),
            PipelineStage::Filter(Box::new(DropFirst("c"))),
            PipelineStage::Filter(Box::new(DropFirst("never"))),
        ];
        let (kept, stats) =
            run_pipeline_stages(vec![record("xx"), record("yyy"), record("z")], &stages)
                .await
                .unwrap();
        assert!(kept.is_empty());
        assert_eq!(stats.content_bytes_total, 6.0);
        // Only the first drop credits weight: later drops are of records the replace stage made.
        assert_eq!(stats.stage.content_bytes_dropped, 2.0);
        assert_eq!(stats.stage.records_dropped_by_rule_id.get("r"), Some(3.0));
        assert_eq!(stats.dropped_by.as_deref(), Some("c"));
        assert_eq!(stats.records_dropped_by_stage.get("never"), None);
    }
}
