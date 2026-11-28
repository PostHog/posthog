#![doc = include_str!("../README.md")]
#![warn(missing_docs)]

mod queries;
mod replica;
mod sync;
mod transport;
mod views;
mod workflows;

pub use transport::{
    AccessToken, EventStream, FileRevision, HttpTransport, Transport, TransportError,
};

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use meep_store::Connection;
use meep_topic::{Changes, Command, CommandId, Envelope, TaskId, ThreadId, TopicId, TopicState};
use meep_wire::{ConnectionGrant, ConnectionInfo, Connections, NeedsYou, SearchResults};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::{path::Path, sync::Arc};
use tokio::sync::{Mutex as AsyncMutex, Notify, broadcast};
use uuid::Uuid;

/// Most bytes of opened task artifacts a device keeps.
pub const ARTIFACT_CACHE_BYTES: u64 = 100 * 1024 * 1024;

/// Current state of the connection to the Meep server.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Status {
    /// The most recent synchronization succeeded.
    Online,
    /// A synchronization is in progress.
    Syncing,
    /// The server has yet to be reached, or contact was lost.
    Offline {
        /// Beginning of this interruption.
        since: DateTime<Utc>,
        /// Commands still awaiting a receipt.
        pending: usize,
    },
    /// The device credential was refused.
    Unauthorized,
}

/// A notification delivered after the corresponding local change commits.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Event {
    /// Read the topic and its derived views again.
    TopicChanged(TopicId),
    /// Workspace views changed.
    ViewsChanged,
    /// The server permanently refused an optimistic command.
    Rejected {
        /// Stable ID of the discarded envelope.
        command: CommandId,
        /// Server explanation for the person.
        reason: String,
    },
    /// The connection indicator changed.
    Status(Status),
}

struct SyncState {
    status: Status,
    offline_since: Option<DateTime<Utc>>,
}

struct Inner {
    db: Arc<Mutex<Connection>>,
    reader: Arc<Mutex<Connection>>,
    transport: Arc<dyn Transport>,
    events: broadcast::Sender<Event>,
    state: Mutex<SyncState>,
    wake: Notify,
    cycle: Arc<AsyncMutex<()>>,
    uploads: Arc<AsyncMutex<()>>,
    accounts: Arc<AsyncMutex<()>>,
    workflows: Arc<AsyncMutex<()>>,
    runner: AsyncMutex<()>,
}

/// A cloneable handle to one device's durable local replica.
#[derive(Clone)]
pub struct Client(Arc<Inner>);

impl Client {
    /// Opens or creates a replica file. The host starts background sync with [`Self::run`].
    pub fn open(path: impl AsRef<Path>, transport: Arc<dyn Transport>) -> Result<Self> {
        let db = replica::open(path.as_ref())?;
        let since = Utc::now();
        let pending = replica::count(&db)?;
        let reader = db
            .path()
            .filter(|p| !p.is_empty())
            .map(Connection::open)
            .transpose()?;
        let db = Arc::new(Mutex::new(db));
        let reader = reader
            .map(|c| Arc::new(Mutex::new(c)))
            .unwrap_or_else(|| db.clone());
        Ok(Self(Arc::new(Inner {
            db,
            reader,
            transport,
            events: broadcast::channel(256).0,
            state: Mutex::new(SyncState {
                status: Status::Offline { since, pending },
                offline_since: Some(since),
            }),
            wake: Notify::new(),
            cycle: Arc::default(),
            uploads: Arc::default(),
            accounts: Arc::default(),
            workflows: Arc::default(),
            runner: AsyncMutex::new(()),
        })))
    }

    // Keep the ordering guard until the database work and its notifications finish,
    // even when the calling request is cancelled.
    async fn local<T: Send + 'static>(
        &self,
        guard: impl Send + 'static,
        work: impl FnOnce(&Self) -> Result<T> + Send + 'static,
    ) -> Result<T> {
        let client = self.clone();
        tokio::task::spawn_blocking(move || {
            let _guard = guard;
            work(&client)
        })
        .await?
    }

    /// Manage the current account’s installations through the Meep server.
    pub async fn mcp_store(
        &self,
        request: &meep_wire::mcp_store::Operation,
    ) -> Result<meep_wire::mcp_store::Outcome> {
        Ok(self.0.transport.mcp_store(request).await?)
    }
    /// Clear reproducible replica state and schedule a full pull. Pending work keeps its base.
    pub async fn clear_replica_cache(&self) -> Result<()> {
        let cycle = self.0.cycle.clone().lock_owned().await;
        self.local(cycle, |client| {
        let removed = meep_store::transaction(&mut client.0.db.lock(), |tx| {
            anyhow::ensure!(replica::count(tx)? == 0 && !tx.query_row("SELECT EXISTS(SELECT 1 FROM records WHERE kind='client/requested-access' AND deleted=0)",[],|r|r.get::<_,bool>(0))?, "Sync pending changes before clearing the replica cache.");
            let ids = tx.prepare("SELECT id FROM records WHERE kind='client/visible' AND deleted=0")?.query_map([], |row| row.get::<_, String>(0))?.collect::<rusqlite::Result<Vec<_>>>()?;
            tx.execute_batch("DELETE FROM client_files;
                DELETE FROM client_artifact_cache;
                DELETE FROM search_documents;
                DELETE FROM records WHERE kind IN ('client/base','client/visible','client/file-list','client/discovery','client/workflows') OR (kind='client/meta' AND id!='replica-id');")?;
            Ok(ids)
        })?;
        for id in removed { client.emit(Event::TopicChanged(id.parse()?)); }
        client.emit(Event::ViewsChanged);
        client.sync_now();
        Ok(())
        }).await
    }
    /// Subscribes to changes. After broadcast lag, reload the visible state and status.
    pub fn subscribe(&self) -> broadcast::Receiver<Event> {
        self.0.events.subscribe()
    }

    /// Permanent server rejections awaiting acknowledgement on this device.
    pub fn rejections(&self) -> Result<Vec<(CommandId, String)>> {
        meep_store::list(&self.0.db.lock(), "client/rejected")?
            .into_iter()
            .map(|(id, reason)| Ok((id.parse()?, reason)))
            .collect()
    }
    /// Original path of a rejected upload that still has a recoverable local copy.
    pub fn rejected_file_path(&self, id: CommandId) -> Result<Option<String>> {
        use rusqlite::OptionalExtension;
        Ok(self
            .0
            .db
            .lock()
            .query_row(
                "SELECT path FROM client_rejected_files WHERE id=?1",
                [id.to_string()],
                |r| r.get(0),
            )
            .optional()?)
    }

    /// Read the original bytes of one rejected upload for export from the device.
    pub fn rejected_file_bytes(&self, id: CommandId) -> Result<Vec<u8>> {
        Ok(self.0.db.lock().query_row(
            "SELECT bytes FROM client_rejected_files WHERE id=?1",
            [id.to_string()],
            |r| r.get(0),
        )?)
    }

    /// Dismiss a rejection and release any associated recovery copy.
    pub fn dismiss_rejection(&self, id: CommandId) -> Result<()> {
        let key = id.to_string();
        meep_store::transaction(&mut self.0.db.lock(), |tx| {
            tx.execute("DELETE FROM client_rejected_files WHERE id=?1", [&key])?;
            meep_store::remove(tx, "client/rejected", &key)?;
            Ok(())
        })
    }
    /// Returns the current connection indicator.
    pub fn status(&self) -> Status {
        self.0.state.lock().status.clone()
    }

    /// Lists local visible snapshots in stable topic ID order.
    pub fn topics(&self) -> Result<Vec<TopicState>> {
        Ok(replica::topics(&self.0.reader.lock())?
            .into_iter()
            .filter(|s| !s.archived && !s.deleted)
            .collect())
    }

    /// Topics that can be returned to the active workspace.
    pub fn archived_topics(&self) -> Result<Vec<TopicState>> {
        Ok(replica::topics(&self.0.reader.lock())?
            .into_iter()
            .filter(|s| s.archived && !s.deleted)
            .collect())
    }

    /// Reads one visible snapshot, including pending edits.
    pub fn topic(&self, topic: TopicId) -> Result<Option<TopicState>> {
        replica::visible(&self.0.reader.lock(), topic)
    }

    /// Lists waiting decisions, approvals and connection problems from local data.
    pub fn needs_you(&self) -> Result<NeedsYou> {
        let mut reader = self.0.reader.lock();
        let tx = reader.transaction()?;
        let states = replica::topics(&tx)?;
        Self::attention(&tx, &states)
    }

    /// Compute attention for topics already loaded by the workspace.
    pub fn needs_you_for(&self, states: &[TopicState]) -> Result<NeedsYou> {
        let mut reader = self.0.reader.lock();
        let tx = reader.transaction()?;
        Self::attention(&tx, states)
    }

    fn attention(db: &Connection, states: &[TopicState]) -> Result<NeedsYou> {
        let connections = replica::connections(db)?;
        let observed = replica::health_observations(db)?;
        Ok(NeedsYou::from_states(
            states,
            connections.connections.into_iter().map(|c| {
                let since = observed
                    .get(&c.id)
                    .copied()
                    .unwrap_or(DateTime::<Utc>::MIN_UTC);
                (c, since)
            }),
        ))
    }

    /// Searches the local full-text index in relevance order.
    pub fn search(&self, query: &str, limit: usize) -> Result<SearchResults> {
        queries::search(&self.0.reader.lock(), query, limit)
    }

    /// Applies and queues one command atomically, then wakes the sync loop.
    pub fn issue(&self, topic: TopicId, command: Command) -> Result<Changes> {
        self.issue_with_access(topic, command, None)
    }

    /// Choose a topic chat model and its billing option together.
    pub async fn set_chat_choice(
        &self,
        topic: TopicId,
        choice: &meep_wire::ChatModelChoice,
    ) -> Result<meep_wire::ChatModels> {
        self.observe(self.0.transport.set_chat_choice(topic, choice).await)
    }
    /// Latest task conversation, refreshed on a topic revision.
    pub async fn task_conversation(
        &self,
        topic: TopicId,
        task: TaskId,
    ) -> Result<meep_wire::TaskConversation> {
        self.observe(self.0.transport.task_conversation(topic, task).await)
    }
    /// What the topic's task runs produced, listed live. Nothing here is synced.
    pub async fn task_artifacts(&self, topic: TopicId) -> Result<Vec<meep_wire::TaskArtifact>> {
        self.observe(self.0.transport.task_artifacts(topic).await)
    }
    /// An artifact version this device opened before, without a request.
    pub fn cached_artifact(&self, artifact: &meep_wire::TaskArtifact) -> Result<Option<Vec<u8>>> {
        replica::cached_artifact(
            &self.0.db.lock(),
            &artifact.cache_key(),
            Utc::now().timestamp_millis(),
        )
    }
    /// Read an artifact version, from the cache or the server. Opened versions are kept
    /// until [`ARTIFACT_CACHE_BYTES`] is exceeded, least recently opened first.
    pub async fn artifact(
        &self,
        topic: TopicId,
        artifact: &meep_wire::TaskArtifact,
    ) -> Result<Vec<u8>> {
        if let Some(bytes) = self.cached_artifact(artifact)? {
            return Ok(bytes);
        }
        let bytes = self.observe(self.0.transport.task_artifact(topic, artifact).await)?;
        let key = artifact.cache_key();
        let kept = bytes.clone();
        self.local((), move |c| {
            replica::cache_artifact(
                &c.0.db.lock(),
                &key,
                &kept,
                Utc::now().timestamp_millis(),
                ARTIFACT_CACHE_BYTES,
            )
        })
        .await?;
        Ok(bytes)
    }
    /// Bytes the artifact cache holds on this device.
    pub fn artifact_cache_size(&self) -> Result<u64> {
        replica::artifact_cache_size(&self.0.reader.lock())
    }
    /// Send a user turn to this investigation.
    pub async fn send_task_message(&self, topic: TopicId, task: TaskId, text: &str) -> Result<()> {
        self.send_task_message_on_model(topic, task, text, None)
            .await
    }
    /// Continue the same task with an optional model override.
    pub async fn send_task_message_on_model(
        &self,
        topic: TopicId,
        task: TaskId,
        text: &str,
        model: Option<&str>,
    ) -> Result<()> {
        self.observe(
            self.0
                .transport
                .send_task_message_on_model(topic, task, text, model)
                .await,
        )
    }
    /// Queue cancellation of this investigation.
    pub fn cancel_run(&self, topic: TopicId, task: TaskId) -> Result<Changes> {
        self.issue(topic, Command::CancelRun { task })
    }
    /// Change the topic display name.
    pub fn rename_topic(&self, topic: TopicId, name: String) -> Result<Changes> {
        self.issue(topic, Command::RenameTopic { name })
    }

    /// Pause the topic and hide it from the active workspace.
    pub fn archive_topic(&self, topic: TopicId) -> Result<Changes> {
        self.issue(topic, Command::ArchiveTopic)
    }

    /// Return an archived topic to the workspace.
    pub fn unarchive_topic(&self, topic: TopicId) -> Result<Changes> {
        self.issue(topic, Command::UnarchiveTopic)
    }

    /// Delete a topic and replicate its tombstone.
    pub fn delete_topic(&self, topic: TopicId) -> Result<Changes> {
        self.issue(topic, Command::DeleteTopic)
    }

    /// Remove a task from the board.
    pub fn delete_task(&self, topic: TopicId, task: TaskId) -> Result<Changes> {
        self.issue(topic, Command::DeleteTask { task })
    }

    /// Archive an inbox conversation.
    pub fn archive_thread(&self, topic: TopicId, thread: ThreadId) -> Result<Changes> {
        self.issue(topic, Command::ArchiveThread { thread })
    }

    /// Remove the current head of a topic file while retaining history.
    pub fn delete_file(&self, topic: TopicId, path: String) -> Result<Changes> {
        self.issue(topic, Command::DeleteFile { path })
    }

    /// Creates a topic offline and durably requests access to its selected account.
    pub fn create_topic(
        &self,
        topic: TopicId,
        name: String,
        mission: String,
        connection: &str,
    ) -> Result<Changes> {
        self.issue_with_access(
            topic,
            Command::CreateTopic { name, mission },
            Some(connection),
        )
    }

    fn issue_with_access(
        &self,
        topic: TopicId,
        command: Command,
        connection: Option<&str>,
    ) -> Result<Changes> {
        let envelope = Envelope {
            id: CommandId(Uuid::new_v4()),
            topic,
            issued_at: Utc::now(),
            command,
        };
        let mut db = self.0.db.lock();
        let changes = replica::issue(&mut db, &envelope, connection)?;
        self.emit(Event::TopicChanged(topic));
        self.added_pending();
        self.sync_now();
        Ok(changes)
    }

    fn added_pending(&self) {
        let mut state = self.0.state.lock();
        if let Status::Offline { since, pending } = state.status {
            self.set_status(
                &mut state,
                Status::Offline {
                    since,
                    pending: pending + 1,
                },
            );
        }
    }

    /// Local presentation preference scoped to this replica. Never enters the outbox.
    pub fn preference<T: serde::de::DeserializeOwned>(&self, key: &str) -> Result<Option<T>> {
        meep_store::get(&self.0.reader.lock(), "client/preferences", key)
    }

    /// Saves a local presentation preference.
    pub fn set_preference<T: Serialize>(&self, key: &str, value: &T) -> Result<()> {
        meep_store::put(&self.0.db.lock(), "client/preferences", key, value)
    }

    /// Last model-ranked source catalog for this topic, including while offline.
    pub fn cached_sources_for(
        &self,
        topic: TopicId,
    ) -> Result<Option<Vec<meep_wire::WatchableSource>>> {
        meep_store::get(
            &self.0.reader.lock(),
            "client/discovery",
            &topic.to_string(),
        )
    }
    /// Rank the topic's granted resources against its mission and cache their order.
    pub async fn sources_for(&self, topic: TopicId) -> Result<Vec<meep_wire::WatchableSource>> {
        let sources = self.observe(self.0.transport.sources_for(topic).await)?;
        meep_store::put(
            &self.0.db.lock(),
            "client/discovery",
            &topic.to_string(),
            &sources,
        )?;
        Ok(sources)
    }

    /// List the models a view can be built with.
    pub async fn view_models(&self) -> Result<meep_wire::ChatModels> {
        self.observe(self.0.transport.view_models().await)
    }

    /// Stage a file for a view request; name it in the request's options after.
    pub async fn put_view_file(&self, view: Uuid, name: &str, bytes: Vec<u8>) -> Result<()> {
        self.observe(self.0.transport.put_view_file(view, name, bytes).await)
    }

    /// List the models this topic's chat can answer with and the one it uses.
    pub async fn chat_models(&self, topic: TopicId) -> Result<meep_wire::ChatModels> {
        self.observe(self.0.transport.chat_models(topic).await)
    }

    /// Choose the model this topic's chat answers with. `None` restores the default.
    pub async fn set_chat_model(
        &self,
        topic: TopicId,
        model: Option<&str>,
    ) -> Result<meep_wire::ChatModels> {
        self.observe(self.0.transport.set_chat_model(topic, model).await)
    }

    /// Reads the last known file list, including files already cached by this device.
    pub fn cached_files(&self, topic: TopicId) -> Result<Vec<String>> {
        let mut reader = self.0.reader.lock();
        let db = reader.transaction()?;
        let mut names: std::collections::BTreeSet<String> =
            meep_store::get(&db, "client/file-list", &topic.to_string())?.unwrap_or_default();
        let mut statement = db.prepare(
            "SELECT path FROM client_files WHERE topic=?1
             UNION ALL SELECT DISTINCT path FROM client_file_outbox WHERE topic=?1",
        )?;
        for row in statement.query_map([topic.to_string()], |row| row.get(0))? {
            names.insert(row?);
        }
        if names.is_empty() {
            return Ok(Vec::new());
        }
        let deleted = replica::deleted_files(&db, topic)?;
        names.retain(|path| !deleted.contains_key(path));
        Ok(names.into_iter().collect())
    }

    /// Refreshes a topic's file list and retains it for offline browsing.
    pub async fn refresh_files(&self, topic: TopicId) -> Result<()> {
        let names = self.observe(self.0.transport.files(topic).await)?;
        let db = self.0.db.lock();
        let key = topic.to_string();
        if meep_store::get::<Vec<String>>(&db, "client/file-list", &key)?.as_ref() != Some(&names) {
            meep_store::put(&db, "client/file-list", &key, &names)?;
            self.emit(Event::TopicChanged(topic));
        }
        Ok(())
    }

    /// Returns the last synchronized connection list, including offline.
    pub fn connections(&self) -> Result<Connections> {
        replica::connections(&self.0.reader.lock())
    }

    /// Register credentials without replacing existing grants or switching an existing project's identity.
    pub async fn register_connection(
        &self,
        id: &str,
        grant: &ConnectionGrant,
    ) -> Result<ConnectionInfo> {
        let guard = self.0.accounts.clone().lock_owned().await;
        let info = self.observe(self.0.transport.register_connection(id, grant).await)?;
        self.save_connection(info.clone(), guard).await?;
        Ok(info)
    }

    /// Sends a grant to the server and saves the returned public connection details.
    pub async fn put_connection(
        &self,
        id: &str,
        grant: &ConnectionGrant,
    ) -> Result<ConnectionInfo> {
        let guard = self.0.accounts.clone().lock_owned().await;
        let info = self.observe(self.0.transport.put_connection(id, grant).await)?;
        self.save_connection(info.clone(), guard).await?;
        Ok(info)
    }

    /// Grant a single existing topic access to a connected account.
    pub async fn grant_topic(&self, connection: &str, topic: TopicId) -> Result<()> {
        let guard = self.0.accounts.clone().lock_owned().await;
        let info = self.observe(self.0.transport.grant_topic(connection, topic).await)?;
        self.save_connection(info, guard).await
    }

    /// Sign out this account on the server and refresh the local connection state.
    pub async fn sign_out(&self, id: &str) -> Result<ConnectionInfo> {
        let guard = self.0.accounts.clone().lock_owned().await;
        let info = self.observe(self.0.transport.sign_out(id).await)?;
        self.save_connection(info.clone(), guard).await?;
        Ok(info)
    }
    /// Reads the latest locally cached revision of a file without making a request.
    pub fn cached_file(&self, topic: TopicId, path: &str) -> Result<Option<FileRevision>> {
        replica::cached_file(&self.0.reader.lock(), topic, path)
    }

    /// Fetches a file, falling back to its last cached revision when the server is unreachable.
    pub async fn get_file(&self, topic: TopicId, path: &str) -> Result<FileRevision> {
        if let Some(bytes) = replica::pending_file(&self.0.reader.lock(), topic, path)? {
            return Ok(FileRevision { revision: 0, bytes });
        }
        match self.observe(self.0.transport.get_file(topic, path).await) {
            Ok(file) => replica::cache_file(&mut self.0.db.lock(), topic, path, file),
            Err(error) if matches!(error.downcast_ref(), Some(TransportError::Unavailable(_))) => {
                self.cached_file(topic, path)?.ok_or(error)
            }
            Err(error) => Err(error),
        }
    }

    /// Read an immutable revision without replacing the current confirmed cache.
    pub async fn get_file_at(
        &self,
        topic: TopicId,
        path: &str,
        revision: u64,
    ) -> Result<FileRevision> {
        anyhow::ensure!(revision > 0, "Expected a saved revision");
        if let Some(file) = self.cached_file(topic, path)?
            && file.revision == revision
        {
            return Ok(file);
        }
        self.observe(self.0.transport.get_file_at(topic, path, revision).await)
    }

    /// Queue an edit based on the current local copy and return the visible file.
    /// Revision zero identifies a pending upload. Divergent edits appear in Needs You.
    pub async fn put_file(
        &self,
        topic: TopicId,
        path: &str,
        bytes: Vec<u8>,
    ) -> Result<FileRevision> {
        self.queue_file_edit(topic, path, bytes, None).await
    }

    /// Queue an edit from the revision opened by the editor, even after a cache refresh.
    pub async fn put_file_from_revision(
        &self,
        topic: TopicId,
        path: &str,
        bytes: Vec<u8>,
        base: u64,
    ) -> Result<FileRevision> {
        self.queue_file_edit(topic, path, bytes, Some(base)).await
    }

    async fn queue_file_edit(
        &self,
        topic: TopicId,
        path: &str,
        bytes: Vec<u8>,
        base: Option<u64>,
    ) -> Result<FileRevision> {
        anyhow::ensure!(
            !path.split('/').any(|s| matches!(s, "" | "." | "..")),
            "Invalid file name"
        );
        anyhow::ensure!(
            bytes.len() <= 64 * 1024 * 1024,
            "File exceeds the upload limit"
        );
        let id = uuid::Uuid::new_v4();
        {
            meep_store::transaction(&mut self.0.db.lock(), |db| {
                anyhow::ensure!(replica::visible(db, topic)?.is_some(), "Unknown topic");
                db.execute("INSERT INTO client_file_bases(id,base,parent) VALUES (?1,
                coalesce(?4,(SELECT revision FROM client_files WHERE topic=?2 AND path=?3),zeroblob(8)),
                (SELECT id FROM client_file_outbox WHERE ?4 IS NULL AND topic=?2 AND path=?3 ORDER BY seq DESC LIMIT 1))",
                rusqlite::params![id.to_string(),topic.to_string(),path,base.map(u64::to_be_bytes)])?;
                db.execute(
                    "INSERT INTO client_file_outbox(id,topic,path,bytes) VALUES (?1,?2,?3,?4)",
                    rusqlite::params![id.to_string(), topic.to_string(), path, bytes],
                )?;
                Ok(())
            })?;
            self.added_pending();
        }
        self.emit(Event::TopicChanged(topic));
        self.sync_now();
        if matches!(self.status(), Status::Online)
            && !replica::has_commands(&self.0.reader.lock(), topic)?
            && let Err(e) = self.upload_files().await
        {
            self.disconnected(&e)?;
            if !matches!(e.downcast_ref(), Some(TransportError::Unavailable(_))) {
                return Err(e);
            }
        }
        let db = self.0.db.lock();
        if let Some(reason) = meep_store::get::<String>(&db, "client/rejected", &id.to_string())? {
            anyhow::bail!("Could not save {path}: {reason}");
        }
        replica::cached_file(&db, topic, path)?.context("missing queued file")
    }

    async fn upload_files(&self) -> Result<()> {
        use rusqlite::OptionalExtension;
        let guard = Arc::new(self.0.uploads.clone().lock_owned().await);
        let end: i64 = self.0.reader.lock().query_row(
            "SELECT coalesce(max(seq),0) FROM client_file_outbox",
            [],
            |row| row.get(0),
        )?;
        loop {
            let reader = self.0.reader.clone();
            let row = tokio::task::spawn_blocking(move || reader.lock()
                .query_row(
                    "SELECT f.id,f.topic,f.path,f.bytes,b.base FROM client_file_outbox f JOIN client_file_bases b ON b.id=f.id
                     WHERE f.seq<=?1 AND NOT EXISTS (SELECT 1 FROM client_outbox c WHERE c.topic=f.topic)
                     ORDER BY f.seq LIMIT 1",
                    [end],
                    |r| {
                        Ok((
                            r.get::<_, String>(0)?,
                            r.get::<_, String>(1)?,
                            r.get::<_, String>(2)?,
                            r.get::<_, Vec<u8>>(3)?,
                            u64::from_be_bytes(r.get(4)?),
                        ))
                    },
                )
                .optional()).await??;
            let Some((id, topic, path, bytes, base)) = row else {
                return Ok(());
            };
            let topic = topic.parse()?;
            let result = self
                .0
                .transport
                .put_file_based(topic, &path, bytes, id.parse()?, base)
                .await;
            // A retained branch has its own revision. Only the server head belongs
            // in the confirmed cache. A lost read can safely replay the same upload.
            let head = if matches!(&result, Ok((_, Some(_)))) {
                Some(self.0.transport.get_file(topic, &path).await?)
            } else {
                None
            };
            self.local(guard.clone(), move |client| {
                let error = meep_store::transaction(&mut client.0.db.lock(), |tx| {
                    let error = match result {
                        Ok((file, _)) => {
                            tx.execute(
                                "UPDATE client_file_bases SET base=?1,parent=NULL WHERE parent=?2",
                                rusqlite::params![file.revision.to_be_bytes(), &id],
                            )?;
                            replica::save_file(tx, topic, &path, head.unwrap_or(file))?;
                            None
                        }
                        Err(TransportError::Api { message, .. }) => {
                            replica::preserve_upload(tx, &id)?;
                            meep_store::put(tx, "client/rejected", &id, &message)?;
                            Some(message)
                        }
                        Err(e) => return Err(e.into()),
                    };
                    tx.execute("DELETE FROM client_file_outbox WHERE id=?1", [&id])?;
                    Ok(error)
                })?;
                if let Some(reason) = error {
                    client.emit(Event::Rejected {
                        command: id.parse()?,
                        reason,
                    });
                }
                client.emit(Event::TopicChanged(topic));
                Ok(())
            })
            .await?;
        }
    }

    async fn save_connection(
        &self,
        info: ConnectionInfo,
        guard: tokio::sync::OwnedMutexGuard<()>,
    ) -> Result<()> {
        self.local(guard, move |client| {
            let mut db = client.0.db.lock();
            let affected = meep_store::transaction(&mut db, |tx| {
                let mut list = replica::connections(tx)?;
                list.connections.retain(|c| c.id != info.id);
                list.connections.push(info);
                list.connections.sort_by(|a, b| a.id.cmp(&b.id));
                replica::replace_connections(tx, &list)
            })?;
            client.emit_topic_changes(affected);
            Ok(())
        })
        .await
    }

    fn emit_topic_changes(&self, topics: Vec<TopicId>) {
        for topic in topics {
            self.emit(Event::TopicChanged(topic));
        }
    }

    fn emit(&self, event: Event) {
        let _ = self.0.events.send(event);
    }

    fn set_status(&self, state: &mut SyncState, status: Status) {
        if state.status != status {
            state.status = status.clone();
            self.emit(Event::Status(status));
        }
    }
}
