//! Sign-in with PostHog (OAuth with PKCE over a loopback redirect) and the API calls the app makes.
//! Everything here blocks, so the UI runs it on the background executor.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use anyhow::{Context as _, Result, anyhow, bail};
use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::models::{Hog, HogMessage, HogRule, HogSchedule, HogTrigger, McpInstallation, Me};

pub struct Host {
    pub label: &'static str,
    pub url: &'static str,
    client_id: &'static str,
}

// The prototype signs in through the PostHog Desktop OAuth applications, which already
// allow this loopback redirect. A shipped app needs its own OAuth application.
pub const HOSTS: [Host; 3] = [
    Host {
        label: "Local (localhost:8010)",
        url: "http://localhost:8010",
        client_id: "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ",
    },
    Host {
        label: "PostHog US Cloud",
        url: "https://us.posthog.com",
        client_id: "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W",
    },
    Host {
        label: "PostHog EU Cloud",
        url: "https://eu.posthog.com",
        client_id: "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9",
    },
];

const CALLBACK_PORT: u16 = 8239;
const REDIRECT_URI: &str = "http://localhost:8239/callback";
const SCOPES: &str = "openid profile email user:read project:read organization:read task:read task:write";
const SIGN_IN_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Tokens {
    pub host: String,
    pub access_token: String,
    pub refresh_token: Option<String>,
}

/// The request was refused because the session is over. The UI goes back to the sign-in screen.
#[derive(Debug)]
pub struct SignedOut;

impl std::fmt::Display for SignedOut {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Your session ended. Sign in again.")
    }
}

impl std::error::Error for SignedOut {}

#[derive(Clone)]
pub struct Client {
    tokens: Arc<Mutex<Option<Tokens>>>,
    // One agent for every call, so polling reuses its connection instead of opening a new one.
    agent: ureq::Agent,
}

impl Default for Client {
    fn default() -> Self {
        let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs(30)).build();
        Self { tokens: Arc::default(), agent }
    }
}

fn random_token(bytes: usize) -> Result<String> {
    let mut buffer = vec![0u8; bytes];
    getrandom::fill(&mut buffer).map_err(|error| anyhow!("No random bytes: {error}"))?;
    Ok(URL_SAFE_NO_PAD.encode(buffer))
}

fn form(pairs: &[(&str, &str)]) -> String {
    pairs
        .iter()
        .map(|(key, value)| format!("{key}={}", urlencoding::encode(value)))
        .collect::<Vec<_>>()
        .join("&")
}

fn token_request(host: &str, pairs: &[(&str, &str)]) -> Result<Tokens> {
    let response = ureq::post(&format!("{host}/oauth/token/"))
        .set("Content-Type", "application/x-www-form-urlencoded")
        .send_string(&form(pairs));
    let body: Value = match response {
        Ok(response) => response.into_json()?,
        Err(ureq::Error::Status(_, response)) => {
            let body: Value = response.into_json().unwrap_or(Value::Null);
            let detail = body["error_description"].as_str().or(body["error"].as_str());
            bail!("{}", detail.unwrap_or("Sign-in was refused."))
        }
        Err(error) => bail!("Could not reach PostHog: {error}"),
    };
    Ok(Tokens {
        host: host.to_string(),
        access_token: body["access_token"].as_str().context("No access token in the reply.")?.to_string(),
        refresh_token: body["refresh_token"].as_str().map(str::to_string),
    })
}

/// Waits for the browser to come back to the loopback address and returns the authorization code.
fn wait_for_code(listener: TcpListener, expected_state: &str) -> Result<String> {
    listener.set_nonblocking(true)?;
    let deadline = Instant::now() + SIGN_IN_TIMEOUT;
    loop {
        let (mut stream, _) = match listener.accept() {
            Ok(connection) => connection,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                if Instant::now() > deadline {
                    bail!("Sign-in timed out. Try again.");
                }
                std::thread::sleep(Duration::from_millis(100));
                continue;
            }
            Err(error) => return Err(error.into()),
        };
        stream.set_nonblocking(false)?;
        stream.set_read_timeout(Some(Duration::from_secs(5)))?;
        let mut buffer = [0u8; 8192];
        let read = stream.read(&mut buffer).unwrap_or(0);
        let request = String::from_utf8_lossy(&buffer[..read]);
        let target = request.split_whitespace().nth(1).unwrap_or("");
        let Some(query) = target.strip_prefix("/callback?") else {
            let _ = stream.write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
            continue;
        };
        let param = |name: &str| {
            query.split('&').find_map(|pair| {
                let (key, value) = pair.split_once('=')?;
                (key == name).then(|| urlencoding::decode(value).map(|v| v.into_owned()).unwrap_or_default())
            })
        };
        let code = param("code").filter(|_| param("state").as_deref() == Some(expected_state));
        let title = if code.is_some() { "You are signed in" } else { "Sign-in did not complete" };
        let html = format!(
            "<body style=\"font-family:system-ui;padding:48px;text-align:center\"><h2>{title}</h2>\
             <p>You can close this tab and go back to Hogs.</p></body>"
        );
        let _ = stream.write_all(
            format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{html}",
                html.len()
            )
            .as_bytes(),
        );
        return code.ok_or_else(|| anyhow!(param("error").unwrap_or_else(|| "Sign-in did not complete.".into())));
    }
}

pub struct SignIn {
    pub authorize_url: String,
    host: &'static Host,
    verifier: String,
    state: String,
    listener: TcpListener,
}

impl SignIn {
    /// Opens the loopback listener first, so the redirect cannot arrive before anything is listening.
    pub fn begin(host: &'static Host) -> Result<Self> {
        let verifier = random_token(48)?;
        let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
        let state = random_token(16)?;
        let listener = TcpListener::bind(("127.0.0.1", CALLBACK_PORT))
            .with_context(|| format!("Could not listen on port {CALLBACK_PORT}."))?;
        let query = form(&[
            ("response_type", "code"),
            ("client_id", host.client_id),
            ("redirect_uri", REDIRECT_URI),
            ("scope", SCOPES),
            ("state", &state),
            ("code_challenge", &challenge),
            ("code_challenge_method", "S256"),
        ]);
        Ok(Self { authorize_url: format!("{}/oauth/authorize/?{query}", host.url), host, verifier, state, listener })
    }

    pub fn finish(self) -> Result<Tokens> {
        let code = wait_for_code(self.listener, &self.state)?;
        token_request(
            self.host.url,
            &[
                ("grant_type", "authorization_code"),
                ("code", &code),
                ("redirect_uri", REDIRECT_URI),
                ("client_id", self.host.client_id),
                ("code_verifier", &self.verifier),
            ],
        )
    }
}

impl Client {
    pub fn set_tokens(&self, tokens: Option<Tokens>) {
        *self.tokens.lock().unwrap() = tokens;
    }

    pub fn tokens(&self) -> Option<Tokens> {
        self.tokens.lock().unwrap().clone()
    }

    fn refresh(&self, stale: &Tokens) -> Result<Tokens> {
        let host = HOSTS.iter().find(|host| host.url == stale.host).ok_or(SignedOut)?;
        let refresh_token = stale.refresh_token.as_deref().ok_or(SignedOut)?;
        let renewed = token_request(
            host.url,
            &[("grant_type", "refresh_token"), ("refresh_token", refresh_token), ("client_id", host.client_id)],
        )
        .map_err(|_| SignedOut)?;
        self.set_tokens(Some(renewed.clone()));
        Ok(renewed)
    }

    fn send(&self, method: &str, path: &str, body: Option<&Value>, tokens: &Tokens) -> Result<ureq::Response, ureq::Error> {
        let request = self
            .agent
            .request(method, &format!("{}{path}", tokens.host))
            .set("Authorization", &format!("Bearer {}", tokens.access_token));
        match body {
            Some(body) => request.send_json(body),
            None => request.call(),
        }
    }

    fn request(&self, method: &str, path: &str, body: Option<Value>) -> Result<Value> {
        let mut tokens = self.tokens().ok_or(SignedOut)?;
        let mut retried = false;
        loop {
            match self.send(method, path, body.as_ref(), &tokens) {
                Ok(response) => {
                    let text = response.into_string()?;
                    return Ok(if text.is_empty() { Value::Null } else { serde_json::from_str(&text)? });
                }
                Err(ureq::Error::Status(401, _)) if !retried => {
                    tokens = self.refresh(&tokens)?;
                    retried = true;
                }
                Err(ureq::Error::Status(401, _)) => return Err(SignedOut.into()),
                Err(ureq::Error::Status(status, response)) => {
                    let body: Value = response.into_json().unwrap_or(Value::Null);
                    bail!("{}", body["detail"].as_str().map(str::to_string).unwrap_or(format!("Request failed ({status}).")))
                }
                Err(error) => bail!("Could not reach PostHog: {error}"),
            }
        }
    }

    fn get<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        Ok(serde_json::from_value(self.request("GET", path, None)?)?)
    }

    pub fn me(&self) -> Result<Me> {
        self.get("/api/users/@me/")
    }

    pub fn hogs(&self, team: i64) -> Result<Vec<Hog>> {
        self.get(&format!("/api/projects/{team}/hogs/"))
    }

    pub fn messages(&self, team: i64, hog: &str) -> Result<Vec<HogMessage>> {
        self.get(&format!("/api/projects/{team}/hogs/{hog}/messages/"))
    }

    pub fn schedules(&self, team: i64, hog: &str) -> Result<Vec<HogSchedule>> {
        self.get(&format!("/api/projects/{team}/hogs/{hog}/schedules/"))
    }

    pub fn triggers(&self, team: i64, hog: &str) -> Result<Vec<HogTrigger>> {
        self.get(&format!("/api/projects/{team}/hogs/{hog}/triggers/"))
    }

    pub fn rules(&self, team: i64, hog: &str) -> Result<Vec<HogRule>> {
        self.get(&format!("/api/projects/{team}/hogs/{hog}/rules/"))
    }

    /// Posts to one of a hog's actions, such as `reports/verdict`, and drops the reply.
    pub fn hog_post(&self, team: i64, hog: &str, action: &str, body: Value) -> Result<()> {
        self.request("POST", &format!("/api/projects/{team}/hogs/{hog}/{action}/"), Some(body)).map(|_| ())
    }

    pub fn mcp_installations(&self, team: i64) -> Result<Vec<McpInstallation>> {
        let value = self.request("GET", &format!("/api/projects/{team}/mcp_server_installations/"), None)?;
        let list = if value.is_array() { value } else { value["results"].clone() };
        Ok(serde_json::from_value(list).unwrap_or_default())
    }

    pub fn send_message(&self, team: i64, hog: &str, content: &str) -> Result<HogMessage> {
        let path = format!("/api/projects/{team}/hogs/{hog}/send/");
        Ok(serde_json::from_value(self.request("POST", &path, Some(json!({ "content": content })))?)?)
    }

    pub fn mark_read(&self, team: i64, hog: &str) -> Result<()> {
        self.request("POST", &format!("/api/projects/{team}/hogs/{hog}/read/"), None).map(|_| ())
    }

    pub fn create_hog(&self, team: i64, name: &str, emoji: &str, color: &str, mcp_ids: &[String]) -> Result<Hog> {
        let body = json!({ "name": name, "emoji": emoji, "color": color, "mcp_installation_ids": mcp_ids });
        Ok(serde_json::from_value(self.request("POST", &format!("/api/projects/{team}/hogs/"), Some(body))?)?)
    }

    pub fn update_hog(&self, team: i64, hog: &str, changes: Value) -> Result<()> {
        self.request("PATCH", &format!("/api/projects/{team}/hogs/{hog}/"), Some(changes)).map(|_| ())
    }

    pub fn delete_hog(&self, team: i64, hog: &str) -> Result<()> {
        self.request("DELETE", &format!("/api/projects/{team}/hogs/{hog}/"), None).map(|_| ())
    }
}
