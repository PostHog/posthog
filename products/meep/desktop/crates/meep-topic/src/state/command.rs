use super::*;

/// Transport and retry identity for one person-initiated operation.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Envelope {
    /// Stable across every delivery attempt.
    pub id: CommandId,
    /// Destination topic, including the identity reserved for creation.
    pub topic: TopicId,
    /// Client display time. The server bounds it at acceptance and timestamps transitions itself.
    pub issued_at: DateTime<Utc>,
    /// Operation and all identities it can allocate.
    pub command: Command,
}

/// A replayable change requested by a person.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Command {
    /// Open a named topic with its initial mission.
    CreateTopic {
        /// Display name.
        name: String,
        /// Initial responsibility.
        mission: String,
    },
    /// Open a topic using the creation command supported by newer servers.
    CreateTopicWithoutSort {
        /// Display name.
        name: String,
        /// Initial responsibility.
        mission: String,
    },
    /// Change the topic display name.
    RenameTopic {
        /// Name.
        name: String,
    },
    /// Pause the topic and hide it from the active workspace.
    ArchiveTopic,
    /// Return an archived topic to the workspace.
    UnarchiveTopic,
    /// Delete a topic and replicate its tombstone.
    DeleteTopic,
    /// Remove a task from the board.
    DeleteTask {
        /// Task.
        task: TaskId,
    },
    /// Archive an inbox conversation.
    ArchiveThread {
        /// Thread.
        thread: ThreadId,
    },
    /// Remove the current head of a topic file while retaining history.
    DeleteFile {
        /// Path.
        path: String,
    },
    /// Restore a removed fact.
    RestoreFact {
        /// Fact.
        fact: FactId,
    },
    /// Restore a recently removed rule at its former precedence.
    RestoreRule {
        /// Rule.
        rule: RuleId,
    },
    /// Put work on the board.
    AddTask {
        /// New task identity.
        id: TaskId,
        /// Task title.
        title: String,
    },
    /// Work the topic agent planned: for the person, for itself later, or for a sub-agent.
    PlanTask {
        /// New task identity.
        id: TaskId,
        /// Task title.
        title: String,
        /// What to do, for whoever picks it up.
        brief: String,
        /// `Human`, `Session` (the topic agent itself) or `Investigate` (a sub-agent run).
        owner: InboxAssignment,
    },
    /// Import PostHog Scout reports into this inbox, optionally filtered; `None` stops.
    SetScoutFeed {
        /// `None` off, empty for every ready report, or a search term.
        feed: Option<String>,
    },
    /// Resolve or dismiss a published report, or reopen it with `None`.
    SetReportVerdict {
        /// The report.
        thread: ThreadId,
        /// Resolved or dismissed; `None` reopens it.
        outcome: Option<ReportOutcome>,
        /// Why, from the report's short list of reasons.
        reason: String,
    },
    /// Create queued work explicitly requested from a published report.
    AddReportTask {
        /// The report to investigate or implement.
        thread: ThreadId,
        /// Stable identity for the new task.
        id: TaskId,
        /// Person-authored task title.
        title: String,
        /// Person-authored instructions.
        instructions: String,
    },
    /// Create an explicitly agent-assigned task with run preferences.
    AddConfiguredTask {
        /// Offer the task to the worker immediately. Defaults to true.
        #[serde(default = "crate::model::enabled_by_default")]
        start: bool,
        /// Stable task identity.
        id: TaskId,
        /// Board title.
        title: String,
        /// PostHog model ID.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        model: Option<String>,
        /// Reasoning effort for the selected model.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        reasoning_effort: Option<String>,
        /// Additional task instructions.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        instructions: Option<String>,
        /// Codex model access, either own-subscription or posthog-gateway.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        billing: Option<String>,
        /// The title is a placeholder; PostHog names the task when it starts.
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        untitled: bool,
    },
    /// Create a separate task from a recommendation selected by the person.
    AcceptTaskSuggestion {
        /// Origin of the recommendation.
        parent: TaskId,
        /// Reserved identity of the new task.
        id: TaskId,
        /// Exact recommendation shown to the person.
        title: String,
    },
    /// Resolve an offered inbox choice.
    Answer {
        /// Conversation awaiting a decision.
        thread: ThreadId,
        /// Version of the question displayed to the person.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        expected_review: Option<u64>,
        /// Selected choice.
        suggestion: Suggestion,
        /// Reserved identity for a resulting task.
        task_id: TaskId,
    },
    /// Approve a task and optionally learn an allowance.
    Approve {
        /// Task under review.
        task: TaskId,
        /// Version of the review displayed to the person. An omitted version addresses the initial review.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        expected_review: Option<u64>,
        /// Final text when edited.
        edited_draft: Option<String>,
        /// Learn an allowance for this action kind.
        always: bool,
        /// Reserved identity for the allowance.
        rule_id: RuleId,
    },
    /// Dismiss an investigation lead awaiting start approval.
    DeclineFollowUp {
        /// Held task.
        task: TaskId,
        /// Review shown to the person.
        expected_review: u64,
    },
    /// Return a task for revision.
    SendBack {
        /// Reviewed task.
        task: TaskId,
        /// Version of the review displayed to the person. An omitted version addresses the initial review.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        expected_review: Option<u64>,
        /// Revision request.
        note: String,
    },
    /// Save an allowance for the action that the person just approved.
    AllowReviewedAction {
        /// Approved task.
        task: TaskId,
        /// Version after the approval committed.
        expected_review: u64,
        /// Action kind displayed with the allowance prompt.
        action_kind: ActionKind,
        /// Identity of the resulting standing rule.
        rule_id: RuleId,
    },
    /// Cancel a running investigation.
    CancelRun {
        /// Running task.
        task: TaskId,
    },
    /// Move a task to a board column.
    MoveTask {
        /// Task to move.
        task: TaskId,
        /// Destination.
        column: Column,
    },
    /// Release a queued task to the agent.
    StartTask {
        /// Task to start.
        task: TaskId,
    },
    /// Release a queued task with the first turn from its composer.
    StartTaskWithInput {
        /// Queued task.
        task: TaskId,
        /// Note and attached context to include in its brief.
        message: String,
        /// Model explicitly selected for the run.
        model: Option<String>,
    },
    /// Replace the mission.
    SetMission {
        /// New mission.
        mission: String,
    },
    /// Append an objective.
    AddGoal {
        /// Objective including its new ID.
        goal: Goal,
    },
    /// Record an objective measurement.
    UpdateGoalProgress {
        /// Objective.
        goal: GoalId,
        /// New measurement, or None to clear.
        progress: Option<Progress>,
    },
    /// Append a policy entry.
    AddRule {
        /// Rule including its new ID.
        rule: Rule,
    },
    /// Remove a policy entry.
    RemoveRule {
        /// Rule to remove.
        rule: RuleId,
    },
    /// Replace the default sorter's subscriptions.
    SetWatch {
        /// Replacement subscriptions.
        watches: Vec<Watch>,
    },
    /// Replace a whole-topic selection while preserving existing owners.
    SetTopicWatches {
        /// Replacement subscriptions.
        watches: Vec<Watch>,
    },
    /// Replace passive context references without enabling monitoring.
    SetContextSources {
        /// References available to topic tasks and routines.
        sources: Vec<Watch>,
    },
    /// Add one passive reference without replacing concurrent additions.
    AddContextSource {
        /// Reference available to topic tasks and routines.
        source: Watch,
    },
    /// Remove one passive reference without affecting monitoring.
    RemoveContextSource {
        /// Identity of the reference to remove.
        source: WatchId,
    },
    /// Assign the replacement subscriptions to one routine.
    SetRoutineWatches {
        /// Topic-local binding ID.
        routine: String,
        /// Replacement subscriptions.
        watches: Vec<Watch>,
    },
    /// Mark an inbox conversation as read.
    MarkSeen {
        /// Thread to mark.
        thread: ThreadId,
    },
    /// Save an assertion and its evidence.
    AddFact {
        /// Assertion including its new ID.
        fact: Fact,
    },
    /// Replace an assertion while retaining its provenance.
    SupersedeFact {
        /// Previous assertion.
        old: FactId,
        /// New assertion.
        new: Fact,
    },
    /// Remove an assertion.
    RemoveFact {
        /// Assertion to remove.
        fact: FactId,
    },
    /// Send a message to the topic. Questions await an agent reply.
    Chat {
        /// Message ID, also used as the new thread UUID.
        message_id: MessageId,
        /// Message text.
        text: String,
        /// Reserved task ID for a request for work.
        task_id: TaskId,
        /// Wait for the agent's current work instead of reaching it straight away.
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        queue: bool,
    },
    /// Record a reply on an existing conversation.
    Reply {
        /// Conversation to reply to.
        thread: ThreadId,
        /// Reply body.
        text: String,
    },
    /// Ask the host to replay a connected account.
    Reconnect {
        /// Account used by this topic.
        connection: String,
    },
    /// Enable or pause a fixed system stage.
    SetTopicSetting {
        /// check_facts.
        key: String,
        /// Desired setting.
        enabled: bool,
    },
    /// Return a source to Meep sorting.
    ReleaseSource {
        /// Stable watch identity.
        key: WatchId,
    },
    /// Request a workflow invocation.
    StartRoutine {
        /// Topic-local routine key.
        routine: String,
        /// Variables for the backend invocation.
        variables: serde_json::Map<String, serde_json::Value>,
    },
    /// Acknowledge a specific uncertain manual dispatch after checking the provider.
    AcknowledgeRoutineDispatch {
        /// Topic-local routine key.
        routine: String,
        /// The dispatch being acknowledged, preventing stale acknowledgements.
        expected: CommandId,
    },
    /// Bind a routine to this topic.
    SetRoutine {
        /// Public binding details.
        routine: RoutineBinding,
    },
}

/// Permission for an action and the rule that decided it.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Verdict {
    /// The matching rule allows this action to run automatically.
    Run(RuleId),
    /// Ask the person. No rule ID denotes the default policy.
    Ask(Option<RuleId>),
    /// The matching rule prohibits this action.
    Refuse(RuleId),
}

/// Applies the last matching action rule, defaulting to a request for approval.
pub fn decide(rules: &[Rule], action: &Action) -> Verdict {
    rules
        .iter()
        .rev()
        .find_map(|rule| match &rule.effect {
            RuleEffect::Allow(kind) if kind == &action.kind => Some(Verdict::Run(rule.id)),
            RuleEffect::Ask(kind) if kind == &action.kind => Some(Verdict::Ask(Some(rule.id))),
            RuleEffect::Deny(kind) if kind == &action.kind => Some(Verdict::Refuse(rule.id)),
            _ => None,
        })
        .unwrap_or(Verdict::Ask(None))
}

/// Builds a standing Allow rule when the person chooses “always” after approval.
/// Choosing “keep asking” or reviewing work without an action creates no rule.
pub fn rule_from_approval(
    task: &Task,
    always: bool,
    id: RuleId,
    now: DateTime<Utc>,
) -> Option<Rule> {
    if !always {
        return None;
    }
    let action = task.reviewed_action()?;
    let kind = &action.kind;
    Some(Rule {
        id,
        text: format!("Always allow {}.", kind.description()),
        effect: RuleEffect::Allow(kind.clone()),
        from_task: Some(task.id),
        created_at: now,
    })
}

impl Envelope {
    /// Builds an initial replica or server state for a CreateTopic command.
    pub fn create(&self) -> Result<(TopicState, Changes), TopicError> {
        self.create_at(self.issued_at)
    }
    /// Create at the authoritative host time.
    pub fn create_at(&self, now: DateTime<Utc>) -> Result<(TopicState, Changes), TopicError> {
        let (name, mission) = match &self.command {
            Command::CreateTopic { name, mission }
            | Command::CreateTopicWithoutSort { name, mission } => (name, mission),
            _ => return Err(TopicError::ExpectedCreate),
        };
        let mut state = TopicState::new(Topic::new(self.topic, name, now));
        let changes = state.set_mission(mission, now)?;
        Ok((state, changes))
    }
}

impl TopicState {
    fn check_review(&self, id: TaskId, expected: u64) -> Result<(), TopicError> {
        if self.tasks[self.task_index(id)?].review_version != expected {
            return Err(TopicError::StaleTaskReview);
        }
        Ok(())
    }

    /// Applies a person's command atomically using only its supplied time and identities.
    /// Create a new state with [`Envelope::create`] for a CreateTopic command.
    pub fn apply(&mut self, envelope: &Envelope) -> Result<Changes, TopicError> {
        self.apply_at(envelope, envelope.issued_at)
    }

    /// Apply on the authoritative host at its own clock time.
    pub fn apply_at(
        &mut self,
        envelope: &Envelope,
        now: DateTime<Utc>,
    ) -> Result<Changes, TopicError> {
        if self.topic.id != envelope.topic {
            return Err(TopicError::WrongTopic(envelope.topic));
        }
        if self.deleted
            || (self.archived
                && !matches!(
                    envelope.command,
                    Command::UnarchiveTopic
                        | Command::ArchiveTopic
                        | Command::DeleteTopic
                        | Command::RenameTopic { .. }
                ))
        {
            return Err(TopicError::InactiveTopic);
        }
        let mut changes = match envelope.command.clone() {
            Command::RenameTopic { name } => {
                let name = name.trim();
                if name.is_empty() {
                    return Err(TopicError::EmptyName);
                }
                self.topic.name = name.to_owned();
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Topic,
                    format!("Renamed topic to {name}."),
                    [ChangeKind::TopicUpdated(envelope.topic)],
                ))
            }
            Command::ArchiveTopic | Command::UnarchiveTopic => {
                self.archived = matches!(envelope.command, Command::ArchiveTopic);
                let text = if self.archived {
                    "Archived topic."
                } else {
                    "Unarchived topic."
                };
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Topic,
                    text.into(),
                    [ChangeKind::TopicUpdated(envelope.topic)],
                ))
            }
            Command::DeleteTopic => {
                *self = Self::new(Topic::new(envelope.topic, "", now));
                self.deleted = true;
                Ok(vec![])
            }
            Command::DeleteTask { task } => {
                let i = self.task_index(task)?;
                self.tasks.remove(i);
                for thread in &mut self.threads {
                    thread.outcomes.retain(|o| o != &Outcome::Task(task));
                }
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Task(task),
                    "Deleted task.".into(),
                    [ChangeKind::TaskUpdated(task)],
                ))
            }
            Command::SetScoutFeed { feed } => {
                let feed = feed.map(|f| f.trim().chars().take(200).collect::<String>());
                let text = match &feed {
                    None => "Stopped PostHog Scout reports.".to_owned(),
                    Some(f) if f.is_empty() => "Receiving PostHog Scout reports.".to_owned(),
                    Some(f) => format!("Receiving PostHog Scout reports about “{f}”."),
                };
                self.topic.settings.scout_feed = feed;
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Topic,
                    text,
                    [ChangeKind::TopicUpdated(self.topic.id)],
                ))
            }
            Command::SetReportVerdict {
                thread,
                outcome,
                reason,
            } => {
                let index = self.thread_index(thread)?;
                if !self.threads[index].is_agent_report() {
                    return Err(TopicError::NotAgentReport);
                }
                let sources = self.threads[index]
                    .report_sources
                    .as_mut()
                    .ok_or(TopicError::NotAgentReport)?;
                sources.verdict = outcome.map(|outcome| ReportVerdict {
                    outcome,
                    reason: reason.trim().to_owned(),
                    at: now,
                });
                let text = match outcome {
                    Some(ReportOutcome::Resolved) => "Resolved the report.",
                    Some(ReportOutcome::Dismissed) => "Dismissed the report.",
                    None => "Reopened the report.",
                };
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Thread(thread),
                    text.into(),
                    [ChangeKind::ThreadUpdated(thread)],
                ))
            }
            Command::ArchiveThread { thread } => {
                self.thread_index(thread)?;
                self.archived_threads.insert(thread);
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Thread(thread),
                    "Archived thread.".into(),
                    [ChangeKind::ThreadUpdated(thread)],
                ))
            }
            Command::DeleteFile { path } => {
                if path.trim().is_empty() {
                    return Err(TopicError::EmptyName);
                }
                self.deleted_files.entry(path.clone()).or_insert(0);
                self.close_file_reviews(&path, now);
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Topic,
                    format!("Deleted file {path}."),
                    [ChangeKind::TopicUpdated(envelope.topic)],
                ))
            }
            Command::RestoreFact { fact } => {
                let original = self
                    .removed_facts
                    .get(&fact)
                    .cloned()
                    .ok_or(TopicError::UnknownFact(fact))?;
                if let Some(existing) = self.topic.facts.iter_mut().find(|f| f.id == fact) {
                    if existing.withdrawn_at.is_none() {
                        return Err(TopicError::DuplicateId(fact.to_string()));
                    }
                    *existing = original;
                } else {
                    self.topic.facts.push(original)
                }
                self.removed_facts.remove(&fact);
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Fact(fact),
                    "Restored fact.".into(),
                    [ChangeKind::FactAdded(fact)],
                ))
            }
            Command::RestoreRule { rule } => {
                let (_, index, original) = self
                    .removed_rules
                    .get(&rule)
                    .filter(|(at, _, _)| *at > now - chrono::TimeDelta::days(30))
                    .cloned()
                    .ok_or(TopicError::UnknownRule(rule))?;
                if self.topic.rules.iter().any(|r| r.id == rule) {
                    return Err(TopicError::DuplicateId(rule.to_string()));
                }
                self.topic
                    .rules
                    .insert(index.min(self.topic.rules.len()), original);
                self.removed_rules.remove(&rule);
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Rule(rule),
                    "Restored rule.".into(),
                    [ChangeKind::RuleAdded(rule)],
                ))
            }
            Command::CreateTopic { .. } | Command::CreateTopicWithoutSort { .. } => {
                Err(TopicError::ExistingTopic(envelope.topic))
            }
            Command::AcceptTaskSuggestion { parent, id, title } => {
                self.accept_suggestion(parent, id, title, now)
            }
            Command::AddConfiguredTask {
                start,
                id,
                title,
                model,
                reasoning_effort,
                instructions,
                billing,
                untitled,
            } => {
                let mut task = Task::new(id, title, Actor::User, None, now);
                task.untitled = untitled;
                task.queued = !start;
                task.model = model;
                task.reasoning_effort = reasoning_effort;
                task.instructions = instructions;
                task.billing = billing;
                self.insert_task(task, now)
            }
            Command::AddTask { id, title } => self.add_task(id, title, Actor::User, None, now),
            Command::PlanTask {
                id,
                title,
                brief,
                owner,
            } => self.plan_task(id, title, brief, owner, now),
            Command::AddReportTask {
                thread,
                id,
                title,
                instructions: requested,
            } => {
                let report = &self.threads[self.thread_index(thread)?];
                if !report.is_agent_report() {
                    return Err(TopicError::NotAgentReport);
                }
                let mut instructions = format!(
                    "{}\n\n# {}\n\n{}",
                    requested.trim(),
                    report.subject,
                    report
                        .question_message()
                        .map_or("", |message| message.text.as_str())
                );
                if let Some(sources) = &report.report_sources {
                    for evidence in &sources.evidence {
                        instructions.push_str(&format!(
                            "\n\nEvidence: {}\nSource: {}",
                            evidence.description, evidence.source_id
                        ));
                    }
                    for reference in &sources.references {
                        instructions.push_str(&format!("\n\nSource: {reference}"));
                    }
                }
                let mut task = Task::new(id, title, Actor::User, Some(thread), now);
                task.instructions = Some(instructions);
                task.queued = true;
                self.insert_task(task, now)
            }
            Command::Answer {
                thread,
                expected_review,
                suggestion,
                task_id,
            } => {
                if self.threads[self.thread_index(thread)?].review_version
                    != expected_review.unwrap_or_default()
                {
                    return Err(TopicError::StaleInboxReview);
                }
                let drafted = matches!(suggestion, Suggestion::DraftReply { .. });
                let mut changes = self.answer(thread, suggestion, task_id, now)?;
                if drafted {
                    let task = &self.tasks[self.task_index(task_id)?];
                    if let Some(action) = &task.action {
                        match decide(&self.topic.rules, action) {
                            Verdict::Run(_) => changes.extend(self.approve(task_id, None, now)?),
                            Verdict::Refuse(rule) => {
                                changes.extend(self.move_task(task_id, Column::InProgress, now)?);
                                changes.extend(self.progress(
                                    task_id,
                                    format!("Refused by rule {rule}."),
                                    now,
                                )?);
                            }
                            Verdict::Ask(_) => {}
                        }
                    }
                }
                Ok(changes)
            }
            Command::Approve {
                task,
                expected_review,
                edited_draft,
                always,
                rule_id,
            } => {
                self.check_review(task, expected_review.unwrap_or_default())?;
                let mut next = self.clone();
                let reviewed = &next.tasks[next.task_index(task)?];
                let start = reviewed.review_before_start && reviewed.follow_up_action().is_some();
                let mut changes = next.approve(task, edited_draft, now)?;
                let i = next.task_index(task)?;
                let task = &mut next.tasks[i];
                if start || task.column == Column::Done && task.action.is_some() {
                    task.approval_rule = Some(rule_id);
                }
                if let Some(rule) = rule_from_approval(task, always, rule_id, now) {
                    changes.extend(next.add_rule(rule, now)?);
                }
                *self = next;
                Ok(changes)
            }
            Command::SendBack {
                task,
                expected_review,
                note,
            } => {
                self.check_review(task, expected_review.unwrap_or_default())?;
                self.send_back(task, note, now)
            }
            Command::AllowReviewedAction {
                task,
                expected_review,
                action_kind,
                rule_id,
            } => {
                self.check_review(task, expected_review)?;
                let approved = &self.tasks[self.task_index(task)?];
                let rule = rule_from_approval(approved, true, rule_id, now)
                    .filter(|rule| rule.effect == RuleEffect::Allow(action_kind.clone()))
                    .ok_or(TopicError::StaleTaskReview)?;
                if approved.approval_rule != Some(rule_id) {
                    return Err(TopicError::StaleTaskReview);
                }
                if let Some(action) = approved.reviewed_action()
                    && let Verdict::Refuse(rule) = decide(&self.topic.rules, &action)
                {
                    return Err(TopicError::ActionDenied(rule));
                }
                self.add_rule(rule, now)
            }
            Command::CancelRun { task } => self.cancel_run(task, now),
            Command::MoveTask { task, column } => self.move_task(task, column, now),
            Command::StartTask { task } | Command::StartTaskWithInput { task, .. } => {
                let i = self.task_index(task)?;
                if !self.tasks[i].queued {
                    return Err(TopicError::TaskNotQueued(task));
                }
                let changes = self.move_task(task, Column::InProgress, now)?;
                if let Command::StartTaskWithInput { message, model, .. } = &envelope.command {
                    let t = &mut self.tasks[i];
                    if let Some(model) = model {
                        t.model = Some(model.clone());
                        t.billing = None;
                        t.reasoning_effort = None;
                    }
                    if !message.is_empty() {
                        let brief = t.instructions.get_or_insert_with(|| t.title.clone());
                        brief.push_str("\n\n");
                        brief.push_str(message);
                    }
                }
                Ok(changes)
            }
            Command::DeclineFollowUp {
                task,
                expected_review,
            } => {
                self.check_review(task, expected_review)?;
                self.decline_follow_up(task, now)
            }
            Command::SetMission { mission } => self.set_mission(mission, now),
            Command::AddGoal { goal } => self.add_goal(goal, now),
            Command::UpdateGoalProgress { goal, progress } => {
                self.update_goal_progress(goal, progress, now)
            }
            Command::AddRule { rule } => self.add_rule(rule, now),
            Command::RemoveRule { rule } => self.remove_rule(rule, now),
            Command::SetTopicWatches { watches } => self.set_topic_watches(watches, now),
            Command::SetContextSources { sources } => self.set_context_sources(sources, now),
            Command::AddContextSource { source } => self.add_context_source(source, now),
            Command::RemoveContextSource { source } => self.remove_context_source(source, now),
            Command::SetRoutineWatches { routine, watches } => {
                self.set_routine_watches(&routine, watches, now)
            }
            Command::SetWatch { watches } => self.set_watch(watches, now),
            Command::MarkSeen { thread } => self.mark_seen(thread, now),
            Command::AddFact { fact } => self.add_fact(fact, now),
            Command::SupersedeFact { old, new } => self.supersede_fact(old, new, now),
            Command::RemoveFact { fact } => self.remove_fact(fact, now),
            Command::Chat {
                message_id,
                text,
                task_id,
                ..
            } => {
                if self.tasks.iter().any(|t| t.id == task_id) {
                    return Err(TopicError::DuplicateId(task_id.to_string()));
                }
                let thread = ThreadId(message_id.0);
                let mut next = self.clone();
                let changes = next.receive(
                    Message {
                        id: message_id,
                        producer: Producer::User,
                        origin: None,
                        author: "You".into(),
                        at: now,
                        text: text.clone(),
                        external_id: None,
                    },
                    thread.to_string(),
                    thread,
                    now,
                )?;
                if !changes
                    .iter()
                    .any(|c| c.kind == ChangeKind::ThreadOpened(thread))
                {
                    return Err(TopicError::DuplicateId(thread.to_string()));
                }
                *self = next;
                Ok(changes)
            }
            Command::Reply { thread, text } => {
                let index = self.thread_index(thread)?;
                let message = MessageId(envelope.id.0);
                if self
                    .threads
                    .iter()
                    .flat_map(|t| &t.messages)
                    .any(|m| m.id == message)
                {
                    return Err(TopicError::DuplicateId(message.to_string()));
                }
                let t = &mut self.threads[index];
                let to = t
                    .messages
                    .iter()
                    .rev()
                    .filter_map(Message::reply_target)
                    .find(|to| *to != Source::User)
                    .or_else(|| t.messages.last()?.reply_target())
                    .ok_or(TopicError::ThreadState(thread))?;
                t.messages.push(Message {
                    id: message,
                    producer: Producer::User,
                    origin: None,
                    author: "You".into(),
                    at: now,
                    text: text.clone(),
                    external_id: None,
                });
                t.outcomes.push(Outcome::Reply {
                    to,
                    text: text.clone(),
                });
                if !matches!(t.state, ThreadState::NeedsYou { .. }) {
                    t.summary = text;
                    t.state = ThreadState::Handled;
                }
                t.updated_at = now;
                t.unseen = false;
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Thread(thread),
                    "Replied to the thread.".into(),
                    [
                        ChangeKind::ThreadUpdated(thread),
                        ChangeKind::MessageReceived(thread, message),
                    ],
                ))
            }
            Command::Reconnect { .. } => Ok(vec![]),
            Command::ReleaseSource { key } => {
                let mut watches = self.topic.fallback.binding.watches.clone();
                if let Some(w) = self.topic.watches().find(|w| w.id == key)
                    && !watches.contains(w)
                {
                    watches.push(w.clone());
                }
                self.set_routine_watches(&self.topic.fallback.binding.id.clone(), watches, now)
            }
            Command::SetTopicSetting {
                key: routine,
                enabled,
            } => {
                let flag = self
                    .topic
                    .settings
                    .setting_mut(&routine)
                    .ok_or_else(|| TopicError::UnknownRoutine(routine.clone()))?;
                if *flag == enabled {
                    return Ok(vec![]);
                }
                *flag = enabled;
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Topic,
                    format!("Changed {routine} to {enabled}"),
                    [ChangeKind::TopicUpdated(self.topic.id)],
                ))
            }
            Command::StartRoutine { routine, .. } => {
                if !self.topic.routines.iter().any(|r| r.binding.id == routine) {
                    return Err(TopicError::UnknownRoutine(routine));
                }
                Ok(vec![])
            }
            Command::AcknowledgeRoutineDispatch { routine, expected } => {
                let info = self
                    .topic
                    .routines
                    .iter_mut()
                    .find(|r| r.binding.id == routine)
                    .ok_or_else(|| TopicError::UnknownRoutine(routine.clone()))?;
                if info.uncertain_manual_run != Some(expected) {
                    return Err(TopicError::StaleRoutineDispatch);
                }
                info.uncertain_manual_run = None;
                Ok(self.record(
                    now,
                    Actor::User,
                    Ref::Topic,
                    format!("Acknowledged the uncertain run of {routine}."),
                    [ChangeKind::TopicUpdated(self.topic.id)],
                ))
            }
            Command::SetRoutine { mut routine, .. } => {
                let id = routine.id.clone();
                let existing = self.topic.routines.iter().find(|r| r.binding.id == id);
                if routine.id == self.topic.fallback.binding.id
                    || routine.backend == "local"
                    || routine.backend == "system"
                    || existing.is_some_and(|r| r.binding.backend == "system")
                {
                    return Err(TopicError::ReservedRoutine(id));
                }
                super::context::validate_watches(&routine.watches)?;
                let watches = std::mem::take(&mut routine.watches);
                if let Some(existing) = existing {
                    routine.watches.clone_from(&existing.binding.watches);
                }
                let info = RoutineInfo {
                    event: None,
                    enabled: true,
                    observations: self
                        .topic
                        .routines
                        .iter()
                        .find(|r| r.binding.id == id)
                        .map(|r| r.observations.clone())
                        .unwrap_or_default(),
                    uncertain_manual_run: existing.and_then(|e| e.uncertain_manual_run),
                    binding: routine,
                    last_run: None,
                    health: RoutineHealth::Unknown,
                };
                match self.topic.routines.iter_mut().find(|r| r.binding.id == id) {
                    Some(existing) => *existing = info,
                    None => self.topic.routines.push(info),
                }
                if !watches.is_empty() {
                    self.assign_watches(&id, watches)?;
                }
                let mut changes = self.record(
                    now,
                    Actor::User,
                    Ref::Topic,
                    format!("Bound routine {id}."),
                    [ChangeKind::TopicUpdated(self.topic.id)],
                );
                let held: Vec<_> = self.tasks.iter().filter(|t| t.review_before_start && t.column == Column::NeedsYou && matches!(&t.assignment, Some(InboxAssignment::Routine(r)) if r == &id)).map(|t| t.id).collect();
                for task in held {
                    changes.extend(self.routine_review_changed(task, now)?);
                }
                Ok(changes)
            }
        }?;
        if changes.iter().any(|change| {
            matches!(
                change.kind,
                ChangeKind::FactRemoved(_)
                    | ChangeKind::FactSuperseded(_, _)
                    | ChangeKind::FactInvalidated(_, _)
            )
        }) {
            changes.extend(self.close_stale_fact_reviews(now));
        }
        Ok(changes)
    }
}
