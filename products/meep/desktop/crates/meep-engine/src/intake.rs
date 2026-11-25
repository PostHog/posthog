use super::*;
use meep_ingest::{Event, group_key};

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Pending {
    #[serde(default)]
    pub failures: u8,
    #[serde(default)]
    pub sort_step: bool,
    #[serde(default)]
    pub instructions: Option<String>,
    #[serde(default)]
    pub retry_at: Option<DateTime<Utc>>,
    #[serde(default)]
    pub retry_reason: Option<String>,
    #[serde(default)]
    pub suggestion: Option<Sorted>,
    pub thread: ThreadId,
    #[serde(default)]
    pub parent: Option<TaskId>,
    #[serde(default)]
    pub message: Option<MessageId>,
    pub event: Event,
    pub cause: Causality,
    #[serde(default)]
    pub receipt: Option<Change>,
}

impl StoredTopic {
    // Only the first pending message in each thread can run.
    pub(super) fn refresh_sort_retry(&mut self, thread: ThreadId) {
        let retry = self
            .intake
            .iter()
            .find(|job| job.thread == thread)
            .and_then(|job| {
                Some(SortRetry {
                    failures: job.failures.into(),
                    next_at: job.retry_at?,
                    reason: job
                        .retry_reason
                        .clone()
                        .unwrap_or_else(|| "The previous sort failed.".into()),
                })
            });
        if let Some(t) = self.state.threads.iter_mut().find(|t| t.id == thread) {
            t.sort_retry = retry;
        }
    }
    pub(super) fn ready_sorts(&self) -> impl Iterator<Item = (usize, &Pending)> {
        let mut threads = std::collections::BTreeSet::new();
        self.intake
            .iter()
            .enumerate()
            .filter(move |(_, job)| threads.insert(job.thread))
    }
}
impl Engine {
    /// Drain committed arrivals in order. Model calls run outside the topic edit lock.
    pub async fn sort_pending(&self, topic: TopicId) -> Result<()> {
        let slot = self.slot(topic)?;
        let _worker = slot.sort_worker.lock().await;
        let count = slot.saved.read().intake.len();
        for _ in 0..count {
            let saved = slot.saved.read().clone();
            let snapshot = &saved.state;
            if snapshot.archived || snapshot.deleted {
                break;
            }
            let Some((_, job)) = saved
                .ready_sorts()
                .find(|(_, j)| j.retry_at.is_none_or(|at| at <= self.0.clock.now()))
            else {
                break;
            };
            let routines = routines::task_routines(&saved, &job.cause);
            let job = job.clone();
            let incoming = snapshot
                .threads
                .iter()
                .find(|t| t.id == job.thread)
                .context("Missing intake thread")?;
            let index = match job.message {
                Some(id) => incoming
                    .messages
                    .iter()
                    .position(|m| m.id == id)
                    .context("Missing intake message")?,
                None => 0, // Older jobs were only written for newly opened threads.
            };
            let message = incoming
                .messages
                .get(index)
                .context("The message to sort is missing")?;
            let mut prefix;
            let conversation = if index + 1 == incoming.messages.len() {
                incoming
            } else {
                prefix = incoming.clone();
                prefix.messages.truncate(index + 1);
                &prefix
            };
            let disputes = snapshot.disputed_facts();
            let input = SortInput {
                topic: &snapshot.topic,
                disputed_fact_ids: &disputes,
                thread: conversation,
                tasks: &snapshot.tasks,
                routines: &routines,
                message,
                event: &job.event,
            };
            let mut owner = job.thread;

            let result = async {
                if let Some(suggestion) = job.suggestion.clone() {
                    return Ok(suggestion);
                }
                if job.sort_step {
                    return self
                        .0
                        .sorter
                        .sort_step(input, job.instructions.as_deref())
                        .await;
                }
                if group_key(&job.event).is_none() && index == 0 {
                    let mut open: Vec<_> = snapshot
                        .threads
                        .iter()
                        .take_while(|t| t.id != incoming.id)
                        .filter(|t| {
                            t.source_material == incoming.source_material
                                && t.accepts_follow_up()
                                && !snapshot.archived_threads.contains(&t.id)
                        })
                        .collect();
                    open.sort_by_key(|t| std::cmp::Reverse(t.updated_at));
                    open.truncate(32);
                    if !open.is_empty()
                        && let Some(target) = self.0.sorter.thread(&input, &open).await?
                    {
                        let target = open
                            .into_iter()
                            .find(|t| t.id == target)
                            .context("Unknown selected thread")?;
                        let mut merged = target.clone();
                        merged.messages.push(message.clone());
                        owner = target.id;
                        return self
                            .0
                            .sorter
                            .sort(SortInput {
                                thread: &merged,
                                ..input
                            })
                            .await;
                    }
                }
                self.0.sorter.sort(input).await
            }
            .await;
            let guard = slot.edit.clone().lock_owned().await;
            let mut next = slot.draft();
            if next.state.archived || next.state.deleted {
                break;
            }
            let target = snapshot
                .threads
                .iter()
                .find(|t| t.id == owner)
                .context("Missing destination thread")?;
            if next.state.archived_threads.contains(&job.thread)
                || next.state.archived_threads.contains(&owner)
                || next.state.threads.iter().find(|t| t.id == owner) != Some(target)
                || next.state.threads.iter().find(|t| t.id == job.thread) != Some(incoming)
                || next.state.topic != snapshot.topic
                || next.state.tasks != snapshot.tasks
                || next.state.disputed_facts() != disputes
            {
                continue;
            }
            // Answering a different thread may have requeued a sort ahead of this one during I/O.
            let position = next
                .intake
                .iter()
                .position(|p| p.thread == job.thread && p.message == job.message)
                .context("Missing pending sort")?;
            let now = self.0.clock.now();
            let sorted = match result {
                Ok(sorted) => sorted,
                Err(error) => {
                    owner = job.thread;
                    let mut retry = job.clone();
                    retry.failures += 1;
                    if retry.failures < 6 {
                        retry.retry_at = Some(
                            now + chrono::Duration::minutes((1i64 << (retry.failures - 1)).min(30)),
                        );
                        retry.retry_reason = Some(sorter::sort_error_reason(&error));
                        next.intake[position] = retry;
                        next.refresh_sort_retry(job.thread);
                        self.commit(slot.clone(), guard, next, vec![], &job.cause)
                            .await?;
                        continue;
                    }
                    retry.receipt = None;
                    next.parked_sorts.insert(message.id, retry);
                    Sorted {
                        confidence: None,
                        work: None,
                        fact: None,
                        decision: Decision::Ask {
                            summary: message.text.clone(),
                            reason: sorter::sort_error_reason(&error),
                            suggestions: vec![
                                Suggestion::SortAgain {
                                    message: message.id,
                                },
                                Suggestion::Leave,
                            ],
                        },
                    }
                }
            };
            let mut changes = if owner != job.thread {
                next.state.join_thread(job.thread, owner, now)?
            } else {
                vec![]
            };
            if let Some(parent) = job.parent {
                let thread = next
                    .state
                    .threads
                    .iter_mut()
                    .find(|t| t.id == owner)
                    .context("Missing follow-up thread")?;
                thread.parent_task = Some(parent);
                if let Some(findings) = job
                    .event
                    .attributes
                    .get("findings")
                    .and_then(|v| v.as_str())
                    && !findings.trim().is_empty()
                {
                    let note = Outcome::Note(findings.to_owned());
                    if !thread.outcomes.contains(&note) {
                        thread.outcomes.push(note);
                    }
                }
            }
            let prior = job.suggestion.is_some().then(|| next.state.clone());
            let applied = apply_sorted(
                &mut next.state,
                owner,
                message,
                &job.event.connection,
                sorted,
                now,
            );
            match (applied, prior) {
                (Ok(applied), _) => changes.extend(applied),
                (Err(e), Some(prior)) => {
                    next.state = prior;
                    changes.extend(next.state.decide_message(
                        owner,
                        message.id,
                        Decision::Ask {
                            summary: message.text.clone(),
                            reason: format!("The saved source suggestion needs review: {e}"),
                            suggestions: vec![Suggestion::Investigate, Suggestion::Leave],
                        },
                        now,
                    )?);
                }
                (Err(e), None) => return Err(e),
            }
            if let Some(task) = changes.iter().find_map(|c| match c.kind {
                ChangeKind::TaskAdded(id) => Some(id),
                _ => None,
            }) {
                changes.extend(routines::start_assigned(&mut next, task, &job.cause, now)?);
            }
            if let Some(mut receipt) = job.receipt {
                receipt.kind = ChangeKind::MessageReceived(owner, message.id);
                routines::on_changes(&mut next, &[receipt], &job.cause);
            }
            next.intake.remove(position);
            next.refresh_sort_retry(job.thread);
            self.commit(slot.clone(), guard, next, changes, &job.cause)
                .await?;
        }
        Ok(())
    }
}

pub(super) fn apply_sorted(
    state: &mut TopicState,
    owner: ThreadId,
    message: &Message,
    connection: &str,
    sorted: Sorted,
    now: DateTime<Utc>,
) -> Result<Changes> {
    let Sorted {
        confidence: _,
        mut decision,
        mut fact,
        mut work,
    } = sorted;
    if let Decision::Ask { suggestions, .. } = &mut decision {
        if !matches!(work, Some(InboxWork::Create { .. }))
            && !suggestions.contains(&Suggestion::Investigate)
        {
            let at = suggestions
                .iter()
                .position(|s| *s == Suggestion::Leave)
                .unwrap_or(suggestions.len());
            suggestions.insert(at, Suggestion::Investigate);
        }
        let target = match &mut work {
            Some(InboxWork::Update(id)) => Some(*id),
            Some(InboxWork::Create { review, .. }) => {
                *review = true;
                None
            }
            None => None,
        };
        if target.is_some() {
            work = None;
        }
        let assertion = fact.take().filter(|text| !text.trim().is_empty());
        if assertion.is_some() || target.is_some() {
            suggestions.insert(
                0,
                Suggestion::AcceptEvidence {
                    message: message.id,
                    task: target,
                    fact: assertion,
                },
            );
        }
    }
    let mut changes = vec![];
    if let Some(work) = work {
        let summary = match &decision {
            Decision::Handle { summary, .. } | Decision::Ask { summary, .. } => summary,
            Decision::Skip { .. } => {
                return Err(anyhow::anyhow!("Cannot assign work on a skipped message").into());
            }
        };
        let task = match work {
            InboxWork::Update(id) => {
                state
                    .tasks
                    .iter()
                    .find(|t| t.id == id && t.column != Column::Done)
                    .context("Unknown open task")?;
                id
            }
            InboxWork::Create { assignment, review } => {
                let id = id();
                changes.extend(state.add_inbox_task(id, owner, summary, assignment, review, now)?);
                let task = state
                    .tasks
                    .iter_mut()
                    .find(|task| task.id == id)
                    .context("Missing new inbox task")?;
                task.source_message = Some(message.id);
                id
            }
        };
        changes.extend(state.add_task_evidence(
            task,
            owner,
            format!("{}: {}", message.author, message.text),
            now,
        )?);
        if let Decision::Handle { outcomes, .. } = &mut decision {
            outcomes.push(Outcome::Task(task));
        } else {
            let thread = state
                .threads
                .iter_mut()
                .find(|t| t.id == owner)
                .context("Missing inbox thread")?;
            if !thread.outcomes.contains(&Outcome::Task(task)) {
                thread.outcomes.push(Outcome::Task(task));
            }
        }
    }
    if let Some(text) = fact.filter(|t| !t.trim().is_empty())
        && !matches!(decision, Decision::Skip { .. })
    {
        let id = id();
        changes.extend(state.add_fact(
            Fact {
                id,
                text,
                provenance: Provenance {
                    origin: message.origin.clone(),
                    author: message.author.clone(),
                    via: connection.to_owned(),
                    at: message.at,
                    thread: Some(owner),
                },
                superseded_by: None,
                invalidated_by: None,
                withdrawn_at: None,
            },
            now,
        )?);
        if let Decision::Handle { outcomes, .. } = &mut decision {
            outcomes.push(Outcome::Fact(id));
        }
    }
    changes.extend(state.decide_message(owner, message.id, decision, now)?);
    Ok(changes)
}
