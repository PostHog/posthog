//! Per-file-type disk usage of the store directory and the local checkpoint directory. RocksDB
//! reports only SST sizes, so this walk is the only view of the WAL, info `LOG`, `MANIFEST`, and
//! checkpoint bytes on the store volume.

use std::fs::{self, DirEntry, Metadata};
use std::io;
use std::path::Path;

/// Bytes on disk per file type.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct StoreFileUsage {
    pub sst_bytes: u64,
    pub wal_bytes: u64,
    pub info_log_bytes: u64,
    pub manifest_bytes: u64,
    /// `OPTIONS`, `CURRENT`, `IDENTITY`, `LOCK`, and any file RocksDB adds later.
    pub other_bytes: u64,
    /// Checkpoint bytes that no other file shares: SSTs that the live store compacted away, and
    /// the files the checkpoint copies instead of hard-links. A hard-linked SST that the live
    /// store still holds is already in `sst_bytes`, so it is not counted again here.
    pub checkpoint_bytes: u64,
}

impl StoreFileUsage {
    /// `(kind label, bytes)` pairs for the `store_file_bytes` gauge.
    pub fn by_kind(&self) -> [(&'static str, u64); 6] {
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

/// Sum file sizes per type in `store_path` (flat, as RocksDB lays it out) and the unshared bytes
/// under `checkpoint_dir` (recursive). A missing checkpoint directory counts as 0 bytes.
pub fn sample_store_files(store_path: &Path, checkpoint_dir: &Path) -> io::Result<StoreFileUsage> {
    let mut usage = StoreFileUsage::default();
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
    }
    usage.checkpoint_bytes = unshared_bytes(checkpoint_dir)?;
    Ok(usage)
}

fn unshared_bytes(root: &Path) -> io::Result<u64> {
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
                if !is_hard_linked(&meta) {
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

#[cfg(unix)]
fn is_hard_linked(meta: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    meta.nlink() > 1
}

#[cfg(not(unix))]
fn is_hard_linked(_meta: &Metadata) -> bool {
    false
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

        let usage = sample_store_files(dir.path(), &dir.path().join("missing")).unwrap();

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

    #[cfg(unix)]
    #[test]
    fn checkpoint_counts_only_files_the_live_store_no_longer_shares() {
        let root = tempfile::tempdir().unwrap();
        let store = root.path().join("store");
        let attempt = root.path().join("ckpt").join("topic").join("0").join("a1");
        fs::create_dir_all(&store).unwrap();
        fs::create_dir_all(&attempt).unwrap();

        fs::write(store.join("000020.sst"), vec![0u8; 40]).unwrap();
        fs::hard_link(store.join("000020.sst"), attempt.join("000020.sst")).unwrap();
        // The live store compacted this SST away, so only the checkpoint holds it.
        fs::write(attempt.join("000010.sst"), vec![0u8; 30]).unwrap();
        fs::write(attempt.join("MANIFEST-000003"), vec![0u8; 5]).unwrap();

        let usage = sample_store_files(&store, &root.path().join("ckpt")).unwrap();

        assert_eq!(usage.sst_bytes, 40);
        assert_eq!(usage.checkpoint_bytes, 35);
    }
}
