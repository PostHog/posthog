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
use common_metrics::inc;
use flate2::read::GzDecoder;
use percent_encoding::percent_decode;
use std::io::Read;

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
            FlagRequest::from_bytes(decoded_body)
        }
        "application/x-www-form-urlencoded" => decode_form_data(body, query.compression),
        _ => Err(FlagError::RequestDecodingError(format!(
            "unsupported content type: {content_type}"
        ))),
    }
}

fn decode_body(
    body: Bytes,
    compression: Option<Compression>,
    headers: &HeaderMap,
) -> Result<Bytes, FlagError> {
    // First try explicit compression parameter; Android doesn't send this but other clients do.
    if let Some(compression) = compression {
        return match compression {
            Compression::Gzip => decompress_gzip(body),
            Compression::Base64 => decode_base64(body),
            Compression::Unsupported => Err(FlagError::RequestDecodingError(
                "Unsupported compression type".to_string(),
            )),
        };
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
    let mut decoder = GzDecoder::new(&compressed[..]);
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed).map_err(|e| {
        tracing::debug!("gzip decompression failed: {}", e);
        FlagError::RequestDecodingError(format!("gzip decompression failed: {}", e))
    })?;
    Ok(Bytes::from(decompressed))
}

fn decode_base64(body: Bytes) -> Result<Bytes, FlagError> {
    let decoded = general_purpose::STANDARD
        .decode(body)
        .map_err(|e| FlagError::RequestDecodingError(format!("Base64 decoding error: {}", e)))?;
    Ok(Bytes::from(decoded))
}

pub fn decode_form_data(
    body: Bytes,
    compression: Option<Compression>,
) -> Result<FlagRequest, FlagError> {
    // Convert bytes to string first so we can manipulate it
    let form_data = String::from_utf8(body.to_vec()).map_err(|e| {
        tracing::debug!("Invalid UTF-8 in form data: {}", e);
        FlagError::RequestDecodingError("Invalid UTF-8 in form data".into())
    })?;

    // URL decode the string if needed
    let decoded_form = percent_decode(form_data.as_bytes())
        .decode_utf8()
        .map_err(|e| {
            tracing::debug!("Failed to URL decode form data: {}", e);
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
            return Err(FlagError::RequestDecodingError(
                "Gzip compression not supported for form-urlencoded data".into(),
            ))
        }
        Some(Compression::Base64) | None => decode_base64(Bytes::from(cleaned_base64))?,
        Some(Compression::Unsupported) => {
            return Err(FlagError::RequestDecodingError(
                "Unsupported compression type".into(),
            ))
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
        tracing::debug!("failed to parse JSON: {}", e);
        FlagError::RequestDecodingError("invalid JSON structure".into())
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::types::{Compression, FlagsQueryParams};
    use axum::http::HeaderMap;
    use flate2::write::GzEncoder;
    use flate2::Compression as FlateCompression;
    use std::io::Write;

    fn create_gzipped_json(json_data: &str) -> Bytes {
        let mut encoder = GzEncoder::new(Vec::new(), FlateCompression::default());
        encoder.write_all(json_data.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
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
}
