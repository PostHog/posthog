use super::{ConnectionInfo, NeedsYou, NeedsYouItem};
use chrono::{DateTime, Utc};
use meep_topic::{Column, Thread, ThreadState, TopicState};

/// Older workflow-created questions put a generic prompt before the actual
/// source item. Derive the list copy at read time so existing replicas benefit
/// without changing the question or its identity.
fn decision_copy(state: &TopicState, thread: &Thread, reason: &str) -> (String, String) {
    const QUESTION: &str = "How should we handle this item?";
    if thread.subject.trim() != QUESTION {
        return (thread.subject.clone(), reason.to_owned());
    }
    let current = match thread.question_source {
        Some(id) => thread.messages.iter().find(|message| message.id == id),
        None => thread.messages.first(),
    };
    let Some(item) = current
        .and_then(|message| message.text.trim().strip_prefix(QUESTION))
        .map(str::trim)
        .filter(|item| !item.is_empty())
    else {
        return (thread.subject.clone(), reason.to_owned());
    };
    let title = meep_topic::title_line(item);
    if title.is_empty() {
        return (thread.subject.clone(), reason.to_owned());
    }
    let source = thread
        .report_sources
        .as_ref()
        .and_then(|sources| sources.observation.as_ref())
        .and_then(|origin| {
            state
                .topic
                .watches()
                .find(|watch| watch.connection == origin.connection && watch.key == origin.channel)
        })
        .map(|watch| watch.label.trim())
        .filter(|label| !label.is_empty());
    let reason = reason.trim();
    let detail = if reason.is_empty() || reason.starts_with(QUESTION) {
        QUESTION
    } else {
        reason
    };
    let detail = source.map_or_else(|| detail.to_owned(), |name| format!("{name} · {detail}"));
    (title, detail)
}

impl NeedsYou {
    /// Build the cross-topic attention list in descending order of observation time.
    /// Connections carry the time their unhealthy state was first observed by the caller.
    pub fn from_states<'a>(
        states: impl IntoIterator<Item = &'a TopicState> + Clone,
        connections: impl IntoIterator<Item = (ConnectionInfo, DateTime<Utc>)>,
    ) -> Self {
        let mut items = vec![];
        for state in states
            .clone()
            .into_iter()
            .filter(|s| !s.archived && !s.deleted)
        {
            let topic = state.topic.id;
            for thread in state
                .threads
                .iter()
                .filter(|t| !state.archived_threads.contains(&t.id))
            {
                if let ThreadState::NeedsYou { reason, .. } = &thread.state {
                    let (title, detail) = decision_copy(state, thread, reason);
                    items.push((
                        thread.updated_at,
                        NeedsYouItem::Decide {
                            topic,
                            thread: thread.id.to_string(),
                            title,
                            detail,
                        },
                    ));
                }
            }
            for task in &state.tasks {
                // The topic agent's own conversation reports its problems in the chat; only
                // its permission prompt also waits here.
                if task.column == Column::NeedsYou && task.is_session() {
                    if let Some(action) = &task.action {
                        items.push((
                            task.updated_at,
                            NeedsYouItem::Approve {
                                topic,
                                task: task.id.to_string(),
                                title: action.label.clone(),
                                detail: "The agent asks for your OK in the conversation.".into(),
                                action: Some("Approve".into()),
                            },
                        ));
                    }
                    continue;
                }
                if task.column == Column::NeedsYou {
                    items.push((
                        task.updated_at,
                        NeedsYouItem::Approve {
                            topic,
                            task: task.id.to_string(),
                            title: task.title.clone(),
                            detail: task
                                .input_question
                                .as_ref()
                                .or(task.result.as_ref())
                                .or(task.draft.as_ref())
                                .cloned()
                                .unwrap_or_default(),
                            action: Some(
                                if task.input_question.is_some() {
                                    "Reply"
                                } else {
                                    task.review_action_label()
                                }
                                .into(),
                            ),
                        },
                    ));
                }
            }
        }
        for (c, since) in connections {
            if c.health == "ok" {
                continue;
            }
            let topics: Vec<_> = states
                .clone()
                .into_iter()
                .filter(|s| {
                    !s.archived
                        && !s.deleted
                        && (c.grants.contains(&s.topic.id)
                            || s.topic.watches().any(|w| w.connection == c.id))
                })
                .map(|s| s.topic.id)
                .collect();
            if !topics.is_empty() {
                items.push((
                    c.unhealthy_since.unwrap_or(since),
                    NeedsYouItem::Problem {
                        topics,
                        connection: c.id,
                        title: if c.health == "expired" {
                            format!("Sign in to {} again", c.label)
                        } else {
                            format!("{} isn't working", c.label)
                        },
                        detail: c.summary,
                    },
                ));
            }
        }
        items.sort_by_key(|(at, _)| std::cmp::Reverse(*at));
        NeedsYou {
            items: items.into_iter().map(|(_, item)| item).collect(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use meep_topic::{
        Actor, Decision, Message, MessageId, Origin, Producer, ReportSources, Source, TaskId,
        ThreadId, Topic, TopicId, Watch, WatchId,
    };

    #[test]
    fn workflow_questions_show_the_observation_and_source_instead_of_duplicate_prompts() {
        let now = DateTime::UNIX_EPOCH;
        let topic: TopicId = "00000000-0000-0000-0000-000000000001".parse().unwrap();
        let mut state = TopicState::new(Topic::new(topic, "Example", now));
        for (n, label, text) in [
            (1, "Launch flag", "The launch flag is now active."),
            (2, "Checkout flag", "The checkout flag is now inactive."),
        ] {
            let watch = Watch {
                id: format!("00000000-0000-0000-0000-{n:012x}").parse().unwrap(),
                connection: "posthog".into(),
                kind: "flag".into(),
                key: n.to_string(),
                label: label.into(),
            };
            state.topic.default_watches_mut().push(watch);
            let thread: ThreadId = format!("10000000-0000-0000-0000-{n:012x}").parse().unwrap();
            let message: MessageId = format!("20000000-0000-0000-0000-{n:012x}").parse().unwrap();
            let body = format!("How should we handle this item?\n\n{text}");
            state
                .receive(
                    Message {
                        id: message,
                        producer: Producer::Routine("sort".into()),
                        origin: Some(Source::Topic(topic).into_origin(
                            "Sort inbox".into(),
                            now,
                            None,
                        )),
                        author: "Sort inbox".into(),
                        at: now,
                        text: body.clone(),
                        external_id: None,
                    },
                    thread.to_string(),
                    thread,
                    now,
                )
                .unwrap();
            state.threads.last_mut().unwrap().report_sources = Some(ReportSources {
                references: vec![],
                evidence: vec![],
                observation: Some(Origin {
                    connection: "posthog".into(),
                    channel: n.to_string(),
                    external_id: None,
                    thread_hint: None,
                    author: label.into(),
                    at: now,
                }),
                ..Default::default()
            });
            state
                .decide_message(
                    thread,
                    message,
                    Decision::Ask {
                        summary: body.clone(),
                        reason: body,
                        suggestions: vec![],
                    },
                    now,
                )
                .unwrap();
        }
        let items = NeedsYou::from_states([&state], []).items;
        assert!(matches!(&items[..], [
            NeedsYouItem::Decide { title: first, detail: first_detail, .. },
            NeedsYouItem::Decide { title: second, detail: second_detail, .. },
        ] if first == "The launch flag is now active."
            && first_detail == "Launch flag · How should we handle this item?"
            && second == "The checkout flag is now inactive."
            && second_detail == "Checkout flag · How should we handle this item?"));
        assert_eq!(
            decision_copy(&state, &state.threads[1], "Review the rollback.").1,
            "Checkout flag · Review the rollback."
        );
    }

    #[test]
    fn specific_or_context_free_questions_keep_their_original_copy() {
        let now = DateTime::UNIX_EPOCH;
        let topic: TopicId = "00000000-0000-0000-0000-000000000001".parse().unwrap();
        let mut state = TopicState::new(Topic::new(topic, "Example", now));
        let thread: ThreadId = "10000000-0000-0000-0000-000000000001".parse().unwrap();
        let message: MessageId = "20000000-0000-0000-0000-000000000001".parse().unwrap();
        state
            .receive(
                Message {
                    id: message,
                    producer: Producer::User,
                    origin: Some(Source::User.into_origin("Person".into(), now, None)),
                    author: "Person".into(),
                    at: now,
                    text: "Which release should ship?".into(),
                    external_id: None,
                },
                "question",
                thread,
                now,
            )
            .unwrap();
        state
            .decide_message(
                thread,
                message,
                Decision::Ask {
                    summary: "Release question".into(),
                    reason: "Choose a release".into(),
                    suggestions: vec![],
                },
                now,
            )
            .unwrap();
        assert!(matches!(&NeedsYou::from_states([&state], []).items[..],
            [NeedsYouItem::Decide { title, detail, .. }] if title == "Which release should ship?" && detail == "Choose a release"));
    }

    #[test]
    fn a_connection_problem_lists_granted_and_watching_topics_once_in_input_order() {
        let now = DateTime::UNIX_EPOCH;
        let topic = |n: u128| {
            let id: TopicId = format!("00000000-0000-0000-0000-{n:012x}").parse().unwrap();
            TopicState::new(Topic::new(id, "Example", now))
        };
        let mut granted = topic(1);
        let mut watched = topic(2);
        let unrelated = topic(3);
        let task: TaskId = "00000000-0000-0000-0000-000000000004".parse().unwrap();
        granted
            .add_task(task, "Review", Actor::User, None, now)
            .unwrap();
        granted.move_task(task, Column::NeedsYou, now).unwrap();
        let watch = Watch {
            id: "00000000-0000-0000-0000-000000000005"
                .parse::<WatchId>()
                .unwrap(),
            connection: "work".into(),
            kind: "channel".into(),
            key: "design".into(),
            label: "Design".into(),
        };
        granted.topic.default_watches_mut().push(watch.clone());
        watched.topic.default_watches_mut().push(watch);
        let ids = [watched.topic.id, granted.topic.id];
        let connection = ConnectionInfo {
            unrouted: 0,
            id: "work".into(),
            kind: "slack".into(),
            label: "Work".into(),
            account: None,
            health: "expired".into(),
            unhealthy_since: None,
            summary: "Sign in".into(),
            grants: vec![granted.topic.id],
        };
        let states = [watched, unrelated, granted];
        let later = now + chrono::TimeDelta::seconds(1);
        let items = NeedsYou::from_states(&states, [(connection.clone(), later)]).items;
        assert!(
            matches!(&items[..], [NeedsYouItem::Problem { topics, detail, .. }, NeedsYouItem::Approve { .. }] if topics == &ids && detail == "Sign in")
        );
        let healthy = ConnectionInfo {
            health: "ok".into(),
            ..connection
        };
        assert!(matches!(
            &NeedsYou::from_states(&states, [(healthy, later)]).items[..],
            [NeedsYouItem::Approve { .. }]
        ));
    }
}
