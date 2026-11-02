//! The wrappers that keep shadow mode free of billing and customer-visible effects.

use std::sync::Arc;

use async_trait::async_trait;

use crate::js::JsValue;
use crate::metric_rules::{MetricsEmitter, OtlpTransport};
use crate::pipeline::{Team, TeamManager, UsageRecordBatch};

pub const SUPPRESSED_COUNTER: &str = "logs_ingestion_shadow_suppressed_total";

fn suppressed(effect: &'static str, n: u64) {
    metrics::counter!(SUPPRESSED_COUNTER, "effect" => effect).increment(n);
}

pub struct ReadOnlyTeamManager(pub Arc<dyn TeamManager>);

#[async_trait]
impl TeamManager for ReadOnlyTeamManager {
    async fn get_team(&self, team_id: i64) -> anyhow::Result<Option<Team>> {
        self.0.get_team(team_id).await
    }
    async fn get_team_by_token(&self, token: &str) -> anyhow::Result<Option<Team>> {
        self.0.get_team_by_token(token).await
    }
    async fn set_teams_ingested_data(&self, team_ids: &[i64]) -> anyhow::Result<()> {
        suppressed("set_teams_ingested_data", team_ids.len() as u64);
        Ok(())
    }
}

/// The shadow mints its own record ids, so a record it sent would bill twice.
pub struct DiscardUsageRecords;

#[async_trait]
impl UsageRecordBatch for DiscardUsageRecords {
    fn add(&self, _team_id: i64, _usage_key: &str, _record_id: &str, _quantity: f64, _unit: &str) {
        suppressed("usage_record", 1);
    }
    async fn flush(&self) -> anyhow::Result<()> {
        Ok(())
    }
}

/// Present rather than absent: its presence decides whether a buffer is decoded.
pub struct SuppressedMetricsEmitter;

#[async_trait]
impl MetricsEmitter for SuppressedMetricsEmitter {
    async fn emit(&self, _token: &str, _team_id: i64, _payload: &JsValue) -> bool {
        suppressed("metric_rules_otlp", 1);
        true
    }
}

/// `internalFetch` reaches in-cluster capture-logs without a proxy, so this one client opts out
/// instead of a process-wide `NO_PROXY` entry.
pub struct ReqwestOtlpTransport {
    client: reqwest::Client,
}

impl ReqwestOtlpTransport {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self {
            client: reqwest::Client::builder()
                .no_proxy()
                .timeout(std::time::Duration::from_millis(3000))
                .build()?,
        })
    }
}

#[async_trait]
impl OtlpTransport for ReqwestOtlpTransport {
    async fn post(&self, url: &str, headers: &[(&str, String)], body: &str) -> anyhow::Result<u16> {
        let mut request = self.client.post(url).body(body.to_string());
        for (k, v) in headers {
            request = request.header(*k, v);
        }
        let response = request.send().await?;
        let status = response.status().as_u16();
        response.bytes().await?;
        Ok(status)
    }
}
