use std::{
    sync::Mutex,
    time::{Duration, Instant},
};

use anyhow::Error;
use async_trait::async_trait;
use common_types::{InternallyCapturedEvent, RawEvent};
use posthog_rs::{Client, Event};
use tracing::{info, warn};

use crate::job::backoff::BackoffPolicy;

use super::{Emitter, Transaction};

const MAX_RETRIES: u32 = 5;

/// Retry policy for transient HTTP errors from the capture service. Starts at
/// 1 second and doubles up to 30 seconds, giving roughly a minute of total
/// retry time before surfacing the error.
const RETRY_POLICY: BackoffPolicy =
    BackoffPolicy::new(Duration::from_secs(1), 2.0, Duration::from_secs(30));

pub struct CaptureEmitter {
    client: Client,
    send_rate: u64,
}

pub struct CaptureTransaction<'a> {
    client: &'a Client,
    send_rate: u64,
    start: Instant,
    events: Mutex<Vec<Event>>,
    retry_policy: BackoffPolicy,
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
            retry_policy: RETRY_POLICY,
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

fn is_retryable(err: &posthog_rs::Error) -> bool {
    matches!(
        err,
        posthog_rs::Error::RateLimit { .. } | posthog_rs::Error::ServerError { .. }
    )
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

        let min_duration = get_min_txn_duration(self.send_rate, count);
        let txn_elapsed = self.start.elapsed();
        let to_sleep = min_duration.saturating_sub(txn_elapsed);

        info!(
            "sending {count} events to capture in {txn_elapsed:?}, minimum send duration is {min_duration:?}, sleeping for {to_sleep:?}"
        );

        for attempt in 0..=MAX_RETRIES {
            match self.client.capture_batch(events.clone(), true).await {
                Ok(()) => break,
                Err(e) if is_retryable(&e) && attempt < MAX_RETRIES => {
                    // Prefer the server's Retry-After hint when present (capped
                    // to our max delay), otherwise fall back to exponential backoff.
                    let delay = match &e {
                        posthog_rs::Error::RateLimit {
                            retry_after: Some(ra),
                        } => (*ra).min(self.retry_policy.max_delay),
                        _ => self.retry_policy.next_delay(attempt),
                    };
                    warn!(
                        "transient capture error, retrying (attempt {attempt}/{MAX_RETRIES}, delay {delay:?}): {e}"
                    );
                    tokio::time::sleep(delay).await;
                }
                Err(e) => {
                    return Err(Error::msg(format!(
                        "capture batch failed after {} attempts: {e}",
                        attempt + 1
                    )));
                }
            }
        }

        info!("successfully sent batch to capture");
        Ok(to_sleep)
    }
}

fn get_min_txn_duration(send_rate: u64, count: usize) -> Duration {
    let max_send_rate = send_rate as f64;
    let batch_size = count as f64;
    Duration::from_secs_f64(batch_size / max_send_rate)
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
        assert_eq!(json["$distinct_id"], "user123");
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

    #[test]
    fn test_is_retryable() {
        assert!(is_retryable(&posthog_rs::Error::RateLimit {
            retry_after: None
        }));
        assert!(is_retryable(&posthog_rs::Error::ServerError {
            status: 500,
            message: "internal".to_string()
        }));
        assert!(!is_retryable(&posthog_rs::Error::BadRequest(
            "bad".to_string()
        )));
        assert!(!is_retryable(&posthog_rs::Error::Connection(
            "timeout".to_string()
        )));
    }

    async fn make_client(base_url: &str) -> Client {
        let options: posthog_rs::ClientOptions = ("test_api_key", base_url).into();
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
            retry_policy: BackoffPolicy::new(Duration::ZERO, 1.0, Duration::ZERO),
        })
    }

    #[tokio::test]
    async fn test_commit_write_succeeds_on_first_try() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/batch/")
            .with_status(200)
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
            .mock("POST", "/batch/")
            .with_status(500)
            .with_body("internal error")
            .expect(2)
            .create();
        let success_mock = server
            .mock("POST", "/batch/")
            .with_status(200)
            .expect(1)
            .create();

        let client = make_client(&server.url()).await;
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
            .mock("POST", "/batch/")
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
            .contains("after 1 attempts"));
        mock.assert();
    }

    #[tokio::test]
    async fn test_commit_write_exhausts_retries_on_persistent_500() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("POST", "/batch/")
            .with_status(500)
            .with_body("internal error")
            .expect((MAX_RETRIES + 1) as usize)
            .create();

        let client = make_client(&server.url()).await;
        let txn = make_transaction(&client);

        let result = txn.commit_write().await;
        assert!(result.is_err());
        mock.assert();
    }
}
