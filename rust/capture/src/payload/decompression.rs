//! Payload decompression and decoding logic
//!
//! This module handles decompression of HTTP request payloads using various
//! compression formats (GZIP, LZ64) and handles legacy base64 encoding.

use std::io::prelude::*;

use bytes::{Buf, Bytes};
use flate2::read::GzDecoder;
use metrics;
use tracing::{debug, error, instrument, warn, Span};

use crate::{
    api::CaptureError,
    prometheus::report_dropped_events,
    utils::{
        decode_base64, decompress_lz64, is_likely_base64, Base64Option, MAX_PAYLOAD_SNIPPET_SIZE,
    },
    v0_request::path_is_legacy_endpoint,
};

use super::types::Compression;

pub static GZIP_MAGIC_NUMBERS: [u8; 3] = [0x1f, 0x8b, 0x08];

// Metrics constants
const METRIC_PAYLOAD_SIZE_EXCEEDED: &str = "capture_payload_size_exceeded";
const METRIC_GZIP_DECOMPRESSION_RATIO: &str = "capture_gzip_decompression_ratio";

/// Decompresses and decodes a payload based on compression hint and content detection.
/// This is shared logic used by both analytics and recording event processing.
///
/// # Arguments
/// * `bytes` - Raw compressed/encoded bytes from the HTTP request
/// * `compression` - Compression hint from query params or headers
/// * `limit` - Maximum allowed size for decompressed payload (in bytes)
/// * `path` - Request path (used for legacy endpoint detection)
///
/// # Returns
/// Decompressed UTF-8 string payload ready for JSON deserialization
#[instrument(skip_all, fields(compression, path))]
pub fn decompress_payload(
    bytes: Bytes,
    compression: Compression,
    limit: usize,
    path: &str,
) -> Result<String, CaptureError> {
    Span::current().record("compression", compression.to_string());
    Span::current().record("path", path);

    debug!(
        payload_len = bytes.len(),
        "decompress_payload: decoding payload"
    );
    metrics::histogram!("capture_raw_payload_size").record(bytes.len() as f64);

    let mut payload = if compression == Compression::Gzip || bytes.starts_with(&GZIP_MAGIC_NUMBERS)
    {
        let len = bytes.len();
        debug!(
            payload_len = len,
            "decompress_payload: matched GZIP compression"
        );

        let mut zipstream = GzDecoder::new(bytes.reader());
        let mut chunk = [0; 8192];
        let mut buf = Vec::new();
        let mut total_read = 0;

        loop {
            let got = match zipstream.read(&mut chunk) {
                Ok(got) => got,
                Err(e) => {
                    error!(
                        "decompress_payload: failed to read GZIP chunk from stream: {}",
                        e
                    );
                    return Err(CaptureError::RequestDecodingError(String::from(
                        "invalid GZIP data",
                    )));
                }
            };
            if got == 0 {
                break;
            }

            // Check size BEFORE allocation to prevent memory spikes
            if total_read + got > limit {
                error!(
                    decompressed_size = total_read + got,
                    compressed_size = len,
                    limit = limit,
                    "decompress_payload: GZIP decompression would exceed size limit"
                );

                // Metric for exceeding payload sizes
                metrics::counter!(METRIC_PAYLOAD_SIZE_EXCEEDED, "kind" => "gzip").increment(1);
                metrics::histogram!("capture_full_payload_size", "oversize" => "true")
                    .record((total_read + got) as f64);
                report_dropped_events("event_too_big", 1);

                return Err(CaptureError::EventTooBig(format!(
                    "Decompressed payload would exceed {} bytes (got {} bytes)",
                    limit,
                    total_read + got
                )));
            }

            buf.extend_from_slice(&chunk[..got]);
            total_read += got;
        }

        // Record decompression ratio metric
        if len > 0 {
            let ratio = total_read as f64 / len as f64;
            metrics::histogram!(METRIC_GZIP_DECOMPRESSION_RATIO).record(ratio);

            // Warn on potential GZIP bombs
            if ratio > 20.0 {
                warn!(
                    compressed_size = len,
                    decompressed_size = total_read,
                    ratio = ratio,
                    "High GZIP compression ratio detected - potential GZIP bomb"
                );
            }
        }

        match String::from_utf8(buf) {
            Ok(s) => s,
            Err(e) => {
                error!("decompress_payload: failed to decode gzip: {}", e);
                return Err(CaptureError::RequestDecodingError(String::from(
                    "invalid gzip data",
                )));
            }
        }
    } else if compression == Compression::LZString {
        debug!(
            payload_len = bytes.len(),
            "decompress_payload: matched LZ64 compression"
        );
        match decompress_lz64(&bytes, limit) {
            Ok(payload) => payload,
            Err(e) => {
                error!("decompress_payload: failed LZ64 decompress: {:?}", e);
                return Err(e);
            }
        }
    } else {
        debug!(
            path = path,
            payload_len = bytes.len(),
            "decompress_payload: best-effort, assuming no compression"
        );

        let s = String::from_utf8(bytes.into()).map_err(|e| {
            error!(
                valid_up_to = &e.utf8_error().valid_up_to(),
                "decompress_payload: failed to convert request payload to UTF8: {}", e
            );
            CaptureError::RequestDecodingError(String::from("invalid UTF8 in request payload"))
        })?;
        if s.len() > limit {
            error!("decompress_payload: request size limit reached");
            metrics::counter!(METRIC_PAYLOAD_SIZE_EXCEEDED, "kind" => "none").increment(1);
            metrics::histogram!("capture_full_payload_size", "oversize" => "true")
                .record(s.len() as f64);
            report_dropped_events("event_too_big", 1);
            return Err(CaptureError::EventTooBig(format!(
                "Uncompressed payload size limit {} exceeded: {}",
                limit,
                s.len(),
            )));
        }
        s
    };
    metrics::histogram!("capture_full_payload_size", "oversize" => "false")
        .record(payload.len() as f64);

    // TODO: test removing legacy special casing against /i/v0/e/ and /batch/ using mirror deploy
    if path_is_legacy_endpoint(path) {
        if is_likely_base64(payload.as_bytes(), Base64Option::Strict) {
            debug!("decompress_payload: payload still base64 after decoding step");
            payload = match decode_base64(payload.as_bytes(), "decompress_payload_after_decoding") {
                Ok(out) => match String::from_utf8(out) {
                    Ok(unwrapped_payload) => {
                        let unwrapped_size = unwrapped_payload.len();
                        if unwrapped_size > limit {
                            error!(unwrapped_size,
                                    "decompress_payload: request size limit exceeded after post-decode base64 unwrap");
                            report_dropped_events("event_too_big", 1);
                            return Err(CaptureError::EventTooBig(format!(
                                    "decompress_payload: payload size limit {limit} exceeded after post-decode base64 unwrap: {unwrapped_size}",
                                )));
                        }
                        unwrapped_payload
                    }
                    Err(e) => {
                        error!("decompress_payload: failed UTF8 conversion after post-decode base64: {}", e);
                        payload
                    }
                },
                Err(e) => {
                    error!(
                        path = path,
                        "decompress_payload: failed post-decode base64 unwrap: {}", e
                    );
                    payload
                }
            }
        } else {
            debug!("decompress_payload: payload may be LZ64 or other after decoding step");
        }
    }

    let truncate_at: usize = payload
        .char_indices()
        .nth(MAX_PAYLOAD_SNIPPET_SIZE)
        .map(|(n, _)| n)
        .unwrap_or(0);
    let payload_snippet = &payload[0..truncate_at];
    debug!(
        path = path,
        json = payload_snippet,
        "decompress_payload: event payload extracted"
    );

    Ok(payload)
}
