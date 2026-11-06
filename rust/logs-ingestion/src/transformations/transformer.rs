use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use hogvm::OrderedJson;
use metrics::{counter, histogram};

use crate::attribute_value::{decode_log_attribute_value, encode_log_attribute_value};
use crate::avro::{AvroMap, AvroValue};
use crate::content_weights::StagedRecord;
use crate::pipeline::LogsTransformer;
use crate::rate_limiter::Clock;
use crate::record::LogRecord;

use super::exec::{
    build_record_globals, execute_log_transformation, globals, project_globals, resolve_inputs,
    sanitize_log_message, TransformStatus,
};
use super::functions::{HogFunction, HogFunctionSource};
use super::monitoring::{HogFunctionMonitoring, LogEntry};

/// A panic inside one function run must not reach the pipeline, which would send the whole message to the DLQ.
fn guarded<T>(run: impl FnOnce() -> T) -> Option<T> {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(run)).ok()
}

const ATTR_TRANSFORMATIONS_FAILED: &str = "$transformations_failed";
const ATTR_TRANSFORMATIONS_SKIPPED: &str = "$transformations_skipped";

#[derive(Debug, Clone)]
pub struct LogsTransformerConfig {
    pub site_url: String,
    pub hog_timeout_ms: f64,
    pub message_budget_ms: f64,
    pub batch_budget_ms: f64,
    pub max_error_logs_per_function_per_message: usize,
}

#[derive(Debug)]
pub struct TransformationBatchBudget {
    total_ms: f64,
    used_ms: Mutex<f64>,
}

impl TransformationBatchBudget {
    pub fn new(total_ms: f64) -> Self {
        Self {
            total_ms,
            used_ms: Mutex::new(0.0),
        }
    }

    pub fn exhausted(&self) -> bool {
        *self.used_ms.lock().unwrap() >= self.total_ms
    }

    pub fn add(&self, ms: f64) {
        *self.used_ms.lock().unwrap() += ms;
    }

    pub fn used_ms(&self) -> f64 {
        *self.used_ms.lock().unwrap()
    }
}

#[derive(Debug, Default, Clone)]
pub struct FunctionAggregates {
    pub succeeded: u64,
    pub failed: u64,
    pub dropped: u64,
    pub budget_skipped: u64,
    pub total_duration_ms: f64,
    pub error_logs: Vec<LogEntry>,
}

#[derive(Debug, Default)]
pub struct MessageTransformResult {
    pub records_dropped: u64,
    pub records_dropped_by_function_id: Vec<(String, u64)>,
    pub aggregates: Vec<(String, FunctionAggregates)>,
    pub vm_ms: f64,
}

fn aggregates_for<'a>(
    aggregates: &'a mut Vec<(String, FunctionAggregates)>,
    id: &str,
) -> &'a mut FunctionAggregates {
    let index = match aggregates.iter().position(|(k, _)| k == id) {
        Some(i) => i,
        None => {
            aggregates.push((id.to_string(), FunctionAggregates::default()));
            aggregates.len() - 1
        }
    };
    &mut aggregates[index].1
}

fn record_counter(result: &'static str) {
    counter!("logs_ingestion_transformations_records_total", "result" => result).increment(1);
}

fn attributes_mut(record: &mut LogRecord) -> &mut AvroMap {
    if record.get_map("attributes").is_none() {
        record.set("attributes", AvroValue::Map(AvroMap::new()));
    }
    record.get_map_mut("attributes").expect("set above")
}

fn annotate_failure(record: &mut LogRecord, function: &HogFunction) {
    let attributes = attributes_mut(record);
    let existing = attributes
        .get(ATTR_TRANSFORMATIONS_FAILED)
        .and_then(AvroValue::as_str)
        .filter(|raw| !raw.is_empty())
        .map(|raw| decode_log_attribute_value(raw).into_string_lossy());
    let identifier = format!("{} ({})", function.name, function.id);
    let value = match existing {
        Some(existing) if !existing.is_empty() => format!("{existing}, {identifier}"),
        _ => identifier,
    };
    attributes.assign(
        ATTR_TRANSFORMATIONS_FAILED.to_string(),
        AvroValue::String(encode_log_attribute_value(&value)),
    );
}

pub struct MessageRun<'a> {
    pub team_id: i64,
    pub functions: &'a [Arc<HogFunction>],
    pub config: &'a LogsTransformerConfig,
    pub batch_budget: Option<&'a TransformationBatchBudget>,
    pub clock: &'a Clock,
    pub instance_id: String,
}

struct RecordContext<'a> {
    run: &'a MessageRun<'a>,
    project: OrderedJson,
    inputs_cache: HashMap<String, Option<OrderedJson>>,
    result: MessageTransformResult,
}

impl RecordContext<'_> {
    fn add_vm_ms(&mut self, ms: f64) {
        self.result.vm_ms += ms;
        if let Some(budget) = self.run.batch_budget {
            budget.add(ms);
        }
    }

    /// Cached per message unless a template mentions `record`. A cached `None` remembers that decision.
    fn resolve_inputs(
        &mut self,
        function: &HogFunction,
        record: &OrderedJson,
    ) -> Result<(OrderedJson, f64), String> {
        match self.inputs_cache.get(&function.id) {
            Some(Some(cached)) => return Ok((cached.clone(), 0.0)),
            Some(None) => {}
            None => {
                if !function.inputs_reference_record {
                    let resolved = resolve_inputs(
                        function,
                        &self.project,
                        record,
                        self.run.config.hog_timeout_ms,
                    )?;
                    self.inputs_cache
                        .insert(function.id.clone(), Some(resolved.0.clone()));
                    return Ok(resolved);
                }
                self.inputs_cache.insert(function.id.clone(), None);
            }
        }
        resolve_inputs(
            function,
            &self.project,
            record,
            self.run.config.hog_timeout_ms,
        )
    }

    fn capture_error_logs(&mut self, function: &HogFunction, print_logs: Vec<String>, error: &str) {
        let max = self.run.config.max_error_logs_per_function_per_message;
        let team_id = self.run.team_id;
        let instance_id = self.run.instance_id.clone();
        let clock = self.run.clock;
        let agg = aggregates_for(&mut self.result.aggregates, &function.id);
        if agg.error_logs.iter().filter(|l| l.level == "error").count() >= max {
            return;
        }
        let entry = |level: &'static str, message: String| LogEntry {
            team_id,
            log_source_id: function.id.clone(),
            instance_id: instance_id.clone(),
            level,
            message,
            timestamp_ms: clock(),
        };
        for message in print_logs {
            agg.error_logs.push(entry("info", message));
        }
        // The thrown text is customer-influenced like print output, so it is redacted too.
        let message = sanitize_log_message(
            &[crate::js::JsValue::string(error)],
            &function.sensitive_values,
        );
        agg.error_logs.push(entry("error", message));
    }

    fn unexpected_failure(&mut self, record: &mut LogRecord, function: &HogFunction) {
        counter!("logs_ingestion_transformations_unexpected_errors_total").increment(1);
        tracing::error!(
            team_id = self.run.team_id,
            function_id = %function.id,
            "[logs-transformer] unexpected error"
        );
        self.fail(record, function);
    }

    fn fail(&mut self, record: &mut LogRecord, function: &HogFunction) {
        aggregates_for(&mut self.result.aggregates, &function.id).failed += 1;
        record_counter("failed");
        annotate_failure(record, function);
    }

    fn transform_record(&mut self, record: &mut LogRecord) -> bool {
        let mut record_globals = build_record_globals(record);
        // Every function that does not drop the record writes to it, through its result or a failure annotation.
        for (index, function) in self.run.functions.iter().enumerate() {
            aggregates_for(&mut self.result.aggregates, &function.id);
            if index > 0 {
                record_globals = build_record_globals(record);
            }
            let resolved = guarded(|| self.resolve_inputs(function, &record_globals));
            let inputs = match resolved {
                None => {
                    self.unexpected_failure(record, function);
                    continue;
                }
                Some(Ok((inputs, ms))) => {
                    self.add_vm_ms(ms);
                    aggregates_for(&mut self.result.aggregates, &function.id).total_duration_ms +=
                        ms;
                    inputs
                }
                Some(Err(error)) => {
                    self.fail(record, function);
                    self.capture_error_logs(function, Vec::new(), &error);
                    continue;
                }
            };
            let timeout_ms = self.run.config.hog_timeout_ms;
            let root = globals(&self.project, &record_globals, inputs);
            let Some(outcome) = guarded(|| {
                execute_log_transformation(
                    function,
                    record,
                    root,
                    timeout_ms,
                    &function.sensitive_values,
                )
            }) else {
                self.unexpected_failure(record, function);
                continue;
            };
            self.add_vm_ms(outcome.duration_ms);
            let agg = aggregates_for(&mut self.result.aggregates, &function.id);
            agg.total_duration_ms += outcome.duration_ms;
            match outcome.status {
                TransformStatus::Failed(error) => {
                    self.fail(record, function);
                    self.capture_error_logs(function, outcome.logs, &error);
                }
                TransformStatus::Dropped => {
                    agg.dropped += 1;
                    record_counter("dropped");
                    match self
                        .result
                        .records_dropped_by_function_id
                        .iter_mut()
                        .find(|(id, _)| *id == function.id)
                    {
                        Some(entry) => entry.1 += 1,
                        None => self
                            .result
                            .records_dropped_by_function_id
                            .push((function.id.clone(), 1)),
                    }
                    return true;
                }
                TransformStatus::Mutated => {
                    agg.succeeded += 1;
                    record_counter("succeeded");
                }
            }
        }
        false
    }
}

pub fn transform_message(
    run: &MessageRun<'_>,
    records: &mut Vec<StagedRecord>,
) -> MessageTransformResult {
    let mut ctx = RecordContext {
        run,
        project: project_globals(run.team_id, &run.config.site_url),
        inputs_cache: HashMap::new(),
        result: MessageTransformResult::default(),
    };
    let mut exhausted_scope: Option<&'static str> = None;
    // Records change in place and leave the vector only at the end, so a panic leaves every record in it.
    let mut dropped = vec![false; records.len()];
    for (index, staged) in records.iter_mut().enumerate() {
        if exhausted_scope.is_none() {
            if run.batch_budget.is_some_and(|b| b.exhausted()) {
                exhausted_scope = Some("batch");
            } else if ctx.result.vm_ms >= run.config.message_budget_ms {
                exhausted_scope = Some("message");
            }
            if let Some(scope) = exhausted_scope {
                let team_id: Arc<str> = Arc::from(run.team_id.to_string());
                counter!("logs_ingestion_transformations_budget_exhausted_total", "scope" => scope, "team_id" => team_id)
                    .increment(1);
            }
        }
        if exhausted_scope.is_some() {
            attributes_mut(&mut staged.record).assign(
                ATTR_TRANSFORMATIONS_SKIPPED.to_string(),
                AvroValue::String(encode_log_attribute_value("budget")),
            );
            record_counter("budget_skipped");
            for function in run.functions {
                aggregates_for(&mut ctx.result.aggregates, &function.id).budget_skipped += 1;
            }
            continue;
        }
        if ctx.transform_record(&mut staged.record) {
            ctx.result.records_dropped += 1;
            dropped[index] = true;
        }
    }
    let mut index = 0;
    records.retain(|_| {
        index += 1;
        !dropped[index - 1]
    });
    ctx.result
}

pub struct LogsTransformerService {
    functions: Arc<dyn HogFunctionSource>,
    monitoring: Arc<HogFunctionMonitoring>,
    config: LogsTransformerConfig,
    clock: Clock,
}

impl LogsTransformerService {
    pub fn new(
        functions: Arc<dyn HogFunctionSource>,
        monitoring: Arc<HogFunctionMonitoring>,
        config: LogsTransformerConfig,
        clock: Clock,
    ) -> Self {
        Self {
            functions,
            monitoring,
            config,
            clock,
        }
    }

    fn queue_aggregates(&self, team_id: i64, aggregates: Vec<(String, FunctionAggregates)>) {
        for (function_id, agg) in aggregates {
            for (count, kind, name) in [
                (agg.succeeded, "success", "succeeded"),
                (agg.failed, "failure", "failed"),
                (agg.dropped, "other", "dropped"),
                (agg.budget_skipped, "other", "budget_skipped"),
            ] {
                if count > 0 {
                    self.monitoring.queue_app_metric(
                        team_id,
                        &function_id,
                        kind,
                        name,
                        count as f64,
                    );
                }
            }
            self.monitoring.queue_logs(agg.error_logs);
        }
    }

    pub async fn transform(
        &self,
        team_id: i64,
        records: &mut Vec<StagedRecord>,
        batch_budget: Option<Arc<TransformationBatchBudget>>,
    ) -> anyhow::Result<MessageTransformResult> {
        let functions = match self.functions.transformations(team_id).await {
            Ok(functions) => functions,
            Err(error) => {
                counter!("logs_ingestion_transformations_infra_errors_total", "source" => "functions_fetch")
                    .increment(1);
                tracing::warn!(team_id, error = %error, "[logs-transformer] function fetch failed, records passed through untransformed");
                return Ok(MessageTransformResult::default());
            }
        };
        if functions.is_empty() || records.is_empty() {
            return Ok(MessageTransformResult::default());
        }
        let shared = Arc::new(Mutex::new(std::mem::take(records)));
        let task_records = shared.clone();
        let config = self.config.clone();
        let clock = self.clock.clone();
        // The VM is CPU-bound for up to the message budget, so it runs off the async workers.
        let joined = tokio::task::spawn_blocking(move || {
            let run = MessageRun {
                team_id,
                functions: &functions,
                config: &config,
                batch_budget: batch_budget.as_deref(),
                clock: &clock,
                instance_id: uuid::Uuid::now_v7().to_string(),
            };
            let mut records = task_records.lock().unwrap_or_else(|e| e.into_inner());
            transform_message(&run, &mut records)
        })
        .await;
        *records = std::mem::take(&mut *shared.lock().unwrap_or_else(|e| e.into_inner()));
        // Fail open like Node's catch: the records go on as the task left them.
        let result = match joined {
            Ok(result) => result,
            Err(error) => {
                counter!("logs_ingestion_transformations_unexpected_errors_total").increment(1);
                tracing::error!(team_id, error = %error, "[logs-transformer] unexpected error");
                return Ok(MessageTransformResult::default());
            }
        };
        histogram!("logs_ingestion_transformations_vm_duration_seconds")
            .record(result.vm_ms / 1000.0);
        self.queue_aggregates(team_id, result.aggregates.clone());
        Ok(result)
    }
}

#[async_trait]
impl LogsTransformer for LogsTransformerService {
    fn start_batch(&self) -> Arc<TransformationBatchBudget> {
        Arc::new(TransformationBatchBudget::new(self.config.batch_budget_ms))
    }

    async fn team_has_transformations(&self, team_id: i64) -> anyhow::Result<bool> {
        match self.functions.transformation_ids(team_id).await {
            Ok(ids) => Ok(!ids.is_empty()),
            Err(error) => {
                counter!("logs_ingestion_transformations_infra_errors_total", "source" => "functions_fetch")
                    .increment(1);
                tracing::warn!(team_id, error = %error, "[logs-transformer] function id fetch failed, skipping transformations");
                Ok(false)
            }
        }
    }

    async fn transform_records(
        &self,
        team_id: i64,
        records: &mut Vec<StagedRecord>,
        batch_budget: Option<Arc<TransformationBatchBudget>>,
    ) -> anyhow::Result<()> {
        self.transform(team_id, records, batch_budget).await?;
        Ok(())
    }

    async fn flush(&self) -> anyhow::Result<()> {
        self.monitoring.flush().await;
        Ok(())
    }
}
