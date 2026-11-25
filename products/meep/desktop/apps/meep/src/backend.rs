mod direct;

use anyhow::{Context, Result, ensure};
use clap::Parser;
use meep_client::{Client, HttpTransport};
use meep_connections::{KeychainSecrets, SecretStore};
use meep_posthog::oauth::{Callback, Server, TokenResponse, session::registration};
use meep_wire::ConnectionGrant;
use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Arc,
    time::Duration,
};

/// Keychain service for this app's credentials.
const KEYCHAIN: &str = "Meep";
/// Service name used before the app was called Meep.
const LEGACY_KEYCHAIN: &str = "Meep Topics";
const SCOPES: &[&str] = &[
    "task:read",
    "task:write",
    "insight:read",
    "feature_flag:read",
    "query:read",
    "hog_flow:read",
    "hog_flow:write",
    "project:read",
    "project:write",
    "organization:read",
    "person:read",
    "user:read",
    // PostHog Scout reports: read them into topics, write verdicts back.
    "inbox:read",
    "inbox:write",
];

#[derive(Clone, Parser)]
#[command(name = "meep", about = "Meep")]
pub(super) struct Options {
    /// Hosted Meep server. Pair once using MEEP_DEVICE_TOKEN, then use the Keychain.
    #[arg(long)]
    server: Option<String>,
    /// Connect directly to this PostHog region using browser sign-in.
    #[arg(long, value_enum, conflicts_with = "server")]
    posthog: Option<Region>,
    /// Use the standalone Rust service and its local workspace.
    #[arg(long, conflicts_with_all = ["posthog", "server"])]
    legacy: bool,
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
    /// Account email returned by PostHog. Older replicas only stored the project.
    #[serde(default)]
    pub email: Option<String>,
    pub region: Region,
    project: u64,
}

#[derive(Clone)]
pub(super) struct Backend {
    pub(super) direct: Option<Arc<direct::Account>>,
    pub client: Client,
    pub server: String,
    pub root: PathBuf,
    /// Keychain account for this owner's PostHog sign-in on this server.
    pub credentials: String,
}

impl Options {
    pub(super) async fn connect(&self) -> Result<(Backend, Option<String>)> {
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
        if !self.legacy && self.server.is_none() && std::env::var_os("MEEP_LEGACY_SERVER").is_none()
        {
            let region = self.posthog.unwrap_or_else(|| {
                if std::env::var("MEEP_POSTHOG_LOCAL").as_deref() == Ok("1") {
                    Region::Local
                } else {
                    Region::Us
                }
            });
            return Ok((direct::connect(root, region).await?, None));
        }
        if let Some(server) = self.server.clone() {
            ensure!(
                dev_root.is_none(),
                "MEEP_DEV_DIR cannot be used with --server"
            );
            let token = match std::env::var("MEEP_DEVICE_TOKEN") {
                Ok(value) => Some(value),
                Err(std::env::VarError::NotPresent) => None,
                Err(std::env::VarError::NotUnicode(_)) => {
                    anyhow::bail!("Invalid device token encoding")
                }
            };
            let backend = hosted(
                &root,
                &server,
                token.as_deref(),
                &mut KeychainSecrets::new(KEYCHAIN),
            )
            .await?;
            return Ok((backend, None));
        }
        ensure!(
            dev_root.is_none() || std::env::var_os("MEEP_DATA_DIR").is_none(),
            "MEEP_DEV_DIR cannot be combined with MEEP_DATA_DIR"
        );
        let port = if dev_root.is_some() {
            let port = std::env::var("MEEP_DEV_PORT").unwrap_or_else(|_| "47951".into());
            let port: u16 = port.parse().context("Invalid MEEP_DEV_PORT")?;
            ensure!(
                port != 0 && port != 47950,
                "MEEP_DEV_PORT must be a nonzero port other than 47950"
            );
            port
        } else {
            47950
        };
        let listen = format!("127.0.0.1:{port}");
        let server = format!("http://{listen}");
        let dir = std::env::var_os("MEEP_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| root.join("server"));
        let path = if dir == root.join("server") {
            root.join("replica.sqlite")
        } else {
            let hash = Sha256::digest(dir.as_os_str().as_encoded_bytes());
            root.join(format!("replica-local-{hash:x}.sqlite"))
        };
        let startup = ensure_server(&dir, &listen, dev_root.is_some()).await;
        if dev_root.is_some() {
            startup.as_ref().map_err(|e| anyhow::anyhow!("{e:#}"))?;
        }
        let token = fs::read_to_string(dir.join("device-token")).with_context(|| {
            startup
                .as_ref()
                .err()
                .map(ToString::to_string)
                .unwrap_or_else(|| format!("Cannot read the device token in {}", dir.display()))
        })?;
        let client = Client::open(path, Arc::new(HttpTransport::new(&server, token.trim())?))?;
        let credentials = if dev_root.is_some() {
            let digest = Sha256::digest(root.canonicalize()?.as_os_str().as_encoded_bytes());
            format!("{server}#dev-{digest:x}")
        } else {
            server.clone()
        };
        Ok((
            Backend {
                direct: None,
                client,
                server: server.clone(),
                root,
                credentials,
            },
            startup.err().map(|e| e.to_string()),
        ))
    }
}

/// Pair with a hosted server. The replica and the PostHog sign-in belong to the
/// owner of the device token, so switching owners never reuses the other's cache
/// or outbox.
pub(super) async fn hosted(
    root: &Path,
    server: &str,
    supplied: Option<&str>,
    secrets: &mut impl SecretStore,
) -> Result<Backend> {
    let pairing = Client::pair(root, server, supplied, secrets).await?;
    Ok(Backend {
        direct: None,
        client: pairing.client,
        server: server.to_owned(),
        root: root.to_owned(),
        credentials: pairing.credential_namespace,
    })
}

fn spawn_server(dir: &Path, listen: &str) -> Result<Child> {
    let sibling = std::env::current_exe()?.with_file_name("meep-server");
    let exe = if sibling.is_file() {
        sibling
    } else {
        PathBuf::from("meep-server")
    };
    let mut command = Command::new(exe);
    #[cfg(unix)]
    std::os::unix::process::CommandExt::process_group(&mut command, 0);
    command.arg("--data-dir")
        .arg(dir)
        .args(["--listen", listen, "serve"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .spawn()
        .context("Could not start meep-server. Build it with cargo build -p meep-server, or put it on PATH.")
}

async fn ensure_server(dir: &Path, listen: &str, isolated: bool) -> Result<()> {
    let http = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_millis(900))
        .build()?;
    let url = format!("http://{listen}/v1/health");
    let reachable = |starting| {
        let http = &http;
        let url = &url;
        async move {
            let mut request = http.get(url.as_str());
            let token = if isolated {
                fs::read_to_string(dir.join("device-token")).ok()
            } else {
                None
            };
            if let Some(token) = &token {
                request = request.bearer_auth(token.trim());
            }
            match request.send().await {
                Ok(r) if r.status().is_success() && isolated && starting && token.is_none() => {
                    Ok(false)
                }
                Ok(r) if r.status().is_success() && isolated => {
                    ensure!(
                        token.is_some(),
                        "No device token for the server at {listen}"
                    );
                    r.json::<meep_wire::ServerHealth>()
                        .await
                        .context("Unexpected server health response")?;
                    Ok(true)
                }
                Ok(r) if r.status().is_success() => Ok(true),
                Ok(r)
                    if r.status() == StatusCode::UNAUTHORIZED
                        && isolated
                        && starting
                        && token.is_none() =>
                {
                    Ok(false)
                }
                Ok(r) if r.status() == StatusCode::UNAUTHORIZED && !isolated => Ok(true),
                Ok(r) => anyhow::bail!(
                    "Unexpected health response at {listen} ({}); the port may belong to another server",
                    r.status()
                ),
                Err(e) if e.is_connect() => Ok(false),
                Err(e) => Err(e.into()),
            }
        }
    };
    if reachable(false).await? {
        return Ok(());
    }
    let mut child = spawn_server(dir, listen)?;
    for _ in 0..100 {
        tokio::time::sleep(Duration::from_millis(75)).await;
        if reachable(true).await? {
            std::thread::Builder::new()
                .name("topics-server-child".into())
                .spawn(move || {
                    let _ = child.wait();
                })?;
            return Ok(());
        }
        if let Some(status) = child.try_wait()? {
            anyhow::bail!("meep-server exited during startup ({status})")
        }
    }
    anyhow::bail!("meep-server did not become ready at {listen}")
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
    /// Look up the missing profile field for a replica created before email was cached.
    pub(super) async fn restore_email(&self, region: Region) -> Result<String> {
        let server = self.credentials.clone();
        let secrets = tokio::task::spawn_blocking(move || {
            // Credentials saved before the rename live under the old service name.
            match KeychainSecrets::new(KEYCHAIN).get(&server, "posthog") {
                Ok(Some(v)) => Ok(Some(v)),
                _ => KeychainSecrets::new(LEGACY_KEYCHAIN).get(&server, "posthog"),
            }
        })
        .await??
        .context("No local PostHog credentials")?;
        let values: BTreeMap<String, String> = serde_json::from_str(&secrets)?;
        Ok(posthog_user(
            &account_http()?,
            region.origin(),
            values
                .get("access_token")
                .context("Missing PostHog access token")?,
        )
        .await?
        .email)
    }
    pub(super) async fn login(&self, region: Region) -> Result<Identity> {
        if let Some(account) = &self.direct {
            let identity = account.login(&self.root, region).await?;
            self.client.set_preference("signed-in", &true)?;
            self.client.sync_now();
            return Ok(identity);
        }
        self.login_with(
            region,
            region.origin(),
            Callback::bind(43180).await?,
            &mut KeychainSecrets::new(KEYCHAIN),
            |url| Ok(open::that_detached(url.as_str())?),
        )
        .await
    }

    pub(super) async fn login_with(
        &self,
        region: Region,
        origin: &str,
        callback: Callback,
        keychain: &mut (impl SecretStore + Send),
        open_browser: impl FnOnce(&Url) -> Result<()>,
    ) -> Result<Identity> {
        let (identity, secrets) =
            authorize(&self.root, region, origin, callback, SCOPES, open_browser).await?;
        let previous = self.client.preference::<Identity>("posthog-project")?;
        ensure!(
            previous
                .as_ref()
                .is_none_or(|p| p.region == region && p.project == identity.project),
            "This replica belongs to another PostHog project. Connect a separate Meep server for this project."
        );
        self.client
            .register_connection(
                "posthog",
                &ConnectionGrant {
                    kind: "posthog".into(),
                    label: "PostHog".into(),
                    account: Some(identity.label.clone()),
                    grants: vec![],
                    secrets: secrets.clone(),
                },
            )
            .await?;
        keychain.set(
            &self.credentials,
            "posthog",
            &serde_json::to_string(&secrets)?,
        )?;
        self.client.set_preference("posthog-project", &identity)?;
        self.client.set_preference("signed-in", &true)?;
        Ok(identity)
    }
    /// Sign out on this Mac, then on the server so it stops using the account.
    /// The local sign-out always happens; a server error is reported after it.
    pub(super) async fn sign_out(&self) -> Result<()> {
        if let Some(account) = &self.direct {
            account.sign_out().await?;
            self.client.set_preference("signed-in", &false)?;
            return Ok(());
        }
        KeychainSecrets::new(KEYCHAIN).delete(&self.credentials, "posthog")?;
        self.client.set_preference("signed-in", &false)?;
        self.client
            .sign_out("posthog")
            .await
            .map(|_| ())
            .map_err(|e| e.context("Signed out on this Mac, but the server still has the sign-in. Sign out again when it is reachable"))
    }
}

async fn authorize(
    root: &Path,
    region: Region,
    origin: &str,
    callback: Callback,
    scopes: &[&str],
    open_browser: impl FnOnce(&Url) -> Result<()>,
) -> Result<(Identity, BTreeMap<String, String>)> {
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
                .join(format!("{:x}", Sha256::digest(scopes.join(" ")))),
            "Meep",
            scopes,
        )
        .await?
    };
    let client = issuer.client(client_id.clone(), &callback)?;
    let tokens = client.authorize(callback, scopes, open_browser).await?;
    if let Some(granted) = tokens.scopes() {
        ensure!(
            scopes
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
    let identity = Identity {
        email: Some(user.email),
        label: project.name,
        project: project.id,
        region,
    };
    let mut secrets = BTreeMap::from([
        (
            "region".into(),
            if region != Region::Local && origin == region.origin() {
                region.key()
            } else {
                origin
            }
            .into(),
        ),
        ("client_id".into(), client_id),
        ("user_uuid".into(), user.uuid.to_string()),
        ("project_id".into(), project.id.to_string()),
        ("access_token".into(), token.clone()),
        ("refresh_token".into(), refresh.clone()),
    ]);
    if let Some(ttl) = tokens.expires_in() {
        secrets.insert(
            "expires_at".into(),
            (chrono::Utc::now().timestamp() + ttl.as_secs() as i64).to_string(),
        );
    }
    if region == Region::Local {
        secrets.insert(
            "config".into(),
            serde_json::json!({"mcp_endpoint":"http://localhost:8787/mcp"}).to_string(),
        );
    }
    Ok((identity, secrets))
}
