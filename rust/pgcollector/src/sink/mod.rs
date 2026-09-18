pub mod postgres;

use crate::collector::{Snapshot, State, Target};
use anyhow::Result;
use async_trait::async_trait;

/// Where snapshots go. Collection code never knows.
#[async_trait]
pub trait Sink: Send + Sync {
    async fn write(&self, snap: &Snapshot) -> Result<()>;
    /// Record one collector tick (self-metrics).
    async fn record_run(&self, run: &Run) -> Result<()>;
    /// Persist/restore per-(collector,target) state across restarts.
    async fn save_state(&self, collector: &str, target: &Target, state: &State) -> Result<()>;
    async fn load_state(&self, collector: &str, target: &Target) -> Result<Option<State>>;
    /// Housekeeping: create upcoming partitions, drop expired ones.
    async fn maintain(&self) -> Result<()> {
        Ok(())
    }
    /// Upsert the server row (identity, version, instances) the API lists servers from.
    async fn register_server(&self, _info: &ServerInfo) -> Result<()> {
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct ServerInfo {
    pub server_id: String,
    pub system_identifier: Option<i64>,
    pub version_num: i32,
    pub version: String,
    pub aurora_version: Option<String>,
    pub instances: Vec<String>,
    pub databases: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct Run {
    pub collector: String,
    pub target: Target,
    pub started_at: chrono::DateTime<chrono::Utc>,
    pub duration_ms: i64,
    pub rows: i64,
    pub error: Option<String>,
}

/// `--once` mode: print what would be written.
pub struct StdoutSink;

#[async_trait]
impl Sink for StdoutSink {
    async fn write(&self, snap: &Snapshot) -> Result<()> {
        println!(
            "{:<24} {:<12} {:<8} {:<20} rows={:<6} events={} interval={:.0}s",
            snap.collector,
            snap.target.server_id,
            snap.target.instance,
            snap.target.datname.as_deref().unwrap_or("-"),
            snap.rows.len(),
            snap.events.len(),
            snap.interval_seconds
        );
        if let Some(r) = snap.rows.first() {
            println!("    first row: {}", serde_json::to_string(r)?);
        }
        for a in &snap.aux {
            Box::pin(self.write(a)).await?;
        }
        Ok(())
    }
    async fn record_run(&self, run: &Run) -> Result<()> {
        if let Some(e) = &run.error {
            println!(
                "{:<24} {:<12} ERROR {e}",
                run.collector, run.target.server_id
            );
        }
        Ok(())
    }
    async fn save_state(&self, _: &str, _: &Target, _: &State) -> Result<()> {
        Ok(())
    }
    async fn load_state(&self, _: &str, _: &Target) -> Result<Option<State>> {
        Ok(None)
    }
}
