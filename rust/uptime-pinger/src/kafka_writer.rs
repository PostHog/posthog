use anyhow::Result;
use chrono::{DateTime, Utc};
use common_kafka::kafka_messages::internal_events::{InternalEvent, InternalEventEvent};
use common_kafka::kafka_producer::{send_keyed_iter_to_kafka, KafkaContext};
use rdkafka::producer::FutureProducer;
use serde::Serialize;
use serde_json::json;
use uuid::Uuid;

use crate::ping::{PingExecution, PingOutcome};

/// Inputs needed to build a status-change internal event once a worker has confirmed
/// the previous-status redis swap actually flipped.
#[derive(Debug, Clone)]
pub struct StatusChange {
    pub team_id: i64,
    pub monitor_id: Uuid,
    pub monitor_name: String,
    pub monitor_url: String,
    pub previous_status: String,
    pub new_status: &'static str,
    pub status_code: u16,
    pub latency_ms: u32,
}

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

/// Payload identical to what `posthog/cdp/internal_events.py::produce_internal_event` writes,
/// so the downstream CDP consumer can route the event without caring whether it came from
/// Python or Rust.
pub fn build_status_change_event(change: &StatusChange, timestamp: DateTime<Utc>) -> InternalEvent {
    let mut event = InternalEventEvent::new(
        "$uptime_monitor_status_changed",
        format!("uptime_monitor_{}", change.monitor_id),
        timestamp,
        None,
    );
    event
        .insert_prop("monitor_id", change.monitor_id.to_string())
        .expect("serializable");
    event
        .insert_prop("monitor_name", change.monitor_name.as_str())
        .expect("serializable");
    event
        .insert_prop("monitor_url", change.monitor_url.as_str())
        .expect("serializable");
    event
        .insert_prop("previous_status", change.previous_status.as_str())
        .expect("serializable");
    event
        .insert_prop("new_status", change.new_status)
        .expect("serializable");
    // Match the Python emitter: 0 status_code means "no HTTP response" — null it out so
    // downstream filters don't treat the sentinel like a real HTTP code.
    event
        .insert_prop(
            "status_code",
            if change.status_code == 0 {
                json!(null)
            } else {
                json!(change.status_code)
            },
        )
        .expect("serializable");
    event
        .insert_prop("latency_ms", change.latency_ms)
        .expect("serializable");

    InternalEvent {
        team_id: change.team_id as i32,
        event,
        person: None,
    }
}

pub async fn produce_status_change(
    producer: &FutureProducer<KafkaContext>,
    topic: &str,
    event: InternalEvent,
) -> Result<()> {
    let key = event.event.uuid.clone();
    let results = send_keyed_iter_to_kafka(
        producer,
        topic,
        |_| Some(key.clone()),
        std::iter::once(event),
    )
    .await;
    results
        .into_iter()
        .next()
        .unwrap_or(Err(
            common_kafka::kafka_producer::KafkaProduceError::KafkaProduceCanceled,
        ))
        .map_err(|e| anyhow::anyhow!(e.to_string()))
}

pub fn outcome_to_status(outcome: PingOutcome) -> &'static str {
    match outcome {
        PingOutcome::Success => "up",
        PingOutcome::Failure => "down",
    }
}
