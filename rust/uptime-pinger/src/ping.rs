use std::time::Instant;

use reqwest::Client;
use serde::Serialize;

/// Outcome string matches the LowCardinality(String) values the ClickHouse
/// `uptime_pings` table expects ("success" | "failure").
#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum PingOutcome {
    Success,
    Failure,
}

impl PingOutcome {
    pub fn as_str(&self) -> &'static str {
        match self {
            PingOutcome::Success => "success",
            PingOutcome::Failure => "failure",
        }
    }
}

/// Result of pinging a single monitor. Mirrors the ClickHouse `uptime_pings` row schema —
/// serialized as JSONEachRow and consumed by the `kafka_uptime_pings` Kafka-engine table.
#[derive(Debug, Clone)]
pub struct PingExecution {
    pub status_code: u16,
    pub latency_ms: u32,
    pub outcome: PingOutcome,
}

pub async fn ping(http: &Client, url: &str) -> PingExecution {
    let started = Instant::now();
    let response = http.get(url).send().await;
    let latency_ms = started.elapsed().as_millis().min(u32::MAX as u128) as u32;

    match response {
        Ok(resp) => {
            let status = resp.status().as_u16();
            let outcome = if resp.status().is_client_error() || resp.status().is_server_error() {
                PingOutcome::Failure
            } else {
                PingOutcome::Success
            };
            PingExecution {
                status_code: status,
                latency_ms,
                outcome,
            }
        }
        Err(_) => PingExecution {
            // 0 is the sentinel for "no HTTP response" — written as status_code when the
            // connection failed. UInt16 in CH can't be NULL.
            status_code: 0,
            latency_ms,
            outcome: PingOutcome::Failure,
        },
    }
}
