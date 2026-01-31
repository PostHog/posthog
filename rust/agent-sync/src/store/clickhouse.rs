use async_trait::async_trait;
use clickhouse::Row;
use serde::Deserialize;
use std::sync::Arc;
use uuid::Uuid;

use super::LogStore;
use crate::error::Result;
use crate::types::AgentEvent;

#[derive(Debug, Row, Deserialize)]
struct LogRow {
    team_id: i64,
    task_id: Uuid,
    run_id: Uuid,
    sequence: u64,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    timestamp: time::OffsetDateTime,
    entry_type: String,
    entry: String,
}

impl From<LogRow> for AgentEvent {
    fn from(row: LogRow) -> Self {
        let timestamp = chrono::DateTime::from_timestamp(
            row.timestamp.unix_timestamp(),
            row.timestamp.nanosecond(),
        )
        .unwrap_or_else(|| {
            tracing::warn!(
                run_id = %row.run_id,
                sequence = row.sequence,
                "Invalid timestamp in log row, using epoch"
            );
            chrono::DateTime::UNIX_EPOCH
        });

        let entry = serde_json::from_str(&row.entry).unwrap_or_else(|e| {
            tracing::warn!(
                run_id = %row.run_id,
                sequence = row.sequence,
                error = %e,
                "Failed to parse entry JSON, using null"
            );
            serde_json::Value::Null
        });

        AgentEvent {
            team_id: row.team_id,
            task_id: row.task_id,
            run_id: row.run_id,
            sequence: row.sequence,
            timestamp,
            entry_type: row.entry_type,
            entry,
        }
    }
}

pub struct ClickHouseLogStore {
    client: clickhouse::Client,
}

impl ClickHouseLogStore {
    pub fn new(
        host: &str,
        port: u16,
        database: &str,
        user: &str,
        password: &str,
    ) -> Arc<Self> {
        let url = format!("http://{}:{}", host, port);
        let mut client = clickhouse::Client::default()
            .with_url(&url)
            .with_database(database)
            .with_user(user);

        if !password.is_empty() {
            client = client.with_password(password);
        }

        Arc::new(Self { client })
    }
}

#[async_trait]
impl LogStore for ClickHouseLogStore {
    async fn get_logs(
        &self,
        run_id: &Uuid,
        after: Option<u64>,
        limit: Option<u32>,
    ) -> Result<Vec<AgentEvent>> {
        let after_seq = after.unwrap_or(0);
        let limit = limit.unwrap_or(10000);

        let rows: Vec<LogRow> = self
            .client
            .query(
                r#"
                SELECT team_id, task_id, run_id, sequence, timestamp, entry_type, entry
                FROM agent_logs
                WHERE run_id = ?
                  AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                "#,
            )
            .bind(run_id)
            .bind(after_seq)
            .bind(limit)
            .fetch_all()
            .await?;

        Ok(rows.into_iter().map(AgentEvent::from).collect())
    }

    async fn health_check(&self) -> Result<()> {
        self.client.query("SELECT 1").execute().await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_log_row_conversion() {
        let row = LogRow {
            team_id: 1,
            task_id: Uuid::new_v4(),
            run_id: Uuid::new_v4(),
            sequence: 1,
            timestamp: time::OffsetDateTime::now_utc(),
            entry_type: "test".to_string(),
            entry: r#"{"test": true}"#.to_string(),
        };

        let event: AgentEvent = row.into();
        assert_eq!(event.team_id, 1);
        assert_eq!(event.sequence, 1);
        assert_eq!(event.entry_type, "test");
    }
}
