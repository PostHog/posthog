use anyhow::Result;
use chrono::{DateTime, Utc};
use common_kafka::kafka_producer::{send_keyed_iter_to_kafka, KafkaContext};
use rdkafka::producer::FutureProducer;
use serde::Serialize;
use uuid::Uuid;

use crate::ping::PingExecution;

/// JSON row matching the column list of `kafka_uptime_pings`.
#[derive(Debug, Clone, Serialize)]
pub struct PingRow {
    pub team_id: i64,
    pub monitor_id: Uuid,
    /// Serialized as `YYYY-MM-DD HH:MM:SS.ffffff` — CH's default `date_time_input_format = basic`
    /// rejects RFC3339 (`T` separator + `Z` suffix), so chrono's `to_rfc3339()` produces strings
    /// the Kafka engine refuses to parse. Keep this format unless you also set
    /// `date_time_input_format = best_effort` on the Kafka engine table.
    #[serde(serialize_with = "serialize_ch_datetime")]
    pub timestamp: DateTime<Utc>,
    pub latency_ms: u32,
    pub status_code: u16,
    pub outcome: &'static str,
}

fn serialize_ch_datetime<S>(value: &DateTime<Utc>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: serde::Serializer,
{
    serializer.serialize_str(&value.format("%Y-%m-%d %H:%M:%S%.6f").to_string())
}

impl PingRow {
    pub fn from_execution(team_id: i64, monitor_id: Uuid, execution: &PingExecution) -> Self {
        Self {
            team_id,
            monitor_id,
            timestamp: Utc::now(),
            latency_ms: execution.latency_ms,
            status_code: execution.status_code,
            outcome: execution.outcome.as_str(),
        }
    }
}

pub async fn produce_pings(
    producer: &FutureProducer<KafkaContext>,
    topic: &str,
    rows: Vec<PingRow>,
) -> Vec<Result<()>> {
    let results = send_keyed_iter_to_kafka(
        producer,
        topic,
        // Sharding key for the Kafka topic — keeps a monitor's pings on the same partition,
        // which matters once we want strictly-ordered downstream processing per monitor.
        |row| Some(row.monitor_id.to_string()),
        rows,
    )
    .await;

    results
        .into_iter()
        .map(|r| r.map_err(|e| anyhow::anyhow!(e.to_string())))
        .collect()
}
