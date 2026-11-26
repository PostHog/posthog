use super::*;

impl TopicState {
    /// Appends to the newest matching thread. Uses `new_thread` only if a new one must open.
    pub fn receive(
        &mut self,
        message: Message,
        key: impl Into<String>,
        new_thread: ThreadId,
        now: DateTime<Utc>,
    ) -> Transition {
        let key = key.into();
        if self
            .threads
            .iter()
            .flat_map(|t| &t.messages)
            .any(|m| m.id == message.id)
        {
            return Err(TopicError::DuplicateId(message.id.to_string()));
        }
        let newest = self
            .threads
            .iter()
            .enumerate()
            .filter(|(_, t)| t.key == key)
            .max_by_key(|(_, t)| t.created_at)
            .filter(|(_, t)| !matches!(t.state, ThreadState::Skipped { rule: Some(_), .. }))
            .map(|(index, _)| index);
        let actor = match message.reply_target() {
            Some(Source::User) => Actor::User,
            Some(Source::Topic(id)) => Actor::Topic(id),
            _ => Actor::Inbox(newest.map_or(new_thread, |i| self.threads[i].id)),
        };
        let id = message.id;
        let author = message.author.clone();
        let (thread, change) = if let Some(i) = newest {
            let thread = &mut self.threads[i];
            if thread.question_source.is_none()
                && matches!(thread.state, ThreadState::NeedsYou { .. })
            {
                thread.question_source = thread.messages.last().map(|m| m.id);
            }
            thread.messages.push(message);
            thread.updated_at = now;
            thread.unseen = true;
            (thread.id, ChangeKind::ThreadUpdated(thread.id))
        } else {
            if self.threads.iter().any(|t| t.id == new_thread)
                || self.history.iter().any(|change| {
                    matches!(change.kind,
                    ChangeKind::ThreadJoined { incoming, .. } if incoming == new_thread)
                })
            {
                return Err(TopicError::DuplicateId(new_thread.to_string()));
            }
            let subject = message
                .text
                .lines()
                .find(|line| !line.trim().is_empty())
                .map(str::trim)
                .unwrap_or(&key)
                .to_owned();
            self.threads.push(Thread {
                id: new_thread,
                source_material: false,
                report_sources: None,
                subject,
                summary: String::new(),
                state: ThreadState::Sorting,
                sort_retry: None,
                review_version: 0,
                question_source: None,
                parent_task: None,
                pending_questions: Default::default(),
                messages: vec![message],
                outcomes: vec![],
                key,
                unseen: true,
                created_at: now,
                updated_at: now,
            });
            (new_thread, ChangeKind::ThreadOpened(new_thread))
        };
        Ok(self.record(
            now,
            actor,
            Ref::Thread(thread),
            format!("Received a message from {author}."),
            [change, ChangeKind::MessageReceived(thread, id)],
        ))
    }

    /// Open an inbox report for a finding another system produced. The same report
    /// ID never opens a second thread.
    #[allow(clippy::too_many_arguments)]
    pub fn receive_report(
        &mut self,
        thread: ThreadId,
        message: MessageId,
        report_id: String,
        title: String,
        summary: String,
        url: String,
        at: DateTime<Utc>,
        now: DateTime<Utc>,
    ) -> Transition {
        if self.threads.iter().any(|t| {
            t.report_sources
                .as_ref()
                .and_then(|r| r.external.as_ref())
                .is_some_and(|e| e.id == report_id)
        }) {
            return Err(TopicError::DuplicateId(report_id));
        }
        let text = summary.clone();
        let changes = self.receive(
            Message {
                id: message,
                producer: Producer::System,
                origin: None,
                author: "PostHog".into(),
                at,
                text,
                external_id: Some(report_id.clone()),
            },
            format!("report:{report_id}"),
            thread,
            now,
        )?;
        if let Some(opened) = self.threads.iter_mut().find(|t| t.id == thread) {
            opened.subject = title;
            opened.summary = summary;
            opened.state = ThreadState::Handled;
            opened.report_sources = Some(ReportSources {
                external: Some(ExternalReport {
                    provider: "posthog-scout".into(),
                    id: report_id,
                    url,
                    synced: None,
                }),
                ..Default::default()
            });
        }
        Ok(changes)
    }

    /// Move a provisional intake conversation into the open thread selected for it.
    pub fn join_thread(
        &mut self,
        incoming: ThreadId,
        target: ThreadId,
        now: DateTime<Utc>,
    ) -> Transition {
        let index = self.thread_index(incoming)?;
        let dest = self.thread_index(target)?;
        if index == dest
            || self.threads[index].state != ThreadState::Sorting
            || !self.threads[dest].accepts_follow_up()
        {
            return Err(TopicError::ThreadState(incoming));
        }
        let mut messages = std::mem::take(&mut self.threads[index].messages);
        if self.threads[dest].question_source.is_none()
            && matches!(self.threads[dest].state, ThreadState::NeedsYou { .. })
        {
            self.threads[dest].question_source = self.threads[dest].messages.last().map(|m| m.id);
        }
        self.threads[dest].messages.append(&mut messages);
        self.threads[dest].updated_at = now;
        self.threads[dest].unseen = true;
        self.threads.remove(index);
        for task in &mut self.tasks {
            if task.from_thread == Some(incoming) {
                task.from_thread = Some(target);
            }
            if task.added_by == Actor::Inbox(incoming) {
                task.added_by = Actor::Inbox(target);
            }
        }
        for fact in &mut self.topic.facts {
            if fact.provenance.thread == Some(incoming) {
                fact.provenance.thread = Some(target);
            }
        }
        for entry in &mut self.activity {
            if entry.subject == Ref::Thread(incoming) {
                entry.subject = Ref::Thread(target);
            }
            if entry.actor == Actor::Inbox(incoming) {
                entry.actor = Actor::Inbox(target);
            }
        }
        Ok(self.record(
            now,
            Actor::Agent,
            Ref::Thread(target),
            "Continued this conversation.".into(),
            [ChangeKind::ThreadJoined { incoming, target }],
        ))
    }

    /// Applies a sorter's decision to a thread in Sorting.
    pub fn sort(&mut self, id: ThreadId, decision: Decision, now: DateTime<Utc>) -> Transition {
        let index = self.thread_index(id)?;
        if self.threads[index].state != ThreadState::Sorting {
            return Err(TopicError::ThreadState(id));
        }
        self.apply_inbox_decision(id, decision, now)
    }

    /// Apply the decision for a delivered message, retaining earlier outcomes and unanswered questions.
    pub fn apply_inbox_decision(
        &mut self,
        id: ThreadId,
        decision: Decision,
        now: DateTime<Utc>,
    ) -> Transition {
        let index = self.thread_index(id)?;
        let message = self.threads[index]
            .messages
            .last()
            .ok_or(TopicError::ThreadState(id))?
            .id;
        self.decide_message(id, message, decision, now)
    }

    /// Apply the decision to the exact arrival even if more messages arrived during sorting.
    pub fn decide_message(
        &mut self,
        id: ThreadId,
        message: MessageId,
        decision: Decision,
        now: DateTime<Utc>,
    ) -> Transition {
        let index = self.thread_index(id)?;
        if !self.threads[index].messages.iter().any(|m| m.id == message) {
            return Err(TopicError::ThreadState(id));
        }
        let preserve_question = matches!(self.threads[index].state, ThreadState::NeedsYou { .. });
        let mut kinds = vec![ChangeKind::ThreadUpdated(id)];
        let (state, summary, outcomes, verb) = match decision {
            Decision::Handle { summary, outcomes } => {
                for outcome in &outcomes {
                    match outcome {
                        Outcome::Fact(fact) => {
                            self.fact_index(*fact)?;
                        }
                        Outcome::Task(task) => {
                            self.task_index(*task)?;
                        }
                        _ => (),
                    }
                }
                (ThreadState::Handled, summary, outcomes, "Handled")
            }
            Decision::Ask {
                summary,
                reason,
                suggestions,
            } => (
                ThreadState::NeedsYou {
                    reason,
                    suggestions,
                },
                summary,
                vec![],
                "Asked for a decision on",
            ),
            Decision::Skip { reason, rule } => {
                if let Some(id) = rule
                    && !self.topic.rules.iter().any(|r| r.id == id)
                {
                    return Err(TopicError::UnknownRule(id));
                }
                if !preserve_question {
                    kinds.push(ChangeKind::ThreadSkipped(id));
                }
                (
                    ThreadState::Skipped {
                        reason: reason.clone(),
                        rule,
                    },
                    reason,
                    vec![],
                    "Skipped",
                )
            }
        };
        let thread = &mut self.threads[index];
        if preserve_question {
            if let ThreadState::NeedsYou {
                reason,
                suggestions,
            } = state
            {
                thread.pending_questions.push_back(InboxQuestion {
                    source: message,
                    summary,
                    reason,
                    suggestions,
                });
            }
        } else {
            thread.question_source =
                matches!(state, ThreadState::NeedsYou { .. }).then_some(message);
            thread.state = state;
            thread.summary = summary;
        }
        for outcome in outcomes {
            if !thread.outcomes.contains(&outcome) {
                thread.outcomes.push(outcome);
            }
        }
        thread.updated_at = now;
        let text = format!("{verb} “{}”.", thread.subject);
        Ok(self.record(now, Actor::Agent, Ref::Thread(id), text, kinds))
    }

    /// Holds a reply to the thread's latest external message as a draft task in Needs You.
    /// The draft carries the same action kind as an inbox reply draft, so topic policy and
    /// approval apply to it unchanged.
    pub fn propose_reply(
        &mut self,
        id: ThreadId,
        draft: String,
        new_task: TaskId,
        now: DateTime<Utc>,
    ) -> Transition {
        let thread = &self.threads[self.thread_index(id)?];
        let original = thread
            .messages
            .iter()
            .rev()
            .find(|m| {
                matches!(
                    m.reply_target(),
                    Some(Source::Connection { .. } | Source::Topic(_))
                )
            })
            .ok_or(TopicError::ThreadState(id))?;
        let action = reply_action(
            original,
            original.reply_target().ok_or(TopicError::ThreadState(id))?,
        );
        let mut task = Task::new(
            new_task,
            format!("Reply: {}", thread.subject),
            Actor::Inbox(id),
            Some(id),
            now,
        );
        task.source_message = Some(original.id);
        task.column = Column::NeedsYou;
        task.action = Some(action);
        task.result = Some("Draft reply ready.".into());
        task.draft = Some(draft);
        task.log.push(LogEntry {
            origin: None,
            at: now,
            text: "Drafted a reply for you to check.".into(),
        });
        self.insert_task(task, now)
    }

    /// Resolves an offered choice. Uses `new_task` for either task-producing suggestion.
    pub fn answer(
        &mut self,
        id: ThreadId,
        suggestion: Suggestion,
        new_task: TaskId,
        now: DateTime<Utc>,
    ) -> Transition {
        let index = self.thread_index(id)?;
        let thread = &self.threads[index];
        let ThreadState::NeedsYou { suggestions, .. } = &thread.state else {
            return Err(TopicError::ThreadState(id));
        };
        if !suggestions.contains(&suggestion) {
            return Err(TopicError::SuggestionNotOffered(id));
        }
        let mut changes = vec![];
        let mut kinds = vec![ChangeKind::ThreadUpdated(id)];
        let creates_task = matches!(
            suggestion,
            Suggestion::DraftReply { .. }
                | Suggestion::MakeTask { .. }
                | Suggestion::Investigate
                | Suggestion::AnswerInChat
        );
        let (state, text) = match suggestion {
            Suggestion::DraftReply { draft, task_title } => {
                let original = thread
                    .question_message()
                    .ok_or(TopicError::ThreadState(id))?;
                let action = reply_action(
                    original,
                    original.reply_target().ok_or(TopicError::ThreadState(id))?,
                );
                let mut task = Task::new(new_task, task_title, Actor::Inbox(id), Some(id), now);
                task.column = Column::NeedsYou;
                task.action = Some(action);
                task.result = Some("Draft reply ready.".into());
                task.draft = Some(draft);
                task.log.push(LogEntry {
                    origin: None,
                    at: now,
                    text: "Drafted a reply for you to check.".into(),
                });
                changes.extend(self.insert_task(task, now)?);
                (ThreadState::Handled, "Drafted a reply for review.")
            }
            Suggestion::MakeTask { title } => {
                // Older sort workflows offered the entire generated question as the
                // task title. Keep its source text, rather than the generic preface.
                let title = thread
                    .question_message()
                    .and_then(|message| {
                        if !matches!(message.producer, Producer::Routine(_))
                            || title != message.text
                        {
                            return None;
                        }
                        message
                            .text
                            .strip_prefix("How should we handle this item?\n\n")
                            .filter(|item| !item.trim().is_empty())
                            .map(str::to_owned)
                    })
                    .unwrap_or(title);
                changes.extend(self.add_task(new_task, title, Actor::Inbox(id), Some(id), now)?);
                (ThreadState::Handled, "Added a task from this thread.")
            }
            Suggestion::AnswerInChat => {
                let message = thread
                    .messages
                    .first()
                    .filter(|m| m.reply_target() == Some(Source::User) && m.id.0 == id.0)
                    .ok_or(TopicError::ThreadState(id))?;
                changes.extend(self.add_requested_task(
                    new_task,
                    id,
                    message.text.clone(),
                    InboxAssignment::ChatAnswer,
                    now,
                )?);
                (ThreadState::Handled, "Queued a PostHog Task to answer.")
            }
            Suggestion::Investigate => {
                let source = thread
                    .question_message()
                    .ok_or(TopicError::ThreadState(id))?;
                let title = format!("Investigate: {}", source.text);
                changes.extend(self.add_requested_task(
                    new_task,
                    id,
                    title,
                    InboxAssignment::Investigate,
                    now,
                )?);
                (ThreadState::Handled, "Requested an investigation.")
            }
            Suggestion::AcceptEvidence {
                message,
                task,
                fact,
            } => {
                let source = thread
                    .messages
                    .iter()
                    .find(|m| m.id == message)
                    .ok_or(TopicError::SuggestionNotOffered(id))?
                    .clone();
                if let Some(task) = task {
                    let current = &self.tasks[self.task_index(task)?];
                    if current.column == Column::Done {
                        return Err(TopicError::TaskColumn(task, Column::Done));
                    }
                }
                let mut outcomes = Vec::new();
                if let Some(text) = fact {
                    let fid = FactId(new_task.0);
                    let via = match source.reply_target() {
                        Some(Source::Connection { connection, .. }) => connection,
                        Some(Source::Topic(_)) => "topic".into(),
                        Some(Source::User) => "user".into(),
                        None => source.author.clone(),
                    };
                    changes.extend(self.add_fact(
                        Fact {
                            id: fid,
                            text,
                            provenance: Provenance {
                                origin: source.origin.clone(),
                                author: source.author.clone(),
                                via,
                                at: source.at,
                                thread: Some(id),
                            },
                            superseded_by: None,
                            invalidated_by: None,
                            withdrawn_at: None,
                        },
                        now,
                    )?);
                    outcomes.push(Outcome::Fact(fid));
                }
                if let Some(task) = task {
                    changes.extend(self.add_task_evidence(
                        task,
                        id,
                        format!("{}: {}", source.author, source.text),
                        now,
                    )?);
                    outcomes.push(Outcome::Task(task));
                }
                for outcome in outcomes {
                    if !self.threads[index].outcomes.contains(&outcome) {
                        self.threads[index].outcomes.push(outcome);
                    }
                }
                (ThreadState::Handled, "Accepted the proposed evidence.")
            }
            Suggestion::ChooseFileRevision {
                path,
                candidate,
                use_candidate,
                ..
            } => {
                if self.threads[index].key != format!("file-review/{candidate}/{path}") {
                    return Err(TopicError::SuggestionNotOffered(id));
                }
                (
                    ThreadState::Handled,
                    if use_candidate {
                        "Selected the offline revision."
                    } else {
                        "Kept the current file revision."
                    },
                )
            }
            Suggestion::ResolveFacts {
                changed,
                other,
                resolution,
            } => {
                changes.extend(self.resolve_facts(changed, other, resolution, Actor::User, now)?);
                (
                    ThreadState::Handled,
                    match resolution {
                        FactResolution::KeepChanged => "Kept the added fact.",
                        FactResolution::KeepExisting => "Kept the existing fact.",
                        FactResolution::KeepBoth => "Kept both facts.",
                        FactResolution::KeepDependent => "Kept the remaining fact.",
                        FactResolution::RetireDependent => "Retired the unsupported fact.",
                    },
                )
            }
            Suggestion::SortAgain { .. } => (ThreadState::Sorting, "Queued for sorting."),
            Suggestion::Leave => {
                kinds.push(ChangeKind::ThreadSkipped(id));
                (
                    ThreadState::Skipped {
                        reason: "You chose to leave it.".into(),
                        rule: None,
                    },
                    "You chose to leave it.",
                )
            }
        };
        let thread = &mut self.threads[index];
        if state == ThreadState::Handled {
            if creates_task {
                thread.outcomes.push(Outcome::Task(new_task));
            }
            thread.summary = format!("{} {text}", thread.summary).trim().to_string();
        } else {
            thread.summary = text.into();
        }
        thread.state = state;
        thread.updated_at = now;
        thread.unseen = false;
        if thread.advance_question() {
            kinds.retain(|k| !matches!(k, ChangeKind::ThreadSkipped(_)));
        }
        changes.extend(self.record(now, Actor::User, Ref::Thread(id), text.into(), kinds));
        Ok(changes)
    }

    /// Close decisions about a path whose current revision has been deleted.
    pub fn close_file_reviews(&mut self, path: &str, now: DateTime<Utc>) {
        for thread in &mut self.threads {
            if matches!(&thread.state, ThreadState::NeedsYou {suggestions,..} if suggestions.iter().any(|s|matches!(s,Suggestion::ChooseFileRevision{path:p,..} if p == path)))
            {
                thread.state = ThreadState::Handled;
                thread.summary = format!("{path} was deleted.");
                thread.review_version += 1;
                thread.updated_at = now;
            }
        }
    }

    /// Bind outstanding choices for this path to its new head and invalidate old replies.
    pub fn refresh_file_reviews(
        &mut self,
        path: &str,
        current: u64,
        now: DateTime<Utc>,
    ) -> Vec<Change> {
        let mut changed = vec![];
        for thread in &mut self.threads {
            let ThreadState::NeedsYou { suggestions, .. } = &mut thread.state else {
                continue;
            };
            let mut updated = false;
            for choice in suggestions {
                if let Suggestion::ChooseFileRevision {
                    path: target,
                    current: old,
                    ..
                } = choice
                    && target == path
                    && *old != current
                {
                    *old = current;
                    updated = true;
                }
            }
            if updated {
                thread.review_version += 1;
                thread.updated_at = now;
                thread.summary = format!(
                    "Choose the current revision of {path}. Revision {current} is now current."
                );
                changed.push(thread.id);
            }
        }
        changed
            .into_iter()
            .flat_map(|thread| {
                self.record(
                    now,
                    Actor::Agent,
                    Ref::Thread(thread),
                    format!("File head advanced to revision {current}."),
                    [ChangeKind::ThreadUpdated(thread)],
                )
            })
            .collect()
    }

    /// Close reviews whose facts were resolved or removed by another edit.
    pub fn close_stale_fact_reviews(&mut self, now: DateTime<Utc>) -> Vec<Change> {
        let mut changes = vec![];
        for i in 0..self.threads.len() {
            let mut pending = std::mem::take(&mut self.threads[i].pending_questions);
            let before = pending.len();
            let stale = |choices: &[Suggestion]| {
                choices.iter().any(|s| matches!(s, Suggestion::ResolveFacts { changed, other, resolution } if !self.can_resolve_facts(*changed, *other, *resolution)))
            };
            pending.retain(|q| !stale(&q.suggestions));
            let active = matches!(&self.threads[i].state, ThreadState::NeedsYou { suggestions, .. } if stale(suggestions));
            let removed = pending.len() != before;
            let thread = &mut self.threads[i];
            thread.pending_questions = pending;
            if active {
                thread.state = ThreadState::Handled;
                thread.summary = "The facts changed. This review is closed.".into();
                thread.advance_question();
            }
            if active || removed {
                thread.updated_at = now;
                let id = thread.id;
                changes.extend(self.record(
                    now,
                    Actor::Agent,
                    Ref::Thread(id),
                    "Closed an outdated fact review.".into(),
                    [ChangeKind::ThreadUpdated(id)],
                ));
            }
        }
        changes
    }
    /// Marks a thread as read.
    pub fn mark_seen(&mut self, id: ThreadId, now: DateTime<Utc>) -> Transition {
        let index = self.thread_index(id)?;
        let thread = &mut self.threads[index];
        thread.unseen = false;
        thread.updated_at = now;
        let text = format!("Read “{}”.", thread.subject);
        Ok(self.record(
            now,
            Actor::User,
            Ref::Thread(id),
            text,
            [ChangeKind::ThreadUpdated(id)],
        ))
    }
}

impl Thread {
    /// Topic chat has its own conversation surface.
    pub fn is_topic_chat(&self) -> bool {
        self.messages
            .first()
            .is_some_and(|m| m.reply_target() == Some(Source::User) && m.id.0 == self.id.0)
    }

    /// A report links both to work it produced and the task that published it.
    pub fn links_task(&self, task: &Task) -> bool {
        let source_link = task.origin.as_ref().is_some_and(|origin| {
            self.report_sources
                .as_ref()
                .and_then(|sources| sources.observation.as_ref())
                .into_iter()
                .chain(self.messages.iter().filter_map(|m| m.origin.as_ref()))
                .any(|source| origin.relates_to(source))
        });
        source_link
            || task.from_thread == Some(self.id)
            || self.parent_task == Some(task.id)
            || self.outcomes.contains(&Outcome::Task(task.id))
            || self
                .messages
                .iter()
                .any(|m| m.producer == Producer::PostHogTask(task.id))
    }

    /// Source message for the decision currently displayed.
    pub fn question_message(&self) -> Option<&Message> {
        self.question_source
            .and_then(|id| self.messages.iter().find(|m| m.id == id))
            .or_else(|| self.messages.last())
    }
    /// Conversations eligible for model-selected follow-ups without a provider thread key.
    pub fn accepts_follow_up(&self) -> bool {
        if self.report_sources.is_some()
            || self.key.starts_with("fact-review/")
            || self.key.starts_with("file-review/")
        {
            return false;
        }
        match &self.state {
            ThreadState::NeedsYou { suggestions, .. } => !suggestions
                .iter()
                .any(|s| matches!(s, Suggestion::ResolveFacts { .. })),
            ThreadState::Handled => self.messages.first().is_some_and(|m| {
                matches!(
                    m.reply_target(),
                    Some(Source::Connection { .. } | Source::Topic(_))
                )
            }),
            _ => false,
        }
    }

    fn advance_question(&mut self) -> bool {
        self.review_version += 1;
        self.question_source = None;
        let Some(question) = self.pending_questions.pop_front() else {
            return false;
        };
        self.question_source = Some(question.source);
        self.summary = question.summary;
        self.state = ThreadState::NeedsYou {
            reason: question.reason,
            suggestions: question.suggestions,
        };
        self.unseen = true;
        true
    }
}

/// The reviewable action that sends a reply to `original` where it came from.
fn reply_action(original: &Message, source: Source) -> Action {
    let (kind, destination) = match &source {
        Source::Connection {
            connection,
            channel,
        } if connection == "slack" && channel.trim_start_matches('#') == "general" => {
            ("slack-post-general".into(), channel.clone())
        }
        Source::Connection {
            connection,
            channel,
        } => (format!("{connection}-reply"), channel.clone()),
        Source::Topic(topic) => ("topic-reply".into(), topic.to_string()),
        Source::User => ("user-reply".into(), "your inbox".into()),
    };
    Action {
        depends_on_facts: None,
        kind: ActionKind(kind),
        label: "Send reply".into(),
        done_label: format!("Reply sent in {destination}"),
        payload: serde_json::json!({ "to": source, "message": original.id }),
    }
}
