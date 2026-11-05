//! One `flags_request_outcome_total` count per `/flags` request. The middleware wraps
//! `TimeoutLayer`, so requests that the timeout or a client disconnect drops still count.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use axum::{
    extract::{MatchedPath, Request},
    http::StatusCode,
    middleware::Next,
    response::Response,
};
use strum::{EnumIter, IntoEnumIterator};

use crate::{
    api::errors::FlagError, metrics::consts::FLAG_REQUEST_OUTCOME_COUNTER, router::FLAGS_ROUTES,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, EnumIter)]
enum Outcome {
    /// 2xx, and no flag failed because a database or a timeout failed.
    Ok,
    /// 2xx, and at least one flag failed because a database or a timeout failed.
    Degraded,
    /// 5xx, including the 503 that the request timeout returns, or a panic in the handler.
    Error,
    /// 4xx: rate limits, auth failures and bad requests.
    Rejected,
    /// The client left before the server answered.
    Abandoned,
}

impl Outcome {
    fn of_response(status: StatusCode, marks: &OutcomeMarks) -> Self {
        if status.is_server_error() {
            Self::Error
        } else if status.is_client_error() {
            Self::Rejected
        } else if marks.degraded() {
            Self::Degraded
        } else {
            Self::Ok
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Ok => "ok",
            Self::Degraded => "degraded",
            Self::Error => "error",
            Self::Rejected => "rejected",
            Self::Abandoned => "abandoned",
        }
    }
}

/// Clones share the marks: evaluation writes them, and [`record_request_outcome`] reads them.
#[derive(Clone, Debug, Default)]
pub struct OutcomeMarks(Arc<Marks>);

// Relaxed is enough: the middleware reads the marks on the same task, after the handler future
// completes or is dropped.
#[derive(Debug, Default)]
struct Marks {
    needs_persons: AtomicBool,
    degraded: AtomicBool,
}

impl OutcomeMarks {
    /// Call before the persons DB work, so a request that the timeout drops keeps the label.
    pub fn mark_needs_persons(&self) {
        self.0.needs_persons.store(true, Ordering::Relaxed);
    }

    pub fn mark_flag_failed(&self, error: &FlagError) {
        if error.is_database_or_timeout_failure() {
            self.0.degraded.store(true, Ordering::Relaxed);
        }
    }

    /// Whether the request needed person data, even when no persons DB call ran.
    pub(crate) fn needs_persons(&self) -> bool {
        self.0.needs_persons.load(Ordering::Relaxed)
    }

    pub(crate) fn degraded(&self) -> bool {
        self.0.degraded.load(Ordering::Relaxed)
    }
}

/// Records `Abandoned` when dropped before `finish`, or `Error` when a handler panic drops it.
struct PendingOutcome(Option<OutcomeMarks>);

impl PendingOutcome {
    fn finish(mut self, status: StatusCode) {
        if let Some(marks) = self.0.take() {
            counter(Outcome::of_response(status, &marks), marks.needs_persons()).increment(1);
        }
    }
}

impl Drop for PendingOutcome {
    fn drop(&mut self) {
        if let Some(marks) = self.0.take() {
            // Tokio drops a panicking task's future while it unwinds, so a handler panic gets here
            // with `panicking()` true.
            let outcome = if std::thread::panicking() {
                Outcome::Error
            } else {
                Outcome::Abandoned
            };
            counter(outcome, marks.needs_persons()).increment(1);
        }
    }
}

fn counter(outcome: Outcome, needs_persons: bool) -> metrics::Counter {
    metrics::counter!(
        FLAG_REQUEST_OUTCOME_COUNTER,
        "outcome" => outcome.as_str(),
        "needs_persons" => if needs_persons { "true" } else { "false" }
    )
}

/// A ratio alert over a series that never fired evaluates to nothing.
pub fn precreate_request_outcome_counters() {
    for outcome in Outcome::iter() {
        for needs_persons in [false, true] {
            counter(outcome, needs_persons).increment(0);
        }
    }
}

/// Skips the definitions routes, which share the timeout stack.
pub async fn record_request_outcome(mut req: Request, next: Next) -> Response {
    let is_flags_request = req
        .extensions()
        .get::<MatchedPath>()
        .is_some_and(|path| FLAGS_ROUTES.contains(&path.as_str()));
    if !is_flags_request {
        return next.run(req).await;
    }

    let marks = OutcomeMarks::default();
    req.extensions_mut().insert(marks.clone());
    let pending = PendingOutcome(Some(marks));
    let response = next.run(req).await;
    pending.finish(response.status());
    response
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use axum::{
        body::Body, error_handling::HandleErrorLayer, extract::Extension, routing::get, Router,
    };
    use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
    use rstest::rstest;
    use tower::{timeout::TimeoutLayer, ServiceBuilder, ServiceExt};

    use super::*;

    const REQUEST_TIMEOUT: Duration = Duration::from_secs(1);

    #[derive(Clone, Copy)]
    enum Evaluation {
        Healthy,
        PersonsDbFailed,
        RateLimited,
        /// Needs person data and never finishes.
        Stalls,
        Panics,
    }

    async fn evaluate(evaluation: Evaluation, marks: OutcomeMarks) -> StatusCode {
        match evaluation {
            Evaluation::Healthy => StatusCode::OK,
            Evaluation::PersonsDbFailed => {
                marks.mark_needs_persons();
                marks.mark_flag_failed(&FlagError::DatabaseUnavailable);
                StatusCode::OK
            }
            Evaluation::RateLimited => StatusCode::TOO_MANY_REQUESTS,
            Evaluation::Stalls => {
                marks.mark_needs_persons();
                std::future::pending().await
            }
            Evaluation::Panics => panic!("evaluation panicked"),
        }
    }

    /// Production layer order: the outcome middleware wraps the timeout.
    fn app(evaluation: Evaluation) -> Router {
        Router::new()
            .route(
                "/flags",
                get(move |Extension(marks): Extension<OutcomeMarks>| evaluate(evaluation, marks)),
            )
            .route("/flags/definitions", get(|| async { StatusCode::OK }))
            .layer(
                ServiceBuilder::new()
                    .layer(HandleErrorLayer::new(|_: tower::BoxError| async {
                        StatusCode::SERVICE_UNAVAILABLE
                    }))
                    .layer(TimeoutLayer::new(REQUEST_TIMEOUT)),
            )
            .layer(axum::middleware::from_fn(record_request_outcome))
    }

    fn request(path: &str) -> Request {
        axum::http::Request::builder()
            .uri(path)
            .body(Body::empty())
            .unwrap()
    }

    fn recorded_outcomes(snapshotter: &Snapshotter) -> Vec<(String, String, u64)> {
        snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter_map(|(key, _, _, value)| {
                let key = key.key();
                let DebugValue::Counter(count) = value else {
                    return None;
                };
                let label = |name: &str| {
                    key.labels()
                        .find(|label| label.key() == name)
                        .map(|label| label.value().to_string())
                        .unwrap()
                };
                (key.name() == FLAG_REQUEST_OUTCOME_COUNTER)
                    .then(|| (label("outcome"), label("needs_persons"), count))
            })
            .collect()
    }

    #[rstest]
    #[case::healthy("/flags", Evaluation::Healthy, Some(("ok", "false")))]
    #[case::persons_db_failed("/flags", Evaluation::PersonsDbFailed, Some(("degraded", "true")))]
    #[case::rate_limited("/flags", Evaluation::RateLimited, Some(("rejected", "false")))]
    #[case::timed_out("/flags", Evaluation::Stalls, Some(("error", "true")))]
    #[case::panicked("/flags", Evaluation::Panics, Some(("error", "false")))]
    #[case::not_a_flags_route("/flags/definitions", Evaluation::Healthy, None)]
    #[tokio::test(start_paused = true)]
    async fn test_records_one_outcome_per_request(
        #[case] path: &str,
        #[case] evaluation: Evaluation,
        #[case] expected: Option<(&str, &str)>,
    ) {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        // Spawned, so a panic unwinds through a tokio task as it does in production.
        let joined = tokio::spawn(app(evaluation).oneshot(request(path))).await;
        assert_eq!(joined.is_err(), matches!(evaluation, Evaluation::Panics));

        let expected: Vec<_> = expected
            .into_iter()
            .map(|(outcome, needs_persons)| (outcome.to_string(), needs_persons.to_string(), 1))
            .collect();
        assert_eq!(recorded_outcomes(&snapshotter), expected);
    }

    #[tokio::test(start_paused = true)]
    async fn test_records_abandoned_when_the_client_leaves_first() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        let response = app(Evaluation::Stalls).oneshot(request("/flags"));
        let client_wait = REQUEST_TIMEOUT / 2;
        assert!(tokio::time::timeout(client_wait, response).await.is_err());

        assert_eq!(
            recorded_outcomes(&snapshotter),
            vec![("abandoned".to_string(), "true".to_string(), 1)]
        );
    }
}
