use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::Value;
use sqlx::Executor;
use uuid::Uuid;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ReleaseRecord {
    pub id: Uuid,
    pub team_id: i32,
    pub hash_id: String,
    pub created_at: DateTime<Utc>,
    pub version: String,
    pub project: String,
    pub metadata: Option<Value>,
}

// The info, as written to clickhouse at the exception level. Doesn't include the
// project, as that's used as a key in the hashmap of releases on the exception
#[derive(Debug, Clone, Serialize)]
pub struct ReleaseInfo {
    version: String,
    timestamp: DateTime<Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    metadata: Option<Value>,
}

impl ReleaseRecord {
    pub async fn for_symbol_set<'c, E>(
        e: E,
        symbol_set_ref: String,
        team_id: i32,
    ) -> Result<Option<Self>, sqlx::Error>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        let row = sqlx::query_as!(
            Self,
            r#"
            SELECT r.id, r.team_id, r.hash_id, r.created_at, r.version, r.project, r.metadata
            FROM posthog_errortrackingsymbolset ss
            INNER JOIN posthog_errortrackingrelease r ON ss.release_id = r.id
            WHERE ss.ref = $1 AND ss.team_id = $2
            "#,
            symbol_set_ref,
            team_id
        )
        .fetch_optional(e)
        .await?;

        Ok(row)
    }

    pub fn collect_to_map<'a, I>(iter: I) -> HashMap<String, ReleaseInfo>
    where
        I: IntoIterator<Item = &'a Self>,
    {
        let mut res = HashMap::new();
        for record in iter {
            if !res.contains_key(&record.hash_id) {
                res.insert(
                    record.hash_id.clone(),
                    ReleaseInfo {
                        version: record.version.clone(),
                        timestamp: record.created_at,
                        metadata: record.metadata.clone(),
                    },
                );
            }
        }
        res
    }
}
