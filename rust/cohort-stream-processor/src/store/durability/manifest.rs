//! The multi-partition offset manifest for the disaster-recovery layer.
//!
//! A RocksDB `Checkpoint` is a whole-DB snapshot, so one checkpoint freezes every partition's state
//! at once. On restore the DB content is materialized, but Kafka still needs to know where to resume
//! each topic-partition. The processor keeps one DB per process spanning up to 64 partitions across
//! four topics, so the resume positions live here, in a sibling `offsets.json` written alongside the
//! checkpoint.
//!
//! [`capture`](OffsetManifest::capture) records [`OffsetTracker::committed_offset`] (the offset Kafka
//! last acked), not the processed position, which can outrun the fsync'd state under the async WAL.
//! The committed offset is `<= durable`: the events consumer fsyncs the WAL before every offset
//! commit, so seeking a restored DB to its committed offset re-folds the gap `[committed, processed]`
//! idempotently via per-key `AppliedOffsets` — no loss, no double-count.

use std::collections::BTreeMap;
use std::path::Path;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::partitions::OffsetTracker;

/// Filename of the offset manifest, written as a sibling of the RocksDB checkpoint files and tracked
/// by the planner like any other file, so it rides the S3 upload/restore.
pub const MANIFEST_FILENAME: &str = "offsets.json";

/// Current on-disk shape version, bumped on any structural change to [`OffsetManifest`]. Decode is
/// strict: a manifest whose `version` does not match is rejected, so a format skew surfaces as a
/// restore failure (fall through to S3 / cold-start) instead of a mis-seek.
pub const MANIFEST_VERSION: u32 = 1;

/// The per-process resume positions captured alongside a whole-DB checkpoint: for each topic, the
/// next offset to consume on each owned partition.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OffsetManifest {
    /// On-disk shape version; see [`MANIFEST_VERSION`].
    pub version: u32,
    /// When this manifest was captured (the checkpoint's logical instant).
    pub captured_at: DateTime<Utc>,
    /// `topic -> { partition -> next-offset-to-consume }`. A `BTreeMap` keeps the serialized JSON
    /// deterministic, so the SHA256 the planner computes over non-SST files stays stable across
    /// captures with identical content.
    pub topics: BTreeMap<String, BTreeMap<i32, i64>>,
}

impl OffsetManifest {
    /// Capture the committed positions of every owned partition across the supplied trackers.
    ///
    /// For each `(topic, tracker)` and each partition in `owned`, records
    /// `topics[topic][partition] = committed_offset` only when the tracker has a committed offset for
    /// that partition. A partition the tracker has never seen (an idle follower, or a topic that
    /// never produced to this pod) is absent — inert on restore (nothing to seek).
    pub fn capture(owned: &[i32], trackers: &[(&str, &OffsetTracker)]) -> Self {
        let mut topics: BTreeMap<String, BTreeMap<i32, i64>> = BTreeMap::new();
        for (topic, tracker) in trackers {
            let mut per_partition: BTreeMap<i32, i64> = BTreeMap::new();
            for &partition in owned {
                if let Some(offset) = tracker.committed_offset(partition) {
                    per_partition.insert(partition, offset);
                }
            }
            topics.insert((*topic).to_string(), per_partition);
        }
        Self {
            version: MANIFEST_VERSION,
            captured_at: Utc::now(),
            topics,
        }
    }

    /// The next-offset-to-consume for one `(topic, partition)`, if present.
    pub fn offset_for(&self, topic: &str, partition: i32) -> Option<i64> {
        self.topics
            .get(topic)
            .and_then(|partitions| partitions.get(&partition).copied())
    }

    /// Load the manifest from `<dir>/offsets.json`. Strict-decodes: a missing file, malformed JSON,
    /// or a `version` other than [`MANIFEST_VERSION`] is an error (the caller treats the source as
    /// unusable and falls through).
    pub fn load_from_dir(dir: &Path) -> Result<Self> {
        let path = dir.join(MANIFEST_FILENAME);
        let bytes = std::fs::read(&path)
            .with_context(|| format!("reading offset manifest from {path:?}"))?;
        let manifest: Self = serde_json::from_slice(&bytes)
            .with_context(|| format!("parsing offset manifest from {path:?}"))?;
        if manifest.version != MANIFEST_VERSION {
            anyhow::bail!(
                "offset manifest at {path:?} has version {} but this build expects {MANIFEST_VERSION}",
                manifest.version,
            );
        }
        Ok(manifest)
    }

    /// Write the manifest to `<dir>/offsets.json` atomically (tmp file + rename) so a concurrent
    /// reader never observes a torn file.
    pub fn write_to_dir(&self, dir: &Path) -> Result<()> {
        let json = serde_json::to_vec_pretty(self).context("serializing offset manifest")?;
        let path = dir.join(MANIFEST_FILENAME);
        let tmp_path = dir.join(".offsets.json.tmp");
        if let Err(e) = std::fs::write(&tmp_path, &json) {
            // Best-effort cleanup of the partial tmp file before propagating the write error.
            drop(std::fs::remove_file(&tmp_path));
            return Err(e).with_context(|| format!("writing temp offset manifest to {tmp_path:?}"));
        }
        // rename(2) atomically replaces the destination on Unix.
        std::fs::rename(&tmp_path, &path)
            .with_context(|| format!("renaming temp offset manifest to {path:?}"))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::partitions::MarkOutcome;
    use tempfile::TempDir;

    fn capture_one(owned: &[i32], topic: &str, tracker: &OffsetTracker) -> OffsetManifest {
        OffsetManifest::capture(owned, &[(topic, tracker)])
    }

    #[test]
    fn manifest_round_trips_through_a_dir() {
        let dir = TempDir::new().unwrap();
        let mut topics = BTreeMap::new();
        topics.insert(
            "cohort_stream_events".to_string(),
            BTreeMap::from([(0, 100), (3, 250)]),
        );
        topics.insert("person_merge_events".to_string(), BTreeMap::from([(0, 7)]));
        let manifest = OffsetManifest {
            version: MANIFEST_VERSION,
            captured_at: Utc::now(),
            topics,
        };

        manifest.write_to_dir(dir.path()).unwrap();
        let loaded = OffsetManifest::load_from_dir(dir.path()).unwrap();
        assert_eq!(loaded, manifest);
        assert_eq!(loaded.offset_for("cohort_stream_events", 3), Some(250));
        assert_eq!(loaded.offset_for("cohort_stream_events", 1), None);
        assert_eq!(loaded.offset_for("person_merge_events", 0), Some(7));
    }

    #[test]
    fn capture_uses_committed_not_committable() {
        // `capture` must record the committed (durable) offset, not the processed one — recording
        // processed could seek past un-fsynced state on restore and silently skip events.
        let tracker = OffsetTracker::new();
        let partition = 5;
        tracker.mark_dispatched(partition, 1000);
        assert_eq!(
            tracker.mark_processed(partition, 1000),
            MarkOutcome::WithinDispatch,
        );
        tracker.mark_committed(partition, 400);

        let manifest = capture_one(&[partition], "cohort_stream_events", &tracker);
        assert_eq!(
            manifest.offset_for("cohort_stream_events", partition),
            Some(400),
            "capture must record the committed offset (400), not the processed one (1000)",
        );
    }

    #[test]
    fn capture_omits_an_absent_follower() {
        let owned = [0, 1, 2];
        let idle = OffsetTracker::new();
        let manifest = capture_one(&owned, "person_merge_events", &idle);
        let inner = manifest
            .topics
            .get("person_merge_events")
            .expect("topic recorded even when empty");
        assert!(
            inner.is_empty(),
            "an idle follower's topic maps to an empty inner map",
        );
        for partition in owned {
            assert_eq!(manifest.offset_for("person_merge_events", partition), None);
        }
    }

    #[test]
    fn capture_records_present_follower_offsets() {
        let owned = [3, 7];
        let merge = OffsetTracker::new();
        let transfer = OffsetTracker::new();
        let cascade = OffsetTracker::new();
        for (tracker, base) in [(&merge, 10), (&transfer, 20), (&cascade, 30)] {
            for (partition, bump) in [(3, 1), (7, 2)] {
                let offset = base + bump;
                tracker.mark_dispatched(partition, offset);
                let _ = tracker.mark_processed(partition, offset);
                tracker.mark_committed(partition, offset);
            }
        }

        let manifest = OffsetManifest::capture(
            &owned,
            &[
                ("person_merge_events", &merge),
                ("cohort_merge_state_transfer", &transfer),
                ("cohort_cascade_events", &cascade),
            ],
        );

        for (topic, base) in [
            ("person_merge_events", 10),
            ("cohort_merge_state_transfer", 20),
            ("cohort_cascade_events", 30),
        ] {
            let inner = manifest.topics.get(topic).expect("follower topic recorded");
            assert!(!inner.is_empty(), "{topic} follower map must be non-empty");
            assert_eq!(inner.len(), 2, "{topic} records both owned partitions");
            assert_eq!(manifest.offset_for(topic, 3), Some(base + 1));
            assert_eq!(manifest.offset_for(topic, 7), Some(base + 2));
        }
    }

    #[test]
    fn capture_records_only_owned_partitions() {
        // Partitions committed in the tracker but not in `owned` must not appear in the manifest.
        let tracker = OffsetTracker::new();
        for partition in [0, 1, 9] {
            tracker.mark_dispatched(partition, 50);
            let _ = tracker.mark_processed(partition, 50);
            tracker.mark_committed(partition, 50);
        }
        let manifest = capture_one(&[0, 1], "cohort_stream_events", &tracker);
        let inner = manifest.topics.get("cohort_stream_events").unwrap();
        assert_eq!(inner.len(), 2);
        assert_eq!(manifest.offset_for("cohort_stream_events", 0), Some(50));
        assert_eq!(manifest.offset_for("cohort_stream_events", 1), Some(50));
        assert_eq!(manifest.offset_for("cohort_stream_events", 9), None);
    }

    #[test]
    fn capture_spans_multiple_topics() {
        let events = OffsetTracker::new();
        events.mark_dispatched(0, 100);
        let _ = events.mark_processed(0, 100);
        events.mark_committed(0, 100);

        let merges = OffsetTracker::new();
        merges.mark_dispatched(0, 5);
        let _ = merges.mark_processed(0, 5);
        merges.mark_committed(0, 5);

        let manifest = OffsetManifest::capture(
            &[0],
            &[
                ("cohort_stream_events", &events),
                ("person_merge_events", &merges),
            ],
        );
        assert_eq!(manifest.offset_for("cohort_stream_events", 0), Some(100));
        assert_eq!(manifest.offset_for("person_merge_events", 0), Some(5));
    }

    #[test]
    fn a_version_mismatch_fails_to_decode() {
        let dir = TempDir::new().unwrap();
        let json = serde_json::json!({
            "version": MANIFEST_VERSION + 1,
            "captured_at": Utc::now(),
            "topics": { "cohort_stream_events": { "0": 100 } },
        });
        std::fs::write(
            dir.path().join(MANIFEST_FILENAME),
            serde_json::to_vec(&json).unwrap(),
        )
        .unwrap();

        let err = OffsetManifest::load_from_dir(dir.path()).unwrap_err();
        assert!(
            err.to_string().contains("version"),
            "version-mismatch error should mention version: {err}",
        );
    }

    #[test]
    fn a_missing_manifest_fails_to_load() {
        let dir = TempDir::new().unwrap();
        assert!(
            OffsetManifest::load_from_dir(dir.path()).is_err(),
            "load on a dir with no offsets.json must error",
        );
    }
}
