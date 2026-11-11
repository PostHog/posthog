use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Duration, Timelike, Utc};
use ingestion_framework::{IngestionOutputs, OutputMessage};
use metrics::counter;

use crate::js::{json_stringify, JsObject, JsValue};
use crate::rate_limiter::Clock;
use crate::retention::evaluate::RETENTION_MONTH_DAYS;

pub const APP_METRICS_OUTPUT: &str = "app_metrics";

pub fn datetime_from_ms(ms: f64) -> DateTime<Utc> {
    DateTime::from_timestamp_millis(ms as i64).unwrap_or_default()
}

/// Luxon `yyyy-MM-dd HH:mm:ss.u`.
pub fn clickhouse_timestamp(at: DateTime<Utc>) -> String {
    at.format("%Y-%m-%d %H:%M:%S%.3f").to_string()
}

pub fn iso_timestamp(ms: f64) -> String {
    datetime_from_ms(ms)
        .format("%Y-%m-%dT%H:%M:%S%.3fZ")
        .to_string()
}

#[derive(Debug, Clone)]
struct BufferedAppMetric {
    team_id: i64,
    app_source: String,
    app_source_id: String,
    instance_id: String,
    metric_kind: String,
    metric_name: String,
    count: f64,
    timestamp: Option<String>,
}

#[derive(Debug, Clone)]
pub struct AppMetricInput {
    pub team_id: i64,
    pub app_source: String,
    pub app_source_id: String,
    pub instance_id: String,
    pub metric_kind: String,
    pub metric_name: String,
    pub count: f64,
    pub timestamp: Option<DateTime<Utc>>,
}

/// Rows in first-queued order, as a Node `Map` keeps them, with a key index for the merge.
#[derive(Default)]
struct AppMetricBuffer {
    rows: Vec<BufferedAppMetric>,
    index: HashMap<String, usize>,
}

pub struct AppMetricsAggregator {
    buffer: Mutex<AppMetricBuffer>,
    outputs: Arc<dyn IngestionOutputs>,
    clock: Clock,
}

impl AppMetricsAggregator {
    pub fn new(outputs: Arc<dyn IngestionOutputs>, clock: Clock) -> Self {
        Self {
            buffer: Mutex::new(AppMetricBuffer::default()),
            outputs,
            clock,
        }
    }

    pub fn queue(&self, metric: AppMetricInput) {
        counter!("app_metrics_aggregator_queued_total", "app_source" => metric.app_source.clone())
            .increment(1);
        let timestamp = metric.timestamp.map(|t| {
            let hour = t
                .with_minute(0)
                .and_then(|t| t.with_second(0))
                .and_then(|t| t.with_nanosecond(0))
                .unwrap_or(t);
            clickhouse_timestamp(hour)
        });
        let row = BufferedAppMetric {
            team_id: metric.team_id,
            app_source: metric.app_source,
            app_source_id: metric.app_source_id,
            instance_id: metric.instance_id,
            metric_kind: metric.metric_kind,
            metric_name: metric.metric_name,
            count: metric.count,
            timestamp,
        };
        let key = format!(
            "{}:{}:{}:{}:{}:{}:{}",
            row.team_id,
            row.app_source,
            row.app_source_id,
            row.instance_id,
            row.metric_kind,
            row.metric_name,
            row.timestamp.as_deref().unwrap_or("")
        );
        let mut buffer = self.buffer.lock().unwrap();
        let AppMetricBuffer { rows, index } = &mut *buffer;
        match index.entry(key) {
            Entry::Occupied(slot) => rows[*slot.get()].count += row.count,
            Entry::Vacant(slot) => {
                slot.insert(rows.len());
                rows.push(row);
            }
        }
    }

    pub async fn flush(&self) -> anyhow::Result<()> {
        let drained = std::mem::take(&mut *self.buffer.lock().unwrap()).rows;
        if drained.is_empty() {
            return Ok(());
        }
        let flush_timestamp = clickhouse_timestamp(datetime_from_ms((self.clock)()));
        let messages = drained
            .iter()
            .map(|m| {
                let mut row = JsObject::new();
                row.insert_str("team_id", JsValue::Number(m.team_id as f64));
                row.insert_str(
                    "timestamp",
                    JsValue::string(m.timestamp.as_deref().unwrap_or(&flush_timestamp)),
                );
                row.insert_str("app_source", JsValue::string(&m.app_source));
                row.insert_str("app_source_id", JsValue::string(&m.app_source_id));
                row.insert_str("instance_id", JsValue::string(&m.instance_id));
                row.insert_str("metric_kind", JsValue::string(&m.metric_kind));
                row.insert_str("metric_name", JsValue::string(&m.metric_name));
                row.insert_str("count", JsValue::Number(m.count));
                OutputMessage {
                    value: Some(json_stringify(&JsValue::Object(row)).into_bytes().into()),
                    key: None,
                    headers: Default::default(),
                }
            })
            .collect();
        self.outputs
            .queue_messages(APP_METRICS_OUTPUT, messages)
            .await?;
        for m in &drained {
            counter!("app_metrics_aggregator_flushed_total", "app_source" => m.app_source.clone())
                .increment(1);
        }
        Ok(())
    }
}

/// Lives as long as the consumer, so rows a failed batch queued flush with the next batch that succeeds.
pub struct LogsUsageMetricsQueue {
    aggregator: AppMetricsAggregator,
    app_source: String,
    clock: Clock,
}

impl LogsUsageMetricsQueue {
    pub fn new(aggregator: AppMetricsAggregator, app_source: &str, clock: Clock) -> Self {
        Self {
            aggregator,
            app_source: app_source.to_string(),
            clock,
        }
    }

    fn input(
        &self,
        team_id: i64,
        instance_id: &str,
        metric_name: &str,
        count: f64,
    ) -> AppMetricInput {
        AppMetricInput {
            team_id,
            app_source: self.app_source.clone(),
            app_source_id: String::new(),
            instance_id: instance_id.to_string(),
            metric_kind: "usage".to_string(),
            metric_name: metric_name.to_string(),
            count,
            timestamp: None,
        }
    }

    pub fn queue_usage_metric(&self, team_id: i64, metric_name: &str, count: f64) {
        self.queue_usage_metric_at(team_id, metric_name, count, None);
    }

    pub fn queue_usage_metric_at(
        &self,
        team_id: i64,
        metric_name: &str,
        count: f64,
        at: Option<DateTime<Utc>>,
    ) {
        if count == 0.0 {
            return;
        }
        let mut input = self.input(team_id, "", metric_name, count);
        input.timestamp = at;
        self.aggregator.queue(input);
    }

    /// One `retention_byte_days` row per 30-day month of retention, dated at the start of its month.
    pub fn queue_retention_byte_days(&self, team_id: i64, bytes: f64, retention_days: f64) {
        let now = datetime_from_ms((self.clock)());
        let month = RETENTION_MONTH_DAYS as f64;
        let mut offset = 0.0;
        while offset < retention_days {
            let days = month.min(retention_days - offset);
            let at = now + Duration::days(offset as i64);
            self.queue_usage_metric_at(team_id, "retention_byte_days", bytes * days, Some(at));
            offset += month;
        }
    }

    pub fn queue_by_rule(
        &self,
        team_id: i64,
        metric_name: &str,
        by_rule: &crate::content_weights::OrderedCounts,
    ) {
        for (rule_id, count) in &by_rule.0 {
            if *count <= 0.0 {
                continue;
            }
            self.aggregator
                .queue(self.input(team_id, rule_id, metric_name, *count));
        }
    }

    pub async fn flush(&self) -> anyhow::Result<()> {
        self.aggregator.flush().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timestamps_format_like_luxon_and_date() {
        let at = datetime_from_ms(1_736_944_633_250.0);
        assert_eq!(clickhouse_timestamp(at), "2025-01-15 12:37:13.250");
        assert_eq!(
            iso_timestamp(1_736_944_633_250.0),
            "2025-01-15T12:37:13.250Z"
        );
    }
}
