#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

mod agent;
mod backend;
mod blobs;
mod clock;
mod commands;
mod delivery;
mod effects;
pub use effects::WorkflowReview;
mod event_routines;
mod files;
#[cfg(test)]
mod fixture_flows;
mod intake;
mod memory;
mod observations;
mod store;
pub use backend::*;
pub use blobs::*;
pub use store::*;
mod replication;
mod routines;
mod session;
mod setup;
pub use routines::{RoutineAsk, RoutineOp, RoutineReports, RoutineSortContext};
pub use setup::SETUP_TITLE;
mod sorter;
mod worker;

pub use agent::*;
pub use clock::*;
pub use sorter::*;

use anyhow::Context;
use chrono::{DateTime, Utc};
use meep_connections::{Connection, Health, Registry};
use meep_ingest::Connector;
use meep_policy::{Limits, RunWindow};

use meep_topic::*;
use parking_lot::{Mutex, RwLock};
use routines::{Causality, Routine};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    path::Path,
    sync::{Arc, Weak},
};
use thiserror::Error;
use tokio::sync::{Mutex as AsyncMutex, broadcast};
use tokio_util::{
    sync::{CancellationToken, DropGuard},
    task::TaskTracker,
};
use uuid::Uuid;

pub use meep_wire::{Applied, TopicRevision, TopicSnapshot};

/// Command, integration or persistence failure.
#[derive(Debug, Error)]
pub enum Error {
    /// The supplied observation is unavailable to this callback.
    #[error("Unknown, consumed or foreign observation {0}")]
    UnavailableObservation(Uuid),
    /// A callback supplied the wrong binding secret.
    #[error("invalid callback secret for routine {0}")]
    InvalidRoutineSecret(String),
    /// No routine has this key in the requested topic.
    #[error("unknown routine {0}")]
    UnknownRoutine(String),
    /// A command supplied an invalid routine definition or backend.
    #[error("invalid routine binding: {0}")]
    InvalidBinding(String),
    /// A command ID was reused for a different topic or operation.
    #[error("command {0} was already used for a different command")]
    CommandCollision(CommandId),
    /// The topic does not exist.
    #[error("unknown topic {0}")]
    UnknownTopic(TopicId),
    /// The connection or its live connector is unknown.
    #[error("unknown connection or connector {0}")]
    UnknownConnection(String),
    /// Delivery exceeded the configured hop budget.
    #[error("inter-topic hop limit exceeded at hop {0}")]
    HopLimit(u32),
    /// The domain rejected a state transition.
    #[error(transparent)]
    Topic(#[from] TopicError),
    /// Polling a connector or decoding its source identity failed.
    #[error(transparent)]
    Ingest(#[from] meep_ingest::Error),
    /// Serialization failed for a stored record or provider token.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// An operation failed in storage, the sorter, an agent or a workflow.
    #[error(transparent)]
    Integration(#[from] anyhow::Error),
}

/// Result of a topic runtime operation.
pub type Result<T> = std::result::Result<T, Error>;

/// An engine notification scoped to its owning topic.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EngineEvent {
    /// Topic that a host should refresh.
    pub topic: TopicId,
    /// Authoritative topic revision at publication.
    pub revision: u64,
    /// Domain mutation or runtime observation.
    pub change: EngineChange,
}

/// A persisted domain change or an observation from a worker or connector.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum EngineChange {
    /// Public state advanced without a granular domain change.
    Revised,
    /// One domain change, in the model's sequence order.
    Change(Change),
    /// Observed health of a connection used by this topic.
    ConnectionHealth {
        /// Account ID.
        connection: String,
        /// Latest health.
        health: Health,
    },
    /// A workflow ended with an error.
    RoutineFailed {
        /// Workflow ID.
        routine: String,
        /// Runner's diagnostic.
        error: String,
    },
    /// A routine's notification for the person.
    NeedsYou(String),
    /// A background operation encountered a retryable error.
    WorkerError(String),
}

/// One actionable item in the cross-topic attention list.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Attention {
    /// Topic to open.
    pub topic: TopicId,
    /// Item requiring attention.
    pub item: AttentionItem,
}

/// Source of an attention item.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum AttentionItem {
    /// A thread awaiting an answer.
    Thread(ThreadId),
    /// A task awaiting approval.
    Task(TaskId),
    /// An unhealthy service account.
    Connection(Connection),
}

/// A ranked search result linking directly to a topic object.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SearchHit {
    /// Containing topic.
    pub topic: TopicId,
    /// Matching thread, task or fact.
    pub subject: Ref,
    /// Matching text excerpt.
    pub snippet: String,
}

/// Persisted server record, including private credentials and resumable work.
/// Send only the public [`TopicSnapshot`] to replicas.
#[derive(Clone, Serialize, Deserialize)]
pub struct StoredTopic {
    // Replicas that received this topic must see its tombstone before collection.
    #[serde(default, skip_serializing_if = "BTreeSet::is_empty")]
    replicas: BTreeSet<Uuid>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    retired_state: Option<Box<TopicState>>,
    #[serde(default)]
    default_sort_request: Option<TaskId>,
    #[serde(default)]
    default_sort_removed: bool,
    #[serde(default)]
    dispatch_keys: BTreeMap<Uuid, chrono::NaiveDate>,
    #[serde(default)]
    observations: Vec<observations::Observation>,
    /// Public revision of this record.
    #[serde(default)]
    pub revision: u64,
    /// Domain state included in snapshots.
    #[serde(flatten)]
    pub state: TopicState,
    #[serde(default)]
    runs: BTreeMap<TaskId, Work>,
    #[serde(default)]
    task_handles: BTreeMap<TaskId, RunHandle>,
    // An idle interactive run can still return its previous answer while a new turn queues.
    #[serde(default)]
    pending_messages: BTreeMap<TaskId, (usize, String)>,
    #[serde(default)]
    conversations: BTreeMap<TaskId, meep_wire::TaskConversation>,
    #[serde(default)]
    conversation_history: BTreeMap<TaskId, Vec<meep_wire::TaskConversation>>,
    #[serde(default)]
    last_progress: BTreeMap<TaskId, DateTime<Utc>>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    deliveries: BTreeMap<Uuid, effects::Delivery>,
    #[serde(default)]
    dispatches: BTreeMap<CommandId, RoutineRun>,
    #[serde(default)]
    effects: VecDeque<effects::Effect>,
    #[serde(default)]
    proposals: BTreeMap<TaskId, effects::Proposer>,
    #[serde(default, skip_serializing_if = "BTreeSet::is_empty")]
    evidence_holds: BTreeSet<TaskId>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    activation_aliases: BTreeMap<TaskId, TaskId>,
    #[serde(default)]
    intake: VecDeque<intake::Pending>,
    #[serde(default)]
    parked_sorts: BTreeMap<MessageId, intake::Pending>,
    #[serde(default)]
    fact_checks: VecDeque<memory::Pending>,
    #[serde(default)]
    routines: BTreeMap<String, Routine>,
    #[serde(default)]
    starts: RunWindow,
    #[serde(default, skip_serializing_if = "setup::Setup::is_none")]
    setup: setup::Setup,
    #[serde(default, skip_serializing_if = "session::Inbox::is_empty")]
    inbox: session::Inbox,
}

#[derive(Clone, PartialEq, Serialize, Deserialize)]
enum Work {
    AssignedFlow {
        binding: RoutineBinding,
        generation: Option<CommandId>,
        key: Uuid,
        invocation: Option<Uuid>,
    },
    Poll(RunHandle),
    Approved(RunHandle),
    Routine {
        binding: RoutineBinding,
        #[serde(default)]
        generation: Option<CommandId>,
        invocation: Uuid,
    },
    Stopped,
}

#[derive(Default)]
struct Lanes<K>(Mutex<BTreeMap<K, Weak<AsyncMutex<()>>>>);

impl<K: Ord> Lanes<K> {
    fn lane(&self, key: K) -> Arc<AsyncMutex<()>> {
        let mut lanes = self.0.lock();
        lanes.retain(|_, lane| lane.strong_count() != 0);
        let entry = lanes.entry(key).or_default();
        entry.upgrade().unwrap_or_else(|| {
            let lane = Arc::new(AsyncMutex::new(()));
            *entry = Arc::downgrade(&lane);
            lane
        })
    }
}

struct Slot {
    wake: tokio::sync::watch::Sender<()>,
    saved: RwLock<Arc<StoredTopic>>,
    edit: Arc<AsyncMutex<()>>,
    files: Arc<AsyncMutex<()>>,
    worker: AsyncMutex<()>,
    effect_worker: AsyncMutex<()>,
    observation_worker: AsyncMutex<()>,
    sort_worker: AsyncMutex<()>,
}

struct Inner {
    runtime: tokio::runtime::Handle,
    stop: CancellationToken,
    tasks: TaskTracker,
    store: Arc<dyn Store>,
    blobs: Arc<dyn Blobs>,
    backends: BTreeMap<String, Arc<dyn RoutineBackend>>,
    command_topics: Lanes<TopicId>,
    command_ids: Lanes<CommandId>,
    deliveries: Lanes<(String, String)>,
    sort_steps: Lanes<(TopicId, Uuid)>,
    callbacks: Lanes<(TopicId, String, Uuid)>,
    topics: RwLock<BTreeMap<TopicId, Arc<Slot>>>,
    connectors: RwLock<BTreeMap<String, Arc<dyn Connector>>>,

    polling: Lanes<String>,
    limits: Limits,
    agent: Arc<dyn Agent>,
    sorter: Arc<dyn Sorter>,
    clock: Arc<dyn Clock>,
    events: broadcast::Sender<EngineEvent>,
    setup: std::sync::atomic::AtomicBool,
}

/// A cloneable headless runtime. Dropping the last host handle releases idle workers.
#[derive(Clone)]
pub struct Engine(Arc<Inner>, #[allow(dead_code)] Option<Arc<DropGuard>>);

fn id<T: From<Uuid>>() -> T {
    Uuid::new_v4().into()
}

impl Engine {
    /// Opens or creates a private directory with the default sorter and no external agent.
    pub async fn open(dir: impl AsRef<Path>) -> Result<Self> {
        let dir = dir.as_ref().to_owned();
        let (store, blobs) = tokio::task::spawn_blocking(move || -> Result<_> {
            Ok((
                Arc::new(SqliteStore::open(&dir)?),
                Arc::new(DirBlobs::open(dir.join("files"))?),
            ))
        })
        .await
        .context("Opening topic storage interrupted")??;
        Self::defaults(store, blobs).await
    }

    /// Creates an isolated, automatically driven engine.
    pub async fn in_memory() -> Result<Self> {
        Self::defaults(
            Arc::new(MemoryStore::default()),
            Arc::new(MemoryBlobs::default()),
        )
        .await
    }

    async fn defaults(store: Arc<dyn Store>, blobs: Arc<dyn Blobs>) -> Result<Self> {
        Self::with_backends(
            store,
            blobs,
            vec![],
            Limits {
                max_hops: 4,
                max_runs_per_hour: 60,
            },
            Arc::new(agent::NoAgent),
            Arc::new(sorter::Disconnected),
            Arc::new(SystemClock),
        )
        .await
    }

    /// Opens a runtime with the host's storage, limits, agent and sorter.
    pub async fn new(
        store: Arc<dyn Store>,
        limits: Limits,
        agent: Arc<dyn Agent>,
        sorter: Arc<dyn Sorter>,
    ) -> Result<Self> {
        Self::with_clock(store, limits, agent, sorter, Arc::new(SystemClock)).await
    }

    /// Opens a runtime with an injectable clock and in-memory files.
    pub async fn with_clock(
        store: Arc<dyn Store>,
        limits: Limits,
        agent: Arc<dyn Agent>,
        sorter: Arc<dyn Sorter>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self> {
        Self::with_backends(
            store,
            Arc::new(MemoryBlobs::default()),
            vec![],
            limits,
            agent,
            sorter,
            clock,
        )
        .await
    }

    /// Opens a server with the supplied routine backends.
    pub async fn with_backends(
        store: Arc<dyn Store>,
        blobs: Arc<dyn Blobs>,
        backends: Vec<Arc<dyn RoutineBackend>>,
        limits: Limits,
        agent: Arc<dyn Agent>,
        sorter: Arc<dyn Sorter>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self> {
        let mut providers: BTreeMap<String, Arc<dyn RoutineBackend>> = BTreeMap::new();
        for backend in backends {
            let key = backend.name().to_owned();
            if providers.insert(key.clone(), backend).is_some() {
                return Err(anyhow::anyhow!("duplicate routine backend {key}").into());
            }
        }
        let loader = store.clone();
        let files = blobs.clone();
        let topics = tokio::task::spawn_blocking(move || {
            loader
                .load()?
                .into_iter()
                .map(|saved| {
                    if saved.state.deleted && saved.replicas.is_empty() {
                        files.purge(saved.state.topic.id)?;
                    }
                    Ok((saved.state.topic.id, Slot::new(saved)))
                })
                .collect::<Result<_>>()
        })
        .await
        .context("Topic loading interrupted")??;
        let stop = CancellationToken::new();
        let lifetime = Arc::new(stop.clone().drop_guard());
        let engine = Self(
            Arc::new(Inner {
                stop,
                tasks: TaskTracker::new(),
                runtime: tokio::runtime::Handle::current(),
                store,
                blobs,
                backends: providers,
                command_topics: Lanes(Mutex::default()),
                command_ids: Lanes(Mutex::default()),
                deliveries: Lanes(Mutex::default()),
                sort_steps: Lanes(Mutex::default()),
                callbacks: Lanes(Mutex::default()),
                topics: RwLock::new(topics),
                connectors: RwLock::default(),

                polling: Lanes(Mutex::default()),
                limits,
                agent,
                sorter,
                clock,
                events: broadcast::channel(512).0,
                setup: Default::default(),
            }),
            Some(lifetime),
        );
        engine.maintain_topics().await?;
        for topic in engine.topic_ids() {
            engine.recover_file_reviews(topic).await?;
        }
        engine.spawn_connector_worker();
        for topic in engine.topic_ids() {
            engine.spawn_worker(topic);
        }
        Ok(engine)
    }

    /// Stop background work and drain accepted commands and in-flight commits.
    pub async fn shutdown(&self) {
        self.0.stop.cancel();
        self.0.tasks.close();
        self.0.tasks.wait().await;
    }

    /// List topic IDs without cloning their snapshots.
    pub fn topic_ids(&self) -> Vec<TopicId> {
        self.0
            .topics
            .read()
            .iter()
            .filter(|(_, s)| !s.saved.read().state.deleted)
            .map(|(id, _)| *id)
            .collect()
    }
    fn slot(&self, topic: TopicId) -> Result<Arc<Slot>> {
        self.0
            .topics
            .read()
            .get(&topic)
            .filter(|s| !s.saved.read().state.deleted)
            .cloned()
            .ok_or(Error::UnknownTopic(topic))
    }

    /// Recheck agent eligibility after a host changes a topic’s connection grants.
    pub fn wake_topic(&self, topic: TopicId) {
        if let Ok(slot) = self.slot(topic) {
            slot.wake.send_replace(());
        }
    }

    /// Provider handles of the topic's agent runs that are still being observed.
    /// A host can use them to scope credentials it issued to a single run.
    pub fn active_runs(&self, topic: TopicId) -> Result<Vec<RunHandle>> {
        let slot = self.slot(topic)?;
        let saved = slot.saved.read();
        Ok(saved
            .runs
            .values()
            .chain(saved.deliveries.values().map(|d| &d.work))
            .filter_map(|w| match w {
                Work::Poll(h) | Work::Approved(h) => Some(h.clone()),
                _ => None,
            })
            .collect())
    }

    /// The latest provider run handle of each task that has started one.
    /// A host reads its own handles back to browse what those runs produced.
    pub fn task_runs(&self, topic: TopicId) -> Result<Vec<(TaskId, RunHandle)>> {
        let slot = self.slot(topic)?;
        let saved = slot.saved.read();
        let mut handles = saved.task_handles.clone();
        for (task, work) in &saved.runs {
            if let Work::Poll(h) | Work::Approved(h) = work {
                handles.entry(*task).or_insert_with(|| h.clone());
            }
        }
        Ok(handles
            .into_iter()
            .filter(|(task, _)| saved.state.tasks.iter().any(|t| t.id == *task))
            .collect())
    }

    /// Count one System One request, including calls that later fail.
    pub async fn record_system_one(&self, topic: TopicId) -> Result<()> {
        self.update(topic, &Default::default(), |s, now| {
            if s.state.archived || s.state.deleted {
                return Err(TopicError::InactiveTopic.into());
            }
            s.state
                .usage
                .days
                .entry(now.date_naive())
                .or_default()
                .system_one += 1;
            Ok(vec![])
        })
        .await?;
        Ok(())
    }

    /// Expire replicated undo records even for topics without incoming edits.
    pub async fn maintain_topics(&self) -> Result<()> {
        let now = self.0.clock.now();
        for topic in self.topic_ids() {
            let slot = self.slot(topic)?;
            let needs_write = {
                let saved = slot.saved.read();
                saved.state.usage.hourly_cap != self.0.limits.max_runs_per_hour
                    || saved
                        .state
                        .removed_rules
                        .values()
                        .any(|(at, _, _)| *at <= now - chrono::TimeDelta::days(30))
            };
            if needs_write {
                self.update(topic, &Default::default(), |_, _| Ok(vec![]))
                    .await?;
            }
        }
        Ok(())
    }

    /// Snapshot of a single topic.
    pub fn topic(&self, topic: TopicId) -> Result<TopicState> {
        self.read_topic(topic, Clone::clone)
    }

    /// Project a field from the current topic without copying unrelated history.
    pub fn read_topic<T>(&self, topic: TopicId, read: impl FnOnce(&TopicState) -> T) -> Result<T> {
        let saved = self.slot(topic)?.saved.read().clone();
        Ok(read(&saved.state))
    }

    /// Snapshots of all topics, ordered by stable ID.
    pub fn topics(&self) -> Vec<TopicState> {
        self.read_topics(|topics| topics.iter().map(|t| (*t).clone()).collect())
    }

    /// Read current topics in ID order, pinning each version for the duration of the query.
    pub fn read_topics<T>(&self, read: impl FnOnce(&[&TopicState]) -> T) -> T {
        let records: Vec<_> = self
            .0
            .topics
            .read()
            .values()
            .map(|s| s.saved.read().clone())
            .collect();
        let topics: Vec<_> = records
            .iter()
            .filter(|r| !r.state.deleted)
            .map(|r| &r.state)
            .collect();
        read(&topics)
    }

    /// Domain activity counts since an inclusive time.
    pub fn digest(&self, topic: TopicId, since: DateTime<Utc>) -> Result<Digest> {
        Ok(self.slot(topic)?.saved.read().state.digest(since))
    }

    /// Returns pending threads, reviews and unhealthy connections with the topic they concern.
    pub fn needs_you(&self) -> Result<Vec<Attention>> {
        let connections = self.connections()?;
        let mut all = vec![];
        for slot in self.0.topics.read().values() {
            let saved = slot.saved.read();
            if saved.state.archived || saved.state.deleted {
                continue;
            }
            let topic = &saved.state.topic;
            let needs = saved.state.needs_you();
            let items = needs
                .threads
                .into_iter()
                .map(AttentionItem::Thread)
                .chain(needs.tasks.into_iter().map(AttentionItem::Task))
                .chain(
                    connections
                        .iter()
                        .filter(|c| !matches!(c.health, Health::Ok { .. }) && depends_on(topic, c))
                        .cloned()
                        .map(AttentionItem::Connection),
                );
            all.extend(items.map(|item| Attention {
                topic: topic.id,
                item,
            }));
        }
        Ok(all)
    }

    /// Searches thread subjects, current facts and task titles across all topics, in relevance order.
    pub fn search(&self, query: &str) -> Result<Vec<SearchHit>> {
        Ok(self.0.store.search(query, usize::MAX)?)
    }

    /// Revisioned file storage selected by the host.
    pub fn blobs(&self) -> &dyn Blobs {
        self.0.blobs.as_ref()
    }

    /// A public topic state and the revision that produced it.
    pub fn snapshot(&self, topic: TopicId) -> Result<TopicSnapshot> {
        self.0
            .store
            .snapshot(topic)?
            .ok_or(Error::UnknownTopic(topic))
    }

    /// Revision of the last published state, including a deletion tombstone.
    pub fn revision(&self, topic: TopicId) -> Result<u64> {
        Ok(self
            .0
            .topics
            .read()
            .get(&topic)
            .ok_or(Error::UnknownTopic(topic))?
            .saved
            .read()
            .revision)
    }

    /// Pull all committed revisions after an exclusive global cursor, starting at zero.
    pub fn changes_since(&self, cursor: u64) -> Result<(Vec<TopicRevision>, u64)> {
        Ok(self.0.store.changes_since(cursor)?)
    }

    /// Subscribes to future events. Reload snapshots if the broadcast receiver reports lag.
    pub fn subscribe(&self) -> broadcast::Receiver<EngineEvent> {
        self.0.events.subscribe()
    }

    fn emit(&self, topic: TopicId, change: EngineChange) {
        if let Ok(slot) = self.slot(topic) {
            let saved = slot.saved.read();
            let _ = self.0.events.send(EngineEvent {
                topic,
                revision: saved.revision,
                change,
            });
        }
    }

    /// Creates a topic and returns its ID and initial mission change.
    pub async fn create_topic(
        &self,
        name: impl Into<String>,
        mission: impl Into<String>,
    ) -> Result<(TopicId, Changes)> {
        let topic = id();
        let changes = self
            .command(
                topic,
                Command::CreateTopic {
                    name: name.into(),
                    mission: mission.into(),
                },
            )
            .await?;
        Ok((topic, changes))
    }

    async fn install(
        &self,
        state: TopicState,
        changes: Changes,
        command: Option<Envelope>,
    ) -> Result<Applied> {
        let topic = state.topic.id;
        let setup = if command.as_ref().is_some_and(|c| {
            matches!(
                c.command,
                Command::CreateTopic { .. } | Command::CreateTopicWithoutSort { .. }
            )
        }) && self.0.setup.load(std::sync::atomic::Ordering::SeqCst)
        {
            setup::Setup::Pending
        } else {
            setup::Setup::None
        };
        let mut state = state;
        state.usage.hourly_cap = self.0.limits.max_runs_per_hour;
        let saved = StoredTopic {
            replicas: Default::default(),
            retired_state: None,
            default_sort_removed: command
                .as_ref()
                .is_some_and(|c| matches!(c.command, Command::CreateTopicWithoutSort { .. })),
            dispatch_keys: Default::default(),
            default_sort_request: None,
            observations: vec![],
            revision: 1,
            state,
            runs: BTreeMap::new(),
            task_handles: Default::default(),
            pending_messages: Default::default(),
            conversations: Default::default(),
            conversation_history: Default::default(),
            last_progress: BTreeMap::new(),
            deliveries: BTreeMap::new(),
            dispatches: BTreeMap::new(),
            effects: VecDeque::new(),
            evidence_holds: BTreeSet::new(),
            activation_aliases: BTreeMap::new(),
            proposals: BTreeMap::new(),
            intake: VecDeque::new(),
            parked_sorts: Default::default(),
            fact_checks: VecDeque::new(),
            routines: BTreeMap::new(),
            starts: RunWindow::default(),
            setup,
            inbox: Default::default(),
        };
        let engine = self.clone();
        self.0
            .tasks
            .spawn_blocking(move || {
                if engine.0.topics.read().contains_key(&topic) {
                    return Err(TopicError::ExistingTopic(topic).into());
                }
                engine.0.store.save(0, &saved, command.as_ref(), &changes)?;
                engine.0.topics.write().insert(topic, Slot::new(saved));
                engine.publish(topic, 1, &changes);

                engine.spawn_worker(topic);
                Ok(Applied {
                    revision: 1,
                    changes,
                })
            })
            .await
            .context("topic creation interrupted")?
    }

    fn publish(&self, topic: TopicId, revision: u64, changes: &[Change]) {
        if changes.is_empty() {
            let _ = self.0.events.send(EngineEvent {
                topic,
                revision,
                change: EngineChange::Revised,
            });
        }
        for change in changes {
            let _ = self.0.events.send(EngineEvent {
                topic,
                revision,
                change: EngineChange::Change(change.clone()),
            });
        }
    }

    async fn update<F>(&self, topic: TopicId, cause: &Causality, f: F) -> Result<Vec<Change>>
    where
        F: FnOnce(&mut StoredTopic, DateTime<Utc>) -> Result<Vec<Change>>,
    {
        let slot = self.slot(topic)?;
        let guard = slot.edit.clone().lock_owned().await;
        let mut next = slot.draft();
        let changes = f(&mut next, self.0.clock.now())?;
        self.commit(slot, guard, next, changes, cause).await
    }

    async fn commit(
        &self,
        slot: Arc<Slot>,
        guard: tokio::sync::OwnedMutexGuard<()>,
        mut next: StoredTopic,
        changes: Vec<Change>,
        cause: &Causality,
    ) -> Result<Vec<Change>> {
        // A source without a provider thread key can move during sorting. Publish its
        // message-arrived trigger after the sorter resolves the owning thread.
        let deferred = next
            .intake
            .back()
            .and_then(|job| job.receipt.as_ref())
            .map(|c| c.seq);
        routines::on_changes(
            &mut next,
            changes.iter().filter(|c| Some(c.seq) != deferred),
            cause,
        );
        Ok(self.write(slot, guard, next, changes, None).await?.changes)
    }

    async fn write(
        &self,
        slot: Arc<Slot>,
        guard: tokio::sync::OwnedMutexGuard<()>,
        mut next: StoredTopic,
        mut changes: Changes,
        command: Option<Envelope>,
    ) -> Result<Applied> {
        let engine = self.clone();
        self.0
            .tasks
            .spawn_blocking(move || {
                let _guard = guard;
                next.last_progress
                    .retain(|id, _| matches!(next.runs.get(id), Some(Work::Poll(_))));
                let current = slot.saved.read().clone();
                let topic = next.state.topic.id;
                if current.state.deleted {
                    return Err(Error::UnknownTopic(topic));
                }
                let now = engine.0.clock.now();
                let monday = now.date_naive().week(chrono::Weekday::Mon).first_day();
                next.state.usage.days.retain(|day, _| *day >= monday);
                next.state
                    .usage
                    .agent_starts
                    .retain(|at| *at > now - chrono::TimeDelta::hours(1));
                next.state.usage.hourly_cap = engine.0.limits.max_runs_per_hour;
                next.dispatch_keys.retain(|_, day| *day >= monday);
                next.state
                    .removed_rules
                    .retain(|_, (at, _, _)| *at > now - chrono::TimeDelta::days(30));
                if memory::enqueue(&mut next, &current.state, &changes) {
                    changes.extend(next.state.close_stale_fact_reviews(engine.0.clock.now()));
                }
                let released = next.release_evidence_holds(engine.0.clock.now())?;
                routines::on_changes(&mut next, &released, &Default::default());
                changes.extend(released);
                let changed =
                    current.state != next.state || current.conversations != next.conversations;
                if changed {
                    next.revision = current
                        .revision
                        .checked_add(1)
                        .context("topic revision exhausted")?;
                }
                engine
                    .0
                    .store
                    .save_transition(&current, &next, command.as_ref(), &changes)?;
                let revision = next.revision;
                drop(current);
                *slot.saved.write() = Arc::new(next);
                if changed {
                    engine.publish(topic, revision, &changes);
                }
                slot.wake.send_replace(());
                Ok(Applied { revision, changes })
            })
            .await
            .context("topic commit interrupted")?
    }
}

impl Slot {
    fn draft(&self) -> StoredTopic {
        let current = self.saved.read().clone();
        current.as_ref().clone()
    }
    fn new(saved: StoredTopic) -> Arc<Self> {
        Arc::new(Self {
            wake: tokio::sync::watch::channel(()).0,
            saved: RwLock::new(Arc::new(saved)),
            edit: Arc::default(),
            files: Default::default(),
            worker: AsyncMutex::default(),
            effect_worker: AsyncMutex::default(),
            observation_worker: Default::default(),
            sort_worker: AsyncMutex::default(),
        })
    }
}

fn depends_on(topic: &Topic, c: &Connection) -> bool {
    c.grants.contains(&topic.id) || topic.watches().any(|w| w.connection == c.id)
}

#[cfg(test)]
mod tests;
