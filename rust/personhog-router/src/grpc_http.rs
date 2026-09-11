//! Shared gRPC-over-HTTP helpers used by the proxy, the leader backend,
//! and the stash handler: error responses built directly, and the unary
//! codec for the batch requests the router splits and the responses it
//! merges — all without going through a tonic codec.

use bytes::Bytes;
use http::HeaderValue;
use http_body::Frame;
use http_body_util::{BodyExt, Empty, StreamBody};
use prost::Message;
use tonic::body::BoxBody;
use tonic::Code;

/// Decode a unary gRPC frame. Compressed frames are refused rather than
/// inflated: the decoded methods' client never compresses, and the leader
/// never compresses a response.
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
            Code::InvalidArgument,
            "compressed frames are not decoded by the router",
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
    T::decode(message)
        .map_err(|e| grpc_error_response(Code::InvalidArgument, &format!("malformed message: {e}")))
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

/// Read a unary gRPC response to its end and decode its message. A status
/// other than OK comes back as an error response with that same status,
/// so the caller answers what the leader answered. The status is read from
/// the trailers, where a success carries it, or from the headers of a
/// trailers-only error.
pub(crate) async fn decode_unary_response<T: Message + Default>(
    response: http::Response<BoxBody>,
    max_bytes: usize,
) -> Result<T, http::Response<BoxBody>> {
    let (parts, mut body) = response.into_parts();
    let mut frame_bytes: Vec<u8> = Vec::new();
    let mut trailers: Option<http::HeaderMap> = None;
    while let Some(frame) = body.frame().await {
        let frame = frame.map_err(|e| {
            grpc_error_response(
                Code::Internal,
                &format!("failed to read leader response: {e}"),
            )
        })?;
        match frame.into_data() {
            Ok(data) => {
                if frame_bytes.len() + data.len() > max_bytes {
                    return Err(grpc_error_response(
                        Code::ResourceExhausted,
                        &format!("leader response larger than max ({max_bytes} bytes)"),
                    ));
                }
                frame_bytes.extend_from_slice(&data);
            }
            Err(frame) => {
                if let Ok(map) = frame.into_trailers() {
                    trailers = Some(map);
                }
            }
        }
    }
    let status_headers = trailers.as_ref().unwrap_or(&parts.headers);
    let code = status_headers
        .get("grpc-status")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<i32>().ok())
        .filter(|code| *code != 0);
    if let Some(code) = code {
        return Err(grpc_status_response(
            code,
            status_headers.get("grpc-message").cloned(),
        ));
    }
    decode_unary_frame(&frame_bytes)
}

/// A successful unary gRPC response carrying `message`: the frame as its
/// body and an OK status in its trailers, the shape a tonic client reads.
pub(crate) fn encode_unary_response<T: Message>(message: &T) -> http::Response<BoxBody> {
    let mut trailers = http::HeaderMap::new();
    trailers.insert("grpc-status", HeaderValue::from(Code::Ok as i32));
    let frames = futures::stream::iter([
        Ok::<_, tonic::Status>(Frame::data(encode_unary_frame(message))),
        Ok(Frame::trailers(trailers)),
    ]);
    let mut response = http::Response::new(BoxBody::new(StreamBody::new(frames)));
    response
        .headers_mut()
        .insert("content-type", HeaderValue::from_static("application/grpc"));
    response
}

/// Build a gRPC error response carrying `code` and `message` in the
/// `grpc-status`/`grpc-message` headers with an empty body.
pub(crate) fn grpc_error_response(code: Code, message: &str) -> http::Response<BoxBody> {
    let encoded = if message.is_empty() {
        None
    } else {
        percent_encode_grpc(message).parse::<HeaderValue>().ok()
    };
    grpc_status_response(code as i32, encoded)
}

/// A trailers-only response carrying a status verbatim: `code` and an
/// already percent-encoded `grpc-message`, as read off another response.
fn grpc_status_response(code: i32, message: Option<HeaderValue>) -> http::Response<BoxBody> {
    let body = BoxBody::new(Empty::<Bytes>::new().map_err(|never| match never {}));
    let mut response = http::Response::new(body);
    response
        .headers_mut()
        .insert("content-type", HeaderValue::from_static("application/grpc"));
    response
        .headers_mut()
        .insert("grpc-status", HeaderValue::from(code));
    if let Some(message) = message {
        response.headers_mut().insert("grpc-message", message);
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
        assert_eq!(
            grpc_status_code(&refused),
            Some(Code::InvalidArgument as i32)
        );

        let truncated = &frame[..frame.len() - 1];
        let refused = decode_unary_frame::<ReleaseFencesRequest>(truncated).unwrap_err();
        assert_eq!(
            grpc_status_code(&refused),
            Some(Code::InvalidArgument as i32)
        );
    }

    /// The merged response the router hands back must read as a success
    /// through the same codec, and a status the leader put in its trailers
    /// must come back as that status, not as a decode failure.
    #[tokio::test]
    async fn unary_response_codec_round_trips_and_keeps_trailer_status() {
        use personhog_proto::personhog::types::v1::{FencePersonsResponse, FencedPersonSeal};

        let message = FencePersonsResponse {
            sealed: vec![FencedPersonSeal {
                person_id: 42,
                version: 3,
                created_at: 1,
            }],
            not_found: vec![7],
        };
        let response = encode_unary_response(&message);
        assert!(!is_grpc_error_response(&response));
        let decoded: FencePersonsResponse = decode_unary_response(response, 1 << 20)
            .await
            .expect("round trip");
        assert_eq!(decoded, message);

        let mut trailers = http::HeaderMap::new();
        trailers.insert("grpc-status", HeaderValue::from(Code::Unavailable as i32));
        trailers.insert("grpc-message", HeaderValue::from_static("leader%20down"));
        let frames = futures::stream::iter([
            Ok::<_, tonic::Status>(Frame::data(encode_unary_frame(&message))),
            Ok(Frame::trailers(trailers)),
        ]);
        let failed = http::Response::new(BoxBody::new(StreamBody::new(frames)));
        let refused = decode_unary_response::<FencePersonsResponse>(failed, 1 << 20)
            .await
            .unwrap_err();
        assert_eq!(grpc_status_code(&refused), Some(Code::Unavailable as i32));
        assert_eq!(
            refused.headers().get("grpc-message").unwrap(),
            "leader%20down",
            "the leader's message travels verbatim, not re-encoded"
        );
    }
}
