#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use meep_store::Connection;
use meep_topic::{Message, MessageId, Origin, Producer, RoutineBinding, TopicId, Watch, WatchId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashSet, str::FromStr};

/// Failure to identify, poll or persist an incoming event.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// An inter-topic message named an invalid sending topic.
    #[error("invalid sending topic ID")]
    InvalidSendingTopic(#[source] <TopicId as FromStr>::Err),
    /// The store could not read or commit a delivery receipt.
    #[error(transparent)]
    Storage(Box<dyn std::error::Error + Send + Sync>),
    /// The host's connector failed to poll the account.
    #[error(transparent)]
    Connector(Box<dyn std::error::Error + Send + Sync>),
}

/// Result of polling a connector or recording a delivery.
pub type Result<T> = std::result::Result<T, Error>;

fn storage(error: impl Into<Box<dyn std::error::Error + Send + Sync>>) -> Error {
    Error::Storage(error.into())
}

/// One observation from a connector, before delivery to watching topics.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Event {
    /// Account ID, or the reserved origin `topic` or `user`.
    pub connection: String,
    /// Resource kind, such as `channel` or `label`.
    pub kind: String,
    /// Stable ID at this connection, shared across replays.
    pub external_id: String,
    /// Resource key matched against a watch. For topic delivery this is the sending topic ID.
    pub channel: String,
    /// Service-supplied conversation key.
    pub thread_hint: Option<String>,
    /// Sender's display name.
    pub author: String,
    /// Timestamp at the source.
    pub at: DateTime<Utc>,
    /// Message body.
    pub text: String,
    /// Service-specific sorting context.
    pub attributes: Value,
}

impl Event {
    /// Whether the connection, resource kind and channel match the subscription.
    pub fn matches_watch(&self, watch: &Watch) -> bool {
        watch.connection == self.connection && watch.kind == self.kind && watch.key == self.channel
    }

    /// Builds an inbox message, retaining source identity and the original timestamp.
    pub fn message(&self, id: MessageId) -> Result<Message> {
        let producer = if self.connection == "user" {
            Producer::User
        } else {
            Producer::System
        };
        self.message_for(id, producer)
    }

    /// Source identity shared by messages and routine observations.
    pub fn origin(&self) -> Origin {
        Origin {
            connection: self.connection.clone(),
            channel: self.channel.clone(),
            external_id: Some(self.external_id.clone()),
            thread_hint: self.thread_hint.clone(),
            author: self.author.clone(),
            at: self.at,
        }
    }

    /// Builds a message for a specific producer, retaining the observed event.
    pub fn message_for(&self, id: MessageId, producer: Producer) -> Result<Message> {
        if self.connection == "topic" {
            self.channel
                .parse::<TopicId>()
                .map_err(Error::InvalidSendingTopic)?;
        }
        Ok(Message {
            id,
            producer,
            origin: Some(self.origin()),
            author: self.author.clone(),
            at: self.at,
            text: self.text.clone(),
            external_id: Some(self.external_id.clone()),
        })
    }
}

/// Returns the provider's explicit conversation key when one exists.
pub fn group_key(event: &Event) -> Option<&str> {
    event.thread_hint.as_deref().filter(|key| !key.is_empty())
}

/// Select each matching (topic, routine) once in supplied order.
pub fn route(event: &Event, bindings: &[(TopicId, RoutineBinding)]) -> Vec<(TopicId, String)> {
    route_bindings(
        event,
        bindings.iter().map(|(topic, binding)| (*topic, binding)),
    )
}

/// Route borrowed bindings without copying their watch lists.
pub fn route_bindings<'a>(
    event: &Event,
    bindings: impl IntoIterator<Item = (TopicId, &'a RoutineBinding)>,
) -> Vec<(TopicId, String)> {
    let mut selected = HashSet::new();
    bindings
        .into_iter()
        .filter(|(topic, binding)| {
            binding
                .watches
                .iter()
                .any(|watch| event.matches_watch(watch))
                && selected.insert((*topic, &binding.id))
        })
        .map(|(topic, binding)| (topic, binding.id.clone()))
        .collect()
}

/// Durable or transient set of delivered connector identities.
pub trait SeenStore: Send {
    /// Checks a key without changing it.
    fn contains(&self, connection: &str, external_id: &str) -> Result<bool>;
    /// Atomically inserts a key, returning true only for the first insertion.
    fn insert(&mut self, connection: &str, external_id: &str) -> Result<bool>;
}

/// An isolated, in-memory set of delivered events.
#[derive(Default)]
pub struct MemorySeenStore(HashSet<(String, String)>);
impl SeenStore for MemorySeenStore {
    fn contains(&self, connection: &str, external_id: &str) -> Result<bool> {
        Ok(self.0.contains(&(connection.into(), external_id.into())))
    }
    fn insert(&mut self, connection: &str, external_id: &str) -> Result<bool> {
        Ok(self.0.insert((connection.into(), external_id.into())))
    }
}

/// A meep-store set, surviving a restart when given a file-backed database.
pub struct StoreSeenStore(Connection);
impl StoreSeenStore {
    /// Initializes the records table on the host's database.
    pub fn new(db: Connection) -> Result<Self> {
        meep_store::initialize(&db).map_err(storage)?;
        Ok(Self(db))
    }
}
impl SeenStore for StoreSeenStore {
    fn contains(&self, connection: &str, external_id: &str) -> Result<bool> {
        Ok(
            meep_store::get::<bool>(&self.0, &format!("ingest/seen/{connection}"), external_id)
                .map_err(storage)?
                .is_some(),
        )
    }
    fn insert(&mut self, connection: &str, external_id: &str) -> Result<bool> {
        let kind = format!("ingest/seen/{connection}");
        meep_store::transaction(&mut self.0, |db| {
            if meep_store::get::<bool>(db, &kind, external_id)?.is_some() {
                return Ok(false);
            }
            meep_store::put(db, &kind, external_id, &true)?;
            Ok(true)
        })
        .map_err(storage)
    }
}

/// Checks and records delivered events by connection and external ID.
pub struct Deduper<S = MemorySeenStore>(S);
impl<S: SeenStore> Deduper<S> {
    /// Uses a host-selected seen store.
    pub fn new(store: S) -> Self {
        Self(store)
    }
    /// Whether this event has already been delivered.
    pub fn seen(&self, event: &Event) -> Result<bool> {
        self.0.contains(&event.connection, &event.external_id)
    }
    /// Marks delivery complete. Returns false for a duplicate.
    pub fn record(&mut self, event: &Event) -> Result<bool> {
        self.0.insert(&event.connection, &event.external_id)
    }
}

/// A connector observation with an optional specific subscription destination.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RoutedEvent {
    /// Original connector observation.
    pub event: Event,
    /// Restrict delivery to this watch; absent preserves ordinary fan-out.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub watch: Option<WatchId>,
}

/// Pollable source of connector observations. Polling is replayable.
#[async_trait]
pub trait Connector: Send + Sync {
    /// Stable connection ID.
    fn name(&self) -> &str;
    /// Returns observations at or after an inclusive watermark in chronological order.
    async fn poll(&self, since: DateTime<Utc>) -> Result<Vec<Event>>;
    /// Poll with optional subscription-specific routing; existing connectors fan out.
    async fn poll_routed(&self, since: DateTime<Utc>) -> Result<Vec<RoutedEvent>> {
        Ok(self
            .poll(since)
            .await?
            .into_iter()
            .map(|event| RoutedEvent { event, watch: None })
            .collect())
    }
}

#[cfg(feature = "fixtures")]
/// A replayable time-ordered event list for one connection.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FixtureConnector {
    name: String,
    events: Vec<Event>,
}
#[cfg(feature = "fixtures")]
impl FixtureConnector {
    /// Selects events for this account and orders them by source time.
    pub fn new(name: impl Into<String>, mut events: Vec<Event>) -> Self {
        let name = name.into();
        events.retain(|e| e.connection == name);
        events.sort_by_key(|e| e.at);
        Self { name, events }
    }
}
#[cfg(feature = "fixtures")]
#[async_trait]
impl Connector for FixtureConnector {
    fn name(&self) -> &str {
        &self.name
    }
    async fn poll(&self, since: DateTime<Utc>) -> Result<Vec<Event>> {
        Ok(self
            .events
            .iter()
            .filter(|e| e.at >= since)
            .cloned()
            .collect())
    }
}

#[cfg(test)]
mod tests;
