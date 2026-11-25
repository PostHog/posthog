mod support;

use anyhow::{Context, Result};
use meep_client::{Client, Event, Status, TransportError};
use meep_topic::{Column, Command, TaskId, ThreadId, TopicId};
use meep_wire::{ConnectionGrant, NeedsYouItem};
use std::{sync::atomic::Ordering::SeqCst, time::Duration};
use support::Server;
use tempfile::TempDir;
use tokio::{sync::broadcast, task::JoinHandle, time::timeout};
use uuid::Uuid;

async fn setup() -> Result<(TempDir, Server, Client)> {
    let dir = tempfile::tempdir()?;
    let server = Server::start().await?;
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    Ok((dir, server, client))
}

fn create(client: &Client) -> Result<TopicId> {
    let topic = TopicId(Uuid::new_v4());
    client.issue(
        topic,
        Command::CreateTopic {
            name: "Payments".into(),
            mission: "Resolve escalations".into(),
        },
    )?;
    Ok(topic)
}

fn add(client: &Client, topic: TopicId, title: &str) -> Result<TaskId> {
    let id = TaskId(Uuid::new_v4());
    client.issue(
        topic,
        Command::AddTask {
            id,
            title: title.into(),
        },
    )?;
    Ok(id)
}

async fn next_event(
    events: &mut broadcast::Receiver<Event>,
    predicate: impl Fn(&Event) -> bool,
) -> Result<Event> {
    timeout(Duration::from_secs(5), async {
        loop {
            let event = events.recv().await?;
            if predicate(&event) {
                return Ok(event);
            }
        }
    })
    .await?
}

struct Running(JoinHandle<Result<()>>);
impl Drop for Running {
    fn drop(&mut self) {
        self.0.abort();
    }
}

fn run(client: &Client) -> Running {
    let client = client.clone();
    Running(tokio::spawn(async move { client.run().await }))
}

#[tokio::test]
async fn a_failed_index_write_rolls_back_the_offline_edit_and_outbox() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let db = rusqlite::Connection::open(dir.path().join("replica.sqlite"))?;
    db.execute_batch("CREATE TRIGGER disk_full BEFORE INSERT ON search_documents BEGIN SELECT RAISE(ABORT,'disk full'); END;")?;
    assert!(create(&client).is_err());
    assert!(client.topics()?.is_empty());
    assert!(client.search("payments", 4)?.hits.is_empty());
    db.execute_batch("DROP TRIGGER disk_full")?;
    client.sync_once().await?;
    assert!(server.app.engine.topic_ids().is_empty());
    Ok(())
}

#[tokio::test]
async fn a_failed_pull_resumes_from_the_same_cursor_after_reopen() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let path = dir.path().join("replica.sqlite");
    client.sync_once().await?;
    let (topic, _) = server.app.engine.create_topic("Remote", "").await?;
    let db = rusqlite::Connection::open(&path)?;
    db.execute_batch("CREATE TRIGGER interrupt BEFORE INSERT ON records WHEN new.id='cursor' BEGIN SELECT RAISE(ABORT,'interrupted'); END;")?;
    assert!(client.sync_once().await.is_err());
    assert!(client.topic(topic)?.is_none());
    drop(client);
    db.execute_batch("DROP TRIGGER interrupt")?;
    let client = server.client(&path)?;
    client.sync_once().await?;
    assert!(client.topic(topic)?.is_some());
    assert!(server.app.cursors.lock().ends_with(&[0, 0]));
    Ok(())
}

#[tokio::test]
async fn offline_edits_are_visible_and_searchable_before_the_first_request() -> Result<()> {
    let (_dir, server, client) = setup().await?;
    server.app.offline.store(true, SeqCst);
    let mut events = client.subscribe();
    let topic = create(&client)?;
    let task = add(&client, topic, "Reconcile chargebacks")?;
    let changes = client.issue(
        topic,
        Command::MoveTask {
            task,
            column: Column::NeedsYou,
        },
    )?;
    assert!(!changes.is_empty());
    assert_eq!(client.topics()?.len(), 1);
    assert_eq!(
        client.topic(topic)?.context("visible")?.tasks[0].column,
        Column::NeedsYou
    );
    assert!(
        matches!(&client.needs_you()?.items[..], [NeedsYouItem::Approve { task: id, .. }] if id == &task.to_string())
    );
    assert_eq!(client.search("charge", 5)?.hits[0].id, task.to_string());
    assert_eq!(client.search("escalat", 1)?.hits[0].kind, "topic");
    assert!(server.app.engine.topics().is_empty());
    assert_eq!(server.app.requests.load(SeqCst), 0);
    assert_eq!(events.try_recv()?, Event::TopicChanged(topic));
    assert!(client.sync_once().await.is_err());
    assert!(matches!(
        client.status(),
        Status::Offline { pending: 3, .. }
    ));

    server.app.offline.store(false, SeqCst);
    client.sync_once().await?;
    assert_eq!(client.status(), Status::Online);
    assert_eq!(client.topic(topic)?, Some(server.app.engine.topic(topic)?));
    assert_eq!(
        server.app.engine.topic(topic)?.tasks[0].column,
        Column::NeedsYou
    );
    Ok(())
}

#[tokio::test]
async fn invalid_local_transition_changes_neither_database_outbox_nor_events() -> Result<()> {
    let (_dir, server, client) = setup().await?;
    let topic = create(&client)?;
    let before = client.topic(topic)?;
    let mut events = client.subscribe();
    let error = client
        .issue(
            topic,
            Command::Reply {
                thread: ThreadId(Uuid::new_v4()),
                text: "should never appear".into(),
            },
        )
        .unwrap_err();
    assert!(error.downcast_ref::<meep_topic::TopicError>().is_some());
    assert_eq!(client.topic(topic)?, before);
    assert!(matches!(
        client.status(),
        Status::Offline { pending: 1, .. }
    ));
    assert!(matches!(
        events.try_recv(),
        Err(broadcast::error::TryRecvError::Empty)
    ));
    assert!(client.search("never", 3)?.hits.is_empty());
    client.sync_once().await?;
    assert_eq!(server.app.batches.lock()[0].len(), 1);
    Ok(())
}

#[tokio::test]
async fn committed_command_with_a_lost_response_is_repushed_with_the_same_identity() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    let task = add(&client, topic, "Track the retry")?;
    server.app.lose_receipt.store(true, SeqCst);
    assert!(client.sync_once().await.is_err());
    let committed = server.app.engine.snapshot(topic)?;
    assert_eq!(committed.state.tasks[0].id, task);
    drop(client);
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    assert!(matches!(
        client.status(),
        Status::Offline { pending: 1, .. }
    ));
    client.sync_once().await?;
    let batches = server.app.batches.lock();
    assert_eq!(batches.len(), 3);
    assert_eq!(batches[1], batches[2]);
    assert_eq!(
        server.app.engine.snapshot(topic)?.revision,
        committed.revision
    );
    assert_eq!(client.topic(topic)?, Some(committed.state));
    Ok(())
}

#[tokio::test]
async fn snapshot_failure_after_receipt_preserves_the_overlay_across_restart() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    server.app.fail_snapshot.store(true, SeqCst);
    assert!(client.sync_once().await.is_err());
    drop(client);
    let reopened = server.client(&dir.path().join("replica.sqlite"))?;
    assert_eq!(reopened.search("escalations", 2)?.hits.len(), 1);
    assert!(matches!(
        reopened.status(),
        Status::Offline { pending: 1, .. }
    ));
    reopened.sync_once().await?;
    assert_eq!(
        reopened.topic(topic)?,
        Some(server.app.engine.topic(topic)?)
    );
    Ok(())
}

#[tokio::test]
async fn a_server_revision_rebases_an_edit_issued_during_pull() -> Result<()> {
    let (_dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    server
        .app
        .engine
        .set_mission(topic, "Implement refunds")
        .await?;
    let (started, resume) = server.pause_next_pull();
    let other = client.clone();
    let sync = tokio::spawn(async move { other.sync_once().await });
    timeout(Duration::from_secs(5), started).await??;
    let task = add(&client, topic, "Investigate dispute")?;
    resume.send(()).expect("pull awaiting release");
    sync.await??;

    let visible = client.topic(topic)?.context("visible")?;
    assert_eq!(visible.topic.mission, "Implement refunds");
    assert_eq!(visible.tasks[0].id, task);
    assert!(server.app.engine.topic(topic)?.tasks.is_empty());
    assert!(client.search("escalations", 3)?.hits.is_empty());
    assert_eq!(client.search("dispute", 3)?.hits[0].id, task.to_string());
    client.sync_once().await?;
    assert_eq!(client.topic(topic)?, Some(server.app.engine.topic(topic)?));
    Ok(())
}

#[tokio::test]
async fn rejection_reports_the_envelope_and_replaces_the_optimistic_search_result() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    let task = add(&client, topic, "Obsolete local estimate")?;
    server
        .app
        .engine
        .apply(meep_topic::Envelope {
            topic,
            id: Uuid::new_v4().into(),
            issued_at: chrono::Utc::now(),
            command: Command::AddTask {
                id: task,
                title: "Canonical server estimate".into(),
            },
        })
        .await?;
    let kept = add(&client, topic, "Independent work")?;
    let mut events = client.subscribe();
    client.sync_once().await?;
    let rejected = next_event(&mut events, |e| matches!(e, Event::Rejected { .. })).await?;
    let batches = server.app.batches.lock().clone();
    assert!(
        matches!(rejected, Event::Rejected { command, reason } if command == batches[1][0].id && reason.contains(&task.to_string()))
    );
    let reopened = server.client(&dir.path().join("replica.sqlite"))?;
    let unread = reopened.rejections()?;
    assert_eq!(unread.len(), 1);
    assert_eq!(unread[0].0, batches[1][0].id);
    reopened.dismiss_rejection(unread[0].0)?;
    assert!(client.rejections()?.is_empty());
    assert!(client.search("obsolete", 2)?.hits.is_empty());
    assert_eq!(client.search("canonical", 1)?.hits.len(), 1);
    assert_eq!(
        client.search("independent", 1)?.hits[0].id,
        kept.to_string()
    );
    assert_eq!(client.topic(topic)?, Some(server.app.engine.topic(topic)?));
    client.sync_once().await?;
    assert_eq!(server.app.batches.lock().len(), 2);
    Ok(())
}

#[tokio::test]
async fn restart_resumes_the_cursor_and_pending_commands_without_a_network_read() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    let cursor = server.app.engine.changes_since(0)?.1;
    let task = add(&client, topic, "Persist my draft")?;
    let requests = server.app.requests.load(SeqCst);
    drop(client);

    let client = server.client(&dir.path().join("replica.sqlite"))?;
    assert_eq!(client.topic(topic)?.context("visible")?.tasks[0].id, task);
    assert_eq!(client.search("draft", 2)?.hits[0].id, task.to_string());
    assert_eq!(server.app.requests.load(SeqCst), requests);
    assert!(matches!(
        client.status(),
        Status::Offline { pending: 1, .. }
    ));
    server.app.cursors.lock().clear();
    server
        .app
        .engine
        .set_mission(topic, "Server work while closed")
        .await?;
    client.sync_once().await?;
    assert_eq!(server.app.cursors.lock()[0], cursor);
    assert_eq!(client.topic(topic)?, Some(server.app.engine.topic(topic)?));
    Ok(())
}

#[tokio::test]
async fn live_revision_wakes_the_idle_replica_and_pulls_from_its_committed_cursor() -> Result<()> {
    let (_dir, server, client) = setup().await?;
    let (topic, _) = server.app.engine.create_topic("People", "Recruit").await?;
    client.sync_once().await?;
    let before = server.app.engine.changes_since(0)?.1;
    let mut stream = server.app.stream_cursor.subscribe();
    let _running = run(&client);
    timeout(
        Duration::from_secs(5),
        stream.wait_for(|c| *c == Some(before)),
    )
    .await??;
    let mut notifications = client.subscribe();
    server
        .app
        .engine
        .set_mission(topic, "Delivered over live feed")
        .await?;
    next_event(&mut notifications, |e| e == &Event::TopicChanged(topic)).await?;
    assert_eq!(
        client.topic(topic)?.context("visible")?.topic.mission,
        "Delivered over live feed"
    );
    assert_eq!(
        *server.app.cursors.lock().last().context("pull cursor")?,
        before
    );
    Ok(())
}

#[tokio::test]
async fn status_reports_offline_since_and_pending_and_recovers_from_unauthorized_on_wake()
-> Result<()> {
    let (_dir, server, client) = setup().await?;
    let mut events = client.subscribe();
    server.app.offline.store(true, SeqCst);
    let _running = run(&client);
    next_event(&mut events, |e| e == &Event::Status(Status::Syncing)).await?;
    let offline = next_event(&mut events, |e| {
        matches!(e, Event::Status(Status::Offline { pending: 0, .. }))
    })
    .await?;
    let Event::Status(Status::Offline { since, .. }) = offline else {
        unreachable!()
    };
    let topic = create(&client)?;
    next_event(
        &mut events,
        |e| matches!(e, Event::Status(Status::Offline {since: s,pending: 1}) if *s == since),
    )
    .await?;
    server.app.offline.store(false, SeqCst);
    server.app.unauthorized.store(true, SeqCst);
    client.sync_now();
    next_event(&mut events, |e| e == &Event::Status(Status::Unauthorized)).await?;
    assert!(client.topic(topic)?.is_some());
    server.app.unauthorized.store(false, SeqCst);
    client.sync_now();
    next_event(&mut events, |e| e == &Event::Status(Status::Online)).await?;
    assert_eq!(client.topic(topic)?, Some(server.app.engine.topic(topic)?));
    Ok(())
}

#[tokio::test]
async fn file_cache_is_revisioned_scoped_by_topic_and_survives_reopen_and_outage() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let first = create(&client)?;
    let other = create(&client)?;
    client.sync_once().await?;
    let path = "notes/100% #résumé?.md";
    let written = client.put_file(first, path, vec![0, 255, 7]).await?;
    assert_eq!(written.bytes, [0, 255, 7]);
    assert_eq!(written.revision, 1);
    server.app.engine.blobs().put(first, path, &[0, 1])?;
    let second = client.get_file(first, path).await?;
    assert_eq!((second.revision, second.bytes.as_slice()), (2, &[0, 1][..]));
    client.put_file(other, path, vec![]).await?;
    let err = client.get_file(first, "../connections").await.unwrap_err();
    assert!(matches!(
        err.downcast_ref::<TransportError>(),
        Some(TransportError::Protocol(_))
    ));
    drop(client);
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    server.app.offline.store(true, SeqCst);
    assert_eq!(client.get_file(first, path).await?, second);
    assert!(
        client
            .cached_file(other, path)?
            .context("cache")?
            .bytes
            .is_empty()
    );
    assert!(client.get_file(other, "missing").await.is_err());
    server.app.offline.store(false, SeqCst);
    server.app.unauthorized.store(true, SeqCst);
    assert!(matches!(
        client
            .get_file(first, path)
            .await
            .unwrap_err()
            .downcast_ref::<TransportError>(),
        Some(TransportError::Unauthorized)
    ));
    Ok(())
}

#[tokio::test]
async fn connection_grants_and_health_are_available_to_offline_attention_queries() -> Result<()> {
    let (_dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    let grant = ConnectionGrant {
        kind: "chat".into(),
        label: "Chat".into(),
        account: Some("me".into()),
        secrets: Default::default(),
        grants: vec![topic],
    };
    let info = client.put_connection("chat", &grant).await?;
    assert_eq!(client.connections()?.connections, [info]);
    server
        .app
        .engine
        .add_connection(meep_connections::Connection {
            unrouted: 0,
            id: "mail".into(),
            kind: "mail".into(),
            label: "Mail".into(),
            account: "me".into(),
            grants: vec![topic],
            health: meep_connections::Health::Expired {
                since: chrono::DateTime::UNIX_EPOCH,
                detail: "Sign in to Mail".into(),
            },
        })?;
    let task = add(&client, topic, "Review now")?;
    client.issue(
        topic,
        Command::MoveTask {
            task,
            column: Column::NeedsYou,
        },
    )?;
    client.sync_once().await?;
    let items = client.needs_you()?.items;
    assert!(matches!(
        &items[..],
        [NeedsYouItem::Approve { .. }, NeedsYouItem::Problem { .. }]
    ));
    client.issue(
        topic,
        Command::MoveTask {
            task,
            column: Column::Done,
        },
    )?;
    server.app.offline.store(true, SeqCst);
    let before = server.app.requests.load(SeqCst);
    assert_eq!(client.connections()?.connections.len(), 2);
    assert!(
        matches!(&client.needs_you()?.items[..], [NeedsYouItem::Problem {topics, connection, title,detail}]
        if topics == &[topic] && connection == "mail" && title == "Sign in to Mail again" && detail == "Sign in to Mail")
    );
    assert_eq!(before, server.app.requests.load(SeqCst));
    Ok(())
}

#[tokio::test]
async fn a_rejected_sibling_is_removed_even_when_the_accepted_snapshot_is_unavailable() -> Result<()>
{
    let (_dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    client.issue(
        topic,
        Command::Reconnect {
            connection: "missing".into(),
        },
    )?;
    add(&client, topic, "Keep this pending")?;
    let mut events = client.subscribe();
    server.app.fail_snapshot.store(true, SeqCst);
    assert!(client.sync_once().await.is_err());
    let rejected = next_event(&mut events, |e| matches!(e, Event::Rejected { .. })).await?;
    let first_attempt = server.app.batches.lock()[1].clone();
    assert!(matches!(rejected, Event::Rejected {command,..} if command == first_attempt[0].id));
    assert!(matches!(
        client.status(),
        Status::Offline { pending: 1, .. }
    ));
    assert_eq!(client.search("pending", 1)?.hits.len(), 1);
    client.sync_once().await?;
    assert_eq!(server.app.batches.lock()[2], first_attempt[1..]);
    Ok(())
}

#[tokio::test]
async fn an_offline_loop_retries_and_pulls_server_work_without_a_manual_wake() -> Result<()> {
    let (_dir, server, client) = setup().await?;
    let (topic, _) = server
        .app
        .engine
        .create_topic("Projects", "Deliver")
        .await?;
    server.app.offline.store(true, SeqCst);
    let mut events = client.subscribe();
    let _running = run(&client);
    next_event(&mut events, |e| {
        matches!(e, Event::Status(Status::Offline { .. }))
    })
    .await?;
    server.app.offline.store(false, SeqCst);
    next_event(&mut events, |e| *e == Event::Status(Status::Online)).await?;
    assert_eq!(client.topic(topic)?, Some(server.app.engine.topic(topic)?));
    Ok(())
}

#[tokio::test]
async fn an_offline_file_edit_survives_reopen_and_uploads_once() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    server.app.offline.store(true, SeqCst);
    let file = client.put_file(topic, "note", b"offline".to_vec()).await?;
    assert_eq!(file.bytes, b"offline");
    drop(client);
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    assert_eq!(client.get_file(topic, "note").await?.bytes, b"offline");
    server.app.offline.store(false, SeqCst);
    client.sync_once().await?;
    client.sync_once().await?;
    assert_eq!(server.app.engine.blobs().history(topic, "note")?.len(), 1);
    assert_eq!(client.get_file(topic, "note").await?.revision, 1);
    Ok(())
}

#[tokio::test]
async fn a_replica_reader_can_hold_a_snapshot_while_an_edit_commits() -> Result<()> {
    let (dir, _, client) = setup().await?;
    let reader = rusqlite::Connection::open(dir.path().join("replica.sqlite"))?;
    reader.execute_batch("BEGIN; SELECT * FROM client_outbox")?;
    create(&client)?;
    assert_eq!(
        reader.query_row("SELECT count(*) FROM client_outbox", [], |r| r
            .get::<_, i64>(0))?,
        0
    );
    Ok(())
}

#[tokio::test]
async fn edits_files_and_workflow_switches_for_a_rejected_creation_never_reach_the_other_topic()
-> Result<()> {
    let (_dir, server, client) = setup().await?;
    let topic = create(&client)?;
    server
        .app
        .engine
        .apply(meep_topic::Envelope {
            id: Uuid::new_v4().into(),
            topic,
            issued_at: chrono::Utc::now(),
            command: Command::CreateTopic {
                name: "Other".into(),
                mission: "".into(),
            },
        })
        .await?;
    add(&client, topic, "Private task")?;
    client.issue(
        topic,
        Command::SetRoutine {
            routine: meep_topic::RoutineBinding {
                watches: vec![],
                id: "review".into(),
                backend: "posthog".into(),
                external_id: "1".into(),
                name: "Review".into(),
                trigger: "manual".into(),
            },
        },
    )?;
    client.set_workflow_enabled(topic, "review", true)?;
    client.put_file(topic, "draft", b"private".to_vec()).await?;
    assert!(matches!(
        client.status(),
        Status::Offline { pending: 5, .. }
    ));
    client.sync_once().await?;
    assert!(server.app.engine.blobs().list(topic)?.is_empty());
    assert!(client.cached_file(topic, "draft")?.is_none());
    assert!(server.app.engine.topic(topic)?.tasks.is_empty());
    assert!(
        server
            .app
            .engine
            .topic(topic)?
            .topic
            .routines
            .iter()
            .all(|r| r.binding.backend == "system")
    );
    assert_eq!(client.rejections()?.len(), 5);
    let mut recovered = Vec::new();
    for (id, _) in client.rejections()? {
        if let Some(path) = client.rejected_file_path(id)? {
            recovered.push((path, client.rejected_file_bytes(id)?));
        }
    }
    assert_eq!(recovered, [("draft".into(), b"private".to_vec())]);
    Ok(())
}

#[tokio::test]
async fn a_refused_upload_reports_the_reason_even_when_an_old_revision_is_cached() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    let old = client.put_file(topic, "plan", b"original".to_vec()).await?;
    server.app.reject_upload.store(true, SeqCst);
    let error = client
        .put_file(topic, "plan", b"edit".to_vec())
        .await
        .expect_err("refused write");
    assert!(error.to_string().contains("File is read-only"));
    assert_eq!(client.cached_file(topic, "plan")?, Some(old));
    drop(client);
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    client.clear_replica_cache().await?;
    let rejected = client.rejections()?;
    assert_eq!(rejected.len(), 1);
    let id = rejected[0].0;
    assert_eq!(client.rejected_file_path(id)?.as_deref(), Some("plan"));
    assert_eq!(client.rejected_file_bytes(id)?, b"edit");
    client.dismiss_rejection(id)?;
    assert!(client.rejected_file_path(id)?.is_none());
    Ok(())
}

#[tokio::test]
async fn an_offline_approval_cannot_complete_a_reopened_task() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    let task = add(&client, topic, "Review timetable")?;
    client.issue(
        topic,
        Command::MoveTask {
            task,
            column: Column::NeedsYou,
        },
    )?;
    client.sync_once().await?;
    client.issue(
        topic,
        Command::Approve {
            task,
            expected_review: None,
            edited_draft: None,
            always: false,
            rule_id: Uuid::new_v4().into(),
        },
    )?;
    assert_eq!(client.topic(topic)?.unwrap().tasks[0].column, Column::Done);
    drop(client);
    server
        .app
        .engine
        .move_task(topic, task, Column::InProgress)
        .await?;
    server
        .app
        .engine
        .move_task(topic, task, Column::NeedsYou)
        .await?;
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    let mut events = client.subscribe();
    client.sync_once().await?;
    let rejection =
        next_event(&mut events, |event| matches!(event, Event::Rejected { .. })).await?;
    assert!(
        matches!(rejection, Event::Rejected {reason, ..} if reason.contains("review has changed"))
    );
    assert_eq!(
        client.topic(topic)?.unwrap().tasks[0].column,
        Column::NeedsYou
    );
    client.issue(
        topic,
        Command::Approve {
            task,
            expected_review: None,
            edited_draft: None,
            always: false,
            rule_id: Uuid::new_v4().into(),
        },
    )?;
    client.sync_once().await?;
    assert_eq!(
        server.app.engine.topic(topic)?.tasks[0].column,
        Column::Done
    );
    Ok(())
}

#[tokio::test]
async fn two_offline_replicas_keep_both_edits_until_a_shared_choice() -> Result<()> {
    use meep_topic::ThreadState;
    let (dir, server, first) = setup().await?;
    let second = server.client(&dir.path().join("other.sqlite"))?;
    let topic = create(&first)?;
    first.sync_once().await?;
    first.put_file(topic, "note", b"original".to_vec()).await?;
    second.sync_once().await?;
    assert_eq!(second.get_file(topic, "note").await?.revision, 1);
    server.app.offline.store(true, SeqCst);
    first.put_file(topic, "note", b"first".to_vec()).await?;
    second.put_file(topic, "note", b"second".to_vec()).await?;
    drop(second);
    let second = server.client(&dir.path().join("other.sqlite"))?;
    server.app.offline.store(false, SeqCst);
    first.sync_once().await?;
    second.sync_once().await?;
    first.sync_once().await?;
    let state = first.topic(topic)?.unwrap();
    let thread = &state.threads[0];
    let ThreadState::NeedsYou { suggestions, .. } = &thread.state else {
        panic!("missing file review")
    };
    assert_eq!(second.cached_file(topic, "note")?.unwrap().bytes, b"first");
    assert_eq!(first.get_file_at(topic, "note", 3).await?.bytes, b"second");
    assert_eq!(first.get_file_at(topic, "note", 2).await?.bytes, b"first");
    first.issue(
        topic,
        Command::Answer {
            thread: thread.id,
            expected_review: Some(thread.review_version),
            suggestion: suggestions[1].clone(),
            task_id: Uuid::new_v4().into(),
        },
    )?;
    first.sync_once().await?;
    second.sync_once().await?;
    assert!(second.topic(topic)?.unwrap().needs_you().threads.is_empty());
    assert_eq!(first.get_file(topic, "note").await?.revision, 4);
    assert_eq!(second.get_file(topic, "note").await?.bytes, b"second");
    // An editor may still be showing an older revision after a background refresh.
    first
        .put_file_from_revision(topic, "note", b"older editor".to_vec(), 1)
        .await?;
    first.sync_once().await?;
    assert_eq!(server.app.engine.topic(topic)?.needs_you().threads.len(), 1);
    assert_eq!(first.get_file(topic, "note").await?.bytes, b"second");
    Ok(())
}

#[tokio::test]
async fn a_retrying_creation_keeps_dependent_edits_and_pulls_other_topics() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let local = create(&client)?;
    add(&client, local, "Offline work")?;
    let (remote, _) = server.app.engine.create_topic("Other device", "").await?;
    server.app.retry_next.store(true, SeqCst);
    client.sync_once().await?;
    assert!(server.app.engine.topic(local).is_err());
    assert!(client.topic(remote)?.is_some());
    assert_eq!(client.topic(local)?.unwrap().tasks.len(), 1);
    let db = rusqlite::Connection::open(dir.path().join("replica.sqlite"))?;
    db.execute("UPDATE client_command_retry SET due=unixepoch()+60", [])?;
    client.sync_once().await?;
    assert_eq!(server.app.batches.lock().len(), 1);
    db.execute("UPDATE client_command_retry SET due=0", [])?;
    client.sync_once().await?;
    assert_eq!(server.app.engine.topic(local)?.tasks.len(), 1);
    Ok(())
}

#[tokio::test]
async fn topic_lifecycle_replicates_to_a_returning_device_and_purges_deleted_files() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let other = server.client(&dir.path().join("second.sqlite"))?;
    let topic = create(&client)?;
    let task = add(&client, topic, "Escalation report")?;
    client.rename_topic(topic, "Delivery".into())?;
    client.sync_once().await?;
    other.sync_once().await?;
    let engine = &server.app.engine;
    engine.chat(topic, "Record the incident").await?;
    let thread = engine.topic(topic)?.threads[0].id;
    client.sync_once().await?;
    client.archive_thread(topic, thread)?;
    client.delete_task(topic, task)?;
    client.archive_topic(topic)?;
    client.sync_once().await?;
    other.sync_once().await?;
    assert!(other.topics()?.is_empty());
    assert_eq!(other.archived_topics()?[0].topic.name, "Delivery");
    assert!(engine.search("Delivery")?.is_empty());
    assert!(engine.needs_you()?.is_empty());
    assert!(
        other.archived_topics()?[0]
            .tasks
            .iter()
            .all(|t| t.id != task)
    );
    assert!(
        other.archived_topics()?[0]
            .archived_threads
            .contains(&thread)
    );
    other.unarchive_topic(topic)?;
    other.sync_once().await?;
    assert_eq!(engine.search("Delivery")?.len(), 1);
    engine
        .write_file(topic, "release".into(), b"v1".into(), Uuid::new_v4(), None)
        .await?;
    other.delete_file(topic, "release".into())?;
    other.sync_once().await?;
    assert!(engine.blobs().get(topic, "release", None)?.is_none());
    assert_eq!(
        engine
            .blobs()
            .get(topic, "release", Some(1))?
            .unwrap()
            .bytes,
        b"v1"
    );
    other.delete_topic(topic)?;
    other.sync_once().await?;
    assert!(other.topic(topic)?.is_none());
    assert!(!engine.blobs().history(topic, "release")?.is_empty());
    client.sync_once().await?;
    assert!(client.topic(topic)?.is_none() && other.topic(topic)?.is_none());
    assert!(engine.topic(topic).is_err());
    assert!(engine.blobs().history(topic, "release")?.is_empty());
    Ok(())
}

#[tokio::test]
async fn offline_create_without_sort_survives_restart_and_syncs_dependent_edits() -> Result<()> {
    let (dir, server, client) = setup().await?;
    server.app.offline.store(true, SeqCst);
    let topic = TopicId(Uuid::new_v4());
    client.issue(
        topic,
        Command::CreateTopicWithoutSort {
            name: "No sort".into(),
            mission: "Track work".into(),
        },
    )?;
    add(&client, topic, "Offline task")?;
    drop(client);
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    assert!(client.topic(topic)?.is_some());
    server.app.offline.store(false, SeqCst);
    client.sync_once().await?;
    assert_eq!(server.app.engine.topic(topic)?.tasks.len(), 1);
    Ok(())
}

#[tokio::test]
async fn unsupported_without_sort_does_not_block_other_topics() -> Result<()> {
    let (_dir, server, client) = setup().await?;
    server.app.without_sort_supported.store(false, SeqCst);
    let held = TopicId(Uuid::new_v4());
    client.issue(
        held,
        Command::CreateTopicWithoutSort {
            name: "Held".into(),
            mission: "".into(),
        },
    )?;
    add(&client, held, "Held task")?;
    let other = create(&client)?;
    client.sync_once().await?;
    assert!(server.app.engine.topic(held).is_err());
    assert!(server.app.engine.topic(other).is_ok());
    server.app.without_sort_supported.store(true, SeqCst);
    client.sync_once().await?;
    assert_eq!(server.app.engine.topic(held)?.tasks.len(), 1);
    Ok(())
}

#[test]
fn old_health_response_does_not_advertise_without_sort() -> Result<()> {
    let health: meep_wire::ServerHealth = serde_json::from_value(serde_json::json!({
        "owner_id": Uuid::nil(), "implicit_owner": false, "version": "old",
        "cursor": 0, "posthog": false
    }))?;
    assert!(!health.create_topic_without_sort);
    Ok(())
}

#[tokio::test]
async fn passive_context_waits_for_server_support_without_blocking_other_topics() -> Result<()> {
    let (dir, server, client) = setup().await?;
    let topic = create(&client)?;
    client.sync_once().await?;
    server.app.context_sources_supported.store(false, SeqCst);
    let source = meep_topic::Watch {
        id: Uuid::new_v4().into(),
        connection: "posthog".into(),
        kind: "flag".into(),
        key: "flag-a".into(),
        label: "Flag A".into(),
    };
    client.issue(
        topic,
        Command::AddContextSource {
            source: source.clone(),
        },
    )?;
    add(&client, topic, "After source")?;
    let other = create(&client)?;
    drop(client);
    let client = server.client(&dir.path().join("replica.sqlite"))?;
    assert_eq!(
        client.topic(topic)?.unwrap().topic.context_sources,
        vec![source.clone()]
    );
    client.sync_once().await?;
    assert!(
        server
            .app
            .engine
            .topic(topic)?
            .topic
            .context_sources
            .is_empty()
    );
    assert!(server.app.engine.topic(topic)?.tasks.is_empty());
    assert!(server.app.engine.topic(other).is_ok());
    server.app.context_sources_supported.store(true, SeqCst);
    client.sync_once().await?;
    assert_eq!(
        server.app.engine.topic(topic)?.topic.context_sources,
        vec![source]
    );
    assert_eq!(server.app.engine.topic(topic)?.tasks.len(), 1);
    Ok(())
}
