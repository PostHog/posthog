use super::*;
use meep_client::{AccessToken, TransportError};
use meep_posthog::oauth::RefreshToken;
use tokio::sync::Mutex;

pub(crate) struct Account {
    key: String,
    user: uuid::Uuid,
    project: u64,
    region: Region,
    credentials: Mutex<Option<Credentials>>,
}

async fn authorize_direct(root: &Path, region: Region) -> Result<Credentials> {
    authorize(
        root,
        region,
        region.origin(),
        Callback::bind(43180).await?,
        |url| Ok(open::that_detached(url.as_str())?),
    )
    .await
}

pub(super) async fn connect(root: PathBuf, region: Region) -> Result<Backend> {
    let digest = Sha256::digest(root.canonicalize()?.as_os_str().as_encoded_bytes());
    let key = format!("posthog-{}-{digest:x}", region.key());
    let saved = KeychainSecrets::new(KEYCHAIN).get(&key, "session")?;
    let credentials: Credentials = if let Some(value) = saved {
        serde_json::from_str(&value)?
    } else {
        let value = authorize_direct(&root, region).await?;
        KeychainSecrets::new(KEYCHAIN).set(&key, "session", &serde_json::to_string(&value)?)?;
        value
    };
    let identity = credentials.identity.clone();
    ensure!(identity.region == region, "PostHog region changed");
    let user = credentials.user;
    let project = identity.project;
    let account = Arc::new(Account {
        key,
        region,
        user,
        project,
        credentials: Mutex::new(Some(credentials)),
    });
    let transport = HttpTransport::posthog(region.origin(), project, account.clone())?;
    let path = root.join(format!("replica-{}-{project}-{user}.sqlite", region.key()));
    let client = Client::open(path, Arc::new(transport))?;
    client.set_preference("posthog-project", &identity)?;
    client.set_preference("signed-in", &true)?;
    Ok(Backend {
        direct: Some(account),
        client,
        server: format!("{}/api/projects/{project}/meep", region.origin()),
        root,
    })
}

impl Account {
    pub(super) async fn login(&self, root: &Path, region: Region) -> Result<Identity> {
        ensure!(
            region == self.region,
            "Reopen Meep with this region to switch accounts."
        );
        let value = authorize_direct(root, region).await?;
        ensure!(
            value.user == self.user && value.identity.project == self.project,
            "Reopen Meep to switch accounts."
        );
        let mut state = self.credentials.lock().await;
        KeychainSecrets::new(KEYCHAIN).set(
            &self.key,
            "session",
            &serde_json::to_string(&value)?,
        )?;
        let identity = value.identity.clone();
        *state = Some(value);
        Ok(identity)
    }

    pub(super) async fn sign_out(&self) -> Result<()> {
        let mut state = self.credentials.lock().await;
        KeychainSecrets::new(KEYCHAIN).delete(&self.key, "session")?;
        *state = None;
        Ok(())
    }

    async fn token(&self, value: &mut Credentials) -> Result<String> {
        if value.expires_at <= chrono::Utc::now().timestamp() + 60 {
            let issuer = Server::discover(self.region.origin()).await?;
            let client = issuer
                .client_for_redirect(value.client_id.clone(), "http://127.0.0.1:43180/callback")?;
            let tokens = client
                .refresh(&RefreshToken::new(value.refresh_token.clone()))
                .await?;
            if let Some(refresh) = tokens.refresh_token() {
                value.refresh_token = refresh.secret().clone();
            }
            value.access_token = tokens.access_token().secret().clone();
            let ttl = tokens.expires_in().unwrap_or(Duration::from_secs(300));
            value.expires_at = chrono::Utc::now().timestamp() + ttl.as_secs() as i64;
            KeychainSecrets::new(KEYCHAIN).set(
                &self.key,
                "session",
                &serde_json::to_string(value)?,
            )?;
        }
        Ok(value.access_token.clone())
    }
}

#[async_trait::async_trait]
impl AccessToken for Account {
    async fn sources(
        &self,
    ) -> std::result::Result<Vec<meep_wire::WatchableSource>, TransportError> {
        let token = self.access_token().await?;
        self.discover_sources(&token)
            .await
            .map_err(|err| TransportError::Protocol(err.to_string()))
    }

    async fn read_view_source(
        &self,
        params: &serde_json::Value,
    ) -> std::result::Result<serde_json::Value, TransportError> {
        let token = self.access_token().await?;
        let origin = self.region.origin();
        let configured_endpoint = std::env::var("POSTHOG_MCP_URL").ok();
        let endpoint = configured_endpoint
            .as_deref()
            .filter(|url| !url.is_empty())
            .unwrap_or(match self.region {
                Region::Local => "http://localhost:8787/mcp",
                Region::Us | Region::Eu => meep_posthog::mcp::DEFAULT_ENDPOINT,
            });
        let read = async {
            let client = meep_posthog::mcp::McpClient::new(endpoint, Some(self.project))?;
            meep_posthog::mcp::view::read_source(
                client,
                origin,
                self.project,
                &token,
                params["source"].as_str().context("Missing source")?,
                params["tool"].as_str().context("Missing tool")?,
                &params["arguments"],
            )
            .await
        };
        read.await
            .map_err(|error| TransportError::Protocol(error.to_string()))
    }

    async fn mcp_store(
        &self,
        operation: &meep_wire::mcp_store::Operation,
    ) -> std::result::Result<meep_wire::mcp_store::Outcome, TransportError> {
        let token = self.access_token().await?;
        meep_posthog::mcp::store::execute(
            self.region.origin(),
            self.project,
            &token,
            operation.clone(),
        )
        .await
        .map_err(|error| TransportError::Protocol(error.to_string()))
    }

    async fn access_token(&self) -> std::result::Result<String, TransportError> {
        let mut guard = self.credentials.lock().await;
        self.token(guard.as_mut().ok_or(TransportError::Unauthorized)?)
            .await
            .map_err(|e| TransportError::Unavailable(e.to_string()))
    }
}

impl Account {
    async fn discover_sources(&self, token: &str) -> Result<Vec<meep_wire::WatchableSource>> {
        use meep_posthog::api::ProjectEndpoint;
        use serde_json::Value;
        #[derive(Deserialize)]
        struct Page {
            results: Vec<Value>,
            next: Option<String>,
        }
        let mut sources = Vec::new();
        for (collection, kind) in [("insights", "insight"), ("feature_flags", "flag")] {
            let api = ProjectEndpoint::new(self.region.origin(), self.project, collection)?;
            let mut next = Some("?limit=100".to_string());
            let mut visited = std::collections::HashSet::new();
            while let Some(page) = next {
                ensure!(
                    visited.insert(page.clone()),
                    "Repeated PostHog pagination link"
                );
                let page: Page = api.get(token, &page).await?;
                for row in page.results {
                    let Some(key) = row["id"].as_u64().map(|i| i.to_string()) else {
                        continue;
                    };
                    let label = ["name", "derived_name", "key", "short_id"]
                        .iter()
                        .find_map(|field| row[*field].as_str().filter(|s| !s.is_empty()))
                        .unwrap_or(&key)
                        .to_owned();
                    sources.push(meep_wire::WatchableSource {
                        connection: "posthog".into(),
                        kind: kind.into(),
                        key,
                        label,
                        supported_modes: vec!["pull".into()],
                    });
                }
                next = page.next;
            }
        }
        let gateway = meep_posthog::mcp::Gateway::new(self.region.origin(), self.project)?;
        for server in gateway.available(token).await? {
            if server.tools.iter().any(|t| t.approval_state == "approved") {
                sources.push(meep_wire::WatchableSource {
                    connection: "posthog".into(),
                    kind: "service".into(),
                    key: server.installation_id.to_string(),
                    label: server.name,
                    supported_modes: vec![],
                });
            }
        }
        sources.sort_by(|a, b| a.label.cmp(&b.label).then(a.key.cmp(&b.key)));
        Ok(sources)
    }
}
