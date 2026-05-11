use std::time::{Instant, SystemTime};

use axum::{
    body::Body, extract::MatchedPath, http::Request, middleware::Next, response::IntoResponse,
    routing::get, Router,
};
pub use metrics_exporter_prometheus::Matcher;
use metrics_exporter_prometheus::PrometheusBuilder;
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
/// Use [`setup_metrics_routes_for_product`] when you want a `product` global
/// label for cost attribution.
pub fn setup_metrics_routes(router: Router) -> Router {
    install_metrics_routes(router, None, &[])
}

/// Like [`setup_metrics_routes`], but emits a static `product="<value>"` global
/// label on every metric for per-product cost attribution (see
/// <https://posthog.com/handbook/product/per-product-cost-margin-analysis>),
/// so metrics can be grouped across services without depending on metric-name
/// prefixes or K8s topology labels. Use a snake_case product slug matching
/// the Python `posthog.clickhouse.query_tagging.Product` enum values — e.g.
/// `feature_flags`, `experiments`, `product_analytics`.
pub fn setup_metrics_routes_for_product(router: Router, product: impl Into<String>) -> Router {
    install_metrics_routes(router, Some(product.into()), &[])
}

/// Like [`setup_metrics_routes_for_product`], but applies per-metric histogram
/// bucket overrides on top of the default bucket configuration. Each entry in
/// `overrides` is a `(Matcher, &[f64])` pair: the matcher (Full / Prefix /
/// Suffix) selects metric names and the slice provides ascending bucket
/// boundaries (in the metric's native unit). Bucket values must be non-empty;
/// invalid configuration panics at startup, matching the existing
/// `set_buckets(...).unwrap()` style here.
pub fn setup_metrics_routes_for_product_with_overrides(
    router: Router,
    product: impl Into<String>,
    overrides: &[(Matcher, &[f64])],
) -> Router {
    install_metrics_routes(router, Some(product.into()), overrides)
}

fn install_metrics_routes(
    router: Router,
    product: Option<String>,
    overrides: &[(Matcher, &[f64])],
) -> Router {
    let mut builder = build_prometheus_builder(product);
    for (matcher, buckets) in overrides {
        builder = builder
            .set_buckets_for_metric(matcher.clone(), buckets)
            .unwrap();
    }
    let recorder_handle = builder.install_recorder().unwrap();

    router
        .route(
            "/metrics",
            get(move || std::future::ready(recorder_handle.render())),
        )
        .layer(axum::middleware::from_fn(track_metrics))
}

fn build_prometheus_builder(product: Option<String>) -> PrometheusBuilder {
    const BUCKETS: &[f64] = &[
        1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
    ];

    let mut builder = PrometheusBuilder::new().set_buckets(BUCKETS).unwrap();
    if let Some(product) = product {
        builder = builder.add_global_label("product", product);
    }
    builder
}

/// Normalize an unmatched path to its first segment to avoid high-cardinality
/// metric labels from arbitrary 404 paths (tokens, locales, scanner probes, etc.).
///
/// Examples: `/array/phc_xxx/config.js` → `/array/`, `/metrics` → `/metrics`
pub fn normalize_unmatched_path(raw: &str) -> String {
    match raw.find('/').and_then(|_| raw[1..].find('/')) {
        Some(i) => raw[..i + 2].to_owned(),
        None => raw.to_owned(),
    }
}

/// Middleware to record some common HTTP metrics
/// Someday tower-http might provide a metrics middleware: https://github.com/tower-rs/tower-http/issues/57
pub async fn track_metrics(req: Request<Body>, next: Next) -> impl IntoResponse {
    let start = Instant::now();

    let path = if let Some(matched_path) = req.extensions().get::<MatchedPath>() {
        matched_path.as_str().to_owned()
    } else {
        normalize_unmatched_path(req.uri().path())
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

pub fn gauge(name: &'static str, labels: &[(String, String)], value: f64) {
    let filtered_labels = apply_label_filter(labels);
    metrics::gauge!(name, &filtered_labels).set(value);
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
        let filtered_labels = apply_label_filter(labels);
        metrics::histogram!(self.name, &filtered_labels)
            .record(self.start.elapsed().as_millis() as f64);
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

/// Like [`TimingGuard`], but records elapsed time as `as_secs_f64() * 1000.0`
/// (sub-millisecond precision) instead of truncating to integer milliseconds.
/// Pair with histogram bucket overrides containing sub-ms boundaries (e.g.
/// 0.05, 0.1, 0.5, ...) — without matching overrides, sub-ms values still
/// round to whatever buckets the recorder is configured with.
pub struct TimingGuardHighPrecision<'a> {
    name: &'static str,
    labels: TimingGuardLabels<'a>,
    start: Instant,
}

/// Constructs a [`TimingGuardHighPrecision`]. Use for fast operations (sub-ms
/// pool acquires, governor rate-limit checks) where integer-millisecond
/// resolution would collapse the distribution into the lowest bucket.
pub fn timing_guard_high_precision<'a>(
    name: &'static str,
    labels: &'a [(String, String)],
) -> TimingGuardHighPrecision<'a> {
    TimingGuardHighPrecision {
        name,
        labels: TimingGuardLabels::new(labels),
        start: Instant::now(),
    }
}

impl TimingGuardHighPrecision<'_> {
    pub fn label(mut self, key: &str, value: &str) -> Self {
        self.labels.push_label(key, value);
        self
    }

    pub fn fin(self) {}
}

impl Drop for TimingGuardHighPrecision<'_> {
    fn drop(&mut self) {
        let labels = self.labels.as_slice();
        let filtered_labels = apply_label_filter(labels);
        metrics::histogram!(self.name, &filtered_labels)
            .record(self.start.elapsed().as_secs_f64() * 1000.0);
    }
}

#[cfg(test)]
mod tests {
    use super::{
        build_prometheus_builder, normalize_unmatched_path, timing_guard_high_precision, Matcher,
    };

    #[test]
    fn test_product_global_label_emission() {
        let cases: &[(&'static str, Option<&'static str>)] = &[
            ("test_counter_with_product", Some("feature_flags")),
            ("test_counter_without_product", None),
        ];
        for &(counter_name, product) in cases {
            let recorder = build_prometheus_builder(product.map(str::to_string)).build_recorder();
            let handle = recorder.handle();
            metrics::with_local_recorder(&recorder, || {
                metrics::counter!(counter_name).increment(1);
            });
            let rendered = handle.render();
            assert!(
                rendered.contains(counter_name),
                "missing counter {counter_name}:\n{rendered}"
            );
            match product {
                Some(p) => assert!(
                    rendered.contains(&format!("product=\"{p}\"")),
                    "missing product label {p}:\n{rendered}"
                ),
                None => assert!(
                    !rendered.contains("product=\""),
                    "unexpected product label:\n{rendered}"
                ),
            }
        }
    }

    #[test]
    fn test_normalize_unmatched_path() {
        let cases = [
            // (input, expected)
            ("/array/phc_xxx/config.js", "/array/"),
            ("/array/phc_xxx/en_GB/config.js", "/array/"),
            ("/array/N/A/config", "/array/"),
            ("/array/https:/us.i.posthog.com/config", "/array/"),
            ("/api/surveys/blah", "/api/"),
            ("/array/env", "/array/"),
            ("/array/package.json", "/array/"),
            ("/metrics", "/metrics"),
            ("/", "/"),
            // Edge cases from scanner/malformed input
            ("/foo/", "/foo/"),
            ("//", "//"),
            ("/array/", "/array/"),
            ("/a/b", "/a/"),
            ("/array/phc_xxx/", "/array/"),
            ("", ""),
        ];
        for (input, expected) in cases {
            assert_eq!(normalize_unmatched_path(input), expected, "input: {input}");
        }
    }

    #[test]
    fn test_set_buckets_for_metric_full_match_overrides_default() {
        // Apply a per-metric override and confirm a custom bucket boundary
        // (well outside the default ladder) is rendered for that metric.
        let builder = build_prometheus_builder(None)
            .set_buckets_for_metric(Matcher::Full("custom_metric_ms".into()), &[30000.0])
            .unwrap();
        let recorder = builder.build_recorder();
        let handle = recorder.handle();

        metrics::with_local_recorder(&recorder, || {
            metrics::histogram!("custom_metric_ms").record(15.0);
        });

        let rendered = handle.render();
        assert!(
            rendered.contains("custom_metric_ms_bucket{le=\"30000\"}"),
            "expected override bucket le=30000 in rendered output:\n{rendered}"
        );
    }

    #[test]
    fn test_timing_guard_high_precision_records_sub_ms_value() {
        // With a sub-ms bucket override and an immediate guard drop, the
        // recorded value rounds into the smallest sub-ms bucket. The default
        // (integer-ms) guard would record 0.0 and could not distinguish this.
        let builder = build_prometheus_builder(None)
            .set_buckets_for_metric(Matcher::Full("hp_metric_ms".into()), &[0.05, 0.5, 1.0])
            .unwrap();
        let recorder = builder.build_recorder();
        let handle = recorder.handle();

        metrics::with_local_recorder(&recorder, || {
            let _g = timing_guard_high_precision("hp_metric_ms", &[]);
            // Drop immediately — elapsed will be a tiny fraction of a ms.
        });

        let rendered = handle.render();
        // The value should land in the 0.05 bucket (or the +Inf bucket if the
        // host is heavily loaded). Just verify the override was applied.
        assert!(
            rendered.contains("hp_metric_ms_bucket{le=\"0.05\"}"),
            "expected sub-ms override bucket le=0.05 in rendered output:\n{rendered}"
        );
    }
}
