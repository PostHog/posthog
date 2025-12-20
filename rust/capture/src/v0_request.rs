use bytes::Bytes;
use chrono::{DateTime, Utc};
use common_types::{CapturedEvent, RawEngageEvent, RawEvent};
use serde::Deserialize;
use time::format_description::well_known::Iso8601;
use time::OffsetDateTime;
use tracing::{error, instrument, warn, Span};

use crate::{
    api::CaptureError,
    payload::{decompress_payload, Compression},
};

#[derive(Deserialize)]
#[serde(untagged)]
pub enum RawRequest {
    /// Array of events (posthog-js)
    Array(Vec<RawEvent>),
    /// Batched events (/batch)
    Batch(BatchedRequest),
    /// Single event (/capture)
    One(Box<RawEvent>),
    /// Single person-props update event w/o name (/engage)
    Engage(Box<RawEngageEvent>),
}

#[derive(Deserialize)]
pub struct BatchedRequest {
    #[serde(alias = "api_key")]
    pub token: String,
    pub historical_migration: Option<bool>,
    pub sent_at: Option<String>,
    pub batch: Vec<RawEvent>,
}

impl RawRequest {
    /// Takes a request payload and tries to decompress and unmarshall it.
    /// While posthog-js sends a compression query param, a sizable portion of requests
    /// fail due to it being missing when the body is compressed.
    /// Instead of trusting the parameter, we peek at the payload's first three bytes to
    /// detect gzip, fallback to uncompressed utf8 otherwise.
    #[instrument(skip_all, fields(request_id, compression, is_mirror_deploy))]
    pub fn from_bytes<'a>(
        bytes: Bytes,
        cmp_hint: Compression,
        request_id: &'a str,
        limit: usize,
        path: String,
    ) -> Result<RawRequest, CaptureError> {
        Span::current().record("compression", cmp_hint.to_string());
        Span::current().record("path", path.clone());
        Span::current().record("request_id", request_id);

        // Use shared decompression logic
        let payload = decompress_payload(bytes, cmp_hint, limit, &path)?;

        Ok(serde_json::from_str::<RawRequest>(&payload)?)
    }

    pub fn get_batch_token(&self) -> Option<String> {
        if let RawRequest::Batch(req) = self {
            return Some(req.token.clone());
        }
        None
    }

    pub fn events(self, path: &str) -> Result<Vec<RawEvent>, CaptureError> {
        let result = match self {
            RawRequest::Array(events) => Ok(events),
            RawRequest::One(event) => Ok(vec![*event]),
            RawRequest::Batch(req) => Ok(req.batch),
            RawRequest::Engage(engage_event) => {
                if path.starts_with("/engage") {
                    Ok(vec![RawEvent {
                        event: String::from("$identify"),
                        token: engage_event.token,
                        distinct_id: engage_event.distinct_id,
                        uuid: engage_event.uuid,
                        timestamp: engage_event.timestamp,
                        offset: engage_event.offset,
                        set: engage_event.set,
                        set_once: engage_event.set_once,
                        properties: engage_event.properties,
                    }])
                } else {
                    let err_msg = String::from("non-engage request missing event name attribute");
                    error!("event hydration from request failed: {}", &err_msg);
                    Err(CaptureError::RequestHydrationError(err_msg))
                }
            }
        };

        // do some basic hydrated event payload filtering here
        match result {
            Ok(mut events) => {
                if events.is_empty() {
                    warn!("rejected empty batch");
                    return Err(CaptureError::EmptyBatch);
                }

                // filter event types we don't want to ingest; return a sentinel
                // error response if this results in an empty payload
                events.retain(|event| event.event != "$performance_event");
                if events.is_empty() {
                    return Err(CaptureError::EmptyPayloadFiltered);
                }
                Ok(events)
            }

            // pass along payload hydration and other error types
            _ => result,
        }
    }

    pub fn historical_migration(&self) -> bool {
        match self {
            RawRequest::Batch(req) => req.historical_migration.unwrap_or_default(),
            _ => false,
        }
    }

    pub fn sent_at(&self) -> Option<OffsetDateTime> {
        if let RawRequest::Batch(req) = &self {
            if let Some(value) = &req.sent_at {
                if let Ok(parsed) = OffsetDateTime::parse(value, &Iso8601::DEFAULT) {
                    return Some(parsed);
                }
            }
        }
        None
    }
}

#[derive(Debug)]
pub struct ProcessingContext {
    pub lib_version: Option<String>,
    pub user_agent: Option<String>,
    pub sent_at: Option<OffsetDateTime>,
    pub token: String,
    pub now: DateTime<Utc>,
    pub client_ip: String,
    pub request_id: String,
    pub path: String,
    pub is_mirror_deploy: bool, // TODO(eli): can remove after migration
    pub historical_migration: bool,
    pub chatty_debug_enabled: bool,
}

// these are the legacy endpoints capture maintains. Can eliminate this
// during post-migration refactoring, once we validate we can safely unite
// the legacy and "common" handling flows
pub fn path_is_legacy_endpoint(path: &str) -> bool {
    path == "/e"
        || path.starts_with("/e/")
        || path.starts_with("/e?")
        || path.starts_with("/capture")
        || path.starts_with("/engage")
        || path.starts_with("/track")
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub enum DataType {
    AnalyticsMain,
    AnalyticsHistorical,
    ClientIngestionWarning,
    HeatmapMain,
    ExceptionMain,
    SnapshotMain,
}

#[derive(Debug, Clone)]
pub struct ProcessedEvent {
    pub metadata: ProcessedEventMetadata,
    pub event: CapturedEvent,
}

#[derive(Debug, Clone)]
pub struct ProcessedEventMetadata {
    pub data_type: DataType,
    pub session_id: Option<String>,
    pub computed_timestamp: Option<chrono::DateTime<chrono::Utc>>,
    pub event_name: String,
    /// Force this event to overflow topic (set by event restrictions)
    pub force_overflow: bool,
    /// Skip person processing for this event (set by event restrictions)
    pub skip_person_processing: bool,
}

#[cfg(test)]
mod tests {
    use crate::token::InvalidTokenReason;
    use crate::utils::extract_and_verify_token;
    use base64::Engine as _;
    use bytes::Bytes;
    use common_types::RawEvent;
    use rand::distributions::Alphanumeric;
    use rand::Rng;
    use serde::Deserialize;
    use serde_json::json;

    use super::{CaptureError, Compression, RawRequest};

    #[test]
    fn decode_compression_param() {
        #[derive(Deserialize, Debug)]
        struct TestConfig {
            compression: Option<Compression>,
        }

        struct CompressionUnit {
            input: &'static str,
            output: Option<Compression>,
        }

        let units = vec![
            CompressionUnit {
                input: r#"{"compression": "gzip"}"#,
                output: Some(Compression::Gzip),
            },
            CompressionUnit {
                input: r#"{"compression": "gzip-js"}"#,
                output: Some(Compression::Gzip),
            },
            CompressionUnit {
                input: r#"{"compression": "GZIP"}"#,
                output: Some(Compression::Gzip),
            },
            CompressionUnit {
                input: r#"{"compression": "lz64"}"#,
                output: Some(Compression::LZString),
            },
            CompressionUnit {
                input: r#"{"compression": "lz-string"}"#,
                output: Some(Compression::LZString),
            },
            CompressionUnit {
                input: r#"{"compression": "LZ64"}"#,
                output: Some(Compression::LZString),
            },
            CompressionUnit {
                input: r#"{"compression": "base64"}"#,
                output: Some(Compression::Base64),
            },
            CompressionUnit {
                input: r#"{"compression": "b64"}"#,
                output: Some(Compression::Base64),
            },
            CompressionUnit {
                input: r#"{"compression": "BASE64"}"#,
                output: Some(Compression::Base64),
            },
            CompressionUnit {
                input: r#"{"compression": "foobar"}"#,
                output: Some(Compression::Unsupported),
            },
            CompressionUnit {
                input: r#"{"compression": ""}"#,
                output: Some(Compression::Unsupported),
            },
            CompressionUnit {
                input: "{}", // no compression param set
                output: None,
            },
        ];

        for unit in units {
            let result: Result<TestConfig, _> = serde_json::from_str(unit.input);

            assert!(
                result.is_ok(),
                "result was not OK for input({}): {:?}",
                unit.input,
                result
            );

            let got = result.unwrap().compression;
            assert!(
                got == unit.output,
                "result {:?} didn't match expected {:?}",
                got,
                unit.output
            );
        }
    }

    #[test]
    fn decode_uncompressed_raw_event() {
        let base64_payload = "ewogICAgImRpc3RpbmN0X2lkIjogIm15X2lkMSIsCiAgICAiZXZlbnQiOiAibXlfZXZlbnQxIiwKICAgICJwcm9wZXJ0aWVzIjogewogICAgICAgICIkZGV2aWNlX3R5cGUiOiAiRGVza3RvcCIKICAgIH0sCiAgICAiYXBpX2tleSI6ICJteV90b2tlbjEiCn0K";
        let compressed_bytes = Bytes::from(
            base64::engine::general_purpose::STANDARD
                .decode(base64_payload)
                .expect("payload is not base64"),
        );

        let path = "/i/v0/e";
        let events = RawRequest::from_bytes(
            compressed_bytes,
            Compression::Unsupported,
            "decode_uncompressed_raw_event",
            1024,
            path.to_string(),
        )
        .expect("failed to parse")
        .events(path)
        .unwrap();
        assert_eq!(1, events.len());
        assert_eq!(Some("my_token1".to_string()), events[0].extract_token());
        assert_eq!("my_event1".to_string(), events[0].event);
        assert_eq!(
            "my_id1".to_string(),
            events[0]
                .extract_distinct_id()
                .expect("cannot find distinct_id")
        );
    }

    #[test]
    fn decode_gzipped_raw_event() {
        let base64_payload = "H4sIADQSbmUCAz2MsQqAMAxE936FBEcnR2f/o4i9IRTb0AahiP9urcVMx3t3ucxQjxxn5bCrZUfLQEepYabpkzgRtOOWfyMpCpIyctVXY42PDifvsFoE73BF9hqFWuPu403YepT+WKNHmMnc5gENoFu2kwAAAA==";
        let compressed_bytes = Bytes::from(
            base64::engine::general_purpose::STANDARD
                .decode(base64_payload)
                .expect("payload is not base64"),
        );

        let path = "/i/v0/e";
        let events = RawRequest::from_bytes(
            compressed_bytes,
            Compression::Unsupported,
            "decode_gzipped_raw_event",
            2048,
            path.to_string(),
        )
        .expect("failed to parse")
        .events(path)
        .unwrap();
        assert_eq!(1, events.len());
        assert_eq!(Some("my_token2".to_string()), events[0].extract_token());
        assert_eq!("my_event2".to_string(), events[0].event);
        assert_eq!(
            "my_id2".to_string(),
            events[0]
                .extract_distinct_id()
                .expect("cannot find distinct_id")
        );
    }

    #[test]
    fn extract_non_engage_event_without_name_fails() {
        let path = "/e/?ip=192.0.0.1&ver=2.3.4";
        let parse_and_extract_events =
            |input: &'static str| -> Result<Vec<RawEvent>, CaptureError> {
                RawRequest::from_bytes(
                    input.into(),
                    Compression::Unsupported,
                    "extract_distinct_id",
                    2048,
                    path.to_string(),
                )
                .expect("failed to parse")
                .events(path)
            };

        // since we're not extracting events against the /engage endpoint path,
        // an event with a missing "event" (name) attribute is invalid
        assert!(matches!(
            parse_and_extract_events(
                r#"{"token": "token", "distinct_id": "distinct_id", "properties":{"foo": 42, "bar": true}}"#
            ),
            Err(CaptureError::RequestHydrationError(_))
        ));
    }

    #[test]
    fn extract_engage_event_without_name_is_resolved() {
        let path = "/engage/?ip=10.0.0.1&ver=1.2.3";
        let parse_and_extract_events =
            |input: &'static str| -> Result<Vec<RawEvent>, CaptureError> {
                RawRequest::from_bytes(
                    input.into(),
                    Compression::Unsupported,
                    "extract_distinct_id",
                    2048,
                    path.to_string(),
                )
                .expect("failed to parse")
                .events(path)
            };

        let got = parse_and_extract_events(
            r#"{"token": "token", "distinct_id": "distinct_id", "$set":{"foo": 42, "bar": true}}"#,
        )
        .expect("engage event hydrated");
        assert!(got.len() == 1);
        assert!(&got[0].event == "$identify");
    }

    #[test]
    fn extract_distinct_id() {
        let path = "/i/v0/e";
        let parse_and_extract = |input: &'static str| -> Result<String, CaptureError> {
            let parsed = RawRequest::from_bytes(
                input.into(),
                Compression::Unsupported,
                "extract_distinct_id",
                2048,
                path.to_string(),
            )
            .expect("failed to parse")
            .events(path)
            .unwrap();
            parsed[0]
                .extract_distinct_id()
                .ok_or(CaptureError::MissingDistinctId)
        };
        // Return MissingDistinctId if not found
        assert!(matches!(
            parse_and_extract(r#"{"event": "e"}"#),
            Err(CaptureError::MissingDistinctId)
        ));
        // Return MissingDistinctId if null
        assert!(matches!(
            parse_and_extract(r#"{"event": "e", "distinct_id": null}"#),
            Err(CaptureError::MissingDistinctId)
        ));
        // Return EmptyDistinctId if empty string
        assert!(matches!(
            parse_and_extract(r#"{"event": "e", "distinct_id": ""}"#),
            Err(CaptureError::MissingDistinctId)
        ));

        let assert_extracted_id = |input: &'static str, expected: &str| {
            let id = parse_and_extract(input).expect("failed to extract");
            assert_eq!(id, expected);
        };
        // Happy path: toplevel field present
        assert_extracted_id(r#"{"event": "e", "distinct_id": "myid"}"#, "myid");
        assert_extracted_id(r#"{"event": "e", "$distinct_id": "23"}"#, "23");

        // Sourced from properties if not present in toplevel field, but toplevel wins if both present
        assert_extracted_id(
            r#"{"event": "e", "properties":{"distinct_id": "myid"}}"#,
            "myid",
        );
        assert_extracted_id(
            r#"{"event": "e", "distinct_id": 23, "properties":{"distinct_id": "myid"}}"#,
            "23",
        );

        // Numbers are stringified
        assert_extracted_id(r#"{"event": "e", "distinct_id": 23}"#, "23");
        assert_extracted_id(r#"{"event": "e", "distinct_id": 23.4}"#, "23.4");

        // Containers are stringified
        assert_extracted_id(
            r#"{"event": "e", "distinct_id": ["a", "b"]}"#,
            r#"["a","b"]"#,
        );
        assert_extracted_id(
            r#"{"event": "e", "distinct_id": {"string": "a", "number": 3}}"#,
            r#"{"number":3,"string":"a"}"#,
        );
    }

    #[test]
    fn extract_distinct_id_trims_to_200_chars() {
        let distinct_id: String = rand::thread_rng()
            .sample_iter(Alphanumeric)
            .take(222)
            .map(char::from)
            .collect();
        let (expected_distinct_id, _) = distinct_id.split_at(200); // works because ascii chars only
        let input = json!([{
            "token": "mytoken",
            "event": "myevent",
            "distinct_id": distinct_id
        }]);

        let path = "/i/v0/e";
        let parsed = RawRequest::from_bytes(
            input.to_string().into(),
            Compression::Unsupported,
            "extract_distinct_id_trims_to_200_chars",
            2048,
            path.to_string(),
        )
        .expect("failed to parse")
        .events(path)
        .unwrap();
        assert_eq!(
            parsed[0].extract_distinct_id().expect("failed to extract"),
            expected_distinct_id
        );
    }

    #[test]
    fn test_gzip_bomb_protection() {
        use flate2::write::GzEncoder;
        use flate2::Compression as GzCompression;
        use std::io::Write;

        // Create a highly compressible payload (GZIP bomb)
        // 10MB of zeros compresses to just a few KB
        let uncompressed_size = 10 * 1024 * 1024; // 10MB
        let zeros = vec![0u8; uncompressed_size];

        // Wrap in JSON structure
        let json_payload = format!(
            r#"[{{"event":"test","distinct_id":"test","properties":{{"data":"{}"}}}}"#,
            base64::engine::general_purpose::STANDARD.encode(&zeros)
        );

        // Compress with maximum compression
        let mut encoder = GzEncoder::new(Vec::new(), GzCompression::best());
        encoder
            .write_all(json_payload.as_bytes())
            .expect("Failed to write");
        let compressed = encoder.finish().expect("Failed to compress");

        let compressed_size = compressed.len();
        let compression_ratio = uncompressed_size as f64 / compressed_size as f64;

        // Verify we created a highly compressed payload
        assert!(
            compression_ratio > 100.0,
            "Expected compression ratio > 100, got {compression_ratio}"
        );

        // Set a reasonable limit that should catch the bomb
        let limit = 1024 * 1024; // 1MB limit

        let path = "/i/v0/e";
        let result = RawRequest::from_bytes(
            Bytes::from(compressed),
            Compression::Gzip,
            "test_gzip_bomb",
            limit,
            path.to_string(),
        );

        // Should fail due to size limit
        match result {
            Err(CaptureError::EventTooBig(msg)) => {
                assert!(
                    msg.contains("exceed"),
                    "Expected error message about exceeding limit, got: {msg}"
                );
            }
            Ok(_) => panic!("GZIP bomb should have been rejected"),
            Err(e) => panic!("Wrong error type: {e:?}"),
        }
    }

    #[test]
    fn test_gzip_normal_compression_allowed() {
        use flate2::write::GzEncoder;
        use flate2::Compression as GzCompression;
        use std::io::Write;

        // Create a normal JSON payload with realistic compression ratio
        let json_payload = r#"[{
            "event": "pageview",
            "distinct_id": "user123",
            "properties": {
                "url": "https://example.com/page",
                "referrer": "https://google.com",
                "timestamp": "2024-01-01T00:00:00Z",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
        }]"#;

        // Compress with normal compression
        let mut encoder = GzEncoder::new(Vec::new(), GzCompression::default());
        encoder
            .write_all(json_payload.as_bytes())
            .expect("Failed to write");
        let compressed = encoder.finish().expect("Failed to compress");

        let compressed_size = compressed.len();
        let uncompressed_size = json_payload.len();
        let compression_ratio = uncompressed_size as f64 / compressed_size as f64;

        // Normal JSON typically compresses 2-4x
        assert!(
            compression_ratio < 10.0,
            "Expected normal compression ratio < 10, got {compression_ratio}"
        );

        // Should succeed with reasonable limit
        let limit = 10 * 1024; // 10KB limit

        let path = "/i/v0/e";
        let result = RawRequest::from_bytes(
            Bytes::from(compressed),
            Compression::Gzip,
            "test_normal_compression",
            limit,
            path.to_string(),
        );

        // Should succeed
        match result {
            Ok(req) => {
                let events = req.events(path).expect("Failed to extract events");
                assert_eq!(events.len(), 1);
                assert_eq!(events[0].event, "pageview");
                assert_eq!(events[0].extract_distinct_id(), Some("user123".to_string()));
            }
            Err(e) => panic!("Normal compressed payload should succeed: {e:?}"),
        }
    }

    #[test]
    fn test_gzip_decompression_size_check_happens_before_allocation() {
        use flate2::write::GzEncoder;
        use flate2::Compression as GzCompression;
        use std::io::Write;

        // Create a payload that's just under the limit when compressed
        // but would exceed it when decompressed
        let limit = 1024; // 1KB limit

        // Create 2KB of JSON data (exceeds limit when decompressed)
        let large_string = "x".repeat(2048);
        let json_payload = format!(
            r#"[{{"event":"test","distinct_id":"test","properties":{{"data":"{large_string}"}}}}"#
        );

        // Compress it (will be smaller than limit)
        let mut encoder = GzEncoder::new(Vec::new(), GzCompression::best());
        encoder
            .write_all(json_payload.as_bytes())
            .expect("Failed to write");
        let compressed = encoder.finish().expect("Failed to compress");

        assert!(
            compressed.len() < limit,
            "Compressed size {} should be less than limit {}",
            compressed.len(),
            limit
        );

        assert!(
            json_payload.len() > limit,
            "Uncompressed size {} should exceed limit {}",
            json_payload.len(),
            limit
        );

        let path = "/i/v0/e";
        let result = RawRequest::from_bytes(
            Bytes::from(compressed),
            Compression::Gzip,
            "test_size_check_before_alloc",
            limit,
            path.to_string(),
        );

        // Should fail due to decompressed size exceeding limit
        match result {
            Err(CaptureError::EventTooBig(msg)) => {
                // Verify the error message indicates it caught the size during decompression
                assert!(
                    msg.contains("would exceed") || msg.contains("exceed"),
                    "Expected error about exceeding size during decompression, got: {msg}"
                );
            }
            Ok(_) => panic!("Should have rejected payload that exceeds limit when decompressed"),
            Err(e) => panic!("Wrong error type: {e:?}"),
        }
    }

    #[test]
    fn test_extract_and_verify_token() {
        let parse_and_extract = |input: &'static str| -> Result<String, CaptureError> {
            let path = "/i/v0/e";
            let raw_req = RawRequest::from_bytes(
                input.into(),
                Compression::Unsupported,
                "extract_and_verify_token",
                2048,
                path.to_string(),
            )
            .expect("failed to parse");

            let maybe_batch_token = raw_req.get_batch_token();

            let events = raw_req
                .events(path)
                .expect("failed to hydrate Vec<RawEvent>");

            extract_and_verify_token(&events, maybe_batch_token)
        };

        let assert_extracted_token = |input: &'static str, expected: &str| {
            let id = parse_and_extract(input).expect("failed to extract");
            assert_eq!(id, expected);
        };

        // Return NoTokenError if not found
        assert!(matches!(
            parse_and_extract(r#"{"event": "e"}"#),
            Err(CaptureError::NoTokenError)
        ));

        // Return TokenValidationError if token empty
        assert!(matches!(
            parse_and_extract(r#"{"api_key": "", "batch":[{"event": "e"}]}"#),
            Err(CaptureError::TokenValidationError(
                InvalidTokenReason::Empty
            ))
        ));

        // Return TokenValidationError if personal apikey
        assert!(matches!(
            parse_and_extract(r#"[{"event": "e", "token": "phx_hellothere"}]"#),
            Err(CaptureError::TokenValidationError(
                InvalidTokenReason::PersonalApiKey
            ))
        ));

        // Return MultipleTokensError if tokens don't match in array
        assert!(matches!(
            parse_and_extract(
                r#"[{"event": "e", "token": "token1"},{"event": "e", "token": "token2"}]"#
            ),
            Err(CaptureError::MultipleTokensError)
        ));

        // Return token from array if consistent
        assert_extracted_token(
            r#"[{"event":"e","token":"token1"},{"event":"e","token":"token1"}]"#,
            "token1",
        );

        // Return token from batch if present
        assert_extracted_token(
            r#"{"batch":[{"event":"e","token":"token1"}],"api_key":"batched"}"#,
            "batched",
        );

        // Return token from single event if present
        assert_extracted_token(r#"{"event":"e","$token":"single_token"}"#, "single_token");
        assert_extracted_token(r#"{"event":"e","api_key":"single_token"}"#, "single_token");
    }
}
