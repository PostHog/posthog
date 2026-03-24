use std::collections::HashMap;

use chrono::{DateTime, Utc};
use uuid::Uuid;

use super::response::Response;
use super::types::{CaptureV1Batch, CaptureV1Event, WrappedEvent};
use crate::v1::context::Context;
use crate::v1::Error;

const CAPTURE_PARSED_EVENTS: &str = "capture_v1_parsed_events";
const CAPTURE_V1_MAX_EVENT_NAME_LENGTH: usize = 200;
const CAPTURE_V1_DISTINCT_ID_MAX_SIZE: usize = 200;
const FUTURE_EVENT_HOURS_CUTOFF_MS: i64 = 23 * 3600 * 1000;

pub async fn process_batch(context: &Context, batch: CaptureV1Batch) -> Result<Response, Error> {
    tracing::info!(ctx = ?context, "process_batch called");

    validate_batch(&batch)?;

    let _events: Vec<WrappedEvent> = validate_events(context, batch);

    unimplemented!()
}

fn validate_batch(batch: &CaptureV1Batch) -> Result<(), Error> {
    DateTime::parse_from_rfc3339(&batch.created_at).map_err(|_| {
        Error::InvalidBatch(format!(
            "created_at is not valid RFC 3339: {}",
            batch.created_at
        ))
    })?;

    for event in &batch.batch {
        Uuid::parse_str(&event.uuid).map_err(|_| Error::MissingEventUuid)?;
    }

    Ok(())
}

fn validate_events(context: &Context, batch: CaptureV1Batch) -> Vec<WrappedEvent> {
    let skew = context.clock_skew();
    let now = context.server_received_at;
    let mut malformed: HashMap<&'static str, u64> = HashMap::new();

    let events: Vec<WrappedEvent> = batch
        .batch
        .into_iter()
        .enumerate()
        .map(|(ordinal, event)| match validate_event(&event) {
            Ok(raw_ts) => {
                metrics::counter!(CAPTURE_PARSED_EVENTS, "result" => "valid").increment(1);
                WrappedEvent {
                    event,
                    timestamp: Some(normalize_timestamp(skew, raw_ts, now)),
                    ordinal,
                    status_code: 200,
                }
            }
            Err(err) => {
                *malformed.entry(err.tag()).or_insert(0) += 1;
                WrappedEvent {
                    event,
                    timestamp: None,
                    ordinal,
                    status_code: 400,
                }
            }
        })
        .collect();

    for (error_tag, count) in &malformed {
        metrics::counter!(CAPTURE_PARSED_EVENTS, "result" => "malformed", "error" => *error_tag)
            .increment(*count);
    }

    events
}

fn validate_event(event: &CaptureV1Event) -> Result<DateTime<Utc>, Error> {
    if event.event.is_empty() {
        return Err(Error::MissingEventName);
    }
    if event.event.len() > CAPTURE_V1_MAX_EVENT_NAME_LENGTH {
        return Err(Error::EventNameTooLong);
    }
    if event.distinct_id.is_empty() {
        return Err(Error::MissingDistinctId);
    }
    if event.distinct_id.len() > CAPTURE_V1_DISTINCT_ID_MAX_SIZE {
        return Err(Error::DistinctIdTooLarge);
    }
    let ts = DateTime::parse_from_rfc3339(&event.timestamp)
        .map(|dt| dt.with_timezone(&Utc))
        .map_err(|_| Error::InvalidEventTimestamp)?;
    Ok(ts)
}

fn normalize_timestamp(
    skew: chrono::Duration,
    raw_event_ts: DateTime<Utc>,
    now: DateTime<Utc>,
) -> DateTime<Utc> {
    let adjusted = raw_event_ts - skew;
    if adjusted.signed_duration_since(now).num_milliseconds() > FUTURE_EVENT_HOURS_CUTOFF_MS {
        return now;
    }
    adjusted
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use chrono::{DateTime, Duration, Utc};
    use uuid::Uuid;

    use super::*;
    use crate::v1::analytics::types::{CaptureV1Batch, CaptureV1Event};
    use crate::v1::Error;

    fn valid_event() -> CaptureV1Event {
        CaptureV1Event {
            event: "$pageview".to_string(),
            uuid: Uuid::new_v4().to_string(),
            distinct_id: "user-42".to_string(),
            timestamp: "2026-03-19T14:29:58.123Z".to_string(),
            properties: HashMap::new(),
        }
    }

    fn valid_batch(events: Vec<CaptureV1Event>) -> CaptureV1Batch {
        CaptureV1Batch {
            created_at: "2026-03-19T14:30:00.000Z".to_string(),
            batch: events,
        }
    }

    // --- validate_batch ---

    #[test]
    fn batch_valid() {
        let batch = valid_batch(vec![valid_event()]);
        assert!(validate_batch(&batch).is_ok());
    }

    #[test]
    fn batch_bad_created_at() {
        let batch = CaptureV1Batch {
            created_at: "not-a-timestamp".to_string(),
            batch: vec![valid_event()],
        };
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::InvalidBatch(_)));
    }

    #[test]
    fn batch_bad_uuid() {
        let mut event = valid_event();
        event.uuid = "not-a-uuid".to_string();
        let batch = valid_batch(vec![event]);
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::MissingEventUuid));
    }

    #[test]
    fn batch_empty_uuid() {
        let mut event = valid_event();
        event.uuid = String::new();
        let batch = valid_batch(vec![event]);
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::MissingEventUuid));
    }

    #[test]
    fn batch_multiple_events_second_bad_uuid() {
        let good = valid_event();
        let mut bad = valid_event();
        bad.uuid = "garbage".to_string();
        let batch = valid_batch(vec![good, bad]);
        let err = validate_batch(&batch).unwrap_err();
        assert!(matches!(err, Error::MissingEventUuid));
    }

    // --- validate_event ---

    #[test]
    fn event_valid() {
        let event = valid_event();
        let ts = validate_event(&event);
        assert!(ts.is_ok());
        assert_eq!(
            ts.unwrap(),
            DateTime::parse_from_rfc3339("2026-03-19T14:29:58.123Z")
                .unwrap()
                .with_timezone(&Utc)
        );
    }

    #[test]
    fn event_empty_name() {
        let mut event = valid_event();
        event.event = String::new();
        assert!(matches!(
            validate_event(&event),
            Err(Error::MissingEventName)
        ));
    }

    #[test]
    fn event_name_too_long() {
        let mut event = valid_event();
        event.event = "x".repeat(CAPTURE_V1_MAX_EVENT_NAME_LENGTH + 1);
        assert!(matches!(
            validate_event(&event),
            Err(Error::EventNameTooLong)
        ));
    }

    #[test]
    fn event_name_at_max_length_ok() {
        let mut event = valid_event();
        event.event = "x".repeat(CAPTURE_V1_MAX_EVENT_NAME_LENGTH);
        assert!(validate_event(&event).is_ok());
    }

    #[test]
    fn event_empty_distinct_id() {
        let mut event = valid_event();
        event.distinct_id = String::new();
        assert!(matches!(
            validate_event(&event),
            Err(Error::MissingDistinctId)
        ));
    }

    #[test]
    fn event_distinct_id_too_large() {
        let mut event = valid_event();
        event.distinct_id = "d".repeat(CAPTURE_V1_DISTINCT_ID_MAX_SIZE + 1);
        assert!(matches!(
            validate_event(&event),
            Err(Error::DistinctIdTooLarge)
        ));
    }

    #[test]
    fn event_distinct_id_at_max_size_ok() {
        let mut event = valid_event();
        event.distinct_id = "d".repeat(CAPTURE_V1_DISTINCT_ID_MAX_SIZE);
        assert!(validate_event(&event).is_ok());
    }

    #[test]
    fn event_bad_timestamp() {
        let mut event = valid_event();
        event.timestamp = "yesterday".to_string();
        assert!(matches!(
            validate_event(&event),
            Err(Error::InvalidEventTimestamp)
        ));
    }

    #[test]
    fn event_empty_timestamp() {
        let mut event = valid_event();
        event.timestamp = String::new();
        assert!(matches!(
            validate_event(&event),
            Err(Error::InvalidEventTimestamp)
        ));
    }

    // --- normalize_timestamp ---

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    #[test]
    fn normalize_no_skew() {
        let now = dt("2026-03-19T12:00:00Z");
        let event_ts = dt("2026-03-19T11:00:00Z");
        let result = normalize_timestamp(Duration::zero(), event_ts, now);
        assert_eq!(result, event_ts);
    }

    #[test]
    fn normalize_positive_skew_client_ahead() {
        let now = dt("2026-03-19T12:00:00Z");
        let event_ts = dt("2026-03-19T11:00:00Z");
        let skew = Duration::seconds(10);
        let result = normalize_timestamp(skew, event_ts, now);
        assert_eq!(result, dt("2026-03-19T10:59:50Z"));
    }

    #[test]
    fn normalize_negative_skew_client_behind() {
        let now = dt("2026-03-19T12:00:00Z");
        let event_ts = dt("2026-03-19T11:00:00Z");
        let skew = Duration::seconds(-10);
        let result = normalize_timestamp(skew, event_ts, now);
        assert_eq!(result, dt("2026-03-19T11:00:10Z"));
    }

    #[test]
    fn normalize_clamps_far_future() {
        let now = dt("2026-03-19T12:00:00Z");
        let event_ts = dt("2026-03-21T12:00:00Z");
        let result = normalize_timestamp(Duration::zero(), event_ts, now);
        assert_eq!(result, now);
    }

    #[test]
    fn normalize_allows_near_future() {
        let now = dt("2026-03-19T12:00:00Z");
        let event_ts = dt("2026-03-20T10:00:00Z");
        let result = normalize_timestamp(Duration::zero(), event_ts, now);
        assert_eq!(result, event_ts);
    }
}
