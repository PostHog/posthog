#![doc = include_str!("../README.md")]
#![deny(missing_docs)]
mod model;
use async_trait::async_trait;
pub use model::*;
use reqwest::{Client, StatusCode, Url};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use serde_json::{Value, json};
use std::{
    sync::Arc,
    time::{Duration, SystemTime},
};
use thiserror::Error;

/// Default US gateway origin.
pub const US: &str = "https://ai-gateway.us.posthog.com";
/// EU gateway origin (unverified).
pub const EU: &str = "https://ai-gateway.eu.posthog.com";
/// Model and transport settings, configured independently of credentials.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    /// Gateway origin without the v1 suffix.
    pub base_url: String,
    /// System One model ID.
    pub decision_model: String,
    /// OpenAI-compatible generation model ID.
    pub writing_model: String,
    /// Timeout for each HTTP exchange.
    pub timeout: Duration,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            base_url: US.into(),
            decision_model: "posthog/hogference/jevk5-fp8-0.2".into(),
            writing_model: "openai/gpt-5.4-mini".into(),
            timeout: Duration::from_secs(25),
        }
    }
}

/// Gateway and credential failures. Diagnostics exclude tokens and request bodies.
#[derive(Debug, Error)]
pub enum Error {
    /// The access token was rejected or could not be obtained.
    #[error("PostHog sign-in required")]
    Unauthorized,
    /// OAuth consent must include this literal scope.
    #[error("PostHog sign-in needs the llm_gateway:read scope")]
    MissingScope,
    /// The model declined the requested output.
    #[error("the model declined to answer")]
    Refused,
    /// A transient failure after bounded retries.
    #[error("gateway unavailable ({cause})")]
    Unavailable {
        /// Delay requested by the service.
        retry_after: Option<Duration>,
        /// Non-sensitive diagnostic.
        cause: String,
    },
    /// The gateway returned a permanent rejection or malformed response.
    #[error("invalid gateway request or response: {0}")]
    Invalid(String),
}

/// Supplies the current bearer token. A rejected token allows one conditional refresh.
#[async_trait]
pub trait TokenSource: Send + Sync {
    /// Observe the final outcome of an authenticated request.
    fn observe(&self, _error: Option<&Error>) {}
    /// Obtain a token or refresh a previously rejected credential.
    async fn token(&self, rejected: Option<&str>) -> Result<String, Error>;
}
#[async_trait]
impl TokenSource for String {
    async fn token(&self, rejected: Option<&str>) -> Result<String, Error> {
        if rejected.is_some() || self.is_empty() {
            Err(Error::Unauthorized)
        } else {
            Ok(self.clone())
        }
    }
}

/// Metadata for one HTTP attempt. A missing status denotes a request starting.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Exchange<'a> {
    /// Relative API path.
    pub path: &'a str,
    /// One-based attempt number.
    pub attempt: u8,
    /// Response status, or zero for a transport failure.
    pub status: Option<u16>,
}

/// A credential-aware client for System One and chat completions.
#[derive(Clone)]
pub struct Gateway {
    config: Config,
    client: Client,
    source: Arc<dyn TokenSource>,
    log: Arc<dyn Fn(Exchange<'_>) + Send + Sync>,
}
impl Gateway {
    /// Build a gateway with bounded request timeouts and redirects disabled.
    pub fn new(config: Config, source: Arc<dyn TokenSource>) -> Result<Self, Error> {
        let url =
            Url::parse(&config.base_url).map_err(|_| Error::Invalid("gateway origin".into()))?;
        let loopback = url.host_str().is_some_and(|host| {
            host == "localhost"
                || host
                    .trim_matches(['[', ']'])
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback())
        });
        if !(url.scheme() == "https" || (url.scheme() == "http" && loopback))
            || url.host().is_none()
            || url.query().is_some()
            || url.fragment().is_some()
            || !url.username().is_empty()
            || url.password().is_some()
            || config.timeout.is_zero()
        {
            return Err(Error::Invalid(
                "expected an HTTPS gateway or loopback HTTP URL and a nonzero timeout".into(),
            ));
        }
        let client = Client::builder()
            .timeout(config.timeout)
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| Error::Invalid("HTTP client configuration".into()))?;
        Ok(Self {
            config,
            client,
            source,
            log: Arc::new(|_| {}),
        })
    }
    /// Observe request and response metadata, without prompts, bodies or credentials.
    pub fn with_log(mut self, hook: impl Fn(Exchange<'_>) + Send + Sync + 'static) -> Self {
        self.log = Arc::new(hook);
        self
    }
    /// Ask up to 32 questions about the same state.
    pub async fn decide(&self, state: &Value, questions: &Questions) -> Result<Decisions, Error> {
        if questions.is_empty() || questions.len() > 32 {
            return Err(Error::Invalid("expected 1–32 questions".into()));
        }
        for (id, question) in questions {
            let valid = match question {
                Question::Choice { criteria, .. } => {
                    (1..=255).contains(&criteria.len()) && criteria.keys().all(|k| !k.is_empty())
                }
                Question::Score { criteria, .. } => (2..=10).contains(&criteria.len()),
                Question::Noul { .. } => true,
            };
            if id.is_empty() || !valid {
                return Err(Error::Invalid("invalid question ID or rubric size".into()));
            }
        }
        let decisions: Decisions = self
            .post(
                "/v1/systemone",
                json!({"model":self.config.decision_model,"state":state,"questions":questions}),
            )
            .await?;
        if decisions.answers.len() != questions.len() {
            return Err(Error::Invalid("incomplete answers".into()));
        }
        for (id, q) in questions {
            let valid = match (q, decisions.answers.get(id)) {
                (_, Some(Answer::Refusal)) => true,
                (Question::Noul { .. }, Some(Answer::Noul { noul, calibration })) => {
                    (0.0..=1.).contains(noul) && calibrated(calibration)
                }
                (
                    Question::Choice { criteria, .. },
                    Some(Answer::Choice {
                        choice,
                        calibration,
                    }),
                ) => {
                    criteria.contains_key(choice)
                        && calibrated(calibration)
                        && calibration
                            .probabilities
                            .keys()
                            .all(|k| criteria.contains_key(k))
                }
                (Question::Score { criteria, .. }, Some(Answer::Score { score, calibration })) => {
                    (0.0..=criteria.len().saturating_sub(1) as f64).contains(score)
                        && calibrated(calibration)
                }
                _ => false,
            };
            if !valid {
                return Err(Error::Invalid(format!("unexpected answer for {id}")));
            }
        }
        Ok(decisions)
    }
    /// Generate a non-streaming reply, limited to the requested token budget.
    pub async fn write(
        &self,
        system: &str,
        messages: &[Message],
        max_tokens: u32,
    ) -> Result<String, Error> {
        let instructions = Message {
            role: Role::System,
            content: system.into(),
        };
        let turns: Vec<_> = std::iter::once(&instructions).chain(messages).collect();
        let request = json!({
            "model":self.config.writing_model,
            "messages":turns,
            "max_completion_tokens":max_tokens
        });
        let result: Value = self.post("/v1/chat/completions", request).await?;
        let choice = &result["choices"][0];
        if choice["message"]["refusal"].is_string() || choice["finish_reason"] == "content_filter" {
            return Err(Error::Refused);
        }
        choice["message"]["content"]
            .as_str()
            .filter(|s| !s.trim().is_empty())
            .map(str::to_owned)
            .ok_or_else(|| Error::Invalid("empty completion".into()))
    }
    async fn post<T: DeserializeOwned>(&self, path: &str, body: Value) -> Result<T, Error> {
        let result = self.exchange(path, body).await;
        self.source.observe(result.as_ref().err());
        result
    }

    async fn exchange<T: DeserializeOwned>(&self, path: &str, body: Value) -> Result<T, Error> {
        let url = format!("{}{path}", self.config.base_url.trim_end_matches('/'));
        let mut token = self.source.token(None).await?;
        let mut refreshed = false;
        let mut attempt = 0;
        loop {
            attempt += 1;
            (self.log)(Exchange {
                path,
                attempt,
                status: None,
            });
            let response = self
                .client
                .post(&url)
                .bearer_auth(&token)
                .json(&body)
                .send()
                .await;
            (self.log)(Exchange {
                path,
                attempt,
                status: Some(response.as_ref().map_or(0, |r| r.status().as_u16())),
            });
            let failure = match response {
                Ok(response) => match decode(response).await {
                    Ok(value) => return Ok(value),
                    Err(Error::Unauthorized) if !refreshed && attempt < 3 => {
                        token = self.source.token(Some(&token)).await?;
                        refreshed = true;
                        continue;
                    }
                    Err(e) => e,
                },
                Err(e) => transport(&e),
            };
            let Error::Unavailable { retry_after, .. } = &failure else {
                return Err(failure);
            };
            let delay = retry_after
                .unwrap_or_default()
                .max(Duration::from_millis(100 << (attempt - 1)));
            if attempt == 3 || delay > Duration::from_secs(2) {
                return Err(failure);
            }
            tokio::time::sleep(delay + Duration::from_millis(rand::random_range(0..100))).await;
        }
    }
}

async fn decode<T: DeserializeOwned>(response: reqwest::Response) -> Result<T, Error> {
    let status = response.status();
    if status.is_success() {
        let bytes = response.bytes().await.map_err(|e| transport(&e))?;
        return serde_json::from_slice(&bytes)
            .map_err(|_| Error::Invalid("malformed JSON response".into()));
    }
    if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
        let error = response.json::<Value>().await.unwrap_or_default();
        return Err(
            if error["error"]["code"] == "scope_missing" || error["code"] == "scope_missing" {
                Error::MissingScope
            } else if status == StatusCode::UNAUTHORIZED {
                Error::Unauthorized
            } else {
                Error::Invalid(status.to_string())
            },
        );
    }
    if status.is_server_error()
        || matches!(
            status,
            StatusCode::TOO_MANY_REQUESTS | StatusCode::REQUEST_TIMEOUT
        )
    {
        let retry_after = response
            .headers()
            .get("retry-after")
            .and_then(|v| v.to_str().ok())
            .and_then(parse_delay);
        return Err(Error::Unavailable {
            cause: status.to_string(),
            retry_after,
        });
    }
    Err(Error::Invalid(status.to_string()))
}

fn transport(error: &reqwest::Error) -> Error {
    Error::Unavailable {
        cause: if error.is_timeout() {
            "request timed out"
        } else {
            "connection failed"
        }
        .into(),
        retry_after: None,
    }
}

fn calibrated(c: &Calibration) -> bool {
    c.confidence
        .iter()
        .chain(c.probabilities.values())
        .all(|p| (0.0..=1.).contains(p))
}
fn parse_delay(value: &str) -> Option<Duration> {
    value.parse().ok().map(Duration::from_secs).or_else(|| {
        httpdate::parse_http_date(value)
            .ok()
            .map(|time| time.duration_since(SystemTime::now()).unwrap_or_default())
    })
}

#[cfg(test)]
mod tests;
