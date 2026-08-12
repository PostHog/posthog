use std::time::Duration;
use thiserror::Error;

#[derive(Error, Debug, Clone)]
#[error("User Error: {msg}")]
pub struct UserError {
    pub msg: String,
}

impl UserError {
    pub fn new(msg: impl Into<String>) -> Self {
        Self { msg: msg.into() }
    }
}

pub trait ToUserError<T> {
    fn user_error(self, msg: impl Into<String>) -> anyhow::Result<T>;
}

// Use this to inject a user facing error message into the error chain
// Our main thread can extract this from an error chain and display it to the user
impl<T, E: std::error::Error + Send + Sync + 'static> ToUserError<T> for Result<T, E> {
    fn user_error(self, msg: impl Into<String>) -> anyhow::Result<T> {
        self.map_err(|e| anyhow::Error::from(e).context(UserError::new(msg)))
    }
}

const DEFAULT_USER_ERROR_MESSAGE: &str = "An unknown error occurred";

pub fn get_user_message(error: &anyhow::Error) -> String {
    // Get the shallowest UserError in the chain
    // To provide the user with all the error context they need, we concatenate the user errors together at call site
    match error.downcast_ref::<UserError>() {
        Some(user_error) => user_error.msg.clone(),
        None => DEFAULT_USER_ERROR_MESSAGE.to_string(),
    }
}

/// Attach a public-facing message only when the chain doesn't already carry one, so a
/// specific message deeper in the stack (e.g. the plaintext-ceiling breach) is never
/// shadowed by a generic wrapper added higher up.
pub fn ensure_user_message(error: anyhow::Error, msg: impl Into<String>) -> anyhow::Error {
    if error.downcast_ref::<UserError>().is_some() {
        error
    } else {
        error.context(UserError::new(msg))
    }
}

#[derive(Error, Debug)]
#[error("Rate limited")]
pub struct RateLimitedError {
    pub retry_after: Option<Duration>,
    #[source]
    pub source: reqwest::Error,
}

/// Extracts a Retry-After duration if a RateLimitedError is present in the error chain
pub fn extract_retry_after_from_error(error: &anyhow::Error) -> Option<Duration> {
    if let Some(rl) = error.downcast_ref::<RateLimitedError>() {
        return rl.retry_after;
    }

    let mut source = error.source();
    while let Some(err) = source {
        if let Some(rl) = err.downcast_ref::<RateLimitedError>() {
            return rl.retry_after;
        }
        source = err.source();
    }
    None
}

/// Returns true if the error chain contains a reqwest::Error with HTTP 429.
pub fn is_rate_limited_error(error: &anyhow::Error) -> bool {
    // Our custom rate limit error also counts
    if error.downcast_ref::<RateLimitedError>().is_some() {
        return true;
    }

    if let Some(reqwest_err) = error.downcast_ref::<reqwest::Error>() {
        if reqwest_err.status().is_some_and(|s| s.as_u16() == 429) {
            return true;
        }
    }

    let mut source = error.source();
    while let Some(err) = source {
        if let Some(reqwest_err) = err.downcast_ref::<reqwest::Error>() {
            if reqwest_err.status().is_some_and(|s| s.as_u16() == 429) {
                return true;
            }
        }
        source = err.source();
    }
    false
}

/// Returns true if the error chain contains a reqwest timeout error.
/// Timeouts are transient and should be retried with backoff.
pub fn is_timeout_error(error: &anyhow::Error) -> bool {
    if let Some(reqwest_err) = error.downcast_ref::<reqwest::Error>() {
        if reqwest_err.is_timeout() {
            return true;
        }
    }

    let mut source = error.source();
    while let Some(err) = source {
        if let Some(reqwest_err) = err.downcast_ref::<reqwest::Error>() {
            if reqwest_err.is_timeout() {
                return true;
            }
        }
        source = err.source();
    }
    false
}

/// Returns true if the error chain contains a transport-level reqwest error
/// (connection refused/closed/reset, DNS, TLS, premature body close). Transient,
/// retry with backoff. Excludes timeouts (see is_timeout_error), HTTP status errors,
/// and builder errors (malformed URL / illegal header).
pub fn is_transient_network_error(error: &anyhow::Error) -> bool {
    error.chain().any(|err| {
        err.downcast_ref::<reqwest::Error>()
            .is_some_and(|re| !re.is_timeout() && !re.is_builder() && re.status().is_none())
    })
}

/// Returns true if the error chain contains a reqwest::Error with HTTP 502/503/504.
pub fn is_transient_server_error(error: &anyhow::Error) -> bool {
    error.chain().any(|err| {
        err.downcast_ref::<reqwest::Error>()
            .is_some_and(|re| matches!(re.status().map(|s| s.as_u16()), Some(502..=504)))
    })
}

/// Returns true if the error chain contains a *transient* `object_store` (temp-bucket
/// S3) failure that outlived the client's internal retries: 429/5xx responses,
/// timeouts, and transport-level errors. Everything else — 401/403 (IAM), 404, other
/// 4xx, config errors — is deliberately NOT transient: job-level backoff can retry
/// without limit (`BACKOFF_MAX_ATTEMPTS=0`), so misclassifying a permanent failure
/// here would retry it forever instead of pausing visibly. Unknown shapes therefore
/// default to "not transient" (pause), the fail-safe direction.
pub fn is_transient_object_store_error(error: &anyhow::Error) -> bool {
    for cause in error.chain() {
        if let Some(ose) = cause.downcast_ref::<object_store::Error>() {
            return match ose {
                // Everything object_store couldn't map to a specific (permanent)
                // variant: 429/5xx after retries, timeouts, transport failures —
                // and also unmapped 4xx, which the helper filters back out.
                object_store::Error::Generic { source, .. } => {
                    object_store_generic_is_transient(source.as_ref())
                }
                // Tokio task join failure inside the store: process-local, retryable.
                object_store::Error::JoinError { .. } => true,
                // NotFound / PermissionDenied / Unauthenticated / Precondition /
                // AlreadyExists / config errors: permanent, pause.
                _ => false,
            };
        }
    }
    false
}

/// Classify the source chain under `object_store::Error::Generic`.
///
/// Transport-level failures (timeout, connect, reset) surface as a public
/// `object_store::client::HttpError` in the chain and are transient by construction.
/// HTTP-status failures keep the status only in the retry error's message
/// ("Server returned non-2xx status code: <status>..."), because the retry error
/// type is not public API; 429/5xx are transient, other statuses are not. An S3
/// error body on a 200 ("Server returned error response: ...", e.g. InternalError /
/// SlowDown) is transient — object_store retries those for the same reason. If the
/// message format changes in an object_store upgrade, classification degrades to
/// "not transient" (a visible pause), never to an infinite retry.
fn object_store_generic_is_transient(source: &(dyn std::error::Error + 'static)) -> bool {
    let mut messages = String::new();
    let mut cur: Option<&(dyn std::error::Error + 'static)> = Some(source);
    while let Some(err) = cur {
        if err
            .downcast_ref::<object_store::client::HttpError>()
            .is_some()
        {
            return true;
        }
        messages.push_str(&err.to_string());
        messages.push('\n');
        cur = err.source();
    }
    if let Some(idx) = messages.find("status code: ") {
        let status = &messages[idx + "status code: ".len()..];
        return status.starts_with('5') || status.starts_with("429");
    }
    messages.contains("Server returned error response")
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::anyhow;
    use httpmock::MockServer;
    use reqwest::Client;

    #[test]
    fn test_user_error_as_root() {
        let user_error = UserError::new("Root user error message");
        let error = anyhow::Error::from(user_error);

        let result = get_user_message(&error);
        assert_eq!(result, "Root user error message");
    }

    #[test]
    fn test_user_error_in_middle_of_chain() {
        let io_error = std::io::Error::new(std::io::ErrorKind::NotFound, "File not found");
        let user_error = UserError::new("User-friendly file error");

        let error = anyhow::Error::from(io_error)
            .context(user_error)
            .context("High level operation failed");

        let result = get_user_message(&error);
        assert_eq!(result, "User-friendly file error");
    }

    #[test]
    fn test_user_error_at_end_of_chain() {
        let user_error = UserError::new("Deep user error");
        let error = anyhow::Error::from(user_error)
            .context("Middle layer error")
            .context("Top level error");

        let result = get_user_message(&error);
        assert_eq!(result, "Deep user error");
    }

    #[test]
    fn test_multiple_user_errors_returns_shallowest() {
        let deep_user_error = UserError::new("Deep user error");
        let shallowest_user_error = UserError::new("Shallowest user error");

        let error = anyhow::Error::from(deep_user_error)
            .context("Some system error")
            .context(shallowest_user_error)
            .context("Top level error");

        let result = get_user_message(&error);
        assert_eq!(result, "Shallowest user error");
    }

    #[test]
    fn test_concatenated_user_error() {
        // Test the pattern we use: concatenate inner message when creating outer error
        let inner_error = anyhow::Error::from(UserError::new("specific parse error"));
        let inner_msg = get_user_message(&inner_error);

        let outer_error = inner_error.context(UserError::new(format!(
            "File 'test.json' failed: {inner_msg}"
        )));

        let result = get_user_message(&outer_error);
        assert_eq!(result, "File 'test.json' failed: specific parse error");
    }

    #[test]
    fn test_no_user_error_in_chain() {
        let io_error = std::io::Error::new(std::io::ErrorKind::PermissionDenied, "Access denied");
        let error = anyhow::Error::from(io_error)
            .context("Failed to read config")
            .context("Application startup failed");

        let result = get_user_message(&error);
        assert_eq!(result, DEFAULT_USER_ERROR_MESSAGE);
    }

    #[test]
    fn test_single_non_user_error() {
        let simple_error = anyhow!("Simple error message");

        let result = get_user_message(&simple_error);
        assert_eq!(result, DEFAULT_USER_ERROR_MESSAGE);
    }

    #[test]
    fn test_user_error_trait_integration() {
        let io_error = std::io::Error::new(std::io::ErrorKind::NotFound, "File not found");
        let result: anyhow::Result<()> =
            Err(io_error).user_error("Could not find configuration file");

        let error = result.unwrap_err();
        let user_message = get_user_message(&error);
        assert_eq!(user_message, "Could not find configuration file");
    }

    #[tokio::test]
    async fn test_is_rate_limited_error_true_for_429() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/rl");
            then.status(429);
        });

        let client = Client::new();
        let resp = client.get(server.url("/rl")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);
        assert!(is_rate_limited_error(&err));
    }

    #[tokio::test]
    async fn test_is_rate_limited_error_false_for_non_429() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/err");
            then.status(500);
        });

        let client = Client::new();
        let resp = client.get(server.url("/err")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);
        assert!(!is_rate_limited_error(&err));
    }

    #[tokio::test]
    async fn test_is_timeout_error_true_for_timeout() {
        // Use a server that accepts the connection but never responds,
        // combined with a very short client timeout
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();

        let client = Client::builder()
            .timeout(std::time::Duration::from_millis(50))
            .build()
            .unwrap();

        let err = client
            .get(format!("http://{addr}/slow"))
            .send()
            .await
            .unwrap_err();
        let err = anyhow::Error::from(err);
        assert!(is_timeout_error(&err));
        assert!(!is_rate_limited_error(&err));
    }

    #[tokio::test]
    async fn test_is_timeout_error_false_for_non_timeout() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/ok");
            then.status(500);
        });

        let client = Client::new();
        let resp = client.get(server.url("/ok")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);
        assert!(!is_timeout_error(&err));
    }

    #[tokio::test]
    async fn test_is_transient_network_error_true_for_connection_refused() {
        // Bind to get a free port, then drop so nothing is listening.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        drop(listener);

        let client = Client::new();
        let err = client
            .get(format!("http://{addr}/"))
            .send()
            .await
            .unwrap_err();
        let err = anyhow::Error::from(err);
        assert!(is_transient_network_error(&err));
        assert!(!is_timeout_error(&err));
        assert!(!is_rate_limited_error(&err));
    }

    #[tokio::test]
    async fn test_is_transient_network_error_false_for_http_status() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/err");
            then.status(500);
        });

        let client = Client::new();
        let resp = client.get(server.url("/err")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);
        assert!(!is_transient_network_error(&err));
    }

    #[tokio::test]
    async fn test_is_transient_network_error_true_for_connection_closed_mid_request() {
        // Server accepts the TCP connection then immediately drops it — reproduces
        // the "connection closed before message completed" reqwest variant we saw in prod.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            if let Ok((stream, _)) = listener.accept() {
                drop(stream);
            }
        });

        let client = Client::new();
        let err = client
            .get(format!("http://{addr}/"))
            .send()
            .await
            .unwrap_err();
        let err = anyhow::Error::from(err);
        assert!(is_transient_network_error(&err));
        assert!(!is_timeout_error(&err));
    }

    #[tokio::test]
    async fn test_is_transient_network_error_false_for_builder_error() {
        // Null byte in header value — rejected at request construction, not transient.
        let client = Client::new();
        let err = client
            .get("http://127.0.0.1:1/")
            .header("X-Test", "bad\0value")
            .send()
            .await
            .unwrap_err();
        let err = anyhow::Error::from(err);
        assert!(!is_transient_network_error(&err));
    }

    #[tokio::test]
    async fn test_is_transient_server_error_true_for_502() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/e");
            then.status(502);
        });

        let client = Client::new();
        let resp = client.get(server.url("/e")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);
        assert!(is_transient_server_error(&err));
        assert!(!is_rate_limited_error(&err));
        assert!(!is_transient_network_error(&err));
    }

    #[tokio::test]
    async fn test_is_transient_server_error_true_for_503_and_504() {
        for status in [503, 504] {
            let server = MockServer::start();
            let _mock = server.mock(|when, then| {
                when.method(httpmock::Method::GET).path("/e");
                then.status(status);
            });

            let client = Client::new();
            let resp = client.get(server.url("/e")).send().await.unwrap();
            let http_err = resp.error_for_status().unwrap_err();
            let err = anyhow::Error::from(http_err);
            assert!(
                is_transient_server_error(&err),
                "expected true for {status}"
            );
        }
    }

    #[tokio::test]
    async fn test_is_transient_server_error_false_for_500_and_4xx() {
        // 500 is ambiguous (could be a real bug) and 4xx are client errors — neither auto-retries.
        for status in [500, 400, 404] {
            let server = MockServer::start();
            let _mock = server.mock(|when, then| {
                when.method(httpmock::Method::GET).path("/e");
                then.status(status);
            });

            let client = Client::new();
            let resp = client.get(server.url("/e")).send().await.unwrap();
            let http_err = resp.error_for_status().unwrap_err();
            let err = anyhow::Error::from(http_err);
            assert!(
                !is_transient_server_error(&err),
                "expected false for {status}"
            );
        }
    }

    /// Build a real object_store S3 client against a mock endpoint with client-level
    /// retries disabled, so tests classify the genuine error shapes the production
    /// client produces (not synthetic strings that could drift from the crate).
    fn object_store_against(url: &str) -> object_store::aws::AmazonS3 {
        use object_store::aws::AmazonS3Builder;
        AmazonS3Builder::new()
            .with_bucket_name("test-bucket")
            .with_endpoint(url)
            .with_region("us-east-1")
            .with_allow_http(true)
            .with_virtual_hosted_style_request(false)
            .with_access_key_id("k")
            .with_secret_access_key("s")
            .with_retry(object_store::RetryConfig {
                max_retries: 0,
                retry_timeout: std::time::Duration::from_secs(5),
                ..Default::default()
            })
            .build()
            .unwrap()
    }

    async fn object_store_error_for_status(status: u16) -> anyhow::Error {
        use object_store::ObjectStoreExt;
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.any_request();
            then.status(status);
        });
        let store = object_store_against(&server.base_url());
        let err = store
            .get(&object_store::path::Path::from("k.data"))
            .await
            .unwrap_err();
        anyhow::Error::from(err).context("Failed to read staged object for key: k")
    }

    #[tokio::test]
    async fn test_object_store_5xx_and_429_are_transient() {
        // A throttle/outage that outlives the client's internal retries must reach
        // job-level backoff, not a pause: with real jobs this is the difference
        // between self-healing and a support ticket.
        for status in [500, 502, 503, 504, 429] {
            let err = object_store_error_for_status(status).await;
            assert!(
                is_transient_object_store_error(&err),
                "expected transient for {status}: {err:#}"
            );
        }
    }

    #[tokio::test]
    async fn test_object_store_permanent_errors_pause_not_retry() {
        // 401/403 (IAM misconfig), 404, and other 4xx must never classify as
        // transient: job backoff retries without limit, so a misclassified
        // permanent error would retry invisibly forever instead of pausing.
        for status in [401, 403, 404, 400] {
            let err = object_store_error_for_status(status).await;
            assert!(
                !is_transient_object_store_error(&err),
                "expected permanent for {status}: {err:#}"
            );
        }
    }

    #[tokio::test]
    async fn test_object_store_timeout_and_connect_errors_are_transient() {
        use object_store::ObjectStoreExt;

        // Request timeout: server delays past the client timeout.
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.any_request();
            then.status(200)
                .delay(std::time::Duration::from_millis(500));
        });
        let store = {
            use object_store::aws::AmazonS3Builder;
            AmazonS3Builder::new()
                .with_bucket_name("test-bucket")
                .with_endpoint(server.base_url())
                .with_region("us-east-1")
                .with_allow_http(true)
                .with_virtual_hosted_style_request(false)
                .with_access_key_id("k")
                .with_secret_access_key("s")
                .with_client_options(
                    object_store::ClientOptions::new()
                        .with_timeout(std::time::Duration::from_millis(50)),
                )
                .with_retry(object_store::RetryConfig {
                    max_retries: 0,
                    retry_timeout: std::time::Duration::from_secs(5),
                    ..Default::default()
                })
                .build()
                .unwrap()
        };
        let err = anyhow::Error::from(
            store
                .get(&object_store::path::Path::from("k.data"))
                .await
                .unwrap_err(),
        );
        assert!(
            is_transient_object_store_error(&err),
            "timeout must be transient: {err:#}"
        );

        // Transport error: nothing listens on the target port.
        let store = object_store_against("http://127.0.0.1:1");
        let err = anyhow::Error::from(
            store
                .get(&object_store::path::Path::from("k.data"))
                .await
                .unwrap_err(),
        );
        assert!(
            is_transient_object_store_error(&err),
            "connect failure must be transient: {err:#}"
        );
    }

    #[test]
    fn test_ensure_user_message_never_shadows_a_specific_one() {
        let specific = anyhow::Error::msg("root").context(UserError::new("specific message"));
        let wrapped = ensure_user_message(specific, "generic message");
        assert_eq!(get_user_message(&wrapped), "specific message");

        let bare = anyhow::Error::msg("root");
        let wrapped = ensure_user_message(bare, "generic message");
        assert_eq!(get_user_message(&wrapped), "generic message");
    }
}
