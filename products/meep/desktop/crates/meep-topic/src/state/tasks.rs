use super::*;

/// Keep a free-form status or revision note separate from the transition that introduces it.
fn with_note(event: &str, note: &str) -> String {
    let note = note.trim();
    if note.is_empty() {
        return event.to_owned();
    }
    let mut text = format!("{event} {note}");
    if note.ends_with(char::is_alphanumeric) {
        text.push('.');
    }
    text
}

impl Task {
    /// Whether this is the topic agent's conversation rather than work on the board.
    pub fn is_session(&self) -> bool {
        self.assignment == Some(InboxAssignment::ChatAnswer)
    }
    /// A routine's own run: it reports to the inbox instead of showing as a task.
    pub fn is_routine_run(&self) -> bool {
        matches!(self.added_by, Actor::Routine(_)) && self.assignment.is_none()
    }
    /// Kept off task lists: the conversation itself and routine runs.
    pub fn hidden(&self) -> bool {
        self.is_session() || self.is_routine_run()
    }
    pub(super) fn follow_up_action(&self) -> Option<Action> {
        ((self.parent.is_some() || self.added_by == Actor::Agent)
            && matches!(
                self.assignment,
                Some(InboxAssignment::Investigate | InboxAssignment::Routine(_))
            ))
        .then(|| Action {
            kind: ActionKind::start_follow_up(),
            label: "Start follow-up".into(),
            done_label: "Started follow-up".into(),
            depends_on_facts: Some(vec![]),
            payload: serde_json::json!({"task":self.id}),
        })
    }

    fn check_start_rule(&self, rules: &[Rule], action: &Action) -> Result<(), TopicError> {
        match decide(rules, action) {
            Verdict::Refuse(rule) => Err(TopicError::ActionDenied(rule)),
            Verdict::Ask(_) if self.approval_rule.is_none() => {
                Err(TopicError::StartNeedsApproval(self.id))
            }
            _ => Ok(()),
        }
    }

    fn pending_start(&self) -> Option<Action> {
        self.action
            .as_ref()
            .filter(|a| a.kind == ActionKind::start_follow_up())
            .cloned()
            .or_else(|| {
                self.reviewed_action()
                    .filter(|a| a.kind == ActionKind::start_follow_up())
            })
    }

    /// The action addressed by the standing-rule offer after an approval.
    pub fn reviewed_action(&self) -> Option<Action> {
        if self.column == Column::Done {
            return self.action.clone();
        }
        if matches!(self.column, Column::Todo | Column::InProgress) && self.approval_rule.is_some()
        {
            return self.follow_up_action();
        }
        None
    }

    /// Button text for completing a task in Needs You.
    pub fn review_action_label(&self) -> &str {
        if self.review_before_start {
            "Approve start"
        } else {
            self.action
                .as_ref()
                .map_or("Mark done", |a| a.label.as_str())
        }
    }

    pub(super) fn new(
        id: TaskId,
        title: String,
        added_by: Actor,
        from_thread: Option<ThreadId>,
        now: DateTime<Utc>,
    ) -> Self {
        Self {
            id,
            title,
            model: None,
            reasoning_effort: None,
            instructions: None,
            billing: None,
            untitled: false,
            column: Column::Todo,
            added_by,
            from_thread,
            source_message: None,
            origin: None,
            assignment: None,
            queued: false,
            parent: None,
            review_before_start: false,

            review_version: 0,
            approval_rule: None,
            worker: None,
            action: None,
            input_question: None,
            suggestions: vec![],
            files: vec![],
            result: None,
            draft: None,
            log: vec![],
            created_at: now,
            updated_at: now,
        }
    }
}

impl TopicState {
    /// Adds work to To do, optionally linking it to the thread that prompted it.
    pub fn add_task(
        &mut self,
        id: TaskId,
        title: impl Into<String>,
        added_by: Actor,
        from_thread: Option<ThreadId>,
        now: DateTime<Utc>,
    ) -> Transition {
        self.insert_task(Task::new(id, title.into(), added_by, from_thread, now), now)
    }

    /// Keep an external attempt on its originating work. Only the still-current
    /// approved attempt can return the card to Needs you.
    pub fn delivery_receipt(
        &mut self,
        attempt: uuid::Uuid,
        subject: Ref,
        detail: String,
        needs_review: bool,
        now: DateTime<Utc>,
    ) -> Transition {
        let changes = if let Ref::Task(task) = subject
            && needs_review
            && let Some(i) = self
                .tasks
                .iter()
                .position(|t| t.id == task && t.column == Column::Done)
        {
            self.tasks[i].result = Some(detail.clone());
            self.move_with_log(i, Column::NeedsYou, Actor::Agent, detail, now, None)
        } else {
            let change = match subject {
                Ref::Task(task) => Some(ChangeKind::TaskUpdated(task)),
                Ref::Thread(thread) => Some(ChangeKind::ThreadUpdated(thread)),
                _ => None,
            };
            self.record(now, Actor::Agent, subject, detail, change)
        };
        self.activity.last_mut().expect("receipt recorded").delivery = Some(attempt);
        Ok(changes)
    }

    /// Create a queued task from a suggestion selected by a person.
    pub(super) fn accept_suggestion(
        &mut self,
        parent: TaskId,
        id: TaskId,
        title: String,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_index(parent)?;
        let position = self.tasks[i]
            .suggestions
            .iter()
            .position(|s| s == &title)
            .ok_or(TopicError::StaleTaskReview)?;
        let mut child = Task::new(id, title, Actor::User, self.tasks[i].from_thread, now);
        child.parent = Some(parent);
        child.queued = true;
        let mut changes = self.insert_task(child, now)?;
        self.tasks[i].suggestions.remove(position);
        changes.extend(self.record(
            now,
            Actor::User,
            Ref::Task(parent),
            "Created a task from a suggested next step.".into(),
            [ChangeKind::TaskUpdated(parent)],
        ));
        Ok(changes)
    }

    /// Put classified inbox work in its initial column, with its source and executor.
    pub fn add_inbox_task(
        &mut self,
        id: TaskId,
        thread: ThreadId,
        summary: &str,
        assignment: InboxAssignment,
        review: bool,
        now: DateTime<Utc>,
    ) -> Transition {
        let title = match &assignment {
            InboxAssignment::Investigate => format!("Investigate: {summary}"),
            _ => summary.to_owned(),
        };
        let mut task = Task::new(id, title, Actor::Inbox(thread), Some(thread), now);
        let human = assignment == InboxAssignment::Human;
        task.assignment = Some(assignment);
        task.review_before_start = review && !human;
        if human || review {
            task.column = Column::NeedsYou;
            task.result = Some(if human {
                summary.to_owned()
            } else {
                format!("Approve starting this work: {summary}")
            });
        }
        task.parent = self.threads[self.thread_index(thread)?].parent_task;
        self.admit_follow_up(&mut task);
        self.insert_task(task, now)
    }

    fn admit_follow_up(&self, task: &mut Task) {
        let Some(action) = task.follow_up_action() else {
            return;
        };
        let permission = task.check_start_rule(&self.topic.rules, &action);
        task.action = Some(action);
        let Err(reason) = permission else {
            return;
        };
        task.column = Column::NeedsYou;
        task.review_before_start = true;
        task.result = Some(reason.to_string());
    }

    /// Recheck a queued follow-up immediately before a worker takes it.
    pub fn review_follow_up_start(&mut self, id: TaskId, now: DateTime<Utc>) -> Transition {
        let i = self.task_index(id)?;
        let task = &self.tasks[i];
        if task.column != Column::Todo {
            return Ok(vec![]);
        }
        let Some(action) = task.pending_start() else {
            return Ok(vec![]);
        };
        let Err(reason) = task.check_start_rule(&self.topic.rules, &action) else {
            return Ok(vec![]);
        };
        let detail = reason.to_string();
        self.tasks[i].review_before_start = true;
        self.tasks[i].result = Some(detail.clone());
        Ok(self.move_with_log(i, Column::NeedsYou, Actor::Agent, detail, now, None))
    }

    /// Create the task explicitly requested by a person in a conversation.
    pub fn add_requested_task(
        &mut self,
        id: TaskId,
        thread: ThreadId,
        title: String,
        assignment: InboxAssignment,
        now: DateTime<Utc>,
    ) -> Transition {
        let actor = if assignment == InboxAssignment::ChatAnswer {
            Actor::User
        } else {
            Actor::Inbox(thread)
        };
        let mut task = Task::new(id, title, actor, Some(thread), now);
        task.assignment = Some(assignment);
        self.insert_task(task, now)
    }

    /// Add work the topic agent planned, owned by the person, by the agent itself, or
    /// by a sub-agent run.
    pub fn plan_task(
        &mut self,
        id: TaskId,
        title: String,
        brief: String,
        owner: InboxAssignment,
        now: DateTime<Utc>,
    ) -> Transition {
        if !matches!(
            owner,
            InboxAssignment::Human | InboxAssignment::Session | InboxAssignment::Investigate
        ) {
            return Err(TopicError::PlannedTaskOwner);
        }
        let mut task = Task::new(id, title, Actor::Agent, None, now);
        task.assignment = Some(owner);
        let brief = brief.trim();
        if !brief.is_empty() {
            task.instructions = Some(brief.to_owned());
        }
        self.insert_task(task, now)
    }

    /// Attach source evidence without changing the task's execution or approval state.
    pub fn add_task_evidence(
        &mut self,
        id: TaskId,
        thread: ThreadId,
        text: String,
        now: DateTime<Utc>,
    ) -> Transition {
        self.thread_index(thread)?;
        self.record_task_evidence(id, Actor::Inbox(thread), text, None, now)
    }

    /// Append evidence supplied by an inbox or routine.
    pub fn record_task_evidence(
        &mut self,
        id: TaskId,
        actor: Actor,
        text: String,
        origin: Option<Origin>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_index(id)?;
        let task = &mut self.tasks[i];
        task.updated_at = now;
        task.log.push(LogEntry {
            origin,
            at: now,
            text: text.clone(),
        });
        Ok(self.record(
            now,
            actor,
            Ref::Task(id),
            text,
            [ChangeKind::TaskUpdated(id)],
        ))
    }

    pub(super) fn insert_task(&mut self, mut task: Task, now: DateTime<Utc>) -> Transition {
        if self.tasks.iter().any(|t| t.id == task.id) {
            return Err(TopicError::DuplicateId(task.id.to_string()));
        }
        if let Some(id) = task.from_thread {
            let source = &self.threads[self.thread_index(id)?];
            task.parent = task.parent.or(source.parent_task);
            if task.source_message.is_none() {
                task.source_message = source.question_message().map(|m| m.id);
            }
        }
        if let Actor::Inbox(id) = task.added_by {
            self.thread_index(id)?;
        }
        let id = task.id;
        let actor = task.added_by.clone();
        let text = format!("Added “{}” to {}.", task.title, task.column.label());
        self.tasks.push(task);
        Ok(self.record(now, actor, Ref::Task(id), text, [ChangeKind::TaskAdded(id)]))
    }

    fn task_in(&self, id: TaskId, required: Column) -> Result<usize, TopicError> {
        let i = self.task_index(id)?;
        if self.tasks[i].column != required {
            return Err(TopicError::TaskColumn(id, self.tasks[i].column));
        }
        Ok(i)
    }

    fn move_with_log(
        &mut self,
        i: usize,
        to: Column,
        actor: Actor,
        text: String,
        now: DateTime<Utc>,
        extra: Option<ChangeKind>,
    ) -> Vec<Change> {
        let task = &mut self.tasks[i];
        let id = task.id;
        let from = task.column;
        if from == Column::Done {
            task.suggestions.clear();
        }
        if from == Column::NeedsYou {
            task.input_question = None;
            task.review_version += 1;
        }
        // Starting the approved work can race a device's subsequent Always allow command.
        if !(from == Column::Todo && to == Column::InProgress && task.follow_up_action().is_some())
        {
            task.approval_rule = None;
        }
        task.queued = false;
        task.column = to;
        if to != Column::InProgress {
            task.worker = None;
        }
        task.updated_at = now;
        task.log.push(LogEntry {
            origin: None,
            at: now,
            text: text.clone(),
        });
        let changes = std::iter::once(ChangeKind::TaskMoved { task: id, from, to }).chain(extra);
        self.record(now, actor, Ref::Task(id), text, changes)
    }

    /// Continue an existing investigation after its approved workflow step succeeds.
    pub fn resume_after_workflow(&mut self, task: TaskId, now: DateTime<Utc>) -> Transition {
        let i = self.task_in(task, Column::Done)?;
        self.tasks[i].action = None;
        Ok(self.move_with_log(
            i,
            Column::InProgress,
            Actor::Agent,
            "Continuing after the workflow action.".into(),
            now,
            None,
        ))
    }

    /// Refresh a pending review after the automation it referred to was rebound.
    pub fn routine_review_changed(&mut self, task: TaskId, now: DateTime<Utc>) -> Transition {
        let i = self.task_in(task, Column::NeedsYou)?;
        let task = &mut self.tasks[i];
        task.review_version += 1;
        let detail = if task.review_before_start {
            "The assigned routine changed. Review the updated automation before starting."
        } else {
            task.action = None;
            task.draft = None;
            "The proposing routine changed. Its previous action was withdrawn."
        };
        task.updated_at = now;
        task.result = Some(detail.into());
        task.log.push(LogEntry {
            origin: None,
            at: now,
            text: detail.into(),
        });
        let id = task.id;
        Ok(self.record(
            now,
            Actor::Agent,
            Ref::Task(id),
            detail.into(),
            [ChangeKind::TaskUpdated(id)],
        ))
    }

    /// Pause the current investigation for a reply from the person.
    pub fn ask_user(&mut self, id: TaskId, question: String, now: DateTime<Utc>) -> Transition {
        let i = self.task_in(id, Column::InProgress)?;
        self.tasks[i].input_question = Some(question.clone());
        self.tasks[i].result = None;
        Ok(self.move_with_log(i, Column::NeedsYou, Actor::Agent, question, now, None))
    }

    /// A reply continues the same investigation that asked the question.
    pub fn resume_task_message(&mut self, id: TaskId, now: DateTime<Utc>) -> Transition {
        let i = self.task_index(id)?;
        if self.tasks[i].column == Column::NeedsYou && self.tasks[i].input_question.is_some() {
            return Ok(self.move_with_log(
                i,
                Column::InProgress,
                Actor::User,
                "Answered the question.".into(),
                now,
                None,
            ));
        }
        self.move_task(id, Column::InProgress, now)
    }

    /// Return work that could not run to the person with its diagnostic.
    pub fn work_needs_attention(
        &mut self,
        id: TaskId,
        detail: String,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_index(id)?;
        let task = &mut self.tasks[i];
        if !matches!(task.column, Column::Todo | Column::InProgress) {
            return Err(TopicError::TaskColumn(id, task.column));
        }
        task.action = None;
        task.result = Some(detail.clone());
        Ok(self.move_with_log(i, Column::NeedsYou, Actor::Agent, detail, now, None))
    }

    pub(super) fn cancel_run(&mut self, id: TaskId, now: DateTime<Utc>) -> Transition {
        let i = self.task_in(id, Column::InProgress)?;
        let detail = "Run cancelled by person.";
        self.tasks[i].action = None;
        self.tasks[i].result = Some(detail.into());
        Ok(self.move_with_log(i, Column::NeedsYou, Actor::User, detail.into(), now, None))
    }

    /// Starts a To do task and records the worker's initial status.
    pub fn start(
        &mut self,
        id: TaskId,
        worker: impl Into<String>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_in(id, Column::Todo)?;
        let worker = worker.into();
        let text = with_note("Started work.", &worker);
        if let Some(action) = self.tasks[i].pending_start() {
            self.tasks[i].check_start_rule(&self.topic.rules, &action)?;
            self.tasks[i].action = None;
        }
        self.tasks[i].worker = Some(worker);
        Ok(self.move_with_log(i, Column::InProgress, Actor::Agent, text, now, None))
    }

    /// Updates the worker's status on an active task.
    pub fn progress(
        &mut self,
        id: TaskId,
        worker: impl Into<String>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_in(id, Column::InProgress)?;
        let worker = worker.into();
        let text = with_note("Updated progress.", &worker);
        let task = &mut self.tasks[i];
        task.worker = Some(worker);
        task.updated_at = now;
        task.log.push(LogEntry {
            origin: None,
            at: now,
            text: text.clone(),
        });
        Ok(self.record(
            now,
            Actor::Agent,
            Ref::Task(id),
            text,
            [ChangeKind::TaskUpdated(id)],
        ))
    }

    /// Link a topic file to the task whose run wrote it. Writing it again changes nothing.
    pub fn record_file(
        &mut self,
        id: TaskId,
        path: impl Into<String>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_index(id)?;
        let path = path.into();
        if self.tasks[i].files.contains(&path) {
            return Ok(vec![]);
        }
        let task = &mut self.tasks[i];
        task.files.push(path.clone());
        task.updated_at = now;
        Ok(self.record(
            now,
            Actor::Agent,
            Ref::Task(id),
            format!("Wrote {path}."),
            [ChangeKind::TaskUpdated(id)],
        ))
    }

    /// Submits an active task's action, result and optional draft for approval.
    pub fn submit(
        &mut self,
        id: TaskId,
        action: Action,
        result: impl Into<String>,
        draft: Option<String>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_in(id, Column::InProgress)?;
        let task = &mut self.tasks[i];
        let text = format!("Requested approval for “{}”.", action.label.trim());
        task.action = Some(action);
        task.result = Some(result.into());
        task.draft = draft;
        Ok(self.move_with_log(i, Column::NeedsYou, Actor::Agent, text, now, None))
    }

    /// Resume an allowed proposal whose evidence survived human review.
    pub fn release_evidence_hold(&mut self, id: TaskId, now: DateTime<Utc>) -> Transition {
        self.allow_reviewed_action(id, false, now)
    }

    /// Release an allowed action, including a host-provisioned default when no rule overrides it.
    pub fn allow_reviewed_action(
        &mut self,
        id: TaskId,
        default_allowed: bool,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_in(id, Column::NeedsYou)?;
        let action = self.tasks[i]
            .action
            .as_ref()
            .ok_or(TopicError::StaleTaskReview)?;
        self.check_action_evidence(action)?;
        match decide(&self.topic.rules, action) {
            Verdict::Run(_) => {}
            Verdict::Ask(None) if default_allowed => {}
            _ => return Err(TopicError::StaleTaskReview),
        }
        Ok(self.move_with_log(
            i,
            Column::Done,
            Actor::Agent,
            format!("Allowed “{}” by topic policy.", action.label),
            now,
            None,
        ))
    }

    /// Return a previously allowed, undelivered proposal to human review.
    pub fn review_before_delivery(&mut self, id: TaskId, now: DateTime<Utc>) -> Transition {
        let i = self.task_in(id, Column::Done)?;
        Ok(self.move_with_log(
            i,
            Column::NeedsYou,
            Actor::Agent,
            "Topic policy now requires approval.".into(),
            now,
            None,
        ))
    }

    /// Approves a task awaiting review. The final text is in `Task::draft`.
    /// The `TaskApproved` change says whether to offer a standing Allow rule.
    pub fn approve(
        &mut self,
        id: TaskId,
        edited_draft: Option<String>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_in(id, Column::NeedsYou)?;
        let task = &mut self.tasks[i];
        if task.review_before_start {
            if let Some(action) = task.follow_up_action()
                && let Verdict::Refuse(rule) = decide(&self.topic.rules, &action)
            {
                return Err(TopicError::ActionDenied(rule));
            }
            task.review_before_start = false;
            task.action = None;
            task.result = None;
            return Ok(self.move_with_log(
                i,
                Column::Todo,
                Actor::User,
                "Approved starting the task.".into(),
                now,
                None,
            ));
        }
        if let Some(action) = &self.tasks[i].action {
            if let Verdict::Refuse(rule) = decide(&self.topic.rules, action) {
                return Err(TopicError::ActionDenied(rule));
            }
            self.check_action_evidence(action)?;
        }
        let task = &mut self.tasks[i];
        if let Some(draft) = edited_draft {
            task.draft = Some(draft);
        }
        let offer_always = task.action.as_ref().is_some_and(|a| !self.topic.rules.iter().any(|r|
            matches!(&r.effect, RuleEffect::Allow(kind) | RuleEffect::Deny(kind) if *kind == a.kind)));
        let text = task.action.as_ref().map_or_else(
            || format!("Completed “{}”.", task.title),
            |a| format!("Approved “{}”.", a.label),
        );
        Ok(self.move_with_log(
            i,
            Column::Done,
            Actor::User,
            text,
            now,
            Some(ChangeKind::TaskApproved {
                task: id,
                offer_always,
            }),
        ))
    }

    pub(super) fn decline_follow_up(&mut self, id: TaskId, now: DateTime<Utc>) -> Transition {
        let i = self.task_in(id, Column::NeedsYou)?;
        let task = &mut self.tasks[i];
        if !task.review_before_start || (task.parent.is_none() && task.added_by != Actor::Agent) {
            return Err(TopicError::StaleTaskReview);
        }
        task.review_before_start = false;
        task.action = None;
        let text = "Declined this follow-up.".to_owned();
        task.result = Some(text.clone());
        Ok(self.move_with_log(i, Column::Done, Actor::User, text, now, None))
    }

    /// Sends a task awaiting review back for revision and keeps the person's note in the log.
    pub fn send_back(
        &mut self,
        id: TaskId,
        note: impl Into<String>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_in(id, Column::NeedsYou)?;
        if self.tasks[i].review_before_start {
            let text = with_note("Requested a change before starting.", &note.into());
            return Ok(self.move_with_log(i, Column::NeedsYou, Actor::User, text, now, None));
        }
        let note = note.into();
        self.tasks[i].action = None;
        if matches!(self.tasks[i].assignment, Some(InboxAssignment::Routine(_))) {
            let text = with_note("Requested another routine run.", &note);
            return Ok(self.move_with_log(i, Column::Todo, Actor::User, text, now, None));
        }
        let text = with_note("Sent back for revision.", &note);
        self.tasks[i].worker = Some("Revising".into());
        Ok(self.move_with_log(i, Column::InProgress, Actor::User, text, now, None))
    }

    /// Drags a task to any board column. A drag has no approval side effects.
    pub fn move_task(&mut self, id: TaskId, to: Column, now: DateTime<Utc>) -> Transition {
        let i = self.task_index(id)?;
        if self.tasks[i].column == to {
            return Ok(vec![]);
        }
        if self.tasks[i].review_before_start && matches!(to, Column::Todo | Column::InProgress) {
            return Err(TopicError::StartNeedsApproval(id));
        }
        if matches!(to, Column::Todo | Column::InProgress)
            && let Some(action) = self.tasks[i].follow_up_action()
            && self.tasks[i].column != Column::InProgress
        {
            self.tasks[i].check_start_rule(&self.topic.rules, &action)?;
        }
        if to == Column::Done {
            self.tasks[i].review_before_start = false;
        }
        self.tasks[i].action = None;
        let text = format!("Moved “{}” to {}.", self.tasks[i].title, to.label());
        Ok(self.move_with_log(i, to, Actor::User, text, now, None))
    }

    /// Finishes active work that did not require approval.
    pub fn complete(
        &mut self,
        id: TaskId,
        result: impl Into<String>,
        now: DateTime<Utc>,
    ) -> Transition {
        let i = self.task_in(id, Column::InProgress)?;
        let result = result.into();
        let text = with_note("Completed the task.", &result);
        let chat = self.tasks[i]
            .from_thread
            .filter(|_| self.tasks[i].assignment == Some(InboxAssignment::ChatAnswer));
        if let Some(thread) = chat {
            self.thread_index(thread)?;
        }
        self.tasks[i].result = Some(result.clone());
        let mut changes = self.move_with_log(i, Column::Done, Actor::Agent, text, now, None);
        if let Some(thread) = chat {
            changes.extend(self.apply_inbox_decision(
                thread,
                Decision::Handle {
                    summary: result.clone(),
                    outcomes: vec![Outcome::Reply {
                        to: Source::User,
                        text: result,
                    }],
                },
                now,
            )?);
        }
        Ok(changes)
    }
}
