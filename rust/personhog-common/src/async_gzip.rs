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
use std::sync::Arc;
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

use crate::grpc::GZIP_OVERHEAD_HEADER;

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

    /// Gzip compression level (1–9, clamped). Lower levels are faster with
    /// less compression; higher levels compress more but use more CPU.
    /// Level 6 is the flate2/zlib default.
    pub compression_level: u32,

    /// Minimum payload size (bytes) to bother compressing. Responses smaller
    /// than this pass through uncompressed — the gzip header overhead would
    /// make them larger, and the CPU cost isn't worth it.
    pub min_payload_size: usize,

    /// Maximum response payload size (bytes) after compression (or uncompressed
    /// if gzip is not negotiated). When a response exceeds this limit, behavior
    /// depends on `max_response_size_enforce`: in enforce mode, the response is
    /// rejected with an OUT_OF_RANGE gRPC error; in monitor mode, a metric is
    /// emitted but the response is delivered normally. `None` disables the check.
    ///
    /// This replaces tonic's `max_encoding_message_size` as the primary guardrail
    /// because tonic's check runs before this layer's gzip compression, rejecting
    /// responses that would compress well below the limit.
    pub max_response_size: Option<usize>,

    /// When true, responses exceeding `max_response_size` are rejected with a
    /// gRPC OUT_OF_RANGE error. When false (monitor mode), the metric fires
    /// but the response is delivered normally — useful for observing violations
    /// before enabling enforcement.
    pub max_response_size_enforce: bool,
}

impl AsyncGzipConfig {
    pub fn new(enabled: bool, compression_level: u32, min_payload_size: usize) -> Self {
        Self {
            enabled,
            compression_level: compression_level.clamp(1, 9),
            min_payload_size,
            max_response_size: None,
            max_response_size_enforce: false,
        }
    }

    pub fn with_max_response_size(mut self, max_bytes: Option<usize>, enforce: bool) -> Self {
        self.max_response_size = max_bytes;
        self.max_response_size_enforce = enforce;
        self
    }
}

impl Default for AsyncGzipConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            compression_level: 6,
            min_payload_size: 256,
            max_response_size: None,
            max_response_size_enforce: false,
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

        let method: Arc<str> = Arc::from(
            request
                .uri()
                .path()
                .rsplit_once('/')
                .map(|(_, m)| m)
                .filter(|m| !m.is_empty())
                .unwrap_or("unknown"),
        );

        let client: Arc<str> = Arc::from(
            request
                .headers()
                .get("x-client-name")
                .and_then(|v| v.to_str().ok())
                .unwrap_or("unknown"),
        );

        let caller_tag: Arc<str> = Arc::from(
            request
                .headers()
                .get("x-caller-tag")
                .and_then(|v| v.to_str().ok())
                .unwrap_or(""),
        );

        let config = self.config.clone();
        let mut inner = self.inner.clone();

        Box::pin(async move {
            let response = inner.call(request).await?;
            let (mut parts, body) = response.into_parts();

            let gzip_start = Instant::now();

            // Always collect the body so we can enforce size limits on all
            // response paths. For unary RPCs this is a single frame — the
            // overhead is one Vec allocation and Bytes reference copies (no
            // data copying for the common single-chunk case).
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
                        counter!("grpc_gzip_responses_total", "outcome" => "collect_error", "method" => method.clone())
                            .increment(1);
                        // Synthesize a grpc-status trailer so the client gets a
                        // clean error instead of a protocol violation from a
                        // missing trailer.
                        let error_trailers = trailers.unwrap_or_else(|| {
                            let mut map = HeaderMap::new();
                            map.insert("grpc-status", HeaderValue::from_static("13"));
                            map.insert(
                                "grpc-message",
                                HeaderValue::from_str(&format!("body collection failed: {e}"))
                                    .unwrap_or_else(|_| {
                                        HeaderValue::from_static("body collection failed")
                                    }),
                            );
                            map
                        });
                        let boxed: ResponseBody =
                            Box::pin(PrecomputedBody::trailers_only(error_trailers));
                        return Ok(Response::from_parts(parts, boxed));
                    }
                    None => break,
                }
            }

            histogram!(
                "grpc_gzip_body_collect_ms",
                "method" => method.clone(),
            )
            .record(gzip_start.elapsed().as_secs_f64() * 1000.0);

            // Client doesn't accept gzip — return the collected body uncompressed.
            if !accepts_gzip {
                counter!("grpc_gzip_responses_total", "outcome" => "passthrough_no_gzip", "method" => method.clone()).increment(1);
                if let Some(body) =
                    check_response_size(&config, &method, &client, &caller_tag, total_size)
                {
                    return Ok(Response::from_parts(parts, body));
                }
                let data = concat_chunks(&chunks);
                let boxed: ResponseBody = Box::pin(PrecomputedBody::new(data, trailers));
                return Ok(Response::from_parts(parts, boxed));
            }

            let payload_size = total_size.saturating_sub(GRPC_HEADER_SIZE);
            let already_compressed = chunks.iter().find_map(|c| c.first().copied()) == Some(1);

            // Skip compression when there's no data, the payload is below the
            // minimum threshold, or the frame is already compressed by tonic.
            if chunks.is_empty()
                || total_size <= GRPC_HEADER_SIZE
                || payload_size < config.min_payload_size
                || already_compressed
            {
                counter!("grpc_gzip_responses_total", "outcome" => "passthrough_small", "method" => method.clone()).increment(1);
                if let Some(body) =
                    check_response_size(&config, &method, &client, &caller_tag, total_size)
                {
                    return Ok(Response::from_parts(parts, body));
                }
                let gzip_overhead_ms = gzip_start.elapsed().as_secs_f64() * 1000.0;
                set_gzip_overhead_header(&mut parts, method.clone(), gzip_overhead_ms);
                let data = concat_chunks(&chunks);
                let boxed: ResponseBody = Box::pin(PrecomputedBody::new(data, trailers));
                return Ok(Response::from_parts(parts, boxed));
            }

            // Compress the protobuf payload on the blocking thread pool.
            // We move the chunk references directly — the encoder reads each
            // chunk sequentially without copying them into a contiguous buffer.
            let level = config.compression_level;
            let compress_start = Instant::now();
            let compressed = spawn_blocking(move || gzip_compress_chunks(&chunks, level)).await;
            let compress_elapsed = compress_start.elapsed();

            match compressed {
                Ok(Ok(bytes)) => {
                    histogram!("grpc_gzip_compression_duration_ms", "method" => method.clone())
                        .record(compress_elapsed.as_secs_f64() * 1000.0);
                    histogram!("grpc_gzip_uncompressed_bytes", "method" => method.clone())
                        .record(payload_size as f64);
                    histogram!("grpc_gzip_compressed_bytes", "method" => method.clone())
                        .record(bytes.len() as f64);
                    counter!("grpc_gzip_responses_total", "outcome" => "compressed", "method" => method.clone()).increment(1);

                    // Size check on the compressed output — this is the actual
                    // number of bytes that will go over the wire.
                    let compressed_frame_size = GRPC_HEADER_SIZE + bytes.len();
                    if let Some(body) = check_response_size(
                        &config,
                        &method,
                        &client,
                        &caller_tag,
                        compressed_frame_size,
                    ) {
                        return Ok(Response::from_parts(parts, body));
                    }

                    let mut frame = BytesMut::with_capacity(GRPC_HEADER_SIZE + bytes.len());
                    frame.put_u8(1); // compression flag
                    frame.put_u32(bytes.len() as u32);
                    frame.extend_from_slice(&bytes);

                    parts
                        .headers
                        .insert(GRPC_ENCODING, HeaderValue::from_static("gzip"));

                    let gzip_overhead_ms = gzip_start.elapsed().as_secs_f64() * 1000.0;
                    set_gzip_overhead_header(&mut parts, method.clone(), gzip_overhead_ms);

                    let boxed: ResponseBody =
                        Box::pin(PrecomputedBody::new(frame.freeze(), trailers));
                    Ok(Response::from_parts(parts, boxed))
                }
                Ok(Err(e)) => {
                    warn!(error = %e, "gzip compression failed, returning uncompressed");
                    counter!("grpc_gzip_responses_total", "outcome" => "compress_error", "method" => method.clone())
                        .increment(1);
                    let gzip_overhead_ms = gzip_start.elapsed().as_secs_f64() * 1000.0;
                    set_gzip_overhead_header(&mut parts, method.clone(), gzip_overhead_ms);
                    let boxed: ResponseBody = Box::pin(PrecomputedBody::trailers_only(trailers));
                    Ok(Response::from_parts(parts, boxed))
                }
                Err(e) => {
                    warn!(error = %e, "spawn_blocking panicked, returning uncompressed");
                    counter!("grpc_gzip_responses_total", "outcome" => "spawn_error", "method" => method.clone()).increment(1);
                    let gzip_overhead_ms = gzip_start.elapsed().as_secs_f64() * 1000.0;
                    set_gzip_overhead_header(&mut parts, method.clone(), gzip_overhead_ms);
                    let boxed: ResponseBody = Box::pin(PrecomputedBody::trailers_only(trailers));
                    Ok(Response::from_parts(parts, boxed))
                }
            }
        })
    }
}

/// Checks the response size against the configured limit. In enforce mode,
/// returns a rejection body that the caller should wrap with the original
/// response `parts` (preserving headers like `Content-Type: application/grpc`).
/// In monitor mode, emits a metric and returns `None` so the caller proceeds
/// normally.
fn check_response_size(
    config: &AsyncGzipConfig,
    method: &Arc<str>,
    client: &Arc<str>,
    caller_tag: &Arc<str>,
    size: usize,
) -> Option<ResponseBody> {
    let limit = config.max_response_size?;
    if size <= limit {
        return None;
    }

    let enforced = config.max_response_size_enforce;

    counter!(
        "grpc_gzip_response_over_limit_total",
        "method" => method.clone(),
        "client" => client.clone(),
        "enforced" => if enforced { "true" } else { "false" },
    )
    .increment(1);

    if !enforced {
        warn!(
            response_size_bytes = size,
            limit_bytes = limit,
            method = %method,
            client = %client,
            caller_tag = %caller_tag,
            "oversized gRPC response (monitor mode)"
        );
        return None;
    }

    warn!(
        response_size_bytes = size,
        limit_bytes = limit,
        method = %method,
        client = %client,
        caller_tag = %caller_tag,
        "rejecting oversized gRPC response"
    );

    let mut trailers = HeaderMap::new();
    trailers.insert("grpc-status", HeaderValue::from_static("11")); // OUT_OF_RANGE
    let msg = format!("response size {size} bytes exceeds limit of {limit} bytes");
    if let Ok(hv) = HeaderValue::from_str(&msg) {
        trailers.insert("grpc-message", hv);
    }
    Some(Box::pin(PrecomputedBody::trailers_only(trailers)))
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

    fn trailers_only(trailers: impl Into<Option<HeaderMap>>) -> Self {
        Self {
            data: None,
            trailers: trailers.into(),
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

fn set_gzip_overhead_header(parts: &mut http::response::Parts, method: Arc<str>, overhead_ms: f64) {
    histogram!("grpc_gzip_total_overhead_ms", "method" => method).record(overhead_ms);
    if let Ok(hv) = HeaderValue::from_str(&format!("{overhead_ms:.3}")) {
        parts.headers.insert(GZIP_OVERHEAD_HEADER, hv);
    }
}

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
            max_response_size: None,
            max_response_size_enforce: false,
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
            Box::pin(async {
                let mut resp = Response::new(body);
                resp.headers_mut().insert(
                    "content-type",
                    HeaderValue::from_static("application/grpc+proto"),
                );
                Ok(resp)
            })
        }
    }

    /// A service whose body yields one data frame then errors before trailers,
    /// simulating a mid-stream failure.
    #[derive(Clone)]
    struct MockErrorService;

    /// Body that yields data then an error — no trailers are ever produced.
    struct ErrorBody {
        data: Option<Bytes>,
        errored: bool,
    }

    impl Body for ErrorBody {
        type Data = Bytes;
        type Error = Status;

        fn poll_frame(
            mut self: Pin<&mut Self>,
            _cx: &mut Context<'_>,
        ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
            if let Some(data) = self.data.take() {
                return Poll::Ready(Some(Ok(Frame::data(data))));
            }
            if !self.errored {
                self.errored = true;
                return Poll::Ready(Some(Err(Status::internal("simulated body error"))));
            }
            Poll::Ready(None)
        }
    }

    impl Service<Request<()>> for MockErrorService {
        type Response = Response<ErrorBody>;
        type Error = Infallible;
        type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _request: Request<()>) -> Self::Future {
            let body = ErrorBody {
                data: Some(make_grpc_frame(b"partial data")),
                errored: false,
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

    #[tokio::test]
    async fn body_error_synthesizes_grpc_status_trailer() {
        let mut svc = AsyncGzipLayer::new(default_test_config()).layer(MockErrorService);
        let svc = svc.ready().await.unwrap();

        let mut request = Request::new(());
        request
            .headers_mut()
            .insert(GRPC_ACCEPT_ENCODING, HeaderValue::from_static("gzip"));

        let response = svc.call(request).await.unwrap();
        let (parts, body) = response.into_parts();
        let collected = body.collect().await.unwrap();
        let trailers = collected.trailers().cloned();

        // No grpc-encoding — compression was aborted
        assert!(parts.headers.get(GRPC_ENCODING).is_none());

        // Body should have no data (empty response on error)
        let data = collected.to_bytes();
        assert!(data.is_empty());

        // Should have a synthesized grpc-status: 13 (INTERNAL) trailer
        let trailers = trailers.expect("error path must produce trailers");
        assert_eq!(trailers.get("grpc-status").unwrap(), "13");
        assert!(trailers.get("grpc-message").is_some());
    }

    #[tokio::test]
    async fn large_5mb_payload_compresses_correctly() {
        let payload: Vec<u8> = (0..5_000_000).map(|i| (i % 256) as u8).collect();
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

    #[rstest::rstest]
    #[case::compressed(b"payload that will be compressed by the gzip layer".as_slice(), default_test_config(), Some("gzip"), true)]
    #[case::passthrough_collected(b"tiny".as_slice(), AsyncGzipConfig { min_payload_size: 1000, ..default_test_config() }, Some("gzip"), true)]
    #[case::not_accepted(b"no gzip requested".as_slice(), default_test_config(), None, false)]
    #[tokio::test]
    async fn gzip_overhead_header_presence(
        #[case] payload: &[u8],
        #[case] config: AsyncGzipConfig,
        #[case] accept_encoding: Option<&str>,
        #[case] expect_present: bool,
    ) {
        let service = MockGrpcService::new(payload);
        let (parts, _data, _trailers) = call_layer(service, config, accept_encoding).await;

        match parts.headers.get(GZIP_OVERHEAD_HEADER) {
            Some(val) if expect_present => {
                let overhead: f64 = val.to_str().unwrap().parse().unwrap();
                assert!(overhead >= 0.0, "overhead should be non-negative");
            }
            None if !expect_present => {}
            Some(_) => panic!("header should be absent"),
            None => panic!("header should be present"),
        }
    }

    // ============================================================
    // Response size limit tests
    // ============================================================

    #[tokio::test]
    async fn enforce_rejects_oversized_compressed_response() {
        let payload = vec![42u8; 10_000];
        let service = MockGrpcService::new(&payload);
        let config = AsyncGzipConfig {
            max_response_size: Some(10), // tiny limit — compressed output will exceed
            max_response_size_enforce: true,
            ..default_test_config()
        };

        let (parts, data, trailers) = call_layer(service, config, Some("gzip")).await;
        assert!(data.is_empty(), "rejected response should have no data");
        let trailers = trailers.expect("should have trailers");
        assert_eq!(trailers.get("grpc-status").unwrap(), "11"); // OUT_OF_RANGE
                                                                // Verify the original response headers (e.g. content-type) are preserved
        assert_eq!(
            parts.headers.get("content-type").unwrap(),
            "application/grpc+proto"
        );
    }

    #[tokio::test]
    async fn enforce_rejects_oversized_uncompressed_response() {
        let payload = vec![42u8; 10_000];
        let service = MockGrpcService::new(&payload);
        let config = AsyncGzipConfig {
            max_response_size: Some(100),
            max_response_size_enforce: true,
            ..default_test_config()
        };

        // No gzip header — uncompressed passthrough, still size-checked
        let (parts, data, trailers) = call_layer(service, config, None).await;
        assert!(data.is_empty(), "rejected response should have no data");
        let trailers = trailers.expect("should have trailers");
        assert_eq!(trailers.get("grpc-status").unwrap(), "11");
        assert_eq!(
            parts.headers.get("content-type").unwrap(),
            "application/grpc+proto"
        );
    }

    #[tokio::test]
    async fn monitor_mode_delivers_oversized_response() {
        let payload = vec![42u8; 10_000];
        let service = MockGrpcService::new(&payload);
        let config = AsyncGzipConfig {
            max_response_size: Some(10),      // tiny limit
            max_response_size_enforce: false, // monitor only
            ..default_test_config()
        };

        let (parts, data, _trailers) = call_layer(service, config, Some("gzip")).await;
        // Response should still be delivered despite exceeding the limit
        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
    }

    #[tokio::test]
    async fn enforce_allows_response_under_limit() {
        let payload = b"small payload";
        let service = MockGrpcService::new(payload);
        let config = AsyncGzipConfig {
            max_response_size: Some(1_000_000), // generous limit
            max_response_size_enforce: true,
            ..default_test_config()
        };

        let (parts, data, trailers) = call_layer(service, config, Some("gzip")).await;
        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (compressed, compressed_payload) = parse_grpc_frame(&data);
        assert!(compressed);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
        let trailers = trailers.expect("trailers should be present");
        assert_eq!(trailers.get("grpc-status").unwrap(), "0");
    }

    #[tokio::test]
    async fn no_limit_allows_any_size() {
        let payload = vec![42u8; 100_000];
        let service = MockGrpcService::new(&payload);
        let config = default_test_config(); // max_response_size = None

        let (parts, data, _trailers) = call_layer(service, config, Some("gzip")).await;
        assert_eq!(parts.headers.get(GRPC_ENCODING).unwrap(), "gzip");
        let (_, compressed_payload) = parse_grpc_frame(&data);
        assert_eq!(gzip_decompress(&compressed_payload), payload);
    }
}
