//! The checkpoint orchestrator.
//!
//! [`CheckpointSweeper`] is one sweep loop, driven by
//! [`run_sweep_loop`](crate::sweep::run_sweep_loop) at `checkpoint_interval`. Each tick takes a
//! frozen whole-DB RocksDB checkpoint to the local volume, beside an offset manifest read from the
//! consumer groups; every Nth tick it also uploads that checkpoint to S3 incrementally. One
//! `create_checkpoint` per tick, never two racing.
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

use async_trait::async_trait;
use chrono::Utc;
use tokio::sync::OnceCell;
use tracing::{error, info, warn};

use super::lineage::CheckpointLineage;
use super::{
    plan_checkpoint, CheckpointExporter, CheckpointMetadata, CheckpointPlan, DurabilityConfig,
    OffsetManifest, S3Uploader, METADATA_FILENAME,
};
use crate::consumers::EventDispatcher;
use crate::observability::metrics::{
    CHECKPOINT_CAPTURE_FAILURES_TOTAL, CHECKPOINT_FILE_COUNT,
    CHECKPOINT_LAST_CAPTURE_TIMESTAMP_SECONDS, CHECKPOINT_LAST_UPLOAD_TIMESTAMP_SECONDS,
    CHECKPOINT_SIZE_BYTES, CHECKPOINT_UPLOADS_TOTAL,
};
use crate::partitions::InputGroups;
use crate::store::CohortStore;
use crate::sweep::Sweeper;

/// The loop-name label for the checkpoint sweep cycle metrics.
pub const CHECKPOINT_LOOP_NAME: &str = "checkpoint";

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
}

impl CheckpointSweeper {
    pub fn new(
        store: CohortStore,
        dispatcher: Arc<EventDispatcher>,
        groups: Arc<InputGroups>,
        lineage: CheckpointLineage,
        config: DurabilityConfig,
        upload_every_n: u64,
    ) -> Self {
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
            baseline: Mutex::new(None),
        }
    }

    fn local_dir(&self) -> PathBuf {
        self.lineage
            .local_dir(Path::new(&self.config.local_checkpoint_dir))
    }

    async fn checkpoint_once(&self) {
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
        let owned: BTreeSet<u16> = self
            .dispatcher
            .owned_partitions()
            .into_iter()
            .filter_map(|partition| u16::try_from(partition).ok())
            .collect();
        if owned.is_empty() {
            info!("checkpoint tick: no owned slice; skipping tick");
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
        let baseline = self
            .baseline
            .lock()
            .expect("the baseline lock is never held across a panic")
            .clone();
        let plan = match plan_checkpoint(
            &attempt_dir,
            CheckpointMetadata::new(self.lineage.ordinal(), attempt_timestamp),
            self.config.s3_key_prefix.clone(),
            baseline.as_ref(),
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
            dir = %attempt_dir.display(),
            size_bytes,
            file_count,
            "local checkpoint taken",
        );

        // 9. Upload when due, and advance the baseline on success.
        if should_upload(tick, self.upload_every_n) {
            self.upload(&plan).await;
        }

        // 10. Prune older local checkpoint dirs (keep latest only) to avoid pinning SSTs that the live
        //    DB compacted away, which would cause unbounded PVC growth.
        self.prune_old_checkpoints(&attempt_dir).await;
    }

    async fn upload(&self, plan: &CheckpointPlan) {
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
                metrics::counter!(CHECKPOINT_UPLOADS_TOTAL, "result" => "unavailable").increment(1);
                warn!(error = %format!("{e:#}"), "checkpoint S3 uploader unavailable; retrying on the next upload");
                return;
            }
        };

        if let Err(e) = exporter.export_checkpoint_with_plan(plan).await {
            warn!(error = %format!("{e:#}"), "checkpoint S3 upload failed; baseline unchanged");
            return;
        }
        metrics::gauge!(CHECKPOINT_LAST_UPLOAD_TIMESTAMP_SECONDS)
            .set(Utc::now().timestamp() as f64);
        *self
            .baseline
            .lock()
            .expect("the baseline lock is never held across a panic") =
            Some(plan.info.metadata.clone());
        info!(
            uploaded_files = plan.files_to_upload.len(),
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
        self.checkpoint_once().await;
    }
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
