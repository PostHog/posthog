//! The single gate every ingest handler passes a request through.
//!
//! Token handling used to be copy-pasted into each handler, which made it possible for a check
//! to reach some endpoints and not others. Resolving the token is only available here, together
//! with the checks, so a handler cannot obtain a token without having been authorized.

use std::sync::Arc;

use axum::http::HeaderMap;
use capture::token::validate_token;
use limiters::token_dropper::TokenDropper;
use metrics::counter;

use crate::errors::ApiError;
use crate::quota::{QuotaLimiter, Signal};

const REJECTED_COUNTER: &str = "capture_logs_requests_rejected_total";

#[derive(Clone)]
pub struct Authorizer {
    token_dropper: Arc<TokenDropper>,
    /// `None` when no quota Redis is configured, which leaves the service accepting everything
    /// exactly as it did before quota enforcement existed.
    quota_limiter: Option<Arc<QuotaLimiter>>,
}

impl Authorizer {
    pub fn new(token_dropper: Arc<TokenDropper>, quota_limiter: Option<Arc<QuotaLimiter>>) -> Self {
        Self {
            token_dropper,
            quota_limiter,
        }
    }

    /// Resolve the project token from `Authorization: Bearer <token>`, falling back to the
    /// `token` query parameter, then authorize it for `signal`.
    pub async fn authorize<'a>(
        &self,
        headers: &'a HeaderMap,
        query_token: Option<&'a str>,
        signal: Signal,
    ) -> Result<&'a str, ApiError> {
        let token = resolve_token(headers, query_token)
            .map_err(|error| self.reject(signal, "missing_token", error))?;
        self.authorize_token(token, signal).await?;
        Ok(token)
    }

    /// Authorize a token that the caller resolved itself. The Datadog endpoint accepts the token
    /// in a path segment and in a bare `Authorization` value, so it cannot use `authorize`.
    pub async fn authorize_token(&self, token: &str, signal: Signal) -> Result<(), ApiError> {
        if self.token_dropper.should_drop(token, "") {
            return Err(self.reject(
                signal,
                "dropped_token",
                ApiError::unauthorized("Invalid token"),
            ));
        }

        // Shape validation only rules out tokens that cannot be a project API key at all, such
        // as a personal API key pasted into an exporter. A well-formed token belonging to no
        // team still gets a 200 here and is dropped by the consumer, because resolving a token
        // to a team needs Postgres, which this service does not have.
        if let Err(reason) = validate_token(token) {
            return Err(self.reject(
                signal,
                "invalid_token",
                ApiError::unauthorized(format!(
                    "Invalid project API key ({reason}). Use your project API key, which you can find in your PostHog project settings."
                )),
            ));
        }

        if let Some(quota_limiter) = &self.quota_limiter {
            if let Some(retry_after) = quota_limiter.retry_after_if_limited(signal, token).await {
                return Err(self.reject(
                    signal,
                    "over_quota",
                    ApiError::quota_exceeded(
                        format!(
                            "Over the {} ingestion quota for this project. Raise your limit in billing settings, or wait for the quota to reset.",
                            signal.as_str()
                        ),
                        retry_after,
                    ),
                ));
            }
        }

        Ok(())
    }

    fn reject(&self, signal: Signal, reason: &'static str, error: ApiError) -> ApiError {
        counter!(REJECTED_COUNTER, "reason" => reason, "signal" => signal.as_str()).increment(1);
        error
    }
}

/// Bearer header first, `?token=` second, matching what the handlers did individually.
fn resolve_token<'a>(
    headers: &'a HeaderMap,
    query_token: Option<&'a str>,
) -> Result<&'a str, ApiError> {
    let missing = || ApiError::unauthorized("No token provided");

    if let Some(value) = headers.get("Authorization") {
        return value
            .to_str()
            .unwrap_or("")
            .split("Bearer ")
            .last()
            .filter(|token| !token.is_empty())
            .ok_or_else(missing);
    }

    query_token
        .filter(|token| !token.is_empty())
        .ok_or_else(missing)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;
    use axum::response::IntoResponse;
    use common_redis::MockRedisClient;
    use std::time::Duration;

    const RETRY_AFTER: u64 = 900;
    const LOGS_KEY: &str = "@posthog/quota-limits/logs_mb_ingested";

    fn headers(pairs: &[(&str, &str)]) -> HeaderMap {
        let mut headers = HeaderMap::new();
        for (name, value) in pairs {
            headers.insert(
                axum::http::HeaderName::from_bytes(name.as_bytes()).unwrap(),
                value.parse().unwrap(),
            );
        }
        headers
    }

    fn authorizer(limited_tokens: Vec<String>) -> Authorizer {
        let redis = MockRedisClient::new().zrangebyscore_ret(LOGS_KEY, limited_tokens);
        let quota = QuotaLimiter::new(Arc::new(redis), Duration::from_millis(5), None, RETRY_AFTER)
            .expect("failed to build quota limiter");
        Authorizer::new(Arc::new(TokenDropper::default()), Some(Arc::new(quota)))
    }

    fn status_of(error: ApiError) -> StatusCode {
        error.status()
    }

    /// The quota snapshot loads in a spawned task, so poll the observable condition rather than
    /// sleeping for a duration the test would have to guess.
    async fn await_rejected(authorizer: &Authorizer, token: &str) -> Option<ApiError> {
        for _ in 0..200 {
            if let Err(error) = authorizer.authorize_token(token, Signal::Logs).await {
                return Some(error);
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        None
    }

    #[tokio::test]
    async fn over_quota_is_rejected_with_a_retryable_throttle() {
        let authorizer = authorizer(vec!["phc_over".into()]);

        let error = await_rejected(&authorizer, "phc_over")
            .await
            .expect("an over-quota token should be rejected");

        let response = error.into_response();
        assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(
            response
                .headers()
                .get(axum::http::header::RETRY_AFTER)
                .and_then(|v| v.to_str().ok()),
            Some("900")
        );
    }

    #[tokio::test]
    async fn a_personal_api_key_is_rejected_instead_of_silently_accepted() {
        // Pasting a personal API key into an exporter is the misconfiguration that used to be
        // answered 200 forever while every record was dropped downstream.
        let authorizer = authorizer(vec![]);

        let error = authorizer
            .authorize_token("phx_personal_api_key", Signal::Logs)
            .await
            .expect_err("a personal API key should not be accepted");

        assert_eq!(status_of(error), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn structurally_impossible_tokens_are_rejected() {
        let authorizer = authorizer(vec![]);
        let too_long = "a".repeat(65);

        for token in [too_long.as_str(), "tokenwith\0nullbyte", "🦀"] {
            let error = authorizer
                .authorize_token(token, Signal::Logs)
                .await
                .expect_err("expected rejection");
            assert_eq!(status_of(error), StatusCode::UNAUTHORIZED, "{token:?}");
        }
    }

    #[tokio::test]
    async fn a_well_formed_token_within_quota_is_accepted() {
        let authorizer = authorizer(vec!["phc_over".into()]);

        assert!(authorizer
            .authorize_token("phc_within_quota", Signal::Logs)
            .await
            .is_ok());
    }

    #[tokio::test]
    async fn without_a_quota_limiter_nothing_is_throttled() {
        let authorizer = Authorizer::new(Arc::new(TokenDropper::default()), None);

        assert!(authorizer
            .authorize_token("phc_anything", Signal::Logs)
            .await
            .is_ok());
    }

    struct TokenSourceCase {
        name: &'static str,
        auth_header: Option<&'static str>,
        query_token: Option<&'static str>,
        expected: Option<&'static str>,
    }

    #[tokio::test]
    async fn token_comes_from_the_bearer_header_then_the_query_param() {
        let authorizer = authorizer(vec![]);

        let cases = [
            TokenSourceCase {
                name: "bearer header",
                auth_header: Some("Bearer phc_header"),
                query_token: None,
                expected: Some("phc_header"),
            },
            TokenSourceCase {
                name: "header wins over query param",
                auth_header: Some("Bearer phc_header"),
                query_token: Some("phc_query"),
                expected: Some("phc_header"),
            },
            TokenSourceCase {
                name: "query param fallback",
                auth_header: None,
                query_token: Some("phc_query"),
                expected: Some("phc_query"),
            },
            TokenSourceCase {
                name: "nothing provided",
                auth_header: None,
                query_token: None,
                expected: None,
            },
            TokenSourceCase {
                name: "empty query param",
                auth_header: None,
                query_token: Some(""),
                expected: None,
            },
            TokenSourceCase {
                name: "bearer with no token",
                auth_header: Some("Bearer "),
                query_token: None,
                expected: None,
            },
        ];

        for case in cases {
            let request_headers = match case.auth_header {
                Some(value) => headers(&[("Authorization", value)]),
                None => HeaderMap::new(),
            };
            let result = authorizer
                .authorize(&request_headers, case.query_token, Signal::Logs)
                .await;

            match case.expected {
                Some(token) => assert_eq!(result.ok(), Some(token), "{}", case.name),
                None => assert_eq!(
                    status_of(result.expect_err(case.name)),
                    StatusCode::UNAUTHORIZED,
                    "{}",
                    case.name
                ),
            }
        }
    }
}
