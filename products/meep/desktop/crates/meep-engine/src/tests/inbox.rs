use super::*;

#[tokio::test]
async fn a_drafted_reply_waits_for_review_and_always_allows_the_next_reply() -> Result<()> {
    let (e, clock) = world().await?;
    let topic = watching(&e, "Web").await?;
    let mut events = e.subscribe();
    let question = |key| {
        event(
            key,
            "Can we get a sixth slot?",
            json!({"needs_decision":true,"draft":"Let's keep five."}),
        )
    };
    let changes = e.ingest(question("first")).await?;
    for change in changes {
        assert_eq!(
            events.try_recv()?,
            EngineEvent {
                topic,
                revision: e.snapshot(topic)?.revision,
                change: EngineChange::Change(change)
            }
        );
    }
    e.sort_pending(topic).await?;
    let state = e.topic(topic)?;
    let thread = state.threads[0].id;
    assert_eq!(
        e.needs_you()?,
        [Attention {
            topic,
            item: AttentionItem::Thread(thread)
        }]
    );
    e.answer(topic, thread, draft(&state)).await?;
    let task = e.topic(topic)?.tasks[0].clone();
    assert_eq!(task.column, Column::NeedsYou);
    assert_eq!(task.draft.as_deref(), Some("Let's keep five."));
    assert_eq!(
        e.needs_you()?,
        [Attention {
            topic,
            item: AttentionItem::Task(task.id)
        }]
    );
    clock.advance(TimeDelta::seconds(1));
    e.approve(
        topic,
        task.id,
        Some("Let's keep five and review on Friday.".into()),
        true,
    )
    .await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks[0].column, Column::Done);
    assert_eq!(
        state.tasks[0].draft.as_deref(),
        Some("Let's keep five and review on Friday.")
    );
    assert_eq!(state.topic.rules[0].from_task, Some(task.id));
    assert_eq!(
        state.topic.rules[0].effect,
        RuleEffect::Allow(action().kind)
    );
    e.ingest(question("second")).await?;
    e.sort_pending(topic).await?;
    let state = e.topic(topic)?;
    e.answer(topic, state.threads[1].id, draft(&state)).await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks[1].column, Column::Done);
    assert_eq!(
        state.tasks[1].log.last().expect("approval").text,
        "Approved “Send reply”."
    );
    assert!(e.needs_you()?.is_empty());
    assert_eq!(e.digest(topic, clock.now())?.messages, 1);
    Ok(())
}

#[tokio::test]
async fn fan_out_replay_skip_priority_and_thread_followups_are_independent_per_topic() -> Result<()>
{
    let (e, _) = world().await?;
    let a = watching(&e, "A").await?;
    let b = watching(&e, "B").await?;
    e.add_rule(
        a,
        "Skip lunch.",
        RuleEffect::Skip(Matcher {
            ..Default::default()
        }),
    )
    .await?;
    let first = event(
        "1",
        "Lunch update",
        json!({"skip":true,"fact":"Lunch is at noon","needs_decision":true}),
    );
    let (x, y) = tokio::join!(e.ingest(first.clone()), e.ingest(first.clone()));
    assert_ne!(x?.is_empty(), y?.is_empty());
    e.sort_pending(a).await?;
    e.sort_pending(b).await?;
    let follow = Event {
        external_id: "2".into(),
        text: "More lunch news".into(),
        ..first
    };
    e.ingest(follow).await?;
    e.sort_pending(a).await?;
    assert_eq!(e.topic(a)?.threads.len(), 2);
    assert!(
        e.topic(a)?
            .threads
            .iter()
            .all(|t| matches!(t.state, ThreadState::Skipped { rule: Some(_), .. }))
    );
    let state = e.topic(b)?;
    assert_eq!(state.threads.len(), 1);
    assert_eq!(state.threads[0].messages.len(), 2);
    assert!(state.threads[0].unseen);
    e.mark_seen(b, state.threads[0].id).await?;
    assert!(!e.topic(b)?.threads[0].unseen);
    assert!(e.topic(a)?.topic.facts.is_empty());
    Ok(())
}

#[tokio::test]
async fn sort_retries_keep_one_delivery_and_the_person_can_requeue_it() -> Result<()> {
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Once(AtomicUsize);
    #[async_trait::async_trait]
    impl Sorter for Once {
        async fn sort(&self, input: SortInput<'_>) -> anyhow::Result<Sorted> {
            if (1..=7).contains(&self.0.fetch_add(1, Ordering::Relaxed)) {
                anyhow::bail!("temporary sorting failure");
            }
            FixtureSorter.sort(input).await
        }
    }
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = Engine::with_clock(
        Arc::new(crate::MemoryStore::default()),
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(Once(AtomicUsize::new(0))),
        clock.clone(),
    )
    .await?;
    let a = watching(&e, "first").await?;
    let b = watching(&e, "other").await?;
    let (first, second) = if a < b { (a, b) } else { (b, a) };
    let event = event("f", "Review", Value::Null);
    e.ingest(event.clone()).await?;
    assert_eq!(e.topic(first)?.threads[0].state, ThreadState::Sorting);
    assert_eq!(e.topic(second)?.threads[0].state, ThreadState::Sorting);
    e.sort_pending(first).await?;
    e.sort_pending(second).await?;
    for (index, minutes) in [1, 2, 4, 8, 16].into_iter().enumerate() {
        let thread = &e.snapshot(second)?.state.threads[0];
        assert_eq!(
            thread.sort_retry,
            Some(SortRetry {
                failures: index as u32 + 1,
                next_at: clock.now() + TimeDelta::minutes(minutes),
                reason: "Couldn't reach PostHog AI: temporary sorting failure".into()
            })
        );
        e.sort_pending(second).await?;
        assert_eq!(e.topic(second)?.threads[0].state, ThreadState::Sorting);
        clock.advance(TimeDelta::minutes(minutes));
        e.sort_pending(second).await?;
    }
    let thread = &e.topic(second)?.threads[0];
    assert!(thread.sort_retry.is_none());
    let choice = Suggestion::SortAgain {
        message: thread.messages[0].id,
    };
    assert!(
        matches!(&thread.state,ThreadState::NeedsYou{suggestions,..} if suggestions.contains(&choice))
    );
    e.answer(second, thread.id, choice).await?;
    e.sort_pending(second).await?;
    assert_eq!(
        e.snapshot(second)?.state.threads[0]
            .sort_retry
            .as_ref()
            .unwrap()
            .failures,
        1
    );
    clock.advance(TimeDelta::minutes(1));
    e.sort_pending(second).await?;
    assert!(e.snapshot(second)?.state.threads[0].sort_retry.is_none());
    assert_eq!(
        e.topic(second)?.threads[0].state,
        e.topic(first)?.threads[0].state
    );
    for topic in [first, second] {
        assert_eq!(e.topic(topic)?.threads[0].messages.len(), 1);
    }
    assert!(e.ingest(event).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn inter_topic_messages_preserve_sender_and_refuse_past_the_hop_limit() -> Result<()> {
    let (e, _) = world().await?;
    let (a, _) = e.create_topic("Quill", "").await?;
    let (b, _) = e.create_topic("Web", "").await?;
    e.send_to_topic(a, b, "Tooltip is ready", 2).await?;
    e.sort_pending(b).await?;
    let state = e.topic(b)?;
    assert_eq!(
        state.threads[0].messages[0].reply_target(),
        Some(Source::Topic(a))
    );
    assert_eq!(state.threads[0].state, ThreadState::Handled);
    assert!(matches!(
        e.send_to_topic(a, b, "Again", 3).await,
        Err(Error::HopLimit(3))
    ));
    assert_eq!(e.topic(b)?, state);
    Ok(())
}

#[tokio::test]
async fn unhealthy_accounts_appear_with_each_dependent_topic_and_replay_once() -> Result<()> {
    let (e, clock) = world().await?;
    let a = watching(&e, "A").await?;
    let b = watching(&e, "B").await?;
    e.create_topic("Unrelated", "").await?;
    let account = Connection {
        unrouted: 0,
        id: "slack".into(),
        kind: "slack".into(),
        label: "Slack".into(),
        account: "team".into(),
        health: Health::Expired {
            since: clock.now(),
            detail: "Expired".into(),
        },
        grants: vec![a, b],
    };
    e.add_connection(account.clone())?;
    assert_eq!(e.needs_you()?.len(), 2);
    assert!(
        e.needs_you()?
            .iter()
            .all(|n| [a, b].contains(&n.topic)
                && n.item == AttentionItem::Connection(account.clone()))
    );
    assert!(matches!(
        e.reconnect("slack").await,
        Err(Error::UnknownConnection(_))
    ));
    assert_eq!(e.needs_you()?.len(), 2);
    e.attach_connector(Arc::new(FixtureConnector::new(
        "slack",
        vec![event("1", "New note", Value::Null)],
    )));
    let mut events = e.subscribe();
    e.reconnect("slack").await?;
    assert!(e.needs_you()?.is_empty());
    assert_eq!(
        std::iter::from_fn(|| events.try_recv().ok())
            .filter(|ev| matches!(
                ev.change,
                EngineChange::ConnectionHealth {
                    health: Health::Ok { .. },
                    ..
                }
            ))
            .count(),
        2
    );
    assert!(e.reconnect("slack").await?.is_empty());
    for t in [a, b] {
        assert_eq!(e.topic(t)?.threads[0].messages.len(), 1);
    }
    Ok(())
}

#[tokio::test]
async fn healthy_connectors_feed_the_inbox_while_expired_accounts_wait_for_reconnect() -> Result<()>
{
    let (e, clock) = world().await?;
    let topic = watching(&e, "Rail").await?;
    let since = clock.now();
    e.add_connection(Connection {
        unrouted: 0,
        id: "slack".into(),
        kind: "slack".into(),
        label: "Slack".into(),
        account: "team".into(),
        health: Health::Ok { checked_at: since },
        grants: vec![topic],
    })?;
    e.attach_connector(Arc::new(FixtureConnector::new(
        "slack",
        vec![event(
            "fresh",
            "Rail notes",
            json!({"fact":"Keep five slots"}),
        )],
    )));
    clock.advance(TimeDelta::seconds(30));
    e.tick().await?;
    assert_eq!(e.topic(topic)?.topic.facts[0].text, "Keep five slots");
    struct Offline;
    #[async_trait::async_trait]
    impl Connector for Offline {
        fn name(&self) -> &str {
            "slack"
        }
        async fn poll(&self, _: DateTime<Utc>) -> meep_ingest::Result<Vec<Event>> {
            Err(meep_ingest::Error::Connector("Offline".into()))
        }
    }
    e.attach_connector(Arc::new(Offline));
    clock.advance(TimeDelta::seconds(30));
    assert!(e.tick().await.is_err());
    assert!(
        matches!(&e.connections()?[0].health,Health::Failing{since:t,detail} if *t==since+TimeDelta::seconds(30) && detail=="Offline")
    );
    assert!(matches!(
        &e.needs_you()?[0].item,
        AttentionItem::Connection(_)
    ));
    Ok(())
}

#[tokio::test]
async fn removing_a_skip_rule_makes_the_next_decision_independent() -> Result<()> {
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = Engine::with_clock(
        Arc::new(crate::MemoryStore::default()),
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        clock,
    )
    .await?;
    let t = watching(&e, "Rail").await?;
    e.add_rule(
        t,
        "Skip Mia",
        RuleEffect::Skip(Matcher {
            ..Default::default()
        }),
    )
    .await?;
    e.ingest(event(
        "old",
        "Please SIGN OFF",
        json!({"skip":true,"needs_decision":true}),
    ))
    .await?;
    e.sort_pending(t).await?;
    let state = e.topic(t)?;
    assert!(matches!(
        state.threads[0].state,
        ThreadState::Skipped { .. }
    ));
    e.remove_rule(t, state.topic.rules[0].id).await?;
    e.ingest(event(
        "new",
        "Please SIGN OFF",
        json!({"skip":true,"needs_decision":true}),
    ))
    .await?;
    e.sort_pending(t).await?;
    assert!(matches!(
        e.topic(t)?.threads[1].state,
        ThreadState::NeedsYou { .. }
    ));
    Ok(())
}

#[tokio::test]
async fn a_pending_chat_has_a_durable_receipt_before_the_agent_answers_and_releases_the_command_queue()
-> Result<()> {
    use tokio::sync::Notify;
    struct WaitingAgent {
        started: Notify,
        release: Notify,
    }
    #[async_trait::async_trait]
    impl Agent for WaitingAgent {
        async fn start(&self, run: AgentRun) -> Result<RunHandle> {
            assert_eq!(run.task.assignment, Some(InboxAssignment::ChatAnswer));
            self.started.notify_one();
            self.release.notified().await;
            Ok(RunHandle(Value::Null))
        }
        async fn poll(&self, _: &RunHandle) -> Result<RunState> {
            Ok(RunState::Done {
                result: "Five.".into(),
            })
        }
    }
    let agent = Arc::new(WaitingAgent {
        started: Notify::new(),
        release: Notify::new(),
    });
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        agent.clone(),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let (t, _) = e.create_topic("Rail", "").await?;
    let request = envelope(
        t,
        Command::Chat {
            message_id: id(),
            text: "How many?".into(),
            task_id: id(),
            queue: false,
        },
    );
    let caller = e.clone();
    assert_eq!(e.apply(request.clone()).await?.revision, 2);
    let pending = tokio::spawn(async move { caller.tick().await });
    tokio::time::timeout(std::time::Duration::from_secs(3), agent.started.notified()).await?;
    let claimed = e.snapshot(t)?;
    assert_eq!(claimed.state.tasks[0].column, Column::InProgress);
    assert_eq!(
        claimed.state.threads[0].outcomes,
        [Outcome::Task(claimed.state.tasks[0].id)]
    );
    assert_eq!(
        tokio::time::timeout(std::time::Duration::from_secs(3), e.apply(request)).await??,
        Applied {
            revision: claimed.revision,
            changes: vec![]
        }
    );
    e.set_mission(t, "Ship five").await?;
    agent.release.notify_one();
    pending.await??;
    e.tick_topic(t).await?;
    assert_eq!(e.topic(t)?.tasks.len(), 1);
    assert_eq!(e.topic(t)?.threads[0].summary, "Five.");
    Ok(())
}

#[tokio::test]
async fn an_engine_reply_delivers_to_its_source_once_without_a_server_wrapper() -> Result<()> {
    let (e, _) = world().await?;
    let (a, _) = e.create_topic("a", "").await?;
    let (b, _) = e.create_topic("b", "").await?;
    e.send_to_topic(a, b, "question", 1).await?;
    let reply = envelope(
        b,
        Command::Reply {
            thread: e.topic(b)?.threads[0].id,
            text: "answer".into(),
        },
    );
    for _ in 0..2 {
        e.apply(reply.clone()).await?;
        e.tick().await?;
    }
    let state = e.topic(a)?;
    assert_eq!(state.threads.len(), 1);
    assert_eq!(state.threads[0].messages[0].text, "answer");
    Ok(())
}

#[tokio::test]
async fn leaving_a_thread_never_redispatches_an_earlier_approved_draft() -> Result<()> {
    let (engine, _) = world().await?;
    let topic = watching(&engine, "Triage").await?;
    let question = |key| event(key, "Can we ship?", json!({"needs_decision": true}));
    engine.ingest(question("first")).await?;
    engine.sort_pending(topic).await?;
    let state = engine.topic(topic)?;
    engine
        .answer(topic, state.threads[0].id, draft(&state))
        .await?;
    let task = engine.topic(topic)?.tasks[0].id;
    engine.approve(topic, task, None, false).await?;
    engine.tick().await?;
    let approved = engine.topic(topic)?.tasks[0].clone();
    engine.ingest(question("second")).await?;
    engine.sort_pending(topic).await?;
    engine
        .apply(envelope(
            topic,
            Command::Answer {
                thread: engine.topic(topic)?.threads[1].id,
                expected_review: None,
                suggestion: Suggestion::Leave,
                task_id: task,
            },
        ))
        .await?;
    engine.tick().await?;
    assert_eq!(engine.topic(topic)?.tasks[0], approved);
    Ok(())
}

#[tokio::test]
async fn a_failed_reply_records_one_receipt_on_its_report_across_replay() -> Result<()> {
    let (e, _) = world().await?;
    let topic = watching(&e, "Delivery").await?;
    e.ingest(event("shipment", "Where is the shipment?", json!({})))
        .await?;
    e.sort_pending(topic).await?;
    let thread = e.topic(topic)?.threads[0].id;
    let reply = envelope(
        topic,
        Command::Reply {
            thread,
            text: "It is at the dock.".into(),
        },
    );
    e.apply(reply.clone()).await?;
    e.apply(reply).await?;
    e.tick_topic(topic).await?;
    let state = e.topic(topic)?;
    assert!(state.tasks.is_empty());
    let receipts: Vec<_> = state
        .activity
        .iter()
        .filter(|a| a.subject == Ref::Thread(thread) && a.delivery.is_some())
        .collect();
    assert_eq!(receipts.len(), 1);
    assert!(receipts[0].text.contains("Delivery failed"));
    Ok(())
}

#[tokio::test]
async fn a_restored_chat_task_delivers_one_answer_to_its_original_thread() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let mut agent = FixtureAgent::default();
    agent.script(
        "When is the review?",
        Script {
            delay: TimeDelta::zero(),
            progress: "Looking up the review".into(),
            outcome: RunState::Findings {
                result: "Friday.".into(),
                follow_ups: vec!["Schedule the review".into()],
            },
        },
    );
    let open = || {
        Engine::with_clock(
            Arc::new(SqliteStore::open(dir.path()).unwrap()),
            limits(),
            Arc::new(agent.clone()),
            Arc::new(FixtureSorter),
            Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
        )
    };
    let engine = open().await?;
    let (topic, _) = engine.create_topic("Reviews", "").await?;
    let message: MessageId = id();
    let task: TaskId = id();
    let request = envelope(
        topic,
        Command::Chat {
            message_id: message,
            task_id: task,
            text: "When is the review?".into(),
            queue: false,
        },
    );
    engine.apply(request.clone()).await?;
    engine.tick_topic(topic).await?;
    assert_eq!(engine.topic(topic)?.tasks[0].column, Column::InProgress);
    drop(engine);
    let engine = open().await?;
    assert!(engine.apply(request.clone()).await?.changes.is_empty());
    engine.tick_topic(topic).await?;
    assert!(engine.apply(request).await?.changes.is_empty());
    engine.tick_topic(topic).await?;
    let state = engine.topic(topic)?;
    assert_eq!(state.tasks.len(), 1);
    assert_eq!(state.tasks[0].id, task);
    assert_eq!(state.tasks[0].result.as_deref(), Some("Friday."));
    assert_eq!(state.threads.len(), 1);
    assert_eq!(state.threads[0].id, ThreadId(message.0));
    assert_eq!(
        state.threads[0].outcomes,
        [
            Outcome::Task(task),
            Outcome::Reply {
                to: Source::User,
                text: "Friday.".into()
            }
        ]
    );
    Ok(())
}

#[tokio::test]
async fn queued_tasks_wait_for_a_start_command_or_a_move_to_in_progress() -> Result<()> {
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        Arc::new(scripted()),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let topic = watching(&e, "Assignments").await?;
    let first = id();
    let second = id();
    for task in [first, second] {
        e.command(
            topic,
            Command::AddConfiguredTask {
                id: task,
                title: "Draft".into(),
                start: false,
                model: Some("fixture-model".into()),
                reasoning_effort: Some("high".into()),
                instructions: Some("Check the draft".into()),
                billing: None,
                untitled: false,
            },
        )
        .await?;
    }
    e.tick_topic(topic).await?;
    assert!(
        e.topic(topic)?
            .tasks
            .iter()
            .all(|t| t.queued && t.column == Column::Todo)
    );
    assert!(e.active_runs(topic)?.is_empty());
    e.command(topic, Command::StartTask { task: first }).await?;
    e.move_task(topic, second, Column::InProgress).await?;
    e.tick_topic(topic).await?;
    assert_eq!(e.active_runs(topic)?.len(), 2);
    assert!(e.topic(topic)?.tasks.iter().all(|t| !t.queued
        && t.column == Column::InProgress
        && t.model.as_deref() == Some("fixture-model")));
    Ok(())
}

#[tokio::test]
async fn the_topic_agent_keeps_one_conversation_and_picks_up_its_own_tasks() -> Result<()> {
    let mut agent = FixtureAgent::default();
    agent.script(
        "What is our mission?",
        Script {
            delay: TimeDelta::zero(),
            progress: "Reading".into(),
            outcome: RunState::Done {
                result: "Keep five items visible".into(),
            },
        },
    );
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        Arc::new(agent),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let t = watching(&e, "Design").await?;
    e.chat(t, "What is our mission?").await?;
    e.tick_topic(t).await?;
    e.tick_topic(t).await?;
    // The next message is a turn in the same session, not a new task.
    e.chat(t, "And who owns the rail?").await?;
    e.tick_topic(t).await?;
    let state = e.topic(t)?;
    assert_eq!(state.tasks.len(), 1, "one session for the topic");
    let session = state.tasks[0].id;
    assert_eq!(state.threads[1].outcomes[0], Outcome::Task(session));
    assert!(state.threads[1].outcomes.contains(&Outcome::Reply {
        to: Source::User,
        text: "Re: And who owns the rail?".into()
    }));
    // A task the agent planned for itself comes back to it as a turn when it is idle.
    let later = e
        .plan_task(
            t,
            "Check opens after the deploy",
            "Compare with last week.",
            InboxAssignment::Session,
        )
        .await?;
    e.tick_topic(t).await?;
    let state = e.topic(t)?;
    assert_eq!(state.tasks.len(), 2, "no extra run for its own task");
    // The agent got it in its conversation, under a line saying what it picked up.
    let picked = state.threads.last().unwrap();
    assert!(
        picked.messages[0]
            .text
            .contains("Check opens after the deploy")
    );
    assert!(picked.outcomes.iter().any(|o| matches!(o,
        Outcome::Reply { text, .. } if text.contains("Waiting for you") && text.contains(&later.to_string()))));
    // A message written while it works reaches it at once and the person's words lead.
    e.plan_task(t, "Draft the weekly summary", "", InboxAssignment::Session)
        .await?;
    e.chat(t, "Ignore that, what changed today?").await?;
    e.tick_topic(t).await?;
    let state = e.topic(t)?;
    let reply = state
        .threads
        .iter()
        .rev()
        .find_map(|th| {
            th.outcomes.iter().find_map(|o| match o {
                Outcome::Reply { text, .. } => Some(text.clone()),
                _ => None,
            })
        })
        .unwrap();
    assert!(
        reply.starts_with("Re: Ignore that, what changed today?"),
        "{reply}"
    );
    assert!(reply.contains("Draft the weekly summary"));
    assert_eq!(state.tasks.iter().filter(|x| x.is_session()).count(), 1);
    Ok(())
}

#[tokio::test]
async fn the_conversation_asks_before_acting_and_carries_out_what_was_approved() -> Result<()> {
    let mut agent = FixtureAgent::default();
    agent.script(
        "Roll the winner out",
        Script {
            delay: TimeDelta::minutes(5),
            progress: "Checking the flag".into(),
            outcome: RunState::Done {
                result: "Asked for your OK".into(),
            },
        },
    );
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        Arc::new(agent),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let t = watching(&e, "Sharing").await?;
    e.chat(t, "Roll the winner out").await?;
    e.tick_topic(t).await?;
    let (session, run) = e.task_runs(t)?.into_iter().next().expect("the turn runs");
    // A change outside Meep, proposed from the conversation, waits as its prompt.
    e.propose_action(t, &run, None, action(), None).await?;
    let task = e
        .topic(t)?
        .tasks
        .into_iter()
        .find(|t| t.id == session)
        .unwrap();
    assert_eq!(task.column, Column::NeedsYou);
    assert_eq!(task.action, Some(action()));
    // Approving tells the agent to carry it out; nothing runs it from outside.
    e.approve(t, session, None, false).await?;
    let notes = e.slot(t)?.saved.read().inbox.texts().join("\n");
    assert!(
        notes.contains("The person approved; carry it out now"),
        "{notes}"
    );
    assert!(notes.contains(&action().label), "{notes}");
    assert!(
        e.topic(t)?
            .tasks
            .iter()
            .find(|t| t.id == session)
            .unwrap()
            .action
            .is_none()
    );
    Ok(())
}
