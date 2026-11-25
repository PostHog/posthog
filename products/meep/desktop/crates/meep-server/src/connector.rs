use crate::vault::Secrets;
use anyhow::{Context, Result, ensure};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use meep_connectors::{LiveConnector, StateStore};
use meep_engine::Store;
use meep_ingest::{Connector, Event, RoutedEvent};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashSet, sync::Arc};

/// Builds connector-specific pollers and webhook decoders for a registered connection.
pub trait ConnectorFactory: Send + Sync {
    /// Build an adapter from its kind, configuration, secrets and durable checkpoint store.
    fn build(
        &self,
        kind: &str,
        config: Value,
        secrets: &std::collections::BTreeMap<String, String>,
        state: Arc<dyn StateStore>,
    ) -> Result<Box<dyn LiveConnector>>;
}

/// Production factory for the connectors supplied by meep-connectors.
pub struct Connectors;
impl ConnectorFactory for Connectors {
    fn build(
        &self,
        kind: &str,
        config: Value,
        secrets: &Secrets,
        state: Arc<dyn StateStore>,
    ) -> Result<Box<dyn LiveConnector>> {
        meep_connectors::ConnectorFactory::new(state).build(kind, config, secrets)
    }
}

#[derive(Default, Serialize, Deserialize)]
struct Delivery {
    checkpoint: Option<Value>,
    pending: Vec<RoutedEvent>,
}

struct Journal {
    durable: Arc<dyn StateStore>,
    staged: Mutex<Option<Value>>,
}
impl StateStore for Journal {
    fn load(&self, id: &str) -> Result<Option<Value>> {
        Ok(self.delivery(id)?.1.checkpoint)
    }
    fn webhook_delivered(&self, connection: &str, event: &str) -> Result<bool> {
        self.durable.webhook_delivered(connection, event)
    }
    fn mark_webhook_delivered(&self, connection: &str, event: &str) -> Result<()> {
        self.durable.mark_webhook_delivered(connection, event)
    }
    fn commit(&self, id: &str, expected: Option<&Value>, next: &Value) -> Result<()> {
        ensure!(
            self.load(id)?.as_ref() == expected,
            "Concurrent connector checkpoint"
        );
        *self.staged.lock() = Some(next.clone());
        Ok(())
    }
}
impl Journal {
    fn delivery(&self, id: &str) -> Result<(Option<Value>, Delivery)> {
        let old = self.durable.load(id)?;
        let batch: Delivery = old
            .clone()
            .map(serde_json::from_value)
            .transpose()?
            .unwrap_or_default();
        Ok((old, batch))
    }
}

pub(crate) struct Poller {
    pub source: Box<dyn LiveConnector>,
    idle: bool,
    store: Arc<dyn Store>,
    journal: Arc<Journal>,
    poll_lock: Arc<tokio::sync::Mutex<()>>,
}

impl Poller {
    pub fn new(
        factory: &dyn ConnectorFactory,
        kind: &str,
        config: Value,
        secrets: &Secrets,
        checkpoints: Arc<dyn StateStore>,
        store: Arc<dyn Store>,
    ) -> Result<Self> {
        let journal = Arc::new(Journal {
            durable: checkpoints,
            staged: Default::default(),
        });
        Ok(Self {
            idle: kind == "posthog" && config["watches"].as_array().is_some_and(Vec::is_empty),
            source: factory.build(kind, config, secrets, journal.clone())?,
            journal,
            store,
            poll_lock: Default::default(),
        })
    }
    async fn pending_events(&self, since: DateTime<Utc>) -> Result<Vec<RoutedEvent>> {
        let guard = self.poll_lock.clone().lock_owned().await;
        let id = self.name().to_owned();
        let journal = self.journal.clone();
        let store = self.store.clone();
        let (old, mut batch) = tokio::task::spawn_blocking(move || -> Result<_> {
            let (old, mut batch) = journal.delivery(&id)?;
            let mut pending = Vec::with_capacity(batch.pending.len());
            for routed in batch.pending {
                if !store.seen(&id, &routed.event.external_id)? {
                    pending.push(routed);
                }
            }
            batch.pending = pending;
            Ok((old, batch))
        })
        .await??;
        // Retain unrouted events, but do not let an old unmatched watch stop new
        // polls. The durable batch remains replayable when a binding reappears.
        if self.idle {
            return Ok(batch.pending);
        }
        self.journal.staged.lock().take();
        let events = self
            .source
            .poll_routed(since)
            .await
            .map_err(|_| anyhow::anyhow!("Could not poll the configured service"))?;
        ensure!(
            events.iter().all(|e| e.event.connection == self.name()),
            "Connector returned another account's events"
        );
        if let Some(next) = self.journal.staged.lock().take() {
            batch.checkpoint = Some(next);
        }
        let mut ids: HashSet<_> = batch
            .pending
            .iter()
            .map(|e| e.event.external_id.clone())
            .collect();
        for routed in events {
            if ids.insert(routed.event.external_id.clone()) {
                batch.pending.push(routed);
            }
        }
        let id = self.name().to_owned();
        let journal = self.journal.clone();
        tokio::task::spawn_blocking(move || {
            let _guard = guard;
            let next = serde_json::to_value(&batch)?;
            if old.as_ref() != Some(&next) {
                journal
                    .durable
                    .commit(&id, old.as_ref(), &next)
                    .context("Saving pending connector deliveries")?;
            }
            Ok(batch.pending)
        })
        .await?
    }
}
#[async_trait]
impl Connector for Poller {
    fn name(&self) -> &str {
        self.source.name()
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
        self.pending_events(since)
            .await
            .map_err(|error| meep_ingest::Error::Connector(error.into()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;
    use meep_connections::Health;
    use meep_connectors::StoreState;
    use meep_engine::MemoryStore;
    use serde_json::json;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    struct Source {
        calls: Arc<AtomicUsize>,
        failing: Arc<AtomicBool>,
        target: Option<meep_topic::WatchId>,
        state: Arc<dyn StateStore>,
    }
    #[async_trait]
    impl Connector for Source {
        fn name(&self) -> &str {
            "usage"
        }
        async fn poll(&self, since: DateTime<Utc>) -> meep_ingest::Result<Vec<Event>> {
            if self.failing.load(Ordering::SeqCst) {
                return Err(meep_ingest::Error::Connector(
                    anyhow::anyhow!("offline").into(),
                ));
            }
            let next = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
            let storage = |error: anyhow::Error| meep_ingest::Error::Storage(error.into());
            self.state
                .commit(
                    self.name(),
                    self.state.load(self.name()).map_err(storage)?.as_ref(),
                    &json!(next),
                )
                .map_err(storage)?;
            Ok((0..2)
                .map(|i| Event {
                    connection: self.name().into(),
                    kind: "event".into(),
                    channel: "count".into(),
                    external_id: if next == 2 && i == 0 {
                        "1/1".into()
                    } else {
                        format!("{next}/{i}")
                    },
                    author: "Analytics".into(),
                    text: "Changed".into(),
                    at: since,
                    thread_hint: None,
                    attributes: Value::Null,
                })
                .collect())
        }
    }
    #[async_trait]
    impl Connector for TargetedSource {
        fn name(&self) -> &str {
            self.0.name()
        }
        async fn poll(&self, since: DateTime<Utc>) -> meep_ingest::Result<Vec<Event>> {
            self.0.poll(since).await
        }
        async fn poll_routed(&self, since: DateTime<Utc>) -> meep_ingest::Result<Vec<RoutedEvent>> {
            Ok(self
                .0
                .poll(since)
                .await?
                .into_iter()
                .map(|event| RoutedEvent {
                    event,
                    watch: self.0.target,
                })
                .collect())
        }
    }
    struct TargetedSource(Source);
    impl LiveConnector for TargetedSource {
        fn health(&self) -> Health {
            self.0.health()
        }
        fn receive_webhook(&self, h: &HeaderMap, b: &[u8]) -> Result<Vec<Event>> {
            self.0.receive_webhook(h, b)
        }
    }
    impl LiveConnector for Source {
        fn health(&self) -> Health {
            Health::Ok {
                checked_at: Utc::now(),
            }
        }
        fn receive_webhook(&self, _: &HeaderMap, _: &[u8]) -> Result<Vec<Event>> {
            anyhow::bail!("poll only")
        }
    }
    struct Factory(
        Arc<AtomicUsize>,
        Arc<AtomicBool>,
        Option<meep_topic::WatchId>,
    );
    impl ConnectorFactory for Factory {
        fn build(
            &self,
            _: &str,
            _: Value,
            _: &Secrets,
            state: Arc<dyn StateStore>,
        ) -> Result<Box<dyn LiveConnector>> {
            Ok(Box::new(TargetedSource(Source {
                calls: self.0.clone(),
                failing: self.1.clone(),
                target: self.2,
                state,
            })))
        }
    }

    #[tokio::test]
    async fn unmatched_events_survive_new_polls_and_restart_until_recorded() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let store = Arc::new(MemoryStore::default());
        let calls = Arc::new(AtomicUsize::default());
        let failing = Arc::new(AtomicBool::new(false));
        let factory = Factory(calls.clone(), failing.clone(), None);
        let open = || {
            let checkpoints = StoreState::new(meep_store::Connection::open(
                dir.path().join("connector.sqlite"),
            )?)?;
            Poller::new(
                &factory,
                "usage",
                Value::Null,
                &Secrets::new(),
                Arc::new(checkpoints),
                store.clone(),
            )
        };
        let first = open()?.poll(Utc::now()).await?;
        store.record_seen("usage", &first[0].external_id)?;
        let resumed = open()?;
        let next = resumed.poll(Utc::now()).await?;
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert!(!next.iter().any(|e| e.external_id == first[0].external_id));
        assert_eq!(
            next.iter()
                .filter(|e| e.external_id == first[1].external_id)
                .count(),
            1
        );
        assert_eq!(next.len(), 2);
        failing.store(true, Ordering::SeqCst);
        assert!(resumed.poll(Utc::now()).await.is_err());
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        drop(resumed);
        failing.store(false, Ordering::SeqCst);
        let reopened = open()?;
        let replayed = reopened.poll(Utc::now()).await?;
        assert_eq!(calls.load(Ordering::SeqCst), 3);
        assert_eq!(
            replayed
                .iter()
                .filter(|e| e.external_id == first[1].external_id)
                .count(),
            1
        );
        // An absent binding leaves the event unrouted; adding it later accepts
        // the exact same pending event and deduplicates repeated delivery.
        let engine = meep_engine::Engine::in_memory().await?;
        let (topic, _) = engine.create_topic("Pending fixture", "").await?;
        assert!(!engine.ingest_routed(first[1].clone()).await?.1);
        engine
            .set_watch(
                topic,
                vec![meep_topic::Watch {
                    id: uuid::Uuid::new_v4().into(),
                    connection: "usage".into(),
                    kind: "event".into(),
                    key: "count".into(),
                    label: "Count".into(),
                }],
            )
            .await?;
        assert!(engine.ingest_routed(first[1].clone()).await?.1);
        assert!(engine.ingest_routed(first[1].clone()).await?.1);
        assert_eq!(engine.source_observations(topic, 10)?.len(), 1);
        store.record_seen("usage", &first[1].external_id)?;
        let accepted = reopened.poll(Utc::now()).await?;
        assert!(
            !accepted
                .iter()
                .any(|e| e.external_id == first[1].external_id)
        );
        assert_eq!(calls.load(Ordering::SeqCst), 4);
        Ok(())
    }
    #[tokio::test]
    async fn journal_preserves_targeted_events_across_restart() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let store = Arc::new(MemoryStore::default());
        let target = uuid::Uuid::new_v4().into();
        let factory = Factory(
            Arc::new(AtomicUsize::default()),
            Arc::new(AtomicBool::new(false)),
            Some(target),
        );
        let open = || -> Result<Poller> {
            let checkpoints = StoreState::new(meep_store::Connection::open(
                dir.path().join("connector.sqlite"),
            )?)?;
            Poller::new(
                &factory,
                "usage",
                Value::Null,
                &Secrets::new(),
                Arc::new(checkpoints),
                store.clone(),
            )
        };
        let first = open()?.poll_routed(Utc::now()).await?;
        assert!(first.iter().all(|e| e.watch == Some(target)));
        let reopened = open()?;
        let next = reopened.poll_routed(Utc::now()).await?;
        for old in &first {
            assert!(
                next.iter().any(
                    |e| e.event.external_id == old.event.external_id && e.watch == Some(target)
                )
            );
        }
        Ok(())
    }
}
