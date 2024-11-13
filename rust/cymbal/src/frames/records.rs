use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::Executor;
use uuid::Uuid;

use crate::error::UnhandledError;

use super::Frame;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ErrorTrackingStackFrame {
    pub raw_id: String,
    pub team_id: i32,
    pub created_at: DateTime<Utc>,
    pub symbol_set_id: Option<Uuid>,
    pub contents: Frame,
    pub resolved: bool,
    pub context: Option<String>,
}

impl ErrorTrackingStackFrame {
    pub fn new(
        raw_id: String,
        team_id: i32,
        symbol_set_id: Option<Uuid>,
        contents: Frame,
        resolved: bool,
        context: Option<String>,
    ) -> Self {
        Self {
            raw_id,
            team_id,
            symbol_set_id,
            contents,
            resolved,
            created_at: Utc::now(),
            context,
        }
    }

    pub async fn save<'c, E>(&self, e: E) -> Result<(), UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackingstackframe (raw_id, team_id, created_at, symbol_set_id, contents, resolved, id, context)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (raw_id, team_id) DO UPDATE SET
                created_at = $3,
                symbol_set_id = $4,
                contents = $5,
                resolved = $6,
                context = $8
            "#,
            self.raw_id,
            self.team_id,
            self.created_at,
            self.symbol_set_id,
            serde_json::to_value(&self.contents)?,
            self.resolved,
            Uuid::now_v7(),
            self.context
        ).execute(e).await?;
        Ok(())
    }

    pub async fn load<'c, E>(
        e: E,
        team_id: i32,
        raw_id: &str,
    ) -> Result<Option<Self>, UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        struct Returned {
            raw_id: String,
            team_id: i32,
            created_at: DateTime<Utc>,
            symbol_set_id: Option<Uuid>,
            contents: Value,
            resolved: bool,
            context: Option<String>,
        }
        let res = sqlx::query_as!(
            Returned,
            r#"
            SELECT raw_id, team_id, created_at, symbol_set_id, contents, resolved, context
            FROM posthog_errortrackingstackframe
            WHERE raw_id = $1 AND team_id = $2
            "#,
            raw_id,
            team_id
        )
        .fetch_optional(e)
        .await?;

        let Some(found) = res else {
            return Ok(None);
        };

        // We don't serialise frame contexts on the Frame itself, but save it on the frame record,
        // and so when we load a frame record we need to patch back up the context onto the frame,
        // since we dropped it when we serialised the frame during saving.

        let mut frame: Frame = serde_json::from_value(found.contents)?;
        frame.context = found.context.clone();

        Ok(Some(Self {
            raw_id: found.raw_id,
            team_id: found.team_id,
            created_at: found.created_at,
            symbol_set_id: found.symbol_set_id,
            contents: frame,
            resolved: found.resolved,
            context: found.context,
        }))
    }
}
