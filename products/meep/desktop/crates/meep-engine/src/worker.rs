use super::*;
use commands::submission;
use futures_util::{StreamExt, stream};
use session::started;
use std::time::Duration;
use tokio::time::Instant;

const FIRST_POLL: Duration = Duration::from_millis(250);
const MAX_POLL: Duration = Duration::from_secs(30);
const POLL_CONCURRENCY: usize = 8;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum PollTarget {
    Task(TaskId),
    Delivery(Uuid),
}

#[derive(Default)]
struct Polls(BTreeMap<PollTarget, (Work, Instant, Duration)>);

impl Polls {
    fn deadline(&self, task: PollTarget, handle: &Work) -> Instant {
        self.0
            .get(&task)
            .filter(|(h, _, _)| h == handle)
            .map_or_else(Instant::now, |(_, at, _)| *at)
    }

    fn observed(&mut self, task: PollTarget, handle: Work) {
        let delay = self
            .0
            .get(&task)
            .filter(|(h, _, _)| *h == handle)
            .map_or(FIRST_POLL, |(_, _, previous)| (*previous * 2).min(MAX_POLL));
        self.0.insert(task, (handle, Instant::now() + delay, delay));
    }
}

/// Keep distinct, selectable recommendations in the order the provider returned them.
fn suggestions(titles: Vec<String>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    titles
        .iter()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty() && seen.insert(*s))
        .map(str::to_owned)
        .collect()
}

impl Engine {
    /// Latest worker observation. Topic revision events notify readers of changes.
    pub fn task_conversation(
        &self,
        topic: TopicId,
        task: TaskId,
    ) -> Result<meep_wire::TaskConversation> {
        let slot = self.slot(topic)?;
        let s = slot.saved.read();
        let t = s
            .state
            .tasks
            .iter()
            .find(|t| t.id == task)
            .ok_or(TopicError::UnknownTask(task))?;
        let mut current =
            s.conversations
                .get(&task)
                .cloned()
                .unwrap_or_else(|| meep_wire::TaskConversation {
                    status: t
                        .worker
                        .clone()
                        .unwrap_or_else(|| format!("{:?}", t.column)),
                    messages: vec![],
                });
        if t.input_question.is_some() {
            current.status = "awaiting_input".into();
        } else if t.queued {
            current.status = "queued".into();
        }
        if let Some(history) = s.conversation_history.get(&task) {
            let mut messages: Vec<_> = history
                .iter()
                .flat_map(|c| c.messages.iter().cloned())
                .collect();
            messages.append(&mut current.messages);
            current.messages = messages;
        }
        // PostHog keeps the run's full instructions as its first turn; the person
        // sees the brief they gave, or the task's title.
        let brief = t
            .instructions
            .clone()
            .filter(|b| !b.trim().is_empty())
            .unwrap_or_else(|| meep_topic::title_line(&t.title));
        for m in &mut current.messages {
            if m.role == "user" && m.text.starts_with("[meep ") {
                m.text = brief.clone();
            }
        }
        Ok(current)
    }
    /// Deliver a user turn and track the confirmed investigation handle.
    pub async fn send_task_message(&self, topic: TopicId, task: TaskId, text: &str) -> Result<()> {
        self.send_task_message_on_model(topic, task, text, None)
            .await
    }
    /// Continue the same investigation on a selected model.
    pub async fn send_task_message_on_model(
        &self,
        topic: TopicId,
        task: TaskId,
        text: &str,
        model: Option<&str>,
    ) -> Result<()> {
        if text.trim().is_empty() {
            return Err(anyhow::anyhow!("Empty task message").into());
        }
        let slot = self.slot(topic)?;
        let guard = slot.edit.clone().lock_owned().await;
        let mut s = slot.draft();
        let t = s
            .state
            .tasks
            .iter_mut()
            .find(|t| t.id == task)
            .ok_or(TopicError::UnknownTask(task))?;
        if s.state.archived
            || s.state.deleted
            || t.action.is_some()
            || t.review_before_start
            || !matches!(
                t.column,
                Column::InProgress | Column::Done | Column::NeedsYou
            )
        {
            return Err(anyhow::anyhow!("Task is unavailable for agent messages").into());
        }
        let session = t.is_session();
        let now = self.0.clock.now();
        let mut changes = s.state.resume_task_message(task, now)?;
        let handle = match s.runs.get(&task) {
            Some(Work::Poll(h)) => Some(h),
            None => s.task_handles.get(&task),
            _ => None,
        }
        .context("No investigation run available")?;
        // The conversation continues in a new run that resumes the last one, stopping
        // any work in progress first, so its tools always work.
        let next = if session && model.is_none() {
            self.0.agent.resume_task(handle, text).await?
        } else {
            self.0
                .agent
                .message_task_on_model(handle, text, model)
                .await?
        };
        // Wait for the reply to this message: a resumed run's log can start with the
        // earlier turns, whose last answer must not be taken for this one.
        let users = if &next == handle {
            s.conversations.get(&task).map_or(0, |c| {
                c.messages.iter().filter(|m| m.role == "user").count()
            })
        } else {
            0
        };
        s.pending_messages.insert(task, (users, text.to_owned()));
        if &next != handle
            && let Some(previous) = s.conversations.remove(&task)
        {
            s.conversation_history
                .entry(task)
                .or_default()
                .push(previous);
        }
        let t = s
            .state
            .tasks
            .iter_mut()
            .find(|t| t.id == task)
            .expect("validated task");
        if let Some(model) = model {
            t.model = Some(model.to_owned());
        }
        t.log.push(LogEntry {
            at: now,
            text: text.to_owned(),
            origin: None,
        });
        if let Some(c) = s.conversations.get_mut(&task) {
            c.status = "running".into();
        }
        t.result = None;
        s.task_handles.insert(task, next.clone());
        s.runs.insert(task, Work::Poll(next));
        s.last_progress.insert(task, now);
        changes.extend(s.state.progress(task, "Running", now)?);
        self.commit(slot, guard, s, changes, &Default::default())
            .await?;
        Ok(())
    }

    pub(super) fn spawn_worker(&self, topic: TopicId) {
        if !self.0.clock.automatic() {
            return;
        }
        let stop = self.0.stop.clone();
        let weak = Arc::downgrade(&self.0);
        self.0.tasks.spawn_on(
            async move {
                tokio::select! { _ = stop.cancelled() => {}, _ = Self::drive(weak,topic) => {} }
            },
            &self.0.runtime,
        );
    }

    /// Drive one topic until the host cancels the future. Used by hosts with managed workers.
    pub async fn drive_topic(&self, topic: TopicId) {
        Self::drive(Arc::downgrade(&self.0), topic).await;
    }

    async fn drive(weak: Weak<Inner>, topic: TopicId) {
        let Some(mut wake) = weak.upgrade().and_then(|inner| {
            inner
                .topics
                .read()
                .get(&topic)
                .map(|slot| slot.wake.subscribe())
        }) else {
            return;
        };
        let mut polls = Polls::default();
        let mut retry = FIRST_POLL;
        loop {
            wake.borrow_and_update();
            let Some(inner) = weak.upgrade() else { return };
            let engine = Engine(inner, None);
            let Ok(slot) = engine.slot(topic) else { return };
            let deadline = engine.next_work(&slot.saved.read(), &mut polls);
            drop(slot);
            if deadline.is_some_and(|at| at <= Instant::now()) {
                if let Err(error) = engine.advance_topic(topic, Some(&mut polls)).await {
                    engine.emit(topic, EngineChange::WorkerError(error.to_string()));
                    drop(engine);
                    tokio::time::sleep(retry).await;
                    retry = (retry * 2).min(MAX_POLL);
                } else {
                    retry = FIRST_POLL;
                }
                continue;
            }
            drop(engine);
            if let Some(at) = deadline {
                tokio::select! {
                    _ = tokio::time::sleep_until(at) => {},
                    changed = wake.changed() => if changed.is_err() { return },
                }
            } else if wake.changed().await.is_err() {
                return;
            }
        }
    }

    fn next_work(&self, s: &StoredTopic, polls: &mut Polls) -> Option<Instant> {
        let now = self.0.clock.now();
        if s.state.archived || s.state.deleted {
            return None;
        }
        let instant = Instant::now();
        let deadline = |date: DateTime<Utc>| instant + (date - now).to_std().unwrap_or_default();
        polls.0.retain(|task, (work, _, _)| match task {
            PollTarget::Task(id) => s.runs.get(id) == Some(work),
            PollTarget::Delivery(key) => s.deliveries.get(key).is_some_and(|d| &d.work == work),
        });
        if s.next_effect(now).is_some() || self.setup_due(s) || session::next_step(s).is_some() {
            return Some(instant);
        }
        let tasks = s
            .state
            .tasks
            .iter()
            .filter(|t| watched(s, t))
            .filter_map(|t| match s.runs.get(&t.id) {
                Some(handle @ (Work::Poll(_) | Work::AssignedFlow { .. })) => {
                    Some(polls.deadline(PollTarget::Task(t.id), handle))
                }
                Some(Work::Stopped) if stopped_problem(t).is_some() => Some(instant),
                None if startable(s, t) && self.0.agent.can_take_for(s.state.topic.id, t) => {
                    s.starts.next_start(now, self.0.limits).map(deadline)
                }
                _ => None,
            });
        let memory = s
            .fact_checks
            .front()
            .map(|job| job.retry_at.map_or(instant, deadline));
        let deliveries = s
            .deliveries
            .iter()
            .map(|(key, d)| polls.deadline(PollTarget::Delivery(*key), &d.work));
        s.observation_deadlines()
            .map(|(_, at)| deadline(at))
            .chain(
                s.ready_sorts()
                    .map(|(_, job)| job.retry_at.map_or(instant, deadline)),
            )
            .chain(
                s.effects
                    .iter()
                    .filter_map(|e| e.retry_at)
                    .filter(|at| *at > now)
                    .map(deadline),
            )
            .chain(tasks)
            .chain(memory)
            .chain(deliveries)
            .min()
    }

    /// Advances due schedules and workers once, then waits for resulting routines to settle.
    pub async fn tick(&self) -> Result<()> {
        let mut error = self.poll_connections().await.err();
        for topic in self.topic_ids() {
            if let Err(e) = self.tick_topic(topic).await {
                error.get_or_insert(e);
            }
        }
        error.map_or(Ok(()), Err)
    }

    /// Advance a single topic on a host-managed worker schedule.
    pub async fn tick_topic(&self, topic: TopicId) -> Result<()> {
        self.advance_topic(topic, None).await
    }

    async fn advance_topic(&self, topic: TopicId, mut polls: Option<&mut Polls>) -> Result<()> {
        let slot = self.slot(topic)?;
        let _worker = slot.worker.lock().await;
        if slot.saved.read().state.archived || slot.saved.read().state.deleted {
            return Ok(());
        }
        self.deliver_effects(topic).await?;
        self.begin_setup(topic).await?;
        let due: Vec<_> = slot
            .saved
            .read()
            .observation_deadlines()
            .filter(|(_, at)| *at <= self.0.clock.now())
            .take(if polls.is_some() { 64 } else { usize::MAX })
            .map(|(key, _)| key)
            .collect();
        for key in due {
            self.advance_observation(topic, key).await?;
        }
        self.sort_pending(topic).await?;
        self.reconcile_facts(topic).await?;
        // The conversation goes before other work, so a message it starts runs this pass.
        let session = self.drive_session(topic).await;
        let (starts, running) = {
            let saved = slot.saved.read();
            let mut starts = Vec::new();
            let mut running = Vec::new();
            let due = |target, handle: &Work| {
                polls
                    .as_ref()
                    .is_none_or(|p| p.deadline(target, handle) <= Instant::now())
            };
            for task in &saved.state.tasks {
                if watched(&saved, task) {
                    let target = PollTarget::Task(task.id);
                    match saved.runs.get(&task.id) {
                        Some(handle @ (Work::Poll(_) | Work::AssignedFlow { .. }))
                            if due(target, handle) =>
                        {
                            running.push((target, handle.clone()))
                        }
                        Some(Work::Stopped) if stopped_problem(task).is_some() => {
                            starts.push(task.id)
                        }
                        None if startable(&saved, task) => starts.push(task.id),
                        _ => {}
                    }
                }
            }
            for (key, delivery) in &saved.deliveries {
                let target = PollTarget::Delivery(*key);
                if due(target, &delivery.work) {
                    running.push((target, delivery.work.clone()));
                }
            }
            (starts, running)
        };
        let mut first_error = None;
        for task in starts {
            if let Err(error) = self.advance(topic, &slot, task).await {
                first_error.get_or_insert(error);
            }
        }
        let mut pending = stream::iter(running)
            .map(|(id, handle)| {
                let slot = &slot;
                async move {
                    let result = match id {
                        PollTarget::Task(task) => self.advance(topic, slot, task).await,
                        PollTarget::Delivery(key) => self.poll_delivery(topic, key, &handle).await,
                    };
                    (id, handle, result)
                }
            })
            .buffer_unordered(POLL_CONCURRENCY);
        while let Some((id, handle, result)) = pending.next().await {
            if let Some(polls) = polls.as_deref_mut() {
                polls.observed(id, handle);
            }
            if let Err(error) = result {
                first_error.get_or_insert(error);
            }
        }
        if let Err(error) = session {
            first_error.get_or_insert(error);
        }
        first_error.map_or(Ok(()), Err)
    }

    async fn poll_delivery(&self, topic: TopicId, key: Uuid, approved: &Work) -> Result<()> {
        let now = self.0.clock.now();
        let result = match approved {
            Work::Approved(handle) => self.0.agent.poll_at(handle, now).await?,
            Work::Routine {
                binding,
                generation,
                invocation,
            } => {
                if !self.binding_is_current(topic, binding, *generation)? {
                    RunState::Failed {
                        error: "The proposing routine was removed or rebound.".into(),
                    }
                } else {
                    let status = self
                        .status_bound(topic, binding, *generation, *invocation)
                        .await?
                        .status;
                    match routines::InvocationStatus::from_provider(&status) {
                        routines::InvocationStatus::Succeeded => RunState::Done {
                            result: format!("Routine {}: {status}", binding.name),
                        },
                        routines::InvocationStatus::Failed => RunState::Failed { error: status },
                        routines::InvocationStatus::Pending => return Ok(()),
                    }
                }
            }
            _ => return Ok(()),
        };
        let failed = matches!(result, RunState::Failed { .. } | RunState::Submitted { .. });
        let mut next_steps = vec![];
        let detail = match result {
            RunState::Running { .. } => return Ok(()),
            RunState::Done { result } => result,
            RunState::Findings { result, follow_ups } => {
                next_steps = suggestions(follow_ups);
                result
            }
            RunState::Failed { error } => format!("Execution failed: {error}"),
            RunState::Submitted { .. } => {
                "Execution failed: the approved action produced another proposal".into()
            }
        };
        self.update(topic, &Default::default(), |s, now| {
            let Some(delivery) = s.deliveries.remove(&key) else {
                return Ok(vec![]);
            };
            let detail = match (failed, delivery.action_label) {
                (true, Some(label)) => format!("{detail} (action: {label})"),
                _ => detail,
            };
            if failed && let Work::Routine { binding, .. } = approved {
                s.routine_failed(&binding.id, &detail, now, &Default::default());
            }
            let subject = Ref::Task(delivery.task);
            let current = s.state.tasks.iter_mut().find(|t| {
                t.id == delivery.task
                    && t.column == Column::Done
                    && Some(t.log.len()) == delivery.task_log_len
            });
            let needs_review = failed && current.is_some();
            if let Some(task) = current {
                if failed {
                    task.action = None;
                } else {
                    task.suggestions = next_steps;
                    task.result = Some(detail.clone());
                    task.updated_at = now;
                    task.log.push(LogEntry {
                        origin: None,
                        at: now,
                        text: detail.clone(),
                    });
                }
            }
            Ok(s.state
                .delivery_receipt(key, subject, detail, needs_review, now)?)
        })
        .await?;
        Ok(())
    }

    /// Pause the authenticated investigation until a person replies on the same task.
    pub async fn ask_user(&self, topic: TopicId, run: &RunHandle, question: &str) -> Result<()> {
        let question = question.trim();
        if question.is_empty() || question.chars().count() > 8000 {
            return Err(anyhow::anyhow!("Question must be 1 to 8000 characters").into());
        }
        self.update(topic, &Default::default(), |s, now| {
            let task = s
                .runs
                .iter()
                .find_map(|(id, work)| match work {
                    Work::Poll(handle) if handle == run => Some(*id),
                    _ => None,
                })
                .context("No active investigation for this run")?;
            let changes = s.state.ask_user(task, question.to_owned(), now)?;
            s.runs.remove(&task);
            Ok(changes)
        })
        .await?;
        Ok(())
    }

    /// Submit a proposal for the investigation represented by the authenticated run handle.
    pub async fn propose_action(
        &self,
        topic: TopicId,
        run: &RunHandle,
        requested: Option<TaskId>,
        action: Action,
        draft: Option<String>,
    ) -> Result<()> {
        self.update(topic, &Default::default(), |s, now| {
            let task = s
                .runs
                .iter()
                .find_map(|(id, w)| (w == &Work::Poll(run.clone())).then_some(*id))
                .context("No active investigation for this run")?;
            if requested.is_some_and(|id| id != task) {
                return Err(anyhow::anyhow!("Proposal belongs to a different task").into());
            }
            // The conversation asks in a permission prompt and keeps its run until the
            // turn ends there; approving it reaches the agent as a note to carry it out.
            if s.state.tasks.iter().any(|t| t.id == task && t.is_session()) {
                let verdict = decide(&s.state.topic.rules, &action);
                if let Verdict::Refuse(rule) = verdict {
                    return Err(TopicError::ActionDenied(rule).into());
                }
                let mut changes =
                    s.state
                        .submit(task, action.clone(), action.label.clone(), draft, now)?;
                s.proposals
                    .insert(task, effects::Proposer::Agent(run.clone()));
                if matches!(verdict, Verdict::Run(_))
                    && s.state.check_action_evidence(&action).is_ok()
                {
                    changes.extend(s.state.allow_reviewed_action(task, false, now)?);
                    s.queue_approval(task, Uuid::new_v4(), true);
                }
                return Ok(changes);
            }
            s.proposals
                .insert(task, effects::Proposer::Agent(run.clone()));
            let result = action.label.clone();
            submission(s, task, action, result, draft, now)
        })
        .await?;
        Ok(())
    }
    pub(super) async fn advance(&self, topic: TopicId, slot: &Slot, task_id: TaskId) -> Result<()> {
        if slot.saved.read().runs.get(&task_id) == Some(&Work::Stopped) {
            self.update(topic, &Default::default(), |s, now| {
                let problem = s
                    .state
                    .tasks
                    .iter()
                    .find(|t| t.id == task_id)
                    .and_then(stopped_problem);
                if s.runs.get(&task_id) == Some(&Work::Stopped)
                    && let Some(detail) = problem
                {
                    s.runs.remove(&task_id);
                    return Ok(s
                        .state
                        .work_needs_attention(task_id, detail.to_owned(), now)?);
                }
                Ok(vec![])
            })
            .await?;
            return Ok(());
        }
        let now = self.0.clock.now();
        let (task, work, context) = {
            let saved = slot.saved.read();
            let task = saved
                .state
                .tasks
                .iter()
                .find(|t| t.id == task_id)
                .ok_or(TopicError::UnknownTask(task_id))?;
            if !watched(&saved, task) {
                return Ok(());
            }
            let work = saved.runs.get(&task_id).cloned();
            let run = match &work {
                Some(Work::Stopped) => return Ok(()),
                Some(
                    Work::Poll(_)
                    | Work::Approved(_)
                    | Work::Routine { .. }
                    | Work::AssignedFlow { .. },
                ) => None,
                None if agent_assigned(task)
                    && self.0.agent.can_take_for(topic, task)
                    && saved.starts.has_capacity(now, self.0.limits) =>
                {
                    let (facts, historical_facts) = saved
                        .state
                        .topic
                        .facts
                        .iter()
                        .cloned()
                        .partition(|f| f.is_current());
                    Some(AgentRun {
                        topic_name: saved.state.topic.name.clone(),
                        mission: saved.state.topic.mission.clone(),
                        goals: saved.state.topic.goals.clone(),
                        context_sources: saved.state.topic.context_sources.clone(),
                        watches: saved.state.topic.watches().cloned().collect::<Vec<_>>(),
                        routines: saved.state.topic.routines.clone(),
                        disputed_fact_ids: saved.state.disputed_facts(),
                        facts,
                        historical_facts,
                        rules: saved.state.topic.rules.clone(),
                        thread: task
                            .from_thread
                            .and_then(|id| saved.state.threads.iter().find(|t| t.id == id))
                            .cloned(),
                        task: task.clone(),
                        setup: saved.setup == setup::Setup::Started(task.id),
                        started_at: now,
                    })
                }
                None => return Ok(()),
            };
            (task.clone(), work, run)
        };
        if let Some(context) = context {
            // Claim the task before calling an external provider. An ambiguous start must
            // never be reissued just because the process restarted.
            let mut claimed = false;
            self.update(topic, &Causality::default(), |s, now| {
                if s.state.archived
                    || !s.state.tasks.contains(&task)
                    || s.runs.contains_key(&task_id)
                {
                    return Ok(vec![]);
                }
                let held = s.state.review_follow_up_start(task_id, now)?;
                if !held.is_empty() || !s.starts.try_start(now, self.0.limits) {
                    return Ok(held);
                }
                claimed = true;
                s.state.usage.agent_starts.push(now);
                s.runs.insert(task_id, Work::Stopped);
                let changes = if task.column == Column::Todo {
                    s.state.start(task_id, "Starting", now)?
                } else {
                    s.state.progress(task_id, "Starting", now)?
                };
                Ok(changes)
            })
            .await?;
            if !claimed {
                return Ok(());
            }
            let started = self.0.agent.start_for(topic, context).await;
            // A task the person left untitled takes the name PostHog gave it.
            let named = match (&started, task.untitled) {
                (Ok(handle), true) => self.0.agent.task_title(handle).await.ok().flatten(),
                _ => None,
            };
            self.update(topic, &Causality::default(), |s, now| {
                let current = s.state.tasks.iter().find(|t| t.id == task_id);
                if s.runs.get(&task_id) != Some(&Work::Stopped)
                    || current.is_none_or(|t| {
                        t.column != Column::InProgress || t.worker.as_deref() != Some("Starting")
                    })
                {
                    if let Ok(handle) = started {
                        s.queue_effect(
                            Uuid::new_v4(),
                            effects::Target::Cancel(handle),
                            Ref::Task(task_id),
                        );
                    }
                    return Ok(vec![]);
                }
                match started {
                    Ok(handle) => {
                        if let Some(title) = named
                            && let Some(t) = s.state.tasks.iter_mut().find(|t| t.id == task_id)
                        {
                            t.title = title;
                            t.untitled = false;
                        }
                        s.task_handles.insert(task_id, handle.clone());
                        s.runs.insert(task_id, Work::Poll(handle));
                        s.last_progress.insert(task_id, now);
                        Ok(s.state.progress(task_id, "Running", now)?)
                    }
                    Err(e) => {
                        s.runs.remove(&task_id);
                        Ok(s.state.work_needs_attention(
                            task_id,
                            format!("Start failed: {e}"),
                            now,
                        )?)
                    }
                }
            })
            .await?;
        } else if let Some(owned @ Work::AssignedFlow { .. }) = work {
            self.advance_assigned_flow(topic, &task, owned).await?;
        } else if let Some(Work::Poll(handle)) = work {
            let mut wake = slot.wake.subscribe();
            let last_progress = slot
                .saved
                .read()
                .last_progress
                .get(&task_id)
                .copied()
                .unwrap_or(task.updated_at);
            let remaining = (last_progress + chrono::Duration::minutes(60) - now)
                .to_std()
                .unwrap_or_default();
            let observed = if remaining.is_zero() {
                None
            } else {
                let observation =
                    tokio::time::timeout(remaining, self.0.agent.observe_task(&handle, now));
                tokio::pin!(observation);
                loop {
                    if !matches!(slot.saved.read().runs.get(&task_id),Some(Work::Poll(current)) if current==&handle)
                    {
                        return Ok(());
                    }
                    tokio::select! {
                        result=&mut observation=>break result.ok().transpose()?,
                        _=wake.changed()=>{}
                    }
                }
            };
            let timed_out = observed.is_none();
            let (mut result, mut conversation) = observed.unwrap_or_else(|| {
                (
                    RunState::Failed {
                        error: "No progress for 60 minutes.".into(),
                    },
                    None,
                )
            });
            let waiting = slot.saved.read().pending_messages.get(&task_id).cloned();
            let awaiting_turn = if let (Some((users, text)), Some(c)) = (&waiting, &conversation) {
                let mut seen = 0;
                let mut answered = false;
                let mut received = false;
                for m in &c.messages {
                    if m.role == "user" {
                        if seen >= *users && &m.text == text {
                            received = true;
                            answered = false;
                        }
                        seen += 1;
                    }
                    if received && m.role == "assistant" {
                        answered = true;
                    }
                }
                // A resumed run's log starts with the earlier turns; a "cancelled" from
                // the run it resumed is not this turn failing.
                let replayed_stop = !received
                    && matches!(&result, RunState::Failed { error } if error == "Run cancelled");
                (!answered && !matches!(result, RunState::Failed { .. })) || replayed_stop
            } else {
                false
            };
            if awaiting_turn {
                result = RunState::Running {
                    progress: "Waiting for reply".into(),
                };
                if let Some(c) = &mut conversation {
                    c.status = "Waiting for reply".into();
                }
            }
            let changed = conversation
                .as_ref()
                .is_some_and(|c| slot.saved.read().conversations.get(&task_id) != Some(c));
            if !changed
                && matches!(&result,RunState::Running {progress} if Some(progress)==task.worker.as_ref())
            {
                return Ok(());
            }
            // A finished turn leaves its interactive run waiting in a sandbox; stop it
            // afterwards, since the next turn resumes from it and PostHog caps open sandboxes.
            let mut idle_run = None;
            self.update(topic, &Causality::default(), |s, now| {
                if s.state.archived
                    || !s.state.tasks.contains(&task)
                    || s.runs.get(&task_id) != Some(&Work::Poll(handle.clone()))
                {
                    return Ok(vec![]);
                }
                if !awaiting_turn {
                    s.pending_messages.remove(&task_id);
                }
                if let Some(mut c) = conversation {
                    if c.messages.is_empty()
                        && let Some(previous) = s.conversations.get_mut(&task_id)
                    {
                        c.messages = std::mem::take(&mut previous.messages);
                    }
                    s.conversations.insert(task_id, c);
                }
                s.task_handles.insert(task_id, handle.clone());
                if timed_out {
                    s.queue_effect(
                        Uuid::new_v4(),
                        effects::Target::Cancel(handle.clone()),
                        Ref::Task(task_id),
                    );
                }
                match result {
                    RunState::Running { progress } => {
                        s.last_progress.insert(task_id, now);
                        if task.worker.as_ref() == Some(&progress) {
                            Ok(vec![])
                        } else {
                            Ok(s.state.progress(task_id, progress, now)?)
                        }
                    }
                    // The conversation's turn ended at a permission prompt: post what it
                    // said and leave the prompt open for the person.
                    RunState::Done { result } | RunState::Findings { result, .. }
                        if task.is_session() && task.column == Column::NeedsYou =>
                    {
                        s.runs.remove(&task_id);
                        idle_run = Some(handle.clone());
                        let Some(thread) = task.from_thread else {
                            return Ok(vec![]);
                        };
                        Ok(s.state.apply_inbox_decision(
                            thread,
                            Decision::Handle {
                                summary: result.clone(),
                                outcomes: vec![Outcome::Reply {
                                    to: Source::User,
                                    text: result,
                                }],
                            },
                            now,
                        )?)
                    }
                    RunState::Done { result } => {
                        s.runs.remove(&task_id);
                        if task.is_session() {
                            idle_run = Some(handle.clone());
                        }
                        report_to_conversation(s, &task, "finished", &result);
                        Ok(s.state.complete(task_id, result, now)?)
                    }
                    RunState::Findings { result, follow_ups } => {
                        s.runs.remove(&task_id);
                        report_to_conversation(s, &task, "finished", &result);
                        if task.assignment != Some(InboxAssignment::ChatAnswer) {
                            s.state
                                .tasks
                                .iter_mut()
                                .find(|t| t.id == task_id)
                                .expect("checked active task")
                                .suggestions = suggestions(follow_ups);
                        }
                        Ok(s.state.complete(task_id, result, now)?)
                    }
                    RunState::Failed { error } => {
                        s.runs.remove(&task_id);
                        report_to_conversation(s, &task, "failed", &error);
                        Ok(s.state.work_needs_attention(
                            task_id,
                            format!("Failed: {error}"),
                            now,
                        )?)
                    }
                    RunState::Submitted { .. }
                        if task.assignment == Some(InboxAssignment::ChatAnswer) =>
                    {
                        s.runs.remove(&task_id);
                        Ok(s.state.work_needs_attention(
                            task_id,
                            "The question returned an action proposal instead of an answer.".into(),
                            now,
                        )?)
                    }
                    RunState::Submitted {
                        action,
                        result,
                        draft,
                    } => {
                        s.proposals
                            .insert(task_id, effects::Proposer::Agent(handle));
                        submission(s, task_id, action, result, draft, now)
                    }
                }
            })
            .await?;
            if let Some(run) = idle_run {
                // Best effort: a run that already ended has nothing to stop.
                let _ = self.0.agent.cancel(&run).await;
            }
        }
        Ok(())
    }
}

/// A sub-agent's result goes back to the conversation that planned it, so the topic's
/// agent can summarise it for the person on its next turn.
fn report_to_conversation(s: &mut StoredTopic, task: &Task, outcome: &str, text: &str) {
    if !matches!(task.added_by, meep_topic::Actor::Agent)
        || task.assignment != Some(InboxAssignment::Investigate)
    {
        return;
    }
    let text: String = text.trim().chars().take(1500).collect();
    s.inbox.note(
        &format!("A sub-agent {outcome}:"),
        &format!("{}: {text}", meep_topic::title_line(&task.title)),
    );
}

// A stopped start is ambiguous after a restart.
fn stopped_problem(task: &Task) -> Option<&str> {
    (task.column == Column::InProgress && task.worker.as_deref() == Some("Starting"))
        .then_some("Start outcome unknown after interruption. Check the provider before retrying.")
}

/// Tasks the worker starts or watches: open work, and the conversation while its run
/// waits on a permission prompt.
fn watched(s: &StoredTopic, t: &Task) -> bool {
    matches!(t.column, Column::Todo | Column::InProgress)
        || (t.is_session() && matches!(s.runs.get(&t.id), Some(Work::Poll(_))))
}

/// Agent work that needs a new run. The conversation gets one run ever; later turns
/// resume it.
fn startable(s: &StoredTopic, t: &Task) -> bool {
    agent_assigned(t) && !(t.is_session() && started(s, t.id))
}

fn agent_assigned(task: &Task) -> bool {
    !task.queued
        && !task.review_before_start
        && matches!(
            task.assignment,
            None | Some(InboxAssignment::Investigate | InboxAssignment::ChatAnswer)
        )
}
