use std::collections::{HashMap, HashSet};
use std::io::prelude::*;

use bytes::{Buf, Bytes};
use flate2::read::GzDecoder;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use time::format_description::well_known::Iso8601;
use time::OffsetDateTime;
use tracing::instrument;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::prometheus::report_dropped_events;
use crate::token::validate_token;

#[derive(Deserialize, Default)]
pub enum Compression {
    #[default]
    Unsupported,

    #[serde(rename = "gzip", alias = "gzip-js")]
    Gzip,
}

#[derive(Deserialize, Default)]
pub struct EventQuery {
    pub compression: Option<Compression>,

    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    #[serde(alias = "_")]
    sent_at: Option<i64>,
}

impl EventQuery {
    /// Returns the parsed value of the sent_at timestamp if present in the query params.
    /// We only support the format sent by recent posthog-js versions, in milliseconds integer.
    /// Values in seconds integer (older SDKs will be ignored).
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

#[derive(Debug, Deserialize)]
pub struct EventFormData {
    pub data: String,
}

pub fn empty_string_is_none<'de, D>(deserializer: D) -> Result<Option<Uuid>, D::Error>
where
    D: Deserializer<'de>,
{
    let opt = Option::<String>::deserialize(deserializer)?;
    match opt {
        None => Ok(None),
        Some(s) if s.is_empty() => Ok(None),
        Some(s) => Uuid::parse_str(&s)
            .map(Some)
            .map_err(serde::de::Error::custom),
    }
}

#[derive(Default, Debug, Deserialize, Serialize)]
pub struct RawEvent {
    #[serde(
        alias = "$token",
        alias = "api_key",
        skip_serializing_if = "Option::is_none"
    )]
    pub token: Option<String>,
    #[serde(alias = "$distinct_id", skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<Value>, // posthog-js accepts arbitrary values as distinct_id
    #[serde(default, deserialize_with = "empty_string_is_none")]
    pub uuid: Option<Uuid>,
    pub event: String,
    #[serde(default)]
    pub properties: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>, // Passed through if provided, parsed by ingestion
    #[serde(skip_serializing_if = "Option::is_none")]
    pub offset: Option<i64>, // Passed through if provided, parsed by ingestion
    #[serde(rename = "$set", skip_serializing_if = "Option::is_none")]
    pub set: Option<HashMap<String, Value>>,
    #[serde(rename = "$set_once", skip_serializing_if = "Option::is_none")]
    pub set_once: Option<HashMap<String, Value>>,
}

static GZIP_MAGIC_NUMBERS: [u8; 3] = [0x1f, 0x8b, 8];

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
    pub fn from_bytes(bytes: Bytes, limit: usize) -> Result<RawRequest, CaptureError> {
        tracing::debug!(len = bytes.len(), "decoding new event");

        let payload = if bytes.starts_with(&GZIP_MAGIC_NUMBERS) {
            let len = bytes.len();
            let mut zipstream = GzDecoder::new(bytes.reader());
            let chunk = &mut [0; 1024];
            let mut buf = Vec::with_capacity(len);
            loop {
                let got = match zipstream.read(chunk) {
                    Ok(got) => got,
                    Err(e) => {
                        tracing::error!("failed to read gzip stream: {}", e);
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
                    tracing::error!("GZIP decompression limit reached");
                    report_dropped_events("event_too_big", 1);
                    return Err(CaptureError::EventTooBig);
                }
            }
            match String::from_utf8(buf) {
                Ok(s) => s,
                Err(e) => {
                    tracing::error!("failed to decode gzip: {}", e);
                    return Err(CaptureError::RequestDecodingError(String::from(
                        "invalid gzip data",
                    )));
                }
            }
        } else {
            let s = String::from_utf8(bytes.into()).map_err(|e| {
                tracing::error!("failed to decode body: {}", e);
                CaptureError::RequestDecodingError(String::from("invalid body encoding"))
            })?;
            if s.len() > limit {
                tracing::error!("Request size limit reached");
                report_dropped_events("event_too_big", 1);
                return Err(CaptureError::EventTooBig);
            }
            s
        };

        tracing::debug!(json = payload, "decoded event data");
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

impl RawEvent {
    pub fn extract_token(&self) -> Option<String> {
        match &self.token {
            Some(value) => Some(value.clone()),
            None => self
                .properties
                .get("token")
                .and_then(Value::as_str)
                .map(String::from),
        }
    }

    /// Extracts, stringifies and trims the distinct_id to a 200 chars String.
    /// SDKs send the distinct_id either in the root field or as a property,
    /// and can send string, number, array, or map values. We try to best-effort
    /// stringify complex values, and make sure it's not longer than 200 chars.
    pub fn extract_distinct_id(&self) -> Result<String, CaptureError> {
        // Breaking change compared to capture-py: None / Null is not allowed.
        let value = match &self.distinct_id {
            None | Some(Value::Null) => match self.properties.get("distinct_id") {
                None | Some(Value::Null) => return Err(CaptureError::MissingDistinctId),
                Some(id) => id,
            },
            Some(id) => id,
        };

        let distinct_id = value
            .as_str()
            .map(|s| s.to_owned())
            .unwrap_or_else(|| value.to_string());
        match distinct_id.len() {
            0 => Err(CaptureError::EmptyDistinctId),
            1..=200 => Ok(distinct_id),
            _ => Ok(distinct_id.chars().take(200).collect()),
        }
    }
}

#[derive(Debug)]
pub struct ProcessingContext {
    pub lib_version: Option<String>,
    pub sent_at: Option<OffsetDateTime>,
    pub token: String,
    pub now: String,
    pub client_ip: String,
    pub historical_migration: bool,
}

#[cfg(test)]
mod tests {
    use crate::token::InvalidTokenReason;
    use crate::v0_request::empty_string_is_none;
    use base64::Engine as _;
    use bytes::Bytes;
    use rand::distributions::Alphanumeric;
    use rand::Rng;
    use serde::Deserialize;
    use serde_json::json;
    use serde_json::Value;
    use uuid::Uuid;

    use super::CaptureError;
    use super::RawRequest;

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

        let events = RawRequest::from_bytes(compressed_bytes, 1024)
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

        let events = RawRequest::from_bytes(compressed_bytes, 2048)
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
            let parsed = RawRequest::from_bytes(input.into(), 2048)
                .expect("failed to parse")
                .events();
            parsed[0].extract_distinct_id()
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
            Err(CaptureError::EmptyDistinctId)
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

        let parsed = RawRequest::from_bytes(input.to_string().into(), 2048)
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
            RawRequest::from_bytes(input.into(), 2048)
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
