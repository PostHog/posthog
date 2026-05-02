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

/// Constant fudge added by `approx_doc_bytes` to cover the JSON scaffolding
/// (keys, separators) for the small metadata fields we don't enumerate.
/// Sized to keep the estimate from undercounting realistic event shapes.
const DOC_OVERHEAD_FUDGE: usize = 256;

/// Accumulator for a single `_bulk` request. Holds the index docs that produce
/// NDJSON plus *all* offsets that should commit when the batch is ack'd —
/// including offsets from skipped non-`$ai_*` events that the consumer forwards
/// through the channel for ordering. A Skip at offset N+1 must wait for any
/// in-flight Index at N to be ack'd, otherwise a crash mid-flush would advance
/// the partition past unwritten data.
///
/// Generic over the offset type so unit tests can exercise state transitions
/// with `BulkBatch<()>` (real `Offset` is non-constructible outside the
/// `common_kafka` crate). Production code uses the default `BulkBatch<Offset>`.
#[derive(Debug)]
pub struct BulkBatch<O = Offset> {
    docs: Vec<IndexDoc>,
    offsets: Vec<O>,
    /// Cheap running estimate of the eventual NDJSON payload size. Avoids
    /// re-serializing on every push.
    bytes_estimate: usize,
    /// Anchor for the age-based flush trigger: earliest of (first indexed doc's
    /// `parsed_at`, wall-clock time of first skip). The field name reflects
    /// that skip-only batches anchor to wall-clock, not to any event time.
    flush_age_anchor: Option<Instant>,
}

impl<O> BulkBatch<O> {
    pub fn new() -> Self {
        Self {
            docs: Vec::new(),
            offsets: Vec::new(),
            bytes_estimate: 0,
            flush_age_anchor: None,
        }
    }

    pub fn doc_count(&self) -> usize {
        self.docs.len()
    }

    pub fn offset_count(&self) -> usize {
        self.offsets.len()
    }

    pub fn is_empty(&self) -> bool {
        self.offsets.is_empty()
    }

    /// Push an `$ai_*` event: contributes both an NDJSON action+body line and
    /// an offset to commit on ack.
    pub fn push_index(&mut self, doc: IndexDoc, offset: O) {
        if self.flush_age_anchor.is_none() {
            self.flush_age_anchor = Some(doc.parsed_at);
        }
        // Coarse — we'd rather over-estimate than re-serialize per push.
        self.bytes_estimate += approx_doc_bytes(&doc) + ACTION_LINE_OVERHEAD;
        self.docs.push(doc);
        self.offsets.push(offset);
    }

    /// Push a non-`$ai_*` skip: contributes only an offset, riding the next
    /// flush so it commits in receive order.
    pub fn push_skip(&mut self, offset: O) {
        if self.flush_age_anchor.is_none() {
            self.flush_age_anchor = Some(Instant::now());
        }
        self.offsets.push(offset);
    }

    pub fn should_flush_size(&self, max_bytes: usize) -> bool {
        self.bytes_estimate >= max_bytes
    }

    pub fn should_flush_age(&self, max_age: Duration) -> bool {
        self.flush_age_anchor
            .map(|t| t.elapsed() >= max_age)
            .unwrap_or(false)
    }

    /// Drain into NDJSON bytes plus the offsets to commit after ack. An empty
    /// payload signals a skip-only batch — caller should bypass the POST and
    /// commit the offsets directly.
    pub fn drain_payload(&mut self) -> (Vec<u8>, Vec<O>) {
        let docs = std::mem::take(&mut self.docs);
        let offsets = std::mem::take(&mut self.offsets);
        self.bytes_estimate = 0;
        self.flush_age_anchor = None;

        let mut payload = Vec::with_capacity(docs.len() * 256);
        for doc in &docs {
            serialize_action_and_body(&mut payload, doc);
        }
        (payload, offsets)
    }
}

impl<O> Default for BulkBatch<O> {
    fn default() -> Self {
        Self::new()
    }
}

fn approx_doc_bytes(doc: &IndexDoc) -> usize {
    // Heaviest fields dominate. tool_names can be substantial for agent traces;
    // the +DOC_OVERHEAD_FUDGE covers timestamp/ids/model/provider/numeric
    // fields plus JSON scaffolding (keys, commas, braces).
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

/// HTTP `_bulk` writer. Retries 5xx and transport errors with `1s → 60s`
/// exponential backoff (uncapped attempt count — channel back-pressure pauses
/// the consumer). Per-item failures inside a 200 response are logged and
/// committed; per-item retry/DLQ classification is handled by the caller.
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

    /// Drains `batch`, POSTs `_bulk`, retries transient errors infinitely, and
    /// stores offsets after a 2xx ack. Returns `Ok` for both `errors:false`
    /// and `errors:true` — per-item failures are surfaced via `FlushStats` for
    /// the caller to classify.
    pub async fn flush(&self, batch: &mut BulkBatch) -> Result<FlushStats, FlushError> {
        if batch.is_empty() {
            return Ok(FlushStats::default());
        }
        let (payload, offsets) = batch.drain_payload();
        let offset_count = offsets.len();

        let failures = if payload.is_empty() {
            // Skip-only batch — no docs to write; just advance the partitions.
            0
        } else {
            let response = self.post_with_retry(Bytes::from(payload)).await?;
            let failures = response.failure_count();
            if response.errors {
                warn!(
                    failures,
                    total = offset_count,
                    "bulk response had per-item errors; committing anyway"
                );
            }
            failures
        };

        for off in offsets {
            if let Err(e) = off.store() {
                error!(error = %e, "Failed to store offset after bulk ack");
            }
        }

        Ok(FlushStats {
            committed: offset_count,
            failures,
        })
    }

    /// HTTP retry loop, factored out so unit tests can drive it without
    /// constructing real `Offset` values (those are only obtainable from
    /// `common_kafka::SingleTopicConsumer`).
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

#[derive(Default, Debug)]
pub struct FlushStats {
    pub committed: usize,
    pub failures: usize,
}

#[derive(Error, Debug)]
pub enum FlushError {
    #[error("transport: {0}")]
    Transport(reqwest::Error),
    /// Any non-2xx HTTP response. Retryability is decided by `is_retryable()`
    /// based on the status code class (5xx → retry, 4xx → bail).
    #[error("HTTP {0}")]
    HttpStatus(reqwest::StatusCode),
    #[error("parse: {0}")]
    Parse(serde_json::Error),
}

impl FlushError {
    fn is_retryable(&self) -> bool {
        match self {
            FlushError::Transport(_) => true,
            FlushError::HttpStatus(s) => s.is_server_error(),
            FlushError::Parse(_) => false,
        }
    }
}

#[derive(Debug, Deserialize)]
struct BulkResponse {
    errors: bool,
    items: Vec<BulkResponseItem>,
}

/// Each item is `{"index": {...}}`. We only emit `index` actions; if a future
/// change adds `create`/`update` actions, this required field will fail to
/// deserialize for those rows — `FlushError::Parse` is intentional so the
/// change must be deliberate, not a silent miss in `failure_count()`.
#[derive(Debug, Deserialize)]
struct BulkResponseItem {
    index: BulkActionResult,
}

#[derive(Debug, Deserialize)]
struct BulkActionResult {
    status: u16,
}

impl BulkResponse {
    fn failure_count(&self) -> usize {
        self.items.iter().filter(|i| i.index.status >= 400).count()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;
    use uuid::Uuid;

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
            assert!(
                body.get("event_uuid").is_none(),
                "event_uuid is the bulk action _id, not body"
            );
        }
    }

    #[test]
    fn payload_terminates_with_newline() {
        // OpenSearch _bulk requires a trailing newline; without it the last action
        // is silently ignored. Lock it in.
        let mut buf = Vec::new();
        serialize_action_and_body(&mut buf, &fixture_doc(1));
        assert_eq!(buf.last(), Some(&b'\n'));
    }

    #[test]
    fn bulk_response_no_errors() {
        let body = br#"{"took":3,"errors":false,"items":[{"index":{"status":201}}]}"#;
        let resp: BulkResponse = serde_json::from_slice(body).unwrap();
        assert!(!resp.errors);
        assert_eq!(resp.failure_count(), 0);
    }

    #[test]
    fn bulk_response_counts_per_item_failures() {
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
        assert!(resp.errors);
        assert_eq!(resp.failure_count(), 2);
    }

    #[test]
    fn bulk_response_rejects_unknown_action_type() {
        // If a future change emits `create` actions, the response shape changes
        // and BulkResponseItem must be updated deliberately rather than silently
        // missing the new action type.
        let body = br#"{"took":3,"errors":false,"items":[{"create":{"status":201}}]}"#;
        let result: Result<BulkResponse, _> = serde_json::from_slice(body);
        assert!(
            result.is_err(),
            "non-`index` actions must fail to deserialize"
        );
    }

    #[test]
    fn flush_error_classifies_retryable() {
        assert!(FlushError::Transport(reqwest_transport_error()).is_retryable());
        assert!(FlushError::HttpStatus(reqwest::StatusCode::INTERNAL_SERVER_ERROR).is_retryable());
        assert!(FlushError::HttpStatus(reqwest::StatusCode::SERVICE_UNAVAILABLE).is_retryable());
        assert!(!FlushError::HttpStatus(reqwest::StatusCode::BAD_REQUEST).is_retryable());
        assert!(!FlushError::HttpStatus(reqwest::StatusCode::NOT_FOUND).is_retryable());
        assert!(!FlushError::Parse(serde_json::from_str::<u8>("xx").unwrap_err()).is_retryable());
    }

    fn reqwest_transport_error() -> reqwest::Error {
        // Easiest way to get a `reqwest::Error` without making a real request.
        let bad_url = reqwest::Url::parse("http://localhost:1").unwrap();
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        rt.block_on(async {
            reqwest::Client::builder()
                .timeout(Duration::from_millis(1))
                .build()
                .unwrap()
                .get(bad_url)
                .send()
                .await
                .expect_err("expected connection failure")
        })
    }

    #[test]
    fn approx_doc_bytes_includes_tool_names() {
        let mut bare = fixture_doc(1);
        bare.tool_names = Vec::new();
        let baseline = approx_doc_bytes(&bare);

        let mut with_tools = bare.clone();
        with_tools.tool_names = vec!["get_weather".to_string(), "search_web".to_string()];
        let estimate = approx_doc_bytes(&with_tools);

        // Each tool name contributes len + 4 (quotes + comma).
        assert_eq!(estimate - baseline, "get_weather".len() + 4 + "search_web".len() + 4);
    }

    #[test]
    fn approx_doc_bytes_doesnt_undercount_serialized_size() {
        // Estimate must >= the actual serialized body length for the size-flush
        // trigger to honor its byte cap. Over-estimation is fine.
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
            assert!(
                estimate >= actual,
                "estimate ({estimate}) must not undercount actual serialized size ({actual})"
            );
        }
    }

    // ---------- BulkBatch state tests (use BulkBatch<()>) ----------

    #[test]
    fn batch_starts_empty() {
        let b: BulkBatch<()> = BulkBatch::new();
        assert!(b.is_empty());
        assert_eq!(b.doc_count(), 0);
        assert_eq!(b.offset_count(), 0);
        assert!(!b.should_flush_size(1));
        assert!(!b.should_flush_age(Duration::ZERO));
    }

    #[test]
    fn push_index_grows_doc_and_offset_counts() {
        let mut b: BulkBatch<()> = BulkBatch::new();
        b.push_index(fixture_doc(1), ());
        assert_eq!(b.doc_count(), 1);
        assert_eq!(b.offset_count(), 1);
        assert!(!b.is_empty());
    }

    #[test]
    fn push_skip_only_advances_offsets() {
        let mut b: BulkBatch<()> = BulkBatch::new();
        b.push_skip(());
        assert_eq!(b.doc_count(), 0);
        assert_eq!(b.offset_count(), 1);
        assert!(!b.is_empty());
    }

    #[test]
    fn first_indexed_doc_anchors_age_subsequent_pushes_dont_reset() {
        let mut b: BulkBatch<()> = BulkBatch::new();
        let now = Instant::now();
        let mut early = fixture_doc(1);
        early.parsed_at = now.checked_sub(Duration::from_secs(5)).unwrap();
        let mut late = fixture_doc(2);
        late.parsed_at = now;

        b.push_index(early, ());
        b.push_index(late, ());

        // Anchor stayed on the first push (~5s old). 1s threshold should fire,
        // 1h threshold should not.
        assert!(b.should_flush_age(Duration::from_secs(1)));
        assert!(!b.should_flush_age(Duration::from_secs(3600)));
    }

    #[test]
    fn skip_anchors_age_when_first() {
        let mut b: BulkBatch<()> = BulkBatch::new();
        b.push_skip(());
        // Anchor is now (set inside push_skip). Threshold of 0 fires.
        assert!(b.should_flush_age(Duration::ZERO));
        // 1h threshold doesn't.
        assert!(!b.should_flush_age(Duration::from_secs(3600)));
    }

    #[test]
    fn drain_payload_resets_state() {
        let mut b: BulkBatch<()> = BulkBatch::new();
        b.push_index(fixture_doc(1), ());
        b.push_skip(());

        let (payload, offsets) = b.drain_payload();
        assert!(!payload.is_empty(), "should serialize the indexed doc");
        assert_eq!(offsets.len(), 2);

        // State fully reset — ready for the next batch cycle.
        assert!(b.is_empty());
        assert_eq!(b.doc_count(), 0);
        assert_eq!(b.offset_count(), 0);
        assert!(!b.should_flush_size(1));
        assert!(!b.should_flush_age(Duration::ZERO));
    }

    #[test]
    fn drain_skip_only_yields_empty_payload() {
        // The skip-only branch in flush() relies on this: empty payload → no POST.
        let mut b: BulkBatch<()> = BulkBatch::new();
        b.push_skip(());
        b.push_skip(());
        let (payload, offsets) = b.drain_payload();
        assert!(payload.is_empty(), "skip-only batches have empty payload");
        assert_eq!(offsets.len(), 2);
    }

    #[test]
    fn should_flush_size_at_and_above_threshold() {
        let mut b: BulkBatch<()> = BulkBatch::new();
        let doc = fixture_doc(1);
        let est_per_push = approx_doc_bytes(&doc) + ACTION_LINE_OVERHEAD;
        b.push_index(doc, ());
        assert!(b.should_flush_size(est_per_push), "exactly at threshold");
        assert!(
            !b.should_flush_size(est_per_push + 1),
            "below threshold"
        );
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
        assert!(!resp.errors);
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn post_with_retry_recovers_after_5xx() {
        let server = MockServer::start_async().await;
        // Phase 1: respond 503. After observing at least one failed attempt,
        // swap to 200 so the retry loop is exercised end-to-end.
        let fail = server
            .mock_async(|when, then| {
                when.method(POST).path("/llm-traces/_bulk");
                then.status(503).body("");
            })
            .await;

        let writer = writer_for(format!("{}/llm-traces/_bulk", server.base_url()));
        let post_handle = tokio::spawn(async move {
            writer.post_with_retry(Bytes::from_static(b"")).await
        });

        // Wait for at least one attempt to land, then swap the mock.
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

        let resp = post_handle
            .await
            .expect("task joined")
            .expect("expected Ok after retry");
        assert!(!resp.errors);
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
        // Should hit exactly once (no retries on 4xx).
        assert_eq!(mock.hits_async().await, 1);
    }
}
