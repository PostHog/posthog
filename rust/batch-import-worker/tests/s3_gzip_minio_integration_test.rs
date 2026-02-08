//! MinIO integration test for S3 gzip source: upload 3 × 10-event .jsonl.gz files,
//! run the pipeline (source + captured parser + file sink), assert 30 well-formed output events.
//!
//! Requires MinIO running at localhost:19000 (e.g. docker-compose.dev.yml). Skips if unreachable.

use anyhow::Result;
use batch_import_worker::{
    cache::{MemoryGroupCache, MemoryIdentifyCache},
    job::config::{JobSecrets, SourceConfig},
    parse::content::{captured::captured_parse_fn, TransformContext},
    parse::format::{json_nd, skip_geoip},
    parse::Parsed,
    source::DataSource,
};
use common_types::{InternallyCapturedEvent, RawEvent};
use flate2::write::GzEncoder;
use flate2::Compression;
use std::collections::HashSet;
use std::io::Write;
use std::sync::Arc;
use tempfile::NamedTempFile;
use uuid::Uuid;

mod common;
use common::{
    cleanup_bucket, create_minio_client, ensure_bucket_exists, MINIO_ACCESS_KEY, MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
};

const TEST_BUCKET: &str = "batch-import-test";
const TEST_PREFIX: &str = "s3_gzip_integration";
const CHUNK_SIZE: u64 = 64 * 1024;

fn make_captured_event(i: u32) -> String {
    let uuid = Uuid::now_v7();
    let distinct_id = format!("user-{}", i);
    let timestamp = format!("2024-01-{:02}T12:00:00Z", (i % 28) + 1);
    serde_json::json!({
        "event": "$pageview",
        "distinct_id": distinct_id,
        "timestamp": timestamp,
        "uuid": uuid.to_string(),
        "properties": { "idx": i }
    })
    .to_string()
}

fn gzip_bytes(data: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(data).unwrap();
    encoder.finish().unwrap()
}

#[tokio::test]
async fn test_s3_gzip_minio_integration() {
    let client = match create_minio_client().await.list_buckets().send().await {
        Ok(_) => create_minio_client().await,
        Err(_) => {
            eprintln!("MinIO unreachable at {}, skipping test", MINIO_ENDPOINT);
            return;
        }
    };

    ensure_bucket_exists(&client, TEST_BUCKET).await;
    cleanup_bucket(&client, TEST_BUCKET, TEST_PREFIX).await;

    let prefix = format!("{}/", TEST_PREFIX);
    for file_idx in 1..=3 {
        let mut lines = Vec::new();
        for i in 0..10 {
            let global_idx = (file_idx - 1) * 10 + i;
            lines.push(make_captured_event(global_idx));
        }
        let jsonl = lines.join("\n") + "\n";
        let gz = gzip_bytes(jsonl.as_bytes());
        let key = format!("{}file{}.jsonl.gz", prefix, file_idx);
        client
            .put_object()
            .bucket(TEST_BUCKET)
            .key(&key)
            .body(aws_sdk_s3::primitives::ByteStream::from(gz))
            .send()
            .await
            .expect("upload test file");
    }

    let source_config: SourceConfig = serde_json::from_value(serde_json::json!({
        "type": "s3_gzip",
        "access_key_id_key": "aws_access_key_id",
        "secret_access_key_key": "aws_secret_access_key",
        "bucket": TEST_BUCKET,
        "prefix": prefix,
        "region": "us-east-1",
        "endpoint_url": MINIO_ENDPOINT
    }))
    .expect("source config from json");
    let s3_config = match &source_config {
        SourceConfig::S3Gzip(c) => c.clone(),
        _ => panic!("expected s3_gzip"),
    };

    let secrets = JobSecrets {
        secrets: [
            (
                "aws_access_key_id".to_string(),
                serde_json::Value::String(MINIO_ACCESS_KEY.to_string()),
            ),
            (
                "aws_secret_access_key".to_string(),
                serde_json::Value::String(MINIO_SECRET_KEY.to_string()),
            ),
        ]
        .into_iter()
        .collect(),
    };

    let source = s3_config
        .create_gzip_source(&secrets)
        .await
        .expect("create gzip source");
    source.prepare_for_job().await.expect("prepare for job");

    let keys = source.keys().await.expect("keys");
    assert_eq!(keys.len(), 3, "expected 3 keys");

    let transform_context = TransformContext {
        team_id: 1,
        token: "test-token".to_string(),
        job_id: Uuid::now_v7(),
        identify_cache: Arc::new(MemoryIdentifyCache::with_defaults()),
        group_cache: Arc::new(MemoryGroupCache::with_defaults()),
        import_events: true,
        generate_identify_events: false,
        generate_group_identify_events: false,
    };

    let format_parse = json_nd::<RawEvent>(true);
    let event_transform = captured_parse_fn(transform_context, skip_geoip());

    let parser = move |data: Vec<u8>| -> Result<Parsed<Vec<InternallyCapturedEvent>>> {
        let parsed_raw = format_parse(data)?;
        let mut events = Vec::new();
        for raw in parsed_raw.data {
            if let Some(ev) = event_transform(raw)? {
                events.push(ev);
            }
        }
        Ok(Parsed {
            data: events,
            consumed: parsed_raw.consumed,
        })
    };

    let out_file = NamedTempFile::new().expect("temp file");
    let out_path = out_file.path().to_path_buf();

    let mut all_events: Vec<InternallyCapturedEvent> = Vec::new();
    for key in &keys {
        source.prepare_key(key).await.expect("prepare_key");
        let size = source.size(key).await.expect("size").expect("size some");
        let mut offset = 0u64;
        while offset < size {
            let chunk = source
                .get_chunk(key, offset, CHUNK_SIZE)
                .await
                .expect("get_chunk");
            let parsed = parser(chunk).expect("parse chunk");
            all_events.extend(parsed.data);
            offset += parsed.consumed as u64;
        }
    }

    let out_json = all_events
        .iter()
        .map(|e| serde_json::to_string(&e.inner).expect("serialize"))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(&out_path, out_json + "\n").expect("write output");

    assert_eq!(all_events.len(), 30, "expected 30 events");

    let mut uuids = HashSet::new();
    for ev in &all_events {
        uuids.insert(ev.inner.uuid.to_string());
    }
    assert_eq!(uuids.len(), 30, "30 unique uuids (no duplicate events)");

    cleanup_bucket(&client, TEST_BUCKET, TEST_PREFIX).await;
}
