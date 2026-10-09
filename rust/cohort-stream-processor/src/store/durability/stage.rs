//! A checkpoint restore in two moves, each safe against a kill.
//!
//! 1. The checkpoint is materialized in a staging directory beside the live store and validated
//!    there. A kill leaves only the stage, which the next boot deletes.
//! 2. Publishing writes a `restore.json` marker into the stage and renames the stage onto the store
//!    path. Until the events group commits the restored positions, the marker keeps every later
//!    boot on the restore path, so a crash never reopens the restored store at the broker's old
//!    offsets.

use std::collections::HashSet;
use std::fs::File;
use std::io;
use std::path::{Path, PathBuf};

use metrics::counter;
use rdkafka::error::{KafkaError, KafkaResult};
use serde::{Deserialize, Serialize};
use tracing::warn;

use super::manifest::OffsetManifest;
use super::metadata::CheckpointMetadata;
use super::restore_plan::{ReplayWindow, RestorePlan};
use crate::observability::metrics::CHECKPOINT_RESTORE_SLICES_RESET_TOTAL;
use crate::partitions::{InputGroups, InputTopic, ResumeOffset};
use crate::store::{CohortStore, StoreError};

/// The marker a published restore carries inside the store directory. RocksDB ignores files it
/// does not name, so the store opens with it in place.
pub const MARKER_FILENAME: &str = "restore.json";

const RECORD_VERSION: u32 = 1;

/// `<store>.restore`: a sibling of the store on the same mount, so a rename publishes it.
pub fn staging_path(live: &Path) -> PathBuf {
    let mut name = live.file_name().unwrap_or_default().to_os_string();
    name.push(".restore");
    live.with_file_name(name)
}

/// Where a restored store came from.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RestoredFrom {
    /// A local checkpoint. Its `metadata.json` describes a plan that may never have been uploaded,
    /// so it is no upload baseline.
    Local { checkpoint_id: String },
    /// An uploaded checkpoint, which the next upload can build on.
    S3 { candidate: CheckpointMetadata },
}

impl RestoredFrom {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Local { .. } => "local",
            Self::S3 { .. } => "s3",
        }
    }

    pub fn checkpoint_id(&self) -> &str {
        match self {
            Self::Local { checkpoint_id } => checkpoint_id,
            Self::S3 { candidate } => &candidate.id,
        }
    }
}

/// What `restore.json` holds. The manifest travels with it, so a resumed restore can check the
/// replay window again.
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RestoreRecord {
    version: u32,
    source: RestoredFrom,
    manifest: OffsetManifest,
}

/// A store materialized in the staging directory that opened read-only, holds every SST its
/// MANIFEST names at the recorded size, and carries this build's schema stamp. Only a validated
/// stage can be published.
#[derive(Debug)]
pub struct ValidatedStage {
    dir: PathBuf,
    source: RestoredFrom,
}

impl ValidatedStage {
    pub fn validate(dir: PathBuf, source: RestoredFrom) -> Result<Self, StoreError> {
        CohortStore::validate_read_only(&dir)?;
        Ok(Self { dir, source })
    }

    pub fn source(&self) -> &RestoredFrom {
        &self.source
    }

    /// Fsyncs the staged files, writes the marker, renames the stage onto `live`, then fsyncs the
    /// parent. A kill at any point leaves either the stage, which the next boot deletes, or a
    /// published store with its marker. `plan` is the window check that admitted the candidate.
    pub fn publish(
        self,
        manifest: OffsetManifest,
        plan: RestorePlan,
        live: &Path,
    ) -> io::Result<PendingRestore> {
        for entry in std::fs::read_dir(&self.dir)? {
            File::open(entry?.path())?.sync_all()?;
        }
        let record = RestoreRecord {
            version: RECORD_VERSION,
            source: self.source,
            manifest,
        };
        let json = serde_json::to_vec_pretty(&record).map_err(io::Error::other)?;
        let staged_marker = self.dir.join(MARKER_FILENAME);
        std::fs::write(&staged_marker, json)?;
        File::open(&staged_marker)?.sync_all()?;
        sync_dir(&self.dir)?;
        std::fs::rename(&self.dir, live)?;
        sync_dir(parent_dir(live))?;
        Ok(PendingRestore {
            marker: live.join(MARKER_FILENAME),
            record,
            plan,
        })
    }
}

/// Hard-links the SSTs of a local checkpoint into a new `stage` and copies every other file.
/// RocksDB never rewrites an SST, so a link costs no space, and the stage shares the store's mount.
pub fn link_checkpoint(checkpoint: &Path, stage: &Path) -> io::Result<()> {
    std::fs::create_dir(stage)?;
    for entry in std::fs::read_dir(checkpoint)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        let target = stage.join(entry.file_name());
        if entry.path().extension().is_some_and(|ext| ext == "sst") {
            std::fs::hard_link(entry.path(), target)?;
        } else {
            std::fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}

#[derive(Debug, thiserror::Error)]
pub enum ResumeError {
    /// Positions are unknown, so the store cannot be trusted: the boot deletes it and restores
    /// again.
    #[error("the restore marker is unreadable")]
    Undecodable(#[source] serde_json::Error),
    #[error("reading the replay window failed")]
    Window(#[source] KafkaError),
    #[error(transparent)]
    Io(#[from] io::Error),
}

/// A published restore whose inputs are not all positioned. `restore.json` keeps every later boot
/// on this path until [`Self::settle`].
#[derive(Debug)]
pub struct PendingRestore {
    marker: PathBuf,
    record: RestoreRecord,
    plan: RestorePlan,
}

impl PendingRestore {
    /// Reads the marker of a store found at boot and re-checks the replay window, because the
    /// broker may have expired more of it since the restore was published. `None` when the store
    /// carries no marker.
    pub(crate) fn resume(
        live: &Path,
        window: &impl ReplayWindow,
        partition_count: u16,
    ) -> Result<Option<Self>, ResumeError> {
        let marker = live.join(MARKER_FILENAME);
        let bytes = match std::fs::read(&marker) {
            Ok(bytes) => bytes,
            Err(err) if err.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(err) => return Err(err.into()),
        };
        let record: RestoreRecord =
            serde_json::from_slice(&bytes).map_err(ResumeError::Undecodable)?;
        if record.version != RECORD_VERSION {
            return Err(ResumeError::Undecodable(serde::de::Error::custom(
                format_args!("restore record version {}", record.version),
            )));
        }
        let plan = RestorePlan::check(&record.manifest, window, partition_count)
            .map_err(ResumeError::Window)?;
        Ok(Some(Self {
            marker,
            record,
            plan,
        }))
    }

    pub fn plan(&self) -> &RestorePlan {
        &self.plan
    }

    pub fn source(&self) -> &RestoredFrom {
        &self.record.source
    }

    /// Commits each follower's planned positions. Safe to repeat: nothing consumes a follower
    /// before the restore settles.
    pub(crate) fn position_followers(&self, groups: &InputGroups) -> KafkaResult<()> {
        for follower in groups.followers() {
            follower.commit(&self.plan.positions(follower.topic()))?;
        }
        Ok(())
    }

    /// Deletes the slices the plan cannot replay. Runs right after the store opens, before anything
    /// reads it.
    // Called once at startup, before any task reads the store, like `CohortStore::open`.
    #[allow(clippy::disallowed_methods)]
    pub(crate) fn reset_slices(&self, store: &CohortStore) -> Result<(), StoreError> {
        store.reset_slices(self.plan.resets().map(|(partition, _)| partition))?;
        for (partition, reason) in self.plan.resets() {
            counter!(CHECKPOINT_RESTORE_SLICES_RESET_TOTAL, "reason" => reason.label())
                .increment(1);
            warn!(
                partition,
                ?reason,
                "checkpoint restore reset a slice it cannot replay; it begins again behind the coverage fence",
            );
        }
        Ok(())
    }

    /// Ends the restore once every position it kept still holds. Each kept position on a partition
    /// in `owned` is checked against its input's low watermark first: the plan was checked before
    /// boot, and a consumer whose position fell below the low watermark since then skips ahead
    /// without a trace. `low_watermarks` reads all of them in one call, because the events consumer
    /// blocks on it within its liveness deadline. It answers in the order it was asked. Then
    /// `commit_events` commits the events group's restored positions, and only then does the marker
    /// go. On any error the marker stays, so the next boot resumes the restore and its window check
    /// resets what expired.
    pub(crate) fn settle(
        &self,
        owned: &HashSet<i32>,
        low_watermarks: impl FnOnce(&[(&InputTopic, u16)]) -> KafkaResult<Vec<i64>>,
        commit_events: impl FnOnce() -> KafkaResult<()>,
    ) -> Result<(), SettleError> {
        let (partitions, positions): (Vec<(&InputTopic, u16)>, Vec<ResumeOffset>) = self
            .plan
            .kept()
            .filter(|&(partition, _, _)| owned.contains(&i32::from(partition)))
            .map(|(partition, topic, position)| ((topic, partition), position))
            .unzip();
        let lows = low_watermarks(&partitions).map_err(SettleError::Watermarks)?;
        let expired: Vec<(InputTopic, u16)> = partitions
            .iter()
            .zip(positions.iter().zip(lows))
            .filter(|&(_, (position, low))| position.get() < low)
            .map(|(&(topic, partition), _)| (topic.clone(), partition))
            .collect();
        if !expired.is_empty() {
            return Err(SettleError::Expired(expired));
        }
        commit_events().map_err(SettleError::Commit)?;
        match std::fs::remove_file(&self.marker) {
            Ok(()) => {}
            Err(err) if err.kind() == io::ErrorKind::NotFound => {}
            Err(err) => return Err(err.into()),
        }
        Ok(sync_dir(parent_dir(&self.marker))?)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum SettleError {
    /// The boot must stop rather than retry: these slices need the next boot's reset.
    #[error("the broker expired restored positions since the restore checked them: {0:?}")]
    Expired(Vec<(InputTopic, u16)>),
    #[error("reading the inputs' low watermarks failed")]
    Watermarks(#[source] KafkaError),
    #[error("committing the events group's restored positions failed")]
    Commit(#[source] KafkaError),
    #[error("deleting the restore marker failed")]
    Io(#[from] io::Error),
}

/// Creates the checkpoint directory and checks that it shares a filesystem with the store: a
/// RocksDB checkpoint and a local restore both hard-link SSTs between the two.
pub fn ensure_one_filesystem(checkpoint_dir: &Path, store_path: &Path) -> io::Result<()> {
    use std::os::unix::fs::MetadataExt;

    let store_parent = parent_dir(store_path);
    std::fs::create_dir_all(checkpoint_dir)?;
    std::fs::create_dir_all(store_parent)?;
    let checkpoint_device = std::fs::metadata(checkpoint_dir)?.dev();
    let store_device = std::fs::metadata(store_parent)?.dev();
    if checkpoint_device != store_device {
        return Err(io::Error::other(format!(
            "{} and {} are on different filesystems; checkpoints hard-link SSTs between them",
            checkpoint_dir.display(),
            store_parent.display(),
        )));
    }
    Ok(())
}

pub(super) fn parent_dir(path: &Path) -> &Path {
    match path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent,
        _ => Path::new("."),
    }
}

pub(super) fn sync_dir(dir: &Path) -> io::Result<()> {
    File::open(dir)?.sync_all()
}

#[cfg(test)]
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use std::cell::Cell;
    use std::collections::{BTreeMap, BTreeSet};

    use rdkafka::types::RDKafkaErrorCode;

    use rdkafka::error::KafkaResult;
    use tempfile::TempDir;

    use crate::partitions::{InputPositions, InputTopic, ResumeOffset};
    use crate::store::durability::lineage::PodOrdinal;
    use crate::store::keyspace::{Behavioral, BehavioralKey, Meta, META_SCHEMA_VERSION};
    use crate::store::{LeafStateKey, StoreConfig};

    const EVENTS: &str = "cohort_stream_events";
    const MERGES: &str = "person_merge_events";

    struct OpenWindow(BTreeSet<InputTopic>);

    impl ReplayWindow for OpenWindow {
        fn inputs(&self) -> &BTreeSet<InputTopic> {
            &self.0
        }

        fn watermarks(
            &self,
            _topic: &InputTopic,
            partition_count: u16,
        ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
            Ok((0..partition_count).map(|p| (p, (0, i64::MAX))).collect())
        }
    }

    fn window() -> OpenWindow {
        OpenWindow(BTreeSet::from([
            InputTopic::new(EVENTS),
            InputTopic::new(MERGES),
        ]))
    }

    /// Slice 0 resumes the events at 42 and the merges at 5.
    fn manifest() -> OffsetManifest {
        let at = |topic: &str, offset: i64| {
            InputPositions::new(
                InputTopic::new(topic),
                BTreeMap::from([(0, ResumeOffset::try_from(offset).unwrap())]),
            )
        };
        OffsetManifest::capture(
            PodOrdinal::STANDALONE,
            &BTreeSet::from([0]),
            vec![at(EVENTS, 42), at(MERGES, 5)],
        )
        .unwrap()
    }

    fn key() -> BehavioralKey {
        BehavioralKey::new(0, 7, uuid::Uuid::from_u128(1), LeafStateKey([0xAB; 16]))
    }

    /// A checkpoint of a store holding one flushed row, so its MANIFEST names at least one SST.
    fn checkpoint(root: &Path) -> PathBuf {
        let store = CohortStore::open(&StoreConfig {
            path: root.join("source"),
            ..StoreConfig::default()
        })
        .unwrap();
        store
            .write_batch(|b| b.put::<Behavioral>(&key(), b"restored"))
            .unwrap();
        store.flush().unwrap();
        let checkpoint = root.join("checkpoint");
        store.create_checkpoint(&checkpoint).unwrap();
        checkpoint
    }

    fn staged(root: &Path) -> PathBuf {
        let stage = staging_path(&root.join("store"));
        link_checkpoint(&checkpoint(root), &stage).unwrap();
        stage
    }

    fn local() -> RestoredFrom {
        RestoredFrom::Local {
            checkpoint_id: "2026-10-09T16-00-00-000Z".to_string(),
        }
    }

    #[test]
    fn a_stage_missing_an_sst_its_manifest_names_fails_validation() {
        let root = TempDir::new().unwrap();
        let stage = staged(root.path());
        let sst = std::fs::read_dir(&stage)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .find(|path| path.extension().is_some_and(|ext| ext == "sst"))
            .expect("the checkpoint holds an SST");
        std::fs::remove_file(&sst).unwrap();
        let missing = sst.file_name().unwrap().to_string_lossy().into_owned();

        let err = ValidatedStage::validate(stage, local()).unwrap_err();
        assert!(
            matches!(err, StoreError::Open { .. }) && err.to_string().contains(&missing),
            "{err:?}"
        );
    }

    #[test]
    fn a_stage_with_another_schema_stamp_fails_validation() {
        let root = TempDir::new().unwrap();
        let stage = staged(root.path());
        {
            let store = CohortStore::open(&StoreConfig {
                path: stage.clone(),
                ..StoreConfig::default()
            })
            .unwrap();
            store
                .write_batch(|b| b.put::<Meta>(&META_SCHEMA_VERSION, &0u32.to_be_bytes()))
                .unwrap();
        }

        let err = ValidatedStage::validate(stage, local()).unwrap_err();
        assert!(
            matches!(err, StoreError::SchemaMismatch { found: Some(0), .. }),
            "{err:?}"
        );
    }

    #[test]
    fn a_published_restore_settles_only_when_its_positions_hold_and_the_events_group_commits() {
        let root = TempDir::new().unwrap();
        let live = root.path().join("store");
        let stage = staged(root.path());
        let plan = RestorePlan::check(&manifest(), &window(), 1).unwrap();

        let published = ValidatedStage::validate(stage.clone(), local())
            .unwrap()
            .publish(manifest(), plan.clone(), &live)
            .unwrap();
        assert!(!stage.exists());
        let store = CohortStore::open(&StoreConfig {
            path: live.clone(),
            ..StoreConfig::default()
        })
        .unwrap();
        assert_eq!(
            store.get_behavioral(&key()).unwrap().as_deref(),
            Some(b"restored".as_slice())
        );
        drop(store);

        let resumed = PendingRestore::resume(&live, &window(), 1)
            .unwrap()
            .expect("the marker survives the store's open");
        assert_eq!(resumed.plan(), &plan);
        assert_eq!(resumed.source(), &local());

        let owned: HashSet<i32> = HashSet::from([0]);
        let merges = InputTopic::new(MERGES);
        let low = |events: i64, merge_low: i64| {
            let merges = merges.clone();
            move |partitions: &[(&InputTopic, u16)]| -> KafkaResult<Vec<i64>> {
                Ok(partitions
                    .iter()
                    .map(|&(topic, _)| if *topic == merges { merge_low } else { events })
                    .collect())
            }
        };
        // Every position at its low watermark still replays.
        let held = low(42, 5);
        let merges_expired = low(42, 6);
        let committed = Cell::new(false);
        let commit = || {
            committed.set(true);
            Ok(())
        };
        assert!(matches!(
            published.settle(&owned, &merges_expired, commit),
            Err(SettleError::Expired(ref expired)) if expired == &[(merges.clone(), 0)]
        ));
        assert!(
            !committed.get(),
            "an expired follower position stops the settle before any commit"
        );

        let refused = || Err(KafkaError::OffsetFetch(RDKafkaErrorCode::RequestTimedOut));
        assert!(matches!(
            published.settle(&HashSet::new(), low(i64::MAX, i64::MAX), refused),
            Err(SettleError::Commit(_)),
        ));
        assert!(matches!(
            published.settle(&owned, &held, refused),
            Err(SettleError::Commit(_))
        ));
        assert!(
            PendingRestore::resume(&live, &window(), 1)
                .unwrap()
                .is_some(),
            "a restore that did not settle is still pending",
        );

        published.settle(&owned, &held, || Ok(())).unwrap();
        assert!(PendingRestore::resume(&live, &window(), 1)
            .unwrap()
            .is_none());
    }
}
