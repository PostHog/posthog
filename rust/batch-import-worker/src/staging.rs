use std::path::Path;

use anyhow::{Context, Error};
use tracing::{debug, info, warn};

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
}
