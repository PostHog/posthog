use std::collections::HashMap;
use std::path::PathBuf;

use anyhow::{Context, Error};
use async_trait::async_trait;
use bytes::Bytes;
use tokio::fs::File;
use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt};
use tokio::sync::{mpsc, Mutex};
use tracing::warn;
use uuid::Uuid;

/// A forward, on-demand stream of decompressed plaintext blocks for a single part.
///
/// Produced by the shared fetch+decompress pipeline (added in a later change) and
/// consumed by a [`StagingBackend`] in `stage_part`. Decoupling the producer from
/// the backend is what lets both the local-disk and temp-bucket backends persist the
/// exact same byte stream, so a part's byte offsets stay valid across backends.
pub struct PlaintextStream {
    rx: mpsc::Receiver<Result<Bytes, Error>>,
}

impl PlaintextStream {
    /// Wrap a receiver of decompressed blocks. The sender side is the pipeline's
    /// producer; each item is either a block of plaintext or a decode/IO error.
    pub fn new(rx: mpsc::Receiver<Result<Bytes, Error>>) -> Self {
        Self { rx }
    }

    /// Pull the next block, or `None` once the producer has finished (EOF).
    pub async fn next(&mut self) -> Option<Result<Bytes, Error>> {
        self.rx.recv().await
    }

    /// Build a stream from in-memory blocks, feeding them through a bounded channel
    /// on a background task. Mirrors the real producer shape; handy for tests and for
    /// callers that already hold the full plaintext.
    pub fn from_chunks<I>(chunks: I) -> Self
    where
        I: IntoIterator<Item = Bytes> + Send + 'static,
        I::IntoIter: Send,
    {
        let (tx, rx) = mpsc::channel(16);
        tokio::spawn(async move {
            for chunk in chunks {
                if tx.send(Ok(chunk)).await.is_err() {
                    break;
                }
            }
        });
        Self { rx }
    }
}

/// Where a compressed source's decompressed part plaintext is staged so the job loop
/// can read it back by byte offset.
///
/// The two compressed sources (`date_range_export`, `s3_gzip`) delegate their
/// `prepare_key`/`size`/`get_chunk`/`cleanup_key` here. Implementations must satisfy the
/// job-loop contract: `read` is idempotent and side-effect-free (reads past EOF return
/// short/empty rather than erroring), and staging a key is atomic — a partially staged
/// key must not be observable via `size`/`read`.
#[async_trait]
pub trait StagingBackend: Send + Sync {
    /// Prepare any per-job resources (e.g. create the staging directory). No-op by default.
    async fn prepare_job(&self) -> Result<(), Error> {
        Ok(())
    }

    /// Reclaim all staging for the job. Best-effort: failures are logged, not fatal.
    async fn cleanup_job(&self) -> Result<(), Error> {
        Ok(())
    }

    /// Consume the decompressed plaintext for `key` and persist it, returning the total
    /// byte size. Must be atomic: on error, no readable staging is left behind.
    async fn stage_part(&self, key: &str, plaintext: PlaintextStream) -> Result<u64, Error>;

    /// Total staged size in bytes, or `None` if the key is not staged.
    async fn size(&self, key: &str) -> Result<Option<u64>, Error>;

    /// Read up to `size` bytes starting at `offset`. Reads at/after EOF return empty;
    /// reads that overrun EOF return the available prefix. Never mutates staging.
    async fn read(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error>;

    /// Delete the staging for a single key. Must no-op (not error) if already absent.
    async fn cleanup_key(&self, key: &str) -> Result<(), Error>;
}

/// Make a key safe to use as a filename / object suffix. Matches the existing sources'
/// `:`-replacement and additionally neutralizes path separators so nested S3 keys stay
/// a single flat name.
///
/// Invariant: callers stage one source per job, so all keys within a job share a single
/// style (date-range keys or S3 paths) and stay distinct after sanitization. This does not
/// guarantee global injectivity — `a:b` and `a/b` both map to `a_b` — so do not mix key
/// styles under one backend instance.
pub(crate) fn sanitize_key(key: &str) -> String {
    key.replace([':', '/'], "_")
}

/// Write a plaintext stream to `path`, fsync, and return the byte count. Used by
/// `LocalDiskBackend::stage_part` against a temp path so the caller can rename atomically.
async fn stage_to_file(
    path: &std::path::Path,
    plaintext: &mut PlaintextStream,
    key: &str,
) -> Result<u64, Error> {
    let mut file = File::create(path)
        .await
        .with_context(|| format!("Failed to create data file for key: {key}"))?;

    let mut total: u64 = 0;
    while let Some(block) = plaintext.next().await {
        let block = block.with_context(|| format!("Failed to decompress part for key: {key}"))?;
        file.write_all(&block)
            .await
            .with_context(|| format!("Failed to write staged data for key: {key}"))?;
        total += block.len() as u64;
    }

    file.sync_all()
        .await
        .with_context(|| format!("Failed to sync staged data for key: {key}"))?;
    Ok(total)
}

/// Stages part plaintext as a `.data` file under a per-job directory, reading it back with
/// seek + `read_exact`. Behaviorally identical to the current on-disk staging path; it is
/// the byte-identity reference the temp-bucket backend is validated against.
pub struct LocalDiskBackend {
    job_dir: PathBuf,
    // Sizes recorded at stage time, mirroring the sources' in-memory prepared-key map.
    // Reads fall back to stat-ing the file so a resumed process can attach without a
    // prior `stage_part`.
    sizes: Mutex<HashMap<String, u64>>,
}

impl LocalDiskBackend {
    /// `job_dir` is the per-job staging directory (e.g. `{staging_dir}/job-{id}`).
    pub fn new(job_dir: PathBuf) -> Self {
        Self {
            job_dir,
            sizes: Mutex::new(HashMap::new()),
        }
    }

    fn data_path(&self, key: &str) -> PathBuf {
        self.job_dir.join(format!("{}.data", sanitize_key(key)))
    }
}

#[async_trait]
impl StagingBackend for LocalDiskBackend {
    async fn prepare_job(&self) -> Result<(), Error> {
        tokio::fs::create_dir_all(&self.job_dir)
            .await
            .with_context(|| format!("Failed to create staging dir: {}", self.job_dir.display()))
    }

    async fn cleanup_job(&self) -> Result<(), Error> {
        if let Err(e) = tokio::fs::remove_dir_all(&self.job_dir).await {
            if e.kind() != std::io::ErrorKind::NotFound {
                warn!(
                    "Failed to remove staging dir {}: {e}",
                    self.job_dir.display()
                );
            }
        }
        self.sizes.lock().await.clear();
        Ok(())
    }

    async fn stage_part(&self, key: &str, mut plaintext: PlaintextStream) -> Result<u64, Error> {
        tokio::fs::create_dir_all(&self.job_dir)
            .await
            .with_context(|| format!("Failed to create staging dir: {}", self.job_dir.display()))?;

        // Stage to a unique temp file, then atomically rename to the key path only after a
        // successful sync. A failure mid-write leaves the partial at the temp path, never at
        // the observable key path, so `size`/`read` can't see a truncated part.
        let final_path = self.data_path(key);
        let tmp_path =
            self.job_dir
                .join(format!("{}.{}.partial", sanitize_key(key), Uuid::now_v7()));

        let total = match stage_to_file(&tmp_path, &mut plaintext, key).await {
            Ok(total) => total,
            Err(e) => {
                if let Err(cleanup_err) = tokio::fs::remove_file(&tmp_path).await {
                    if cleanup_err.kind() != std::io::ErrorKind::NotFound {
                        warn!(
                            "Failed to remove partial staged file {}: {cleanup_err}",
                            tmp_path.display()
                        );
                    }
                }
                return Err(e);
            }
        };

        tokio::fs::rename(&tmp_path, &final_path)
            .await
            .with_context(|| format!("Failed to publish staged data for key: {key}"))?;

        self.sizes.lock().await.insert(key.to_string(), total);
        Ok(total)
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        if let Some(size) = self.sizes.lock().await.get(key).copied() {
            return Ok(Some(size));
        }
        match tokio::fs::metadata(self.data_path(key)).await {
            Ok(meta) => Ok(Some(meta.len())),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => {
                Err(Error::from(e)
                    .context(format!("Failed to stat staged data file for key: {key}")))
            }
        }
    }

    async fn read(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        let total_size = match self.size(key).await? {
            Some(s) => s,
            None => return Err(Error::msg(format!("Key not staged: {key}"))),
        };

        if total_size == 0 || offset >= total_size {
            return Ok(Vec::new());
        }

        let end_offset = std::cmp::min(offset + size, total_size);
        let read_size = (end_offset - offset) as usize;

        let mut file = File::open(self.data_path(key))
            .await
            .with_context(|| format!("Failed to open staged data file for key: {key}"))?;
        file.seek(std::io::SeekFrom::Start(offset))
            .await
            .with_context(|| format!("Failed to seek to offset {offset} for key: {key}"))?;
        let mut buffer = vec![0u8; read_size];
        file.read_exact(&mut buffer)
            .await
            .with_context(|| format!("Failed to read {read_size} bytes for key: {key}"))?;
        Ok(buffer)
    }

    async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
        if let Err(e) = tokio::fs::remove_file(self.data_path(key)).await {
            if e.kind() != std::io::ErrorKind::NotFound {
                return Err(Error::from(e)
                    .context(format!("Failed to remove staged data file for key: {key}")));
            }
        }
        self.sizes.lock().await.remove(key);
        Ok(())
    }
}

/// Convenience for callers that hold a full plaintext buffer (tests, and any future
/// non-streaming producer): stage it and return the recorded size.
#[cfg(test)]
pub(crate) async fn stage_bytes(
    backend: &dyn StagingBackend,
    key: &str,
    data: &[u8],
) -> Result<u64, Error> {
    let stream = PlaintextStream::from_chunks(vec![Bytes::copy_from_slice(data)]);
    backend.stage_part(key, stream).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;
    use tempfile::TempDir;

    fn backend(root: &Path) -> LocalDiskBackend {
        LocalDiskBackend::new(root.join("job-TEST"))
    }

    #[tokio::test]
    async fn stage_then_read_slices_match() {
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        let body = b"line one\nline two\nline three\n";
        let size = stage_bytes(&be, "2024-01-01", body).await.unwrap();
        assert_eq!(size, body.len() as u64);
        assert_eq!(
            be.size("2024-01-01").await.unwrap(),
            Some(body.len() as u64)
        );

        // Full read.
        assert_eq!(be.read("2024-01-01", 0, 1000).await.unwrap(), body);
        // Mid-slice.
        assert_eq!(be.read("2024-01-01", 9, 8).await.unwrap(), b"line two");
        // Overrun EOF returns the available prefix.
        let tail = be.read("2024-01-01", 18, 1000).await.unwrap();
        assert_eq!(tail, b"line three\n");
        // Read at EOF is empty, not an error.
        assert!(be
            .read("2024-01-01", body.len() as u64, 10)
            .await
            .unwrap()
            .is_empty());
    }

    #[tokio::test]
    async fn multi_chunk_stream_is_concatenated_in_order() {
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        let stream = PlaintextStream::from_chunks(vec![
            Bytes::from_static(b"aaa"),
            Bytes::from_static(b"bbb"),
            Bytes::from_static(b"ccc"),
        ]);
        let size = be.stage_part("k", stream).await.unwrap();
        assert_eq!(size, 9);
        assert_eq!(be.read("k", 0, 9).await.unwrap(), b"aaabbbccc");
    }

    #[tokio::test]
    async fn empty_part_reports_zero_and_reads_empty() {
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        let size = stage_bytes(&be, "empty", b"").await.unwrap();
        assert_eq!(size, 0);
        assert_eq!(be.size("empty").await.unwrap(), Some(0));
        assert!(be.read("empty", 0, 100).await.unwrap().is_empty());
    }

    #[tokio::test]
    async fn size_none_and_read_errors_for_unstaged_key() {
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        assert_eq!(be.size("missing").await.unwrap(), None);
        assert!(be.read("missing", 0, 10).await.is_err());
    }

    #[tokio::test]
    async fn size_attaches_to_existing_file_without_stage_part() {
        // Simulates a resumed process: the .data file exists on disk but the in-memory
        // size map is empty. size()/read() must recover from the file.
        let root = TempDir::new().unwrap();
        let job_dir = root.path().join("job-TEST");
        tokio::fs::create_dir_all(&job_dir).await.unwrap();
        let body = b"resumed body\n";
        tokio::fs::write(job_dir.join(format!("{}.data", sanitize_key("k1"))), body)
            .await
            .unwrap();

        let be = LocalDiskBackend::new(job_dir);
        assert_eq!(be.size("k1").await.unwrap(), Some(body.len() as u64));
        assert_eq!(be.read("k1", 0, 1000).await.unwrap(), body);
    }

    #[tokio::test]
    async fn failed_stage_leaves_no_observable_key() {
        // A mid-stream error must not publish a partial file: size() stays None and no
        // .data appears at the key path (only, transiently, a .partial temp that is removed).
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        let (tx, rx) = mpsc::channel(4);
        tx.send(Ok(Bytes::from_static(b"partial data")))
            .await
            .unwrap();
        tx.send(Err(anyhow::anyhow!("decode blew up")))
            .await
            .unwrap();
        drop(tx);

        let result = be.stage_part("k", PlaintextStream::new(rx)).await;
        assert!(result.is_err());
        assert_eq!(be.size("k").await.unwrap(), None);
        assert!(be.read("k", 0, 10).await.is_err());

        // No leftover files under the job dir (partial temp cleaned up, no key file).
        let mut entries = tokio::fs::read_dir(root.path().join("job-TEST"))
            .await
            .unwrap();
        assert!(entries.next_entry().await.unwrap().is_none());
    }

    #[tokio::test]
    async fn restage_overwrites_atomically() {
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        stage_bytes(&be, "k", b"first version").await.unwrap();
        let size = stage_bytes(&be, "k", b"second").await.unwrap();
        assert_eq!(size, 6);
        assert_eq!(be.read("k", 0, 100).await.unwrap(), b"second");
    }

    #[tokio::test]
    async fn cleanup_key_is_idempotent() {
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        stage_bytes(&be, "k", b"data").await.unwrap();
        be.cleanup_key("k").await.unwrap();
        assert_eq!(be.size("k").await.unwrap(), None);
        // Second delete of an absent key is a no-op, not an error.
        be.cleanup_key("k").await.unwrap();
    }

    #[tokio::test]
    async fn cleanup_job_removes_all_staging() {
        let root = TempDir::new().unwrap();
        let be = backend(root.path());
        stage_bytes(&be, "a", b"aaa").await.unwrap();
        stage_bytes(&be, "b", b"bbb").await.unwrap();
        be.cleanup_job().await.unwrap();
        assert_eq!(be.size("a").await.unwrap(), None);
        assert_eq!(be.size("b").await.unwrap(), None);
        // Idempotent: cleaning an already-removed job dir is fine.
        be.cleanup_job().await.unwrap();
    }

    #[tokio::test]
    async fn sanitize_key_neutralizes_separators() {
        assert_eq!(sanitize_key("2024-01-01:00"), "2024-01-01_00");
        assert_eq!(sanitize_key("path/to/key"), "path_to_key");
        assert_eq!(sanitize_key("a:b/c"), "a_b_c");
    }
}
