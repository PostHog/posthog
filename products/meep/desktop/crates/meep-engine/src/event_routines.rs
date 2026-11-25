//! Translate committed topic changes into durable PostHog invocations.
use super::*;
use meep_ingest::Event;
use serde_json::{Value, json};

fn matches_filter(on: TopicEvent, key: &str, actual: Option<&str>, expected: &str) -> bool {
    actual.is_some_and(|actual| {
        if on == TopicEvent::TaskMoved && matches!(key, "from" | "to" | "column") {
            actual.eq_ignore_ascii_case(expected)
        } else {
            actual == expected
        }
    })
}

impl StoredTopic {
    pub(super) fn queue_topic_change(&mut self, c: &Change, cause: &Causality) {
        if self.state.archived
            || self.state.deleted
            || !self
                .state
                .topic
                .routines
                .iter()
                .any(|r| r.enabled && r.event.is_some())
        {
            return;
        }
        let (on, fields) = match c.kind {
            ChangeKind::MessageReceived(thread, message) => {
                let Some(m) = self
                    .state
                    .threads
                    .iter()
                    .find(|t| t.id == thread && !t.source_material)
                    .and_then(|t| t.messages.iter().find(|m| m.id == message))
                else {
                    return;
                };
                let (connection, channel) = match m.reply_target() {
                    Some(Source::Connection {
                        connection,
                        channel,
                    }) => (connection, channel),
                    Some(Source::Topic(id)) => ("topic".into(), id.to_string()),
                    Some(Source::User) => ("user".into(), String::new()),
                    None => Default::default(),
                };
                (
                    TopicEvent::MessageArrived,
                    json!({"thread":thread,"message":message,"author":m.author,"text":m.text,"connection":connection,"channel":channel}),
                )
            }
            ChangeKind::TaskAdded(id) | ChangeKind::TaskMoved { task: id, .. } => {
                let Some(t) = self.state.tasks.iter().find(|t| t.id == id) else {
                    return;
                };
                if let ChangeKind::TaskMoved { from, to, .. } = c.kind {
                    let column = |c| match c {
                        Column::Todo => "todo",
                        Column::InProgress => "inProgress",
                        Column::NeedsYou => "needsYou",
                        Column::Done => "done",
                    };
                    (
                        TopicEvent::TaskMoved,
                        json!({"task":id,"title":t.title,"from":column(from),"to":column(to),"column":column(to)}),
                    )
                } else {
                    (TopicEvent::TaskAdded, json!({"task":id,"title":t.title}))
                }
            }
            ChangeKind::FactAdded(id)
            | ChangeKind::FactRemoved(id)
            | ChangeKind::FactSuperseded(id, _)
            | ChangeKind::FactInvalidated(id, _) => {
                let (change, replacement) = match c.kind {
                    ChangeKind::FactAdded(_) => ("added", None),
                    ChangeKind::FactSuperseded(_, new) => ("superseded", Some(new)),
                    ChangeKind::FactInvalidated(_, by) => ("invalidated", Some(by)),
                    _ => ("removed", None),
                };
                (
                    TopicEvent::FactChanged,
                    json!({"fact":id,"text":self.state.topic.facts.iter().find(|f|f.id==id).map(|f|&f.text),"change":change,"replacement":replacement}),
                )
            }
            _ => return,
        };
        self.queue_topic_event(on, fields, c.at, cause);
    }

    pub(super) fn routine_failed(
        &mut self,
        routine: &str,
        error: &str,
        now: DateTime<Utc>,
        cause: &Causality,
    ) {
        let mut cause = cause.clone();
        cause.stack.push((self.state.topic.id, routine.into()));
        self.queue_topic_event(
            TopicEvent::RoutineFailed,
            json!({"routine":routine,"error":error}),
            now,
            &cause,
        );
    }

    fn queue_topic_event(
        &mut self,
        on: TopicEvent,
        mut fields: Value,
        now: DateTime<Utc>,
        cause: &Causality,
    ) {
        let topic = self.state.topic.id;
        let targets: Vec<_> = self
            .state
            .topic
            .routines
            .iter()
            .filter(|r| {
                r.enabled
                    && r.binding.backend == "posthog"
                    && r.event.as_ref().is_some_and(|e| {
                        e.on == on
                            && e.filter
                                .iter()
                                .all(|(k, v)| matches_filter(on, k, fields[k].as_str(), v))
                    })
                    && !cause.stack.contains(&(topic, r.binding.id.clone()))
            })
            .map(|r| r.binding.clone())
            .collect();
        if targets.is_empty() {
            return;
        }
        fields
            .as_object_mut()
            .expect("event fields")
            .retain(|_, value| !value.is_null());
        fields["event"] = json!(on.name());
        let event = Event {
            connection: "topic".into(),
            kind: on.name().into(),
            channel: topic.to_string(),
            external_id: Uuid::new_v4().to_string(),
            thread_hint: None,
            author: "Meep".into(),
            text: on.name().into(),
            at: now,
            attributes: fields,
        };
        for binding in targets {
            let mut path = cause.clone();
            path.stack.push((topic, binding.id.clone()));
            self.record_observation(&binding, &event, Some(path), now);
        }
    }
}

impl Engine {
    /// Register a draft workflow's manual trigger for topic events.
    pub async fn subscribe_routine(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        event: EventSubscription,
    ) -> Result<()> {
        if !event
            .filter
            .keys()
            .all(|k| event.on.fields().contains(&k.as_str()))
        {
            return Err(Error::InvalidBinding("Unknown event filter field".into()));
        }
        self.update(topic, &Default::default(), |s, _| {
            let r = s
                .state
                .topic
                .routines
                .iter_mut()
                .find(|r| r.binding.same_workflow(binding) && binding.backend == "posthog")
                .ok_or_else(|| Error::UnknownRoutine(binding.id.clone()))?;
            r.event = Some(event);
            r.enabled = false;
            Ok(vec![])
        })
        .await?;
        Ok(())
    }

    /// Synchronize event dispatch with confirmed provider activation or pause.
    pub async fn set_event_delivery(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
        enabled: bool,
    ) -> Result<()> {
        self.update(topic, &Default::default(), |s, now| {
            if let Some(r) = s
                .state
                .topic
                .routines
                .iter_mut()
                .find(|r| r.event.is_some() && r.binding.same_workflow(binding))
            {
                r.enabled = enabled;
                if !enabled {
                    let pending: Vec<_> = s
                        .observations
                        .iter()
                        .filter(|o| {
                            o.event_cause.is_some()
                                && o.binding.same_workflow(binding)
                                && o.report.invocation.is_none()
                                && !o.reserved
                                && o.report.outcome.pending()
                        })
                        .map(|o| o.report.key)
                        .collect();
                    for key in pending {
                        s.transition(
                            key,
                            ObservationOutcome::Finished {
                                reason: "Routine paused before dispatch".into(),
                            },
                            now,
                        )?;
                    }
                }
            }
            Ok(vec![])
        })
        .await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn task_column_filters_accept_capitalization_but_other_fields_remain_exact() {
        for key in ["from", "to", "column"] {
            assert!(matches_filter(
                TopicEvent::TaskMoved,
                key,
                Some("done"),
                "Done"
            ));
            assert!(matches_filter(
                TopicEvent::TaskMoved,
                key,
                Some("inProgress"),
                "InProgress"
            ));
            assert!(!matches_filter(
                TopicEvent::TaskMoved,
                key,
                Some("todo"),
                "Done"
            ));
            assert!(!matches_filter(TopicEvent::TaskMoved, key, None, "Done"));
        }
        assert!(!matches_filter(
            TopicEvent::TaskMoved,
            "title",
            Some("done"),
            "Done"
        ));
        assert!(!matches_filter(
            TopicEvent::TaskAdded,
            "title",
            Some("done"),
            "Done"
        ));
    }
}
