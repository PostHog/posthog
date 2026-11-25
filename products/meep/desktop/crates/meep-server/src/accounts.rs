use crate::{
    auth::matches_secret,
    connector::{ConnectorFactory, Poller},
    posthog::Project,
    vault::{Secrets, Vault},
};
use anyhow::{Context, Result, ensure};
use axum::http::HeaderMap;
use chrono::Utc;
use meep_connections::{Connection, Health};
use meep_connectors::{StateStore, WebhookError};
use meep_engine::{Engine, Store};
use meep_topic::TopicId;
use meep_wire::{ConnectionGrant, ConnectionInfo};
use parking_lot::{Mutex, RwLock};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio::sync::broadcast;
use uuid::Uuid;

#[derive(Clone)]
pub(crate) struct Account {
    pub public: Connection,
    pub version: Uuid,
    pub values: Secrets,
    pub project: Option<Arc<Project>>,
    /// Independent project check; source-specific failures must not block other APIs.
    pub(super) project_ready: Arc<AtomicBool>,
    /// Whether a failed project check is safe to retry before dispatch.
    pub(super) project_retryable: Arc<AtomicBool>,
    pub poller: Option<Arc<Poller>>,
    pub interval: std::time::Duration,
    config: Value,
    pub(super) refresh_lock: Arc<tokio::sync::Mutex<()>>,
}
pub(crate) struct Accounts {
    pub(super) owner: std::sync::Weak<Accounts>,
    pub(super) engine: std::sync::OnceLock<std::sync::Weak<Engine>>,
    pub(super) jobs: tokio_util::task::TaskTracker,

    pub store: Arc<dyn Store>,
    vault: Mutex<Vault>,
    factory: Arc<dyn ConnectorFactory>,
    pub(super) checkpoints: Arc<dyn StateStore>,
    live: RwLock<BTreeMap<String, Arc<Account>>>,
    pub(super) writes: Mutex<()>,
    pub feed: broadcast::Sender<ConnectionInfo>,
    /// Externally reachable base for run-scoped MCP endpoints.
    pub(super) public_base: RwLock<Option<String>>,
    /// Topic MCP capabilities whose run start has not yet been recorded: fingerprint, topic,
    /// connection, and once PostHog accepted the run, when the grace for the engine to record
    /// it ends.
    pub(super) launching: Mutex<Vec<Launch>>,
}

/// A launching run's capability fingerprint, topic, connection and grace deadline.
pub(super) type Launch = (String, TopicId, String, Option<std::time::Instant>);

#[derive(serde::Deserialize)]
struct AiOutage {
    version: Uuid,
    connector: Health,
}
pub fn info(c: &Connection) -> ConnectionInfo {
    ConnectionInfo {
        unrouted: c.unrouted,
        id: c.id.clone(),
        kind: c.kind.clone(),
        label: c.label.clone(),
        account: (!c.account.is_empty()).then(|| c.account.clone()),
        health: match c.health {
            Health::Ok { .. } => "ok",
            Health::Expired { ref detail, .. } if detail == "Signed out" => "signed_out",
            Health::Expired { .. } => "expired",
            Health::Failing { .. } => "failing",
        }
        .into(),
        unhealthy_since: match c.health {
            Health::Ok { .. } => None,
            Health::Expired { since, .. } | Health::Failing { since, .. } => Some(since),
        },
        summary: c.health.summary().into(),
        grants: c.grants.clone(),
    }
}
impl Accounts {
    pub fn new(
        owner: std::sync::Weak<Accounts>,
        store: Arc<dyn Store>,
        vault: Vault,
        factory: Arc<dyn ConnectorFactory>,
        checkpoints: Arc<dyn StateStore>,
    ) -> Self {
        Self {
            owner,
            engine: Default::default(),
            jobs: Default::default(),
            store,
            vault: Mutex::new(vault),
            factory,
            checkpoints,
            live: Default::default(),
            writes: Default::default(),
            feed: broadcast::channel(128).0,
            public_base: Default::default(),
            launching: Default::default(),
        }
    }
    pub fn restore(&self, engine: &Engine) -> Result<()> {
        for mut c in self.store.connections()? {
            let credentials = self.store.credential_version(&c.id)?;
            if credentials == Some(Uuid::nil()) {
                continue;
            }
            let loaded = credentials.and_then(|v| {
                self.vault
                    .lock()
                    .read(&c.id, v)
                    .ok()
                    .map(|values| (v, values))
            });
            c.health = match loaded {
                Some((version, values)) => match self.build(c.clone(), version, values, None) {
                    Ok(mut a) => {
                        if a.public.kind == "posthog" {
                            let key = format!("\0topics/ai-health/{}", c.id);
                            let previous = self.checkpoints.load(&key)?.filter(|v| !v.is_null());
                            if let Some(record) = &previous {
                                let outage: AiOutage = serde_json::from_value(record.clone())?;
                                if outage.version == version {
                                    a.public.health = outage.connector;
                                    self.store.set_health(&c.id, a.public.health.clone())?;
                                }
                                self.checkpoints.commit(&key, Some(record), &Value::Null)?;
                            }
                            if a.values.contains_key("ai_key") || a.values.contains_key("ai_oauth")
                            {
                                let mut values = a.values.clone();
                                values.remove("ai_key");
                                values.remove("ai_oauth");
                                self.persist(engine, a.public.clone(), values, Some(&a))?;
                                continue;
                            }
                        }
                        self.install(engine, a);
                        continue;
                    }
                    Err(_) => Health::Failing {
                        since: Utc::now(),
                        detail:
                            "Register this connection again with a valid connector configuration"
                                .into(),
                    },
                },
                None => Health::Expired {
                    since: Utc::now(),
                    detail: "Register this connection's credentials again".into(),
                },
            };
            self.store.set_health(&c.id, c.health)?;
        }
        Ok(())
    }
    fn build(
        &self,
        public: Connection,
        version: Uuid,
        values: Secrets,
        subscriptions: Option<Value>,
    ) -> Result<Account> {
        let kind = public.kind.as_str();
        let project = (kind == "posthog")
            .then(|| Project::from_secrets(&values).map(Arc::new))
            .transpose()?;
        let mut config: Value = values
            .get("config")
            .map(|s| serde_json::from_str(s))
            .transpose()?
            .unwrap_or_else(|| json!({}));
        let fields = config
            .as_object_mut()
            .context("Expected a connector configuration object")?;
        fields.insert("connection".into(), json!(public.id));
        let mut adapter_secrets = values.clone();
        if let Some(token) = values.get("access_token") {
            adapter_secrets.insert("token".into(), token.clone());
        }
        if let Some(token) = values.get("webhook_secret") {
            adapter_secrets.insert("secret".into(), token.clone());
        }
        if let Some(p) = &project {
            fields.insert("origin".into(), json!(p.origin));
            fields.insert("project".into(), json!(p.project));
            let origin = p.origin.trim_end_matches('/');
            if !matches!(origin, "https://us.posthog.com" | "https://eu.posthog.com") {
                fields
                    .entry("mcp_endpoint")
                    .or_insert_with(|| json!(format!("{origin}/mcp")));
            }
            if let Some(watches) = subscriptions {
                fields.insert("watches".into(), watches);
            } else {
                fields.entry("watches").or_insert_with(|| json!([]));
            }
        }
        let poller = if kind == "webhook" && !values.contains_key("config") {
            ensure!(
                values.get("webhook_secret").is_some_and(|s| !s.is_empty()),
                "Missing webhook_secret"
            );
            None
        } else {
            Some(Arc::new(Poller::new(
                self.factory.as_ref(),
                kind,
                config.clone(),
                &adapter_secrets,
                self.checkpoints.clone(),
                self.store.clone(),
            )?))
        };
        let interval = values
            .get("poll_interval_seconds")
            .map(|s| s.parse::<u64>())
            .transpose()?
            .unwrap_or(30);
        ensure!(interval > 0, "Polling interval must be positive");
        let project_ready = matches!(public.health, Health::Ok { .. });
        Ok(Account {
            refresh_lock: Default::default(),
            config,
            interval: std::time::Duration::from_secs(interval),
            public,
            version,
            values,
            project,
            project_ready: Arc::new(AtomicBool::new(project_ready)),
            project_retryable: Arc::new(AtomicBool::new(!project_ready)),
            poller,
        })
    }
    fn install(&self, engine: &Engine, a: Account) {
        let key = a.public.id.clone();
        if let Some(p) = &a.poller {
            engine.attach_connector(p.clone());
        } else {
            engine.attach_connector(Arc::new(WebhookInbox(key.clone())));
        }
        self.live.write().insert(key, Arc::new(a));
    }
    pub fn get(&self, id: &str) -> Option<Arc<Account>> {
        self.live.read().get(id).cloned()
    }
    pub fn all(&self) -> Vec<Arc<Account>> {
        self.live.read().values().cloned().collect()
    }
    pub fn put(&self, engine: &Engine, id: &str, grant: ConnectionGrant) -> Result<ConnectionInfo> {
        ensure!(
            !id.trim().is_empty() && id.len() <= 128 && !matches!(id, "topic" | "user"),
            "Invalid connection ID"
        );
        let _lock = self.writes.lock();
        let old = self.get(id);
        let mut values = old
            .as_ref()
            .filter(|a| a.public.kind == grant.kind)
            .map(|a| a.values.clone())
            .unwrap_or_default();
        // A new destination needs its own credentials. Changing a URL must never
        // forward a stored token to a different service.
        let previous_target = destination(&values)?;
        values.extend(grant.secrets.clone());
        if grant.kind == "posthog" {
            values.remove("ai_oauth");
            values.remove("ai_key");
        }
        if previous_target != destination(&values)? {
            for name in ["token", "access_token", "refresh_token"] {
                if !grant.secrets.contains_key(name) {
                    values.remove(name);
                }
            }
        }
        let mut seen = BTreeSet::new();
        let mut public = Connection {
            unrouted: old.as_ref().map_or(0, |a| a.public.unrouted),
            id: id.into(),
            kind: grant.kind,
            label: grant.label,
            account: grant.account.unwrap_or_default(),
            grants: grant
                .grants
                .into_iter()
                .filter(|t| seen.insert(*t))
                .collect(),
            health: Health::Ok {
                checked_at: Utc::now(),
            },
        };
        if public.kind != "webhook" {
            public.health = Health::Failing {
                since: old
                    .as_ref()
                    .filter(|a| a.public.kind == public.kind)
                    .map_or_else(Utc::now, |a| watermark(&a.public.health)),
                detail: "Waiting for a service health check".into(),
            };
        }
        self.persist(engine, public, values, old.as_deref())
    }
    pub(super) fn persist(
        &self,
        engine: &Engine,
        public: Connection,
        values: Secrets,
        old: Option<&Account>,
    ) -> Result<ConnectionInfo> {
        let id = public.id.clone();
        let version = Uuid::new_v4();
        let a = self.build(public.clone(), version, values, None)?;
        let mut vault = self.vault.lock();
        vault
            .save(&id, version, &a.values)
            .context("Could not save the connection settings")
            .map_err(meep_engine::Error::from)?;
        if let Err(e) = self.store.put_connection(public.clone(), version) {
            vault.remove(&id, version);
            return Err(meep_engine::Error::from(
                e.context("Could not save the connection settings"),
            )
            .into());
        }
        self.install(engine, a);
        if let Some(old) = old {
            vault.remove(&id, old.version);
        }
        let result = info(&public);
        let _ = self.feed.send(result.clone());
        Ok(result)
    }
    pub(super) fn signed_out_grants(
        &self,
        id: &str,
        grant: &ConnectionGrant,
    ) -> Result<Vec<TopicId>> {
        if self.store.credential_version(id)? != Some(Uuid::nil()) {
            return Ok(vec![]);
        }
        let Some(binding) = grant_binding(&grant.secrets) else {
            return Ok(vec![]);
        };
        if self
            .checkpoints
            .load(&format!("\0topics/grant-owner/{id}"))?
            != Some(binding)
        {
            return Ok(vec![]);
        }
        Ok(self
            .store
            .connections()?
            .into_iter()
            .find(|c| c.id == id && c.kind == grant.kind)
            .map(|c| c.grants)
            .unwrap_or_default())
    }
    pub(super) fn sign_out(&self, engine: &Engine, id: &str) -> Result<ConnectionInfo> {
        let _lock = self.writes.lock();
        let mut connection = self
            .store
            .connections()?
            .into_iter()
            .find(|c| c.id == id)
            .context("Unknown connection")?;
        let prior = self.store.credential_version(id)?;
        if prior != Some(Uuid::nil()) {
            if connection.kind == "posthog" {
                let binding = self
                    .get(id)
                    .and_then(|a| grant_binding(&a.values))
                    .unwrap_or(Value::Null);
                let key = format!("\0topics/grant-owner/{id}");
                let previous = self.checkpoints.load(&key)?;
                self.checkpoints.commit(&key, previous.as_ref(), &binding)?;
            }
            if let Some(old) = prior {
                self.vault.lock().revoke(id, old)?;
            }
            connection.health = Health::Expired {
                since: Utc::now(),
                detail: "Signed out".into(),
            };
            self.store.put_connection(connection.clone(), Uuid::nil())?;
        }
        self.live.write().remove(id);
        engine.detach_connector(id);
        let info = info(&connection);
        let _ = self.feed.send(info.clone());
        Ok(info)
    }
    pub fn record_unrouted(&self, id: &str) -> Result<()> {
        let _lock = self.writes.lock();
        let current = self.get(id).context("Unknown connection")?;
        let mut public = current.public.clone();
        public.unrouted += 1;
        self.store
            .put_connection(public.clone(), current.version)
            .context("Could not save the connection settings")
            .map_err(meep_engine::Error::from)?;
        self.live.write().insert(
            id.into(),
            Arc::new(Account {
                public: public.clone(),
                ..(*current).clone()
            }),
        );
        let _ = self.feed.send(info(&public));
        Ok(())
    }
    pub fn grant(&self, id: &str, topic: TopicId) -> Result<ConnectionInfo> {
        let _lock = self.writes.lock();
        let current = self.get(id).context("Sign in to this connection first")?;
        let mut public = current.public.clone();
        if !public.grants.contains(&topic) {
            public.grants.push(topic);
            self.store
                .put_connection(public.clone(), current.version)
                .context("Could not save the connection settings")
                .map_err(meep_engine::Error::from)?;
            self.live.write().insert(
                id.into(),
                Arc::new(Account {
                    public: public.clone(),
                    ..(*current).clone()
                }),
            );
            let _ = self.feed.send(info(&public));
        }
        Ok(info(&public))
    }
    pub fn project_for(&self, id: &str, topic: TopicId) -> Result<Arc<Project>> {
        let a = self.get(id).context("PostHog connection unavailable")?;
        ensure!(
            a.public.grants.contains(&topic),
            "This topic has no PostHog grant"
        );
        ensure!(
            a.project_ready.load(Ordering::Acquire),
            "PostHog connection needs attention"
        );
        a.project.clone().context("Connect PostHog to this topic")
    }
    pub fn project(&self, topic: TopicId) -> Result<(String, Arc<Project>)> {
        self.live
            .read()
            .values()
            .find_map(|a| {
                if a.public.grants.contains(&topic) && a.project_ready.load(Ordering::Acquire) {
                    a.project.clone().map(|p| (a.public.id.clone(), p))
                } else {
                    None
                }
            })
            .context("Connect a healthy PostHog account to this topic")
    }
    pub(super) fn source_project(&self, topic: TopicId) -> Result<(String, Arc<Project>)> {
        match self.project(topic) {
            Ok(project) => Ok(project),
            Err(error) => {
                let retryable = self.all().iter().any(|account| {
                    account.public.grants.contains(&topic)
                        && account.project.is_some()
                        && !account.project_ready.load(Ordering::Acquire)
                        && account.project_retryable.load(Ordering::Acquire)
                });
                if retryable {
                    Err(meep_engine::SourceTemporarilyUnavailable.into())
                } else {
                    Err(error)
                }
            }
        }
    }
    pub fn observe(&self, a: &Account, health: Health) -> Result<()> {
        let _lock = self.writes.lock();
        let Some(current) = self.get(&a.public.id).filter(|c| c.version == a.version) else {
            return Ok(());
        };
        let mut public = current.public.clone();
        public.health = health;
        self.store.set_health(&public.id, public.health.clone())?;
        let new = info(&public);
        let changed = new != info(&current.public);
        self.live.write().insert(
            public.id.clone(),
            Arc::new(Account {
                public,
                ..(*current).clone()
            }),
        );
        // Notify after installing, so woken workers see the new health.
        if changed {
            let _ = self.feed.send(new);
        }
        Ok(())
    }
    pub async fn poll(&self, engine: &Engine, a: &Account) -> Result<()> {
        let since = watermark(&a.public.health);
        let checked_at = Utc::now();
        if let Some(project) = &a.project
            && let Err(e) = project.check().await
        {
            a.project_retryable
                .store(project_check_retryable(&e), Ordering::Release);
            a.project_ready.store(false, Ordering::Release);
            if e.downcast_ref::<meep_posthog::api::ApiError>()
                .is_some_and(|e| e.status == 401)
            {
                let Err(refresh) = self.refresh_token(a).await else {
                    return Ok(());
                };
                self.observe(a,Health::Expired{since,detail:"Sign in to PostHog again. The access token expired and OAuth refresh failed.".into()})?;
                return Err(refresh.context("Could not refresh the PostHog connection"));
            } else {
                self.observe(
                    a,
                    Health::Failing {
                        since,
                        detail: "Could not reach the PostHog project with this connection".into(),
                    },
                )?;
            }
            return Err(e.context("PostHog health check failed"));
        }
        if a.project.is_some() {
            a.project_retryable.store(false, Ordering::Release);
            a.project_ready.store(true, Ordering::Release);
        }
        let mut service_error = None;
        if a.public.kind != "webhook" {
            if a.project.is_some() {
                let _guard = engine.connection_guard(&a.public.id).await;
                let Some(current) = self.get(&a.public.id).filter(|c| c.version == a.version)
                else {
                    return Ok(());
                };
                let a = current.as_ref();
                let base: Value = a
                    .values
                    .get("config")
                    .map(|v| serde_json::from_str(v))
                    .transpose()?
                    .unwrap_or_default();
                if let Err(error) =
                    crate::service_watch::poll(engine, a, self.checkpoints.as_ref(), &base).await
                {
                    service_error = Some(error);
                }
                let mut watches = base.get("watches").cloned().unwrap_or_else(|| json!([]));
                merge_watches(engine, &a.public, &mut watches)?;
                if a.config["watches"] != watches {
                    match self.build(a.public.clone(), a.version, a.values.clone(), Some(watches)) {
                        Ok(mut changed) => {
                            changed.project_ready = a.project_ready.clone();
                            changed.project_retryable = a.project_retryable.clone();
                            self.install(engine, changed);
                        }
                        Err(error) => {
                            self.observe(a, Health::Failing { since, detail: "Check the resource IDs and settings for this connection's watches".into() })?;
                            return Err(error);
                        }
                    }
                }
            }
            // Engine replay serializes explicit reconnects with scheduled polls.
            if engine.replay(&a.public.id).await.is_err() {
                let detail = format!(
                    "Could not poll {}. Check its credentials and watch configuration.",
                    a.public.label
                );
                let observed = self
                    .get(&a.public.id)
                    .and_then(|a| a.poller.as_ref().map(|p| p.source.health()));
                let health = match observed {
                    Some(Health::Expired { .. }) => Health::Expired { since, detail },
                    _ => Health::Failing { since, detail },
                };
                self.observe(a, health)?;
                anyhow::bail!("Connector poll failed");
            }
        }
        // A single broken watch should not slow healthy watches or connector replay.
        // Keep the connection unhealthy, but retain its normal polling cadence.
        let connector_health = self.get(&a.public.id).and_then(|account| {
            // An idle PostHog puller has no watches to check and does not poll.
            if account.public.kind == "posthog"
                && account.config["watches"]
                    .as_array()
                    .is_some_and(Vec::is_empty)
            {
                return None;
            }
            account.poller.as_ref().map(|poller| poller.source.health())
        });
        if let Some(error) = service_error {
            log::warn!(
                "Could not poll service watches for {}: {error:#}",
                a.public.id
            );
            self.observe(a, Health::Failing { since, detail: "A connected service watch needs an approved read tool or a working PostHog workflow.".into() })
        } else if let Some(Health::Failing { detail, .. }) = connector_health {
            self.observe(a, Health::Failing { since, detail })
        } else if let Some(Health::Expired { detail, .. }) = connector_health {
            self.observe(a, Health::Expired { since, detail })
        } else {
            self.observe(a, Health::Ok { checked_at })
        }
    }
}

fn project_check_retryable(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<meep_posthog::api::ApiError>()
        .is_none_or(|error| matches!(error.status, 408 | 429) || error.status >= 500)
}

pub(super) fn watermark(health: &Health) -> chrono::DateTime<Utc> {
    match health {
        Health::Ok { checked_at } => *checked_at,
        Health::Failing { since, .. } | Health::Expired { since, .. } => *since,
    }
}

// Push-only sources have no remote history to replay on a Reconnect command.
struct WebhookInbox(String);
#[async_trait::async_trait]
impl meep_ingest::Connector for WebhookInbox {
    fn name(&self) -> &str {
        &self.0
    }
    async fn poll(&self, _: chrono::DateTime<Utc>) -> meep_ingest::Result<Vec<meep_ingest::Event>> {
        Ok(Vec::new())
    }
}

fn grant_binding(values: &Secrets) -> Option<Value> {
    Some(json!([
        values.get("region")?,
        values.get("project_id")?,
        values.get("user_uuid")?.parse::<Uuid>().ok()?
    ]))
}

fn destination(values: &Secrets) -> Result<Value> {
    let config: Option<Value> = values
        .get("config")
        .map(|s| serde_json::from_str(s))
        .transpose()?;
    let config = config.unwrap_or_default();
    Ok(json!([
        values.get("region"),
        config.get("origin"),
        config.get("mcp_endpoint")
    ]))
}

fn merge_watches(engine: &Engine, account: &Connection, subscriptions: &mut Value) -> Result<()> {
    let entries = subscriptions
        .as_array_mut()
        .context("Expected a list of watch subscriptions")?;
    let mut ids: BTreeSet<meep_topic::WatchId> = entries
        .iter()
        .map(|v| serde_json::from_value(v["watch"]["id"].clone()))
        .collect::<std::result::Result<_, _>>()?;
    for topic in &account.grants {
        let watches = match engine.read_topic(*topic, |s| {
            if s.archived || s.deleted {
                return Vec::new();
            }
            s.topic
                .watches()
                .filter(|w| w.connection == account.id)
                .cloned()
                .collect::<Vec<_>>()
        }) {
            Ok(s) => s,
            Err(meep_engine::Error::UnknownTopic(_)) => continue,
            Err(e) => return Err(e.into()),
        };
        for watch in watches {
            if !ids.insert(watch.id) {
                continue;
            }
            entries.push(match watch.kind.as_str() {
                "event" => json!({"watch":watch,"threshold":1,"window_seconds":3600}),
                "flag" | "insight" => json!({"watch":watch}),
                _ => continue,
            });
        }
    }
    Ok(())
}

pub(crate) enum WebhookFailure {
    Unauthorized,
    Payload,
}
impl Account {
    fn decodes_workflow(&self) -> bool {
        self.public.kind == "webhook"
            || self.config["watches"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|w| w["mode"] == "push" || (w["mode"].is_null() && w["workflow"].is_string()))
    }

    /// Remember delivered event ids once the engine has stored them.
    pub fn acknowledge(&self, events: &[meep_ingest::Event]) -> anyhow::Result<()> {
        match &self.poller {
            Some(p) if self.decodes_workflow() => p.source.acknowledge_webhook(events),
            _ => Ok(()),
        }
    }

    pub fn receive(
        &self,
        headers: &HeaderMap,
        body: &[u8],
    ) -> Result<Vec<meep_ingest::Event>, WebhookFailure> {
        if self.decodes_workflow()
            && let Some(p) = &self.poller
        {
            return p.source.receive_webhook(headers, body).map_err(|e| {
                match e.downcast_ref::<WebhookError>() {
                    Some(WebhookError::InvalidPayload(_)) => WebhookFailure::Payload,
                    _ => WebhookFailure::Unauthorized,
                }
            });
        }
        if self.public.kind != "webhook" || self.poller.is_some() {
            return Err(WebhookFailure::Unauthorized);
        }
        let mut header = headers.get_all("x-meep-secret").iter();
        let token = header.next().and_then(|h| h.to_str().ok());
        if !token
            .zip(self.values.get("webhook_secret"))
            .is_some_and(|(a, b)| matches_secret(a, b))
            || header.next().is_some()
        {
            return Err(WebhookFailure::Unauthorized);
        }
        let event: meep_ingest::Event =
            serde_json::from_slice(body).map_err(|_| WebhookFailure::Payload)?;
        if event.connection != self.public.id || event.external_id.is_empty() {
            return Err(WebhookFailure::Payload);
        }
        Ok(vec![event])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_check_retries_transport_rate_limits_and_server_errors_only() {
        let error = |status| {
            anyhow::Error::new(meep_posthog::api::ApiError {
                status,
                code: String::new(),
                detail: String::new(),
            })
        };
        assert!(project_check_retryable(&anyhow::anyhow!(
            "transport unavailable"
        )));
        for status in [408, 429, 500, 503, 504] {
            assert!(project_check_retryable(&error(status)));
        }
        for status in [400, 401, 403, 404] {
            assert!(!project_check_retryable(&error(status)));
        }
    }

    #[tokio::test]
    async fn archived_topic_watches_are_excluded_until_reactivated() -> Result<()> {
        let engine = Engine::in_memory().await?;
        let (topic, _) = engine.create_topic("Archive fixture", "").await?;
        let watch = meep_topic::Watch {
            id: Uuid::new_v4().into(),
            connection: "work".into(),
            kind: "flag".into(),
            key: "42".into(),
            label: "Fixture flag".into(),
        };
        engine.set_watch(topic, vec![watch.clone()]).await?;
        let account = Connection {
            unrouted: 0,
            id: "work".into(),
            kind: "posthog".into(),
            label: "Work".into(),
            account: String::new(),
            health: Health::Ok {
                checked_at: Utc::now(),
            },
            grants: vec![topic],
        };
        let watches = || -> Result<Value> {
            let mut value = json!([]);
            merge_watches(&engine, &account, &mut value)?;
            Ok(value)
        };
        assert_eq!(watches()?.as_array().unwrap().len(), 1);
        let command = |command| meep_topic::Envelope {
            id: Uuid::new_v4().into(),
            topic,
            issued_at: Utc::now(),
            command,
        };
        engine
            .apply(command(meep_topic::Command::ArchiveTopic))
            .await?;
        assert!(watches()?.as_array().unwrap().is_empty());
        engine
            .apply(command(meep_topic::Command::UnarchiveTopic))
            .await?;
        assert_eq!(watches()?[0]["watch"]["id"], json!(watch.id));
        Ok(())
    }

    #[tokio::test]
    async fn passive_context_does_not_create_posthog_poll_subscriptions() -> Result<()> {
        let engine = Engine::in_memory().await?;
        let (topic, _) = engine.create_topic("Passive", "").await?;
        let source = meep_topic::Watch {
            id: Uuid::new_v4().into(),
            connection: "work".into(),
            kind: "flag".into(),
            key: "42".into(),
            label: "Flag".into(),
        };
        engine
            .apply(meep_topic::Envelope {
                id: Uuid::new_v4().into(),
                topic,
                issued_at: Utc::now(),
                command: meep_topic::Command::AddContextSource {
                    source: source.clone(),
                },
            })
            .await?;
        let account = Connection {
            unrouted: 0,
            id: "work".into(),
            kind: "posthog".into(),
            label: "Work".into(),
            account: String::new(),
            health: Health::Ok {
                checked_at: Utc::now(),
            },
            grants: vec![topic],
        };
        let mut subscriptions = json!([]);
        merge_watches(&engine, &account, &mut subscriptions)?;
        assert_eq!(subscriptions, json!([]));
        engine.set_watch(topic, vec![source.clone()]).await?;
        merge_watches(&engine, &account, &mut subscriptions)?;
        assert_eq!(subscriptions[0]["watch"]["id"], json!(source.id));
        Ok(())
    }

    #[test]
    fn only_plain_webhook_accounts_accept_legacy_raw_events() -> Result<()> {
        let mut a = Account {
            refresh_lock: Default::default(),
            public: Connection {
                unrouted: 0,
                id: "build".into(),
                kind: "webhook".into(),
                label: "Build".into(),
                account: String::new(),
                health: Health::Ok {
                    checked_at: Utc::now(),
                },
                grants: vec![],
            },
            version: Uuid::new_v4(),
            values: [("webhook_secret".into(), "fixture".into())].into(),
            project: None,
            project_ready: Arc::new(AtomicBool::new(false)),
            project_retryable: Arc::new(AtomicBool::new(false)),
            poller: None,
            interval: std::time::Duration::from_secs(30),
            config: json!({}),
        };
        let body = serde_json::to_vec(
            &json!({"connection":"build","kind":"channel","channel":"a","external_id":"one","at":Utc::now(),"author":"fixture","text":"ready","attributes":null}),
        )?;
        let mut headers = HeaderMap::new();
        headers.insert("x-meep-secret", "fixture".parse()?);
        assert!(a.receive(&headers, &body).is_ok());
        a.public.kind = "mcp".into();
        assert!(matches!(
            a.receive(&headers, &body),
            Err(WebhookFailure::Unauthorized)
        ));
        Ok(())
    }
}
