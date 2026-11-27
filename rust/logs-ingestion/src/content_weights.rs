//! Node keys content weights by record identity, so `StagedRecord` keeps the decode origin and a stage-made record weighs 0.

use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;

use crate::avro::AvroMap;
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

/// A map has distinct keys, so the sorted pairs are equal exactly when the TypeScript's sorted `JSON.stringify` texts are.
fn resource_entries(map: Option<&AvroMap>) -> Vec<(&str, &str)> {
    let mut entries: Vec<(&str, &str)> =
        map.map(|m| m.iter_strings().collect()).unwrap_or_default();
    entries.sort_unstable_by(|a, b| a.0.cmp(b.0));
    entries
}

/// Resource and scope bytes are split across the rows that share them, so the weights are fractional.
pub fn measure_content_weights(records: &[LogRecord]) -> Vec<f64> {
    let mut resource_ids: HashMap<Vec<(&str, &str)>, usize, ahash::RandomState> =
        HashMap::default();
    let mut scope_ids: HashMap<(usize, &str), usize, ahash::RandomState> = HashMap::default();
    let mut rows_by_resource: Vec<f64> = Vec::new();
    let mut rows_by_scope: Vec<f64> = Vec::new();
    let mut previous: Option<(Option<&AvroMap>, usize)> = None;
    let keys: Vec<(usize, usize)> = records
        .iter()
        .map(|record| {
            let map = record.resource_attributes();
            // Records of one message usually share their resource, so an equal map skips the sort.
            let resource = match previous {
                Some((previous_map, id)) if previous_map == map => id,
                _ => {
                    let next = resource_ids.len();
                    let id = *resource_ids.entry(resource_entries(map)).or_insert(next);
                    if id == rows_by_resource.len() {
                        rows_by_resource.push(0.0);
                    }
                    id
                }
            };
            previous = Some((map, resource));
            let next = scope_ids.len();
            let scope = *scope_ids
                .entry((resource, record.instrumentation_scope().unwrap_or("")))
                .or_insert(next);
            if scope == rows_by_scope.len() {
                rows_by_scope.push(0.0);
            }
            rows_by_resource[resource] += 1.0;
            rows_by_scope[scope] += 1.0;
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
                + map_bytes(record.resource_attributes()) / rows_by_resource[resource]
                + string_bytes(record.instrumentation_scope()) / rows_by_scope[scope]
        })
        .collect()
}

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

#[derive(Debug, Clone, Default, PartialEq)]
pub struct StageDropStats {
    pub records_dropped: f64,
    pub records_dropped_by_rule_id: OrderedCounts,
    pub bytes_dropped: f64,
    pub bytes_dropped_by_rule_id: OrderedCounts,
    pub content_bytes_dropped: f64,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DropStats {
    pub stage: StageDropStats,
    /// The billing pro-rate denominator, over the whole decoded batch.
    pub content_bytes_total: f64,
    pub records_dropped_by_stage: OrderedCounts,
    pub dropped_by: Option<String>,
}

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

    pub fn content_bytes_of(&self, record: &StagedRecord) -> f64 {
        record
            .origin
            .and_then(|i| self.weights.get(i).copied())
            .unwrap_or(0.0)
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct FilterResult {
    pub kept: Vec<StagedRecord>,
    pub stats: StageDropStats,
}

#[async_trait]
pub trait MutateStage: Send + Sync {
    fn name(&self) -> &str;
    async fn run(&self, records: &mut Vec<StagedRecord>) -> anyhow::Result<()>;
}

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
