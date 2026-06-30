use std::path::{Path, PathBuf};

use anyhow::{Context, Error};
use tracing::{debug, info, warn};

use crate::error::UserError;

/// Default amount of freshly-written data between staging-size checks. Stat-ing
/// the whole staging tree is O(files), so we only re-measure after this much has
/// been written, bounding overshoot to roughly this value plus one download chunk.
const DEFAULT_GUARD_CHECK_INTERVAL_BYTES: u64 = 256 * 1024 * 1024;

/// Fail-fast guard against unbounded staging growth.
///
/// Sources that download large parts call [`StagingGuard::check`] before starting
/// (to catch staging that is already over budget from earlier work) and
/// [`StagingGuard::record`] as they write. If staging exceeds the configured
/// limit the job is paused via a [`UserError`] instead of the pod being evicted
/// under disk pressure (which loses all progress and restart-loops). A limit of
/// `0` disables the guard.
pub struct StagingGuard {
    staging_dir: PathBuf,
    max_bytes: u64,
    check_interval: u64,
    since_check: u64,
}

impl StagingGuard {
    pub fn new(staging_dir: PathBuf, max_bytes: u64) -> Self {
        Self {
            staging_dir,
            max_bytes,
            check_interval: DEFAULT_GUARD_CHECK_INTERVAL_BYTES,
            since_check: 0,
        }
    }

    fn enabled(&self) -> bool {
        self.max_bytes > 0
    }

    /// Record `written` freshly-staged bytes and re-check the staging size once
    /// enough has accumulated since the last check. Cheap to call per chunk.
    pub async fn record(&mut self, written: u64) -> Result<(), Error> {
        if !self.enabled() {
            return Ok(());
        }
        self.since_check = self.since_check.saturating_add(written);
        if self.since_check < self.check_interval {
            return Ok(());
        }
        self.since_check = 0;
        self.check().await
    }

    /// Measure staging usage now and fail if it exceeds the limit.
    pub async fn check(&self) -> Result<(), Error> {
        if !self.enabled() {
            return Ok(());
        }
        let used = staging_dir_bytes(&self.staging_dir).await;
        if used > self.max_bytes {
            crate::metrics::staging_guard_tripped();
            let user_msg = format!(
                "Staging disk limit exceeded ({used} bytes used, limit {} bytes). This import \
                 part is too large to process on a single worker -- split the import into smaller \
                 date ranges or parts.",
                self.max_bytes
            );
            return Err(Error::msg(format!(
                "staging dir {} at {used} bytes exceeds limit {}",
                self.staging_dir.display(),
                self.max_bytes
            ))
            .context(UserError::new(user_msg)));
        }
        Ok(())
    }
}

/// Ensure the staging directory exists, creating it if necessary.
pub async fn ensure_staging_dir(path: &Path) -> Result<(), Error> {
    tokio::fs::create_dir_all(path)
        .await
        .with_context(|| format!("Failed to create staging directory: {}", path.display()))
}

/// Remove all contents of the staging directory without removing the directory
/// itself. Called on startup to reclaim temp trees leaked by previous
/// non-graceful pod terminations (SIGKILL, OOM, disk-pressure eviction).
pub async fn sweep_staging_dir(path: &Path) -> Result<u64, Error> {
    let mut entries = match tokio::fs::read_dir(path).await {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(0),
        Err(e) => {
            return Err(
                Error::from(e).context(format!("Failed to read staging dir: {}", path.display()))
            );
        }
    };

    let mut removed: u64 = 0;
    loop {
        let entry = match entries.next_entry().await {
            Ok(Some(e)) => e,
            Ok(None) => break,
            Err(e) => {
                warn!("Error iterating staging dir {}: {e}", path.display());
                continue;
            }
        };

        let entry_path = entry.path();
        let name = entry.file_name();
        if !name.to_string_lossy().starts_with("job-") {
            continue;
        }

        let is_dir = match entry.file_type().await {
            Ok(ft) => ft.is_dir(),
            Err(e) => {
                warn!("Cannot stat {}, skipping: {e}", entry_path.display());
                continue;
            }
        };

        let result = if is_dir {
            tokio::fs::remove_dir_all(&entry_path).await
        } else {
            tokio::fs::remove_file(&entry_path).await
        };

        match result {
            Ok(()) => removed += 1,
            Err(e) => {
                warn!(
                    "Failed to remove stale staging entry {}: {e}",
                    entry_path.display()
                );
            }
        }
    }

    if removed > 0 {
        info!(
            "Startup sweep: removed {removed} stale entries from {}",
            path.display()
        );
    }

    Ok(removed)
}

/// Compute total disk usage of the staging directory (recursive).
/// Returns 0 if the directory doesn't exist.
pub async fn staging_dir_bytes(path: &Path) -> u64 {
    match compute_dir_size(path).await {
        Ok(bytes) => bytes,
        Err(e) => {
            debug!("Failed to compute staging dir size: {e}");
            0
        }
    }
}

async fn compute_dir_size(path: &Path) -> Result<u64, std::io::Error> {
    let mut total: u64 = 0;
    let mut entries = tokio::fs::read_dir(path).await?;
    loop {
        let entry = match entries.next_entry().await {
            Ok(Some(e)) => e,
            Ok(None) => break,
            Err(_) => continue,
        };
        let is_dir = match entry.file_type().await {
            Ok(ft) => ft.is_dir(),
            Err(_) => continue,
        };
        if is_dir {
            total += Box::pin(compute_dir_size(&entry.path())).await.unwrap_or(0);
        } else {
            total += entry.metadata().await.map(|m| m.len()).unwrap_or(0);
        }
    }
    Ok(total)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[tokio::test]
    async fn test_sweep_removes_stale_entries() {
        let root = TempDir::new().unwrap();
        let staging = root.path().join("staging");
        ensure_staging_dir(&staging).await.unwrap();

        // Simulate leaked temp dirs from crashed pods (job- prefix)
        let leaked_dir = staging.join("job-ABCDEF");
        tokio::fs::create_dir(&leaked_dir).await.unwrap();
        tokio::fs::write(leaked_dir.join("key.raw"), b"raw data")
            .await
            .unwrap();
        tokio::fs::write(leaked_dir.join("key.data"), b"decompressed data")
            .await
            .unwrap();

        let leaked_dir2 = staging.join("job-GHIJKL");
        tokio::fs::create_dir(&leaked_dir2).await.unwrap();

        // Non-job entry should be left alone
        let other = staging.join("something-else");
        tokio::fs::create_dir(&other).await.unwrap();

        let removed = sweep_staging_dir(&staging).await.unwrap();
        assert_eq!(removed, 2);

        // Staging dir should still contain the non-job entry
        assert!(staging.exists());
        assert!(other.exists());
        let mut entries = tokio::fs::read_dir(&staging).await.unwrap();
        let remaining = entries.next_entry().await.unwrap().unwrap();
        assert_eq!(remaining.file_name(), "something-else");
        assert!(entries.next_entry().await.unwrap().is_none());
    }

    #[tokio::test]
    async fn test_sweep_nonexistent_dir_is_noop() {
        let root = TempDir::new().unwrap();
        let staging = root.path().join("does-not-exist");
        let removed = sweep_staging_dir(&staging).await.unwrap();
        assert_eq!(removed, 0);
    }

    #[tokio::test]
    async fn test_ensure_creates_nested_dirs() {
        let root = TempDir::new().unwrap();
        let staging = root.path().join("a").join("b").join("staging");
        ensure_staging_dir(&staging).await.unwrap();
        assert!(staging.exists());
    }

    #[tokio::test]
    async fn test_staging_dir_bytes_counts_files() {
        let root = TempDir::new().unwrap();
        let staging = root.path().join("staging");
        ensure_staging_dir(&staging).await.unwrap();

        let subdir = staging.join("job-tmpXYZ");
        tokio::fs::create_dir(&subdir).await.unwrap();
        tokio::fs::write(subdir.join("key.raw"), vec![0u8; 1024])
            .await
            .unwrap();
        tokio::fs::write(subdir.join("key.data"), vec![0u8; 2048])
            .await
            .unwrap();

        let bytes = staging_dir_bytes(&staging).await;
        assert_eq!(bytes, 3072);
    }

    #[tokio::test]
    async fn test_staging_dir_bytes_nonexistent() {
        let root = TempDir::new().unwrap();
        let staging = root.path().join("does-not-exist");
        let bytes = staging_dir_bytes(&staging).await;
        assert_eq!(bytes, 0);
    }

    #[tokio::test]
    async fn test_staging_guard_disabled_never_trips() {
        let root = TempDir::new().unwrap();
        ensure_staging_dir(root.path()).await.unwrap();
        tokio::fs::write(root.path().join("big"), vec![0u8; 10_000])
            .await
            .unwrap();

        // max_bytes == 0 disables the guard regardless of usage.
        let mut guard = StagingGuard::new(root.path().to_path_buf(), 0);
        guard.check().await.unwrap();
        guard.record(1_000_000_000).await.unwrap();
    }

    #[tokio::test]
    async fn test_staging_guard_check_trips_over_limit_with_user_message() {
        use crate::error::get_user_message;

        let root = TempDir::new().unwrap();
        ensure_staging_dir(root.path()).await.unwrap();
        tokio::fs::write(root.path().join("big"), vec![0u8; 4096])
            .await
            .unwrap();

        let guard = StagingGuard::new(root.path().to_path_buf(), 1024);
        let err = guard.check().await.unwrap_err();
        // Surfaces an actionable user-facing message (so the job pauses, not evicts).
        assert!(get_user_message(&err).contains("Staging disk limit exceeded"));

        // Under-limit passes.
        let ok_guard = StagingGuard::new(root.path().to_path_buf(), 1024 * 1024);
        ok_guard.check().await.unwrap();
    }

    #[tokio::test]
    async fn test_staging_guard_record_throttles_until_interval() {
        let root = TempDir::new().unwrap();
        ensure_staging_dir(root.path()).await.unwrap();
        tokio::fs::write(root.path().join("big"), vec![0u8; 4096])
            .await
            .unwrap();

        // Already over the limit, but record() only re-measures after the check
        // interval of newly-recorded bytes has accumulated.
        let mut guard = StagingGuard::new(root.path().to_path_buf(), 1024);
        guard.check_interval = 1_000_000;

        guard.record(500_000).await.unwrap(); // below interval -> no measurement
        let tripped = guard.record(600_000).await; // crosses interval -> measures
        assert!(tripped.is_err());
    }
}
