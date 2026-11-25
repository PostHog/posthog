use super::*;

#[tokio::test]
async fn workers_poll_progress_revise_and_obey_ask_allow_and_refuse() -> Result<()> {
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = Engine::with_clock(
        Arc::new(crate::MemoryStore::default()),
        limits(),
        Arc::new(scripted()),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let (t, _) = e.create_topic("Web", "").await?;
    e.add_task(t, "Draft").await?;
    e.apply(envelope(t, Command::ArchiveTopic)).await?;
    e.tick().await?;
    assert_eq!(e.topic(t)?.usage.last_hour(clock.now()), 0);
    e.apply(envelope(t, Command::UnarchiveTopic)).await?;
    e.tick().await?;
    e.tick().await?;
    let task = e.topic(t)?.tasks[0].clone();
    let usage = e.topic(t)?.usage;
    assert_eq!(usage.last_hour(clock.now()), 1);
    assert_eq!(usage.last_hour(clock.now() + TimeDelta::hours(1)), 0);
    assert_eq!(usage.hourly_cap, limits().max_runs_per_hour);
    assert_eq!(task.worker.as_deref(), Some("Reading the thread"));
    e.tick().await?;
    assert_eq!(e.topic(t)?.tasks[0], task);
    clock.advance(TimeDelta::seconds(5));
    e.tick().await?;
    assert_eq!(e.topic(t)?.tasks[0].column, Column::NeedsYou);
    e.send_back(t, task.id, "Mention Shortcuts").await?;
    let active = e.topic(t)?.tasks[0].clone();
    assert_eq!(active.column, Column::InProgress);
    assert!(
        active
            .log
            .last()
            .expect("revision")
            .text
            .contains("Mention Shortcuts")
    );
    e.tick().await?;
    clock.advance(TimeDelta::seconds(5));
    e.tick().await?;
    e.approve(t, task.id, None, true).await?;
    let mut allowed = e.subscribe();
    e.add_task(t, "Draft").await?;
    e.tick().await?;
    clock.advance(TimeDelta::seconds(5));
    e.tick().await?;
    assert_eq!(e.topic(t)?.tasks[1].column, Column::Done);
    assert!(
        !std::iter::from_fn(|| allowed.try_recv().ok()).any(|e| matches!(
            e.change,
            EngineChange::Change(Change {
                kind: ChangeKind::TaskMoved {
                    to: Column::NeedsYou,
                    ..
                },
                ..
            })
        ))
    );
    e.add_rule(t, "Never send.", RuleEffect::Deny(action().kind))
        .await?;
    e.add_task(t, "Draft").await?;
    e.tick().await?;
    let state = e.topic(t)?;
    assert!(
        state.tasks[1]
            .result
            .as_ref()
            .is_some_and(|result| result.contains("rule blocks this action"))
    );
    assert_eq!(state.tasks.len(), 3);
    assert_eq!(state.tasks[1].column, Column::NeedsYou);
    clock.advance(TimeDelta::seconds(5));
    e.tick().await?;
    let refused = e.topic(t)?.tasks[2].clone();
    assert_eq!(refused.column, Column::InProgress);
    assert!(refused.log.last().expect("reason").text.contains("Refused"));
    e.tick().await?;
    assert_eq!(e.topic(t)?.tasks[2], refused);
    Ok(())
}

#[tokio::test]
async fn rate_limits_survive_reopen_and_a_terminal_failure_requires_an_explicit_retry() -> Result<()>
{
    let dir = tempfile::tempdir()?;
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let mut agent = FixtureAgent::default();
    agent.script(
        "Inspect",
        Script {
            delay: TimeDelta::zero(),
            progress: "Checking".into(),
            outcome: RunState::Failed {
                error: "Missing input".into(),
            },
        },
    );
    let agent = Arc::new(agent);
    let open = || async {
        Engine::with_clock(
            Arc::new(SqliteStore::open(dir.path())?),
            Limits {
                max_runs_per_hour: 1,
                ..limits()
            },
            agent.clone(),
            Arc::new(FixtureSorter),
            clock.clone(),
        )
        .await
    };
    let e = open().await?;
    let (t, _) = e.create_topic("Rail", "").await?;
    e.add_task(t, "Inspect").await?;
    e.add_task(t, "Inspect").await?;
    e.tick().await?;
    e.tick().await?;
    let failed = e.topic(t)?.tasks[0].clone();
    assert_eq!(failed.result.as_deref(), Some("Failed: Missing input"));
    assert_eq!(e.topic(t)?.needs_you().tasks, [failed.id]);
    drop(e);
    let e = open().await?;
    clock.advance(TimeDelta::minutes(59));
    e.tick().await?;
    assert_eq!(e.topic(t)?.tasks[1].column, Column::Todo);
    clock.advance(TimeDelta::minutes(1));
    e.tick().await?;
    assert_eq!(e.topic(t)?.tasks[0], failed);
    assert_eq!(e.topic(t)?.tasks[1].column, Column::InProgress);
    e.move_task(t, failed.id, Column::Todo).await?;
    assert_eq!(e.topic(t)?.tasks[0].column, Column::Todo);
    Ok(())
}

#[tokio::test]
async fn an_automatic_worker_completes_work_without_a_host_tick() -> Result<()> {
    let mut agent = FixtureAgent::default();
    agent.script(
        "Count",
        Script {
            delay: TimeDelta::zero(),
            progress: "Counting".into(),
            outcome: RunState::Done {
                result: "Five".into(),
            },
        },
    );
    let e = Engine::new(
        Arc::new(crate::MemoryStore::default()),
        limits(),
        Arc::new(agent),
        Arc::new(FixtureSorter),
    )
    .await?;
    let (t, _) = e.create_topic("Rail", "").await?;
    let mut events = e.subscribe();
    e.add_task(t, "Count").await?;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let event = events.recv().await?;
            if matches!(
                event.change,
                EngineChange::Change(Change {
                    kind: ChangeKind::TaskMoved {
                        to: Column::Done,
                        ..
                    },
                    ..
                })
            ) {
                break;
            }
        }
        Ok::<_, tokio::sync::broadcast::error::RecvError>(())
    })
    .await??;
    assert_eq!(e.topic(t)?.tasks[0].result.as_deref(), Some("Five"));
    Ok(())
}

#[tokio::test]
async fn a_blocked_command_orders_its_topic_without_blocking_another() -> Result<()> {
    use std::time::Duration;
    let (e, _) = world().await?;
    let (a, _) = e.create_topic("A", "").await?;
    let (b, _) = e.create_topic("B", "").await?;
    let slot = e.slot(a)?;
    let blocked = slot.edit.lock().await;
    let mut first = Box::pin(e.set_mission(a, "first"));
    let mut second = Box::pin(e.set_mission(a, "second"));
    for future in [&mut first, &mut second] {
        assert!(
            tokio::time::timeout(Duration::from_millis(10), future)
                .await
                .is_err()
        );
    }
    tokio::time::timeout(Duration::from_millis(300), e.set_mission(b, "independent")).await??;
    drop(blocked);
    first.await?;
    second.await?;
    assert_eq!(e.topic(a)?.topic.mission, "second");
    Ok(())
}

#[tokio::test]
async fn eight_running_tasks_can_poll_together_while_the_ninth_waits() -> Result<()> {
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct AgentGate {
        active: AtomicUsize,
        entered: tokio::sync::Notify,
        release: tokio::sync::Semaphore,
    }
    #[async_trait::async_trait]
    impl Agent for AgentGate {
        async fn start(&self, _: AgentRun) -> Result<RunHandle> {
            Ok(RunHandle(Value::Null))
        }
        async fn poll(&self, _: &RunHandle) -> Result<RunState> {
            if self.active.fetch_add(1, Ordering::SeqCst) == 7 {
                self.entered.notify_one();
            }
            self.release.acquire().await?.forget();
            self.active.fetch_sub(1, Ordering::SeqCst);
            Ok(RunState::Done {
                result: "ok".into(),
            })
        }
    }
    let agent = Arc::new(AgentGate {
        active: AtomicUsize::new(0),
        entered: Default::default(),
        release: tokio::sync::Semaphore::new(0),
    });
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        agent.clone(),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let (topic, _) = e.create_topic("Poll", "").await?;
    for _ in 0..9 {
        e.add_task(topic, "work").await?;
    }
    e.tick_topic(topic).await?;
    let tick = e.tick_topic(topic);
    tokio::pin!(tick);
    tokio::select! {
        r = &mut tick => panic!("polls completed before release: {r:?}"),
        r = tokio::time::timeout(std::time::Duration::from_secs(5), agent.entered.notified()) => r?,
    }
    assert_eq!(agent.active.load(Ordering::SeqCst), 8);
    agent.release.add_permits(9);
    tick.await?;
    assert!(
        e.topic(topic)?
            .tasks
            .iter()
            .all(|t| t.column == Column::Done)
    );
    Ok(())
}

#[tokio::test(start_paused = true)]
async fn idle_topics_sleep_until_a_change() -> Result<()> {
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct CountingClock(AtomicUsize);
    impl Clock for CountingClock {
        fn now(&self) -> DateTime<Utc> {
            self.0.fetch_add(1, Ordering::Relaxed);
            Utc::now()
        }
        fn automatic(&self) -> bool {
            false
        }
    }
    let clock = Arc::new(CountingClock(AtomicUsize::new(0)));
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let (topic, _) = e.create_topic("Idle", "").await?;
    let driver = e.drive_topic(topic);
    tokio::pin!(driver);
    assert!(futures_util::poll!(&mut driver).is_pending());
    let before = clock.0.load(Ordering::Relaxed);
    tokio::time::advance(std::time::Duration::from_secs(60)).await;
    assert!(futures_util::poll!(&mut driver).is_pending());
    assert_eq!(clock.0.load(Ordering::Relaxed), before);
    e.wake_topic(topic);
    assert!(futures_util::poll!(&mut driver).is_pending());
    assert!(clock.0.load(Ordering::Relaxed) > before);
    Ok(())
}

#[tokio::test]
async fn an_approved_agent_proposal_dispatches_once_with_the_edited_draft() -> Result<()> {
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        Arc::new(scripted()),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let (t, _) = e.create_topic("A", "").await?;
    e.add_task(t, "Draft").await?;
    e.tick().await?;
    let task = e.topic(t)?.tasks[0].id;
    let run = e.active_runs(t)?.pop().context("started run")?;
    let action = Action {
        kind: ActionKind("reply".into()),
        label: "Send reply".into(),
        done_label: "Sent reply".into(),
        payload: json!({}),
        depends_on_facts: Some(vec![]),
    };
    assert!(
        e.propose_action(t, &run, Some(id()), action.clone(), None)
            .await
            .is_err()
    );
    e.propose_action(t, &run, Some(task), action, Some("original".into()))
        .await?;
    assert_eq!(e.topic(t)?.tasks[0].column, Column::NeedsYou);
    let approved = envelope(
        t,
        Command::Approve {
            task,
            expected_review: None,
            edited_draft: Some("edited".into()),
            always: false,
            rule_id: id(),
        },
    );
    e.apply(approved.clone()).await?;
    e.tick().await?;
    e.apply(approved).await?;
    e.tick().await?;
    clock.advance(TimeDelta::seconds(5));
    e.tick().await?;
    let task = &e.topic(t)?.tasks[0];
    assert_eq!(task.result.as_deref(), Some("Executed Send reply: edited"));
    assert_eq!(
        task.log
            .iter()
            .filter(|entry| entry.text == "Executed Send reply: edited")
            .count(),
        1
    );
    Ok(())
}

#[tokio::test]
async fn a_cancelled_start_is_observable_and_never_started_twice() -> Result<()> {
    struct PendingStart(tokio::sync::Notify);
    #[async_trait::async_trait]
    impl Agent for PendingStart {
        async fn start(&self, _: AgentRun) -> Result<RunHandle> {
            self.0.notify_one();
            std::future::pending().await
        }
        async fn poll(&self, _: &RunHandle) -> Result<RunState> {
            unreachable!()
        }
    }
    let provider = Arc::new(PendingStart(Default::default()));
    let (store, clock) = (
        Arc::new(MemoryStore::default()),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    );
    let e = Engine::with_clock(
        store,
        limits(),
        provider.clone(),
        Arc::new(FixtureSorter),
        clock,
    )
    .await?;
    let (topic, _) = e.create_topic("Start", "").await?;
    e.add_task(topic, "Start once").await?;
    tokio::select! { _ = provider.0.notified() => {}, result=e.tick_topic(topic) => panic!("{result:?}") }
    e.tick_topic(topic).await?;
    let state = e.topic(topic)?;
    let task = &state.tasks[0];
    assert_eq!(state.needs_you().tasks, [task.id]);
    assert!(task.result.as_ref().is_some_and(|s| s.contains("unknown")));
    e.tick_topic(topic).await?;
    assert_eq!(e.topic(topic)?.tasks, state.tasks);
    Ok(())
}

#[tokio::test]
async fn dropping_last_host_releases_a_worker_waiting_on_a_provider() -> Result<()> {
    struct Paused(tokio::sync::Notify);
    #[async_trait::async_trait]
    impl Agent for Paused {
        async fn start(&self, _: AgentRun) -> Result<RunHandle> {
            self.0.notify_one();
            std::future::pending().await
        }
        async fn poll(&self, _: &RunHandle) -> Result<RunState> {
            unreachable!()
        }
    }
    let agent = Arc::new(Paused(Default::default()));
    let e = Engine::new(
        Arc::new(MemoryStore::default()),
        limits(),
        agent.clone(),
        Arc::new(FixtureSorter),
    )
    .await?;
    let weak = Arc::downgrade(&e.0);
    let (topic, _) = e.create_topic("Wait", "").await?;
    e.add_task(topic, "Wait").await?;
    agent.0.notified().await;
    drop(e);
    tokio::time::timeout(std::time::Duration::from_millis(300), async {
        while weak.strong_count() != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    Ok(())
}

#[tokio::test]
async fn a_blocked_first_watcher_does_not_starve_the_thirty_third_or_reorder_its_messages()
-> Result<()> {
    let (e, _) = world().await?;
    for _ in 0..33 {
        watching(&e, "Watch").await?;
    }
    let ids = e.topic_ids();
    let slot = e.slot(ids[0])?;
    let lock = slot.edit.lock().await;
    let mut events = e.subscribe();
    let first = e.ingest(event("one", "one", Value::Null));
    tokio::pin!(first);
    tokio::select! {
        v = &mut first => panic!("unexpected result {v:?}"),
        r = tokio::time::timeout(std::time::Duration::from_millis(500), async {
            loop { if events.recv().await?.topic == ids[32] { return anyhow::Ok(()); } }
        }) => r??,
    }
    drop(lock);
    let second = e.ingest(event("two", "two", Value::Null));
    let (a, b) = tokio::join!(first, second);
    a?;
    b?;
    for id in ids {
        assert_eq!(
            e.topic(id)?
                .threads
                .iter()
                .map(|t| t.messages[0].text.clone())
                .collect::<Vec<_>>(),
            ["one", "two"]
        );
    }
    Ok(())
}

#[tokio::test]
async fn unrelated_edits_do_not_reset_a_long_running_tasks_poll_deadline() -> Result<()> {
    struct Counting(tokio::sync::mpsc::UnboundedSender<tokio::time::Instant>);
    #[async_trait::async_trait]
    impl Agent for Counting {
        async fn start(&self, _: AgentRun) -> Result<RunHandle> {
            Ok(RunHandle(Value::Null))
        }
        async fn poll(&self, _: &RunHandle) -> Result<RunState> {
            self.0.send(tokio::time::Instant::now())?;
            Ok(RunState::Running {
                progress: "Still working".into(),
            })
        }
    }
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
    let e = Engine::new(
        Arc::new(MemoryStore::default()),
        limits(),
        Arc::new(Counting(tx)),
        Arc::new(FixtureSorter),
    )
    .await?;
    let (topic, _) = e.create_topic("Polling", "").await?;
    e.add_task(topic, "work").await?;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let first = rx.recv().await.context("poll one")?;
        let second = rx.recv().await.context("poll two")?;
        e.set_mission(topic, "change during backoff").await?;
        let third = rx.recv().await.context("poll three")?;
        assert!(second - first >= std::time::Duration::from_millis(250));
        assert!(third - second >= std::time::Duration::from_millis(500));
        anyhow::Ok(())
    })
    .await??;
    Ok(())
}

#[tokio::test]
async fn a_delayed_approval_receipt_preserves_a_reopened_task() -> Result<()> {
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        Arc::new(scripted()),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let (topic, _) = e.create_topic("Review", "").await?;
    e.add_task(topic, "Draft").await?;
    e.tick().await?;
    clock.advance(TimeDelta::seconds(5));
    e.tick().await?;
    let task = e.topic(topic)?.tasks[0].id;
    e.approve(topic, task, None, false).await?;
    e.move_task(topic, task, Column::Todo).await?;
    let reopened = e.topic(topic)?.tasks[0].clone();
    e.deliver_effects(topic).await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks[0], reopened);
    assert!(
        state
            .activity
            .iter()
            .any(|a| a.subject == Ref::Task(task) && a.text == "Approved action dispatched.")
    );
    e.tick().await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks[0].column, Column::InProgress);
    assert!(
        state
            .activity
            .iter()
            .any(|a| a.subject == Ref::Task(task) && a.text == "Executed Send reply: Five items")
    );
    assert_ne!(
        state.tasks[0].result.as_deref(),
        Some("Executed Send reply: Five items")
    );
    Ok(())
}

#[tokio::test]
async fn a_dispatched_action_reports_failure_after_a_board_move_and_restart() -> Result<()> {
    struct Provider(std::sync::atomic::AtomicUsize);
    #[async_trait::async_trait]
    impl Agent for Provider {
        async fn start(&self, _: AgentRun) -> Result<RunHandle> {
            Ok(RunHandle(json!("investigation")))
        }

        async fn poll(&self, handle: &RunHandle) -> Result<RunState> {
            if handle.0 == "delivery" {
                return Ok(RunState::Failed {
                    error: "Recipient refused the message".into(),
                });
            }
            Ok(RunState::Submitted {
                action: action(),
                result: "Ready".into(),
                draft: None,
            })
        }

        async fn execute(&self, _: &RunHandle, _: &Task, _: Uuid) -> Result<RunHandle> {
            self.0.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            Ok(RunHandle(json!("delivery")))
        }
    }

    let dir = tempfile::tempdir()?;
    let provider = Arc::new(Provider(Default::default()));
    let open = || async {
        Engine::with_clock(
            Arc::new(SqliteStore::open(dir.path())?),
            limits(),
            provider.clone(),
            Arc::new(FixtureSorter),
            Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
        )
        .await
    };
    let e = open().await?;
    let (topic, _) = e.create_topic("Review", "").await?;
    e.add_task(topic, "Draft").await?;
    let task = e.topic(topic)?.tasks[0].id;
    e.tick().await?;
    e.tick().await?;
    e.approve(topic, task, None, false).await?;
    e.deliver_effects(topic).await?;
    e.shutdown().await;
    drop(e);

    let e = open().await?;
    e.move_task(topic, task, Column::NeedsYou).await?;
    let reopened = e.topic(topic)?.tasks[0].clone();
    e.shutdown().await;
    drop(e);

    let e = open().await?;
    assert_eq!(e.active_runs(topic)?, vec![RunHandle(json!("delivery"))]);
    e.tick().await?;
    e.tick().await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks[0], reopened);
    assert_eq!(state.tasks.len(), 1);
    assert!(
        state
            .activity
            .iter()
            .any(|a| a.subject == Ref::Task(task) && a.text.contains("Recipient refused"))
    );
    assert!(e.active_runs(topic)?.is_empty());
    assert_eq!(provider.0.load(std::sync::atomic::Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn leaving_in_progress_or_timing_out_cancels_the_provider_run_once() -> Result<()> {
    #[derive(Default)]
    struct Provider(parking_lot::Mutex<Vec<RunHandle>>);
    #[async_trait::async_trait]
    impl Agent for Provider {
        async fn start(&self, run: AgentRun) -> Result<RunHandle> {
            Ok(RunHandle(json!(run.task.id)))
        }
        async fn poll(&self, _: &RunHandle) -> Result<RunState> {
            Ok(RunState::Running {
                progress: "Investigating".into(),
            })
        }
        async fn cancel(&self, h: &RunHandle) -> Result<()> {
            self.0.lock().push(h.clone());
            Ok(())
        }
    }
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let agent = Arc::new(Provider::default());
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        limits(),
        agent.clone(),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let (topic, _) = e.create_topic("Cancellation", "").await?;
    for name in ["move", "cancel", "timeout"] {
        e.add_task(topic, name).await?;
    }
    e.tick().await?;
    let tasks = e.topic(topic)?.tasks;
    e.apply(envelope(
        topic,
        Command::MoveTask {
            task: tasks[0].id,
            column: Column::Todo,
        },
    ))
    .await?;
    e.apply(envelope(topic, Command::CancelRun { task: tasks[1].id }))
        .await?;
    e.tick().await?;
    assert_eq!(agent.0.lock().len(), 2);
    clock.advance(TimeDelta::minutes(60));
    e.tick().await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks[2].column, Column::NeedsYou);
    assert!(
        state.tasks[2]
            .result
            .as_deref()
            .unwrap()
            .contains("No progress")
    );
    e.tick().await?;
    assert_eq!(
        *agent.0.lock(),
        tasks
            .iter()
            .map(|t| RunHandle(json!(t.id)))
            .collect::<Vec<_>>()
    );
    Ok(())
}

#[tokio::test]
async fn an_untitled_task_takes_the_name_its_provider_gives_it() -> Result<()> {
    let e = Engine::new(
        Arc::new(crate::MemoryStore::default()),
        limits(),
        Arc::new(scripted()),
        Arc::new(FixtureSorter),
    )
    .await?;
    let (t, _) = e.create_topic("Web", "").await?;
    e.apply(envelope(
        t,
        Command::AddConfiguredTask {
            start: true,
            id: TaskId(Uuid::new_v4()),
            title: "Draft".into(),
            untitled: true,
            model: None,
            reasoning_effort: None,
            instructions: Some("Check the draft".into()),
            billing: None,
        },
    ))
    .await?;
    e.tick().await?;
    e.tick().await?;
    let task = &e.topic(t)?.tasks[0];
    assert_eq!(task.title, "Named: Check the draft");
    assert!(!task.untitled);
    Ok(())
}

#[tokio::test]
async fn a_sub_agents_result_comes_back_to_the_conversation() -> Result<()> {
    let mut agent = FixtureAgent::default();
    agent.script(
        "Count weekly signups",
        Script {
            delay: TimeDelta::zero(),
            progress: "Querying".into(),
            outcome: RunState::Done {
                result: "412 signups last week".into(),
            },
        },
    );
    let e = Engine::new(
        Arc::new(crate::MemoryStore::default()),
        limits(),
        Arc::new(agent),
        Arc::new(FixtureSorter),
    )
    .await?;
    let (t, _) = e.create_topic("Growth", "").await?;
    e.plan_task(t, "Count weekly signups", "", InboxAssignment::Investigate)
        .await?;
    e.tick().await?;
    e.tick().await?;
    let note = e.slot(t)?.saved.read().inbox.texts().join("\n");
    assert!(note.contains("A sub-agent finished:"), "{note}");
    assert!(
        note.contains("Count weekly signups: 412 signups last week"),
        "{note}"
    );
    Ok(())
}
