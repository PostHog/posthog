//! Custom extractors for request body handling
//!
//! This module provides utilities for extracting request bodies with
//! configurable timeouts to prevent slow clients from holding connections.

use std::time::Duration;

use axum::body::Body;
use bytes::{BufMut, Bytes, BytesMut};
use futures::{Stream, StreamExt};
use tracing::warn;

use crate::api::CaptureError;

const METRIC_BODY_READ_TIMEOUT: &str = "capture_body_read_timeout_total";
const METRIC_REJECTED_BODY_DRAIN: &str = "capture_rejected_body_drain_total";

/// Wall-clock ceiling on draining a body we have already rejected.
///
/// A per-chunk timeout does not bound this work. A client that sends one byte just
/// before each deadline resets the timer every time, so the byte budget alone would
/// let a drain run for as long as it takes to drip `payload_size_limit` bytes. One
/// deadline over the whole drain bounds it regardless of chunk cadence, and it also
/// covers deployments that leave the per-chunk timeout unset.
///
/// Kept short because this is work on a request we are already refusing.
pub const REJECTED_BODY_DRAIN_DEADLINE: Duration = Duration::from_secs(5);

/// Outcome of draining a request body we have already decided to reject.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DrainOutcome {
    /// The body was consumed in full, so the rejection can be written on a
    /// connection the client can keep using.
    Drained,
    /// We stopped early. The connection is torn down and the client may see a
    /// reset instead of our status code.
    Abandoned(DrainAbandoned),
}

/// Why a drain stopped before the body ended. Each cause calls for a different
/// response, so they are reported apart rather than as one bucket.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DrainAbandoned {
    /// The client sent more after the rejection than we were willing to read.
    Budget,
    /// The deadline elapsed first: a stalled client, or one dripping slowly.
    Deadline,
    /// The stream failed, so the connection is already gone.
    StreamError,
}

impl DrainOutcome {
    fn as_metric_tag(&self) -> &'static str {
        match self {
            DrainOutcome::Drained => "drained",
            DrainOutcome::Abandoned(_) => "abandoned",
        }
    }

    fn reason_metric_tag(&self) -> &'static str {
        match self {
            DrainOutcome::Drained => "complete",
            DrainOutcome::Abandoned(DrainAbandoned::Budget) => "budget",
            DrainOutcome::Abandoned(DrainAbandoned::Deadline) => "deadline",
            DrainOutcome::Abandoned(DrainAbandoned::StreamError) => "stream_error",
        }
    }
}

/// Read and discard the rest of a request body we have already decided to reject.
///
/// Hyper cannot complete a keep-alive HTTP/1.1 response while the request body is
/// still unread; it tears the connection down instead, and the client sees a reset
/// rather than our status code. Consuming the remainder first lets the rejection be
/// delivered normally.
///
/// The read is bounded two ways: `budget` bytes, and `deadline` of wall-clock time
/// across the whole drain. Neither bound depends on the client's chunk cadence, so a
/// client cannot make us read indefinitely just to be told no. Only rejection paths
/// reach this, so it costs nothing on the happy path.
pub async fn drain_rejected_body<S>(
    stream: &mut S,
    budget: usize,
    deadline: Duration,
    path: &str,
) -> DrainOutcome
where
    S: Stream<Item = Result<Bytes, axum::Error>> + Unpin,
{
    let mut drained: usize = 0;
    let drain = async {
        loop {
            match stream.next().await {
                Some(Ok(chunk)) => {
                    drained += chunk.len();
                    if drained > budget {
                        break DrainOutcome::Abandoned(DrainAbandoned::Budget);
                    }
                }
                // The stream broke while we discarded it, so the connection is already gone.
                Some(Err(_)) => break DrainOutcome::Abandoned(DrainAbandoned::StreamError),
                None => break DrainOutcome::Drained,
            }
        }
    };

    // Covers both a client that stops sending and one that drips just fast enough
    // to keep a per-chunk timer alive.
    let outcome = tokio::time::timeout(deadline, drain)
        .await
        .unwrap_or(DrainOutcome::Abandoned(DrainAbandoned::Deadline));

    metrics::counter!(
        METRIC_REJECTED_BODY_DRAIN,
        "path" => path.to_string(),
        "outcome" => outcome.as_metric_tag(),
        "reason" => outcome.reason_metric_tag(),
    )
    .increment(1);

    if matches!(outcome, DrainOutcome::Abandoned(_)) {
        warn!(
            path = path,
            reason = outcome.reason_metric_tag(),
            drained_bytes = drained,
            budget = budget,
            "Rejected body drain abandoned; client may see a reset instead of our status"
        );
    }

    outcome
}

/// Extract body bytes from a streaming Body with a per-chunk timeout.
///
/// If `chunk_timeout` is None, reads the entire body without timeout (existing behavior).
/// If `chunk_timeout` is Some, each chunk read is wrapped in a timeout. If no data
/// arrives within the timeout window, returns `CaptureError::BodyReadTimeout`.
///
/// The `payload_size_limit` parameter enforces a maximum body size during streaming.
pub async fn extract_body_with_timeout(
    body: Body,
    payload_size_limit: usize,
    chunk_timeout: Option<Duration>,
    chunk_size_kb: usize,
    path: &str,
) -> Result<Bytes, CaptureError> {
    let mut stream = body.into_data_stream();
    let mut buf = BytesMut::with_capacity(std::cmp::min(payload_size_limit, chunk_size_kb * 1024));

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
                if buf.len() + chunk.len() > payload_size_limit {
                    // The drain can run for seconds. Holding the buffer and the
                    // oversize chunk across it turns every rejection into a memory
                    // spike the size of the limit we just refused.
                    drop(buf);
                    drop(chunk);
                    // Consume what is left so the 413 reaches the client rather than a
                    // connection reset. Bounded by the size we were willing to accept
                    // in the first place.
                    drain_rejected_body(
                        &mut stream,
                        payload_size_limit,
                        REJECTED_BODY_DRAIN_DEADLINE,
                        path,
                    )
                    .await;
                    return Err(CaptureError::EventTooBig(format!(
                        "Request body exceeds limit of {payload_size_limit} bytes"
                    )));
                }
                buf.put(chunk);
            }
            Some(Err(e)) => {
                return Err(CaptureError::RequestDecodingError(format!(
                    "Error reading request body: {e:#}"
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

/// Test-only stream builders shared by the readers' test modules.
#[cfg(test)]
pub(crate) mod test_support {
    use bytes::Bytes;
    use futures::{stream, Stream, StreamExt};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    /// A stream of `count` ten-byte chunks that records how many were pulled.
    pub(crate) fn counted_chunks(
        count: usize,
    ) -> (
        impl Stream<Item = Result<Bytes, axum::Error>> + Unpin,
        Arc<AtomicUsize>,
    ) {
        let pulled = Arc::new(AtomicUsize::new(0));
        let counter = pulled.clone();
        let chunks: Vec<Result<Bytes, axum::Error>> = (0..count)
            .map(|_| Ok(Bytes::from_static(b"0123456789")))
            .collect();
        let stream = Box::pin(stream::iter(chunks).inspect(move |_| {
            counter.fetch_add(1, Ordering::SeqCst);
        }));
        (stream, pulled)
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::counted_chunks;
    use super::*;
    use axum::body::Body;
    use bytes::Bytes;
    use futures::stream;
    use std::sync::atomic::Ordering;
    use std::time::Duration;

    const TEST_CHUNK_SIZE_KB: usize = 256;

    #[tokio::test]
    async fn drain_rejected_body_consumes_the_whole_stream() {
        let (mut stream, pulled) = counted_chunks(3);

        let outcome =
            drain_rejected_body(&mut stream, 1024, Duration::from_secs(30), "/test").await;

        assert_eq!(outcome, DrainOutcome::Drained);
        assert_eq!(pulled.load(Ordering::SeqCst), 3);
    }

    #[tokio::test]
    async fn drain_rejected_body_stops_once_the_budget_is_spent() {
        let (mut stream, pulled) = counted_chunks(10);

        // Budget of 25 bytes covers two ten-byte chunks; the third overruns it.
        let outcome = drain_rejected_body(&mut stream, 25, Duration::from_secs(30), "/test").await;

        assert_eq!(outcome, DrainOutcome::Abandoned(DrainAbandoned::Budget));
        assert_eq!(pulled.load(Ordering::SeqCst), 3);
    }

    #[tokio::test(start_paused = true)]
    async fn drain_rejected_body_gives_up_on_a_stalled_client() {
        let chunks: Vec<Result<Bytes, axum::Error>> = vec![Ok(Bytes::from_static(b"partial"))];
        let mut stream = Box::pin(stream::iter(chunks).chain(stream::pending()));

        let outcome =
            drain_rejected_body(&mut stream, 1024, Duration::from_millis(50), "/test").await;

        assert_eq!(outcome, DrainOutcome::Abandoned(DrainAbandoned::Deadline));
    }

    #[tokio::test]
    async fn drain_rejected_body_reports_a_broken_stream_apart_from_a_timeout() {
        // A mid-drain stream error must not be filed as budget or deadline: the
        // metric drives whether the budget is the value to change.
        let chunks: Vec<Result<Bytes, axum::Error>> = vec![
            Ok(Bytes::from_static(b"partial")),
            Err(axum::Error::new(std::io::Error::other("broken pipe"))),
        ];
        let mut stream = Box::pin(stream::iter(chunks));

        let outcome =
            drain_rejected_body(&mut stream, 1024, Duration::from_secs(30), "/test").await;

        assert_eq!(
            outcome,
            DrainOutcome::Abandoned(DrainAbandoned::StreamError)
        );
    }

    #[tokio::test(start_paused = true)]
    async fn drain_rejected_body_bounds_a_slow_drip_client() {
        // One byte every 10ms, forever. No single gap is long enough to trip a
        // per-chunk timer, and the byte budget alone would allow hours of this.
        let mut stream = Box::pin(stream::unfold((), |_| async {
            tokio::time::sleep(Duration::from_millis(10)).await;
            Some((Ok(Bytes::from_static(b"x")), ()))
        }));

        let started = tokio::time::Instant::now();
        let outcome = drain_rejected_body(
            &mut stream,
            10 * 1024 * 1024,
            Duration::from_secs(5),
            "/test",
        )
        .await;

        // The reason proves which bound fired; the elapsed check proves the
        // deadline was honored rather than the drip simply ending.
        assert_eq!(outcome, DrainOutcome::Abandoned(DrainAbandoned::Deadline));
        assert!(started.elapsed() < Duration::from_secs(6));
    }

    #[tokio::test]
    async fn extract_body_drains_an_oversize_body_before_rejecting() {
        // Four ten-byte chunks against a 25-byte limit: the third trips it, and the
        // fourth must still be pulled so hyper can deliver the 413 on a live
        // connection instead of resetting.
        let (stream, pulled) = counted_chunks(4);
        let body = Body::from_stream(stream);

        let result = extract_body_with_timeout(body, 25, None, TEST_CHUNK_SIZE_KB, "/test").await;

        assert!(matches!(result, Err(CaptureError::EventTooBig(_))));
        assert_eq!(pulled.load(Ordering::SeqCst), 4);
    }

    #[tokio::test]
    async fn test_extract_body_no_timeout() {
        let body = Body::from("hello world");
        let result = extract_body_with_timeout(body, 1024, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Bytes::from("hello world"));
    }

    #[tokio::test]
    async fn test_extract_body_with_timeout_success() {
        let body = Body::from("hello world");
        let timeout = Some(Duration::from_secs(5));
        let result =
            extract_body_with_timeout(body, 1024, timeout, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Bytes::from("hello world"));
    }

    #[tokio::test]
    async fn test_extract_body_exceeds_limit() {
        let body = Body::from("hello world this is a long message");
        let result = extract_body_with_timeout(body, 10, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(matches!(result, Err(CaptureError::EventTooBig(_))));
    }

    #[tokio::test]
    async fn test_extract_body_timeout_fires() {
        // Create a stream that yields one chunk then stalls forever
        let chunks: Vec<Result<Bytes, std::io::Error>> = vec![Ok(Bytes::from("partial"))];
        let slow_stream = stream::iter(chunks).chain(stream::pending());
        let body = Body::from_stream(slow_stream);

        let timeout = Some(Duration::from_millis(50));
        let result =
            extract_body_with_timeout(body, 1024, timeout, TEST_CHUNK_SIZE_KB, "/test").await;

        assert!(matches!(result, Err(CaptureError::BodyReadTimeout)));
    }

    #[tokio::test]
    async fn test_extract_body_empty() {
        let body = Body::empty();
        let result = extract_body_with_timeout(body, 1024, None, TEST_CHUNK_SIZE_KB, "/test").await;
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }
}
