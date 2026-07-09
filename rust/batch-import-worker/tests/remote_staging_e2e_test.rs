//! End-to-end validation of the S3 remote staging method through the job loop,
//! against live SeaweedFS (dev stack, S3 API on :8333). Skips when SeaweedFS is
//! unreachable locally; panics in CI where the dev stack is always up.
//!
//! Remote staging exists to make resume offsets safe: the decompressed part
//! plaintext is staged once to the temp bucket, so a pod replacement mid-part
//! re-reads the exact bytes the offset was committed against instead of
//! re-downloading from an export API that returns different bytes each call.
//! These tests prove that property end to end (exactly-once event output), plus
//! the guardrails around it: a swept staged object fails loudly, the plaintext
//! ceiling refuses oversized parts without leaving a readable object, and job
//! completion sweeps staging while transient interruption keeps it.
//!
//! A note on what is deliberately absent: there is no partially-staged-object
//! scenario. Staged parts are written as a multipart upload that is only
//! completed on success and aborted on any decode/ceiling error
//! (`src/staging/temp_bucket.rs`), so a readable partial object cannot exist.

use std::collections::HashSet;

use batch_import_worker::error::get_user_message;
use batch_import_worker::extractor::ExtractorType;
use batch_import_worker::job::model::{JobState, PartState};
use batch_import_worker::job::select_and_fetch_next_chunk;
use batch_import_worker::source::s3_gzip::GzipS3Source;
use batch_import_worker::source::{DataSource, RemoteStaging};
use batch_import_worker::staging::StagingBackend;
use common_types::InternallyCapturedEvent;
use object_store::ObjectStoreExt;
use tokio::sync::Mutex;
use uuid::Uuid;

mod common;
use common::harness::{build_parser, minimal_model, Harness, RunOutcome, StagingSpec};
use common::mock_export::{day_body, day_expected, Behavior, ExpectedEvent, MockExport, Provider};
use common::{seaweedfs_reachable, seaweedfs_sdk_client, seaweedfs_store};

const SEED: u64 = 0x57a6ed;
const STAGING_PREFIX: &str = "batch-import-staging/";

fn spec(max_plaintext_bytes: u64) -> StagingSpec {
    StagingSpec {
        store: seaweedfs_store(),
        prefix: STAGING_PREFIX.to_string(),
        job_tag: format!("e2e-{}", Uuid::now_v7()),
        max_plaintext_bytes,
    }
}

fn assert_exactly_once(emitted: &[InternallyCapturedEvent], expected: Vec<ExpectedEvent>) {
    let imported: Vec<ExpectedEvent> = emitted
        .iter()
        .filter(|e| e.inner.event != "$identify")
        .map(|e| ExpectedEvent {
            uuid: e.inner.uuid,
            name: e.inner.event.clone(),
            distinct_id: e.inner.distinct_id.clone(),
        })
        .collect();
    let got: HashSet<ExpectedEvent> = imported.iter().cloned().collect();
    let want: HashSet<ExpectedEvent> = expected.into_iter().collect();
    assert_eq!(got.len(), imported.len(), "duplicate events emitted");
    assert_eq!(
        got.len(),
        want.len(),
        "event count mismatch: got {}, want {}",
        got.len(),
        want.len()
    );
    assert_eq!(got, want, "emitted set does not match ground truth");
}

/// The staging counterpart of the incident regression: with remote staging, a
/// restart mid-part against a reordering export API must NOT re-download - the
/// resume reads the staged plaintext, so the committed offset stays valid and
/// the import completes exactly-once. This is the property that makes staging
/// the fix for the offset-misalignment failure class.
#[tokio::test]
async fn staged_resume_shields_against_reordering_export() {
    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable, skipping test");
        return;
    }

    let mock = MockExport::start(Provider::Mixpanel, SEED, 1500).await;
    mock.set_behavior("2022-01-24", Behavior::Reorder);
    let staging = spec(0);
    let backend = staging.backend();
    let mut h = Harness::with_staging(mock, "2022-01-24", 1, 32 * 1024, Some(staging)).await;

    let outcome = h.run_chunks(2).await.expect("first chunks should parse");
    assert!(matches!(outcome, RunOutcome::MoreRemaining));
    h.restart().await;

    h.run_to_end()
        .await
        .expect("staged resume must complete despite the reordering origin");

    assert_exactly_once(&h.emitted, h.mock.expected_events("2022-01-24"));
    assert_eq!(
        h.mock.download_count("2022-01-24"),
        1,
        "the resume must re-attach to the staged object, not re-download"
    );

    h.finish_job().await.unwrap();
    let _unused = backend.cleanup_job().await;
}

/// If the staged object disappears mid-pause (TTL sweep), the resume falls back
/// to a re-download - which against a reordering origin must fail loudly like
/// the unstaged path, never proceed silently.
#[tokio::test]
async fn swept_staged_object_falls_back_to_redownload_and_fails_loudly() {
    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable, skipping test");
        return;
    }

    let mock = MockExport::start(Provider::Mixpanel, SEED, 1500).await;
    mock.set_behavior("2022-01-24", Behavior::Reorder);
    let staging = spec(0);
    let backend = staging.backend();
    let mut h = Harness::with_staging(mock, "2022-01-24", 1, 32 * 1024, Some(staging)).await;

    let outcome = h.run_chunks(2).await.expect("first chunks should parse");
    assert!(matches!(outcome, RunOutcome::MoreRemaining));
    let emitted_before = h.emitted.len();
    h.restart().await;

    // Simulate the temp bucket TTL sweeping the staged object while paused.
    let key = h.parts().await[0].key.clone();
    backend.cleanup_key(&key).await.unwrap();

    let err = h
        .run_to_end()
        .await
        .expect_err("resume against a re-downloaded reordered stream must fail");
    assert!(
        get_user_message(&err).contains("Invalid JSON syntax"),
        "expected the parse failure, got: {err:#}"
    );
    assert_eq!(
        h.mock.download_count("2022-01-24"),
        2,
        "the swept object must force exactly one re-download"
    );
    assert_eq!(h.emitted.len(), emitted_before, "no output after the sweep");

    h.finish_job().await.unwrap();
    let _unused = backend.cleanup_job().await;
}

/// The decompression-bomb guard: a part whose plaintext exceeds
/// `max_plaintext_bytes` must refuse to stage with the user-facing ceiling
/// error, and must not leave a readable staged object behind.
#[tokio::test]
async fn plaintext_ceiling_refuses_part_and_leaves_no_object() {
    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable, skipping test");
        return;
    }

    // 1500 events decompress well past a 10 KiB ceiling.
    let mock = MockExport::start(Provider::Mixpanel, SEED, 1500).await;
    let staging = spec(10 * 1024);
    let backend = staging.backend();
    let mut h = Harness::with_staging(mock, "2022-01-24", 1, 32 * 1024, Some(staging)).await;

    let err = h
        .run_to_end()
        .await
        .expect_err("a part over the plaintext ceiling must refuse to stage");
    assert!(
        get_user_message(&err).contains("exceeding"),
        "expected the ceiling error, got: {}",
        get_user_message(&err)
    );
    assert!(h.emitted.is_empty());

    let key = h.parts().await[0].key.clone();
    assert_eq!(
        backend.size(&key).await.unwrap(),
        None,
        "an over-ceiling part must not leave a readable staged object"
    );

    h.finish_job().await.unwrap();
    let _unused = backend.cleanup_job().await;
}

/// The lifecycle contract that makes staged resume work at all: transient
/// interruption (`release_job_resources`) must keep staged objects for the
/// resume to re-attach to, while terminal cleanup (`cleanup_after_job`) must
/// sweep the job's staging prefix.
#[tokio::test]
async fn interruption_keeps_staging_and_completion_sweeps_it() {
    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable, skipping test");
        return;
    }

    let mock = MockExport::start(Provider::Mixpanel, SEED, 500).await;
    let staging = spec(0);
    let mut h =
        Harness::with_staging(mock, "2022-01-24", 1, 16 * 1024, Some(staging.clone())).await;

    let outcome = h.run_chunks(1).await.expect("first chunk should parse");
    assert!(matches!(outcome, RunOutcome::MoreRemaining));
    let key = h.parts().await[0].key.clone();
    // Each observation uses a fresh backend instance: the size cache is
    // per-instance, so a stale cache on a long-lived observer would mask the
    // very deletion this test asserts.
    assert!(
        staging.backend().size(&key).await.unwrap().is_some(),
        "part must be staged after the first read"
    );

    // Transient interruption: the staged object must survive for the resume.
    h.release_job().await.unwrap();
    assert!(
        staging.backend().size(&key).await.unwrap().is_some(),
        "release_job_resources must keep remote staging for the resume"
    );

    h.restart().await;
    h.run_to_end().await.expect("resume should complete");
    assert_exactly_once(&h.emitted, h.mock.expected_events("2022-01-24"));
    assert_eq!(h.mock.download_count("2022-01-24"), 1);

    // Terminal cleanup: the job's staging prefix must be swept.
    h.finish_job().await.unwrap();
    assert_eq!(
        staging.backend().size(&key).await.unwrap(),
        None,
        "cleanup_after_job must sweep the staged object"
    );
}

/// The S3 gzip source's staged path, which had no staged coverage at all: gzip
/// JSONL objects in a bucket (SeaweedFS standing in for a customer bucket) are
/// staged as plaintext, and a restart mid-part resumes from the staged copy to
/// an exactly-once result. Driven through the same job fetch loop as the
/// harness, with a hand-rolled loop because `Harness` is date-range specific.
#[tokio::test]
async fn gzip_s3_source_staged_restart_is_exactly_once() {
    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable, skipping test");
        return;
    }

    // Upload two gzip JSONL "files" as the customer bucket contents.
    let run_tag = Uuid::now_v7();
    let origin_prefix = format!("e2e-s3-origin/{run_tag}/");
    let days = ["2022-05-01", "2022-05-02"];
    for day in days {
        let body = day_body(Provider::Mixpanel, SEED, day, 800, 0, 0);
        store
            .put(
                &object_store::path::Path::from(format!("{origin_prefix}{day}.jsonl.gz")),
                body.into(),
            )
            .await
            .unwrap();
    }

    let staging_spec = spec(0);
    let backend = staging_spec.backend();
    let sdk_client = seaweedfs_sdk_client().await;
    let job_id = Uuid::now_v7();
    let staging_dir = tempfile::TempDir::new().unwrap();

    let build = || {
        GzipS3Source::new(
            sdk_client.clone(),
            common::SEAWEEDFS_BUCKET.to_string(),
            origin_prefix.clone(),
            ExtractorType::PlainGzip.create_extractor(),
            staging_dir.path().to_path_buf(),
            0,
            Some(RemoteStaging {
                backend: std::sync::Arc::new(staging_spec.backend()),
                extractor_type: ExtractorType::PlainGzip,
                max_plaintext_bytes: 0,
            }),
        )
    };

    let source = build();
    source.prepare_for_job().await.unwrap();
    let parts: Vec<PartState> = source
        .keys()
        .await
        .unwrap()
        .into_iter()
        .map(|key| PartState {
            key,
            current_offset: 0,
            total_size: None,
        })
        .collect();
    assert_eq!(parts.len(), 2, "both uploaded objects must be listed");

    let state = Mutex::new(JobState {
        parts: parts.clone(),
    });
    let model = Mutex::new(minimal_model(
        Provider::Mixpanel,
        job_id,
        JobState { parts },
    ));
    let parser = std::sync::Arc::new(build_parser(Provider::Mixpanel, job_id));
    let chunk_size = 16 * 1024;
    let mut emitted: Vec<InternallyCapturedEvent> = Vec::new();

    // First chunk, then a pod replacement.
    let (_, parsed, _) =
        select_and_fetch_next_chunk(&state, &model, &source, &parser, chunk_size, job_id)
            .await
            .expect("first chunk should parse")
            .expect("there is work to do");
    emitted.extend(parsed.data);
    drop(source);

    let resumed = build();
    resumed.prepare_for_job().await.unwrap();
    loop {
        match select_and_fetch_next_chunk(&state, &model, &resumed, &parser, chunk_size, job_id)
            .await
            .expect("staged resume must keep parsing")
        {
            None => break,
            Some((_, parsed, _)) => emitted.extend(parsed.data),
        }
    }

    let want: Vec<ExpectedEvent> = days
        .iter()
        .flat_map(|d| day_expected(Provider::Mixpanel, SEED, d, 800))
        .collect();
    assert_exactly_once(&emitted, want);

    resumed.cleanup_after_job().await.unwrap();
    let _unused = backend.cleanup_job().await;
    for day in days {
        let _unused = store
            .delete(&object_store::path::Path::from(format!(
                "{origin_prefix}{day}.jsonl.gz"
            )))
            .await;
    }
}
