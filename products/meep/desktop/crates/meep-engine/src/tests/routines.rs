use super::*;

#[tokio::test]
async fn callback_secrets_survive_restart_are_scoped_to_the_binding_and_rotate_on_rebind()
-> Result<()> {
    let dir = tempfile::tempdir()?;
    let engine = Engine::with_backends(
        Arc::new(SqliteStore::open(dir.path())?),
        Arc::new(MemoryBlobs::default()),
        vec![Arc::new(crate::fixture_flows::FixtureFlows)],
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let (a, _) = engine.create_topic("First", "").await?;
    let (b, _) = engine.create_topic("Second", "").await?;
    let flow = crate::fixture_flows::fixture_binding("watch");
    engine.bind_routine(a, flow.clone()).await?;
    engine.bind_routine(b, flow.clone()).await?;
    let secret = engine.routine_secret(a, "watch")?;
    assert_ne!(secret, engine.routine_secret(b, "watch")?);
    drop(engine);
    let engine = Engine::with_backends(
        Arc::new(SqliteStore::open(dir.path())?),
        Arc::new(MemoryBlobs::default()),
        vec![Arc::new(crate::fixture_flows::FixtureFlows)],
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let note = RoutineOp::Note {
        text: "Reviewed".into(),
    };
    assert!(matches!(
        engine
            .routine_callback(b, "watch", &secret, note.clone())
            .await,
        Err(Error::InvalidRoutineSecret(_))
    ));
    engine
        .routine_callback(a, "watch", &secret, note.clone())
        .await?;
    engine.bind_routine(a, flow).await?;
    assert!(matches!(
        engine.routine_callback(a, "watch", &secret, note).await,
        Err(Error::InvalidRoutineSecret(_))
    ));
    let notes = |topic| -> Result<usize> {
        Ok(engine
            .topic(topic)?
            .activity
            .iter()
            .filter(|a| a.text == "Reviewed")
            .count())
    };
    assert_eq!((notes(a)?, notes(b)?), (1, 0));
    Ok(())
}

#[tokio::test]
async fn a_routine_receives_its_approved_action_and_its_terminal_status_reaches_the_task()
-> Result<()> {
    let (e, _) = world().await?;
    let (topic, _) = e.create_topic("Work", "").await?;
    e.add_task(topic, "Edit").await?;
    let task = e.topic(topic)?.tasks[0].id;
    e.move_task(topic, task, Column::InProgress).await?;
    let name = "review";
    e.bind_routine(topic, crate::fixture_flows::fixture_binding(name))
        .await?;
    let op = RoutineOp::Ask(RoutineAsk::Approval {
        observation: None,
        task,
        action: action(),
        result: "prepared".into(),
        draft: Some("old".into()),
    });
    let secret = e.routine_secret(topic, name)?;
    e.routine_callback_once(topic, name, &secret, Uuid::new_v4(), op)
        .await?;
    e.approve(topic, task, Some("edited".into()), false).await?;
    e.tick().await?;
    e.tick().await?;
    let state = e.topic(topic)?;
    assert!(
        state.tasks[0]
            .result
            .as_ref()
            .is_some_and(|s| s.ends_with("completed"))
    );
    Ok(())
}

#[tokio::test]
async fn interrupted_send_callbacks_bind_the_delivery_id_to_the_original_destination_and_body()
-> Result<()> {
    let (e, _) = world().await?;
    let (source, _) = e.create_topic("send", "").await?;
    let (to, _) = e.create_topic("receive", "").await?;
    let (other, _) = e.create_topic("unrelated", "").await?;
    e.bind_routine(source, crate::fixture_flows::fixture_binding("send"))
        .await?;
    let secret = e.routine_secret(source, "send")?;
    let key = Uuid::new_v4();
    let original = RoutineOp::Send {
        to,
        text: "original".into(),
    };
    let receiver = e.slot(to)?;
    let lock = receiver.edit.lock().await;
    assert!(
        tokio::time::timeout(
            std::time::Duration::from_millis(100),
            e.routine_callback_once(source, "send", &secret, key, original.clone())
        )
        .await
        .is_err()
    );
    drop(lock);
    let altered = RoutineOp::Send {
        to: other,
        text: "changed".into(),
    };
    assert!(matches!(
        e.routine_callback_once(source, "send", &secret, key, altered)
            .await,
        Err(Error::CommandCollision(_))
    ));
    for _ in 0..2 {
        e.routine_callback_once(source, "send", &secret, key, original.clone())
            .await?;
    }
    assert!(e.topic(other)?.threads.is_empty());
    assert_eq!(e.topic(to)?.threads.len(), 1);
    Ok(())
}

#[tokio::test]
async fn rebinding_the_same_routine_with_new_steps_withdraws_the_old_proposal() -> Result<()> {
    let (e, _) = world().await?;
    let (topic, _) = e.create_topic("Shipping", "").await?;
    e.add_task(topic, "Draft notice").await?;
    let task = e.topic(topic)?.tasks[0].id;
    e.move_task(topic, task, Column::InProgress).await?;
    e.bind_routine(topic, crate::fixture_flows::fixture_binding("shipping"))
        .await?;
    let secret = e.routine_secret(topic, "shipping")?;
    e.routine_callback_once(
        topic,
        "shipping",
        &secret,
        Uuid::new_v4(),
        RoutineOp::Ask(RoutineAsk::Approval {
            observation: None,
            task,
            action: action(),
            result: "Proposed".into(),
            draft: None,
        }),
    )
    .await?;
    let old = e.topic(topic)?.tasks[0].review_version;
    e.bind_routine(topic, crate::fixture_flows::fixture_binding("shipping"))
        .await?;
    let command = envelope(
        topic,
        Command::Approve {
            task,
            expected_review: Some(old),
            edited_draft: None,
            always: true,
            rule_id: id(),
        },
    );
    assert!(e.apply(command).await.is_err());
    let state = e.topic(topic)?;
    assert!(state.tasks[0].action.is_none());
    assert_eq!(state.tasks[0].column, Column::NeedsYou);
    assert!(state.topic.rules.is_empty());
    e.tick().await?;
    assert!(
        !e.topic(topic)?
            .activity
            .iter()
            .any(|entry| entry.text == "replacement")
    );
    Ok(())
}

#[tokio::test]
async fn activation_returns_to_review_when_allow_changes_before_delivery() -> Result<()> {
    let (e, _) = world().await?;
    let (topic, _) = e.create_topic("Orders", "").await?;
    e.bind_routine(topic, crate::fixture_flows::fixture_binding("weekly"))
        .await?;
    let (binding, _) = e.binding(topic, "weekly")?;
    let kind = ActionKind("routine-activate".into());
    e.add_rule(
        topic,
        "Activate automatically",
        RuleEffect::Allow(kind.clone()),
    )
    .await?;
    let slot = e.slot(topic)?;
    let blocked = slot.effect_worker.lock().await;
    let mut changes = e.subscribe();
    let request = id();
    let activation = tokio::spawn({
        let e = e.clone();
        let binding = binding.clone();
        async move {
            e.request_routine_activation(topic, &binding, request, Some(vec![]))
                .await
        }
    });
    tokio::time::timeout(std::time::Duration::from_secs(4), async {
        while !e
            .topic(topic)?
            .tasks
            .iter()
            .any(|t| t.id == request && t.column == Column::Done)
        {
            changes.recv().await?;
        }
        anyhow::Ok(())
    })
    .await??;
    e.add_rule(topic, "Review each activation", RuleEffect::Ask(kind))
        .await?;
    drop(blocked);
    assert_eq!(activation.await??.column, Column::NeedsYou);
    // Both the original request and a coalesced duplicate identify the same review.
    let duplicate = id();
    assert_eq!(
        e.request_routine_activation(topic, &binding, duplicate, Some(vec![]))
            .await?
            .id,
        request
    );
    e.approve(topic, request, None, false).await?;
    let prior = e
        .request_routine_activation(topic, &binding, duplicate, Some(vec![]))
        .await?;
    assert_eq!(prior.id, request);
    assert_eq!(
        e.topic(topic)?
            .tasks
            .iter()
            .filter(|t| t
                .action
                .as_ref()
                .is_some_and(|a| a.kind.0 == "routine-activate"))
            .count(),
        1
    );
    Ok(())
}
