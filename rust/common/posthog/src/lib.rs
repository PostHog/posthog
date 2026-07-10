//! Internal PostHog telemetry for PostHog's own Rust services: global client
//! initialization and manual `$exception` capture with a process-wide rate
//! cap.

use std::future::Future;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, OnceLock};
use std::task::{Context, Waker};
use std::time::Instant;

use posthog_rs::PostHogError;
use serde_json::Value;

/// Hard cap on captured exceptions per process per minute. Bounds both outage
/// storms (every request failing at once) and self-amplification: cymbal
/// ingests the internal project's `$exception` events, i.e. its own captures.
const MAX_CAPTURES_PER_MINUTE: u32 = 10;

/// Terminal SDK delivery failures, counted once per `on_error` invocation.
/// Labeled `service` (the caller passed to [`init`]), `surface` (which SDK
/// network path failed), and `reason` (bounded failure class). Shared across
/// every service that inits through this crate; the `service` label keeps them
/// cleanly faceted regardless of scrape topology.
const SDK_DELIVERY_FAILURES: &str = "posthog_sdk_delivery_failures_total";

static SERVICE: OnceLock<ServiceContext> = OnceLock::new();
static CAPTURE_WINDOW: RateWindow = RateWindow::new();
static CLOCK_START: OnceLock<Instant> = OnceLock::new();

#[derive(Clone)]
struct ServiceContext {
    service: &'static str,
    pod: Option<String>,
    region: Option<String>,
}

/// Initialize the global PostHog client used for internal service telemetry
/// (product analytics events and exception capture).
///
/// `endpoint` accepts both a bare host (`https://us.i.posthog.com`) and the
/// legacy full capture URLs still present in deployment config (`…/i/v0/e/`,
/// `…/capture`); any capture path suffix is stripped before the host is
/// handed to the SDK, which appends endpoint paths itself.
///
/// Without an API key the global client is disabled and every capture is a
/// no-op.
pub async fn init(
    service: &'static str,
    api_key: Option<&str>,
    endpoint: &str,
) -> Result<(), posthog_rs::Error> {
    let context = SERVICE
        .get_or_init(|| ServiceContext {
            service,
            pod: std::env::var("POD_NAME")
                .or_else(|_| std::env::var("HOSTNAME"))
                .ok(),
            region: std::env::var("POSTHOG_REGION").ok(),
        })
        .clone();

    let Some(api_key) = api_key else {
        posthog_rs::disable_global();
        tracing::warn!("PostHog client disabled (no API key)");
        return Ok(());
    };

    // Exclude this crate's own frames from in-app classification so captured
    // stacks lead with the real service call site, not the shared wrapper.
    let error_tracking = posthog_rs::ErrorTrackingOptionsBuilder::default()
        .capture_panics(true)
        .in_app_exclude_paths(vec!["common_posthog::".to_string()])
        .build()
        .expect("all error tracking options have defaults");
    let options = posthog_rs::ClientOptionsBuilder::default()
        .api_key(api_key.to_string())
        .host(normalize_host(endpoint))
        .error_tracking(error_tracking)
        .before_send(move |event| prepare_event_for_capture(event, &context))
        // Observe terminal SDK delivery failures. Registering a hook silences the
        // SDK's default per-drop WARN, so the hook re-emits it alongside a metric.
        // Observability-only: must not re-enter the SDK.
        .on_error(move |err| report_sdk_error(service, err))
        .build()
        .expect("all client options have defaults");
    posthog_rs::init_global(options).await?;
    tracing::info!("PostHog client initialized");
    Ok(())
}

/// Capture a handled error as a personless `$exception` event, fire and
/// forget. Callers keep their `Arc` clone, so capturing never steals an error
/// that is still needed for a response or log line.
///
/// Events are stamped with the service identity from [`init`] plus
/// `properties`. At most [`MAX_CAPTURES_PER_MINUTE`] captures per process are
/// sent; beyond that they are silently dropped.
pub fn capture_exception<E>(
    error: Arc<E>,
    properties: impl IntoIterator<Item = (&'static str, Value)>,
) where
    E: std::error::Error + Send + Sync + 'static,
{
    if posthog_rs::global_is_disabled() {
        return;
    }

    if !CAPTURE_WINDOW.allows(clock_window_minutes(), MAX_CAPTURES_PER_MINUTE) {
        return;
    }

    // Strings and pre-built JSON values always serialize.
    let prop_err = "string and JSON property values always serialize";
    let mut options = posthog_rs::CaptureExceptionOptions::new();
    for (key, value) in properties {
        options = options.property(key, value).expect(prop_err);
    }

    let send = async move {
        if let Err(e) = posthog_rs::capture_exception_with(&*error, options).await {
            tracing::error!(error = ?e, "Failed to capture exception to PostHog");
        }
    };

    // The SDK builds the event (including the capture-site backtrace) eagerly,
    // before its first await point. Polling once on the caller's stack makes
    // that backtrace show real frames instead of a tokio worker; only the
    // pending network send moves to a task.
    let mut send = Box::pin(send);
    let mut cx = Context::from_waker(Waker::noop());
    if send.as_mut().poll(&mut cx).is_pending() {
        tokio::spawn(send);
    }
}

fn prepare_event_for_capture(
    mut event: posthog_rs::Event,
    context: &ServiceContext,
) -> Option<posthog_rs::Event> {
    if is_fatal_exception(&event)
        && !CAPTURE_WINDOW.allows(clock_window_minutes(), MAX_CAPTURES_PER_MINUTE)
    {
        return None;
    }

    let prop_err = "string property values always serialize";
    event
        .insert_prop("service", context.service)
        .expect(prop_err);
    if let Some(pod) = &context.pod {
        event.insert_prop("pod", pod.as_str()).expect(prop_err);
    }
    if let Some(region) = &context.region {
        event
            .insert_prop("region", region.as_str())
            .expect(prop_err);
    }
    Some(event)
}

fn is_fatal_exception(event: &posthog_rs::Event) -> bool {
    event.event_name() == "$exception"
        && event
            .properties()
            .get("$exception_level")
            .and_then(Value::as_str)
            == Some("fatal")
}

/// Emit the delivery-failure metric and a log breadcrumb for one terminal SDK
/// failure. Wired as the client's `on_error` hook in [`init`]; runs on whichever
/// SDK thread hit the failure, stays allocation-light, and never calls back into
/// the SDK.
///
/// The `warn!` restores the signal the SDK emitted before a hook took over:
/// registering `on_error` suppresses the SDK's own default per-drop `warn!`, so
/// without this we would go dark on logs. `warn`, not `error`, matches that
/// default and the severity of dropped telemetry (degraded, not fatal); it fires
/// only on terminal failure (post-retry), so it stays bounded.
fn report_sdk_error(service: &'static str, err: &PostHogError<'_>) {
    let (surface, reason) = classify_sdk_error(err);
    metrics::counter!(
        SDK_DELIVERY_FAILURES,
        "service" => service,
        "surface" => surface,
        "reason" => reason,
    )
    .increment(1);
    tracing::warn!(
        service,
        surface,
        reason,
        "posthog-rs dropped telemetry after terminal delivery failure"
    );
}

/// Map a `PostHogError` to bounded `(surface, reason)` metric labels. `surface`
/// is the SDK network path that failed; `reason` classifies the cause. Both are
/// `&'static str` to keep the label set low-cardinality. `PostHogError` is
/// `#[non_exhaustive]`, hence the catch-all arm.
fn classify_sdk_error(err: &PostHogError<'_>) -> (&'static str, &'static str) {
    match err {
        // A capture failure with no underlying error is the capture-v1 2xx
        // whose per-event verdicts left events unpersisted (no transport error).
        PostHogError::Capture(f) => (
            "capture",
            f.error().map_or("partial_drop", sdk_error_reason),
        ),
        PostHogError::FeatureFlags(f) => ("flags", sdk_error_reason(f.error())),
        PostHogError::LocalEvaluation(f) => ("local_evaluation", sdk_error_reason(f.error())),
        _ => ("unknown", "other"),
    }
}

/// Bounded failure class for a `posthog_rs::Error`. Mirrors the tag split the
/// batch-import-worker uses so `quota` (expected billing enforcement) stays
/// separable from actionable transport/server failures in alerts.
/// `posthog_rs::Error` is `#[non_exhaustive]`, hence the catch-all arm.
fn sdk_error_reason(err: &posthog_rs::Error) -> &'static str {
    match err {
        posthog_rs::Error::BillingLimitExceeded(_) => "quota",
        posthog_rs::Error::BadRequest(_) => "bad_request",
        posthog_rs::Error::ServerError { .. } => "server_error",
        posthog_rs::Error::RateLimit => "rate_limited",
        posthog_rs::Error::Unauthorized => "unauthorized",
        posthog_rs::Error::Connection(_) => "transport",
        posthog_rs::Error::Serialization(_) => "serialization",
        _ => "other",
    }
}

/// Strip a legacy capture path suffix from a configured PostHog endpoint,
/// leaving the bare host the SDK expects.
fn normalize_host(endpoint: &str) -> String {
    let trimmed = endpoint.trim().trim_end_matches('/');
    let trimmed = trimmed
        .strip_suffix("/i/v0/e")
        .or_else(|| trimmed.strip_suffix("/capture"))
        .unwrap_or(trimmed);
    trimmed.trim_end_matches('/').to_string()
}

fn clock_window_minutes() -> u64 {
    CLOCK_START.get_or_init(Instant::now).elapsed().as_secs() / 60
}

/// Windowed counter for the capture cap. The reset is not atomic with the
/// increment, so captures racing a window change can be over-allowed or
/// over-suppressed by a few; the cap is a safety bound, not an exact quota.
struct RateWindow {
    window: AtomicU64,
    count: AtomicU32,
}

impl RateWindow {
    const fn new() -> Self {
        Self {
            window: AtomicU64::new(0),
            count: AtomicU32::new(0),
        }
    }

    fn allows(&self, window: u64, max: u32) -> bool {
        if self.window.swap(window, Ordering::Relaxed) != window {
            self.count.store(0, Ordering::Relaxed);
        }
        self.count.fetch_add(1, Ordering::Relaxed) < max
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_host_strips_capture_suffixes() {
        let cases = [
            ("https://us.i.posthog.com", "https://us.i.posthog.com"),
            ("https://us.i.posthog.com/", "https://us.i.posthog.com"),
            (
                "https://us.i.posthog.com/i/v0/e/",
                "https://us.i.posthog.com",
            ),
            (
                "https://us.i.posthog.com/i/v0/e",
                "https://us.i.posthog.com",
            ),
            (
                "https://us.i.posthog.com/capture",
                "https://us.i.posthog.com",
            ),
            (
                "https://us.i.posthog.com/capture/",
                "https://us.i.posthog.com",
            ),
            (" http://localhost:8010/i/v0/e/ ", "http://localhost:8010"),
            (
                "http://capture.posthog.svc:3000",
                "http://capture.posthog.svc:3000",
            ),
        ];
        for (input, expected) in cases {
            assert_eq!(normalize_host(input), expected, "input: {input:?}");
        }
    }

    #[test]
    fn rate_window_caps_within_a_window() {
        let limiter = RateWindow::new();
        for _ in 0..3 {
            assert!(limiter.allows(7, 3));
        }
        assert!(!limiter.allows(7, 3));
        assert!(!limiter.allows(7, 3));
    }

    #[test]
    fn rate_window_resets_on_new_window() {
        let limiter = RateWindow::new();
        for _ in 0..3 {
            assert!(limiter.allows(1, 3));
        }
        assert!(!limiter.allows(1, 3));
        assert!(limiter.allows(2, 3));
    }

    #[test]
    fn sdk_error_reason_maps_every_variant() {
        use posthog_rs::Error;
        // The exact tag per variant is an alerting contract: `quota` (expected
        // billing enforcement) MUST stay separable from actionable failures.
        let cases: &[(Error, &str)] = &[
            (Error::BillingLimitExceeded("x".into()), "quota"),
            (Error::BadRequest("x".into()), "bad_request"),
            (
                Error::ServerError {
                    status: 503,
                    message: "x".into(),
                },
                "server_error",
            ),
            (Error::RateLimit, "rate_limited"),
            (Error::Unauthorized, "unauthorized"),
            (Error::Connection("x".into()), "transport"),
            (Error::Serialization("x".into()), "serialization"),
            // A variant outside the classified set maps safely via the
            // non_exhaustive catch-all instead of panicking.
            (Error::NotInitialized, "other"),
        ];
        for (err, expected) in cases {
            assert_eq!(sdk_error_reason(err), *expected, "reason for {err:?}");
        }
    }
}
