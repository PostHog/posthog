//! Serving middleware for PostHog gRPC servers.
//!
//! `personhog-common` carries its own copy of this layer alongside personhog's routing
//! contract. This crate holds the part that is not about personhog, so a service can take
//! request metrics without taking `personhog-proto`, sqlx, and the persons modules with it.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use http::{Request, Response};
use metrics::{counter, gauge, histogram};
use pin_project::{pin_project, pinned_drop};
use tower::{Layer, Service};

/// Header a caller sets to name itself. Requests without it are labelled `unknown`.
const CLIENT_NAME_HEADER: &str = "x-client-name";

/// Label for a failure carrying no gRPC status at all. Part of the same vocabulary as
/// [`code_as_str`], and deliberately distinct from its `unknown`, which is a real code a
/// server can return.
pub const NON_STATUS: &str = "non_status";

/// Stable snake_case name for a gRPC status code, for use as a metric label. Codes are a
/// fixed vocabulary, which is what makes them safe to label with; status *messages* never
/// are.
pub fn code_as_str(code: tonic::Code) -> &'static str {
    use tonic::Code;
    match code {
        Code::Ok => "ok",
        Code::Cancelled => "cancelled",
        Code::Unknown => "unknown",
        Code::InvalidArgument => "invalid_argument",
        Code::DeadlineExceeded => "deadline_exceeded",
        Code::NotFound => "not_found",
        Code::AlreadyExists => "already_exists",
        Code::PermissionDenied => "permission_denied",
        Code::ResourceExhausted => "resource_exhausted",
        Code::FailedPrecondition => "failed_precondition",
        Code::Aborted => "aborted",
        Code::OutOfRange => "out_of_range",
        Code::Unimplemented => "unimplemented",
        Code::Internal => "internal",
        Code::Unavailable => "unavailable",
        Code::DataLoss => "data_loss",
        Code::Unauthenticated => "unauthenticated",
    }
}

const MAX_HEADER_TAG_LEN: usize = 128;

fn is_safe_tag_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '/' | '_' | '-' | ':' | '.')
}

/// A caller-controlled value becomes a metric label, so an unbounded or hostile one becomes
/// unbounded cardinality. Anything outside the safe set collapses to `unknown`.
fn sanitize_header_tag(raw: &str) -> &str {
    let value = if raw.len() > MAX_HEADER_TAG_LEN {
        &raw[..MAX_HEADER_TAG_LEN]
    } else {
        raw
    };
    if value.chars().all(is_safe_tag_char) {
        value
    } else {
        "unknown"
    }
}

fn extract_client_name<B>(request: &Request<B>) -> Arc<str> {
    request
        .headers()
        .get(CLIENT_NAME_HEADER)
        .and_then(|value| value.to_str().ok())
        .filter(|value| !value.is_empty())
        .map(sanitize_header_tag)
        .unwrap_or("unknown")
        .into()
}

/// Extract the method name from a gRPC URI path, which looks like
/// `/package.Service/MethodName`.
///
/// `Server::layer` wraps tonic's router, so this runs before routing and sees the path of a
/// request no method will serve. The value is therefore caller-controlled and goes through
/// the same sanitizer as a header, or one client calling a wrong path mints a series per
/// path it tries.
fn extract_grpc_method(path: &str) -> &str {
    let method = path
        .rsplit_once('/')
        .map(|(_, method)| method)
        .filter(|method| !method.is_empty())
        .unwrap_or("unknown");
    sanitize_header_tag(method)
}

/// The `code` label for a response, in the [`code_as_str`] vocabulary.
///
/// A failed gRPC call is a trailers-only response: an empty body with `grpc-status` in the
/// headers. tonic gives a handler error that shape, so the layer reads the status at the
/// head and never polls the body. An absent header therefore means the handler returned Ok,
/// whose `grpc-status: 0` rides the body trailers instead.
///
/// This holds while every method is unary. A server-streaming method that failed part way
/// through its stream would read as `ok` here, and would need the trailers read from the
/// response body.
fn response_code(headers: &http::HeaderMap) -> &'static str {
    let Some(raw) = headers.get("grpc-status") else {
        return "ok";
    };
    raw.to_str()
        .ok()
        .and_then(|value| value.parse::<i32>().ok())
        .map_or(NON_STATUS, |code| code_as_str(tonic::Code::from_i32(code)))
}

/// Tower layer that instruments gRPC requests with timing and concurrency metrics.
///
/// Records:
/// - `grpc_server_requests_total` — counter with method, client and code labels
/// - `grpc_server_request_duration_ms` — histogram with method and client labels
/// - `grpc_server_requests_in_flight` — gauge with method and client labels
#[derive(Clone, Default)]
pub struct GrpcMetricsLayer;

impl<S> Layer<S> for GrpcMetricsLayer {
    type Service = GrpcMetricsService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcMetricsService { inner: service }
    }
}

#[derive(Clone)]
pub struct GrpcMetricsService<S> {
    inner: S,
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for GrpcMetricsService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>>,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = GrpcMetricsFuture<S::Future>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        let method: Arc<str> = Arc::from(extract_grpc_method(request.uri().path()));
        let client = extract_client_name(&request);
        gauge!("grpc_server_requests_in_flight", "method" => method.clone(), "client" => client.clone())
            .increment(1.0);

        GrpcMetricsFuture {
            inner: self.inner.call(request),
            method,
            client,
            start: Instant::now(),
        }
    }
}

/// Future returned by [`GrpcMetricsService`]. Lives inline in the caller's async state
/// machine, so instrumenting a request costs no heap allocation.
#[pin_project(PinnedDrop)]
pub struct GrpcMetricsFuture<F> {
    #[pin]
    inner: F,
    method: Arc<str>,
    client: Arc<str>,
    start: Instant,
}

impl<F, ResBody, E> Future for GrpcMetricsFuture<F>
where
    F: Future<Output = Result<Response<ResBody>, E>>,
{
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        let Poll::Ready(result) = this.inner.poll(cx) else {
            return Poll::Pending;
        };

        // A transport-level error never reached the handler, so it carries no gRPC status.
        let code = match result {
            Ok(ref response) => response_code(response.headers()),
            Err(_) => NON_STATUS,
        };
        counter!("grpc_server_requests_total",
            "method" => this.method.clone(),
            "client" => this.client.clone(),
            "code" => code)
        .increment(1);
        histogram!("grpc_server_request_duration_ms",
            "method" => this.method.clone(),
            "client" => this.client.clone())
        .record(this.start.elapsed().as_secs_f64() * 1000.0);

        Poll::Ready(result)
    }
}

/// Decrements the in-flight gauge on both normal completion and cancellation.
#[pinned_drop]
impl<F> PinnedDrop for GrpcMetricsFuture<F> {
    fn drop(self: Pin<&mut Self>) {
        let this = self.project();
        gauge!("grpc_server_requests_in_flight",
            "method" => this.method.clone(),
            "client" => this.client.clone())
        .decrement(1.0);
    }
}

#[cfg(test)]
mod tests {
    use std::convert::Infallible;

    use tower::ServiceExt;

    use super::*;

    /// Serves whatever response it is built with, so a test can drive the layer with the
    /// exact shape tonic produces.
    #[derive(Clone)]
    struct FixedService(http::StatusCode, Option<&'static str>);

    impl Service<Request<()>> for FixedService {
        type Response = Response<()>;
        type Error = Infallible;
        type Future = std::future::Ready<Result<Response<()>, Infallible>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _request: Request<()>) -> Self::Future {
            let mut builder = Response::builder().status(self.0);
            if let Some(status) = self.1 {
                builder = builder.header("grpc-status", status);
            }
            std::future::ready(Ok(builder.body(()).unwrap()))
        }
    }

    fn grpc_request(path: &str) -> Request<()> {
        Request::builder().uri(path).body(()).unwrap()
    }

    #[tokio::test]
    async fn the_layer_passes_the_response_through_untouched() {
        let service = GrpcMetricsLayer.layer(FixedService(http::StatusCode::OK, None));

        let response = service
            .oneshot(grpc_request("/pkg.Svc/Method"))
            .await
            .unwrap();

        assert_eq!(response.status(), 200);
        assert!(response.headers().get("grpc-status").is_none());
    }

    /// Serves the response tonic builds for a failed handler, which is the shape the layer
    /// has to read the status out of.
    #[derive(Clone)]
    struct StatusService(tonic::Code);

    impl Service<Request<()>> for StatusService {
        type Response = Response<tonic::body::BoxBody>;
        type Error = Infallible;
        type Future = std::future::Ready<Result<Self::Response, Infallible>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _request: Request<()>) -> Self::Future {
            std::future::ready(Ok(tonic::Status::new(self.0, "test").into_http()))
        }
    }

    #[test]
    fn the_counter_carries_the_method_client_and_code_of_a_real_response() {
        let recorder = metrics_util::debugging::DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .build()
            .unwrap();

        metrics::with_local_recorder(&recorder, || {
            let service = GrpcMetricsLayer.layer(StatusService(tonic::Code::NotFound));
            let request = Request::builder()
                .uri("/usage_ingestion.v1.UsageIngestion/IngestBillingUsage")
                .header("x-client-name", "feature-flags")
                .body(())
                .unwrap();
            runtime.block_on(service.oneshot(request)).unwrap();
        });

        let labels = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find(|(key, _, _, _)| key.key().name() == "grpc_server_requests_total")
            .map(|(key, _, _, _)| {
                let mut labels = key
                    .key()
                    .labels()
                    .map(|l| format!("{}={}", l.key(), l.value()))
                    .collect::<Vec<_>>();
                labels.sort();
                labels
            })
            .expect("the layer must count the request");

        assert_eq!(
            labels,
            vec![
                "client=feature-flags",
                "code=not_found",
                "method=IngestBillingUsage"
            ]
        );
    }

    #[test]
    fn a_handler_error_reads_as_its_own_code() {
        // Pinned against tonic rather than a hand-built response: the whole design rests on
        // tonic putting the status in the headers of a trailers-only response.
        let response = tonic::Status::not_found("nope").into_http();

        assert_eq!(response_code(response.headers()), "not_found");
    }

    #[test]
    fn response_code_vocabulary() {
        let code_for = |header: Option<&str>| {
            let mut headers = http::HeaderMap::new();
            if let Some(value) = header {
                headers.insert("grpc-status", value.parse().unwrap());
            }
            response_code(&headers)
        };

        // Absent means the handler returned Ok and grpc-status rides the body trailers.
        assert_eq!(code_for(None), "ok");
        assert_eq!(code_for(Some("0")), "ok");
        assert_eq!(code_for(Some("14")), "unavailable");
        // An out-of-range code is still a code; only an unparseable one is non_status.
        assert_eq!(code_for(Some("99")), "unknown");
        assert_eq!(code_for(Some("not-a-number")), NON_STATUS);
    }

    #[test]
    fn extract_method_from_grpc_path() {
        assert_eq!(
            extract_grpc_method("/package.Service/IngestBillingUsage"),
            "IngestBillingUsage"
        );
        assert_eq!(extract_grpc_method("/"), "unknown");
        assert_eq!(extract_grpc_method(""), "unknown");
    }

    #[test]
    fn a_method_that_would_blow_up_cardinality_becomes_unknown() {
        // This layer sits above tonic's router, so it labels paths no method will serve.
        assert_eq!(extract_grpc_method("/pkg.Svc/not a method"), "unknown");
        assert_eq!(
            extract_grpc_method(&format!("/pkg.Svc/{}", "a".repeat(8192))).len(),
            MAX_HEADER_TAG_LEN
        );
    }

    #[test]
    fn a_client_name_that_would_blow_up_cardinality_becomes_unknown() {
        let named = |value: &str| {
            let request = Request::builder()
                .uri("/pkg.Svc/Method")
                .header("x-client-name", value)
                .body(())
                .unwrap();
            extract_client_name(&request)
        };

        assert_eq!(&*named("feature-flags"), "feature-flags");
        assert_eq!(&*named(""), "unknown");
        assert_eq!(&*named("bad name!"), "unknown");
        assert_eq!(named(&"b".repeat(200)).len(), MAX_HEADER_TAG_LEN);
        assert_eq!(
            &*extract_client_name(&grpc_request("/pkg.Svc/Method")),
            "unknown"
        );
    }
}
