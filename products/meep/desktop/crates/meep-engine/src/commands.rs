use super::*;
use meep_policy::{Verdict, decide};

impl Engine {
    pub(super) async fn command(&self, topic: TopicId, command: Command) -> Result<Changes> {
        Ok(self
            .apply(Envelope {
                id: id(),
                topic,
                issued_at: self.0.clock.now(),
                command,
            })
            .await?
            .changes)
    }

    /// Applies a person's envelope in arrival order. Retrying an accepted ID returns
    /// the current revision without running its effects again.
    pub async fn apply(&self, envelope: Envelope) -> Result<Applied> {
        let engine = Engine(self.0.clone(), None);
        let order = self
            .0
            .command_topics
            .lane(envelope.topic)
            .lock_owned()
            .await;
        self.0
            .tasks
            .spawn(async move {
                let _order = order;
                let _id = engine.0.command_ids.lane(envelope.id).lock_owned().await;
                engine.apply_ordered(envelope).await
            })
            .await
            .context("command interrupted")?
    }

    async fn apply_ordered(&self, mut envelope: Envelope) -> Result<Applied> {
        let now = self.0.clock.now();
        envelope.issued_at = envelope.issued_at.min(now);
        let topic = envelope.topic;
        let store = self.0.store.clone();
        let command_id = envelope.id;
        if let Some(receipt) = tokio::task::spawn_blocking(move || store.receipt(command_id))
            .await
            .context("Command receipt lookup interrupted")??
        {
            if !receipt.matches(&envelope) {
                return Err(Error::CommandCollision(envelope.id));
            }
            if matches!(envelope.command, Command::DeleteTopic)
                && self
                    .0
                    .topics
                    .read()
                    .get(&topic)
                    .is_some_and(|s| s.saved.read().replicas.is_empty())
            {
                self.purge_files(topic).await?;
            }
            let slot = self
                .0
                .topics
                .read()
                .get(&topic)
                .cloned()
                .ok_or(Error::UnknownTopic(topic))?;
            let _edit = slot.edit.lock().await;
            return Ok(Applied {
                revision: slot.saved.read().revision,
                changes: vec![],
            });
        }
        if matches!(
            envelope.command,
            Command::CreateTopic { .. } | Command::CreateTopicWithoutSort { .. }
        ) {
            let (state, changes) = envelope.create_at(now)?;
            return self.install(state, changes, Some(envelope)).await;
        }
        let slot = self.slot(topic)?;
        let watches: &[Watch] = match &envelope.command {
            Command::SetContextSources { sources } => sources,
            Command::AddContextSource { source } => std::slice::from_ref(source),
            Command::SetWatch { watches }
            | Command::SetTopicWatches { watches }
            | Command::SetRoutineWatches { watches, .. } => watches,
            Command::SetRoutine { routine, .. } => &routine.watches,
            _ => &[],
        };
        for watch in watches.iter().filter(|w| w.connection == "topic") {
            let source = watch
                .key
                .parse()
                .map_err(|_| Error::InvalidBinding("Expected a source topic ID".into()))?;
            self.slot(source)?;
        }
        let effect = match &envelope.command {
            Command::Reconnect { connection } => {
                let account = self.account(connection)?;
                if !self.0.connectors.read().contains_key(connection) {
                    return Err(Error::UnknownConnection(connection.clone()));
                }
                if !depends_on(&slot.saved.read().state.topic, &account) {
                    return Err(Error::UnknownConnection(connection.clone()));
                }
                Some(effects::Target::Reconnect(connection.clone()))
            }
            Command::StartRoutine { routine, variables } => {
                let (binding, generation) = self.binding(topic, routine)?;
                self.ensure_manual_routine(topic, routine)?;
                Some(effects::Target::Run {
                    binding,
                    generation,
                    variables: variables.clone(),
                })
            }
            _ => None,
        };
        // File mutations and topic deletion share an ordering lane. Other topic
        // workers may commit while the blob is flushed, so apply to fresh state afterwards.
        let _file = match &envelope.command {
            Command::DeleteFile { .. }
            | Command::DeleteTopic
            | Command::Answer {
                suggestion: Suggestion::ChooseFileRevision { .. },
                ..
            } => Some(slot.files.lock().await),
            _ => None,
        };
        let file_revision = match &envelope.command {
            Command::DeleteFile { path } => {
                slot.saved.read().state.clone().apply_at(&envelope, now)?;
                let blobs = self.0.blobs.clone();
                let path = path.clone();
                Some(
                    tokio::task::spawn_blocking(move || blobs.delete(topic, &path, command_id.0))
                        .await
                        .context("File deletion interrupted")??,
                )
            }
            Command::Answer {
                suggestion:
                    Suggestion::ChooseFileRevision {
                        path,
                        current,
                        candidate,
                        use_candidate,
                    },
                ..
            } => {
                slot.saved.read().state.clone().apply_at(&envelope, now)?;
                let selected = if *use_candidate { *candidate } else { *current };
                Some(
                    self.select_file(topic, path.clone(), *current, selected, command_id.0)
                        .await?,
                )
            }
            _ => None,
        };
        let guard = slot.edit.clone().lock_owned().await;
        let mut next = slot.draft();
        if let Some(effect) = effect {
            next.queue_effect(envelope.id.0, effect, Ref::Topic);
        }
        if let Command::CancelRun { task } = envelope.command
            && !matches!(next.runs.get(&task), Some(Work::Poll(_) | Work::Stopped))
        {
            return Err(Error::InvalidBinding("Task has no running agent".into()));
        }
        if let Command::Answer {
            thread, suggestion, ..
        } = &envelope.command
        {
            let source = next
                .state
                .threads
                .iter()
                .find(|t| t.id == *thread)
                .and_then(|t| t.question_source);
            let parked = source.and_then(|id| next.parked_sorts.remove(&id));
            if let Suggestion::SortAgain { message } = suggestion {
                let mut job = parked
                    .filter(|_| source == Some(*message))
                    .ok_or(TopicError::SuggestionNotOffered(*thread))?;
                job.retry_at = None;
                job.failures = 0;
                job.retry_reason = None;
                next.intake.push_front(job);
                next.refresh_sort_retry(*thread);
            }
        }
        let mut changes = next.state.apply_at(&envelope, now)?;
        match &envelope.command {
            Command::DeleteTopic => {
                next = serde_json::from_value(serde_json::to_value(&next.state)?)?;
                let collect = {
                    let old = slot.saved.read();
                    next.revision = old.revision;
                    next.replicas.clone_from(&old.replicas);
                    if !next.replicas.is_empty() {
                        next.retired_state = Some(Box::new(old.state.clone()));
                    }
                    next.replicas.is_empty()
                };
                let applied = self
                    .write(slot.clone(), guard, next, vec![], Some(envelope))
                    .await?;
                if collect {
                    self.purge_files(topic).await?;
                }
                return Ok(applied);
            }
            Command::DeleteFile { path } => {
                next.state.deleted_files.insert(
                    path.clone(),
                    file_revision.context("Missing file deletion revision")?,
                );
            }
            Command::ArchiveThread { thread } => {
                next.intake.retain(|p| p.thread != *thread);
                next.refresh_sort_retry(*thread);
                next.parked_sorts.retain(|_, p| p.thread != *thread);
            }
            Command::DeleteTask { task } => {
                next.conversations.remove(task);
                next.conversation_history.remove(task);
                next.task_handles.remove(task);
                next.pending_messages.remove(task);
                if let Some(Work::Poll(handle)) = next.runs.remove(task) {
                    next.queue_effect(
                        envelope.id.0,
                        effects::Target::Cancel(handle),
                        Ref::Task(*task),
                    );
                }
                next.proposals.remove(task);
                next.evidence_holds.remove(task);
                next.effects
                    .retain(|e| e.task.as_ref().is_none_or(|t| t.id != *task));
                next.deliveries.retain(|_, d| d.task != *task);
            }
            _ => {}
        }
        if let Command::Answer {
            suggestion: Suggestion::ChooseFileRevision { path, .. },
            ..
        } = &envelope.command
            && let Some(head) = file_revision
        {
            changes.extend(next.state.refresh_file_reviews(path, head, now));
        }
        match &envelope.command {
            Command::Reply { thread, text } => next.queue_reply(*thread, text, envelope.id.0),
            Command::Approve { task, .. }
            | Command::Answer {
                task_id: task,
                suggestion: Suggestion::DraftReply { .. },
                ..
            } => next.queue_approval(*task, envelope.id.0, false),
            Command::SendBack { task, .. } | Command::MoveTask { task, .. }
                if !changes.is_empty() =>
            {
                next.proposals.remove(task);
            }
            _ => {}
        }
        match &envelope.command {
            Command::Answer {
                task_id,
                suggestion: Suggestion::DraftReply { .. },
                ..
            } => {
                if next
                    .state
                    .tasks
                    .iter()
                    .any(|task| task.id == *task_id && task.column == Column::InProgress)
                {
                    next.runs.insert(*task_id, Work::Stopped);
                }
            }
            Command::Approve { task, .. }
            | Command::CancelRun { task }
            | Command::StartTask { task }
            | Command::StartTaskWithInput { task, .. }
            | Command::SendBack { task, .. }
            | Command::MoveTask { task, .. }
                if !changes.is_empty() =>
            {
                if matches!(envelope.command, Command::CancelRun { .. })
                    && let Some(c) = next.conversations.get_mut(task)
                {
                    c.status = "cancelled".into();
                }
                // Answering the conversation's prompt lets its turn finish on its own.
                let answering_prompt = matches!(
                    envelope.command,
                    Command::Approve { .. } | Command::SendBack { .. }
                ) && session::session_task(&next) == Some(*task);
                let work = if answering_prompt {
                    None
                } else {
                    next.runs.remove(task)
                };
                let cancelled = matches!(work, Some(Work::Poll(_) | Work::Stopped));
                if let Some(Work::Poll(handle)) = work {
                    next.queue_effect(
                        envelope.id.0,
                        effects::Target::Cancel(handle),
                        Ref::Task(*task),
                    );
                }
                if cancelled
                    && matches!(
                        envelope.command,
                        Command::MoveTask {
                            column: Column::Todo,
                            ..
                        }
                    )
                {
                    next.runs.insert(*task, Work::Stopped);
                }
            }
            Command::Chat {
                message_id,
                task_id,
                text,
                queue,
            } => {
                next.inbox
                    .message(ThreadId(message_id.0), *task_id, text.trim(), *queue);
            }
            Command::SetRoutine { routine } => changes.extend(
                self.configure_routine(&mut next, routine, envelope.id, now)
                    .map_err(|e| Error::InvalidBinding(e.to_string()))?,
            ),
            _ => {}
        }
        if !changes.is_empty() {
            session_command(&mut next, &envelope.command, now)?;
        }
        if let Command::Approve { task, .. }
        | Command::SendBack { task, .. }
        | Command::MoveTask {
            task,
            column: Column::Todo,
        } = envelope.command
            && !changes.is_empty()
        {
            changes.extend(routines::start_assigned(
                &mut next,
                task,
                &Causality::default(),
                now,
            )?);
        }
        routines::on_changes(&mut next, &changes, &Causality::default());
        let is_reply = matches!(envelope.command, Command::Reply { .. });
        let mut applied = self
            .write(slot.clone(), guard, next, changes, Some(envelope))
            .await?;
        if is_reply {
            self.deliver_effects(topic).await?;
            applied.revision = self.slot(topic)?.saved.read().revision;
        }

        Ok(applied)
    }

    /// Resolve an offered inbox choice.
    pub async fn answer(
        &self,
        topic: TopicId,
        thread: ThreadId,
        suggestion: Suggestion,
    ) -> Result<Changes> {
        let expected_review = self
            .slot(topic)?
            .saved
            .read()
            .state
            .threads
            .iter()
            .find(|t| t.id == thread)
            .map(|t| t.review_version);
        self.command(
            topic,
            Command::Answer {
                thread,
                expected_review,
                suggestion,
                task_id: id(),
            },
        )
        .await
    }
    /// Approve work, optionally learning a standing Allow rule.
    pub async fn approve(
        &self,
        topic: TopicId,
        task: TaskId,
        edited_draft: Option<String>,
        always: bool,
    ) -> Result<Changes> {
        self.command(
            topic,
            Command::Approve {
                task,
                expected_review: self
                    .topic(topic)?
                    .tasks
                    .iter()
                    .find(|t| t.id == task)
                    .map(|t| t.review_version),
                edited_draft,
                always,
                rule_id: id(),
            },
        )
        .await
    }
    /// Return a task to the worker with a revision note.
    pub async fn send_back(
        &self,
        topic: TopicId,
        task: TaskId,
        note: impl Into<String>,
    ) -> Result<Changes> {
        self.command(
            topic,
            Command::SendBack {
                task,
                expected_review: self
                    .topic(topic)?
                    .tasks
                    .iter()
                    .find(|t| t.id == task)
                    .map(|t| t.review_version),
                note: note.into(),
            },
        )
        .await
    }
    /// Move a task to another column.
    pub async fn move_task(&self, topic: TopicId, task: TaskId, column: Column) -> Result<Changes> {
        self.command(topic, Command::MoveTask { task, column })
            .await
    }
    /// Add work the topic agent planned: for the person, for itself later, or for a
    /// sub-agent run.
    pub async fn plan_task(
        &self,
        topic: TopicId,
        title: impl Into<String>,
        brief: impl Into<String>,
        owner: meep_topic::InboxAssignment,
    ) -> Result<TaskId> {
        let task = id();
        self.command(
            topic,
            Command::PlanTask {
                id: task,
                title: title.into(),
                brief: brief.into(),
                owner,
            },
        )
        .await?;
        Ok(task)
    }
    /// Add work to the board.
    pub async fn add_task(&self, topic: TopicId, title: impl Into<String>) -> Result<Changes> {
        self.command(
            topic,
            Command::AddTask {
                id: id(),
                title: title.into(),
            },
        )
        .await
    }
    /// Write to the topic agent. The topic worker delivers the reply asynchronously.
    pub async fn chat(&self, topic: TopicId, text: impl Into<String>) -> Result<Changes> {
        self.command(
            topic,
            Command::Chat {
                message_id: id(),
                text: text.into(),
                task_id: id(),
                queue: false,
            },
        )
        .await
    }
    /// Record a reply on an existing thread.
    pub async fn reply(
        &self,
        topic: TopicId,
        thread: ThreadId,
        text: impl Into<String>,
    ) -> Result<Changes> {
        self.command(
            topic,
            Command::Reply {
                thread,
                text: text.into(),
            },
        )
        .await
    }
    /// Propose a reply written by an agent. Topic policy decides as for an inbox reply
    /// draft: an Allow rule delivers it, a Deny rule refuses it without a change, and
    /// otherwise the draft waits in Needs You for the person's approval.
    pub async fn propose_reply(
        &self,
        topic: TopicId,
        thread: ThreadId,
        text: impl Into<String>,
    ) -> Result<Task> {
        let task: TaskId = id();
        let text = text.into();
        self.update(topic, &Causality::default(), |s, now| {
            let mut next = s.state.clone();
            let mut changes = next.propose_reply(thread, text, task, now)?;
            let action = next
                .tasks
                .iter()
                .find(|t| t.id == task)
                .and_then(|t| t.action.clone());
            match action.as_ref().map(|a| decide(&next.topic.rules, a)) {
                Some(Verdict::Refuse(rule)) => return Err(TopicError::ActionDenied(rule).into()),
                Some(Verdict::Run(_)) => {
                    changes.extend(next.approve(task, None, now)?);
                    s.state = next;
                    s.queue_approval(task, Uuid::new_v4(), true);
                }
                _ => s.state = next,
            }
            Ok(changes)
        })
        .await?;
        self.deliver_effects(topic).await?;
        self.read_topic(topic, |s| s.tasks.iter().find(|t| t.id == task).cloned())?
            .ok_or(Error::Topic(TopicError::UnknownTask(task)))
    }
    /// Replace the mission.
    pub async fn set_mission(&self, topic: TopicId, mission: impl Into<String>) -> Result<Changes> {
        self.command(
            topic,
            Command::SetMission {
                mission: mission.into(),
            },
        )
        .await
    }
    /// Append a new goal to the topic.
    pub async fn add_goal(&self, topic: TopicId, goal: Goal) -> Result<Changes> {
        self.command(topic, Command::AddGoal { goal }).await
    }
    /// Append a policy entry with a fresh ID.
    pub async fn add_rule(
        &self,
        topic: TopicId,
        text: impl Into<String>,
        effect: RuleEffect,
    ) -> Result<Changes> {
        self.command(
            topic,
            Command::AddRule {
                rule: Rule {
                    id: id(),
                    text: text.into(),
                    effect,
                    from_task: None,
                    created_at: self.0.clock.now(),
                },
            },
        )
        .await
    }
    /// Remove a policy entry.
    pub async fn remove_rule(&self, topic: TopicId, rule: RuleId) -> Result<Changes> {
        self.command(topic, Command::RemoveRule { rule }).await
    }
    /// Replace the built-in sorter's subscriptions.
    pub async fn set_watch(&self, topic: TopicId, watches: Vec<Watch>) -> Result<Changes> {
        self.command(topic, Command::SetWatch { watches }).await
    }
    /// Edit the combined source list while retaining each existing binding.
    pub async fn set_topic_watches(&self, topic: TopicId, watches: Vec<Watch>) -> Result<Changes> {
        self.command(topic, Command::SetTopicWatches { watches })
            .await
    }

    /// Replace one binding's source list.
    pub async fn set_routine_watches(
        &self,
        topic: TopicId,
        routine: String,
        watches: Vec<Watch>,
    ) -> Result<Changes> {
        self.command(topic, Command::SetRoutineWatches { routine, watches })
            .await
    }

    /// Mark a conversation as read.
    pub async fn mark_seen(&self, topic: TopicId, thread: ThreadId) -> Result<Changes> {
        self.command(topic, Command::MarkSeen { thread }).await
    }
    /// Add a fact with provenance.
    pub async fn add_fact(&self, topic: TopicId, fact: Fact) -> Result<Changes> {
        self.command(topic, Command::AddFact { fact }).await
    }
    /// Remove a fact from context.
    pub async fn remove_fact(&self, topic: TopicId, fact: FactId) -> Result<Changes> {
        self.command(topic, Command::RemoveFact { fact }).await
    }
}

fn stop(
    s: &mut StoredTopic,
    task: TaskId,
    detail: String,
    now: DateTime<Utc>,
) -> Result<Vec<Change>> {
    s.runs.insert(task, Work::Stopped);
    Ok(s.state.progress(task, detail, now)?)
}

pub(super) fn submission(
    s: &mut StoredTopic,
    task: TaskId,
    action: Action,
    result: String,
    draft: Option<String>,
    now: DateTime<Utc>,
) -> Result<Vec<Change>> {
    match decide(&s.state.topic.rules, &action) {
        Verdict::Refuse(rule) => stop(
            s,
            task,
            format!("Refused {} by rule {rule}.", action.label),
            now,
        ),
        Verdict::Run(_) if let Err(reason) = s.state.check_action_evidence(&action) => {
            if reason == TopicError::DisputedEvidence {
                s.evidence_holds.insert(task);
            }
            s.runs.remove(&task);
            Ok(s.state.submit(task, action, result, draft, now)?)
        }
        Verdict::Ask(rule) if rule.is_some() || !s.default_activation(task, &action) => {
            s.runs.remove(&task);
            Ok(s.state.submit(task, action, result, draft, now)?)
        }
        Verdict::Run(_) | Verdict::Ask(_) => {
            let changes = s.state.complete(task, result, now)?;
            let completed = s
                .state
                .tasks
                .iter_mut()
                .find(|t| t.id == task)
                .ok_or(TopicError::UnknownTask(task))?;
            completed.log.push(LogEntry {
                origin: None,
                at: now,
                text: format!("Allowed “{}” by policy.", action.label),
            });
            completed.action = Some(action);
            completed.draft = draft;
            s.queue_approval(task, Uuid::new_v4(), true);
            s.runs.remove(&task);
            Ok(changes)
        }
    }
}

/// What the topic's conversation hears about a person's command on it.
fn session_command(
    next: &mut StoredTopic,
    command: &Command,
    now: chrono::DateTime<chrono::Utc>,
) -> std::result::Result<(), TopicError> {
    let Some(session) = session::session_task(next) else {
        return Ok(());
    };
    match command {
        Command::SendBack { task, note, .. } if *task == session => {
            let label = next
                .state
                .tasks
                .iter()
                .find(|t| t.id == session)
                .and_then(|t| t.log.iter().rev().find(|l| l.text.starts_with("Requested")))
                .map(|l| l.text.clone())
                .unwrap_or_else(|| "your request".into());
            next.inbox.note(
                "The person declined:",
                &format!("{label} ({})", note.trim()),
            );
        }
        // Stopping the conversation's work puts the to-dos it was on back in the list.
        Command::CancelRun { task } if *task == session => {
            let doing: Vec<TaskId> = next
                .state
                .tasks
                .iter()
                .filter(|t| {
                    t.assignment == Some(InboxAssignment::Session) && t.column == Column::InProgress
                })
                .map(|t| t.id)
                .collect();
            for id in doing {
                next.state.move_task(id, Column::Todo, now)?;
                next.inbox.unsee(id);
            }
        }
        _ => {}
    }
    Ok(())
}
