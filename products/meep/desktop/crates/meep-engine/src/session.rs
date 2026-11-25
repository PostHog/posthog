//! The topic's one agent and its conversation.
//!
//! Everything for the agent lands in the topic inbox: the person's messages, notes
//! from Meep (approval answers, memory changes) and the to-dos it planned for itself.
//! A turn takes everything waiting at once, the person's messages first. A message
//! from the person reaches a working agent straight away (it steers), unless it was
//! sent to wait for the current work (queued).

use super::*;

/// What is waiting for the topic agent. Persisted with the topic.
#[derive(Clone, Default, Serialize, Deserialize)]
pub(super) struct Inbox {
    #[serde(default, skip_serializing_if = "VecDeque::is_empty")]
    items: VecDeque<Item>,
    /// To-dos the agent has already been shown, so they don't wake it again.
    #[serde(default, skip_serializing_if = "BTreeSet::is_empty")]
    seen: BTreeSet<TaskId>,
    /// The turn in progress, so a message that interrupts it can carry it along.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    current: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
struct Item {
    text: String,
    /// The person's chat message this item stands for.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    thread: Option<ThreadId>,
    /// The task reserved for the conversation, if this message has to start it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    task: Option<TaskId>,
    /// Sent to wait for the agent's current work instead of interrupting it.
    #[serde(default)]
    queued: bool,
}

impl Inbox {
    #[cfg(test)]
    pub(super) fn texts(&self) -> Vec<String> {
        self.items.iter().map(|i| i.text.clone()).collect()
    }
    pub(super) fn is_empty(&self) -> bool {
        self.items.is_empty() && self.seen.is_empty() && self.current.is_none()
    }
    /// A message from the person.
    pub(super) fn message(&mut self, thread: ThreadId, task: TaskId, text: &str, queued: bool) {
        self.items.push_back(Item {
            text: text.to_owned(),
            thread: Some(thread),
            task: Some(task),
            queued,
        });
    }
    /// A note from Meep for the agent's next turn. Notes with the same heading are
    /// merged, so many small changes make one note.
    pub(super) fn note(&mut self, heading: &str, line: &str) {
        if let Some(item) = self
            .items
            .iter_mut()
            .find(|i| i.thread.is_none() && i.text.starts_with(heading))
        {
            item.text.push_str(&format!("\n- {line}"));
            return;
        }
        self.items.push_back(Item {
            text: format!("{heading}\n- {line}"),
            thread: None,
            task: None,
            queued: false,
        });
    }
    /// Offer a to-do to the agent again, for example after its work on it was stopped.
    pub(super) fn unsee(&mut self, task: TaskId) {
        self.seen.remove(&task);
    }
    fn waiting_messages(&self) -> impl Iterator<Item = &Item> {
        self.items.iter().filter(|i| i.thread.is_some())
    }
}

/// What the topic worker should do for the conversation now.
#[derive(Debug, PartialEq)]
pub(super) enum Step {
    /// No conversation yet: this message starts it.
    Start,
    /// The conversation never got a run; start it again with the newest message.
    Restart(TaskId),
    /// Send the next turn. `steer` stops the work in progress first; `decline`
    /// answers an open permission prompt with “no” first.
    Turn {
        session: TaskId,
        steer: bool,
        decline: bool,
    },
}

/// The topic's conversation: the newest chat task. There is one per topic.
pub(crate) fn session_task(s: &StoredTopic) -> Option<TaskId> {
    s.state
        .tasks
        .iter()
        .rev()
        .find(|t| t.is_session())
        .map(|t| t.id)
}

/// Whether the conversation's task has been given a run at some point.
pub(super) fn started(s: &StoredTopic, task: TaskId) -> bool {
    s.task_handles.contains_key(&task) || matches!(s.runs.get(&task), Some(Work::Poll(_)))
}

fn unseen_todos(s: &StoredTopic) -> impl Iterator<Item = &Task> {
    s.state.tasks.iter().filter(|t| {
        t.assignment == Some(InboxAssignment::Session)
            && t.column == Column::Todo
            && !t.queued
            && !s.inbox.seen.contains(&t.id)
    })
}

/// Decide the next step without changing anything.
pub(super) fn next_step(s: &StoredTopic) -> Option<Step> {
    if s.state.archived || s.state.deleted {
        return None;
    }
    let urgent = s.inbox.waiting_messages().any(|i| !i.queued);
    let any_message = s.inbox.waiting_messages().next().is_some();
    let Some(session) = session_task(s) else {
        return any_message.then_some(Step::Start);
    };
    let task = s.state.tasks.iter().find(|t| t.id == session)?;
    if !started(s, session) {
        // A start that failed before any run: the next message tries again.
        return (task.column == Column::NeedsYou && any_message).then_some(Step::Restart(session));
    }
    if matches!(s.runs.get(&session), Some(Work::Poll(_))) {
        return urgent.then_some(Step::Turn {
            session,
            steer: true,
            decline: false,
        });
    }
    if s.runs.contains_key(&session) {
        return None;
    }
    let prompt = task.column == Column::NeedsYou && task.action.is_some();
    if prompt {
        // An open permission prompt waits for an answer; writing to the agent instead
        // declines it.
        return urgent.then_some(Step::Turn {
            session,
            steer: false,
            decline: true,
        });
    }
    (!s.inbox.items.is_empty() || unseen_todos(s).next().is_some()).then_some(Step::Turn {
        session,
        steer: false,
        decline: false,
    })
}

/// The turn's text: the person's messages first, then everything else waiting.
fn turn_text(you: &[String], notes: &[String], todos: &[String], steer: Option<&str>) -> String {
    let mut out = String::new();
    if !you.is_empty() {
        if let Some(doing) = steer {
            let doing: String = doing.chars().take(2000).collect();
            let quoted = doing
                .lines()
                .map(|l| format!("> {l}"))
                .collect::<Vec<_>>()
                .join("\n");
            out.push_str(&format!(
                "The person wrote while you were working. You were in the middle of this:\n\n{quoted}\n\nAnswer the person first, then finish that work unless they redirect you.\n\nThe person wrote:\n\n"
            ));
        }
        out.push_str(&you.join("\n\n"));
    }
    let mut waiting: Vec<&String> = notes.iter().collect();
    waiting.extend(todos);
    if !waiting.is_empty() {
        if !out.is_empty() {
            out.push_str("\n\n---\nAlso waiting:\n");
        } else {
            out.push_str("Waiting for you:\n");
        }
        for w in waiting {
            out.push_str(&format!("\n{w}\n"));
        }
        out.push_str(
            "\nDecide how to handle these: do quick ones now, use a sub-agent (plan_task for: sub_agent) only for work that can run in parallel or suits a simpler, faster model, and leave the rest as to-dos. Mark to-dos done with complete_task. Say briefly what you are doing.",
        );
    }
    out
}

impl Engine {
    /// Move the conversation forward: start it, retry it, or give it its next turn.
    pub(super) async fn drive_session(&self, topic: TopicId) -> Result<()> {
        let slot = self.slot(topic)?;
        let mut step = next_step(&slot.saved.read());
        if let Some(Step::Turn {
            steer: true,
            session,
            ..
        }) = step
        {
            // The run may have finished since it was last checked: post its answer
            // instead of interrupting it.
            self.advance(topic, &slot, session).await?;
            step = next_step(&slot.saved.read());
        }
        match step {
            None => Ok(()),
            Some(Step::Start) => self.start_session(topic).await,
            Some(Step::Restart(session)) => self.restart_session(topic, session).await,
            Some(Step::Turn {
                session,
                steer,
                decline,
            }) => {
                if decline {
                    self.send_back(
                        topic,
                        session,
                        "The person wrote to you instead of answering this.",
                    )
                    .await?;
                }
                self.take_turn(topic, session, steer).await
            }
        }
    }

    /// The first message opens the conversation, on the task reserved for it.
    async fn start_session(&self, topic: TopicId) -> Result<()> {
        self.update(topic, &Default::default(), |s, now| {
            let Some(index) = s.inbox.items.iter().position(|i| i.thread.is_some()) else {
                return Ok(vec![]);
            };
            let item = s.inbox.items.remove(index).expect("found");
            let (Some(thread), Some(task)) = (item.thread, item.task) else {
                return Ok(vec![]);
            };
            let mut changes = s.state.add_requested_task(
                task,
                thread,
                meep_topic::title_line(&item.text),
                InboxAssignment::ChatAnswer,
                now,
            )?;
            changes.extend(sent(&mut s.state, thread, task, now)?);
            Ok(changes)
        })
        .await?;
        Ok(())
    }

    /// The conversation's first run never started: try again, answering the newest message.
    async fn restart_session(&self, topic: TopicId, session: TaskId) -> Result<()> {
        self.update(topic, &Default::default(), |s, now| {
            let threads: Vec<ThreadId> = s
                .inbox
                .waiting_messages()
                .filter_map(|i| i.thread)
                .collect();
            s.inbox.items.retain(|i| i.thread.is_none());
            let mut changes = vec![];
            for thread in &threads {
                changes.extend(sent(&mut s.state, *thread, session, now)?);
            }
            if let Some(t) = s.state.tasks.iter_mut().find(|t| t.id == session) {
                t.from_thread = threads.last().copied().or(t.from_thread);
            }
            changes.extend(s.state.move_task(session, Column::Todo, now)?);
            Ok(changes)
        })
        .await?;
        Ok(())
    }

    /// Hand the agent everything waiting as one turn of its conversation.
    async fn take_turn(&self, topic: TopicId, session: TaskId, steer: bool) -> Result<()> {
        let mut text = String::new();
        self.update(topic, &Default::default(), |s, now| {
            // What it was in the middle of, in full, so it can finish it after answering.
            let doing = steer.then(|| {
                s.inbox
                    .current
                    .clone()
                    .unwrap_or_else(|| "the turn in progress".into())
            });
            // Steering brings in only the person's messages; the rest waits for the turn.
            let (taken, kept): (Vec<Item>, Vec<Item>) = s.inbox.items.drain(..).partition(|i| {
                if steer {
                    i.thread.is_some() && !i.queued
                } else {
                    true
                }
            });
            s.inbox.items = kept.into();
            let you: Vec<&Item> = taken.iter().filter(|i| i.thread.is_some()).collect();
            let notes: Vec<String> = taken
                .iter()
                .filter(|i| i.thread.is_none())
                .map(|i| i.text.clone())
                .collect();
            let todos: Vec<(TaskId, String)> = if steer {
                vec![]
            } else {
                unseen_todos(s)
                    .map(|t| {
                        let brief = t
                            .instructions
                            .as_deref()
                            .map(|b| format!(": {b}"))
                            .unwrap_or_default();
                        (t.id, format!("To-do “{}” (task {}){brief}", t.title, t.id))
                    })
                    .collect()
            };
            if you.is_empty() && notes.is_empty() && todos.is_empty() {
                return Ok(vec![]);
            }
            s.inbox.seen.extend(todos.iter().map(|(id, _)| *id));
            let mut changes = vec![];
            for item in &you {
                changes.extend(sent(
                    &mut s.state,
                    item.thread.expect("message"),
                    session,
                    now,
                )?);
            }
            // The answer goes to the person's newest message, or to a line saying what
            // the agent picked up when nobody asked.
            let reply_to = match you.last().and_then(|i| i.thread) {
                Some(thread) => thread,
                None => {
                    let label = todos
                        .first()
                        .map(|(_, t)| t.split(" (task").next().unwrap_or(t).to_owned())
                        .or_else(|| {
                            notes.first().map(|n| {
                                let mut lines = n.lines();
                                let head = lines.next().unwrap_or(n).trim_end_matches(':');
                                match lines.next() {
                                    Some(first) => {
                                        format!("{head}: {}", first.trim_start_matches("- "))
                                    }
                                    None => head.to_owned(),
                                }
                            })
                        })
                        .unwrap_or_default();
                    let (thread, opened) = announce(&mut s.state, &label, session, now)?;
                    changes.extend(opened);
                    thread
                }
            };
            if let Some(t) = s.state.tasks.iter_mut().find(|t| t.id == session) {
                t.from_thread = Some(reply_to);
            }
            let you: Vec<String> = you.iter().map(|i| i.text.clone()).collect();
            let todos: Vec<String> = todos.into_iter().map(|(_, t)| t).collect();
            text = turn_text(&you, &notes, &todos, doing.as_deref());
            s.inbox.current = Some(text.clone());
            Ok(changes)
        })
        .await?;
        if text.is_empty() {
            return Ok(());
        }
        if let Err(e) = self.send_task_message(topic, session, &text).await {
            self.update(topic, &Default::default(), |s, now| {
                let Some(thread) = s
                    .state
                    .tasks
                    .iter()
                    .find(|t| t.id == session)
                    .and_then(|t| t.from_thread)
                else {
                    return Ok(vec![]);
                };
                let reply = format!(
                    "Couldn't reach the topic agent: {e}. Send your message again to retry."
                );
                Ok(s.state
                    .apply_inbox_decision(
                        thread,
                        Decision::Handle {
                            summary: reply.clone(),
                            outcomes: vec![Outcome::Reply {
                                to: Source::User,
                                text: reply,
                            }],
                        },
                        now,
                    )
                    .unwrap_or_default())
            })
            .await?;
        }
        Ok(())
    }
}

/// Mark the person's message as handed to the conversation.
fn sent(
    state: &mut TopicState,
    thread: ThreadId,
    session: TaskId,
    now: DateTime<Utc>,
) -> std::result::Result<Changes, TopicError> {
    if !state
        .threads
        .iter()
        .any(|t| t.id == thread && t.state == ThreadState::Sorting)
    {
        return Ok(vec![]);
    }
    state.sort(
        thread,
        Decision::Handle {
            summary: "Sent to the topic agent.".into(),
            outcomes: vec![Outcome::Task(session)],
        },
        now,
    )
}

/// A line in the chat for a turn nobody asked for, such as picking up a to-do.
fn announce(
    state: &mut TopicState,
    label: &str,
    session: TaskId,
    now: DateTime<Utc>,
) -> std::result::Result<(ThreadId, Changes), TopicError> {
    let thread = ThreadId(Uuid::new_v4());
    let mut changes = state.receive(
        Message {
            id: MessageId(thread.0),
            producer: Producer::System,
            origin: Some(Source::User.into_origin("Meep".into(), now, None)),
            author: "Meep".into(),
            at: now,
            text: label.to_owned(),
            external_id: None,
        },
        thread.to_string(),
        thread,
        now,
    )?;
    changes.extend(sent(state, thread, session, now)?);
    Ok((thread, changes))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_persons_messages_come_first_and_the_rest_is_listed_as_waiting() {
        let text = turn_text(
            &["Why did retention drop?".into()],
            &["Approved: Activate Scout".into()],
            &["To-do “Weekly summary” (task 1)".into()],
            None,
        );
        assert!(text.starts_with("Why did retention drop?"));
        assert!(text.contains("Also waiting:"));
        assert!(text.find("Approved").unwrap() < text.find("Weekly summary").unwrap());
        let steer = turn_text(
            &["Stop and check signups".into()],
            &[],
            &[],
            Some("Draft the weekly summary"),
        );
        assert!(steer.contains("> Draft the weekly summary"));
        assert!(steer.ends_with("Stop and check signups"));
    }
}
