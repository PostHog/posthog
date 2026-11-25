use super::*;

async fn open_at_epoch(dir: &Path) -> crate::Result<Engine> {
    Engine::with_clock(
        Arc::new(SqliteStore::open(dir)?),
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await
}

#[tokio::test]
async fn records_reopen_with_search_receipts_schedules_and_an_active_agent_handle() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let open = || async {
        Engine::with_clock(
            Arc::new(SqliteStore::open(dir.path())?),
            limits(),
            Arc::new(scripted()),
            Arc::new(FixtureSorter),
            clock.clone(),
        )
        .await
    };
    let e = open().await?;
    let t = watching(&e, "Web").await?;
    let f = event(
        "1",
        "Navigation review",
        json!({"fact":"Navigation keeps five items"}),
    );
    e.ingest(f.clone()).await?;
    e.add_task(t, "Navigation copy").await?;
    e.add_task(t, "Draft").await?;
    e.tick().await?;
    let saved = e.topic(t)?;
    drop(e);
    let e = open().await?;
    assert_eq!(e.topic(t)?, saved);
    assert_eq!(e.search("navig")?.len(), 3);
    assert!(e.search("navigation")?.iter().all(|h| h.topic == t));
    assert!(e.ingest(f).await?.is_empty());
    clock.advance(TimeDelta::seconds(6));
    e.tick().await?;
    let state = e.topic(t)?;
    assert_eq!(state.tasks[1].column, Column::NeedsYou);
    e.tick().await?;
    assert_eq!(state.topic.facts.len(), 1);
    Ok(())
}

#[test]
fn the_topic_directory_has_one_writer() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let store = SqliteStore::open(dir.path())?;
    assert!(SqliteStore::open(dir.path()).is_err());
    drop(store);
    SqliteStore::open(dir.path())?;
    Ok(())
}

#[tokio::test]
async fn moving_a_source_changes_its_only_route_and_leaves_failed_delivery_replayable() -> Result<()>
{
    let (engine, _) = world().await?;
    let topic = watching(&engine, "Web").await?;
    let source = engine.topic(topic)?.topic.watches().next().unwrap().clone();
    engine
        .bind_routine(topic, crate::fixture_flows::fixture_binding("other"))
        .await?;
    engine
        .set_routine_watches(topic, "other".into(), vec![source.clone()])
        .await?;
    let event = event("moved", "Second arrival", Value::Null);
    // Whole-topic editors retain the owner. Legacy SetWatch only edits the sorter.
    engine
        .set_topic_watches(topic, vec![source.clone()])
        .await?;
    engine.set_watch(topic, vec![]).await?;
    let state = engine.topic(topic)?;
    let bindings = state
        .topic
        .routines
        .into_iter()
        .map(|r| (topic, r.binding))
        .collect::<Vec<_>>();
    assert_eq!(
        meep_ingest::route(&event, &bindings),
        [(topic, "other".into())]
    );
    engine.ingest(event.clone()).await?;
    assert!(engine.topic(topic)?.threads.is_empty());
    engine
        .apply(envelope(topic, Command::ReleaseSource { key: source.id }))
        .await?;
    let mut fresh = event;
    fresh.external_id = "fresh".into();
    engine.ingest(fresh).await?;
    assert_eq!(engine.topic(topic)?.threads.len(), 1);
    Ok(())
}

#[tokio::test]
async fn cancelling_a_waiting_command_cannot_leave_its_committed_revision_out_of_the_snapshot()
-> Result<()> {
    let dir = tempfile::tempdir()?;
    let e = open_at_epoch(dir.path()).await?;
    let (topic, _) = e.create_topic("Web", "").await?;
    let blocker = Database::open(dir.path().join("topics.sqlite"))?;
    blocker.execute_batch("BEGIN IMMEDIATE")?;
    let caller = e.clone();
    let command =
        tokio::spawn(async move { caller.add_task(topic, "Started before cancellation").await });
    let slot = e.slot(topic)?;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while slot.edit.try_lock().is_ok() {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    command.abort();
    assert!(command.await.expect_err("caller cancelled").is_cancelled());
    blocker.execute_batch("COMMIT")?;
    e.add_task(topic, "Next command").await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks.len(), 2);
    drop(e);
    assert_eq!(open_at_epoch(dir.path()).await?.topic(topic)?, state);
    Ok(())
}

#[tokio::test]
async fn a_command_retry_returns_the_current_revision_after_reopen_and_never_advances_the_cursor()
-> Result<()> {
    let dir = tempfile::tempdir()?;
    let e = Engine::open(dir.path()).await?;
    let t = id();
    let create = envelope(
        t,
        Command::CreateTopic {
            name: "Rail".into(),
            mission: "Five".into(),
        },
    );
    let added = envelope(
        t,
        Command::AddTask {
            id: id(),
            title: "Check the rail".into(),
        },
    );
    assert_eq!(e.apply(create.clone()).await?.revision, 1);
    let mut feed = e.subscribe();
    let (first, second) = tokio::join!(e.apply(added.clone()), e.apply(added.clone()));
    let (first, second) = (first?, second?);
    assert_eq!((first.revision, second.revision), (2, 2));
    assert_ne!(first.changes.is_empty(), second.changes.is_empty());
    assert_eq!(feed.try_recv()?.revision, 2);
    assert!(feed.try_recv().is_err());
    let task = e.topic(t)?.tasks[0].id;
    let noop = envelope(
        t,
        Command::MoveTask {
            task,
            column: Column::Todo,
        },
    );
    assert_eq!(e.apply(noop.clone()).await?.revision, 2);
    e.move_task(t, task, Column::Done).await?;
    assert!(
        e.apply(envelope(t, Command::StartTask { task }))
            .await
            .is_err()
    );
    assert_eq!(
        e.changes_since(1)?,
        (
            vec![
                TopicRevision {
                    topic: t,
                    revision: 2
                },
                TopicRevision {
                    topic: t,
                    revision: 3
                }
            ],
            3
        )
    );
    drop(e);
    let e = Engine::open(dir.path()).await?;
    for request in [create, added.clone(), noop] {
        assert_eq!(
            e.apply(request).await?,
            Applied {
                revision: 3,
                changes: vec![]
            }
        );
    }
    assert!(matches!(
        e.apply(Envelope {
            command: Command::AddTask {
                id: task,
                title: "Different title".into(),
            },
            ..added.clone()
        })
        .await,
        Err(Error::CommandCollision(_))
    ));
    assert!(matches!(
        e.apply(Envelope {
            topic: id(),
            ..added
        })
        .await,
        Err(Error::CommandCollision(_))
    ));
    assert_eq!(e.changes_since(3)?, (vec![], 3));
    assert_eq!(e.search("rail")?.len(), 2);
    assert_eq!(e.snapshot(t)?.revision, 3);
    Ok(())
}

#[tokio::test]
async fn ingest_agent_results_callbacks_and_topic_messages_each_publish_a_pullable_revision()
-> Result<()> {
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let e = Engine::with_backends(
        Arc::new(MemoryStore::default()),
        Arc::new(MemoryBlobs::default()),
        vec![Arc::new(crate::fixture_flows::FixtureFlows)],
        limits(),
        Arc::new(scripted()),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let t = watching(&e, "Design").await?;
    let (other, _) = e.create_topic("Other", "").await?;
    let mut feed = e.subscribe();
    let (_, cursor) = e.changes_since(0)?;
    e.ingest(event("a", "review", Value::Null)).await?;
    let ingest = e.snapshot(t)?.revision;
    e.add_task(t, "Draft").await?;
    e.tick().await?;
    clock.advance(TimeDelta::seconds(5));
    e.tick().await?;
    let agent = e.snapshot(t)?.revision;
    assert!(agent > ingest + 1);
    e.send_to_topic(other, t, "An update", 1).await?;
    assert_eq!(e.snapshot(t)?.revision, agent + 1);
    e.bind_routine(t, crate::fixture_flows::fixture_binding("weekly"))
        .await?;
    let secret = e.routine_secret(t, "weekly")?;
    let before = e.snapshot(t)?.revision;
    let op = RoutineOp::AddTask {
        observation: None,
        title: "Callback work".into(),
        instructions: None,
    };
    assert!(matches!(
        e.routine_callback(t, "weekly", "wrong", op.clone()).await,
        Err(Error::InvalidRoutineSecret(_))
    ));
    let denied = e.snapshot(t)?;
    assert_eq!(denied.revision, before + 1);
    assert_eq!(denied.state.tasks.len(), 1);
    assert!(
        denied
            .state
            .activity
            .last()
            .expect("audit entry")
            .text
            .contains("Rejected")
    );
    e.routine_callback(t, "weekly", &secret, op).await?;
    let updated = e.snapshot(t)?;
    assert_eq!(updated.revision, before + 2);
    assert_eq!(
        updated.state.tasks[1].added_by,
        Actor::Routine("weekly".into())
    );
    assert_eq!(updated.state.topic.routines[0].last_run, Some(clock.now()));
    let public = serde_json::to_string(&updated)?;
    assert!(!public.contains(&secret));
    let (revisions, end) = e.changes_since(cursor)?;
    let mut broadcast_revisions = Vec::new();
    while let Ok(event) = feed.try_recv() {
        assert_eq!(event.topic, t);
        broadcast_revisions.push(event.revision);
    }
    broadcast_revisions.dedup();
    assert_eq!(
        broadcast_revisions,
        revisions.iter().map(|r| r.revision).collect::<Vec<_>>()
    );
    assert_eq!(
        broadcast_revisions,
        (ingest..=updated.revision).collect::<Vec<_>>()
    );
    assert_eq!(e.changes_since(end)?, (vec![], end));
    Ok(())
}

#[test]
fn revisioned_files_keep_history_across_concurrent_writes_and_reopen() -> Result<()> {
    fn exercise(blobs: &dyn Blobs, topic: TopicId) -> Result<()> {
        let key = "../notes/é";
        assert!(blobs.get(topic, key, None)?.is_none());
        blobs.put(topic, key, b"one")?;
        std::thread::scope(|scope| -> Result<()> {
            let a = scope.spawn(|| blobs.put(topic, key, b"two"));
            let b = scope.spawn(|| blobs.put(topic, key, b"three"));
            let mut revisions = [
                a.join().expect("writer")?.revision,
                b.join().expect("writer")?.revision,
            ];
            revisions.sort();
            assert_eq!(revisions, [2, 3]);
            Ok(())
        })?;
        assert_eq!(blobs.history(topic, key)?.len(), 3);
        assert_eq!(
            blobs.get(topic, key, Some(1))?.expect("initial").bytes,
            b"one"
        );
        assert_eq!(
            blobs.list(topic)?,
            [blobs.get(topic, key, None)?.expect("head")]
        );
        assert!(blobs.list(id())?.is_empty());
        Ok(())
    }
    let t = id();
    exercise(&MemoryBlobs::default(), t)?;
    let dir = tempfile::tempdir()?;
    exercise(&DirBlobs::open(dir.path())?, t)?;
    assert_eq!(DirBlobs::open(dir.path())?.list(t)?[0].revision, 3);
    Ok(())
}

#[tokio::test]
async fn a_failed_index_write_rolls_back_the_snapshot_receipt_and_change_cursor() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let e = Engine::open(dir.path()).await?;
    let (topic, _) = e.create_topic("Rail", "").await?;
    let request = envelope(
        topic,
        Command::AddTask {
            id: id(),
            title: "Transactional insert".into(),
        },
    );
    let db = Database::open(dir.path().join("topics.sqlite"))?;
    db.execute_batch(
        "CREATE TRIGGER reject_index BEFORE INSERT ON search_documents
                      BEGIN SELECT RAISE(ABORT,'fixture index failure'); END;",
    )?;
    let before = e.snapshot(topic)?;
    assert!(e.apply(request.clone()).await.is_err());
    assert_eq!(e.snapshot(topic)?, before);
    assert_eq!(e.changes_since(1)?, (vec![], 1));
    assert!(e.search("transactional")?.is_empty());
    db.execute_batch("DROP TRIGGER reject_index")?;
    drop(e);
    let e = Engine::open(dir.path()).await?;
    assert_eq!(e.snapshot(topic)?, before);
    assert_eq!(e.apply(request).await?.revision, 2);
    assert_eq!(e.search("transactional")?.len(), 1);
    Ok(())
}

#[tokio::test]
async fn a_reader_does_not_prevent_saving_a_topic() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let e = Engine::open(dir.path()).await?;
    let reader = Database::open(dir.path().join("topics.sqlite"))?;
    reader.execute_batch("BEGIN; SELECT * FROM topic_revisions")?;
    e.create_topic("write during read", "").await?;
    assert_eq!(
        reader.query_row("SELECT count(*) FROM topic_revisions", [], |r| r
            .get::<_, i64>(0))?,
        0
    );
    Ok(())
}

#[tokio::test]
async fn search_matches_a_mission_and_messages_beyond_the_thread_subject() -> Result<()> {
    let (e, _) = world().await?;
    let topic = watching(&e, "Topic").await?;
    e.set_mission(topic, "Reconcile chargebacks").await?;
    e.ingest(event("thread", "First message", Value::Null))
        .await?;
    let mut next = event("second", "Billing reconciliation", Value::Null);
    next.thread_hint = Some("thread".into());
    e.ingest(next).await?;
    assert_eq!(e.search("recon charge")?[0].subject, Ref::Topic);
    assert!(matches!(e.search("billing")?[0].subject, Ref::Thread(_)));
    Ok(())
}

#[tokio::test]
async fn a_snapshot_covers_a_visible_feed_revision_during_commit_publication() -> Result<()> {
    let (e, _) = world().await?;
    let (topic, _) = e.create_topic("Committed", "").await?;
    let mut next = e.slot(topic)?.draft();
    let changes = next
        .state
        .set_mission("published in SQLite", DateTime::UNIX_EPOCH)?;
    next.revision += 1;
    // The store has committed the feed cursor; the blocking writer has not yet
    // installed the new in-process worker state.
    e.0.store.save(1, &next, None, &changes)?;
    assert_eq!(e.changes_since(1)?.0[0].revision, 2);
    let snapshot = e.snapshot(topic)?;
    assert_eq!(snapshot.revision, 2);
    assert_eq!(snapshot.state.topic.mission, "published in SQLite");
    Ok(())
}

#[tokio::test]
async fn an_old_proposal_without_provider_identity_reports_undeliverable_work() -> Result<()> {
    let (e, _) = world().await?;
    let (topic, _) = e.create_topic("Old work", "").await?;
    let task = id();
    e.update(topic, &Default::default(), |s, now| {
        let mut c = s.state.add_task(task, "Review", Actor::User, None, now)?;
        c.extend(s.state.start(task, "Old agent", now)?);
        c.extend(s.state.submit(task, action(), "Ready", None, now)?);
        Ok(c)
    })
    .await?;
    e.approve(topic, task, None, false).await?;
    e.tick().await?;
    assert!(
        e.topic(topic)?.tasks[0]
            .result
            .as_ref()
            .is_some_and(|s| s.contains("proposing provider"))
    );
    Ok(())
}

#[tokio::test]
async fn a_replayed_file_branch_and_review_survive_restart_and_preserve_both_originals()
-> Result<()> {
    let dir = tempfile::tempdir()?;
    let e = Engine::open(dir.path()).await?;
    let (topic, _) = e.create_topic("Field notes", "").await?;
    let name = "notes";
    let edit = Uuid::new_v4();
    for (base, bytes) in [(0, "original"), (1, "server edit")] {
        e.write_file(topic, name.into(), bytes.into(), id(), Some(base))
            .await?;
    }
    // Stop after the blob append and before the topic writer saved its review.
    let branch = e.blobs().put_based(topic, name, b"offline edit", edit, 1)?;
    assert_eq!(
        (branch.revision.revision, branch.competing_with),
        (3, Some(2))
    );
    assert!(e.topic(topic)?.needs_you().threads.is_empty());
    drop(e);
    let e = Engine::open(dir.path()).await?;
    let review = e.topic(topic)?.threads[0].clone();
    let choose = |current| Suggestion::ChooseFileRevision {
        path: name.into(),
        current,
        candidate: 3,
        use_candidate: true,
    };
    let answer = |current, version| {
        envelope(
            topic,
            Command::Answer {
                thread: review.id,
                expected_review: Some(version),
                suggestion: choose(current),
                task_id: id(),
            },
        )
    };
    let stale = answer(2, review.review_version);
    drop(e);
    let e = Engine::open(dir.path()).await?;
    e.write_file(topic, name.into(), b"offline edit".to_vec(), edit, Some(1))
        .await?;
    assert_eq!(e.topic(topic)?.threads.len(), 1);
    e.write_file(
        topic,
        name.into(),
        b"newer server edit".to_vec(),
        id(),
        Some(2),
    )
    .await?;
    assert!(e.apply(stale).await.is_err());
    let approved = answer(4, e.topic(topic)?.threads[0].review_version);
    e.apply(approved.clone()).await?;
    drop(e);
    let e = Engine::open(dir.path()).await?;
    e.apply(approved).await?;
    e.write_file(topic, name.into(), b"offline edit".to_vec(), edit, Some(1))
        .await?;
    assert!(e.topic(topic)?.needs_you().threads.is_empty());
    let versions = e.blobs().history(topic, name)?;
    assert_eq!(
        versions
            .iter()
            .map(|v| v.bytes.as_slice())
            .collect::<Vec<_>>(),
        [
            "original",
            "server edit",
            "offline edit",
            "newer server edit",
            "offline edit"
        ]
        .map(str::as_bytes)
    );
    assert_eq!(e.blobs().get(topic, name, None)?.unwrap(), versions[4]);
    let equal = e
        .write_file(topic, name.into(), b"offline edit".to_vec(), id(), Some(1))
        .await?;
    assert!(equal.competing_with.is_none());
    assert_eq!(e.topic(topic)?.threads.len(), 1);
    Ok(())
}

#[tokio::test]
async fn disputed_proposals_resume_only_for_surviving_evidence_after_restart() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let open = || async {
        Engine::with_clock(
            Arc::new(SqliteStore::open(dir.path())?),
            limits(),
            Arc::new(FixtureAgent::default()),
            Arc::new(FixtureSorter),
            clock.clone(),
        )
        .await
    };
    let e = open().await?;
    let (topic, _) = e.create_topic("Collection cutoff", "").await?;
    let first = id();
    let second = id();
    for (id, text) in [(first, "16:00"), (second, "17:00")] {
        e.add_fact(
            topic,
            Fact {
                id,
                text: text.into(),
                provenance: Provenance {
                    origin: None,
                    author: "Carrier".into(),
                    via: "Notice".into(),
                    at: DateTime::UNIX_EPOCH,
                    thread: None,
                },
                superseded_by: None,
                invalidated_by: None,
                withdrawn_at: None,
            },
        )
        .await?;
    }
    e.add_rule(topic, "Allow sending", RuleEffect::Allow(action().kind))
        .await?;
    let review = id();
    let choice = Suggestion::ResolveFacts {
        changed: first,
        other: second,
        resolution: FactResolution::KeepChanged,
    };
    let tasks: [TaskId; 4] = std::array::from_fn(|_| id());
    e.update(topic, &Default::default(), |s, now| {
        let mut changes = s.state.receive(
            Message {
                id: id(),
                producer: Producer::System,
                origin: Some(Source::Topic(topic).into_origin("System 1".into(), now, None)),
                author: "System 1".into(),
                text: "Which cutoff applies?".into(),
                at: now,
                external_id: None,
            },
            "fact-review/conflicting-notices",
            review,
            now,
        )?;
        changes.extend(s.state.sort(
            review,
            Decision::Ask {
                summary: "Conflicting notices".into(),
                reason: "Choose a cutoff".into(),
                suggestions: vec![choice.clone()],
            },
            now,
        )?);
        for (task, deps) in
            tasks
                .into_iter()
                .zip([Some(vec![first]), Some(vec![second]), None, Some(vec![])])
        {
            let mut proposed = action();
            proposed.depends_on_facts = deps;
            changes.extend(
                s.state
                    .add_task(task, "Notify carrier", Actor::Agent, None, now)?,
            );
            changes.extend(s.state.start(task, "Preparing reply", now)?);
            s.proposals
                .insert(task, effects::Proposer::Agent(RunHandle(json!({}))));
            changes.extend(commands::submission(
                s,
                task,
                proposed,
                "Ready".into(),
                None,
                now,
            )?);
        }
        Ok(changes)
    })
    .await?;
    assert_eq!(
        e.topic(topic)?.disputed_facts(),
        BTreeSet::from([first, second])
    );
    assert!(matches!(
        e.approve(topic, tasks[0], None, false).await,
        Err(Error::Topic(TopicError::DisputedEvidence))
    ));
    e.deliver_effects(topic).await?;
    let before = e.topic(topic)?;
    assert_eq!(
        before.tasks.iter().map(|t| t.column).collect::<Vec<_>>(),
        [
            Column::NeedsYou,
            Column::NeedsYou,
            Column::NeedsYou,
            Column::Done
        ]
    );
    assert_eq!(
        before.tasks[3].result.as_deref(),
        Some("Approved action dispatched.")
    );
    drop(e);
    let e = open().await?;
    e.answer(topic, review, choice).await?;
    e.deliver_effects(topic).await?;
    let state = e.topic(topic)?;
    assert!(state.disputed_facts().is_empty());
    assert_eq!(
        state.tasks.iter().map(|t| t.column).collect::<Vec<_>>(),
        [Column::Done, Column::NeedsYou, Column::Done, Column::Done]
    );
    assert_eq!(
        state.tasks[0].result.as_deref(),
        Some("Approved action dispatched.")
    );
    assert!(
        matches!(e.approve(topic,tasks[1],None,false).await,Err(Error::Topic(TopicError::RetiredEvidence(loser))) if loser == second)
    );
    Ok(())
}

#[tokio::test]
async fn retention_keeps_latest_snapshots_and_bounds_receipt_replay() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let store = Arc::new(SqliteStore::open(dir.path())?);
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH + TimeDelta::days(2)));
    let e = Engine::with_clock(
        store.clone(),
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let t = watching(&e, "Retained").await?;
    let other = watching(&e, "Other").await?;
    let past = clock.now() - TimeDelta::days(1);
    for issued in [past, clock.now() + TimeDelta::days(1)] {
        let mut cmd = envelope(
            t,
            Command::SetMission {
                mission: issued.to_string(),
            },
        );
        cmd.issued_at = issued;
        let key = cmd.id;
        e.apply(cmd).await?;
        assert_eq!(e.topic(t)?.activity.last().unwrap().at, clock.now());
        assert!(
            store
                .receipt(key)?
                .is_some_and(|receipt| receipt.issued_at == issued.min(clock.now()))
        );
    }
    store.record_seen("fixture", "old")?;
    let db = Database::open(dir.path().join("topics.sqlite"))?;
    db.execute_batch("UPDATE topic_revisions SET committed_at=unixepoch('now','-8 days'); UPDATE records SET updated_ms=0 WHERE kind='engine/command' OR kind GLOB 'ingest/seen/*'")?;
    let fresh = envelope(
        t,
        Command::SetMission {
            mission: "current".into(),
        },
    );
    e.apply(fresh.clone()).await?;
    store.maintain()?;
    assert_eq!(store.revision_page(0, 100)?.len(), 3);
    let bootstrap = store.bootstrap_page(0, 100)?;
    assert_eq!(bootstrap.len(), 2);
    assert_eq!(bootstrap[0].1.topic, other);
    assert_eq!(bootstrap[1].1.revision, e.snapshot(t)?.revision);
    assert!(store.receipt(fresh.id)?.is_some());
    assert!(!store.seen("fixture", "old")?);
    Ok(())
}

#[tokio::test]
async fn undo_restores_removed_context_and_expires_removed_rules_after_thirty_days() -> Result<()> {
    let (e, clock) = world().await?;
    let (t, _) = e.create_topic("Undo", "").await?;
    e.add_rule(t, "Review", RuleEffect::Ask(ActionKind("publish".into())))
        .await?;
    e.add_rule(t, "Refuse", RuleEffect::Deny(ActionKind("publish".into())))
        .await?;
    let rules = e.topic(t)?.topic.rules;
    let rule = rules[0].id;
    let fact = Fact {
        id: id(),
        text: "Launch Friday".into(),
        provenance: Provenance {
            author: "You".into(),
            via: "Note".into(),
            at: clock.now(),
            thread: None,
            origin: None,
        },
        superseded_by: None,
        invalidated_by: None,
        withdrawn_at: None,
    };
    e.add_fact(t, fact.clone()).await?;
    e.remove_fact(t, fact.id).await?;
    e.command(t, Command::RemoveRule { rule }).await?;
    e.command(t, Command::RestoreFact { fact: fact.id }).await?;
    e.command(t, Command::RestoreRule { rule }).await?;
    assert_eq!(e.topic(t)?.topic.facts, [fact]);
    assert_eq!(e.topic(t)?.topic.rules, rules);
    e.command(t, Command::RemoveRule { rule }).await?;
    clock.advance(chrono::TimeDelta::days(30));
    assert!(e.command(t, Command::RestoreRule { rule }).await.is_err());
    Ok(())
}

#[tokio::test]
async fn stalled_file_write_allows_topic_edits_and_finishes_before_purge() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let engine = Engine::open(dir.path()).await?;
    let (topic, _) = engine.create_topic("Files", "Initial mission").await?;
    engine
        .write_file(topic, "notes".into(), vec![1], Uuid::new_v4(), None)
        .await?;
    let entry = std::fs::read_dir(dir.path().join("files").join(topic.to_string()))?
        .next()
        .context("missing file directory")??;
    let lock = std::fs::File::open(entry.path().join("write.lock"))?;
    lock.lock()?;
    let uploading = engine.clone();
    let upload = tokio::spawn(async move {
        uploading
            .write_file(topic, "notes".into(), vec![2], Uuid::new_v4(), None)
            .await
    });
    let slot = engine.slot(topic)?;
    tokio::time::timeout(std::time::Duration::from_secs(3), async {
        while slot.files.try_lock().is_ok() {
            tokio::task::yield_now().await;
        }
        engine.set_mission(topic, "Updated during upload").await
    })
    .await
    .context("topic edit stalled behind file I/O")??;
    upload.abort();
    let deleting = engine.clone();
    let deletion = tokio::spawn(async move { deleting.command(topic, Command::DeleteTopic).await });
    drop(lock);
    deletion.await.context("deletion interrupted")??;
    assert!(engine.blobs().names(topic)?.is_empty());
    engine.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn topic_created_without_sort_stays_opted_out_after_restart() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let engine = Engine::open(dir.path()).await?;
    let topic = id();
    let create = envelope(
        topic,
        Command::CreateTopicWithoutSort {
            name: "No automatic sort".into(),
            mission: "Keep the mission".into(),
        },
    );
    engine.apply(create.clone()).await?;
    {
        let slot = engine.slot(topic)?;
        let saved = slot.saved.read();
        assert!(saved.default_sort_removed);
        assert!(saved.default_sort_request.is_none());
    }
    drop(engine);
    let engine = Engine::open(dir.path()).await?;
    engine.apply(create).await?;
    let slot = engine.slot(topic)?;
    let saved = slot.saved.read();
    assert!(saved.default_sort_removed);
    assert!(saved.default_sort_request.is_none());
    Ok(())
}

#[tokio::test]
async fn passive_context_survives_restart_without_watching_or_provisioning() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let engine = open_at_epoch(dir.path()).await?;
    let (topic, _) = engine.create_topic("Passive", "Use this reference").await?;
    let reference = watch();
    engine
        .apply(envelope(
            topic,
            Command::SetContextSources {
                sources: vec![reference.clone()],
            },
        ))
        .await?;
    assert!(!engine.default_sort_pending(topic)?);
    assert_eq!(
        engine.topic(topic)?.topic.context_sources,
        vec![reference.clone()]
    );
    assert_eq!(engine.topic(topic)?.topic.watches().count(), 0);
    engine
        .ingest(event("passive", "should not route", Value::Null))
        .await?;
    assert!(engine.topic(topic)?.threads.is_empty());
    drop(engine);
    let engine = open_at_epoch(dir.path()).await?;
    assert_eq!(engine.topic(topic)?.topic.context_sources, vec![reference]);
    assert_eq!(engine.topic(topic)?.topic.watches().count(), 0);
    assert!(!engine.default_sort_pending(topic)?);
    Ok(())
}
