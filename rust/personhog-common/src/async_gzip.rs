//! Tower layer that offloads gRPC response compression to a blocking thread.
//!
//! Tonic's built-in compression runs synchronously inside `poll_next`, blocking
//! the tokio runtime for the entire duration of gzip deflate. For large protobuf
//! payloads this is the dominant CPU cost on the service, starving other tasks of
//! runtime time. This layer replaces tonic's inline compression with one that
//! collects the uncompressed response, compresses it on `spawn_blocking`, and
//! returns the compressed frame — freeing the runtime to handle other requests
//! while compression runs on the blocking thread pool.
//!
//! Designed for **unary RPCs only**. The implementation buffers the entire response
//! body before compressing, which is fine for request-response patterns but would
//! defeat the purpose of server-streaming RPCs.

use std::fmt;
use std::future::Future;
use std::io::Write;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Instant;

use bytes::{BufMut, Bytes, BytesMut};
use flate2::write::GzEncoder;
use flate2::Compression;
use futures::pin_mut;
use http::{HeaderMap, HeaderValue, Request, Response};
use http_body::{Body, Frame, SizeHint};
use http_body_util::BodyExt;
use metrics::{counter, histogram};
use tokio::task::spawn_blocking;
use tonic::Status;
use tower::{Layer, Service};
use tracing::warn;

/// gRPC frame header: 1 byte compression flag + 4 byte payload length.
const GRPC_HEADER_SIZE: usize = 5;

/// Header names used in gRPC compression negotiation.
const GRPC_ACCEPT_ENCODING: &str = "grpc-accept-encoding";
const GRPC_ENCODING: &str = "grpc-encoding";

/// Type alias for the boxed body returned by the layer. Both the passthrough
/// and compressed paths produce bodies that implement this trait, boxed to
/// keep a single concrete return type on the service.
pub type ResponseBody = Pin<Box<dyn Body<Data = Bytes, Error = Status> + Send>>;

// ============================================================
// Configuration
// ============================================================

/// Configuration for the async gzip compression layer.
#[derive(Clone, Debug)]
pub struct AsyncGzipConfig {
    /// Whether compression is enabled. When false, the layer is a no-cost
    /// passthrough regardless of client headers.
    pub enabled: bool,

    /// Gzip compression level (1–9). Lower levels are faster with less
    /// compression; higher levels compress more but use more CPU. Level 6
    /// is the flate2/zlib default.
    pub compression_level: u32,

    /// Minimum payload size (bytes) to bother compressing. Responses smaller
    /// than this pass through uncompressed — the gzip header overhead would
    /// make them larger, and the CPU cost isn't worth it.
    pub min_payload_size: usize,
}

impl Default for AsyncGzipConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            compression_level: 6,
            min_payload_size: 256,
        }
    }
}

// ============================================================
// Layer
// ============================================================

/// Tower layer that adds async gzip compression to gRPC responses.
///
/// The inner tonic service must have gzip compression **disabled** — this layer
/// takes over gzip entirely. When disabled via config, the layer is a no-cost
/// passthrough.
#[derive(Clone)]
pub struct AsyncGzipLayer {
    config: AsyncGzipConfig,
}

impl AsyncGzipLayer {
    pub fn new(config: AsyncGzipConfig) -> Self {
        Self { config }
    }
}

impl<S> Layer<S> for AsyncGzipLayer {
    type Service = AsyncGzipService<S>;

    fn layer(&self, service: S) -> Self::Service {
        AsyncGzipService {
            inner: service,
            config: self.config.clone(),
        }
    }
}

// ============================================================
// Service
// ============================================================

#[derive(Clone)]
pub struct AsyncGzipService<S> {
    inner: S,
    config: AsyncGzipConfig,
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for AsyncGzipService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>> + Clone + Send + 'static,
    S::Future: Send,
    S::Error: Send + 'static,
    ReqBody: Send + 'static,
    ResBody: Body<Data = Bytes> + Send + 'static,
    ResBody::Error: fmt::Display + Send,
{
    type Response = Response<ResponseBody>;
    type Error = S::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        let accepts_gzip = self.config.enabled
            && request
                .headers()
                .get(GRPC_ACCEPT_ENCODING)
                .and_then(|v| v.to_str().ok())
                .is_some_and(|v| v.split(',').any(|e| e.trim() == "gzip"));

        let config = self.config.clone();
        let mut inner = self.inner.clone();

        Box::pin(async move {
            let response = inner.call(request).await?;
            let (mut parts, body) = response.into_parts();

            // When compression isn't requested, pass the original body through
            // without collecting or copying — zero overhead for the common case
            // where the client doesn't accept gzip or the feature is disabled.
            if !accepts_gzip {
                counter!("grpc_gzip_responses_total", "outcome" => "passthrough").increment(1);
                let body = body.map_err(|e| Status::internal(e.to_string()));
                let boxed: ResponseBody = Box::pin(body);
                return Ok(Response::from_parts(parts, boxed));
            }

            // Gather body data chunks and trailers separately. For unary RPCs,
            // tonic produces one or more data frames (split at ~32KB boundaries)
            // followed by a trailers frame. We keep chunks as individual Bytes
            // references to avoid copying them into a contiguous buffer.
            let mut chunks: Vec<Bytes> = Vec::new();
            let mut trailers: Option<HeaderMap> = None;
            let mut total_size: usize = 0;
            pin_mut!(body);
            loop {
                match body.frame().await {
                    Some(Ok(frame)) => match frame.into_data() {
                        Ok(data) => {
                            total_size += data.len();
                            chunks.push(data);
                        }
                        Err(frame) => {
                            if let Ok(t) = frame.into_trailers() {
                                trailers = Some(t);
                            }
                        }
                    },
                    Some(Err(e)) => {
                        warn!(error = %e, "Failed to read response body for compression");
                        counter!("grpc_gzip_responses_total", "outcome" => "collect_error")
                            .increment(1);
                        let boxed: ResponseBody = Box::pin(PrecomputedBody::empty());
                        return Ok(Response::from_parts(parts, boxed));
                    }
                    None => break,
                }
            }

            let payload_size = total_size.saturating_sub(GRPC_HEADER_SIZE);
            let already_compressed = !chunks.is_empty() && chunks[0].first().copied() == Some(1);

            // Skip compression when there's no data, the payload is below the
            // minimum threshold, or the frame is already compressed by tonic.
            if chunks.is_empty()
                || total_size <= GRPC_HEADER_SIZE
                || payload_size < config.min_payload_size
                || already_compressed
            {
                counter!("grpc_gzip_responses_total", "outcome" => "passthrough").increment(1);
                let data = concat_chunks(&chunks);
                let boxed: ResponseBody = Box::pin(PrecomputedBody::new(data, trailers));
                return Ok(Response::from_parts(parts, boxed));
            }

            // Compress the protobuf payload on the blocking thread pool.
            // We move the chunk references directly — the encoder reads each
            // chunk sequentially without copying them into a contiguous buffer.
            let level = config.compression_level;
            let start = Instant::now();
            let compressed = spawn_blocking(move || gzip_compress_chunks(&chunks, level)).await;
            let elapsed = start.elapsed();

            match compressed {
                Ok(Ok(bytes)) => {
                    histogram!("grpc_gzip_compression_duration_ms")
                        .record(elapsed.as_secs_f64() * 1000.0);
                    histogram!("grpc_gzip_uncompressed_bytes").record(payload_size as f64);
                    histogram!("grpc_gzip_compressed_bytes").record(bytes.len() as f64);
                    counter!("grpc_gzip_responses_total", "outcome" => "compressed").increment(1);

                    let mut frame = BytesMut::with_capacity(GRPC_HEADER_SIZE + bytes.len());
                    frame.put_u8(1); // compression flag
                    frame.put_u32(bytes.len() as u32);
                    frame.extend_from_slice(&bytes);

                    parts
                        .headers
                        .insert(GRPC_ENCODING, HeaderValue::from_static("gzip"));

                    let boxed: ResponseBody =
                        Box::pin(PrecomputedBody::new(frame.freeze(), trailers));
                    Ok(Response::from_parts(parts, boxed))
                }
                Ok(Err(e)) => {
                    warn!(error = %e, "gzip compression failed, returning uncompressed");
                    counter!("grpc_gzip_responses_total", "outcome" => "compress_error")
                        .increment(1);
                    let boxed: ResponseBody = Box::pin(PrecomputedBody::trailers_only(trailers));
                    Ok(Response::from_parts(parts, boxed))
                }
                Err(e) => {
                    warn!(error = %e, "spawn_blocking panicked, returning uncompressed");
                    counter!("grpc_gzip_responses_total", "outcome" => "spawn_error").increment(1);
                    let boxed: ResponseBody = Box::pin(PrecomputedBody::trailers_only(trailers));
                    Ok(Response::from_parts(parts, boxed))
                }
            }
        })
    }
}

// ============================================================
// Response bodies
// ============================================================

/// Response body that yields pre-computed data followed by optional trailers.
/// Used for compressed responses and small-payload passthrough where the chunks
/// have already been collected.
struct PrecomputedBody {
    data: Option<Bytes>,
    trailers: Option<HeaderMap>,
}

impl PrecomputedBody {
    fn new(data: Bytes, trailers: Option<HeaderMap>) -> Self {
        Self {
            data: if data.is_empty() { None } else { Some(data) },
            trailers,
        }
    }

    fn trailers_only(trailers: Option<HeaderMap>) -> Self {
        Self {
            data: None,
            trailers,
        }
    }

    fn empty() -> Self {
        Self {
            data: None,
            trailers: None,
        }
    }
}

impl Body for PrecomputedBody {
    type Data = Bytes;
    type Error = Status;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        _cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        if let Some(data) = self.data.take() {
            return Poll::Ready(Some(Ok(Frame::data(data))));
        }
        if let Some(trailers) = self.trailers.take() {
            return Poll::Ready(Some(Ok(Frame::trailers(trailers))));
        }
        Poll::Ready(None)
    }

    fn is_end_stream(&self) -> bool {
        self.data.is_none() && self.trailers.is_none()
    }

    fn size_hint(&self) -> SizeHint {
        SizeHint::default()
    }
}

// ============================================================
// Compression helpers
// ============================================================

/// Concatenate chunks into a contiguous buffer. Only used for the passthrough
/// path where we already collected but decided not to compress.
fn concat_chunks(chunks: &[Bytes]) -> Bytes {
    if chunks.len() == 1 {
        return chunks[0].clone();
    }
    let total: usize = chunks.iter().map(|c| c.len()).sum();
    let mut buf = BytesMut::with_capacity(total);
    for chunk in chunks {
        buf.extend_from_slice(chunk);
    }
    buf.freeze()
}

/// Compress body chunks without copying them into a contiguous buffer first.
/// Skips the 5-byte gRPC frame header, then feeds each chunk sequentially to
/// the gzip encoder.
fn gzip_compress_chunks(chunks: &[Bytes], level: u32) -> std::io::Result<Vec<u8>> {
    let total: usize = chunks.iter().map(|c| c.len()).sum();
    let mut encoder = GzEncoder::new(Vec::with_capacity(total / 2), Compression::new(level));
    let mut skip = GRPC_HEADER_SIZE;
    for chunk in chunks {
        if skip >= chunk.len() {
            skip -= chunk.len();
            continue;
        }
        encoder.write_all(&chunk[skip..])?;
        skip = 0;
    }
    encoder.finish()
}

/// Compress a contiguous byte slice.
#[cfg(test)]
fn gzip_compress(data: &[u8], level: u32) -> std::io::Result<Vec<u8>> {
    let mut encoder = GzEncoder::new(Vec::with_capacity(data.len() / 2), Compression::new(level));
    encoder.write_all(data)?;
    encoder.finish()
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::read::GzDecoder;
    use http_body_util::BodyExt;
    use std::convert::Infallible;
    use std::io::Read;
    use std::slice;

    use http::response;
    use tower::{Service, ServiceExt};

    // -- test helpers --

    fn make_grpc_frame(payload: &[u8]) -> Bytes {
        let mut frame = BytesMut::with_capacity(GRPC_HEADER_SIZE + payload.len());
        frame.put_u8(0);
        frame.put_u32(payload.len() as u32);
        frame.extend_from_slice(payload);
        frame.freeze()
    }

    fn parse_grpc_frame(data: &[u8]) -> (bool, Vec<u8>) {
        assert!(data.len() >= GRPC_HEADER_SIZE, "frame too short");
        let compressed = data[0] == 1;
        let len = u32::from_be_bytes(data[1..5].try_into().unwrap()) as usize;
        assert_eq!(data.len() - GRPC_HEADER_SIZE, len, "frame length mismatch");
        (compressed, data[GRPC_HEADER_SIZE..].to_vec())
    }

    fn gzip_decompress(data: &[u8]) -> Vec<u8> {
        let mut decoder = GzDecoder::new(data);
        let mut out = Vec::new();
        decoder.read_to_end(&mut out).unwrap();
        out
    }

    fn grpc_ok_trailers() -> HeaderMap {
        let mut map = HeaderMap::new();
        map.insert("grpc-status", HeaderValue::from_static("0"));
        map
    }

    fn default_test_config() -> AsyncGzipConfig {
        AsyncGzipConfig {
            enabled: true,
            compression_level: 6,
            min_payload_size: 0,
        }
    }

    // -- mock service --

    #[derive(Clone)]
    struct MockGrpcService {
        body: Bytes,
        trailers: Option<HeaderMap>,
    }

    impl MockGrpcService {
        fn new(payload: &[u8]) -> Self {
            Self {
                body: make_grpc_frame(payload),
                trailers: Some(grpc_ok_trailers()),
            }
        }

        fn with_trailers(mut self, trailers: HeaderMap) -> Self {
            self.trailers = Some(trailers);
            self
        }

        fn without_trailers(mut self) -> Self {
            self.trailers = None;
            self
        }
    }

    struct MockBody {
        data: Option<Bytes>,
        trailers: Option<HeaderMap>,
    }

    impl Body for MockBody {
        type Data = Bytes;
        type Error = Status;

        fn poll_frame(
            mut self: Pin<&mut Self>,
            _cx: &mut Context<'_>,
        ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
            if let Some(data) = self.data.take() {
                return Poll::Ready(Some(Ok(Frame::data(data))));
            }
            if let Some(trailers) = self.trailers.take() {
                return Poll::Ready(Some(Ok(Frame::trailers(trailers))));
            }
            Poll::Ready(None)
        }
    }

    impl Service<Request<()>> for MockGrpcService {
        type Response = Response<MockBody>;
        type Error = Infallible;
        type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _request: Request<()>) -> Self::Future {
            let body = MockBody {
                data: Some(self.body.clone()),
                trailers: self.trailers.clone(),
            };
            Box::pin(async { Ok(Response::new(body)) })
        }
    }

    /// Call the layer with a request, returning (response_parts, body_bytes, trailers).
    async fn call_layer(
        service: MockGrpcService,
        config: AsyncGzipConfig,
        accept_encoding: Option<&str>,
    ) -> (response::Parts, Bytes, Option<HeaderMap>) {
        let mut svc = AsyncGzipLayer::new(config).layer(service);
        let svc = svc.ready().await.unwrap();

        let mut request = Request::new(());
        if let Some(enc) = accept_encoding {
            request
                .headers_mut()
                .insert(GRPC_ACCEPT_ENCODING, HeaderValue::from_str(enc).unwrap());
        }

        let response = svc.call(request).await.unwrap();
        let (parts, body) = response.into_parts();
        let collected = body.collect().await.unwrap();
        let trailers = collected.trailers().cloned();
        let data = collected.to_bytes();

        (parts, data, trailers)
    }

    // ============================================================
    // Helper function unit tests
    // ============================================================

    #[test]
    fn gzip_roundtrip() {
        let original = b"hello world, this is a test payload for gzip compression";
        let compressed = gzip_compress(original, 6).unwrap();
        assert_eq!(gzip_decompress(&compressed), original);
    }

    #[test]
    fn gzip_empty_input() {
        let compressed = gzip_compress(b"", 6).unwrap();
        assert_eq!(gzip_decompress(&compressed), b"");
    }

    #[test]
    fn gzip_compression_levels() {
        let data = vec![42u8; 10_000];
        let fast = gzip_compress(&data, 1).unwrap();
        let slow = gzip_compress(&data, 9).unwrap();
        assert_eq!(gzip_decompress(&fast), data);
        assert_eq!(gzip_decompress(&slow), data);
        assert!(slow.len() <= fast.len());
    }

    #[test]
    fn concat_chunks_single_chunk() {
        let chunk = Bytes::from_static(b"hello");
        let result = concat_chunks(slice::from_ref(&chunk));
        assert_eq!(result, chunk);
    }

    #[test]
    fn concat_chunks_multiple() {
        let chunks = vec![
            Bytes::from_static(b"hel"),
            Bytes::from_static(b"lo "),
            Bytes::from_static(b"world"),
        ];
        assert_eq!(concat_chunks(&chunks), Bytes::from_static(b"hello world"));
    }

    #[test]
    fn compress_chunks_single_chunk() {
        let payload = b"protobuf data here";
        let frame = make_grpc_frame(payload);
        let compressed = gzip_compress_chunks(&[frame], 6).unwrap();
        assert_eq!(gzip_decompress(&compressed), payload);
    }

    #[test]
    fn compress_chunks_header_in_first_chunk() {
        // Header (5 bytes) + first part of payload in chunk 1, rest in chunk 2
        let payload = b"abcdefghijklmnopqrstuvwxyz";
        let frame = make_grpc_frame(payload);
        let chunks = vec![frame.slice(..15), frame.slice(15..)];
        let compressed = gzip_compress_chunks(&chunks, 6).unwrap();
        assert_eq!(gzip_decompress(&compressed), payload);
    }

    #[test]
    fn compress_chunks_header_spans_two_chunks() {
        // 3 bytes of header in chunk 1, remaining 2 bytes + payload in chunk 2
        let payload = b"the payload";
        let frame = make_grpc_frame(payload);
        let chunks = vec![frame.slice(..3), frame.slice(3..)];
        let compressed = gzip_compress_chunks(&chunks, 6).unwrap();
        assert_eq!(gzip_decompress(&compressed), payload);
    }

    #[test]
    fn compress_chunks_header_exactly_one_chunk() {
        // First chunk is exactly the 5-byte header, second chunk is payload
        let payload = b"payload after header";
        let frame = make_grpc_frame(payload);
        let chunks = vec![
            frame.slice(..GRPC_HEADER_SIZE),
            frame.slice(GRPC_HEADER_SIZE..),
        ];
        let compressed = gzip_compress_chunks(&chunks, 6).unwrap();
        assert_eq!(gzip_decompress(&compressed), payload);
    }

    #[test]
    fn compress_chunks_many_small_chunks() {
        // Simulate a body split into many small chunks
        let payload: Vec<u8> = (0..1000).map(|i| (i % 256) as u8).collect();
        let frame = make_grpc_frame(&payload);
        let chunks: Vec<Bytes> = frame.chunks(50).map(Bytes::copy_from_slice).collect();
        assert!(chunks.len() > 10);
        let compressed = gzip_compress_chunks(&chunks, 6).unwrap();
        assert_eq!(gzip_decompress(&compressed), payload);
    }

    // ============================================================
    // Layer integration tests
    // ============================================================

    #[tokio::test]
    async fn compresses_response_when_client_accepts_gzip() {
        let payload = b"fake protobuf payload that should be compressed";
        let service = MockGrpcService::new(payload);
        let (parts, data, trailers) =
            call_layer(service, default_test_config(), Some("gzip")).await;

        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed, "compression flag should be set");
        assert_eq!(gzip_decompress(&compressed_payload), payload);

        let trailers = trailers.expect("trailers should be present");
        assert_eq!(trailers.get("grpc-status").unwrap(), "0");
    }

    #[tokio::test]
    async fn no_compression_without_accept_encoding_header() {
        let payload = b"this payload should not be compressed";
        let service = MockGrpcService::new(payload);
        let (parts, data, _trailers) = call_layer(service, default_test_config(), None).await;

        assert!(parts.headers.get(GRPC_ENCODING).is_none());
        let (compressed, raw_payload) = parse_grpc_frame(&data);
        assert!(!compressed);
        assert_eq!(raw_payload, payload);
    }

    #[tokio::test]
    async fn no_compression_when_gzip_not_in_accept_encoding() {
        let payload = b"this payload should not be compressed";
        let service = MockGrpcService::new(payload);
        let (parts, data, _trailers) =
            call_layer(service, default_test_config(), Some("zstd,identity")).await;

        assert!(parts.headers.get(GRPC_ENCODING).is_none());
        let (compressed, raw_payload) = parse_grpc_frame(&data);
        assert!(!compressed);
        assert_eq!(raw_payload, payload);
    }

    #[tokio::test]
    async fn compresses_when_gzip_among_multiple_encodings() {
        let payload = b"mixed encoding header test";
        let service = MockGrpcService::new(payload);
        let (parts, data, _trailers) =
            call_layer(service, default_test_config(), Some("zstd, gzip, identity")).await;

        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
    }

    #[tokio::test]
    async fn preserves_trailers() {
        let payload = b"trailers test";
        let mut custom_trailers = grpc_ok_trailers();
        custom_trailers.insert("grpc-message", HeaderValue::from_static("all good"));

        let service = MockGrpcService::new(payload).with_trailers(custom_trailers);
        let (_parts, _data, trailers) =
            call_layer(service, default_test_config(), Some("gzip")).await;

        let trailers = trailers.expect("trailers should be present");
        assert_eq!(trailers.get("grpc-status").unwrap(), "0");
        assert_eq!(trailers.get("grpc-message").unwrap(), "all good");
    }

    #[tokio::test]
    async fn handles_response_without_trailers() {
        let payload = b"no trailers";
        let service = MockGrpcService::new(payload).without_trailers();
        let (parts, data, trailers) =
            call_layer(service, default_test_config(), Some("gzip")).await;

        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
        assert!(trailers.is_none());
    }

    #[tokio::test]
    async fn passthrough_on_trailers_only_response() {
        // A response with no data frames (only trailers) — e.g. a gRPC error
        // where the status is sent entirely in the trailers frame.
        let service = MockGrpcService {
            body: Bytes::new(),
            trailers: Some(grpc_ok_trailers()),
        };
        let (parts, data, trailers) =
            call_layer(service, default_test_config(), Some("gzip")).await;

        assert!(parts.headers.get(GRPC_ENCODING).is_none());
        assert!(data.is_empty());
        let trailers = trailers.expect("trailers should be present");
        assert_eq!(trailers.get("grpc-status").unwrap(), "0");
    }

    #[tokio::test]
    async fn passthrough_on_empty_grpc_frame() {
        let mut frame = BytesMut::with_capacity(GRPC_HEADER_SIZE);
        frame.put_u8(0);
        frame.put_u32(0);

        let service = MockGrpcService {
            body: frame.freeze(),
            trailers: Some(grpc_ok_trailers()),
        };
        let (parts, data, _trailers) =
            call_layer(service, default_test_config(), Some("gzip")).await;

        assert!(parts.headers.get(GRPC_ENCODING).is_none());
        assert_eq!(data.len(), GRPC_HEADER_SIZE);
    }

    #[tokio::test]
    async fn compressed_frame_length_field_matches_payload() {
        let payload = vec![42u8; 10_000];
        let service = MockGrpcService::new(&payload);
        let (_parts, data, _trailers) =
            call_layer(service, default_test_config(), Some("gzip")).await;

        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        let header_len = u32::from_be_bytes(data[1..5].try_into().unwrap()) as usize;
        assert_eq!(header_len, compressed_payload.len());
        assert_eq!(gzip_decompress(&compressed_payload), payload);
    }

    #[tokio::test]
    async fn large_payload_compresses_correctly() {
        let payload: Vec<u8> = (0..100_000).map(|i| (i % 256) as u8).collect();
        let service = MockGrpcService::new(&payload);
        let (parts, data, trailers) =
            call_layer(service, default_test_config(), Some("gzip")).await;

        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
        assert!(
            compressed_payload.len() < payload.len(),
            "compressed ({}) should be smaller than original ({})",
            compressed_payload.len(),
            payload.len()
        );

        let trailers = trailers.expect("trailers should be present");
        assert_eq!(trailers.get("grpc-status").unwrap(), "0");
    }

    #[tokio::test]
    async fn disabled_flag_skips_compression() {
        let payload = b"should not be compressed";
        let service = MockGrpcService::new(payload);
        let config = AsyncGzipConfig {
            enabled: false,
            ..default_test_config()
        };
        let (parts, data, _trailers) = call_layer(service, config, Some("gzip")).await;

        assert!(parts.headers.get(GRPC_ENCODING).is_none());
        let (compressed, raw_payload) = parse_grpc_frame(&data);
        assert!(!compressed);
        assert_eq!(raw_payload, payload);
    }

    #[tokio::test]
    async fn min_payload_size_skips_small_responses() {
        let payload = b"tiny";
        let service = MockGrpcService::new(payload);
        let config = AsyncGzipConfig {
            min_payload_size: 1000,
            ..default_test_config()
        };
        let (parts, data, _trailers) = call_layer(service, config, Some("gzip")).await;

        assert!(parts.headers.get(GRPC_ENCODING).is_none());
        let (compressed, raw_payload) = parse_grpc_frame(&data);
        assert!(!compressed);
        assert_eq!(raw_payload, payload);
    }

    #[tokio::test]
    async fn min_payload_size_compresses_large_responses() {
        let payload = vec![42u8; 2000];
        let service = MockGrpcService::new(&payload);
        let config = AsyncGzipConfig {
            min_payload_size: 1000,
            ..default_test_config()
        };
        let (parts, data, _trailers) = call_layer(service, config, Some("gzip")).await;

        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
    }

    #[tokio::test]
    async fn custom_compression_level() {
        let payload = vec![42u8; 10_000];
        let service = MockGrpcService::new(&payload);
        let config = AsyncGzipConfig {
            compression_level: 1,
            ..default_test_config()
        };
        let (parts, data, _trailers) = call_layer(service, config, Some("gzip")).await;

        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
    }
}
