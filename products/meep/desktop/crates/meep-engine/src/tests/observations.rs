use super::*;
use serde_json::Map;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

#[derive(Default)]
struct Flow {
    requests: parking_lot::Mutex<Vec<(Uuid, Map<String, Value>)>>,
    invocations: parking_lot::Mutex<std::collections::BTreeMap<Uuid, Uuid>>,
    interrupt_after_accept: AtomicBool,
    accepted: tokio::sync::Notify,
    fail: AtomicBool,
    offline: AtomicBool,
    transient: AtomicBool,
    late_transient: AtomicBool,
    uncertain: AtomicBool,
    recovered: parking_lot::Mutex<Option<RoutineRun>>,
    recovery_calls: AtomicUsize,
    block_recovery: AtomicBool,
    recovery_started: tokio::sync::Notify,
    recovery_resume: tokio::sync::Notify,
}

#[async_trait::async_trait]
impl RoutineBackend for Flow {
    fn name(&self) -> &str {
        "posthog"
    }
    fn bind(&self, _: &RoutineBinding) -> Result<()> {
        Ok(())
    }
    fn source_ready(&self, _: TopicId) -> Result<()> {
        if self.transient.load(Ordering::Relaxed) {
            return Err(SourceTemporarilyUnavailable.into());
        }
        anyhow::ensure!(
            !self.offline.load(Ordering::Relaxed),
            "MEEP_PUBLIC_BASE_URL is not configured"
        );
        Ok(())
    }
    async fn start(
        &self,
        _: RoutineContext<'_>,
        vars: Map<String, Value>,
        key: Uuid,
    ) -> Result<RoutineRun> {
        if self.late_transient.swap(false, Ordering::SeqCst) {
            return Err(SourceTemporarilyUnavailable.into());
        }
        self.requests.lock().push((key, vars));
        if self.uncertain.load(Ordering::Relaxed) {
            return Err(DispatchUncertain.into());
        }
        anyhow::ensure!(!self.fail.load(Ordering::Relaxed), "dispatch failed");
        let invocation_id = *self
            .invocations
            .lock()
            .entry(key)
            .or_insert_with(Uuid::new_v4);
        if self.interrupt_after_accept.swap(false, Ordering::SeqCst) {
            self.accepted.notify_one();
            std::future::pending::<()>().await;
        }
        Ok(RoutineRun {
            invocation_id,
            status: "queued".into(),
        })
    }
    async fn status(&self, _: RoutineContext<'_>, id: Uuid) -> Result<RoutineRun> {
        Ok(RoutineRun {
            invocation_id: id,
            status: "completed".into(),
        })
    }
    async fn find_observation(&self, _: RoutineContext<'_>, _: Uuid) -> Result<Option<RoutineRun>> {
        self.recovery_calls.fetch_add(1, Ordering::SeqCst);
        if self.block_recovery.load(Ordering::SeqCst) {
            self.recovery_started.notify_one();
            self.recovery_resume.notified().await;
        }
        Ok(self.recovered.lock().clone())
    }
    async fn health(&self, _: RoutineContext<'_>) -> Result<RoutineHealth> {
        Ok(RoutineHealth::Ok)
    }
}

#[tokio::test]
async fn recovered_status_is_not_committed_after_topic_is_archived() -> Result<()> {
    let flow = Arc::new(Flow::default());
    flow.uncertain.store(true, Ordering::SeqCst);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(MemoryStore::default()),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Support", "").await?;
    bind(&engine, topic).await?;
    engine
        .ingest(event("archive-race", "Review", Value::Null))
        .await?;
    let key = engine.topic(topic)?.topic.routines[0].observations[0].key;
    let invocation = Uuid::new_v4();
    *flow.recovered.lock() = Some(RoutineRun {
        invocation_id: invocation,
        status: "failed".into(),
    });
    flow.block_recovery.store(true, Ordering::SeqCst);
    clock.advance(TimeDelta::seconds(31));
    let running = tokio::spawn({
        let engine = engine.clone();
        async move { engine.advance_observation(topic, key).await }
    });
    tokio::time::timeout(
        std::time::Duration::from_secs(5),
        flow.recovery_started.notified(),
    )
    .await?;
    engine.apply(envelope(topic, Command::ArchiveTopic)).await?;
    flow.block_recovery.store(false, Ordering::SeqCst);
    flow.recovery_resume.notify_one();
    running.await??;
    let report = &engine.topic(topic)?.topic.routines[0].observations[0];
    assert_eq!(report.outcome, ObservationOutcome::Pending);
    assert_eq!(report.invocation, None);
    engine
        .apply(envelope(topic, Command::UnarchiveTopic))
        .await?;
    clock.advance(TimeDelta::seconds(31));
    engine.tick_topic(topic).await?;
    let report = &engine.topic(topic)?.topic.routines[0].observations[0];
    assert!(matches!(report.outcome, ObservationOutcome::Failed { .. }));
    assert_eq!(report.invocation, Some(invocation));
    assert_eq!(flow.requests.lock().len(), 1);
    Ok(())
}

#[tokio::test]
async fn recovered_status_is_not_committed_after_routine_is_rebound() -> Result<()> {
    let flow = Arc::new(Flow::default());
    flow.uncertain.store(true, Ordering::SeqCst);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(MemoryStore::default()),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Support", "").await?;
    bind(&engine, topic).await?;
    engine
        .ingest(event("rebind-race", "Review", Value::Null))
        .await?;
    let key = engine.topic(topic)?.topic.routines[0].observations[0].key;
    let invocation = Uuid::new_v4();
    *flow.recovered.lock() = Some(RoutineRun {
        invocation_id: invocation,
        status: "failed".into(),
    });
    flow.block_recovery.store(true, Ordering::SeqCst);
    clock.advance(TimeDelta::seconds(31));
    let running = tokio::spawn({
        let engine = engine.clone();
        async move { engine.advance_observation(topic, key).await }
    });
    tokio::time::timeout(
        std::time::Duration::from_secs(5),
        flow.recovery_started.notified(),
    )
    .await?;
    let mut binding = engine.topic(topic)?.topic.routines[0].binding.clone();
    binding.external_id = "new-fixture".into();
    engine.bind_routine(topic, binding).await?;
    flow.block_recovery.store(false, Ordering::SeqCst);
    flow.recovery_resume.notify_one();
    running.await??;
    let slot = engine.slot(topic)?;
    let saved = slot.saved.read();
    assert!(
        !saved.routines["triage"]
            .invocations
            .contains_key(&invocation)
    );
    assert!(
        saved
            .observations
            .iter()
            .filter(|o| o.report.key == key)
            .all(|o| o.report.invocation.is_none())
    );
    assert_eq!(flow.requests.lock().len(), 1);
    Ok(())
}

#[tokio::test]
async fn recovered_status_waits_while_event_delivery_is_paused() -> Result<()> {
    let flow = Arc::new(Flow::default());
    flow.uncertain.store(true, Ordering::SeqCst);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(MemoryStore::default()),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Support", "").await?;
    bind(&engine, topic).await?;
    let binding = engine.topic(topic)?.topic.routines[0].binding.clone();
    engine
        .subscribe_routine(
            topic,
            &binding,
            EventSubscription {
                on: TopicEvent::TaskAdded,
                filter: Default::default(),
            },
        )
        .await?;
    engine.set_event_delivery(topic, &binding, true).await?;
    engine
        .ingest(event("pause-race", "Review", Value::Null))
        .await?;
    let key = engine.topic(topic)?.topic.routines[0].observations[0].key;
    let invocation = Uuid::new_v4();
    *flow.recovered.lock() = Some(RoutineRun {
        invocation_id: invocation,
        status: "failed".into(),
    });
    flow.block_recovery.store(true, Ordering::SeqCst);
    clock.advance(TimeDelta::seconds(31));
    let running = tokio::spawn({
        let engine = engine.clone();
        async move { engine.advance_observation(topic, key).await }
    });
    tokio::time::timeout(
        std::time::Duration::from_secs(5),
        flow.recovery_started.notified(),
    )
    .await?;
    engine.set_event_delivery(topic, &binding, false).await?;
    flow.block_recovery.store(false, Ordering::SeqCst);
    flow.recovery_resume.notify_one();
    running.await??;
    let report = &engine.topic(topic)?.topic.routines[0].observations[0];
    assert_eq!(report.outcome, ObservationOutcome::Pending);
    assert_eq!(report.invocation, None);
    clock.advance(TimeDelta::seconds(31));
    engine.tick_topic(topic).await?;
    assert_eq!(flow.recovery_calls.load(Ordering::SeqCst), 1);
    assert!(
        engine
            .slot(topic)?
            .saved
            .read()
            .observation_deadlines()
            .all(|(_, due)| due > clock.now())
    );
    engine.set_event_delivery(topic, &binding, true).await?;
    clock.advance(TimeDelta::seconds(31));
    engine.tick_topic(topic).await?;
    let report = &engine.topic(topic)?.topic.routines[0].observations[0];
    assert!(matches!(report.outcome, ObservationOutcome::Failed { .. }));
    assert_eq!(report.invocation, Some(invocation));
    assert_eq!(flow.requests.lock().len(), 1);
    Ok(())
}

#[tokio::test]
async fn uncertain_dispatch_recovers_exact_run_without_redispatch() -> Result<()> {
    for status in ["failed", "completed", "running"] {
        let flow = Arc::new(Flow::default());
        flow.uncertain.store(true, Ordering::SeqCst);
        let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
        let engine = open(
            flow.clone(),
            Arc::new(MemoryStore::default()),
            clock.clone(),
        )
        .await?;
        let (topic, _) = engine.create_topic("Support", "").await?;
        bind(&engine, topic).await?;
        engine
            .ingest(event("recovery", "Review", Value::Null))
            .await?;
        clock.advance(TimeDelta::seconds(31));
        engine.tick_topic(topic).await?;
        assert_eq!(
            engine.topic(topic)?.topic.routines[0].observations[0].outcome,
            ObservationOutcome::Pending
        );
        let invocation = Uuid::new_v4();
        *flow.recovered.lock() = Some(RoutineRun {
            invocation_id: invocation,
            status: status.into(),
        });
        clock.advance(TimeDelta::seconds(31));
        engine.tick_topic(topic).await?;
        let report = &engine.topic(topic)?.topic.routines[0].observations[0];
        assert_eq!(report.invocation, Some(invocation));
        assert!(report.failures.is_empty());
        match status {
            "failed" => assert!(matches!(report.outcome, ObservationOutcome::Failed { .. })),
            "completed" => assert!(matches!(
                report.outcome,
                ObservationOutcome::Finished { .. }
            )),
            _ => assert_eq!(report.outcome, ObservationOutcome::Dispatched),
        }
        assert_eq!(flow.requests.lock().len(), 1);
        if status == "running" {
            clock.advance(TimeDelta::seconds(6));
            engine.tick_topic(topic).await?;
            assert!(matches!(
                engine.topic(topic)?.topic.routines[0].observations[0].outcome,
                ObservationOutcome::Finished { .. }
            ));
            assert_eq!(flow.requests.lock().len(), 1);
        }
    }
    Ok(())
}

#[tokio::test]
async fn uncertain_dispatch_recovers_after_restart_without_redispatch() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let flow = Arc::new(Flow::default());
    flow.uncertain.store(true, Ordering::SeqCst);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Support", "").await?;
    bind(&engine, topic).await?;
    engine
        .ingest(event("restart-recovery", "Review", Value::Null))
        .await?;
    engine.shutdown().await;
    drop(engine);
    let invocation = Uuid::new_v4();
    *flow.recovered.lock() = Some(RoutineRun {
        invocation_id: invocation,
        status: "failed".into(),
    });
    clock.advance(TimeDelta::seconds(31));
    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock,
    )
    .await?;
    engine.tick_topic(topic).await?;
    let report = &engine.topic(topic)?.topic.routines[0].observations[0];
    assert!(matches!(report.outcome, ObservationOutcome::Failed { .. }));
    assert_eq!(report.invocation, Some(invocation));
    assert_eq!(flow.requests.lock().len(), 1);
    Ok(())
}

#[tokio::test]
async fn uncertain_dispatch_stays_pending_across_restart_and_accepts_a_late_callback() -> Result<()>
{
    let dir = tempfile::tempdir()?;
    let flow = Arc::new(Flow::default());
    flow.uncertain.store(true, Ordering::SeqCst);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Support", "").await?;
    let secret = bind(&engine, topic).await?;
    engine
        .ingest(event("uncertain", "Review this update", Value::Null))
        .await?;
    let report = engine.topic(topic)?.topic.routines[0].observations[0].clone();
    assert_eq!(report.outcome, ObservationOutcome::Pending);
    assert!(report.failures[0].contains("outcome is unknown"));
    assert_eq!(flow.requests.lock().len(), 1);
    engine.shutdown().await;
    drop(engine);

    // Do not dispatch again, even after the provider's idempotency window expires.
    clock.advance(TimeDelta::hours(25));
    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock,
    )
    .await?;
    engine.tick_topic(topic).await?;
    assert_eq!(flow.requests.lock().len(), 1);
    assert_eq!(
        engine.topic(topic)?.topic.routines[0].observations[0].outcome,
        ObservationOutcome::Pending
    );
    engine
        .routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::AddTask {
                observation: Some(report.key),
                title: "Review this update".into(),
                instructions: None,
            },
        )
        .await?;
    let state = engine.topic(topic)?;
    assert_eq!(
        state.topic.routines[0].observations[0].outcome,
        ObservationOutcome::Task(state.tasks[0].id)
    );
    Ok(())
}

#[tokio::test]
async fn uncertain_event_finishes_only_after_explicit_completion_callback() -> Result<()> {
    let flow = Arc::new(Flow::default());
    flow.uncertain.store(true, Ordering::SeqCst);
    let engine = open(
        flow.clone(),
        Arc::new(MemoryStore::default()),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let (topic, _) = engine.create_topic("Support", "").await?;
    let secret = bind(&engine, topic).await?;
    engine
        .ingest(event("event", "An update", Value::Null))
        .await?;
    let key = engine.topic(topic)?.topic.routines[0].observations[0].key;
    engine
        .event_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::Note {
                text: "A step finished".into(),
            },
            Some(key),
        )
        .await?;
    assert_eq!(
        engine.topic(topic)?.topic.routines[0].observations[0].outcome,
        ObservationOutcome::Pending
    );
    let receipt = Uuid::new_v4();
    let complete = RoutineOp::Complete { observation: key };
    assert!(
        engine
            .event_callback_once(
                topic,
                "triage",
                &Uuid::new_v4().to_string(),
                receipt,
                complete.clone(),
                Some(key)
            )
            .await
            .is_err()
    );
    engine
        .event_callback_once(
            topic,
            "triage",
            &secret,
            receipt,
            complete.clone(),
            Some(key),
        )
        .await?;
    // A delivery retry must be safe even after the observation has completed.
    engine
        .event_callback_once(topic, "triage", &secret, receipt, complete, Some(key))
        .await?;
    assert!(
        matches!(&engine.topic(topic)?.topic.routines[0].observations[0].outcome,
        ObservationOutcome::Finished { reason } if reason == "Workflow completed")
    );
    let state = engine.topic(topic)?;
    assert!(state.topic.routines[0].observations[0].failures.is_empty());
    let latest = state.activity.last().unwrap();
    assert!(!latest.text.contains("outcome is unknown"));
    assert_eq!(flow.requests.lock().len(), 1);
    Ok(())
}

async fn open(flow: Arc<Flow>, store: Arc<dyn Store>, clock: Arc<ManualClock>) -> Result<Engine> {
    Ok(Engine::with_backends(
        store,
        Arc::new(MemoryBlobs::default()),
        vec![flow],
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        clock,
    )
    .await?)
}

async fn bind(e: &Engine, t: TopicId) -> Result<String> {
    Ok(e.bind_routine(
        t,
        RoutineBinding {
            id: "triage".into(),
            name: "Triage".into(),
            backend: "posthog".into(),
            trigger: "Source event".into(),
            external_id: "fixture".into(),
            watches: vec![watch()],
        },
    )
    .await?)
}

#[tokio::test]
async fn hosted_unassigned_source_records_evidence_without_decision_and_explicit_routine_still_runs()
-> Result<()> {
    let flow = Arc::new(Flow::default());
    let store = Arc::new(MemoryStore::default());
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let open = || {
        Engine::with_backends(
            store.clone(),
            Arc::new(MemoryBlobs::default()),
            vec![flow.clone()],
            limits(),
            Arc::new(FixtureAgent::default()),
            Arc::new(WorkflowSorter),
            clock.clone(),
        )
    };
    let engine = open().await?;
    let (topic, _) = engine.create_topic("Evidence", "").await?;
    engine.set_watch(topic, vec![watch()]).await?;
    let input = event("unassigned", "A source observation", Value::Null);
    engine.ingest(input.clone()).await?;
    engine.ingest(input).await?;
    engine.sort_pending(topic).await?;
    let state = engine.topic(topic)?;
    assert!(state.threads.is_empty());
    assert!(state.needs_you().threads.is_empty());
    assert_eq!(engine.source_observations(topic, 10)?.len(), 1);
    assert_eq!(
        engine.source_observations(topic, 10)?[0]["text"],
        "A source observation"
    );
    assert!(flow.requests.lock().is_empty());
    drop(engine);
    let engine = open().await?;
    assert_eq!(engine.source_observations(topic, 10)?.len(), 1);
    assert!(engine.topic(topic)?.threads.is_empty());
    engine.set_watch(topic, vec![]).await?;
    bind(&engine, topic).await?;
    engine
        .ingest(event(
            "assigned",
            "An explicit routine observation",
            Value::Null,
        ))
        .await?;
    assert_eq!(flow.requests.lock().len(), 1);
    assert_eq!(engine.source_observations(topic, 10)?.len(), 2);
    assert!(engine.topic(topic)?.threads.is_empty());
    Ok(())
}

#[tokio::test]
async fn restart_reconciles_an_accepted_dispatch_without_resending() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let flow = Arc::new(Flow::default());
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Support", "").await?;
    let secret = bind(&engine, topic).await?;
    let input = event("restart", "Review this update", Value::Null);

    flow.interrupt_after_accept.store(true, Ordering::SeqCst);
    {
        let ingest = engine.ingest(input.clone());
        tokio::pin!(ingest);
        tokio::select! {
            result = &mut ingest => anyhow::bail!("Ingest finished before interruption: {result:?}"),
            result = tokio::time::timeout(std::time::Duration::from_secs(5), flow.accepted.notified()) => result?,
        }
        // Drop the in-flight request while the provider holds the response.
    }
    engine.shutdown().await;
    drop(engine);

    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock.clone(),
    )
    .await?;
    let audit = &engine.topic(topic)?.topic.routines[0].observations;
    assert_eq!(audit.len(), 1);
    let key = audit[0].key;
    assert_eq!(audit[0].invocation, None);
    assert_eq!(audit[0].outcome, ObservationOutcome::Pending);

    // No matching provider history must remain pending and must not resend,
    // even after the provider's 24-hour idempotency cache has expired.
    clock.advance(TimeDelta::hours(25));
    engine.tick_topic(topic).await?;
    assert_eq!(flow.requests.lock().len(), 1);
    assert_eq!(flow.recovery_calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        engine.topic(topic)?.topic.routines[0].observations[0].outcome,
        ObservationOutcome::Pending
    );
    let invocations = flow.invocations.lock().clone();
    assert_eq!(invocations.len(), 1);
    *flow.recovered.lock() = Some(RoutineRun {
        invocation_id: invocations[&key],
        status: "queued".into(),
    });
    clock.advance(TimeDelta::seconds(31));
    engine.tick_topic(topic).await?;
    assert_eq!(flow.requests.lock().len(), 1);
    assert_eq!(
        engine.topic(topic)?.topic.routines[0].observations[0].invocation,
        Some(invocations[&key])
    );
    let callback = RoutineOp::AddTask {
        observation: Some(key),
        title: "Review this update".into(),
        instructions: None,
    };
    let receipt = Uuid::new_v4();
    let result = engine
        .routine_callback_once(topic, "triage", &secret, receipt, callback.clone())
        .await?;
    assert_eq!(
        engine
            .routine_callback_once(topic, "triage", &secret, receipt, callback)
            .await?,
        result
    );
    engine.ingest(input).await?;
    let state = engine.topic(topic)?;
    assert_eq!(state.tasks.len(), 1);
    let audit = &state.topic.routines[0].observations;
    assert_eq!(audit.len(), 1);
    assert_eq!(audit[0].invocation, Some(invocations[&key]));
    assert_eq!(
        audit[0].outcome,
        ObservationOutcome::Task(state.tasks[0].id)
    );
    assert_eq!(flow.requests.lock().len(), 1);
    Ok(())
}

#[tokio::test]
async fn interrupted_dispatch_after_history_window_never_resends_or_guesses() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let flow = Arc::new(Flow::default());
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Long outage", "").await?;
    bind(&engine, topic).await?;
    flow.interrupt_after_accept.store(true, Ordering::SeqCst);
    {
        let ingest = engine.ingest(event("long-outage", "Synthetic", Value::Null));
        tokio::pin!(ingest);
        tokio::select! {
            result = &mut ingest => anyhow::bail!("Ingest finished before interruption: {result:?}"),
            result = tokio::time::timeout(std::time::Duration::from_secs(5), flow.accepted.notified()) => result?,
        }
    }
    engine.shutdown().await;
    drop(engine);
    let engine = open(
        flow.clone(),
        Arc::new(SqliteStore::open(dir.path())?),
        clock.clone(),
    )
    .await?;
    clock.advance(TimeDelta::days(8));
    engine.tick_topic(topic).await?;
    assert_eq!(flow.requests.lock().len(), 1);
    assert_eq!(flow.recovery_calls.load(Ordering::SeqCst), 0);
    let report = &engine.topic(topic)?.topic.routines[0].observations[0];
    assert_eq!(report.outcome, ObservationOutcome::Pending);
    assert!(
        report
            .failures
            .iter()
            .any(|failure| failure.contains("outcome is unknown"))
    );
    Ok(())
}

#[tokio::test]
async fn source_reports_cite_observations_and_consume_each_once() -> Result<()> {
    let flow = Arc::new(Flow::default());
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let store = Arc::new(MemoryStore::default());
    let e = open(flow.clone(), store.clone(), clock.clone()).await?;
    let (t, _) = e.create_topic("Web", "").await?;
    e.set_topic_watches(t, vec![watch()]).await?;
    assert!(
        !e.ingest_routed(event("bare", "Just a Slack message", Value::Null))
            .await?
            .1
    );
    assert!(e.topic(t)?.threads.is_empty());
    let secret = bind(&e, t).await?;
    let mut events = vec![];
    for key in ["first", "second", "drop", "empty"] {
        let mut input = event(key, key, Value::Null);
        input.thread_hint = Some("slack-thread".into());
        e.ingest(input.clone()).await?;
        e.ingest(input.clone()).await?;
        events.push(input);
    }
    let requests = flow.requests.lock().clone();
    assert_eq!(requests.len(), 4);
    assert!(e.topic(t)?.threads.is_empty());
    drop(e);
    let e = open(flow.clone(), store, clock.clone()).await?;
    for ((key, vars), input) in requests.iter().zip(&events).take(2) {
        assert_eq!(vars["observation"], json!(key));
        assert_eq!(vars["author"], input.author);
        let op = RoutineOp::Report {
            observation: Some(*key),
            reports: RoutineReports::Single {
                title: "Error rate increased".into(),
                body: "Checkout failures doubled in the past hour.".into(),
                sources: vec!["Checkout health dashboard".into()],
            },
        };
        let receipt = Uuid::new_v4();
        let first = e
            .routine_callback_once(t, "triage", &secret, receipt, op.clone())
            .await?;
        assert_eq!(
            first,
            e.routine_callback_once(t, "triage", &secret, receipt, op)
                .await?
        );
    }
    let original = e.topic(t)?;
    assert_eq!(
        original
            .threads
            .iter()
            .filter(|t| t.is_agent_report())
            .count(),
        2
    );
    e.routine_callback_once(
        t,
        "triage",
        &secret,
        Uuid::new_v4(),
        RoutineOp::Drop {
            observation: requests[2].0,
            reason: "noise".into(),
        },
    )
    .await?;
    clock.advance(TimeDelta::seconds(6));
    e.tick_topic(t).await?;
    let state = e.topic(t)?;
    assert_eq!(state.threads, original.threads);
    let audit = &state.topic.routines[0].observations;
    assert_eq!(
        audit
            .iter()
            .find(|item| item.key == requests[2].0)
            .unwrap()
            .outcome,
        ObservationOutcome::Dropped {
            reason: "noise".into()
        }
    );
    assert_eq!(
        audit
            .iter()
            .find(|item| item.key == requests[3].0)
            .unwrap()
            .outcome,
        ObservationOutcome::Finished {
            reason: "no result".into()
        }
    );
    Ok(())
}

#[tokio::test]
async fn unavailable_and_failed_dispatches_do_not_publish_raw_events() -> Result<()> {
    let flow = Arc::new(Flow::default());
    flow.offline.store(true, Ordering::Relaxed);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = open(
        flow.clone(),
        Arc::new(MemoryStore::default()),
        clock.clone(),
    )
    .await?;
    let (t, _) = e.create_topic("Web", "").await?;
    bind(&e, t).await?;
    e.ingest(event("offline", "first", Value::Null)).await?;
    e.tick_topic(t).await?;
    let state = e.topic(t)?;
    assert!(
        matches!(&state.topic.routines[0].observations[0].outcome,ObservationOutcome::Failed {reason} if reason.contains("MEEP_PUBLIC_BASE_URL"))
    );
    assert!(state.threads.is_empty());
    assert!(flow.requests.lock().is_empty());
    flow.offline.store(false, Ordering::Relaxed);
    flow.fail.store(true, Ordering::Relaxed);
    e.ingest(event("failed", "second", Value::Null)).await?;
    for _ in 0..4 {
        clock.advance(TimeDelta::seconds(6));
        e.tick_topic(t).await?;
    }
    let requests = flow.requests.lock().clone();
    assert_eq!(requests.len(), 5);
    assert!(requests.iter().all(|r| r == &requests[0]));
    let state = e.topic(t)?;
    assert!(state.threads.is_empty());
    let report = state.topic.routines[0].observations.last().unwrap();
    assert_eq!(report.failures.len(), 5);
    assert!(
        matches!(&report.outcome,ObservationOutcome::Failed {reason} if reason.contains("dispatch failed"))
    );
    Ok(())
}

#[tokio::test]
async fn temporary_readiness_failure_retries_unsent_observation_after_recovery() -> Result<()> {
    let flow = Arc::new(Flow::default());
    flow.transient.store(true, Ordering::Relaxed);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let store = Arc::new(MemoryStore::default());
    let engine = open(flow.clone(), store.clone(), clock.clone()).await?;
    let (topic, _) = engine.create_topic("Transient provider", "").await?;
    bind(&engine, topic).await?;
    engine
        .ingest(event("readiness-retry", "Synthetic payload", Value::Null))
        .await?;
    engine.tick_topic(topic).await?;
    let report = engine.topic(topic)?.topic.routines[0].observations[0].clone();
    assert_eq!(report.outcome, ObservationOutcome::Pending);
    assert_eq!(
        report.failures,
        vec![SourceTemporarilyUnavailable.to_string()]
    );
    assert!(flow.requests.lock().is_empty());
    clock.advance(TimeDelta::seconds(15));
    engine.tick_topic(topic).await?;
    assert!(flow.requests.lock().is_empty());
    drop(engine);
    let engine = open(flow.clone(), store, clock.clone()).await?;
    assert_eq!(
        engine.topic(topic)?.topic.routines[0].observations[0].outcome,
        ObservationOutcome::Pending
    );
    flow.transient.store(false, Ordering::Relaxed);
    clock.advance(TimeDelta::seconds(16));
    engine.tick_topic(topic).await?;
    assert_eq!(flow.requests.lock().len(), 1);
    let report = engine.topic(topic)?.topic.routines[0].observations[0].clone();
    assert!(report.failures.is_empty());
    assert!(report.invocation.is_some());
    Ok(())
}

#[tokio::test]
async fn provider_becoming_unavailable_after_preflight_retries_without_spending_failure_budget()
-> Result<()> {
    let flow = Arc::new(Flow::default());
    flow.late_transient.store(true, Ordering::SeqCst);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = open(
        flow.clone(),
        Arc::new(MemoryStore::default()),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Late outage", "").await?;
    bind(&engine, topic).await?;
    engine
        .ingest(event("late-outage", "Synthetic", Value::Null))
        .await?;
    let report = engine.topic(topic)?.topic.routines[0].observations[0].clone();
    assert_eq!(report.outcome, ObservationOutcome::Pending);
    assert_eq!(
        report.failures,
        vec![SourceTemporarilyUnavailable.to_string()]
    );
    assert!(flow.requests.lock().is_empty());
    clock.advance(TimeDelta::seconds(31));
    engine.tick_topic(topic).await?;
    assert_eq!(flow.requests.lock().len(), 1);
    let report = engine.topic(topic)?.topic.routines[0].observations[0].clone();
    assert!(report.failures.is_empty());
    assert!(report.invocation.is_some());
    Ok(())
}

#[tokio::test]
async fn retention_keeps_pending_and_the_last_500_completions_across_bindings() -> Result<()> {
    let (e, clock) = world().await?;
    let topic = watching(&e, "Web").await?;
    let mut saved = e.slot(topic)?.draft();
    let default = saved.state.topic.fallback.binding.clone();
    let event = event("cap", "sample", Value::Null);
    let now = clock.now();
    let pending = saved.record_observation(&default, &event, None, now);
    let mut other = saved.state.topic.fallback.clone();
    other.binding.id = "other".into();
    other.binding.backend = "posthog".into();
    other.observations.clear();
    saved.state.topic.routines.push(other.clone());
    let mut keys = Vec::new();
    for index in 0..501 {
        let binding = if index % 2 == 0 {
            &default
        } else {
            &other.binding
        };
        let key = saved.record_observation(binding, &event, None, now);
        saved.transition(
            key,
            ObservationOutcome::Dropped {
                reason: "sample".into(),
            },
            now,
        )?;
        keys.push(key);
    }
    let stored: std::collections::HashSet<_> =
        saved.observations.iter().map(|o| o.report.key).collect();
    let visible: std::collections::HashSet<_> = saved
        .state
        .topic
        .destinations()
        .flat_map(|r| r.observations.iter().map(|o| o.key))
        .collect();
    assert_eq!(stored, visible);
    assert_eq!(stored.len(), 501);
    assert!(stored.contains(&pending));
    assert!(!stored.contains(&keys[0]));
    assert!(keys[1..].iter().all(|k| stored.contains(k)));
    Ok(())
}

#[tokio::test]
async fn observed_questions_tasks_facts_and_evidence_use_the_stored_origin() -> Result<()> {
    let flow = Arc::new(Flow::default());
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = open(flow.clone(), Arc::new(MemoryStore::default()), clock).await?;
    let (topic, _) = e.create_topic("Web", "").await?;
    let secret = bind(&e, topic).await?;
    let mut inputs = vec![];
    for n in ["question", "task", "fact", "evidence", "related update"] {
        let mut input = event(n, n, Value::Null);
        input.thread_hint = Some("shared".into());
        e.ingest(input.clone()).await?;
        inputs.push(input);
    }
    let keys = flow.requests.lock().iter().map(|r| r.0).collect::<Vec<_>>();
    let callback = |op| e.routine_callback_once(topic, "triage", &secret, Uuid::new_v4(), op);
    assert!(
        callback(RoutineOp::Ask(RoutineAsk::Question {
            observation: Some(keys[0]),
            text: "Proceed?".into(),
            suggestions: None,
        }))
        .await
        .is_err()
    );
    let added = callback(RoutineOp::AddTask {
        observation: Some(keys[1]),
        title: "Check".into(),
        instructions: None,
    })
    .await?;
    let task = serde_json::from_value(added["task"].clone())?;
    callback(RoutineOp::AddFact {
        observation: Some(keys[2]),
        text: "Observed fact".into(),
    })
    .await?;
    assert!(
        callback(RoutineOp::AttachEvidence {
            observation: keys[3],
            task: id()
        })
        .await
        .is_err()
    );
    callback(RoutineOp::AttachEvidence {
        observation: keys[3],
        task,
    })
    .await?;
    let state = e.topic(topic)?;
    assert!(state.threads.is_empty());
    assert_eq!(state.tasks[0].origin, inputs[1].message(id())?.origin);
    let provenance = &state.topic.facts[0].provenance;
    assert_eq!(provenance.origin, inputs[2].message(id())?.origin);
    assert_eq!(provenance.thread, None);
    assert_eq!(provenance.via, "slack");
    assert_eq!(
        state.tasks[0].log.last().unwrap().origin,
        inputs[3].message(id())?.origin
    );
    let related = callback(RoutineOp::Classified {
        observation: keys[4],
        category: "investigate".into(),
    })
    .await?;
    assert_eq!(related["task"], added["task"]);
    let state = e.topic(topic)?;
    assert_eq!(state.tasks.len(), 1);
    assert_eq!(
        state.tasks[0].log.last().unwrap().origin,
        inputs[4].message(id())?.origin
    );
    Ok(())
}

#[derive(Default)]
struct CountingSorter(parking_lot::Mutex<Vec<Option<String>>>);
#[async_trait::async_trait]
impl Sorter for CountingSorter {
    async fn sort(&self, _: SortInput<'_>) -> anyhow::Result<Sorted> {
        anyhow::bail!("unexpected intake sort")
    }
    async fn sort_step(
        &self,
        input: SortInput<'_>,
        instructions: Option<&str>,
    ) -> anyhow::Result<Sorted> {
        assert_eq!(input.topic.mission, "Fixture mission");
        assert_eq!(input.thread.messages.last().unwrap(), input.message);
        self.0.lock().push(instructions.map(str::to_owned));
        Ok(Sorted {
            decision: Decision::Handle {
                summary: "Handled by System 1".into(),
                outcomes: vec![],
            },
            fact: Some(input.message.text.clone()),
            work: None,
            confidence: Some(1.0),
        })
    }
}

#[tokio::test]
async fn workflow_sort_uses_one_evaluation_and_preserves_the_observed_source() -> Result<()> {
    for (deferred, instructions) in [
        (false, None),
        (true, None),
        (true, Some("Focus on changes")),
    ] {
        let flow = Arc::new(Flow::default());
        let sorter = Arc::new(CountingSorter::default());
        let e = Engine::with_backends(
            Arc::new(MemoryStore::default()),
            Arc::new(MemoryBlobs::default()),
            vec![flow.clone()],
            limits(),
            Arc::new(FixtureAgent::default()),
            sorter.clone(),
            Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
        )
        .await?;
        let (t, _) = e.create_topic("Web", "Fixture mission").await?;
        let secret = bind(&e, t).await?;
        if deferred {
            let binding = e.binding(t, "triage")?.0;
            e.defer_source_sort(t, &binding).await?;
        }
        let input = event("fixture", "Version shipped", Value::Null);
        e.ingest(input.clone()).await?;
        assert_eq!(sorter.0.lock().len(), usize::from(!deferred));
        let key = flow.requests.lock()[0].0;
        let op = RoutineOp::Sort {
            observation: key,
            instructions: instructions.map(str::to_owned),
        };
        let receipt = Uuid::new_v4();
        for _ in 0..2 {
            e.routine_callback_once(t, "triage", &secret, receipt, op.clone())
                .await?;
        }
        assert_eq!(*sorter.0.lock(), vec![instructions.map(str::to_owned)]);
        let state = e.topic(t)?;
        let message = &state.threads[0].messages[0];
        assert_eq!(message.producer, Producer::Routine("triage".into()));
        assert_eq!(message.origin, input.message(id())?.origin);
        assert_eq!(state.topic.facts[0].provenance.origin, message.origin);
        assert_eq!(
            state.topic.routines[0].observations[0].outcome,
            ObservationOutcome::Fact(state.topic.facts[0].id)
        );
    }
    Ok(())
}

#[tokio::test]
async fn hosted_skip_rule_uses_source_and_preserves_attribution_and_receipt() -> Result<()> {
    let flow = Arc::new(Flow::default());
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = open(flow.clone(), Arc::new(MemoryStore::default()), clock).await?;
    let (topic, _) = e.create_topic("Skip fixture", "").await?;
    let secret = bind(&e, topic).await?;
    e.add_rule(
        topic,
        "Ignore routine rollout updates",
        RuleEffect::Skip(Matcher {
            connection: Some("slack".into()),
            channel: Some("#other".into()),
        }),
    )
    .await?;
    e.add_rule(
        topic,
        "Ignore this rollout",
        RuleEffect::Skip(Matcher {
            connection: Some("slack".into()),
            channel: Some("#rail".into()),
        }),
    )
    .await?;
    let rule = e.topic(topic)?.topic.rules.last().unwrap().id;
    let input = event("source-skip", "The rollout changed", Value::Null);
    e.ingest(input.clone()).await?;
    let key = flow.requests.lock()[0].0;
    let context = e.routine_sort_input(topic, "triage", &secret, key)?;
    assert_eq!(context.skip_guard, "single");
    assert!(!context.skip_fingerprint.is_empty());
    assert!(context.context.contains("Ignore this rollout"));
    assert!(!context.context.contains("Ignore routine rollout updates"));
    let request = Uuid::new_v4();
    let op = RoutineOp::SkipRule {
        observation: key,
        fingerprint: context.skip_fingerprint,
    };
    let first = e
        .routine_callback_once(topic, "triage", &secret, request, op.clone())
        .await?;
    let replay = e
        .routine_callback_once(topic, "triage", &secret, request, op)
        .await?;
    assert_eq!(first, replay);
    let state = e.topic(topic)?;
    assert_eq!(state.threads.len(), 1);
    assert!(
        matches!(&state.threads[0].state, ThreadState::Skipped { rule:Some(id), .. } if *id == rule)
    );
    assert_eq!(
        state.threads[0].messages[0].origin,
        input.message(id())?.origin
    );
    assert_eq!(state.threads[0].messages[0].text, input.text);
    assert!(state.tasks.is_empty());
    Ok(())
}

#[tokio::test]
async fn hosted_skip_rule_requires_current_unambiguous_rule_and_model_choice() -> Result<()> {
    let flow = Arc::new(Flow::default());
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = open(flow.clone(), Arc::new(MemoryStore::default()), clock).await?;
    let (topic, _) = e.create_topic("Skip fixture", "").await?;
    let secret = bind(&e, topic).await?;
    e.add_rule(
        topic,
        "Ignore only routine rollouts",
        RuleEffect::Skip(Matcher {
            connection: Some("slack".into()),
            channel: Some("#rail".into()),
        }),
    )
    .await?;
    let rule = e.topic(topic)?.topic.rules.last().unwrap().id;
    for key in [
        "semantic-mismatch",
        "stale-rule",
        "multiple-rules",
        "other-source",
        "stale-classification",
        "cross-observation",
        "guarded-multiple",
        "oversized-rule",
        "legacy-review",
    ] {
        e.ingest(event(key, "Urgent event", Value::Null)).await?;
    }
    let keys = flow.requests.lock().iter().map(|v| v.0).collect::<Vec<_>>();
    let first = e.routine_sort_input(topic, "triage", &secret, keys[0])?;
    assert_eq!(first.skip_guard, "single");
    e.routine_callback_once(
        topic,
        "triage",
        &secret,
        Uuid::new_v4(),
        RoutineOp::GuardedClassified {
            observation: keys[0],
            category: "inbox".into(),
            snapshot: first.skip_snapshot,
        },
    )
    .await?;
    assert!(matches!(
        e.topic(topic)?.threads.last().unwrap().state,
        ThreadState::Handled
    ));
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::Classified {
                observation: keys[8],
                category: "investigate".into(),
            },
        )
        .await
        .is_err()
    );

    let cross = e.routine_sort_input(topic, "triage", &secret, keys[5])?;
    assert_ne!(first.skip_fingerprint, cross.skip_fingerprint);
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::SkipRule {
                observation: keys[5],
                fingerprint: first.skip_fingerprint,
            },
        )
        .await
        .is_err()
    );

    let stale = e.routine_sort_input(topic, "triage", &secret, keys[1])?;
    e.remove_rule(topic, rule).await?;
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::SkipRule {
                observation: keys[1],
                fingerprint: stale.skip_fingerprint.clone(),
            },
        )
        .await
        .is_err()
    );

    for text in ["Ignore this item", "Ignore only automated items"] {
        e.add_rule(
            topic,
            text,
            RuleEffect::Skip(Matcher {
                connection: Some("slack".into()),
                channel: Some("#rail".into()),
            }),
        )
        .await?;
    }
    let ambiguous = e.routine_sort_input(topic, "triage", &secret, keys[2])?;
    assert_eq!(ambiguous.skip_guard, "review");
    assert!(ambiguous.skip_fingerprint.is_empty());
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::SkipRule {
                observation: keys[2],
                fingerprint: stale.context,
            },
        )
        .await
        .is_err()
    );

    let multiple = e.routine_sort_input(topic, "triage", &secret, keys[6])?;
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::GuardedClassified {
                observation: keys[6],
                category: "investigate".into(),
                snapshot: multiple.skip_snapshot,
            },
        )
        .await
        .is_err()
    );

    let ids = e
        .topic(topic)?
        .topic
        .rules
        .iter()
        .map(|r| r.id)
        .collect::<Vec<_>>();
    for id in ids {
        e.remove_rule(topic, id).await?;
    }
    e.add_rule(
        topic,
        "Ignore another channel",
        RuleEffect::Skip(Matcher {
            connection: Some("slack".into()),
            channel: Some("#other".into()),
        }),
    )
    .await?;
    let mismatch = e.routine_sort_input(topic, "triage", &secret, keys[3])?;
    assert_eq!(mismatch.skip_guard, "none");
    assert!(!mismatch.context.contains("Ignore another channel"));
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::SkipRule {
                observation: keys[3],
                fingerprint: stale.skip_fingerprint,
            },
        )
        .await
        .is_err()
    );

    let prior = e.routine_sort_input(topic, "triage", &secret, keys[4])?;
    e.add_rule(
        topic,
        "Ignore this newly relevant source",
        RuleEffect::Skip(Matcher {
            connection: Some("slack".into()),
            channel: Some("#rail".into()),
        }),
    )
    .await?;
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::GuardedClassified {
                observation: keys[4],
                category: "investigate".into(),
                snapshot: prior.skip_snapshot,
            },
        )
        .await
        .is_err()
    );
    let state = e.topic(topic)?;

    assert!(
        state.tasks.is_empty(),
        "stale classification must not start work"
    );
    for rule in state.topic.rules {
        e.remove_rule(topic, rule.id).await?;
    }
    e.add_rule(
        topic,
        "x".repeat(301),
        RuleEffect::Skip(Matcher {
            connection: Some("slack".into()),
            channel: Some("#rail".into()),
        }),
    )
    .await?;
    let long = e.routine_sort_input(topic, "triage", &secret, keys[7])?;
    assert_eq!(long.skip_guard, "review");
    assert!(long.skip_fingerprint.is_empty());
    assert!(
        e.routine_callback_once(
            topic,
            "triage",
            &secret,
            Uuid::new_v4(),
            RoutineOp::GuardedClassified {
                observation: keys[7],
                category: "inbox".into(),
                snapshot: long.skip_snapshot,
            },
        )
        .await
        .is_err()
    );

    Ok(())
}

#[tokio::test]
async fn watch_target_limits_fanout_and_preserves_legacy_delivery() -> Result<()> {
    let (engine, _) = world().await?;
    let first = watching(&engine, "First").await?;
    let second = watching(&engine, "Second").await?;
    let first_watch = engine.topic(first)?.topic.fallback.binding.watches[0].id;
    let second_watch = engine.topic(second)?.topic.fallback.binding.watches[0].id;
    let targeted = event("targeted-first", "Only first", Value::Null);
    assert!(
        engine
            .ingest_routed_to(targeted.clone(), Some(first_watch))
            .await?
            .1
    );
    assert_eq!(engine.source_observations(first, 10)?.len(), 1);
    assert!(engine.source_observations(second, 10)?.is_empty());
    assert!(
        engine
            .ingest_routed_to(targeted, Some(first_watch))
            .await?
            .1
    );
    assert_eq!(engine.source_observations(first, 10)?.len(), 1);
    // A temporarily archived target must not redirect its event to another watch.
    engine.apply(envelope(first, Command::ArchiveTopic)).await?;
    let later = event("targeted-later", "After archive", Value::Null);
    // Simulate the target being archived after route selection but before its
    // delivery lock: this must fail so replay does not record it as delivered.
    let writers = tokio::sync::Semaphore::new(1);
    assert!(
        engine
            .deliver(
                first,
                &later,
                Producer::System,
                &Causality::default(),
                Some((&writers, "system:sort-inbox".into(), Some(first_watch)))
            )
            .await
            .is_err()
    );
    assert!(
        !engine
            .ingest_routed_to(later.clone(), Some(first_watch))
            .await?
            .1
    );
    assert!(engine.source_observations(second, 10)?.is_empty());
    engine
        .apply(envelope(first, Command::UnarchiveTopic))
        .await?;
    assert!(engine.ingest_routed_to(later, Some(first_watch)).await?.1);
    assert_eq!(engine.source_observations(first, 10)?.len(), 2);
    assert!(engine.source_observations(second, 10)?.is_empty());
    // Removed watches also cannot redirect to another subscription.
    engine.set_watch(first, vec![]).await?;
    assert!(
        !engine
            .ingest_routed_to(event("removed", "Removed", Value::Null), Some(first_watch))
            .await?
            .1
    );
    assert!(engine.source_observations(second, 10)?.is_empty());
    assert!(
        engine
            .ingest_routed_to(
                event("second", "Only second", Value::Null),
                Some(second_watch)
            )
            .await?
            .1
    );
    assert_eq!(engine.source_observations(second, 10)?.len(), 1);
    // Existing untargeted connectors still fan out to every matching watch.
    engine
        .set_watch(
            first,
            vec![Watch {
                id: first_watch,
                ..watch()
            }],
        )
        .await?;
    engine.ingest(event("legacy", "Both", Value::Null)).await?;
    assert_eq!(engine.source_observations(first, 10)?.len(), 3);
    assert_eq!(engine.source_observations(second, 10)?.len(), 2);
    Ok(())
}
