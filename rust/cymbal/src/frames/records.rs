use chrono::{DateTime, Duration, Utc};
use common_types::error_tracking::RawFrameId;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::Executor;
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    frames::{releases::ReleaseRecord, FrameId},
};

use super::{Context, Frame};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ErrorTrackingStackFrame {
    pub id: FrameId,
    pub created_at: DateTime<Utc>,
    pub symbol_set_id: Option<Uuid>,
    pub contents: Frame,
    pub resolved: bool,
    pub context: Option<Context>,
}

impl ErrorTrackingStackFrame {
    pub fn new(
        id: FrameId,
        symbol_set_id: Option<Uuid>,
        contents: Frame,
        resolved: bool,
        context: Option<Context>,
    ) -> Self {
        Self {
            id,
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
        let context = if let Some(context) = &self.context {
            Some(serde_json::to_value(context)?)
        } else {
            None
        };
        sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackingstackframe (raw_id, part, team_id, created_at, symbol_set_id, contents, resolved, id, context)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (raw_id, team_id, part) DO UPDATE SET
                created_at = $4,
                symbol_set_id = $5,
                contents = $6,
                resolved = $7,
                context = $9
            "#,
            self.id.hash_id,
            self.id.part,
            self.id.team_id,
            self.created_at,
            self.symbol_set_id,
            serde_json::to_value(&self.contents)?,
            self.resolved,
            Uuid::now_v7(),
            context,
        ).execute(e).await?;
        Ok(())
    }

    pub async fn load_all<'c, E>(
        e: E,
        id: &RawFrameId,
        result_ttl: Duration,
    ) -> Result<Vec<Self>, UnhandledError>
    where
        E: Executor<'c, Database = sqlx::Postgres> + Clone,
    {
        struct Returned {
            raw_id: String,
            part: i32,
            team_id: i32,
            created_at: DateTime<Utc>,
            symbol_set_id: Option<Uuid>,
            contents: Value,
            resolved: bool,
            context: Option<Value>,
        }
        let res = sqlx::query_as!(
            Returned,
            r#"
            SELECT raw_id, part, team_id, created_at, symbol_set_id, contents, resolved, context
            FROM posthog_errortrackingstackframe
            WHERE raw_id = $1 AND team_id = $2
            "#,
            id.hash_id,
            id.team_id
        )
        .fetch_all(e.clone())
        .await?;

        if res.is_empty() {
            return Ok(Vec::new());
        }

        let mut results = Vec::new();
        if res.iter().any(|f| f.created_at < Utc::now() - result_ttl) {
            // If any resultant frame is too old, we should recalculate all of them
            return Ok(Vec::new());
        }

        let mut release = None;
        if let Some(ss_id) = &res[0].symbol_set_id {
            release = ReleaseRecord::for_symbol_set_id(e, *ss_id, id.team_id).await?;
        }

        for found in res {
            // Frame ID's lose team_id when they're serialized, so we fix that up here when loading them
            let frame_id = FrameId::new(found.raw_id, found.team_id, found.part);
            // We don't serialise frame contexts on the Frame itself, but save it on the frame record,
            // and so when we load a frame record we need to patch back up the context onto the frame,
            // since we dropped it when we serialised the frame during saving.
            let mut frame: Frame = serde_json::from_value(found.contents)?;
            frame.frame_id = frame_id;

            let context = if let Some(context) = found.context {
                // We serialise the frame context as a json string, but it's a structure we have to manually
                // deserialise back into the frame.
                serde_json::from_value(context)?
            } else {
                None
            };

            frame.release = release.clone();
            frame.context = context.clone();

            results.push(Self {
                id: frame.frame_id.clone(),
                created_at: found.created_at,
                symbol_set_id: found.symbol_set_id,
                contents: frame,
                resolved: found.resolved,
                context,
            })
        }

        Ok(results)
    }
}
