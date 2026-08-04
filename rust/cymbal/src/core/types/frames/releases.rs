use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha512};
use sqlx::Executor;
use uuid::Uuid;

/// Kept in sync with MAX_METADATA_BYTES in the release API
/// (products/error_tracking/backend/presentation/views/releases.py). The API rejects larger
/// metadata on write; rows predating the cap (or written outside it) are clamped at fetch so a
/// single oversized release can't be amplified into every matching event, and so cache entries
/// stay small enough for an entry-count budget.
pub const MAX_RELEASE_METADATA_BYTES: usize = 8 * 1024;

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

// The info, as written to clickhouse at the exception level. The scalar fields are a
// point-in-time snapshot; `id` references the release row so consumers can re-fetch the
// current values if the release is later edited via the API.
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

        Ok(row.map(Self::with_clamped_metadata))
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

        Ok(row.map(Self::with_clamped_metadata))
    }

    pub fn to_info(&self) -> ReleaseInfo {
        ReleaseInfo {
            id: self.id,
            project: self.project.clone(),
            version: self.version.clone(),
            timestamp: self.created_at,
            metadata: self.metadata.clone(),
        }
    }

    /// Drops `metadata` when its serialized form exceeds the cap the API enforces on new writes.
    /// The `id` survives, so consumers can still fetch the full release.
    fn with_clamped_metadata(mut self) -> Self {
        let oversized = self.metadata.as_ref().is_some_and(|metadata| {
            serde_json::to_string(metadata).map_or(true, |s| s.len() > MAX_RELEASE_METADATA_BYTES)
        });
        if oversized {
            self.metadata = None;
        }
        self
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
    use serde_json::json;

    /// Golden vectors pinning the release `hash_id`: `content_hash([name, pack_version(version,
    /// build)])`. Identical to the CLI's `release_hash_id_golden_vectors` test in
    /// `cli/src/sourcemaps/args.rs`. The CLI computes this hash when it creates a release and cymbal
    /// reconstructs it from a mobile event's app metadata, so these literals must stay the same on
    /// both sides or mobile releases silently stop resolving. Keep the two tests in sync.
    #[test]
    fn release_hash_id_golden_vectors() {
        // (name, version, build, expected hash_id)
        let cases: [(&str, Option<&str>, Option<&str>, &str); 4] = [
            (
                "com.posthog.iosraw",
                Some("1.0"),
                Some("1"),
                "75605cac5268ba4bdc57b4c8336f6686802e88236ae4026418a18cabcde854d1015f18734489b8ec4c71c68773a027e5b880f7278b8ba6864a5334d76ef9eba6",
            ),
            (
                "com.example.app",
                Some("1.0"),
                Some("42"),
                "5a7f7b504d81759fa4e15f8b3bbc77c694a9dc222cfcd06c801fae9619076e97909edf651087106af331aea76463449f015ccc41ccacbf19148329b1c2c35aa7",
            ),
            (
                "com.example.app",
                Some("2.3"),
                None,
                "09aeeb69b914985562d4aa39d13033abf0f90c753ef90b0148cb06b8aeadca7dd1dd853fa24c7cc51d18cf251bb7348eae58906347a217a98d74ba7ca5673b66",
            ),
            (
                "com.example.app",
                None,
                Some("99"),
                "5e925a3f2e9349f64ab88eede466b641a7332dc79d6f1901d931fb659704a0475fa77a3ca25c0a60b2919547de8d94117fbcc52448e83aa72787a3fe35f725ae",
            ),
        ];

        for (name, version, build, expected) in cases {
            assert_eq!(
                mobile_release_hash_id(name, version, build).as_deref(),
                Some(expected),
                "release hash_id drift for {name} {version:?}+{build:?}"
            );
        }
    }

    fn record(metadata: Option<Value>) -> ReleaseRecord {
        ReleaseRecord {
            id: Uuid::nil(),
            team_id: 1,
            hash_id: "hash".to_string(),
            created_at: Utc::now(),
            version: "1.0".to_string(),
            project: "com.app".to_string(),
            metadata,
        }
    }

    #[test]
    fn oversized_metadata_is_clamped_but_small_metadata_survives() {
        // Rows predating the API's write-time cap can hold multi-megabyte metadata; without the
        // clamp every matching event would embed it, re-opening the amplification the cap closed.
        let big = record(Some(json!({"git": {"commit_id": "x".repeat(100_000)}})));
        assert_eq!(big.with_clamped_metadata().metadata, None);

        let small_value = json!({"git": {"commit_id": "abc123"}});
        let small = record(Some(small_value.clone()));
        assert_eq!(small.with_clamped_metadata().metadata, Some(small_value));
    }
}
