//! Table opening helpers.

use std::collections::HashMap;
use std::sync::Arc;

use deltalake::{DeltaTable, DeltaTableBuilder};

use crate::errors::{Error, Result};
use crate::prefetch::{CheckpointCache, CheckpointPrefetchLogStore};
use crate::store::{CommitProbe, MultipartLogStore};

/// How data-file uploads are performed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MultipartConfig {
    /// Files at or above this size upload as multipart; 0 disables the rewrite.
    pub threshold: usize,
    /// Part size for multipart uploads (clamped to >= 5 MiB by the store wrapper).
    pub part_size: usize,
}

impl Default for MultipartConfig {
    fn default() -> Self {
        Self {
            threshold: crate::store::DEFAULT_MULTIPART_THRESHOLD,
            part_size: crate::store::DEFAULT_MULTIPART_PART_SIZE,
        }
    }
}

impl MultipartConfig {
    /// Resolve from explicit arguments, then `DELTALITE_MULTIPART_THRESHOLD_BYTES` /
    /// `DELTALITE_MULTIPART_PART_SIZE_BYTES`, then the defaults. An explicit
    /// `Some(0)` threshold disables multipart entirely.
    pub fn resolve(threshold: Option<usize>, part_size: Option<usize>) -> Self {
        let d = Self::default();
        Self {
            threshold: threshold.unwrap_or_else(|| {
                crate::limits::env_usize("DELTALITE_MULTIPART_THRESHOLD_BYTES", d.threshold)
            }),
            part_size: part_size.unwrap_or_else(|| {
                crate::limits::env_usize("DELTALITE_MULTIPART_PART_SIZE_BYTES", d.part_size)
            }),
        }
    }
}

/// Open and load a Delta table from `uri` with the given delta-rs `storage_options`
/// (the same keys the Python package accepts; the dict passes through unchanged).
///
/// The load reads its checkpoint through the prefetch wrapper (see [`crate::prefetch`])
/// and releases the prefetched bytes before returning, so the table costs no more memory
/// than a plain load once it is open.
pub async fn open_table(uri: &str, storage_options: HashMap<String, String>) -> Result<DeltaTable> {
    let (table, prefetch) = open_table_prefetched(uri, storage_options).await?;
    // Nothing clears the cache after later operations on this table, so it must not
    // collect the commit files that they read and write.
    prefetch.stop_caching_commits();
    prefetch.clear();
    Ok(table)
}

/// [`open_table`] that also hands back the checkpoint cache the table's stores serve
/// from, still holding the checkpoint bytes read by this load. The caller clears it once
/// it is done and can clear it again after each later load through the same table.
pub async fn open_table_prefetched(
    uri: &str,
    storage_options: HashMap<String, String>,
) -> Result<(DeltaTable, Arc<CheckpointCache>)> {
    let url = deltalake::ensure_table_uri(uri)
        .map_err(|e| Error::NotFound(format!("invalid table uri {uri}: {e}")))?;
    let built = DeltaTableBuilder::from_url(url)?
        .with_storage_options(storage_options)
        .build()?;
    let cache = Arc::new(CheckpointCache::from_env());
    let log_store = Arc::new(CheckpointPrefetchLogStore::new(
        built.log_store(),
        cache.clone(),
    ));
    let mut table = DeltaTable::new(log_store, built.config.clone());
    table.load().await?;
    Ok((table, cache))
}

/// Open a table whose data-file uploads go through the multipart-aware store wrapper
/// (see [`crate::store`]). Commit-entry writes keep the inner log store's conditional
/// -put path untouched.
pub async fn open_table_multipart(
    uri: &str,
    storage_options: HashMap<String, String>,
    multipart: MultipartConfig,
) -> Result<DeltaTable> {
    let table = open_table(uri, storage_options).await?;
    Ok(wrap_multipart(table, multipart))
}

/// Re-home an already-loaded table onto the multipart-aware store wrapper, without I/O.
/// The loaded snapshot moves across as-is: the wrapper changes how large data-file
/// `put`s are performed, never what the log contains, so replaying the log under the
/// wrapped store would rebuild an identical snapshot at a full log-replay's cost.
pub fn wrap_multipart(table: DeltaTable, multipart: MultipartConfig) -> DeltaTable {
    if multipart.threshold == 0 {
        return table;
    }
    let wrapped = Arc::new(MultipartLogStore::new(
        table.log_store(),
        multipart.threshold,
        multipart.part_size,
    ));
    let mut wrapped_table = DeltaTable::new(wrapped, Default::default());
    wrapped_table.state = table.state;
    wrapped_table
}

/// [`wrap_multipart`] for a handle's view of its table. `commit_probe` lets a commit
/// through the view skip the LIST before the commit put (see [`CommitProbe`]). Always
/// wraps; a zero threshold keeps every upload a single put.
pub(crate) fn wrap_multipart_view(
    table: DeltaTable,
    multipart: MultipartConfig,
    commit_probe: Option<CommitProbe>,
) -> DeltaTable {
    let threshold = if multipart.threshold == 0 {
        usize::MAX
    } else {
        multipart.threshold
    };
    let mut wrapped = MultipartLogStore::new(table.log_store(), threshold, multipart.part_size);
    if let Some(probe) = commit_probe {
        wrapped = wrapped.with_commit_probe(probe);
    }
    let mut wrapped_table = DeltaTable::new(Arc::new(wrapped), Default::default());
    wrapped_table.state = table.state;
    wrapped_table
}
