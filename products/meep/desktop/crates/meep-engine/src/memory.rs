//! Durable System One reconciliation of committed topic memory edits.
use super::*;
use std::collections::BTreeSet;

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Pending {
    seq: u64,
    changed: Fact,
    withdrawal: bool,
    candidates: Vec<FactId>,
    attempts: u8,
    pub(super) retry_at: Option<DateTime<Utc>>,
}

fn source_messages(state: &TopicState, id: ThreadId) -> Option<&[Message]> {
    state
        .threads
        .iter()
        .find(|t| t.id == id)
        .map(|t| t.messages.as_slice())
}

/// Called at the shared commit boundary, while the before-image of a removal is still available.
pub(super) fn enqueue(next: &mut StoredTopic, before: &TopicState, changes: &[Change]) -> bool {
    if !next.state.topic.stage_enabled(CHECK_FACTS) {
        next.fact_checks.clear();
        return false;
    }
    let mut queued = false;
    for (index, change) in changes.iter().enumerate() {
        let (id, withdrawal) = match change.kind {
            ChangeKind::FactAdded(id) => (id, false),
            ChangeKind::FactRemoved(id)
            | ChangeKind::FactInvalidated(id, _)
            | ChangeKind::FactSuperseded(id, _) => (id, true),
            _ => continue,
        };
        let Some(fact) = next
            .state
            .topic
            .facts
            .iter()
            .chain(&before.topic.facts)
            .find(|f| f.id == id)
        else {
            continue;
        };
        let candidates = next
            .state
            .topic
            .facts
            .iter()
            .filter(|f| f.is_current() && f.id != id && Some(f.id) != fact.superseded_by)
            .filter(|f| {
                !changes[index + 1..]
                    .iter()
                    .any(|later| later.kind == ChangeKind::FactAdded(f.id))
            })
            .map(|f| f.id)
            .collect();
        next.fact_checks.push_back(Pending {
            seq: change.seq,
            changed: fact.clone(),
            withdrawal,
            candidates,
            attempts: 0,
            retry_at: None,
        });
        queued = true;
    }
    queued
}

impl Engine {
    // Called under the topic worker lock. Release the edit lock throughout model I/O.
    pub(super) async fn reconcile_facts(&self, topic: TopicId) -> Result<()> {
        let slot = self.slot(topic)?;
        let count = slot.saved.read().fact_checks.len();
        for _ in 0..count {
            let saved = slot.saved.read().clone();
            let snapshot = &saved.state;
            if snapshot.archived || snapshot.deleted {
                break;
            }
            let Some(job) = saved.fact_checks.front() else {
                break;
            };
            if job.retry_at.is_some_and(|at| at > self.0.clock.now()) {
                break;
            }
            let eligible: BTreeSet<_> = job.candidates.iter().copied().collect();
            let active = snapshot
                .topic
                .facts
                .iter()
                .any(|f| f.id == job.changed.id && f.is_current());
            let peers: Vec<_> = snapshot
                .topic
                .facts
                .iter()
                .filter(|f| active != job.withdrawal && f.is_current() && eligible.contains(&f.id))
                .collect();
            if self.0.sorter.hosted_decisions() {
                let compare: Vec<_> = peers.iter().map(|fact| fact.id).collect();
                let line = format!(
                    "“{}” (fact {}{}); it may affect facts {}",
                    meep_topic::title_line(&job.changed.text),
                    job.changed.id,
                    if job.withdrawal { ", withdrawn" } else { "" },
                    serde_json::to_string(&compare)?
                );
                self.update(topic, &Default::default(), |state, _| {
                    if state
                        .fact_checks
                        .front()
                        .is_none_or(|head| head.seq != job.seq)
                        || state.state.topic.facts != snapshot.topic.facts
                    {
                        return Ok(vec![]);
                    }
                    state.fact_checks.pop_front();
                    // The agent's own edits during its turn need no second look; edits by
                    // the person or a routine become one note for its next turn.
                    let agent_editing = session::session_task(state)
                        .is_some_and(|t| matches!(state.runs.get(&t), Some(Work::Poll(_))));
                    if !compare.is_empty() && !agent_editing {
                        state.inbox.note(
                            "Facts changed outside this conversation; correct or withdraw anything that no longer holds:",
                            &line,
                        );
                    }
                    Ok(vec![])
                })
                .await?;
                continue;
            }
            let input = FactCheckInput {
                topic: &snapshot.topic,
                changed: &job.changed,
                withdrawal: job.withdrawal,
                candidates: &peers,
                threads: &snapshot.threads,
            };
            let source_threads: BTreeSet<_> = std::iter::once(&job.changed)
                .chain(peers.iter().copied())
                .chain(input.replacement())
                .filter_map(|f| f.provenance.thread)
                .collect();
            let result = self.0.sorter.check_facts(input).await.and_then(|v| {
                anyhow::ensure!(v.len() == peers.len(), "incomplete fact assessment");
                Ok(v)
            });
            let guard = slot.edit.clone().lock_owned().await;
            let mut next = slot.draft();
            if next.state.archived || next.state.deleted {
                break;
            }
            let now = self.0.clock.now();
            if next.state.topic.facts != snapshot.topic.facts
                || next.state.topic.mission != snapshot.topic.mission
                || source_threads
                    .iter()
                    .any(|id| source_messages(snapshot, *id) != source_messages(&next.state, *id))
            {
                break;
            }
            let Some(head) = next.fact_checks.front_mut().filter(|p| p.seq == job.seq) else {
                break;
            };
            let verdicts = match result {
                Ok(v) => v,
                Err(error) => {
                    head.attempts = head.attempts.saturating_add(1);
                    head.retry_at = Some(
                        now + chrono::TimeDelta::seconds((1_i64 << head.attempts.min(8)).min(300)),
                    );
                    self.write(slot.clone(), guard, next, vec![], None).await?;
                    self.emit(
                        topic,
                        EngineChange::WorkerError(format!(
                            "System One fact check will retry: {error}"
                        )),
                    );
                    break;
                }
            };
            let changes = resolve(&mut next.state, job, &peers, verdicts, now)?;
            next.fact_checks.pop_front();
            self.commit(slot.clone(), guard, next, changes, &Default::default())
                .await?;
        }
        Ok(())
    }
}

fn resolve(
    state: &mut TopicState,
    job: &Pending,
    peers: &[&Fact],
    verdicts: Vec<FactVerdict>,
    now: DateTime<Utc>,
) -> Result<Changes> {
    let mut changes = vec![];
    // Replacing the focal fact would invalidate other outstanding judgments about it.
    let ambiguous = verdicts.contains(&FactVerdict::ExistingWins)
        && verdicts
            .iter()
            .filter(|v| **v != FactVerdict::Independent)
            .count()
            > 1;
    for (&peer, verdict) in peers.iter().zip(verdicts) {
        if verdict == FactVerdict::Independent {
            continue;
        }
        let resolution = match (verdict, job.withdrawal) {
            (FactVerdict::ChangedWins, false) if !ambiguous => Some(FactResolution::KeepChanged),
            (FactVerdict::ExistingWins, false) if !ambiguous => Some(FactResolution::KeepExisting),
            (FactVerdict::Unsupported, true) => Some(FactResolution::RetireDependent),
            _ => None,
        };
        if let Some(resolution) = resolution {
            changes.extend(state.resolve_facts(
                job.changed.id,
                peer.id,
                resolution,
                Actor::Agent,
                now,
            )?);
        } else {
            changes.extend(ask(state, job, peer, now)?);
        }
    }
    Ok(changes)
}

fn ask(state: &mut TopicState, job: &Pending, other: &Fact, now: DateTime<Utc>) -> Result<Changes> {
    let changed = &job.changed;
    let key = format!("fact-review/{}/{}/{}", job.seq, changed.id, other.id);
    let thread: ThreadId = id();
    let (reason, choices): (_, &[_]) = if job.withdrawal {
        (
            "Does B still have independent support after A was withdrawn?",
            &[
                FactResolution::KeepDependent,
                FactResolution::RetireDependent,
            ],
        )
    } else {
        (
            "Which assertion should this topic use?",
            &[
                FactResolution::KeepChanged,
                FactResolution::KeepExisting,
                FactResolution::KeepBoth,
            ],
        )
    };
    let evidence = |fact: &Fact| {
        format!(
            "{}\n{} · {} · {}",
            fact.text, fact.provenance.author, fact.provenance.via, fact.provenance.at
        )
    };
    let text = format!(
        "Fact review · {}\n\nA ({}) · {}\n\nB (existing) · {}",
        other.text,
        if job.withdrawal { "withdrawn" } else { "added" },
        evidence(changed),
        evidence(other)
    );
    let mut changes = state.receive(
        Message {
            id: id(),
            producer: Producer::System,
            origin: Some(Source::Topic(state.topic.id).into_origin("System 1".into(), now, None)),
            author: "System 1".into(),
            at: now,
            text,
            external_id: None,
        },
        key,
        thread,
        now,
    )?;
    let suggestions = choices
        .iter()
        .map(|&resolution| Suggestion::ResolveFacts {
            changed: changed.id,
            other: other.id,
            resolution,
        })
        .collect();
    changes.extend(state.sort(
        thread,
        Decision::Ask {
            summary: format!("Review “{}”", other.text),
            reason: reason.into(),
            suggestions,
        },
        now,
    )?);
    Ok(changes)
}
