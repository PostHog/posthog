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
            let decoded_body = decode_body(body, query.compression)?;
            FlagRequest::from_bytes(decoded_body)
        }
        "application/x-www-form-urlencoded" => decode_form_data(body, query.compression),
        _ => Err(FlagError::RequestDecodingError(format!(
            "unsupported content type: {content_type}"
        ))),
    }
}

fn decode_body(body: Bytes, compression: Option<Compression>) -> Result<Bytes, FlagError> {
    match compression {
        Some(Compression::Gzip) => decompress_gzip(body),
        Some(Compression::Base64) => decode_base64(body),
        Some(Compression::Unsupported) => Err(FlagError::RequestDecodingError(
            "Unsupported compression type".to_string(),
        )),
        None => Ok(body),
    }
}

fn decompress_gzip(compressed: Bytes) -> Result<Bytes, FlagError> {
    let mut decoder = GzDecoder::new(&compressed[..]);
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed).map_err(|e| {
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
    // Convert bytes to string first so we can manipluate it
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
