//! Scoped HTTP requests for a single collection in a PostHog project.
use anyhow::{Context, Result, ensure};
use reqwest::{Client, Method, Response, redirect::Policy};
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::time::Duration;
use url::Url;

/// A non-success response from the PostHog API.
#[derive(Debug, thiserror::Error)]
#[error("PostHog HTTP {status} {code} {detail}")]
pub struct ApiError {
    /// HTTP status returned by the server.
    pub status: u16,
    /// Machine-readable PostHog error code, when supplied.
    pub code: String,
    /// Human-readable description returned by the server.
    pub detail: String,
}

/// Authenticated HTTP operations scoped to a collection within one project.
#[derive(Clone)]
pub struct ProjectEndpoint {
    http: Client,
    root: Url,
}

impl ProjectEndpoint {
    /// Select a numeric project and collection on the given origin.
    pub fn new(origin: &str, project: u64, collection: &str) -> Result<Self> {
        ensure!(project > 0, "Invalid PostHog project ID");
        Self::for_project(origin, &project.to_string(), collection)
    }

    /// Let PostHog resolve the signed-in user's current project.
    pub fn current(origin: &str, collection: &str) -> Result<Self> {
        Self::for_project(origin, "@current", collection)
    }

    fn for_project(origin: &str, project: &str, collection: &str) -> Result<Self> {
        ensure!(
            !collection.is_empty()
                && collection
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_'),
            "Invalid project collection name"
        );
        let origin = Url::parse(origin)?;
        ensure!(
            origin.has_host()
                && origin.username().is_empty()
                && origin.password().is_none()
                && origin.path() == "/"
                && origin.query().is_none()
                && origin.fragment().is_none()
                && crate::is_https_or_loopback(&origin),
            "Invalid PostHog origin or project ID"
        );
        let http = Client::builder()
            .timeout(Duration::from_secs(30))
            .redirect(Policy::none())
            .retry(reqwest::retry::never())
            .build()?;
        Ok(Self {
            http,
            root: origin.join(&format!("api/projects/{project}/{collection}/"))?,
        })
    }

    #[cfg(feature = "mcp")]
    pub(crate) fn child_url(&self, segments: &[&str]) -> Url {
        let mut url = self.root.clone();
        url.path_segments_mut()
            .expect("validated HTTP origin")
            .pop_if_empty()
            .extend(segments);
        url
    }

    pub(crate) async fn request(
        &self,
        token: &str,
        method: Method,
        path: &str,
        body: Option<Value>,
        idempotency_key: Option<&str>,
    ) -> Result<Response> {
        let url = self.resolve(path)?;
        let mut req = self.http.request(method.clone(), url).bearer_auth(token);
        if let Some(key) = idempotency_key {
            req = req.header("Idempotency-Key", key);
        }
        if let Some(json) = body {
            req = req.json(&json);
        }
        let response = req.send().await.with_context(|| if method == Method::POST {
            "Connection failed. The action may have reached PostHog. Check the outcome before trying again."
        } else { "Could not reach PostHog" })?;
        let status = response.status();
        if !status.is_success() {
            let data = response.json::<Value>().await.unwrap_or(Value::Null);
            let code = data
                .get("code")
                .or_else(|| data.get("reason"))
                .and_then(Value::as_str)
                .unwrap_or("");
            let detail = ["detail", "error", "message"]
                .into_iter()
                .find_map(|k| data.get(k).and_then(Value::as_str))
                .unwrap_or("");
            return Err(ApiError {
                status: status.as_u16(),
                code: code.to_owned(),
                detail: detail.to_owned(),
            }
            .into());
        }
        Ok(response)
    }

    fn resolve(&self, path: &str) -> Result<Url> {
        let url = self.root.join(path)?;
        ensure!(
            url.origin() == self.root.origin()
                && url.path().starts_with(self.root.path())
                && url.username().is_empty()
                && url.password().is_none(),
            "Request is outside the configured collection"
        );
        Ok(url)
    }

    /// Follow one redirect by hand: return where a GET points without sending the bearer there.
    pub async fn redirect(&self, token: &str, path: &str) -> Result<Url> {
        let response = self
            .http
            .get(self.resolve(path)?)
            .bearer_auth(token)
            .send()
            .await
            .context("Could not reach PostHog")?;
        let status = response.status();
        ensure!(
            status.is_redirection(),
            ApiError {
                status: status.as_u16(),
                code: String::new(),
                detail: "Expected a redirect".into(),
            }
        );
        let location = response
            .headers()
            .get(reqwest::header::LOCATION)
            .and_then(|v| v.to_str().ok())
            .context("PostHog redirect has no location")?;
        Ok(response.url().join(location)?)
    }

    /// Get a response whose headers or streaming body the caller needs.
    pub async fn get_response(&self, token: &str, path: &str) -> Result<Response> {
        self.request(token, Method::GET, path, None, None).await
    }
    /// Fetch a JSON value relative to this collection.
    pub async fn get<T: DeserializeOwned>(&self, token: &str, path: &str) -> Result<T> {
        Ok(self
            .request(token, Method::GET, path, None, None)
            .await?
            .json()
            .await?)
    }

    /// Delete a resource. A missing resource already satisfies the request on retry.
    pub async fn delete(&self, token: &str, path: &str) -> Result<()> {
        match self.request(token, Method::DELETE, path, None, None).await {
            Ok(_) => Ok(()),
            Err(e)
                if e.downcast_ref::<ApiError>()
                    .is_some_and(|e| e.status == 404) =>
            {
                Ok(())
            }
            Err(e) => Err(e),
        }
    }

    /// Post a JSON body and decode the response.
    pub async fn post<T: DeserializeOwned>(
        &self,
        token: &str,
        path: &str,
        body: Value,
    ) -> Result<T> {
        self.post_with_key(token, path, body, None).await
    }

    /// Patch a resource relative to this collection and decode the response.
    pub async fn patch<T: DeserializeOwned>(
        &self,
        token: &str,
        path: &str,
        body: Value,
    ) -> Result<T> {
        self.request(token, Method::PATCH, path, Some(body), None)
            .await?
            .json()
            .await
            .context("PostHog accepted the change but its response was unreadable. Check the outcome before trying again.")
    }

    /// Use a caller-owned key for endpoints that deduplicate writes.
    pub async fn post_with_key<T: DeserializeOwned>(
        &self,
        token: &str,
        path: &str,
        body: Value,
        key: Option<&str>,
    ) -> Result<T> {
        self.request(token, Method::POST, path, Some(body), key).await?.json().await
            .context("PostHog accepted the action but its response was unreadable. Check the outcome before trying again.")
    }
}
