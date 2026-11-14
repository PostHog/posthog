use std::sync::{Arc, Mutex};
use std::time::Instant;

use ingestion_framework::{IngestionOutputs, OutputMessage};
use metrics::{counter, gauge, histogram};

use crate::js::{json_stringify, JsObject, JsValue};
use crate::pipeline::app_metrics::{
    clickhouse_timestamp, datetime_from_ms, AppMetricInput, AppMetricsAggregator,
};
use crate::rate_limiter::Clock;

pub const LOG_ENTRIES_OUTPUT: &str = "log_entries";
pub const HOG_FUNCTION_SOURCE: &str = "hog_function";

#[derive(Debug, Clone, PartialEq)]
pub struct LogEntry {
    pub team_id: i64,
    pub log_source_id: String,
    pub instance_id: String,
    pub level: &'static str,
    pub message: String,
    pub timestamp_ms: f64,
}

pub struct HogFunctionMonitoring {
    aggregator: AppMetricsAggregator,
    outputs: Arc<dyn IngestionOutputs>,
    queued_logs: Mutex<Vec<Vec<u8>>>,
    /// Shadow mode has no `log_entries` topic, so it drops the entries.
    write_log_entries: bool,
}

impl HogFunctionMonitoring {
    pub fn new(outputs: Arc<dyn IngestionOutputs>, clock: Clock, write_log_entries: bool) -> Self {
        Self {
            aggregator: AppMetricsAggregator::new(outputs.clone(), clock),
            outputs,
            queued_logs: Mutex::new(Vec::new()),
            write_log_entries,
        }
    }

    pub fn queue_app_metric(
        &self,
        team_id: i64,
        app_source_id: &str,
        metric_kind: &'static str,
        metric_name: &'static str,
        count: f64,
    ) {
        counter!("cdp_hog_function_metric", "metric_kind" => metric_kind, "metric_name" => metric_name)
            .increment(count as u64);
        self.aggregator.queue(AppMetricInput {
            team_id,
            app_source: HOG_FUNCTION_SOURCE.to_string(),
            app_source_id: app_source_id.to_string(),
            instance_id: String::new(),
            metric_kind: metric_kind.to_string(),
            metric_name: metric_name.to_string(),
            count,
            timestamp: None,
        });
    }

    /// `queueLogs` with `fixLogDeduplication`: ClickHouse dedupes equal timestamps, so each later entry moves 1 ms past the one before.
    pub fn queue_logs(&self, mut entries: Vec<LogEntry>) {
        if entries.is_empty() || !self.write_log_entries {
            return;
        }
        entries.sort_by(|a, b| a.timestamp_ms.total_cmp(&b.timestamp_ms));
        let mut previous = entries[0].timestamp_ms - 1.0;
        let mut serialized = Vec::with_capacity(entries.len());
        for entry in &mut entries {
            if entry.timestamp_ms <= previous {
                entry.timestamp_ms = previous + 1.0;
            }
            previous = entry.timestamp_ms;
            serialized.push(serialize_log_entry(entry));
        }
        let mut queued = self.queued_logs.lock().unwrap();
        queued.extend(serialized);
        gauge!("cdp_hog_function_monitoring_pending_messages").set(queued.len() as f64);
    }

    pub async fn flush(&self) {
        let start = Instant::now();
        let messages = std::mem::take(&mut *self.queued_logs.lock().unwrap());
        gauge!("cdp_hog_function_monitoring_pending_messages").set(0.0);
        let metrics = async {
            if let Err(error) = self.aggregator.flush().await {
                tracing::error!(error = %error, "failed to flush app metrics");
            }
        };
        let logs = futures::future::join_all(messages.into_iter().map(|value| async move {
            let length = value.len();
            let message = OutputMessage {
                value: Some(value.into()),
                key: None,
                headers: Default::default(),
            };
            if let Err(error) = self.outputs.produce(LOG_ENTRIES_OUTPUT, message).await {
                tracing::error!(error = %error, length, "failed to produce log entry");
            }
        }));
        futures::join!(metrics, logs);
        histogram!("cdp_hog_function_monitoring_flush_duration_seconds")
            .record(start.elapsed().as_secs_f64());
    }
}

pub fn serialize_log_entry(entry: &LogEntry) -> Vec<u8> {
    let mut o = JsObject::new();
    o.insert_str("team_id", JsValue::Number(entry.team_id as f64));
    o.insert_str("log_source", JsValue::string(HOG_FUNCTION_SOURCE));
    o.insert_str("log_source_id", JsValue::string(&entry.log_source_id));
    o.insert_str("instance_id", JsValue::string(&entry.instance_id));
    o.insert_str("level", JsValue::string(entry.level));
    o.insert_str("message", JsValue::string(&entry.message));
    o.insert_str(
        "timestamp",
        JsValue::string(&clickhouse_timestamp(datetime_from_ms(entry.timestamp_ms))),
    );
    json_stringify(&JsValue::Object(o)).into_bytes()
}
