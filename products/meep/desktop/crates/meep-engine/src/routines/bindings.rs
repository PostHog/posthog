use super::*;

impl StoredTopic {
    /// Publish a terminal provider failure once across dispatch and polling workers.
    pub(crate) fn record_invocation(
        &mut self,
        routine: &str,
        run: &RoutineRun,
        now: DateTime<Utc>,
    ) {
        let failed =
            |status: &str| InvocationStatus::from_provider(status) == InvocationStatus::Failed;
        let Some(binding) = self.routines.get_mut(routine) else {
            return;
        };
        let previous = binding
            .invocations
            .insert(run.invocation_id, run.status.clone());
        if failed(&run.status)
            && !previous.as_deref().is_some_and(failed)
            && !self
                .observations
                .iter()
                .any(|o| o.report.invocation == Some(run.invocation_id))
        {
            self.routine_failed(routine, &run.status, now, &Default::default());
        }
    }
}

impl Engine {
    /// Bind a remote flow and return its new callback credential to the host.
    pub async fn bind_routine(&self, topic: TopicId, binding: RoutineBinding) -> Result<String> {
        let key = binding.id.clone();
        let id = id();
        self.apply(Envelope {
            id,
            topic,
            issued_at: self.0.clock.now(),
            command: Command::SetRoutine { routine: binding },
        })
        .await?;
        let slot = self.slot(topic)?;
        let saved = slot.saved.read();
        let binding = saved
            .routines
            .get(&key)
            .filter(|r| r.bound_by == Some(id))
            .context("routine was rebound during provisioning")?;
        Ok(binding.secret.to_string())
    }

    pub(crate) fn configure_routine(
        &self,
        s: &mut StoredTopic,
        b: &RoutineBinding,
        command: CommandId,
        now: DateTime<Utc>,
    ) -> Result<Changes> {
        let backend = self.backend(&b.backend)?;
        backend.bind(b)?;
        let changes =
            Self::withdraw_workflow(s, b, now, "The automation was rebound during this task.")?;
        s.routines.insert(
            b.id.clone(),
            Routine {
                defer_sort: false,
                observation_only: false,
                secret: Uuid::new_v4(),
                bound_by: Some(command),
                invocations: BTreeMap::new(),
                receipts: BTreeMap::new(),
                pending_sends: BTreeMap::new(),
            },
        );
        Ok(changes)
    }

    /// Revoke a deleted workflow's callbacks, subscriptions and outstanding work.
    pub async fn remove_workflow(&self, topic: TopicId, binding: &RoutineBinding) -> Result<()> {
        self.update(topic, &Default::default(), |s, now| {
            let mut changes = s.state.remove_workflow(binding, now)?;
            changes.extend(Self::withdraw_workflow(
                s,
                binding,
                now,
                "The assigned routine was deleted.",
            )?);
            s.routines.remove(&binding.id);
            s.observations.retain(|o| o.binding.id != binding.id);
            if binding.id == "default:sort-inbox" {
                if s.default_sort_request.take().is_some() {
                    let waiting: Vec<_> = s
                        .observations
                        .iter_mut()
                        .filter(|o| o.awaiting_default)
                        .map(|o| {
                            o.awaiting_default = false;
                            o.report.key
                        })
                        .collect();
                    for key in waiting {
                        s.transition(
                            key,
                            ObservationOutcome::Finished {
                                reason: "Sort inbox was deleted before activation".into(),
                            },
                            now,
                        )?;
                    }
                }
                s.default_sort_removed = true;
                s.default_flow = None;
            }
            Ok(changes)
        })
        .await?;
        Ok(())
    }

    fn withdraw_workflow(
        s: &mut StoredTopic,
        b: &RoutineBinding,
        now: DateTime<Utc>,
        interrupted_reason: &str,
    ) -> Result<Changes> {
        let mut changes = Vec::new();
        let withdrawn: Vec<_> = s
            .proposals
            .iter()
            .filter_map(|(task, owner)| {
                matches!(owner, effects::Proposer::Routine { binding, .. } | effects::Proposer::Run { binding, .. } | effects::Proposer::Activation { binding, .. } if binding.id == b.id)
                    .then_some(*task)
            })
            .collect();
        for task in withdrawn {
            s.proposals.remove(&task);
            if s.state
                .tasks
                .iter()
                .any(|t| t.id == task && t.column == Column::NeedsYou)
            {
                changes.extend(s.state.routine_review_changed(task, now)?);
            }
        }
        let interrupted: Vec<_> = s
            .runs
            .iter()
            .filter_map(|(task, work)| match work {
                Work::AssignedFlow { binding, .. } if binding.id == b.id => Some(*task),
                _ => None,
            })
            .collect();
        for task in interrupted {
            s.runs.remove(&task);
            if s.state
                .tasks
                .iter()
                .any(|t| t.id == task && t.column == Column::InProgress)
            {
                changes.extend(s.state.work_needs_attention(
                    task,
                    interrupted_reason.into(),
                    now,
                )?);
            }
        }
        Ok(changes)
    }

    /// Defer sorting until the source workflow runs, preserving the full dispatch payload.
    pub async fn defer_source_sort(&self, topic: TopicId, binding: &RoutineBinding) -> Result<()> {
        self.configure_source_sort(topic, binding, false).await
    }

    /// Let the workflow classify its own sources. A standalone sorter fetches input by observation ID.
    pub async fn configure_source_sort(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        observation_only: bool,
    ) -> Result<()> {
        self.update(topic, &Default::default(), |s, _| {
            s.state
                .topic
                .routines
                .iter()
                .find(|r| {
                    r.binding.id == binding.id && r.binding.external_id == binding.external_id
                })
                .context("Workflow binding changed")?;
            let routine = s.routines.get_mut(&binding.id).context("Missing routine")?;
            routine.defer_sort = true;
            routine.observation_only = observation_only;
            Ok(vec![])
        })
        .await?;
        Ok(())
    }

    /// Read a callback credential for server-side provisioning.
    pub fn routine_secret(&self, topic: TopicId, routine: &str) -> Result<String> {
        Ok(self
            .slot(topic)?
            .saved
            .read()
            .routines
            .get(routine)
            .ok_or_else(|| Error::UnknownRoutine(routine.into()))?
            .secret
            .to_string())
    }

    pub(crate) fn backend(&self, name: &str) -> Result<&dyn RoutineBackend> {
        Ok(self
            .0
            .backends
            .get(name)
            .with_context(|| format!("unknown routine backend {name}"))?
            .as_ref())
    }

    pub(crate) fn ensure_manual_routine(&self, topic: TopicId, routine: &str) -> Result<()> {
        let slot = self.slot(topic)?;
        if slot
            .saved
            .read()
            .state
            .topic
            .routines
            .iter()
            .any(|r| r.binding.id == routine && r.uncertain_manual_run.is_some())
        {
            return Err(Error::InvalidBinding(
                "Check PostHog and acknowledge the earlier uncertain run before starting another"
                    .into(),
            ));
        }
        if slot
            .saved
            .read()
            .routines
            .get(routine)
            .is_some_and(|r| r.observation_only)
        {
            return Err(Error::InvalidBinding(
                "This routine requires a source observation and cannot be run manually".into(),
            ));
        }
        Ok(())
    }

    /// Whether the current binding can run without an observed source event.
    pub fn manual_run_allowed(&self, topic: TopicId, binding: &RoutineBinding) -> Result<bool> {
        let slot = self.slot(topic)?;
        let saved = slot.saved.read();
        if !saved
            .state
            .topic
            .routines
            .iter()
            .any(|r| r.binding == *binding)
        {
            return Err(Error::InvalidBinding(
                "The routine binding changed. Refresh its details.".into(),
            ));
        }
        let routine = saved
            .routines
            .get(&binding.id)
            .ok_or_else(|| Error::UnknownRoutine(binding.id.clone()))?;
        Ok(!routine.observation_only)
    }

    pub(crate) fn binding(
        &self,
        topic: TopicId,
        routine: &str,
    ) -> Result<(RoutineBinding, Option<CommandId>)> {
        let slot = self.slot(topic)?;
        let saved = slot.saved.read();
        let generation = saved
            .routines
            .get(routine)
            .ok_or_else(|| Error::UnknownRoutine(routine.into()))?
            .bound_by;
        saved
            .state
            .topic
            .routines
            .iter()
            .find(|r| r.binding.id == routine)
            .map(|r| (r.binding.clone(), generation))
            .ok_or_else(|| Error::UnknownRoutine(routine.into()))
    }

    pub(crate) fn binding_is_current(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        generation: Option<CommandId>,
    ) -> Result<bool> {
        match self.binding(topic, &binding.id) {
            Ok((current, bound_by)) => Ok(bound_by == generation && current.same_workflow(binding)),
            Err(Error::UnknownRoutine(_)) => Ok(false),
            Err(error) => Err(error),
        }
    }

    /// Dispatch an invocation with a stable idempotency key and host-supplied variables.
    pub async fn start_routine(
        &self,
        topic: TopicId,
        routine: &str,
        variables: serde_json::Map<String, Value>,
        key: Uuid,
    ) -> Result<RoutineRun> {
        let id = CommandId(key);
        self.apply(Envelope {
            id,
            topic,
            issued_at: self.0.clock.now(),
            command: Command::StartRoutine {
                routine: routine.into(),
                variables,
            },
        })
        .await?;
        if let Some(run) = self.slot(topic)?.saved.read().dispatches.get(&id).cloned() {
            return Ok(run);
        }
        self.update(topic, &Default::default(), |s, _| {
            s.retry_dispatch(key);
            Ok(vec![])
        })
        .await?;
        self.flush_effects(topic).await?;
        Ok(self
            .slot(topic)?
            .saved
            .read()
            .dispatches
            .get(&id)
            .cloned()
            .context("command was not a routine dispatch")?)
    }

    pub(crate) async fn dispatch_bound(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        generation: Option<CommandId>,
        variables: serde_json::Map<String, Value>,
        key: Uuid,
    ) -> Result<RoutineRun> {
        if self.slot(topic)?.saved.read().state.archived {
            return Err(TopicError::InactiveTopic.into());
        }
        let result = self
            .backend(&binding.backend)?
            .start(RoutineContext { topic, binding }, variables, key)
            .await;
        if let Err(error) = &result {
            self.observe(
                topic,
                binding,
                generation,
                RoutineHealth::Failing(error.to_string()),
            )
            .await?;
        }
        let run = result?;
        self.update(topic, &Default::default(), |s, now| {
            if s.dispatch_keys.insert(key, now.date_naive()).is_none() {
                s.state
                    .usage
                    .days
                    .entry(now.date_naive())
                    .or_default()
                    .routine_dispatches += 1;
            }
            Ok(vec![])
        })
        .await?;
        Ok(run)
    }

    /// Resume an inbox-assigned remote flow using the original binding and dispatch key.
    pub(crate) async fn advance_assigned_flow(
        &self,
        topic: TopicId,
        task: &Task,
        work: Work,
    ) -> Result<()> {
        let Work::AssignedFlow {
            ref binding,
            generation,
            key,
            invocation,
        } = work
        else {
            return Ok(());
        };
        let current = self
            .slot(topic)?
            .saved
            .read()
            .routines
            .get(&binding.id)
            .is_some_and(|r| r.bound_by == generation);
        let context = RoutineContext { topic, binding };
        let observed = if !current {
            Err(anyhow::anyhow!("The assigned routine was rebound."))
        } else if let Some(id) = invocation {
            self.backend(&binding.backend)?.status(context, id).await
        } else {
            let variables = serde_json::from_value(
                json!({"task":task.id,"title":task.title,"thread":task.from_thread}),
            )?;
            self.dispatch_bound(topic, binding, generation, variables, key)
                .await
                .map_err(Into::into)
        };
        self.update(topic, &Default::default(), |s, now| {
            if s.runs.get(&task.id) != Some(&work) {
                return Ok(vec![]);
            }
            let detail = match observed {
                Ok(run) => {
                    let status = InvocationStatus::from_provider(&run.status);
                    if s.routines
                        .get(&binding.id)
                        .is_some_and(|r| r.bound_by == generation)
                    {
                        s.record_invocation(&binding.id, &run, now);
                    }
                    if let Some(info) = s
                        .state
                        .topic
                        .routines
                        .iter_mut()
                        .find(|r| r.binding.same_workflow(binding))
                    {
                        if invocation.is_none() {
                            info.last_run = Some(now);
                        }
                        info.health = RoutineHealth::Ok;
                    }
                    if status == InvocationStatus::Succeeded {
                        s.runs.remove(&task.id);
                        return Ok(s.state.complete(
                            task.id,
                            format!("{} completed.", binding.name),
                            now,
                        )?);
                    }
                    if status == InvocationStatus::Pending {
                        s.runs.insert(
                            task.id,
                            Work::AssignedFlow {
                                binding: binding.clone(),
                                generation,
                                key,
                                invocation: Some(run.invocation_id),
                            },
                        );
                        return Ok(vec![]);
                    }
                    format!("{}: {}", binding.name, run.status)
                }
                Err(e) if current => {
                    // A lost start response can follow a successful dispatch. Keep the key for retry.
                    return Err(e.into());
                }
                Err(e) => e.to_string(),
            };
            s.runs.remove(&task.id);
            Ok(s.state.work_needs_attention(task.id, detail, now)?)
        })
        .await?;
        Ok(())
    }

    /// Read an invocation from its configured backend.
    pub async fn routine_status(
        &self,
        topic: TopicId,
        routine: &str,
        invocation: Uuid,
    ) -> Result<RoutineRun> {
        let (binding, generation) = self.binding(topic, routine)?;
        self.status_bound(topic, &binding, generation, invocation)
            .await
    }

    pub(crate) async fn status_bound(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        generation: Option<CommandId>,
        invocation: Uuid,
    ) -> Result<RoutineRun> {
        if !self.binding_is_current(topic, binding, generation)? {
            return Err(Error::UnknownRoutine(binding.id.clone()));
        }
        Ok(self
            .backend(&binding.backend)?
            .status(RoutineContext { topic, binding }, invocation)
            .await?)
    }

    /// Poll unfinished remote runs and save their observed status across restarts.
    pub async fn poll_routine_runs(&self, topic: TopicId, routine: &str) -> Result<()> {
        let slot = self.slot(topic)?;
        let (secret, pending) = {
            let saved = slot.saved.read();
            let binding = saved
                .routines
                .get(routine)
                .ok_or_else(|| Error::UnknownRoutine(routine.into()))?;
            let pending = binding
                .invocations
                .iter()
                .filter(|(_, status)| {
                    InvocationStatus::from_provider(status) == InvocationStatus::Pending
                })
                .map(|(id, status)| (*id, status.clone()))
                .collect::<Vec<_>>();
            (binding.secret, pending)
        };
        for (id, previous) in pending {
            let latest = self.routine_status(topic, routine, id).await?;
            if latest.status != previous {
                self.update(topic, &Default::default(), |s, now| {
                    if s.routines.get(routine).is_some_and(|r| {
                        r.secret == secret && r.invocations.get(&id) == Some(&previous)
                    }) {
                        s.record_invocation(routine, &latest, now);
                        for receipt in s
                            .dispatches
                            .values_mut()
                            .filter(|receipt| receipt.invocation_id == id)
                        {
                            receipt.status.clone_from(&latest.status);
                        }
                    }
                    Ok(vec![])
                })
                .await?;
            }
        }
        Ok(())
    }

    /// Refresh the health displayed in the replicated routine list.
    pub async fn routine_health(&self, topic: TopicId, routine: &str) -> Result<RoutineHealth> {
        let (binding, generation) = self.binding(topic, routine)?;
        let health = self
            .backend(&binding.backend)?
            .health(RoutineContext {
                topic,
                binding: &binding,
            })
            .await
            .unwrap_or_else(|e| RoutineHealth::Failing(e.to_string()));
        self.observe(topic, &binding, generation, health.clone())
            .await?;
        Ok(health)
    }

    async fn observe(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        generation: Option<CommandId>,
        health: RoutineHealth,
    ) -> Result<()> {
        let slot = self.slot(topic)?;
        let guard = slot.edit.clone().lock_owned().await;
        let next = {
            let saved = slot.saved.read();
            let Some(index) = saved
                .state
                .topic
                .routines
                .iter()
                .position(|r| r.binding.same_workflow(binding))
            else {
                return Ok(());
            };
            if saved.state.topic.routines[index].health == health
                || saved
                    .routines
                    .get(&binding.id)
                    .is_none_or(|r| r.bound_by != generation)
            {
                return Ok(());
            }
            let mut next = saved.as_ref().clone();
            next.state.topic.routines[index].health = health;
            next
        };
        self.commit(slot, guard, next, vec![], &Default::default())
            .await?;
        Ok(())
    }
}
