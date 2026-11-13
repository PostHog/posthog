use std::sync::{Arc, Mutex};

use ingestion_framework::KafkaMessage;
use logs_ingestion::pipeline::app_metrics::{AppMetricInput, AppMetricsAggregator};
use logs_ingestion::pipeline::UsageRecordBatch;

/// Counts are sums of safe integers, kept as doubles as Node keeps them.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct UsageStats {
    pub bytes_received: f64,
    pub records_received: f64,
    pub bytes_allowed: f64,
    pub bytes_allowed_records: f64,
    pub records_allowed: f64,
    pub bytes_dropped: f64,
    pub records_dropped: f64,
}

type StatReader = fn(&UsageStats) -> f64;

pub const USAGE_METRIC_NAMES: [(StatReader, &str); 7] = [
    (|s| s.bytes_received, "bytes_received"),
    (|s| s.records_received, "records_received"),
    (|s| s.bytes_allowed, "bytes_ingested"),
    (|s| s.bytes_allowed_records, "bytes_ingested_records"),
    (|s| s.records_allowed, "records_ingested"),
    (|s| s.bytes_dropped, "bytes_dropped"),
    (|s| s.records_dropped, "records_dropped"),
];

#[derive(Debug, Clone, PartialEq)]
pub struct AllowedMetricsMessage {
    pub team_id: i64,
    pub record_id: String,
    pub timestamp_ms: Option<i64>,
    pub bytes: f64,
    pub bytes_records: f64,
    pub records: f64,
}

/// `kafkaMessageUsageIdentity`: stable across Kafka replays, because usage-ingestion dedups on the record id and the day of the timestamp.
pub fn kafka_message_usage_identity(message: &KafkaMessage) -> (String, Option<i64>) {
    (
        format!("{}:{}:{}", message.topic, message.partition, message.offset),
        message.timestamp,
    )
}

/// Teams in first-seen order, as a Node `Map` keeps them.
#[derive(Debug, Default)]
pub struct MetricsUsageAccumulator {
    stats: Vec<(i64, UsageStats)>,
    allowed: Vec<AllowedMetricsMessage>,
}

impl MetricsUsageAccumulator {
    fn stats_for(&mut self, team_id: i64) -> &mut UsageStats {
        let index = match self.stats.iter().position(|(t, _)| *t == team_id) {
            Some(i) => i,
            None => {
                self.stats.push((team_id, UsageStats::default()));
                self.stats.len() - 1
            }
        };
        &mut self.stats[index].1
    }

    pub fn record_received(&mut self, team_id: i64, bytes: f64, records: f64) {
        let stats = self.stats_for(team_id);
        stats.bytes_received += bytes;
        stats.records_received += records;
    }

    pub fn record_allowed(
        &mut self,
        team_id: i64,
        identity: (String, Option<i64>),
        bytes: f64,
        records: f64,
        bytes_records: f64,
    ) {
        let stats = self.stats_for(team_id);
        stats.bytes_allowed += bytes;
        stats.bytes_allowed_records += bytes_records;
        stats.records_allowed += records;
        self.allowed.push(AllowedMetricsMessage {
            team_id,
            record_id: identity.0,
            timestamp_ms: identity.1,
            bytes,
            bytes_records,
            records,
        });
    }

    pub fn record_dropped(&mut self, team_id: i64, bytes: f64, records: f64) {
        let stats = self.stats_for(team_id);
        stats.bytes_dropped += bytes;
        stats.records_dropped += records;
    }

    pub fn entries(&self) -> &[(i64, UsageStats)] {
        &self.stats
    }

    pub fn allowed_messages(&self) -> &[AllowedMetricsMessage] {
        &self.allowed
    }
}

#[derive(Debug, Default)]
pub struct MetricsUsageBatchContext {
    pub usage: Mutex<MetricsUsageAccumulator>,
}

fn increment_usage_counters(usage: &MetricsUsageAccumulator) {
    let mut totals = UsageStats::default();
    for (team_id, stats) in usage.entries() {
        totals.bytes_received += stats.bytes_received;
        totals.records_received += stats.records_received;
        totals.bytes_allowed += stats.bytes_allowed;
        totals.records_allowed += stats.records_allowed;
        let team: Arc<str> = Arc::from(team_id.to_string());
        if stats.bytes_dropped > 0.0 {
            metrics::counter!("metrics_ingestion_bytes_dropped_total", "team_id" => team.clone())
                .increment(stats.bytes_dropped as u64);
        }
        if stats.records_dropped > 0.0 {
            metrics::counter!("metrics_ingestion_records_dropped_total", "team_id" => team)
                .increment(stats.records_dropped as u64);
        }
    }
    metrics::counter!("metrics_ingestion_bytes_received_total")
        .increment(totals.bytes_received as u64);
    metrics::counter!("metrics_ingestion_records_received_total")
        .increment(totals.records_received as u64);
    metrics::counter!("metrics_ingestion_bytes_allowed_total")
        .increment(totals.bytes_allowed as u64);
    metrics::counter!("metrics_ingestion_records_allowed_total")
        .increment(totals.records_allowed as u64);
}

pub fn add_metrics_usage_records(
    usage_batch: &dyn UsageRecordBatch,
    usage: &MetricsUsageAccumulator,
) {
    for m in usage.allowed_messages() {
        for (quantity, usage_key, unit) in [
            (m.bytes, "metrics_bytes", "bytes"),
            (m.bytes_records, "metrics_bytes_records", "bytes"),
            (m.records, "metrics_records", "records"),
        ] {
            usage_batch.add_at(
                m.team_id,
                usage_key,
                &m.record_id,
                quantity,
                unit,
                m.timestamp_ms,
            );
        }
    }
}

async fn emit_usage_rows(aggregator: &AppMetricsAggregator, usage: &MetricsUsageAccumulator) {
    for (team_id, stats) in usage.entries() {
        for (stat, metric_name) in USAGE_METRIC_NAMES {
            let count = stat(stats);
            if count == 0.0 {
                continue;
            }
            aggregator.queue(AppMetricInput {
                team_id: *team_id,
                app_source: "metrics".to_string(),
                app_source_id: String::new(),
                instance_id: String::new(),
                metric_kind: "usage".to_string(),
                metric_name: metric_name.to_string(),
                count,
                timestamp: None,
            });
        }
    }
    if let Err(error) = aggregator.flush().await {
        tracing::error!(%error, "Failed to emit usage metrics - billing data may be lost");
    }
}

/// `emitMetricsUsage`. It never fails: a failed write of the billing rows is logged.
pub async fn emit_metrics_usage(
    aggregator: &AppMetricsAggregator,
    usage_batch: &dyn UsageRecordBatch,
    usage: &MetricsUsageAccumulator,
) {
    increment_usage_counters(usage);
    add_metrics_usage_records(usage_batch, usage);
    let flush_records = async {
        if let Err(error) = usage_batch.flush().await {
            tracing::error!(%error, "Failed to emit usage records - billing data may be lost");
        }
    };
    futures::join!(emit_usage_rows(aggregator, usage), flush_records);
}
