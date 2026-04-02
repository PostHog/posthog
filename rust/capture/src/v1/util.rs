use std::time::Duration;

use async_compression::tokio::bufread;
use axum::body::Body;
use bytes::{BufMut, Bytes, BytesMut};
use futures::StreamExt;
use tokio::io::AsyncReadExt;

use crate::v1::constants::CAPTURE_V1_BODY_READ_TIMEOUT;
use crate::v1::Error;

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
                    metrics::counter!(CAPTURE_V1_BODY_READ_TIMEOUT, "path" => path.to_string())
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

    let bytes = buf.freeze();
    if bytes.is_empty() {
        return Err(Error::EmptyBody);
    }
    Ok(bytes)
}

/// Decompress a payload using the specified Content-Encoding.
///
/// Returns bytes unchanged when `content_encoding` is `None`. For recognized
/// encodings (gzip, deflate, br, zstd), streams through the appropriate
/// `async-compression` decoder with a size limit enforced per-chunk.
pub async fn decompress_payload(
    content_encoding: Option<&str>,
    bytes: Bytes,
    payload_size_limit: usize,
    chunk_size_kb: usize,
) -> Result<Bytes, Error> {
    let encoding = match content_encoding {
        Some(enc) => enc,
        None => return Ok(bytes),
    };

    let reader = tokio::io::BufReader::new(std::io::Cursor::new(bytes));

    match encoding {
        "gzip" => {
            read_decompressed(
                bufread::GzipDecoder::new(reader),
                payload_size_limit,
                chunk_size_kb,
                encoding,
            )
            .await
        }
        "deflate" => {
            read_decompressed(
                bufread::DeflateDecoder::new(reader),
                payload_size_limit,
                chunk_size_kb,
                encoding,
            )
            .await
        }
        "br" => {
            read_decompressed(
                bufread::BrotliDecoder::new(reader),
                payload_size_limit,
                chunk_size_kb,
                encoding,
            )
            .await
        }
        "zstd" => {
            read_decompressed(
                bufread::ZstdDecoder::new(reader),
                payload_size_limit,
                chunk_size_kb,
                encoding,
            )
            .await
        }
        other => Err(Error::UnsupportedEncoding(other.to_string())),
    }
}

async fn read_decompressed(
    mut reader: impl tokio::io::AsyncRead + Unpin,
    limit: usize,
    chunk_size_kb: usize,
    encoding: &str,
) -> Result<Bytes, Error> {
    let chunk_size = chunk_size_kb * 1024;
    let mut buf = BytesMut::with_capacity(std::cmp::min(limit, chunk_size));
    loop {
        if buf.len() >= limit {
            return Err(Error::PayloadTooLarge(format!(
                "decompressed {encoding} payload exceeds limit of {limit} bytes"
            )));
        }
        let remaining = limit - buf.len();
        let to_read = std::cmp::min(remaining, chunk_size);
        buf.reserve(to_read);
        let n = reader.read_buf(&mut buf).await.map_err(|e| {
            Error::RequestDecodingError(format!("{encoding} decompression failed: {e:#}"))
        })?;
        if n == 0 {
            break;
        }
    }
    Ok(buf.freeze())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use bytes::Bytes;
    use flate2::write::{DeflateEncoder, GzEncoder};
    use flate2::Compression;
    use futures::stream;
    use std::io::Write;
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
        assert!(matches!(result, Err(Error::EmptyBody)));
    }

    // --- decompression tests ---

    fn compress_gzip(data: &[u8]) -> Vec<u8> {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
        encoder.write_all(data).unwrap();
        encoder.finish().unwrap()
    }

    fn compress_deflate(data: &[u8]) -> Vec<u8> {
        let mut encoder = DeflateEncoder::new(Vec::new(), Compression::fast());
        encoder.write_all(data).unwrap();
        encoder.finish().unwrap()
    }

    fn compress_brotli(data: &[u8]) -> Vec<u8> {
        let mut out = Vec::new();
        {
            let mut writer = brotli::CompressorWriter::new(&mut out, 4096, 6, 22);
            writer.write_all(data).unwrap();
        }
        out
    }

    fn compress_zstd(data: &[u8]) -> Vec<u8> {
        zstd::encode_all(std::io::Cursor::new(data), 3).unwrap()
    }

    #[tokio::test]
    async fn decompress_none_is_passthrough() {
        let data = Bytes::from("hello world");
        let result = decompress_payload(None, data.clone(), 4096, TEST_CHUNK_SIZE_KB).await;
        assert_eq!(result.unwrap(), data);
    }

    #[tokio::test]
    async fn decompress_gzip_valid() {
        let original = b"hello gzip world";
        let compressed = Bytes::from(compress_gzip(original));
        let result = decompress_payload(Some("gzip"), compressed, 4096, TEST_CHUNK_SIZE_KB).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn decompress_deflate_valid() {
        let original = b"hello deflate world";
        let compressed = Bytes::from(compress_deflate(original));
        let result =
            decompress_payload(Some("deflate"), compressed, 4096, TEST_CHUNK_SIZE_KB).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn decompress_br_valid() {
        let original = b"hello brotli world";
        let compressed = Bytes::from(compress_brotli(original));
        let result = decompress_payload(Some("br"), compressed, 4096, TEST_CHUNK_SIZE_KB).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn decompress_zstd_valid() {
        let original = b"hello zstd world";
        let compressed = Bytes::from(compress_zstd(original));
        let result = decompress_payload(Some("zstd"), compressed, 4096, TEST_CHUNK_SIZE_KB).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn decompress_gzip_exceeds_limit() {
        let big = vec![0u8; 64 * 1024];
        let compressed = Bytes::from(compress_gzip(&big));
        let result = decompress_payload(Some("gzip"), compressed, 1024, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::PayloadTooLarge(_))));
    }

    #[tokio::test]
    async fn decompress_deflate_exceeds_limit() {
        let big = vec![0u8; 64 * 1024];
        let compressed = Bytes::from(compress_deflate(&big));
        let result =
            decompress_payload(Some("deflate"), compressed, 1024, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::PayloadTooLarge(_))));
    }

    #[tokio::test]
    async fn decompress_br_exceeds_limit() {
        let big = vec![0u8; 64 * 1024];
        let compressed = Bytes::from(compress_brotli(&big));
        let result = decompress_payload(Some("br"), compressed, 1024, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::PayloadTooLarge(_))));
    }

    #[tokio::test]
    async fn decompress_zstd_exceeds_limit() {
        let big = vec![0u8; 64 * 1024];
        let compressed = Bytes::from(compress_zstd(&big));
        let result = decompress_payload(Some("zstd"), compressed, 1024, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::PayloadTooLarge(_))));
    }

    #[tokio::test]
    async fn decompress_invalid_gzip_data() {
        let garbage = Bytes::from_static(b"this is not gzip");
        let result = decompress_payload(Some("gzip"), garbage, 4096, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::RequestDecodingError(_))));
    }

    #[tokio::test]
    async fn decompress_invalid_deflate_data() {
        let garbage = Bytes::from_static(b"this is not deflate");
        let result = decompress_payload(Some("deflate"), garbage, 4096, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::RequestDecodingError(_))));
    }

    #[tokio::test]
    async fn decompress_invalid_br_data() {
        let garbage = Bytes::from_static(b"this is not brotli");
        let result = decompress_payload(Some("br"), garbage, 4096, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::RequestDecodingError(_))));
    }

    #[tokio::test]
    async fn decompress_invalid_zstd_data() {
        let garbage = Bytes::from_static(b"this is not zstd");
        let result = decompress_payload(Some("zstd"), garbage, 4096, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::RequestDecodingError(_))));
    }

    #[tokio::test]
    async fn decompress_unsupported_encoding() {
        let data = Bytes::from("irrelevant");
        let result = decompress_payload(Some("lz4"), data, 4096, TEST_CHUNK_SIZE_KB).await;
        assert!(matches!(result, Err(Error::UnsupportedEncoding(_))));
    }

    // --- split-limit tests (compressed limit < decompressed limit) ---

    /// Simulates the two-step handler flow: extract with a compressed limit,
    /// then decompress with a (larger) decompressed limit.
    async fn handler_roundtrip(
        encoding: Option<&str>,
        raw: Bytes,
        compressed_limit: usize,
        decompressed_limit: usize,
    ) -> Result<Bytes, Error> {
        let body = Body::from(raw);
        let wire =
            extract_body_with_timeout(body, compressed_limit, None, TEST_CHUNK_SIZE_KB, "/test")
                .await?;
        decompress_payload(encoding, wire, decompressed_limit, TEST_CHUNK_SIZE_KB).await
    }

    #[tokio::test]
    async fn extract_body_at_exact_limit_succeeds() {
        let data = vec![b'x'; 128];
        let body = Body::from(data.clone());
        let result = extract_body_with_timeout(body, 128, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert_eq!(result.unwrap().len(), 128);
    }

    #[tokio::test]
    async fn extract_body_one_byte_over_limit_rejected() {
        let data = vec![b'x'; 129];
        let body = Body::from(data);
        let result = extract_body_with_timeout(body, 128, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(matches!(result, Err(Error::PayloadTooLarge(_))));
    }

    #[tokio::test]
    async fn split_limits_gzip_bomb_rejected_at_decompression() {
        let big = vec![0u8; 8192];
        let compressed = Bytes::from(compress_gzip(&big));
        assert!(
            compressed.len() < 256,
            "compressed should be much smaller than decompressed for this test"
        );
        let result = handler_roundtrip(Some("gzip"), compressed, 256, 4096).await;
        assert!(
            matches!(result, Err(Error::PayloadTooLarge(_))),
            "decompressed 8KB should exceed the 4KB decompressed limit"
        );
    }

    #[tokio::test]
    async fn split_limits_zstd_bomb_rejected_at_decompression() {
        let big = vec![0u8; 8192];
        let compressed = Bytes::from(compress_zstd(&big));
        assert!(
            compressed.len() < 256,
            "compressed should be much smaller than decompressed for this test"
        );
        let result = handler_roundtrip(Some("zstd"), compressed, 256, 4096).await;
        assert!(
            matches!(result, Err(Error::PayloadTooLarge(_))),
            "decompressed 8KB should exceed the 4KB decompressed limit"
        );
    }

    #[tokio::test]
    async fn split_limits_compressed_over_wire_limit_rejected() {
        let big = vec![b'a'; 4096];
        let compressed = Bytes::from(compress_gzip(&big));
        let wire_limit = compressed.len() - 1;
        let result = handler_roundtrip(Some("gzip"), compressed, wire_limit, 1024 * 1024).await;
        assert!(
            matches!(result, Err(Error::PayloadTooLarge(_))),
            "wire bytes should exceed the compressed limit"
        );
    }

    #[tokio::test]
    async fn split_limits_both_within_bounds_succeeds_gzip() {
        let original = b"split limit roundtrip gzip";
        let compressed = Bytes::from(compress_gzip(original));
        let result = handler_roundtrip(Some("gzip"), compressed, 4096, 4096).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn split_limits_both_within_bounds_succeeds_zstd() {
        let original = b"split limit roundtrip zstd";
        let compressed = Bytes::from(compress_zstd(original));
        let result = handler_roundtrip(Some("zstd"), compressed, 4096, 4096).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn split_limits_both_within_bounds_succeeds_deflate() {
        let original = b"split limit roundtrip deflate";
        let compressed = Bytes::from(compress_deflate(original));
        let result = handler_roundtrip(Some("deflate"), compressed, 4096, 4096).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn split_limits_both_within_bounds_succeeds_brotli() {
        let original = b"split limit roundtrip brotli";
        let compressed = Bytes::from(compress_brotli(original));
        let result = handler_roundtrip(Some("br"), compressed, 4096, 4096).await;
        assert_eq!(result.unwrap(), Bytes::from_static(original));
    }

    #[tokio::test]
    async fn split_limits_uncompressed_passthrough_within_bounds() {
        let original = Bytes::from("no encoding, just plain text");
        let result = handler_roundtrip(None, original.clone(), 4096, 4096).await;
        assert_eq!(result.unwrap(), original);
    }
}
