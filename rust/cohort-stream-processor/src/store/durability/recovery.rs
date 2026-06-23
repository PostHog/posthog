//! Boot-time restore decision + materialization, run **before** `CohortStore::open`.
//!
//! The entry point is [`run_boot_restore`] (distinct from the top-level `crate::recovery` cold-start
//! stub). It decides where the live store should come from and, for the disaster paths, materializes
//! it at `store_path` so the existing `effective_wipe_on_start` logic then sees `db_dir_exists ==
//! true` and keeps the restored data.
//!
//! ## Precedence
//!
//! 1. **ReopenLive** — an intact, non-stale live store already sits at `store_path`. A normal restart
//!    with an intact PVC lands here; it needs no manifest, because resume-from-committed
//!    (`Offset::Stored`) is safe under the `committed <= durable` invariant.
//! 2. **PvcCheckpoint(dir)** — the live store is gone/stale (lost or corrupt PVC) but a recent local
//!    checkpoint with a readable `offsets.json` exists within `checkpoint_local_max_staleness`.
//! 3. **S3** — no usable local source; restore from the most recent S3 checkpoint.
//! 4. **ColdStart** — nothing to restore; the wipe+replay path takes over.
//!
//! The PVC/S3 branches are **gated behind `checkpoint_enabled`**: with the gate off,
//! [`decide_restore_source`] returns only `ReopenLive` or `ColdStart`.

use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::Result;
use chrono::Utc;
use tracing::{info, warn};

use super::{
    CheckpointImporter, DirCleanupGuard, OffsetManifest, S3Downloader, MANIFEST_FILENAME,
    METADATA_FILENAME,
};
use crate::config::Config;
use crate::observability::metrics::{
    CHECKPOINT_RESTORE_DURATION_SECONDS, CHECKPOINT_RESTORE_TOTAL,
};

/// Where the live store should be sourced from on this boot. Resolved by [`decide_restore_source`]
/// before the store is opened.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RestoreSource {
    /// Reopen the intact live store already at `store_path`. No materialization, no manifest.
    ReopenLive,
    /// Recursive-copy this local PVC checkpoint dir into `store_path`, then read its `offsets.json`.
    PvcCheckpoint(PathBuf),
    /// Download the most recent S3 checkpoint directly into `store_path`, then read its `offsets.json`.
    S3,
    /// Nothing to restore; fall through to the wipe+replay cold path.
    ColdStart,
}

impl RestoreSource {
    /// The `source` metric label (`reopen_live` | `pvc` | `s3` | `cold`).
    fn metric_label(&self) -> &'static str {
        match self {
            RestoreSource::ReopenLive => "reopen_live",
            RestoreSource::PvcCheckpoint(_) => "pvc",
            RestoreSource::S3 => "s3",
            RestoreSource::ColdStart => "cold",
        }
    }
}

/// The result of [`run_boot_restore`]: the chosen source plus the offset manifest that the events
/// consumer seeks to. `manifest` is `None` for the no-seek paths (`ReopenLive`, `ColdStart`) and
/// `Some` for the disaster paths (`PvcCheckpoint`, `S3`).
#[derive(Debug)]
pub struct RestoreOutcome {
    pub source: RestoreSource,
    pub manifest: Option<OffsetManifest>,
}

/// True when `path` looks like a valid, non-empty RocksDB store: the directory exists and contains a
/// `CURRENT` file (RocksDB's manifest pointer, present in every opened DB). A bare or partially-wiped
/// directory without `CURRENT` is treated as absent so reopen-live never resumes from a torn store.
fn live_store_is_intact(path: &Path) -> bool {
    path.is_dir() && path.join("CURRENT").is_file()
}

/// Decide the restore source. Runs before `CohortStore::open`. Touches the filesystem.
///
/// `checkpoint_enabled == false` is the inert default: it can only return `ReopenLive` (intact live
/// store) or `ColdStart` (no live store), never `PvcCheckpoint`/`S3`. When the live store is intact
/// and not slated for a wipe, reopen-live always wins (it takes precedence even over a fresh PVC
/// checkpoint).
pub fn decide_restore_source(config: &Config) -> RestoreSource {
    let store_path = PathBuf::from(&config.store_path);

    // `effective_wipe_on_start()` is `false` exactly when durable restore is on and a store exists;
    // paired with an intact on-disk store, that means reopen-live is safe.
    if !config.effective_wipe_on_start() && live_store_is_intact(&store_path) {
        return RestoreSource::ReopenLive;
    }

    if !config.checkpoint_enabled {
        return RestoreSource::ColdStart;
    }

    if let Some(dir) = newest_fresh_local_checkpoint(config) {
        return RestoreSource::PvcCheckpoint(dir);
    }

    // Return S3 here; `run_boot_restore` downgrades to cold if no S3 checkpoint is found, keeping
    // the network-free `decide_restore_source` cheap.
    RestoreSource::S3
}

/// Scan `checkpoint_local_dir` for the newest checkpoint attempt directory that (a) carries a
/// readable `offsets.json` and (b) was captured within `checkpoint_local_max_staleness`. A
/// manifest-less directory is unusable (we cannot align offsets) and is skipped; a too-old directory
/// is distrusted (another pod likely advanced the partitions while we were down) and falls through to
/// S3.
fn newest_fresh_local_checkpoint(config: &Config) -> Option<PathBuf> {
    let base = PathBuf::from(&config.checkpoint_local_dir);
    let max_staleness = config.checkpoint_local_max_staleness();
    let now = Utc::now();

    let mut best: Option<(chrono::DateTime<Utc>, PathBuf)> = None;
    for dir in checkpoint_attempt_dirs(&base) {
        // The manifest is authoritative for the capture instant and is required for the seek; a dir
        // without a readable, version-matching one is unusable.
        let Ok(manifest) = OffsetManifest::load_from_dir(&dir) else {
            continue;
        };
        let age = now.signed_duration_since(manifest.captured_at);
        // A future-dated capture (clock skew) maps to a negative duration, which is treated as 0 → fresh.
        let within_bound = age
            .to_std()
            .map(|elapsed| elapsed <= max_staleness)
            .unwrap_or(true);
        if !within_bound {
            continue;
        }
        match &best {
            Some((best_at, _)) if *best_at >= manifest.captured_at => {}
            _ => best = Some((manifest.captured_at, dir)),
        }
    }
    best.map(|(_, dir)| dir)
}

/// Enumerate candidate checkpoint attempt directories under `base`. A checkpoint attempt dir is the
/// leaf that holds the RocksDB files + `metadata.json` + `offsets.json`; the planner lays them out as
/// `<base>/<topic>/<partition>/<checkpoint_id>`, so the candidates are the directories that contain a
/// `metadata.json`. Walks defensively: any unreadable level yields no candidates rather than erroring.
fn checkpoint_attempt_dirs(base: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![base.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        // A dir that directly holds metadata.json is an attempt leaf; otherwise descend.
        if dir.join(METADATA_FILENAME).is_file() {
            out.push(dir);
            continue;
        }
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            }
        }
    }
    out
}

/// Materialize `store_path` from the decided source and return the outcome (source + manifest).
///
/// - `ReopenLive` → no-op (store already in place), `manifest: None`.
/// - `PvcCheckpoint(dir)` → recursive-copy `dir` into `store_path`, read `offsets.json`.
/// - `S3` → import the newest S3 checkpoint into `store_path`, read the downloaded `offsets.json`;
///   if no S3 checkpoint is usable, downgrade to a cold start.
/// - `ColdStart` → no-op, `manifest: None`.
///
/// Always emits `CHECKPOINT_RESTORE_TOTAL{source}` + `CHECKPOINT_RESTORE_DURATION_SECONDS` and a
/// one-line boot summary.
pub async fn run_boot_restore(config: &Config, store_path: &Path) -> RestoreOutcome {
    let started = Instant::now();
    let decided = decide_restore_source(config);

    let outcome = match decided {
        RestoreSource::ReopenLive => RestoreOutcome {
            source: RestoreSource::ReopenLive,
            manifest: None,
        },
        RestoreSource::ColdStart => RestoreOutcome {
            source: RestoreSource::ColdStart,
            manifest: None,
        },
        RestoreSource::PvcCheckpoint(dir) => restore_from_pvc(&dir, store_path),
        RestoreSource::S3 => restore_from_s3(config, store_path).await,
    };

    let label = outcome.source.metric_label();
    metrics::counter!(CHECKPOINT_RESTORE_TOTAL, "source" => label).increment(1);
    metrics::histogram!(CHECKPOINT_RESTORE_DURATION_SECONDS)
        .record(started.elapsed().as_secs_f64());

    info!(
        source = label,
        store_path = %store_path.display(),
        seek_topics = outcome
            .manifest
            .as_ref()
            .map_or(0, |m| m.topics.len()),
        elapsed_secs = started.elapsed().as_secs_f64(),
        "boot restore decided",
    );

    outcome
}

/// Recursive-copy a local PVC checkpoint into `store_path`, then read its manifest. On any copy or
/// manifest failure, downgrade to a cold start (the wipe+replay path is always safe).
fn restore_from_pvc(checkpoint_dir: &Path, store_path: &Path) -> RestoreOutcome {
    // Remove any partial store before copying so the restored DB is the only content.
    if store_path.exists() {
        if let Err(e) = std::fs::remove_dir_all(store_path) {
            warn!(error = %e, store_path = %store_path.display(), "failed to clear store before PVC restore; cold start");
            return cold_downgrade();
        }
    }

    // `copy_dir_recursive` is non-atomic: a mid-copy failure (disk full, transient I/O) leaves a
    // half-written dir at `store_path`. Without cleanup the next boot would keep it (the wipe is
    // skipped once the dir exists) and `decide_restore_source` would pick ReopenLive over a fresh
    // restore — silently empty if `CURRENT` was missed, crash-looping if its SSTs were. The guard
    // wipes the partial dir on every early return so a cold-start *outcome* actually starts cold.
    //
    // Residual: a SIGKILL *mid-copy* runs no Rust code, so the guard cannot fire; closing that needs
    // a crash-safe copy (temp dir + atomic rename, or copy `CURRENT` last). Deferred follow-up.
    let guard = DirCleanupGuard::new(store_path.to_path_buf());

    if let Err(e) = copy_dir_recursive(checkpoint_dir, store_path) {
        warn!(error = %e, from = %checkpoint_dir.display(), "PVC checkpoint copy failed; cold start");
        return cold_downgrade();
    }
    match OffsetManifest::load_from_dir(store_path) {
        Ok(manifest) => {
            guard.defuse();
            RestoreOutcome {
                source: RestoreSource::PvcCheckpoint(checkpoint_dir.to_path_buf()),
                manifest: Some(manifest),
            }
        }
        Err(e) => {
            warn!(error = %e, "PVC checkpoint manifest unreadable after copy; cold start");
            cold_downgrade()
        }
    }
}

/// Import the newest usable S3 checkpoint directly into `store_path`, then read the downloaded
/// manifest. On any failure (no S3 config, no usable checkpoint, unreadable manifest), downgrade to a
/// cold start.
async fn restore_from_s3(config: &Config, store_path: &Path) -> RestoreOutcome {
    let durability = config.durability_config();
    let downloader = match S3Downloader::new(&durability).await {
        Ok(downloader) => downloader,
        Err(e) => {
            warn!(error = %e, "S3 downloader unavailable; cold start");
            return cold_downgrade();
        }
    };
    let importer = CheckpointImporter::new(
        Box::new(downloader),
        durability.checkpoint_import_attempt_depth,
        durability.checkpoint_import_timeout,
    );

    match importer.import_checkpoint(store_path).await {
        Ok(_imported_path) => match OffsetManifest::load_from_dir(store_path) {
            Ok(manifest) => RestoreOutcome {
                source: RestoreSource::S3,
                manifest: Some(manifest),
            },
            Err(e) => {
                warn!(error = %e, "S3 checkpoint imported but {MANIFEST_FILENAME} unreadable; cold start");
                cold_downgrade()
            }
        },
        Err(e) => {
            warn!(error = %e, "no usable S3 checkpoint to restore; cold start");
            cold_downgrade()
        }
    }
}

/// A failed disaster-restore path falls back to a cold start: no manifest, wipe+replay takes over.
fn cold_downgrade() -> RestoreOutcome {
    RestoreOutcome {
        source: RestoreSource::ColdStart,
        manifest: None,
    }
}

/// Recursively copy `from` into `to` (creating `to`).
fn copy_dir_recursive(from: &Path, to: &Path) -> Result<()> {
    std::fs::create_dir_all(to)?;
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let src = entry.path();
        let dst = to.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_recursive(&src, &dst)?;
        } else {
            std::fs::copy(&src, &dst)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::durability::{CheckpointMetadata, STORE_PARTITION, STORE_TOPIC};
    use chrono::Duration as ChronoDuration;
    use envconfig::Envconfig;
    use std::collections::BTreeMap;
    use tempfile::TempDir;

    fn config_with(checkpoint_enabled: bool, store_path: &Path, checkpoint_dir: &Path) -> Config {
        let mut config = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        config.checkpoint_enabled = checkpoint_enabled;
        // Durable restore must be on for reopen-live to ever beat a wipe (effective_wipe folds it in).
        config.durable_restore_enabled = true;
        config.wipe_store_on_start = true;
        config.store_path = store_path.to_string_lossy().into_owned();
        config.checkpoint_local_dir = checkpoint_dir.to_string_lossy().into_owned();
        config
    }

    fn make_live_store(path: &Path) {
        std::fs::create_dir_all(path).unwrap();
        std::fs::write(path.join("CURRENT"), b"MANIFEST-000001\n").unwrap();
    }

    fn make_local_checkpoint(base: &Path, id: &str, age: ChronoDuration) -> PathBuf {
        let attempt = base
            .join(STORE_TOPIC)
            .join(STORE_PARTITION.to_string())
            .join(id);
        std::fs::create_dir_all(&attempt).unwrap();
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            Utc::now(),
            1,
            0,
            0,
        );
        let json = metadata.to_json().unwrap();
        std::fs::write(attempt.join(METADATA_FILENAME), json).unwrap();
        let mut topics = BTreeMap::new();
        topics.insert(
            "cohort_stream_events".to_string(),
            BTreeMap::from([(0, 42)]),
        );
        let manifest = OffsetManifest {
            version: super::super::manifest::MANIFEST_VERSION,
            captured_at: Utc::now() - age,
            topics,
        };
        manifest.write_to_dir(&attempt).unwrap();
        attempt
    }

    #[test]
    fn reopen_live_takes_precedence_over_a_fresh_checkpoint() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let checkpoint_dir = tmp.path().join("ckpt");
        make_live_store(&store_path);
        make_local_checkpoint(
            &checkpoint_dir,
            "2026-06-17T00-00-00Z",
            ChronoDuration::minutes(1),
        );

        let config = config_with(true, &store_path, &checkpoint_dir);
        assert_eq!(decide_restore_source(&config), RestoreSource::ReopenLive);
    }

    #[test]
    fn pvc_checkpoint_chosen_when_live_store_is_gone() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let checkpoint_dir = tmp.path().join("ckpt");
        let attempt = make_local_checkpoint(
            &checkpoint_dir,
            "2026-06-17T00-00-00Z",
            ChronoDuration::minutes(5),
        );

        let config = config_with(true, &store_path, &checkpoint_dir);
        assert_eq!(
            decide_restore_source(&config),
            RestoreSource::PvcCheckpoint(attempt),
        );
    }

    #[test]
    fn the_newest_fresh_checkpoint_is_chosen() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let checkpoint_dir = tmp.path().join("ckpt");
        let _older = make_local_checkpoint(
            &checkpoint_dir,
            "2026-06-17T00-00-00Z",
            ChronoDuration::minutes(30),
        );
        let newer = make_local_checkpoint(
            &checkpoint_dir,
            "2026-06-17T01-00-00Z",
            ChronoDuration::minutes(2),
        );

        let config = config_with(true, &store_path, &checkpoint_dir);
        assert_eq!(
            decide_restore_source(&config),
            RestoreSource::PvcCheckpoint(newer),
        );
    }

    #[test]
    fn a_stale_checkpoint_falls_through_to_s3() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let max_staleness_secs = 7200;

        let stale_dir = tmp.path().join("ckpt_stale");
        make_local_checkpoint(
            &stale_dir,
            "2026-06-17T00-00-00Z",
            ChronoDuration::seconds(max_staleness_secs as i64 + 60),
        );
        let mut config = config_with(true, &store_path, &stale_dir);
        config.checkpoint_local_max_staleness_secs = max_staleness_secs;
        assert_eq!(
            decide_restore_source(&config),
            RestoreSource::S3,
            "a checkpoint older than max_staleness must not be trusted",
        );

        let fresh_dir = tmp.path().join("ckpt_fresh");
        let fresh = make_local_checkpoint(
            &fresh_dir,
            "2026-06-17T00-30-00Z",
            ChronoDuration::seconds(max_staleness_secs as i64 - 60),
        );
        config.checkpoint_local_dir = fresh_dir.to_string_lossy().into_owned();
        assert_eq!(
            decide_restore_source(&config),
            RestoreSource::PvcCheckpoint(fresh),
        );
    }

    #[test]
    fn a_manifest_less_checkpoint_dir_is_skipped() {
        // A dir with metadata.json but no offsets.json cannot align offsets → unusable.
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let checkpoint_dir = tmp.path().join("ckpt");
        let attempt = checkpoint_dir
            .join(STORE_TOPIC)
            .join(STORE_PARTITION.to_string())
            .join("2026-06-17T00-00-00Z");
        std::fs::create_dir_all(&attempt).unwrap();
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            Utc::now(),
            1,
            0,
            0,
        );
        std::fs::write(attempt.join(METADATA_FILENAME), metadata.to_json().unwrap()).unwrap();
        // offsets.json intentionally absent

        let config = config_with(true, &store_path, &checkpoint_dir);
        assert_eq!(decide_restore_source(&config), RestoreSource::S3);
    }

    #[test]
    fn cold_start_when_no_store_no_checkpoint_and_gate_on() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let checkpoint_dir = tmp.path().join("ckpt");

        let config = config_with(true, &store_path, &checkpoint_dir);
        // Gate on but no live store or local checkpoint → S3 (importer downgrades to cold if empty).
        assert_eq!(decide_restore_source(&config), RestoreSource::S3);
    }

    #[test]
    fn gate_off_never_picks_a_disaster_path() {
        let tmp = TempDir::new().unwrap();
        let checkpoint_dir = tmp.path().join("ckpt");
        make_local_checkpoint(
            &checkpoint_dir,
            "2026-06-17T00-00-00Z",
            ChronoDuration::minutes(1),
        );

        let absent = tmp.path().join("absent");
        let config_absent = config_with(false, &absent, &checkpoint_dir);
        assert_eq!(
            decide_restore_source(&config_absent),
            RestoreSource::ColdStart
        );

        let present = tmp.path().join("present");
        make_live_store(&present);
        let config_present = config_with(false, &present, &checkpoint_dir);
        assert_eq!(
            decide_restore_source(&config_present),
            RestoreSource::ReopenLive
        );
    }

    #[tokio::test]
    async fn run_boot_restore_reopen_live_is_a_noop_with_no_manifest() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let checkpoint_dir = tmp.path().join("ckpt");
        make_live_store(&store_path);
        let config = config_with(true, &store_path, &checkpoint_dir);

        let outcome = run_boot_restore(&config, &store_path).await;
        assert_eq!(outcome.source, RestoreSource::ReopenLive);
        assert!(
            outcome.manifest.is_none(),
            "reopen-live needs no manifest (resume-from-committed)",
        );
        assert!(store_path.join("CURRENT").is_file());
    }

    #[tokio::test]
    async fn run_boot_restore_copies_a_pvc_checkpoint_into_the_store_path() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        let checkpoint_dir = tmp.path().join("ckpt");
        let attempt = make_local_checkpoint(
            &checkpoint_dir,
            "2026-06-17T00-00-00Z",
            ChronoDuration::minutes(3),
        );
        std::fs::write(attempt.join("000001.sst"), b"sst-bytes").unwrap();

        let config = config_with(true, &store_path, &checkpoint_dir);
        let outcome = run_boot_restore(&config, &store_path).await;

        assert!(matches!(outcome.source, RestoreSource::PvcCheckpoint(_)));
        let manifest = outcome.manifest.expect("PVC restore yields a manifest");
        assert_eq!(manifest.offset_for("cohort_stream_events", 0), Some(42));
        assert!(store_path.join("000001.sst").is_file());
        assert!(store_path.join(MANIFEST_FILENAME).is_file());
    }

    #[test]
    fn restore_from_pvc_wipes_a_partial_store_when_the_copy_fails() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        // A leftover partial store from a prior torn restore that the copy must not preserve.
        std::fs::create_dir_all(&store_path).unwrap();
        std::fs::write(store_path.join("000001.sst"), b"torn").unwrap();

        // A non-existent checkpoint dir makes `copy_dir_recursive`'s `read_dir` fail mid-restore.
        let missing = tmp.path().join("nonexistent_checkpoint");

        let outcome = restore_from_pvc(&missing, &store_path);
        assert_eq!(outcome.source, RestoreSource::ColdStart);
        assert!(
            !store_path.exists(),
            "the guard must wipe the partial store so the cold-start outcome actually starts cold",
        );
    }

    #[test]
    fn restore_from_pvc_wipes_the_store_when_the_manifest_is_unreadable() {
        let tmp = TempDir::new().unwrap();
        let store_path = tmp.path().join("store");
        // A checkpoint dir that copies cleanly but carries no offsets.json → manifest load fails.
        let checkpoint_dir = tmp.path().join("ckpt");
        std::fs::create_dir_all(&checkpoint_dir).unwrap();
        std::fs::write(checkpoint_dir.join("CURRENT"), b"MANIFEST-000001\n").unwrap();

        let outcome = restore_from_pvc(&checkpoint_dir, &store_path);
        assert_eq!(outcome.source, RestoreSource::ColdStart);
        assert!(
            !store_path.exists(),
            "an unreadable manifest after copy must leave no partial store behind",
        );
    }

    #[test]
    fn manifest_is_none_for_reopen_live_and_cold_some_for_disaster_paths() {
        let reopen = RestoreOutcome {
            source: RestoreSource::ReopenLive,
            manifest: None,
        };
        let cold = RestoreOutcome {
            source: RestoreSource::ColdStart,
            manifest: None,
        };
        let pvc = RestoreOutcome {
            source: RestoreSource::PvcCheckpoint(PathBuf::from("/x")),
            manifest: Some(OffsetManifest {
                version: super::super::manifest::MANIFEST_VERSION,
                captured_at: Utc::now(),
                topics: BTreeMap::new(),
            }),
        };
        assert!(reopen.manifest.is_none());
        assert!(cold.manifest.is_none());
        assert!(pvc.manifest.is_some());
    }
}
