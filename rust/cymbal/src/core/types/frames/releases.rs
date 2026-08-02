use std::collections::HashSet;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha512};
use sqlx::Executor;
use uuid::Uuid;

use super::Frame;

// Serialized only on the internal resolution-service wire (`Done.releases_json`), never into the
// clickhouse-bound event JSON — `Frame.release` stays `#[serde(skip)]`.
#[derive(Debug, Clone, Eq, PartialEq, Serialize, Deserialize)]
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

    pub fn to_info(&self) -> ReleaseInfo {
        ReleaseInfo {
            project: self.project.clone(),
            version: self.version.clone(),
            timestamp: self.created_at,
            metadata: self.metadata.clone(),
        }
    }

    /// Distinct releases attached to the given frames, deduped by release id, in first-seen order.
    pub fn collect_from_frames<'a>(frames: impl Iterator<Item = &'a Frame>) -> Vec<Self> {
        let mut seen = HashSet::new();
        let mut out = Vec::new();
        for release in frames.filter_map(|f| f.release.as_ref()) {
            if seen.insert(release.id) {
                out.push(release.clone());
            }
        }
        out
    }

    /// The most recently created release, with ties broken by id so the pick is deterministic
    /// regardless of frame order.
    pub fn latest(releases: impl IntoIterator<Item = Self>) -> Option<Self> {
        releases
            .into_iter()
            .max_by_key(|release| (release.created_at, release.id))
    }

    /// Rough in-memory footprint, for the release cache's weigher. `metadata` is a free-form
    /// JSON column any client can write, so it dominates and is the only reason this exists —
    /// without it a cache bounded on entry count would be unbounded in bytes. Only has to be
    /// proportional to the real cost, not exact.
    pub fn approx_size_bytes(&self) -> usize {
        size_of::<Self>()
            + self.hash_id.len()
            + self.version.len()
            + self.project.len()
            + self.metadata.as_ref().map_or(0, json_size_bytes)
    }
}

/// Heap bytes held by a `Value`, ignoring the inline scalars already counted by `size_of`.
///
/// The recursion is bounded: these values are decoded by `serde_json`, which enforces its own
/// nesting limit while parsing, so a hostile `metadata` column can't drive this deep enough to
/// overflow the stack.
fn json_size_bytes(value: &Value) -> usize {
    match value {
        Value::Null | Value::Bool(_) | Value::Number(_) => 0,
        Value::String(s) => s.len(),
        Value::Array(items) => {
            items.len() * size_of::<Value>() + items.iter().map(json_size_bytes).sum::<usize>()
        }
        Value::Object(entries) => entries
            .iter()
            .map(|(key, val)| key.len() + size_of::<Value>() + json_size_bytes(val))
            .sum(),
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
    fn size_estimate_tracks_metadata_payload() {
        // The cache weigher is only a real memory bound if the estimate actually grows with the
        // free-form `metadata` column. Returning a constant here (or ignoring nested strings)
        // would silently restore the unbounded-by-entry-count behavior the weigher replaced.
        let blob = "x".repeat(100_000);
        let bare = record(None).approx_size_bytes();
        let nested = record(Some(json!({"git": {"commit_id": blob}}))).approx_size_bytes();

        assert!(
            nested >= bare + 100_000,
            "nested metadata under-counted: {nested} vs {bare}"
        );
    }
}
