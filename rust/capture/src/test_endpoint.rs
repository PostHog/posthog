use std::{io::Read, ops::Deref};

use axum::{
    debug_handler,
    extract::{MatchedPath, Query, State},
    http::{HeaderMap, Method},
    Json,
};
use axum_client_ip::InsecureClientIp;
use base64::Engine;
use bytes::{Buf, Bytes};
use flate2::bufread::GzDecoder;
use tracing::error;

use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    router,
    utils::extract_and_verify_token,
    v0_request::{Compression, EventFormData, EventQuery, RawRequest, GZIP_MAGIC_NUMBERS},
};

// These metrics are only used in the test paths below
pub const REQUEST_SEEN: &str = "capture_test_request_seen";
pub const COMPRESSION_TYPE: &str = "capture_test_compression_type";
pub const CONTENT_HEADER_TYPE: &str = "capture_test_content_header_type";
pub const REQUEST_OUTCOME: &str = "capture_test_request_outcome";
pub const GZIP_FOUND: &str = "capture_test_gzip_found";
pub const GZIP_FAILED: &str = "capture_test_gzip_failed";
pub const UTF8_FAILED: &str = "capture_test_utf8_failed";

// A handler that does nothing except try to parse the request, and produce a tonne of metrics
// about failures. Once python capture is dead, we should remove file entirely.
#[debug_handler]
pub async fn test_black_hole(
    state: State<router::State>,
    _ip: InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    _method: Method,
    _path: MatchedPath,
    body: Bytes,
) -> Result<Json<CaptureResponse>, CaptureError> {
    metrics::counter!(REQUEST_SEEN).increment(1);
    let comp = match meta.compression {
        Some(Compression::Gzip) => String::from("gzip"),
        Some(Compression::Unsupported) => String::from("unsupported"),
        _ => String::from("unknown"),
    };

    metrics::counter!(COMPRESSION_TYPE, "type" => comp.clone()).increment(1);

    // First stage is just to try and parse the request
    let request = match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/x-www-form-urlencoded" => {
            metrics::counter!(CONTENT_HEADER_TYPE, "type" => "form").increment(1);

            let input: EventFormData = match serde_urlencoded::from_bytes(body.deref()) {
                Ok(input) => input,
                Err(e) => {
                    error!("failed to decode form data: {}", e);
                    metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "form_data_decoding_error").increment(1);
                    return Err(CaptureError::RequestDecodingError(String::from(
                        "missing data field",
                    )));
                }
            };
            if input.data.is_none() || input.data.as_ref().is_some_and(|d| d.is_empty()) {
                error!("unexpected missing EventFormData payload");
                return Err(CaptureError::EmptyPayload);
            }

            let payload = match base64::engine::general_purpose::STANDARD
                .decode(input.data.unwrap())
            {
                Ok(payload) => payload,
                Err(e) => {
                    error!("failed to decode form data: {}", e);
                    metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "base64_form_decode_error").increment(1);
                    return Err(CaptureError::RequestDecodingError(String::from(
                        "failed to decode base64",
                    )));
                }
            };
            from_bytes(payload.into(), state.event_size_limit, comp)
        }
        ct => {
            // TODO - I'm a little worried about label count exploding here, but if it does we can always
            // turn this off.
            metrics::counter!(CONTENT_HEADER_TYPE, "type" => ct.to_string()).increment(1);
            from_bytes(body, state.event_size_limit, comp)
        }
    };

    let request = match request {
        Ok(r) => r,
        Err(e) => {
            match e {
                CaptureError::RequestDecodingError(_) => {
                    metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "request_decoding")
                        .increment(1);
                }
                CaptureError::RequestParsingError(_) => {
                    metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "request_parsing")
                        .increment(1);
                }
                CaptureError::TokenValidationError(_) => {
                    metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "token_validation")
                        .increment(1);
                }
                e => {
                    metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => e.to_string())
                        .increment(1);
                }
            };
            // We don't *really* care about returning accurate errors here
            return Ok(Json(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            }));
        }
    };

    // Now, token handling
    let maybe_batch_token = request.get_batch_token();
    let events = request.events("/i/v0/e").unwrap();
    let t = match extract_and_verify_token(&events, maybe_batch_token) {
        Ok(t) => Ok(t),
        Err(CaptureError::NoTokenError) => {
            metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "no_token")
                .increment(1);
            Err(CaptureError::NoTokenError)
        }
        Err(CaptureError::MultipleTokensError) => {
            metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "multiple_tokens")
                .increment(1);
            Err(CaptureError::MultipleTokensError)
        }
        Err(CaptureError::TokenValidationError(e)) => {
            metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "token_validation", "error" => e.to_string())
                .increment(1);
            Err(CaptureError::TokenValidationError(e))
        }
        Err(e) => {
            metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "unknown_token_error")
                .increment(1);
            Err(e)
        }
    };

    // We can just bail out at this point, since we track if t is an error above.
    t?;

    if events.is_empty() {
        metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "empty_batch")
            .increment(1);
        return Err(CaptureError::EmptyBatch);
    }

    // Check every event has a distinct id. This is the last piece of data validation capture does.
    for event in events {
        match event.extract_distinct_id() {
            Some(_) => {}
            None => {
                metrics::counter!(REQUEST_OUTCOME, "outcome" => "failure", "reason" => "missing_distinct_id")
                    .increment(1);
                return Err(CaptureError::MissingDistinctId);
            }
        }
    }

    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    }))
}

pub fn from_bytes(bytes: Bytes, limit: usize, comp: String) -> Result<RawRequest, CaptureError> {
    let payload = if bytes.starts_with(&GZIP_MAGIC_NUMBERS) {
        metrics::counter!(GZIP_FOUND, "comp" => comp.clone()).increment(1);
        let len = bytes.len();
        let mut zipstream = GzDecoder::new(bytes.reader());
        let chunk = &mut [0; 1024];
        let mut buf = Vec::with_capacity(len);
        loop {
            let got = match zipstream.read(chunk) {
                Ok(got) => got,
                Err(_) => {
                    metrics::counter!(GZIP_FAILED, "reason" => "read_fail", "comp" => comp.clone())
                        .increment(1);
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
                metrics::counter!(GZIP_FAILED, "reason" => "too_big", "comp" => comp.clone())
                    .increment(1);
                return Err(CaptureError::EventTooBig(format!(
                    "Event or batch exceeded {limit} during unzipping",
                )));
            }
        }
        match String::from_utf8(buf) {
            Ok(s) => s,
            Err(_) => {
                metrics::counter!(UTF8_FAILED, "input" => "gzip", "comp" => comp.clone())
                    .increment(1);
                return Err(CaptureError::RequestDecodingError(String::from(
                    "invalid gzip data",
                )));
            }
        }
    } else {
        let s = String::from_utf8(bytes.into()).map_err(|_| {
            metrics::counter!(UTF8_FAILED, "input" => "plain", "comp" => comp.clone()).increment(1);
            CaptureError::RequestDecodingError(String::from("invalid body encoding"))
        })?;
        if s.len() > limit {
            return Err(CaptureError::EventTooBig(format!(
                "Event or batch exceeded {limit}, wasn't compressed",
            )));
        }
        s
    };

    match serde_json::from_str::<RawRequest>(&payload) {
        Ok(res) => Ok(res),
        Err(e) => Err(CaptureError::RequestParsingError(e.to_string())),
    }
}
