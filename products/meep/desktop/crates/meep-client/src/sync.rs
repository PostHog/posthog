use crate::{Client, Event, Status, TransportError, replica};
use anyhow::{Context, Result};
use chrono::Utc;
use futures_util::StreamExt;
use meep_wire::{CommandBatch, CommandResult, StreamEvent};
use std::{collections::BTreeMap, sync::Arc, time::Duration};

const FIRST_RETRY: Duration = Duration::from_millis(500);

pub(super) type Cycle = Arc<tokio::sync::OwnedMutexGuard<()>>;

impl Client {
    /// Wakes the background loop immediately, including during backoff. Call on network regain.
    pub fn sync_now(&self) {
        self.0.wake.notify_one();
    }

    /// Pushes commands queued at the start of this pass, pulls every available page and
    /// refreshes connection details. Concurrent sync passes run one at a time.
    pub async fn sync_once(&self) -> Result<()> {
        let cycle = Arc::new(self.0.cycle.clone().lock_owned().await);
        self.set_status(&mut self.0.state.lock(), Status::Syncing);
        match self.exchange(&cycle).await {
            Ok(()) => {
                let mut state = self.0.state.lock();
                state.offline_since = None;
                self.set_status(&mut state, Status::Online);
                Ok(())
            }
            Err(error) => {
                self.disconnected(&error)?;
                Err(error)
            }
        }
    }

    pub(super) fn disconnected(&self, error: &anyhow::Error) -> Result<()> {
        let db = self.0.db.lock();
        let mut state = self.0.state.lock();
        let status = match error.downcast_ref::<TransportError>() {
            Some(TransportError::Unauthorized) => Status::Unauthorized,
            _ => Status::Offline {
                since: *state.offline_since.get_or_insert_with(Utc::now),
                pending: replica::count(&db)?,
            },
        };
        self.set_status(&mut state, status);
        Ok(())
    }

    pub(super) fn observe<T>(&self, result: Result<T, TransportError>) -> Result<T> {
        match result {
            Err(error @ (TransportError::Unauthorized | TransportError::Unavailable(_))) => {
                let error = error.into();
                self.disconnected(&error)?;
                self.sync_now();
                Err(error)
            }
            other => Ok(other?),
        }
    }

    async fn exchange(&self, cycle: &Cycle) -> Result<()> {
        let end = self
            .local((), |c| replica::outbox_end(&c.0.reader.lock()))
            .await?;
        let has_without_sort = self
            .local((), |c| replica::has_without_sort(&c.0.reader.lock()))
            .await?;
        let supports_without_sort = if has_without_sort {
            self.0
                .transport
                .supports_create_topic_without_sort()
                .await?
        } else {
            false
        };
        let has_context_sources = self
            .local((), |c| replica::has_context_sources(&c.0.reader.lock()))
            .await?;
        let supports_context_sources = if has_context_sources {
            self.0.transport.supports_context_sources().await?
        } else {
            false
        };
        self.grant_created_topics(cycle).await?;
        let mut after = 0;
        while after < end {
            let (last, commands) = self
                .local((), move |c| {
                    replica::next_batch(
                        &c.0.reader.lock(),
                        after,
                        end,
                        supports_without_sort,
                        supports_context_sources,
                    )
                })
                .await?;
            if commands.is_empty() {
                break;
            }
            let created = commands.last().is_some_and(|e| {
                matches!(
                    e.command,
                    meep_topic::Command::CreateTopic { .. }
                        | meep_topic::Command::CreateTopicWithoutSort { .. }
                )
            });
            self.push_batch(&CommandBatch { commands }, cycle).await?;
            if created {
                self.grant_created_topics(cycle).await?;
            }
            after = last;
        }
        self.upload_files().await?;
        self.pull(cycle).await?;
        self.refresh_connections().await?;
        self.sync_views(cycle).await?;
        self.sync_workflows().await
    }

    async fn grant_created_topics(&self, cycle: &Cycle) -> Result<()> {
        let access = self
            .local((), |c| replica::requested_access(&c.0.reader.lock()))
            .await?;
        for (topic, connection, command) in access {
            let mut refused = None;
            if self.local((), move |c| Ok(c.0.reader.lock().query_row("SELECT EXISTS(SELECT 1 FROM records WHERE kind='client/visible' AND id=?1 AND deleted=0)", [topic.to_string()], |r| r.get::<_,bool>(0))?)).await? {
                let guard = self.0.accounts.clone().lock_owned().await;
                match self.0.transport.grant_topic(&connection, topic).await {
                    Ok(info) => self.save_connection(info, guard).await?,
                    Err(TransportError::Api { message, .. }) => {
                        refused = Some(format!("Could not grant {connection} access: {message}"))
                    }
                    Err(error) => return Err(error.into()),
                }
            }
            self.local(cycle.clone(), move |c| {
                meep_store::transaction(&mut c.0.db.lock(), |tx| {
                    if let Some(reason) = &refused {
                        meep_store::put(tx, "client/rejected", &command.to_string(), reason)?;
                    }
                    meep_store::remove(tx, "client/requested-access", &topic.to_string())
                })?;
                if let Some(reason) = refused {
                    c.emit(Event::Rejected { command, reason });
                }
                Ok(())
            })
            .await?;
        }
        Ok(())
    }

    async fn push_batch(&self, batch: &CommandBatch, cycle: &Cycle) -> Result<()> {
        let response = self.0.transport.push(batch).await?;
        if response.results.len() != batch.commands.len() {
            return Err(
                TransportError::Protocol("missing or extra command receipts".into()).into(),
            );
        }
        let mut required = BTreeMap::<_, u64>::new();
        let mut applied = vec![];
        let mut refused = vec![];
        let mut rejected = vec![];
        for (envelope, result) in batch.commands.iter().zip(response.results) {
            match result {
                CommandResult::Applied {
                    id,
                    topic,
                    revision,
                } if id == envelope.id && topic == envelope.topic => {
                    applied.push((id, topic));
                    let latest = required.entry(topic).or_default();
                    *latest = (*latest).max(revision);
                }
                CommandResult::Retry { id, reason } if id == envelope.id => {
                    self.local(cycle.clone(), move |client| {client.0.db.lock().execute("INSERT INTO client_command_retry(id,due,delay,reason) VALUES(?1,unixepoch()+1,1,?2)
                        ON CONFLICT(id) DO UPDATE SET delay=min(delay*2,300), due=unixepoch()+min(delay*2,300), reason=excluded.reason",
                        rusqlite::params![id.to_string(),reason])?; Ok(())}).await?;
                }
                CommandResult::Rejected { id, reason } if id == envelope.id => {
                    refused.push((id, envelope.topic));
                    rejected.push(Event::Rejected {
                        command: id,
                        reason,
                    });
                }
                _ => {
                    return Err(TransportError::Protocol(
                        "command receipt identity mismatch".into(),
                    )
                    .into());
                }
            }
        }

        // A refusal is final even if fetching an accepted sibling's snapshot fails.
        if !refused.is_empty() {
            let creates: Vec<_> = batch
                .commands
                .iter()
                .filter(|e| {
                    matches!(
                        e.command,
                        meep_topic::Command::CreateTopic { .. }
                            | meep_topic::Command::CreateTopicWithoutSort { .. }
                    ) && refused.contains(&(e.id, e.topic))
                })
                .map(|e| (e.topic, e.id))
                .collect();
            self.local(cycle.clone(), move |client| {
                let changed = {
                    meep_store::transaction(&mut client.0.db.lock(), |db| {
                        for (topic, id) in creates {
                            rejected.extend(replica::reject_dependents(db, topic, id)?);
                        }
                        for event in &rejected {
                            if let Event::Rejected { command, reason } = event {
                                meep_store::put(
                                    db,
                                    "client/rejected",
                                    &command.to_string(),
                                    reason,
                                )?;
                            }
                        }
                        replica::reconcile_in(db, &refused, &[], None)
                    })?
                };
                for event in rejected {
                    client.emit(event);
                }
                client.emit_topic_changes(changed);
                Ok(())
            })
            .await?;
        }

        // A receipt is not a snapshot: the engine may have performed extra work. Keep
        // the optimistic overlay durable until the corresponding base can replace it.
        let mut snapshots = vec![];
        for (topic, minimum) in required {
            let snapshot = self.0.transport.snapshot(topic).await?;
            if snapshot.state.topic.id != topic || snapshot.revision < minimum {
                return Err(TransportError::Protocol(
                    "snapshot does not cover command receipt".into(),
                )
                .into());
            }
            snapshots.push(snapshot);
        }
        self.commit_sync(cycle, move |db| {
            replica::reconcile(db, &applied, &snapshots, None)
        })
        .await
    }

    async fn commit_sync(
        &self,
        cycle: &Cycle,
        commit: impl FnOnce(&mut meep_store::Connection) -> Result<Vec<meep_topic::TopicId>>
        + Send
        + 'static,
    ) -> Result<()> {
        self.local(cycle.clone(), move |client| {
            let changed = commit(&mut client.0.db.lock())?;
            client.emit_topic_changes(changed);
            Ok(())
        })
        .await
    }

    async fn pull(&self, cycle: &Cycle) -> Result<()> {
        let replica = self
            .local(cycle.clone(), |c| {
                meep_store::transaction(&mut c.0.db.lock(), |tx| {
                    if let Some(id) = meep_store::get(tx, "client/meta", "replica-id")? {
                        return Ok(id);
                    }
                    let id = uuid::Uuid::new_v4();
                    // Existing installations must register for topics that have not changed.
                    meep_store::put(tx, "client/meta", "cursor", &0_u64)?;
                    meep_store::put(tx, "client/meta", "replica-id", &id)?;
                    Ok(id)
                })
            })
            .await?;
        let mut cursor = replica::cursor(&self.0.reader.lock())?;
        let bootstrap = cursor == 0
            || meep_store::get::<bool>(&self.0.reader.lock(), "client/meta", "bootstrapping")?
                .unwrap_or_default();
        loop {
            let page = self
                .0
                .transport
                .replica_page(replica, cursor, bootstrap)
                .await?;
            if page.cursor < cursor || (page.more && page.cursor == cursor) {
                return Err(TransportError::Protocol("invalid change page cursor".into()).into());
            }
            cursor = page.cursor;
            let more = page.more;
            self.commit_sync(cycle, move |db| {
                meep_store::transaction(db, |tx| {
                    if bootstrap {
                        meep_store::put(tx, "client/meta", "bootstrapping", &page.more)?;
                    }
                    for snapshot in &page.topics {
                        if snapshot.state.deleted {
                            meep_store::put(
                                tx,
                                "client/deletion-ack",
                                &snapshot.state.topic.id.to_string(),
                                &snapshot.revision,
                            )?;
                        }
                    }
                    replica::reconcile_in(tx, &[], &page.topics, Some(cursor))
                })
            })
            .await?;
            let topics = meep_store::list::<u64>(&self.0.reader.lock(), "client/deletion-ack")?
                .into_iter()
                .map(|(id, rev)| Ok((id.parse::<meep_topic::TopicId>()?, rev)))
                .collect::<anyhow::Result<std::collections::BTreeMap<_, _>>>()?;
            if !topics.is_empty() {
                let ack = meep_wire::DeletionAck { replica, topics };
                self.0.transport.acknowledge_deletions(&ack).await?;
                self.local(cycle.clone(), move |c| {
                    meep_store::transaction(&mut c.0.db.lock(), |tx| {
                        for topic in ack.topics.keys() {
                            meep_store::remove(tx, "client/deletion-ack", &topic.to_string())?;
                        }
                        Ok(())
                    })
                })
                .await?;
            }
            if !more {
                break;
            }
        }

        Ok(())
    }

    async fn refresh_connections(&self) -> Result<()> {
        let guard = self.0.accounts.clone().lock_owned().await;
        let list = self.0.transport.connections().await?;
        self.local(guard, move |client| {
            let changed = meep_store::transaction(&mut client.0.db.lock(), |tx| {
                replica::replace_connections(tx, &list)
            })?;
            client.emit_topic_changes(changed);
            Ok(())
        })
        .await
    }

    /// Drives synchronization until cancelled by the host. A dropped future leaves committed
    /// edits and their outbox entries available for the next run. Start one loop per client.
    pub async fn run(&self) -> Result<()> {
        let _runner = self
            .0
            .runner
            .try_lock()
            .context("sync loop already running")?;
        let mut delay = FIRST_RETRY;
        loop {
            let error = match self.follow(&mut delay).await {
                Ok(()) => continue,
                Err(error) => error,
            };
            self.disconnected(&error)?;
            match error.downcast_ref::<TransportError>() {
                Some(TransportError::Unauthorized) => self.0.wake.notified().await,
                Some(_) => {
                    let millis = delay.as_millis() as u64;
                    let jittered = Duration::from_millis(rand::random_range(millis / 2..=millis));
                    tokio::select! {
                        _ = tokio::time::sleep(jittered) => delay = (delay * 2).min(Duration::from_secs(60)),
                        _ = self.0.wake.notified() => delay = FIRST_RETRY,
                    }
                }
                None => return Err(error),
            }
        }
    }

    async fn refresh_views(&self) -> Result<()> {
        let guard = Arc::new(self.0.cycle.clone().lock_owned().await);
        self.pull_views(&guard).await
    }

    async fn follow(&self, delay: &mut Duration) -> Result<()> {
        self.sync_once().await?;
        let cursor = replica::cursor(&self.0.reader.lock())?;
        let mut events = self.0.transport.stream(cursor).await?;
        // Unlike topic revisions, connection events have no resumable cursor. Catch changes
        // made between the last list response and subscribing to the live feed.
        self.refresh_connections().await?;
        self.refresh_views().await?;
        loop {
            tokio::select! {
                _ = self.0.wake.notified() => self.sync_once().await?,
                event = events.next() => {
                    let event = event.ok_or_else(|| TransportError::Unavailable("change stream closed".into()))??;
                    *delay = FIRST_RETRY;
                    match event {
                        // Use only the durable page cursor; a stream hint can be duplicated or skip positions.
                        StreamEvent::Topic { cursor, .. } => {
                            let committed = replica::cursor(&self.0.reader.lock())?;
                            if cursor > committed { self.sync_once().await?; }
                        }
                        // A concurrent grant may already be newer than the streamed value.
                        StreamEvent::Connection(_) => self.refresh_connections().await?,
                        StreamEvent::Views => self.refresh_views().await?,
                        StreamEvent::Heartbeat { .. } => { let retry = self.0.db.lock().query_row("SELECT EXISTS(SELECT 1 FROM client_command_retry WHERE due<=unixepoch())", [], |r| r.get::<_,bool>(0))?; if retry {self.sync_once().await?;} }
                    }
                }
            }
        }
    }
}
