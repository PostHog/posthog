use anyhow::Error;
use async_trait::async_trait;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::extractor::StreamingReader;

pub mod date_range_export;
pub mod folder;
pub mod s3;
pub mod s3_gzip;
pub mod url_list;

/// Per-key state for sources that download a compressed `.raw` file and
/// stream-decompress it on demand (see [`crate::extractor::StreamingReader`]).
///
/// Disk usage is bounded by the compressed file: there is no decompressed
/// `.data` copy. The decompressed size is discovered lazily — it is only known
/// once the reader reaches end-of-stream — so `total_size` stays `None` until
/// the job has read the whole key.
pub(crate) struct PreparedPart {
    /// The compressed file backing this key. `None` for empty keys (404 /
    /// zero-byte objects) and once the key has been streamed to EOF, when the
    /// file is deleted and this is cleared (see [`read_prepared_chunk`]).
    pub raw_file_path: Option<PathBuf>,
    /// Forward streaming reader over the compressed file. `None` for empty keys
    /// and once the key has been fully read (the reader is dropped at EOF).
    pub reader: Option<Arc<Mutex<StreamingReader>>>,
    /// Total decompressed size, known only after EOF. Always `Some(0)` for empty.
    pub total_size: Option<u64>,
}

impl PreparedPart {
    pub(crate) fn empty() -> Self {
        Self {
            raw_file_path: None,
            reader: None,
            total_size: Some(0),
        }
    }

    pub(crate) fn streaming(raw_file_path: PathBuf, reader: StreamingReader) -> Self {
        Self {
            raw_file_path: Some(raw_file_path),
            reader: Some(Arc::new(Mutex::new(reader))),
            total_size: None,
        }
    }
}

/// Read a forward range from a prepared, stream-decompressed key.
///
/// Reads are forward-only and monotonic, matching the job's chunker. On the read
/// that reaches end-of-stream, the discovered total size is recorded (so
/// [`DataSource::size`] can return it) and the compressed backing file is freed
/// immediately: the reader is dropped (stopping the producer thread) and the
/// `.raw` deleted, since a forward-only stream never re-reads it. The bookkeeping
/// entry is kept with `reader: None` so `size()` still reports the total and
/// `prepare_key` stays a no-op. Cleanup therefore happens on the EOF read itself
/// and never depends on a later terminal read or on how the caller drives reads.
pub(crate) async fn read_prepared_chunk(
    prepared_keys: &Mutex<HashMap<String, PreparedPart>>,
    key: &str,
    offset: u64,
    size: u64,
) -> Result<Vec<u8>, Error> {
    let reader = {
        let map = prepared_keys.lock().await;
        let part = map
            .get(key)
            .ok_or_else(|| Error::msg(format!("Key not prepared: {key}")))?;
        match &part.reader {
            // Empty key, or a key already streamed to EOF and freed: nothing left
            // to read. Idempotent — we leave the tiny reader-less entry in place
            // (dropped by cleanup_after_job) so behavior can't depend on the
            // caller's read pattern.
            None => return Ok(Vec::new()),
            Some(reader) => reader.clone(),
        }
    };

    let chunk = reader.lock().await.read_at(offset, size as usize).await?;

    let mut raw_to_delete = None;
    if let Some(total) = chunk.total {
        let mut map = prepared_keys.lock().await;
        if let Some(part) = map.get_mut(key) {
            part.total_size = Some(total);
            // EOF reached with the final bytes in hand. A forward-only stream
            // never reads this file again, so free it now instead of waiting for
            // a terminal offset>=total read; keep the reader-less entry so size()
            // still reports `total` and prepare_key stays a no-op.
            part.reader = None;
            raw_to_delete = part.raw_file_path.take();
        }
    }

    // Delete the compressed file outside the map lock.
    if let Some(raw) = raw_to_delete {
        if let Err(e) = tokio::fs::remove_file(&raw).await {
            tracing::warn!("Failed to remove raw file for key {key}: {e}");
        }
    }

    Ok(chunk.bytes)
}

/// Remove a prepared key, dropping its reader (which stops the producer thread)
/// and deleting the backing compressed file.
pub(crate) async fn remove_prepared_key(
    prepared_keys: &Mutex<HashMap<String, PreparedPart>>,
    key: &str,
) {
    let removed = { prepared_keys.lock().await.remove(key) };
    if let Some(part) = removed {
        if let Some(raw) = part.raw_file_path {
            if let Err(e) = tokio::fs::remove_file(&raw).await {
                tracing::warn!("Failed to remove raw file for key {key}: {e}");
            }
        }
    }
}

#[async_trait]
pub trait DataSource: Sync + Send {
    async fn keys(&self) -> Result<Vec<String>, Error>;
    async fn size(&self, key: &str) -> Result<Option<u64>, Error>;
    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error>;

    // life cycle methods that support preparing and cleaning up resources for job/keys
    // no op by default
    async fn prepare_key(&self, _key: &str) -> Result<(), Error> {
        Ok(())
    }

    async fn cleanup_key(&self, _key: &str) -> Result<(), Error> {
        Ok(())
    }

    async fn prepare_for_job(&self) -> Result<(), Error> {
        Ok(())
    }
    async fn cleanup_after_job(&self) -> Result<(), Error> {
        Ok(())
    }

    fn get_date_range_for_key(&self, _key: &str) -> Option<String> {
        None
    }
}
