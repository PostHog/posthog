//! Shared gRPC-over-HTTP helpers used by the proxy, the leader backend,
//! and the stash handler: error responses built directly, and the unary
//! frame codec for the one request the router decodes — all without
//! going through a tonic codec.

use bytes::Bytes;
use http::HeaderValue;
use http_body_util::{BodyExt, Empty};
use prost::Message;
use tonic::body::BoxBody;
use tonic::Code;

/// Decode a unary gRPC request frame. Compressed frames are refused
/// rather than inflated: the one decoded method's client never compresses.
#[allow(clippy::result_large_err)]
pub(crate) fn decode_unary_frame<T: Message + Default>(
    frame: &[u8],
) -> Result<T, http::Response<BoxBody>> {
    let Some((prefix, message)) = frame.split_first_chunk::<5>() else {
        return Err(grpc_error_response(
            Code::InvalidArgument,
            "gRPC frame is shorter than its 5-byte prefix",
        ));
    };
    if prefix[0] != 0 {
        return Err(grpc_error_response(
            Code::Unimplemented,
            "compressed request frames are not decoded by the router",
        ));
    }
    let declared = u32::from_be_bytes([prefix[1], prefix[2], prefix[3], prefix[4]]) as usize;
    if declared != message.len() {
        return Err(grpc_error_response(
            Code::InvalidArgument,
            &format!(
                "gRPC frame declares {declared} message bytes but carries {}",
                message.len()
            ),
        ));
    }
    T::decode(message).map_err(|e| {
        grpc_error_response(
            Code::InvalidArgument,
            &format!("malformed request message: {e}"),
        )
    })
}

/// Encode a message as an uncompressed unary gRPC frame.
pub(crate) fn encode_unary_frame<T: Message>(message: &T) -> Bytes {
    let len = message.encoded_len();
    let mut frame = Vec::with_capacity(5 + len);
    frame.push(0);
    frame.extend_from_slice(&(len as u32).to_be_bytes());
    message
        .encode(&mut frame)
        .expect("a Vec<u8> never runs out of capacity");
    Bytes::from(frame)
}

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

/// The `grpc-status` code carried in a response's HTTP headers, if any.
/// Only trailers-only (error) responses expose their status here; a
/// successful response carries its status in the trailers and yields
/// `None`.
pub(crate) fn grpc_status_code(response: &http::Response<BoxBody>) -> Option<i32> {
    response
        .headers()
        .get("grpc-status")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<i32>().ok())
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

    /// The codec must round-trip the one message the router decodes, and
    /// refuse the frames it cannot read rather than forward garbage.
    #[test]
    fn unary_frame_codec_round_trips_and_fails_closed() {
        use personhog_proto::personhog::types::v1::{ReleaseFenceItem, ReleaseFencesRequest};

        let request = ReleaseFencesRequest {
            team_id: 7,
            op_id: "op".to_string(),
            outcome: 1,
            persons: vec![ReleaseFenceItem {
                person_id: 42,
                person_uuid: "u".to_string(),
                sealed_version: Some(0),
                created_at: 1,
            }],
        };
        let frame = encode_unary_frame(&request);
        let decoded: ReleaseFencesRequest = decode_unary_frame(&frame).expect("round trip");
        assert_eq!(decoded, request);

        let mut compressed = frame.to_vec();
        compressed[0] = 1;
        let refused = decode_unary_frame::<ReleaseFencesRequest>(&compressed).unwrap_err();
        assert_eq!(grpc_status_code(&refused), Some(Code::Unimplemented as i32));

        let truncated = &frame[..frame.len() - 1];
        let refused = decode_unary_frame::<ReleaseFencesRequest>(truncated).unwrap_err();
        assert_eq!(
            grpc_status_code(&refused),
            Some(Code::InvalidArgument as i32)
        );
    }
}
