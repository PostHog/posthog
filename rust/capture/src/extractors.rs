//! Custom extractors for request body handling
//!
//! This module provides utilities for extracting request bodies with
//! configurable timeouts to prevent slow clients from holding connections.

use std::time::Duration;

use axum::body::Body;
use bytes::{BufMut, Bytes, BytesMut};
use futures::StreamExt;
use tracing::warn;

use crate::api::CaptureError;

const METRIC_BODY_READ_TIMEOUT: &str = "capture_body_read_timeout_total";

/// Extract body bytes from a streaming Body with a per-chunk timeout.
///
/// If `chunk_timeout` is None, reads the entire body without timeout (existing behavior).
/// If `chunk_timeout` is Some, each chunk read is wrapped in a timeout. If no data
/// arrives within the timeout window, returns `CaptureError::BodyReadTimeout`.
///
/// The `limit` parameter enforces a maximum body size during streaming.
pub async fn extract_body_with_timeout(
    body: Body,
    limit: usize,
    chunk_timeout: Option<Duration>,
    path: &str,
) -> Result<Bytes, CaptureError> {
    let mut stream = body.into_data_stream();
    let mut buf = BytesMut::with_capacity(std::cmp::min(limit, 64 * 1024)); // Start with 64KB or limit

    loop {
        let chunk_result = match chunk_timeout {
            Some(timeout) => {
                match tokio::time::timeout(timeout, stream.next()).await {
                    Ok(result) => result,
                    Err(_elapsed) => {
                        // Timeout waiting for next chunk
                        metrics::counter!(METRIC_BODY_READ_TIMEOUT, "path" => path.to_string())
                            .increment(1);
                        warn!(
                            path = path,
                            bytes_received = buf.len(),
                            timeout_ms = timeout.as_millis() as u64,
                            "Body read timeout: client stopped sending data"
                        );
                        return Err(CaptureError::BodyReadTimeout);
                    }
                }
            }
            None => stream.next().await,
        };

        match chunk_result {
            Some(Ok(chunk)) => {
                // Check size limit before appending
                if buf.len() + chunk.len() > limit {
                    return Err(CaptureError::EventTooBig(format!(
                        "Request body exceeds limit of {limit} bytes"
                    )));
                }
                buf.put(chunk);
            }
            Some(Err(e)) => {
                return Err(CaptureError::RequestDecodingError(format!(
                    "Error reading request body: {e}"
                )));
            }
            None => {
                // Stream complete
                break;
            }
        }
    }

    Ok(buf.freeze())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use bytes::Bytes;
    use futures::stream;
    use std::time::Duration;

    #[tokio::test]
    async fn test_extract_body_no_timeout() {
        let body = Body::from("hello world");
        let result = extract_body_with_timeout(body, 1024, None, "/test").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Bytes::from("hello world"));
    }

    #[tokio::test]
    async fn test_extract_body_with_timeout_success() {
        let body = Body::from("hello world");
        let timeout = Some(Duration::from_secs(5));
        let result = extract_body_with_timeout(body, 1024, timeout, "/test").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Bytes::from("hello world"));
    }

    #[tokio::test]
    async fn test_extract_body_exceeds_limit() {
        let body = Body::from("hello world this is a long message");
        let result = extract_body_with_timeout(body, 10, None, "/test").await;
        assert!(matches!(result, Err(CaptureError::EventTooBig(_))));
    }

    #[tokio::test]
    async fn test_extract_body_timeout_fires() {
        // Create a stream that yields one chunk then stalls forever
        let chunks: Vec<Result<Bytes, std::io::Error>> = vec![Ok(Bytes::from("partial"))];
        let slow_stream = stream::iter(chunks).chain(stream::pending());
        let body = Body::from_stream(slow_stream);

        let timeout = Some(Duration::from_millis(50));
        let result = extract_body_with_timeout(body, 1024, timeout, "/test").await;

        assert!(matches!(result, Err(CaptureError::BodyReadTimeout)));
    }

    #[tokio::test]
    async fn test_extract_body_empty() {
        let body = Body::empty();
        let result = extract_body_with_timeout(body, 1024, None, "/test").await;
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }
}
