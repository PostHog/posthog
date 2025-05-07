use std::collections::HashSet;
use std::io::prelude::*;

use bytes::{Buf, Bytes};
use common_types::{CapturedEvent, RawEvent};
use flate2::read::GzDecoder;
use serde::Deserialize;
use time::format_description::well_known::Iso8601;
use time::OffsetDateTime;
use tracing::{error, instrument, warn};

use crate::{
    api::CaptureError, prometheus::report_dropped_events, token::validate_token,
    v0_endpoint::MAX_PAYLOAD_SNIPPET_SIZE,
};

#[derive(Deserialize, Default, Clone, Copy, PartialEq, Eq)]
pub enum Compression {
    #[default]
    Unsupported,

    #[serde(rename = "gzip", alias = "gzip-js")]
    Gzip,

    #[serde(rename = "lz64")]
    LZString,
}

impl std::fmt::Display for Compression {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Compression::Gzip => write!(f, "gzip"),
            Compression::LZString => write!(f, "lz64"),
            Compression::Unsupported => write!(f, "unsupported"),
        }
    }
}

#[derive(Deserialize, Default)]
pub struct EventQuery {
    pub compression: Option<Compression>,

    // legacy GET requests can include data as query param
    pub data: Option<String>,

    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    #[serde(alias = "_")]
    sent_at: Option<i64>,
}

impl EventQuery {
    /// Returns the parsed value of the sent_at timestamp if present in the query params.
    /// We only support the format sent by recent posthog-js versions, in milliseconds integer.
    /// Values in seconds integer (older SDKs) will be ignored.
    pub fn sent_at(&self) -> Option<OffsetDateTime> {
        if let Some(value) = self.sent_at {
            let value_nanos: i128 = i128::from(value) * 1_000_000; // Assuming the value is in milliseconds, latest posthog-js releases
            if let Ok(sent_at) = OffsetDateTime::from_unix_timestamp_nanos(value_nanos) {
                if sent_at.year() > 2020 {
                    // Could be lower if the input is in seconds
                    return Some(sent_at);
                }
            }
        }
        None
    }
}

// Some SDKs like posthog-js-lite can include metadata in the POST body
#[derive(Deserialize)]
pub struct EventFormData {
    pub data: Option<String>,
    pub compression: Option<Compression>,
    #[serde(alias = "ver")]
    pub lib_version: Option<String>,
}

pub static GZIP_MAGIC_NUMBERS: [u8; 3] = [0x1f, 0x8b, 0x08];

#[derive(Deserialize)]
#[serde(untagged)]
pub enum RawRequest {
    /// Array of events (posthog-js)
    Array(Vec<RawEvent>),
    /// Batched events (/batch)
    Batch(BatchedRequest),
    /// Single event (/capture)
    One(Box<RawEvent>),
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
    #[instrument(skip_all)]
    pub fn from_bytes(
        bytes: Bytes,
        cmp_hint: Compression,
        limit: usize,
        is_mirror_deploy: bool,
    ) -> Result<RawRequest, CaptureError> {
        if is_mirror_deploy {
            warn!(
                len = bytes.len(),
                is_mirror_deploy = is_mirror_deploy,
                cmp_hint = cmp_hint.to_string(),
                "from_bytes: decoding new event"
            );
        }

        let payload = if (is_mirror_deploy && cmp_hint == Compression::Gzip)
            || bytes.starts_with(&GZIP_MAGIC_NUMBERS)
        {
            let len = bytes.len();

            if is_mirror_deploy {
                warn!(
                    len = len,
                    is_mirror_deploy = is_mirror_deploy,
                    cmp_hint = cmp_hint.to_string(),
                    "from_bytes: matched GZIP compression"
                );
            }

            let mut zipstream = GzDecoder::new(bytes.reader());
            let chunk = &mut [0; 1024];
            let mut buf = Vec::with_capacity(len);
            loop {
                let got = match zipstream.read(chunk) {
                    Ok(got) => got,
                    Err(e) => {
                        tracing::error!("from_bytes: failed to read gzip stream: {}", e);
                        return Err(CaptureError::RequestDecodingError(String::from(
                            "invalid gzip data",
                        )));
                    }
                };
                if got == 0 {
                    break;
                }
                buf.extend_from_slice(&chunk[..got]);
                if buf.len() > limit {
                    error!("from_bytes: GZIP decompression limit reached");
                    report_dropped_events("event_too_big", 1);
                    return Err(CaptureError::EventTooBig(format!(
                        "Event or batch exceeded {} during unzipping",
                        limit
                    )));
                }
            }
            match String::from_utf8(buf) {
                Ok(s) => s,
                Err(e) => {
                    error!("from_bytes: failed to decode gzip: {}", e);
                    return Err(CaptureError::RequestDecodingError(String::from(
                        "invalid gzip data",
                    )));
                }
            }
        } else if is_mirror_deploy && cmp_hint == Compression::LZString {
            if is_mirror_deploy {
                warn!(
                    len = bytes.len(),
                    is_mirror_deploy = is_mirror_deploy,
                    cmp_hint = cmp_hint.to_string(),
                    "from_bytes: matched LZ64 compression"
                );
            }
            decompress_lz64(&bytes, limit)?
        } else {
            if is_mirror_deploy {
                warn!(
                    len = bytes.len(),
                    is_mirror_deploy = is_mirror_deploy,
                    cmp_hint = cmp_hint.to_string(),
                    "from_bytes: best-effort, assuming no compression"
                );
            }

            let s = String::from_utf8(bytes.into()).map_err(|e| {
                error!(
                    "from_bytes: failed to convert request payload to UTF8: {}",
                    e
                );
                CaptureError::RequestDecodingError(String::from("invalid UTF8 in request payload"))
            })?;
            if s.len() > limit {
                error!("from_bytes: request size limit reached");
                report_dropped_events("event_too_big", 1);
                return Err(CaptureError::EventTooBig(format!(
                    "Event or batch wasn't compressed, size exceeded {}",
                    limit
                )));
            }
            s
        };

        if is_mirror_deploy {
            let truncate_at: usize = payload
                .char_indices()
                .nth(MAX_PAYLOAD_SNIPPET_SIZE)
                .map(|(n, _)| n)
                .unwrap_or(0);
            let payload_snippet = &payload[0..truncate_at];
            warn!(
                json = payload_snippet,
                is_mirror_deploy = is_mirror_deploy,
                cmp_hint = cmp_hint.to_string(),
                "from_bytes: event payload extracted"
            );
        }
        tracing::debug!(json = payload, "from_bytes: decoded event data");
        Ok(serde_json::from_str::<RawRequest>(&payload)?)
    }

    pub fn events(self) -> Vec<RawEvent> {
        match self {
            RawRequest::Array(events) => events,
            RawRequest::One(event) => vec![*event],
            RawRequest::Batch(req) => req.batch,
        }
    }

    pub fn extract_and_verify_token(&self) -> Result<String, CaptureError> {
        let token = match self {
            RawRequest::Batch(req) => req.token.to_string(),
            RawRequest::One(event) => event.extract_token().ok_or(CaptureError::NoTokenError)?,
            RawRequest::Array(events) => extract_token(events)?,
        };
        validate_token(&token)?;
        Ok(token)
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

fn decompress_lz64(payload: &[u8], limit: usize) -> Result<String, CaptureError> {
    // with lz64 the payload is a Base64 string that must be decoded prior to decompression
    let b64_payload = std::str::from_utf8(payload).unwrap_or("INVALID_UTF8");
    let decomp_utf16 = match lz_str::decompress_from_base64(b64_payload) {
        Some(v) => v,
        None => {
            let max_chars: usize = std::cmp::min(payload.len(), MAX_PAYLOAD_SNIPPET_SIZE);
            let form_data_snippet = String::from_utf8(payload[..max_chars].to_vec())
                .unwrap_or(String::from("INVALID_UTF8"));
            error!(
                form_data = form_data_snippet,
                "decompress_lz64: failed decompress to UTF16"
            );
            return Err(CaptureError::RequestDecodingError(String::from(
                "decompress_lz64: failed decompress to UTF16",
            )));
        }
    };

    // the decompressed data is UTF16 so we need to convert it to UTF8 to
    // obtain the JSON event batch payload we've come to know and love
    let decompressed = match String::from_utf16(&decomp_utf16) {
        Ok(result) => result,
        Err(e) => {
            error!(
                "decompress_lz64: failed UTF16 to UTF8 conversion, got: {}",
                e
            );
            return Err(CaptureError::RequestDecodingError(String::from(
                "decompress_lz64: failed UTF16 to UTF8 conversion",
            )));
        }
    };

    if decompressed.len() > limit {
        error!(
            "lz64 request payload size limit exceeded: {}",
            decompressed.len()
        );
        report_dropped_events("event_too_big", 1);
        return Err(CaptureError::EventTooBig(String::from(
            "lz64 request payload size limit exceeded",
        )));
    }

    Ok(decompressed)
}

#[instrument(skip_all, fields(events = events.len()))]
pub fn extract_token(events: &[RawEvent]) -> Result<String, CaptureError> {
    let distinct_tokens: HashSet<Option<String>> = HashSet::from_iter(
        events
            .iter()
            .map(RawEvent::extract_token)
            .filter(Option::is_some),
    );

    return match distinct_tokens.len() {
        0 => Err(CaptureError::NoTokenError),
        1 => match distinct_tokens.iter().last() {
            Some(Some(token)) => Ok(token.clone()),
            _ => Err(CaptureError::NoTokenError),
        },
        _ => Err(CaptureError::MultipleTokensError),
    };
}

#[derive(Debug)]
pub struct ProcessingContext {
    pub lib_version: Option<String>,
    pub user_agent: Option<String>,
    pub sent_at: Option<OffsetDateTime>,
    pub token: String,
    pub now: String,
    pub client_ip: String,
    pub historical_migration: bool,
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
}

#[cfg(test)]
mod tests {
    use crate::token::InvalidTokenReason;
    use base64::Engine as _;
    use bytes::Bytes;
    use common_types::util::empty_string_is_none;
    use rand::distributions::Alphanumeric;
    use rand::Rng;
    use serde::Deserialize;
    use serde_json::json;
    use serde_json::Value;
    use uuid::Uuid;

    use super::{CaptureError, Compression, RawRequest};

    fn test_deserialize(json: Value) -> Result<Option<Uuid>, serde_json::Error> {
        #[derive(Deserialize)]
        struct TestStruct {
            #[serde(deserialize_with = "empty_string_is_none")]
            uuid: Option<Uuid>,
        }

        let result: TestStruct = serde_json::from_value(json)?;
        Ok(result.uuid)
    }

    #[test]
    fn decode_uncompressed_raw_event() {
        let base64_payload = "ewogICAgImRpc3RpbmN0X2lkIjogIm15X2lkMSIsCiAgICAiZXZlbnQiOiAibXlfZXZlbnQxIiwKICAgICJwcm9wZXJ0aWVzIjogewogICAgICAgICIkZGV2aWNlX3R5cGUiOiAiRGVza3RvcCIKICAgIH0sCiAgICAiYXBpX2tleSI6ICJteV90b2tlbjEiCn0K";
        let compressed_bytes = Bytes::from(
            base64::engine::general_purpose::STANDARD
                .decode(base64_payload)
                .expect("payload is not base64"),
        );

        let events =
            RawRequest::from_bytes(compressed_bytes, Compression::Unsupported, 1024, false)
                .expect("failed to parse")
                .events();
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

        let events =
            RawRequest::from_bytes(compressed_bytes, Compression::Unsupported, 2048, false)
                .expect("failed to parse")
                .events();
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
    fn extract_distinct_id() {
        let parse_and_extract = |input: &'static str| -> Result<String, CaptureError> {
            let parsed =
                RawRequest::from_bytes(input.into(), Compression::Unsupported, 2048, false)
                    .expect("failed to parse")
                    .events();
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

        let parsed = RawRequest::from_bytes(
            input.to_string().into(),
            Compression::Unsupported,
            2048,
            false,
        )
        .expect("failed to parse")
        .events();
        assert_eq!(
            parsed[0].extract_distinct_id().expect("failed to extract"),
            expected_distinct_id
        );
    }

    #[test]
    fn extract_and_verify_token() {
        let parse_and_extract = |input: &'static str| -> Result<String, CaptureError> {
            RawRequest::from_bytes(input.into(), Compression::Unsupported, 2048, false)
                .expect("failed to parse")
                .extract_and_verify_token()
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

    #[test]
    fn test_empty_uuid_string_is_none() {
        let json = serde_json::json!({"uuid": ""});
        let result = test_deserialize(json);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), None);
    }

    #[test]
    fn test_valid_uuid_is_some() {
        let valid_uuid = "550e8400-e29b-41d4-a716-446655440000";
        let json = serde_json::json!({"uuid": valid_uuid});
        let result = test_deserialize(json);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Some(Uuid::parse_str(valid_uuid).unwrap()));
    }

    #[test]
    fn test_invalid_uuid_is_error() {
        let invalid_uuid = "not-a-uuid";
        let json = serde_json::json!({"uuid": invalid_uuid});
        let result = test_deserialize(json);
        assert!(result.is_err());
    }
}
