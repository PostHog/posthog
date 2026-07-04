use std::collections::HashMap;
use std::future::Future;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Error;
use async_trait::async_trait;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};

use crate::extractor::{ExtractorType, StreamingReader};
use crate::staging::{open_plaintext_stream, PlaintextStream, StagingBackend};

pub mod date_range_export;
pub mod folder;
pub mod s3;
pub mod s3_gzip;
pub mod url_list;

/// Remote (temp-bucket) staging for a compressed source, selected by
/// `STAGING_BACKEND=temp_bucket`. Bundles the backend with how this source's parts
/// decompress, so a downloaded `.raw` can be ingested in one call.
///
/// When present, a source stages each part's decompressed plaintext in the backend and
/// serves `size`/`get_chunk`/`cleanup_key` from it, bypassing the local
/// [`PreparedPart`]/[`StreamingReader`] machinery. When absent (`local_disk`, the
/// default), the local streaming path below is used unchanged.
#[derive(Clone)]
pub struct RemoteStaging {
    pub backend: Arc<dyn StagingBackend>,
    pub extractor_type: ExtractorType,
    /// Per-part decompressed-byte ceiling forwarded to the pipeline (0 = disabled).
    pub max_plaintext_bytes: u64,
}

/// Read retries against the staging backend, mirroring the local prepared-chunk
/// retry behavior both compressed sources have always used.
const REMOTE_READ_RETRIES: usize = 3;

impl RemoteStaging {
    /// `DataSource::prepare_key` delegation for a compressed source: attach if the
    /// part is already staged (cached size, or `head` on a cold process — multipart
    /// atomicity guarantees no torn part is ever visible), otherwise run the source's
    /// download and ingest the result. Idempotent, matching the job loop's
    /// call-every-iteration contract.
    pub(crate) async fn prepare_key<F, Fut>(&self, key: &str, download: F) -> Result<(), Error>
    where
        F: FnOnce() -> Fut,
        Fut: Future<Output = Result<Option<(PathBuf, u64)>, Error>>,
    {
        // Guarantee a public-facing message on the staging legs of this path (attach
        // check + ingest) without shadowing more specific ones (ceiling breach, rate
        // limits). Download errors keep their own source-specific messages.
        let staging_user_msg = || {
            format!(
                "Preparing import data for part {key} failed. The job retries temporary \
                 storage errors automatically; if it stays paused, resume it to retry, \
                 and if it keeps failing the source file may be corrupt — re-export it \
                 or split it and run the remainder as a separate job."
            )
        };
        match self.backend.size(key).await {
            Ok(Some(_)) => {
                debug!("Key already staged remotely: {}", key);
                return Ok(());
            }
            Ok(None) => {}
            Err(e) => return Err(crate::error::ensure_user_message(e, staging_user_msg())),
        }
        let downloaded = download().await?;
        let size = self
            .stage_downloaded(key, downloaded.map(|(path, _)| path))
            .await
            .map_err(|e| crate::error::ensure_user_message(e, staging_user_msg()))?;
        info!(key, size, "Staged key remotely (decompressed bytes)");
        Ok(())
    }

    /// `DataSource::get_chunk` delegation: a ranged, side-effect-free read with the
    /// same small retry loop the sources use for local prepared-chunk reads (the
    /// backend's S3 client retries transient failures internally as well).
    pub(crate) async fn read_chunk(
        &self,
        key: &str,
        offset: u64,
        size: u64,
    ) -> Result<Vec<u8>, Error> {
        let mut retries = REMOTE_READ_RETRIES;
        loop {
            match self.backend.read(key, offset, size).await {
                Ok(chunk) => return Ok(chunk),
                Err(e) => {
                    if retries == 0 {
                        return Err(crate::error::ensure_user_message(
                            e,
                            format!(
                                "Reading staged import data for part {key} failed. The job \
                                 retries temporary storage errors automatically; if it stays \
                                 paused, resume it to continue from where it left off."
                            ),
                        ));
                    }
                    warn!(
                        key,
                        offset, "Error reading staged chunk: {e:?}, remaining retries: {retries}"
                    );
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    retries -= 1;
                }
            }
        }
    }

    /// `DataSource::cleanup_after_job` delegation: sweep this job's staged objects,
    /// best-effort (the bucket TTL is the final backstop).
    pub(crate) async fn sweep_job(&self) {
        if let Err(e) = self.backend.cleanup_job().await {
            warn!("Failed to clean up remote staging after job: {e:#}");
        }
    }

    /// Ingest a downloaded part into the backend and return its decompressed size.
    /// `raw_file_path: None` means an empty part (404 / zero-byte object): an empty
    /// object is staged so `size()` reports `Some(0)` and resume skips re-download.
    /// The `.raw` is deleted after a successful stage (its bytes now live remotely).
    pub(crate) async fn stage_downloaded(
        &self,
        key: &str,
        raw_file_path: Option<PathBuf>,
    ) -> Result<u64, Error> {
        match raw_file_path {
            None => {
                self.backend
                    .stage_part(
                        key,
                        PlaintextStream::from_chunks(Vec::<bytes::Bytes>::new()),
                    )
                    .await
            }
            Some(raw) => {
                let stream = open_plaintext_stream(
                    raw.clone(),
                    self.extractor_type.clone(),
                    self.max_plaintext_bytes,
                );
                let result = self.backend.stage_part(key, stream).await;
                // The `.raw` is single-use: on success its bytes now live remotely; on
                // failure the retry re-downloads from origin (the backend has no object,
                // so prepare_key won't attach). Remove it either way so a failed or paused
                // job doesn't hold staging disk or trip the staging guard on resume.
                if let Err(e) = tokio::fs::remove_file(&raw).await {
                    warn!("Failed to remove staged raw file {}: {e}", raw.display());
                }
                result
            }
        }
    }
}

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
