use super::*;
use crate::{Engine, ManualClock, MemoryStore, NoAgent, SqliteStore, Store};
use chrono::DateTime;
use meep_policy::Limits;
use meep_topic::{Matcher, RuleEffect, ThreadState, Watch};
use std::{sync::Arc, thread, time::Duration};
use tiny_http::{Response, Server};
use uuid::Uuid;

fn server() -> (Arc<ModelSorter>, Server) {
    let server = Server::http("127.0.0.1:0").expect("bind loopback");
    let gateway = Gateway::new(
        meep_ai::Config {
            base_url: format!("http://{}", server.server_addr()),
            ..Default::default()
        },
        Arc::new("pha_test".to_owned()),
    )
    .expect("gateway");
    (
        Arc::new(ModelSorter::new(Arc::new(gateway), 0.8).expect("threshold")),
        server,
    )
}
async fn engine(store: Arc<dyn Store>, sorter: Arc<ModelSorter>) -> Result<Engine> {
    Ok(Engine::with_clock(
        store,
        Limits {
            max_hops: 2,
            max_runs_per_hour: 0,
        },
        Arc::new(NoAgent),
        sorter,
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?)
}
async fn topic(e: &Engine) -> Result<TopicId> {
    let (topic, _) = e
        .create_topic("Delivery", "Track the port's deliveries")
        .await?;
    e.set_watch(
        topic,
        vec![Watch {
            id: Uuid::new_v4().into(),
            connection: "mail".into(),
            kind: "inbox".into(),
            key: "depot".into(),
            label: "Depot notices".into(),
        }],
    )
    .await?;
    Ok(topic)
}
fn incoming(key: &str, text: &str) -> Event {
    Event {
        connection: "mail".into(),
        kind: "inbox".into(),
        channel: "depot".into(),
        external_id: key.into(),
        thread_hint: None,
        author: "Dispatcher".into(),
        at: DateTime::UNIX_EPOCH,
        text: text.into(),
        attributes: Value::Null,
    }
}
fn respond(s: &Server, path: &str, f: impl FnOnce(Value) -> Value) {
    let mut r = s
        .recv_timeout(Duration::from_secs(5))
        .expect("loopback")
        .expect("request received");
    assert_eq!(r.url(), path);
    assert!(
        r.headers()
            .iter()
            .any(|h| h.field.equiv("Authorization") && h.value.as_str() == "Bearer pha_test")
    );
    let body = serde_json::from_reader(r.as_reader()).expect("JSON");
    r.respond(Response::from_string(f(body).to_string()))
        .expect("reply");
}
fn decision(body: &Value, answers: Value) -> Value {
    assert_eq!(body["model"], "posthog/hogference/jevk5-fp8-0.2");
    json!({"model":"jev","usage":{"input_tokens":21},"answers":answers})
}
fn disposition(s: &Server, p: f64, acts: f64) {
    respond(s, "/v1/systemone", |b| {
        assert_eq!(b["state"]["mission"], "Track the port's deliveries");
        assert_eq!(b["state"]["watches"][0]["key"], "depot");
        assert_eq!(b["questions"]["disposition"]["type"], "choice");
        assert_eq!(b["questions"]["speaks_for_person"]["type"], "noul");
        decision(
            &b,
            json!({"disposition":{"type":"choice","choice":"handle","confidence":p,"probabilities":{"handle":p,"ask":1.-p,"skip":0.0}},"speaks_for_person":{"type":"noul","noul":acts}}),
        )
    });
}
#[tokio::test]
async fn durable_intake_is_visible_before_io_and_resumes_once_with_attributed_fact() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let (sorter, s) = server();
    let (id, revision) = {
        let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter.clone()).await?;
        let id = topic(&e).await?;
        let mut event = incoming("order-1", "The delivery moved to Monday.");
        event.attributes = json!({"fact":"Cargo arrives Monday."});
        e.ingest(event.clone()).await?;
        assert!(e.ingest(event).await?.is_empty());
        let snapshot = e.snapshot(id)?;
        assert_eq!(snapshot.state.threads[0].state, ThreadState::Sorting);
        (id, snapshot.revision)
    };
    let h = thread::spawn(move || {
        disposition(&s, 0.98, 0.02);
    });
    let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter).await?;
    e.sort_pending(id).await?;
    let snapshot = e.snapshot(id)?;
    assert_eq!(snapshot.revision, revision + 1);
    let thread = &snapshot.state.threads[0];
    assert_eq!(thread.summary, "The delivery moved to Monday.");
    assert_eq!(thread.state, ThreadState::Handled);
    let fact = &snapshot.state.topic.facts[0];
    assert_eq!(fact.text, "Cargo arrives Monday.");
    assert_eq!(fact.provenance.thread, Some(thread.id));
    assert_eq!(fact.provenance.author, "Dispatcher");
    e.sort_pending(id).await?;
    assert_eq!(e.snapshot(id)?.revision, snapshot.revision);
    h.join().expect("gateway");
    Ok(())
}
#[tokio::test]
async fn uncertain_disposition_asks_with_ranked_probabilities_and_followups_use_thread_ids()
-> Result<()> {
    let (sorter, s) = server();
    let e = engine(Arc::new(MemoryStore::default()), sorter).await?;
    let id = topic(&e).await?;
    e.ingest(incoming("1", "Dock 17")).await?;
    let existing = e.topic(id)?.threads[0].id;
    let h = thread::spawn(move || {
        disposition(&s, 0.52, 0.03);
        respond(&s, "/v1/systemone", |b| {
            assert_eq!(b["state"]["open_threads"][0]["id"], existing.to_string());
            let criteria = b["questions"]["thread"]["criteria"]
                .as_object()
                .expect("choices");
            assert!(criteria.contains_key("new") && criteria.contains_key(&existing.to_string()));
            decision(
                &b,
                json!({"thread":{"type":"choice","choice":existing,"probabilities":{existing.to_string():0.96,"new":0.04}}}),
            )
        });
        disposition(&s, 0.99, 0.01);
    });
    e.sort_pending(id).await?;
    assert!(
        matches!(&e.topic(id)?.threads[0].state,ThreadState::NeedsYou{reason,suggestions} if reason=="Not sure whether to keep it in the inbox, ask you about it, or skip it." && suggestions.contains(&Suggestion::Investigate))
    );
    e.ingest(incoming("2", "Monday's delay")).await?;
    assert_eq!(e.topic(id)?.threads.len(), 2);
    e.sort_pending(id).await?;
    let state = e.topic(id)?;
    assert_eq!(state.threads.len(), 1);
    assert_eq!(state.threads[0].messages.len(), 2);
    assert_eq!(state.threads[0].messages[1].text, "Monday's delay");
    e.answer(id, existing, Suggestion::Investigate).await?;
    let state = e.topic(id)?;
    assert_eq!(state.tasks[0].title, "Investigate: Dock 17");
    assert_eq!(
        state.tasks[0].assignment,
        Some(InboxAssignment::Investigate)
    );
    assert_eq!(state.tasks[0].column, Column::Todo);
    assert_eq!(state.tasks[0].from_thread, Some(existing));
    h.join().expect("gateway");
    Ok(())
}
#[tokio::test]
async fn a_natural_language_skip_requires_strictly_more_than_the_threshold() -> Result<()> {
    for (p, skipped) in [(0.8, false), (0.81, true)] {
        let (sorter, s) = server();
        let e = engine(Arc::new(MemoryStore::default()), sorter).await?;
        let id = topic(&e).await?;
        e.add_rule(
            id,
            "Ignore already settled invoices",
            RuleEffect::Skip(Matcher::default()),
        )
        .await?;
        let rule = e.topic(id)?.topic.rules[0].id;
        let h = thread::spawn(move || {
            disposition(&s, 0.99, 0.02);
            respond(&s, "/v1/systemone", |b| {
                assert_eq!(
                    b["state"]["rules"][0]["text"],
                    "Ignore already settled invoices"
                );
                assert_eq!(b["questions"][rule.to_string()]["type"], "noul");
                decision(&b, json!({rule.to_string():{"type":"noul","noul":p}}))
            });
        });
        e.ingest(incoming("invoice", "Paid in full")).await?;
        e.sort_pending(id).await?;
        assert_eq!(
            matches!(e.topic(id)?.threads[0].state,ThreadState::Skipped{rule:Some(r),..} if r==rule),
            skipped
        );
        h.join().expect("gateway");
    }
    Ok(())
}
#[tokio::test]
async fn speaking_for_the_person_follows_model_answers_independently_of_punctuation() -> Result<()>
{
    let (sorter, s) = server();
    let e = engine(Arc::new(MemoryStore::default()), sorter).await?;
    let id = topic(&e).await?;
    let h = thread::spawn(move || {
        disposition(&s, 0.97, 0.96);
    });
    e.ingest(incoming("3", "Delivery today")).await?;
    e.sort_pending(id).await?;
    assert!(
        matches!(&e.topic(id)?.threads[0].state,ThreadState::NeedsYou{reason,..} if reason=="Delivery today")
    );
    h.join().expect("gateway");
    Ok(())
}

fn routed(body: &Value, route: &str, review: bool) -> Value {
    assert!(
        body["questions"]["disposition"]["criteria"]
            .get(route)
            .is_some(),
        "route {route} must be offered"
    );
    decision(
        body,
        json!({
            "disposition":{"type":"choice","choice":route,"confidence":1.0},
            "speaks_for_person":{"type":"noul","noul":if review {1.0} else {0.0}}
        }),
    )
}

#[tokio::test]
async fn a_reply_can_start_an_investigation_after_review_and_attach_evidence_once() -> Result<()> {
    use crate::{FixtureAgent, RunState, Script};
    let (sorter, server) = server();
    let mut agent = FixtureAgent::default();
    agent.script(
        "Investigate: Crane stopped",
        Script {
            delay: chrono::TimeDelta::zero(),
            progress: "Inspecting logs".into(),
            outcome: RunState::Findings {
                result: "Damaged cable".into(),
                follow_ups: vec![
                    "Decide when to replace the cable".into(),
                    " Decide when to replace the cable ".into(),
                    "Check the replacement inventory".into(),
                    " ".into(),
                ],
            },
        },
    );
    let e = Engine::with_clock(
        Arc::new(MemoryStore::default()),
        Limits {
            max_hops: 2,
            max_runs_per_hour: 10,
        },
        Arc::new(agent),
        sorter,
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let topic = topic(&e).await?;
    let gateway = thread::spawn(move || {
        for (message, route, review) in [
            ("Cargo unloaded", "handle", false),
            ("Crane stopped", "investigate", true),
            ("Pier 3 affected", "update", false),
        ] {
            respond(&server, "/v1/systemone", |body| {
                assert_eq!(body["state"]["message"]["text"], message);
                assert_eq!(
                    body["state"]["thread"]["messages"]
                        .as_array()
                        .unwrap()
                        .last()
                        .unwrap()["text"],
                    message
                );
                let key = if route == "update" {
                    body["questions"]["disposition"]["criteria"]
                        .as_object()
                        .unwrap()
                        .keys()
                        .find(|s| s.starts_with("update:"))
                        .unwrap()
                        .clone()
                } else {
                    route.to_owned()
                };
                routed(&body, &key, review)
            });
        }
    });
    for text in ["Cargo unloaded", "Crane stopped", "Pier 3 affected"] {
        let event = Event {
            thread_hint: Some("dock".into()),
            ..incoming(text, text)
        };
        e.ingest(event.clone()).await?;
        assert!(e.ingest(event).await?.is_empty());
    }
    e.tick_topic(topic).await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks.len(), 1);
    let task = &state.tasks[0];
    assert_eq!(
        state.threads[0].outcomes,
        [meep_topic::Outcome::Task(task.id)]
    );
    assert_eq!(task.column, Column::NeedsYou);
    assert!(task.review_before_start);
    assert!(task.log.last().unwrap().text.contains("Pier 3 affected"));
    e.approve(topic, task.id, None, false).await?;
    e.tick_topic(topic).await?;
    assert_eq!(e.topic(topic)?.tasks[0].column, Column::InProgress);
    e.tick_topic(topic).await?;
    e.tick_topic(topic).await?;
    let state = e.topic(topic)?;
    assert_eq!(state.tasks.len(), 1);
    assert_eq!(state.tasks[0].column, Column::Done);
    assert_eq!(state.tasks[0].result.as_deref(), Some("Damaged cable"));
    assert_eq!(
        state.tasks[0].suggestions,
        [
            "Decide when to replace the cable",
            "Check the replacement inventory"
        ]
    );
    let accept = meep_topic::Command::AcceptTaskSuggestion {
        parent: task.id,
        id: crate::id(),
        title: state.tasks[0].suggestions[0].clone(),
    };
    e.command(topic, accept.clone()).await?;
    assert!(e.command(topic, accept).await.is_err());
    let accepted = e.topic(topic)?;
    assert_eq!(accepted.tasks.len(), 2);
    assert_eq!(accepted.tasks[1].parent, Some(task.id));
    assert!(accepted.tasks[1].queued);
    assert_eq!(state.threads.len(), 1);
    assert_eq!(state.threads[0].messages.len(), 3);
    assert_eq!(task.source_message, Some(state.threads[0].messages[1].id));
    gateway.join().unwrap();
    Ok(())
}

#[cfg(feature = "posthog")]
#[tokio::test]
async fn assigned_posthog_workflow_retries_a_lost_start_with_the_same_key_after_restart()
-> Result<()> {
    use crate::{MemoryBlobs, PostHogRoutines};
    let dir = tempfile::tempdir()?;
    let (sorter, gateway) = server();
    let flows = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
    let origin = format!("http://{}", flows.server_addr());
    let flow = Uuid::new_v4();
    let run = Uuid::new_v4();
    let upstream = thread::spawn(move || -> Result<()> {
        respond(&gateway, "/v1/systemone", |b| {
            routed(&b, "routine:audit", false)
        });
        let mut previous = None;
        for status in [503, 200] {
            let mut req = flows
                .recv_timeout(Duration::from_secs(5))?
                .context("missing start")?;
            assert_eq!(req.url(), format!("/api/projects/7/hog_flows/{flow}/run/"));
            let key = req
                .headers()
                .iter()
                .find(|h| h.field.equiv("idempotency-key"))
                .unwrap()
                .value
                .to_string();
            let body: Value = serde_json::from_reader(req.as_reader())?;
            assert_eq!(body["variables"]["title"], "Check manifest");
            if let Some((first_key, first_body)) = previous.take() {
                assert_eq!(first_key, key);
                assert_eq!(first_body, body);
            }
            previous = Some((key, body));
            req.respond(
                Response::from_string(json!({"invocation_id":run,"status":"queued"}).to_string())
                    .with_status_code(status),
            )?;
        }
        let req = flows
            .recv_timeout(Duration::from_secs(5))?
            .context("missing poll")?;
        assert_eq!(
            req.url(),
            format!("/api/projects/7/hog_flows/{flow}/invocation_results/{run}/")
        );
        req.respond(Response::from_string(
            json!({"invocation_id":run,"status":"completed"}).to_string(),
        ))?;
        Ok(())
    });
    let open = || async {
        Engine::with_backends(
            Arc::new(SqliteStore::open(dir.path())?),
            Arc::new(MemoryBlobs::default()),
            vec![Arc::new(PostHogRoutines::new(&origin, 7, "loopback-only")?)],
            Limits {
                max_hops: 2,
                max_runs_per_hour: 0,
            },
            Arc::new(NoAgent),
            sorter.clone(),
            Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
        )
        .await
    };
    let e = open().await?;
    let id = topic(&e).await?;
    e.bind_routine(
        id,
        meep_topic::RoutineBinding {
            watches: vec![],
            id: "audit".into(),
            name: "Manifest audit".into(),
            backend: "posthog".into(),
            external_id: flow.to_string(),
            trigger: "Check a manifest".into(),
        },
    )
    .await?;
    e.ingest(incoming("manifest", "Check manifest")).await?;
    assert!(e.tick_topic(id).await.is_err());
    assert_eq!(e.topic(id)?.tasks[0].column, Column::InProgress);
    drop(e);
    let e = open().await?;
    e.tick_topic(id).await?;
    e.tick_topic(id).await?;
    assert_eq!(e.topic(id)?.tasks[0].column, Column::Done);
    upstream.join().unwrap()?;
    Ok(())
}

fn memory_fact(text: &str) -> meep_topic::Fact {
    meep_topic::Fact {
        id: Uuid::new_v4().into(),
        text: text.into(),
        provenance: meep_topic::Provenance {
            origin: None,
            author: "Dispatcher".into(),
            via: "Manifest".into(),
            at: DateTime::UNIX_EPOCH,
            thread: None,
        },
        superseded_by: None,
        invalidated_by: None,
        withdrawn_at: None,
    }
}

fn memory_answer(
    s: &Server,
    change: &str,
    subject: &str,
    decide: impl Fn(&str) -> (&'static str, f64),
) {
    respond(s, "/v1/systemone", |body| {
        assert_eq!(body["state"]["fact_change"], change);
        assert_eq!(body["state"]["changed"]["fact"]["text"], subject);
        assert_eq!(
            body["state"]["changed"]["fact"]["provenance"]["via"],
            "Manifest"
        );
        let mut answers = serde_json::Map::new();
        for key in body["questions"].as_object().unwrap().keys() {
            let (answer, confidence) = if key == "memory:empty" {
                ("independent", 1.)
            } else {
                let id = key.strip_prefix("memory:").unwrap();
                let peer = body["state"]["candidates"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|p| p["fact"]["id"] == id)
                    .unwrap();
                decide(peer["fact"]["text"].as_str().unwrap())
            };
            answers.insert(
                key.clone(),
                json!({"type":"choice","choice":answer,"confidence":confidence}),
            );
        }
        decision(&body, Value::Object(answers))
    });
}

#[tokio::test]
async fn system_one_reconciles_committed_memory_after_restart_and_humans_resolve_uncertain_claims()
-> Result<()> {
    use meep_topic::{FactResolution, Ref};
    let dir = tempfile::tempdir()?;
    let (sorter, server) = server();
    let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter.clone()).await?;
    let id = topic(&e).await?;
    let old = memory_fact("Unloading is on Monday");
    let new = memory_fact("Correction: unloading is on Tuesday");
    e.add_fact(id, old.clone()).await?;
    e.add_fact(id, new.clone()).await?;
    drop(e);
    let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter).await?;
    let h = thread::spawn(move || {
        memory_answer(
            &server,
            "added",
            "Unloading is on Monday",
            |_| unreachable!(),
        );
        memory_answer(
            &server,
            "added",
            "Correction: unloading is on Tuesday",
            |_| ("changed_wins", 0.99),
        );
        memory_answer(
            &server,
            "withdrawn",
            "Unloading is on Monday",
            |_| unreachable!(),
        );
        memory_answer(&server, "added", "The registry says Friday", |_| {
            ("existing_wins", 0.55)
        });
        memory_answer(&server, "added", "Another source says Saturday", |peer| {
            if peer.contains("Tuesday") {
                ("review", 0.99)
            } else {
                ("independent", 0.99)
            }
        });
        memory_answer(
            &server,
            "withdrawn",
            "Correction: unloading is on Tuesday",
            |_| ("independent", 1.),
        );
        memory_answer(&server, "withdrawn", "The registry says Friday", |peer| {
            assert_eq!(peer, "Another source says Saturday");
            ("unsupported", 0.99)
        });
    });
    e.tick_topic(id).await?;
    assert_eq!(e.topic(id)?.topic.facts[0].superseded_by, Some(new.id));
    assert_eq!(e.topic(id)?.topic.facts[0].provenance, old.provenance);
    e.tick_topic(id).await?;
    let friday = memory_fact("The registry says Friday");
    e.add_fact(id, friday.clone()).await?;
    e.add_fact(id, memory_fact("Another source says Saturday"))
        .await?;
    e.tick_topic(id).await?;
    let pending = e.topic(id)?.needs_you().threads;
    assert_eq!(pending.len(), 2);
    let choice = Suggestion::ResolveFacts {
        changed: friday.id,
        other: new.id,
        resolution: FactResolution::KeepChanged,
    };
    let mut replica = e.topic(id)?;
    replica.apply(&meep_topic::Envelope {
        id: Uuid::new_v4().into(),
        topic: id,
        issued_at: DateTime::UNIX_EPOCH,
        command: meep_topic::Command::Answer {
            thread: pending[0],
            expected_review: None,
            suggestion: choice.clone(),
            task_id: Uuid::new_v4().into(),
        },
    })?;
    assert!(replica.needs_you().threads.is_empty());
    e.answer(id, pending[0], choice.clone()).await?;
    let state = e.topic(id)?;
    assert!(state.needs_you().threads.is_empty());
    assert!(state.tasks.is_empty() && state.threads[0].outcomes.is_empty());
    assert_eq!(state.topic.facts[1].superseded_by, Some(friday.id));
    assert!(
        state
            .activity
            .iter()
            .any(|a| a.subject == Ref::Fact(new.id) && a.actor == meep_topic::Actor::User)
    );
    assert!(e.answer(id, pending[0], choice).await.is_err());
    e.remove_fact(id, friday.id).await?;
    e.tick_topic(id).await?;
    let state = e.topic(id)?;
    assert!(state.topic.facts.iter().all(|fact| !fact.is_current()));
    assert!(
        state
            .topic
            .facts
            .iter()
            .any(|f| f.id == friday.id && f.withdrawn_at.is_some())
    );
    assert!(
        state
            .topic
            .facts
            .iter()
            .any(|f| f.invalidated_by == Some(friday.id))
    );
    e.command(
        id,
        meep_topic::Command::SetTopicSetting {
            key: meep_topic::CHECK_FACTS.into(),
            enabled: false,
        },
    )
    .await?;
    e.add_fact(id, memory_fact("Unloading is on Sunday"))
        .await?;
    assert!(e.slot(id)?.saved.read().fact_checks.is_empty());
    h.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn removed_evidence_retires_only_unsupported_facts_and_checks_their_dependents() -> Result<()>
{
    use meep_topic::FactResolution;
    let dir = tempfile::tempdir()?;
    let (sorter, server) = server();
    let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter.clone()).await?;
    let id = topic(&e).await?;
    let permit = memory_fact("The permit is active");
    let dock = memory_fact("Dock three can open");
    let team = memory_fact("Team three is ready");
    let h = thread::spawn(move || {
        memory_answer(&server, "added", "The permit is active", |_| unreachable!());
        memory_answer(&server, "added", "Dock three can open", |_| {
            ("independent", 1.)
        });
        memory_answer(&server, "added", "Team three is ready", |_| {
            ("independent", 1.)
        });
        memory_answer(&server, "withdrawn", "The permit is active", |peer| {
            if peer.starts_with("Dock") {
                ("unsupported", 0.99)
            } else {
                ("review", 1.)
            }
        });
        memory_answer(&server, "withdrawn", "Dock three can open", |_| {
            ("independent", 1.)
        });
    });
    for f in [&permit, &dock, &team] {
        e.add_fact(id, f.clone()).await?;
    }
    e.tick_topic(id).await?;
    e.remove_fact(id, permit.id).await?;
    drop(e);
    let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter).await?;
    e.tick_topic(id).await?;
    let state = e.topic(id)?;
    assert_eq!(state.topic.facts[0].invalidated_by, Some(permit.id));
    assert!(!state.topic.facts[0].is_current());
    assert_eq!(state.topic.facts[0].provenance, dock.provenance);
    let review = state.needs_you().threads[0];
    assert!(
        state
            .threads
            .iter()
            .find(|t| t.id == review)
            .unwrap()
            .messages[0]
            .text
            .contains("A (withdrawn) · The permit is active")
    );
    e.answer(
        id,
        review,
        Suggestion::ResolveFacts {
            changed: permit.id,
            other: team.id,
            resolution: FactResolution::KeepDependent,
        },
    )
    .await?;
    e.tick_topic(id).await?;
    assert!(
        e.topic(id)?
            .topic
            .facts
            .iter()
            .any(|f| f.id == team.id && f.is_current())
    );
    assert!(e.topic(id)?.needs_you().threads.is_empty());
    h.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn a_reviewed_inbox_update_changes_the_task_and_memory_only_after_confirmation() -> Result<()>
{
    let (sorter, gateway) = server();
    let e = engine(Arc::new(MemoryStore::default()), sorter).await?;
    let id = topic(&e).await?;
    e.add_task(id, "Check berth").await?;
    let task = e.topic(id)?.tasks[0].id;
    let upstream = thread::spawn(move || {
        respond(&gateway, "/v1/systemone", |b| {
            routed(&b, &format!("update:{task}"), true)
        });
    });
    let mut arrival = incoming("berth", "Dispatch says berth four is clear");
    arrival.attributes["fact"] = json!("Berth four is clear");
    e.ingest(arrival).await?;
    e.sort_pending(id).await?;
    let state = e.topic(id)?;
    assert!(
        state.topic.facts.is_empty()
            && state.tasks[0].log.is_empty()
            && state.threads[0].outcomes.is_empty()
    );
    let thread = &state.threads[0];
    let ThreadState::NeedsYou { suggestions, .. } = &thread.state else {
        panic!("expected evidence review")
    };
    let suggestion = suggestions
        .iter()
        .find(|v| matches!(v, Suggestion::AcceptEvidence { .. }))
        .unwrap()
        .clone();
    e.answer(id, thread.id, suggestion).await?;
    let confirmed = e.topic(id)?;
    assert_eq!(confirmed.topic.facts[0].text, "Berth four is clear");
    assert_eq!(confirmed.topic.facts[0].provenance.thread, Some(thread.id));
    assert_eq!(confirmed.tasks[0].log.len(), 1);
    assert_eq!(confirmed.threads[0].outcomes.len(), 2);
    upstream.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn a_replacement_sources_new_evidence_invalidates_an_in_flight_fact_verdict() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let (sorter, gateway) = server();
    let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter.clone()).await?;
    let id = topic(&e).await?;
    let mut notice = incoming("source-1", "Temporary permit");
    notice.thread_hint = Some("permit".into());
    e.ingest(notice.clone()).await?;
    let old = memory_fact("Original permit");
    let dependent = memory_fact("The dock is open");
    let mut new = memory_fact("Replacement permit");
    let thread = e.topic(id)?.threads[0].id;
    new.provenance.thread = Some(thread);
    e.add_fact(id, old.clone()).await?;
    e.add_fact(id, dependent.clone()).await?;
    let (entered, waiting) = tokio::sync::oneshot::channel();
    let (release, resume) = std::sync::mpsc::channel();
    let upstream = thread::spawn(move || {
        memory_answer(&gateway, "added", "Original permit", |_| unreachable!());
        memory_answer(&gateway, "added", "The dock is open", |_| {
            ("independent", 1.)
        });
        memory_answer(&gateway, "added", "Replacement permit", |_| {
            ("independent", 1.)
        });
        respond(&gateway, "/v1/systemone", |b| {
            assert_eq!(
                b["state"]["replacement"]["source_messages"]
                    .as_array()
                    .unwrap()
                    .len(),
                1
            );
            entered.send(()).unwrap();
            resume.recv_timeout(Duration::from_secs(5)).unwrap();
            let key = b["questions"].as_object().unwrap().keys().next().unwrap();
            decision(
                &b,
                json!({key:{"type":"choice","choice":"unsupported","confidence":1.}}),
            )
        });
        respond(&gateway, "/v1/systemone", |b| {
            assert_eq!(
                b["state"]["replacement"]["source_messages"][1]["text"],
                "The permit covers the dock"
            );
            let key = b["questions"].as_object().unwrap().keys().next().unwrap();
            decision(
                &b,
                json!({key:{"type":"choice","choice":"independent","confidence":1.}}),
            )
        });
    });
    e.reconcile_facts(id).await?;
    e.apply(meep_topic::Envelope {
        id: Uuid::new_v4().into(),
        topic: id,
        issued_at: DateTime::UNIX_EPOCH,
        command: meep_topic::Command::SupersedeFact { old: old.id, new },
    })
    .await?;
    let work = e.clone();
    let job = tokio::spawn(async move { work.reconcile_facts(id).await });
    tokio::time::timeout(Duration::from_secs(5), waiting).await??;
    notice.external_id = "source-2".into();
    notice.text = "The permit covers the dock".into();
    e.ingest(notice).await?;
    release.send(())?;
    job.await??;
    assert!(
        e.topic(id)?
            .topic
            .facts
            .iter()
            .find(|f| f.id == dependent.id)
            .unwrap()
            .is_current()
    );
    e.shutdown().await;
    drop(e);
    let e = engine(Arc::new(SqliteStore::open(dir.path())?), sorter).await?;
    e.reconcile_facts(id).await?;
    assert!(
        e.topic(id)?
            .topic
            .facts
            .iter()
            .find(|f| f.id == dependent.id)
            .unwrap()
            .is_current()
    );
    upstream.join().unwrap();
    Ok(())
}
