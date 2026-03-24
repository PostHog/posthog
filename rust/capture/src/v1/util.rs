use std::time::Duration;

use axum::body::Body;
use bytes::{BufMut, Bytes, BytesMut};
use futures::StreamExt;

use crate::v1::Error;

const METRIC_BODY_READ_TIMEOUT: &str = "capture_v1_body_read_timeout_total";

/// Extract body bytes from a streaming Body with a per-chunk timeout.
///
/// If `chunk_timeout` is None, reads the entire body without timeout.
/// If `chunk_timeout` is Some, each chunk read is wrapped in a timeout. If no data
/// arrives within the timeout window, returns `Error::BodyReadTimeout`.
///
/// The `payload_size_limit` parameter enforces a maximum body size during streaming.
pub async fn extract_body_with_timeout(
    body: Body,
    payload_size_limit: usize,
    chunk_timeout: Option<Duration>,
    chunk_size_kb: usize,
    path: &str,
) -> Result<Bytes, Error> {
    let mut stream = body.into_data_stream();
    let mut buf = BytesMut::with_capacity(std::cmp::min(payload_size_limit, chunk_size_kb * 1024));

    loop {
        let chunk_result = match chunk_timeout {
            Some(timeout) => match tokio::time::timeout(timeout, stream.next()).await {
                Ok(result) => result,
                Err(_elapsed) => {
                    metrics::counter!(METRIC_BODY_READ_TIMEOUT, "path" => path.to_string())
                        .increment(1);
                    return Err(Error::BodyReadTimeout(buf.len()));
                }
            },
            None => stream.next().await,
        };

        match chunk_result {
            Some(Ok(chunk)) => {
                if buf.len() + chunk.len() > payload_size_limit {
                    return Err(Error::PayloadTooLarge(format!(
                        "Request body exceeds limit of {payload_size_limit} bytes"
                    )));
                }
                buf.put(chunk);
            }
            Some(Err(e)) => {
                return Err(Error::RequestDecodingError(format!(
                    "Error reading request body: {e:#}"
                )));
            }
            None => break,
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

    const TEST_CHUNK_SIZE_KB: usize = 256;

    #[tokio::test]
    async fn extract_body_no_timeout() {
        let body = Body::from("hello world");
        let result = extract_body_with_timeout(body, 1024, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Bytes::from("hello world"));
    }

    #[tokio::test]
    async fn extract_body_with_timeout_success() {
        let body = Body::from("hello world");
        let timeout = Some(Duration::from_secs(5));
        let result =
            extract_body_with_timeout(body, 1024, timeout, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Bytes::from("hello world"));
    }

    #[tokio::test]
    async fn extract_body_exceeds_limit() {
        let body = Body::from("hello world this is a long message");
        let result = extract_body_with_timeout(body, 10, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(matches!(result, Err(Error::PayloadTooLarge(_))));
    }

    #[tokio::test]
    async fn extract_body_timeout_fires() {
        let chunks: Vec<Result<Bytes, std::io::Error>> = vec![Ok(Bytes::from("partial"))];
        let slow_stream = stream::iter(chunks).chain(stream::pending());
        let body = Body::from_stream(slow_stream);

        let timeout = Some(Duration::from_millis(50));
        let result =
            extract_body_with_timeout(body, 1024, timeout, TEST_CHUNK_SIZE_KB, "/test").await;

        assert!(matches!(result, Err(Error::BodyReadTimeout(_))));
    }

    #[tokio::test]
    async fn extract_body_empty() {
        let body = Body::empty();
        let result = extract_body_with_timeout(body, 1024, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }
}
