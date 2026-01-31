use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEvent {
    pub team_id: i64,
    pub task_id: Uuid,
    pub run_id: Uuid,
    pub sequence: u64,
    pub timestamp: DateTime<Utc>,
    pub entry_type: String,
    pub entry: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthContext {
    pub user_id: i32,
    pub team_id: Option<i32>,
}

#[cfg(test)]
impl AuthContext {
    pub fn test() -> Self {
        Self {
            user_id: 1,
            team_id: Some(1),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogsQuery {
    pub after: Option<u64>,
    pub limit: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PathParams {
    pub project_id: i64,
    pub task_id: Uuid,
    pub run_id: Uuid,
}
