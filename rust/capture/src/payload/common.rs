//! Common helpers for payload processing
//!
//! This module contains shared utilities used by both analytics and recording
//! payload handlers for extracting metadata, processing request bodies, and
//! handling various encoding/compression formats.

use axum::http::{HeaderMap, Method};
use bytes::Bytes;
use tracing::{error, Span};

use crate::{
    api::CaptureError,
    payload::{Compression, EventFormData, EventQuery},
    utils::{
        decode_base64, decode_form, extract_compression, extract_lib_version, is_likely_base64,
        is_likely_urlencoded_form, Base64Option, FORM_MIME_TYPE, MAX_PAYLOAD_SNIPPET_SIZE,
    },
};

/// Helper struct to hold extracted request metadata
#[derive(Debug)]
pub struct RequestMetadata<'a> {
    pub user_agent: &'a str,
    pub content_type: &'a str,
    pub content_encoding: &'a str,
    pub request_id: &'a str,
    pub is_mirror_deploy: bool,
}

/// Extract and record request metadata from headers
pub fn extract_and_record_metadata<'a>(
    headers: &'a HeaderMap,
    path: &str,
    is_mirror_deploy: bool,
) -> RequestMetadata<'a> {
    Span::current().record("path", path);

    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("user_agent", user_agent);

    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("content_type", content_type);

    let content_encoding = headers
        .get("content-encoding")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("content_encoding", content_encoding);

    let request_id = headers
        .get("x-request-id")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("request_id", request_id);

    Span::current().record("is_mirror_deploy", is_mirror_deploy);

    RequestMetadata {
        user_agent,
        content_type,
        content_encoding,
        request_id,
        is_mirror_deploy,
    }
}

/// Extract payload bytes from request (handles query params, form data, base64 encoding)
/// Returns (payload_bytes, compression, lib_version)
pub fn extract_payload_bytes(
    query_params: &mut EventQuery,
    headers: &HeaderMap,
    method: &Method,
    body: Bytes,
) -> Result<(Bytes, Compression, Option<String>), CaptureError> {
    // Unpack the payload - it may be in a GET query param or POST body
    let raw_payload: Bytes = if query_params.data.as_ref().is_some_and(|d| !d.is_empty()) {
        let tmp_vec = std::mem::take(&mut query_params.data);
        Bytes::from(tmp_vec.unwrap())
    } else if !body.is_empty() {
        body
    } else {
        error!("missing payload on {:?} request", method);
        return Err(CaptureError::EmptyPayload);
    };

    // First round of processing: is this byte payload entirely base64 encoded?
    let payload = if !is_likely_urlencoded_form(&raw_payload)
        && is_likely_base64(&raw_payload, Base64Option::Strict)
    {
        decode_base64(&raw_payload, "optimistic_decode_raw_payload")
            .map_or(raw_payload, Bytes::from)
    } else {
        raw_payload
    };

    // Attempt to decode POST payload if it is form data
    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    let form: EventFormData = match content_type {
        FORM_MIME_TYPE => {
            if is_likely_urlencoded_form(&payload) {
                let mut form = decode_form(&payload)?;

                // Corner case: if the form "data" payload is Base64 encoded,
                // we need to restore the '+' chars that were urldecoded to spaces
                if form
                    .data
                    .as_ref()
                    .is_some_and(|d| is_likely_base64(d.as_bytes(), Base64Option::Loose))
                {
                    form.data = Some(form.data.unwrap().replace(" ", "+"));
                }
                form
            } else {
                let max_chars = std::cmp::min(payload.len(), MAX_PAYLOAD_SNIPPET_SIZE);
                let form_data_snippet = String::from_utf8(payload[..max_chars].to_vec())
                    .unwrap_or(String::from("INVALID_UTF8"));
                error!(
                    form_data = form_data_snippet,
                    "expected form data in {} request payload", *method
                );
                return Err(CaptureError::RequestDecodingError(String::from(
                    "expected form data in POST request payload",
                )));
            }
        }
        _ => EventFormData::default(),
    };

    // Extract compression hint and lib_version from query params or form data
    let compression = extract_compression(&form, query_params, headers);
    let lib_version = extract_lib_version(&form, query_params);

    // Get the actual payload bytes (either from form data or direct body)
    let payload_bytes: Bytes = if form.data.is_some() {
        Bytes::from(form.data.unwrap())
    } else {
        payload
    };

    Ok((payload_bytes, compression, lib_version))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    #[test]
    fn test_extract_and_record_metadata_basic() {
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", HeaderValue::from_static("test-agent"));
        headers.insert("content-type", HeaderValue::from_static("application/json"));
        headers.insert("x-request-id", HeaderValue::from_static("req-123"));

        let metadata = extract_and_record_metadata(&headers, "/test", false);

        assert_eq!(metadata.user_agent, "test-agent");
        assert_eq!(metadata.content_type, "application/json");
        assert_eq!(metadata.request_id, "req-123");
        assert!(!metadata.is_mirror_deploy);
    }

    #[test]
    fn test_extract_and_record_metadata_missing_headers() {
        let headers = HeaderMap::new();

        let metadata = extract_and_record_metadata(&headers, "/test", true);

        assert_eq!(metadata.user_agent, "unknown");
        assert_eq!(metadata.content_type, "unknown");
        assert_eq!(metadata.content_encoding, "unknown");
        assert_eq!(metadata.request_id, "unknown");
        assert!(metadata.is_mirror_deploy);
    }

    #[test]
    fn test_extract_payload_bytes_from_body() {
        let mut query_params = EventQuery::default();
        let headers = HeaderMap::new();
        let method = Method::POST;
        let body = Bytes::from(r#"{"event":"test"}"#);

        let result = extract_payload_bytes(&mut query_params, &headers, &method, body);
        assert!(result.is_ok());

        let (payload, compression, lib_version) = result.unwrap();
        assert_eq!(payload, Bytes::from(r#"{"event":"test"}"#));
        assert_eq!(compression, Compression::Unsupported);
        assert_eq!(lib_version, None);
    }

    #[test]
    fn test_extract_payload_bytes_from_query_param() {
        let mut query_params = EventQuery {
            data: Some(r#"{"event":"test"}"#.to_string()),
            compression: None,
            lib_version: None,
            sent_at: None,
            beacon: false,
        };
        let headers = HeaderMap::new();
        let method = Method::GET;
        let body = Bytes::new();

        let result = extract_payload_bytes(&mut query_params, &headers, &method, body);
        assert!(result.is_ok());

        let (payload, _, _) = result.unwrap();
        assert_eq!(payload, Bytes::from(r#"{"event":"test"}"#));
    }

    #[test]
    fn test_extract_payload_bytes_empty_payload_error() {
        let mut query_params = EventQuery::default();
        let headers = HeaderMap::new();
        let method = Method::POST;
        let body = Bytes::new();

        let result = extract_payload_bytes(&mut query_params, &headers, &method, body);
        assert!(matches!(result, Err(CaptureError::EmptyPayload)));
    }

    #[test]
    fn test_extract_payload_bytes_with_compression_hint() {
        let mut query_params = EventQuery {
            data: Some(r#"{"event":"test"}"#.to_string()),
            compression: Some(Compression::Gzip),
            lib_version: None,
            sent_at: None,
            beacon: false,
        };
        let headers = HeaderMap::new();
        let method = Method::GET;
        let body = Bytes::new();

        let result = extract_payload_bytes(&mut query_params, &headers, &method, body);
        assert!(result.is_ok());

        let (_, compression, _) = result.unwrap();
        assert_eq!(compression, Compression::Gzip);
    }

    #[test]
    fn test_extract_payload_bytes_with_lib_version() {
        let mut query_params = EventQuery {
            data: Some(r#"{"event":"test"}"#.to_string()),
            compression: None,
            lib_version: Some("1.2.3".to_string()),
            sent_at: None,
            beacon: false,
        };
        let headers = HeaderMap::new();
        let method = Method::GET;
        let body = Bytes::new();

        let result = extract_payload_bytes(&mut query_params, &headers, &method, body);
        assert!(result.is_ok());

        let (_, _, lib_version) = result.unwrap();
        assert_eq!(lib_version, Some("1.2.3".to_string()));
    }
}
