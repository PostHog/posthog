use crate::{
    api::{
        errors::FlagError,
        types::{Compression, FlagsQueryParams},
    },
    flags::flag_request::FlagRequest,
    metrics::consts::{FLAG_GZIP_OUTPUT_EXCEEDED_COUNTER, FLAG_REQUEST_KLUDGE_COUNTER},
    utils::user_agent::UserAgentInfo,
};
use axum::http::{header::CONTENT_TYPE, header::USER_AGENT, HeaderMap};
use base64::{engine::general_purpose, Engine as _};
use bytes::Bytes;
use common_compression::{self, has_gzip_magic_header};
use common_metrics::inc;
use percent_encoding::percent_decode;

/// 4 MiB cap on the decompressed `/flags` request body. The compressed body is
/// already capped at 2 MiB by axum's `DefaultBodyLimit` (`MAX_FLAGS_BODY_BYTES`),
/// so this is a backstop against gzip-bomb amplification.
const MAX_FLAGS_DECOMPRESSED_BYTES: usize = 4 * 1024 * 1024;

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

/// Decode and parse a /flags request body.
///
/// Returns the parsed [`FlagRequest`] along with the **decoded** body bytes
/// — post gzip-decompression and post base64-decoding when those apply, or
/// the raw body for plain JSON. Callers that want to log or otherwise reuse
/// the parsed-form bytes (e.g. body logging) can avoid a second decompress
/// pass by reusing the returned `Bytes`.
pub fn decode_request(
    headers: &HeaderMap,
    body: Bytes,
    query: &FlagsQueryParams,
) -> Result<(FlagRequest, Bytes), FlagError> {
    let content_type = headers
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/json"); // Default to JSON if no content type

    let base_content_type = content_type.split(';').next().unwrap_or("").trim();

    let user_agent = headers.get(USER_AGENT).and_then(|v| v.to_str().ok());

    match base_content_type {
        "application/json" | "text/plain" => {
            let decoded_body = decode_body(body, query.compression, headers)?;

            try_parse_with_fallbacks(decoded_body, user_agent)
        }
        "application/x-www-form-urlencoded" => {
            decode_form_data(body, query.compression, user_agent)
        }
        _ => {
            tracing::warn!("unsupported content type: {}", content_type);
            Err(FlagError::RequestDecodingError(format!(
                "unsupported content type: {content_type}"
            )))
        }
    }
}

/// Decode a request body to its raw JSON bytes.
///
/// Handles gzip explicitly via `Compression::Gzip`, the `Content-Encoding`
/// header, or auto-detection from magic bytes. `Compression::Base64` is left
/// to `try_parse_with_fallbacks`; this function returns the body unchanged in
/// that case.
pub(crate) fn decode_body(
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
    if has_gzip_magic_header(&body) {
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
    common_compression::decompress_gzip_capped(&compressed, MAX_FLAGS_DECOMPRESSED_BYTES)
        .map(Bytes::from)
        .map_err(|e| {
            if matches!(
                e,
                common_compression::CompressionError::OutputTooLarge { .. }
            ) {
                inc(FLAG_GZIP_OUTPUT_EXCEEDED_COUNTER, &[], 1);
            } else {
                tracing::warn!("gzip decompression failed: {}", e);
            }
            FlagError::from(e)
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

/// Parse a request body that has already been gzip-decompressed (if it was
/// gzipped). Falls back to base64-decoding when the body is not direct JSON
/// — some SDKs send base64-wrapped JSON via `application/json` rather than
/// the form-urlencoded path.
///
/// Returns the parsed [`FlagRequest`] along with the bytes that successfully
/// parsed: the input bytes when direct JSON parsing wins, or the
/// base64-decoded bytes when the fallback wins.
pub fn try_parse_with_fallbacks(
    body: Bytes,
    user_agent: Option<&str>,
) -> Result<(FlagRequest, Bytes), FlagError> {
    // Strategy 1: Try parsing as JSON directly
    if let Ok(request) = FlagRequest::from_bytes(body.clone()) {
        return Ok((request, body));
    }

    // Strategy 2: Try base64 decode then JSON
    // Even if compression is not specified, we still try to decode it as base64
    let client_type = UserAgentInfo::client_type_label_from_raw(user_agent);
    tracing::warn!(
        client_type = client_type,
        "Direct JSON parsing failed, trying base64 decode fallback"
    );
    match decode_base64(body.clone()) {
        Ok(decoded) => match FlagRequest::from_bytes(decoded.clone()) {
            Ok(request) => {
                inc(
                    FLAG_REQUEST_KLUDGE_COUNTER,
                    &[
                        ("type".to_string(), "base64_fallback_success".to_string()),
                        ("client_type".to_string(), client_type.to_string()),
                    ],
                    1,
                );
                tracing::info!(
                    client_type = client_type,
                    "Successfully parsed request after base64 fallback decoding"
                );
                return Ok((request, decoded));
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
    user_agent: Option<&str>,
) -> Result<(FlagRequest, Bytes), FlagError> {
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
        // Include client_type to help identify which SDKs are sending malformed data
        let client_type = UserAgentInfo::client_type_label_from_raw(user_agent);
        inc(
            FLAG_REQUEST_KLUDGE_COUNTER,
            &[
                ("type".to_string(), "missing_data_prefix".to_string()),
                ("client_type".to_string(), client_type.to_string()),
            ],
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

    // Parse JSON into FlagRequest. Return the decoded JSON bytes alongside
    // the parsed request so callers (e.g. body logging) don't have to redo
    // the URL-decode + base64-decode dance to recover them.
    let json_bytes = Bytes::from(json_str.into_bytes());
    let request = serde_json::from_slice(&json_bytes).map_err(|e| {
        tracing::warn!("failed to parse JSON: {}", e);
        FlagError::RequestDecodingError("invalid JSON structure".into())
    })?;
    Ok((request, json_bytes))
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

        let (request, decoded) = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
        // Decoded body is the post-gzip JSON, not the gzipped bytes.
        assert!(decoded.starts_with(b"{"));
        assert!(decoded.windows(11).any(|w| w == b"distinct_id"));
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

        let (request, _decoded) = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
    }

    #[test]
    fn test_gzip_bomb_rejected_with_payload_too_large() {
        // Compress 8 MiB of zeros — gzip's redundant-input case where the
        // decompressed size dwarfs the compressed size. Decompresses to
        // 8 MiB, which is well over MAX_FLAGS_DECOMPRESSED_BYTES (4 MiB).
        let bomb = vec![0u8; 8 * 1024 * 1024];
        let compressed = common_compression::compress_gzip(&bomb).unwrap();
        assert!(
            compressed.len() < 100_000,
            "bomb should compress small (got {} bytes)",
            compressed.len()
        );

        let mut headers = HeaderMap::new();
        headers.insert("content-encoding", "gzip".parse().unwrap());
        let query = FlagsQueryParams::default();

        let result = decode_request(&headers, Bytes::from(compressed), &query);
        match result {
            Err(FlagError::PayloadTooLarge {
                decompressed,
                limit,
            }) => {
                assert_eq!(limit, MAX_FLAGS_DECOMPRESSED_BYTES);
                assert!(
                    decompressed > MAX_FLAGS_DECOMPRESSED_BYTES,
                    "decompressed size {decompressed} should exceed cap {MAX_FLAGS_DECOMPRESSED_BYTES}"
                );
            }
            other => panic!("expected PayloadTooLarge, got {other:?}"),
        }
    }

    #[test]
    fn test_gzip_under_cap_still_works() {
        // A 1 MiB body is well over typical /flags traffic but still inside
        // the 4 MiB cap, so it must round-trip cleanly.
        let mut large_payload = String::from(r#"{"distinct_id": "u", "token": "t", "padding": ""#);
        large_payload.push_str(&"a".repeat(1024 * 1024));
        large_payload.push_str(r#""}"#);

        let gzipped = create_gzipped_json(&large_payload);
        let mut headers = HeaderMap::new();
        headers.insert("content-encoding", "gzip".parse().unwrap());
        let query = FlagsQueryParams::default();

        let result = decode_request(&headers, gzipped, &query);
        assert!(
            result.is_ok(),
            "1 MiB request body should decode under the 4 MiB cap, got {:?}",
            result.err()
        );
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

        let (request, _decoded) = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
    }

    #[test]
    fn test_uncompressed_json_still_works() {
        let json_data = r#"{"distinct_id": "test", "token": "test_token"}"#;
        let body = Bytes::from(json_data);

        let headers = HeaderMap::new();
        let query = FlagsQueryParams::default();

        let result = decode_request(&headers, body.clone(), &query);
        assert!(result.is_ok());

        let (request, decoded) = result.unwrap();
        assert_eq!(request.distinct_id, Some("test".to_string()));
        assert_eq!(request.token, Some("test_token".to_string()));
        // Plain-JSON path returns the input bytes unchanged.
        assert_eq!(decoded, body);
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

        let (request, decoded) = result.unwrap();
        assert_eq!(request.distinct_id, Some("user".to_string()));
        assert_eq!(request.token, Some("test".to_string()));
        // Base64 fallback returns the *decoded* JSON bytes, not the base64 string.
        assert!(decoded.starts_with(b"{"));
        assert!(!decoded.windows(7).any(|w| w == b"eyJ0b2t"));
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

    mod client_type_label_tests {
        use super::*;
        use rstest::rstest;

        #[rstest]
        #[case(Some("posthog-js/1.88.0"), "posthog-js")]
        #[case(Some("posthog-android/3.1.0"), "posthog-android")]
        #[case(Some("posthog-ios/3.0.0"), "posthog-ios")]
        #[case(Some("posthog-react-native/2.5.0"), "posthog-react-native")]
        #[case(Some("posthog-flutter/4.0.0"), "posthog-flutter")]
        #[case(Some("posthog-python/1.4.0"), "posthog-python")]
        #[case(Some("posthog-ruby/2.0.0"), "posthog-ruby")]
        #[case(Some("posthog-ruby2.0.0"), "posthog-ruby")]
        #[case(Some("posthog-php/3.0.0"), "posthog-php")]
        #[case(Some("posthog-java/1.0.0"), "posthog-java")]
        #[case(Some("posthog-go/0.1.0"), "posthog-go")]
        #[case(Some("posthog-node/2.2.0"), "posthog-node")]
        #[case(Some("posthog-dotnet/1.0.0"), "posthog-dotnet")]
        #[case(Some("posthog-elixir/0.2.0"), "posthog-elixir")]
        #[case(Some("posthog-rs/0.10.0"), "posthog-rs")]
        #[case(
            Some("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
            "browser"
        )]
        #[case(
            Some("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/91.0.4472.124"),
            "browser"
        )]
        #[case(Some("Mozilla/5.0 (X11; Linux x86_64) Firefox/89.0"), "browser")]
        #[case(Some("curl/7.68.0"), "curl")]
        #[case(Some("python-requests/2.28.0"), "python-requests")]
        #[case(Some("custom-client/1.0"), "other")]
        #[case(Some(""), "unknown")]
        #[case(None, "unknown")]
        fn test_client_type_label(#[case] user_agent: Option<&str>, #[case] expected: &str) {
            assert_eq!(
                UserAgentInfo::client_type_label_from_raw(user_agent),
                expected
            );
        }
    }
}
