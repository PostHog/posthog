use super::*;
use meep_ingest::{Event, group_key, route_bindings};
use serde_json::Value;

/// Publish an authenticated producer's report with its supporting evidence.
pub(super) fn publish_report(
    state: &mut TopicState,
    producer: Producer,
    title: &str,
    body: &str,
    sources: ReportSources,
    now: DateTime<Utc>,
) -> anyhow::Result<(ThreadId, Changes)> {
    anyhow::ensure!(
        matches!(producer, Producer::PostHogTask(_) | Producer::Routine(_))
            || (producer == Producer::System && sources.external.is_some()),
        "Expected an authenticated report producer"
    );
    anyhow::ensure!(
        !state.archived && !state.deleted,
        "The publishing topic is inactive"
    );
    let title = title.trim();
    let body = body.trim();
    anyhow::ensure!(
        !title.is_empty() && title.lines().count() == 1 && title.chars().count() <= 300,
        "A report needs a one-line title of up to 300 characters"
    );
    anyhow::ensure!(
        !body.is_empty() && body != title && body.chars().count() <= 16000,
        "Write findings that explain the headline (up to 16000 characters)"
    );
    anyhow::ensure!(
        sources.observation.is_some()
            || !sources.references.is_empty()
            || !sources.evidence.is_empty(),
        "Cite at least one source"
    );
    anyhow::ensure!(
        sources.evidence.len() <= 50
            && sources
                .evidence
                .iter()
                .all(|e| !e.description.trim().is_empty()
                    && e.description.chars().count() <= 2000
                    && !e.source_id.trim().is_empty()
                    && e.source_id.chars().count() <= 2000),
        "Use up to 50 evidence entries with a description and source ID"
    );
    anyhow::ensure!(
        sources
            .impact
            .as_ref()
            .is_none_or(|i| !i.trim().is_empty() && i.chars().count() <= 300)
            && sources
                .proposal
                .as_ref()
                .is_none_or(|p| !p.trim().is_empty() && p.chars().count() <= 2000)
            && sources
                .evidence
                .iter()
                .all(|e| e.kind.as_ref().is_none_or(|k| k.chars().count() <= 32)),
        "Keep the impact to one sentence (300 characters) and the proposal under 2000"
    );
    anyhow::ensure!(
        sources.references.len() <= 32
            && sources
                .references
                .iter()
                .all(|s| !s.trim().is_empty() && s.chars().count() <= 2000),
        "Use up to 32 nonempty source references"
    );
    if matches!(producer, Producer::PostHogTask(_))
        && let Some(previous) = state.threads.iter().find(|t| {
            t.subject == title
                && t.report_sources.as_ref() == Some(&sources)
                && t.messages
                    .first()
                    .is_some_and(|m| m.producer == producer && m.text == body)
        })
    {
        return Ok((previous.id, vec![]));
    }
    let thread: ThreadId = id();
    let author = state.topic.name.clone();
    let origin = Source::Topic(state.topic.id).into_origin(author.clone(), now, None);
    let message = Message {
        id: id(),
        producer,
        origin: Some(origin),
        author,
        at: now,
        text: body.into(),
        external_id: None,
    };
    let mut changes = state.receive(message, thread.to_string(), thread, now)?;
    changes.extend(state.sort(
        thread,
        Decision::Handle {
            summary: body.into(),
            outcomes: vec![],
        },
        now,
    )?);
    let published = state
        .threads
        .iter_mut()
        .find(|t| t.id == thread)
        .context("Missing published report")?;
    published.subject = title.into();
    published.report_sources = Some(sources);
    Ok((thread, changes))
}

impl Engine {
    /// Bring a report from another system, such as a PostHog Scout report, into a
    /// topic's inbox. A report already imported (by its external ID) is left alone.
    pub async fn import_report(
        &self,
        topic: TopicId,
        author: &str,
        title: &str,
        body: &str,
        sources: ReportSources,
    ) -> Result<Option<ThreadId>> {
        let external = sources
            .external
            .clone()
            .context("An imported report needs its external identity")?;
        let known = |s: &TopicState| {
            s.threads.iter().any(|t| {
                t.report_sources
                    .as_ref()
                    .and_then(|r| r.external.as_ref())
                    .is_some_and(|e| e.provider == external.provider && e.id == external.id)
            })
        };
        if self.read_topic(topic, known)? {
            return Ok(None);
        }
        let mut imported = None;
        self.update(topic, &Default::default(), |s, now| {
            if known(&s.state) {
                return Ok(vec![]);
            }
            let (thread, changes) = publish_report(
                &mut s.state,
                Producer::System,
                title,
                body,
                sources.clone(),
                now,
            )?;
            if let Some(message) = s
                .state
                .threads
                .iter_mut()
                .find(|t| t.id == thread)
                .and_then(|t| t.messages.first_mut())
            {
                message.author = author.to_owned();
            }
            imported = Some(thread);
            Ok(changes)
        })
        .await?;
        Ok(imported)
    }

    /// Record that a report's verdict reached the system it was imported from.
    pub async fn mark_report_synced(
        &self,
        topic: TopicId,
        thread: ThreadId,
        outcome: meep_topic::ReportOutcome,
    ) -> Result<()> {
        self.update(topic, &Default::default(), |s, _| {
            if let Some(e) = s
                .state
                .threads
                .iter_mut()
                .find(|t| t.id == thread)
                .and_then(|t| t.report_sources.as_mut())
                .and_then(|r| r.external.as_mut())
            {
                e.synced = Some(outcome);
            }
            Ok(vec![])
        })
        .await?;
        Ok(())
    }

    /// Publish a sourced report in the running task's own topic.
    pub async fn publish_task_report(
        &self,
        topic: TopicId,
        run: &RunHandle,
        title: &str,
        body: &str,
        references: Vec<String>,
    ) -> Result<ThreadId> {
        self.publish_task_report_with_evidence(topic, run, title, body, references, vec![])
            .await
    }

    /// Publish an agent report with described, attributable evidence.
    pub async fn publish_task_report_with_evidence(
        &self,
        topic: TopicId,
        run: &RunHandle,
        title: &str,
        body: &str,
        references: Vec<String>,
        evidence: Vec<ReportEvidence>,
    ) -> Result<ThreadId> {
        self.publish_task_report_to_topic(
            topic,
            topic,
            run,
            title,
            body,
            ReportSources {
                references,
                evidence,
                ..Default::default()
            },
        )
        .await
    }

    /// Publish from a running task into an authorized destination topic.
    #[allow(clippy::too_many_arguments)]
    pub async fn publish_task_report_to_topic(
        &self,
        source_topic: TopicId,
        target_topic: TopicId,
        run: &RunHandle,
        title: &str,
        body: &str,
        sources: ReportSources,
    ) -> Result<ThreadId> {
        let (task, source_name) = {
            let slot = self.slot(source_topic)?;
            let saved = slot.saved.read();
            let task = saved
                .runs
                .iter()
                .find_map(|(id, work)| match work {
                    Work::Poll(h) if h == run => Some(*id),
                    _ => None,
                })
                .context("No active task for this run")?;
            let topic = &saved.state.topic.name;
            let author = saved
                .state
                .tasks
                .iter()
                .find(|item| item.id == task)
                .map_or_else(|| topic.clone(), |item| format!("{topic} · {}", item.title));
            (task, author)
        };
        let mut published = None;
        self.update(target_topic, &Default::default(), |s, now| {
            let (thread, changes) = publish_report(
                &mut s.state,
                Producer::PostHogTask(task),
                title,
                body,
                ReportSources {
                    observation: None,
                    verdict: None,
                    ..sources.clone()
                },
                now,
            )?;
            if let Some(message) = s
                .state
                .threads
                .iter_mut()
                .find(|item| item.id == thread)
                .and_then(|item| item.messages.first_mut())
            {
                message.author = source_name.clone();
                message.origin =
                    Some(Source::Topic(source_topic).into_origin(source_name.clone(), now, None));
            }
            published = Some(thread);
            Ok(changes)
        })
        .await?;
        Ok(published.context("Missing published report")?)
    }

    /// Routes an observation to every matching topic. A replay resumes any unfinished fan-out.
    pub async fn ingest(&self, event: Event) -> Result<Vec<Change>> {
        Ok(self.ingest_routed(event).await?.0)
    }
    /// Returns whether this event has reached any binding, including an acknowledged replay.
    pub async fn ingest_routed(&self, event: Event) -> Result<(Changes, bool)> {
        self.ingest_routed_to(event, None).await
    }

    pub(crate) async fn ingest_routed_to(
        &self,
        event: Event,
        target: Option<meep_topic::WatchId>,
    ) -> Result<(Changes, bool)> {
        use futures_util::{StreamExt, stream::FuturesOrdered};
        let _event = self
            .0
            .deliveries
            .lane((event.connection.clone(), event.external_id.clone()))
            .lock_owned()
            .await;
        let store = self.0.store.clone();
        let connection = event.connection.clone();
        let external = event.external_id.clone();
        let (seen, grants) = tokio::task::spawn_blocking(move || -> anyhow::Result<_> {
            if store.seen(&connection, &external)? {
                return Ok((true, None));
            }
            Ok((
                false,
                store
                    .connections()?
                    .into_iter()
                    .find(|c| c.id == connection)
                    .map(|c| c.grants),
            ))
        })
        .await
        .context("Looking up event routes interrupted")??;
        if seen {
            return Ok((vec![], true));
        }
        let targets: Vec<_> = self
            .0
            .topics
            .read()
            .iter()
            .flat_map(|(id, slot)| {
                let saved = slot.saved.read();
                if saved.state.archived
                    || saved.state.deleted
                    || grants.as_ref().is_some_and(|allowed| !allowed.contains(id))
                {
                    return vec![];
                }
                route_bindings(
                    &event,
                    saved
                        .state
                        .topic
                        .destinations()
                        .filter(|r| !r.binding.is_builtin_sorter() || r.enabled)
                        .filter(|r| {
                            target.is_none_or(|id| {
                                r.binding
                                    .watches
                                    .iter()
                                    .any(|w| w.id == id && event.matches_watch(w))
                            })
                        })
                        .map(|r| (*id, &r.binding)),
                )
            })
            .collect();
        let mut changes = vec![];
        let cause = Causality::default();
        // Queue every target immediately. A slow watcher consumes only its own
        // FIFO lane, even when there are more matches than concurrent writes.
        let writers = tokio::sync::Semaphore::new(32);
        let mut deliveries: FuturesOrdered<_> = targets
            .into_iter()
            .map(|(topic, routine)| {
                self.deliver(
                    topic,
                    &event,
                    Producer::System,
                    &cause,
                    Some((&writers, routine, target)),
                )
            })
            .collect();
        if deliveries.is_empty() {
            return Ok((vec![], false));
        }
        while let Some(result) = deliveries.next().await {
            changes.extend(result?);
        }
        drop(deliveries);
        let store = self.0.store.clone();
        tokio::task::spawn_blocking(move || {
            store.record_seen(&event.connection, &event.external_id)
        })
        .await
        .context("Recording event delivery interrupted")??;
        Ok((changes, true))
    }

    pub(crate) async fn deliver(
        &self,
        topic: TopicId,
        event: &Event,
        producer: Producer,
        cause: &Causality,
        source: Option<(&tokio::sync::Semaphore, String, Option<meep_topic::WatchId>)>,
    ) -> Result<Vec<Change>> {
        let message = event.message_for(id(), producer)?;
        let slot = self.slot(topic)?;
        let guard = slot.edit.clone().lock_owned().await;
        let _writer = match &source {
            Some((semaphore, _, _)) => Some(semaphore.acquire().await.context("fan-out closed")?),
            None => None,
        };
        let mut next = slot.draft();
        if next.state.archived || next.state.deleted {
            if source
                .as_ref()
                .is_some_and(|(_, _, target)| target.is_some())
            {
                return Err(anyhow::anyhow!("Target topic became inactive during delivery").into());
            }
            return Ok(vec![]);
        }
        let mut observation = None;
        if let Some((_, routine, target)) = source {
            let info = next
                .state
                .topic
                .destinations_mut()
                .find(|r| r.binding.id == routine)
                .context("Source routine changed during delivery")?;
            if !info
                .binding
                .watches
                .iter()
                .any(|watch| event.matches_watch(watch) && target.is_none_or(|id| watch.id == id))
            {
                return Err(anyhow::anyhow!("Source moved during delivery").into());
            }
            let binding = info.binding.clone();
            if let Some(previous) = next.observations.iter().find(|o| {
                o.binding.id == routine
                    && o.event.connection == event.connection
                    && o.event.external_id == event.external_id
            }) {
                let key = previous.report.key;
                drop(guard);
                drop(_writer);
                return self.advance_observation(topic, key).await;
            }
            if binding.backend != "system" && binding.backend != "posthog" {
                return Err(anyhow::anyhow!(
                    "Source dispatch is unavailable for routine {routine}"
                )
                .into());
            }
            let key = next.record_observation(&binding, event, None, self.0.clock.now());
            if binding.backend == "posthog" {
                self.commit(slot, guard, next, vec![], cause).await?;
                drop(_writer);
                return self.advance_observation(topic, key).await;
            }
            if self.0.sorter.hosted_decisions() {
                // A watch without an explicitly configured workflow still
                // records its evidence, but cannot ask a person to decide or
                // pretend that an automatic sorter will be provisioned.
                next.transition(
                    key,
                    ObservationOutcome::Finished {
                        reason: "Recorded source observation".into(),
                    },
                    self.0.clock.now(),
                )?;
                self.commit(slot, guard, next, vec![], cause).await?;
                return Ok(vec![]);
            }
            observation = Some(key);
        }
        if next
            .state
            .threads
            .iter()
            .flat_map(|t| &t.messages)
            .any(|m| {
                if m.external_id != message.external_id
                    || matches!(m.producer, Producer::PostHogTask(_))
                {
                    return false;
                }
                match (m.reply_target(), message.reply_target()) {
                    (
                        Some(Source::Connection { connection: a, .. }),
                        Some(Source::Connection { connection: b, .. }),
                    ) => a == b,
                    (a, b) => a == b,
                }
            })
        {
            return Ok(vec![]);
        }
        let now = self.0.clock.now();
        let (changes, receipt, thread, message) =
            receive_event(&mut next.state, event, message, observation.is_some(), now)?;
        if let Some(key) = observation {
            next.transition(
                key,
                ObservationOutcome::Finished {
                    reason: "Queued for source sorting".into(),
                },
                now,
            )?;
        }
        next.intake.push_back(intake::Pending {
            failures: 0,
            sort_step: false,
            instructions: None,
            retry_at: None,
            retry_reason: None,
            suggestion: None,
            parent: None,
            thread,
            message: Some(message),
            event: event.clone(),
            cause: cause.clone(),
            receipt: group_key(event).is_none().then_some(receipt),
        });
        if group_key(event).is_none() {
            return Ok(self.write(slot, guard, next, changes, None).await?.changes);
        }
        self.commit(slot, guard, next, changes, cause).await
    }

    /// Delivers directly into the target inbox with the sending topic as the source.
    pub async fn send_to_topic(
        &self,
        from: TopicId,
        to: TopicId,
        text: impl Into<String>,
        hops: u32,
    ) -> Result<Vec<Change>> {
        self.send(
            from,
            to,
            text.into(),
            Causality {
                hops,
                ..Default::default()
            },
        )
        .await
    }

    pub(super) async fn send(
        &self,
        from: TopicId,
        to: TopicId,
        text: String,
        cause: Causality,
    ) -> Result<Vec<Change>> {
        self.send_identified(
            from,
            to,
            text,
            Producer::User,
            cause,
            Uuid::new_v4().to_string(),
        )
        .await
    }

    pub(super) async fn send_identified(
        &self,
        from: TopicId,
        to: TopicId,
        text: String,
        producer: Producer,
        cause: Causality,
        external_id: String,
    ) -> Result<Vec<Change>> {
        if !self.0.limits.hop_ok(cause.hops) {
            return Err(Error::HopLimit(cause.hops));
        }
        let sender = self.topic(from)?.topic;
        let event = Event {
            connection: "topic".into(),
            kind: "topic".into(),
            channel: sender.id.to_string(),
            author: format!("@{}", sender.name),
            text,
            external_id,
            at: self.0.clock.now(),
            thread_hint: None,
            attributes: Value::Null,
        };
        self.deliver(to, &event, producer, &cause, None).await
    }

    /// Registers an account and its initial grants and health in the durable registry.
    pub fn add_connection(&self, connection: Connection) -> Result<()> {
        self.0.store.add_connection(connection.clone())?;
        self.publish_health(&connection);
        Ok(())
    }

    /// Lists registered accounts in stable ID order.
    pub fn connections(&self) -> Result<Vec<Connection>> {
        Ok(self.0.store.connections()?)
    }

    /// Attaches a live polling implementation to an account, including after reopen.
    pub fn attach_connector(&self, connector: Arc<dyn Connector>) {
        self.0
            .connectors
            .write()
            .insert(connector.name().into(), connector);
    }

    /// Detach a signed-out account from scheduled and explicit polling.
    pub fn detach_connector(&self, id: &str) {
        self.0.connectors.write().remove(id);
    }

    pub(super) fn spawn_connector_worker(&self) {
        if !self.0.clock.automatic() {
            return;
        }
        let weak = Arc::downgrade(&self.0);
        let stop = self.0.stop.clone();
        self.0.tasks.spawn_on(
            async move {
                let run = async move {
                    loop {
                        tokio::time::sleep(std::time::Duration::from_secs(30)).await;
                        let Some(inner) = weak.upgrade() else { break };
                        let engine = Engine(inner, None);
                        // Poll failures are published as health changes on dependent topics.
                        if let Err(error) = engine.poll_connections().await {
                            eprintln!("Could not poll connections: {error:#}");
                        }
                    }
                };
                tokio::select! { _=stop.cancelled()=>{}, _=run=>{} }
            },
            &self.0.runtime,
        );
    }

    pub(super) async fn poll_connections(&self) -> Result<()> {
        let now = self.0.clock.now();
        let mut first_error = None;
        for account in self.connections()? {
            if let Health::Ok { checked_at } = account.health
                && now - checked_at >= chrono::TimeDelta::seconds(30)
                && self.0.connectors.read().contains_key(&account.id)
                && let Err(error) = self.replay(&account.id).await
            {
                first_error.get_or_insert(error);
            }
        }
        first_error.map_or(Ok(()), Err)
    }

    /// Replays from the account's last healthy check or outage start and marks it healthy after delivery.
    pub async fn reconnect(&self, connection: &str) -> Result<Vec<Change>> {
        let account = self.account(connection)?;
        let topic = self.dependent_topics(&account).into_iter().next();
        if let Some(topic) = topic {
            let changes = self
                .command(
                    topic,
                    Command::Reconnect {
                        connection: connection.into(),
                    },
                )
                .await?;
            self.flush_effects(topic).await?;
            return Ok(changes);
        }
        self.replay(connection).await
    }

    pub(super) fn account(&self, id: &str) -> Result<Connection> {
        self.connections()?
            .into_iter()
            .find(|c| c.id == id)
            .ok_or_else(|| Error::UnknownConnection(id.into()))
    }

    /// Serialize account credential or adapter changes with this account's polls.
    pub async fn connection_guard(&self, connection: &str) -> tokio::sync::OwnedMutexGuard<()> {
        self.0
            .polling
            .lane(connection.to_owned())
            .lock_owned()
            .await
    }

    /// Poll a registered connector from its durable watermark.
    pub async fn replay(&self, connection: &str) -> Result<Changes> {
        let poll = self.connection_guard(connection).await;
        let engine = self.clone();
        let id = connection.to_owned();
        let mut account = tokio::task::spawn_blocking(move || engine.account(&id))
            .await
            .context("Reading connection interrupted")??;
        let connector = self
            .0
            .connectors
            .read()
            .get(connection)
            .cloned()
            .ok_or_else(|| Error::UnknownConnection(connection.into()))?;
        let since = match account.health {
            Health::Ok { checked_at } => checked_at,
            Health::Expired { since, .. } | Health::Failing { since, .. } => since,
        };
        let checked_at = self.0.clock.now();
        let mut changes = vec![];
        let events = match connector.poll_routed(since).await {
            Ok(events) => events,
            Err(error) => {
                // Preserve an existing expiry prompt and its earliest replay point.
                if !matches!(account.health, Health::Expired { .. }) {
                    account.health = Health::Failing {
                        since,
                        detail: error.to_string(),
                    };
                    self.save_poll_health(account, poll).await?;
                }
                return Err(error.into());
            }
        };
        for routed in events {
            let event = routed.event;
            if event.connection != connection {
                return Err(
                    anyhow::anyhow!("connector returned an event for another account").into(),
                );
            }
            changes.extend(self.ingest_routed_to(event, routed.watch).await?.0);
        }
        account.health = Health::Ok { checked_at };
        self.save_poll_health(account, poll).await?;
        Ok(changes)
    }

    fn dependent_topics(&self, connection: &Connection) -> Vec<TopicId> {
        self.0
            .topics
            .read()
            .iter()
            .filter_map(|(&id, slot)| {
                depends_on(&slot.saved.read().state.topic, connection).then_some(id)
            })
            .collect()
    }

    async fn save_poll_health(
        &self,
        account: Connection,
        guard: tokio::sync::OwnedMutexGuard<()>,
    ) -> Result<()> {
        let engine = self.clone();
        engine
            .0
            .tasks
            .clone()
            .spawn_blocking(move || {
                let _guard = guard;
                engine
                    .0
                    .store
                    .set_health(&account.id, account.health.clone())?;
                engine.publish_health(&account);
                Ok(())
            })
            .await
            .context("Saving poll health interrupted")?
    }

    fn publish_health(&self, c: &Connection) {
        for topic in self.dependent_topics(c) {
            self.emit(
                topic,
                EngineChange::ConnectionHealth {
                    connection: c.id.clone(),
                    health: c.health.clone(),
                },
            );
        }
    }
}

pub(super) fn receive_event(
    state: &mut TopicState,
    event: &Event,
    message: Message,
    source_material: bool,
    now: DateTime<Utc>,
) -> Result<(Changes, Change, ThreadId, MessageId)> {
    let thread_id: ThreadId = id();
    let key = if let Some(hint) = group_key(event) {
        let key = serde_json::to_string(&(&event.connection, &event.channel, hint))?;
        let key = if source_material {
            format!("observation/{key}")
        } else {
            key
        };
        // Existing stores used the raw hint. Only migrate conversations from this source.
        for previous in &mut state.threads {
            if previous.source_material == source_material
                && previous.key == hint
                && previous
                    .messages
                    .first()
                    .is_some_and(|m| m.reply_target() == message.reply_target())
            {
                previous.key = key.clone();
            }
        }
        key
    } else {
        thread_id.to_string()
    };
    let changes = state.receive(message, key, thread_id, now)?;
    let receipt = changes
        .iter()
        .find(|c| matches!(c.kind, ChangeKind::MessageReceived(..)))
        .context("missing received message")?
        .clone();
    let ChangeKind::MessageReceived(thread, message) = receipt.kind else {
        unreachable!()
    };
    if source_material {
        state
            .threads
            .iter_mut()
            .find(|t| t.id == thread)
            .context("Missing source evidence")?
            .source_material = true;
    }
    Ok((changes, receipt, thread, message))
}
