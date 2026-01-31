mod clickhouse;

pub use clickhouse::ClickHouseLogStore;

use async_trait::async_trait;
use uuid::Uuid;

use crate::error::Result;
use crate::types::AgentEvent;

#[async_trait]
pub trait LogStore: Send + Sync {
    async fn get_logs(
        &self,
        run_id: &Uuid,
        after: Option<u64>,
        limit: Option<u32>,
    ) -> Result<Vec<AgentEvent>>;

    async fn health_check(&self) -> Result<()>;
}
