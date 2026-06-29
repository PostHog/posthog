use std::{
    sync::Mutex,
    time::{Duration, Instant},
};

use anyhow::Error;
use async_trait::async_trait;
use common_types::{InternallyCapturedEvent, RawEvent};
use metrics::counter;
use posthog_rs::{Client, Event};
use tracing::{info, warn};

use super::{Emitter, Transaction};

pub struct CaptureEmitter {
    client: Client,
    send_rate: u64,
}

pub struct CaptureTransaction<'a> {
    client: &'a Client,
    send_rate: u64,
    start: Instant,
    events: Mutex<Vec<Event>>,
}

impl CaptureEmitter {
    pub fn new(client: Client, send_rate: u64) -> Self {
        Self { client, send_rate }
    }
}

#[async_trait]
impl Emitter for CaptureEmitter {
    async fn begin_write<'a>(&'a mut self) -> Result<Box<dyn Transaction<'a> + 'a>, Error> {
        Ok(Box::new(CaptureTransaction {
            client: &self.client,
            send_rate: self.send_rate,
            start: Instant::now(),
            events: Mutex::new(Vec::new()),
        }))
    }
}

fn convert_event(ice: &InternallyCapturedEvent) -> Result<Event, Error> {
    let raw: RawEvent = serde_json::from_str(&ice.inner.data)?;

    let mut event = Event::new(&ice.inner.event, &ice.inner.distinct_id);

    event.set_uuid(ice.inner.uuid);
    event
        .set_timestamp(ice.inner.timestamp)
        .map_err(|e| Error::msg(e.to_string()))?;

    for (key, value) in &raw.properties {
        event
            .insert_prop(key, value)
            .map_err(|e| Error::msg(e.to_string()))?;
    }

    if let Some(set) = &raw.set {
        event
            .insert_prop("$set", set)
            .map_err(|e| Error::msg(e.to_string()))?;
    }

    if let Some(set_once) = &raw.set_once {
        event
            .insert_prop("$set_once", set_once)
            .map_err(|e| Error::msg(e.to_string()))?;
    }

    event
        .insert_prop("$geoip_disable", true)
        .map_err(|e| Error::msg(e.to_string()))?;

    Ok(event)
}

#[async_trait]
impl<'a> Transaction<'a> for CaptureTransaction<'a> {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        let converted: Vec<Event> = data.iter().map(convert_event).collect::<Result<_, _>>()?;

        self.events
            .lock()
            .map_err(|e| Error::msg(format!("events lock poisoned: {e}")))?
            .extend(converted);

        Ok(())
    }

    async fn commit_write(self: Box<Self>) -> Result<Duration, Error> {
        let events = self
            .events
            .into_inner()
            .map_err(|e| Error::msg(format!("events lock poisoned: {e}")))?;
        let count = events.len();

        if count == 0 {
            info!("skipping capture send for empty event batch");
            return Ok(Duration::ZERO);
        }

        let min_duration = get_min_txn_duration(self.send_rate, count);
        let txn_elapsed = self.start.elapsed();
        let to_sleep = min_duration.saturating_sub(txn_elapsed);

        // Split oversized chunks across multiple requests so we stay under capture's
        // 10 MiB body limit. Re-sending a chunk on retry is already safe (events carry
        // stable UUIDs and route through historical migration, which dedupes), so a
        // partial failure here just re-sends the whole chunk and downstream dedupes the
        // overlap.
        let batches = split_into_byte_limited_batches(events)?;

        info!(
            count,
            batches = batches.len(),
            ?txn_elapsed,
            ?min_duration,
            ?to_sleep,
            "sending events to capture"
        );

        for batch in batches {
            let batch_count = batch.len();
            if let Err(e) = self.client.capture_batch(batch, true).await {
                counter!("capture_batch_events_total", "outcome" => "failure")
                    .increment(batch_count as u64);
                return Err(Error::msg(format!("capture batch failed: {e}")));
            }
        }

        // Count success once per fully-committed chunk. A mid-chunk failure rolls the offset
        // back and re-sends the whole chunk on retry, so counting per sub-batch would inflate
        // the success total across retries.
        counter!("capture_batch_events_total", "outcome" => "success").increment(count as u64);

        info!(count, "successfully sent batch to capture");
        Ok(to_sleep)
    }
}

fn get_min_txn_duration(send_rate: u64, count: usize) -> Duration {
    let max_send_rate = send_rate as f64;
    let batch_size = count as f64;
    Duration::from_secs_f64(batch_size / max_send_rate)
}

/// Capture's `/batch/` endpoint rejects any request body larger than 10 MiB with
/// `payload_too_large`. We pack events into sub-batches that stay under this budget so a
/// chunk whose serialized events exceed the limit is split across several requests
/// instead of wedging the import. The headroom below 10 MiB absorbs the batch envelope
/// and the per-event `api_key` / `$lib*` fields capture injects into each event.
const MAX_BATCH_PAYLOAD_BYTES: usize = 9 * 1024 * 1024;

/// Overhead capture adds per event beyond its own JSON (injected `api_key`, `$lib*`
/// properties and separators). Counted toward every event so a flood of tiny events
/// can't accumulate past the wire limit.
const PER_EVENT_OVERHEAD_BYTES: usize = 256;

/// Greedily pack events into batches whose estimated serialized size stays under
/// [`MAX_BATCH_PAYLOAD_BYTES`], preserving order. A single event larger than the budget
/// gets its own batch — best effort, since capture may still reject it, but that is a
/// genuinely oversized event rather than an aggregation problem.
fn split_into_byte_limited_batches(events: Vec<Event>) -> Result<Vec<Vec<Event>>, Error> {
    let mut batches: Vec<Vec<Event>> = Vec::new();
    let mut current: Vec<Event> = Vec::new();
    let mut current_bytes: usize = 0;

    for event in events {
        let event_bytes = serialized_len(&event)?.saturating_add(PER_EVENT_OVERHEAD_BYTES);

        if !current.is_empty()
            && current_bytes.saturating_add(event_bytes) > MAX_BATCH_PAYLOAD_BYTES
        {
            batches.push(std::mem::take(&mut current));
            current_bytes = 0;
        }

        if event_bytes > MAX_BATCH_PAYLOAD_BYTES {
            warn!(
                event_bytes,
                limit = MAX_BATCH_PAYLOAD_BYTES,
                "single event exceeds capture batch size limit; sending it in its own request"
            );
        }

        current.push(event);
        current_bytes = current_bytes.saturating_add(event_bytes);
    }

    if !current.is_empty() {
        batches.push(current);
    }

    Ok(batches)
}

/// Serialized JSON byte length of `event`, measured without retaining the bytes:
/// `serde_json::to_writer` into a counting sink, so sizing a multi-MB event doesn't
/// allocate a multi-MB buffer just to read its length.
fn serialized_len(event: &Event) -> Result<usize, Error> {
    let mut counter = ByteCountWriter(0);
    serde_json::to_writer(&mut counter, event)
        .map_err(|e| Error::msg(format!("failed to size event for batching: {e}")))?;
    Ok(counter.0)
}

struct ByteCountWriter(usize);

impl std::io::Write for ByteCountWriter {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0 += buf.len();
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{DateTime, Utc};
    use common_types::CapturedEvent;
    use uuid::Uuid;

    fn make_internally_captured_event(
        event_name: &str,
        distinct_id: &str,
        properties: serde_json::Value,
        set: Option<serde_json::Value>,
        set_once: Option<serde_json::Value>,
    ) -> InternallyCapturedEvent {
        let mut raw = serde_json::json!({
            "event": event_name,
            "properties": properties,
        });
        if let Some(s) = set {
            raw["$set"] = s;
        }
        if let Some(s) = set_once {
            raw["$set_once"] = s;
        }

        InternallyCapturedEvent {
            inner: CapturedEvent {
                uuid: Uuid::now_v7(),
                distinct_id: distinct_id.to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: serde_json::to_string(&raw).unwrap(),
                now: "2023-10-15T14:30:00+00:00".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                event: event_name.to_string(),
                timestamp: DateTime::parse_from_rfc3339("2023-10-15T14:30:00+00:00")
                    .unwrap()
                    .with_timezone(&Utc),
                is_cookieless_mode: false,
                historical_migration: true,
            },
            team_id: 1,
        }
    }

    /// V1 capture returns a JSON body with per-event results. An empty results
    /// map means all events are silently accepted (dropped from retry tracking).
    const V1_OK_BODY: &str = r#"{"results":{}}"#;

    #[test]
    fn test_convert_event_basic_properties() {
        let ice = make_internally_captured_event(
            "test_event",
            "user123",
            serde_json::json!({"color": "red", "count": 42}),
            None,
            None,
        );

        let event = convert_event(&ice).unwrap();
        let json = serde_json::to_value(&event).unwrap();

        assert_eq!(json["event"], "test_event");
        assert_eq!(json["distinct_id"], "user123");
        assert_eq!(json["properties"]["color"], "red");
        assert_eq!(json["properties"]["count"], 42);
        assert_eq!(json["properties"]["$geoip_disable"], true);
    }

    #[test]
    fn test_convert_event_with_set_and_set_once() {
        let ice = make_internally_captured_event(
            "$identify",
            "user456",
            serde_json::json!({}),
            Some(serde_json::json!({"email": "test@example.com"})),
            Some(serde_json::json!({"created_at": "2023-01-01"})),
        );

        let event = convert_event(&ice).unwrap();
        let json = serde_json::to_value(&event).unwrap();

        assert_eq!(json["properties"]["$set"]["email"], "test@example.com");
        assert_eq!(json["properties"]["$set_once"]["created_at"], "2023-01-01");
    }

    #[test]
    fn test_convert_event_always_disables_geoip() {
        let ice = make_internally_captured_event(
            "pageview",
            "user789",
            serde_json::json!({}),
            None,
            None,
        );

        let event = convert_event(&ice).unwrap();
        let json = serde_json::to_value(&event).unwrap();

        assert_eq!(json["properties"]["$geoip_disable"], true);
    }

    #[test]
    fn test_get_min_txn_duration() {
        assert_eq!(get_min_txn_duration(1000, 500), Duration::from_millis(500));
        assert_eq!(get_min_txn_duration(1000, 1000), Duration::from_secs(1));
        assert_eq!(get_min_txn_duration(500, 1000), Duration::from_secs(2));
    }

    async fn make_client(base_url: &str) -> Client {
        let options = posthog_rs::ClientOptionsBuilder::default()
            .api_key("test_api_key".to_string())
            .host(base_url)
            .max_capture_attempts(1u32)
            .build()
            .unwrap();
        posthog_rs::client(options).await
    }

    async fn make_client_with_retries(base_url: &str, attempts: u32) -> Client {
        let options = posthog_rs::ClientOptionsBuilder::default()
            .api_key("test_api_key".to_string())
            .host(base_url)
            .max_capture_attempts(attempts)
            .retry_initial_backoff_ms(1u64)
            .retry_max_backoff_ms(1u64)
            .build()
            .unwrap();
        posthog_rs::client(options).await
    }

    fn make_transaction(client: &Client) -> Box<CaptureTransaction<'_>> {
        let mut event = Event::new("test", "user1");
        event.insert_prop("key", "value").unwrap();

        Box::new(CaptureTransaction {
            client,
            send_rate: 10_000,
            start: Instant::now(),
            events: Mutex::new(vec![event]),
        })
    }

    #[tokio::test]
    async fn test_batch_payload_preserves_uuid_and_lib_properties() {
        let expected_uuid = Uuid::parse_str("019c7d2c-5f84-7000-dd7f-9295cfe7993f").unwrap();
        let mut ice = make_internally_captured_event(
            "test_event",
            "user123",
            serde_json::json!({
                "$lib": "posthog-python",
                "$lib_version": "3.0.0",
                "custom_prop": "hello"
            }),
            None,
            None,
        );
        ice.inner.uuid = expected_uuid;

        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/i/v1/analytics/events")
            .match_body(mockito::Matcher::PartialJson(serde_json::json!({
                "batch": [{
                    "uuid": expected_uuid.to_string(),
                    "event": "test_event",
                    "distinct_id": "user123",
                    "properties": {
                        "$lib": "posthog-python",
                        "$lib_version": "3.0.0",
                        "custom_prop": "hello",
                        "$geoip_disable": true
                    }
                }]
            })))
            .with_status(200)
            .with_body(V1_OK_BODY)
            .expect(1)
            .create();

        let client = make_client(&server.url()).await;
        let mut emitter = CaptureEmitter::new(client, 10_000);
        let txn = emitter.begin_write().await.unwrap();
        txn.emit(&[ice]).await.unwrap();
        txn.commit_write().await.unwrap();

        mock.assert();
    }

    #[tokio::test]
    async fn test_commit_write_skips_http_on_empty_batch() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/i/v1/analytics/events")
            .expect(0)
            .create();

        let client = make_client(&server.url()).await;
        let txn = Box::new(CaptureTransaction {
            client: &client,
            send_rate: 10_000,
            start: Instant::now(),
            events: Mutex::new(vec![]),
        });

        let result = txn.commit_write().await;
        assert!(
            result.is_ok(),
            "expected Ok for empty batch, got {result:?}"
        );
        assert_eq!(
            result.unwrap(),
            Duration::ZERO,
            "empty batch should return zero sleep"
        );
        mock.assert();
    }

    #[tokio::test]
    async fn test_commit_write_succeeds_on_first_try() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/i/v1/analytics/events")
            .with_status(200)
            .with_body(V1_OK_BODY)
            .expect(1)
            .create();

        let client = make_client(&server.url()).await;
        let txn = make_transaction(&client);

        let result = txn.commit_write().await;
        assert!(result.is_ok());
        mock.assert();
    }

    #[tokio::test]
    async fn test_commit_write_retries_on_500_then_succeeds() {
        let mut server = mockito::Server::new_async().await;
        let fail_mock = server
            .mock("POST", "/i/v1/analytics/events")
            .with_status(500)
            .with_body("internal error")
            .expect(2)
            .create();
        let success_mock = server
            .mock("POST", "/i/v1/analytics/events")
            .with_status(200)
            .with_body(V1_OK_BODY)
            .expect(1)
            .create();

        let client = make_client_with_retries(&server.url(), 3).await;
        let txn = make_transaction(&client);

        let result = txn.commit_write().await;
        assert!(result.is_ok());
        fail_mock.assert();
        success_mock.assert();
    }

    #[tokio::test]
    async fn test_commit_write_fails_immediately_on_400() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/i/v1/analytics/events")
            .with_status(400)
            .with_body("bad request")
            .expect(1)
            .create();

        let client = make_client(&server.url()).await;
        let txn = make_transaction(&client);

        let result = txn.commit_write().await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("capture batch failed"));
        mock.assert();
    }

    #[tokio::test]
    async fn test_commit_write_fails_on_402_billing_limit() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/i/v1/analytics/events")
            .with_status(402)
            .with_body("billing limit exceeded")
            .expect(1)
            .create();

        let client = make_client(&server.url()).await;
        let txn = make_transaction(&client);

        let result = txn.commit_write().await;
        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        assert!(
            err_msg.contains("Billing Limit Exceeded"),
            "expected billing error, got: {err_msg}"
        );
        mock.assert();
    }

    #[tokio::test]
    async fn test_commit_write_exhausts_retries_on_persistent_500() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/i/v1/analytics/events")
            .with_status(500)
            .with_body("internal error")
            .expect(6)
            .create();

        let client = make_client_with_retries(&server.url(), 6).await;
        let txn = make_transaction(&client);

        let result = txn.commit_write().await;
        assert!(result.is_err());
        mock.assert();
    }

    fn padded_event(pad_bytes: usize) -> Event {
        let mut event = Event::new("big", "user1");
        event.insert_prop("pad", "x".repeat(pad_bytes)).unwrap();
        event
    }

    fn batch_bytes(batch: &[Event]) -> usize {
        batch
            .iter()
            .map(|e| serde_json::to_vec(e).unwrap().len() + PER_EVENT_OVERHEAD_BYTES)
            .sum()
    }

    #[test]
    fn test_split_empty_returns_no_batches() {
        assert!(split_into_byte_limited_batches(vec![]).unwrap().is_empty());
    }

    #[test]
    fn test_split_keeps_small_events_in_one_batch() {
        let events = vec![padded_event(10), padded_event(10), padded_event(10)];
        let batches = split_into_byte_limited_batches(events).unwrap();
        assert_eq!(batches.len(), 1);
        assert_eq!(batches[0].len(), 3);
    }

    #[test]
    fn test_split_breaks_oversized_chunk_into_multiple_batches() {
        // Five ~2.5 MiB events against a 9 MiB budget must span more than one batch.
        let events: Vec<Event> = (0..5).map(|_| padded_event(2_500_000)).collect();
        let total = events.len();

        let batches = split_into_byte_limited_batches(events).unwrap();

        assert!(batches.len() > 1, "expected multiple batches");
        let mut seen = 0;
        for batch in &batches {
            assert!(
                batch_bytes(batch) <= MAX_BATCH_PAYLOAD_BYTES,
                "batch exceeds capture limit"
            );
            seen += batch.len();
        }
        assert_eq!(seen, total, "no events may be dropped while splitting");
    }

    #[test]
    fn test_split_isolates_single_oversized_event() {
        let events = vec![padded_event(10 * 1024 * 1024), padded_event(10)];
        let batches = split_into_byte_limited_batches(events).unwrap();
        assert_eq!(batches.len(), 2);
        assert_eq!(batches[0].len(), 1, "oversized event sent on its own");
        assert_eq!(batches[1].len(), 1);
    }

    #[tokio::test]
    async fn test_commit_write_splits_oversized_chunk_across_requests() {
        let events: Vec<Event> = (0..5).map(|_| padded_event(2_500_000)).collect();
        let expected_requests = split_into_byte_limited_batches(events.clone())
            .unwrap()
            .len();
        assert!(
            expected_requests > 1,
            "test must exercise multiple requests"
        );

        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/i/v1/analytics/events")
            .with_status(200)
            .with_body(V1_OK_BODY)
            .expect(expected_requests)
            .create();

        let client = make_client(&server.url()).await;
        let txn = Box::new(CaptureTransaction {
            client: &client,
            send_rate: 10_000,
            start: Instant::now(),
            events: Mutex::new(events),
        });

        let result = txn.commit_write().await;
        assert!(result.is_ok(), "got {result:?}");
        mock.assert();
    }
}
