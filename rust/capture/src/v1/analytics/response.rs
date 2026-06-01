use axum::http::{header, HeaderValue, StatusCode};
use axum::response::IntoResponse;
use serde::ser::{SerializeMap, SerializeStruct};
use serde::Serialize;
use uuid::Uuid;

use super::constants::DEFAULT_RETRY_AFTER_SECS;
use super::types::{EventResult, WrappedEvent};
use crate::v1::context::Context;

// ---------------------------------------------------------------------------
// BatchEntryStatus
// ---------------------------------------------------------------------------

/// Per-event outcome communicated to the SDK in the 200 response body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BatchEntryStatus {
    pub result: EventResult,
    pub details: Option<&'static str>,
}

impl Serialize for BatchEntryStatus {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let field_count = if self.details.is_some() { 2 } else { 1 };
        let mut state = serializer.serialize_struct("BatchEntryStatus", field_count)?;
        state.serialize_field("result", &self.result)?;
        if let Some(detail) = self.details {
            state.serialize_field("details", detail)?;
        }
        state.end()
    }
}

// ---------------------------------------------------------------------------
// BatchResponse
// ---------------------------------------------------------------------------

/// 200 OK response for the V1 analytics batch endpoint.
///
/// Preserves event insertion order via a Vec (events arrive in batch-index
/// order and are never reordered during processing).
#[derive(Debug)]
pub struct BatchResponse {
    pub has_retry: bool,
    entries: Vec<(Uuid, BatchEntryStatus)>,
}

impl BatchResponse {
    /// Build the response from a processed batch of WrappedEvents.
    /// Call this after sink publishing and result merging are complete.
    pub fn build(ctx: &Context, events: &[WrappedEvent]) -> Self {
        let _ = ctx; // Context reserved for future per-response metadata
        let mut has_retry = false;
        let entries: Vec<(Uuid, BatchEntryStatus)> = events
            .iter()
            .map(|ev| {
                if ev.result == EventResult::Retry {
                    has_retry = true;
                }
                (
                    ev.uuid,
                    BatchEntryStatus {
                        result: ev.result,
                        details: ev.details,
                    },
                )
            })
            .collect();

        Self { has_retry, entries }
    }

    pub fn entries(&self) -> &[(Uuid, BatchEntryStatus)] {
        &self.entries
    }
}

/// Wrapper for serializing the response body as `{"results": {uuid: status, ...}}`.
struct ResponseBody<'a>(&'a [(Uuid, BatchEntryStatus)]);

impl Serialize for ResponseBody<'_> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut outer = serializer.serialize_struct("ResponseBody", 1)?;
        outer.serialize_field("results", &ResultsMap(self.0))?;
        outer.end()
    }
}

struct ResultsMap<'a>(&'a [(Uuid, BatchEntryStatus)]);

impl Serialize for ResultsMap<'_> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(self.0.len()))?;
        for (uuid, status) in self.0 {
            map.serialize_entry(&uuid.to_string(), status)?;
        }
        map.end()
    }
}

impl IntoResponse for BatchResponse {
    fn into_response(self) -> axum::response::Response {
        let body = serde_json::to_vec(&ResponseBody(&self.entries))
            .expect("BatchResponse serialization cannot fail");

        let mut response = (StatusCode::OK, body).into_response();
        let headers = response.headers_mut();

        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );

        if self.has_retry {
            headers.insert(header::RETRY_AFTER, DEFAULT_RETRY_AFTER_SECS);
        }

        response
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use axum::body::to_bytes;
    use axum::response::IntoResponse;
    use chrono::Utc;
    use serde_json::Value;
    use uuid::Uuid;

    use super::*;
    use crate::v1::analytics::types::{Event, EventResult, Options, WrappedEvent};
    use crate::v1::sinks::Destination;
    use crate::v1::test_utils;

    fn make_wrapped(result: EventResult, details: Option<&'static str>) -> WrappedEvent {
        let uuid = Uuid::new_v4();
        WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-1".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: None,
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_correction: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: serde_json::value::RawValue::from_string("{}".to_owned()).unwrap(),
            },
            uuid,
            adjusted_timestamp: Some(Utc::now()),
            result,
            details,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        }
    }

    #[test]
    fn batch_entry_status_serialize_ok() {
        let status = BatchEntryStatus {
            result: EventResult::Ok,
            details: None,
        };
        let json = serde_json::to_string(&status).unwrap();
        assert_eq!(json, r#"{"result":"ok"}"#);
    }

    #[test]
    fn batch_entry_status_serialize_with_details() {
        let status = BatchEntryStatus {
            result: EventResult::Retry,
            details: Some("not_persisted"),
        };
        let json = serde_json::to_string(&status).unwrap();
        assert_eq!(json, r#"{"result":"retry","details":"not_persisted"}"#);
    }

    #[test]
    fn batch_entry_status_serialize_drop_with_details() {
        let status = BatchEntryStatus {
            result: EventResult::Drop,
            details: Some("billing_limit_exceeded"),
        };
        let json = serde_json::to_string(&status).unwrap();
        assert_eq!(
            json,
            r#"{"result":"drop","details":"billing_limit_exceeded"}"#
        );
    }

    #[test]
    fn batch_entry_status_serialize_limited_with_details() {
        let status = BatchEntryStatus {
            result: EventResult::Limited,
            details: Some("person_processing_disabled"),
        };
        let json = serde_json::to_string(&status).unwrap();
        assert_eq!(
            json,
            r#"{"result":"limited","details":"person_processing_disabled"}"#
        );
    }

    #[test]
    fn batch_response_build_all_ok() {
        let ctx = test_utils::test_context();
        let events = vec![
            make_wrapped(EventResult::Ok, None),
            make_wrapped(EventResult::Ok, None),
        ];
        let resp = BatchResponse::build(&ctx, &events);
        assert!(!resp.has_retry);
        assert_eq!(resp.entries().len(), 2);
        for (uuid, status) in resp.entries() {
            assert_eq!(status.result, EventResult::Ok);
            assert!(status.details.is_none());
            assert_ne!(*uuid, Uuid::nil());
        }
    }

    #[test]
    fn batch_response_build_mixed() {
        let ctx = test_utils::test_context();
        let events = vec![
            make_wrapped(EventResult::Ok, None),
            make_wrapped(EventResult::Drop, Some("billing_limit_exceeded")),
            make_wrapped(EventResult::Limited, Some("person_processing_disabled")),
            make_wrapped(EventResult::Retry, Some("not_persisted")),
        ];
        let resp = BatchResponse::build(&ctx, &events);
        assert!(resp.has_retry);
        assert_eq!(resp.entries().len(), 4);
        assert_eq!(resp.entries()[0].1.result, EventResult::Ok);
        assert_eq!(resp.entries()[1].1.result, EventResult::Drop);
        assert_eq!(resp.entries()[2].1.result, EventResult::Limited);
        assert_eq!(resp.entries()[3].1.result, EventResult::Retry);
    }

    #[test]
    fn batch_response_has_retry_false_when_no_retry() {
        let ctx = test_utils::test_context();
        let events = vec![
            make_wrapped(EventResult::Ok, None),
            make_wrapped(EventResult::Drop, Some("billing")),
            make_wrapped(EventResult::Limited, Some("pp_disabled")),
        ];
        let resp = BatchResponse::build(&ctx, &events);
        assert!(!resp.has_retry);
    }

    #[test]
    fn batch_response_preserves_insertion_order() {
        let ctx = test_utils::test_context();
        let events = vec![
            make_wrapped(EventResult::Ok, None),
            make_wrapped(EventResult::Retry, Some("not_persisted")),
            make_wrapped(EventResult::Ok, None),
        ];
        let uuids: Vec<Uuid> = events.iter().map(|e| e.uuid).collect();
        let resp = BatchResponse::build(&ctx, &events);
        let resp_uuids: Vec<Uuid> = resp.entries().iter().map(|(u, _)| *u).collect();
        assert_eq!(resp_uuids, uuids);
    }

    #[tokio::test]
    async fn into_response_status_200() {
        let ctx = test_utils::test_context();
        let events = vec![make_wrapped(EventResult::Ok, None)];
        let resp = BatchResponse::build(&ctx, &events).into_response();
        assert_eq!(resp.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn into_response_content_type_json() {
        let ctx = test_utils::test_context();
        let events = vec![make_wrapped(EventResult::Ok, None)];
        let resp = BatchResponse::build(&ctx, &events).into_response();
        assert_eq!(
            resp.headers().get(header::CONTENT_TYPE).unwrap(),
            "application/json"
        );
    }

    #[tokio::test]
    async fn into_response_retry_after_present_when_retry() {
        let ctx = test_utils::test_context();
        let events = vec![make_wrapped(EventResult::Retry, Some("not_persisted"))];
        let resp = BatchResponse::build(&ctx, &events).into_response();
        let hdr = resp
            .headers()
            .get(header::RETRY_AFTER)
            .expect("Retry-After header should be present");
        assert_eq!(hdr.to_str().unwrap(), "1");
    }

    #[tokio::test]
    async fn into_response_retry_after_absent_when_no_retry() {
        let ctx = test_utils::test_context();
        let events = vec![make_wrapped(EventResult::Ok, None)];
        let resp = BatchResponse::build(&ctx, &events).into_response();
        assert!(resp.headers().get(header::RETRY_AFTER).is_none());
    }

    #[tokio::test]
    async fn into_response_body_json_shape() {
        let ctx = test_utils::test_context();
        let events = vec![
            make_wrapped(EventResult::Ok, None),
            make_wrapped(EventResult::Drop, Some("billing_limit_exceeded")),
        ];
        let uuids: Vec<String> = events.iter().map(|e| e.uuid.to_string()).collect();
        let resp = BatchResponse::build(&ctx, &events).into_response();
        let body_bytes = to_bytes(resp.into_body(), usize::MAX).await.unwrap();
        let body: Value = serde_json::from_slice(&body_bytes).unwrap();

        let results = body.get("results").expect("results key must exist");
        assert!(results.is_object());

        let first = results.get(&uuids[0]).unwrap();
        assert_eq!(first["result"], "ok");
        assert!(!first.as_object().unwrap().contains_key("details"));

        let second = results.get(&uuids[1]).unwrap();
        assert_eq!(second["result"], "drop");
        assert_eq!(second["details"], "billing_limit_exceeded");
    }
}
