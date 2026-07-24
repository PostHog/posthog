//! Table opening helpers.

use std::collections::HashMap;
use std::sync::Arc;

use deltalake::{DeltaTable, DeltaTableBuilder};

use crate::errors::{Error, Result};
use crate::store::MultipartLogStore;

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
pub async fn open_table(uri: &str, storage_options: HashMap<String, String>) -> Result<DeltaTable> {
    let url = deltalake::ensure_table_uri(uri)
        .map_err(|e| Error::NotFound(format!("invalid table uri {uri}: {e}")))?;
    Ok(DeltaTableBuilder::from_url(url)?
        .with_storage_options(storage_options)
        .load()
        .await?)
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
    if multipart.threshold == 0 {
        return Ok(table);
    }
    let wrapped = Arc::new(MultipartLogStore::new(
        table.log_store(),
        multipart.threshold,
        multipart.part_size,
    ));
    let mut wrapped_table = DeltaTable::new(wrapped, Default::default());
    wrapped_table.load().await.map_err(Error::from)?;
    Ok(wrapped_table)
}
