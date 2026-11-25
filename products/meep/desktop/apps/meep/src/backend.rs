mod direct;

use anyhow::{Context, Result, ensure};
use clap::Parser;
use meep_client::{Client, HttpTransport};
use meep_connections::{KeychainSecrets, SecretStore};
use meep_posthog::oauth::{Callback, Server, TokenResponse, session::registration};
use reqwest::Url;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

/// Keychain service for this app's credentials.
const KEYCHAIN: &str = "Meep";
const SCOPES: &[&str] = &[
    "meep:read",
    "inbox:read",
    "signal_scout:read",
    "meep:write",
    "task:read",
    "task:write",
    "project:read",
    "project:write",
    "feature_flag:read",
    "insight:read",
    "query:read",
    "event_definition:read",
    "user:read",
];

#[derive(Clone, Parser)]
#[command(name = "meep", about = "Meep")]
pub(super) struct Options {
    /// PostHog region for browser sign-in.
    #[arg(long, value_enum)]
    posthog: Option<Region>,
}

#[derive(clap::ValueEnum, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(super) enum Region {
    #[default]
    Us,
    Eu,
    Local,
}
impl Region {
    pub(super) fn key(self) -> &'static str {
        match self {
            Self::Us => "us",
            Self::Eu => "eu",
            Self::Local => "local",
        }
    }
    fn origin(self) -> &'static str {
        match self {
            Self::Us => "https://us.posthog.com",
            Self::Eu => "https://eu.posthog.com",
            Self::Local => "http://localhost:8010",
        }
    }
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct Identity {
    pub label: String,
    pub email: String,
    pub region: Region,
    project: u64,
}

impl Identity {
    pub(super) fn inbox_url(&self, section: &str, item: &str) -> Url {
        let mut url = Url::parse(self.region.origin()).expect("region is an HTTP origin");
        url.path_segments_mut()
            .expect("region has a hierarchical URL")
            .extend(["project", &self.project.to_string(), "inbox", section, item]);
        url
    }
}

#[derive(Clone)]
pub(super) struct Backend {
    account: Arc<direct::Account>,
    pub client: Client,
    pub server: String,
    pub root: PathBuf,
}

impl Options {
    pub(super) async fn connect(&self) -> Result<Backend> {
        let dev_root = std::env::var_os("MEEP_DEV_DIR").map(PathBuf::from);
        ensure!(
            std::env::var("MEEP_POSTHOG_LOCAL").as_deref() != Ok("1") || dev_root.is_some(),
            "Set MEEP_DEV_DIR to use local PostHog with isolated Meep data"
        );
        if let Some(path) = &dev_root {
            ensure!(path.is_absolute(), "MEEP_DEV_DIR must be an absolute path");
            if let Some(default) = dirs::data_dir() {
                let standard = default.join("Meep");
                ensure!(
                    !path.starts_with(&standard),
                    "MEEP_DEV_DIR must be outside the standard Meep data directory"
                );
            }
        }
        let root = match &dev_root {
            Some(path) => path.clone(),
            None => dirs::data_dir()
                .context("Missing application support directory")?
                .join("Meep"),
        };
        fs::create_dir_all(&root)?;
        if dev_root.is_some()
            && let Some(default) = dirs::data_dir()
        {
            let standard = default.join("Meep");
            if let Ok(standard) = standard.canonicalize() {
                ensure!(
                    !root.canonicalize()?.starts_with(standard),
                    "MEEP_DEV_DIR must be outside the standard Meep data directory"
                );
            }
        }
        let region = self.posthog.unwrap_or_else(|| {
            if std::env::var("MEEP_POSTHOG_LOCAL").as_deref() == Ok("1") {
                Region::Local
            } else {
                Region::Us
            }
        });
        direct::connect(root, region).await
    }
}

fn account_http() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(20))
        .build()?)
}

#[derive(Deserialize)]
struct PostHogUser {
    uuid: uuid::Uuid,
    email: String,
}

async fn posthog_user(http: &reqwest::Client, origin: &str, token: &str) -> Result<PostHogUser> {
    let account = http
        .get(format!("{origin}/api/users/@me/"))
        .bearer_auth(token)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    Ok(account)
}

impl Backend {
    pub(super) async fn login(&self, region: Region) -> Result<Identity> {
        let identity = self.account.login(&self.root, region).await?;
        self.client.set_preference("posthog-project", &identity)?;
        self.client.set_preference("signed-in", &true)?;
        self.client.sync_now();
        Ok(identity)
    }

    pub(super) async fn sign_out(&self) -> Result<()> {
        self.account.sign_out().await?;
        self.client.set_preference("signed-in", &false)?;
        Ok(())
    }
}

#[derive(Serialize, Deserialize)]
pub(super) struct Credentials {
    pub(super) identity: Identity,
    user: uuid::Uuid,
    pub(super) client_id: String,
    access_token: String,
    pub(super) refresh_token: String,
    expires_at: i64,
}

pub(super) async fn authorize(
    root: &Path,
    region: Region,
    origin: &str,
    callback: Callback,
    open_browser: impl FnOnce(&Url) -> Result<()>,
) -> Result<Credentials> {
    let issuer = Server::discover(origin).await?;
    let client_id_file = match region {
        Region::Us => Some("posthog-us-client-id"),
        Region::Local => Some("posthog-local-client-id"),
        Region::Eu => None,
    };
    let configured_id = if let Some(file) = client_id_file {
        match fs::read_to_string(root.join(file)) {
            Ok(id) => {
                ensure!(!id.trim().is_empty(), "Empty PostHog client ID in {file}");
                Some(id.trim().to_owned())
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
            Err(e) => return Err(e).context("Reading PostHog client ID"),
        }
    } else {
        None
    };
    let client_id = if let Some(id) = configured_id {
        id
    } else {
        registration(
            &issuer,
            &callback,
            origin,
            region.key(),
            root.join("topics-oauth")
                .join(format!("{:x}", Sha256::digest(SCOPES.join(" ")))),
            "Meep",
            SCOPES,
        )
        .await?
    };
    let client = issuer.client(client_id.clone(), &callback)?;
    let tokens = client.authorize(callback, SCOPES, open_browser).await?;
    if let Some(granted) = tokens.scopes() {
        ensure!(
            SCOPES
                .iter()
                .all(|scope| granted.iter().any(|s| s.as_str() == *scope)),
            "PostHog did not grant all the requested permissions."
        );
    }
    let token = tokens.access_token().secret();
    let refresh = tokens
        .refresh_token()
        .context("PostHog did not grant offline access. Sign in again.")?
        .secret();
    #[derive(Deserialize)]
    struct Project {
        id: u64,
        name: String,
    }
    let http = account_http()?;
    let project: Project = http
        .get(format!("{origin}/api/projects/@current/"))
        .bearer_auth(token)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    let user = posthog_user(&http, origin, token).await?;
    Ok(Credentials {
        identity: Identity {
            email: user.email,
            label: project.name,
            project: project.id,
            region,
        },
        user: user.uuid,
        client_id,
        access_token: token.clone(),
        refresh_token: refresh.clone(),
        expires_at: chrono::Utc::now().timestamp()
            + tokens
                .expires_in()
                .unwrap_or(Duration::from_secs(300))
                .as_secs() as i64,
    })
}
