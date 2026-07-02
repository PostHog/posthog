use std::fs::File as StdFile;
use std::io::Read;
use std::path::{Path, PathBuf};

use anyhow::{Context, Error};
use bytes::Bytes;
use flate2::read::GzDecoder;
use tokio::sync::mpsc;
use zip::ZipArchive;

use crate::error::UserError;
use crate::extractor::ExtractorType;

use super::backend::PlaintextStream;

// Blocks read from each gzip member, matching the extractor's buffer size.
const READ_BUFFER_SIZE: usize = 8192;
// Bounded channel depth: backpressure caps in-flight decompressed bytes.
const CHANNEL_CAPACITY: usize = 16;

/// Open a forward, on-demand decompression stream over a compressed `.raw` file.
///
/// The returned [`PlaintextStream`] yields the exact plaintext the materializing
/// `PartExtractor::extract_compressed_to_seekable_file` would have written to disk —
/// same decode, same natural-sort member order, same trailing-newline normalization —
/// so a part's byte offsets are identical whether it is staged from this stream or read
/// back from the legacy `.data` file. Decompression runs on a blocking task feeding a
/// bounded channel, so decode CPU stays off the async runtime and memory stays bounded.
///
/// `max_plaintext_bytes` is a per-part decompressed-byte ceiling (0 = disabled): if the
/// emitted plaintext exceeds it, the stream yields a user-facing error that pauses the
/// job instead of staging unbounded output. This is a decompression-bomb / cost guard,
/// not a disk guard.
pub fn open_plaintext_stream(
    raw_path: PathBuf,
    extractor: ExtractorType,
    max_plaintext_bytes: u64,
) -> PlaintextStream {
    let (tx, rx) = mpsc::channel(CHANNEL_CAPACITY);
    let handle = tokio::task::spawn_blocking(move || match extractor {
        ExtractorType::PlainGzip => run_plain_gzip_producer(raw_path, max_plaintext_bytes, &tx),
        ExtractorType::ZipGzipJson => {
            run_zip_gzip_json_producer(raw_path, max_plaintext_bytes, &tx)
        }
    });
    // Attach the producer handle so a panic in flate2/zip is surfaced as a stream error at
    // EOF instead of masquerading as a clean end-of-stream (silent truncation).
    PlaintextStream::from_producer(rx, handle)
}

/// Build the user-facing ceiling-breach error (classifies as Pause). Returned once the
/// running plaintext total exceeds a non-zero limit.
fn plaintext_ceiling_error(total: u64, max_plaintext_bytes: u64) -> Error {
    const GIB: f64 = (1024 * 1024 * 1024) as f64;
    let msg = format!(
        "Import part decompressed to {:.2} GiB, exceeding the {:.2} GiB limit \
         (STAGED_PLAINTEXT_MAX_BYTES={max_plaintext_bytes}); the source is likely \
         corrupt or misconfigured. Split the import into smaller parts or fix the source.",
        total as f64 / GIB,
        max_plaintext_bytes as f64 / GIB,
    );
    Error::from(UserError::new(msg))
}

/// Returns `true` once the ceiling is breached (limit enabled and total past it).
fn ceiling_breached(total: u64, max_plaintext_bytes: u64) -> bool {
    max_plaintext_bytes > 0 && total > max_plaintext_bytes
}

/// Decode a single gzip member forward, emitting decoded blocks and a single trailing
/// newline if the stream did not already end with one (matching `PlainGzipExtractor`).
fn run_plain_gzip_producer(
    raw_path: PathBuf,
    max_plaintext_bytes: u64,
    tx: &mpsc::Sender<Result<Bytes, Error>>,
) {
    let file = match StdFile::open(&raw_path).context("Failed to open gzip file for decompression")
    {
        Ok(f) => f,
        Err(e) => {
            drop(tx.blocking_send(Err(e)));
            return;
        }
    };

    let mut decoder = GzDecoder::new(file);
    let mut buffer = [0u8; READ_BUFFER_SIZE];
    let mut last_byte: Option<u8> = None;
    let mut total: u64 = 0;

    loop {
        let bytes_read = match decoder
            .read(&mut buffer)
            .context("Failed to decompress gzip data from file")
        {
            Ok(n) => n,
            Err(e) => {
                drop(tx.blocking_send(Err(e)));
                return;
            }
        };
        if bytes_read == 0 {
            break;
        }
        last_byte = Some(buffer[bytes_read - 1]);
        total += bytes_read as u64;
        if ceiling_breached(total, max_plaintext_bytes) {
            drop(tx.blocking_send(Err(plaintext_ceiling_error(total, max_plaintext_bytes))));
            return;
        }
        if tx
            .blocking_send(Ok(Bytes::copy_from_slice(&buffer[..bytes_read])))
            .is_err()
        {
            return;
        }
    }

    if last_byte != Some(b'\n') && total > 0 {
        drop(tx.blocking_send(Ok(Bytes::from_static(b"\n"))));
    }
}

/// Decode a zip of `*.json.gz` members in natural-sort order, emitting each member's
/// decoded bytes followed by a per-member trailing newline when missing (matching
/// `ZipGzipJsonExtractor`). A running total across all members feeds the ceiling.
fn run_zip_gzip_json_producer(
    raw_path: PathBuf,
    max_plaintext_bytes: u64,
    tx: &mpsc::Sender<Result<Bytes, Error>>,
) {
    let member_names = match collect_json_gz_members(&raw_path) {
        Ok(names) => names,
        Err(e) => {
            drop(tx.blocking_send(Err(e)));
            return;
        }
    };

    let mut total: u64 = 0;
    for member_name in member_names {
        let file =
            match StdFile::open(&raw_path).context("Failed to open zip file for decompression") {
                Ok(f) => f,
                Err(e) => {
                    drop(tx.blocking_send(Err(e)));
                    return;
                }
            };
        let mut archive =
            match ZipArchive::new(file).context("Failed to read zip archive for decompression") {
                Ok(a) => a,
                Err(e) => {
                    drop(tx.blocking_send(Err(e)));
                    return;
                }
            };
        let zip_file = match archive
            .by_name(&member_name)
            .context("Failed to find file in zip archive")
        {
            Ok(f) => f,
            Err(e) => {
                drop(tx.blocking_send(Err(e)));
                return;
            }
        };

        let mut decoder = GzDecoder::new(zip_file);
        let mut buffer = [0u8; READ_BUFFER_SIZE];
        let mut last_byte: Option<u8> = None;
        let mut member_size: u64 = 0;

        loop {
            let bytes_read = match decoder
                .read(&mut buffer)
                .context("Failed to decompress gzip data from zip member")
            {
                Ok(n) => n,
                Err(e) => {
                    drop(tx.blocking_send(Err(e)));
                    return;
                }
            };
            if bytes_read == 0 {
                break;
            }
            last_byte = Some(buffer[bytes_read - 1]);
            member_size += bytes_read as u64;
            total += bytes_read as u64;
            if ceiling_breached(total, max_plaintext_bytes) {
                drop(tx.blocking_send(Err(plaintext_ceiling_error(total, max_plaintext_bytes))));
                return;
            }
            if tx
                .blocking_send(Ok(Bytes::copy_from_slice(&buffer[..bytes_read])))
                .is_err()
            {
                return;
            }
        }

        if last_byte != Some(b'\n') && member_size > 0 {
            total += 1;
            if tx.blocking_send(Ok(Bytes::from_static(b"\n"))).is_err() {
                return;
            }
        }
    }
}

/// List the `*.json.gz` members of a zip archive in natural-sort order (matching the
/// extractor's `natord` ordering).
fn collect_json_gz_members(raw_path: &Path) -> Result<Vec<String>, Error> {
    let file = StdFile::open(raw_path).context("Failed to open zip file")?;
    let mut archive = ZipArchive::new(file).context("Failed to read and create zip archive")?;

    let mut names: Vec<String> = (0..archive.len())
        .filter_map(|i| {
            archive.by_index(i).ok().and_then(|f| {
                let name = f.name().to_string();
                name.ends_with(".json.gz").then_some(name)
            })
        })
        .collect();

    names.sort_by(|a, b| natord::compare(a, b));
    Ok(names)
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{write::GzEncoder, Compression};
    use std::io::Write;
    use tempfile::TempDir;
    use zip::{write::SimpleFileOptions, ZipWriter};

    fn write_gzip(content: &[u8], path: &std::path::Path) {
        let file = StdFile::create(path).unwrap();
        let mut encoder = GzEncoder::new(file, Compression::default());
        encoder.write_all(content).unwrap();
        encoder.finish().unwrap();
    }

    fn write_zip_of_gzip(members: &[(&str, &[u8])], path: &std::path::Path) {
        let file = StdFile::create(path).unwrap();
        let mut zip = ZipWriter::new(file);
        for (name, content) in members {
            zip.start_file(*name, SimpleFileOptions::default()).unwrap();
            let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
            encoder.write_all(content).unwrap();
            let compressed = encoder.finish().unwrap();
            zip.write_all(&compressed).unwrap();
        }
        zip.finish().unwrap();
    }

    async fn collect(mut stream: PlaintextStream) -> Result<Vec<u8>, Error> {
        let mut out = Vec::new();
        while let Some(block) = stream.next().await {
            out.extend_from_slice(&block?);
        }
        Ok(out)
    }

    /// Bytes the materializing extractor would have written to disk — the oracle the
    /// streaming pipeline must reproduce exactly.
    async fn extractor_data(extractor: ExtractorType, raw_path: &std::path::Path) -> Vec<u8> {
        let temp_dir = TempDir::new().unwrap();
        let part = extractor
            .create_extractor()
            .extract_compressed_to_seekable_file("golden", raw_path, temp_dir.path())
            .await
            .unwrap();
        let bytes = tokio::fs::read(&part.data_file_path).await.unwrap();
        assert_eq!(
            bytes.len(),
            part.data_file_size,
            "extractor data_file_size must match on-disk length"
        );
        bytes
    }

    async fn assert_pipeline_matches_extractor(extractor: ExtractorType, raw_path: PathBuf) {
        let expected = extractor_data(extractor.clone(), &raw_path).await;
        let actual = collect(open_plaintext_stream(raw_path, extractor, 0))
            .await
            .unwrap();
        assert_eq!(actual, expected);
    }

    #[tokio::test]
    async fn plain_gzip_with_trailing_newline_matches_extractor() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip(b"line1\nline2\nline3\n", &raw);
        assert_pipeline_matches_extractor(ExtractorType::PlainGzip, raw).await;
    }

    #[tokio::test]
    async fn plain_gzip_without_trailing_newline_appends_one() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip(b"line1\nline2\nline3", &raw);
        // Prove the appended newline both matches the extractor and is actually present.
        let expected = extractor_data(ExtractorType::PlainGzip, &raw).await;
        assert_eq!(expected, b"line1\nline2\nline3\n");
        let actual = collect(open_plaintext_stream(raw, ExtractorType::PlainGzip, 0))
            .await
            .unwrap();
        assert_eq!(actual, expected);
    }

    #[tokio::test]
    async fn empty_gzip_yields_no_bytes_and_no_newline() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip(b"", &raw);
        let actual = collect(open_plaintext_stream(
            raw.clone(),
            ExtractorType::PlainGzip,
            0,
        ))
        .await
        .unwrap();
        assert!(actual.is_empty());
        assert_pipeline_matches_extractor(ExtractorType::PlainGzip, raw).await;
    }

    #[tokio::test]
    async fn large_plain_gzip_matches_extractor() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip("line\n".repeat(10_000).as_bytes(), &raw);
        assert_pipeline_matches_extractor(ExtractorType::PlainGzip, raw).await;
    }

    #[tokio::test]
    async fn zip_single_member_matches_extractor() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.zip");
        write_zip_of_gzip(&[("data.json.gz", b"{\"a\":1}")], &raw);
        assert_pipeline_matches_extractor(ExtractorType::ZipGzipJson, raw).await;
    }

    #[tokio::test]
    async fn zip_multi_member_preserves_natsort_order_and_per_member_newlines() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.zip");
        // Intentionally out of lexical/natural order in the archive; extractor sorts by natord.
        write_zip_of_gzip(
            &[
                ("010.json.gz", b"{\"id\":10}"),
                ("002.json.gz", b"{\"id\":2}\n"),
                ("001.json.gz", b"{\"id\":1}"),
            ],
            &raw,
        );
        let expected = extractor_data(ExtractorType::ZipGzipJson, &raw).await;
        // natord order 001, 002, 010; 001 and 010 get a newline appended, 002 already has one.
        assert_eq!(expected, b"{\"id\":1}\n{\"id\":2}\n{\"id\":10}\n");
        let actual = collect(open_plaintext_stream(raw, ExtractorType::ZipGzipJson, 0))
            .await
            .unwrap();
        assert_eq!(actual, expected);
    }

    #[tokio::test]
    async fn zip_ignores_non_json_gz_members() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.zip");
        let file = StdFile::create(&raw).unwrap();
        let mut zip = ZipWriter::new(file);
        zip.start_file("data.json.gz", SimpleFileOptions::default())
            .unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"valid json").unwrap();
        let compressed = encoder.finish().unwrap();
        zip.write_all(&compressed).unwrap();
        zip.start_file("readme.txt", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"ignore me").unwrap();
        zip.finish().unwrap();

        assert_pipeline_matches_extractor(ExtractorType::ZipGzipJson, raw).await;
    }

    #[tokio::test]
    async fn truncated_gzip_surfaces_error_not_silent_truncation() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip(b"some content that will be cut off midstream", &raw);
        // Chop the gzip trailer/body so decoding fails partway.
        let full = std::fs::read(&raw).unwrap();
        std::fs::write(&raw, &full[..full.len() - 5]).unwrap();

        let result = collect(open_plaintext_stream(raw, ExtractorType::PlainGzip, 0)).await;
        assert!(result.is_err(), "truncated gzip must surface an error");
    }

    #[tokio::test]
    async fn ceiling_breach_yields_pause_classified_user_error() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip("x".repeat(100_000).as_bytes(), &raw);

        let err = collect(open_plaintext_stream(raw, ExtractorType::PlainGzip, 1024))
            .await
            .unwrap_err();

        // Actionable user message survives in the chain (so the job pauses, not retries),
        // and it is GiB-formatted.
        let user_msg = crate::error::get_user_message(&err);
        assert!(
            user_msg.contains("STAGED_PLAINTEXT_MAX_BYTES=1024"),
            "unexpected message: {user_msg}"
        );
        assert!(user_msg.contains("GiB"), "unexpected message: {user_msg}");
        // Not classified as a transient/retryable error.
        assert!(!crate::error::is_rate_limited_error(&err));
        assert!(!crate::error::is_timeout_error(&err));
        assert!(!crate::error::is_transient_network_error(&err));
        assert!(!crate::error::is_transient_server_error(&err));
    }

    #[tokio::test]
    async fn ceiling_disabled_with_zero_never_trips() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        // Newline-terminated so nothing is appended and the length is exact.
        write_gzip("y\n".repeat(25_000).as_bytes(), &raw);
        let actual = collect(open_plaintext_stream(raw, ExtractorType::PlainGzip, 0))
            .await
            .unwrap();
        assert_eq!(actual.len(), 50_000);
    }
}
