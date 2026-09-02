//! The single gate every ingest handler passes a request through.
//!
//! Token handling used to be copy-pasted into each handler, which made it possible for a check
//! to reach some endpoints and not others. Resolving the token is only available here, together
//! with the checks, so a handler cannot obtain a token without having been authorized.

use std::sync::Arc;

use axum::http::{HeaderMap, StatusCode};
use axum::response::Json;
use capture::token::validate_token;
use limiters::token_dropper::TokenDropper;
use metrics::counter;
use serde_json::json;
use tracing::error;

const REJECTED_COUNTER: &str = "capture_logs_requests_rejected_total";

/// The `(status, body)` pair the handlers already return, so a rejection needs no new plumbing.
type Rejection = (StatusCode, Json<serde_json::Value>);

/// The OTLP signal a request carries, used to label rejections so a spike can be attributed to
/// one signal rather than to capture-logs as a whole.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Signal {
    Logs,
    Metrics,
    Traces,
}

impl Signal {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Logs => "logs",
            Self::Metrics => "metrics",
            Self::Traces => "traces",
        }
    }
}

#[derive(Clone)]
pub struct Authorizer {
    token_dropper: Arc<TokenDropper>,
}

impl Authorizer {
    pub fn new(token_dropper: Arc<TokenDropper>) -> Self {
        Self { token_dropper }
    }

    /// Resolve the project token from `Authorization: Bearer <token>`, falling back to the
    /// `token` query parameter, then authorize it for `signal`.
    pub fn authorize<'a>(
        &self,
        headers: &'a HeaderMap,
        query_token: Option<&'a str>,
        signal: Signal,
    ) -> Result<&'a str, Rejection> {
        let token = resolve_token(headers, query_token)
            .map_err(|rejection| self.reject(signal, "missing_token", rejection))?;
        self.authorize_token(token, signal)?;
        Ok(token)
    }

    /// Authorize a token that the caller resolved itself. The Datadog endpoint accepts the token
    /// in a path segment and in a bare `Authorization` value, so it cannot use `authorize`.
    pub fn authorize_token(&self, token: &str, signal: Signal) -> Result<(), Rejection> {
        if self.token_dropper.should_drop(token, "") {
            return Err(self.reject(signal, "dropped_token", unauthorized("Invalid token")));
        }

        // Shape validation only rules out tokens that cannot be a project API key at all, such
        // as a personal API key pasted into an exporter. A well-formed token belonging to no
        // team still gets a 200 here and is dropped by the consumer, because resolving a token
        // to a team needs Postgres, which this service does not have.
        if let Err(reason) = validate_token(token) {
            error!("Rejecting request with an invalid project API key: {reason}");
            return Err(self.reject(
                signal,
                "invalid_token",
                unauthorized(format!(
                    "Invalid project API key ({reason}). Use your project API key, which you can find in your PostHog project settings."
                )),
            ));
        }

        Ok(())
    }

    fn reject(&self, signal: Signal, reason: &'static str, rejection: Rejection) -> Rejection {
        counter!(REJECTED_COUNTER, "reason" => reason, "signal" => signal.as_str()).increment(1);
        rejection
    }
}

fn unauthorized(message: impl Into<String>) -> Rejection {
    (
        StatusCode::UNAUTHORIZED,
        Json(json!({ "error": message.into() })),
    )
}

/// Bearer header first, `?token=` second, matching what the handlers did individually.
fn resolve_token<'a>(
    headers: &'a HeaderMap,
    query_token: Option<&'a str>,
) -> Result<&'a str, Rejection> {
    let missing = || {
        error!("No token provided");
        unauthorized("No token provided")
    };

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

    fn authorizer() -> Authorizer {
        Authorizer::new(Arc::new(TokenDropper::default()))
    }

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

    #[test]
    fn a_personal_api_key_is_rejected_instead_of_silently_accepted() {
        // Pasting a personal API key into an exporter is the misconfiguration that used to be
        // answered 200 forever while every record was dropped downstream.
        let (status, _) = authorizer()
            .authorize_token("phx_personal_api_key", Signal::Logs)
            .expect_err("a personal API key should not be accepted");

        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    #[test]
    fn structurally_impossible_tokens_are_rejected() {
        let too_long = "a".repeat(65);

        for token in [too_long.as_str(), "tokenwith\0nullbyte", "🦀", ""] {
            let (status, _) = authorizer()
                .authorize_token(token, Signal::Logs)
                .expect_err("expected rejection");
            assert_eq!(status, StatusCode::UNAUTHORIZED, "{token:?}");
        }
    }

    #[test]
    fn a_well_formed_token_is_accepted() {
        assert!(authorizer()
            .authorize_token("phc_well_formed", Signal::Logs)
            .is_ok());
    }

    struct TokenSourceCase {
        name: &'static str,
        auth_header: Option<&'static str>,
        query_token: Option<&'static str>,
        expected: Option<&'static str>,
    }

    #[test]
    fn token_comes_from_the_bearer_header_then_the_query_param() {
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
            let result = authorizer().authorize(&request_headers, case.query_token, Signal::Logs);

            match case.expected {
                Some(token) => assert_eq!(result.ok(), Some(token), "{}", case.name),
                None => assert_eq!(
                    result.expect_err(case.name).0,
                    StatusCode::UNAUTHORIZED,
                    "{}",
                    case.name
                ),
            }
        }
    }
}
