use std::collections::HashMap;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context, Error};
use async_compression::tokio::bufread::GzipDecoder;
use async_trait::async_trait;
use aws_sdk_s3::Client as S3Client;
use tempfile::TempDir;
use tokio::sync::Mutex;
use tokio::{
    fs::File,
    io::{AsyncReadExt, AsyncWriteExt, BufReader},
};
use tracing::{debug, info, warn};

use crate::error::ToUserError;

use super::s3::extract_user_friendly_error;
use super::DataSource;

fn sanitize_key_for_path(key: &str) -> String {
    key.replace(['/', ':'], "_")
}

fn is_gzip_key(key: &str) -> bool {
    key.ends_with(".gz")
}

type Decoder = GzipDecoder<BufReader<File>>;

/// A gzip decoder positioned at `pos` decompressed (logical) bytes for one object. Sequential
/// reads continue from here; a non-sequential offset rebuilds the reader and skips forward.
///
/// "Logical" bytes are the decompressed bytes plus a single synthetic trailing newline emitted
/// at end-of-stream when the content does not already end with one — matching the materialized
/// extractor, so the JSON-lines parser always sees a terminated final line and offsets line up
/// across the two implementations.
struct ForwardReader {
    pos: u64,
    decoder: Decoder,
    last_byte: Option<u8>,
    trailer_pending: bool,
    finished: bool,
}

impl ForwardReader {
    async fn open(raw_path: &Path) -> Result<Self, Error> {
        let file = File::open(raw_path)
            .await
            .with_context(|| format!("Failed to open staged file: {}", raw_path.display()))?;
        Ok(Self {
            pos: 0,
            decoder: GzipDecoder::new(BufReader::new(file)),
            last_byte: None,
            trailer_pending: false,
            finished: false,
        })
    }

    /// Fill `buf` with up to `buf.len()` logical bytes, returning the count. A return value
    /// shorter than `buf` means end-of-stream was reached.
    async fn read_logical(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let mut filled = 0;
        while filled < buf.len() {
            if self.finished {
                break;
            }
            if self.trailer_pending {
                buf[filled] = b'\n';
                filled += 1;
                self.trailer_pending = false;
                self.finished = true;
                break;
            }
            let n = self.decoder.read(&mut buf[filled..]).await?;
            if n == 0 {
                // Decoder EOF. Owe a synthetic newline iff the content didn't end with one.
                match self.last_byte {
                    Some(b) if b != b'\n' => self.trailer_pending = true,
                    _ => self.finished = true,
                }
                continue;
            }
            self.last_byte = Some(buf[filled + n - 1]);
            filled += n;
        }
        Ok(filled)
    }

    /// Discard `count` logical bytes from the current position (used to seek to a resume offset).
    async fn skip(&mut self, count: u64) -> io::Result<()> {
        let mut scratch = vec![0u8; 64 * 1024];
        let mut remaining = count;
        while remaining > 0 {
            let want = std::cmp::min(remaining as usize, scratch.len());
            let n = self.read_logical(&mut scratch[..want]).await?;
            if n == 0 {
                break; // offset is past end-of-stream; leave reader finished
            }
            remaining -= n as u64;
            self.pos += n as u64;
        }
        Ok(())
    }
}

/// Per-prepared-key streaming state. The compressed object is staged to disk (bounded, far
/// below the decompressed size that would exhaust ephemeral storage) and decoded on demand, so
/// the full decompressed object is never materialized.
struct PreparedStream {
    // `None` for an empty source object — nothing to decode.
    raw_path: Option<PathBuf>,
    reader: Mutex<Option<ForwardReader>>,
}

pub struct GzipS3Source {
    client: S3Client,
    bucket: String,
    prefix: String,
    staging_dir: PathBuf,
    temp_dir: Arc<Mutex<Option<TempDir>>>,
    prepared: Arc<Mutex<HashMap<String, Arc<PreparedStream>>>>,
}

impl GzipS3Source {
    pub fn new(client: S3Client, bucket: String, prefix: String, staging_dir: PathBuf) -> Self {
        Self {
            client,
            bucket,
            prefix,
            staging_dir,
            temp_dir: Arc::new(Mutex::new(None)),
            prepared: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    async fn get_temp_dir_path(&self) -> Result<PathBuf, Error> {
        let guard = self.temp_dir.lock().await;
        Ok(guard
            .as_ref()
            .ok_or_else(|| Error::msg("Temp directory not initialized"))?
            .path()
            .to_path_buf())
    }

    async fn prepared_stream(&self, key: &str) -> Result<Arc<PreparedStream>, Error> {
        let prepared = self.prepared.lock().await;
        prepared
            .get(key)
            .cloned()
            .ok_or_else(|| Error::msg(format!("Key not prepared: {key}")))
    }
}

#[async_trait]
impl DataSource for GzipS3Source {
    async fn keys(&self) -> Result<Vec<String>, Error> {
        debug!(
            "Listing keys in bucket {} with prefix {}",
            self.bucket, self.prefix
        );
        let mut keys = Vec::new();
        let mut continuation_token = None;
        loop {
            let mut cmd = self
                .client
                .list_objects_v2()
                .bucket(&self.bucket)
                .prefix(self.prefix.clone());
            if let Some(token) = continuation_token {
                cmd = cmd.continuation_token(token);
            }
            let output = cmd.send().await.or_else(|sdk_error| {
                let friendly_msg =
                    extract_user_friendly_error(&sdk_error, &self.bucket, "list objects");
                Err(sdk_error).user_error(friendly_msg)
            })?;

            debug!("Got response: {:?}", output);
            if let Some(contents) = output.contents {
                keys.extend(
                    contents
                        .iter()
                        .filter_map(|o| o.key.clone())
                        .filter(|k| is_gzip_key(k)),
                );
            }
            match output.next_continuation_token {
                Some(token) => continuation_token = Some(token),
                None => break,
            }
        }
        Ok(keys)
    }

    // The decompressed size is not known without reading the whole object, so it is reported as
    // unknown. The job loop detects end-of-part from the empty read `get_chunk` returns at EOF.
    async fn size(&self, _key: &str) -> Result<Option<u64>, Error> {
        Ok(None)
    }

    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        let stream = self.prepared_stream(key).await?;

        let Some(raw_path) = stream.raw_path.clone() else {
            return Ok(Vec::new()); // empty source object
        };

        let (data, at_eof) = {
            let mut guard = stream.reader.lock().await;

            // Ensure a decoder positioned exactly at `offset`: reuse it on the sequential fast
            // path, otherwise (first read or resume) rebuild it and skip forward.
            let needs_reopen = guard.as_ref().map(|r| r.pos != offset).unwrap_or(true);
            if needs_reopen {
                let mut reader = ForwardReader::open(&raw_path).await?;
                reader.skip(offset).await.with_context(|| {
                    format!("Failed to seek to offset {offset} in staged data for key: {key}")
                })?;
                reader.pos = offset;
                *guard = Some(reader);
            }
            let reader = guard.as_mut().expect("reader set above");

            let mut buf = vec![0u8; size as usize];
            let n = reader
                .read_logical(&mut buf)
                .await
                .with_context(|| format!("Failed to read decompressed data for key: {key}"))?;
            buf.truncate(n);
            reader.pos += n as u64;

            // A short read means this object is fully consumed. Drop the decoder before the
            // staged file is removed below.
            let at_eof = n == 0;
            if at_eof {
                *guard = None;
            }
            (buf, at_eof)
        };

        if at_eof {
            // Remove the staged compressed file as soon as a part is done, so at most one object
            // is ever on disk at a time.
            if let Err(e) = self.cleanup_key(key).await {
                warn!("Failed to cleanup key {key} after EOF: {e:?}");
            }
        }

        Ok(data)
    }

    async fn prepare_for_job(&self) -> Result<(), Error> {
        let temp_dir = tempfile::Builder::new()
            .prefix("job-")
            .tempdir_in(&self.staging_dir)
            .with_context(|| {
                format!(
                    "Failed to create temp directory in staging dir: {}",
                    self.staging_dir.display()
                )
            })?;
        debug!("Created temp directory for job: {:?}", temp_dir.path());

        let mut temp_dir_guard = self.temp_dir.lock().await;
        *temp_dir_guard = Some(temp_dir);

        Ok(())
    }

    async fn cleanup_after_job(&self) -> Result<(), Error> {
        {
            let mut prepared = self.prepared.lock().await;
            prepared.clear();
        }
        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            if let Some(temp_dir) = temp_dir_guard.take() {
                let path = temp_dir.path().to_path_buf();
                if let Err(e) = temp_dir.close() {
                    warn!("Failed to remove temp directory {}: {e}", path.display());
                } else {
                    debug!("Cleaned up temp directory: {}", path.display());
                }
            }
        }
        debug!("Job cleanup complete");
        Ok(())
    }

    async fn prepare_key(&self, key: &str) -> Result<(), Error> {
        {
            let prepared = self.prepared.lock().await;
            if prepared.contains_key(key) {
                debug!("Key already prepared: {}", key);
                return Ok(());
            }
        }

        let get = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .or_else(|sdk_error| {
                let friendly_msg =
                    extract_user_friendly_error(&sdk_error, &self.bucket, "get object");
                Err(sdk_error).user_error(friendly_msg)
            })?;

        let temp_dir = self.get_temp_dir_path().await?;
        let safe_key = sanitize_key_for_path(key);
        let raw_file_path = temp_dir.join(format!("{}.raw", safe_key));

        let mut raw_file = File::create(&raw_file_path)
            .await
            .with_context(|| format!("Failed to create raw file: {}", raw_file_path.display()))?;

        let mut stream = get.body;
        let mut total_bytes: u64 = 0;
        while let Some(chunk) = stream.try_next().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object s3://{0}/{key}",
                self.bucket,
            )
        })? {
            raw_file.write_all(&chunk).await.with_context(|| {
                format!("Failed to write raw file: {}", raw_file_path.display())
            })?;
            total_bytes += chunk.len() as u64;
        }
        raw_file
            .sync_all()
            .await
            .with_context(|| format!("Failed to sync raw file: {}", raw_file_path.display()))?;
        drop(raw_file);

        let prepared_stream = if total_bytes == 0 {
            if let Err(e) = tokio::fs::remove_file(&raw_file_path).await {
                warn!(
                    "Failed to remove empty raw file {}: {e}",
                    raw_file_path.display()
                );
            }
            info!("Prepared key {} (empty object)", key);
            PreparedStream {
                raw_path: None,
                reader: Mutex::new(None),
            }
        } else {
            info!(
                "Prepared key {} ({} compressed bytes staged)",
                key, total_bytes
            );
            PreparedStream {
                raw_path: Some(raw_file_path),
                reader: Mutex::new(None),
            }
        };

        let mut prepared = self.prepared.lock().await;
        prepared.insert(key.to_string(), Arc::new(prepared_stream));
        Ok(())
    }

    async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
        let stream = {
            let mut prepared = self.prepared.lock().await;
            prepared.remove(key)
        };

        if let Some(stream) = stream {
            // Drop any open decoder (closing the file handle) before removing the staged file.
            stream.reader.lock().await.take();
            if let Some(raw_path) = &stream.raw_path {
                if let Err(e) = tokio::fs::remove_file(raw_path).await {
                    warn!("Failed to remove staged file for key {}: {}", key, e);
                } else {
                    debug!("Cleaned up key: {}", key);
                }
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{write::GzEncoder, Compression};
    use std::io::Write;

    #[test]
    fn test_sanitize_key_for_path() {
        assert_eq!(sanitize_key_for_path("a/b/c.jsonl.gz"), "a_b_c.jsonl.gz");
        assert_eq!(sanitize_key_for_path("key:with:colons"), "key_with_colons");
        assert_eq!(
            sanitize_key_for_path("path/to/file.jsonl.gz"),
            "path_to_file.jsonl.gz"
        );
    }

    #[test]
    fn test_is_gzip_key() {
        let cases = vec![
            ("analytics/366676/366676_2025-01-01_0#0.json.gz", true),
            ("analytics/366676/366676_2025-01-01_0#1.json.gz", true),
            ("path/to/file.jsonl.gz", true),
            ("data.gz", true),
            ("analytics/366676/366676_2025-01-01_0_complete", false),
            ("some/path/metadata.json", false),
            ("", false),
        ];

        for (key, expected) in cases {
            assert_eq!(is_gzip_key(key), expected, "is_gzip_key({key:?})");
        }
    }

    fn write_gzip(content: &[u8]) -> (tempfile::TempDir, PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("obj.gz");
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(content).unwrap();
        let bytes = encoder.finish().unwrap();
        std::fs::write(&path, bytes).unwrap();
        (dir, path)
    }

    // Read the whole logical stream from a fresh reader in `chunk` sized reads.
    async fn read_all(raw_path: &Path, chunk: usize) -> Vec<u8> {
        let mut reader = ForwardReader::open(raw_path).await.unwrap();
        let mut out = Vec::new();
        loop {
            let mut buf = vec![0u8; chunk];
            let n = reader.read_logical(&mut buf).await.unwrap();
            if n == 0 {
                break;
            }
            out.extend_from_slice(&buf[..n]);
        }
        out
    }

    #[tokio::test]
    async fn test_decodes_full_content() {
        let (_dir, path) = write_gzip(b"line one\nline two\n");
        assert_eq!(read_all(&path, 4).await, b"line one\nline two\n");
    }

    #[tokio::test]
    async fn test_appends_trailing_newline_when_missing() {
        let (_dir, path) = write_gzip(b"no newline at end");
        assert_eq!(read_all(&path, 8).await, b"no newline at end\n");
    }

    #[tokio::test]
    async fn test_does_not_double_newline() {
        let (_dir, path) = write_gzip(b"ends with newline\n");
        assert_eq!(read_all(&path, 8).await, b"ends with newline\n");
    }

    #[tokio::test]
    async fn test_chunk_size_does_not_change_output() {
        let content = b"alpha\nbeta\ngamma\ndelta\nepsilon";
        let (_dir, path) = write_gzip(content);
        let small = read_all(&path, 1).await;
        let large = read_all(&path, 4096).await;
        assert_eq!(small, large);
        assert_eq!(small, b"alpha\nbeta\ngamma\ndelta\nepsilon\n");
    }

    #[tokio::test]
    async fn test_skip_matches_sequential_read_at_every_offset() {
        let content = b"first\nsecond\nthird\nfourth\nfifth";
        let (_dir, path) = write_gzip(content);
        let full = read_all(&path, 4096).await; // includes synthetic trailing newline

        // For each offset, a freshly-opened reader skipped to it must yield the same tail bytes a
        // sequential reader produces from that offset — this is the resume path.
        for offset in 0..=full.len() {
            let mut reader = ForwardReader::open(&path).await.unwrap();
            reader.skip(offset as u64).await.unwrap();
            let mut buf = vec![0u8; full.len()];
            let n = reader.read_logical(&mut buf).await.unwrap();
            assert_eq!(&buf[..n], &full[offset..], "mismatch resuming at {offset}");
        }
    }

    #[tokio::test]
    async fn test_empty_content_yields_no_bytes() {
        let (_dir, path) = write_gzip(b"");
        assert_eq!(read_all(&path, 16).await, b"");
    }

    fn dummy_client() -> S3Client {
        let conf = aws_sdk_s3::Config::builder()
            .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
            .region(aws_sdk_s3::config::Region::new("us-east-1"))
            .build();
        S3Client::from_conf(conf)
    }

    async fn source_with_prepared(key: &str, raw_path: PathBuf) -> GzipS3Source {
        let source = GzipS3Source::new(
            dummy_client(),
            "bucket".to_string(),
            "prefix".to_string(),
            std::env::temp_dir(),
        );
        source.prepared.lock().await.insert(
            key.to_string(),
            Arc::new(PreparedStream {
                raw_path: Some(raw_path),
                reader: Mutex::new(None),
            }),
        );
        source
    }

    #[tokio::test]
    async fn test_get_chunk_reassembles_sequentially_then_cleans_up() {
        let (_dir, path) = write_gzip(b"a\nbb\nccc\ndddd\neeeee");
        let key = "obj.gz";
        let source = source_with_prepared(key, path.clone()).await;

        let mut out = Vec::new();
        loop {
            let chunk = source.get_chunk(key, out.len() as u64, 4).await.unwrap();
            if chunk.is_empty() {
                break;
            }
            out.extend_from_slice(&chunk);
        }

        assert_eq!(out, b"a\nbb\nccc\ndddd\neeeee\n");
        // The staged file and prepared entry are removed once the part is fully consumed.
        assert!(source.prepared.lock().await.get(key).is_none());
        assert!(!path.exists());
    }

    #[tokio::test]
    async fn test_get_chunk_resumes_from_arbitrary_offset() {
        let (_dir, path) = write_gzip(b"first\nsecond\nthird\nfourth");
        let key = "obj.gz";
        let source = source_with_prepared(key, path).await;

        // A fresh source instance reading at a mid-stream offset (the resume path) returns the
        // same tail bytes a sequential reader would.
        let chunk = source.get_chunk(key, 7, 4096).await.unwrap();
        assert_eq!(&chunk, &b"first\nsecond\nthird\nfourth\n"[7..]);
    }
}
