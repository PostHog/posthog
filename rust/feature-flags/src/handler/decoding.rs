use crate::{
    api::{
        errors::FlagError,
        types::{Compression, FlagsQueryParams},
    },
    flags::flag_request::FlagRequest,
    metrics::consts::FLAG_REQUEST_KLUDGE_COUNTER,
};
use axum::http::{header::CONTENT_TYPE, HeaderMap};
use base64::{engine::general_purpose, Engine as _};
use bytes::Bytes;
use common_compression;
use common_metrics::inc;
use percent_encoding::percent_decode;

/// Lightweight token extraction for rate limiting.
/// Tries to extract the token without full request deserialization.
/// Falls back to None if extraction fails (caller should use IP).
pub fn extract_token(body: &Bytes) -> Option<String> {
    // Try to parse just the token field from JSON body
    // This is much faster than full decode_request()
    serde_json::from_slice::<serde_json::Value>(body)
        .ok()
        .and_then(|v| {
            v.get("token")
                .or_else(|| v.get("api_key"))
                .or_else(|| v.get("$token"))
                .and_then(|t| t.as_str())
                .filter(|s| !s.is_empty())
                .map(String::from)
        })
}

pub fn decode_request(
    headers: &HeaderMap,
    body: Bytes,
    query: &FlagsQueryParams,
) -> Result<FlagRequest, FlagError> {
    let content_type = headers
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/json"); // Default to JSON if no content type

    let base_content_type = content_type.split(';').next().unwrap_or("").trim();

    match base_content_type {
        "application/json" | "text/plain" => {
            let decoded_body = decode_body(body, query.compression, headers)?;

            try_parse_with_fallbacks(decoded_body)
        }
        "application/x-www-form-urlencoded" => decode_form_data(body, query.compression),
        _ => {
            tracing::warn!("unsupported content type: {}", content_type);
            Err(FlagError::RequestDecodingError(format!(
                "unsupported content type: {content_type}"
            )))
        }
    }
}

fn decode_body(
    body: Bytes,
    compression: Option<Compression>,
    headers: &HeaderMap,
) -> Result<Bytes, FlagError> {
    if let Some(compression) = compression {
        match compression {
            Compression::Gzip => return decompress_gzip(body),
            Compression::Base64 => {
                // handle base64 detection separately in try_parse_with_fallbacks
            }
            Compression::Unsupported => {
                tracing::warn!("unsupported compression type");
                return Err(FlagError::RequestDecodingError(
                    "Unsupported compression type".to_string(),
                ));
            }
        }
    }

    // Check Content-Encoding header (Android uses this primarily)
    if let Some(encoding) = headers.get("content-encoding") {
        if let Ok(encoding_str) = encoding.to_str() {
            if encoding_str.contains("gzip") {
                tracing::debug!(
                    "Detected gzip from Content-Encoding header: {}",
                    encoding_str
                );
                return decompress_gzip(body);
            }
        }
    }

    // Fallback: Auto-detect gzip by checking magic bytes (0x1f, 0x8b)
    // This handles cases where clients send gzipped data without proper headers
    if body.len() >= 2 && body[0] == 0x1f && body[1] == 0x8b {
        tracing::debug!("Auto-detected gzip compression from magic bytes");
        inc(
            FLAG_REQUEST_KLUDGE_COUNTER,
            &[("type".to_string(), "auto_detected_gzip".to_string())],
            1,
        );
        return decompress_gzip(body);
    }

    // No compression detected
    Ok(body)
}

fn decompress_gzip(compressed: Bytes) -> Result<Bytes, FlagError> {
    common_compression::decompress_gzip(&compressed)
        .map(Bytes::from)
        .map_err(|e| {
            tracing::warn!("gzip decompression failed: {}", e);
            FlagError::RequestDecodingError(format!("gzip decompression failed: {e}"))
        })
}

fn decode_base64(body: Bytes) -> Result<Bytes, FlagError> {
    // Convert to string and apply URL decoding like base64_decode in Python decide
    let body_str = String::from_utf8_lossy(&body);
    let url_decoded = percent_decode(body_str.as_bytes())
        .decode_utf8()
        .map_err(|e| {
            tracing::warn!("Failed to URL decode base64 data: {}", e);
            FlagError::RequestDecodingError(format!("Failed to URL decode: {e}"))
        })?;

    // Remove whitespace and add padding if necessary
    let mut cleaned = url_decoded.replace(" ", "");
    let padding_needed = cleaned.len() % 4;
    if padding_needed > 0 {
        cleaned.push_str(&"=".repeat(4 - padding_needed));
    }

    let decoded = general_purpose::STANDARD.decode(cleaned).map_err(|e| {
        tracing::warn!("Base64 decoding error: {}", e);
        FlagError::RequestDecodingError(format!("Base64 decoding error: {e}"))
    })?;
    Ok(Bytes::from(decoded))
}

pub fn try_parse_with_fallbacks(body: Bytes) -> Result<FlagRequest, FlagError> {
    // Strategy 1: Try parsing as JSON directly
    if let Ok(request) = FlagRequest::from_bytes(body.clone()) {
        return Ok(request);
    }

    // Strategy 2: Try base64 decode then JSON
    // Even if compression is not specified, we still try to decode it as base64
    tracing::warn!("Direct JSON parsing failed, trying base64 decode fallback");
    match decode_base64(body.clone()) {
        Ok(decoded) => match FlagRequest::from_bytes(decoded) {
            Ok(request) => {
                inc(
                    FLAG_REQUEST_KLUDGE_COUNTER,
                    &[("type".to_string(), "base64_fallback_success".to_string())],
                    1,
                );
                return Ok(request);
            }
            Err(e) => {
                tracing::warn!("Base64 decode succeeded but JSON parsing failed: {}", e);
            }
        },
        Err(e) => {
            tracing::warn!("Base64 decode failed: {}", e);
        }
    }

    Err(FlagError::RequestDecodingError("invalid JSON".to_string()))
}

pub fn decode_form_data(
    body: Bytes,
    compression: Option<Compression>,
) -> Result<FlagRequest, FlagError> {
    // Convert bytes to string first so we can manipulate it
    let form_data = String::from_utf8(body.to_vec()).map_err(|e| {
        tracing::warn!("Invalid UTF-8 in form data: {}", e);
        FlagError::RequestDecodingError("Invalid UTF-8 in form data".into())
    })?;

    // URL decode the string if needed
    let decoded_form = percent_decode(form_data.as_bytes())
        .decode_utf8()
        .map_err(|e| {
            tracing::warn!("Failed to URL decode form data: {}", e);
            FlagError::RequestDecodingError("Failed to URL decode form data".into())
        })?;

    // Extract base64 part, handling both with and without 'data=' prefix
    // see https://github.com/PostHog/posthog/blob/master/posthog/utils.py#L693-L699
    let base64_str = if decoded_form.starts_with("data=") {
        decoded_form.split('=').nth(1).unwrap_or("")
    } else {
        // Count how often we receive base64 data without the 'data=' prefix
        inc(
            FLAG_REQUEST_KLUDGE_COUNTER,
            &[("type".to_string(), "missing_data_prefix".to_string())],
            1,
        );
        &decoded_form
    };

    // Remove whitespace and add padding if necessary
    // https://github.com/PostHog/posthog/blob/master/posthog/utils.py#L701-L705
    let mut cleaned_base64 = base64_str.replace(' ', "");
    let padding_needed = cleaned_base64.len() % 4;
    if padding_needed > 0 {
        inc(
            FLAG_REQUEST_KLUDGE_COUNTER,
            &[("type".to_string(), "padding_needed".to_string())],
            1,
        );
        cleaned_base64.push_str(&"=".repeat(4 - padding_needed));
    }

    // Handle compression if specified (we don't support gzip for form-urlencoded data)
    let decoded = match compression {
        Some(Compression::Gzip) => {
            tracing::warn!("Gzip compression not supported for form-urlencoded data");
            return Err(FlagError::RequestDecodingError(
                "Gzip compression not supported for form-urlencoded data".into(),
            ));
        }
        Some(Compression::Base64) | None => decode_base64(Bytes::from(cleaned_base64))?,
        Some(Compression::Unsupported) => {
            tracing::warn!("Unsupported compression type for form-urlencoded data");
            return Err(FlagError::RequestDecodingError(
                "Unsupported compression type".into(),
            ));
        }
    };

    // Convert to UTF-8 string with utf8_lossy to handle invalid UTF-8 sequences
    // this is equivalent to using Python's `surrogatepass`, since it just replaces
    // unparseable characters with the Unicode replacement character (U+FFFD) instead of failing to decode the request
    // at all.
    let json_str = {
        let lossy_str = String::from_utf8_lossy(&decoded);
        // Count how often we receive base64 data with invalid UTF-8 sequences
        if lossy_str.contains('\u{FFFD}') {
            inc(
                FLAG_REQUEST_KLUDGE_COUNTER,
                &[("type".to_string(), "lossy_utf8".to_string())],
                1,
            );
        }
        lossy_str.into_owned()
    };

    // Parse JSON into FlagRequest
    serde_json::from_str(&json_str).map_err(|e| {
        tracing::warn!("failed to parse JSON: {}", e);
        FlagError::RequestDecodingError("invalid JSON structure".into())
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::types::{Compression, FlagsQueryParams};
    use axum::http::HeaderMap;
    fn create_gzipped_json(json_data: &str) -> Bytes {
        let compressed = common_compression::compress_gzip(json_data.as_bytes()).unwrap();
        Bytes::from(compressed)
    }

    #[test]
    fn test_gzip_auto_detection_from_magic_bytes() {
        let json_data = r#"{"distinct_id": "test", "token": "test_token"}"#;
        let gzipped_body = create_gzipped_json(json_data);

        // Verify magic bytes are present
        assert_eq!(gzipped_body[0], 0x1f);
        assert_eq!(gzipped_body[1], 0x8b);

        let headers = HeaderMap::new();
        let query = FlagsQueryParams::default(); // No compression specified

        let result = decode_request(&headers, gzipped_body, &query);
        assert!(result.is_ok());

        let request = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
    }

    #[test]
    fn test_gzip_detection_from_content_encoding_header() {
        let json_data = r#"{"distinct_id": "test", "token": "test_token"}"#;
        let gzipped_body = create_gzipped_json(json_data);

        let mut headers = HeaderMap::new();
        headers.insert("content-encoding", "gzip".parse().unwrap());

        let query = FlagsQueryParams::default(); // No compression specified

        let result = decode_request(&headers, gzipped_body, &query);
        assert!(result.is_ok());

        let request = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
    }

    #[test]
    fn test_explicit_gzip_compression_parameter() {
        let json_data = r#"{"distinct_id": "test", "token": "test_token"}"#;
        let gzipped_body = create_gzipped_json(json_data);

        let headers = HeaderMap::new();
        let query = FlagsQueryParams {
            compression: Some(Compression::Gzip),
            ..Default::default()
        };

        let result = decode_request(&headers, gzipped_body, &query);
        assert!(result.is_ok());

        let request = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
    }

    #[test]
    fn test_uncompressed_json_still_works() {
        let json_data = r#"{"distinct_id": "test", "token": "test_token"}"#;
        let body = Bytes::from(json_data);

        let headers = HeaderMap::new();
        let query = FlagsQueryParams::default();

        let result = decode_request(&headers, body, &query);
        assert!(result.is_ok());

        let request = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
    }

    #[test]
    fn test_base64_with_url_encoding() {
        // This test verifies the fix for URL-encoded base64 data
        // Base64 with padding: eyJ0b2tlbiI6ICJ0ZXN0IiwgImRpc3RpbmN0X2lkIjogInVzZXIifQo=
        // URL-encoded (= becomes %3D): eyJ0b2tlbiI6ICJ0ZXN0IiwgImRpc3RpbmN0X2lkIjogInVzZXIifQo%3D
        let url_encoded_base64 = "eyJ0b2tlbiI6ICJ0ZXN0IiwgImRpc3RpbmN0X2lkIjogInVzZXIifQo%3D";
        let body = Bytes::from(url_encoded_base64);

        let headers = HeaderMap::new();
        let query = FlagsQueryParams {
            compression: Some(Compression::Base64),
            ..Default::default()
        };

        let result = decode_request(&headers, body, &query);
        assert!(result.is_ok());

        let request = result.unwrap();
        assert_eq!(request.distinct_id, Some("user".to_string()));
        assert_eq!(request.token, Some("test".to_string()));
    }

    #[test]
    fn test_extract_token_with_token_field() {
        let json_data = r#"{"token": "test_token_123", "distinct_id": "user"}"#;
        let body = Bytes::from(json_data);

        let token = extract_token(&body);
        assert_eq!(token, Some("test_token_123".to_string()));
    }

    #[test]
    fn test_extract_token_with_api_key_field() {
        let json_data = r#"{"api_key": "phc_test123", "distinct_id": "user"}"#;
        let body = Bytes::from(json_data);

        let token = extract_token(&body);
        assert_eq!(token, Some("phc_test123".to_string()));
    }

    #[test]
    fn test_extract_token_with_dollar_token_field() {
        let json_data = r#"{"$token": "test_token", "distinct_id": "user"}"#;
        let body = Bytes::from(json_data);

        let token = extract_token(&body);
        assert_eq!(token, Some("test_token".to_string()));
    }

    #[test]
    fn test_extract_token_prefers_token_over_api_key() {
        let json_data = r#"{"token": "token_value", "api_key": "api_key_value"}"#;
        let body = Bytes::from(json_data);

        let token = extract_token(&body);
        assert_eq!(token, Some("token_value".to_string()));
    }

    #[test]
    fn test_extract_token_with_empty_token() {
        let json_data = r#"{"token": "", "distinct_id": "user"}"#;
        let body = Bytes::from(json_data);

        let token = extract_token(&body);
        assert_eq!(token, None);
    }

    #[test]
    fn test_extract_token_with_no_token_field() {
        let json_data = r#"{"distinct_id": "user", "properties": {}}"#;
        let body = Bytes::from(json_data);

        let token = extract_token(&body);
        assert_eq!(token, None);
    }

    #[test]
    fn test_extract_token_with_invalid_json() {
        let body = Bytes::from("not valid json {{{");

        let token = extract_token(&body);
        assert_eq!(token, None);
    }

    #[test]
    fn test_extract_token_with_empty_body() {
        let body = Bytes::from("");

        let token = extract_token(&body);
        assert_eq!(token, None);
    }
}
