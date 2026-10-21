//! Boot-time choice of the live store, run before `CohortStore::open`.
//!
//! ## Order
//!
//! 1. A leftover staging directory from a killed restore is deleted.
//! 2. **Reopened.** An intact live store reopens. If it carries a restore marker, the restore it
//!    published is still pending and resumes instead. A reshard child that is taking its
//!    partitions over discards a live store without a marker, because its parent advanced them.
//! 3. With checkpoints enabled, candidates are tried newest first, the freshest local checkpoint
//!    before S3. A reshard child that is taking over searches only its parent's S3 lineage. A
//!    candidate restores on any pod whose partitions its split covers. The first one that
//!    publishes wins.
//! 4. **Created.** Nothing is restorable: no candidate, or only unusable ones. Every slice then
//!    begins when its worker spawns, behind the coverage fence.
//!
//! A candidate that fails, and any listing or local error, blocks the boot instead of creating the
//! store: a created store would quietly drop the history the checkpoint holds. The boot retries
//! until the operator fixes the cause or turns checkpoints off.

use std::collections::HashSet;
use std::io;
use std::ops::ControlFlow;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use metrics::{counter, gauge, histogram};
use rdkafka::error::KafkaError;
use tracing::{error, info, warn};

use super::checkpoint::{UploadBaseline, UPLOADED_FILENAME};
use super::import::{CheckpointImporter, ImportError};
use super::lineage::CheckpointLineage;
use super::manifest::{ManifestError, OffsetManifest};
use super::metadata::{CheckpointMetadata, MetadataError, METADATA_FILENAME};
use super::restore_plan::{ReplayWindow, RestorePlan};
use super::stage::{
    link_checkpoint, parent_dir, staging_path, sync_dir, PendingRestore, RestoredFrom, ResumeError,
    ValidatedStage,
};
use super::{DirCleanupGuard, S3Downloader};
use crate::config::Config;
use crate::observability::metrics::{
    CHECKPOINT_RESTORE_BLOCKED, CHECKPOINT_RESTORE_CANDIDATES_TOTAL,
    CHECKPOINT_RESTORE_DURATION_SECONDS, CHECKPOINT_RESTORE_TOTAL,
};
use crate::partitions::{AdmittedSplit, InputGroups, InputTopic, PartitionOwnership, StoreSource};
use crate::store::{CohortStore, StoreError, STORE_SCHEMA_VERSION};

pub(crate) const RETRY_START: Duration = Duration::from_secs(30);
pub(crate) const RETRY_MAX: Duration = Duration::from_secs(300);

/// Where the live store came from.
#[derive(Debug)]
enum BootStore {
    /// The live store reopened. The groups' commits are its positions.
    Reopened,
    /// A checkpoint is published at the store path. Nothing folds until the restore finishes.
    Restored(Box<PendingRestore>),
    /// No store and nothing usable to restore. Every slice begins when its worker spawns.
    Created,
}

#[derive(Debug, thiserror::Error)]
enum RestoreBlocked {
    #[error("listing checkpoints failed")]
    Listing(#[source] anyhow::Error),
    #[error("no checkpoint candidate restored: {0:?}")]
    Candidates(Vec<CandidateFailure>),
    #[error("reading or committing input positions failed")]
    Positions(#[source] KafkaError),
    #[error("staging or publishing the restore failed")]
    Local(#[source] io::Error),
}

#[derive(Debug)]
struct CandidateFailure {
    checkpoint_id: String,
    reason: String,
}

impl CandidateFailure {
    fn new(checkpoint_id: &str, reason: impl std::fmt::Display) -> Self {
        Self {
            checkpoint_id: checkpoint_id.to_owned(),
            reason: format!("{reason:#}"),
        }
    }
}

#[derive(Debug)]
enum Verdict {
    Published(PendingRestore),
    Unusable(Unusable),
    Failed(CandidateFailure),
    /// Its download outlasted the import timeout. Older candidates are about as large, so the
    /// search stops instead of downloading each of them for as long.
    TimedOut(CandidateFailure),
}

/// Candidates that no retry can restore. Older candidates are no better, so a search that finds
/// only these creates the store.
#[derive(Debug, thiserror::Error)]
enum Unusable {
    #[error("its upload never wrote metadata.json")]
    Unfinished,
    #[error("store schema {found}, and COHORT_WIPE_ON_SCHEMA_MISMATCH passes over it")]
    SchemaMismatch { found: u32 },
    #[error("metadata format {found}")]
    MetadataFormat { found: u32 },
    #[error("manifest format {found}")]
    ManifestFormat { found: u32 },
    #[error("the broker no longer holds what it lacks on any partition this pod owns")]
    NothingToReplay,
    #[error("its manifest's split, {found}, does not cover this pod's partitions")]
    OtherSplit { found: PartitionOwnership },
}

/// A candidate whose stage failed validation, so later rounds fail it without downloading it
/// again. A local attempt and its S3 upload share one id, so the source is part of the key.
#[derive(Debug, PartialEq, Eq, Hash)]
enum Rejected {
    Local(String),
    S3(String),
}

impl Rejected {
    fn of(source: &RestoredFrom) -> Self {
        match source {
            RestoredFrom::Local { checkpoint_id } => Self::Local(checkpoint_id.clone()),
            RestoredFrom::S3 { candidate } => Self::S3(candidate.id.clone()),
        }
    }
}

fn failed(checkpoint_id: &str, reason: impl std::fmt::Display) -> Verdict {
    Verdict::Failed(CandidateFailure::new(checkpoint_id, reason))
}

/// The live store's rule: a store of another schema blocks the boot unless the operator allowed
/// wiping it.
fn schema_mismatch(checkpoint_id: &str, found: u32, wipe_on_schema_mismatch: bool) -> Verdict {
    if wipe_on_schema_mismatch {
        Verdict::Unusable(Unusable::SchemaMismatch { found })
    } else {
        failed(
            checkpoint_id,
            format_args!(
                "store schema {found}, this build writes {STORE_SCHEMA_VERSION}; set \
                 COHORT_WIPE_ON_SCHEMA_MISMATCH=true to pass over it"
            ),
        )
    }
}

/// The failed candidates of one search, newest first.
#[derive(Debug, Default)]
struct Search {
    failed: Vec<CandidateFailure>,
}

impl Search {
    /// Breaks with the restore once a candidate publishes, so no older candidate is downloaded.
    fn record(&mut self, verdict: Verdict) -> ControlFlow<Box<PendingRestore>> {
        let label = match &verdict {
            Verdict::Published(_) => "published",
            Verdict::Unusable(_) => "unusable",
            Verdict::Failed(_) | Verdict::TimedOut(_) => "failed",
        };
        counter!(CHECKPOINT_RESTORE_CANDIDATES_TOTAL, "verdict" => label).increment(1);
        match verdict {
            Verdict::Published(pending) => ControlFlow::Break(Box::new(pending)),
            Verdict::Unusable(reason) => {
                info!(%reason, "passing over an unusable checkpoint");
                ControlFlow::Continue(())
            }
            Verdict::Failed(failure) | Verdict::TimedOut(failure) => {
                warn!(
                    checkpoint = %failure.checkpoint_id,
                    reason = %failure.reason,
                    "checkpoint candidate failed",
                );
                self.failed.push(failure);
                ControlFlow::Continue(())
            }
        }
    }

    /// With nothing published, any failure blocks; only unusable candidates, or none at all, create
    /// the store.
    fn conclude(self) -> Result<BootStore, RestoreBlocked> {
        if self.failed.is_empty() {
            Ok(BootStore::Created)
        } else {
            Err(RestoreBlocked::Candidates(self.failed))
        }
    }
}

/// The store this boot runs on: reopened, restored or created, with a restore's unreplayable slices
/// reset. A restore comes back with it, for the events consumer to finish before anything folds.
///
/// A restore that cannot finish blocks here, retrying with backoff, until the operator fixes the
/// cause or turns checkpoints off. `lineage` is this pod's own, and `None` when checkpoints are
/// disabled. The store refuses to open when it was written under a split that does not cover the
/// one `admitted`.
pub async fn open_store(
    config: &Config,
    admitted: &AdmittedSplit,
    lineage: Option<CheckpointLineage>,
    groups: Arc<InputGroups>,
) -> Result<(CohortStore, Option<PendingRestore>), StoreError> {
    let boot = restore_until_ready(config.clone(), admitted.clone(), lineage, groups).await;

    // A published restore leaves a store at the path, so `effective_wipe_on_start` keeps it.
    let store_config = config.store_config(admitted.ownership());
    info!(
        durable_restore_enabled = config.durable_restore_enabled,
        wipe_store_on_start = config.wipe_store_on_start,
        effective_wipe = store_config.wipe_on_start,
        store_path = %config.store_path,
        mode = if store_config.wipe_on_start { "wipe+replay" } else { "reopen-live" },
        "opening RocksDB state store",
    );
    let store = CohortStore::open(&store_config)?;
    let restore = match boot {
        BootStore::Restored(pending) => {
            pending.reset_slices(&store)?;
            Some(*pending)
        }
        BootStore::Reopened | BootStore::Created => None,
    };
    Ok((store, restore))
}

/// Retries [`prepare_store`] with backoff until the boot has a store. For a restore, it waits until
/// the fence admits `admitted`'s split again, then positions the follower groups on the partitions
/// the split owns before returning it.
///
/// The restore runs on a blocking thread: staging, validation and the Kafka position calls block,
/// and the health server must keep answering meanwhile. A SIGTERM here kills the process; staging
/// survives a kill.
async fn restore_until_ready(
    config: Config,
    admitted: AdmittedSplit,
    lineage: Option<CheckpointLineage>,
    groups: Arc<InputGroups>,
) -> BootStore {
    let runtime = tokio::runtime::Handle::current();
    let restore = tokio::task::spawn_blocking(move || {
        runtime.block_on(async {
            let mut rejected = HashSet::new();
            // Every round measures the candidate windows up to the first round's start. If the
            // windows moved, a candidate that failed could leave them between rounds, and a round
            // that finds nothing creates the store without the history the checkpoint holds.
            let searched_at = Utc::now();
            let mut backoff = RETRY_START;
            loop {
                let started = Instant::now();
                let attempt = match prepare_store(
                    &config,
                    admitted.source(),
                    admitted.ownership(),
                    lineage,
                    groups.as_ref(),
                    searched_at,
                    &mut rejected,
                )
                .await
                {
                    Ok((BootStore::Restored(pending), source)) => {
                        // Another split can claim while the restore runs, so the boot's admission
                        // no longer covers the follower commits.
                        let admitted =
                            AdmittedSplit::admit(admitted.split_claim(), groups.clone()).await;
                        pending
                            .position_followers(&groups, &admitted)
                            .map(|()| (BootStore::Restored(pending), source))
                            .map_err(RestoreBlocked::Positions)
                    }
                    other => other,
                };
                match attempt {
                    Ok((store, source)) => {
                        gauge!(CHECKPOINT_RESTORE_BLOCKED).set(0.0);
                        return prepared(store, source, started);
                    }
                    Err(blocked) => {
                        gauge!(CHECKPOINT_RESTORE_BLOCKED).set(1.0);
                        error!(
                            error = format!("{:#}", anyhow::Error::new(blocked)),
                            retry_in_secs = backoff.as_secs(),
                            "boot restore blocked; fix the cause, or set CHECKPOINT_ENABLED=false to \
                             create the store behind the coverage fence",
                        );
                        tokio::time::sleep(backoff).await;
                        backoff = (backoff * 2).min(RETRY_MAX);
                    }
                }
            }
        })
    });
    match restore.await {
        Ok(store) => store,
        Err(err) => std::panic::resume_unwind(err.into_panic()),
    }
}

/// Decide where the live store comes from, and materialize it for a restore. Returns the store with
/// its `source` label for `checkpoint_restore_total`. The local staleness window and the S3 listing
/// window both end at `searched_at`. `rejected` holds the candidates that failed validation after
/// their download, so a later round fails them without downloading them again.
///
/// Blocks on file and Kafka I/O; see [`restore_until_ready`].
async fn prepare_store(
    config: &Config,
    source: StoreSource,
    ownership: PartitionOwnership,
    lineage: Option<CheckpointLineage>,
    window: &impl ReplayWindow,
    searched_at: DateTime<Utc>,
    rejected: &mut HashSet<Rejected>,
) -> Result<(BootStore, &'static str), RestoreBlocked> {
    let live = PathBuf::from(&config.store_path);
    let stage = staging_path(&live);
    remove_dir_if_present(&stage).map_err(RestoreBlocked::Local)?;

    if !config.effective_wipe_on_start() && live_store_is_intact(&live) {
        match PendingRestore::resume(&live, window, config.partition_count()) {
            Ok(Some(pending)) => return Ok((BootStore::Restored(Box::new(pending)), "pending")),
            Ok(None) => match source {
                StoreSource::Own => return Ok((BootStore::Reopened, "reopen_live")),
                StoreSource::TakeOver { parent } => {
                    warn!(
                        %parent,
                        store = %live.display(),
                        "taking the partitions over from the parent, which advanced them since this \
                         store; deleting the store",
                    );
                    discard_live_store(&live, &stage).map_err(RestoreBlocked::Local)?;
                }
            },
            Err(ResumeError::Undecodable(err)) => {
                warn!(
                    error = %err,
                    store = %live.display(),
                    "the pending restore's marker is unreadable, so its positions are unknown; \
                     deleting the store and restoring again",
                );
                discard_live_store(&live, &stage).map_err(RestoreBlocked::Local)?;
            }
            Err(ResumeError::Window(err)) => return Err(RestoreBlocked::Positions(err)),
            Err(ResumeError::Io(err)) => return Err(RestoreBlocked::Local(err)),
        }
    }

    let Some(lineage) = lineage else {
        return Ok((BootStore::Created, "cold"));
    };
    // A store directory without `CURRENT` is a torn leftover; the rename that publishes a restore
    // needs the path free.
    remove_dir_if_present(&live).map_err(RestoreBlocked::Local)?;

    let durability = config.durability_config();
    let local_dir = lineage.local_dir(Path::new(&durability.local_checkpoint_dir));
    let mut restore = Restore {
        live: &live,
        stage,
        uploaded: local_dir.join(UPLOADED_FILENAME),
        s3_bucket: &durability.s3_bucket,
        ownership,
        events_topic: InputTopic::new(&config.cohort_stream_events_topic),
        window,
        wipe_on_schema_mismatch: config.cohort_wipe_on_schema_mismatch,
        rejected,
    };
    let mut search = Search::default();

    let (local, searched, s3_label) = match source {
        StoreSource::Own => (
            newest_fresh_local_checkpoint(
                &local_dir,
                durability.local_checkpoint_max_staleness,
                searched_at,
            ),
            lineage,
            "s3",
        ),
        // The local directory holds only this pod's own lineage.
        StoreSource::TakeOver { parent } => {
            (None, CheckpointLineage::new(parent.ordinal()), "parent_s3")
        }
    };
    if let Some(attempt) = local {
        let verdict = match attempt {
            Ok(attempt) => restore.local(attempt)?,
            Err(failure) => Verdict::Failed(failure),
        };
        if let ControlFlow::Break(pending) = search.record(verdict) {
            return Ok((BootStore::Restored(pending), "local"));
        }
    }

    let downloader = S3Downloader::new(&durability, searched)
        .await
        .map_err(RestoreBlocked::Listing)?;
    let importer =
        CheckpointImporter::new(Box::new(downloader), durability.checkpoint_import_timeout);
    if let ControlFlow::Break(pending) = restore
        .search_s3(
            &importer,
            durability.checkpoint_import_attempt_depth,
            searched_at,
            &mut search,
        )
        .await?
    {
        return Ok((BootStore::Restored(pending), s3_label));
    }
    search.conclude().map(|store| (store, "cold"))
}

fn prepared(store: BootStore, source: &'static str, started: Instant) -> BootStore {
    counter!(CHECKPOINT_RESTORE_TOTAL, "source" => source).increment(1);
    histogram!(CHECKPOINT_RESTORE_DURATION_SECONDS).record(started.elapsed().as_secs_f64());
    info!(
        source,
        elapsed_secs = started.elapsed().as_secs_f64(),
        "boot store prepared"
    );
    store
}

/// What the window check says about a candidate.
enum Admission {
    Replays(RestorePlan),
    Rejected(Unusable),
}

/// A complete local checkpoint attempt: both its manifest and its `metadata.json`, which the
/// sweeper writes last, decode.
struct LocalAttempt {
    dir: PathBuf,
    manifest: OffsetManifest,
    metadata: CheckpointMetadata,
}

/// One round's restore of candidates into the staging directory.
struct Restore<'a, W> {
    live: &'a Path,
    stage: PathBuf,
    /// The lineage's `uploaded.json`, which a publish rewrites.
    uploaded: PathBuf,
    s3_bucket: &'a str,
    /// This pod's split. A candidate restores only when its split covers it.
    ownership: PartitionOwnership,
    events_topic: InputTopic,
    window: &'a W,
    wipe_on_schema_mismatch: bool,
    rejected: &'a mut HashSet<Rejected>,
}

impl<W: ReplayWindow> Restore<'_, W> {
    fn local(&mut self, attempt: LocalAttempt) -> Result<Verdict, RestoreBlocked> {
        let LocalAttempt {
            dir,
            manifest,
            metadata,
        } = attempt;
        let source = RestoredFrom::Local {
            checkpoint_id: metadata.id.clone(),
        };
        if self.rejected.contains(&Rejected::of(&source)) {
            return Ok(failed(
                &metadata.id,
                "failed validation earlier in this process",
            ));
        }
        if let Some(verdict) = self.admit(&metadata.id, metadata.store_schema, &manifest)? {
            return Ok(verdict);
        }

        let guard = DirCleanupGuard::new(self.stage.clone());
        if let Err(err) = link_checkpoint(&dir, &self.stage) {
            return Ok(failed(
                &metadata.id,
                format_args!("linking its files into the stage failed: {err}"),
            ));
        }
        self.publish(guard, source, manifest)
    }

    /// Tries the S3 candidates newest first, up to `depth` of them. An unfinished upload does not
    /// count toward the depth, so a run of failed uploads cannot hide a complete one behind it.
    /// Neither does a candidate whose split does not cover this pod: a reshard child that starts
    /// late passes over its parent's checkpoints from after the reshard.
    async fn search_s3(
        &mut self,
        importer: &CheckpointImporter,
        depth: usize,
        searched_at: DateTime<Utc>,
        search: &mut Search,
    ) -> Result<ControlFlow<Box<PendingRestore>>, RestoreBlocked> {
        let candidates = importer
            .candidates(searched_at)
            .await
            .map_err(RestoreBlocked::Listing)?;
        let mut tried = 0;
        for metadata_key in &candidates {
            if tried == depth {
                break;
            }
            let verdict = self.s3(importer, metadata_key).await?;
            if !matches!(
                verdict,
                Verdict::Unusable(Unusable::Unfinished | Unusable::OtherSplit { .. })
            ) {
                tried += 1;
            }
            let timed_out = matches!(verdict, Verdict::TimedOut(_));
            if let ControlFlow::Break(pending) = search.record(verdict) {
                return Ok(ControlFlow::Break(pending));
            }
            if timed_out {
                break;
            }
        }
        Ok(ControlFlow::Continue(()))
    }

    async fn s3(
        &mut self,
        importer: &CheckpointImporter,
        metadata_key: &str,
    ) -> Result<Verdict, RestoreBlocked> {
        let checkpoint_id = metadata_key.rsplit('/').nth(1).unwrap_or(metadata_key);
        if self
            .rejected
            .contains(&Rejected::S3(checkpoint_id.to_owned()))
        {
            return Ok(failed(
                checkpoint_id,
                "failed validation earlier in this process",
            ));
        }
        let metadata = match importer.metadata(metadata_key).await {
            Ok(metadata) => metadata,
            Err(ImportError::Unfinished) => return Ok(Verdict::Unusable(Unusable::Unfinished)),
            Err(ImportError::Metadata(MetadataError::UnsupportedFormat { found })) => {
                return Ok(Verdict::Unusable(Unusable::MetadataFormat { found }))
            }
            Err(err) => return Ok(failed(checkpoint_id, err)),
        };
        let manifest = match importer.manifest(&metadata).await {
            Ok(manifest) => manifest,
            Err(ImportError::Manifest(ManifestError::UnsupportedFormat { found })) => {
                return Ok(Verdict::Unusable(Unusable::ManifestFormat { found }))
            }
            Err(err) => return Ok(failed(checkpoint_id, err)),
        };
        if let Some(verdict) = self.admit(checkpoint_id, metadata.store_schema, &manifest)? {
            return Ok(verdict);
        }

        std::fs::create_dir(&self.stage).map_err(RestoreBlocked::Local)?;
        let guard = DirCleanupGuard::new(self.stage.clone());
        match importer.fetch_files(&metadata, &self.stage).await {
            Ok(()) => {}
            Err(err @ ImportError::Timeout(_)) => {
                return Ok(Verdict::TimedOut(CandidateFailure::new(checkpoint_id, err)))
            }
            Err(err) => return Ok(failed(checkpoint_id, err)),
        }
        self.publish(
            guard,
            RestoredFrom::S3 {
                candidate: metadata,
            },
            manifest,
        )
    }

    /// The checks that run before a candidate's bulk download. `Some` is the candidate's verdict.
    fn admit(
        &self,
        checkpoint_id: &str,
        store_schema: u32,
        manifest: &OffsetManifest,
    ) -> Result<Option<Verdict>, RestoreBlocked> {
        // Before the schema check: a candidate of another split never restores on this pod, so a
        // schema mismatch must not fail it and block the boot.
        if !manifest.split().covers(&self.ownership) {
            return Ok(Some(Verdict::Unusable(Unusable::OtherSplit {
                found: manifest.split(),
            })));
        }
        if store_schema != STORE_SCHEMA_VERSION {
            return Ok(Some(schema_mismatch(
                checkpoint_id,
                store_schema,
                self.wipe_on_schema_mismatch,
            )));
        }
        // An input the manifest lacks resumes from its group's commit. For the events group that
        // commit lies past the checkpoint, so the restore would skip the events between.
        if !manifest.inputs().contains(&self.events_topic) {
            return Ok(Some(failed(
                checkpoint_id,
                format_args!("its manifest records no position on {}", self.events_topic),
            )));
        }
        // The plan this check builds is dropped: the one that publishes is checked after the
        // download.
        match self.replay_plan(manifest)? {
            Admission::Replays(_) => Ok(None),
            Admission::Rejected(reason) => Ok(Some(Verdict::Unusable(reason))),
        }
    }

    /// The window check.
    fn replay_plan(&self, manifest: &OffsetManifest) -> Result<Admission, RestoreBlocked> {
        let plan = RestorePlan::check(manifest, self.window, self.ownership.partition_count())
            .map_err(RestoreBlocked::Positions)?;
        if !plan.resumes_any(&self.ownership) {
            // Older candidates hold older positions, which the broker deletes first, so retrying
            // cannot help.
            return Ok(Admission::Rejected(Unusable::NothingToReplay));
        }
        Ok(Admission::Replays(plan))
    }

    fn publish(
        &mut self,
        guard: DirCleanupGuard,
        source: RestoredFrom,
        manifest: OffsetManifest,
    ) -> Result<Verdict, RestoreBlocked> {
        let checkpoint_id = source.checkpoint_id().to_owned();
        let rejected = Rejected::of(&source);
        let staged = match ValidatedStage::validate(self.stage.clone(), source) {
            Ok(staged) => staged,
            Err(err) => {
                self.rejected.insert(rejected);
                return Ok(failed(&checkpoint_id, err));
            }
        };
        // Checked again because the broker can delete positions while the candidate downloads.
        let plan = match self.replay_plan(&manifest)? {
            Admission::Replays(plan) => plan,
            Admission::Rejected(reason) => return Ok(Verdict::Unusable(reason)),
        };
        self.reset_upload_baseline(staged.source())
            .map_err(RestoreBlocked::Local)?;
        let pending = staged
            .publish(manifest, plan, self.live)
            .map_err(RestoreBlocked::Local)?;
        guard.defuse();
        info!(
            checkpoint = %checkpoint_id,
            source = pending.source().label(),
            resets = pending.plan().resets().count(),
            "checkpoint restore published",
        );
        Ok(Verdict::Published(pending))
    }

    /// A restored DB reuses the SST numbers written after its checkpoint, so an `uploaded.json` from
    /// a later upload would name files it rewrites. An uploaded checkpoint becomes the baseline;
    /// after a local one the next upload is full. The directory is synced before the publish, because
    /// a crash could otherwise keep the published store beside the old baseline.
    fn reset_upload_baseline(&self, source: &RestoredFrom) -> io::Result<()> {
        match source {
            RestoredFrom::S3 { candidate } => {
                std::fs::create_dir_all(parent_dir(&self.uploaded))?;
                UploadBaseline::save(&self.uploaded, self.s3_bucket, candidate.clone())
            }
            RestoredFrom::Local { .. } => match std::fs::remove_file(&self.uploaded) {
                Err(err) if err.kind() != io::ErrorKind::NotFound => Err(err),
                _ => Ok(()),
            },
        }?;
        sync_dir(parent_dir(&self.uploaded))
    }
}

/// Renames the live store to the stage before deleting it, because a deletion cut short could leave
/// `CURRENT` without the marker, which would reopen at the broker's old offsets. The next boot
/// deletes a leftover stage.
fn discard_live_store(live: &Path, stage: &Path) -> io::Result<()> {
    std::fs::rename(live, stage)?;
    remove_dir_if_present(stage)
}

/// True when `path` is an opened RocksDB store: the directory holds `CURRENT`, RocksDB's manifest
/// pointer. A directory without it is torn and never reopens.
fn live_store_is_intact(path: &Path) -> bool {
    path.is_dir() && path.join("CURRENT").is_file()
}

fn remove_dir_if_present(path: &Path) -> io::Result<()> {
    match std::fs::remove_dir_all(path) {
        Ok(()) => {
            info!(path = %path.display(), "removed a leftover directory before choosing the store");
            Ok(())
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(err),
    }
}

/// The newest attempt under `lineage_dir` whose id is within `max_staleness` before `now`. An older
/// one is distrusted, because the broker has likely moved past what it would replay. An attempt cut
/// short before its `metadata.json`, or written in a format this build does not read, is passed
/// over for the one before. Any other unreadable file fails the attempt, and so does a listing error
/// other than a missing `lineage_dir`, so the boot blocks instead of creating a store without the
/// history the attempt may hold.
fn newest_fresh_local_checkpoint(
    lineage_dir: &Path,
    max_staleness: Duration,
    now: DateTime<Utc>,
) -> Option<Result<LocalAttempt, CandidateFailure>> {
    let listed = std::fs::read_dir(lineage_dir).and_then(|entries| {
        entries
            .map(|entry| Ok(entry?.path()))
            .collect::<io::Result<Vec<_>>>()
    });
    let paths = match listed {
        Ok(paths) => paths,
        Err(err) if err.kind() == io::ErrorKind::NotFound => return None,
        Err(err) => {
            return Some(Err(CandidateFailure::new(
                &lineage_dir.to_string_lossy(),
                format_args!("listing local checkpoints failed: {err}"),
            )))
        }
    };
    paths
        .into_iter()
        .filter(|path| path.is_dir())
        .filter_map(|dir| {
            let id = dir.file_name()?.to_str()?.to_owned();
            let attempted = CheckpointMetadata::parse_id(&id)?;
            // A future-dated attempt (clock skew) has no positive age and counts as fresh.
            let fresh = now
                .signed_duration_since(attempted)
                .to_std()
                .map_or(true, |age| age <= max_staleness);
            if !fresh {
                return None;
            }
            let metadata = match CheckpointMetadata::load(&dir.join(METADATA_FILENAME)) {
                Ok(metadata) => metadata,
                Err(MetadataError::Io(err)) if err.kind() == io::ErrorKind::NotFound => {
                    return None
                }
                Err(MetadataError::UnsupportedFormat { .. }) => return None,
                Err(err) => return Some((attempted, Err(CandidateFailure::new(&id, err)))),
            };
            let attempt = match OffsetManifest::load_from_dir(&dir) {
                Ok(manifest) => Ok(LocalAttempt {
                    dir,
                    manifest,
                    metadata,
                }),
                Err(ManifestError::UnsupportedFormat { .. }) => return None,
                Err(err) => Err(CandidateFailure::new(&id, err)),
            };
            Some((attempted, attempt))
        })
        .max_by_key(|(attempted, _)| *attempted)
        .map(|(_, attempt)| attempt)
}

#[cfg(test)]
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use std::cell::Cell;
    use std::collections::{BTreeMap, BTreeSet, HashMap};

    use async_trait::async_trait;
    use envconfig::Envconfig;
    use rdkafka::error::KafkaResult;
    use rdkafka::types::RDKafkaErrorCode;
    use tempfile::TempDir;
    use tokio_util::sync::CancellationToken;

    use crate::partitions::{InputPositions, InputTopic, OwnedPositions, ResumeOffset};
    use crate::store::durability::lineage::PodOrdinal;
    use crate::store::durability::stage::MARKER_FILENAME;
    use crate::store::durability::{CheckpointDownloader, CheckpointInfo};
    use crate::store::StoreConfig;

    const EVENTS: &str = "cohort_stream_events";

    /// Every partition holds `[low, i64::MAX]`, and a `None` low fails the read.
    struct FixedWindow {
        inputs: BTreeSet<InputTopic>,
        low: Option<i64>,
    }

    impl ReplayWindow for FixedWindow {
        fn inputs(&self) -> &BTreeSet<InputTopic> {
            &self.inputs
        }

        fn watermarks(
            &self,
            _topic: &InputTopic,
            partition_count: u16,
        ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
            let low = self
                .low
                .ok_or(KafkaError::OffsetFetch(RDKafkaErrorCode::RequestTimedOut))?;
            Ok((0..partition_count).map(|p| (p, (low, i64::MAX))).collect())
        }
    }

    fn window_at(low: Option<i64>) -> FixedWindow {
        FixedWindow {
            inputs: BTreeSet::from([InputTopic::new(EVENTS)]),
            low,
        }
    }

    fn window() -> FixedWindow {
        window_at(Some(0))
    }

    /// Pod `ordinal` of `pods`, over two partitions.
    fn split(pods: u16, ordinal: u16) -> PartitionOwnership {
        PartitionOwnership::new(
            std::num::NonZeroU16::new(pods).unwrap(),
            PodOrdinal::from(ordinal),
            2,
        )
        .unwrap()
    }

    fn failure() -> Verdict {
        failed("2026-10-09T16-00-00-000Z", "download failed")
    }

    #[test]
    fn only_unusable_candidates_or_none_create_the_store_and_any_failure_blocks() {
        let cases: [(&str, Vec<Verdict>, bool); 6] = [
            ("no candidate", vec![], true),
            (
                "only unusable",
                vec![
                    Verdict::Unusable(Unusable::NothingToReplay),
                    Verdict::Unusable(Unusable::ManifestFormat { found: 1 }),
                ],
                true,
            ),
            (
                "a failure among unusable ones",
                vec![
                    Verdict::Unusable(Unusable::NothingToReplay),
                    failure(),
                    Verdict::Unusable(Unusable::MetadataFormat { found: 0 }),
                ],
                false,
            ),
            ("one failure", vec![failure()], false),
            (
                "a schema mismatch the operator lets the boot wipe",
                vec![schema_mismatch("id", STORE_SCHEMA_VERSION - 1, true)],
                true,
            ),
            (
                "a schema mismatch without the wipe flag",
                vec![schema_mismatch("id", STORE_SCHEMA_VERSION - 1, false)],
                false,
            ),
        ];
        for (name, verdicts, creates) in cases {
            let mut search = Search::default();
            for verdict in verdicts {
                assert!(search.record(verdict).is_continue(), "{name}");
            }
            match search.conclude() {
                Ok(BootStore::Created) => assert!(creates, "{name}"),
                Err(RestoreBlocked::Candidates(failures)) => {
                    assert!(!creates, "{name}");
                    assert!(!failures.is_empty(), "{name}");
                }
                other => panic!("{name}: {other:?}"),
            }
        }
    }

    struct Boot {
        root: TempDir,
        config: Config,
        ownership: PartitionOwnership,
    }

    impl Boot {
        fn new() -> Self {
            let root = TempDir::new().unwrap();
            let mut config = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
            config.checkpoint_enabled = true;
            config.durable_restore_enabled = true;
            config.wipe_store_on_start = true;
            config.cohort_partition_count = 1;
            config.store_path = root.path().join("store").to_string_lossy().into_owned();
            config.checkpoint_local_dir = root.path().join("ckpt").to_string_lossy().into_owned();
            Self {
                root,
                config,
                ownership: PartitionOwnership::single(1),
            }
        }

        fn of(ownership: PartitionOwnership) -> Self {
            let mut boot = Self::new();
            boot.config.cohort_partition_count = u32::from(ownership.partition_count());
            boot.ownership = ownership;
            boot
        }

        fn live(&self) -> PathBuf {
            PathBuf::from(&self.config.store_path)
        }

        fn lineage_dir(&self) -> PathBuf {
            CheckpointLineage::new(PodOrdinal::STANDALONE)
                .local_dir(Path::new(&self.config.checkpoint_local_dir))
        }

        /// A checkpoint attempt under `parent`, captured at `at` by `split`, laid out as the
        /// sweeper lays it out: the RocksDB files, `offsets.json`, then `metadata.json`. Every slice
        /// the split owns resumes the events at 42. Returns its metadata.
        fn checkpoint_attempt(
            &self,
            parent: &Path,
            split: PartitionOwnership,
            at: DateTime<Utc>,
        ) -> CheckpointMetadata {
            let store = CohortStore::open(&StoreConfig {
                path: self.root.path().join("source"),
                ..StoreConfig::default()
            })
            .unwrap();
            std::fs::create_dir_all(parent).unwrap();
            let metadata =
                CheckpointMetadata::new(split.ordinal(), at, store.db_identity().unwrap());
            let dir = parent.join(&metadata.id);
            store.create_checkpoint(&dir).unwrap();
            let slices: BTreeSet<u16> = split.partitions().collect();
            let events = InputPositions::new(
                InputTopic::new(EVENTS),
                slices
                    .iter()
                    .map(|&partition| (partition, ResumeOffset::try_from(42).unwrap()))
                    .collect(),
            );
            OffsetManifest::capture(&slices, OwnedPositions::for_test(split, vec![events]))
                .unwrap()
                .write_to_dir(&dir)
                .unwrap();
            metadata.save(&dir.join(METADATA_FILENAME)).unwrap();
            metadata
        }

        fn local_checkpoint(&self) -> CheckpointMetadata {
            self.checkpoint_attempt(&self.lineage_dir(), self.ownership, Utc::now())
        }

        /// A checkpoint by `split` at `at`, uploaded to the objects of `s3`. Returns its id and
        /// metadata key.
        fn upload(
            &self,
            s3: &mut HashMap<String, PathBuf>,
            split: PartitionOwnership,
            at: DateTime<Utc>,
        ) -> (String, String) {
            let parent = self.root.path().join("uploaded");
            let mut metadata = self.checkpoint_attempt(&parent, split, at);
            let dir = parent.join(&metadata.id);
            let mut info = CheckpointInfo::new(metadata.clone(), "checkpoints".to_string());
            for entry in std::fs::read_dir(&dir).unwrap() {
                let path = entry.unwrap().path();
                let name = path.file_name().unwrap().to_string_lossy().into_owned();
                if name != METADATA_FILENAME {
                    info.metadata
                        .track_file(info.get_file_key(&name), String::new());
                    s3.insert(info.get_file_key(&name), path);
                }
            }
            metadata.files = info.metadata.files.clone();
            let metadata_file = parent.join(format!("{}-metadata.json", metadata.id));
            metadata.save(&metadata_file).unwrap();
            s3.insert(info.get_metadata_key(), metadata_file);
            (metadata.id, info.get_metadata_key())
        }

        /// An uploaded checkpoint, listed after a newer attempt whose upload never finished.
        fn uploaded_checkpoint(&self) -> (FakeS3, String) {
            let mut objects = HashMap::new();
            let (id, key) = self.upload(&mut objects, self.ownership, Utc::now());
            let metadata = CheckpointMetadata::load(&objects[&key]).unwrap();

            let unfinished = CheckpointInfo::new(
                CheckpointMetadata::new(
                    PodOrdinal::STANDALONE,
                    metadata.attempt_timestamp + chrono::Duration::minutes(15),
                    metadata.db_identity.clone(),
                ),
                "checkpoints".to_string(),
            );
            let listing = vec![unfinished.get_metadata_key(), key];
            let s3 = FakeS3 {
                listing,
                objects,
                stalled: false,
            };
            (s3, id)
        }

        fn restore<'a, W: ReplayWindow>(
            &'a self,
            window: &'a W,
            rejected: &'a mut HashSet<Rejected>,
        ) -> Restore<'a, W> {
            Restore {
                live: Path::new(&self.config.store_path),
                stage: staging_path(Path::new(&self.config.store_path)),
                uploaded: self.lineage_dir().join(UPLOADED_FILENAME),
                s3_bucket: &self.config.checkpoint_s3_bucket,
                ownership: self.ownership,
                events_topic: InputTopic::new(EVENTS),
                window,
                wipe_on_schema_mismatch: false,
                rejected,
            }
        }

        async fn prepare(&self, window: &impl ReplayWindow) -> Result<BootStore, RestoreBlocked> {
            self.prepare_from(
                StoreSource::Own,
                Some(CheckpointLineage::new(PodOrdinal::STANDALONE)),
                window,
            )
            .await
        }

        async fn prepare_from(
            &self,
            source: StoreSource,
            lineage: Option<CheckpointLineage>,
            window: &impl ReplayWindow,
        ) -> Result<BootStore, RestoreBlocked> {
            prepare_store(
                &self.config,
                source,
                self.ownership,
                lineage,
                window,
                Utc::now(),
                &mut HashSet::new(),
            )
            .await
            .map(|(store, _)| store)
        }
    }

    /// S3 at its boundary: a listing, and objects read from local files. A stalled one never
    /// finishes a bulk download.
    #[derive(Debug)]
    struct FakeS3 {
        listing: Vec<String>,
        objects: HashMap<String, PathBuf>,
        stalled: bool,
    }

    #[async_trait]
    impl CheckpointDownloader for FakeS3 {
        async fn list_recent_checkpoints(
            &self,
            _now: DateTime<Utc>,
        ) -> anyhow::Result<Vec<String>> {
            Ok(self.listing.clone())
        }

        async fn download_file(&self, remote_key: &str) -> anyhow::Result<Vec<u8>> {
            match self.objects.get(remote_key) {
                Some(path) => Ok(std::fs::read(path)?),
                // Wrapped in context as the real downloader wraps it.
                None => Err(anyhow::Error::new(object_store::Error::NotFound {
                    path: remote_key.to_owned(),
                    source: "no such key".into(),
                })
                .context(format!("Failed to get object: {remote_key}"))),
            }
        }

        async fn download_and_store_file_cancellable(
            &self,
            remote_key: &str,
            local_filepath: &Path,
            _cancel_token: Option<&CancellationToken>,
        ) -> anyhow::Result<()> {
            std::fs::write(local_filepath, self.download_file(remote_key).await?)?;
            Ok(())
        }

        async fn download_files_cancellable(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
            _cancel_token: Option<&CancellationToken>,
        ) -> anyhow::Result<()> {
            if self.stalled {
                std::future::pending::<()>().await;
            }
            for key in remote_keys {
                let name = key.rsplit('/').next().unwrap_or(key);
                self.download_and_store_file_cancellable(key, &local_base_path.join(name), None)
                    .await?;
            }
            Ok(())
        }
    }

    #[tokio::test]
    async fn an_unfinished_upload_does_not_count_toward_the_depth_and_a_local_rejection_spares_the_s3_copy(
    ) {
        let boot = Boot::new();
        let (s3, checkpoint_id) = boot.uploaded_checkpoint();
        let importer = CheckpointImporter::new(Box::new(s3), Duration::from_secs(60));
        let window = window();
        let mut rejected = HashSet::from([Rejected::Local(checkpoint_id.clone())]);
        let mut search = Search::default();

        let outcome = boot
            .restore(&window, &mut rejected)
            .search_s3(&importer, 1, Utc::now(), &mut search)
            .await
            .unwrap();

        let ControlFlow::Break(pending) = outcome else {
            panic!("the complete upload behind the unfinished one restores");
        };
        assert_eq!(pending.source().label(), "s3");
        assert_eq!(pending.source().checkpoint_id(), checkpoint_id);
        assert!(search.failed.is_empty(), "{:?}", search.failed);
        assert_eq!(
            UploadBaseline::load(
                &boot.lineage_dir().join(UPLOADED_FILENAME),
                &boot.config.checkpoint_s3_bucket,
            )
            .unwrap()
            .id,
            checkpoint_id,
            "the restored upload becomes the next upload's baseline",
        );
    }

    #[tokio::test]
    async fn a_candidate_of_a_split_that_does_not_cover_this_pod_is_passed_over_outside_the_depth()
    {
        // Pod 1 of 2 restores its parent's lineage: the newest checkpoint is from after the
        // reshard, under the parent's new split, and the one before is from the old split.
        let boot = Boot::of(split(2, 1));
        let mut objects = HashMap::new();
        let now = Utc::now();
        let (_, after_reshard) = boot.upload(&mut objects, split(2, 0), now);
        let (before_id, before_reshard) = boot.upload(
            &mut objects,
            split(1, 0),
            now - chrono::Duration::minutes(15),
        );
        let s3 = FakeS3 {
            listing: vec![after_reshard, before_reshard],
            objects,
            stalled: false,
        };
        let importer = CheckpointImporter::new(Box::new(s3), Duration::from_secs(60));
        let mut search = Search::default();

        let outcome = boot
            .restore(&window(), &mut HashSet::new())
            .search_s3(&importer, 1, Utc::now(), &mut search)
            .await
            .unwrap();

        let ControlFlow::Break(pending) = outcome else {
            panic!(
                "the checkpoint of the old split restores: {:?}",
                search.failed
            );
        };
        assert_eq!(pending.source().checkpoint_id(), before_id);
        assert!(search.failed.is_empty(), "{:?}", search.failed);
    }

    #[tokio::test]
    async fn a_takeover_deletes_a_live_store_but_resumes_a_pending_restore() {
        let takeover = StoreSource::TakeOver {
            parent: PartitionOwnership::single(1),
        };

        let boot = Boot::new();
        drop(CohortStore::open(&StoreConfig {
            path: boot.live(),
            ..StoreConfig::default()
        }));
        assert!(matches!(
            boot.prepare_from(takeover, None, &window()).await,
            Ok(BootStore::Created)
        ));
        assert!(!boot.live().exists(), "the parent advanced what it holds");

        let boot = Boot::new();
        boot.local_checkpoint();
        let Ok(BootStore::Restored(published)) = boot.prepare(&window()).await else {
            panic!("a fresh local checkpoint restores");
        };
        let Ok(BootStore::Restored(resumed)) = boot.prepare_from(takeover, None, &window()).await
        else {
            panic!("a restore the takeover published resumes");
        };
        assert_eq!(resumed.source(), published.source());
    }

    #[tokio::test(start_paused = true)]
    async fn a_download_timeout_ends_the_search_because_older_candidates_are_as_large() {
        let boot = Boot::new();
        let (mut s3, _) = boot.uploaded_checkpoint();
        let complete = s3.listing[1].clone();
        s3.listing = vec![complete.clone(), complete];
        s3.stalled = true;
        let importer = CheckpointImporter::new(Box::new(s3), Duration::from_secs(60));
        let mut search = Search::default();

        let outcome = boot
            .restore(&window(), &mut HashSet::new())
            .search_s3(&importer, 10, Utc::now(), &mut search)
            .await
            .unwrap();

        assert!(outcome.is_continue());
        assert_eq!(search.failed.len(), 1, "{:?}", search.failed);
    }

    #[tokio::test]
    async fn a_leftover_stage_is_deleted_and_an_intact_store_reopens() {
        let boot = Boot::new();
        drop(CohortStore::open(&StoreConfig {
            path: boot.live(),
            ..StoreConfig::default()
        }));
        let stage = staging_path(&boot.live());
        std::fs::create_dir(&stage).unwrap();
        std::fs::write(stage.join("000001.sst"), b"torn").unwrap();

        assert!(matches!(
            boot.prepare(&window()).await,
            Ok(BootStore::Reopened)
        ));
        assert!(!stage.exists());
    }

    #[tokio::test]
    async fn a_local_checkpoint_stays_pending_and_each_boot_checks_its_window_again() {
        let boot = Boot::new();
        let baseline = boot.local_checkpoint();
        let uploaded = boot.lineage_dir().join(UPLOADED_FILENAME);
        UploadBaseline::save(&uploaded, &boot.config.checkpoint_s3_bucket, baseline).unwrap();

        let Ok(BootStore::Restored(published)) = boot.prepare(&window()).await else {
            panic!("a fresh local checkpoint restores");
        };
        assert_eq!(published.source().label(), "local");
        assert!(boot.live().join(MARKER_FILENAME).is_file());
        assert!(
            !uploaded.exists(),
            "a local restore leaves no upload baseline, so the next upload is full",
        );

        let Ok(BootStore::Restored(resumed)) = boot.prepare(&window()).await else {
            panic!("a store with a marker resumes its restore instead of reopening");
        };
        assert_eq!(resumed.plan(), published.plan());

        // The checkpoint resumes the events at 42.
        let Ok(BootStore::Restored(expired)) = boot.prepare(&window_at(Some(43))).await else {
            panic!("a pending restore resumes whatever the window holds");
        };
        assert_eq!(expired.plan().resets().count(), 1);
        assert!(matches!(
            boot.prepare(&window_at(None)).await,
            Err(RestoreBlocked::Positions(_))
        ));
        assert!(
            boot.live().join(MARKER_FILENAME).is_file(),
            "a window that cannot be read keeps the published store for the next round",
        );
    }

    #[tokio::test]
    async fn an_unreadable_marker_deletes_the_store_and_restores_again() {
        let boot = Boot::new();
        boot.local_checkpoint();
        drop(CohortStore::open(&StoreConfig {
            path: boot.live(),
            ..StoreConfig::default()
        }));
        std::fs::write(boot.live().join(MARKER_FILENAME), b"{\"version\": 1").unwrap();

        let Ok(BootStore::Restored(pending)) = boot.prepare(&window()).await else {
            panic!("the store with an unreadable marker is replaced by a restore");
        };
        assert_eq!(pending.source().label(), "local");
        PendingRestore::resume(&boot.live(), &window(), 1)
            .unwrap()
            .expect("the new restore carries a readable marker");
    }

    #[tokio::test]
    async fn the_newest_fresh_local_attempt_restores_and_an_unreadable_one_fails() {
        let boot = Boot::new();
        boot.local_checkpoint();
        let newest = boot.local_checkpoint();
        let torn = boot.local_checkpoint();
        std::fs::remove_file(boot.lineage_dir().join(&torn.id).join(METADATA_FILENAME)).unwrap();

        let Ok(BootStore::Restored(pending)) = boot.prepare(&window()).await else {
            panic!("the newest complete attempt restores");
        };
        assert_eq!(pending.source().checkpoint_id(), newest.id);

        let later = Utc::now() + chrono::Duration::hours(2);
        assert!(
            newest_fresh_local_checkpoint(&boot.lineage_dir(), Duration::from_secs(3600), later)
                .is_none(),
            "an attempt captured before the staleness bound is distrusted",
        );

        std::fs::write(
            boot.lineage_dir().join(&newest.id).join(METADATA_FILENAME),
            b"{\"version\": 2",
        )
        .unwrap();
        assert!(
            matches!(
                newest_fresh_local_checkpoint(
                    &boot.lineage_dir(),
                    Duration::from_secs(3600),
                    Utc::now()
                ),
                Some(Err(_))
            ),
            "a newest attempt that cannot be read fails rather than giving way to an older one",
        );

        let not_a_directory = boot.lineage_dir().join(&newest.id).join(METADATA_FILENAME);
        assert!(
            matches!(
                newest_fresh_local_checkpoint(
                    &not_a_directory,
                    Duration::from_secs(3600),
                    Utc::now()
                ),
                Some(Err(_))
            ),
            "a lineage directory that cannot be listed fails rather than reading as empty",
        );
    }

    #[test]
    fn a_local_attempt_that_cannot_restore_fails_and_leaves_the_search_to_s3() {
        type BreakAttempt = fn(&mut LocalAttempt);
        let cases: [(&str, BreakAttempt); 2] = [
            ("its files are gone", |attempt| {
                std::fs::remove_dir_all(&attempt.dir).unwrap()
            }),
            ("its manifest records no events position", |attempt| {
                attempt.manifest = OffsetManifest::capture(
                    &BTreeSet::from([0]),
                    OwnedPositions::for_test(
                        PartitionOwnership::single(1),
                        vec![InputPositions::new(
                            InputTopic::new("person_merge_events"),
                            BTreeMap::from([(0, ResumeOffset::try_from(7).unwrap())]),
                        )],
                    ),
                )
                .unwrap()
            }),
        ];
        for (name, break_attempt) in cases {
            let boot = Boot::new();
            boot.local_checkpoint();
            let Some(Ok(mut attempt)) = newest_fresh_local_checkpoint(
                &boot.lineage_dir(),
                Duration::from_secs(3600),
                Utc::now(),
            ) else {
                panic!("{name}: the attempt is complete before it breaks");
            };
            break_attempt(&mut attempt);

            let verdict = boot.restore(&window(), &mut HashSet::new()).local(attempt);

            assert!(
                matches!(verdict, Ok(Verdict::Failed(_))),
                "{name}: {verdict:?}"
            );
        }
    }

    /// Holds every position on its first read, as the check before a download sees it, and none
    /// after.
    struct ExpiringWindow {
        inputs: BTreeSet<InputTopic>,
        reads: Cell<u32>,
    }

    impl ReplayWindow for ExpiringWindow {
        fn inputs(&self) -> &BTreeSet<InputTopic> {
            &self.inputs
        }

        fn watermarks(
            &self,
            _topic: &InputTopic,
            partition_count: u16,
        ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
            let reads = self.reads.get();
            self.reads.set(reads + 1);
            let low = if reads == 0 { 0 } else { i64::MAX };
            Ok((0..partition_count).map(|p| (p, (low, i64::MAX))).collect())
        }
    }

    #[tokio::test]
    async fn a_window_that_expires_while_the_candidate_stages_publishes_nothing() {
        let boot = Boot::new();
        boot.local_checkpoint();
        let window = ExpiringWindow {
            inputs: BTreeSet::from([InputTopic::new(EVENTS)]),
            reads: Cell::new(0),
        };
        let attempt = newest_fresh_local_checkpoint(
            &boot.lineage_dir(),
            Duration::from_secs(3600),
            Utc::now(),
        )
        .unwrap()
        .unwrap();

        let verdict = boot
            .restore(&window, &mut HashSet::new())
            .local(attempt)
            .unwrap();

        assert!(
            matches!(verdict, Verdict::Unusable(Unusable::NothingToReplay)),
            "{verdict:?}"
        );
        assert!(!boot.live().exists());
        assert!(!staging_path(&boot.live()).exists());
    }
}
