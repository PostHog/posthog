//! The checkpoint orchestrator.
//!
//! [`CheckpointSweeper`] takes a frozen whole-DB RocksDB checkpoint to the local volume on every
//! tick, beside an offset manifest read from the consumer groups, and uploads it to S3 every Nth
//! tick and once more on a graceful stop. [`run_checkpoints`] drives it. One `create_checkpoint` at
//! a time, never two racing: the final checkpoint runs on the periodic loop's task, after the loop.
//!
//! ## Interior mutability without a lock across `.await`
//!
//! The tick counter is an [`AtomicU64`]. The incremental-upload baseline (the last uploaded
//! [`CheckpointMetadata`]) sits behind a [`Mutex`] that is never held across an `.await`: the
//! baseline is cloned out under the guard, the plan and upload run lock-free, and a successful
//! upload stores the new baseline under a fresh, momentary lock.
//!
//! ## Must not panic
//!
//! The [`Sweeper`] contract forbids panicking (a panic aborts the timer task and stops all future
//! checkpoints). Every fallible step is handled, the failure is logged and counted, and the loop
//! continues.

// The checkpoint sweeper offloads its own store I/O (its own `spawn_blocking` + log-and-skip on
// every `JoinError`) to honor the must-not-panic policy above, so its direct `CohortStore` calls are
// sanctioned. See `checkpoint_once`.
#![allow(clippy::disallowed_methods)]

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use lifecycle::Handle;
use tokio::sync::OnceCell;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use super::lineage::CheckpointLineage;
use super::{
    plan_checkpoint, CheckpointExporter, CheckpointMetadata, CheckpointPlan, DurabilityConfig,
    MetadataError, OffsetManifest, S3Uploader, METADATA_FILENAME,
};
use crate::consumers::events::{DrainWait, DrainedOwnership};
use crate::consumers::EventDispatcher;
use crate::observability::metrics::{
    CHECKPOINT_CAPTURE_FAILURES_TOTAL, CHECKPOINT_FILE_COUNT,
    CHECKPOINT_LAST_CAPTURE_TIMESTAMP_SECONDS, CHECKPOINT_LAST_FULL_UPLOAD_TIMESTAMP_SECONDS,
    CHECKPOINT_LAST_UPLOAD_TIMESTAMP_SECONDS, CHECKPOINT_SIZE_BYTES,
    CHECKPOINT_UPLOADED_BYTES_TOTAL, CHECKPOINT_UPLOADS_TOTAL,
};
use crate::partitions::InputGroups;
use crate::store::{CohortStore, DbIdentity};
use crate::sweep::{run_sweep_loop, Sweeper};

/// The loop-name label for the checkpoint sweep cycle metrics.
pub const CHECKPOINT_LOOP_NAME: &str = "checkpoint";

/// The last successful upload's metadata, in the lineage's local directory. A restarted process
/// builds its first upload on it when the store's DB id still matches. A restore rewrites it, because
/// a restored DB reuses the SST numbers written after its checkpoint.
pub(crate) const UPLOADED_FILENAME: &str = "uploaded.json";

/// True on every `every_n`-th tick (tick 0, N, 2N, …). `every_n == 0` is treated as 1.
pub fn should_upload(tick: u64, every_n: u64) -> bool {
    let n = every_n.max(1);
    tick.is_multiple_of(n)
}

/// `N = max(1, s3_upload_interval / checkpoint_interval)`. Floored at 1 to prevent division by zero
/// and ensure at least every-tick uploading when the checkpoint interval is large.
pub fn upload_cadence(checkpoint_interval_ms: u64, s3_upload_interval_ms: u64) -> u64 {
    (s3_upload_interval_ms / checkpoint_interval_ms.max(1)).max(1)
}

/// Why a checkpoint runs.
#[derive(Debug)]
pub(crate) enum Trigger {
    Periodic,
    /// A graceful stop, after every consumer's final commit.
    Final(DrainedOwnership),
}

impl Trigger {
    fn label(&self) -> &'static str {
        match self {
            Self::Periodic => "periodic",
            Self::Final(_) => "final",
        }
    }

    /// The slices to capture. A final checkpoint uses the ownership the workers drained under,
    /// because closing the events consumer empties the live set.
    fn owned(&self, live: impl FnOnce() -> Vec<i32>) -> BTreeSet<u16> {
        let partitions = match self {
            Self::Periodic => live(),
            Self::Final(drained) => drained.partitions().iter().copied().collect(),
        };
        partitions
            .into_iter()
            .filter_map(|partition| u16::try_from(partition).ok())
            .collect()
    }

    /// A final checkpoint always uploads, so a planned stop leaves nothing to replay past it.
    fn uploads(&self, tick: u64, every_n: u64) -> bool {
        match self {
            Self::Periodic => should_upload(tick, every_n),
            Self::Final(_) => true,
        }
    }
}

/// How the next upload treats the last one.
#[derive(Debug, PartialEq)]
enum UploadKind<'a> {
    Full(FullReason),
    Incremental(&'a CheckpointMetadata),
}

#[derive(Debug, PartialEq)]
enum FullReason {
    NoBaseline,
    /// A created store restarts SST numbering, so a file name from another DB names other data.
    OtherDb,
    /// The chain is older than the full-upload interval, which bounds the age of what a restore
    /// downloads.
    BaselineExpired,
}

impl UploadKind<'_> {
    fn label(&self) -> &'static str {
        match self {
            Self::Full(_) => "full",
            Self::Incremental(_) => "incremental",
        }
    }

    fn previous(&self) -> Option<&CheckpointMetadata> {
        match self {
            Self::Full(_) => None,
            Self::Incremental(baseline) => Some(baseline),
        }
    }
}

fn upload_kind<'a>(
    baseline: Option<&'a CheckpointMetadata>,
    db: &DbIdentity,
    now: DateTime<Utc>,
    full_max_age: Duration,
) -> UploadKind<'a> {
    let Some(baseline) = baseline else {
        return UploadKind::Full(FullReason::NoBaseline);
    };
    if &baseline.db_identity != db {
        return UploadKind::Full(FullReason::OtherDb);
    }
    let chain_age = now.signed_duration_since(baseline.full_upload_at).to_std();
    if chain_age.is_ok_and(|age| age > full_max_age) {
        return UploadKind::Full(FullReason::BaselineExpired);
    }
    UploadKind::Incremental(baseline)
}

/// Drives periodic whole-DB checkpoints to the local volume plus incremental S3 backup.
pub struct CheckpointSweeper {
    store: CohortStore,
    dispatcher: Arc<EventDispatcher>,
    groups: Arc<InputGroups>,
    lineage: CheckpointLineage,
    config: DurabilityConfig,
    /// Built on the first upload, so an S3 outage never stops a pod that has its store.
    exporter: OnceCell<CheckpointExporter>,
    tick: AtomicU64,
    upload_every_n: u64,
    /// Baseline for the next incremental upload. Updated only after a successful upload.
    baseline: Mutex<Option<CheckpointMetadata>>,
    /// Cancels a periodic upload at shutdown, so the final checkpoint does not wait behind it.
    stop: CancellationToken,
}

impl CheckpointSweeper {
    /// The first baseline is the lineage's `uploaded.json`, which [`upload_kind`] uses only for the
    /// same DB.
    pub fn new(
        store: CohortStore,
        dispatcher: Arc<EventDispatcher>,
        groups: Arc<InputGroups>,
        lineage: CheckpointLineage,
        config: DurabilityConfig,
        upload_every_n: u64,
        stop: CancellationToken,
    ) -> Self {
        let uploaded = lineage
            .local_dir(Path::new(&config.local_checkpoint_dir))
            .join(UPLOADED_FILENAME);
        let baseline = match CheckpointMetadata::load(&uploaded) {
            Ok(baseline) => Some(baseline),
            Err(MetadataError::Io(e)) if e.kind() == std::io::ErrorKind::NotFound => None,
            Err(e) => {
                warn!(error = %e, path = %uploaded.display(), "unreadable upload baseline; the next upload is full");
                None
            }
        };
        let started = Utc::now().timestamp() as f64;
        metrics::gauge!(CHECKPOINT_LAST_CAPTURE_TIMESTAMP_SECONDS).set(started);
        metrics::gauge!(CHECKPOINT_LAST_UPLOAD_TIMESTAMP_SECONDS).set(started);
        Self {
            store,
            dispatcher,
            groups,
            lineage,
            config,
            exporter: OnceCell::new(),
            tick: AtomicU64::new(0),
            upload_every_n,
            baseline: Mutex::new(baseline),
            stop,
        }
    }

    fn local_dir(&self) -> PathBuf {
        self.lineage
            .local_dir(Path::new(&self.config.local_checkpoint_dir))
    }

    /// The checkpoint a graceful stop takes once every consumer has made its final commit. Skipped
    /// when the worker drain never finished, because the positions are then not settled.
    pub async fn final_checkpoint(&self) {
        match self.dispatcher.wait_for_worker_drain(Duration::ZERO).await {
            DrainWait::Drained(drained) => self.checkpoint_once(Trigger::Final(drained)).await,
            DrainWait::TimedOut => warn!(
                "final checkpoint skipped: the worker drain did not finish, so positions are unsettled",
            ),
        }
    }

    async fn checkpoint_once(&self, trigger: Trigger) {
        let tick = self.tick.fetch_add(1, Ordering::SeqCst);

        // 1. fsync the WAL before the snapshot. The checkpoint must hold at least what the commits
        //    read in step 3 cover, and each of those followed its own fsync.
        let flush_store = self.store.clone();
        match tokio::task::spawn_blocking(move || flush_store.flush_wal_sync()).await {
            Ok(Ok(())) => {}
            Ok(Err(e)) => {
                warn!(error = %e, "checkpoint tick: WAL fsync failed; skipping tick");
                metrics::counter!(CHECKPOINT_UPLOADS_TOTAL, "result" => "flush_failed")
                    .increment(1);
                return;
            }
            Err(join_err) => {
                error!(error = %join_err, "checkpoint tick: WAL fsync task panicked; skipping tick");
                metrics::counter!(CHECKPOINT_UPLOADS_TOTAL, "result" => "flush_failed")
                    .increment(1);
                return;
            }
        }

        // 2. The slices to capture. A revoke after this point leaves a slice the manifest names but
        //    the checkpoint lacks, which a restore resumes as empty; an assign leaves one the
        //    checkpoint holds but the manifest lacks, which a restore resets. Both are safe.
        let owned = trigger.owned(|| self.dispatcher.owned_partitions());
        if owned.is_empty() {
            info!(
                trigger = trigger.label(),
                "checkpoint tick: no owned slice; skipping tick"
            );
            return;
        }

        // 3. Every input's resume positions, from its consumer group on the broker.
        let groups = self.groups.clone();
        let partitions = owned.clone();
        let positions = match tokio::task::spawn_blocking(move || {
            groups.resume_positions(&partitions)
        })
        .await
        {
            Ok(Ok(positions)) => positions,
            Ok(Err(e)) => {
                warn!(error = %e, "checkpoint tick: reading input positions failed; skipping tick");
                metrics::counter!(CHECKPOINT_CAPTURE_FAILURES_TOTAL, "reason" => "positions")
                    .increment(1);
                return;
            }
            Err(join_err) => {
                error!(error = %join_err, "checkpoint tick: reading input positions panicked; skipping tick");
                metrics::counter!(CHECKPOINT_CAPTURE_FAILURES_TOTAL, "reason" => "positions")
                    .increment(1);
                return;
            }
        };

        // 4. The manifest refuses a slice that lacks a position on any input.
        let manifest = match OffsetManifest::capture(self.lineage.ordinal(), &owned, positions) {
            Ok(manifest) => manifest,
            Err(e) => {
                warn!(error = %e, "checkpoint tick: incomplete manifest; skipping tick");
                metrics::counter!(CHECKPOINT_CAPTURE_FAILURES_TOTAL, "reason" => "incomplete")
                    .increment(1);
                return;
            }
        };

        // 5. Take a whole-DB RocksDB checkpoint (sync I/O → spawn_blocking). The attempt dir must
        //    not be a child of store_path; SST hard-links require the same filesystem.
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let attempt_dir = self.local_dir().join(&checkpoint_id);
        // `create_checkpoint` requires the leaf to NOT exist; it creates it and errors if it does.
        if let Err(e) = tokio::fs::create_dir_all(self.local_dir()).await {
            warn!(error = %e, dir = %self.local_dir().display(), "checkpoint tick: cannot create attempt parent dir; skipping tick");
            return;
        }
        let checkpoint_store = self.store.clone();
        let checkpoint_dir = attempt_dir.clone();
        let create_result = tokio::task::spawn_blocking(move || {
            checkpoint_store.create_checkpoint(&checkpoint_dir)
        })
        .await;
        match create_result {
            Ok(Ok(())) => {}
            Ok(Err(e)) => {
                warn!(error = %e, "checkpoint tick: create_checkpoint failed; skipping tick");
                drop(tokio::fs::remove_dir_all(&attempt_dir).await);
                return;
            }
            Err(join_err) => {
                error!(error = %join_err, "checkpoint tick: create_checkpoint task panicked; skipping tick");
                drop(tokio::fs::remove_dir_all(&attempt_dir).await);
                return;
            }
        }

        // 6. Write offsets.json after create_checkpoint (so it is never frozen mid-write) but before
        //    planning, so the planner tracks it as a non-SST file and the S3 upload carries it.
        if let Err(e) = manifest.write_to_dir(&attempt_dir) {
            warn!(error = %e, "checkpoint tick: writing offsets.json failed; skipping tick");
            drop(tokio::fs::remove_dir_all(&attempt_dir).await);
            return;
        }

        // 7. Plan against the baseline, then write metadata.json.
        let db = match self.store.db_identity() {
            Ok(db) => db,
            Err(e) => {
                warn!(error = %e, "checkpoint tick: reading the DB id failed; skipping tick");
                drop(tokio::fs::remove_dir_all(&attempt_dir).await);
                return;
            }
        };
        let baseline = self
            .baseline
            .lock()
            .expect("the baseline lock is never held across a panic")
            .clone();
        let kind = upload_kind(
            baseline.as_ref(),
            &db,
            attempt_timestamp,
            self.config.full_upload_interval,
        );
        let plan = match plan_checkpoint(
            &attempt_dir,
            CheckpointMetadata::new(self.lineage.ordinal(), attempt_timestamp, db),
            self.config.s3_key_prefix.clone(),
            kind.previous(),
            None,
        ) {
            Ok(plan) => plan,
            Err(e) => {
                warn!(error = %e, "checkpoint tick: planning failed; skipping tick");
                drop(tokio::fs::remove_dir_all(&attempt_dir).await);
                return;
            }
        };
        if let Err(e) = plan
            .info
            .metadata
            .save(&attempt_dir.join(METADATA_FILENAME))
        {
            warn!(error = %e, "checkpoint tick: writing metadata.json failed; skipping tick");
            drop(tokio::fs::remove_dir_all(&attempt_dir).await);
            return;
        }

        // 8. Emit local-checkpoint size and file-count metrics.
        let (size_bytes, file_count) = dir_size_and_count(&attempt_dir);
        metrics::histogram!(CHECKPOINT_SIZE_BYTES).record(size_bytes as f64);
        metrics::histogram!(CHECKPOINT_FILE_COUNT).record(file_count as f64);
        metrics::gauge!(CHECKPOINT_LAST_CAPTURE_TIMESTAMP_SECONDS)
            .set(manifest.captured_at().timestamp() as f64);
        info!(
            checkpoint_id,
            trigger = trigger.label(),
            dir = %attempt_dir.display(),
            size_bytes,
            file_count,
            "local checkpoint taken",
        );

        // 9. Upload when due, and advance the baseline on success.
        if trigger.uploads(tick, self.upload_every_n) {
            match &kind {
                UploadKind::Full(reason) => {
                    info!(checkpoint_id, ?reason, "uploading a full checkpoint")
                }
                UploadKind::Incremental(baseline) => info!(
                    checkpoint_id,
                    baseline = %baseline.id,
                    "uploading an incremental checkpoint",
                ),
            }
            self.upload(&plan, kind.label(), &trigger).await;
        }

        // 10. Prune older local checkpoint dirs (keep latest only) to avoid pinning SSTs that the live
        //    DB compacted away, which would cause unbounded PVC growth.
        self.prune_old_checkpoints(&attempt_dir).await;
    }

    async fn upload(&self, plan: &CheckpointPlan, kind: &'static str, trigger: &Trigger) {
        let exporter = match self
            .exporter
            .get_or_try_init(|| async {
                S3Uploader::new(self.config.clone(), self.lineage)
                    .await
                    .map(|uploader| CheckpointExporter::new(Box::new(uploader)))
            })
            .await
        {
            Ok(exporter) => exporter,
            Err(e) => {
                metrics::counter!(CHECKPOINT_UPLOADS_TOTAL, "result" => "unavailable", "trigger" => trigger.label())
                    .increment(1);
                warn!(error = %format!("{e:#}"), "checkpoint S3 uploader unavailable; retrying on the next upload");
                return;
            }
        };

        // A cancelled upload never writes metadata.json, so the last finished upload stays the newest
        // restorable one, and the baseline stays where it was.
        let result = match trigger {
            Trigger::Periodic => {
                exporter
                    .export_checkpoint_with_plan_cancellable(
                        plan,
                        Some(&self.stop),
                        trigger.label(),
                    )
                    .await
            }
            Trigger::Final(_) => {
                let cancel = CancellationToken::new();
                let upload = exporter.export_checkpoint_with_plan_cancellable(
                    plan,
                    Some(&cancel),
                    trigger.label(),
                );
                tokio::pin!(upload);
                tokio::select! {
                    result = &mut upload => result,
                    _ = tokio::time::sleep(self.config.final_upload_timeout) => {
                        cancel.cancel();
                        upload.await
                    }
                }
            }
        };
        if let Err(e) = result {
            warn!(error = %format!("{e:#}"), "checkpoint S3 upload failed; baseline unchanged");
            return;
        }

        let bytes: u64 = plan
            .files_to_upload
            .iter()
            .filter_map(|file| std::fs::metadata(&file.local_path).ok())
            .map(|metadata| metadata.len())
            .sum();
        metrics::counter!(CHECKPOINT_UPLOADED_BYTES_TOTAL, "kind" => kind).increment(bytes);
        metrics::gauge!(CHECKPOINT_LAST_UPLOAD_TIMESTAMP_SECONDS)
            .set(Utc::now().timestamp() as f64);
        metrics::gauge!(CHECKPOINT_LAST_FULL_UPLOAD_TIMESTAMP_SECONDS)
            .set(plan.info.metadata.full_upload_at.timestamp() as f64);

        let uploaded = plan.info.metadata.clone();
        if let Err(e) = uploaded.save(&self.local_dir().join(UPLOADED_FILENAME)) {
            warn!(error = %e, "saving the upload baseline failed; the next process builds on an older upload of this DB");
        }
        *self
            .baseline
            .lock()
            .expect("the baseline lock is never held across a panic") = Some(uploaded);
        info!(
            kind,
            uploaded_files = plan.files_to_upload.len(),
            bytes,
            "checkpoint uploaded to S3"
        );
    }

    async fn prune_old_checkpoints(&self, keep: &Path) {
        let parent = self.local_dir();
        let entries = match tokio::fs::read_dir(&parent).await {
            Ok(entries) => entries,
            Err(_) => return,
        };
        let mut entries = entries;
        loop {
            let next = match entries.next_entry().await {
                Ok(Some(entry)) => entry,
                Ok(None) => break,
                Err(e) => {
                    warn!(error = %e, "checkpoint prune: reading attempt parent failed");
                    break;
                }
            };
            let path = next.path();
            if path == keep || !path.is_dir() {
                continue;
            }
            if let Err(e) = tokio::fs::remove_dir_all(&path).await {
                warn!(error = %e, dir = %path.display(), "checkpoint prune: failed to remove old checkpoint");
            }
        }
    }
}

#[async_trait]
impl Sweeper for CheckpointSweeper {
    async fn run_once(&self) {
        self.checkpoint_once(Trigger::Periodic).await;
    }
}

/// Takes periodic checkpoints until the sweeper's stop token fires, then a final one once
/// `handle`'s shutdown phase begins. Register `handle` in a later shutdown phase than every
/// consumer, so the final checkpoint runs after their final commits.
pub async fn run_checkpoints(sweeper: Arc<CheckpointSweeper>, interval: Duration, handle: Handle) {
    let _scope = handle.process_scope();
    let stop = sweeper.stop.clone();
    run_sweep_loop(sweeper.clone(), interval, CHECKPOINT_LOOP_NAME, stop).await;
    handle.shutdown_recv().await;
    sweeper.final_checkpoint().await;
}

/// Total byte size and file count of a directory tree. Unreadable entries are skipped.
fn dir_size_and_count(dir: &Path) -> (u64, u64) {
    let mut size = 0u64;
    let mut count = 0u64;
    let mut stack = vec![dir.to_path_buf()];
    while let Some(current) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&current) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            match entry.file_type() {
                Ok(ft) if ft.is_dir() => stack.push(path),
                Ok(_) => {
                    if let Ok(meta) = entry.metadata() {
                        size += meta.len();
                        count += 1;
                    }
                }
                Err(_) => {}
            }
        }
    }
    (size, count)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::durability::PodOrdinal;

    #[test]
    fn should_upload_fires_on_the_first_and_every_nth_tick() {
        let fired: Vec<u64> = (0..10).filter(|&t| should_upload(t, 3)).collect();
        assert_eq!(fired, vec![0, 3, 6, 9]);
    }

    #[test]
    fn should_upload_every_tick_when_n_is_one() {
        for tick in 0..5 {
            assert!(
                should_upload(tick, 1),
                "every tick uploads when every_n == 1"
            );
        }
    }

    #[test]
    fn should_upload_treats_zero_n_as_one_without_panicking() {
        assert!(should_upload(0, 0));
        assert!(should_upload(7, 0));
    }

    #[test]
    fn upload_cadence_is_the_interval_ratio_floored_at_one() {
        assert_eq!(upload_cadence(300_000, 900_000), 3); // 15min / 5min = 3
        assert_eq!(upload_cadence(300_000, 60_000), 1); // upload interval < checkpoint interval → every tick
        assert_eq!(upload_cadence(0, 900_000), 900_000); // zero checkpoint interval handled
    }

    #[test]
    fn the_final_trigger_captures_the_drained_ownership_and_uploads_off_cadence() {
        let final_trigger = Trigger::Final(DrainedOwnership::for_test([3, 7]));
        assert_eq!(final_trigger.owned(Vec::new), BTreeSet::from([3, 7]));
        assert!(final_trigger.uploads(1, 3));

        assert_eq!(
            Trigger::Periodic.owned(|| vec![1, 2]),
            BTreeSet::from([1, 2])
        );
        assert!(!Trigger::Periodic.uploads(1, 3));
    }

    #[test]
    fn an_upload_builds_on_its_baseline_only_for_the_same_db_and_a_young_chain() {
        let now = Utc::now();
        let day = Duration::from_secs(86_400);
        let db = DbIdentity::for_test("db-a");
        let chain_started = |age: chrono::Duration, db: &str| {
            let mut baseline = CheckpointMetadata::new(
                PodOrdinal::STANDALONE,
                now - chrono::Duration::minutes(15),
                DbIdentity::for_test(db),
            );
            baseline.full_upload_at = now - age;
            baseline
        };
        let young = chain_started(chrono::Duration::hours(23), "db-a");
        let at_limit = chain_started(chrono::Duration::days(1), "db-a");
        let expired = chain_started(chrono::Duration::hours(25), "db-a");
        let other_db = chain_started(chrono::Duration::hours(1), "db-b");

        assert_eq!(
            upload_kind(None, &db, now, day),
            UploadKind::Full(FullReason::NoBaseline)
        );
        assert_eq!(
            upload_kind(Some(&other_db), &db, now, day),
            UploadKind::Full(FullReason::OtherDb)
        );
        assert_eq!(
            upload_kind(Some(&expired), &db, now, day),
            UploadKind::Full(FullReason::BaselineExpired)
        );
        assert_eq!(
            upload_kind(Some(&at_limit), &db, now, day),
            UploadKind::Incremental(&at_limit)
        );
        assert_eq!(
            upload_kind(Some(&young), &db, now, day),
            UploadKind::Incremental(&young)
        );
    }

    #[test]
    fn dir_size_and_count_sums_nested_files() {
        let dir = tempfile::TempDir::new().unwrap();
        std::fs::write(dir.path().join("a.sst"), b"12345").unwrap();
        let nested = dir.path().join("nested");
        std::fs::create_dir_all(&nested).unwrap();
        std::fs::write(nested.join("b.sst"), b"123").unwrap();

        let (size, count) = dir_size_and_count(dir.path());
        assert_eq!(count, 2);
        assert_eq!(size, 8);
    }
}
