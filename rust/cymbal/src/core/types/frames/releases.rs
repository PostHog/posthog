use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha512};
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

// The info, as written to clickhouse at the exception level.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReleaseInfo {
    version: String,
    project: String,
    timestamp: DateTime<Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    metadata: Option<Value>,
}

impl ReleaseRecord {
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

    pub async fn for_id<'c, E>(e: E, id: Uuid, team_id: i32) -> Result<Option<Self>, sqlx::Error>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        let row = sqlx::query_as!(
            Self,
            r#"
            SELECT id, team_id, hash_id, created_at, version, project, metadata
            FROM posthog_errortrackingrelease
            WHERE id = $1 AND team_id = $2
            "#,
            id,
            team_id
        )
        .fetch_optional(e)
        .await?;

        Ok(row)
    }

    pub async fn for_hash<'c, E>(
        e: E,
        hash_id: &str,
        team_id: i32,
    ) -> Result<Option<Self>, sqlx::Error>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        let row = sqlx::query_as!(
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
        .await?;

        Ok(row)
    }

    pub fn collect_to_map<'a, I>(iter: I) -> HashMap<String, ReleaseInfo>
    where
        I: Iterator<Item = &'a Self>,
    {
        iter.fold(HashMap::new(), |mut map, record| {
            if !map.contains_key(&record.hash_id) {
                map.insert(
                    record.hash_id.clone(),
                    ReleaseInfo {
                        project: record.project.clone(),
                        version: record.version.clone(),
                        timestamp: record.created_at,
                        metadata: record.metadata.clone(),
                    },
                );
            }
            map
        })
    }
}

/// Reconstruct the release `hash_id` the CLI wrote for a mobile build, from the app metadata the
/// SDK sends on every event. Mobile events carry no injected `$release_id`, so this is how their
/// release is resolved. It must stay byte-for-byte identical to the CLI, which keys releases on
/// `content_hash([name, version])` where `name` is the bundle identifier and `version` is
/// `pack_version(short_version, build)`:
///   - packing lives in `cli/src/sourcemaps/args.rs::pack_version`
///   - hashing lives in `cli/src/utils/files/content.rs::content_hash` (SHA-512 over the name bytes
///     followed by the version bytes, with no separator)
pub fn mobile_release_hash_id(
    namespace: &str,
    version: Option<&str>,
    build: Option<&str>,
) -> Option<String> {
    let packed = pack_version(version, build)?;
    Some(release_hash_id(namespace, &packed))
}

fn pack_version(version: Option<&str>, build: Option<&str>) -> Option<String> {
    match (version, build) {
        (Some(v), Some(b)) => Some(format!("{v}+{b}")),
        (Some(v), None) => Some(v.to_string()),
        (None, Some(b)) => Some(b.to_string()),
        (None, None) => None,
    }
}

fn release_hash_id(name: &str, version: &str) -> String {
    let mut hasher = Sha512::new();
    hasher.update(name.as_bytes());
    hasher.update(version.as_bytes());
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    // The exact hash a real posthog-cli dsym upload wrote for the ios-raw example (bundle id
    // `com.posthog.iosraw`, CFBundleShortVersionString `1.0`, CFBundleVersion `1`). Pins byte-for-byte
    // parity with the CLI's content_hash([name, version]): if the packing separator, field order, or
    // hash here ever drifts from the CLI, this release row would stop resolving and this test breaks.
    const IOS_RAW_HASH: &str = "75605cac5268ba4bdc57b4c8336f6686802e88236ae4026418a18cabcde854d1015f18734489b8ec4c71c68773a027e5b880f7278b8ba6864a5334d76ef9eba6";

    #[test]
    fn mobile_hash_matches_a_real_cli_release() {
        assert_eq!(
            mobile_release_hash_id("com.posthog.iosraw", Some("1.0"), Some("1")).as_deref(),
            Some(IOS_RAW_HASH)
        );
    }

    #[test]
    fn mobile_hash_packing_mirrors_the_cli() {
        // version+build, version-only, build-only, and neither must match
        // cli/src/sourcemaps/args.rs::pack_version.
        assert_eq!(
            mobile_release_hash_id("com.app", Some("1.0"), Some("42")),
            Some(release_hash_id("com.app", "1.0+42"))
        );
        assert_eq!(
            mobile_release_hash_id("com.app", Some("1.0"), None),
            Some(release_hash_id("com.app", "1.0"))
        );
        assert_eq!(
            mobile_release_hash_id("com.app", None, Some("42")),
            Some(release_hash_id("com.app", "42"))
        );
        assert_eq!(mobile_release_hash_id("com.app", None, None), None);
    }
}
