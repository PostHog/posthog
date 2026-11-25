//! Approval and reply delivery. The intent and stable delivery key are committed
//! with the originating transition. Provider I/O happens outside the edit lock.
use super::*;
use serde_json::Value;
use serde_json::json;

fn dispatch_uncertain(error: &anyhow::Error) -> bool {
    error.is::<DispatchUncertain>()
        || error.downcast_ref::<Error>().is_some_and(
            |e| matches!(e, Error::Integration(cause) if cause.is::<DispatchUncertain>()),
        )
}

#[derive(Clone, Serialize, Deserialize)]
pub(super) enum Proposer {
    Agent(RunHandle),
    Run {
        binding: RoutineBinding,
        generation: Option<CommandId>,
        variables: serde_json::Map<String, Value>,
    },
    BindActive(RoutineBinding),
    Activation {
        binding: RoutineBinding,
        generation: Option<CommandId>,
    },
    Routine {
        #[serde(flatten)]
        binding: RoutineBinding,
        #[serde(default)]
        generation: Option<CommandId>,
    },
}

#[derive(Clone, Serialize, Deserialize)]
pub(super) enum Target {
    Cancel(RunHandle),
    Reconnect(String),
    Run {
        binding: RoutineBinding,
        generation: Option<CommandId>,
        variables: serde_json::Map<String, Value>,
    },
    UnknownProposer,
    Proposal(Proposer),
    Reply {
        message: Message,
        text: String,
    },
}

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Effect {
    #[serde(default)]
    pub(super) retry_at: Option<DateTime<Utc>>,
    key: Uuid,
    target: Target,
    pub(super) task: Option<Task>,
    subject: Ref,
    #[serde(default)]
    claimed: bool,
    #[serde(default)]
    safe_retry: bool,
    #[serde(default)]
    automatic: bool,
}

#[derive(Clone, PartialEq, Serialize, Deserialize)]
pub(super) struct Delivery {
    pub(super) task: TaskId,
    pub(super) work: Work,
    #[serde(default)]
    pub(super) action_label: Option<String>,
    // A later task transition appends to this log and gets its own result.
    pub(super) task_log_len: Option<usize>,
}

impl StoredTopic {
    pub(super) fn retry_dispatch(&mut self, key: Uuid) {
        if let Some(effect) = self.effects.iter_mut().find(|e| e.key == key)
            && (!matches!(effect.target, Target::Run { .. }) || effect.safe_retry)
        {
            effect.retry_at = None;
        }
    }
    pub(super) fn queue_effect(&mut self, key: Uuid, target: Target, subject: Ref) {
        self.effects.push_back(Effect {
            retry_at: None,
            safe_retry: false,
            key,
            target,
            subject,
            task: None,
            claimed: false,
            automatic: false,
        });
    }

    pub(super) fn next_effect(&self, now: DateTime<Utc>) -> Option<&Effect> {
        if self.state.archived || self.state.deleted {
            return None;
        }
        self.effects
            .iter()
            .filter(|e| e.retry_at.is_none_or(|at| at <= now))
            .find(|effect| {
                effect.claimed
                    || effect
                        .task
                        .as_ref()
                        .and_then(|t| t.action.as_ref())
                        .is_none_or(|action| {
                            matches!(decide(&self.state.topic.rules, action), Verdict::Refuse(_))
                                || self.state.check_action_evidence(action)
                                    != Err(TopicError::DisputedEvidence)
                        })
            })
    }

    pub(super) fn release_evidence_holds(&mut self, now: DateTime<Utc>) -> Result<Changes> {
        let mut changes = vec![];
        for task in self.evidence_holds.clone() {
            let action = self
                .state
                .tasks
                .iter()
                .find(|t| t.id == task && t.column == Column::NeedsYou)
                .and_then(|t| t.action.as_ref());
            if let Some(action) = action {
                match self.state.check_action_evidence(action) {
                    Err(TopicError::DisputedEvidence) => continue,
                    Ok(())
                        if matches!(decide(&self.state.topic.rules, action), Verdict::Run(_)) =>
                    {
                        changes.extend(self.state.release_evidence_hold(task, now)?);
                        self.queue_approval(task, Uuid::new_v4(), true);
                    }
                    _ => {}
                }
            }
            self.evidence_holds.remove(&task);
        }
        Ok(changes)
    }

    pub(super) fn queue_reply(&mut self, thread: ThreadId, text: &str, key: Uuid) {
        if let Some(message) = self
            .state
            .threads
            .iter()
            .find(|t| t.id == thread)
            .and_then(|t| {
                t.messages.iter().rev().find(|m| {
                    matches!(
                        m.reply_target(),
                        Some(Source::Connection { .. } | Source::Topic(_))
                    )
                })
            })
        {
            self.effects.push_back(Effect {
                retry_at: None,
                safe_retry: false,
                key,
                target: Target::Reply {
                    message: message.clone(),
                    text: text.into(),
                },
                task: None,
                subject: Ref::Thread(thread),
                claimed: false,
                automatic: false,
            });
        }
    }

    pub(super) fn queue_approval(&mut self, task_id: TaskId, key: Uuid, automatic: bool) {
        let Some(task) = self
            .state
            .tasks
            .iter()
            .find(|t| t.id == task_id && t.column == Column::Done && t.action.is_some())
        else {
            return;
        };
        // The conversation's own proposal: nothing runs from outside. The agent is told
        // in its next turn to carry out exactly what it proposed.
        if matches!(self.proposals.get(&task_id), Some(Proposer::Agent(_)))
            && session::session_task(self) == Some(task_id)
        {
            let action = task.action.clone().expect("checked action");
            let draft = task.draft.clone();
            self.proposals.remove(&task_id);
            if let Some(t) = self.state.tasks.iter_mut().find(|t| t.id == task_id) {
                t.action = None;
            }
            // The label leads, so the chat's line for this turn reads well; the agent
            // gets the exact change on the next line.
            let mut line = format!("{}\n  Exactly: {}", action.label, action.payload);
            if let Some(draft) = draft {
                line.push_str(&format!(" (reviewed draft: {draft})"));
            }
            self.inbox.note(
                if automatic {
                    "Allowed by the person's rule; carry it out now, exactly as proposed:"
                } else {
                    "The person approved; carry it out now, exactly as proposed:"
                },
                &line,
            );
            return;
        }
        let target = if let Some(owner) = self.proposals.remove(&task_id) {
            Target::Proposal(owner)
        } else if let Actor::Inbox(thread) = task.added_by
            && let Some(to) = task
                .action
                .as_ref()
                .and_then(|a| a.payload.get("to"))
                .and_then(|v| serde_json::from_value::<Source>(v.clone()).ok())
            && let Some(message) =
                self.state
                    .threads
                    .iter()
                    .find(|t| t.id == thread)
                    .and_then(|t| {
                        let original = task.action.as_ref()?.payload.get("message");
                        match original {
                            Some(value) => {
                                let id: MessageId = serde_json::from_value(value.clone()).ok()?;
                                t.messages
                                    .iter()
                                    .find(|m| m.id == id && m.reply_target().as_ref() == Some(&to))
                            }
                            None => t
                                .messages
                                .iter()
                                .rev()
                                .find(|m| m.reply_target().as_ref() == Some(&to)),
                        }
                    })
            && let Some(text) = &task.draft
        {
            Target::Reply {
                message: message.clone(),
                text: text.clone(),
            }
        } else {
            Target::UnknownProposer
        };
        self.effects.push_back(Effect {
            retry_at: None,
            safe_retry: false,
            key,
            target,
            task: Some(task.clone()),
            subject: Ref::Task(task_id),
            claimed: false,
            automatic,
        });
    }
}

#[derive(Debug, thiserror::Error)]
#[error("Topic policy requires approval before activation")]
struct ApprovalRequired;

enum Delivered {
    Receipt(String),
    Tracking(Work),
    Invocation(RoutineBinding, Option<CommandId>, RoutineRun),
}

/// Where a native workflow action is reviewed.
#[derive(Clone, Copy)]
pub enum WorkflowReview<'a> {
    /// Standalone request from the host or provisioning worker.
    Request(TaskId),
    /// Review on the Meep task authenticated by this provider run.
    Investigation(&'a RunHandle),
}

impl Engine {
    /// Apply topic action policy to a request to activate this exact workflow binding.
    /// The returned task carries the durable decision and its delivery outcome.
    pub async fn request_routine_activation(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        request: TaskId,
        facts: Option<Vec<FactId>>,
    ) -> Result<Task> {
        self.review_routine_activation(topic, binding, WorkflowReview::Request(request), facts)
            .await
    }

    /// Request activation on the originating work.
    pub async fn review_routine_activation(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        review: WorkflowReview<'_>,
        facts: Option<Vec<FactId>>,
    ) -> Result<Task> {
        let (_, generation) = self.binding(topic, &binding.id)?;
        let action = Action {
            kind: ActionKind("routine-activate".into()),
            label: format!("Activate {}", binding.name),
            done_label: format!("Activated {}", binding.name),
            depends_on_facts: facts,
            payload: json!({"routine":binding.id,"flow":binding.external_id,"generation":generation}),
        };
        let proposer = Proposer::Activation {
            binding: binding.clone(),
            generation,
        };
        self.request_workflow_action(topic, review, action, proposer)
            .await
    }
    /// Review a run requested by an agent before dispatching the bound workflow.
    pub async fn request_routine_run(
        &self,
        topic: TopicId,
        routine: &str,
        variables: serde_json::Map<String, Value>,
    ) -> Result<Task> {
        self.review_routine_run(topic, routine, variables, WorkflowReview::Request(id()))
            .await
    }

    /// Request a workflow run on the originating work.
    pub async fn review_routine_run(
        &self,
        topic: TopicId,
        routine: &str,
        variables: serde_json::Map<String, Value>,
        review: WorkflowReview<'_>,
    ) -> Result<Task> {
        let (binding, generation) = self.binding(topic, routine)?;
        self.ensure_manual_routine(topic, routine)?;
        let action = Action {
            kind: ActionKind("routine-run".into()),
            label: format!("Run {}", binding.name),
            done_label: format!("Started {}", binding.name),
            depends_on_facts: None,
            payload: json!({"routine":routine,"flow":binding.external_id,"generation":generation,"variables":variables}),
        };
        self.request_workflow_action(
            topic,
            review,
            action,
            Proposer::Run {
                binding,
                generation,
                variables,
            },
        )
        .await
    }
    /// Review binding a workflow that is already active at the provider.
    pub async fn request_active_binding(
        &self,
        topic: TopicId,
        binding: RoutineBinding,
    ) -> Result<Task> {
        self.review_active_binding(topic, binding, WorkflowReview::Request(id()))
            .await
    }

    /// Request a binding on the originating work.
    pub async fn review_active_binding(
        &self,
        topic: TopicId,
        binding: RoutineBinding,
        review: WorkflowReview<'_>,
    ) -> Result<Task> {
        let action = Action {
            kind: ActionKind("routine-activate".into()),
            label: format!("Bind active workflow {}", binding.name),
            done_label: format!("Bound {}", binding.name),
            depends_on_facts: None,
            payload: json!({"bind":binding}),
        };
        self.request_workflow_action(topic, review, action, Proposer::BindActive(binding))
            .await
    }
    async fn request_workflow_action(
        &self,
        topic: TopicId,
        review: WorkflowReview<'_>,
        action: Action,
        proposer: Proposer,
    ) -> Result<Task> {
        let mut selected = None;
        self.update(topic, &Default::default(), |s, now| {
            let request = match review {
                WorkflowReview::Request(request) => request,
                WorkflowReview::Investigation(run) => {
                    let task = s
                        .runs
                        .iter()
                        .find_map(|(task, work)| {
                            matches!(work, Work::Poll(h) if h == run).then_some(*task)
                        })
                        .context("This run no longer owns an active task")?;
                    selected = Some(task);
                    let verdict = decide(&s.state.topic.rules, &action);
                    if let Verdict::Refuse(rule) = verdict {
                        return Err(TopicError::ActionDenied(rule).into());
                    }
                    let mut changes =
                        s.state
                            .submit(task, action.clone(), action.label.clone(), None, now)?;
                    // The conversation keeps its run, and its tools, until the turn ends
                    // at the prompt; other agent work stops here for the review.
                    if !s.state.tasks.iter().any(|t| t.id == task && t.is_session()) {
                        s.runs.remove(&task);
                    }
                    s.proposals.insert(task, proposer.clone());
                    if matches!(verdict, Verdict::Run(_)) {
                        match s.state.check_action_evidence(&action) {
                            Ok(()) => {
                                changes.extend(s.state.allow_reviewed_action(task, false, now)?);
                                s.queue_approval(task, Uuid::new_v4(), true);
                            }
                            Err(TopicError::DisputedEvidence) => {
                                s.evidence_holds.insert(task);
                            }
                            Err(e) => return Err(e.into()),
                        }
                    }
                    return Ok(changes);
                }
            };
            let existing = s
                .activation_aliases
                .get(&request)
                .copied()
                .unwrap_or(request);
            selected = Some(existing);
            if let Some(task) = s.state.tasks.iter().find(|t| t.id == existing) {
                if task.action.as_ref() != Some(&action) {
                    return Err(TopicError::StaleTaskReview.into());
                }
                // Enabling a flow is an idempotent status update. Resume the same setup
                // task after provider recovery, and recheck policy before delivery.
                if s.default_activation(existing, &action)
                    && matches!(
                        decide(&s.state.topic.rules, &action),
                        Verdict::Run(_) | Verdict::Ask(None)
                    )
                    && task
                        .result
                        .as_deref()
                        .is_some_and(|r| r.starts_with("Delivery failed:"))
                    && !s
                        .effects
                        .iter()
                        .any(|e| e.task.as_ref().is_some_and(|t| t.id == existing))
                {
                    let changes = if task.column == Column::NeedsYou {
                        s.state.allow_reviewed_action(existing, true, now)?
                    } else {
                        vec![]
                    };
                    s.proposals.insert(existing, proposer.clone());
                    s.queue_approval(existing, Uuid::new_v4(), true);
                    return Ok(changes);
                }
                return Ok(vec![]);
            }
            if let Proposer::Activation {
                binding,
                generation,
            }
            | Proposer::Run {
                binding,
                generation,
                ..
            } = &proposer
                && !self.binding_is_current(topic, binding, *generation)?
            {
                return Err(TopicError::StaleTaskReview.into());
            }
            if let Verdict::Refuse(rule) = decide(&s.state.topic.rules, &action) {
                return Err(TopicError::ActionDenied(rule).into());
            }
            if let Some(task) = s
                .state
                .tasks
                .iter()
                .find(|t| t.column == Column::NeedsYou && t.action.as_ref() == Some(&action))
            {
                selected = Some(task.id);
                s.activation_aliases.insert(request, task.id);
                return Ok(vec![]);
            }
            let mut changes =
                s.state
                    .add_task(request, action.label.clone(), Actor::Agent, None, now)?;
            changes.extend(s.state.start(request, "Reviewing workflow request", now)?);
            s.proposals.insert(request, proposer.clone());
            let action_label = action.label.clone();
            changes.extend(commands::submission(
                s,
                request,
                action,
                format!("Requested {}.", action_label),
                None,
                now,
            )?);
            Ok(changes)
        })
        .await?;
        self.flush_effects(topic).await?;
        self.read_topic(topic, |s| {
            s.tasks.iter().find(|t| Some(t.id) == selected).cloned()
        })?
        .context("missing activation task")
        .map_err(Into::into)
    }

    // Synchronous host APIs need a provider receipt. Let the managed worker finish
    // the committed delivery even if the caller disconnects while awaiting it.
    pub(super) async fn flush_effects(&self, topic: TopicId) -> Result<()> {
        let engine = Engine(self.0.clone(), None);
        self.0
            .tasks
            .spawn(async move { engine.deliver_effects(topic).await })
            .await
            .context("delivery worker interrupted")?
    }
    pub(super) async fn deliver_effects(&self, topic: TopicId) -> Result<()> {
        let slot = self.slot(topic)?;
        let _delivery = slot.effect_worker.lock().await;
        let count = slot.saved.read().effects.len();
        for _ in 0..count {
            let effect = slot.saved.read().next_effect(self.0.clock.now()).cloned();
            let Some(effect) = effect else { return Ok(()) };
            // Mark uncertain deliveries before sending, so a crash cannot repeat
            // an agent resume or a manual workflow dispatch.
            let manual_run = matches!(
                effect.target,
                Target::Run { .. } | Target::Proposal(Proposer::Run { .. })
            );
            let unsafe_retry =
                manual_run || matches!(effect.target, Target::Proposal(Proposer::Agent(_)));
            let result = if unsafe_retry && effect.claimed {
                if manual_run {
                    Err(anyhow::Error::new(DispatchUncertain))
                } else {
                    Err(anyhow::anyhow!(
                        "Delivery outcome unknown after interruption. Check the provider before retrying."
                    ))
                }
            } else {
                if unsafe_retry {
                    self.update(topic, &Default::default(), |s, _| {
                        s.effects
                            .iter_mut()
                            .find(|item| item.key == effect.key)
                            .context("missing queued action")?
                            .claimed = true;
                        Ok(vec![])
                    })
                    .await?;
                }
                self.execute_effect(topic, &effect).await
            };
            // A conflict can open between queue selection and the final dispatch check.
            if let Err(error) = &result {
                if let Target::Run {
                    binding,
                    generation,
                    ..
                } = &effect.target
                    && !dispatch_uncertain(error)
                    && self
                        .binding_is_current(topic, binding, *generation)
                        .unwrap_or(false)
                {
                    self.update(topic, &Default::default(), |s, now| {
                        if let Some(job) = s.effects.iter_mut().find(|e| e.key == effect.key) {
                            job.retry_at = Some(now + chrono::TimeDelta::seconds(30));
                            job.claimed = false;
                            job.safe_retry = true;
                        }
                        Ok(vec![])
                    })
                    .await?;
                    continue;
                }
                if error.downcast_ref::<TopicError>() == Some(&TopicError::DisputedEvidence)
                    && !effect.claimed
                {
                    self.update(topic, &Default::default(), |s, _| {
                        if let Some(item) = s.effects.iter_mut().find(|item| item.key == effect.key)
                        {
                            item.claimed = false;
                        }
                        Ok(vec![])
                    })
                    .await?;
                    continue;
                }
                if error.is::<ApprovalRequired>() {
                    self.update(topic, &Default::default(), |s, now| {
                        let original = effect
                            .task
                            .as_ref()
                            .context("Missing activation proposal")?;
                        let Target::Proposal(owner) = &effect.target else {
                            unreachable!()
                        };
                        s.effects.retain(|item| item.key != effect.key);
                        let task = original.id;
                        let changes = if s.state.tasks.iter().any(|t| t == original) {
                            s.state.review_before_delivery(task, now)?
                        } else {
                            return Ok(s.state.delivery_receipt(effect.key, Ref::Task(task),
                                "The earlier action expired when its task changed. Propose the action again to review it.".into(),
                                false, now)?);
                        };
                        s.proposals.insert(task, owner.clone());
                        Ok(changes)
                    })
                    .await?;
                    continue;
                }
            }
            self.update(topic, &Default::default(), |s, now| {
                s.effects.retain(|item| item.key != effect.key);
                // The board can change while a provider is executing the approval.
                // Keep its receipt in activity, but attach it only to the reviewed task version.
                let failed = result.is_err();
                if result.as_ref().err().is_some_and(dispatch_uncertain) {
                    let manual = match &effect.target {
                        Target::Run {
                            binding,
                            generation,
                            ..
                        }
                        | Target::Proposal(Proposer::Run {
                            binding,
                            generation,
                            ..
                        }) => Some((binding, generation)),
                        _ => None,
                    };
                    if let Some((binding, _generation)) = manual
                        && let Some(info) = s
                            .state
                            .topic
                            .routines
                            .iter_mut()
                            .find(|r| r.binding.id == binding.id)
                    {
                        info.uncertain_manual_run = Some(CommandId(effect.key));
                    }
                }
                let (detail, tracking) = match result {
                    Ok(Delivered::Invocation(binding, generation, run)) => {
                        if s.routines.get(&binding.id).and_then(|r| r.bound_by) == generation
                            && let Some(info) = s
                                .state
                                .topic
                                .routines
                                .iter_mut()
                                .find(|r| r.binding.same_workflow(&binding))
                        {
                            info.last_run = Some(now);
                            info.health = RoutineHealth::Ok;
                            if binding.backend != "local" {
                                s.record_invocation(&binding.id, &run, now);
                            }
                        }
                        let detail = format!("Started {} ({}).", binding.name, run.invocation_id);
                        s.dispatches.insert(CommandId(effect.key), run);
                        (detail, None)
                    }
                    Ok(Delivered::Tracking(work)) => {
                        ("Approved action dispatched.".to_owned(), Some(work))
                    }
                    Ok(Delivered::Receipt(detail)) => (detail, None),
                    Err(error) => (format!("Delivery failed: {error}"), None),
                };
                let detail = match (failed, effect.task.as_ref().and_then(|t| t.action.as_ref())) {
                    (true, Some(action)) => format!("{detail} (action: {})", action.label),
                    _ => detail,
                };
                let mut task = effect.task.as_ref().and_then(|original| {
                    s.state
                        .tasks
                        .iter_mut()
                        .find(|current| *current == original)
                });
                let needs_review = failed && task.is_some();
                if needs_review && let Some(task) = task.as_deref_mut() {
                    if s.task_handles.contains_key(&task.id) {
                        task.action = None;
                    } else if let Target::Proposal(owner) = &effect.target {
                        s.proposals.insert(task.id, owner.clone());
                    }
                }
                let task_log_len = task.filter(|_| !needs_review).map(|task| {
                    task.log.push(LogEntry {
                        origin: None,
                        at: now,
                        text: detail.clone(),
                    });
                    task.updated_at = now;
                    task.result = Some(detail.clone());
                    task.log.len()
                });
                if let Some(work) = tracking {
                    let original = effect.task.as_ref().context("missing approved task")?;
                    s.deliveries.insert(
                        effect.key,
                        Delivery {
                            task: original.id,
                            action_label: original.action.as_ref().map(|a| a.label.clone()),
                            work,
                            task_log_len,
                        },
                    );
                }
                let mut changes = s.state.delivery_receipt(
                    effect.key,
                    effect.subject.clone(),
                    detail,
                    needs_review,
                    now,
                )?;
                if !failed
                    && task_log_len.is_some()
                    && matches!(
                        effect.target,
                        Target::Proposal(
                            Proposer::Activation { .. }
                                | Proposer::Run { .. }
                                | Proposer::BindActive(_)
                        )
                    )
                    && let Ref::Task(task) = effect.subject
                    && session::session_task(s) == Some(task)
                {
                    let done = s
                        .state
                        .tasks
                        .iter()
                        .find(|t| t.id == task)
                        .and_then(|t| t.action.as_ref())
                        .map(|a| a.done_label.clone())
                        .unwrap_or_default();
                    if matches!(s.runs.get(&task), Some(Work::Poll(_))) {
                        // Still in its turn: the turn goes on and its reply lands.
                        changes.extend(s.state.resume_after_workflow(task, now)?);
                    } else if let Some(t) = s.state.tasks.iter_mut().find(|t| t.id == task) {
                        t.action = None;
                    }
                    // A person's answer to its prompt reaches it in its next turn.
                    if !effect.automatic {
                        s.inbox.note("Approved by the person and done:", &done);
                    }
                } else if !failed
                    && task_log_len.is_some()
                    && matches!(
                        effect.target,
                        Target::Proposal(
                            Proposer::Activation { .. }
                                | Proposer::Run { .. }
                                | Proposer::BindActive(_)
                        )
                    )
                    && let Ref::Task(task) = effect.subject
                    && let Some(handle) = s.task_handles.get(&task).cloned()
                {
                    changes.extend(s.state.resume_after_workflow(task, now)?);
                    s.runs.insert(task, Work::Poll(handle));
                    s.last_progress.insert(task, now);
                }
                Ok(changes)
            })
            .await?;
        }
        Ok(())
    }

    async fn execute_effect(&self, topic: TopicId, effect: &Effect) -> anyhow::Result<Delivered> {
        if let Some(action) = effect.task.as_ref().and_then(|t| t.action.as_ref()) {
            let slot = self.slot(topic)?;
            let saved = slot.saved.read();
            match decide(&saved.state.topic.rules, action) {
                Verdict::Refuse(rule) => return Err(TopicError::ActionDenied(rule).into()),
                Verdict::Ask(rule)
                    if (rule.is_some()
                        || !effect
                            .task
                            .as_ref()
                            .is_some_and(|t| saved.default_activation(t.id, action)))
                        && effect.automatic
                        && matches!(
                            effect.target,
                            Target::Proposal(
                                Proposer::Activation { .. }
                                    | Proposer::Run { .. }
                                    | Proposer::BindActive(_)
                            )
                        ) =>
                {
                    return Err(ApprovalRequired.into());
                }
                _ => {}
            }
            saved.state.check_action_evidence(action)?;
        }
        match &effect.target {
            Target::Cancel(handle) => {
                self.0.agent.cancel(handle).await?;
                Ok(Delivered::Receipt("Agent run cancelled.".into()))
            }
            Target::Reconnect(connection) => {
                self.replay(connection).await?;
                Ok(Delivered::Receipt(format!("Reconnected {connection}.")))
            }
            Target::Run {
                binding,
                generation,
                variables,
            }
            | Target::Proposal(Proposer::Run {
                binding,
                generation,
                variables,
            }) => {
                self.ensure_manual_routine(topic, &binding.id)?;
                anyhow::ensure!(
                    self.binding_is_current(topic, binding, *generation)?,
                    "Routine binding changed"
                );
                let run = self
                    .dispatch_bound(topic, binding, *generation, variables.clone(), effect.key)
                    .await?;
                Ok(Delivered::Invocation(binding.clone(), *generation, run))
            }
            Target::UnknownProposer => anyhow::bail!(
                "The saved task has no proposing provider. Inspect the original work before retrying."
            ),
            Target::Reply { message, text } => match &message
                .reply_target()
                .context("Missing reply destination")?
            {
                Source::Topic(to) => {
                    self.send_identified(
                        topic,
                        *to,
                        text.clone(),
                        Producer::User,
                        Causality {
                            hops: 1,
                            stack: vec![],
                        },
                        format!("reply/{}", effect.key),
                    )
                    .await?;
                    Ok(Delivered::Receipt(format!(
                        "Delivered reply to topic {to}."
                    )))
                }
                Source::Connection { .. } => Ok(Delivered::Receipt(
                    self.0.agent.reply(topic, message, text, effect.key).await?,
                )),
                Source::User => Ok(Delivered::Receipt("Reply recorded.".into())),
            },
            Target::Proposal(owner) => {
                let task = effect.task.as_ref().context("missing approved task")?;
                match owner {
                    Proposer::Activation {
                        binding,
                        generation,
                    } => {
                        anyhow::ensure!(
                            self.binding_is_current(topic, binding, *generation)?,
                            "The routine binding changed before activation"
                        );
                        self.backend(&binding.backend)?
                            .activate(RoutineContext { topic, binding })
                            .await?;
                        self.set_event_delivery(topic, binding, true).await?;
                        Ok(Delivered::Receipt(format!("Activated {}.", binding.name)))
                    }
                    Proposer::Run { .. } => unreachable!(),
                    Proposer::BindActive(binding) => {
                        self.update(topic, &Default::default(), |s, now| {
                            let key = CommandId(effect.key);
                            if s.routines
                                .get(&binding.id)
                                .is_some_and(|r| r.bound_by == Some(key))
                            {
                                return Ok(vec![]);
                            }
                            if s.state.topic.routines.iter().any(|r| {
                                r.binding.id == binding.id
                                    || (r.binding.backend == binding.backend
                                        && r.binding.external_id == binding.external_id)
                            }) {
                                return Err(Error::InvalidBinding(
                                    "Workflow is already bound".into(),
                                ));
                            }
                            let command = Command::SetRoutine {
                                routine: binding.clone(),
                            };
                            let mut changes = s.state.apply(&Envelope {
                                id: key,
                                topic,
                                issued_at: now,
                                command,
                            })?;
                            changes.extend(self.configure_routine(s, binding, key, now)?);
                            Ok(changes)
                        })
                        .await?;
                        Ok(Delivered::Receipt(format!("Bound {}.", binding.name)))
                    }
                    Proposer::Agent(handle) => Ok(Delivered::Tracking(Work::Approved(
                        self.0.agent.execute(handle, task, effect.key).await?,
                    ))),
                    Proposer::Routine {
                        binding,
                        generation,
                    } => {
                        anyhow::ensure!(
                            self.binding_is_current(topic, binding, *generation)?,
                            "Proposing routine was rebound"
                        );
                        let vars = serde_json::from_value(
                            json!({"approved_task":task.id,"action":task.action,"draft":task.draft}),
                        )?;
                        let run = self
                            .dispatch_bound(topic, binding, *generation, vars, effect.key)
                            .await?;
                        Ok(Delivered::Tracking(Work::Routine {
                            binding: binding.clone(),
                            generation: *generation,
                            invocation: run.invocation_id,
                        }))
                    }
                }
            }
        }
    }
}
