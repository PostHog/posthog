use std::path::PathBuf;

use anyhow::Error;
use bytes::Bytes;
use tokio::sync::mpsc;

use crate::error::UserError;
use crate::extractor::{
    run_plain_gzip_producer, run_zip_gzip_json_producer, spawn_producer_thread, ExtractorType,
};

use super::backend::PlaintextStream;

// Bounded adapter channel depth: backpressure caps in-flight decompressed bytes.
const CHANNEL_CAPACITY: usize = 16;

/// Open a forward, on-demand decompression stream over a compressed `.raw` file.
///
/// This reuses the exact producers behind [`crate::extractor::StreamingReader`]
/// (`run_plain_gzip_producer` / `run_zip_gzip_json_producer`), so the emitted plaintext is
/// byte-identical to what the streaming read path decodes — same single-member
/// `GzDecoder` semantics, same natural-sort member ordering, same trailing-newline
/// normalization — by construction, not by parallel implementation. That identity is what
/// keeps a part's byte offsets valid across staging backends.
///
/// The producer runs on a dedicated OS thread (via the shared, panic-guarded
/// [`spawn_producer_thread`]); a small async adapter task converts its blocks and applies
/// the ceiling.
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
    let block_rx = match extractor {
        ExtractorType::PlainGzip => {
            spawn_producer_thread(move |tx| run_plain_gzip_producer(raw_path, tx))
        }
        ExtractorType::ZipGzipJson => {
            spawn_producer_thread(move |tx| run_zip_gzip_json_producer(raw_path, tx))
        }
    };

    let (tx, rx) = mpsc::channel(CHANNEL_CAPACITY);
    // Attach the adapter handle so a panic in the adapter itself is surfaced as a stream
    // error at EOF instead of masquerading as a clean end-of-stream. Producer-thread
    // panics are already converted to channel errors by spawn_producer_thread.
    let handle = tokio::spawn(adapt_blocks(block_rx, tx, max_plaintext_bytes));
    PlaintextStream::from_producer(rx, handle)
}

/// Forward producer blocks to the plaintext channel, converting `Block` errors into
/// `anyhow` errors and enforcing the decompressed-byte ceiling at this single choke point.
async fn adapt_blocks(
    mut block_rx: mpsc::Receiver<crate::extractor::Block>,
    tx: mpsc::Sender<Result<Bytes, Error>>,
    max_plaintext_bytes: u64,
) {
    let mut total: u64 = 0;
    while let Some(block) = block_rx.recv().await {
        match block {
            Ok(block) => {
                total += block.len() as u64;
                if max_plaintext_bytes > 0 && total > max_plaintext_bytes {
                    let _unused = tx
                        .send(Err(plaintext_ceiling_error(total, max_plaintext_bytes)))
                        .await;
                    return;
                }
                if tx.send(Ok(Bytes::from(block))).await.is_err() {
                    return;
                }
            }
            Err(msg) => {
                let _unused = tx.send(Err(Error::msg(msg))).await;
                return;
            }
        }
    }
}

/// Build the ceiling-breach error (classifies as Pause). Returned once the running
/// plaintext total exceeds a non-zero limit.
///
/// Two channels, per the worker's error convention: the `UserError` context is the
/// public, actionable message (no internal config names — the limit may be operator-set
/// or derived, and either way the remedy is the same); the root error carries the
/// internal detail for `status_message` and logs.
fn plaintext_ceiling_error(total: u64, max_plaintext_bytes: u64) -> Error {
    const GIB: f64 = (1024 * 1024 * 1024) as f64;
    let user_msg = format!(
        "Import part decompressed to {:.2} GiB, exceeding the {:.2} GiB maximum for a \
         single part. Split the import into smaller date ranges (direct imports) or \
         smaller files (S3 imports) and run them as separate jobs.",
        total as f64 / GIB,
        max_plaintext_bytes as f64 / GIB,
    );
    Error::msg(format!(
        "staged plaintext exceeded ceiling: {total} bytes > STAGED_PLAINTEXT_MAX_BYTES={max_plaintext_bytes}"
    ))
    .context(UserError::new(user_msg))
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{write::GzEncoder, Compression};
    use std::fs::File as StdFile;
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

    /// Bytes the streaming read path decodes for the same file — the oracle the pipeline
    /// must reproduce exactly (both consume the same producers; this locks the adapter).
    async fn reader_oracle(extractor: ExtractorType, raw_path: &std::path::Path) -> Vec<u8> {
        let mut reader = extractor
            .create_extractor()
            .open_reader(raw_path.to_path_buf());
        let (bytes, total) = reader.read_to_end_for_test(8192).await;
        assert_eq!(bytes.len() as u64, total);
        bytes
    }

    /// Assert the pipeline matches both the streaming reader and, when provided, an
    /// explicit expected byte string (so the oracle is not purely self-referential).
    async fn assert_pipeline_output(
        extractor: ExtractorType,
        raw_path: PathBuf,
        expected: Option<&[u8]>,
    ) {
        let oracle = reader_oracle(extractor.clone(), &raw_path).await;
        if let Some(expected) = expected {
            assert_eq!(oracle, expected, "oracle must match explicit fixture");
        }
        let actual = collect(open_plaintext_stream(raw_path, extractor, 0))
            .await
            .unwrap();
        assert_eq!(actual, oracle);
    }

    #[tokio::test]
    async fn plain_gzip_with_trailing_newline_matches_reader() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip(b"line1\nline2\nline3\n", &raw);
        assert_pipeline_output(
            ExtractorType::PlainGzip,
            raw,
            Some(b"line1\nline2\nline3\n"),
        )
        .await;
    }

    #[tokio::test]
    async fn plain_gzip_without_trailing_newline_appends_one() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip(b"line1\nline2\nline3", &raw);
        assert_pipeline_output(
            ExtractorType::PlainGzip,
            raw,
            Some(b"line1\nline2\nline3\n"),
        )
        .await;
    }

    #[tokio::test]
    async fn empty_gzip_yields_no_bytes_and_no_newline() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        write_gzip(b"", &raw);
        assert_pipeline_output(ExtractorType::PlainGzip, raw, Some(b"")).await;
    }

    #[tokio::test]
    async fn large_plain_gzip_matches_reader() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.raw");
        // Many producer blocks; no explicit fixture needed, reader oracle suffices.
        write_gzip("line\n".repeat(100_000).as_bytes(), &raw);
        assert_pipeline_output(ExtractorType::PlainGzip, raw, None).await;
    }

    #[tokio::test]
    async fn zip_multi_member_preserves_natsort_order_and_per_member_newlines() {
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("a.zip");
        // Out of natural order in the archive; members 001 and 010 need appended newlines.
        write_zip_of_gzip(
            &[
                ("010.json.gz", b"{\"id\":10}"),
                ("002.json.gz", b"{\"id\":2}\n"),
                ("001.json.gz", b"{\"id\":1}"),
            ],
            &raw,
        );
        assert_pipeline_output(
            ExtractorType::ZipGzipJson,
            raw,
            Some(b"{\"id\":1}\n{\"id\":2}\n{\"id\":10}\n"),
        )
        .await;
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

        assert_pipeline_output(ExtractorType::ZipGzipJson, raw, Some(b"valid json\n")).await;
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

        // Actionable public message survives in the chain (so the job pauses, not
        // retries), is GiB-formatted, and leaks no internal config names.
        let user_msg = crate::error::get_user_message(&err);
        assert!(user_msg.contains("GiB"), "unexpected message: {user_msg}");
        assert!(
            user_msg.contains("Split the import"),
            "unexpected message: {user_msg}"
        );
        assert!(
            !user_msg.contains("STAGED_PLAINTEXT_MAX_BYTES"),
            "public message must not leak env var names: {user_msg}"
        );
        // The internal chain keeps the config detail for status_message/logs.
        let internal = format!("{err:#}");
        assert!(
            internal.contains("STAGED_PLAINTEXT_MAX_BYTES=1024"),
            "internal chain must carry the limit detail: {internal}"
        );
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
