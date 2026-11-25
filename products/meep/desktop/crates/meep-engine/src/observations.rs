use super::{routines::InvocationStatus, *};
use meep_ingest::Event;
use serde_json::{Value, json};

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Observation {
    pub event: Event,
    #[serde(default)]
    pub event_cause: Option<Causality>,
    pub binding: RoutineBinding,
    pub(super) generation: Option<CommandId>,
    pub report: ObservationReport,
    pub suggestion: Option<Sorted>,
    #[serde(default)]
    pub sort_failed: bool,
    #[serde(default)]
    pub sort_error: Option<String>,
    #[serde(default)]
    pub instructions: Option<String>,
    #[serde(default)]
    pub defer_sort: bool,
    #[serde(default)]
    pub(super) awaiting_default: bool,
    #[serde(default)]
    pub(super) reserved: bool,
    #[serde(default)]
    dispatch_uncertain: bool,
    due: DateTime<Utc>,
}

impl Observation {
    fn pending(&self, key: Uuid) -> bool {
        self.report.key == key && self.report.outcome.pending()
    }

    pub(super) fn save_sort_result(&mut self, result: std::result::Result<Sorted, String>) {
        self.sort_failed = result.is_err();
        match result {
            Ok(sorted) => {
                self.suggestion = Some(sorted);
                self.sort_error = None;
            }
            Err(reason) => {
                self.suggestion = None;
                self.sort_error = Some(reason);
            }
        }
    }
}

fn recovery_eligible(state: &StoredTopic, observation: &Observation) -> bool {
    !state.state.archived
        && !state.state.deleted
        && state
            .routines
            .get(&observation.binding.id)
            .is_some_and(|r| r.bound_by == observation.generation)
        && state.state.topic.routines.iter().any(|r| {
            r.binding.same_workflow(&observation.binding) && (r.event.is_none() || r.enabled)
        })
}

impl StoredTopic {
    pub(super) fn resolve_dispatch_uncertainty(&mut self, key: Uuid) {
        if let Some(observation) = self.observations.iter_mut().find(|o| o.report.key == key) {
            observation
                .report
                .failures
                .retain(|failure| failure != &DispatchUncertain.to_string());
        }
    }
    pub(super) fn record_observation(
        &mut self,
        binding: &RoutineBinding,
        event: &Event,
        event_cause: Option<Causality>,
        now: DateTime<Utc>,
    ) -> Uuid {
        let key = Uuid::new_v4();
        let report = ObservationReport {
            key,
            origin: event.origin(),
            at: now,
            invocation: None,
            outcome: ObservationOutcome::Pending,
            failures: vec![],
        };
        self.observations.push(Observation {
            event: event.clone(),
            event_cause,
            binding: binding.clone(),
            generation: self.routines.get(&binding.id).and_then(|r| r.bound_by),
            report: report.clone(),
            suggestion: None,
            sort_failed: false,
            sort_error: None,
            instructions: None,
            defer_sort: self.routines.get(&binding.id).is_some_and(|r| r.defer_sort),
            awaiting_default: false,
            reserved: false,
            dispatch_uncertain: false,
            due: now,
        });
        self.publish_observation(&binding.id, &report);
        key
    }

    fn publish_observation(&mut self, routine: &str, report: &ObservationReport) {
        if let Some(info) = self
            .state
            .topic
            .destinations_mut()
            .find(|r| r.binding.id == routine)
        {
            info.observations.retain(|r| r.key != report.key);
            info.observations.push(report.clone());
            info.last_run = Some(report.at);
        }
        self.state.activity.push(Activity {
            delivery: None,
            at: report.at,
            actor: Actor::Routine(routine.into()),
            subject: Ref::Routine(routine.into()),
            text: format!(
                "Observation {}: {:?}{}",
                report.key,
                report.outcome,
                report
                    .failures
                    .last()
                    .map(|e| format!(" (dispatch: {e})"))
                    .unwrap_or_default()
            ),
        });
    }

    pub(super) fn transition(
        &mut self,
        key: Uuid,
        outcome: ObservationOutcome,
        now: DateTime<Utc>,
    ) -> Result<()> {
        let index = self
            .observations
            .iter()
            .position(|o| o.report.key == key)
            .context("Unknown observation")?;
        if !self.observations[index].report.outcome.pending() {
            return Err(Error::UnavailableObservation(key));
        }
        let mut obs = self.observations.remove(index);
        obs.report.at = now;
        obs.report.outcome = outcome;
        self.publish_observation(&obs.binding.id, &obs.report);
        if let ObservationOutcome::Failed { reason } | ObservationOutcome::FellBack { reason, .. } =
            &obs.report.outcome
        {
            self.routine_failed(
                &obs.binding.id,
                reason,
                now,
                &obs.event_cause.clone().unwrap_or_default(),
            );
        }
        self.observations.push(obs);
        if self
            .observations
            .iter()
            .filter(|o| !o.report.outcome.pending())
            .count()
            > 500
        {
            let oldest = self
                .observations
                .iter()
                .position(|o| !o.report.outcome.pending())
                .expect("finished observation");
            let old = self.observations.remove(oldest);
            if let Some(r) = self
                .state
                .topic
                .destinations_mut()
                .find(|r| r.binding.id == old.binding.id)
            {
                r.observations.retain(|r| r.key != old.report.key);
            }
        }
        Ok(())
    }

    pub(super) fn callback_observation(
        &self,
        key: Uuid,
        routine: &str,
        generation: Option<CommandId>,
    ) -> Result<Observation> {
        self.observations
            .iter()
            .find(|o| o.pending(key) && o.binding.id == routine && o.generation == generation)
            .cloned()
            .ok_or(Error::UnavailableObservation(key))
    }

    pub(super) fn observation_deadlines(&self) -> impl Iterator<Item = (Uuid, DateTime<Utc>)> + '_ {
        self.observations
            .iter()
            .filter(|o| !o.awaiting_default && o.report.outcome.pending())
            .map(|o| (o.report.key, o.due))
    }
}

impl Engine {
    /// Recent connector evidence for a task preparing a topic digest.
    pub fn source_observations(&self, topic: TopicId, limit: usize) -> Result<Vec<Value>> {
        let slot = self.slot(topic)?;
        let saved = slot.saved.read();
        let mut records: Vec<_> = saved
            .observations
            .iter()
            .filter(|o| o.event_cause.is_none())
            .collect();
        records.sort_by_key(|o| std::cmp::Reverse(o.event.at));
        Ok(records
            .into_iter()
            .take(limit.min(100))
            .map(|o| {
                json!({
                    "observation":o.report.key, "source":o.report.origin, "text":o.event.text,
                    "routine":o.binding.id
                })
            })
            .collect())
    }

    pub(super) async fn advance_observation(&self, topic: TopicId, key: Uuid) -> Result<Changes> {
        let slot = self.slot(topic)?;
        let _worker = slot.observation_worker.lock().await;
        let Some(mut obs) = slot
            .saved
            .read()
            .observations
            .iter()
            .find(|o| !o.awaiting_default && o.pending(key) && o.due <= self.0.clock.now())
            .cloned()
        else {
            return Ok(vec![]);
        };
        let cause = Causality {
            hops: 0,
            stack: vec![(topic, obs.binding.id.clone())],
        };
        if obs.dispatch_uncertain {
            // Use a deliberately conservative bound: do not infer uniqueness
            // when the earliest possible match may have fallen out of history.
            let recent = self.0.clock.now() - obs.report.at < chrono::TimeDelta::days(6);
            let eligible = recovery_eligible(&slot.saved.read(), &obs);
            let found = if recent && eligible {
                match self.backend(&obs.binding.backend) {
                    Ok(backend) => tokio::time::timeout(
                        std::time::Duration::from_secs(15),
                        backend.find_observation(
                            RoutineContext {
                                topic,
                                binding: &obs.binding,
                            },
                            key,
                        ),
                    )
                    .await
                    .ok()
                    .and_then(|result| result.ok())
                    .flatten(),
                    Err(_) => None,
                }
            } else {
                None
            };
            return self
                .update(topic, &cause, |s, now| {
                    // Network lookup can overlap archive, pause or rebind. Do
                    // not attach a stale result to a changed topic or routine.
                    let blocked = !recovery_eligible(s, &obs);
                    let Some(o) = s
                        .observations
                        .iter_mut()
                        .find(|o| o.pending(key) && o.dispatch_uncertain)
                    else {
                        return Ok(vec![]);
                    };
                    o.due = now
                        + if recent {
                            chrono::TimeDelta::seconds(30)
                        } else {
                            chrono::TimeDelta::days(365)
                        };
                    if blocked {
                        return Ok(vec![]);
                    }
                    let Some(run) = found else {
                        return Ok(vec![]);
                    };
                    o.dispatch_uncertain = false;
                    o.report.invocation = Some(run.invocation_id);
                    o.due = now + chrono::TimeDelta::seconds(5);
                    if let Some(routine) = s
                        .routines
                        .get_mut(&obs.binding.id)
                        .filter(|r| r.bound_by == obs.generation)
                    {
                        routine
                            .invocations
                            .insert(run.invocation_id, run.status.clone());
                    }
                    s.resolve_dispatch_uncertainty(key);
                    let outcome = match InvocationStatus::from_provider(&run.status) {
                        InvocationStatus::Failed => {
                            ObservationOutcome::Failed { reason: run.status }
                        }
                        InvocationStatus::Pending
                            if !run.status.eq_ignore_ascii_case("finished") =>
                        {
                            ObservationOutcome::Dispatched
                        }
                        _ => ObservationOutcome::Finished {
                            reason: "no result".into(),
                        },
                    };
                    s.transition(key, outcome, now)?;
                    Ok(vec![])
                })
                .await;
        }
        let ready = self
            .binding_is_current(topic, &obs.binding, obs.generation)
            .and_then(|current| {
                if !current {
                    return Err(anyhow::anyhow!("Source binding changed").into());
                }
                if obs.report.invocation.is_none() {
                    self.backend(&obs.binding.backend)?.source_ready(topic)?;
                }
                Ok(())
            });
        if let Err(e) = ready {
            if matches!(&e, Error::Integration(cause) if cause.is::<SourceTemporarilyUnavailable>())
            {
                return self
                    .update(topic, &cause, |s, now| {
                        let Some(observation) = s.observations.iter_mut().find(|o| {
                            o.pending(key) && o.report.invocation.is_none() && !o.dispatch_uncertain
                        }) else {
                            return Ok(vec![]);
                        };
                        observation.due = now + chrono::TimeDelta::seconds(30);
                        let reason = SourceTemporarilyUnavailable.to_string();
                        if !observation.report.failures.contains(&reason) {
                            observation.report.failures.push(reason);
                            let report = observation.report.clone();
                            let binding = observation.binding.id.clone();
                            s.publish_observation(&binding, &report);
                        }
                        Ok(vec![])
                    })
                    .await;
            }
            return self
                .update(topic, &cause, |s, now| {
                    if s.observations.iter().any(|o| o.pending(key)) {
                        s.transition(
                            key,
                            ObservationOutcome::Failed {
                                reason: e.to_string(),
                            },
                            now,
                        )?;
                    }
                    Ok(vec![])
                })
                .await;
        }
        if obs
            .report
            .failures
            .iter()
            .any(|reason| reason == &SourceTemporarilyUnavailable.to_string())
        {
            self.update(topic, &cause, |s, _| {
                if let Some(observation) = s.observations.iter_mut().find(|o| o.pending(key)) {
                    observation
                        .report
                        .failures
                        .retain(|reason| reason != &SourceTemporarilyUnavailable.to_string());
                    let report = observation.report.clone();
                    let binding = observation.binding.id.clone();
                    s.publish_observation(&binding, &report);
                }
                Ok(vec![])
            })
            .await?;
        }
        if !obs.reserved {
            let mut admitted = false;
            self.update(topic, &cause, |s, now| {
                let Some(o) = s.observations.iter_mut().find(|o| o.pending(key)) else {
                    return Ok(vec![]);
                };
                admitted = s.starts.try_start(now, self.0.limits);
                o.reserved = admitted;
                if !admitted {
                    o.due = s
                        .starts
                        .next_start(now, self.0.limits)
                        .unwrap_or(now + chrono::TimeDelta::hours(1));
                }
                Ok(vec![])
            })
            .await?;
            if !admitted {
                return Ok(vec![]);
            }
        }
        if obs.event_cause.is_none()
            && obs.suggestion.is_none()
            && !self.0.sorter.hosted_decisions()
            && !obs.defer_sort
            && !obs.sort_failed
        {
            let snapshot = slot.saved.read().clone();
            let sorted = self
                .evaluate_observation(&snapshot, &obs, &cause, None)
                .await?;
            obs.save_sort_result(sorted);
            self.update(topic, &cause, |s, _| {
                let o = s
                    .observations
                    .iter_mut()
                    .find(|o| o.pending(key))
                    .context("Observation already consumed")?;
                o.suggestion.clone_from(&obs.suggestion);
                o.sort_failed = obs.sort_failed;
                o.sort_error.clone_from(&obs.sort_error);
                Ok(vec![])
            })
            .await?;
        }
        if obs.event_cause.is_none()
            && obs.report.invocation.is_none()
            && self
                .connections()?
                .iter()
                .any(|c| c.id == obs.event.connection && !c.grants.contains(&topic))
        {
            return self
                .update(topic, &cause, |s, now| {
                    s.transition(
                        key,
                        ObservationOutcome::Failed {
                            reason: "Source grant revoked".into(),
                        },
                        now,
                    )?;
                    Ok(vec![])
                })
                .await;
        }
        let polling = obs.report.invocation.is_some();
        let run = match obs.report.invocation {
            Some(invocation) => {
                self.status_bound(topic, &obs.binding, obs.generation, invocation)
                    .await
            }
            None => {
                let sorted = obs.suggestion.as_ref();
                let vars = if obs.event_cause.is_some() {
                    let mut vars = obs
                        .event
                        .attributes
                        .as_object()
                        .cloned()
                        .context("Missing event variables")?;
                    vars.insert("observation".into(), json!(key));
                    vars
                } else if slot
                    .saved
                    .read()
                    .routines
                    .get(&obs.binding.id)
                    .is_some_and(|r| r.observation_only)
                {
                    serde_json::Map::from_iter([("observation".into(), json!(key))])
                } else {
                    serde_json::from_value(
                        json!({"text":obs.event.text,"author":obs.event.author,"channel":obs.event.channel,
                    "observation":key,"suggestion":sorted.map(suggestion),"confidence":sorted.and_then(|s|s.confidence)}),
                    )?
                };
                // The marker is durable before provider I/O. A process crash
                // after this point is reconciled, never blindly re-dispatched.
                let mut marked = false;
                self.update(topic, &cause, |s, now| {
                    if !recovery_eligible(s, &obs) {
                        return Ok(vec![]);
                    }
                    let Some(o) = s.observations.iter_mut().find(|o| {
                        o.pending(key) && o.report.invocation.is_none() && !o.dispatch_uncertain
                    }) else {
                        return Ok(vec![]);
                    };
                    o.dispatch_uncertain = true;
                    o.due = now + chrono::TimeDelta::seconds(30);
                    o.report.at = now;
                    let reason = DispatchUncertain.to_string();
                    if !o.report.failures.contains(&reason) {
                        o.report.failures.push(reason);
                    }
                    let report = o.report.clone();
                    let binding = o.binding.id.clone();
                    s.publish_observation(&binding, &report);
                    marked = true;
                    Ok(vec![])
                })
                .await?;
                if !marked {
                    return Ok(vec![]);
                }
                self.dispatch_bound(topic, &obs.binding, obs.generation, vars, key)
                    .await
            }
        };
        self.update(topic, &cause, |s, now| {
            let Some(o) = s.observations.iter_mut().find(|o| o.report.key == key) else {
                return Ok(vec![]);
            };
            // A receipt, a definite rejection, or a completed callback ends
            // the in-flight state. Ambiguous transport/provider errors retain it.
            let ambiguous =
                matches!(&run, Err(Error::Integration(error)) if error.is::<DispatchUncertain>());
            if !polling && (!ambiguous || !o.report.outcome.pending()) {
                o.dispatch_uncertain = false;
                o.report
                    .failures
                    .retain(|reason| reason != &DispatchUncertain.to_string());
            }
            if let Ok(run) = &run {
                if let Some(r) = s
                    .routines
                    .get_mut(&obs.binding.id)
                    .filter(|r| r.bound_by == obs.generation)
                {
                    r.invocations.insert(run.invocation_id, run.status.clone());
                }
                o.report.invocation = Some(run.invocation_id);
            }
            if !o.report.outcome.pending() {
                // A synchronous callback can beat the dispatch receipt.
                if let Some(info) = s
                    .state
                    .topic
                    .destinations_mut()
                    .find(|r| r.binding.id == obs.binding.id)
                    && let Some(report) = info.observations.iter_mut().find(|r| r.key == key)
                {
                    report.invocation = o.report.invocation;
                    report.failures.clone_from(&o.report.failures);
                }
                return Ok(vec![]);
            }
            o.due = now + chrono::TimeDelta::seconds(5);
            let outcome = match run {
                Ok(run) => match InvocationStatus::from_provider(&run.status) {
                    InvocationStatus::Failed => ObservationOutcome::Failed { reason: run.status },
                    InvocationStatus::Pending if !run.status.eq_ignore_ascii_case("finished") => {
                        if polling {
                            return Ok(vec![]);
                        }
                        ObservationOutcome::Dispatched
                    }
                    _ => ObservationOutcome::Finished {
                        reason: "no result".into(),
                    },
                },
                Err(_) if polling => return Ok(vec![]),
                Err(Error::Integration(error)) if error.is::<SourceTemporarilyUnavailable>() => {
                    o.due = now + chrono::TimeDelta::seconds(30);
                    let reason = SourceTemporarilyUnavailable.to_string();
                    if !o.report.failures.contains(&reason) {
                        o.report.failures.push(reason);
                    }
                    ObservationOutcome::Pending
                }
                Err(Error::Integration(error)) if error.is::<DispatchUncertain>() => {
                    o.dispatch_uncertain = true;
                    o.due = now + chrono::TimeDelta::seconds(30);
                    if !o.report.failures.contains(&error.to_string()) {
                        o.report.failures.push(error.to_string());
                    }
                    ObservationOutcome::Pending
                }
                Err(e) => {
                    let reason = e.to_string();
                    o.report.failures.push(reason.clone());
                    if o.report.failures.len() >= 5 {
                        s.transition(key, ObservationOutcome::Failed { reason }, now)?;
                        return Ok(vec![]);
                    }
                    ObservationOutcome::Pending
                }
            };
            s.transition(key, outcome, now)?;
            Ok(vec![])
        })
        .await
    }

    pub(super) async fn evaluate_observation(
        &self,
        snapshot: &StoredTopic,
        obs: &Observation,
        cause: &Causality,
        instructions: Option<&str>,
    ) -> Result<std::result::Result<Sorted, String>> {
        let now = self.0.clock.now();

        let routines = routines::task_routines(snapshot, cause);
        let mut state = snapshot.state.clone();
        let message = obs
            .event
            .message_for(id(), Producer::Routine(obs.binding.id.clone()))?;
        let (_, _, thread, _) =
            delivery::receive_event(&mut state, &obs.event, message.clone(), true, now)?;
        let thread = state
            .threads
            .iter()
            .find(|t| t.id == thread)
            .context("Missing observation context")?;
        Ok(self
            .0
            .sorter
            .sort_step(
                SortInput {
                    topic: &state.topic,
                    disputed_fact_ids: &state.disputed_facts(),
                    thread,
                    tasks: &state.tasks,
                    routines: &routines,
                    message: &message,
                    event: &obs.event,
                },
                instructions,
            )
            .await
            .map_err(|error| sorter::sort_error_reason(&error)))
    }
}

fn suggestion(sorted: &Sorted) -> &str {
    match (&sorted.decision, &sorted.work) {
        (Decision::Skip { .. }, _) => "skip",
        (Decision::Ask { .. }, _) => "ask",
        (_, Some(InboxWork::Update(_))) => "update",
        (
            _,
            Some(InboxWork::Create {
                assignment: InboxAssignment::Investigate,
                ..
            }),
        ) => "investigate",
        (
            _,
            Some(InboxWork::Create {
                assignment: InboxAssignment::Routine(id),
                ..
            }),
        ) => id,
        (_, Some(InboxWork::Create { .. })) => "review",
        _ if sorted.fact.is_some() => "fact",
        _ => "handle",
    }
}
