//! Admission control for a gRPC server at capacity.

use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use http::{HeaderValue, Request, Response};
use metrics::{counter, gauge, histogram};
use pin_project::pin_project;
use tokio::sync::{AcquireError, OwnedSemaphorePermit, Semaphore};
use tokio::time::error::Elapsed;
use tower::util::Oneshot;
use tower::{Layer, Service, ServiceExt};

use crate::{extract_client_name, extract_grpc_method};

/// Set on a response to a request the server refused before running it, so the caller
/// knows nothing was applied and may retry.
pub const NOT_APPLIED_HEADER: &str = "x-not-applied";

/// Tower layer that sheds gRPC requests when the server is at capacity.
///
/// A request that finds no permit is refused with `x-not-applied`, so the
/// caller knows nothing ran. [`with_wait`](Self::with_wait) lets it wait a
/// bounded time first, so a sub-second burst shows up as latency rather
/// than refusals. When `max_requests` is 0, the layer is a pass-through.
#[derive(Clone)]
pub struct GrpcLoadShedLayer {
    max_requests: usize,
    permits: Arc<Semaphore>,
    wait_for_slot: Duration,
    max_waiters: usize,
    waiters: Arc<AtomicUsize>,
    grpc_status: HeaderValue,
}

impl GrpcLoadShedLayer {
    pub fn new(max_requests: usize) -> Self {
        Self {
            max_requests,
            permits: Arc::new(Semaphore::new(max_requests)),
            wait_for_slot: Duration::ZERO,
            max_waiters: max_requests,
            waiters: Arc::new(AtomicUsize::new(0)),
            grpc_status: grpc_status_header(tonic::Code::Unavailable),
        }
    }

    pub fn with_code(mut self, code: tonic::Code) -> Self {
        self.grpc_status = grpc_status_header(code);
        self
    }

    /// Past `max_waiters` queued requests the pod sheds on arrival again:
    /// a deep queue is the signal that the overload is not a burst, and
    /// shedding late only holds the stream and body longer for the same
    /// answer. `max_waiters` of 0 means `max_requests`.
    pub fn with_wait(mut self, wait_for_slot: Duration, max_waiters: usize) -> Self {
        self.wait_for_slot = wait_for_slot;
        self.max_waiters = if max_waiters == 0 {
            self.max_requests
        } else {
            max_waiters
        };
        self
    }
}

fn grpc_status_header(code: tonic::Code) -> HeaderValue {
    HeaderValue::from(code as i32)
}

impl<S> Layer<S> for GrpcLoadShedLayer {
    type Service = GrpcLoadShedService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcLoadShedService {
            inner: service,
            max_requests: self.max_requests,
            permits: self.permits.clone(),
            wait_for_slot: self.wait_for_slot,
            max_waiters: self.max_waiters,
            waiters: self.waiters.clone(),
            grpc_status: self.grpc_status.clone(),
        }
    }
}

#[derive(Clone)]
pub struct GrpcLoadShedService<S> {
    inner: S,
    max_requests: usize,
    permits: Arc<Semaphore>,
    wait_for_slot: Duration,
    max_waiters: usize,
    waiters: Arc<AtomicUsize>,
    grpc_status: HeaderValue,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ShedReason {
    NoWait,
    QueueFull,
    WaitTimeout,
}

impl ShedReason {
    fn as_str(self) -> &'static str {
        match self {
            ShedReason::NoWait => "no_wait",
            ShedReason::QueueFull => "queue_full",
            ShedReason::WaitTimeout => "wait_timeout",
        }
    }
}

fn record_shed(method: Arc<str>, client: Arc<str>, reason: ShedReason) {
    counter!("grpc_server_load_shed_total",
        "method" => method,
        "client" => client,
        "reason" => reason.as_str(),
    )
    .increment(1);
}

fn shed_response<ResBody: Default>(grpc_status: &HeaderValue) -> Response<ResBody> {
    Response::builder()
        .status(200)
        .header("content-type", "application/grpc")
        .header("grpc-status", grpc_status.clone())
        .header("grpc-message", "Server at capacity")
        .header(NOT_APPLIED_HEADER, "load_shed")
        .body(ResBody::default())
        .unwrap()
}

/// Holds one waiter slot; dropping it releases the slot, so a client that
/// disconnects mid-wait cannot leak one.
pub struct WaiterSlot {
    waiters: Arc<AtomicUsize>,
}

impl Drop for WaiterSlot {
    fn drop(&mut self) {
        self.waiters.fetch_sub(1, Ordering::Relaxed);
        gauge!("grpc_server_admission_waiters").decrement(1.0);
    }
}

type AcquireFuture = Pin<
    Box<dyn Future<Output = Result<Result<OwnedSemaphorePermit, AcquireError>, Elapsed>> + Send>,
>;

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for GrpcLoadShedService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>> + Clone,
    ResBody: Default,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = GrpcLoadShedFuture<S, ReqBody, ResBody>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        if self.max_requests == 0 {
            return GrpcLoadShedFuture::Inner {
                inner: self.inner.call(request),
                permit: None,
            };
        }

        if let Ok(permit) = self.permits.clone().try_acquire_owned() {
            return GrpcLoadShedFuture::Inner {
                inner: self.inner.call(request),
                permit: Some(permit),
            };
        }

        let client = extract_client_name(&request);
        let method: Arc<str> = Arc::from(extract_grpc_method(request.uri().path()));

        if self.wait_for_slot.is_zero() {
            record_shed(method, client, ShedReason::NoWait);
            return GrpcLoadShedFuture::Shed {
                response: Some(shed_response(&self.grpc_status)),
            };
        }

        if self.waiters.fetch_add(1, Ordering::Relaxed) >= self.max_waiters {
            self.waiters.fetch_sub(1, Ordering::Relaxed);
            record_shed(method, client, ShedReason::QueueFull);
            return GrpcLoadShedFuture::Shed {
                response: Some(shed_response(&self.grpc_status)),
            };
        }
        gauge!("grpc_server_admission_waiters").increment(1.0);

        GrpcLoadShedFuture::Waiting {
            acquire: Box::pin(tokio::time::timeout(
                self.wait_for_slot,
                self.permits.clone().acquire_owned(),
            )),
            slot: Some(WaiterSlot {
                waiters: self.waiters.clone(),
            }),
            request: Some(request),
            service: Some(self.inner.clone()),
            method,
            client,
            started: Instant::now(),
            grpc_status: self.grpc_status.clone(),
        }
    }
}

/// The permit and the `WaiterSlot` release on drop, on completion and on
/// cancellation alike, which keeps the counts correct under client
/// disconnects.
#[pin_project(project = GrpcLoadShedFutureProj)]
pub enum GrpcLoadShedFuture<S, ReqBody, ResBody>
where
    S: Service<Request<ReqBody>>,
{
    Shed {
        response: Option<Response<ResBody>>,
    },
    Inner {
        #[pin]
        inner: S::Future,
        permit: Option<OwnedSemaphorePermit>,
    },
    Waiting {
        acquire: AcquireFuture,
        slot: Option<WaiterSlot>,
        request: Option<Request<ReqBody>>,
        service: Option<S>,
        method: Arc<str>,
        client: Arc<str>,
        started: Instant,
        grpc_status: HeaderValue,
    },
    /// `Oneshot` polls the clone's readiness, which `poll_ready` never
    /// covered.
    Admitted {
        #[pin]
        inner: Oneshot<S, Request<ReqBody>>,
        permit: OwnedSemaphorePermit,
    },
}

impl<S, ReqBody, ResBody> Future for GrpcLoadShedFuture<S, ReqBody, ResBody>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>>,
    ResBody: Default,
{
    type Output = Result<Response<ResBody>, S::Error>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let admitted = match self.as_mut().project() {
            GrpcLoadShedFutureProj::Shed { response } => {
                return Poll::Ready(Ok(response.take().unwrap()))
            }
            GrpcLoadShedFutureProj::Inner { inner, .. } => return inner.poll(cx),
            GrpcLoadShedFutureProj::Admitted { inner, .. } => return inner.poll(cx),
            GrpcLoadShedFutureProj::Waiting {
                acquire,
                slot,
                request,
                service,
                method,
                client,
                started,
                grpc_status,
            } => {
                let outcome = match acquire.as_mut().poll(cx) {
                    Poll::Pending => return Poll::Pending,
                    Poll::Ready(outcome) => outcome,
                };
                // Release the queue slot at the decision, not when hyper
                // drops the future.
                drop(slot.take());
                let waited_ms = started.elapsed().as_secs_f64() * 1000.0;
                match outcome {
                    Ok(Ok(permit)) => {
                        histogram!("grpc_server_admission_wait_ms",
                            "method" => method.clone(),
                            "client" => client.clone(),
                            "outcome" => "admitted",
                        )
                        .record(waited_ms);
                        let inner = service.take().unwrap().oneshot(request.take().unwrap());
                        GrpcLoadShedFuture::Admitted { inner, permit }
                    }
                    // The semaphore is never closed, so `Ok(Err)` cannot
                    // happen; shed rather than panic in a server path.
                    Ok(Err(_)) | Err(_) => {
                        histogram!("grpc_server_admission_wait_ms",
                            "method" => method.clone(),
                            "client" => client.clone(),
                            "outcome" => "shed",
                        )
                        .record(waited_ms);
                        record_shed(method.clone(), client.clone(), ShedReason::WaitTimeout);
                        return Poll::Ready(Ok(shed_response(grpc_status)));
                    }
                }
            }
        };
        self.set(admitted);
        self.poll(cx)
    }
}

#[cfg(test)]
mod tests {
    use std::convert::Infallible;

    use futures::poll;
    use tower::Layer;

    use super::*;

    fn grpc_request(path: &str) -> Request<()> {
        Request::builder().uri(path).body(()).unwrap()
    }

    /// Minimal service that immediately returns an empty 200 response.
    #[derive(Clone)]
    struct OkService;

    impl Service<Request<()>> for OkService {
        type Response = Response<()>;
        type Error = Infallible;
        type Future = std::future::Ready<Result<Response<()>, Infallible>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _req: Request<()>) -> Self::Future {
            std::future::ready(Ok(Response::new(())))
        }
    }

    /// Service that never resolves — useful for testing cancellation/drop.
    #[derive(Clone)]
    struct PendingService;

    impl Service<Request<()>> for PendingService {
        type Response = Response<()>;
        type Error = Infallible;
        type Future = std::future::Pending<Result<Response<()>, Infallible>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _req: Request<()>) -> Self::Future {
            std::future::pending()
        }
    }

    fn hold_pod_full(layer: &GrpcLoadShedLayer) -> Vec<GrpcLoadShedFuture<PendingService, (), ()>> {
        let mut svc = layer.layer(PendingService);
        (0..layer.max_requests)
            .map(|_| svc.call(grpc_request("/pkg.Svc/Held")))
            .collect()
    }

    fn waiting_layer(max_waiters: usize) -> GrpcLoadShedLayer {
        GrpcLoadShedLayer::new(1).with_wait(Duration::from_millis(500), max_waiters)
    }

    fn assert_shed(resp: &Response<()>, expected_status: &str) {
        assert_eq!(resp.headers().get("grpc-status").unwrap(), expected_status);
        assert_eq!(
            resp.headers().get("grpc-message").unwrap(),
            "Server at capacity"
        );
        assert_eq!(resp.headers().get(NOT_APPLIED_HEADER).unwrap(), "load_shed");
    }

    fn assert_admitted(resp: &Response<()>) {
        assert_eq!(resp.status(), 200);
        assert!(resp.headers().get("grpc-status").is_none());
    }

    #[tokio::test]
    async fn passthrough_when_disabled() {
        let layer = GrpcLoadShedLayer::new(0);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_admitted(&resp);
    }

    #[tokio::test]
    async fn allows_requests_under_limit() {
        let layer = GrpcLoadShedLayer::new(2);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_admitted(&resp);
    }

    #[tokio::test]
    async fn sheds_at_capacity() {
        for (layer, expected_status) in [
            (GrpcLoadShedLayer::new(2), "14"),
            (
                GrpcLoadShedLayer::new(2).with_code(tonic::Code::ResourceExhausted),
                "8",
            ),
        ] {
            let held = hold_pod_full(&layer);
            let mut svc = layer.layer(OkService);

            let resp = svc.call(grpc_request("/pkg.Svc/GetPerson")).await.unwrap();
            assert_shed(&resp, expected_status);
            assert_eq!(layer.permits.available_permits(), 0);
            drop(held);
            assert_eq!(layer.permits.available_permits(), 2);
        }
    }

    #[tokio::test]
    async fn permit_returns_on_completion() {
        let layer = GrpcLoadShedLayer::new(10);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_admitted(&resp);

        assert_eq!(layer.permits.available_permits(), 10);
    }

    #[tokio::test]
    async fn permit_returns_on_drop() {
        let layer = GrpcLoadShedLayer::new(10);
        let mut svc = layer.layer(PendingService);

        let future = svc.call(grpc_request("/pkg.Svc/Method"));
        assert_eq!(layer.permits.available_permits(), 9);

        // Drop without polling to completion — simulates request cancellation
        drop(future);
        assert_eq!(layer.permits.available_permits(), 10);
    }

    #[tokio::test(start_paused = true)]
    async fn waits_for_a_permit_that_frees_inside_the_window() {
        let layer = waiting_layer(4);
        let mut held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        let waiter = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(waiter);
        assert!(poll!(waiter.as_mut()).is_pending());
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);

        held.pop();
        let resp = waiter.await.unwrap();
        assert_admitted(&resp);
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn sheds_after_the_wait_window() {
        for (layer, expected_status) in [
            (waiting_layer(4), "14"),
            (
                waiting_layer(4).with_code(tonic::Code::ResourceExhausted),
                "8",
            ),
        ] {
            let _held = hold_pod_full(&layer);
            let mut svc = layer.layer(OkService);

            let start = tokio::time::Instant::now();
            let resp = svc.call(grpc_request("/pkg.Svc/GetPerson")).await.unwrap();
            assert!(start.elapsed() >= Duration::from_millis(500));
            assert_shed(&resp, expected_status);
            assert_eq!(layer.waiters.load(Ordering::Relaxed), 0);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn sheds_immediately_when_the_queue_is_full() {
        let layer = waiting_layer(1);
        let _held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        let first = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(first);
        assert!(poll!(first.as_mut()).is_pending());

        let start = tokio::time::Instant::now();
        let resp = svc.call(grpc_request("/pkg.Svc/GetPerson")).await.unwrap();
        assert_eq!(start.elapsed(), Duration::ZERO);
        assert_shed(&resp, "14");
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn dropped_waiter_frees_its_queue_slot() {
        let layer = waiting_layer(1);
        let _held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        {
            let first = svc.call(grpc_request("/pkg.Svc/GetPerson"));
            tokio::pin!(first);
            assert!(poll!(first.as_mut()).is_pending());
            assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);
        }
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 0);

        let second = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(second);
        assert!(poll!(second.as_mut()).is_pending());
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn earliest_waiter_takes_the_freed_permit() {
        let layer = waiting_layer(4);
        let mut held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        let first = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(first);
        let second = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(second);
        assert!(poll!(first.as_mut()).is_pending());
        assert!(poll!(second.as_mut()).is_pending());

        held.pop();
        assert!(poll!(second.as_mut()).is_pending());
        match poll!(first.as_mut()) {
            Poll::Ready(Ok(resp)) => assert_admitted(&resp),
            other => panic!("first waiter not admitted: {other:?}"),
        }
    }
}
