//! A check that the loaded snapshot is current, without a LIST of `_delta_log/`.
//!
//! Two requests, issued together, replace the listing:
//!
//! - a GET of the commit file after the loaded version. Delta versions are contiguous
//!   and a commit file is never written twice, so a 404 for `version + 1` proves that
//!   no newer version exists.
//! - a HEAD of a commit file that the last load read (the [`LogAnchor`]). A table that
//!   was deleted and created again also answers 404 for `version + 1`, but its log
//!   holds other objects, so the anchor is absent or has another ETag.
//!
//! The 404 is proof only while log cleanup cannot have removed `version + 1`. Cleanup
//! removes a commit file when it is older than the table's log retention, so the caller
//! must stop trusting the probe long before that time has passed since it last listed
//! the log (see [`trust_window`]).
//!
//! The probe depends on a store that answers a GET or HEAD with the current state of the
//! object: S3 (strongly consistent for reads after a write or a delete), the local file
//! system and the in-memory store. A store or a cache in front of it that can answer 404
//! for an object that exists must run with `DELTALITE_PROBE_REFRESH=0`.

use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use deltalake::logstore::LogStore;
use object_store::path::Path;
use object_store::{ObjectMeta, ObjectStore, ObjectStoreExt};

/// The longest time the probe is trusted after the last LIST of the log.
pub(crate) const MAX_TRUST_WINDOW: Duration = Duration::from_secs(600);

/// How long after a LIST the probe is proof, for a table with log retention `retention`.
/// Half the retention leaves a margin for clock differences between the writers, and
/// [`MAX_TRUST_WINDOW`] bounds the time that an error in this argument can stay hidden.
pub(crate) fn trust_window(retention: Duration) -> Duration {
    (retention / 2).min(MAX_TRUST_WINDOW)
}

/// The identity of one commit file as the store reported it on a read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LogAnchor {
    pub(crate) version: u64,
    pub(crate) path: Path,
    pub(crate) e_tag: String,
    pub(crate) last_modified: DateTime<Utc>,
}

impl LogAnchor {
    /// The anchor for the commit file that `meta` describes. `None` when the path is not
    /// a commit file or the store gives no ETag, because then nothing identifies the
    /// object.
    pub(crate) fn from_meta(meta: &ObjectMeta) -> Option<Self> {
        Some(Self {
            version: commit_version(&meta.location)?,
            path: meta.location.clone(),
            e_tag: meta.e_tag.clone()?,
            last_modified: meta.last_modified,
        })
    }

    fn matches(&self, meta: &ObjectMeta) -> bool {
        meta.e_tag.as_deref() == Some(self.e_tag.as_str())
            && meta.last_modified == self.last_modified
    }
}

/// What the probe found.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LogProbe {
    /// The table is the one that was loaded and it has no newer version.
    Current,
    /// The table is the one that was loaded and it has a newer version.
    NewCommits,
    /// The anchor is gone or is another object: the table was replaced, or cleanup
    /// removed the anchor. The loaded snapshot must not be used.
    Replaced,
    /// A request failed. The caller must use the LIST.
    Unknown,
}

impl LogProbe {
    /// Static metric label.
    pub(crate) fn label(self) -> &'static str {
        match self {
            LogProbe::Current => "current",
            LogProbe::NewCommits => "new_commits",
            LogProbe::Replaced => "replaced",
            LogProbe::Unknown => "unknown",
        }
    }
}

/// Whether the table still holds the object that `anchor` describes.
pub(crate) async fn check_anchor(store: &Arc<dyn ObjectStore>, anchor: &LogAnchor) -> LogProbe {
    match store.head(&anchor.path).await {
        Ok(meta) if anchor.matches(&meta) => LogProbe::Current,
        Ok(_) | Err(object_store::Error::NotFound { .. }) => LogProbe::Replaced,
        Err(_) => LogProbe::Unknown,
    }
}

/// GET `next_commit` (the commit file after the loaded version) and check `anchor`, in
/// one round trip.
pub(crate) async fn probe_log(
    store: &Arc<dyn ObjectStore>,
    next_commit: &Path,
    anchor: &LogAnchor,
) -> LogProbe {
    let (next, identity) = tokio::join!(store.get(next_commit), check_anchor(store, anchor));
    match (identity, next) {
        (LogProbe::Current, Err(object_store::Error::NotFound { .. })) => LogProbe::Current,
        (LogProbe::Current, Ok(_)) => LogProbe::NewCommits,
        (LogProbe::Current, Err(_)) => LogProbe::Unknown,
        (other, _) => other,
    }
}

/// The store path of the commit file for `version` under `log_store`'s log root.
pub(crate) fn commit_path(log_store: &dyn LogStore, version: u64) -> Option<Path> {
    let root = Path::from_url_path(log_store.root_url().path()).ok()?;
    Some(root.join("_delta_log").join(format!("{version:020}.json")))
}

/// The version that a commit file path names: `_delta_log/<20 digits>.json`.
pub(crate) fn commit_version(location: &Path) -> Option<u64> {
    let in_log = location.parts().any(|part| part.as_ref() == "_delta_log");
    let name = location.filename()?;
    let digits = name.strip_suffix(".json")?;
    if !in_log || digits.len() != 20 || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;
    use object_store::memory::InMemory;
    use object_store::PutPayload;

    use super::*;

    const ANCHOR: &str = "t/_delta_log/00000000000000000004.json";
    const NEXT: &str = "t/_delta_log/00000000000000000006.json";

    async fn put(store: &Arc<dyn ObjectStore>, path: &str, body: &'static str) {
        store
            .put(&Path::from(path), PutPayload::from_bytes(Bytes::from(body)))
            .await
            .unwrap();
    }

    async fn anchored() -> (Arc<dyn ObjectStore>, LogAnchor) {
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        put(&store, ANCHOR, "four").await;
        let meta = store.head(&Path::from(ANCHOR)).await.unwrap();
        (store, LogAnchor::from_meta(&meta).unwrap())
    }

    async fn probe(store: &Arc<dyn ObjectStore>, anchor: &LogAnchor) -> LogProbe {
        probe_log(store, &Path::from(NEXT), anchor).await
    }

    #[test]
    fn only_commit_files_have_a_version() {
        for (path, version) in [
            ("t/_delta_log/00000000000000000004.json", Some(4)),
            ("_delta_log/00000000000000012345.json", Some(12345)),
            ("t/_delta_log/00000000000000000004.checkpoint.parquet", None),
            ("t/_delta_log/_last_checkpoint", None),
            ("t/_delta_log/0000000000000000004.json", None),
            ("t/_delta_log/0000000000000000000a.json", None),
            ("t/p=1/00000000000000000004.json", None),
        ] {
            assert_eq!(commit_version(&Path::from(path)), version, "{path}");
        }
    }

    #[test]
    fn an_object_without_an_etag_is_no_anchor() {
        let meta = ObjectMeta {
            location: Path::from(ANCHOR),
            last_modified: Utc::now(),
            size: 4,
            e_tag: None,
            version: None,
        };
        assert_eq!(LogAnchor::from_meta(&meta), None);
    }

    #[test]
    fn the_trust_window_follows_a_short_retention() {
        let day = Duration::from_secs(86_400);
        assert_eq!(trust_window(30 * day), MAX_TRUST_WINDOW);
        assert_eq!(
            trust_window(Duration::from_secs(60)),
            Duration::from_secs(30)
        );
        assert_eq!(trust_window(Duration::ZERO), Duration::ZERO);
    }

    #[tokio::test]
    async fn an_untouched_log_is_current_until_the_next_commit_exists() {
        let (store, anchor) = anchored().await;
        assert_eq!(probe(&store, &anchor).await, LogProbe::Current);
        put(&store, NEXT, "six").await;
        assert_eq!(probe(&store, &anchor).await, LogProbe::NewCommits);
    }

    #[tokio::test]
    async fn a_deleted_or_rewritten_anchor_is_a_replaced_table() {
        let (store, anchor) = anchored().await;
        put(&store, ANCHOR, "another table").await;
        assert_eq!(probe(&store, &anchor).await, LogProbe::Replaced);
        put(&store, NEXT, "six").await;
        assert_eq!(
            probe(&store, &anchor).await,
            LogProbe::Replaced,
            "a newer commit of another table must not look like progress"
        );
        store.delete(&Path::from(ANCHOR)).await.unwrap();
        assert_eq!(check_anchor(&store, &anchor).await, LogProbe::Replaced);
    }
}
