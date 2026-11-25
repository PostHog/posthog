use super::*;
use anyhow::{Context, Result, ensure};
use meep_store::Connection as Database;
use std::collections::BTreeSet;

/// Server-only state committed with a workspace view.
#[derive(Clone, Serialize, Deserialize)]
pub struct StoredView {
    /// Monotonic record version including transcript and metadata edits.
    pub version: u64,
    /// Snapshot replicated to paired devices.
    pub view: meep_wire::views::View,
    /// Commands accepted on this view, retained for outbox replay.
    pub receipts: BTreeMap<Uuid, meep_wire::views::ViewEnvelope>,
    /// PostHog run to resume for each conversation.
    pub handles: BTreeMap<Uuid, ViewRun>,
    /// Hash of the credential issued to the active run.
    pub capability: Option<String>,
}
/// Project-bound Tasks handle for a view conversation.
#[derive(Clone, Serialize, Deserialize)]
pub struct ViewRun {
    /// PostHog API origin that supplied the handle.
    pub origin: String,
    /// Owning PostHog project.
    pub project: u64,
    /// Remote task and run identity.
    pub handle: RunHandle,
}
/// Durable command identity. Legacy stores retained only the owning topic.
#[derive(Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum CommandReceipt {
    /// Identity and original operation of a newly accepted command.
    Accepted {
        /// Owning topic.
        topic: TopicId,
        /// Display time supplied by the client, bounded by the accepting server clock.
        #[serde(default)]
        issued_at: Option<DateTime<Utc>>,
        /// Original operation and arguments.
        command: Box<Command>,
    },
    /// Topic recorded before payload validation was introduced.
    Legacy(TopicId),
}

impl CommandReceipt {
    fn new(envelope: &Envelope) -> Self {
        Self::Accepted {
            topic: envelope.topic,
            issued_at: Some(envelope.issued_at),
            command: Box::new(envelope.command.clone()),
        }
    }
    pub(super) fn matches(&self, envelope: &Envelope) -> bool {
        match self {
            Self::Accepted { topic, command, .. } => {
                *topic == envelope.topic && command.as_ref() == &envelope.command
            }
            Self::Legacy(topic) => *topic == envelope.topic,
        }
    }
}

/// Atomic persistence for a single authoritative engine. A write commits the snapshot,
/// command receipt, change cursor and search documents together or leaves all unchanged.
pub trait Store: Send + Sync {
    /// Workspace view snapshots and private authoring receipts.
    fn load_views(&self) -> Result<Vec<StoredView>>;
    /// Replace one view, its receipts and resumable runs atomically.
    fn save_view(&self, previous: u64, view: &StoredView) -> Result<()>;
    /// All current snapshots, including the engine's private resumable worker state.
    fn load(&self) -> Result<Vec<StoredTopic>>;
    /// Read the public snapshot committed with the change cursor, including during publication to workers.
    fn snapshot(&self, topic: TopicId) -> Result<Option<TopicSnapshot>>;
    /// Identity of a previously accepted command.
    fn receipt(&self, id: CommandId) -> Result<Option<CommandReceipt>>;
    /// Commit at the expected previous revision (zero for creation). A receipt alone
    /// does not advance the revision or cursor. Changes update the search index.
    fn save(
        &self,
        previous: u64,
        next: &StoredTopic,
        command: Option<&Envelope>,
        changes: &[Change],
    ) -> Result<()>;
    /// Commit a transition when its authoritative prior state is already in memory.
    fn save_transition(
        &self,
        prior: &StoredTopic,
        next: &StoredTopic,
        command: Option<&Envelope>,
        changes: &[Change],
    ) -> Result<()> {
        self.save(prior.revision, next, command, changes)
    }
    /// Revisions strictly after the supplied cursor and the last cursor returned.
    fn changes_since(&self, cursor: u64) -> Result<(Vec<TopicRevision>, u64)> {
        let rows = self.revision_page(cursor, usize::MAX)?;
        let end = rows.last().map_or(cursor, |row| row.0);
        Ok((
            rows.into_iter().map(|(_, revision)| revision).collect(),
            end,
        ))
    }
    /// Return at most `limit` revisions with their actual exclusive resume cursors.
    fn revision_page(&self, cursor: u64, limit: usize) -> Result<Vec<(u64, TopicRevision)>>;
    /// Synchronize from current snapshots, emitting each topic at its latest cursor.
    fn bootstrap_page(&self, cursor: u64, limit: usize) -> Result<Vec<(u64, TopicRevision)>> {
        let mut latest = BTreeMap::new();
        for row in self.revision_page(cursor, usize::MAX)? {
            latest.insert(row.1.topic, row);
        }
        let mut rows: Vec<_> = latest.into_values().collect();
        rows.sort_by_key(|r| r.0);
        rows.truncate(limit);
        Ok(rows)
    }
    /// Prune durable delivery history beyond the offline replay window.
    fn maintain(&self) -> Result<()> {
        Ok(())
    }
    /// Current global change cursor, or zero for an empty store.
    fn cursor(&self) -> Result<u64>;
    /// Insert or replace a connection's entire public configuration.
    fn put_connection(&self, account: Connection, credentials: Uuid) -> Result<()>;
    /// Secret-store generation committed with the public connection configuration.
    fn credential_version(&self, account: &str) -> Result<Option<Uuid>>;
    /// Search live threads, tasks and facts.
    fn search(&self, query: &str, limit: usize) -> Result<Vec<SearchHit>>;
    /// List registered accounts.
    fn connections(&self) -> Result<Vec<Connection>>;
    /// Add a previously unknown account.
    fn add_connection(&self, account: Connection) -> Result<()>;
    /// Update the health of a registered account.
    fn set_health(&self, account: &str, health: Health) -> Result<()>;
    /// Check whether delivery completed for this event.
    fn seen(&self, connection: &str, external_id: &str) -> Result<bool>;
    /// Remember a completed fan-out.
    fn record_seen(&self, connection: &str, external_id: &str) -> Result<()>;
}

/// SQLite records and search index in a directory owned by a single engine.
pub struct SqliteStore {
    db: Mutex<Database>,
    reader: Mutex<Database>,
    registry: Mutex<Registry>,
    receipts: Mutex<meep_ingest::StoreSeenStore>,
    _lock: std::fs::File,
}

// The previous store wrapped every topic snapshot in this JSON envelope.
// Require its original fields so malformed records still abort the import.
#[derive(Deserialize)]
struct LegacyRecord {
    #[serde(rename = "kind")]
    _kind: String,
    #[serde(rename = "id")]
    _id: String,
    rev: u64,
    body: serde_json::Value,
    deleted: bool,
}

impl SqliteStore {
    fn page(
        &self,
        cursor: u64,
        limit: usize,
        bootstrap: bool,
    ) -> Result<Vec<(u64, TopicRevision)>> {
        let db = self.reader.lock();
        let query = if bootstrap {
            "SELECT MAX(cursor),topic,revision FROM topic_revisions
             WHERE cursor>?1 GROUP BY topic ORDER BY MAX(cursor) LIMIT ?2"
        } else {
            "SELECT cursor,topic,revision FROM topic_revisions
             WHERE cursor>?1 ORDER BY cursor LIMIT ?2"
        };
        let mut stmt = db.prepare(query)?;
        let mut rows = stmt.query([
            i64::try_from(cursor).unwrap_or(i64::MAX),
            i64::try_from(limit).unwrap_or(i64::MAX),
        ])?;
        let mut result = Vec::new();
        while let Some(row) = rows.next()? {
            result.push((
                row.get::<_, i64>(0)?.try_into()?,
                TopicRevision {
                    topic: row.get::<_, String>(1)?.parse()?,
                    revision: row.get::<_, i64>(2)?.try_into()?,
                },
            ));
        }
        Ok(result)
    }

    /// Open or initialize a private directory, importing previous sync-format snapshots.
    pub fn open(dir: impl AsRef<Path>) -> Result<Self> {
        let dir = dir.as_ref();
        std::fs::create_dir_all(dir)?;
        let lock = std::fs::File::options()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(dir.join("engine.lock"))?;
        lock.try_lock()
            .context("another engine owns this topic directory")?;
        let path = dir.join("topics.sqlite");
        let mut db = Database::open(&path)?;
        db.pragma_update(None, "journal_mode", "WAL")?;
        meep_store::initialize(&db)?;
        meep_store::transaction(&mut db, |tx| {
            tx.execute_batch("CREATE TABLE IF NOT EXISTS topic_revisions (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL, revision INTEGER NOT NULL
            )")?;
            let has_time:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM pragma_table_info('topic_revisions') WHERE name='committed_at')",[],|r|r.get(0))?;
            if !has_time {
                tx.execute_batch("ALTER TABLE topic_revisions ADD COLUMN committed_at INTEGER NOT NULL DEFAULT 0;
                    UPDATE topic_revisions SET committed_at=unixepoch()")?;
            }
            tx.execute_batch(
                "CREATE INDEX IF NOT EXISTS topic_cursor ON topic_revisions(topic,cursor)",
            )?;
            for (id, record) in meep_store::list::<LegacyRecord>(tx, "meep-sync/cache/topic")? {
                if record.deleted
                    || meep_store::get::<StoredTopic>(tx, "engine/topic", &id)?.is_some()
                {
                    continue;
                }
                let mut saved: StoredTopic = serde_json::from_value(record.body)?;
                ensure!(
                    saved.state.topic.id.to_string() == id,
                    "topic record contains a different ID"
                );
                saved.revision = record.rev.max(1);
                routines::migrate(&mut saved);
                save_sql(tx, 0, &saved, None, None, &stored_body(&saved)?)?;
            }
            for (_, body) in meep_store::list::<serde_json::Value>(tx, "engine/topic")? {
                let legacy_passive = body["topic"].get("context_sources").is_none();
                let unguarded = body["default_sort_removed"].is_boolean()
                    || body.get("default_sort_removed").is_none();
                let old_context = body["topic"].get("fallback").is_none()
                    || body["topic"]["settings"].get("assign_tasks").is_some()
                    || body["tasks"]
                        .as_array()
                        .is_some_and(|tasks| tasks.iter().any(|t| t.get("assignee").is_some()));
                let mut saved: StoredTopic = serde_json::from_value(body)?;
                if old_context
                    || ((legacy_passive || unguarded)
                        && !saved.state.topic.context_sources.is_empty())
                    || !saved.jobs.is_empty()
                    || saved.routines.values().any(|r| r.workflow.is_some())
                {
                    let previous = saved.revision;
                    routines::migrate(&mut saved);
                    saved.revision += 1;
                    save_sql(tx, previous, &saved, None, None, &stored_body(&saved)?)?;
                }
            }
            if meep_store::get::<bool>(tx, "engine/meta", "full-search")? != Some(true) {
                tx.execute("DELETE FROM search_documents", [])?;
                for (_, topic) in meep_store::list::<StoredTopic>(tx, "engine/topic")? {
                    reindex(tx, None, &topic.state)?;
                }
                meep_store::put(tx, "engine/meta", "full-search", &true)?;
            }
            Ok(())
        })?;
        Ok(Self {
            db: Mutex::new(db),
            reader: Mutex::new(Database::open(&path)?),
            registry: Mutex::new(Registry::new(Database::open(&path)?)?),
            receipts: Mutex::new(meep_ingest::StoreSeenStore::new(Database::open(path)?)?),
            _lock: lock,
        })
    }
}

fn has_passive_context(topic: &StoredTopic) -> bool {
    !topic.state.topic.context_sources.is_empty()
        || topic
            .retired_state
            .as_ref()
            .is_some_and(|state| !state.topic.context_sources.is_empty())
}

pub(super) fn stored_body(topic: &StoredTopic) -> Result<String> {
    let mut body = serde_json::to_value(topic)?;
    if has_passive_context(topic) {
        body["default_sort_removed"] = serde_json::json!(if topic.default_sort_removed {
            "passive-context-v1:true"
        } else {
            "passive-context-v1:false"
        });
    }
    Ok(serde_json::to_string(&body)?)
}

fn save_sql(
    db: &Database,
    previous: u64,
    next: &StoredTopic,
    command: Option<&Envelope>,
    prior: Option<&TopicState>,
    body: &str,
) -> Result<()> {
    let topic = next.state.topic.id;
    let key = topic.to_string();
    let current = meep_store::get::<u64>(db, "engine/revision", &key)?.unwrap_or_default();
    ensure!(current == previous, "stale topic revision");
    if next.state.deleted && previous != next.revision {
        db.execute(
            "DELETE FROM records WHERE kind='engine/command' AND json_extract(body,'$.topic')=?1",
            [&key],
        )?;
        meep_store::remove(db, "meep-sync/cache/topic", &key)?;
    }
    if let Some(id) = command {
        let receipt = CommandReceipt::new(id);
        let id = id.id.to_string();
        ensure!(
            meep_store::get::<CommandReceipt>(db, "engine/command", &id)?.is_none(),
            "command already committed"
        );
        meep_store::put(db, "engine/command", &id, &receipt)?;
    }
    if previous != next.revision {
        let loaded;
        let old = if prior.is_none() && previous != 0 {
            loaded = meep_store::get::<StoredTopic>(db, "engine/topic", &key)?;
            loaded.as_ref().map(|t| &t.state)
        } else {
            prior
        };
        reindex(db, old, &next.state)?;
    }
    meep_store::put_json(db, "engine/topic", &key, body)?;
    if previous != next.revision {
        meep_store::put(db, "engine/revision", &key, &next.revision)?;
        db.execute(
            "INSERT INTO topic_revisions(topic, revision,committed_at) VALUES(?1,?2,unixepoch())",
            (&key, i64::try_from(next.revision)?),
        )?;
    }
    Ok(())
}

impl Store for SqliteStore {
    fn maintain(&self) -> Result<()> {
        meep_store::transaction(&mut self.db.lock(), |db| {
            db.execute("DELETE FROM topic_revisions WHERE committed_at<unixepoch('now','-7 days') AND cursor NOT IN (SELECT max(cursor) FROM topic_revisions WHERE committed_at<unixepoch('now','-7 days') GROUP BY topic)",[])?;
            db.execute("DELETE FROM records WHERE updated_ms<unixepoch('now','-30 days')*1000 AND (kind='engine/command' OR kind GLOB 'ingest/seen/*')",[])?;
            Ok(())
        })
    }
    fn bootstrap_page(&self, cursor: u64, limit: usize) -> Result<Vec<(u64, TopicRevision)>> {
        self.page(cursor, limit, true)
    }
    fn load_views(&self) -> Result<Vec<StoredView>> {
        Ok(meep_store::list(&self.db.lock(), "engine/view")?
            .into_iter()
            .map(|(_, v)| v)
            .collect())
    }
    fn save_view(&self, previous: u64, view: &StoredView) -> Result<()> {
        #[derive(Deserialize)]
        struct Version {
            version: u64,
        }
        let key = view.view.id.to_string();
        meep_store::transaction(&mut self.db.lock(), |db| {
            let current =
                meep_store::get::<Version>(db, "engine/view", &key)?.map_or(0, |v| v.version);
            ensure!(
                current == previous && view.version == previous + 1,
                "Stale view revision"
            );
            meep_store::put(db, "engine/view", &key, view)
        })
    }
    fn load(&self) -> Result<Vec<StoredTopic>> {
        Ok(meep_store::list(&self.db.lock(), "engine/topic")?
            .into_iter()
            .map(|(_, s)| s)
            .collect())
    }
    fn snapshot(&self, topic: TopicId) -> Result<Option<TopicSnapshot>> {
        #[derive(Deserialize)]
        struct Record {
            revision: u64,
            #[serde(flatten)]
            state: TopicState,
        }
        let body = meep_store::get_json(&self.reader.lock(), "engine/topic", &topic.to_string())?;
        body.map(|body| {
            let record: Record = serde_json::from_str(&body)?;
            Ok(TopicSnapshot {
                revision: record.revision,
                state: record.state,
            })
        })
        .transpose()
    }
    fn receipt(&self, id: CommandId) -> Result<Option<CommandReceipt>> {
        meep_store::get(&self.reader.lock(), "engine/command", &id.to_string())
    }
    fn save(
        &self,
        previous: u64,
        next: &StoredTopic,
        command: Option<&Envelope>,
        _changes: &[Change],
    ) -> Result<()> {
        let body = stored_body(next)?;
        meep_store::transaction(&mut self.db.lock(), |tx| {
            save_sql(tx, previous, next, command, None, &body)
        })
    }
    fn save_transition(
        &self,
        prior: &StoredTopic,
        next: &StoredTopic,
        command: Option<&Envelope>,
        _changes: &[Change],
    ) -> Result<()> {
        let body = stored_body(next)?;
        meep_store::transaction(&mut self.db.lock(), |tx| {
            save_sql(tx, prior.revision, next, command, Some(&prior.state), &body)
        })
    }
    fn revision_page(&self, cursor: u64, limit: usize) -> Result<Vec<(u64, TopicRevision)>> {
        self.page(cursor, limit, false)
    }
    fn cursor(&self) -> Result<u64> {
        Ok(self
            .reader
            .lock()
            .query_row(
                "SELECT COALESCE(MAX(cursor),0) FROM topic_revisions",
                [],
                |row| row.get::<_, i64>(0),
            )?
            .try_into()?)
    }
    fn put_connection(&self, c: Connection, credentials: Uuid) -> Result<()> {
        meep_store::transaction(&mut self.db.lock(), |db| {
            meep_store::put(db, "connection", &c.id, &c)?;
            meep_store::put(db, "engine/credentials", &c.id, &credentials)
        })
    }
    fn credential_version(&self, account: &str) -> Result<Option<Uuid>> {
        meep_store::get(&self.reader.lock(), "engine/credentials", account)
    }
    fn search(&self, query: &str, limit: usize) -> Result<Vec<SearchHit>> {
        search(&self.reader.lock(), query, limit)
    }
    fn connections(&self) -> Result<Vec<Connection>> {
        self.registry.lock().list()
    }
    fn add_connection(&self, c: Connection) -> Result<()> {
        self.registry.lock().add(c)
    }
    fn set_health(&self, c: &str, h: Health) -> Result<()> {
        self.registry.lock().set_health(c, h)
    }
    fn seen(&self, c: &str, id: &str) -> Result<bool> {
        use meep_ingest::SeenStore;
        Ok(self.receipts.lock().contains(c, id)?)
    }
    fn record_seen(&self, c: &str, id: &str) -> Result<()> {
        use meep_ingest::SeenStore;
        self.receipts.lock().insert(c, id)?;
        Ok(())
    }
}

/// Isolated in-memory engine store. Share an Arc to retain records across engine lifetimes.
#[derive(Default)]
pub struct MemoryStore(Mutex<Memory>);
#[derive(Default)]
struct Memory {
    index: Option<Database>,
    views: BTreeMap<Uuid, StoredView>,
    topics: BTreeMap<TopicId, StoredTopic>,
    commands: BTreeMap<CommandId, CommandReceipt>,
    credentials: BTreeMap<String, Uuid>,
    revisions: Vec<TopicRevision>,
    connections: BTreeMap<String, Connection>,
    seen: BTreeSet<(String, String)>,
}
impl Store for MemoryStore {
    fn load_views(&self) -> Result<Vec<StoredView>> {
        Ok(self.0.lock().views.values().cloned().collect())
    }
    fn save_view(&self, previous: u64, view: &StoredView) -> Result<()> {
        let mut mem = self.0.lock();
        ensure!(
            mem.views.get(&view.view.id).map_or(0, |v| v.version) == previous
                && view.version == previous + 1,
            "Stale view revision"
        );
        mem.views.insert(view.view.id, view.clone());
        Ok(())
    }
    fn load(&self) -> Result<Vec<StoredTopic>> {
        Ok(self.0.lock().topics.values().cloned().collect())
    }
    fn snapshot(&self, topic: TopicId) -> Result<Option<TopicSnapshot>> {
        Ok(self.0.lock().topics.get(&topic).map(|r| TopicSnapshot {
            revision: r.revision,
            state: r.state.clone(),
        }))
    }
    fn receipt(&self, id: CommandId) -> Result<Option<CommandReceipt>> {
        Ok(self.0.lock().commands.get(&id).cloned())
    }
    fn save(
        &self,
        previous: u64,
        next: &StoredTopic,
        command: Option<&Envelope>,
        _changes: &[Change],
    ) -> Result<()> {
        let mut m = self.0.lock();
        let topic = next.state.topic.id;
        ensure!(
            m.topics.get(&topic).map_or(0, |s| s.revision) == previous,
            "stale topic revision"
        );
        if let Some(id) = command {
            ensure!(
                !m.commands.contains_key(&id.id),
                "command already committed"
            );
        }
        if next.state.deleted && previous != next.revision {
            m.commands.retain(|_, receipt| !matches!(receipt, CommandReceipt::Accepted{topic: t,..} if *t == topic));
        }
        if m.index.is_none() {
            let db = Database::open_in_memory()?;
            meep_store::initialize(&db)?;
            m.index = Some(db);
        }
        if previous != next.revision
            && let Some(index) = &m.index
        {
            let tx = index.unchecked_transaction()?;
            reindex(&tx, m.topics.get(&topic).map(|t| &t.state), &next.state)?;
            tx.commit()?;
        }
        if let Some(id) = command {
            m.commands.insert(id.id, CommandReceipt::new(id));
        }
        m.topics.insert(topic, next.clone());
        if next.revision != previous {
            m.revisions.push(TopicRevision {
                topic,
                revision: next.revision,
            });
        }
        Ok(())
    }
    fn revision_page(&self, cursor: u64, limit: usize) -> Result<Vec<(u64, TopicRevision)>> {
        Ok(self
            .0
            .lock()
            .revisions
            .iter()
            .enumerate()
            .skip(usize::try_from(cursor).unwrap_or(usize::MAX))
            .take(limit)
            .map(|(index, revision)| (index as u64 + 1, revision.clone()))
            .collect())
    }
    fn cursor(&self) -> Result<u64> {
        Ok(self.0.lock().revisions.len() as u64)
    }
    fn credential_version(&self, account: &str) -> Result<Option<Uuid>> {
        Ok(self.0.lock().credentials.get(account).copied())
    }
    fn put_connection(&self, c: Connection, credentials: Uuid) -> Result<()> {
        let mut m = self.0.lock();
        m.credentials.insert(c.id.clone(), credentials);
        m.connections.insert(c.id.clone(), c);
        Ok(())
    }
    fn search(&self, query: &str, limit: usize) -> Result<Vec<SearchHit>> {
        match &self.0.lock().index {
            Some(db) => search(db, query, limit),
            None => Ok(vec![]),
        }
    }
    fn connections(&self) -> Result<Vec<Connection>> {
        Ok(self.0.lock().connections.values().cloned().collect())
    }
    fn add_connection(&self, mut c: Connection) -> Result<()> {
        let mut m = self.0.lock();
        ensure!(!m.connections.contains_key(&c.id), "duplicate connection");
        let mut seen = BTreeSet::new();
        c.grants.retain(|t| seen.insert(*t));
        m.connections.insert(c.id.clone(), c);
        Ok(())
    }
    fn set_health(&self, c: &str, h: Health) -> Result<()> {
        self.0
            .lock()
            .connections
            .get_mut(c)
            .context("unknown connection")?
            .health = h;
        Ok(())
    }
    fn seen(&self, c: &str, id: &str) -> Result<bool> {
        Ok(self.0.lock().seen.contains(&(c.into(), id.into())))
    }
    fn record_seen(&self, c: &str, id: &str) -> Result<()> {
        self.0.lock().seen.insert((c.into(), id.into()));
        Ok(())
    }
}

fn search(db: &Database, query: &str, limit: usize) -> Result<Vec<SearchHit>> {
    meep_store::search(db, query, limit)?
        .into_iter()
        .map(|hit| {
            let (topic, object) = hit
                .id
                .split_once('/')
                .context("invalid search document ID")?;
            let subject = match hit.kind.as_str() {
                "topic" => Ref::Topic,
                "thread" => Ref::Thread(object.parse().context("thread ID")?),
                "task" => Ref::Task(object.parse().context("task ID")?),
                "fact" => Ref::Fact(object.parse().context("fact ID")?),
                kind => return Err(anyhow::anyhow!("unknown search kind {kind}")),
            };
            Ok(SearchHit {
                topic: topic.parse().context("search topic ID")?,
                subject,
                snippet: hit.snippet,
            })
        })
        .collect()
}

fn reindex(db: &Database, old: Option<&TopicState>, new: &TopicState) -> Result<()> {
    meep_store::reindex(
        db,
        meep_wire::search_documents(old),
        meep_wire::search_documents(Some(new)),
    )
}
