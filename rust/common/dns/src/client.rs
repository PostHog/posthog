use std::sync::Arc;
use std::time::Duration;

use reqwest::redirect::Policy;
use thiserror::Error;
use url::Host;

use crate::{is_global_ipv4, NoPublicIPv4Error, PublicIPv4Resolver};

/// Returns true if the URL's host is safe (either a hostname or a public IP)
fn is_safe_url(url: &reqwest::Url) -> bool {
    match url.host() {
        Some(Host::Ipv4(ip)) => is_global_ipv4(&ip),
        Some(Host::Ipv6(_)) => false,  // We don't support IPv6
        Some(Host::Domain(_)) => true, // DNS resolver handles this
        None => false,
    }
}

#[derive(Debug, Error)]
pub enum ClientError {
    #[error("Invalid URL: {0}")]
    InvalidUrl(#[from] url::ParseError),
    #[error("{0}")]
    NoPublicIPv4(#[from] NoPublicIPv4Error),
    #[error("{0}")]
    Request(#[from] reqwest::Error),
}

/// Builder for InternalClient
pub struct InternalClientBuilder {
    secure: bool,
    timeout: Option<Duration>,
    connect_timeout: Option<Duration>,
    default_headers: reqwest::header::HeaderMap,
}

impl InternalClientBuilder {
    pub fn new(secure: bool) -> Self {
        Self {
            secure,
            timeout: None,
            connect_timeout: None,
            default_headers: reqwest::header::HeaderMap::new(),
        }
    }

    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = Some(timeout);
        self
    }

    pub fn connect_timeout(mut self, timeout: Duration) -> Self {
        self.connect_timeout = Some(timeout);
        self
    }

    pub fn default_headers(mut self, headers: reqwest::header::HeaderMap) -> Self {
        self.default_headers = headers;
        self
    }

    pub fn build(self) -> Result<InternalClient, ClientError> {
        let mut builder = reqwest::Client::builder();

        if let Some(timeout) = self.timeout {
            builder = builder.timeout(timeout);
        }

        if let Some(connect_timeout) = self.connect_timeout {
            builder = builder.connect_timeout(connect_timeout);
        }

        if !self.default_headers.is_empty() {
            builder = builder.default_headers(self.default_headers);
        }

        if self.secure {
            builder = builder
                .dns_resolver(Arc::new(PublicIPv4Resolver {}))
                .redirect(Policy::custom(|attempt| {
                    if is_safe_url(attempt.url()) {
                        attempt.follow()
                    } else {
                        attempt.error(NoPublicIPv4Error)
                    }
                }));
        }

        Ok(InternalClient {
            inner: builder.build()?,
            secure: self.secure,
        })
    }
}

/// A wrapper around reqwest::Client that optionally validates URLs to prevent SSRF attacks.
///
/// When `secure` is true:
/// - Blocks requests to raw private/internal IP addresses
/// - Blocks DNS resolution to private/internal IP addresses
/// - Blocks redirects to raw private/internal IP addresses
#[derive(Clone)]
pub struct InternalClient {
    inner: reqwest::Client,
    secure: bool,
}

impl InternalClient {
    pub fn new(secure: bool) -> Result<Self, ClientError> {
        InternalClientBuilder::new(secure).build()
    }

    pub fn builder(secure: bool) -> InternalClientBuilder {
        InternalClientBuilder::new(secure)
    }

    fn validate_url(&self, url: &str) -> Result<(), ClientError> {
        if !self.secure {
            return Ok(());
        }
        let parsed: reqwest::Url = url.parse().map_err(ClientError::InvalidUrl)?;
        if !is_safe_url(&parsed) {
            return Err(ClientError::NoPublicIPv4(NoPublicIPv4Error));
        }
        Ok(())
    }

    pub fn get(&self, url: &str) -> Result<reqwest::RequestBuilder, ClientError> {
        self.validate_url(url)?;
        Ok(self.inner.get(url))
    }

    pub fn post(&self, url: &str) -> Result<reqwest::RequestBuilder, ClientError> {
        self.validate_url(url)?;
        Ok(self.inner.post(url))
    }

    pub fn put(&self, url: &str) -> Result<reqwest::RequestBuilder, ClientError> {
        self.validate_url(url)?;
        Ok(self.inner.put(url))
    }

    pub fn patch(&self, url: &str) -> Result<reqwest::RequestBuilder, ClientError> {
        self.validate_url(url)?;
        Ok(self.inner.patch(url))
    }

    pub fn delete(&self, url: &str) -> Result<reqwest::RequestBuilder, ClientError> {
        self.validate_url(url)?;
        Ok(self.inner.delete(url))
    }

    pub fn head(&self, url: &str) -> Result<reqwest::RequestBuilder, ClientError> {
        self.validate_url(url)?;
        Ok(self.inner.head(url))
    }

    pub fn request(
        &self,
        method: reqwest::Method,
        url: &str,
    ) -> Result<reqwest::RequestBuilder, ClientError> {
        self.validate_url(url)?;
        Ok(self.inner.request(method, url))
    }

    pub fn execute(
        &self,
        request: reqwest::Request,
    ) -> Result<
        impl std::future::Future<Output = Result<reqwest::Response, reqwest::Error>>,
        ClientError,
    > {
        self.validate_url(request.url().as_str())?;
        Ok(self.inner.execute(request))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::prelude::*;

    #[test]
    fn secure_client_blocks_raw_loopback_ip() {
        let client = InternalClient::new(true).expect("failed to build client");
        let result = client.get("http://127.0.0.1:9999/test");

        assert!(matches!(result, Err(ClientError::NoPublicIPv4(_))));
    }

    #[test]
    fn secure_client_blocks_raw_private_ip() {
        let client = InternalClient::new(true).expect("failed to build client");
        let result = client.get("http://192.168.1.1:8080/test");

        assert!(matches!(result, Err(ClientError::NoPublicIPv4(_))));
    }

    #[tokio::test]
    async fn secure_client_blocks_localhost_hostname() {
        let client = InternalClient::new(true).expect("failed to build client");
        let result = client
            .get("http://localhost:9999/test")
            .unwrap()
            .send()
            .await;

        assert!(result.is_err());
        let err_str = format!("{:?}", result.unwrap_err());
        assert!(
            err_str.contains("No public IPv4"),
            "expected NoPublicIPv4Error, got: {err_str}",
        );
    }

    #[tokio::test]
    async fn insecure_client_allows_internal_ip() {
        let server = MockServer::start();

        server.mock(|when, then| {
            when.method(GET).path("/test");
            then.status(200).body("response");
        });

        let client = InternalClient::new(false).expect("failed to build client");
        let result = client
            .get(&server.url("/test"))
            .unwrap()
            .send()
            .await
            .unwrap();

        assert_eq!(result.status(), 200);
    }
}
