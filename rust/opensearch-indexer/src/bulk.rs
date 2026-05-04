use std::collections::HashMap;
use std::io::Write;
use std::time::{Duration, Instant};

use bytes::Bytes;
use common_kafka::kafka_consumer::Offset;
use serde::Deserialize;
use thiserror::Error;
use tracing::{error, warn};

use crate::types::IndexDoc;

const RETRY_INITIAL: Duration = Duration::from_secs(1);
const RETRY_MAX: Duration = Duration::from_secs(60);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(120);

/// Per-item overhead from the action line + two newlines on top of the
/// serialized body. `{"index":{"_id":"<36-char uuid>"}}\n` plus the trailing
/// newline after the body line. Constant since `event_uuid` is hyphenated.
const ACTION_LINE_OVERHEAD: usize = 36 + 17 + 2;

/// Coarse over-estimate added per doc to cover JSON scaffolding (keys,
/// separators) for the small metadata fields we don't enumerate.
const DOC_OVERHEAD_FUDGE: usize = 256;

/// Test seam: read-only access to the offset's per-partition identity. Lets
/// `BulkBatch` build the per-partition commit map without depending on the
/// concrete `Offset` (whose `Weak<Inner>` handle is non-constructible outside
/// `common_kafka`). `common_kafka::transaction.rs` does the equivalent reduce
/// inline because it's same-crate; this trait is the cross-crate equivalent.
pub trait OffsetKey {
    fn partition(&self) -> i32;
    fn value(&self) -> i64;
}

impl OffsetKey for Offset {
    fn partition(&self) -> i32 {
        Offset::partition(self)
    }
    fn value(&self) -> i64 {
        self.get_value()
    }
}

/// Test seam: commit one offset to the broker. Production `Offset` calls
/// `store()`; tests record the call and return success.
pub trait StoreOffset: OffsetKey + Sized {
    fn store_now(self) -> bool;
}

impl StoreOffset for Offset {
    fn store_now(self) -> bool {
        match self.store() {
            Ok(()) => true,
            Err(e) => {
                error!(error = %e, "Failed to store offset after bulk ack");
                false
            }
        }
    }
}

#[derive(Debug)]
struct PendingItem<O> {
    doc: IndexDoc,
    offset: O,
}

/// `Permanent` and `Retryable` carry response context so the DLQ-bound log
/// surfaces the *why*.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ItemOutcome {
    Success,
    Permanent {
        status: u16,
        error_type: Option<String>,
        error_reason: Option<String>,
    },
    Retryable {
        status: u16,
    },
}

/// Retains retryable items across flushes; resolved (Success or Permanent)
/// items leave on the same flush, subject to the per-partition low-water-mark
/// hold. Generic over the offset type so unit tests can use `TestOffset`.
#[derive(Debug)]
pub struct BulkBatch<O = Offset> {
    items: Vec<PendingItem<O>>,
    skip_offsets: Vec<O>,
    bytes_estimate: usize,
    /// Earliest of (first indexed doc's `parsed_at`, wall-clock at first skip).
    /// Reset to None on a clean flush; recomputed from retained items on a
    /// flush that retains.
    flush_age_anchor: Option<Instant>,
}

impl<O> BulkBatch<O> {
    pub fn new() -> Self {
        Self {
            items: Vec::new(),
            skip_offsets: Vec::new(),
            bytes_estimate: 0,
            flush_age_anchor: None,
        }
    }

    pub fn doc_count(&self) -> usize {
        self.items.len()
    }

    pub fn offset_count(&self) -> usize {
        self.items.len() + self.skip_offsets.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty() && self.skip_offsets.is_empty()
    }

    /// Caller can bypass the `_bulk` POST and commit skip offsets directly.
    pub(crate) fn is_skip_only(&self) -> bool {
        self.items.is_empty() && !self.skip_offsets.is_empty()
    }

    pub fn push_index(&mut self, doc: IndexDoc, offset: O) {
        if self.flush_age_anchor.is_none() {
            self.flush_age_anchor = Some(doc.parsed_at);
        }
        self.bytes_estimate += approx_doc_bytes(&doc) + ACTION_LINE_OVERHEAD;
        self.items.push(PendingItem { doc, offset });
    }

    pub fn push_skip(&mut self, offset: O) {
        if self.flush_age_anchor.is_none() {
            self.flush_age_anchor = Some(Instant::now());
        }
        self.skip_offsets.push(offset);
    }

    pub fn should_flush_size(&self, max_bytes: usize) -> bool {
        self.bytes_estimate >= max_bytes
    }

    pub fn should_flush_age(&self, max_age: Duration) -> bool {
        self.flush_age_anchor
            .map(|t| t.elapsed() >= max_age)
            .unwrap_or(false)
    }

    fn build_payload(&self) -> Vec<u8> {
        let mut payload = Vec::with_capacity(self.bytes_estimate.max(self.items.len() * 256));
        for item in &self.items {
            serialize_action_and_body(&mut payload, &item.doc);
        }
        payload
    }
}

impl<O> Default for BulkBatch<O> {
    fn default() -> Self {
        Self::new()
    }
}

impl<O: OffsetKey> BulkBatch<O> {
    /// Drain skip offsets into a per-partition commit map and reset state.
    pub(crate) fn take_skip_only_commit(&mut self) -> HashMap<i32, O> {
        let mut commit: HashMap<i32, O> = HashMap::new();
        for offset in std::mem::take(&mut self.skip_offsets) {
            insert_max(&mut commit, offset);
        }
        self.bytes_estimate = 0;
        self.flush_age_anchor = None;
        commit
    }

    /// Apply per-item outcomes to the batch state.
    ///
    /// LW(P) = lowest offset of any retryable item on partition P. Resolved
    /// items (success or permanent) on P contribute to the commit map only if
    /// their offset is strictly below LW(P); otherwise they're held back so a
    /// crash before the retryable resolves can't lose data. Retryable items
    /// stay in the batch for the next flush.
    pub(crate) fn process_response(&mut self, outcomes: Vec<ItemOutcome>) -> ProcessResult<O> {
        debug_assert_eq!(
            outcomes.len(),
            self.items.len(),
            "outcomes vector must align 1:1 with items"
        );

        let low_water = compute_low_water(&self.items, &outcomes);

        let drained = std::mem::take(&mut self.items);
        let mut retained: Vec<PendingItem<O>> = Vec::new();
        let mut commit: HashMap<i32, O> = HashMap::new();
        let mut counts = OutcomeCounts::default();

        for (item, outcome) in drained.into_iter().zip(outcomes) {
            match outcome {
                ItemOutcome::Retryable { .. } => {
                    counts.retryable += 1;
                    retained.push(item);
                }
                ItemOutcome::Success => {
                    counts.success += 1;
                    consider_for_commit(&mut commit, &low_water, item.offset);
                }
                ItemOutcome::Permanent {
                    status,
                    error_type,
                    error_reason,
                } => {
                    counts.permanent += 1;
                    warn!(
                        event_uuid = %item.doc.event_uuid,
                        team_id = item.doc.team_id,
                        partition = item.offset.partition(),
                        offset = item.offset.value(),
                        status = status,
                        error_type = error_type.as_deref().unwrap_or(""),
                        error_reason = error_reason.as_deref().unwrap_or(""),
                        "DLQ-bound bulk item"
                    );
                    consider_for_commit(&mut commit, &low_water, item.offset);
                }
            }
        }

        for offset in std::mem::take(&mut self.skip_offsets) {
            consider_for_commit(&mut commit, &low_water, offset);
        }

        self.items = retained;
        self.bytes_estimate = self
            .items
            .iter()
            .map(|i| approx_doc_bytes(&i.doc) + ACTION_LINE_OVERHEAD)
            .sum();
        self.flush_age_anchor = self.items.iter().map(|i| i.doc.parsed_at).min();

        ProcessResult { commit, counts }
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub(crate) struct OutcomeCounts {
    pub success: usize,
    pub permanent: usize,
    pub retryable: usize,
}

pub(crate) struct ProcessResult<O> {
    pub commit: HashMap<i32, O>,
    pub counts: OutcomeCounts,
}

fn compute_low_water<O: OffsetKey>(
    items: &[PendingItem<O>],
    outcomes: &[ItemOutcome],
) -> HashMap<i32, i64> {
    let mut low_water: HashMap<i32, i64> = HashMap::new();
    for (item, outcome) in items.iter().zip(outcomes.iter()) {
        if matches!(outcome, ItemOutcome::Retryable { .. }) {
            let p = item.offset.partition();
            let v = item.offset.value();
            low_water
                .entry(p)
                .and_modify(|cur| {
                    if v < *cur {
                        *cur = v;
                    }
                })
                .or_insert(v);
        }
    }
    low_water
}

fn consider_for_commit<O: OffsetKey>(
    commit: &mut HashMap<i32, O>,
    low_water: &HashMap<i32, i64>,
    offset: O,
) {
    if let Some(lw) = low_water.get(&offset.partition()) {
        if offset.value() >= *lw {
            return;
        }
    }
    insert_max(commit, offset);
}

fn insert_max<O: OffsetKey>(map: &mut HashMap<i32, O>, candidate: O) {
    let key = candidate.partition();
    match map.get(&key) {
        Some(existing) if existing.value() >= candidate.value() => {}
        _ => {
            map.insert(key, candidate);
        }
    }
}

fn approx_doc_bytes(doc: &IndexDoc) -> usize {
    let text_len = doc.input.as_ref().map(String::len).unwrap_or(0)
        + doc.output.as_ref().map(String::len).unwrap_or(0)
        + doc.error.as_ref().map(String::len).unwrap_or(0)
        + doc.tool_names.iter().map(|s| s.len() + 4).sum::<usize>();
    text_len + DOC_OVERHEAD_FUDGE
}

fn serialize_action_and_body(buf: &mut Vec<u8>, doc: &IndexDoc) {
    write_action_line(buf, doc);
    serde_json::to_writer(&mut *buf, doc).expect("IndexDoc Serialize is infallible");
    buf.push(b'\n');
}

fn write_action_line(buf: &mut Vec<u8>, doc: &IndexDoc) {
    buf.extend_from_slice(br#"{"index":{"_id":""#);
    write!(buf, "{}", doc.event_uuid).expect("Vec<u8> write is infallible");
    buf.extend_from_slice(br#""}}"#);
    buf.push(b'\n');
}

/// Retries 5xx and transport errors with `1s → 60s` exponential backoff
/// (uncapped attempt count — channel back-pressure pauses the consumer).
pub struct BulkWriter {
    client: reqwest::Client,
    url: String,
    retry_initial: Duration,
    retry_max: Duration,
}

impl BulkWriter {
    pub fn new(opensearch_url: &str, alias: &str) -> reqwest::Result<Self> {
        let client = reqwest::Client::builder().timeout(REQUEST_TIMEOUT).build()?;
        let url = format!(
            "{}/{}/_bulk",
            opensearch_url.trim_end_matches('/'),
            alias
        );
        Ok(Self {
            client,
            url,
            retry_initial: RETRY_INITIAL,
            retry_max: RETRY_MAX,
        })
    }

    pub async fn flush<O: StoreOffset>(
        &self,
        batch: &mut BulkBatch<O>,
    ) -> Result<FlushStats, FlushError> {
        if batch.is_empty() {
            return Ok(FlushStats::default());
        }
        if batch.is_skip_only() {
            return Ok(self.flush_skip_only(batch));
        }
        self.flush_with_items(batch).await
    }

    fn flush_skip_only<O: StoreOffset>(&self, batch: &mut BulkBatch<O>) -> FlushStats {
        let commit = batch.take_skip_only_commit();
        let (committed_partitions, store_failures) = store_offsets(commit);
        FlushStats {
            committed_partitions,
            store_failures,
            permanent_failures: 0,
            retryable_failures: 0,
        }
    }

    async fn flush_with_items<O: StoreOffset>(
        &self,
        batch: &mut BulkBatch<O>,
    ) -> Result<FlushStats, FlushError> {
        let payload = batch.build_payload();
        let response = self.post_with_retry(Bytes::from(payload)).await?;

        check_item_count(response.items.len(), batch.items.len())?;

        let outcomes: Vec<ItemOutcome> = response
            .items
            .into_iter()
            .map(|item| classify(item.index))
            .collect();

        let result = batch.process_response(outcomes);
        let (committed_partitions, store_failures) = store_offsets(result.commit);

        if result.counts.permanent > 0 || result.counts.retryable > 0 || store_failures > 0 {
            warn!(
                success = result.counts.success,
                permanent = result.counts.permanent,
                retryable = result.counts.retryable,
                store_failures,
                committed_partitions,
                "bulk flush had per-item failures"
            );
        }

        Ok(FlushStats {
            committed_partitions,
            store_failures,
            permanent_failures: result.counts.permanent,
            retryable_failures: result.counts.retryable,
        })
    }

    /// HTTP retry loop, factored out so unit tests can drive it without
    /// constructing real `Offset` values.
    async fn post_with_retry(&self, body: Bytes) -> Result<BulkResponse, FlushError> {
        let mut backoff = self.retry_initial;
        loop {
            match self.try_post(body.clone()).await {
                Ok(resp) => return Ok(resp),
                Err(e) if e.is_retryable() => {
                    warn!(
                        error = %e,
                        backoff_ms = backoff.as_millis() as u64,
                        "bulk POST failed; retrying"
                    );
                    tokio::time::sleep(backoff).await;
                    backoff = (backoff * 2).min(self.retry_max);
                }
                Err(e) => return Err(e),
            }
        }
    }

    async fn try_post(&self, body: Bytes) -> Result<BulkResponse, FlushError> {
        let resp = self
            .client
            .post(&self.url)
            .header("content-type", "application/x-ndjson")
            .body(body)
            .send()
            .await
            .map_err(FlushError::Transport)?;

        let status = resp.status();
        if !status.is_success() {
            return Err(FlushError::HttpStatus(status));
        }

        let bytes = resp.bytes().await.map_err(FlushError::Transport)?;
        serde_json::from_slice(&bytes).map_err(FlushError::Parse)
    }
}

fn check_item_count(received: usize, sent: usize) -> Result<(), FlushError> {
    if received == sent {
        Ok(())
    } else {
        Err(FlushError::ItemCountMismatch { sent, received })
    }
}

fn store_offsets<O: StoreOffset>(commit: HashMap<i32, O>) -> (usize, usize) {
    let mut committed = 0usize;
    let mut failed = 0usize;
    for (_, offset) in commit {
        if offset.store_now() {
            committed += 1;
        } else {
            failed += 1;
        }
    }
    (committed, failed)
}

/// `committed_partitions` is partitions whose offset was advanced this flush.
/// `store_failures` is per-partition `Offset::store()` failures (rare, log-only).
/// `permanent_failures` and `retryable_failures` are per-item.
#[derive(Default, Debug, Clone, Copy, PartialEq, Eq)]
pub struct FlushStats {
    pub committed_partitions: usize,
    pub permanent_failures: usize,
    pub retryable_failures: usize,
    pub store_failures: usize,
}

#[derive(Error, Debug)]
pub enum FlushError {
    #[error("transport: {0}")]
    Transport(reqwest::Error),
    #[error("HTTP {0}")]
    HttpStatus(reqwest::StatusCode),
    #[error("parse: {0}")]
    Parse(serde_json::Error),
    /// OpenSearch returned a different number of items than we sent. Bail
    /// rather than risk mis-aligned classification.
    #[error("bulk response item count mismatch: sent {sent}, received {received}")]
    ItemCountMismatch { sent: usize, received: usize },
}

impl FlushError {
    fn is_retryable(&self) -> bool {
        match self {
            FlushError::Transport(_) => true,
            FlushError::HttpStatus(s) => s.is_server_error(),
            FlushError::Parse(_) | FlushError::ItemCountMismatch { .. } => false,
        }
    }
}

#[derive(Debug, Deserialize)]
struct BulkResponse {
    items: Vec<BulkResponseItem>,
}

/// Each item is `{"index": {...}}`. We only emit `index` actions; if a future
/// change adds `create`/`update`, this required field will fail to deserialize
/// for those rows — `FlushError::Parse` is intentional so the change must be
/// deliberate, not a silent miss in classification.
#[derive(Debug, Deserialize)]
struct BulkResponseItem {
    index: BulkActionResult,
}

#[derive(Debug, Deserialize)]
struct BulkActionResult {
    status: u16,
    #[serde(default)]
    error: Option<BulkError>,
}

#[derive(Debug, Deserialize)]
struct BulkError {
    #[serde(rename = "type")]
    type_: String,
    reason: Option<String>,
}

/// Map a per-item bulk response to a Success / Permanent / Retryable outcome.
/// 4xx defaults to Permanent; 429 + 5xx are Retryable. Named exceptions for
/// cluster pressure (`circuit_breaking_exception`, `es_rejected_execution_exception`)
/// flip 4xx to Retryable since the same payload should land after recovery.
fn classify(result: BulkActionResult) -> ItemOutcome {
    if result.status < 400 {
        return ItemOutcome::Success;
    }
    if result.status == 429 || result.status >= 500 {
        return ItemOutcome::Retryable {
            status: result.status,
        };
    }
    if let Some(err) = &result.error {
        if matches!(
            err.type_.as_str(),
            "circuit_breaking_exception" | "es_rejected_execution_exception"
        ) {
            return ItemOutcome::Retryable {
                status: result.status,
            };
        }
    }
    ItemOutcome::Permanent {
        status: result.status,
        error_type: result.error.as_ref().map(|e| e.type_.clone()),
        error_reason: result.error.and_then(|e| e.reason),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};
    use uuid::Uuid;

    type StoredOffsets = Arc<Mutex<Vec<(i32, i64)>>>;

    fn recorder() -> StoredOffsets {
        Arc::new(Mutex::new(Vec::new()))
    }

    /// Test offset: partition + value + a shared recorder so flush() tests
    /// can assert which offsets were actually committed.
    #[derive(Debug, Clone)]
    struct TestOffset {
        partition: i32,
        value: i64,
        recorder: StoredOffsets,
    }

    impl TestOffset {
        fn new(partition: i32, value: i64, rec: &StoredOffsets) -> Self {
            Self {
                partition,
                value,
                recorder: rec.clone(),
            }
        }
        /// Builds an offset detached from any recorder. Use in tests that
        /// only exercise BulkBatch state, never call store_now.
        fn detached(partition: i32, value: i64) -> Self {
            Self::new(partition, value, &recorder())
        }
    }

    impl OffsetKey for TestOffset {
        fn partition(&self) -> i32 {
            self.partition
        }
        fn value(&self) -> i64 {
            self.value
        }
    }

    impl StoreOffset for TestOffset {
        fn store_now(self) -> bool {
            self.recorder
                .lock()
                .expect("recorder mutex")
                .push((self.partition, self.value));
            true
        }
    }

    fn fixture_doc(uuid_seed: u128) -> IndexDoc {
        IndexDoc {
            timestamp: "2024-01-01T12:00:00.000Z".to_string(),
            trace_id: Some("trace-1".to_string()),
            team_id: 42,
            model: Some("gpt-4".to_string()),
            provider: Some("openai".to_string()),
            tool_names: Vec::new(),
            is_error: false,
            cost: Some(0.001),
            latency_ms: Some(500),
            input: Some("Hello".to_string()),
            output: None,
            error: None,
            event_uuid: Uuid::from_u128(uuid_seed),
            parsed_at: Instant::now(),
        }
    }

    fn push_indexed(b: &mut BulkBatch<TestOffset>, seed: u128, partition: i32, value: i64) {
        b.push_index(fixture_doc(seed), TestOffset::detached(partition, value));
    }

    // ---------- NDJSON serialization ----------

    #[test]
    fn action_line_uses_event_uuid_as_id() {
        let mut buf = Vec::new();
        let doc = fixture_doc(0xdead_beef);
        write_action_line(&mut buf, &doc);
        let s = std::str::from_utf8(&buf).unwrap();
        let expected = format!(r#"{{"index":{{"_id":"{}"}}}}{}"#, doc.event_uuid, "\n");
        assert_eq!(s, expected);
    }

    #[test]
    fn ndjson_payload_has_action_line_and_body_per_doc() {
        let mut buf = Vec::new();
        let docs = [fixture_doc(1), fixture_doc(2)];
        for doc in &docs {
            serialize_action_and_body(&mut buf, doc);
        }
        let s = std::str::from_utf8(&buf).unwrap();
        let lines: Vec<&str> = s.split('\n').filter(|l| !l.is_empty()).collect();
        assert_eq!(lines.len(), 4, "two action+body pairs");

        for (i, doc) in docs.iter().enumerate() {
            let action: serde_json::Value = serde_json::from_str(lines[i * 2]).unwrap();
            assert_eq!(action["index"]["_id"], doc.event_uuid.to_string());
            let body: serde_json::Value = serde_json::from_str(lines[i * 2 + 1]).unwrap();
            assert_eq!(body["@timestamp"], "2024-01-01T12:00:00.000Z");
            assert_eq!(body["team_id"], 42);
            assert!(body.get("event_uuid").is_none());
        }
    }

    #[test]
    fn payload_terminates_with_newline() {
        let mut buf = Vec::new();
        serialize_action_and_body(&mut buf, &fixture_doc(1));
        assert_eq!(buf.last(), Some(&b'\n'));
    }

    // ---------- Response parse ----------

    #[test]
    fn bulk_response_parses_with_and_without_error_field() {
        let body = br#"{
            "took": 3,
            "errors": true,
            "items": [
                {"index": {"status": 201}},
                {"index": {"status": 429, "error": {"type":"circuit_breaking_exception","reason":"limit"}}},
                {"index": {"status": 400, "error": {"type":"mapper_parsing_exception","reason":"bad"}}}
            ]
        }"#;
        let resp: BulkResponse = serde_json::from_slice(body).unwrap();
        assert_eq!(resp.items.len(), 3);
        assert_eq!(resp.items[0].index.status, 201);
        assert!(resp.items[0].index.error.is_none());
        assert_eq!(
            resp.items[1].index.error.as_ref().unwrap().type_,
            "circuit_breaking_exception"
        );
    }

    #[test]
    fn bulk_response_rejects_unknown_action_type() {
        let body = br#"{"took":3,"errors":false,"items":[{"create":{"status":201}}]}"#;
        let result: Result<BulkResponse, _> = serde_json::from_slice(body);
        assert!(result.is_err(), "non-`index` actions must fail to deserialize");
    }

    // ---------- Classifier ----------

    fn make_result(status: u16, error_type: Option<&str>, reason: Option<&str>) -> BulkActionResult {
        BulkActionResult {
            status,
            error: error_type.map(|t| BulkError {
                type_: t.to_string(),
                reason: reason.map(|r| r.to_string()),
            }),
        }
    }

    #[test]
    fn classify_success_under_400() {
        assert_eq!(classify(make_result(200, None, None)), ItemOutcome::Success);
        assert_eq!(classify(make_result(201, None, None)), ItemOutcome::Success);
    }

    #[test]
    fn classify_429_is_retryable() {
        assert_eq!(
            classify(make_result(429, None, None)),
            ItemOutcome::Retryable { status: 429 }
        );
    }

    #[test]
    fn classify_5xx_is_retryable() {
        assert_eq!(
            classify(make_result(503, None, None)),
            ItemOutcome::Retryable { status: 503 }
        );
        assert_eq!(
            classify(make_result(500, None, None)),
            ItemOutcome::Retryable { status: 500 }
        );
    }

    #[test]
    fn classify_400_mapper_is_permanent_with_context() {
        match classify(make_result(400, Some("mapper_parsing_exception"), Some("bad doc"))) {
            ItemOutcome::Permanent {
                status,
                error_type,
                error_reason,
            } => {
                assert_eq!(status, 400);
                assert_eq!(error_type.as_deref(), Some("mapper_parsing_exception"));
                assert_eq!(error_reason.as_deref(), Some("bad doc"));
            }
            other => panic!("expected Permanent, got {other:?}"),
        }
    }

    #[test]
    fn classify_404_is_permanent_without_error_field() {
        match classify(make_result(404, None, None)) {
            ItemOutcome::Permanent {
                status,
                error_type,
                error_reason,
            } => {
                assert_eq!(status, 404);
                assert!(error_type.is_none());
                assert!(error_reason.is_none());
            }
            other => panic!("expected Permanent, got {other:?}"),
        }
    }

    #[test]
    fn classify_4xx_with_pressure_type_is_retryable() {
        assert_eq!(
            classify(make_result(403, Some("circuit_breaking_exception"), None)),
            ItemOutcome::Retryable { status: 403 }
        );
        assert_eq!(
            classify(make_result(409, Some("es_rejected_execution_exception"), None)),
            ItemOutcome::Retryable { status: 409 }
        );
    }

    // ---------- check_item_count helper ----------

    #[test]
    fn check_item_count_ok_when_equal() {
        assert!(check_item_count(5, 5).is_ok());
    }

    #[test]
    fn check_item_count_fails_when_mismatched() {
        match check_item_count(3, 5) {
            Err(FlushError::ItemCountMismatch { sent, received }) => {
                assert_eq!(sent, 5);
                assert_eq!(received, 3);
            }
            other => panic!("expected ItemCountMismatch, got {other:?}"),
        }
    }

    // ---------- BulkBatch state ----------

    #[test]
    fn batch_starts_empty() {
        let b: BulkBatch<TestOffset> = BulkBatch::new();
        assert!(b.is_empty());
        assert!(!b.is_skip_only());
    }

    #[test]
    fn push_index_grows_doc_and_offset_counts() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        b.push_index(fixture_doc(1), TestOffset::detached(0, 1));
        assert_eq!(b.doc_count(), 1);
        assert_eq!(b.offset_count(), 1);
    }

    #[test]
    fn push_skip_only_advances_offsets() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        b.push_skip(TestOffset::detached(0, 1));
        assert_eq!(b.doc_count(), 0);
        assert_eq!(b.offset_count(), 1);
        assert!(b.is_skip_only());
    }

    #[test]
    fn first_indexed_doc_anchors_age() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        let now = Instant::now();
        let mut early = fixture_doc(1);
        early.parsed_at = now.checked_sub(Duration::from_secs(5)).unwrap();
        let mut late = fixture_doc(2);
        late.parsed_at = now;

        b.push_index(early, TestOffset::detached(0, 1));
        b.push_index(late, TestOffset::detached(0, 2));

        assert!(b.should_flush_age(Duration::from_secs(1)));
        assert!(!b.should_flush_age(Duration::from_secs(3600)));
    }

    #[test]
    fn skip_anchors_age_when_first() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        b.push_skip(TestOffset::detached(0, 1));
        assert!(b.should_flush_age(Duration::ZERO));
    }

    #[test]
    fn should_flush_size_at_and_above_threshold() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        let doc = fixture_doc(1);
        let est_per_push = approx_doc_bytes(&doc) + ACTION_LINE_OVERHEAD;
        b.push_index(doc, TestOffset::detached(0, 1));
        assert!(b.should_flush_size(est_per_push));
        assert!(!b.should_flush_size(est_per_push + 1));
    }

    #[test]
    fn approx_doc_bytes_includes_tool_names() {
        let mut bare = fixture_doc(1);
        bare.tool_names = Vec::new();
        let baseline = approx_doc_bytes(&bare);

        let mut with_tools = bare.clone();
        with_tools.tool_names = vec!["get_weather".to_string(), "search_web".to_string()];
        let estimate = approx_doc_bytes(&with_tools);

        assert_eq!(estimate - baseline, "get_weather".len() + 4 + "search_web".len() + 4);
    }

    #[test]
    fn approx_doc_bytes_doesnt_undercount_serialized_size() {
        let cases: Vec<IndexDoc> = vec![
            fixture_doc(1),
            {
                let mut d = fixture_doc(2);
                d.input = Some("a".repeat(2000));
                d.output = Some("b".repeat(1000));
                d.tool_names = vec!["t1".to_string(), "t2".to_string(), "t3".to_string()];
                d
            },
            {
                let mut d = fixture_doc(3);
                d.tool_names = (0..50).map(|i| format!("tool_{i}")).collect();
                d
            },
        ];
        for doc in cases {
            let estimate = approx_doc_bytes(&doc);
            let actual = serde_json::to_vec(&doc).expect("serialize").len();
            assert!(estimate >= actual, "estimate {estimate} < actual {actual}");
        }
    }

    // ---------- take_skip_only_commit ----------

    #[test]
    fn take_skip_only_commit_dedupes_and_keeps_max_per_partition() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        b.push_skip(TestOffset::detached(0, 1));
        b.push_skip(TestOffset::detached(0, 5));
        b.push_skip(TestOffset::detached(0, 3));
        b.push_skip(TestOffset::detached(1, 9));

        let commit = b.take_skip_only_commit();
        assert_eq!(commit.len(), 2);
        assert_eq!(commit.get(&0).unwrap().value(), 5);
        assert_eq!(commit.get(&1).unwrap().value(), 9);
        assert!(b.is_empty(), "batch should be drained after take");
    }

    // ---------- process_response: per-partition reduce + low-water mark ----------

    #[test]
    fn process_response_reduces_to_max_per_partition_when_all_success() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 1);
        push_indexed(&mut b, 2, 0, 3);
        push_indexed(&mut b, 3, 0, 2);
        push_indexed(&mut b, 4, 1, 5);

        let outcomes = vec![ItemOutcome::Success; 4];
        let result = b.process_response(outcomes);

        assert_eq!(result.counts.success, 4);
        assert_eq!(result.commit.len(), 2);
        assert_eq!(result.commit.get(&0).unwrap().value(), 3);
        assert_eq!(result.commit.get(&1).unwrap().value(), 5);
        assert!(b.items.is_empty());
    }

    #[test]
    fn process_response_holds_back_offsets_above_low_water_mark() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 12);
        push_indexed(&mut b, 2, 0, 13);
        push_indexed(&mut b, 3, 0, 14);

        let outcomes = vec![
            ItemOutcome::Success,
            ItemOutcome::Retryable { status: 429 },
            ItemOutcome::Success,
        ];
        let result = b.process_response(outcomes);

        // LW(0)=13 → only offset 12 may commit. 14 succeeded but is held
        // behind the retryable at 13.
        assert_eq!(result.commit.len(), 1);
        assert_eq!(result.commit.get(&0).unwrap().value(), 12);
        assert_eq!(b.items.len(), 1, "retryable retained");
        assert_eq!(b.items[0].offset.value(), 13);
    }

    #[test]
    fn process_response_skips_partition_with_only_retryable() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 12);
        push_indexed(&mut b, 2, 1, 100);

        let outcomes = vec![
            ItemOutcome::Retryable { status: 429 },
            ItemOutcome::Success,
        ];
        let result = b.process_response(outcomes);

        assert!(!result.commit.contains_key(&0));
        assert_eq!(result.commit.get(&1).unwrap().value(), 100);
    }

    #[test]
    fn process_response_permanent_resolves_and_commits_when_below_lw() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 5);
        let outcomes = vec![ItemOutcome::Permanent {
            status: 400,
            error_type: Some("mapper_parsing_exception".to_string()),
            error_reason: Some("bad".to_string()),
        }];
        let result = b.process_response(outcomes);
        assert_eq!(result.counts.permanent, 1);
        assert_eq!(result.commit.get(&0).unwrap().value(), 5);
        assert!(b.items.is_empty());
    }

    #[test]
    fn process_response_permanent_above_lw_is_held_back() {
        // Permanent at offset > LW gets logged-and-resolved (leaves the batch)
        // but its offset is *not* in the commit map. When the retryable below
        // it eventually succeeds, that commit will implicitly cover the gap.
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 12);
        push_indexed(&mut b, 2, 0, 13);
        push_indexed(&mut b, 3, 0, 14);

        let outcomes = vec![
            ItemOutcome::Success,
            ItemOutcome::Retryable { status: 503 },
            ItemOutcome::Permanent {
                status: 400,
                error_type: Some("mapper_parsing_exception".to_string()),
                error_reason: None,
            },
        ];
        let result = b.process_response(outcomes);

        // Both Success at 12 and Permanent at 14 are resolved (left the batch),
        // but only 12 commits because 14 ≥ LW(0)=13.
        assert_eq!(result.commit.len(), 1);
        assert_eq!(result.commit.get(&0).unwrap().value(), 12);
        assert_eq!(result.counts.permanent, 1);
        assert_eq!(b.items.len(), 1);
        assert_eq!(b.items[0].offset.value(), 13);
    }

    #[test]
    fn process_response_skip_above_lw_is_held_back() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 12);
        push_indexed(&mut b, 2, 0, 13);
        b.push_skip(TestOffset::detached(0, 14));

        let outcomes = vec![
            ItemOutcome::Success,
            ItemOutcome::Retryable { status: 429 },
        ];
        let result = b.process_response(outcomes);

        // Skip at 14 sits above LW(0)=13 → not committable.
        assert_eq!(result.commit.get(&0).unwrap().value(), 12);
    }

    #[test]
    fn process_response_skip_below_lw_is_committable() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        b.push_skip(TestOffset::detached(0, 10));
        push_indexed(&mut b, 1, 0, 11);
        push_indexed(&mut b, 2, 0, 12);

        let outcomes = vec![ItemOutcome::Success, ItemOutcome::Retryable { status: 429 }];
        let result = b.process_response(outcomes);

        // LW(0)=12. Skip at 10 and indexed-success at 11 are both < 12 →
        // commit the max, which is 11.
        assert_eq!(result.commit.get(&0).unwrap().value(), 11);
    }

    #[test]
    fn process_response_multi_partition_independent_lw() {
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 12);
        push_indexed(&mut b, 2, 0, 13);
        push_indexed(&mut b, 3, 1, 5);
        push_indexed(&mut b, 4, 1, 6);

        let outcomes = vec![
            ItemOutcome::Success,
            ItemOutcome::Retryable { status: 429 },
            ItemOutcome::Retryable { status: 503 },
            ItemOutcome::Success,
        ];
        let result = b.process_response(outcomes);

        // p0 LW=13 → commit 12. p1 LW=5 → 6 is held back (≥ 5), no commit.
        assert_eq!(result.commit.len(), 1);
        assert_eq!(result.commit.get(&0).unwrap().value(), 12);
        assert!(!result.commit.contains_key(&1));
        assert_eq!(b.items.len(), 2, "both retryables retained");
    }

    #[test]
    fn process_response_two_phase_retain_then_release() {
        // First flush: middle item is retryable, so only the head commits.
        // Second flush: retryable resolves, its offset commits, batch empties.
        let mut b: BulkBatch<TestOffset> = BulkBatch::new();
        push_indexed(&mut b, 1, 0, 12);
        push_indexed(&mut b, 2, 0, 13);
        push_indexed(&mut b, 3, 0, 14);

        let phase1 = vec![
            ItemOutcome::Success,
            ItemOutcome::Retryable { status: 429 },
            ItemOutcome::Success,
        ];
        let r1 = b.process_response(phase1);
        assert_eq!(r1.commit.get(&0).unwrap().value(), 12);
        assert_eq!(b.items.len(), 1);
        assert_eq!(b.items[0].offset.value(), 13);

        // Push a fresh item between flushes; it should join the batch.
        push_indexed(&mut b, 4, 0, 15);
        assert_eq!(b.items.len(), 2);

        // Phase 2: both succeed — offset 15 wins per partition, 13 also resolves.
        let phase2 = vec![ItemOutcome::Success, ItemOutcome::Success];
        let r2 = b.process_response(phase2);
        assert_eq!(r2.counts.success, 2);
        assert_eq!(r2.commit.get(&0).unwrap().value(), 15);
        assert!(b.items.is_empty());
    }

    // ---------- post_with_retry tests (httpmock + tight backoff) ----------

    use httpmock::prelude::*;

    fn writer_for(url: String) -> BulkWriter {
        BulkWriter {
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(2))
                .build()
                .expect("test client"),
            url,
            retry_initial: Duration::from_millis(10),
            retry_max: Duration::from_millis(50),
        }
    }

    #[tokio::test]
    async fn post_with_retry_succeeds_on_first_200() {
        let server = MockServer::start_async().await;
        let mock = server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(200)
                    .header("content-type", "application/json")
                    .body(r#"{"took":1,"errors":false,"items":[{"index":{"status":201}}]}"#);
            })
            .await;

        let writer = writer_for(format!("{}/llm-traces/_bulk", server.base_url()));
        let resp = writer
            .post_with_retry(Bytes::from_static(b""))
            .await
            .expect("expected Ok");
        assert_eq!(resp.items.len(), 1);
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn post_with_retry_recovers_after_5xx() {
        let server = MockServer::start_async().await;
        let fail = server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(503).body("");
            })
            .await;

        let writer = writer_for(format!("{}/llm-traces/_bulk", server.base_url()));
        let post_handle =
            tokio::spawn(async move { writer.post_with_retry(Bytes::from_static(b"")).await });

        for _ in 0..40 {
            if fail.hits_async().await >= 1 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        fail.delete_async().await;
        let _ok = server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(200)
                    .header("content-type", "application/json")
                    .body(r#"{"took":1,"errors":false,"items":[{"index":{"status":201}}]}"#);
            })
            .await;

        let resp = post_handle.await.expect("task joined").expect("Ok after retry");
        assert_eq!(resp.items.len(), 1);
    }

    #[tokio::test]
    async fn post_with_retry_bails_on_4xx() {
        let server = MockServer::start_async().await;
        let mock = server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(400).body("bad request");
            })
            .await;

        let writer = writer_for(format!("{}/llm-traces/_bulk", server.base_url()));
        let result = writer.post_with_retry(Bytes::from_static(b"")).await;
        match result {
            Err(FlushError::HttpStatus(s)) => assert_eq!(s.as_u16(), 400),
            other => panic!("expected HttpStatus(400), got {other:?}"),
        }
        assert_eq!(mock.hits_async().await, 1);
    }

    #[test]
    fn flush_error_classifies_retryable() {
        assert!(FlushError::HttpStatus(reqwest::StatusCode::INTERNAL_SERVER_ERROR).is_retryable());
        assert!(FlushError::HttpStatus(reqwest::StatusCode::SERVICE_UNAVAILABLE).is_retryable());
        assert!(!FlushError::HttpStatus(reqwest::StatusCode::BAD_REQUEST).is_retryable());
        assert!(!FlushError::HttpStatus(reqwest::StatusCode::NOT_FOUND).is_retryable());
        assert!(!FlushError::Parse(serde_json::from_str::<u8>("xx").unwrap_err()).is_retryable());
        assert!(!FlushError::ItemCountMismatch { sent: 1, received: 0 }.is_retryable());
    }

    // ---------- BulkWriter::flush end-to-end with TestOffset ----------

    #[tokio::test]
    async fn flush_skip_only_bypasses_post_and_commits_skips() {
        let server = MockServer::start_async().await;
        let _mock_unused = server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(500).body(""); // would fail if we accidentally POST
            })
            .await;

        let rec = recorder();
        let mut batch: BulkBatch<TestOffset> = BulkBatch::new();
        batch.push_skip(TestOffset::new(0, 5, &rec));
        batch.push_skip(TestOffset::new(1, 9, &rec));

        let writer = writer_for(format!("{}/llm-traces/_bulk", server.base_url()));
        let stats = writer.flush(&mut batch).await.expect("Ok");

        assert_eq!(stats.committed_partitions, 2);
        assert_eq!(stats.permanent_failures, 0);
        assert_eq!(stats.retryable_failures, 0);
        assert_eq!(stats.store_failures, 0);

        let stored = rec.lock().unwrap().clone();
        assert_eq!(stored.len(), 2);
        assert!(stored.contains(&(0, 5)));
        assert!(stored.contains(&(1, 9)));
        assert!(batch.is_empty());
    }

    #[tokio::test]
    async fn flush_with_items_commits_success_and_propagates_per_item_failure_kinds() {
        let server = MockServer::start_async().await;
        server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(200)
                    .header("content-type", "application/json")
                    .body(
                        r#"{"took":1,"errors":true,"items":[
                            {"index":{"status":201}},
                            {"index":{"status":429,"error":{"type":"circuit_breaking_exception","reason":"pressure"}}},
                            {"index":{"status":400,"error":{"type":"mapper_parsing_exception","reason":"bad cost"}}}
                        ]}"#,
                    );
            })
            .await;

        let rec = recorder();
        let mut batch: BulkBatch<TestOffset> = BulkBatch::new();
        batch.push_index(fixture_doc(1), TestOffset::new(0, 12, &rec));
        batch.push_index(fixture_doc(2), TestOffset::new(0, 13, &rec));
        batch.push_index(fixture_doc(3), TestOffset::new(0, 14, &rec));

        let writer = writer_for(format!("{}/llm-traces/_bulk", server.base_url()));
        let stats = writer.flush(&mut batch).await.expect("Ok");

        // Permanent at 14 is held back behind retryable at 13 → no commit on
        // partition 0 from the success at 12 either? Let's reason:
        //  - LW(0)=13 (only retryable). Resolved offsets < LW: {12 (success)}.
        //  - 14 is Permanent and resolved (left batch, logged as DLQ-bound)
        //    but ≥ LW so doesn't commit.
        // So commit = {0:12}.
        assert_eq!(stats.committed_partitions, 1);
        assert_eq!(stats.permanent_failures, 1);
        assert_eq!(stats.retryable_failures, 1);
        assert_eq!(stats.store_failures, 0);

        let stored = rec.lock().unwrap().clone();
        assert_eq!(stored, vec![(0, 12)]);
        assert_eq!(batch.items.len(), 1, "retryable retained");
    }

    #[tokio::test]
    async fn flush_returns_item_count_mismatch_on_short_response() {
        let server = MockServer::start_async().await;
        server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(200)
                    .header("content-type", "application/json")
                    .body(r#"{"took":1,"errors":false,"items":[{"index":{"status":201}}]}"#);
            })
            .await;

        let rec = recorder();
        let mut batch: BulkBatch<TestOffset> = BulkBatch::new();
        batch.push_index(fixture_doc(1), TestOffset::new(0, 1, &rec));
        batch.push_index(fixture_doc(2), TestOffset::new(0, 2, &rec));

        let writer = writer_for(format!("{}/llm-traces/_bulk", server.base_url()));
        match writer.flush(&mut batch).await {
            Err(FlushError::ItemCountMismatch { sent, received }) => {
                assert_eq!(sent, 2);
                assert_eq!(received, 1);
            }
            other => panic!("expected ItemCountMismatch, got {other:?}"),
        }

        // Batch state is intact — items must remain so a follow-up flush can
        // try again. Offsets must NOT have been stored.
        assert_eq!(batch.items.len(), 2);
        assert!(rec.lock().unwrap().is_empty());
    }
}
