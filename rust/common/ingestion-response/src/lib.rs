//! The response contract between ingestion and the batch services it calls. The README is the spec.

use std::convert::Infallible;

use axum::{
    async_trait,
    extract::FromRequestParts,
    http::{request::Parts, HeaderName, HeaderValue},
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

pub const HEADER: HeaderName = HeaderName::from_static("x-posthog-ingestion-response");
pub const VERSION: &str = "1";

pub mod codes {
    pub const INVALID_INPUT: &str = "invalid_input";
    pub const DEADLINE_EXCEEDED: &str = "deadline_exceeded";
}

/// Whether the caller sent [`HEADER`] with [`VERSION`] and can take per-item results.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PerItemResults(pub bool);

#[async_trait]
impl<S: Send + Sync> FromRequestParts<S> for PerItemResults {
    type Rejection = Infallible;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        let requested = parts
            .headers
            .get(&HEADER)
            .and_then(|value| value.to_str().ok())
            .is_some_and(|value| value.trim() == VERSION);
        Ok(Self(requested))
    }
}

/// The response body. Answering with it echoes [`HEADER`], which tells the client to read
/// per-item results.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemResults<T> {
    results: Vec<ItemResult<T>>,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{actual} item results for {expected} request items")]
pub struct LengthMismatch {
    pub expected: usize,
    pub actual: usize,
}

impl<T> ItemResults<T> {
    pub fn new(request_items: usize, results: Vec<ItemResult<T>>) -> Result<Self, LengthMismatch> {
        if results.len() != request_items {
            return Err(LengthMismatch {
                expected: request_items,
                actual: results.len(),
            });
        }
        Ok(Self { results })
    }

    pub fn into_results(self) -> Vec<ItemResult<T>> {
        self.results
    }
}

impl<T: Serialize> IntoResponse for ItemResults<T> {
    fn into_response(self) -> Response {
        ([(HEADER, HeaderValue::from_static(VERSION))], Json(self)).into_response()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemResult<T> {
    #[serde(flatten)]
    pub outcome: Outcome<T>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<Warning>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum Outcome<T> {
    Ok { value: T },
    Drop { reason: String },
    Retry { error: ItemError },
    Fail { error: ItemError },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ItemError {
    pub code: String,
    pub message: String,
}

/// An ingestion warning for the team that sent the item. `warning_type` must be a type in the
/// ingestion warnings registry.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Warning {
    #[serde(rename = "type")]
    pub warning_type: String,
    pub details: Map<String, Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,
}

impl<T> ItemResult<T> {
    pub fn ok(value: T) -> Self {
        Outcome::Ok { value }.into()
    }

    pub fn drop(reason: impl Into<String>) -> Self {
        Outcome::Drop {
            reason: reason.into(),
        }
        .into()
    }

    pub fn retry(code: impl Into<String>, message: impl Into<String>) -> Self {
        Outcome::Retry {
            error: ItemError::new(code, message),
        }
        .into()
    }

    pub fn fail(code: impl Into<String>, message: impl Into<String>) -> Self {
        Outcome::Fail {
            error: ItemError::new(code, message),
        }
        .into()
    }

    pub fn with_warning(mut self, warning: Warning) -> Self {
        self.warnings.push(warning);
        self
    }
}

impl<T> From<Outcome<T>> for ItemResult<T> {
    fn from(outcome: Outcome<T>) -> Self {
        Self {
            outcome,
            warnings: Vec::new(),
        }
    }
}

impl ItemError {
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

impl Warning {
    pub fn new(warning_type: impl Into<String>, details: Map<String, Value>) -> Self {
        Self {
            warning_type: warning_type.into(),
            details,
            key: None,
        }
    }

    /// Ingestion rate-limits warnings per team, type and key, so a key per item keeps one item's
    /// warning from hiding another's.
    pub fn with_key(mut self, key: impl Into<String>) -> Self {
        self.key = Some(key.into());
        self
    }
}

#[cfg(test)]
mod tests {
    use axum::{body::to_bytes, http::Request};
    use serde_json::json;

    use super::*;

    fn details(value: Value) -> Map<String, Value> {
        value.as_object().cloned().unwrap()
    }

    #[test]
    fn serializes_every_result_in_the_documented_shape() {
        let results = ItemResults::new(
            4,
            vec![
                ItemResult::ok(json!({"id": 1})).with_warning(
                    Warning::new("some_warning", details(json!({"field": "x"}))).with_key("1"),
                ),
                ItemResult::drop("suppressed"),
                ItemResult::retry(codes::DEADLINE_EXCEEDED, "too slow"),
                ItemResult::fail(codes::INVALID_INPUT, "bad item"),
            ],
        )
        .unwrap();

        let wire = json!({
            "results": [
                {
                    "result": "ok",
                    "value": {"id": 1},
                    "warnings": [{"type": "some_warning", "details": {"field": "x"}, "key": "1"}]
                },
                {"result": "drop", "reason": "suppressed"},
                {"result": "retry", "error": {"code": "deadline_exceeded", "message": "too slow"}},
                {"result": "fail", "error": {"code": "invalid_input", "message": "bad item"}}
            ]
        });

        assert_eq!(serde_json::to_value(&results).unwrap(), wire);
        assert_eq!(
            serde_json::from_value::<ItemResults<Value>>(wire).unwrap(),
            results
        );
    }

    #[test]
    fn rejects_results_that_do_not_match_the_request_length() {
        let results = vec![ItemResult::ok(json!({}))];

        assert_eq!(
            ItemResults::new(2, results),
            Err(LengthMismatch {
                expected: 2,
                actual: 1
            })
        );
    }

    #[tokio::test]
    async fn only_the_supported_version_opts_in() {
        for (value, expected) in [
            (Some("1"), true),
            (Some(" 1 "), true),
            (Some("2"), false),
            (None, false),
        ] {
            let mut request = Request::builder();
            if let Some(value) = value {
                request = request.header(HEADER, value);
            }
            let (mut parts, ()) = request.body(()).unwrap().into_parts();

            let PerItemResults(requested) = PerItemResults::from_request_parts(&mut parts, &())
                .await
                .unwrap();

            assert_eq!(requested, expected, "header value {value:?}");
        }
    }

    #[tokio::test]
    async fn the_response_echoes_the_header() {
        let response = ItemResults::<Value>::new(1, vec![ItemResult::drop("suppressed")])
            .unwrap()
            .into_response();

        assert_eq!(response.headers().get(HEADER).unwrap(), VERSION);
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&body).unwrap(),
            json!({"results": [{"result": "drop", "reason": "suppressed"}]})
        );
    }
}
