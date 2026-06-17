//! The checkpoint orchestrator.
//!
//! [`CheckpointSweeper`] is one sweep loop, driven by
//! [`run_sweep_loop`](crate::sweep::run_sweep_loop) at `checkpoint_interval`. Each tick takes a frozen
//! whole-DB RocksDB checkpoint to the local PVC; every Nth tick it also uploads that checkpoint to S3
//! incrementally (only the SSTs that changed). One `create_checkpoint` per tick — never two racing.
//!
//! ## Interior mutability without a mutex across `.await`
//!
//! The tick counter is an [`AtomicU64`] (`fetch_add`, no await). The incremental-upload baseline (the
//! last-uploaded [`CheckpointMetadata`]) is a [`tokio::sync::Mutex`], but it is never held across an
//! `.await`: the baseline is cloned out under the guard, which is then dropped, the plan + upload run
//! lock-free, and on a successful upload the new baseline is stored under a fresh, momentary lock.
//!
//! ## Must not panic
//!
//! The [`Sweeper`] contract forbids panicking (a panic aborts the timer task and stops all future
//! checkpoints). Every fallible step is handled, the failure is logged and counted, and the loop
//! continues.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use tokio::sync::Mutex;
use tracing::{error, info, warn};

use super::{
    plan_checkpoint, CheckpointExporter, CheckpointMetadata, DurabilityConfig, OffsetManifest,
    STORE_PARTITION, STORE_TOPIC,
};
use crate::consumers::EventDispatcher;
use crate::observability::metrics::{
    CHECKPOINT_FILES_UPLOADED_TOTAL, CHECKPOINT_FILE_COUNT, CHECKPOINT_SIZE_BYTES,
    CHECKPOINT_UPLOADS_TOTAL,
};
use crate::partitions::OffsetTracker;
use crate::store::CohortStore;
use crate::sweep::Sweeper;

/// The loop-name label for the checkpoint sweep cycle metrics.
pub const CHECKPOINT_LOOP_NAME: &str = "checkpoint";

/// One topic and the [`OffsetTracker`] that tracks its committed positions, passed to
/// [`CheckpointSweeper::new`].
pub type TrackedTopic = (String, Arc<OffsetTracker>);

/// True on every `every_n`-th tick: the first tick (`tick == 0`) uploads, then every `every_n` ticks
/// thereafter. Pure so the cadence is unit-testable in isolation.
pub fn should_upload(tick: u64, every_n: u64) -> bool {
    // Guard against 0 defensively (a 0 would panic the modulo). With `every_n == 1` every tick uploads.
    let n = every_n.max(1);
    tick.is_multiple_of(n)
}

/// The upload cadence: upload on every Nth local checkpoint tick, `N = max(1, s3_upload_interval /
/// checkpoint_interval)`. Floored at 1 so a zero/larger checkpoint interval still uploads every tick
/// (never divides by zero, never skips forever). Computed once at construction.
pub fn upload_cadence(checkpoint_interval_ms: u64, s3_upload_interval_ms: u64) -> u64 {
    (s3_upload_interval_ms / checkpoint_interval_ms.max(1)).max(1)
}

/// Drives periodic whole-DB checkpoints to the local PVC + incremental S3 backup.
pub struct CheckpointSweeper {
    store: CohortStore,
    /// For `owned_partitions()`.
    dispatcher: Arc<EventDispatcher>,
    /// The `(topic, tracker)` pairs whose committed offsets the manifest captures.
    trackers: Vec<TrackedTopic>,
    exporter: CheckpointExporter,
    config: DurabilityConfig,
    /// Base dir for local checkpoints; a sibling subtree of `store_path` (RocksDB hard-links SSTs, so
    /// it must be on the same filesystem and must not be a child of the store path).
    checkpoint_local_dir: PathBuf,
    /// 0-indexed tick counter, advanced once per `run_once`.
    tick: AtomicU64,
    /// Upload cadence: upload on every `every_n`-th tick. Computed once at construction.
    upload_every_n: u64,
    /// The last-uploaded checkpoint's metadata, the baseline for the next incremental S3 diff. Cloned
    /// out + dropped before the upload await; updated only after a successful upload. `None` until the
    /// first successful upload (then the planner uploads every file).
    last_uploaded: Mutex<Option<CheckpointMetadata>>,
}

impl CheckpointSweeper {
    /// Build the sweeper. `upload_every_n` is the upload cadence from [`upload_cadence`] (every Nth
    /// local tick also uploads to S3).
    pub fn new(
        store: CohortStore,
        dispatcher: Arc<EventDispatcher>,
        trackers: Vec<TrackedTopic>,
        exporter: CheckpointExporter,
        config: DurabilityConfig,
        checkpoint_local_dir: PathBuf,
        upload_every_n: u64,
    ) -> Self {
        Self {
            store,
            dispatcher,
            trackers,
            exporter,
            config,
            checkpoint_local_dir,
            tick: AtomicU64::new(0),
            upload_every_n,
            last_uploaded: Mutex::new(None),
        }
    }

    /// The parent dir under which per-attempt checkpoint dirs live, matching the planner layout
    /// `<base>/<STORE_TOPIC>/<STORE_PARTITION>/<checkpoint_id>`. Pruning keeps only the newest leaf.
    fn attempt_parent(&self) -> PathBuf {
        self.checkpoint_local_dir
            .join(STORE_TOPIC)
            .join(STORE_PARTITION.to_string())
    }

    /// Run one checkpoint tick. Never panics; every fallible step is handled and counted.
    async fn checkpoint_once(&self) {
        let tick = self.tick.fetch_add(1, Ordering::SeqCst);

        // 1. fsync the WAL so `committed <= durable` holds before the snapshot. A failure must not
        //    yield a checkpoint whose manifest claims more than is durable — skip the whole tick.
        let flush_store = self.store.clone();
        let flush_result = tokio::task::spawn_blocking(move || flush_store.flush_wal_sync()).await;
        match flush_result {
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

        // 2. Capture committed offsets for the owned partitions across all trackers. In-memory;
        //    reads `committed` (<= durable), never `committable` (processed).
        let owned = self.dispatcher.owned_partitions();
        let tracker_refs: Vec<(&str, &OffsetTracker)> = self
            .trackers
            .iter()
            .map(|(topic, tracker)| (topic.as_str(), tracker.as_ref()))
            .collect();
        let manifest = OffsetManifest::capture(&owned, &tracker_refs);

        // 3. Take the frozen whole-DB checkpoint into a fresh attempt dir (a UTC timestamp + tick
        //    seq, never a child of store_path). RocksDB checkpoint is sync I/O → spawn_blocking.
        let attempt_timestamp = Utc::now();
        let checkpoint_id = format!(
            "{}-{tick}",
            CheckpointMetadata::generate_id(attempt_timestamp)
        );
        let attempt_dir = self.attempt_parent().join(&checkpoint_id);
        if let Err(e) = tokio::fs::create_dir_all(&attempt_dir).await {
            warn!(error = %e, dir = %attempt_dir.display(), "checkpoint tick: cannot create attempt dir; skipping tick");
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

        // 4. Write offsets.json into the attempt dir after create_checkpoint (so it is never frozen
        //    mid-write) but before planning, so the planner tracks it as a non-SST file and the S3
        //    upload carries it — without it an S3 restore has no manifest to seek. metadata.json is
        //    produced by the plan, so it is written after.
        if let Err(e) = manifest.write_to_dir(&attempt_dir) {
            warn!(error = %e, "checkpoint tick: writing offsets.json failed; skipping tick");
            drop(tokio::fs::remove_dir_all(&attempt_dir).await);
            return;
        }

        // 5. Plan the incremental diff vs the last-uploaded baseline, then write metadata.json (the
        //    file registry) into the attempt dir for the local PVC restore path.
        let baseline = { self.last_uploaded.lock().await.clone() };
        let plan = match plan_checkpoint(
            &attempt_dir,
            self.config.s3_key_prefix.clone(),
            attempt_timestamp,
            tick,
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

        let mut info = plan.info.clone();
        if let Err(e) = info.metadata.write_to_dir(&attempt_dir).await {
            warn!(error = %e, "checkpoint tick: writing metadata.json failed; skipping tick");
            drop(tokio::fs::remove_dir_all(&attempt_dir).await);
            return;
        }

        // 6. Emit local-checkpoint size + file-count metrics. (Duration is recorded inside
        //    create_checkpoint via CHECKPOINT_DURATION_SECONDS.)
        let (size_bytes, file_count) = dir_size_and_count(&attempt_dir);
        metrics::histogram!(CHECKPOINT_SIZE_BYTES).record(size_bytes as f64);
        metrics::histogram!(CHECKPOINT_FILE_COUNT).record(file_count as f64);
        info!(
            checkpoint_id,
            dir = %attempt_dir.display(),
            size_bytes,
            file_count,
            "local checkpoint taken",
        );

        // 7. Every Nth tick: upload to S3 and, on success, advance the baseline.
        if should_upload(tick, self.upload_every_n) {
            self.upload(&plan).await;
        }

        // 8. Prune older local checkpoint dirs (keep-latest-1) so retained checkpoints don't pin SSTs
        //    the live DB later compacts away → unbounded PVC growth.
        self.prune_old_checkpoints(&attempt_dir).await;
    }

    /// Upload the just-taken checkpoint incrementally to S3. On success, store its metadata as the new
    /// baseline (so the next diff is vs what is actually in S3); on local-only ticks the baseline is
    /// unchanged. Counts per-file upload status and the overall upload result.
    async fn upload(&self, plan: &super::CheckpointPlan) {
        let files_in_plan = plan.files_to_upload.len();
        match self
            .exporter
            .export_checkpoint_with_plan_cancellable(plan, None, None)
            .await
        {
            Ok(()) => {
                metrics::counter!(CHECKPOINT_FILES_UPLOADED_TOTAL, "status" => "success")
                    .increment(files_in_plan as u64);
                // Advance the baseline under a momentary lock (never held across an await).
                {
                    let mut baseline = self.last_uploaded.lock().await;
                    *baseline = Some(plan.info.metadata.clone());
                }
                info!(uploaded_files = files_in_plan, "checkpoint uploaded to S3");
            }
            Err(e) => {
                // The exporter already counted CHECKPOINT_UPLOADS_TOTAL{result} and logged detail.
                metrics::counter!(CHECKPOINT_FILES_UPLOADED_TOTAL, "status" => "error")
                    .increment(files_in_plan as u64);
                warn!(error = %e, "checkpoint S3 upload failed; baseline unchanged");
            }
        }
    }

    /// Remove every checkpoint attempt dir under the attempt parent except `keep` (the just-taken
    /// one). Best-effort: a failed removal is logged, not fatal.
    async fn prune_old_checkpoints(&self, keep: &Path) {
        let parent = self.attempt_parent();
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

/// Total byte size + file count of a checkpoint directory tree. Best-effort: an unreadable entry is
/// skipped (the metric is observational, not load-bearing).
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
        // every_n = 3 → upload on ticks 0, 3, 6, … (15min upload over 5min checkpoint).
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
        // A misconfigured 0 must not panic the modulo; treated as "every tick".
        assert!(should_upload(0, 0));
        assert!(should_upload(7, 0));
    }

    #[test]
    fn upload_cadence_is_the_interval_ratio_floored_at_one() {
        // 900_000 / 300_000 = 3 (15min upload over 5min checkpoint).
        assert_eq!(upload_cadence(300_000, 900_000), 3);
        // A larger checkpoint interval than the upload interval still uploads every tick.
        assert_eq!(upload_cadence(300_000, 60_000), 1);
        // A zero checkpoint interval cannot divide by zero (floored to dividing by 1).
        assert_eq!(upload_cadence(0, 900_000), 900_000);
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
