//! End-to-end tests of the batch import pipeline against a mock export API
//! that behaves like the real Mixpanel/Amplitude endpoints - including the ways
//! they misbehave. No external services: the mock server, the source, the
//! parser, and the job fetch loop all run in-process.
//!
//! The central regression here is the offset-resume failure: a pod replacement
//! mid-part forces a re-download, the export API returns the same events in a
//! different byte order, and the committed decompressed-byte offset lands
//! mid-line in the new stream. The job must fail loudly (never silently skip
//! or duplicate data). See `E2E_TEST_PLAN.md`.

use std::collections::{HashMap, HashSet};

use batch_import_worker::error::{get_user_message, is_rate_limited_error};
use common_types::InternallyCapturedEvent;
use uuid::Uuid;

mod common;
use common::harness::{Harness, RunOutcome};
use common::mock_export::{Behavior, ExpectedEvent, MockExport, Provider};

const SEED: u64 = 0x5eed;

/// Split emitted events into (imported events, $identify events) as
/// `(uuid, name, distinct_id)` tuples.
fn split_emitted(events: &[InternallyCapturedEvent]) -> (Vec<ExpectedEvent>, usize) {
    let mut imported = Vec::new();
    let mut identifies = 0;
    for e in events {
        if e.inner.event == "$identify" {
            identifies += 1;
            continue;
        }
        imported.push(ExpectedEvent {
            uuid: e.inner.uuid,
            name: e.inner.event.clone(),
            distinct_id: e.inner.distinct_id.clone(),
        });
    }
    (imported, identifies)
}

/// Assert `emitted` contains every expected event exactly once and nothing else.
fn assert_exactly_once(emitted: &[InternallyCapturedEvent], expected: Vec<ExpectedEvent>) {
    let (imported, _) = split_emitted(emitted);

    let mut counts: HashMap<Uuid, usize> = HashMap::new();
    for ev in &imported {
        *counts.entry(ev.uuid).or_default() += 1;
    }
    let dupes: Vec<_> = counts.iter().filter(|(_, &c)| c > 1).collect();
    assert!(dupes.is_empty(), "duplicated events: {dupes:?}");

    let got: HashSet<ExpectedEvent> = imported.into_iter().collect();
    let want: HashSet<ExpectedEvent> = expected.into_iter().collect();
    let missing: Vec<_> = want.difference(&got).take(3).collect();
    let unexpected: Vec<_> = got.difference(&want).take(3).collect();
    assert!(
        missing.is_empty() && unexpected.is_empty(),
        "emitted set mismatch: {} missing (e.g. {missing:?}), {} unexpected (e.g. {unexpected:?})",
        want.difference(&got).count(),
        got.difference(&want).count(),
    );
}

fn expected_days(mock: &MockExport, days: &[&str]) -> Vec<ExpectedEvent> {
    days.iter().flat_map(|d| mock.expected_events(d)).collect()
}

#[tokio::test]
async fn mixpanel_happy_path_multi_day_multi_chunk() {
    // 1500 events/day at ~150 bytes/line is several 64 KiB chunks per part, so
    // the offset-advance arithmetic is exercised across chunk boundaries.
    let mock = MockExport::start(Provider::Mixpanel, SEED, 1500).await;
    let mut h = Harness::new(mock, "2022-01-24", 3, 64 * 1024).await;

    h.run_to_end().await.expect("import should complete");

    let want = expected_days(&h.mock, &["2022-01-24", "2022-01-25", "2022-01-26"]);
    assert_eq!(want.len(), 4500);
    assert_exactly_once(&h.emitted, want);

    for part in h.parts().await {
        assert!(part.is_done(), "part not done after run: {part:?}");
    }
    // One download per day: no spurious re-preparation.
    for day in ["2022-01-24", "2022-01-25", "2022-01-26"] {
        assert_eq!(h.mock.download_count(day), 1, "day {day}");
    }
}

#[tokio::test]
async fn amplitude_happy_path_with_identify_generation() {
    let mock = MockExport::start(Provider::Amplitude, SEED, 800).await;
    let mut h = Harness::new(mock, "2022-03-01", 2, 64 * 1024).await;

    h.run_to_end().await.expect("import should complete");

    let want = expected_days(&h.mock, &["2022-03-01", "2022-03-02"]);
    assert_exactly_once(&h.emitted, want);

    // Every unique (user_id, device_id) pair produces an $identify, and none is
    // fabricated. The exact count is not asserted: the transform runs in a
    // rayon pool, so the identify cache's check-then-mark can race within a
    // chunk and emit a duplicate $identify - harmless downstream, and the same
    // behavior production has.
    let identify_users: HashSet<String> = h
        .emitted
        .iter()
        .filter(|e| e.inner.event == "$identify")
        .map(|e| e.inner.distinct_id.clone())
        .collect();
    let expected_users: HashSet<String> = h
        .mock
        .expected_events("2022-03-01")
        .into_iter()
        .map(|ev| ev.distinct_id)
        .collect();
    assert_eq!(identify_users, expected_users);
    let (_, identifies) = split_emitted(&h.emitted);
    assert!(identifies >= h.mock.expected_identify_pairs("2022-03-01"));
}

#[tokio::test]
async fn restart_mid_part_with_stable_export_resumes_exactly_once() {
    let mock = MockExport::start(Provider::Mixpanel, SEED, 1500).await;
    let mut h = Harness::new(mock, "2022-01-24", 1, 32 * 1024).await;

    // Consume a couple of chunks, then lose the pod mid-part.
    let outcome = h.run_chunks(2).await.expect("first chunks should parse");
    assert!(matches!(outcome, RunOutcome::MoreRemaining));
    h.restart().await;

    h.run_to_end().await.expect("resume should complete");

    assert_exactly_once(&h.emitted, h.mock.expected_events("2022-01-24"));
    // The restart forced exactly one re-download.
    assert_eq!(h.mock.download_count("2022-01-24"), 2);
}

/// The production incident: a restart mid-part re-downloads the day, the export
/// returns the same events in a different order, and the committed offset lands
/// mid-line in the new byte stream. The job must surface a parse error - not
/// complete while silently skipping whatever moved before the resume offset.
#[tokio::test]
async fn restart_mid_part_with_reordered_export_fails_loudly() {
    let mock = MockExport::start(Provider::Mixpanel, SEED, 1500).await;
    mock.set_behavior("2022-01-24", Behavior::Reorder);
    let mut h = Harness::new(mock, "2022-01-24", 1, 32 * 1024).await;

    let outcome = h.run_chunks(2).await.expect("first chunks should parse");
    assert!(matches!(outcome, RunOutcome::MoreRemaining));
    let emitted_before_restart = h.emitted.len();
    h.restart().await;

    let err = h
        .run_to_end()
        .await
        .expect_err("resuming a byte-offset into a reordered stream must fail");
    let chain = format!("{err:#}");
    assert!(
        chain.contains("Failed to json parse line"),
        "expected the mid-line parse failure, got: {chain}"
    );
    assert!(
        get_user_message(&err).contains("Invalid JSON syntax"),
        "expected the user-facing parse message, got: {}",
        get_user_message(&err)
    );

    // Nothing may have been emitted from the misaligned stream, and nothing
    // emitted so far may be a duplicate or a fabrication.
    assert_eq!(h.emitted.len(), emitted_before_restart);
    let want: HashSet<ExpectedEvent> = h.mock.expected_events("2022-01-24").into_iter().collect();
    let (imported, _) = split_emitted(&h.emitted);
    let got: HashSet<ExpectedEvent> = imported.iter().cloned().collect();
    assert_eq!(got.len(), imported.len(), "duplicates before failure");
    assert!(
        got.is_subset(&want),
        "events emitted that were never generated"
    );
}

#[tokio::test]
async fn rate_limited_download_surfaces_and_then_succeeds() {
    let mock = MockExport::start(Provider::Mixpanel, SEED, 500).await;
    mock.set_behavior(
        "2022-01-24",
        Behavior::RateLimit {
            failures: 1,
            retry_after_secs: 1,
        },
    );
    let mut h = Harness::new(mock, "2022-01-24", 1, 64 * 1024).await;

    // The first attempt surfaces the 429 as a rate-limited error for job-level
    // backoff (the job runner owns the retry, not the source).
    let err = h.run_to_end().await.expect_err("first attempt is a 429");
    assert!(
        is_rate_limited_error(&err),
        "expected a rate-limited error, got: {err:#}"
    );
    assert!(h.emitted.is_empty());

    // The retry (post-backoff in production) completes exactly-once.
    h.run_to_end().await.expect("retry should complete");
    assert_exactly_once(&h.emitted, h.mock.expected_events("2022-01-24"));
    assert_eq!(h.mock.download_count("2022-01-24"), 2);
}

#[tokio::test]
async fn empty_days_complete_without_stalling() {
    let mock = MockExport::start(Provider::Mixpanel, SEED, 500).await;
    // A 404 day and a zero-byte-200 day mixed into a range with real data:
    // both are empty parts, neither may stall or fail the job.
    mock.set_behavior("2022-01-25", Behavior::NotFound);
    mock.set_behavior("2022-01-26", Behavior::EmptyBody);
    let mut h = Harness::new(mock, "2022-01-24", 3, 64 * 1024).await;

    h.run_to_end().await.expect("import should complete");

    assert_exactly_once(&h.emitted, h.mock.expected_events("2022-01-24"));
    for part in h.parts().await {
        assert!(part.is_done(), "part not done: {part:?}");
    }
}

#[tokio::test]
async fn chunk_size_sweep_is_exactly_once_at_every_boundary_shape() {
    // newline_delim's consumed arithmetic is boundary-sensitive (remainder
    // parses, chunks starting exactly on a newline). Sweep chunk sizes that
    // land mid-line, on power-of-two boundaries, and beyond the whole part.
    for chunk_size in [4 * 1024, 8 * 1024 - 1, 64 * 1024, 1 << 20] {
        let mock = MockExport::start(Provider::Mixpanel, SEED, 400).await;
        let mut h = Harness::new(mock, "2022-01-24", 1, chunk_size).await;

        h.run_to_end()
            .await
            .unwrap_or_else(|e| panic!("chunk_size {chunk_size}: {e:#}"));
        assert_exactly_once(&h.emitted, h.mock.expected_events("2022-01-24"));
    }
}
