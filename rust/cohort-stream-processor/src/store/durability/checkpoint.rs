//! The checkpoint orchestrator.
//!
//! [`CheckpointSweeper`] is one sweep loop, driven by
//! [`run_sweep_loop`](crate::sweep::run_sweep_loop) at `checkpoint_interval`. Each tick takes a frozen
//! whole-DB RocksDB checkpoint to the local PVC; every Nth tick it also uploads that checkpoint to S3
//! incrementally (only the SSTs that changed). One `create_checkpoint` per tick — never two racing.
//!
//! ## Final checkpoint on shutdown
//!
//! [`run_checkpoint_loop`] stops the timer when shutdown begins. It then waits until the consumers
//! have drained and made their last commit, and takes one final checkpoint that it always uploads.
//! A restore from that checkpoint replays nothing that the pod had committed before it stopped.
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

// The checkpoint sweeper offloads its own store I/O (its own `spawn_blocking` + log-and-skip on
// every `JoinError`) to honor the must-not-panic policy above, so its direct `CohortStore` calls are
// sanctioned. See `checkpoint_once`.
#![allow(clippy::disallowed_methods)]

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::Utc;
use lifecycle::Handle;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use super::{
    plan_checkpoint, CheckpointExporter, CheckpointMetadata, CheckpointOwner, DurabilityConfig,
    OffsetManifest,
};
use crate::consumers::EventDispatcher;
use crate::observability::disk::sample_store_filesystem;
use crate::observability::metrics::{
    CHECKPOINT_FILES_UPLOADED_TOTAL, CHECKPOINT_FILE_COUNT, CHECKPOINT_FINAL_DURATION_SECONDS,
    CHECKPOINT_FINAL_TOTAL, CHECKPOINT_RESTORE_HEADROOM_BYTES, CHECKPOINT_SIZE_BYTES,
    CHECKPOINT_UPLOADS_TOTAL,
};
use crate::partitions::OffsetTracker;
use crate::store::CohortStore;
use crate::sweep::{run_sweep_loop, Sweeper};

/// The loop-name label for the checkpoint sweep cycle metrics.
pub const CHECKPOINT_LOOP_NAME: &str = "checkpoint";

/// One topic and the [`OffsetTracker`] that tracks its committed positions, passed to
/// [`CheckpointSweeper::new`].
pub type TrackedTopic = (String, Arc<OffsetTracker>);

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

/// Drives periodic whole-DB checkpoints to the local PVC + incremental S3 backup.
pub struct CheckpointSweeper {
    store: CohortStore,
    dispatcher: Arc<EventDispatcher>,
    /// The `(topic, tracker)` pairs whose committed offsets the manifest captures.
    trackers: Vec<TrackedTopic>,
    exporter: CheckpointExporter,
    config: DurabilityConfig,
    /// Base dir for local checkpoints; a sibling subtree of `store_path` (RocksDB hard-links SSTs, so
    /// it must be on the same filesystem and must not be a child of the store path).
    checkpoint_local_dir: PathBuf,
    tick: AtomicU64,
    upload_every_n: u64,
    /// Baseline for the next incremental S3 diff. Cloned out before the upload await (never held
    /// across `.await`); updated only after a successful upload. `None` until the first upload.
    last_uploaded: Mutex<Option<CheckpointMetadata>>,
}

impl CheckpointSweeper {
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

    fn attempt_parent(&self) -> PathBuf {
        self.config
            .identity()
            .local_attempt_parent(&self.checkpoint_local_dir)
    }

    /// Take one checkpoint of `owned` and upload it on the upload cadence, or always when
    /// `final_upload` is set. Returns `true` only when the upload succeeds.
    async fn checkpoint_once(
        &self,
        mut owned: Vec<i32>,
        final_upload: Option<&CancellationToken>,
    ) -> bool {
        let tick = self.tick.fetch_add(1, Ordering::SeqCst);

        // The checkpoint sweeper runs its own `spawn_blocking` and catches every `JoinError` to
        // log-and-skip: the `Sweeper` contract forbids panicking (a panic aborts the timer task and
        // stops all future checkpoints), so store panics must not propagate out of this loop.
        //
        // 1. fsync the WAL before the snapshot so `committed <= durable` holds. A failure here would
        //    yield a checkpoint whose manifest claims more than is durable — skip the tick.
        let flush_store = self.store.clone();
        let flush_result = tokio::task::spawn_blocking(move || flush_store.flush_wal_sync()).await;
        match flush_result {
            Ok(Ok(())) => {}
            Ok(Err(e)) => {
                warn!(error = %e, "checkpoint tick: WAL fsync failed; skipping tick");
                metrics::counter!(CHECKPOINT_UPLOADS_TOTAL, "result" => "flush_failed")
                    .increment(1);
                return false;
            }
            Err(join_err) => {
                error!(error = %join_err, "checkpoint tick: WAL fsync task panicked; skipping tick");
                metrics::counter!(CHECKPOINT_UPLOADS_TOTAL, "result" => "flush_failed")
                    .increment(1);
                return false;
            }
        }

        // 2. Capture committed offsets (not committable/processed) for all owned partitions.
        owned.sort_unstable();
        let tracker_refs: Vec<(&str, &OffsetTracker)> = self
            .trackers
            .iter()
            .map(|(topic, tracker)| (topic.as_str(), tracker.as_ref()))
            .collect();
        let owner = CheckpointOwner {
            pod_count: self.config.pod_count,
            ordinal: self.config.ordinal,
            owned_partitions: owned.clone(),
        };
        let manifest = OffsetManifest::capture(&owned, &tracker_refs).with_owner(owner.clone());

        // 3. Take a whole-DB RocksDB checkpoint (sync I/O → spawn_blocking). The attempt dir must
        //    not be a child of store_path; SST hard-links require the same filesystem.
        let attempt_timestamp = Utc::now();
        let checkpoint_id = format!(
            "{}-{tick}",
            CheckpointMetadata::generate_id(attempt_timestamp)
        );
        let attempt_dir = self.attempt_parent().join(&checkpoint_id);
        // `create_checkpoint` requires the leaf to NOT exist; it creates it and errors if it does.
        if let Err(e) = tokio::fs::create_dir_all(self.attempt_parent()).await {
            warn!(error = %e, dir = %self.attempt_parent().display(), "checkpoint tick: cannot create attempt parent dir; skipping tick");
            return false;
        }
        let checkpoint_store = self.store.clone();
        let checkpoint_dir = attempt_dir.clone();
        debug_assert!(
            !attempt_dir.exists(),
            "checkpoint attempt dir must not exist before create_checkpoint: {}",
            attempt_dir.display(),
        );
        let create_result = tokio::task::spawn_blocking(move || {
            checkpoint_store.create_checkpoint(&checkpoint_dir)
        })
        .await;
        match create_result {
            Ok(Ok(())) => {}
            Ok(Err(e)) => {
                warn!(error = %e, "checkpoint tick: create_checkpoint failed; skipping tick");
                drop(tokio::fs::remove_dir_all(&attempt_dir).await);
                return false;
            }
            Err(join_err) => {
                error!(error = %join_err, "checkpoint tick: create_checkpoint task panicked; skipping tick");
                drop(tokio::fs::remove_dir_all(&attempt_dir).await);
                return false;
            }
        }

        // 4. Write offsets.json after create_checkpoint (so it is never frozen mid-write) but before
        //    planning, so the planner tracks it as a non-SST file and the S3 upload carries it.
        //    Without offsets.json an S3 restore cannot seek. metadata.json is written after planning.
        if let Err(e) = manifest.write_to_dir(&attempt_dir) {
            warn!(error = %e, "checkpoint tick: writing offsets.json failed; skipping tick");
            drop(tokio::fs::remove_dir_all(&attempt_dir).await);
            return false;
        }

        // 5. Plan the incremental diff vs the last-uploaded baseline, then write metadata.json.
        let baseline = { self.last_uploaded.lock().await.clone() };
        let plan = match plan_checkpoint(
            &attempt_dir,
            self.config.s3_key_prefix.clone(),
            attempt_timestamp,
            tick,
            owner,
            baseline.as_ref(),
            None,
        ) {
            Ok(plan) => plan,
            Err(e) => {
                warn!(error = %e, "checkpoint tick: planning failed; skipping tick");
                drop(tokio::fs::remove_dir_all(&attempt_dir).await);
                return false;
            }
        };

        let mut info = plan.info.clone();
        if let Err(e) = info.metadata.write_to_dir(&attempt_dir).await {
            warn!(error = %e, "checkpoint tick: writing metadata.json failed; skipping tick");
            drop(tokio::fs::remove_dir_all(&attempt_dir).await);
            return false;
        }

        // 6. Emit local-checkpoint size and file-count metrics.
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
        record_restore_headroom(&attempt_dir, size_bytes);

        // 7. Every Nth tick, and always for the final checkpoint: upload to S3 and advance the
        //    baseline on success.
        let uploaded = if final_upload.is_some() || should_upload(tick, self.upload_every_n) {
            self.upload(&plan, final_upload).await
        } else {
            false
        };

        // 8. Prune older local checkpoint dirs (keep latest only) to avoid pinning SSTs that the live
        //    DB compacted away, which would cause unbounded PVC growth.
        self.prune_old_checkpoints(&attempt_dir).await;
        uploaded
    }

    /// Take the shutdown checkpoint of `owned` and upload it. `upload_timeout` cancels the upload,
    /// so the pod stops inside its graceful shutdown window. Returns `true` when the upload succeeds.
    pub async fn final_checkpoint(&self, owned: Vec<i32>, upload_timeout: Duration) -> bool {
        let started = Instant::now();
        let cancel = CancellationToken::new();
        let deadline = {
            let cancel = cancel.clone();
            tokio::spawn(async move {
                tokio::time::sleep(upload_timeout).await;
                cancel.cancel();
            })
        };
        let partitions = owned.len();
        let uploaded = self.checkpoint_once(owned, Some(&cancel)).await;
        deadline.abort();

        let elapsed = started.elapsed().as_secs_f64();
        metrics::histogram!(CHECKPOINT_FINAL_DURATION_SECONDS).record(elapsed);
        if uploaded {
            metrics::counter!(CHECKPOINT_FINAL_TOTAL, "result" => "uploaded").increment(1);
            info!(
                partitions,
                elapsed_secs = elapsed,
                "final checkpoint uploaded"
            );
        } else {
            metrics::counter!(CHECKPOINT_FINAL_TOTAL, "result" => "failed").increment(1);
            warn!(
                partitions,
                elapsed_secs = elapsed,
                timed_out = cancel.is_cancelled(),
                "final checkpoint not uploaded; the next restore replays from the last periodic upload",
            );
        }
        uploaded
    }

    async fn upload(
        &self,
        plan: &super::CheckpointPlan,
        cancel: Option<&CancellationToken>,
    ) -> bool {
        let files_in_plan = plan.files_to_upload.len();
        let cause = cancel.map(|_| "shutdown");
        match self
            .exporter
            .export_checkpoint_with_plan_cancellable(plan, cancel, cause)
            .await
        {
            Ok(()) => {
                metrics::counter!(CHECKPOINT_FILES_UPLOADED_TOTAL, "status" => "success")
                    .increment(files_in_plan as u64);
                {
                    let mut baseline = self.last_uploaded.lock().await;
                    *baseline = Some(plan.info.metadata.clone());
                }
                info!(uploaded_files = files_in_plan, "checkpoint uploaded to S3");
                true
            }
            Err(e) => {
                metrics::counter!(CHECKPOINT_FILES_UPLOADED_TOTAL, "status" => "error")
                    .increment(files_in_plan as u64);
                warn!(error = %e, "checkpoint S3 upload failed; baseline unchanged");
                false
            }
        }
    }

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
        self.checkpoint_once(self.dispatcher.owned_partitions(), None)
            .await;
    }
}

/// Drive the periodic checkpoints until `stop` fires, then take the final checkpoint once `handle`
/// signals. Register `handle` in a shutdown phase after the consumers, so it signals only after they
/// have drained and made their last commit.
///
/// The owned partitions are captured when `stop` fires. Closing the events consumer later revokes
/// its partitions and empties the live owned set, but the store and the trackers keep their state,
/// because the rebalance worker stops on the same signal.
pub async fn run_checkpoint_loop(
    sweeper: Arc<CheckpointSweeper>,
    interval: Duration,
    stop: CancellationToken,
    handle: Handle,
    final_upload_timeout: Duration,
) {
    let ((), owned) = tokio::join!(
        run_sweep_loop(
            sweeper.clone(),
            interval,
            CHECKPOINT_LOOP_NAME,
            stop.clone()
        ),
        async {
            stop.cancelled().await;
            sweeper.dispatcher.owned_partitions()
        },
    );
    handle.shutdown_recv().await;
    sweeper.final_checkpoint(owned, final_upload_timeout).await;
    handle.work_completed();
}

/// Publish the restore headroom of the volume that holds `checkpoint_dir`. A failed sample is
/// skipped: the gauge is advisory.
fn record_restore_headroom(checkpoint_dir: &Path, checkpoint_bytes: u64) {
    let Ok(disk) = sample_store_filesystem(checkpoint_dir) else {
        return;
    };
    let headroom = restore_headroom_bytes(disk.available_bytes, checkpoint_bytes);
    metrics::gauge!(CHECKPOINT_RESTORE_HEADROOM_BYTES).set(headroom as f64);
    if headroom < 0 {
        warn!(
            available_bytes = disk.available_bytes,
            checkpoint_bytes, "the volume has no room to stage a restore of the newest checkpoint",
        );
    }
}

/// Free bytes left after a restore stages a copy of a checkpoint of `checkpoint_bytes`.
fn restore_headroom_bytes(available_bytes: u64, checkpoint_bytes: u64) -> i64 {
    let available = i64::try_from(available_bytes).unwrap_or(i64::MAX);
    let checkpoint = i64::try_from(checkpoint_bytes).unwrap_or(i64::MAX);
    available.saturating_sub(checkpoint)
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
    use std::sync::Mutex as StdMutex;

    use lifecycle::{ComponentOptions, Manager};

    use crate::filters::{CatalogHandle, FilterCatalog};
    use crate::producer::{CaptureSink, MembershipSink};
    use crate::store::durability::{CheckpointPlan, CheckpointUploader};
    use crate::store::{OffloadConfig, OffloadMode, StoreConfig, StoreHandle};
    use crate::workers::MergeWorkerDeps;

    #[derive(Debug, Default)]
    struct RecordingUploader {
        owners: Arc<StdMutex<Vec<Option<CheckpointOwner>>>>,
    }

    #[async_trait]
    impl CheckpointUploader for RecordingUploader {
        async fn upload_checkpoint_with_plan_cancellable(
            &self,
            plan: &CheckpointPlan,
            _cancel_token: Option<&CancellationToken>,
        ) -> anyhow::Result<Vec<String>> {
            self.owners
                .lock()
                .unwrap()
                .push(plan.info.metadata.owner.clone());
            Ok(vec![])
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn the_final_checkpoint_keeps_the_partitions_owned_when_shutdown_began() {
        let dir = tempfile::TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let handle = StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        );
        let sink: Arc<dyn MembershipSink> = Arc::new(CaptureSink::new());
        let dispatcher = Arc::new(EventDispatcher::new(
            crate::partitions::PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            handle,
            Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([]))),
            sink,
            MergeWorkerDeps::capture(),
        ));
        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);

        let uploader = RecordingUploader::default();
        let owners = uploader.owners.clone();
        let sweeper = Arc::new(CheckpointSweeper::new(
            store,
            dispatcher.clone(),
            vec![],
            CheckpointExporter::new(Box::new(uploader)),
            DurabilityConfig::default(),
            dir.path().join("checkpoints"),
            u64::MAX,
        ));

        let shutdown = CancellationToken::new();
        let mut manager = Manager::builder("checkpoint-test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_shutdown_token(shutdown.clone())
            .build();
        let consumer = manager.register(
            "consumer",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(10)),
        );
        let checkpoint = manager.register(
            "checkpoint",
            ComponentOptions::new()
                .with_graceful_shutdown(Duration::from_secs(10))
                .with_shutdown_phase(1),
        );
        let guard = manager.monitor_background();
        let checkpoint_loop = tokio::spawn(run_checkpoint_loop(
            sweeper,
            Duration::from_secs(3600),
            consumer.shutdown_token(),
            checkpoint,
            Duration::from_secs(5),
        ));

        // The first timer tick uploads; later ticks never do, because the cadence is u64::MAX.
        tokio::time::sleep(Duration::from_millis(200)).await;
        let periodic_uploads = owners.lock().unwrap().len();
        shutdown.cancel();
        tokio::time::sleep(Duration::from_millis(200)).await;
        // Closing the events consumer revokes its partitions after the drain.
        dispatcher.revoke_partition_sync(0);
        dispatcher.revoke_partition_sync(1);
        assert_eq!(
            owners.lock().unwrap().len(),
            periodic_uploads,
            "no final upload before the consumers finish"
        );
        consumer.work_completed();

        guard.wait().await.unwrap();
        checkpoint_loop.await.unwrap();
        let owners = owners.lock().unwrap();
        assert_eq!(owners.len(), periodic_uploads + 1, "one final upload");
        assert_eq!(
            owners[periodic_uploads]
                .as_ref()
                .map(|owner| owner.owned_partitions.clone()),
            Some(vec![0, 1]),
        );
    }

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
    fn restore_headroom_goes_negative_when_the_copy_does_not_fit() {
        assert_eq!(restore_headroom_bytes(100, 40), 60);
        assert_eq!(restore_headroom_bytes(40, 100), -60);
        assert_eq!(restore_headroom_bytes(u64::MAX, 0), i64::MAX);
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
