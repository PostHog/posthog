//! In-memory access-token refresh and optional public client ID caching for native applications.
use super::{BasicTokenResponse, Callback, NativeClient, RefreshToken, Server, TokenResponse};
use anyhow::{Context, Result, ensure};
use std::{
    fs,
    io::{self, Write},
    path::PathBuf,
    time::{Duration, Instant},
};

/// Cache a public registration for an issuer and callback. Use a separate directory or
/// label for every app and scope set. Only the public registration ID is written.
pub async fn registration(
    server: &Server,
    callback: &Callback,
    origin: &str,
    region: &str,
    directory: PathBuf,
    name: &str,
    scopes: &[&str],
) -> Result<String> {
    let path = directory;
    ensure!(
        !region.is_empty()
            && region
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'-'),
        "Invalid registration cache label"
    );
    fs::create_dir_all(&path)?;
    let url = url::Url::parse(origin)?;
    let callback_url = url::Url::parse(&callback.uri())?;
    let key = format!(
        "{region}-{}-{}-{}-{}.client",
        url.scheme(),
        url.host_str().context("Missing host")?,
        url.port_or_known_default().context("Missing port")?,
        callback_url
            .port_or_known_default()
            .context("Missing callback port")?
    );
    let file = path.join(key);
    match fs::read_to_string(&file) {
        Ok(id) => {
            ensure!(
                !id.trim().is_empty(),
                "Empty registration file at {}",
                file.display()
            );
            return Ok(id.trim().to_string());
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => (),
        Err(err) => return Err(err.into()),
    }
    let id = server.register(name, callback, scopes).await?;
    let mut temp = tempfile::NamedTempFile::new_in(path)?;
    writeln!(temp, "{id}")?;
    temp.persist(file)?;
    Ok(id)
}

/// In-memory credentials for a native session, including refresh-token rotation.
pub struct Session {
    client: NativeClient,
    tokens: BasicTokenResponse,
    refresh: Option<RefreshToken>,
    obtained: Instant,
}
impl Session {
    /// Verify the required scopes and retain the issued tokens.
    pub fn new(client: NativeClient, tokens: BasicTokenResponse, scopes: &[&str]) -> Result<Self> {
        if let Some(granted) = tokens.scopes() {
            ensure!(
                scopes
                    .iter()
                    .all(|s| granted.iter().any(|g| g.as_str() == *s)),
                "OAuth session is missing a requested scope"
            );
        }
        Ok(Self {
            client,
            refresh: tokens.refresh_token().cloned(),
            tokens,
            obtained: Instant::now(),
        })
    }

    /// Return the access token, refreshing it shortly before expiry.
    pub async fn token(&mut self) -> Result<&str> {
        if self
            .tokens
            .expires_in()
            .is_some_and(|ttl| self.obtained.elapsed() + Duration::from_secs(15) >= ttl)
        {
            let token = self
                .refresh
                .as_ref()
                .context("Session expired. Sign in again.")?;
            self.tokens = self.client.refresh(token).await?;
            if let Some(rotated) = self.tokens.refresh_token() {
                self.refresh = Some(rotated.clone());
            }
            self.obtained = Instant::now();
        }
        Ok(self.tokens.access_token().secret())
    }
}
