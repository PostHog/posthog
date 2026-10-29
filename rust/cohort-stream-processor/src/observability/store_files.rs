//! Per-file-type disk usage of the store directory and the local checkpoint directory. RocksDB
//! reports only SST sizes, so this walk is the only view of the WAL, info `LOG`, `MANIFEST`, and
//! checkpoint bytes on the store volume.

use std::collections::HashSet;
use std::fs::{self, DirEntry, Metadata};
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use metrics::gauge;
use tracing::{error, warn};

use crate::observability::metrics::STORE_FILE_BYTES;
use crate::sweep::Sweeper;

/// Publishes the `store_file_bytes` gauge each tick. It has its own sweep loop, apart from
/// [`DiskProbe`](crate::observability::store_stats::DiskProbe), so a slow walk cannot skip a
/// sample of the seed disk gate. The loop awaits each walk, so two walks never overlap.
pub struct StoreFilesSweeper {
    store_path: PathBuf,
    /// Set only when checkpoints are on, because only then does startup check that the directory
    /// is outside the store and on the store's filesystem.
    checkpoint_dir: Option<PathBuf>,
}

impl StoreFilesSweeper {
    pub fn new(store_path: PathBuf, checkpoint_dir: Option<PathBuf>) -> Self {
        Self {
            store_path,
            checkpoint_dir,
        }
    }
}

#[async_trait]
impl Sweeper for StoreFilesSweeper {
    async fn run_once(&self) {
        let store_path = self.store_path.clone();
        let checkpoint_dir = self.checkpoint_dir.clone();
        let sample = tokio::task::spawn_blocking(move || {
            sample_store_files(&store_path, checkpoint_dir.as_deref())
        })
        .await;
        match sample {
            Ok(Ok(usage)) => {
                for (kind, bytes) in usage.by_kind() {
                    gauge!(STORE_FILE_BYTES, "kind" => kind).set(bytes as f64);
                }
            }
            Ok(Err(err)) => {
                warn!(error = %err, path = %self.store_path.display(), "store file usage sample failed");
            }
            Err(err) => error!(error = %err, "store file usage sample panicked"),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct StoreFileUsage {
    sst_bytes: u64,
    wal_bytes: u64,
    info_log_bytes: u64,
    manifest_bytes: u64,
    other_bytes: u64,
    /// Checkpoint bytes that the store directory does not share: SSTs that the live store
    /// compacted away, and the files the checkpoint copies instead of hard-links. Each file counts
    /// once, however many checkpoint attempts hard-link it.
    checkpoint_bytes: u64,
}

impl StoreFileUsage {
    fn by_kind(&self) -> [(&'static str, u64); 6] {
        [
            ("sst", self.sst_bytes),
            ("wal", self.wal_bytes),
            ("info_log", self.info_log_bytes),
            ("manifest", self.manifest_bytes),
            ("other", self.other_bytes),
            ("checkpoint", self.checkpoint_bytes),
        ]
    }
}

fn sample_store_files(
    store_path: &Path,
    checkpoint_dir: Option<&Path>,
) -> io::Result<StoreFileUsage> {
    let mut usage = StoreFileUsage::default();
    // Inode numbers do not collide between the two trees, because startup checks that the
    // checkpoint directory is on the store's filesystem.
    let mut counted = HashSet::new();
    for entry in fs::read_dir(store_path)? {
        let entry = entry?;
        let Some(meta) = file_metadata(&entry)? else {
            continue;
        };
        let name = entry.file_name();
        let name = name.to_string_lossy();
        let bucket = if name.ends_with(".sst") {
            &mut usage.sst_bytes
        } else if name.ends_with(".log") {
            // RocksDB names WAL files `<number>.log`; the info log is `LOG`, with no extension.
            &mut usage.wal_bytes
        } else if name == "LOG" || name.starts_with("LOG.old") {
            &mut usage.info_log_bytes
        } else if name.starts_with("MANIFEST-") {
            &mut usage.manifest_bytes
        } else {
            &mut usage.other_bytes
        };
        *bucket += meta.len();
        counted.insert(meta.ino());
    }
    if let Some(dir) = checkpoint_dir {
        usage.checkpoint_bytes = unshared_bytes(dir, &mut counted)?;
    }
    Ok(usage)
}

fn unshared_bytes(root: &Path, counted: &mut HashSet<u64>) -> io::Result<u64> {
    let mut total = 0;
    let mut pending = vec![root.to_path_buf()];
    while let Some(dir) = pending.pop() {
        let entries = match fs::read_dir(&dir) {
            Ok(entries) => entries,
            // The checkpoint sweeper prunes old attempt directories while this walk runs.
            Err(err) if err.kind() == io::ErrorKind::NotFound => continue,
            Err(err) => return Err(err),
        };
        for entry in entries {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                pending.push(entry.path());
                continue;
            }
            if let Some(meta) = file_metadata(&entry)? {
                if counted.insert(meta.ino()) {
                    total += meta.len();
                }
            }
        }
    }
    Ok(total)
}

/// `None` for a non-file entry or a file that compaction or pruning deleted after the listing.
fn file_metadata(entry: &DirEntry) -> io::Result<Option<Metadata>> {
    match entry.metadata() {
        Ok(meta) if meta.is_file() => Ok(Some(meta)),
        Ok(_) => Ok(None),
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(err),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_store_files_by_rocksdb_name() {
        let dir = tempfile::tempdir().unwrap();
        for (name, len) in [
            ("000012.sst", 100),
            ("000013.sst", 50),
            ("000014.log", 7),
            ("LOG", 3),
            ("LOG.old.1700000000000000", 4),
            ("MANIFEST-000005", 9),
            ("OPTIONS-000007", 2),
            ("CURRENT", 1),
        ] {
            fs::write(dir.path().join(name), vec![0u8; len]).unwrap();
        }

        let usage = sample_store_files(dir.path(), None).unwrap();

        assert_eq!(
            usage,
            StoreFileUsage {
                sst_bytes: 150,
                wal_bytes: 7,
                info_log_bytes: 7,
                manifest_bytes: 9,
                other_bytes: 3,
                checkpoint_bytes: 0,
            },
        );
    }

    #[test]
    fn checkpoint_counts_only_files_the_live_store_no_longer_shares() {
        let root = tempfile::tempdir().unwrap();
        let store = root.path().join("store");
        let lineage = root.path().join("ckpt").join("topic").join("0");
        let (older, newer) = (lineage.join("a1"), lineage.join("a2"));
        fs::create_dir_all(&store).unwrap();
        fs::create_dir_all(&older).unwrap();
        fs::create_dir_all(&newer).unwrap();

        fs::write(store.join("000020.sst"), vec![0u8; 40]).unwrap();
        fs::hard_link(store.join("000020.sst"), newer.join("000020.sst")).unwrap();
        // The live store compacted this SST away, so only the two checkpoint attempts hold it.
        fs::write(older.join("000010.sst"), vec![0u8; 30]).unwrap();
        fs::hard_link(older.join("000010.sst"), newer.join("000010.sst")).unwrap();
        fs::write(newer.join("MANIFEST-000003"), vec![0u8; 5]).unwrap();

        let usage = sample_store_files(&store, Some(&root.path().join("ckpt"))).unwrap();

        assert_eq!(usage.sst_bytes, 40);
        assert_eq!(usage.checkpoint_bytes, 35);
    }
}
