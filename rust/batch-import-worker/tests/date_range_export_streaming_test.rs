//! Dependency-free integration tests for the streaming-decompression path of the
//! date range export source. These exercise the real `PlainGzipExtractor` (not a
//! mock) end-to-end through the public `DataSource` interface, asserting the
//! properties that matter for the critical batch-import path:
//!
//! - reconstruction: the decompressed stream read in small forward chunks equals
//!   the original body (with the trailing-newline guarantee),
//! - resume: a fresh source instance (simulating a pod restart) can resume from a
//!   persisted decompressed offset and reconstruct the remainder exactly,
//! - disk bounding: reading never materializes a decompressed `.data` file, so
//!   staging disk usage stays bounded by the compressed `.raw` size even when the
//!   content decompresses to something far larger.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use batch_import_worker::extractor::ExtractorType;
use batch_import_worker::source::date_range_export::{AuthConfig, DateRangeExportSource};
use batch_import_worker::source::DataSource;
use chrono::{TimeZone, Utc};
use httpmock::MockServer;
use tempfile::TempDir;

mod common;
use common::gzip_bytes;

/// Build a single-interval source pointed at `base_url`, staging under `staging`.
fn build_source(base_url: String, staging: &Path) -> DateRangeExportSource {
    let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
    let end = Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap();
    DateRangeExportSource::builder(
        base_url,
        start,
        end,
        3600,
        ExtractorType::PlainGzip.create_extractor(),
        staging.to_path_buf(),
    )
    .with_auth(AuthConfig::None)
    .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
    .with_headers(HashMap::new())
    .build()
    .unwrap()
}

/// Consume a key forward from `start_offset` in `chunk`-sized reads until the
/// stream ends (an empty chunk), returning the concatenated bytes.
async fn read_forward(
    source: &DateRangeExportSource,
    key: &str,
    start_offset: u64,
    chunk: u64,
) -> Vec<u8> {
    let mut out = Vec::new();
    let mut offset = start_offset;
    loop {
        let bytes = source
            .get_chunk(key, offset, chunk)
            .await
            .expect("get_chunk");
        if bytes.is_empty() {
            break;
        }
        offset += bytes.len() as u64;
        out.extend_from_slice(&bytes);
    }
    out
}

fn list_files_with_ext(dir: &Path, ext: &str) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else if path.extension().and_then(|e| e.to_str()) == Some(ext) {
                out.push(path);
            }
        }
    }
    out
}

fn staging_total_bytes(dir: &Path) -> u64 {
    let mut total = 0u64;
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else if let Ok(meta) = entry.metadata() {
                total += meta.len();
            }
        }
    }
    total
}

#[tokio::test]
async fn test_streaming_reconstructs_full_body() {
    let server = MockServer::start();
    // Distinct JSONL lines so a misordered/duplicated stream would be detectable;
    // body ends with a newline so the decompressed output equals the body exactly.
    let mut body = String::new();
    for i in 0..5000 {
        body.push_str(&format!(
            "{{\"event\":\"e{i}\",\"properties\":{{\"idx\":{i}}}}}\n"
        ));
    }
    let gz = gzip_bytes(body.as_bytes());
    let _mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path("/export");
        then.status(200).body(gz);
    });

    let staging = TempDir::new().unwrap();
    let source = build_source(server.url("/export"), staging.path());
    source.prepare_for_job().await.unwrap();
    let keys = source.keys().await.unwrap();
    let key = &keys[0];
    source.prepare_key(key).await.unwrap();

    // Small chunk size exercises the carry buffer across many reads.
    let reconstructed = read_forward(&source, key, 0, 1024).await;
    assert_eq!(reconstructed, body.as_bytes());

    source.cleanup_after_job().await.unwrap();
}

#[tokio::test]
async fn test_streaming_resumes_from_offset_after_restart() {
    let server = MockServer::start();
    let mut body = String::new();
    for i in 0..5000 {
        body.push_str(&format!("line-{i}-{}\n", "x".repeat(20)));
    }
    let gz = gzip_bytes(body.as_bytes());
    let _mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path("/export");
        then.status(200).body(gz);
    });

    let staging = TempDir::new().unwrap();

    // First instance: read roughly the first half, tracking the decompressed
    // offset the job would persist in PartState.current_offset.
    let resume_offset;
    let mut prefix = Vec::new();
    {
        let source = build_source(server.url("/export"), staging.path());
        source.prepare_for_job().await.unwrap();
        let keys = source.keys().await.unwrap();
        let key = &keys[0];
        source.prepare_key(key).await.unwrap();

        let half = (body.len() / 2) as u64;
        let mut offset = 0u64;
        while offset < half {
            let bytes = source.get_chunk(key, offset, 777).await.unwrap();
            assert!(
                !bytes.is_empty(),
                "did not expect EOF before the halfway mark"
            );
            offset += bytes.len() as u64;
            prefix.extend_from_slice(&bytes);
        }
        resume_offset = offset;
        source.cleanup_after_job().await.unwrap();
    }

    assert!(resume_offset > 0 && (resume_offset as usize) < body.len());

    // Second instance (fresh, as after a pod restart): resume from the persisted
    // offset and read the remainder.
    let suffix;
    {
        let source = build_source(server.url("/export"), staging.path());
        source.prepare_for_job().await.unwrap();
        let keys = source.keys().await.unwrap();
        let key = &keys[0];
        source.prepare_key(key).await.unwrap();

        suffix = read_forward(&source, key, resume_offset, 999).await;
        source.cleanup_after_job().await.unwrap();
    }

    let mut combined = prefix;
    combined.extend_from_slice(&suffix);
    assert_eq!(
        combined,
        body.as_bytes(),
        "prefix + resumed suffix must reconstruct the full body with no gap or overlap"
    );
}

#[tokio::test]
async fn test_streaming_does_not_materialize_decompressed_file() {
    let server = MockServer::start();
    // Highly compressible: ~4 MiB decompressed from a few KiB compressed.
    let body = "A".repeat(4 * 1024 * 1024) + "\n";
    let gz = gzip_bytes(body.as_bytes());
    let compressed_len = gz.len() as u64;
    assert!(
        compressed_len < (body.len() as u64) / 10,
        "test setup expects strong compression"
    );

    let _mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path("/export");
        then.status(200).body(gz);
    });

    let staging = TempDir::new().unwrap();
    let source = build_source(server.url("/export"), staging.path());
    source.prepare_for_job().await.unwrap();
    let keys = source.keys().await.unwrap();
    let key = &keys[0];
    source.prepare_key(key).await.unwrap();

    // After prepare: the compressed .raw exists, no decompressed .data file does,
    // and staging is bounded by the compressed size (not the decompressed size).
    assert_eq!(
        list_files_with_ext(staging.path(), "raw").len(),
        1,
        "expected the compressed .raw to be retained"
    );
    assert!(
        list_files_with_ext(staging.path(), "data").is_empty(),
        "streaming must not materialize a decompressed .data file"
    );

    // Read part of the (large) decompressed stream, then re-check: still no .data,
    // and staging stays close to the compressed size rather than ballooning toward
    // the multi-MiB decompressed size.
    source.get_chunk(key, 0, 64 * 1024).await.unwrap();
    source.get_chunk(key, 64 * 1024, 64 * 1024).await.unwrap();
    assert!(
        list_files_with_ext(staging.path(), "data").is_empty(),
        "streaming must not materialize a decompressed .data file mid-read"
    );
    assert!(
        staging_total_bytes(staging.path()) < (body.len() as u64) / 4,
        "staging disk usage must stay bounded by the compressed size, not the decompressed size"
    );

    // Fully consume to confirm correctness, then clean up.
    let rest = read_forward(&source, key, 128 * 1024, 256 * 1024).await;
    assert_eq!(128 * 1024 + rest.len(), body.len());

    source.cleanup_after_job().await.unwrap();
}
