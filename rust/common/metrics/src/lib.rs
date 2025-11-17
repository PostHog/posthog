use std::time::{Instant, SystemTime};

use axum::{
    body::Body, extract::MatchedPath, http::Request, middleware::Next, response::IntoResponse,
    routing::get, Router,
};
use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};
use std::sync::OnceLock;

type LabelFilterFn =
    Box<dyn Fn(&[(String, String)]) -> Vec<(String, String)> + Send + Sync + 'static>;

static LABEL_FILTER: OnceLock<LabelFilterFn> = OnceLock::new();

pub fn set_label_filter<F>(filter: F)
where
    F: Fn(&[(String, String)]) -> Vec<(String, String)> + Send + Sync + 'static,
{
    let boxed_filter: LabelFilterFn = Box::new(filter);
    if LABEL_FILTER.set(boxed_filter).is_err() {
        panic!("Label filter already set");
    }
}

/// Bind a `TcpListener` on the provided bind address to serve a `Router` on it.
/// This function is intended to take a Router as returned by `setup_metrics_router`, potentially with more routes added by the caller.
pub async fn serve(router: Router, bind: &str) -> Result<(), std::io::Error> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, router).await?;

    Ok(())
}

/// Add the prometheus endpoint and middleware to a router, should be called last.
pub fn setup_metrics_routes(router: Router) -> Router {
    let recorder_handle = setup_metrics_recorder();

    router
        .route(
            "/metrics",
            get(move || std::future::ready(recorder_handle.render())),
        )
        .layer(axum::middleware::from_fn(track_metrics))
}

pub fn setup_metrics_recorder() -> PrometheusHandle {
    const BUCKETS: &[f64] = &[
        1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
    ];

    PrometheusBuilder::new()
        .set_buckets(BUCKETS)
        .unwrap()
        .install_recorder()
        .unwrap()
}

/// Middleware to record some common HTTP metrics
/// Someday tower-http might provide a metrics middleware: https://github.com/tower-rs/tower-http/issues/57
pub async fn track_metrics(req: Request<Body>, next: Next) -> impl IntoResponse {
    let start = Instant::now();

    let path = if let Some(matched_path) = req.extensions().get::<MatchedPath>() {
        matched_path.as_str().to_owned()
    } else {
        req.uri().path().to_owned()
    };

    let method = req.method().clone();

    // Run the rest of the request handling first, so we can measure it and get response
    // codes.
    let response = next.run(req).await;

    let latency = start.elapsed().as_secs_f64();
    let status = response.status().as_u16().to_string();

    let labels = [
        ("method", method.to_string()),
        ("path", path),
        ("status", status),
    ];

    metrics::counter!("http_requests_total", &labels).increment(1);
    metrics::histogram!("http_requests_duration_seconds", &labels).record(latency);

    response
}

/// Returns the number of seconds since the Unix epoch, to use in prom gauges.
/// Saturates to zero if the system time is set before epoch.
pub fn get_current_timestamp_seconds() -> f64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as f64
}

// Shorthand for common metric types
pub fn inc(name: &'static str, labels: &[(String, String)], value: u64) {
    let filtered_labels = apply_label_filter(labels);
    metrics::counter!(name, &filtered_labels).increment(value);
}

fn apply_label_filter(labels: &[(String, String)]) -> Vec<(String, String)> {
    if let Some(filter) = LABEL_FILTER.get() {
        filter(labels)
    } else {
        labels.to_vec()
    }
}

pub fn gauge(name: &'static str, lables: &[(String, String)], value: f64) {
    metrics::gauge!(name, lables).set(value);
}

pub fn histogram(name: &'static str, labels: &[(String, String)], value: f64) {
    let filtered_labels = apply_label_filter(labels);
    metrics::histogram!(name, &filtered_labels).record(value);
}

// A guard to record the time between creation and drop as a histogram entry
pub struct TimingGuard<'a> {
    name: &'static str,
    labels: TimingGuardLabels<'a>,
    start: Instant,
}

// Shorthand constructor for that guard
pub fn timing_guard<'a>(name: &'static str, labels: &'a [(String, String)]) -> TimingGuard<'a> {
    TimingGuard {
        name,
        labels: TimingGuardLabels::new(labels),
        start: Instant::now(),
    }
}

// Timing guards start out cheap to construct, but if you want to push extra
// labels onto them, they'll need to allocate. This enum tracks that state.
enum TimingGuardLabels<'a> {
    None,
    Borrowed(&'a [(String, String)]),
    Owned(Vec<(String, String)>),
}

impl TimingGuard<'_> {
    // This consumes the guard, making "label this span and then immediately report the timing"
    // a one-liner (simply don't re-bind the return value), but also it's a bit of a footgun.
    pub fn label(mut self, key: &str, value: &str) -> Self {
        self.labels.push_label(key, value);
        self
    }

    // This is meant to be used with the above to make what's happening more obvious. I don't know
    // if it's good enough, but it's an improvement.
    pub fn fin(self) {}
}

impl Drop for TimingGuard<'_> {
    fn drop(&mut self) {
        let labels = self.labels.as_slice();
        metrics::histogram!(self.name, labels).record(self.start.elapsed().as_millis() as f64);
    }
}

impl<'a> TimingGuardLabels<'a> {
    fn new(labels: &'a [(String, String)]) -> Self {
        if labels.is_empty() {
            TimingGuardLabels::None
        } else {
            TimingGuardLabels::Borrowed(labels)
        }
    }

    fn as_slice(&self) -> &[(String, String)] {
        match self {
            TimingGuardLabels::None => &[],
            TimingGuardLabels::Borrowed(labels) => labels,
            TimingGuardLabels::Owned(labels) => labels,
        }
    }

    fn push_label(&mut self, key: &str, value: &str) {
        match self {
            TimingGuardLabels::None => {
                *self = TimingGuardLabels::Owned(vec![(key.to_string(), value.to_string())]);
            }
            TimingGuardLabels::Borrowed(labels) => {
                let mut existing = labels.to_vec();
                existing.push((key.to_string(), value.to_string()));
                *self = TimingGuardLabels::Owned(existing);
            }
            TimingGuardLabels::Owned(labels) => {
                labels.push((key.to_string(), value.to_string()));
            }
        };
    }
}
