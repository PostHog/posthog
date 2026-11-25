//! Native authorization-code flow with a browser, PKCE and a loopback callback.
pub mod session;
use std::{
    net::{Ipv4Addr, SocketAddrV4},
    time::Duration,
};

use anyhow::{Context, Result, anyhow, ensure};
use oauth2::{
    AuthType, AuthUrl, AuthorizationCode, ClientId, CsrfToken, EndpointNotSet, EndpointSet,
    PkceCodeChallenge, RedirectUrl, Scope, TokenUrl, basic::BasicClient,
};
pub use oauth2::{RefreshToken, TokenResponse, basic::BasicTokenResponse};
use reqwest::{Client, redirect::Policy};
use serde::Deserialize;
use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
    time::timeout,
};
use url::Url;

type CodeClient =
    BasicClient<EndpointSet, EndpointNotSet, EndpointNotSet, EndpointNotSet, EndpointSet>;

#[derive(Deserialize)]
struct Metadata {
    issuer: Url,
    authorization_endpoint: Url,
    token_endpoint: Url,
    registration_endpoint: Option<Url>,
}

/// PostHog hosts its API and authorization server at the same origin.
pub struct Server {
    http: Client,
    metadata: Metadata,
}

impl Server {
    /// Read the issuer's authorization, registration and token endpoints.
    pub async fn discover(origin: &str) -> Result<Self> {
        let origin = Url::parse(origin)?;
        ensure!(
            origin.has_host()
                && crate::is_https_or_loopback(&origin)
                && origin.username().is_empty()
                && origin.password().is_none()
                && origin.path() == "/"
                && origin.query().is_none()
                && origin.fragment().is_none(),
            "Expected an HTTPS PostHog origin or loopback development server"
        );
        let http = Client::builder()
            .timeout(Duration::from_secs(25))
            .redirect(Policy::none())
            .retry(reqwest::retry::never())
            .build()?;
        let metadata: Metadata = http
            .get(origin.join(".well-known/oauth-authorization-server")?)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        ensure!(metadata.issuer == origin, "Unexpected OAuth issuer");
        for endpoint in [&metadata.authorization_endpoint, &metadata.token_endpoint]
            .into_iter()
            .chain(&metadata.registration_endpoint)
        {
            ensure!(
                endpoint.origin() == origin.origin()
                    && endpoint.username().is_empty()
                    && endpoint.password().is_none()
                    && endpoint.fragment().is_none(),
                "PostHog advertised an endpoint outside its issuer"
            );
        }
        Ok(Self { http, metadata })
    }

    /// Register once per deployment and callback, then reuse the returned public ID.
    pub async fn register(
        &self,
        name: &str,
        callback: &Callback,
        scopes: &[&str],
    ) -> Result<String> {
        let endpoint = self
            .metadata
            .registration_endpoint
            .clone()
            .context("This issuer requires a pre-registered public client ID")?;
        let response = self
            .http
            .post(endpoint)
            .json(&json!({
                "client_name": name, "redirect_uris": [callback.uri()],
                "response_types": ["code"], "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "none", "scope": scopes.join(" ")
            }))
            .send()
            .await?
            .error_for_status()?;
        #[derive(Deserialize)]
        struct Registration {
            client_id: String,
            scope: Option<String>,
        }
        let registration: Registration = response.json().await?;
        if let Some(granted) = registration.scope {
            ensure!(
                scopes
                    .iter()
                    .all(|scope| granted.split_whitespace().any(|s| s == *scope)),
                "Registration did not grant the requested scopes"
            );
        }
        ensure!(!registration.client_id.is_empty(), "Empty OAuth client ID");
        Ok(registration.client_id)
    }

    /// Bind a registered public client ID to its loopback redirect URI.
    pub fn client(&self, id: String, callback: &Callback) -> Result<NativeClient> {
        self.client_for_redirect(id, &callback.uri())
    }

    /// Reopen a registered client for refresh without binding a callback socket.
    pub fn client_for_redirect(&self, id: String, redirect: &str) -> Result<NativeClient> {
        let client = BasicClient::new(ClientId::new(id))
            .set_auth_uri(AuthUrl::from_url(
                self.metadata.authorization_endpoint.clone(),
            ))
            .set_token_uri(TokenUrl::from_url(self.metadata.token_endpoint.clone()))
            .set_auth_type(AuthType::RequestBody)
            .set_redirect_uri(RedirectUrl::new(redirect.to_owned())?);
        Ok(NativeClient {
            client,
            http: self.http.clone(),
        })
    }
}

/// A registered OAuth client for native sign-in and token refresh.
pub struct NativeClient {
    client: CodeClient,
    http: Client,
}

impl NativeClient {
    /// Open the authorization URL and exchange the loopback callback code for tokens.
    pub async fn authorize(
        &self,
        callback: Callback,
        scopes: &[&str],
        open_browser: impl FnOnce(&Url) -> Result<()>,
    ) -> Result<BasicTokenResponse> {
        ensure!(
            self.client.redirect_uri().map(|u| u.as_str()) == Some(callback.uri().as_str()),
            "Callback does not match this OAuth client"
        );
        let (challenge, verifier) = PkceCodeChallenge::new_random_sha256();
        let (url, state) = self
            .client
            .authorize_url(CsrfToken::new_random)
            .add_scopes(scopes.iter().map(|s| Scope::new(s.to_string())))
            .set_pkce_challenge(challenge)
            .url();
        open_browser(&url)?;
        let code = timeout(Duration::from_secs(300), callback.receive(state.secret()))
            .await
            .context("Browser sign-in timed out")??;
        self.client
            .exchange_code(AuthorizationCode::new(code))
            .set_pkce_verifier(verifier)
            .request_async(&self.http)
            .await
            .map_err(token_error)
    }

    /// Exchange a refresh token for a new token response.
    pub async fn refresh(&self, token: &RefreshToken) -> Result<BasicTokenResponse> {
        self.client
            .exchange_refresh_token(token)
            .request_async(&self.http)
            .await
            .map_err(token_error)
    }
}

// Token response decoding errors may carry raw bytes. Only expose the standard OAuth error code.
fn token_error<E: std::error::Error + 'static>(
    error: oauth2::RequestTokenError<E, oauth2::basic::BasicErrorResponse>,
) -> anyhow::Error {
    match error {
        oauth2::RequestTokenError::ServerResponse(response) => {
            anyhow!("PostHog token request failed ({})", response.error())
        }
        _ => anyhow!("PostHog token exchange failed. Start a new sign-in."),
    }
}

/// Loopback listener for one native authorization flow.
pub struct Callback {
    listener: TcpListener,
    port: u16,
}

impl Callback {
    /// Listen for a callback on localhost, using an ephemeral port when passed zero.
    pub async fn bind(port: u16) -> Result<Self> {
        let listener = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port))
            .await
            .context("Cannot bind the meep OAuth loopback listener")?;
        let port = listener.local_addr()?.port();
        Ok(Self { listener, port })
    }
    /// Return the redirect URI for the bound listener.
    pub fn uri(&self) -> String {
        format!("http://127.0.0.1:{}/callback", self.port)
    }

    async fn receive(self, state: &str) -> Result<String> {
        loop {
            let (mut socket, _) = self.listener.accept().await?;
            if let Ok(Ok(Some(outcome))) =
                timeout(Duration::from_secs(2), self.request(&mut socket, state)).await
            {
                return outcome;
            }
        }
    }

    async fn request(&self, socket: &mut TcpStream, state: &str) -> Result<Option<Result<String>>> {
        let mut line = String::new();
        BufReader::new((&mut *socket).take(8192))
            .read_line(&mut line)
            .await?;
        let mut parts = line.split_whitespace();
        let target = parts
            .next()
            .filter(|method| *method == "GET")
            .and_then(|_| parts.next());
        let callback = target
            .filter(|s| s.starts_with("/callback?") && line.ends_with('\n'))
            .and_then(|path| Url::parse(&format!("http://127.0.0.1{path}")).ok());
        let mut outcome = None;
        if let Some(url) = callback {
            let value = |key: &str| {
                let mut found = url.query_pairs().filter(|(name, _)| name == key);
                let (_, v) = found.next()?;
                found.next().is_none().then(|| v.into_owned())
            };
            use subtle::ConstantTimeEq;
            if value("state").is_some_and(|v| bool::from(v.as_bytes().ct_eq(state.as_bytes()))) {
                outcome = Some(if value("error").is_some() {
                    Err(anyhow!("Sign-in was declined by the authorization server"))
                } else {
                    value("code")
                        .filter(|s| !s.is_empty())
                        .context("Authorization server returned no code")
                });
            }
        }
        let status = if outcome.is_some() {
            "200 OK"
        } else {
            "400 Bad Request"
        };
        let body = if outcome.is_some() {
            "Return to the meep terminal to continue."
        } else {
            "Unrecognized callback."
        };
        let response = format!(
            "HTTP/1.1 {status}\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        );
        // A closed browser tab must not discard a code already received.
        if let Err(error) = socket.write_all(response.as_bytes()).await {
            eprintln!("Could not send the sign-in response to the browser: {error}");
        }
        Ok(outcome)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn a_loopback_callback_waits_for_one_matching_state() -> Result<()> {
        let callback = Callback::bind(0).await?;
        let uri = callback.uri();
        let receiver = tokio::spawn(callback.receive("fixture-state"));
        let browser = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()?;
        for query in [
            "state=fixture-stale",
            "state=fixture-state&state=other",
            "code=unused",
        ] {
            let response = browser
                .get(format!("{uri}?code=ignored&{query}"))
                .send()
                .await?;
            assert_eq!(response.status(), reqwest::StatusCode::BAD_REQUEST);
        }
        browser
            .get(format!("{uri}?state=fixture-state&code=accepted"))
            .send()
            .await?
            .error_for_status()?;
        assert_eq!(receiver.await??, "accepted");
        Ok(())
    }
}
