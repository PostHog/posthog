use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::Digest;
use sqlx::Executor;
use uuid::Uuid;

/// Computes the hash_id for a release, matching the CLI's `content_hash([name, version])`.
/// Uses SHA-512, feeding name bytes then version bytes, formatted as lowercase hex.
pub fn release_hash_id(name: &str, version: &str) -> String {
    let mut hasher = sha2::Sha512::new();
    hasher.update(name.as_bytes());
    hasher.update(version.as_bytes());
    format!("{:x}", hasher.finalize())
}

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

// The info, as written to clickhouse at the exception level.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReleaseInfo {
    id: Uuid,
    version: String,
    project: String,
    timestamp: DateTime<Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    metadata: Option<Value>,
}

impl ReleaseRecord {
    pub async fn for_hash_id<'c, E>(
        e: E,
        hash_id: &str,
        team_id: i32,
    ) -> Result<Option<Self>, sqlx::Error>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as!(
            Self,
            r#"
            SELECT id, team_id, hash_id, created_at, version, project, metadata
            FROM posthog_errortrackingrelease
            WHERE hash_id = $1 AND team_id = $2
            "#,
            hash_id,
            team_id
        )
        .fetch_optional(e)
        .await
    }

    pub fn to_release_info(&self) -> ReleaseInfo {
        ReleaseInfo {
            id: self.id,
            project: self.project.clone(),
            version: self.version.clone(),
            timestamp: self.created_at,
            metadata: self.metadata.clone(),
        }
    }

    pub async fn for_symbol_set_ref<'c, E>(
        e: E,
        symbol_set_ref: &str,
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

    pub async fn for_symbol_set_id<'c, E>(
        e: E,
        symbol_set_id: Uuid,
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
            WHERE ss.id = $1 AND ss.team_id = $2
            "#,
            symbol_set_id,
            team_id
        )
        .fetch_optional(e)
        .await?;

        Ok(row)
    }

    pub fn collect_to_map<'a, I>(iter: I) -> HashMap<String, ReleaseInfo>
    where
        I: Iterator<Item = &'a Self>,
    {
        iter.fold(HashMap::new(), |mut map, record| {
            if !map.contains_key(&record.hash_id) {
                map.insert(record.hash_id.clone(), record.to_release_info());
            }
            map
        })
    }
}
