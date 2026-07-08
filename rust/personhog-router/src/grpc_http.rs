//! Shared gRPC-over-HTTP response helpers used by the proxy, the leader
//! backend, and the stash handler to construct error responses directly,
//! without going through a tonic codec.

use bytes::Bytes;
use http::HeaderValue;
use http_body_util::{BodyExt, Empty};
use tonic::body::BoxBody;
use tonic::Code;

/// Build a gRPC error response carrying `code` and `message` in the
/// `grpc-status`/`grpc-message` headers with an empty body.
pub(crate) fn grpc_error_response(code: Code, message: &str) -> http::Response<BoxBody> {
    let body = BoxBody::new(Empty::<Bytes>::new().map_err(|never| match never {}));
    let mut response = http::Response::new(body);
    response
        .headers_mut()
        .insert("content-type", HeaderValue::from_static("application/grpc"));
    response
        .headers_mut()
        .insert("grpc-status", HeaderValue::from(code as i32));
    if !message.is_empty() {
        let encoded = percent_encode_grpc(message);
        if let Ok(val) = encoded.parse::<HeaderValue>() {
            response.headers_mut().insert("grpc-message", val);
        }
    }
    response
}

/// Whether a response carries a non-OK `grpc-status` in its HTTP headers.
/// gRPC errors are trailers-only responses — a single HEADERS frame — so
/// their status is visible here without polling the body; a successful
/// response carries its status in the trailers and reads as not-an-error.
pub(crate) fn is_grpc_error_response(response: &http::Response<BoxBody>) -> bool {
    response
        .headers()
        .get("grpc-status")
        .and_then(|v| v.to_str().ok())
        .is_some_and(|s| s != "0")
}

/// Percent-encode a gRPC status message so it is safe to carry in the
/// ASCII-only `grpc-message` header.
fn percent_encode_grpc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => {
                const HEX: &[u8; 16] = b"0123456789ABCDEF";
                out.push('%');
                out.push(HEX[(b >> 4) as usize] as char);
                out.push(HEX[(b & 0xf) as usize] as char);
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// An error response is flagged by `is_grpc_error_response` while an
    /// OK status is not — this drives the proxy's error counter and the
    /// stash drain's outcome label.
    #[test]
    fn grpc_status_classification() {
        assert!(!is_grpc_error_response(&grpc_error_response(Code::Ok, "")));
        assert!(is_grpc_error_response(&grpc_error_response(
            Code::NotFound,
            "not found"
        )));
    }

    #[test]
    fn grpc_error_response_sets_status_and_message() {
        let response = grpc_error_response(Code::NotFound, "person not found");
        assert_eq!(
            response.headers().get("grpc-status").unwrap(),
            &format!("{}", Code::NotFound as i32),
        );
        let msg = response
            .headers()
            .get("grpc-message")
            .unwrap()
            .to_str()
            .unwrap();
        assert!(msg.contains("person"));
    }

    #[test]
    fn percent_encode_grpc_preserves_safe_chars() {
        assert_eq!(percent_encode_grpc("hello"), "hello");
        assert_eq!(percent_encode_grpc("a-b_c.d~e"), "a-b_c.d~e");
    }

    #[test]
    fn percent_encode_grpc_encodes_special_chars() {
        assert_eq!(percent_encode_grpc("hello world"), "hello%20world");
        assert_eq!(percent_encode_grpc("a/b"), "a%2Fb");
        assert_eq!(percent_encode_grpc("a:b"), "a%3Ab");
    }
}
