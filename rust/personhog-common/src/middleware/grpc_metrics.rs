use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use http::{Request, Response};
use metrics::{counter, histogram};
use pin_project::pin_project;
use tower::{Layer, Service};

/// Tower layer that instruments gRPC requests with timing metrics.
///
/// Records per request:
/// - `grpc_server_requests_total{service, method}` — counter
/// - `grpc_server_request_duration_ms{service, method}` — histogram
///
/// The `service` label distinguishes which personhog service emitted the metric
/// (e.g. `"router"` vs `"replica"`), so Grafana queries don't need to rely on
/// Prometheus job/instance labels.
#[derive(Clone)]
pub struct GrpcMetricsLayer {
    service_name: Arc<str>,
}

impl GrpcMetricsLayer {
    pub fn new(service_name: &str) -> Self {
        Self {
            service_name: Arc::from(service_name),
        }
    }
}

impl<S> Layer<S> for GrpcMetricsLayer {
    type Service = GrpcMetricsService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcMetricsService {
            inner: service,
            service_name: self.service_name.clone(),
        }
    }
}

/// Service wrapper that records metrics for each request.
#[derive(Clone)]
pub struct GrpcMetricsService<S> {
    inner: S,
    service_name: Arc<str>,
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for GrpcMetricsService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>> + Clone + Send + 'static,
    S::Future: Send,
    ReqBody: Send + 'static,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = GrpcMetricsFuture<S::Future>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        let start = Instant::now();

        // Extract method name from URI path (e.g., "/personhog.service.v1.PersonHogService/GetPerson")
        let method = extract_grpc_method(request.uri().path());

        let future = self.inner.call(request);

        GrpcMetricsFuture {
            inner: future,
            start,
            method,
            service_name: self.service_name.clone(),
        }
    }
}

/// Future wrapper that records metrics when the response completes.
#[pin_project]
pub struct GrpcMetricsFuture<F> {
    #[pin]
    inner: F,
    start: Instant,
    method: String,
    service_name: Arc<str>,
}

impl<F, ResBody, E> Future for GrpcMetricsFuture<F>
where
    F: Future<Output = Result<Response<ResBody>, E>>,
{
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        let result = this.inner.poll(cx);

        if result.is_ready() {
            let duration_ms = this.start.elapsed().as_secs_f64() * 1000.0;
            let service: &str = this.service_name;

            counter!(
                "grpc_server_requests_total",
                "service" => service.to_string(),
                "method" => this.method.clone(),
            )
            .increment(1);
            histogram!(
                "grpc_server_request_duration_ms",
                "service" => service.to_string(),
                "method" => this.method.clone(),
            )
            .record(duration_ms);
        }

        result
    }
}

/// Extract the gRPC method name from the URI path.
///
/// gRPC paths look like: `/package.Service/MethodName`
/// We extract just the method name part for cleaner metrics.
///
/// Cardinality is bounded because tonic rejects requests to unknown methods
/// before they reach this middleware.
fn extract_grpc_method(path: &str) -> String {
    path.rsplit_once('/')
        .map(|(_, method)| method)
        .filter(|m| !m.is_empty())
        .unwrap_or("unknown")
        .to_string()
}
