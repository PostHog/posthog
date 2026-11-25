use super::*;

/// A callback either asks an inbox question or submits an existing task for policy review.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum RoutineAsk {
    /// Request an inbox decision.
    Question {
        /// Observed source event, when the workflow handles one.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        observation: Option<Uuid>,
        /// Question shown to the person.
        text: String,
        /// Choices, defaulting to creating a task or leaving the thread.
        suggestions: Option<Vec<Suggestion>>,
    },
    /// Submit active work to the normal action policy.
    Approval {
        /// Observed source event, when the workflow handles one.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        observation: Option<Uuid>,
        /// Existing task.
        task: TaskId,
        /// Proposed action.
        action: Action,
        /// Work produced.
        result: String,
        /// Optional editable draft.
        draft: Option<String>,
    },
}

/// Report formats accepted by the bound workflow callback.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum RoutineReports {
    /// A completed workflow agent's bounded structured output.
    Batch {
        /// Trigger event shared by this workflow invocation.
        event_id: Uuid,
        /// Provider task run used for attribution.
        run_id: Uuid,
        /// PostHog workflow output variables carry strings.
        reports_json: String,
    },
    /// Original single-report callback format.
    Single {
        /// Report headline.
        title: String,
        /// Report findings.
        body: String,
        /// Source references.
        #[serde(default)]
        sources: Vec<String>,
    },
}

#[derive(Deserialize)]
struct WorkflowFinding {
    title: String,
    body: String,
    priority: ReportPriority,
    impact: String,
    proposal: String,
    evidence: Vec<ReportEvidence>,
}

/// Authenticated operation a workflow may perform on its bound topic.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum RoutineOp {
    /// Confirm that all steps of an event-triggered workflow completed.
    Complete {
        /// The event observation dispatched to this workflow.
        observation: Uuid,
    },
    /// Apply the selected branch of a PostHog classification.
    Classified {
        /// Pending source observation in this routine.
        observation: Uuid,
        /// Category selected by the workflow.
        category: String,
    },
    /// Apply a hosted classification only while its source-specific rules remain current.
    GuardedClassified {
        /// Pending source observation in this routine.
        observation: Uuid,
        /// Category selected by the workflow.
        category: String,
        /// Fingerprint of the eligible rule set supplied to the classifier.
        snapshot: String,
    },
    /// Apply a classified Skip rule only while its evaluated snapshot remains current.
    SkipRule {
        /// Pending source observation in this routine.
        observation: Uuid,
        /// Fingerprint returned with the classification context.
        fingerprint: String,
    },
    /// Apply the topic sorter to this source observation.
    Sort {
        /// Engine observation key.
        observation: Uuid,
        /// Optional workflow-specific disposition instructions.
        instructions: Option<String>,
    },
    /// Publish a sourced report for a schedule, event, or observed source.
    Report {
        /// Source observation when this workflow was dispatched for a connector event.
        observation: Option<Uuid>,
        /// Findings delivered by this step.
        #[serde(flatten)]
        reports: RoutineReports,
    },
    /// Deliver the observed event and mark it handled.
    Inbox {
        /// Engine observation key.
        observation: Uuid,
        /// Optional replacement message body.
        text: Option<String>,
        /// Optional thread summary.
        summary: Option<String>,
    },
    /// Record a decision to discard a source event.
    Drop {
        /// Engine observation key.
        observation: Uuid,
        /// Reason for discarding the event.
        reason: String,
    },
    /// Append observed evidence to an existing task.
    AttachEvidence {
        /// Engine observation key.
        observation: Uuid,
        /// Task receiving the evidence.
        task: TaskId,
    },
    /// Add work to the board.
    AddTask {
        /// Observed source event, when the workflow handles one.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        observation: Option<Uuid>,
        /// Task title.
        title: String,
        /// The agent's brief, when the title alone does not say what to do.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        instructions: Option<String>,
    },
    /// Record a fact with routine provenance.
    AddFact {
        /// Observed source event, when the workflow handles one.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        observation: Option<Uuid>,
        /// Assertion.
        text: String,
    },
    /// Ask for an inbox decision or submit a task for approval.
    Ask(RoutineAsk),
    /// Deliver a message to another topic.
    Send {
        /// Destination topic.
        to: TopicId,
        /// Message body.
        text: String,
    },
    /// Publish a refreshed dataset in this topic for a workspace view.
    RefreshView {
        /// Destination view ID.
        view: Uuid,
        /// Latest rows or structured result.
        data: Value,
    },
    /// Append a note to activity.
    Note {
        /// Text for the activity log.
        text: String,
    },
}

#[derive(Clone)]
pub(super) enum Receipt {
    External(Uuid, Box<RoutineOp>),
}

/// Context and rule guard for a hosted source classification.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RoutineSortContext {
    /// Bounded topic and source text for the classifier.
    pub context: String,
    /// Fingerprint of the one eligible rule, or empty if none can be safely attributed.
    pub skip_fingerprint: String,
    /// Whether the graph must ask for review because rule applicability is ambiguous.
    pub skip_guard: String,
    /// Fingerprint of all eligible rules and this source observation.
    pub skip_snapshot: String,
}

fn skip_candidates(topic: &Topic, event: &meep_ingest::Event) -> Result<Vec<Rule>> {
    let message = event.message_for(id(), Producer::System)?;
    Ok(meep_policy::skip_candidates(&topic.rules, &message)
        .cloned()
        .collect())
}

fn skip_rule_fits(rule: &Rule) -> bool {
    let encoded = rule
        .text
        .chars()
        .chain(std::iter::once('\n'))
        .map(|c| match c {
            '"' | '\\' => 2,
            c if c.is_control() => 6,
            c => c.len_utf8(),
        })
        .sum::<usize>();
    encoded <= 300
}

fn skip_fingerprint(rule: &Rule, event: &meep_ingest::Event, observation: Uuid) -> Result<String> {
    use sha2::{Digest, Sha256};
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&(
            rule,
            &event.connection,
            &event.channel,
            &event.external_id,
            &event.text,
            observation
        ))?)
    ))
}

fn skip_snapshot(rules: &[Rule], event: &meep_ingest::Event, observation: Uuid) -> Result<String> {
    use sha2::{Digest, Sha256};
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&(
            rules,
            &event.connection,
            &event.channel,
            &event.external_id,
            &event.text,
            observation
        ))?)
    ))
}

fn authenticates(expected: Uuid, presented: Option<Uuid>) -> bool {
    use subtle::ConstantTimeEq;
    presented.is_some_and(|key| bool::from(expected.as_bytes().ct_eq(key.as_bytes())))
}

impl Engine {
    /// Read compact classification context for one pending source delivery.
    pub fn routine_sort_context(
        &self,
        topic: TopicId,
        routine: &str,
        secret: &str,
        observation: Uuid,
    ) -> Result<String> {
        Ok(self
            .routine_sort_input(topic, routine, secret, observation)?
            .context)
    }

    /// Read classification context and its source-specific skip guard.
    pub fn routine_sort_input(
        &self,
        topic: TopicId,
        routine: &str,
        secret: &str,
        observation: Uuid,
    ) -> Result<RoutineSortContext> {
        let slot = self.slot(topic)?;
        let saved = slot.saved.read();
        let binding = saved
            .routines
            .get(routine)
            .ok_or_else(|| Error::UnknownRoutine(routine.into()))?;
        if !authenticates(binding.secret, secret.parse().ok()) {
            return Err(Error::InvalidRoutineSecret(routine.into()));
        }
        if saved.state.archived || saved.state.deleted {
            return Err(TopicError::InactiveTopic.into());
        }
        let obs = saved.callback_observation(observation, routine, binding.bound_by)?;
        if self
            .connections()?
            .iter()
            .any(|c| c.id == obs.event.connection && !c.grants.contains(&topic))
        {
            return Err(Error::UnavailableObservation(observation));
        }
        let t = &saved.state.topic;
        // Budget each section in JSON-encoded bytes. Keep room for the other flow variables.
        fn section<'a>(lines: impl Iterator<Item = &'a str>, budget: usize) -> String {
            let mut out = String::new();
            let mut remaining = budget;
            for c in lines.flat_map(|line| line.chars().chain(std::iter::once('\n'))) {
                let cost = match c {
                    '"' | '\u{5c}' => 2,
                    c if c.is_control() => 6,
                    c => c.len_utf8(),
                };
                if cost > remaining {
                    break;
                }
                remaining -= cost;
                out.push(c);
            }
            out
        }
        let candidates = skip_candidates(t, &obs.event)?;
        let single = candidates.first().filter(|_| candidates.len() == 1);
        let fits = single.is_some_and(skip_rule_fits);
        let fingerprint = if fits {
            skip_fingerprint(single.expect("checked"), &obs.event, observation)?
        } else {
            String::new()
        };
        let guard = if candidates.is_empty() {
            "none"
        } else if fits {
            "single"
        } else {
            "review"
        };
        let eligible = if fits {
            format!("Eligible Skip rule: {}\n", single.expect("checked").text)
        } else if candidates.is_empty() {
            "No eligible Skip rule.\n".into()
        } else {
            "Skip rules require human review.\n".into()
        };
        let context = format!(
            "Mission: {}Goals: {}{}Other rules: {}Facts: {}Source: {}Item: {}",
            section(std::iter::once(t.mission.as_str()), 350),
            section(t.goals.iter().map(|g| g.text.as_str()), 300),
            eligible,
            section(
                t.rules
                    .iter()
                    .rev()
                    .filter(|r| !matches!(r.effect, RuleEffect::Skip(_)))
                    .map(|r| r.text.as_str()),
                if fits { 200 } else { 500 }
            ),
            section(
                t.facts
                    .iter()
                    .rev()
                    .filter(|f| f.is_current())
                    .map(|f| f.text.as_str()),
                450
            ),
            section(
                [obs.event.author.as_str(), obs.event.channel.as_str()].into_iter(),
                160
            ),
            section(std::iter::once(obs.event.text.as_str()), 1400)
        );
        Ok(RoutineSortContext {
            context,
            skip_fingerprint: fingerprint,
            skip_guard: guard.into(),
            skip_snapshot: skip_snapshot(&candidates, &obs.event, observation)?,
        })
    }

    /// Apply one authenticated provider operation, deduplicated by its stable per-binding key.
    pub async fn routine_callback_once(
        &self,
        topic: TopicId,
        routine: &str,
        secret: &str,
        key: Uuid,
        op: RoutineOp,
    ) -> Result<Value> {
        self.event_callback_once(topic, routine, secret, key, op, None)
            .await
    }

    /// Apply a workflow step with the causal history of its originating topic event.
    pub async fn event_callback_once(
        &self,
        topic: TopicId,
        routine: &str,
        secret: &str,
        key: Uuid,
        op: RoutineOp,
        observation: Option<Uuid>,
    ) -> Result<Value> {
        let _lane = self
            .0
            .callbacks
            .lane((topic, routine.to_owned(), key))
            .lock_owned()
            .await;
        let slot = self.slot(topic)?;
        let cause = observation
            .and_then(|id| {
                let saved = slot.saved.read();
                let generation = saved.routines.get(routine)?.bound_by;
                saved
                    .observations
                    .iter()
                    .find(|o| {
                        o.report.key == id && o.binding.id == routine && o.generation == generation
                    })
                    .and_then(|o| o.event_cause.clone())
            })
            .unwrap_or_else(|| Causality {
                hops: 0,
                stack: vec![(topic, routine.into())],
            });
        self.callback(
            topic,
            routine,
            secret.parse().ok(),
            op.clone(),
            &cause,
            Some(Receipt::External(key, Box::new(op))),
        )
        .await
    }

    /// Accept one authenticated workflow effect. A rejected credential is audited
    /// without including it in any public record.
    pub async fn routine_callback(
        &self,
        topic: TopicId,
        routine: &str,
        secret: &str,
        op: RoutineOp,
    ) -> Result<Value> {
        let cause = Causality {
            hops: 0,
            stack: vec![(topic, routine.into())],
        };
        self.callback(topic, routine, secret.parse().ok(), op, &cause, None)
            .await
    }

    pub(super) async fn callback(
        &self,
        topic: TopicId,
        routine: &str,
        secret: Option<Uuid>,
        op: RoutineOp,
        cause: &Causality,
        receipt: Option<Receipt>,
    ) -> Result<Value> {
        let slot = self.slot(topic)?;
        // Serialize evaluations of the same event while allowing unrelated topic edits.
        let _sort_lane = if let RoutineOp::Sort {
            observation,
            instructions,
        } = &op
        {
            let lane = self
                .0
                .sort_steps
                .lane((topic, *observation))
                .lock_owned()
                .await;
            let snapshot = slot.saved.read().clone();
            if let Some(binding) = snapshot.routines.get(routine)
                && authenticates(binding.secret, secret)
                && !matches!(&receipt,Some(Receipt::External(key,_)) if binding.receipts.contains_key(key))
            {
                let obs = snapshot.callback_observation(*observation, routine, binding.bound_by)?;
                if obs.suggestion.is_none() && !obs.defer_sort && !obs.sort_failed {
                    return Err(Error::UnavailableObservation(*observation));
                }
                if obs.suggestion.is_none() && !obs.sort_failed {
                    let sorted = self
                        .evaluate_observation(&snapshot, &obs, cause, instructions.as_deref())
                        .await?;
                    self.update(topic, cause, |s, _| {
                        let current = s.routines.get(routine).context("Missing routine")?;
                        if !authenticates(current.secret, secret) {
                            return Err(Error::InvalidRoutineSecret(routine.into()));
                        }
                        s.callback_observation(*observation, routine, current.bound_by)?;
                        let obs = s
                            .observations
                            .iter_mut()
                            .find(|o| o.report.key == *observation)
                            .context("Missing observation")?;
                        obs.save_sort_result(sorted);
                        obs.instructions = instructions.clone();
                        Ok(vec![])
                    })
                    .await?;
                }
            }
            Some(lane)
        } else {
            None
        };
        let guard = slot.edit.clone().lock_owned().await;
        let mut next = slot.draft();
        if next.state.archived {
            return Err(TopicError::InactiveTopic.into());
        }
        let r = next
            .routines
            .get(routine)
            .ok_or_else(|| Error::UnknownRoutine(routine.into()))?;
        let now = self.0.clock.now();
        if !authenticates(r.secret, secret) {
            next.state.activity.push(Activity {
                delivery: None,
                at: now,
                actor: Actor::Routine(routine.into()),
                text: "Rejected a callback with an invalid credential.".into(),
                subject: Ref::Routine(routine.into()),
            });
            self.write(slot, guard, next, vec![], None).await?;
            return Err(Error::InvalidRoutineSecret(routine.into()));
        }
        if let Some(Receipt::External(key, requested)) = &receipt
            && let Some((prior, result)) = r.receipts.get(key)
        {
            if requested.as_ref() != prior {
                return Err(Error::CommandCollision(CommandId(*key)));
            }
            return Ok(result.clone());
        }
        if let Some(Receipt::External(key, requested)) = &receipt
            && r.pending_sends
                .get(key)
                .is_some_and(|op| op != requested.as_ref())
        {
            return Err(Error::CommandCollision(CommandId(*key)));
        }
        let observation = match &op {
            RoutineOp::Report { observation, .. }
            | RoutineOp::AddTask { observation, .. }
            | RoutineOp::AddFact { observation, .. }
            | RoutineOp::Ask(
                RoutineAsk::Question { observation, .. } | RoutineAsk::Approval { observation, .. },
            ) => *observation,
            RoutineOp::Sort { observation, .. }
            | RoutineOp::Complete { observation }
            | RoutineOp::Classified { observation, .. }
            | RoutineOp::GuardedClassified { observation, .. }
            | RoutineOp::SkipRule { observation, .. }
            | RoutineOp::Inbox { observation, .. }
            | RoutineOp::Drop { observation, .. }
            | RoutineOp::AttachEvidence { observation, .. } => Some(*observation),
            _ => None,
        }
        .map(|key| next.callback_observation(key, routine, r.bound_by))
        .transpose()?;
        let was_guarded = matches!(&op, RoutineOp::GuardedClassified { .. });
        let op = match op {
            RoutineOp::GuardedClassified {
                observation: key,
                category,
                snapshot,
            } => {
                let event = &observation.as_ref().context("Missing source item")?.event;
                let candidates = skip_candidates(&next.state.topic, event)?;
                let unambiguous = candidates.is_empty()
                    || (candidates.len() == 1 && skip_rule_fits(&candidates[0]));
                if !snapshot.is_empty()
                    && skip_snapshot(&candidates, event, key)? == snapshot
                    && (category == "needs_you" || unambiguous)
                {
                    RoutineOp::Classified {
                        observation: key,
                        category,
                    }
                } else {
                    RoutineOp::Ask(RoutineAsk::Question {
                        observation: Some(key),
                        text: format!(
                            "The applicable skip rules changed; review this item.\n\n{}",
                            event.text
                        ),
                        suggestions: None,
                    })
                }
            }
            other => other,
        };
        let op = match op {
            RoutineOp::Classified {
                observation: key,
                category,
            } if !was_guarded && category != "needs_you" => {
                let event = &observation.as_ref().context("Missing source item")?.event;
                if skip_candidates(&next.state.topic, event)?.is_empty() {
                    RoutineOp::Classified {
                        observation: key,
                        category,
                    }
                } else {
                    RoutineOp::Ask(RoutineAsk::Question {
                        observation: Some(key),
                        text: format!(
                            "Review this item because this workflow cannot attribute a matching skip rule.\n\n{}",
                            event.text
                        ),
                        suggestions: None,
                    })
                }
            }
            other => other,
        };
        let investigate =
            matches!(&op, RoutineOp::Classified { category, .. } if category == "investigate");
        let op = match op {
            RoutineOp::Classified {
                observation: key,
                category,
            } => {
                let item = &observation
                    .as_ref()
                    .context("Missing source item")?
                    .event
                    .text;
                next.state
                    .usage
                    .days
                    .entry(now.date_naive())
                    .or_default()
                    .system_one += 1;
                match category.as_str() {
                    "inbox" => RoutineOp::Classified {
                        observation: key,
                        category,
                    },
                    "drop" => RoutineOp::Drop {
                        observation: key,
                        reason: "Workflow classified this item as irrelevant or redundant".into(),
                    },
                    "investigate" => RoutineOp::AddTask {
                        observation: Some(key),
                        title: format!("Investigate {}", meep_topic::title_line(item)),
                        instructions: None,
                    },
                    "needs_you" => RoutineOp::Ask(RoutineAsk::Question {
                        observation: Some(key),
                        text: format!("How should we handle this item?\n\n{item}"),
                        suggestions: None,
                    }),
                    _ => return Err(anyhow::anyhow!("Unknown sort category").into()),
                }
            }
            other => other,
        };
        let origin = observation.as_ref().map(|o| o.report.origin.clone());
        let source_thread = observation.as_ref().and_then(|o| {
            o.event
                .thread_hint
                .as_deref()
                .filter(|hint| !hint.is_empty())
                .and_then(|hint| {
                    let key = serde_json::to_string(&(&o.event.connection, &o.event.channel, hint))
                        .ok()?;
                    next.state
                        .threads
                        .iter()
                        .rev()
                        .find(|t| {
                            t.report_sources
                                .as_ref()
                                .and_then(|r| r.observation.as_ref())
                                .is_some_and(|source| {
                                    source.connection == o.event.connection
                                        && source.channel == o.event.channel
                                        && source.thread_hint.as_deref() == Some(hint)
                                })
                                || t.key.strip_prefix("observation/") == Some(key.as_str())
                                || t.key == key
                                || (t.key == hint
                                    && t.messages
                                        .first()
                                        .and_then(|m| m.origin.as_ref())
                                        .is_some_and(|origin| {
                                            origin.connection == o.event.connection
                                                && origin.channel == o.event.channel
                                        }))
                        })
                        .map(|t| t.id)
                })
        });
        // A repeat investigation signal on a known source thread continues its open work.
        let op = if investigate
            && let Some(task) = next.state.tasks.iter().rev().find(|t| {
                t.column != Column::Done
                    && (source_thread.is_some() && t.from_thread == source_thread
                        || t.origin
                            .as_ref()
                            .zip(origin.as_ref())
                            .is_some_and(|(a, b)| a.relates_to(b)))
            })
            && let Some(observation) = &observation
        {
            RoutineOp::AttachEvidence {
                task: task.id,
                observation: observation.report.key,
            }
        } else {
            op
        };
        let mut outcome = None;
        let info = next
            .state
            .topic
            .routines
            .iter_mut()
            .find(|r| r.binding.id == routine)
            .context("missing routine metadata")?;
        let name = info.binding.name.clone();
        info.last_run = Some(now);
        info.health = RoutineHealth::Ok;
        let actor = Actor::Routine(name.clone());
        let mut value = Value::Null;
        let mut changes = vec![];
        match op {
            RoutineOp::Complete { .. } => {
                outcome = Some(ObservationOutcome::Finished {
                    reason: "Workflow completed".into(),
                });
            }
            RoutineOp::GuardedClassified { .. } => unreachable!("normalized before dispatch"),
            RoutineOp::SkipRule {
                observation: key,
                fingerprint,
            } => {
                let event = &observation.as_ref().context("Missing source item")?.event;
                let candidates = skip_candidates(&next.state.topic, event)?;
                let valid = candidates.len() == 1
                    && skip_rule_fits(&candidates[0])
                    && !fingerprint.is_empty()
                    && skip_fingerprint(&candidates[0], event, key)? == fingerprint;
                if !valid {
                    return Err(anyhow::anyhow!("The skip rule changed or is ambiguous; start an agent task to investigate the observation.").into());
                }
                let message = event.message_for(id(), Producer::Routine(routine.into()))?;
                let (received, _, thread, message) =
                    delivery::receive_event(&mut next.state, event, message, false, now)?;
                changes = received;
                let decision = {
                    let rule = &candidates[0];
                    outcome = Some(ObservationOutcome::Dropped {
                        reason: rule.text.clone(),
                    });
                    Decision::Skip {
                        reason: rule.text.clone(),
                        rule: Some(rule.id),
                    }
                };
                changes.extend(next.state.decide_message(thread, message, decision, now)?);
                value = json!({"thread":thread});
            }
            RoutineOp::Classified { .. } => {
                let event = &observation.as_ref().context("Missing source item")?.event;
                let message = event.message_for(id(), Producer::Routine(routine.into()))?;
                let (received, _, thread, message) =
                    delivery::receive_event(&mut next.state, event, message, false, now)?;
                changes = received;
                changes.extend(next.state.decide_message(
                    thread,
                    message,
                    Decision::Handle {
                        summary: meep_topic::title_line(&event.text),
                        outcomes: vec![],
                    },
                    now,
                )?);
                outcome = Some(ObservationOutcome::Inboxed(thread));
                value = json!({"thread":thread});
            }
            RoutineOp::AddTask {
                title,
                instructions,
                ..
            } => {
                let task = id();
                changes = next
                    .state
                    .add_task(task, title, actor, source_thread, now)?;
                let added = next.state.tasks.last_mut().expect("just added");
                if instructions.is_some() {
                    added.instructions = instructions;
                }
                added.origin = origin.clone();
                if observation.is_some() {
                    added.source_message = None;
                }
                if investigate {
                    added.assignment = Some(InboxAssignment::Investigate);
                    let item = &observation.as_ref().context("Missing source item")?.event;
                    changes.extend(next.state.record_task_evidence(
                        task,
                        Actor::Routine(routine.into()),
                        item.text.clone(),
                        origin,
                        now,
                    )?);
                }

                outcome = Some(ObservationOutcome::Task(task));
                value = json!({"task":task});
            }
            RoutineOp::AddFact { text, .. } => {
                let fact = id();
                changes = next.state.add_fact(
                    Fact {
                        id: fact,
                        text,
                        provenance: Provenance {
                            author: origin.as_ref().map_or(name, |o| o.author.clone()),
                            via: origin
                                .as_ref()
                                .map_or_else(|| "Routine".into(), |o| o.connection.clone()),
                            at: origin.as_ref().map_or(now, |o| o.at),
                            origin,
                            thread: source_thread,
                        },
                        superseded_by: None,
                        invalidated_by: None,
                        withdrawn_at: None,
                    },
                    now,
                )?;
                outcome = Some(ObservationOutcome::Fact(fact));
                value = json!({"fact":fact});
            }
            RoutineOp::Ask(RoutineAsk::Question { .. }) => {
                return Err(anyhow::anyhow!(
                    "A routine cannot ask a question in the inbox. Start an agent task so it can ask in its task conversation."
                ).into());
            }
            RoutineOp::Ask(RoutineAsk::Approval {
                task,
                action,
                result,
                draft,
                ..
            }) => {
                outcome = Some(ObservationOutcome::Approval(task));
                next.proposals.insert(
                    task,
                    effects::Proposer::Routine {
                        binding: info.binding.clone(),
                        generation: r.bound_by,
                    },
                );
                changes = commands::submission(&mut next, task, action, result, draft, now)?;
                if let Some(o) = observation.as_ref() {
                    changes.extend(next.state.record_task_evidence(
                        task,
                        actor,
                        o.event.text.clone(),
                        origin,
                        now,
                    )?);
                }
            }
            RoutineOp::Sort { instructions, .. } => {
                let o = observation.as_ref().context("Missing observation")?;
                if instructions != o.instructions {
                    return Err(anyhow::anyhow!(
                        "Sort instructions differ from the saved evaluation"
                    )
                    .into());
                }

                // A plain observation or discarded signal needs no working conversation.
                if let Some(sorted) = &o.suggestion
                    && sorted.work.is_none()
                    && sorted.fact.is_none()
                {
                    let outcome = match &sorted.decision {
                        Decision::Skip { reason, .. } => Some(ObservationOutcome::Dropped {
                            reason: reason.clone(),
                        }),
                        Decision::Handle { outcomes, .. } if outcomes.is_empty() => {
                            Some(ObservationOutcome::Finished {
                                reason: "Observed without publishing a report".into(),
                            })
                        }
                        _ => None,
                    };
                    if let Some(outcome) = outcome {
                        next.resolve_dispatch_uncertainty(o.report.key);
                        next.transition(o.report.key, outcome, now)?;
                        let result = json!({"observation":o.report.key});
                        save_receipt(&mut next, routine, receipt, result.clone())?;
                        self.commit(slot, guard, next, vec![], cause).await?;
                        return Ok(result);
                    }
                }
                let message = o
                    .event
                    .message_for(id(), Producer::Routine(routine.into()))?;
                let (received, _, thread, _) =
                    delivery::receive_event(&mut next.state, &o.event, message.clone(), true, now)?;
                changes = received;
                if o.sort_failed {
                    next.intake.push_back(intake::Pending {
                        failures: 1,
                        retry_reason: o.sort_error.clone(),
                        retry_at: Some(now + chrono::TimeDelta::minutes(1)),
                        sort_step: true,
                        instructions,
                        thread,
                        message: Some(message.id),
                        parent: None,
                        suggestion: None,
                        event: o.event.clone(),
                        cause: cause.clone(),
                        receipt: None,
                    });
                    next.refresh_sort_retry(thread);
                    outcome = Some(ObservationOutcome::Finished {
                        reason: "Queued for another sorting attempt".into(),
                    });
                } else {
                    let sorted = o.suggestion.clone().context("Missing Sort evaluation")?;
                    let mut result = match &sorted.decision {
                        Decision::Skip { reason, .. } => ObservationOutcome::Dropped {
                            reason: reason.clone(),
                        },
                        Decision::Ask { .. } => ObservationOutcome::Asked(thread),
                        _ => ObservationOutcome::Finished {
                            reason: "Sorted the source observation".into(),
                        },
                    };
                    if let Some(InboxWork::Update(task)) = sorted.work.as_ref() {
                        result = ObservationOutcome::Evidence(*task);
                    }
                    let prior = next.state.clone();
                    let applied = match intake::apply_sorted(
                        &mut next.state,
                        thread,
                        &message,
                        &o.event.connection,
                        sorted,
                        now,
                    ) {
                        Ok(changes) => changes,
                        Err(e) => {
                            next.state = prior;
                            result = ObservationOutcome::Asked(thread);
                            next.state.decide_message(
                                thread,
                                message.id,
                                Decision::Ask {
                                    summary: message.text.clone(),
                                    reason: format!(
                                        "The saved source suggestion needs review: {e}"
                                    ),
                                    suggestions: vec![Suggestion::Investigate, Suggestion::Leave],
                                },
                                now,
                            )?
                        }
                    };
                    changes.extend(applied.iter().cloned());
                    for change in &applied {
                        match change.kind {
                            ChangeKind::TaskAdded(task) => {
                                result = ObservationOutcome::Task(task);
                                changes
                                    .extend(routines::start_assigned(&mut next, task, cause, now)?);
                            }
                            ChangeKind::FactAdded(fact) => result = ObservationOutcome::Fact(fact),
                            _ => {}
                        }
                    }
                    outcome = Some(result);
                }
                value = json!({"thread":thread});
            }
            RoutineOp::Report { reports, .. } => {
                let (run, findings) = match reports {
                    RoutineReports::Single {
                        title,
                        body,
                        sources,
                    } => (
                        None,
                        vec![(
                            title,
                            body,
                            ReportSources {
                                references: sources,
                                ..Default::default()
                            },
                        )],
                    ),
                    RoutineReports::Batch {
                        event_id,
                        run_id,
                        reports_json,
                    } => {
                        let rows: Vec<WorkflowFinding> = serde_json::from_str(&reports_json)
                            .context("Expected reports_json to contain an array of findings")?;
                        let mut findings = Vec::new();
                        for row in rows {
                            if !row.impact.chars().any(|c| c.is_ascii_digit())
                                || row.evidence.is_empty()
                                || row.evidence.iter().any(|e| {
                                    e.at.is_none()
                                        || e.kind.as_ref().is_none_or(|k| k.trim().is_empty())
                                })
                            {
                                return Err(anyhow::anyhow!("Workflow findings need measured impact and dated, typed evidence").into());
                            }
                            findings.push((
                                row.title,
                                row.body,
                                ReportSources {
                                    evidence: row.evidence,
                                    priority: Some(row.priority),
                                    impact: Some(row.impact),
                                    proposal: Some(row.proposal),
                                    ..Default::default()
                                },
                            ));
                        }
                        (Some((event_id, run_id)), findings)
                    }
                };
                let mut threads = Vec::new();
                for (title, body, mut sources) in findings {
                    sources.observation = origin.clone();
                    let (thread, received) = delivery::publish_report(
                        &mut next.state,
                        Producer::Routine(routine.into()),
                        &title,
                        &body,
                        sources,
                        now,
                    )?;
                    changes.extend(received);
                    threads.push(thread);
                }
                outcome = Some(threads.first().copied().map_or_else(
                    || ObservationOutcome::Finished {
                        reason: "No findings".into(),
                    },
                    ObservationOutcome::Inboxed,
                ));
                if let Some((event, run)) = run {
                    let history = &mut next.state.routine_report_runs;
                    if let Some(entry) = history
                        .iter_mut()
                        .rev()
                        .find(|entry| entry.event == event && entry.routine == routine)
                    {
                        entry.at = now;
                        entry.runs.push(run);
                        entry.threads.extend_from_slice(&threads);
                    } else {
                        history.push(RoutineReportRun {
                            routine: routine.into(),
                            event,
                            at: now,
                            runs: vec![run],
                            threads: threads.clone(),
                        });
                    }
                    value = json!({"threads":threads});
                } else {
                    value = json!({"thread":threads[0]});
                }
            }
            RoutineOp::Inbox { text, summary, .. } => {
                let body = text
                    .as_deref()
                    .or(summary.as_deref())
                    .context("Provide report findings")?;
                let title = summary.as_deref().filter(|s| *s != body).unwrap_or(&name);
                let (thread, received) = delivery::publish_report(
                    &mut next.state,
                    Producer::Routine(routine.into()),
                    title,
                    body,
                    ReportSources {
                        references: vec![],
                        evidence: vec![],
                        observation: origin,
                        ..Default::default()
                    },
                    now,
                )?;
                changes = received;
                outcome = Some(ObservationOutcome::Inboxed(thread));
                value = json!({"thread":thread});
            }
            RoutineOp::Drop { reason, .. } => {
                if reason.trim().is_empty() {
                    return Err(anyhow::anyhow!("A drop needs a reason").into());
                }
                outcome = Some(ObservationOutcome::Dropped { reason });
            }
            RoutineOp::AttachEvidence { task, .. } => {
                let o = observation.as_ref().context("Missing observation")?;
                let text = format!("{}: {}", o.event.author, o.event.text);
                changes = next
                    .state
                    .record_task_evidence(task, actor, text, origin, now)?;
                outcome = Some(ObservationOutcome::Evidence(task));
                value = json!({"task":task});
            }
            RoutineOp::RefreshView { view, data } => {
                next.state.view_data.insert(view, data);
                next.state.activity.push(Activity {
                    delivery: None,
                    at: now,
                    actor,
                    text: format!("Refreshed view {view}."),
                    subject: Ref::Routine(routine.into()),
                });
            }
            RoutineOp::Note { text } => next.state.activity.push(Activity {
                delivery: None,
                at: now,
                actor,
                text,
                subject: Ref::Routine(routine.into()),
            }),
            RoutineOp::Send { to, text } => {
                // Release the sending topic before acquiring the recipient (possibly itself).
                let mut cause = cause.clone();
                cause.hops = cause.hops.checked_add(1).context("hop count overflow")?;
                let key = receipt.as_ref().map_or_else(
                    || Uuid::new_v4().to_string(),
                    |receipt| match receipt {
                        Receipt::External(id, _) => format!(
                            "callback/{}/{id}",
                            r.bound_by
                                .map_or_else(|| routine.to_owned(), |c| c.to_string())
                        ),
                    },
                );
                if let Some(Receipt::External(id, op)) = &receipt {
                    next.routines
                        .get_mut(routine)
                        .context("missing routine")?
                        .pending_sends
                        .insert(*id, op.as_ref().clone());
                    self.write(slot, guard, next, vec![], None).await?;
                } else {
                    drop(guard);
                }
                self.send_identified(
                    topic,
                    to,
                    text,
                    Producer::Routine(routine.into()),
                    cause,
                    key,
                )
                .await?;
                self.update(topic, &Default::default(), |s, now| {
                    if s.routines
                        .get(routine)
                        .is_some_and(|r| authenticates(r.secret, secret))
                        && let Some(info) = s
                            .state
                            .topic
                            .routines
                            .iter_mut()
                            .find(|i| i.binding.id == routine)
                    {
                        info.last_run = Some(now);
                        info.health = RoutineHealth::Ok;
                        s.state.activity.push(Activity {
                            delivery: None,
                            at: now,
                            actor,
                            text: format!("Sent a message to topic {to}."),
                            subject: Ref::Routine(routine.into()),
                        });
                    }
                    if s.routines
                        .get(routine)
                        .is_some_and(|r| authenticates(r.secret, secret))
                    {
                        save_receipt(s, routine, receipt, Value::Null)?;
                    }
                    Ok(vec![])
                })
                .await?;
                return Ok(Value::Null);
            }
        }
        if let (Some(o), Some(outcome)) = (observation, outcome) {
            next.resolve_dispatch_uncertainty(o.report.key);
            next.transition(o.report.key, outcome, now)?;
        }
        save_receipt(&mut next, routine, receipt, value.clone())?;
        self.commit(slot, guard, next, changes, cause).await?;
        Ok(value)
    }
}
fn save_receipt(
    s: &mut StoredTopic,
    routine: &str,
    receipt: Option<Receipt>,
    value: Value,
) -> Result<()> {
    if let Some(Receipt::External(id, op)) = receipt {
        let binding = s.routines.get_mut(routine).context("missing routine")?;
        binding.pending_sends.remove(&id);
        binding.receipts.insert(id, (*op, value));
    }
    Ok(())
}

#[cfg(test)]
mod skip_guard_tests {
    use super::*;

    #[test]
    fn fingerprints_bind_the_observation_even_when_event_fields_are_identical() -> Result<()> {
        let rule = Rule {
            id: id(),
            text: "Ignore this source".into(),
            effect: RuleEffect::Skip(Matcher::default()),
            from_task: None,
            created_at: DateTime::UNIX_EPOCH,
        };
        let event = meep_ingest::Event {
            connection: "fixture".into(),
            kind: "flag".into(),
            external_id: "same".into(),
            channel: "source".into(),
            thread_hint: None,
            author: "fixture".into(),
            at: DateTime::UNIX_EPOCH,
            text: "same item".into(),
            attributes: Value::Null,
        };
        let first = Uuid::new_v4();
        let second = Uuid::new_v4();
        assert_ne!(
            skip_fingerprint(&rule, &event, first)?,
            skip_fingerprint(&rule, &event, second)?
        );
        assert_ne!(
            skip_snapshot(std::slice::from_ref(&rule), &event, first)?,
            skip_snapshot(std::slice::from_ref(&rule), &event, second)?
        );
        assert_eq!(
            skip_fingerprint(&rule, &event, first)?,
            skip_fingerprint(&rule, &event, first)?
        );
        Ok(())
    }
}
