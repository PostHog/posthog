use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha512};
use sqlx::Executor;
use uuid::Uuid;

use crate::symbolication::symbol_store::saving::truncate_ref;

/// The release API does not bound what a row can hold (`version`/`project`/`metadata` are
/// unbounded TextField/JSONField columns), but every one of these fields is embedded into every
/// matching exception event, so a single oversized row would be amplified across the whole event
/// stream after capture's per-event size limit has already been enforced. Clamping at fetch keeps
/// events bounded and cache entries small enough for an entry-count budget. 8 KiB of metadata is
/// ~25x what the CLI writes (a git object), and 255 chars fits any semver, commit SHA, or bundle
/// identifier many times over.
pub const MAX_RELEASE_METADATA_BYTES: usize = 8 * 1024;
pub const MAX_RELEASE_TEXT_CHARS: usize = 255;

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

        Ok(row.map(Self::clamped))
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

        Ok(row.map(Self::clamped))
    }

    /// The newest release bound to any of `symbol_set_refs`, as an id. One query per exception
    /// replaces the per-frame join the resolver used to run, and the id is all the caller needs:
    /// it re-reads the row through its own release cache.
    ///
    /// Ties break on id so a stack spanning two releases created in the same instant still picks
    /// deterministically.
    pub async fn latest_id_for_symbol_set_refs<'c, E>(
        e: E,
        symbol_set_refs: &[String],
        team_id: i32,
    ) -> Result<Option<Uuid>, sqlx::Error>
    where
        E: Executor<'c, Database = sqlx::Postgres>,
    {
        // Stored refs are truncated to MAX_REF_BYTES by SymbolSetRecord::load/save; match on the
        // same truncated value or long refs (e.g. >2KB JS source URLs) never join.
        let refs: Vec<String> = symbol_set_refs
            .iter()
            .map(|r| truncate_ref(r).to_string())
            .collect();

        sqlx::query_scalar!(
            r#"
            SELECT r.id
            FROM posthog_errortrackingsymbolset ss
            INNER JOIN posthog_errortrackingrelease r ON ss.release_id = r.id
            WHERE ss.ref = ANY($1) AND ss.team_id = $2
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT 1
            "#,
            &refs,
            team_id
        )
        .fetch_optional(e)
        .await
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

    /// The most recently created release, with ties broken by id so the pick is deterministic
    /// regardless of input order.
    pub fn latest(releases: impl IntoIterator<Item = Self>) -> Option<Self> {
        releases
            .into_iter()
            .max_by_key(|release| (release.created_at, release.id))
    }

    /// Bounds every field this record can carry into an event: `metadata` over the cap is
    /// dropped, `version`/`project` are truncated. The `id` survives, so consumers can still
    /// fetch the full release.
    fn clamped(mut self) -> Self {
        let oversized = self.metadata.as_ref().is_some_and(|metadata| {
            serde_json::to_string(metadata).map_or(true, |s| s.len() > MAX_RELEASE_METADATA_BYTES)
        });
        if oversized {
            self.metadata = None;
        }
        truncate_chars(&mut self.version, MAX_RELEASE_TEXT_CHARS);
        truncate_chars(&mut self.project, MAX_RELEASE_TEXT_CHARS);
        self
    }
}

fn truncate_chars(value: &mut String, max_chars: usize) {
    if let Some((byte_index, _)) = value.char_indices().nth(max_chars) {
        value.truncate(byte_index);
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

/// Split a packed release version back into the app version and the build number, inverting
/// `pack_version`. Splitting on the last `+` recovers the build from a version that itself carries
/// semver build metadata, such as `1.0.0+sha.abc` built as `1.0.0+sha.abc+42`.
///
/// The inverse is lossy in the one direction `pack_version` is: a release packed from a build
/// alone is a bare build string on the way back out, and comes back as a version with no build.
pub fn unpack_version(packed: &str) -> (&str, Option<&str>) {
    match packed.rsplit_once('+') {
        Some((version, build)) if !version.is_empty() && !build.is_empty() => {
            (version, Some(build))
        }
        _ => (packed, None),
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

    #[test]
    fn unpack_version_recovers_the_build_pack_version_folded_in() {
        // (packed version, app version, build number)
        let cases: [(&str, &str, Option<&str>); 5] = [
            ("1.0+42", "1.0", Some("42")),
            // Splitting on the last `+` is what keeps semver build metadata with the version.
            ("1.0.0+sha.abc+42", "1.0.0+sha.abc", Some("42")),
            ("2.3", "2.3", None),
            // A version whose own metadata reads as a build number: the packing is ambiguous, and
            // the build wins so a real `--build` is never dropped.
            ("1.0.0+sha.abc", "1.0.0", Some("sha.abc")),
            // An empty half is not a build, or events would carry an empty `$app_build`.
            ("1.0+", "1.0+", None),
        ];

        for (packed, version, build) in cases {
            assert_eq!(
                unpack_version(packed),
                (version, build),
                "unpacking {packed}"
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
    fn oversized_fields_are_clamped_but_sane_fields_survive() {
        // The API does not bound these fields, and each is embedded into every matching event;
        // without the clamp one oversized release row would inflate the whole event stream.
        let mut big = record(Some(json!({"git": {"commit_id": "x".repeat(100_000)}})));
        big.version = "v".repeat(10_000);
        big.project = "é".repeat(10_000);
        let clamped = big.clamped();
        assert_eq!(clamped.metadata, None);
        assert_eq!(clamped.version.chars().count(), MAX_RELEASE_TEXT_CHARS);
        assert_eq!(clamped.project.chars().count(), MAX_RELEASE_TEXT_CHARS);

        let small_value = json!({"git": {"commit_id": "abc123"}});
        let small = record(Some(small_value.clone())).clamped();
        assert_eq!(small.metadata, Some(small_value));
        assert_eq!(small.version, "1.0");
    }
}
