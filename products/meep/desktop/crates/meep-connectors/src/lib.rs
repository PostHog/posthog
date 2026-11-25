#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

mod mapping;
mod mcp;
mod mode;
mod posthog;
mod state;
mod webhook;

use anyhow::{Context, Result, ensure};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use http::HeaderMap;
use meep_connections::Health;
use meep_ingest::{Connector, Event, RoutedEvent};
use meep_posthog::api::ApiError;
use meep_topic::{Watch, WatchId};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;

pub use mode::{WatchMode, supported_modes};
pub use state::{StateStore, StoreState};
pub use webhook::WebhookError;

type ValidateSecret<'a> = dyn Fn(&str) -> Result<String> + 'a;

/// An account's poller and its latest service observation.
pub trait LiveConnector: Connector {
    /// Condition of the last poll or webhook delivery.
    fn health(&self) -> Health;

    /// Authenticate the original HTTP bytes, then map a webhook delivery to events.
    /// The host delivers the returned batch to the engine before acknowledging the request.
    fn receive_webhook(&self, headers: &HeaderMap, body: &[u8]) -> Result<Vec<Event>>;

    /// Remember successfully ingested event IDs. A failed delivery remains retryable.
    fn acknowledge_webhook(&self, _events: &[Event]) -> Result<()> {
        Ok(())
    }
}

/// Builds live sources using the same durable checkpoint store across restarts.
pub struct ConnectorFactory {
    state: Arc<dyn StateStore>,
}

impl ConnectorFactory {
    /// Use a host-provided checkpoint store.
    pub fn new(state: Arc<dyn StateStore>) -> Self {
        Self { state }
    }

    /// Build a `posthog`, `mcp` or `webhook` account from JSON and its named secrets.
    pub fn build(
        &self,
        kind: &str,
        config: Value,
        secrets: &BTreeMap<String, String>,
    ) -> Result<Box<dyn LiveConnector>> {
        let connection = config["connection"]
            .as_str()
            .context("missing connection ID")?
            .to_owned();
        ensure!(
            !connection.trim().is_empty()
                && !connection.contains('\0')
                && !matches!(connection.as_str(), "topic" | "user"),
            "invalid connection ID"
        );
        let secret = |name: &str| {
            secrets
                .get(name)
                .filter(|s| !s.trim().is_empty())
                .cloned()
                .with_context(|| format!("missing {name} secret"))
        };
        let plan = mode::plan(kind, config, &secret)?;
        let source = match plan.pull {
            Some(config) if kind == "posthog" => Some(Source::PostHog(Box::new(
                posthog::PostHog::new(config, secret("token")?)?,
            ))),
            Some(config) => Some(Source::Mcp(Box::new(mcp::Mcp::new(
                config,
                secret("token")?,
            )?))),
            None => None,
        };
        let now = Utc::now();
        let health = if source.is_none() {
            Health::Ok { checked_at: now }
        } else {
            Health::Failing {
                since: now,
                detail: format!("Waiting for first poll of {connection}"),
            }
        };
        Ok(Box::new(Account {
            connection,
            source,
            webhook: plan.webhook,
            state: self.state.clone(),
            polling: Default::default(),
            health: Mutex::new(health),
        }))
    }
}

enum Source {
    PostHog(Box<posthog::PostHog>),
    Mcp(Box<mcp::Mcp>),
}

struct Account {
    connection: String,
    source: Option<Source>,
    webhook: Option<webhook::Webhook>,
    state: Arc<dyn StateStore>,
    polling: Arc<tokio::sync::Mutex<()>>,
    health: Mutex<Health>,
}

#[derive(Default, Serialize, Deserialize)]
struct Checkpoint {
    observations: BTreeMap<WatchId, Observation>,
}

#[derive(Clone, Serialize, Deserialize)]
struct Observation {
    source: String,
    value: Value,
}

impl Checkpoint {
    fn value(&self, watch: WatchId, source: &str) -> Option<&Value> {
        self.observations
            .get(&watch)
            .filter(|o| o.source == source)
            .map(|o| &o.value)
    }

    fn record(&mut self, watch: WatchId, source: String, value: Value) {
        self.observations
            .insert(watch, Observation { source, value });
    }
}

// Identify the watched resource without persisting tool arguments or credentials.
fn source_key(source: impl Serialize) -> Result<String> {
    use sha2::{Digest, Sha256};
    Ok(hex::encode(Sha256::digest(serde_json::to_vec(&source)?)))
}

impl Account {
    async fn poll_account(
        &self,
        since: DateTime<Utc>,
    ) -> Result<(Vec<RoutedEvent>, Option<anyhow::Error>)> {
        let Some(source) = &self.source else {
            return Ok((Vec::new(), None));
        };
        let guard = self.polling.clone().lock_owned().await;
        let store = self.state.clone();
        let connection = self.connection.clone();
        let old = tokio::task::spawn_blocking(move || store.load(&connection)).await??;
        let previous: Checkpoint = old
            .as_ref()
            .map(|v| serde_json::from_value(v.clone()))
            .transpose()?
            .unwrap_or_default();
        let mut checkpoint = Checkpoint::default();
        let (mut events, warning) = match source {
            Source::PostHog(source) => source.poll(&previous, &mut checkpoint).await?,
            Source::Mcp(source) => (
                source
                    .poll(&previous, &mut checkpoint, since)
                    .await?
                    .into_iter()
                    .map(|event| RoutedEvent { event, watch: None })
                    .collect(),
                None,
            ),
        };
        let store = self.state.clone();
        let connection = self.connection.clone();
        tokio::task::spawn_blocking(move || {
            let _guard = guard;
            store.commit(
                &connection,
                old.as_ref(),
                &serde_json::to_value(checkpoint)?,
            )
        })
        .await??;
        events.retain(|e| e.event.at >= since);
        events.sort_by_key(|e| e.event.at);
        Ok((events, warning))
    }

    fn decode_webhook(&self, headers: &HeaderMap, body: &[u8]) -> Result<Vec<Event>> {
        let webhook = self
            .webhook
            .as_ref()
            .with_context(|| format!("{} has no workflow webhook configured", self.connection))?;
        let mut ids = HashSet::new();
        let mut events = vec![];
        for event in webhook.receive(headers, body)? {
            if ids.insert(event.external_id.clone())
                && !self
                    .state
                    .webhook_delivered(&self.connection, &event.external_id)?
            {
                events.push(event);
            }
        }
        events.sort_by_key(|e| e.at);
        Ok(events)
    }

    fn observe<T>(&self, result: Result<T>) -> Result<T> {
        let mut health = self.health.lock();
        let now = Utc::now();
        match &result {
            Ok(_) => *health = Health::Ok { checked_at: now },
            Err(err) => {
                let detail = format!("Can't see {}: {err:#}", self.connection);
                if err
                    .downcast_ref::<ApiError>()
                    .is_some_and(|e| e.status == 401)
                {
                    let since = match *health {
                        Health::Expired { since, .. } => since,
                        _ => now,
                    };
                    *health = Health::Expired { since, detail };
                } else {
                    let since = match *health {
                        Health::Failing { since, .. } => since,
                        _ => now,
                    };
                    *health = Health::Failing { since, detail };
                }
            }
        }
        result.with_context(|| health.summary().to_owned())
    }
}

#[async_trait]
impl Connector for Account {
    fn name(&self) -> &str {
        &self.connection
    }
    async fn poll(&self, since: DateTime<Utc>) -> meep_ingest::Result<Vec<Event>> {
        Ok(self
            .poll_routed(since)
            .await?
            .into_iter()
            .map(|r| r.event)
            .collect())
    }
    async fn poll_routed(&self, since: DateTime<Utc>) -> meep_ingest::Result<Vec<RoutedEvent>> {
        if self.source.is_none() {
            return Ok(Vec::new());
        }
        match self.poll_account(since).await {
            Ok((events, Some(warning))) => {
                // A partial poll still delivers its durable successful batch, while
                // exposing the failed watches to the host through health().
                let _ = self.observe::<()>(Err(warning));
                Ok(events)
            }
            Ok((events, None)) => self
                .observe(Ok(events))
                .map_err(|error| meep_ingest::Error::Connector(error.into())),
            Err(error) => self
                .observe(Err(error))
                .map_err(|error| meep_ingest::Error::Connector(error.into())),
        }
    }
}

impl LiveConnector for Account {
    fn health(&self) -> Health {
        self.health.lock().clone()
    }
    fn receive_webhook(&self, headers: &HeaderMap, body: &[u8]) -> Result<Vec<Event>> {
        let result = self.decode_webhook(headers, body);
        // A successful inbound delivery does not verify the token of a separate MCP poller.
        if self.source.is_some() {
            result
        } else {
            self.observe(result)
        }
    }

    fn acknowledge_webhook(&self, events: &[Event]) -> Result<()> {
        ensure!(
            events.iter().all(|e| e.connection == self.connection),
            "cannot acknowledge another connection's delivery"
        );
        for event in events {
            self.state
                .mark_webhook_delivered(&self.connection, &event.external_id)?;
        }
        Ok(())
    }
}

fn validate_watches<'a>(
    connection: &str,
    watches: impl IntoIterator<Item = &'a Watch>,
) -> Result<()> {
    let mut ids = HashSet::new();
    for watch in watches {
        ensure!(
            watch.connection == connection,
            "watch {} belongs to a different connection",
            watch.id
        );
        ensure!(
            !watch.kind.trim().is_empty() && !watch.key.trim().is_empty(),
            "empty watch kind or key"
        );
        ensure!(ids.insert(watch.id), "duplicate watch {}", watch.id);
    }
    Ok(())
}
